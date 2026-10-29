"""Apuração do imposto de renda nas vendas em bolsa: ações, units, BDRs, ETFs, FIIs e Fiagros (spec, Parte A).

Regras (Perguntas e Respostas IRPF 2026, perguntas 704 a 745):
- custo médio ponderado POR TITULAR, juntando todas as corretoras (720); taxas somam na compra e saem da venda
  (708); desdobro e grupamento só mudam a quantidade (722); bonificação entra com o custo por ação informado (721);
- day trade: mesmo ativo, mesmo dia, mesma corretora (705); o que sobra do dia é operação comum;
- apuração mensal em três grupos que não se misturam: comum (15%), day trade (20%) e FII/Fiagro (20%) (706, 709);
- ações e units isentas no mês com vendas de ações até R$ 20 mil (707); prejuízo desse mês continua compensável
  (729). Decisão do usuário: vendas de ações em day trade contam no limite (conservador);
- prejuízo passa de mês e de ano sem prazo (711); IRRF de 0,005% (só acima de R$ 1) e de 1% no day trade descontam
  do imposto no ano (706, 714, 715); DARF 6015 até o último dia útil do mês seguinte, mínimo de R$ 10 (730).

Simplificações, ditas na tela: vencimento pelo mês do pregão; feriados não contam no "último dia útil"; IRRF sem a
nota da corretora é estimado; ordem dentro do dia sem horário: compras antes das vendas.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.db import rows, transaction
from app.services import analytics, household
from app.services.ir import parametros
from app.services.targets import INTERNATIONAL_ETFS

D = Decimal
RV = parametros.RENDA_VARIAVEL
QTY_EPSILON = 100  # 0,0001 unidade
GRUPOS = ("comum", "day_trade", "fii")
GRUPO_NOMES = {"comum": "Operações comuns", "day_trade": "Day trade", "fii": "FII e Fiagro"}
CLASSES = {
    "acao": "Ação", "unit": "Unit de ações", "bdr": "BDR", "etf": "ETF de ações", "etf_rf": "ETF de renda fixa",
    "fii": "FII", "fiagro": "Fiagro", "outro": "Fora do cálculo",
}
ISENTAS = {"acao", "unit"}           # entram no limite de R$ 20 mil e podem ter o lucro isento
FUNDOS_IMOBILIARIOS = {"fii", "fiagro"}
FORA = {"etf_rf", "outro"}           # tributados de outro jeito (fonte, exterior, ganho de capital)
# Bens e Direitos: (grupo, código, descrição). ETF de ações: há guias com 07 – 09; vale o que o programa trouxer.
BENS = {
    "acao": ("03", "01", "Ações (inclusive as listadas em bolsa)"),
    "unit": ("03", "01", "Ações (inclusive as listadas em bolsa)"),
    "bdr": ("04", "04", "Ativos negociados em bolsa no Brasil (BDR, opções e outros)"),
    "etf": ("07", "06", "Fundos de índice (ETF)"),
    "fii": ("07", "03", "Fundos de Investimento Imobiliário (FII)"),
    "fiagro": ("07", "02", "Fiagro"),
}
# Units e ETFs mais comuns, para o ticker 11 sem outra pista.
UNITS = {"TAEE11", "KLBN11", "SANB11", "ALUP11", "BPAC11", "ENGI11", "SAPR11", "IGTI11", "TIET11", "CPLE11",
         "BRBI11", "ITUB11", "AESB11", "SULA11", "RNEW11", "PPLA11", "STBP11", "TRPL11"}
ETFS = INTERNATIONAL_ETFS | {"BOVA11", "BOVV11", "BOVX11", "SMAL11", "DIVO11", "PIBB11", "ECOO11", "FIND11", "MATB11",
                             "ISUS11", "GOVE11", "BRAX11", "XBOV11", "SMAC11", "DIVD11", "NSDV11", "LVOL11", "AUVP11"}
ETFS_RF = {"IMAB11", "IRFM11", "FIXA11", "B5P211", "IB5M11", "DEBB11", "LFTS11", "NTNS11", "IMBB11", "5PRE11"}


# ---------------------------------------------------------------- classe fiscal

def classe_sugerida(ticker: str, asset_class: str | None, currency: str | None = "BRL") -> str | None:
    """Classe pela origem e pelo ticker; None quando não dá para saber (ticker 11 sem pista)."""
    t = (ticker or "").upper()
    kind = (asset_class or "").strip()
    if (currency or "BRL").upper() != "BRL":
        return "outro"
    if t in ETFS_RF:
        return "etf_rf"
    if kind == "FII":
        return "fii"
    if kind.lower() == "fiagro":
        return "fiagro"
    if kind == "BDR" or t[4:] in {"32", "33", "34", "35", "39"}:
        return "bdr"
    if kind == "ETF" or t in ETFS:
        return "etf"
    if t in UNITS:
        return "unit"
    if kind == "Ação" and not t.endswith("11"):
        return "acao"
    # A Pluggy chama tudo de "Ação", até ETF e FII: o ticker 11 fora das listas fica para o usuário dizer
    if kind in {"Ação", "FII/ETF/Unit", "Não classificado", ""}:
        return None if t.endswith("11") else ("acao" if t[4:] in {"3", "4", "5", "6", "7", "8"} else None)
    return "outro"


def instrumentos() -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for r in rows("SELECT i.id, i.ticker, i.name, i.asset_class, i.currency, i.tax_class, c.cnpj FROM instrument i "
                  "LEFT JOIN company_profile c ON c.instrument_id = i.id"):
        sugerida = classe_sugerida(r["ticker"], r["asset_class"], r["currency"])
        out[int(r["id"])] = {"id": int(r["id"]), "ticker": r["ticker"], "name": r["name"], "cnpj": r["cnpj"],
                             "classe": r["tax_class"] or sugerida, "classe_informada": bool(r["tax_class"]),
                             "classe_sugerida": sugerida}
    return out


def definir_classe(ticker: str, classe: str | None) -> dict[str, Any]:
    if classe is not None and classe not in CLASSES:
        raise ValueError(f"Classe inválida: {classe}. Use {', '.join(CLASSES)}.")
    with transaction() as con:
        found = con.execute("SELECT id, ticker FROM instrument WHERE ticker = ? COLLATE NOCASE", (ticker.strip(),)).fetchone()
        if not found:
            raise ValueError(f"Ativo não encontrado: {ticker}.")
        con.execute("UPDATE instrument SET tax_class = ? WHERE id = ?", (classe, found["id"]))
    return {"ticker": found["ticker"], "classe": classe, "classe_nome": CLASSES.get(classe or "", "automática")}


# ---------------------------------------------------------------- informações do titular

def informacoes(member: int) -> list[dict[str, Any]]:
    return [dict(r) for r in rows("SELECT * FROM ir_rv_info WHERE member_id = ? ORDER BY period, kind", (member,))]


def informar(member: int, kind: str, valor_cents: int, period: str = "", grupo: str = "", conta: str = "",
             ref_id: int = 0, pago_em: str | None = None, autor: str = "usuario") -> dict[str, Any]:
    """Grava (ou corrige) uma informação da apuração. Valor None/negativo não é aceito, exceto zero para 'não tenho'."""
    if kind not in {"prejuizo_anterior", "irrf", "taxa", "darf_pago", "custo_bonificacao"}:
        raise ValueError("Tipo de informação desconhecido.")
    if valor_cents < 0:
        raise ValueError("Informe o valor sem sinal negativo.")
    if grupo and grupo not in GRUPOS:
        raise ValueError(f"Grupo inválido: {grupo}. Use {', '.join(GRUPOS)}.")
    if kind == "prejuizo_anterior" and not (len(period) == 4 and period.isdigit()):
        raise ValueError("O prejuízo anterior vale a partir de um ano (AAAA).")
    if kind in {"irrf", "taxa", "darf_pago"} and not (len(period) == 7 and period[4] == "-"):
        raise ValueError("Informe o mês como AAAA-MM.")
    with transaction() as con:
        con.execute(
            "INSERT INTO ir_rv_info(member_id, kind, period, grupo, account_name, ref_id, amount_cents, paid_on, author) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(member_id, kind, period, grupo, account_name, ref_id) "
            "DO UPDATE SET amount_cents = excluded.amount_cents, paid_on = excluded.paid_on, author = excluded.author, "
            "created_at = CURRENT_TIMESTAMP",
            (member, kind, period, grupo, conta, ref_id, valor_cents, pago_em, autor),
        )
    return {"tipo": kind, "periodo": period, "grupo": grupo, "conta": conta, "ref_id": ref_id, "valor": valor_cents / 100}


def remover_informacao(member: int, info_id: int) -> None:
    with transaction() as con:
        con.execute("DELETE FROM ir_rv_info WHERE id = ? AND member_id = ?", (info_id, member))


def _div(a: int, b: int) -> int:
    """a ÷ b arredondado meio para cima (a ≥ 0, b > 0)."""
    return (2 * a + b) // (2 * b)


# ---------------------------------------------------------------- datas

def ultimo_dia_util(ano: int, mes: int) -> date:
    dia = date(ano, mes, calendar.monthrange(ano, mes)[1])
    while dia.weekday() >= 5:
        dia -= timedelta(days=1)
    return dia


def vencimento(mes: str) -> date:
    ano, m = int(mes[:4]), int(mes[5:7])
    ano, m = (ano + 1, 1) if m == 12 else (ano, m + 1)
    return ultimo_dia_util(ano, m)


def _meses(primeiro: str, ultimo: str) -> list[str]:
    ano, mes = int(primeiro[:4]), int(primeiro[5:7])
    out = []
    while f"{ano:04d}-{mes:02d}" <= ultimo:
        out.append(f"{ano:04d}-{mes:02d}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return out


# ---------------------------------------------------------------- estoque

@dataclass
class Estoque:
    quantidade: int = 0
    custo: int = 0
    custo_conhecido: bool = True

    def entrar(self, quantidade: int, custo: int | None) -> None:
        self.quantidade += quantidade
        if custo is None:
            self.custo_conhecido = False
        else:
            self.custo += custo

    def sair(self, quantidade: int) -> tuple[int, int]:
        """Tira a quantidade pelo custo médio. Devolve (custo, quantidade que faltou no estoque)."""
        if self.quantidade <= QTY_EPSILON:
            return 0, quantidade
        usada = min(quantidade, self.quantidade)
        custo = _div(self.custo * usada, self.quantidade)
        self.custo -= custo
        self.quantidade -= usada
        if self.quantidade <= QTY_EPSILON:
            self.quantidade, self.custo = 0, 0
            self.custo_conhecido = True
        falta = quantidade - usada
        return custo, (falta if falta > QTY_EPSILON else 0)

    @property
    def preco_medio(self) -> int | None:
        return _div(self.custo * 1_000_000, self.quantidade) if self.quantidade > QTY_EPSILON else None


@dataclass
class Venda:
    data: str
    conta: str
    instrumento: int
    ticker: str
    classe: str
    grupo: str           # comum | day_trade | fii
    day_trade: bool
    quantidade: int
    valor: int
    custo: int
    pendente: str | None = None

    @property
    def resultado(self) -> int:
        return self.valor - self.custo


@dataclass
class Apuracao:
    vendas: list[Venda] = field(default_factory=list)
    pendencias: list[dict[str, Any]] = field(default_factory=list)
    fechamento: dict[int, dict[int, dict[str, Any]]] = field(default_factory=dict)  # ano → ativo → posição
    proventos: list[dict[str, Any]] = field(default_factory=list)
    irrf_dias: dict[tuple[str, str, str], int] = field(default_factory=dict)  # (dia, conta, grupo) → base
    sem_historico: dict[int, int] = field(default_factory=dict)  # ativo → custódia que o histórico não explica


ORDEM = {"OPENING": 0, "SPLIT": 1, "BONUS": 1, "TRANSFER_OUT": 2, "TRANSFER_IN": 3}


def _efetivos(evs: list[Any]) -> list[Any]:
    """Mesma regra da carteira: a última posição inicial vale, e as operações até ela ficam de fora."""
    openings = [e for e in evs if e["event_type"] == "OPENING"]
    opening_day = openings[-1]["event_date"] if openings else None
    out = []
    for e in evs:
        if e["event_type"] in analytics.INCOME:
            out.append(e)
        elif e["event_type"] == "OPENING":
            if e is openings[-1]:
                out.append(e)
        elif not opening_day or e["event_date"] > opening_day:
            out.append(e)
    return out


def _taxas(member: int, eventos: list[Any]) -> dict[int, int]:
    """Rateio da taxa informada do mês por conta, proporcional ao valor de cada compra e venda."""
    informadas = {(r["period"], r["account_name"]): int(r["amount_cents"])
                  for r in rows("SELECT period, account_name, amount_cents FROM ir_rv_info WHERE member_id = ? AND kind = 'taxa'", (member,))}
    if not informadas:
        return {}
    por_mes: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for e in eventos:
        if e["event_type"] in {"BUY", "SELL"} and e["amount_cents"]:
            por_mes[(e["event_date"][:7], e["account_name"])].append(e)
    out: dict[int, int] = {}
    for chave, taxa in informadas.items():
        evs = por_mes.get(chave, [])
        total = sum(abs(int(e["amount_cents"])) for e in evs)
        restante = taxa
        for i, e in enumerate(evs):
            parte = restante if i == len(evs) - 1 else _div(taxa * abs(int(e["amount_cents"])), total)
            out[int(e["id"])] = parte
            restante -= parte
    return out


def calcular(member: int) -> Apuracao:
    """Percorre toda a história do titular, dia a dia, e devolve vendas, posições de fim de ano e proventos."""
    info = instrumentos()
    ap = Apuracao()
    eventos: list[Any] = []
    for (_, _), evs in analytics.chosen_events(member).items():
        eventos.extend(_efetivos(evs))
    taxas = _taxas(member, eventos)
    bonus_custo = {int(r["ref_id"]): int(r["amount_cents"]) for r in
                   rows("SELECT ref_id, amount_cents FROM ir_rv_info WHERE member_id = ? AND kind = 'custo_bonificacao'", (member,))}
    estoques: dict[int, Estoque] = defaultdict(Estoque)
    custodia: dict[tuple[int, str], int] = defaultdict(int)
    em_transito: dict[int, list[tuple[int, int]]] = defaultdict(list)
    por_dia: dict[str, list[Any]] = defaultdict(list)
    for e in eventos:
        por_dia[e["event_date"]].append(e)
    ano_aberto: int | None = None
    pend_vistas: set[tuple[str, int, str]] = set()

    def pendencia(tipo: str, iid: int, texto: str, ref: Any = None, bloqueia: bool = True, dia: str = "") -> None:
        chave = (tipo, iid, str(ref))
        if chave in pend_vistas:
            return
        pend_vistas.add(chave)
        ap.pendencias.append({"tipo": tipo, "ticker": info.get(iid, {}).get("ticker", ""), "instrumento": iid,
                              "texto": texto, "ref": ref, "bloqueia": bloqueia, "data": dia})

    def fechar(ano: int) -> None:
        ap.fechamento[ano] = {iid: {"quantidade": s.quantidade, "custo": s.custo, "custo_conhecido": s.custo_conhecido,
                                    "custodia": {c: q for (i, c), q in custodia.items() if i == iid and q > QTY_EPSILON}}
                              for iid, s in estoques.items() if s.quantidade > QTY_EPSILON}

    def vender(dia: str, conta: str, iid: int, quantidade: int, valor: int, day_trade: bool = False, custo: int | None = None) -> None:
        classe = info[iid]["classe"]
        pend = None
        if custo is None:
            estoque = estoques[iid]
            sem_custo = not estoque.custo_conhecido
            custo, falta = estoque.sair(quantidade)
            if falta:
                pend = "estoque"
                pendencia("estoque_negativo", iid, f"Venda de {info[iid]['ticker']} em {dia} maior que a posição: falta "
                          "compra, evento ou posição inicial. A parte que faltou entrou com custo zero.", dia, dia=dia)
            elif sem_custo:
                pend = "sem_custo"
                pendencia("venda_sem_custo", iid, f"{info[iid]['ticker']}: venda em {dia} sem preço médio conhecido. Informe "
                          "a posição inicial com preço médio (Importar › posições) ou importe o histórico de compras.", dia=dia)
        grupo = "fii" if classe in FUNDOS_IMOBILIARIOS else "day_trade" if day_trade else "comum"
        ap.vendas.append(Venda(dia, conta, iid, info[iid]["ticker"], classe, grupo, day_trade, quantidade, valor, custo, pend))
        ap.irrf_dias[(dia, conta, grupo)] = ap.irrf_dias.get((dia, conta, grupo), 0) + (
            max(0, valor - custo) if day_trade else valor)

    for dia in sorted(por_dia):
        ano = int(dia[:4])
        if ano_aberto is None:
            ano_aberto = ano
        while ano_aberto < ano:
            fechar(ano_aberto)
            ano_aberto += 1
        evs = sorted(por_dia[dia], key=lambda e: (ORDEM.get(e["event_type"], 5), e["id"]))
        trades: dict[tuple[str, int], dict[str, list[Any]]] = defaultdict(lambda: {"BUY": [], "SELL": []})
        for e in evs:
            iid, kind = int(e["instrument_id"]), e["event_type"]
            q = abs(int(e["quantity_micros"] or 0))
            amount = None if e["amount_cents"] is None else abs(int(e["amount_cents"]))
            if iid not in info:
                continue
            if info[iid]["classe"] in FORA:
                if kind == "SELL" and info[iid]["classe"] == "outro":
                    pendencia("fora_do_calculo", iid, f"{info[iid]['ticker']}: venda fora do cálculo (exterior, renda fixa "
                              "ou outro mercado). Lance à mão no programa.", dia[:4], bloqueia=False, dia=dia)
                continue
            if info[iid]["classe"] is None and kind in {"BUY", "SELL", "OPENING"}:
                pendencia("classe", iid, f"{info[iid]['ticker']}: diga se é FII, ETF ou unit de ações. Muda a alíquota "
                          "e a isenção.", bloqueia=True, dia=dia)
            if kind in analytics.INCOME:
                if amount:
                    ap.proventos.append({"data": dia, "instrumento": iid, "tipo": kind, "valor": amount, "conta": e["account_name"]})
                continue
            if kind == "OPENING":
                estoques[iid].entrar(q, amount)
                custodia[(iid, e["account_name"])] += q
            elif kind == "SPLIT":
                estoques[iid].quantidade += int(e["quantity_micros"] or 0)
                custodia[(iid, e["account_name"])] += int(e["quantity_micros"] or 0)
            elif kind == "BONUS":
                signed = int(e["quantity_micros"] or 0)
                unit = bonus_custo.get(int(e["id"]), e["unit_price_cents"])
                if signed > 0 and unit is None:
                    pendencia("bonificacao", iid, f"{info[iid]['ticker']}: bonificação de {signed / 1_000_000:g} em {dia} sem "
                              "custo. Informe o valor por ação do aviso aos acionistas (até lá, custo zero).", int(e["id"]), dia=dia)
                estoques[iid].entrar(signed, _div(signed * int(unit or 0), 1_000_000) if signed > 0 else 0)
                custodia[(iid, e["account_name"])] += signed
            elif kind == "TRANSFER_OUT":
                custo, _ = estoques[iid].sair(q)
                em_transito[iid].append((q, custo))
                custodia[(iid, e["account_name"])] -= q
            elif kind == "TRANSFER_IN":
                if amount is None and em_transito[iid]:
                    q_out, custo_out = em_transito[iid].pop(0)
                    amount = _div(custo_out * q, q_out) if q_out else 0
                estoques[iid].entrar(q, amount)
                custodia[(iid, e["account_name"])] += q
            elif kind in {"BUY", "SELL"}:
                trades[(e["account_name"], iid)][kind].append(e)
        sobras_venda: list[tuple[str, int, int, int]] = []
        for (conta, iid), lados in trades.items():
            def total(lado: str) -> tuple[int, int | None]:
                qtd, valor = 0, 0
                for e in lados[lado]:
                    qtd += abs(int(e["quantity_micros"] or 0))
                    if e["amount_cents"] is None:
                        valor = None
                    elif valor is not None:
                        taxa = taxas.get(int(e["id"]), 0)
                        valor += abs(int(e["amount_cents"])) + (taxa if lado == "BUY" else -taxa)
                return qtd, valor
            q_compra, v_compra = total("BUY")
            q_venda, v_venda = total("SELL")
            q_dt = min(q_compra, q_venda)
            custo_dt = valor_dt = 0
            if q_dt > QTY_EPSILON and v_compra is not None and v_venda is not None:
                custo_dt = _div(v_compra * q_dt, q_compra)
                valor_dt = _div(v_venda * q_dt, q_venda)
                vender(dia, conta, iid, q_dt, valor_dt, day_trade=True, custo=custo_dt)
            else:
                q_dt = 0
            if q_compra - q_dt > QTY_EPSILON:
                estoques[iid].entrar(q_compra - q_dt, None if v_compra is None else v_compra - custo_dt)
            custodia[(iid, conta)] += q_compra - q_venda
            if q_venda - q_dt > QTY_EPSILON:
                if v_venda is None:
                    pendencia("venda_sem_valor", iid, f"{info[iid]['ticker']}: venda em {dia} sem valor. Importe a planilha "
                              "de Negociação da B3 ou o CSV de operações.", dia, dia=dia)
                sobras_venda.append((conta, iid, q_venda - q_dt, (v_venda or 0) - valor_dt))
        for conta, iid, q, v in sobras_venda:
            vender(dia, conta, iid, q, v)
    if ano_aberto is not None:
        for ano in range(ano_aberto, date.today().year + 1):
            fechar(ano)

    # A Pluggy manda só uns 12 meses de operações: o que a corretora custodia além do histórico não tem custo nem
    # entra em Bens e Direitos até o usuário informar a posição inicial.
    scope, params = analytics.member_scope(member)
    ultima: dict[tuple[int, str], tuple[str, int, int]] = {}
    for r in rows("SELECT a.account_name, ps.instrument_id, ps.as_of_date, ps.quantity_micros, ps.source "
                  "FROM position_snapshot ps JOIN financial_account a ON a.id = ps.account_id" + scope, params):
        k = (int(r["instrument_id"]), r["account_name"])
        rank = analytics.SNAPSHOT_PRIORITY.get(r["source"], 9)
        atual = ultima.get(k)
        if atual is None or r["as_of_date"] > atual[0] or (r["as_of_date"] == atual[0] and rank < atual[1]):
            ultima[k] = (r["as_of_date"], rank, int(r["quantity_micros"]))
    for (iid, conta), (dia, _, q) in sorted(ultima.items()):
        explicado = custodia.get((iid, conta), 0)
        if iid not in info or info[iid]["classe"] in FORA or q - explicado <= QTY_EPSILON:
            continue
        ap.sem_historico[iid] = ap.sem_historico.get(iid, 0) + q - explicado
        pendencia("posicao_sem_historico", iid, f"{info[iid]['ticker']}: {conta} mostra {q / 1_000_000:g} em "
                  f"{dia[8:10]}/{dia[5:7]}/{dia[:4]} e o histórico de operações explica {explicado / 1_000_000:g}. "
                  f"Informe a posição inicial em Importar › posições, na conta {conta}, com data anterior à primeira "
                  "operação do histórico e o preço médio, para Bens e Direitos saírem certos.", conta, bloqueia=False)
    return ap


# ---------------------------------------------------------------- apuração mensal

def _membro(member: int | None) -> int:
    return member if member is not None else household.PRIMARY_ID


def apurar(member: int | None, ano: int, hoje: date | None = None) -> dict[str, Any]:
    """Apuração do ano: meses com venda, DARFs, prejuízos, isentos, bens e direitos e proventos. Centavos."""
    member = _membro(member)
    hoje = hoje or date.today()
    ap = calcular(member)
    infos = informacoes(member)
    irrf_informado = {(i["period"], i["grupo"]): int(i["amount_cents"]) for i in infos if i["kind"] == "irrf"}
    pagos = {i["period"]: i for i in infos if i["kind"] == "darf_pago"}
    prejuizo_inicial: dict[int, dict[str, int]] = defaultdict(lambda: dict.fromkeys(GRUPOS, 0))
    for i in infos:
        if i["kind"] == "prejuizo_anterior":
            prejuizo_inicial[int(i["period"])][i["grupo"] or "comum"] += int(i["amount_cents"])

    vendas_mes: dict[str, list[Venda]] = defaultdict(list)
    for v in ap.vendas:
        vendas_mes[v.data[:7]].append(v)
    irrf_estimado: dict[tuple[str, str], int] = defaultdict(int)
    for (dia, _, grupo), base in ap.irrf_dias.items():
        if grupo == "day_trade":
            valor = parametros.centavos(D(base) * RV["irrf_day_trade"])
        else:
            valor = parametros.centavos(D(base) * RV["irrf_comum"])
            valor = valor if valor > RV["irrf_minimo"] else 0
        irrf_estimado[(dia[:7], grupo)] += valor

    primeiro = min([*vendas_mes, f"{ano}-01", *[f"{a}-01" for a in prejuizo_inicial]])
    ultimo = f"{ano}-12" if ano < hoje.year else hoje.isoformat()[:7]
    prejuizo = dict.fromkeys(GRUPOS, 0)
    irrf_saldo = 0
    acumulado = 0
    meses: list[dict[str, Any]] = []
    prejuizo_inicio_ano = dict(prejuizo)
    irrf_sobra_ano = 0
    for mes in _meses(primeiro, ultimo):
        a = int(mes[:4])
        if mes.endswith("-01"):
            irrf_saldo = 0
            for g, v in prejuizo_inicial.get(a, {}).items():
                prejuizo[g] += v
            if a == ano:
                prejuizo_inicio_ano = dict(prejuizo)
        vs = vendas_mes.get(mes, [])
        vendas_acoes = sum(v.valor for v in vs if v.classe in ISENTAS)
        res_acoes = sum(v.resultado for v in vs if v.grupo == "comum" and v.classe in ISENTAS)
        res_outros = sum(v.resultado for v in vs if v.grupo == "comum" and v.classe not in ISENTAS)
        isento = vendas_acoes <= RV["isencao_acoes_mensal"] and res_acoes > 0
        resultado = {"comum": res_outros + (0 if isento else res_acoes),
                     "day_trade": sum(v.resultado for v in vs if v.grupo == "day_trade"),
                     "fii": sum(v.resultado for v in vs if v.grupo == "fii")}
        compensado, base, imposto = {}, {}, {}
        aliquotas = {"comum": RV["aliquota_comum"], "day_trade": RV["aliquota_day_trade"], "fii": RV["aliquota_fii"]}
        for g in GRUPOS:
            r = resultado[g]
            if r > 0:
                compensado[g] = min(r, prejuizo[g])
                prejuizo[g] -= compensado[g]
                base[g] = r - compensado[g]
            else:
                compensado[g], base[g] = 0, 0
                prejuizo[g] += -r
            imposto[g] = parametros.centavos(D(base[g]) * aliquotas[g])
        irrf = {g: irrf_informado.get((mes, g), irrf_estimado.get((mes, g), 0)) for g in GRUPOS}
        irrf_saldo += sum(irrf.values())
        total_imposto = sum(imposto.values())
        irrf_usado = min(irrf_saldo, total_imposto)
        irrf_saldo -= irrf_usado
        devido = total_imposto - irrf_usado
        darf = devido + acumulado
        if darf and darf < RV["darf_minimo"]:
            acumulado, a_pagar = darf, 0
        else:
            acumulado, a_pagar = 0, darf
        if mes.endswith("-12"):
            irrf_sobra_ano = irrf_saldo if a == ano else irrf_sobra_ano
        if a != ano:
            continue
        pendente = any(v.pendente for v in vs)
        if not vs and not a_pagar:
            continue
        pago = pagos.get(mes)
        meses.append({
            "mes": mes, "vendas_acoes": vendas_acoes, "isencao_restante": max(0, RV["isencao_acoes_mensal"] - vendas_acoes),
            "isento": res_acoes if isento else 0, "resultado_acoes": res_acoes, "resultado_outros": res_outros,
            "resultado": resultado, "compensado": compensado, "base": base, "imposto": imposto,
            "irrf": irrf, "irrf_informado": {g: (mes, g) in irrf_informado for g in GRUPOS},
            "irrf_usado": irrf_usado, "devido": devido, "darf": a_pagar, "acumulado": acumulado,
            "vencimento": vencimento(mes).isoformat() if a_pagar else None,
            "pago": int(pago["amount_cents"]) if pago else None, "pago_em": pago["paid_on"] if pago else None,
            "atrasado": bool(a_pagar and not pago and vencimento(mes) < hoje),
            "prejuizo_fim": dict(prejuizo), "pendente": pendente,
            "vendas": [_venda_json(v) for v in vs],
        })
    if ano < hoje.year:
        irrf_sobra = irrf_sobra_ano
    else:
        irrf_sobra = irrf_saldo
    info = instrumentos()
    ano_vendas = [v for v in ap.vendas if v.data.startswith(str(ano))]
    pendencias = [p for p in ap.pendencias if not p.get("data") or p["data"][:4] <= str(ano)]
    if not any(i["kind"] == "prejuizo_anterior" for i in infos) and ap.vendas:
        pendencias.append({"tipo": "prejuizo_anterior", "ticker": "", "instrumento": None, "bloqueia": False, "data": "",
                           "ref": min(v.data[:4] for v in ap.vendas),
                           "texto": "Você tinha prejuízo na bolsa a compensar de antes do histórico do app? Informe o "
                                    "valor por grupo, ou responda que não tem."})
    mes_atual = hoje.isoformat()[:7]
    vendas_agora = sum(v.valor for v in vendas_mes.get(mes_atual, []) if v.classe in ISENTAS)
    total_vendas_ano = sum(v.valor for v in ano_vendas)
    return {
        "ano": ano, "titular": member, "meses": meses,
        "imposto_ano": sum(m["devido"] for m in meses), "darfs": [m for m in meses if m["darf"]],
        "darf_total": sum(m["darf"] for m in meses), "pendencias": pendencias,
        "bloqueado": any(p["bloqueia"] for p in pendencias),
        "prejuizo_inicio": prejuizo_inicio_ano, "prejuizo_fim": dict(prejuizo),
        "isentos_linha_20": sum(m["isento"] for m in meses), "irrf_sobra": irrf_sobra,
        "acumulado_abaixo_minimo": acumulado,
        "vendas_ano": total_vendas_ano,
        "obriga_declarar": total_vendas_ano > parametros.para(ano).obrigatoriedade.get("vendas_bolsa", 4_000_000)
        or any(sum(m["base"].values()) > 0 for m in meses),
        "este_mes": {"mes": mes_atual, "vendas_acoes": vendas_agora,
                     "isencao_restante": max(0, RV["isencao_acoes_mensal"] - vendas_agora)} if ano == hoje.year else None,
        "bens": _bens(ap, ano, info), "proventos": _proventos(ap, ano, info),
        "regras": {"isencao_acoes": RV["isencao_acoes_mensal"], "darf_codigo": RV["darf_codigo"],
                   "darf_minimo": RV["darf_minimo"]},
    }


def _venda_json(v: Venda) -> dict[str, Any]:
    return {"data": v.data, "conta": v.conta, "ticker": v.ticker, "classe": v.classe, "grupo": v.grupo,
            "day_trade": v.day_trade, "quantidade": v.quantidade, "valor": v.valor, "custo": v.custo,
            "resultado": v.resultado, "preco_medio": _div(v.custo * 1_000_000, v.quantidade) if v.quantidade else None,
            "pendente": v.pendente}


def _bens(ap: Apuracao, ano: int, info: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    antes, depois = ap.fechamento.get(ano - 1, {}), ap.fechamento.get(ano, {})
    # também o que foi comprado e vendido dentro do ano (pergunta 007): entra com zero nas duas datas
    vendidos = {v.instrumento for v in ap.vendas if v.data.startswith(str(ano))}
    out = []
    for iid in sorted(set(antes) | set(depois) | vendidos, key=lambda i: info[i]["ticker"]):
        i = info[iid]
        if i["classe"] not in BENS:
            continue
        grupo, codigo, nome = BENS[i["classe"]]
        a, d = antes.get(iid), depois.get(iid)
        qtd = d["quantidade"] if d else 0
        custo = d["custo"] if d else 0
        custodia = " e ".join(f"{c} ({q / 1_000_000:g})" for c, q in sorted((d or {}).get("custodia", {}).items()))
        if d:
            pm = custo / (qtd / 1_000_000) / 100
            texto = (f"{qtd / 1_000_000:g} {'cotas' if i['classe'] in FUNDOS_IMOBILIARIOS | {'etf'} else 'ações'} "
                     f"{i['ticker']} - {i['name']}" + (f", CNPJ {i['cnpj']}" if i["cnpj"] else "")
                     + (f". Custódia: {custodia}" if custodia else "") + f". Custo médio de R$ {_br(pm)} por unidade.")
        else:
            texto = f"{i['ticker']} - {i['name']}: posição vendida em {ano}."
        out.append({
            "ticker": i["ticker"], "nome": i["name"], "cnpj": i["cnpj"], "classe": i["classe"],
            "grupo": grupo, "codigo": codigo, "codigo_nome": nome,
            "anterior": a["custo"] if a else 0, "atual": custo, "quantidade": qtd,
            "custo_conhecido": (d or a or {}).get("custo_conhecido", True),
            "quantidade_sem_historico": ap.sem_historico.get(iid, 0),
            "dispensado": i["classe"] in ISENTAS and custo < 100_000 and (a["custo"] if a else 0) < 100_000,
            "discriminacao": texto,
        })
    return out


def _br(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _proventos(ap: Apuracao, ano: int, info: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    soma: dict[int, dict[str, int]] = defaultdict(lambda: {"DIVIDEND": 0, "JCP": 0, "INCOME": 0, "INTEREST": 0})
    for p in ap.proventos:
        if p["data"].startswith(str(ano)):
            soma[p["instrumento"]][p["tipo"]] += p["valor"]
    out = []
    for iid, s in sorted(soma.items(), key=lambda kv: info[kv[0]]["ticker"]):
        i = info[iid]
        fundo = i["classe"] in FUNDOS_IMOBILIARIOS
        out.append({"ticker": i["ticker"], "nome": i["name"], "cnpj": i["cnpj"], "classe": i["classe"],
                    "dividendos": 0 if fundo else s["DIVIDEND"], "jcp": s["JCP"],
                    "rendimentos_fii": (s["INCOME"] + s["DIVIDEND"]) if fundo else 0,
                    "outros": 0 if fundo else s["INCOME"] + s["INTEREST"]})
    return out


def dividendos_por_empresa_mes(member: int | None, ano: int) -> dict[tuple[int, str], int]:
    """Dividendos de ações por empresa e mês (a retenção de 10% olha para isso)."""
    ap = calcular(_membro(member))
    info = instrumentos()
    out: dict[tuple[int, str], int] = defaultdict(int)
    for p in ap.proventos:
        if p["data"].startswith(str(ano)) and p["tipo"] == "DIVIDEND" and info[p["instrumento"]]["classe"] not in FUNDOS_IMOBILIARIOS:
            out[(p["instrumento"], p["data"][:7])] += p["valor"]
    return out
