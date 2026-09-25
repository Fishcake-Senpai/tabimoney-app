"""Demonstrações financeiras oficiais das companhias abertas (CVM, dados abertos, sem chave).

- FCA (cadastro): liga o ticker (Codigo_Negociacao) ao CNPJ, e traz setor e código CVM.
- ITR (trimestral) e DFP (anual): DRE, balanço (BPA/BPP), fluxo de caixa (DFC) e composição do capital.

Os arquivos (~30 MB por ano) ficam em cache em %LOCALAPPDATA%/FinancasPessoais/cvm e só são baixados de
novo quando a CVM publica versão nova (a base é atualizada semanalmente). As contas são reconhecidas pela
descrição, não só pelo código: bancos, seguradoras e empresas sem controladas usam planos de contas diferentes.
"""
from __future__ import annotations

import csv
import io
import os
import re
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Iterator

import httpx

from app.db import data_dir

BASE_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC"
REFRESH_AFTER = timedelta(days=6)


class CvmError(RuntimeError):
    """Falha ao obter os dados abertos da CVM."""


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


def cache_dir() -> Path:
    folder = data_dir() / "cvm"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def fetch_zip(kind: str, year: int) -> Path | None:
    """Baixa (ou reaproveita do cache) o zip anual. Devolve None se a CVM ainda não publicou o ano."""
    name = f"{kind.lower()}_cia_aberta_{year}.zip"
    target = cache_dir() / name
    url = f"{BASE_URL}/{kind.upper()}/DADOS/{name}"
    headers = {}
    if target.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(target.stat().st_mtime, timezone.utc)
        # anos fechados há muito tempo quase não mudam; os recentes são conferidos toda semana
        if age < REFRESH_AFTER or (year < date.today().year - 2 and age < timedelta(days=60)):
            return target
        headers["If-Modified-Since"] = format_datetime(
            datetime.fromtimestamp(target.stat().st_mtime, timezone.utc), usegmt=True
        )
    try:
        with httpx.stream("GET", url, headers=headers, timeout=httpx.Timeout(120.0, connect=15.0),
                          follow_redirects=True) as response:
            if response.status_code == 304:
                target.touch()
                return target
            if response.status_code == 404:
                return target if target.exists() else None
            if response.status_code != 200:
                if target.exists():
                    return target
                raise CvmError(f"CVM respondeu HTTP {response.status_code} para {name}.")
            partial = target.with_suffix(".part")
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes(1 << 20):
                    handle.write(chunk)
            partial.replace(target)
            modified = response.headers.get("Last-Modified")
            if modified:
                try:
                    # a data do arquivo vira a da CVM, para o If-Modified-Since da próxima conferência
                    stamp = parsedate_to_datetime(modified).timestamp()
                    os.utime(target, (stamp, stamp))
                except (TypeError, ValueError, OverflowError):
                    pass
    except httpx.HTTPError as exc:
        if target.exists():
            return target
        raise CvmError(f"Falha de rede ao baixar {name} da CVM.") from exc
    return target


def _rows(archive: zipfile.ZipFile, member: str) -> Iterator[dict[str, str]]:
    if member not in archive.namelist():
        return
    with archive.open(member) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1", newline=""), delimiter=";")


# ---------------------------------------------------------------- cadastro

@dataclass
class Company:
    cnpj: str
    name: str
    cvm_code: str | None = None
    sector: str | None = None
    tickers: set[str] = field(default_factory=set)
    shares_per_unit: dict[str, int] = field(default_factory=dict)


UNIT_PART = re.compile(r"(\d+)\s*(?=on\b|pn\b|a[cç][aã]o|a[cç][oõ]es|[a-z]{4}\d)", re.IGNORECASE)


def shares_per_unit(composition: str) -> int | None:
    """'1 ON / 2 PN' → 3; '1 KLBN3 + 4 KLBN4' → 5."""
    parts = [int(n) for n in UNIT_PART.findall(composition or "")]
    return sum(parts) if parts and sum(parts) > 1 else None


def companies_by_ticker(tickers: set[str]) -> dict[str, Company]:
    """Ticker → companhia, pelo cadastro FCA mais recente que contenha o ticker."""
    wanted = {t.upper() for t in tickers}
    found: dict[str, Company] = {}
    this_year = date.today().year
    for year in (this_year, this_year - 1):
        path = fetch_zip("FCA", year)
        if path is None:
            continue
        with zipfile.ZipFile(path) as archive:
            for row in _rows(archive, f"fca_cia_aberta_valor_mobiliario_{year}.csv"):
                ticker = (row.get("Codigo_Negociacao") or "").strip().upper()
                if ticker in wanted and ticker not in found and not (row.get("Data_Fim_Negociacao") or "").strip():
                    found[ticker] = Company(cnpj=row["CNPJ_Companhia"], name=row["Nome_Empresarial"])
                    if (row.get("Valor_Mobiliario") or "").casefold() == "units":
                        size = shares_per_unit(row.get("Composicao_BDR_Unit") or "")
                        if size:
                            found[ticker].shares_per_unit[ticker] = size
            by_cnpj = {c.cnpj: c for c in found.values()}
            for row in _rows(archive, f"fca_cia_aberta_geral_{year}.csv"):
                company = by_cnpj.get(row.get("CNPJ_Companhia", ""))
                if company and not company.sector:
                    company.sector = (row.get("Setor_Atividade") or "").strip() or None
                    company.cvm_code = (row.get("Codigo_CVM") or "").strip() or None
        if wanted <= set(found):
            break
    for ticker, company in found.items():
        company.tickers.add(ticker)
    return found


# ---------------------------------------------------------------- demonstrações

@dataclass
class Filing:
    cnpj: str
    period_end: str
    doc_type: str
    version: int
    received_at: str | None
    link: str | None


@dataclass
class Quarter:
    """Valores em reais. Fluxos (receita, lucro, caixa) são do trimestre isolado; saldos são na data."""
    period_end: str
    values: dict[str, float] = field(default_factory=dict)
    is_financial: bool = False


FLOW_KEYS = ("revenue", "ebit", "net_income", "net_income_total", "da", "cfo", "capex", "dividends_paid")
STOCK_KEYS = ("total_assets", "equity", "equity_parent", "cash", "debt", "shares")


def _depth(code: str) -> int:
    return code.count(".")


def _quarter_start(period_end: str) -> str:
    end = date.fromisoformat(period_end)
    month = end.month - 2
    return date(end.year, month, 1).isoformat()


class _Statement:
    """Linhas de uma demonstração de uma empresa numa data (maior versão, ORDEM_EXERC = ÚLTIMO)."""

    def __init__(self) -> None:
        self.lines: list[tuple[str, str, str, str, float]] = []  # código, descrição normalizada, início, fim, valor

    def add(self, code: str, description: str, start: str, end: str, value: float) -> None:
        self.lines.append((code, _plain(description), start, end, value))

    def pick(self, start: str | None = None) -> list[tuple[str, str, float]]:
        return [(c, d, v) for c, d, s, e, v in self.lines if start is None or s == start]


def _scan(archive: zipfile.ZipFile, member: str, cnpjs: set[str], versions: dict[tuple[str, str], int],
          into: dict[tuple[str, str, str], _Statement], statement: str) -> set[str]:
    seen: set[str] = set()
    for row in _rows(archive, member):
        cnpj = row["CNPJ_CIA"]
        if cnpj not in cnpjs or row["ORDEM_EXERC"] != "ÚLTIMO":
            continue
        key = (cnpj, row["DT_REFER"])
        version = int(row["VERSAO"] or 0)
        if version != versions.get(key, version):
            continue
        scale = 1000.0 if row["ESCALA_MOEDA"].upper() == "MIL" else 1.0
        try:
            value = float(row["VL_CONTA"]) * scale
        except ValueError:
            continue
        into.setdefault((cnpj, row["DT_REFER"], statement), _Statement()).add(
            row["CD_CONTA"], row["DS_CONTA"], row.get("DT_INI_EXERC") or "", row["DT_FIM_EXERC"], value
        )
        seen.add(cnpj)
    return seen


def _load_year(kind: str, year: int, cnpjs: set[str], filings: list[Filing],
               statements: dict[tuple[str, str, str], _Statement], shares: dict[tuple[str, str], float]) -> None:
    path = fetch_zip(kind, year)
    if path is None:
        return
    prefix = f"{kind.lower()}_cia_aberta"
    with zipfile.ZipFile(path) as archive:
        versions: dict[tuple[str, str], int] = {}
        for row in _rows(archive, f"{prefix}_{year}.csv"):
            if row["CNPJ_CIA"] not in cnpjs:
                continue
            key = (row["CNPJ_CIA"], row["DT_REFER"])
            version = int(row["VERSAO"] or 0)
            if version >= versions.get(key, -1):
                versions[key] = version
                filings[:] = [f for f in filings if not (f.cnpj == key[0] and f.period_end == key[1] and f.doc_type == kind)]
                filings.append(Filing(key[0], key[1], kind, version, row.get("DT_RECEB"), row.get("LINK_DOC")))
        for statement in ("DRE", "BPA", "BPP", "DFC_MI", "DFC_MD"):
            consolidated = _scan(archive, f"{prefix}_{statement}_con_{year}.csv", cnpjs, versions, statements, statement)
            # empresas sem controladas só publicam a demonstração individual
            missing = {c for c in cnpjs if c not in consolidated}
            if missing:
                _scan(archive, f"{prefix}_{statement}_ind_{year}.csv", missing, versions, statements, statement)
        for row in _rows(archive, f"{prefix}_composicao_capital_{year}.csv"):
            if row["CNPJ_CIA"] in cnpjs:
                try:
                    total = float(row["QT_ACAO_TOTAL_CAP_INTEGR"] or 0) - float(row["QT_ACAO_TOTAL_TESOURO"] or 0)
                except ValueError:
                    continue
                if total > 0:
                    shares[(row["CNPJ_CIA"], row["DT_REFER"])] = total


def _find(lines: list[tuple[str, str, float]], depth: int | None, *patterns: str) -> tuple[str, float] | None:
    for code, description, value in lines:
        if depth is not None and _depth(code) != depth:
            continue
        if any(re.search(p, description) for p in patterns):
            return code, value
    return None


def _income(dre: _Statement, start: str) -> dict[str, float]:
    lines = dre.pick(start)
    if not lines:
        return {}
    out: dict[str, float] = {}
    revenue = next((v for c, d, v in lines if c == "3.01"), None)
    if revenue:
        out["revenue"] = revenue
    ebit = _find(lines, 1, r"^resultado antes do resultado financeiro e dos tributos")
    if ebit:
        out["ebit"] = ebit[1]
    profits = [(c, d, v) for c, d, v in lines if _depth(c) == 1 and d.startswith("lucro") and ("periodo" in d or "exercicio" in d)]
    if profits:
        code, _, total = profits[-1]
        out["net_income_total"] = total
        parent = next((v for c, d, v in lines if c.startswith(code + ".") and "controladora" in d and "nao" not in d), None)
        out["net_income"] = parent if parent else total
    return out


def _balance(bpa: _Statement | None, bpp: _Statement | None) -> dict[str, float]:
    out: dict[str, float] = {}
    if bpa:
        lines = bpa.pick()
        total = next((v for c, d, v in lines if c == "1"), None)
        if total:
            out["total_assets"] = total
        cash = [v for c, d, v in lines if _depth(c) == 2 and c.startswith("1.01.") and (
            d.startswith("caixa e equivalentes") or d.startswith("aplicacoes financeiras"))]
        if cash:
            out["cash"] = sum(cash)
    if bpp:
        lines = bpp.pick()
        equity_row = next(((c, v) for c, d, v in lines if _depth(c) == 1 and d.startswith("patrimonio liquido")), None)
        if equity_row:
            code, equity = equity_row
            out["equity"] = equity
            parent = next((v for c, d, v in lines if c.startswith(code + ".") and "atribuido ao controlador" in d), None)
            minority = next((v for c, d, v in lines if c.startswith(code + ".") and "nao controlador" in d), None)
            out["equity_parent"] = parent if parent else equity - (minority or 0)
        debt = [v for c, d, v in lines if _depth(c) == 2 and c.startswith(("2.01.", "2.02.")) and (
            d.startswith("emprestimos e financiamentos") or d.startswith("debentures"))]
        if debt:
            out["debt"] = sum(debt)
    return out


def _cash_flow_ytd(dfc: _Statement | None) -> dict[str, float]:
    if not dfc:
        return {}
    lines = dfc.pick()
    out: dict[str, float] = {}
    cfo = next((v for c, d, v in lines if c == "6.01"), None)
    if cfo is not None:
        out["cfo"] = cfo
    da = [v for c, d, v in lines if c.startswith("6.01.01.") and _depth(c) == 3
          and re.search(r"deprecia|amortiza|exaust", d) and "arrendamento" not in d]
    if da:
        out["da"] = abs(sum(da))
    # linhas zeradas contam: no 1º trimestre sem pagamento a linha vem 0, e o 2º trimestre é calculado a partir dela
    capex = [v for c, d, v in lines if c.startswith("6.02.") and v <= 0
             and re.search(r"imobilizado|intangive", d) and not re.search(r"venda|alienac|recebimento", d)]
    if capex:
        out["capex"] = abs(sum(capex))
    dividends = [v for c, d, v in lines if c.startswith("6.03.") and v <= 0
                 and re.search(r"dividend|juros s(obre|/) ?(o )?capital|\bjcp\b", d)]
    if dividends:
        out["dividends_paid"] = abs(sum(dividends))
    return out


PREVIOUS_QUARTER_END = {"06-30": "03-31", "09-30": "06-30", "12-31": "09-30"}
FINANCIAL_PATTERNS = (r"intermediacao financeira", r"atividades? segurador")


def statements_by_company(cnpjs: set[str], years: list[int]) -> tuple[dict[str, list[Quarter]], list[Filing]]:
    """Série trimestral padronizada por empresa, do trimestre mais antigo ao mais recente."""
    filings: list[Filing] = []
    statements: dict[tuple[str, str, str], _Statement] = {}
    shares: dict[tuple[str, str], float] = {}
    for year in years:
        _load_year("ITR", year, cnpjs, filings, statements, shares)
        _load_year("DFP", year, cnpjs, filings, statements, shares)

    output: dict[str, list[Quarter]] = {}
    for cnpj in cnpjs:
        ends = sorted({end for (c, end, _) in statements if c == cnpj})
        quarters: dict[str, Quarter] = {}
        ytd_cash: dict[str, dict[str, float]] = {}
        for end in ends:
            dre = statements.get((cnpj, end, "DRE"))
            quarter = Quarter(period_end=end)
            if dre:
                descriptions = " ".join(d for _, d, *_ in dre.lines)
                quarter.is_financial = any(re.search(p, descriptions) for p in FINANCIAL_PATTERNS)
                if end.endswith("12-31"):
                    annual = _income(dre, f"{end[:4]}-01-01")
                    previous = [quarters.get(f"{end[:4]}-{md}") for md in ("03-31", "06-30", "09-30")]
                    if annual and all(previous):
                        for key, value in annual.items():
                            parts = [q.values.get(key) for q in previous]
                            if all(p is not None for p in parts):
                                quarter.values[key] = value - sum(parts)
                else:
                    quarter.values.update(_income(dre, _quarter_start(end)))
            quarter.values.update(_balance(statements.get((cnpj, end, "BPA")), statements.get((cnpj, end, "BPP"))))
            ytd = _cash_flow_ytd(statements.get((cnpj, end, "DFC_MI")) or statements.get((cnpj, end, "DFC_MD")))
            ytd_cash[end] = ytd
            # o fluxo de caixa vem acumulado no ano: o trimestre é a diferença para o trimestre anterior
            previous_end = PREVIOUS_QUARTER_END.get(end[5:])
            previous_end = f"{end[:4]}-{previous_end}" if previous_end else None
            for key, value in ytd.items():
                if previous_end is None:
                    quarter.values[key] = value
                elif previous_end in ytd_cash:
                    # linha ausente no trimestre anterior = nada acumulado até ali
                    quarter.values[key] = value - ytd_cash[previous_end].get(key, 0.0)
            if (cnpj, end) in shares:
                quarter.values["shares"] = shares[(cnpj, end)]
            if quarter.values:
                quarters[end] = quarter
        output[cnpj] = [quarters[e] for e in sorted(quarters)]
    return output, filings
