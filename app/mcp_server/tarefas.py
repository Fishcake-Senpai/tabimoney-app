"""Operações longas do servidor MCP (atualizar dados, baixar balanços da CVM), rodando numa thread.

Alguns clientes cortam uma chamada de ferramenta depois de ~60 s, e `atualizar` pode levar minutos. A ferramenta
inicia a tarefa, espera um pouco e, se ainda não terminou, devolve o `tarefa_id` para o agente acompanhar com
`tarefa_status`. A tarefa vive no processo do servidor: se o cliente fechar, ela para junto.
"""
from __future__ import annotations

import contextvars
import threading
import uuid
from datetime import datetime
from typing import Any, Callable

_LOCK = threading.Lock()
_TAREFAS: dict[str, dict[str, Any]] = {}


def _agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def iniciar(tipo: str, trabalho: Callable[[Callable[[str], None]], dict[str, Any]]) -> dict[str, Any]:
    """Roda `trabalho(progresso)` numa thread, no contexto atual (a base da demo, se for o caso).
    Se já houver uma tarefa do mesmo tipo rodando, devolve essa em vez de começar outra."""
    with _LOCK:
        for t in _TAREFAS.values():
            if t["tipo"] == tipo and t["situacao"] == "rodando":
                return dict(t)
        tarefa = {"tarefa_id": uuid.uuid4().hex[:12], "tipo": tipo, "situacao": "rodando", "etapa": None,
                  "inicio": _agora(), "fim": None, "resultado": None, "erro": None}
        _TAREFAS[tarefa["tarefa_id"]] = tarefa
    contexto = contextvars.copy_context()

    def progresso(etapa: str) -> None:
        tarefa["etapa"] = etapa

    def rodar() -> None:
        try:
            tarefa["resultado"] = contexto.run(trabalho, progresso)
            tarefa["situacao"] = "concluida"
        except Exception as exc:  # noqa: BLE001 - o agente recebe a mensagem em tarefa_status
            tarefa["erro"] = str(exc) or exc.__class__.__name__
            tarefa["situacao"] = "falhou"
        finally:
            tarefa["fim"] = _agora()

    threading.Thread(target=rodar, name=f"tabimoney-{tipo}", daemon=True).start()
    return dict(tarefa)


def obter(tarefa_id: str) -> dict[str, Any]:
    with _LOCK:
        tarefa = _TAREFAS.get(tarefa_id.strip())
    if not tarefa:
        raise ValueError(f"Tarefa não encontrada: {tarefa_id}. As tarefas só existem enquanto o servidor está aberto.")
    return dict(tarefa)


def limpar() -> None:
    """Para os testes."""
    with _LOCK:
        _TAREFAS.clear()
