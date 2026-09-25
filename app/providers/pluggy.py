from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from uuid import UUID


API_BASE = "https://api.pluggy.ai"


class PluggyError(RuntimeError):
    """Falha externa sem expor payloads nem credenciais da API."""


@dataclass
class PluggyData:
    item: dict[str, Any]
    accounts: list[dict[str, Any]] = field(default_factory=list)
    transactions_by_account: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    investments: list[dict[str, Any]] = field(default_factory=list)
    investment_transactions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    positions_complete: bool = True


class PluggyClient:
    def __init__(self, client_id: str, client_secret: str) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise PluggyError("Preencha Client ID e Client Secret do Meu Pluggy.")
        self._http = httpx.Client(base_url=API_BASE, timeout=httpx.Timeout(30.0, connect=10.0))
        try:
            response = self._http.post(
                "/auth",
                json={"clientId": client_id.strip(), "clientSecret": client_secret},
            )
        except httpx.HTTPError as exc:
            self._http.close()
            raise PluggyError("Não foi possível conectar à API do Meu Pluggy.") from exc
        if response.status_code != 200:
            self._http.close()
            if response.status_code in (401, 403):
                raise PluggyError("Credenciais Pluggy inválidas ou sem permissão para essa conexão.")
            raise PluggyError(f"A autenticação Pluggy respondeu com HTTP {response.status_code}.")
        try:
            self._api_key = response.json()["apiKey"]
        except (ValueError, KeyError, TypeError) as exc:
            self._http.close()
            raise PluggyError("A API Pluggy não retornou uma chave de sessão válida.") from exc
        self._http.headers.update({"X-API-KEY": self._api_key})

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PluggyClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, object] | None = None) -> dict[str, Any]:
        try:
            response = self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            raise PluggyError("Falha de rede ao consultar dados Pluggy.") from exc
        if response.status_code != 200:
            if response.status_code in (401, 403):
                raise PluggyError("A Pluggy recusou o acesso. Confira o Item ID e as permissões da aplicação.")
            if response.status_code == 429:
                raise PluggyError("A Pluggy limitou as consultas. Tente novamente mais tarde.")
            raise PluggyError(f"A Pluggy respondeu com HTTP {response.status_code}.")
        try:
            result = response.json()
        except ValueError as exc:
            raise PluggyError("A Pluggy retornou uma resposta fora do formato esperado.") from exc
        if not isinstance(result, dict):
            raise PluggyError("A Pluggy retornou uma resposta fora do formato esperado.")
        return result

    def _page_list(self, path: str, params: dict[str, object]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        page: int | None = None
        page_offset: int | None = None
        while True:
            page_params = dict(params)
            page_params["pageSize"] = 500
            if page is not None:
                page_params["page"] = page
            payload = self._get(path, page_params)
            results = payload.get("results", [])
            if not isinstance(results, list):
                raise PluggyError("A Pluggy retornou uma lista de dados inválida.")
            output.extend(row for row in results if isinstance(row, dict))
            response_page = int(payload.get("page") or 0) if page is None else page
            if page_offset is None:
                page_offset = 1 if response_page == 0 else 0
            total_pages = int(payload.get("totalPages") or 1)
            if response_page + page_offset >= total_pages:
                break
            page = response_page + 1
        return output

    def _transaction_pages(self, account_id: str) -> list[dict[str, Any]]:
        path = "/v2/transactions"
        params: dict[str, object] | None = {"accountId": account_id}
        output: list[dict[str, Any]] = []
        while True:
            payload = self._get(path, params)
            results = payload.get("results", [])
            if not isinstance(results, list):
                raise PluggyError("A Pluggy retornou uma lista de transações inválida.")
            output.extend(row for row in results if isinstance(row, dict))
            next_query = payload.get("next")
            if not next_query:
                break
            if not isinstance(next_query, str) or "://" in next_query:
                raise PluggyError("A Pluggy retornou um cursor de transações inválido.")
            suffix = next_query if next_query.startswith(("?", "&")) else "?" + next_query
            path = "/v2/transactions" + suffix
            params = None
        return output

    def collect(self, item_id: str) -> PluggyData:
        """Lê um item; a mesma sessão serve para vários itens, e quem abriu o cliente o fecha."""
        normalized_item_id = item_id.strip()
        if not normalized_item_id:
            raise PluggyError("Informe o Item ID proxy do Meu Pluggy.")
        try:
            normalized_item_id = str(UUID(normalized_item_id))
        except ValueError as exc:
            raise PluggyError("O Item ID do Meu Pluggy precisa ser um UUID válido.") from exc
        item = self._get(f"/items/{normalized_item_id}")
        accounts = self._page_list("/accounts", {"itemId": normalized_item_id})

        result = PluggyData(item=item, accounts=accounts)
        for account in accounts:
            account_id = str(account.get("id") or "")
            if not account_id:
                result.errors.append("Uma conta retornou sem identificador.")
                continue
            try:
                result.transactions_by_account[account_id] = self._transaction_pages(account_id)
            except PluggyError as exc:
                result.errors.append(f"Movimentações de uma conta não foram carregadas: {exc}")

        try:
            investments = self._page_list("/investments", {"itemId": normalized_item_id})
            result.investments = investments
        except PluggyError as exc:
            result.positions_complete = False
            result.errors.append(f"Posições de investimento não foram carregadas: {exc}")
            return result

        for investment in investments:
            investment_id = str(investment.get("id") or "")
            if not investment_id:
                result.positions_complete = False
                result.errors.append("Um investimento retornou sem identificador.")
                continue
            try:
                result.investment_transactions[investment_id] = self._page_list(
                    f"/investments/{investment_id}/transactions", {}
                )
            except PluggyError as exc:
                result.positions_complete = False
                result.errors.append(f"Movimentações de um investimento não foram carregadas: {exc}")
        return result
