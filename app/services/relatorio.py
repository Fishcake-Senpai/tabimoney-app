"""Relatório do período (mês, trimestre ou ano) num arquivo HTML só: para guardar, imprimir ou mandar a alguém.

`montar` junta o que as telas de Gastos, Orçamento e Investimentos já calculam (transferências entre contas
próprias ficam de fora das receitas e despesas, estorno abate o gasto) e `renderizar` gera o HTML com fonte,
ícones e mascote embutidos, sem nada da internet. Por padrão, números de conta e nomes de pessoas em Pix e
transferências saem mascarados, porque o arquivo é feito para sair da máquina.
"""
from __future__ import annotations

import calendar
import re
import secrets
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from app import __version__, db
from app.services import analytics, budgets, embutir, household, spending
from app.services.categories import INTERNAL_CATEGORIES, category_icon
from app.services.formatting import brl, brl_compact, brl_whole, date_br, pct

PERIODOS = ("mes", "trimestre", "ano")
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]
MESES_CURTOS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
# quantos períodos anteriores formam a base de comparação
BASE = {"mes": 6, "trimestre": 4, "ano": 1}
NOMES = {"mes": ("mês", "meses"), "trimestre": ("trimestre", "trimestres"), "ano": ("ano", "anos")}
INVESTIMENTOS = "Investimentos"
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


# ---------------------------------------------------------------- período

@dataclass
class Periodo:
    tipo: str
    inicio: date
    fim: date  # inclusive
    ref: str
    titulo: str
    subtitulo: str
    meses: list[str] = field(default_factory=list)

    def anterior(self, passos: int = 1) -> "Periodo":
        dia = self.inicio
        for _ in range(passos):
            dia = periodo(self.tipo, (dia - timedelta(days=1)).strftime("%Y-%m")).inicio
        return periodo(self.tipo, dia.strftime("%Y-%m"))

    def contem(self, dia: str) -> bool:
        return self.inicio.isoformat() <= dia[:10] <= self.fim.isoformat()


def _mes(ano: int, mes: int) -> str:
    return f"{ano:04d}-{mes:02d}"


def periodo(tipo: str, ref: str | None = None, today: date | None = None) -> Periodo:
    """Mês ('AAAA-MM'), trimestre ('AAAA-T3' ou um mês dele) ou ano ('AAAA' ou um mês dele). Sem ref, o atual."""
    if tipo not in PERIODOS:
        raise ValueError(f"Período inválido: {tipo}. Use mes, trimestre ou ano.")
    today = today or date.today()
    text = (ref or today.strftime("%Y-%m")).strip().upper()
    ano, mes = today.year, today.month
    if m := re.fullmatch(r"(\d{4})-(\d{2})", text):
        ano, mes = int(m.group(1)), int(m.group(2))
    elif tipo == "trimestre" and (m := re.fullmatch(r"(\d{4})-[TQ]([1-4])", text)):
        ano, mes = int(m.group(1)), int(m.group(2)) * 3 - 2
    elif tipo == "ano" and re.fullmatch(r"\d{4}", text):
        ano, mes = int(text), 1
    else:
        formato = {"mes": "AAAA-MM", "trimestre": "AAAA-T1 a AAAA-T4", "ano": "AAAA"}[tipo]
        raise ValueError(f"Referência inválida: {ref}. Use {formato}.")
    if not 1 <= mes <= 12:
        raise ValueError(f"Mês inválido: {ref}.")
    if tipo == "mes":
        primeiro, ultimo = mes, mes
        titulo = f"{MESES[mes - 1].capitalize()} de {ano}"
        subtitulo = "Relatório do mês"
        ref_norm = _mes(ano, mes)
    elif tipo == "trimestre":
        tri = (mes - 1) // 3 + 1
        primeiro, ultimo = tri * 3 - 2, tri * 3
        titulo = f"{tri}º trimestre de {ano}"
        subtitulo = f"Relatório do trimestre · {MESES_CURTOS[primeiro - 1]} a {MESES_CURTOS[ultimo - 1]}"
        ref_norm = f"{ano}-T{tri}"
    else:
        primeiro, ultimo = 1, 12
        titulo = str(ano)
        subtitulo = "Relatório do ano"
        ref_norm = str(ano)
    return Periodo(
        tipo=tipo, inicio=date(ano, primeiro, 1), fim=date(ano, ultimo, calendar.monthrange(ano, ultimo)[1]),
        ref=ref_norm, titulo=titulo, subtitulo=subtitulo, meses=[_mes(ano, m) for m in range(primeiro, ultimo + 1)],
    )


def nome_arquivo(p: Periodo) -> str:
    return f"Tabimoney-{p.ref}.html"


# ---------------------------------------------------------------- máscara

_PESSOAS = ("Pix e transferências", "Transferência entre titulares", "Transferência própria")
_PALAVRAS_PIX = {"pix", "ted", "doc", "tef", "transf", "transferencia", "enviado", "enviada", "recebido", "recebida",
                 "para", "de", "da", "do", "qrcode", "qr", "code", "agendado", "-", "–", "·", "transferencia:", "cpf",
                 "cnpj", "chave", "pagamento", "pagto", "pgto", "via", "ao", "a", "•••"}


def mascarar_conta(nome: str | None) -> str:
    """'Nubank Cartão ••••7730' → 'Nubank Cartão ••30'; qualquer sequência de 3+ dígitos fica só com os 2 últimos."""
    return re.sub(r"[•*.]*\d{3,}", lambda m: "••" + re.sub(r"\D", "", m.group())[-2:], nome or "")


def _mascarar_nome(palavra: str) -> str:
    """'(faxineira)' → '(f•••a)', 'Ana' → 'A•••a', 'de' → 'd•': sempre três pontos, para não entregar o tamanho."""
    def parte(m: re.Match[str]) -> str:
        letras = m.group()
        return letras[0] + "•" if len(letras) < 3 else f"{letras[0]}•••{letras[-1]}"

    return re.sub(r"[^\W\d_]+", parte, palavra)


def mascarar_descricao(texto: str, categoria: str | None) -> str:
    """Nome de pessoa em Pix/TED e documentos viram iniciais: 'Pix enviado|Marina Souza' → 'Pix enviado · M•••a S•••a'."""
    texto = re.sub(r"\d[\d.\-/]{5,}\d", "•••", texto or "")  # CPF, CNPJ, conta
    pessoa = categoria in _PESSOAS or spending.normalize(texto).startswith("pix")
    if not pessoa:
        return texto.replace("|", " · ")
    if "|" in texto:
        prefixo, _, nome = texto.rpartition("|")
        return f"{prefixo.strip()} · " + " ".join(_mascarar_nome(p) for p in nome.split())
    palavras = texto.split()
    saida, nomes = [], False
    for palavra in palavras:
        if not nomes and spending.normalize(palavra).strip(":") in _PALAVRAS_PIX:
            saida.append(palavra)
            continue
        nomes = True
        saida.append(_mascarar_nome(palavra) if any(c.isalpha() for c in palavra) else palavra)
    return " ".join(saida)


# ---------------------------------------------------------------- contas do período

def _tipo(t: dict[str, Any]) -> str | None:
    return analytics._flow_kind(t)


def _cat(t: dict[str, Any]) -> str:
    return t["category"] or "Outros"


def _totais(transacoes: list[dict[str, Any]]) -> dict[str, Any]:
    receitas = gastos = 0
    por_categoria: dict[str, int] = defaultdict(int)
    for t in transacoes:
        kind = _tipo(t)
        if kind == "in":
            receitas += int(t["amount_cents"])
        elif kind in ("out", "refund"):
            gastos -= int(t["amount_cents"])
            por_categoria[_cat(t)] -= int(t["amount_cents"])
    return {"receitas": receitas, "gastos": gastos, "categorias": dict(por_categoria)}


def _no_periodo(transacoes: list[dict[str, Any]], p: Periodo, dias: int | None = None) -> list[dict[str, Any]]:
    """Lançamentos do período; com `dias`, só os primeiros N dias (comparação de período ainda em andamento)."""
    fim = p.fim if dias is None else min(p.fim, p.inicio + timedelta(days=dias - 1))
    a, b = p.inicio.isoformat(), fim.isoformat()
    return [t for t in transacoes if a <= t["transaction_date"][:10] <= b]


def _variacao(atual: float, base: float | None) -> float | None:
    return (atual - base) / base if base else None


# ---------------------------------------------------------------- partes do relatório

def _ritmo(gastos_tx: list[dict[str, Any]], p: Periodo, base: list[Periodo], hoje: date, mascarar: bool) -> dict[str, Any]:
    """Mês: gasto acumulado dia a dia contra a média dos meses-base, com os dias de pico anotados."""
    mes = p.meses[0]
    dias = calendar.monthrange(p.inicio.year, p.inicio.month)[1]
    ate = hoje.day if p.contem(hoje.isoformat()) else None
    atual = spending._cumulative(gastos_tx, mes, dias, ate)
    curvas = [spending._cumulative(gastos_tx, b.meses[0], dias) for b in base[:3]]
    media = [int(sum(col) / len(curvas)) for col in zip(*curvas)] if curvas else []
    por_dia: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for t in gastos_tx:
        if t["transaction_date"][:7] == mes:
            por_dia[int(t["transaction_date"][8:10])].append(t)
    diario = {d: -sum(int(t["amount_cents"]) for t in ts) for d, ts in por_dia.items()}
    positivos = sorted(v for v in diario.values() if v > 0)
    picos = []
    if positivos:
        mediana = statistics.median(positivos)
        total = sum(positivos)
        for dia_, valor in sorted(diario.items(), key=lambda item: -item[1])[:3]:
            if valor >= 2.5 * mediana and valor >= 0.12 * total:
                maior = min(por_dia[dia_], key=lambda t: t["amount_cents"])
                picos.append({"dia": dia_, "valor": valor, "motivo": _rotulo(maior, mascarar)})
    return {"dias": dias, "ate": ate, "atual": atual, "media": media, "picos": sorted(picos, key=lambda x: x["dia"]),
            "mes": mes}


def _rotulo(t: dict[str, Any], mascarar: bool) -> str:
    nome = spending.merchant(t["description"])
    return mascarar_descricao(nome, _cat(t)) if mascarar else nome


def _estabelecimentos(gastos_tx: list[dict[str, Any]], mascarar: bool) -> list[dict[str, Any]]:
    grupos: dict[str, dict[str, Any]] = {}
    for t in gastos_tx:
        if t["amount_cents"] >= 0:
            continue
        nome = spending.merchant(t["description"])
        g = grupos.setdefault(spending.normalize(nome), {"nomes": Counter(), "valor": 0, "vezes": 0, "categoria": _cat(t)})
        g["nomes"][nome] += 1
        g["valor"] -= int(t["amount_cents"])
        g["vezes"] += 1
    saida = []
    for g in grupos.values():
        nome = g["nomes"].most_common(1)[0][0]
        saida.append({"nome": mascarar_descricao(nome, g["categoria"]) if mascarar else nome, "valor": g["valor"],
                      "vezes": g["vezes"], "media": g["valor"] // g["vezes"], "categoria": g["categoria"]})
    return sorted(saida, key=lambda x: -x["valor"])


_PARCELA = re.compile(r"(?:parc(?:ela)?\.?\s*)?\(?(\d{1,2})\s*(?:/|de)\s*(\d{1,2})\)?\s*$", re.I)


def parcela(descricao: str) -> tuple[int, int] | None:
    """'Magazine Luiza 3/10' → (3, 10). Só vale de 1/2 até 48/48."""
    m = _PARCELA.search((descricao or "").strip())
    if not m:
        return None
    n, total = int(m.group(1)), int(m.group(2))
    return (n, total) if 1 <= n <= total and 2 <= total <= 48 else None


def _somar_meses(mes: str, n: int) -> str:
    ano, m = int(mes[:4]), int(mes[5:7]) + n
    ano += (m - 1) // 12
    return _mes(ano, (m - 1) % 12 + 1)


def _parcelas(transacoes: list[dict[str, Any]], p: Periodo, mascarar: bool) -> dict[str, Any]:
    """Compras parceladas no cartão que continuam depois do período: a última parcela vista projeta as próximas."""
    fim = p.fim.isoformat()
    recente = (p.fim - timedelta(days=62)).isoformat()
    ultimas: dict[tuple[str, str, int], tuple[int, dict[str, Any]]] = {}
    for t in transacoes:
        if t["account_type"] != "CREDIT" or t["amount_cents"] >= 0 or t["transaction_date"][:10] > fim:
            continue
        info = parcela(t["description"])
        if not info:
            continue
        chave = (t["account_name"], spending.normalize(spending.merchant(t["description"])), info[1])
        if chave not in ultimas or (info[0], t["transaction_date"]) > (ultimas[chave][0], ultimas[chave][1]["transaction_date"]):
            ultimas[chave] = (info[0], t)
    ultimo_mes = p.meses[-1]
    itens, por_mes = [], defaultdict(int)
    for (_conta, _nome, total), (n, t) in ultimas.items():
        if n >= total or t["transaction_date"][:10] < recente:
            continue
        valor = -int(t["amount_cents"])
        mes_visto = t["transaction_date"][:7]
        futuras = [_somar_meses(mes_visto, k) for k in range(1, total - n + 1)]
        futuras = [m for m in futuras if m > ultimo_mes]
        if not futuras:
            continue
        for m in futuras:
            por_mes[m] += valor
        itens.append({
            "nome": _rotulo(t, mascarar), "conta": mascarar_conta(t["account_name"]) if mascarar else t["account_name"],
            "valor": valor, "parcela": f"{n}/{total}", "restantes": len(futuras), "restante": valor * len(futuras),
            "termina": futuras[-1], "categoria": _cat(t),
        })
    meses = sorted(por_mes)[:12]
    maximo = max((por_mes[m] for m in meses), default=0)
    return {
        "itens": sorted(itens, key=lambda x: -x["restante"]),
        "meses": [{"mes": m, "valor": por_mes[m], "altura": por_mes[m] / maximo if maximo else 0} for m in meses],
        "total": sum(por_mes.values()), "proximo": por_mes[meses[0]] if meses else 0,
    }


def _recorrentes(transacoes: list[dict[str, Any]], p: Periodo, mascarar: bool) -> dict[str, Any]:
    """Contas e assinaturas: o mesmo estabelecimento em pelo menos 3 dos 4 meses até o fim do período, no máximo
    duas vezes por mês e com valor estável (contas de casa variam mais, como a luz)."""
    janela = [_somar_meses(p.meses[-1], -k) for k in range(3, -1, -1)]
    grupos: dict[str, dict[str, Any]] = {}
    for t in transacoes:
        mes = t["transaction_date"][:7]
        if mes not in janela or t["amount_cents"] >= 0 or _tipo(t) != "out" or parcela(t["description"]):
            continue
        nome = spending.merchant(t["description"])
        g = grupos.setdefault(spending.normalize(nome), {"nome": nome, "categoria": _cat(t), "meses": defaultdict(list)})
        g["meses"][mes].append(-int(t["amount_cents"]))
    itens = []
    for g in grupos.values():
        meses = g["meses"]
        if len(meses) < 3 or any(len(v) > 2 for v in meses.values()):
            continue
        cobrancas = [v for vs in meses.values() for v in vs]
        tolerancia = 1.6 if g["categoria"] in ("Casa", "Moradia") else 1.25
        if min(cobrancas) <= 0 or max(cobrancas) / min(cobrancas) > tolerancia:
            continue
        mensal = int(statistics.median(sum(v) for v in meses.values()))
        itens.append({
            "nome": mascarar_descricao(g["nome"], g["categoria"]) if mascarar else g["nome"], "categoria": g["categoria"],
            "mensal": mensal, "anual": mensal * 12, "assinatura": g["categoria"] == "Assinaturas",
        })
    itens.sort(key=lambda x: -x["mensal"])
    total = sum(i["mensal"] for i in itens)
    return {"itens": itens, "mensal": total, "anual": total * 12,
            "assinaturas": sum(i["mensal"] for i in itens if i["assinatura"])}


def _orcamento(casa: list[dict[str, Any]], p: Periodo, hoje: date) -> dict[str, Any] | None:
    """Metas de gasto (são da casa). Mês: o acompanhamento da tela de Orçamento. Trimestre e ano: soma dos meses
    contra o limite vezes o número de meses, e em quantos meses fechados a meta foi cumprida."""
    lista = budgets.budgets()
    if not lista:
        return None
    if p.tipo == "mes":
        em_andamento = p.contem(hoje.isoformat())
        status = budgets.status(casa, today=None if em_andamento else p.fim)
        itens = [{
            "nome": i["name"], "gasto": i["spent"], "limite": i["limit"], "pct": i["pct"], "estado": i["state"],
            "projecao": i["projected"] if em_andamento else None, "total": i["is_total"],
        } for i in status["items"]]
    else:
        meses = [m for m in p.meses if m <= hoje.strftime("%Y-%m")]
        tabela = spending.monthly_by_category(casa, meses)
        fechados = [m for m in meses if m < hoje.strftime("%Y-%m")]
        itens = []
        for b in lista:
            mensais = {m: budgets._spent(tabela, b["categories"], m) for m in meses}
            gasto = sum(mensais.values())
            limite = b["monthly_limit_cents"] * len(meses)
            estado = "estourou" if gasto > limite else "risco" if gasto >= limite * b["alert_pct"] else "ok"
            itens.append({
                "nome": b["name"], "gasto": gasto, "limite": limite, "pct": gasto / limite if limite else 0,
                "estado": estado, "projecao": None, "total": b["is_total"],
                "cumpridos": sum(1 for m in fechados if mensais[m] <= b["monthly_limit_cents"]), "fechados": len(fechados),
            })
        itens.sort(key=lambda i: ({"estourou": 0, "risco": 1, "ok": 2}[i["estado"]], -i["pct"]))
    for i in itens:
        i["barra"] = min(i["pct"], 1)
    return {"itens": itens, "ok": sum(1 for i in itens if i["estado"] == "ok"), "total": len(itens)}


def _patrimonio(book: analytics.Book, p: Periodo) -> dict[str, Any] | None:
    serie = book.series()
    fim = [x for x in serie if x["d"] <= p.fim.isoformat()]
    if not fim:
        return None
    ponto = fim[-1]
    antes = [x for x in serie if x["d"] < p.inicio.isoformat()]
    partes = [("Ações e FIIs", ponto["eq"]), ("Renda fixa", ponto["fi"]), ("Previdência", ponto["pv"]),
              ("Contas", ponto["cash"] or 0)]
    positivos = sum(v for _, v in partes if v > 0)
    return {
        "data": ponto["d"], "total": ponto["nw"], "divida": ponto["debt"] or 0,
        "partes": [{"nome": n, "valor": v, "pct": v / positivos if positivos else 0} for n, v in partes if v > 0],
        "inicio": antes[-1]["nw"] if antes else None,
        "variacao": ponto["nw"] - antes[-1]["nw"] if antes else None,
    }


def _resumo(d: dict[str, Any]) -> list[str]:
    """Três ou quatro frases que dizem o que importa no período, com as mesmas contas das seções."""
    frases = []
    gastos, base = d["gastos"], d["base"]
    if base["gastos"] and d["variacao_gastos"] is not None and abs(d["variacao_gastos"]) >= 0.03:
        sentido = "acima" if d["variacao_gastos"] > 0 else "abaixo"
        frases.append(f"Os gastos somaram {brl_whole(gastos)}, {pct(abs(d['variacao_gastos']), 0, signed=False)} "
                      f"{sentido} {base['rotulo']}.")
        diferenca = gastos - base["gastos"]
        if diferenca > 0:
            altas = [c for c in d["categorias"] if (c["delta"] or 0) > 0]
            altas.sort(key=lambda c: -c["delta"])
            nomes, soma = [], 0
            for c in altas[:2]:
                nomes.append(c["nome"])
                soma += c["delta"]
                if soma >= 0.6 * diferenca:
                    break
            if nomes:
                parte = min(soma / diferenca, 1)
                sujeito = " e ".join(nomes)
                verbo = "explica" if len(nomes) == 1 else "explicam"
                frases.append(f"{sujeito} {verbo} {pct(parte, 0, signed=False)} da diferença.")
        else:
            baixas = sorted((c for c in d["categorias"] if (c["delta"] or 0) < 0), key=lambda c: c["delta"])
            if baixas:
                frases.append(f"A maior economia veio de {baixas[0]['nome']} ({brl_whole(baixas[0]['delta'])}).")
    elif gastos:
        frases.append(f"Os gastos somaram {brl_whole(gastos)}"
                      + (f", perto {base['rotulo']}." if base["gastos"] else "."))
    if d["receitas"] > 0:
        if d["sobra"] >= 0:
            frases.append(f"Sobraram {brl_whole(d['sobra'])}, {pct(d['taxa_poupanca'], 0, signed=False)} das receitas.")
        else:
            frases.append(f"As despesas passaram as receitas em {brl_whole(-d['sobra'])}.")
    if d["orcamento"]:
        o = d["orcamento"]
        frases.append(f"{o['ok']} de {o['total']} metas de gasto {'estão' if d['em_andamento'] else 'ficaram'} dentro do limite."
                      if o["total"] > 1 else
                      f"A meta de gasto {'está' if d['em_andamento'] else 'ficou'} "
                      f"{'dentro do' if o['ok'] else 'acima do'} limite.")
    if d["parcelas"]["total"]:
        frases.append(f"Já há {brl_whole(d['parcelas']['total'])} em parcelas assumidas para os próximos meses.")
    return frases[:5]


# ---------------------------------------------------------------- montagem

def _na_demo() -> bool:
    from app import demo  # a demo usa os serviços: import aqui evita o ciclo

    return db.database_path().resolve() == demo.path().resolve()


def montar(tipo: str = "mes", ref: str | None = None, member: int | None = None, mascarar: bool = True,
           extrato: bool = True, today: date | None = None) -> dict[str, Any]:
    hoje = today or date.today()
    p = periodo(tipo, ref, hoje)
    transacoes = analytics.cash_transactions(member=member)
    book = analytics.Book(member)
    todos = transacoes + book.yield_entries()
    casa = transacoes if member is None else analytics.cash_transactions()
    if not todos:
        raise ValueError("Ainda não há lançamentos para montar um relatório. Importe um extrato ou conecte uma conta.")
    em_andamento = p.contem(hoje.isoformat())
    if p.inicio > hoje:
        raise ValueError(f"{p.titulo} ainda não começou.")
    dias = (hoje - p.inicio).days + 1 if em_andamento else None

    do_periodo = _no_periodo(todos, p)
    totais = _totais(do_periodo)
    gastos_tx = [t for t in do_periodo if _tipo(t) in ("out", "refund")]

    # base: os períodos anteriores com dados completos (no período em andamento, até o mesmo dia)
    primeiro = min(t["transaction_date"][:10] for t in todos)
    base_periodos = [b for b in (p.anterior(k) for k in range(1, BASE[tipo] + 1)) if b.inicio.isoformat() >= primeiro[:8] + "01"]
    base_totais = [_totais(_no_periodo(todos, b, dias)) for b in base_periodos]
    n = len(base_totais)
    singular, plural = NOMES[tipo]
    if n == 0:
        rotulo = ""
    elif n == 1:
        rotulo = f"do {singular} anterior" if tipo != "ano" else "do ano anterior"
    else:
        rotulo = f"da média dos {n} {plural} anteriores"
    if n and dias:
        rotulo += " (até o mesmo dia)"
    media = lambda chave: int(sum(b[chave] for b in base_totais) / n) if n else 0  # noqa: E731
    base_cat: dict[str, int] = defaultdict(int)
    for b in base_totais:
        for c, v in b["categorias"].items():
            base_cat[c] += v
    base_cat = {c: v // n for c, v in base_cat.items()} if n else {}

    icones = spending.custom_icons()
    gastos = totais["gastos"]
    categorias = []
    for nome, valor in sorted(totais["categorias"].items(), key=lambda item: -item[1]):
        if valor <= 0:
            continue
        ref_base = base_cat.get(nome) if n else None
        categorias.append({
            "nome": nome, "valor": valor, "pct": valor / gastos if gastos else 0, "icone": category_icon(nome, icones.get(nome)),
            "base": ref_base, "delta": valor - ref_base if ref_base is not None else None,
            "delta_pct": _variacao(valor, ref_base) if ref_base else None,
            "vezes": sum(1 for t in gastos_tx if _cat(t) == nome and t["amount_cents"] < 0),
        })
    maior = max([c["valor"] for c in categorias] + [c["base"] or 0 for c in categorias] + [1])
    for c in categorias:
        c["largura"] = c["valor"] / maior
        c["marca"] = (c["base"] or 0) / maior

    def linha(t: dict[str, Any]) -> dict[str, Any]:
        cat = _cat(t)
        return {
            "data": t["transaction_date"][:10], "descricao": mascarar_descricao(t["description"], cat) if mascarar else t["description"],
            "conta": mascarar_conta(t["account_name"]) if mascarar else t["account_name"], "valor": int(t["amount_cents"]),
            "categoria": cat, "icone": category_icon(cat, icones.get(cat)),
        }

    receitas_tx = sorted((t for t in do_periodo if _tipo(t) == "in"), key=lambda t: -int(t["amount_cents"]))
    investimentos_tx = [t for t in do_periodo if _cat(t) == INVESTIMENTOS and t["account_type"] == "BANK"]
    internos = [t for t in do_periodo if _tipo(t) is None and _cat(t) != INVESTIMENTOS]
    aportes = -sum(int(t["amount_cents"]) for t in investimentos_tx if t["amount_cents"] < 0)
    resgates = sum(int(t["amount_cents"]) for t in investimentos_tx if t["amount_cents"] > 0)
    rendimentos = sum(int(t["amount_cents"]) for t in receitas_tx if _cat(t) in ("Rendimentos", "Proventos"))

    sobra = totais["receitas"] - gastos
    d: dict[str, Any] = {
        "periodo": p, "em_andamento": em_andamento, "hoje": hoje.isoformat(),
        "ultimo_dado": max((t["transaction_date"][:10] for t in do_periodo), default=None),
        "titular": (household.member(member) or {}).get("name") if member else ("Casa" if household.is_shared() else None),
        "contas": sorted({mascarar_conta(t["account_name"]) if mascarar else t["account_name"] for t in do_periodo}),
        "mascarado": mascarar, "versao": __version__, "demo": _na_demo(),
        "receitas": totais["receitas"], "gastos": gastos, "sobra": sobra,
        "taxa_poupanca": sobra / totais["receitas"] if totais["receitas"] > 0 else None,
        "investido": aportes - resgates, "aportes": aportes, "resgates": resgates, "rendimentos": rendimentos,
        "internos": {"valor": -sum(int(t["amount_cents"]) for t in internos if t["amount_cents"] < 0), "vezes": len(internos)},
        "base": {"rotulo": rotulo, "n": n, "receitas": media("receitas"), "gastos": media("gastos"),
                 "sobra": media("receitas") - media("gastos")},
        "categorias": categorias,
        "maiores": [linha(t) for t in sorted((t for t in gastos_tx if t["amount_cents"] < 0), key=lambda t: t["amount_cents"])[:10]],
        "estabelecimentos": _estabelecimentos(gastos_tx, mascarar)[:8],
        "recorrentes": _recorrentes(todos, p, mascarar),
        "parcelas": _parcelas(todos, p, mascarar),
        "orcamento": _orcamento(casa, p, hoje),
        "receitas_lista": [linha(t) for t in receitas_tx],
        "aportes_lista": [linha(t) for t in sorted(investimentos_tx, key=lambda t: t["transaction_date"])],
        "patrimonio": _patrimonio(book, p),
    }
    d["variacao_gastos"] = _variacao(gastos, d["base"]["gastos"]) if n else None
    d["variacao_receitas"] = _variacao(d["receitas"], d["base"]["receitas"]) if n else None
    d["ritmo"] = _ritmo(gastos_tx + [t for b in base_periodos for t in _no_periodo(todos, b) if _tipo(t) in ("out", "refund")],
                        p, base_periodos, hoje, mascarar) if tipo == "mes" else None
    if tipo != "mes":
        mensal = []
        for m in p.meses:
            if m > hoje.strftime("%Y-%m"):
                break
            t_m = _totais([t for t in do_periodo if t["transaction_date"][:7] == m])
            mensal.append({"mes": m, "receitas": t_m["receitas"], "gastos": t_m["gastos"]})
        d["mensal"] = mensal
    d["resumo"] = _resumo(d)
    if extrato:
        grupos: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for t in sorted(do_periodo, key=lambda t: (t["transaction_date"], t["id"])):
            kind = _tipo(t)
            grupo = _cat(t) if kind in ("out", "refund") else "Receitas" if kind == "in" else "Movimentações internas"
            grupos[grupo].append(linha(t))
        ordem = [c["nome"] for c in categorias] + ["Receitas", "Movimentações internas"]
        d["extrato"] = [{"nome": g, "linhas": grupos[g], "total": sum(x["valor"] for x in grupos[g]),
                         "icone": category_icon(g, icones.get(g)) if g in totais["categorias"] else
                         ("banknote" if g == "Receitas" else "arrow-left-right")}
                        for g in ordem if grupos.get(g)]
        d["extrato_total"] = len(do_periodo)
    else:
        d["extrato"] = None
    return d


# ---------------------------------------------------------------- HTML

def _ambiente() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters.update(brl=brl, brl_whole=brl_whole, brl_compact=brl_compact, pct=pct, date_br=date_br,
                       mes_curto=lambda m: f"{MESES_CURTOS[int(m[5:7]) - 1]}/{m[2:4]}",
                       mes_longo=lambda m: f"{MESES[int(m[5:7]) - 1]} de {m[:4]}")
    env.globals["grafico_ritmo"] = grafico_ritmo
    env.globals["grafico_mensal"] = grafico_mensal
    return env


ICONES_FIXOS = {"banknote", "arrow-up-right", "arrow-left-right", "calendar", "credit-card", "eye", "eye-off",
                "file-text", "repeat", "search", "piggy-bank", "trending-up", "trending-down", "wallet", "landmark",
                "sun", "moon", "list-filter", "chevron-down", "target", "receipt", "lock", "calendar-clock", "sparkles", "circle-check",
                "triangle-alert", "circle-alert"}


def renderizar(d: dict[str, Any], nonce: str | None = None) -> str:
    nonce = nonce or secrets.token_urlsafe(16)
    linhas = d["maiores"] + d["receitas_lista"] + d["aportes_lista"]
    icones = (set(ICONES_FIXOS) | {c["icone"] for c in d["categorias"]} | {t["icone"] for t in linhas}
              | {g["icone"] for g in d["extrato"] or []})
    return _ambiente().get_template("relatorio_export.html").render(
        d=d, p=d["periodo"], nonce=nonce, fontes=embutir.font_faces(), sprite=embutir.icon_sprite(icones),
        mascote=embutir.brand_image("mascote-128.png"), favicon=embutir.brand_image("favicon-32.png"),
    )


def csp(nonce: str) -> str:
    """CSP do relatório aberto pelo app: nada de fora; estilo e script só os embutidos (com nonce)."""
    return (f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; img-src data:; font-src data:; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


# ---------------------------------------------------------------- gráficos (SVG no servidor: abre offline e imprime)

def _escala(maximo: int) -> tuple[int, list[int]]:
    """Topo 'redondo' do eixo e 4 marcas."""
    if maximo <= 0:
        return 100, [0, 25, 50, 75, 100]
    bruto = maximo / 4
    potencia = 10 ** (len(str(int(bruto))) - 1)
    passo = next(m * potencia for m in (1, 2, 2.5, 5, 10) if m * potencia >= bruto)
    passo = int(passo)
    return passo * 4, [passo * i for i in range(5)]


def _rotulo_eixo(cents: int) -> str:
    """'R$ 8 mil', 'R$ 2,5 mil', 'R$ 750': o eixo só precisa da ordem de grandeza."""
    reais = cents / 100
    if reais >= 1000:
        return "R$ " + f"{reais / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " mil"
    return f"R$ {reais:.0f}"


def _curto(texto: str, limite: int = 24) -> str:
    return texto if len(texto) <= limite else texto[:limite - 1].rstrip() + "…"


def _eixo_y(ticks: list[int], topo: int, x0: int, x1: int, y0: int, altura: int) -> list[str]:
    partes = []
    for v in ticks:
        y = y0 + altura - altura * v / topo
        partes.append(f'<line class="grid" x1="{x0}" x2="{x1}" y1="{y:.1f}" y2="{y:.1f}"/>')
        partes.append(f'<text class="tick" x="{x0 - 8}" y="{y + 4:.1f}" text-anchor="end">{_rotulo_eixo(v)}</text>')
    return partes


def grafico_ritmo(r: dict[str, Any]) -> Markup:
    """Acumulado do mês (linha cheia) contra a média dos meses-base (tracejada), com os picos anotados."""
    w, h, esq, dir_, topo_, base_ = 720, 260, 64, 96, 18, 30
    largura, altura = w - esq - dir_, h - topo_ - base_
    atual = [v for v in r["atual"] if v is not None]
    maximo = max(atual + [v for v in r["media"]] + [1])
    topo, ticks = _escala(maximo)
    x = lambda dia: esq + largura * (dia - 1) / max(r["dias"] - 1, 1)  # noqa: E731
    y = lambda v: topo_ + altura - altura * v / topo  # noqa: E731
    partes = _eixo_y(ticks, topo, esq, w - dir_, topo_, altura)
    for dia in (1, 8, 15, 22, r["dias"]):
        partes.append(f'<text class="tick" x="{x(dia):.1f}" y="{h - 8}" text-anchor="middle">{dia:02d}/{r["mes"][5:7]}</text>')
    if r["media"]:
        pts = " ".join(f"{x(i + 1):.1f},{y(v):.1f}" for i, v in enumerate(r["media"]))
        partes.append(f'<polyline class="l-media" points="{pts}"/>')
        partes.append(f'<text class="direct muted" x="{x(r["dias"]) + 8:.1f}" y="{y(r["media"][-1]) + 4:.1f}">Média</text>')
    if atual:
        pts = " ".join(f"{x(i + 1):.1f},{y(v):.1f}" for i, v in enumerate(atual))
        partes.append(f'<polyline class="l-atual" points="{pts}"/>')
        ultimo = len(atual)
        partes.append(f'<circle class="dot" cx="{x(ultimo):.1f}" cy="{y(atual[-1]):.1f}" r="4.5"/>')
        rotulo_y = y(atual[-1]) + 4
        if r["media"] and ultimo == r["dias"] and abs(y(r["media"][-1]) - y(atual[-1])) < 14:
            rotulo_y += -12 if atual[-1] >= r["media"][-1] else 12
        partes.append(f'<text class="direct" x="{x(ultimo) + 8:.1f}" y="{rotulo_y:.1f}">{"Este mês" if ultimo == r["dias"] else "Até hoje"}</text>')
    for pico in r["picos"]:
        if pico["dia"] - 1 < len(atual):
            cx, cy = x(pico["dia"]), y(atual[pico["dia"] - 1])
            partes.append(f'<circle class="pico" cx="{cx:.1f}" cy="{cy:.1f}" r="4"/>')
            texto = Markup.escape(_curto(pico["motivo"]))
            anchor = "end" if cx > esq + largura * 0.7 else "start"
            dx = -8 if anchor == "end" else 8
            partes.append(f'<text class="nota" x="{cx + dx:.1f}" y="{cy - 10:.1f}" text-anchor="{anchor}">{texto}</text>')
    # camada de hover: uma faixa por dia
    passo = largura / max(r["dias"] - 1, 1)
    for i in range(r["dias"]):
        dica = [f"{i + 1:02d}/{r['mes'][5:7]}"]
        if i < len(atual):
            dica.append(f"Acumulado: {brl(atual[i])}")
        if r["media"]:
            dica.append(f"Média: {brl(r['media'][i])}")
        partes.append(f'<rect class="hit" x="{x(i + 1) - passo / 2:.1f}" y="{topo_}" width="{passo:.1f}" height="{altura}" '
                      f'data-tip="{Markup.escape(" · ".join(dica))}" data-x="{x(i + 1):.1f}"/>')
    partes.append(f'<line class="cross" x1="0" x2="0" y1="{topo_}" y2="{topo_ + altura}"/>')
    return Markup(f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="Gasto acumulado no mês contra a média">'
                  + "".join(partes) + "</svg>")


def grafico_mensal(linhas: list[dict[str, Any]]) -> Markup:
    """Trimestre e ano: receitas e gastos lado a lado, mês a mês."""
    w, h, esq, topo_, base_ = 720, 240, 64, 14, 30
    largura, altura = w - esq - 12, h - topo_ - base_
    maximo = max([r["receitas"] for r in linhas] + [r["gastos"] for r in linhas] + [1])
    topo, ticks = _escala(maximo)
    partes = _eixo_y(ticks, topo, esq, w - 12, topo_, altura)
    faixa = largura / max(len(linhas), 1)
    barra = min(28.0, (faixa - 14) / 2)
    for i, r in enumerate(linhas):
        cx = esq + faixa * i + faixa / 2
        for j, (classe, valor) in enumerate((("b-in", r["receitas"]), ("b-out", r["gastos"]))):
            alto = max(altura * max(valor, 0) / topo, 0)
            bx = cx - barra - 1 + j * (barra + 2)
            by = topo_ + altura - alto
            raio = min(4, alto / 2)
            partes.append(f'<path class="{classe}" d="M{bx:.1f},{topo_ + altura}V{by + raio:.1f}q0,-{raio:.1f} {raio:.1f},-{raio:.1f}'
                          f'h{barra - 2 * raio:.1f}q{raio:.1f},0 {raio:.1f},{raio:.1f}V{topo_ + altura}Z"/>')
        partes.append(f'<text class="tick" x="{cx:.1f}" y="{h - 8}" text-anchor="middle">'
                      f'{MESES_CURTOS[int(r["mes"][5:7]) - 1]}</text>')
        dica = f'{MESES[int(r["mes"][5:7]) - 1].capitalize()} · Receitas {brl(r["receitas"])} · Gastos {brl(r["gastos"])}'
        partes.append(f'<rect class="hit" x="{esq + faixa * i:.1f}" y="{topo_}" width="{faixa:.1f}" height="{altura}" '
                      f'data-tip="{Markup.escape(dica)}"/>')
    return Markup(f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-label="Receitas e gastos por mês">'
                  + "".join(partes) + "</svg>")
