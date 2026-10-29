"""Estimador do imposto do ano (spec, Parte B): perfil fiscal, deduções, previdência e o ajuste nos dois modelos.

Ordem do cálculo (Lei 9.250/1995 e Lei 15.270/2025; Perguntas e Respostas IRPF 2026):
- mês a mês, por fonte: INSS (tabela do empregado ou 11% do pró-labore, até o teto) e IRRF (deduções legais ou o
  desconto simplificado mensal; tabela; redução sobre o bruto). Outros rendimentos pagam carnê-leão;
- 13º: tributação exclusiva na fonte, fora do ajuste e da base do PGBL;
- ajuste: completo (INSS, dependentes, saúde, educação até o limite por pessoa, pensão, PGBL até 12%) contra
  simplificado (20%, com limite); tabela anual; redução anual sobre os rendimentos tributáveis; doações até 6%;
- PGBL: só o que o participante pagou conta (o aporte da empresa não); a economia de completar o limite é medida
  contra o MELHOR modelo sem o aporte;
- dividendos acima de R$ 50 mil no mês da mesma empresa: 10% retidos, que voltam no ajuste se a renda total ficar
  até R$ 600 mil; acima disso, tributação mínima (IRPFM, sem o redutor do art. 16-B: é um teto).
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from app.db import rows, transaction
from app.services import analytics, household
from app.services.ir import parametros, renda_variavel
from app.services.ir.parametros import centavos, imposto as imposto_tabela

D = Decimal
TIPOS_FONTE = {"clt": "Salário (CLT)", "pro_labore": "Pró-labore (PJ)", "outro": "Outro rendimento tributável"}
TIPOS_DEDUCAO = {"saude": "Saúde", "educacao": "Educação", "pensao": "Pensão alimentícia judicial", "doacao": "Doação incentivada"}
SUBTIPOS_SAUDE = ("Médico", "Dentista", "Psicólogo", "Fisioterapeuta", "Fonoaudiólogo", "Terapeuta ocupacional",
                  "Hospital, clínica ou laboratório", "Plano de saúde", "Outro profissional de saúde")
REGIMES_PJ = {"simples_fator_r": "Simples (atividade com fator R)", "simples_iii": "Simples, Anexo III",
              "simples_v": "Simples, Anexo V", "outro": "Outro regime (informo o lucro)"}
PARENTESCOS = ("filho", "cônjuge", "companheiro", "enteado", "pai/mãe", "outro")
CATEGORIAS_SUGERIDAS = {"Saúde": "saude", "Educação": "educacao"}
# Não dedutíveis comuns (pergunta 392 e capítulo de deduções): ficam fora mesmo na categoria Saúde ou Educação.
NAO_DEDUTIVEIS = (
    (("farmacia", "drogaria", "droga raia", "drogasil", "pague menos", "panvel", "drogao", "farma"),
     "Farmácia não é dedutível (só remédio na conta do hospital)."),
    (("academia", "smart fit", "smartfit", "gympass", "wellhub", "bluefit", "selfit", "bodytech"), "Academia não é dedutível."),
    (("idioma", "ingles", "cultura inglesa", "wizard", "fisk", "cursinho", "udemy", "alura", "duolingo"),
     "Curso livre (idiomas, cursinho, online) não é dedutível."),
    (("papelaria", "livraria", "kalunga", "material escolar", "uniforme"), "Material e uniforme escolar não são dedutíveis."),
)
PREVIDENCIA_DESCRICOES = ("previd", "pgbl", "vgbl", "vida e prev", "brasilprev", "icatu", "prev ")
# Simples Nacional (LC 123/2006): (RBT12 até, alíquota nominal, parcela a deduzir em centavos)
SIMPLES = {
    "III": ((18_000_000, D("0.06"), 0), (36_000_000, D("0.112"), 936_000), (72_000_000, D("0.135"), 1_764_000),
            (180_000_000, D("0.16"), 3_564_000), (360_000_000, D("0.21"), 12_564_000), (480_000_000, D("0.33"), 64_800_000)),
    "V": ((18_000_000, D("0.155"), 0), (36_000_000, D("0.18"), 450_000), (72_000_000, D("0.195"), 990_000),
          (180_000_000, D("0.205"), 1_710_000), (360_000_000, D("0.23"), 6_210_000), (480_000_000, D("0.305"), 54_000_000)),
}
FATOR_R = D("0.28")


def _membro(member: int | None) -> int:
    return member if member is not None else household.PRIMARY_ID


def _norm(text: str | None) -> str:
    raw = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", raw)


def _doc(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return None
    if len(digits) not in (11, 14):
        raise ValueError("CPF tem 11 dígitos e CNPJ tem 14.")
    return digits


def formatar_doc(digits: str | None) -> str:
    if not digits:
        return ""
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    return digits


# ---------------------------------------------------------------- perfil: fontes e dependentes

def fontes(member: int | None, ano: int) -> list[dict[str, Any]]:
    return [dict(r) for r in rows("SELECT * FROM ir_fonte WHERE member_id = ? AND year = ? ORDER BY id", (_membro(member), ano))]


def salvar_fonte(member: int | None, ano: int, dados: dict[str, Any], fonte_id: int | None = None,
                 autor: str = "usuario") -> dict[str, Any]:
    """Cria ou corrige uma fonte de renda. Valores em centavos."""
    kind = dados.get("kind") or "clt"
    if kind not in TIPOS_FONTE:
        raise ValueError(f"Tipo de renda inválido: {kind}. Use {', '.join(TIPOS_FONTE)}.")
    payer = (dados.get("payer") or "").strip()[:120]
    if not payer:
        raise ValueError("Informe quem paga (empregador, sua empresa ou a fonte).")
    gross = int(dados.get("gross_monthly_cents") or 0)
    if gross <= 0:
        raise ValueError("Informe o valor bruto mensal.")
    first, last = int(dados.get("first_month") or 1), int(dados.get("last_month") or 12)
    if not (1 <= first <= last <= 12):
        raise ValueError("Meses de início e fim devem estar entre 1 e 12, nessa ordem.")
    vacation = dados.get("vacation_month")
    vacation = int(vacation) if vacation not in (None, "", 0, "0") else None
    regime = dados.get("pj_regime") or None
    if regime and regime not in REGIMES_PJ:
        raise ValueError("Regime da empresa inválido.")
    values = (
        kind, payer, _doc(dados.get("payer_doc")), gross, first, last,
        1 if dados.get("thirteenth", kind == "clt") else 0, vacation if kind == "clt" else None,
        _opt_int(dados.get("inss_monthly_cents")), _opt_int(dados.get("irrf_year_cents")),
        int(dados.get("payroll_deductions_monthly_cents") or 0),
        _opt_int(dados.get("pj_revenue_monthly_cents")) if kind == "pro_labore" else None,
        regime if kind == "pro_labore" else None,
        _opt_int(dados.get("pj_profit_monthly_cents")) if kind == "pro_labore" else None,
    )
    member = _membro(member)
    with transaction() as con:
        if fonte_id:
            found = con.execute("SELECT id FROM ir_fonte WHERE id = ? AND member_id = ?", (fonte_id, member)).fetchone()
            if not found:
                raise ValueError("Fonte de renda não encontrada.")
            con.execute(
                "UPDATE ir_fonte SET kind=?, payer=?, payer_doc=?, gross_monthly_cents=?, first_month=?, last_month=?, "
                "thirteenth=?, vacation_month=?, inss_monthly_cents=?, irrf_year_cents=?, payroll_deductions_monthly_cents=?, "
                "pj_revenue_monthly_cents=?, pj_regime=?, pj_profit_monthly_cents=?, author=? WHERE id = ?",
                (*values, autor, fonte_id))
            new_id = fonte_id
        else:
            cur = con.execute(
                "INSERT INTO ir_fonte(member_id, year, kind, payer, payer_doc, gross_monthly_cents, first_month, last_month, "
                "thirteenth, vacation_month, inss_monthly_cents, irrf_year_cents, payroll_deductions_monthly_cents, "
                "pj_revenue_monthly_cents, pj_regime, pj_profit_monthly_cents, author) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (member, ano, *values, autor))
            new_id = int(cur.lastrowid)
    return next(f for f in fontes(member, ano) if f["id"] == new_id)


def _opt_int(value: Any) -> int | None:
    return None if value in (None, "") else int(value)


def remover_fonte(member: int | None, fonte_id: int) -> None:
    with transaction() as con:
        con.execute("DELETE FROM ir_fonte WHERE id = ? AND member_id = ?", (fonte_id, _membro(member)))


def copiar_perfil(member: int | None, de: int, para_ano: int) -> int:
    """Copia fontes e dependentes de um ano para o seguinte (o usuário corrige o que mudou)."""
    member = _membro(member)
    with transaction() as con:
        if con.execute("SELECT 1 FROM ir_fonte WHERE member_id = ? AND year = ?", (member, para_ano)).fetchone():
            raise ValueError(f"{para_ano} já tem fontes de renda.")
        n = con.execute(
            "INSERT INTO ir_fonte(member_id, year, kind, payer, payer_doc, gross_monthly_cents, first_month, last_month, "
            "thirteenth, vacation_month, payroll_deductions_monthly_cents, pj_revenue_monthly_cents, pj_regime, "
            "pj_profit_monthly_cents, author) SELECT member_id, ?, kind, payer, payer_doc, gross_monthly_cents, 1, 12, "
            "thirteenth, vacation_month, payroll_deductions_monthly_cents, pj_revenue_monthly_cents, pj_regime, "
            "pj_profit_monthly_cents, author FROM ir_fonte WHERE member_id = ? AND year = ?", (para_ano, member, de)).rowcount
        con.execute("INSERT INTO ir_dependente(member_id, year, name, kinship, birth_year) SELECT member_id, ?, name, "
                    "kinship, birth_year FROM ir_dependente WHERE member_id = ? AND year = ?", (para_ano, member, de))
    return n


def dependentes(member: int | None, ano: int) -> list[dict[str, Any]]:
    return [dict(r) for r in rows("SELECT * FROM ir_dependente WHERE member_id = ? AND year = ? ORDER BY name",
                                  (_membro(member), ano))]


def salvar_dependente(member: int | None, ano: int, nome: str, parentesco: str = "filho",
                      nascimento: int | None = None) -> dict[str, Any]:
    nome = (nome or "").strip()[:80]
    if not nome:
        raise ValueError("Informe o nome do dependente.")
    if parentesco not in PARENTESCOS:
        raise ValueError(f"Parentesco inválido. Use {', '.join(PARENTESCOS)}.")
    with transaction() as con:
        cur = con.execute("INSERT INTO ir_dependente(member_id, year, name, kinship, birth_year) VALUES (?, ?, ?, ?, ?)",
                          (_membro(member), ano, nome, parentesco, nascimento))
    return {"id": int(cur.lastrowid), "name": nome, "kinship": parentesco, "birth_year": nascimento}


def remover_dependente(member: int | None, dependente_id: int) -> None:
    with transaction() as con:
        con.execute("DELETE FROM ir_dependente WHERE id = ? AND member_id = ?", (dependente_id, _membro(member)))


def perfil(member: int | None, ano: int) -> dict[str, Any]:
    member = _membro(member)
    found = rows("SELECT * FROM ir_perfil WHERE member_id = ? AND year = ?", (member, ano))
    return dict(found[0]) if found else {"member_id": member, "year": ano, "contribui_previdencia_oficial": None, "note": None}


def definir_perfil(member: int | None, ano: int, contribui_previdencia: bool | None) -> dict[str, Any]:
    with transaction() as con:
        con.execute(
            "INSERT INTO ir_perfil(member_id, year, contribui_previdencia_oficial) VALUES (?, ?, ?) "
            "ON CONFLICT(member_id, year) DO UPDATE SET contribui_previdencia_oficial = excluded.contribui_previdencia_oficial, "
            "updated_at = CURRENT_TIMESTAMP",
            (_membro(member), ano, None if contribui_previdencia is None else int(contribui_previdencia)))
    return perfil(member, ano)


# ---------------------------------------------------------------- deduções

def categorias_deducao() -> dict[str, str]:
    return {r["category"]: r["kind"] for r in rows("SELECT category, kind FROM ir_categoria_deducao")}


def definir_categoria(categoria: str, kind: str | None, autor: str = "usuario") -> dict[str, Any]:
    categoria = (categoria or "").strip()
    if not categoria:
        raise ValueError("Informe a categoria.")
    if kind is not None and kind not in TIPOS_DEDUCAO:
        raise ValueError(f"Tipo de dedução inválido. Use {', '.join(TIPOS_DEDUCAO)}.")
    with transaction() as con:
        if kind is None:
            con.execute("DELETE FROM ir_categoria_deducao WHERE category = ?", (categoria,))
        else:
            con.execute("INSERT INTO ir_categoria_deducao(category, kind, author) VALUES (?, ?, ?) "
                        "ON CONFLICT(category) DO UPDATE SET kind = excluded.kind, author = excluded.author",
                        (categoria, kind, autor))
    return {"categoria": categoria, "tipo": kind}


def _beneficiario(member: int, ano: int, value: str | None) -> str:
    value = (value or "titular").strip()
    if value == "titular":
        return value
    if value.startswith("dep:") and value[4:].isdigit():
        if any(d["id"] == int(value[4:]) for d in dependentes(member, ano)):
            return value
    raise ValueError("Beneficiário deve ser 'titular' ou um dependente cadastrado no ano (dep:<id>).")


def marcar_lancamentos(ids: list[int], kind: str, beneficiario: str = "titular", prestador: str | None = None,
                       documento: str | None = None, subtipo: str | None = None, reembolso_cents: int = 0,
                       autor: str = "usuario") -> dict[str, Any]:
    """Marca lançamentos como dedução (ou 'nenhuma' para tirar). Manda na categoria."""
    if kind not in TIPOS_DEDUCAO and kind != "nenhuma":
        raise ValueError(f"Tipo inválido. Use {', '.join(TIPOS_DEDUCAO)} ou nenhuma.")
    if not ids:
        raise ValueError("Informe ao menos um lançamento.")
    doc = _doc(documento)
    found = {int(r["id"]): r for r in rows(
        "SELECT t.id, t.transaction_date, COALESCE(a.member_id, 1) AS member_id FROM cash_transaction t "
        f"JOIN financial_account a ON a.id = t.account_id WHERE t.id IN ({','.join('?' * len(ids))})", tuple(ids))}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ValueError(f"Lançamento não encontrado: {', '.join(map(str, missing))}.")
    with transaction() as con:
        for i in ids:
            r = found[i]
            ben = "titular" if kind == "nenhuma" else _beneficiario(int(r["member_id"]), int(r["transaction_date"][:4]), beneficiario)
            con.execute(
                "INSERT INTO ir_lancamento_deducao(transaction_id, kind, beneficiary, provider_name, provider_doc, subkind, "
                "reimbursed_cents, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(transaction_id) DO UPDATE SET "
                "kind = excluded.kind, beneficiary = excluded.beneficiary, "
                "provider_name = COALESCE(excluded.provider_name, ir_lancamento_deducao.provider_name), "
                "provider_doc = COALESCE(excluded.provider_doc, ir_lancamento_deducao.provider_doc), "
                "subkind = COALESCE(excluded.subkind, ir_lancamento_deducao.subkind), "
                "reimbursed_cents = excluded.reimbursed_cents, author = excluded.author, updated_at = CURRENT_TIMESTAMP",
                (i, kind, ben, (prestador or "").strip()[:120] or None, doc, subtipo or None, int(reembolso_cents or 0), autor))
    return {"lancamentos": ids, "tipo": kind}


def desmarcar_lancamentos(ids: list[int]) -> dict[str, Any]:
    """Volta o lançamento para a regra da categoria."""
    with transaction() as con:
        con.execute(f"DELETE FROM ir_lancamento_deducao WHERE transaction_id IN ({','.join('?' * len(ids))})", tuple(ids))
    return {"lancamentos": ids, "tipo": "pela categoria"}


def adicionar_manual(member: int | None, dados: dict[str, Any], autor: str = "usuario") -> dict[str, Any]:
    member = _membro(member)
    kind = dados.get("kind")
    if kind not in TIPOS_DEDUCAO:
        raise ValueError(f"Tipo de dedução inválido. Use {', '.join(TIPOS_DEDUCAO)}.")
    paid_on = str(dados.get("paid_on") or "")
    try:
        date.fromisoformat(paid_on)
    except ValueError as exc:
        raise ValueError("Informe a data do pagamento (AAAA-MM-DD).") from exc
    amount = int(dados.get("amount_cents") or 0)
    if amount <= 0:
        raise ValueError("Informe o valor pago.")
    provider = (dados.get("provider_name") or "").strip()[:120]
    if not provider:
        raise ValueError("Informe o nome de quem prestou o serviço.")
    ben = _beneficiario(member, int(paid_on[:4]), dados.get("beneficiary"))
    with transaction() as con:
        cur = con.execute(
            "INSERT INTO ir_deducao_manual(member_id, paid_on, kind, beneficiary, provider_name, provider_doc, subkind, "
            "amount_cents, reimbursed_cents, note, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (member, paid_on, kind, ben, provider, _doc(dados.get("provider_doc")), dados.get("subkind") or None, amount,
             int(dados.get("reimbursed_cents") or 0), (dados.get("note") or "").strip()[:300] or None, autor))
    return {"id": int(cur.lastrowid), "tipo": kind, "valor": amount / 100}


def remover_manual(member: int | None, deducao_id: int) -> None:
    with transaction() as con:
        con.execute("UPDATE ir_deducao_manual SET deleted_at = CURRENT_TIMESTAMP WHERE id = ? AND member_id = ?",
                    (deducao_id, _membro(member)))


def _aviso_nao_dedutivel(texto: str) -> str | None:
    t = _norm(texto)
    for palavras, aviso in NAO_DEDUTIVEIS:
        if any(p in t for p in palavras):
            return aviso
    return None


def deducoes(member: int | None, ano: int) -> dict[str, Any]:
    """Despesas dedutíveis do ano: pela categoria, pelo lançamento e as manuais, com o que falta em cada uma."""
    member = _membro(member)
    por_categoria = categorias_deducao()
    marcas = {int(r["transaction_id"]): dict(r) for r in rows("SELECT * FROM ir_lancamento_deducao")}
    deps = {f"dep:{d['id']}": d["name"] for d in dependentes(member, ano)}
    itens: list[dict[str, Any]] = []
    sugestoes: dict[str, dict[str, Any]] = {}
    for t in analytics.cash_transactions(member=member):
        if not t["transaction_date"].startswith(str(ano)) or t["amount_cents"] >= 0 or t.get("status") == "PENDING":
            continue
        marca = marcas.get(int(t["id"]))
        categoria = t["category"]
        if marca:
            kind, origem = marca["kind"], "lancamento"
        elif categoria in por_categoria:
            kind, origem = por_categoria[categoria], "categoria"
        else:
            if categoria in CATEGORIAS_SUGERIDAS:
                s = sugestoes.setdefault(categoria, {"categoria": categoria, "tipo": CATEGORIAS_SUGERIDAS[categoria],
                                                     "lancamentos": 0, "total": 0})
                s["lancamentos"] += 1
                s["total"] += -t["amount_cents"]
            continue
        if kind == "nenhuma":
            continue
        valor = -int(t["amount_cents"])
        aviso = None if marca else _aviso_nao_dedutivel(t["description"])
        reembolso = int(marca["reimbursed_cents"]) if marca else 0
        itens.append(_item(
            "lancamento", int(t["id"]), t["transaction_date"], t["description"], kind,
            (marca or {}).get("beneficiary") or "titular", (marca or {}).get("provider_name") or t["description"],
            (marca or {}).get("provider_doc"), (marca or {}).get("subkind"), valor, reembolso, deps,
            origem=origem, aviso=aviso, categoria=categoria))
    for r in rows("SELECT * FROM ir_deducao_manual WHERE member_id = ? AND deleted_at IS NULL AND paid_on LIKE ?",
                  (member, f"{ano}-%")):
        itens.append(_item("manual", int(r["id"]), r["paid_on"], r["provider_name"], r["kind"], r["beneficiary"],
                           r["provider_name"], r["provider_doc"], r["subkind"], int(r["amount_cents"]),
                           int(r["reimbursed_cents"]), deps, origem="manual", nota=r["note"]))
    itens.sort(key=lambda i: (i["data"], i["id"]))
    return {"itens": itens, "sugestoes": list(sugestoes.values()), "categorias": por_categoria}


def por_prestador(itens: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Agrupa as despesas como a ficha Pagamentos Efetuados pede: tipo, prestador e beneficiário. Separa o que o
    app tirou por não ser dedutível (farmácia, academia...)."""
    grupos: dict[tuple[str, str, str], dict[str, Any]] = {}
    fora: dict[str, dict[str, Any]] = {}
    for i in itens:
        if i["aviso"]:
            g = fora.setdefault(i["prestador"], {"prestador": i["prestador"], "aviso": i["aviso"], "valor": 0, "itens": []})
            g["valor"] += i["valor"]
            g["itens"].append(i)
            continue
        chave = (i["tipo"], i["documento"] or _norm(i["prestador"]), i["beneficiario"])
        g = grupos.setdefault(chave, {"tipo": i["tipo"], "tipo_nome": i["tipo_nome"], "prestador": i["prestador"],
                                      "documento_fmt": i["documento_fmt"], "subtipo": i["subtipo"],
                                      "beneficiario_nome": i["beneficiario_nome"], "valor": 0, "reembolso": 0,
                                      "conta": 0, "faltas": [], "itens": []})
        g["valor"] += i["valor"]
        g["reembolso"] += i["reembolso"]
        g["conta"] += i["conta"]
        g["documento_fmt"] = g["documento_fmt"] or i["documento_fmt"]
        g["itens"].append(i)
    for g in grupos.values():
        g["faltas"] = sorted({f for i in g["itens"] for f in i["faltas"]} if not g["documento_fmt"] else
                             {f for i in g["itens"] for f in i["faltas"] if "CPF ou CNPJ" not in f})
    ordem = sorted(grupos.values(), key=lambda g: (list(TIPOS_DEDUCAO).index(g["tipo"]), -g["conta"]))
    return {"grupos": ordem, "fora": sorted(fora.values(), key=lambda g: -g["valor"])}


def _item(fonte: str, item_id: int, dia: str, descricao: str, kind: str, beneficiario: str, prestador: str,
          documento: str | None, subtipo: str | None, valor: int, reembolso: int, deps: dict[str, str], *,
          origem: str, aviso: str | None = None, categoria: str | None = None, nota: str | None = None) -> dict[str, Any]:
    conta = 0 if aviso else max(0, valor - reembolso)
    faltas = []
    if aviso:
        faltas.append(aviso + " Se não for o caso, marque o lançamento.")
    elif kind in {"saude", "educacao", "pensao"} and not documento:
        faltas.append("Falta o CPF ou CNPJ de quem prestou o serviço (pedido na ficha Pagamentos Efetuados).")
    if kind == "doacao":
        faltas.append("Só doação a fundos e projetos incentivados (ECA, Idoso, cultura, esporte), com recibo.")
    return {"fonte": fonte, "id": item_id, "data": dia, "descricao": descricao, "tipo": kind,
            "tipo_nome": TIPOS_DEDUCAO.get(kind, kind), "beneficiario": beneficiario,
            "beneficiario_nome": "Titular" if beneficiario == "titular" else deps.get(beneficiario, "Dependente removido"),
            "prestador": prestador, "documento": documento, "documento_fmt": formatar_doc(documento), "subtipo": subtipo,
            "valor": valor, "reembolso": reembolso, "conta": conta, "origem": origem, "aviso": aviso,
            "categoria": categoria, "nota": nota, "faltas": faltas}


# ---------------------------------------------------------------- previdência

def planos() -> list[dict[str, Any]]:
    """Planos de previdência lançados (último extrato de cada), com o titular da conta."""
    return [dict(r) for r in rows(
        "SELECT f.product_key, f.name, f.issuer, f.indexer AS plan_type, a.institution, COALESCE(a.member_id, 1) AS member_id "
        "FROM fixed_income_snapshot f JOIN financial_account a ON a.id = f.account_id "
        "WHERE f.product_type = 'Previdência' AND f.id = (SELECT g.id FROM fixed_income_snapshot g "
        "WHERE g.product_key = f.product_key ORDER BY g.as_of_date DESC, g.id DESC LIMIT 1) ORDER BY f.name")]


def aportes(member: int | None, ano: int | None = None) -> list[dict[str, Any]]:
    """Aportes dos planos do titular (None = todos), do ano ou de sempre."""
    by_key = {p["product_key"]: p for p in planos()}
    out = []
    for r in rows("SELECT * FROM previdencia_aporte WHERE deleted_at IS NULL"
                  + (" AND paid_on LIKE ?" if ano else "") + " ORDER BY paid_on, id", (f"{ano}-%",) if ano else ()):
        plano = by_key.get(r["product_key"])
        if plano is None or (member is not None and plano["member_id"] != member):
            continue
        out.append({**dict(r), "plano": plano["name"], "tipo_plano": plano["plan_type"], "seguradora": plano["issuer"],
                    "previsto": r["paid_on"] > date.today().isoformat()})
    return out


def registrar_aporte(product_key: str, data: str, valor_cents: int, pagador: str = "participante", folha: bool = False,
                     transaction_id: int | None = None, repetir_ate_dezembro: bool = False,
                     autor: str = "usuario") -> dict[str, Any]:
    if pagador not in {"participante", "empresa"}:
        raise ValueError("Quem pagou deve ser 'participante' ou 'empresa'.")
    if valor_cents <= 0:
        raise ValueError("Informe o valor do aporte.")
    plano = next((p for p in planos() if p["product_key"] == product_key), None)
    if not plano:
        raise ValueError("Plano não encontrado. Registre antes um saldo do plano em Investimentos › Previdência.")
    try:
        inicio = date.fromisoformat(data)
    except ValueError as exc:
        raise ValueError("Data do aporte inválida (AAAA-MM-DD).") from exc
    datas = [inicio]
    if repetir_ate_dezembro:
        datas += [date(inicio.year, m, min(inicio.day, 28)) for m in range(inicio.month + 1, 13)]
    with transaction() as con:
        for d in datas:
            con.execute("INSERT INTO previdencia_aporte(product_key, paid_on, amount_cents, payer, payroll, transaction_id, author) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)", (product_key, d.isoformat(), valor_cents, pagador, int(folha),
                                                         transaction_id if d == inicio else None, autor))
    return {"plano": plano["name"], "aportes": len(datas), "valor": valor_cents / 100, "pagador": pagador}


def remover_aporte(aporte_id: int) -> None:
    with transaction() as con:
        con.execute("UPDATE previdencia_aporte SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?", (aporte_id,))


def sugestoes_aporte(member: int | None, ano: int) -> list[dict[str, Any]]:
    """Débitos do ano que parecem aporte de previdência e ainda não foram registrados."""
    ligados = {int(r["transaction_id"]) for r in rows("SELECT transaction_id FROM previdencia_aporte "
                                                      "WHERE transaction_id IS NOT NULL AND deleted_at IS NULL")}
    out = []
    for t in analytics.cash_transactions(member=member):
        if (t["transaction_date"].startswith(str(ano)) and t["amount_cents"] < 0 and int(t["id"]) not in ligados
                and t["category"] not in analytics.INTERNAL_CATEGORIES - {"Investimentos"}
                and any(p in _norm(t["description"]) for p in PREVIDENCIA_DESCRICOES)):
            out.append({"id": int(t["id"]), "data": t["transaction_date"], "descricao": t["description"],
                        "valor": -int(t["amount_cents"])})
    return out


# ---------------------------------------------------------------- cálculo

def _ajuste(p: parametros.Parametros, rendimentos: int, legais: int, doacoes: int) -> dict[str, dict[str, int]]:
    out = {}
    simplificado = min(centavos(D(rendimentos) * p.simplificado_pct), p.simplificado_limite)
    for modelo, deducoes_modelo in (("completo", legais), ("simplificado", simplificado)):
        base = max(0, rendimentos - deducoes_modelo)
        imposto = imposto_tabela(base, p.tabela_anual)
        reducao = parametros.reducao_anual(p, rendimentos, imposto)
        apos = imposto - reducao
        doacao = min(doacoes, centavos(D(apos) * p.doacoes_pct)) if modelo == "completo" else 0
        out[modelo] = {"deducoes": deducoes_modelo, "base": base, "imposto": imposto, "reducao": reducao,
                       "doacoes": doacao, "devido": apos - doacao,
                       "aliquota_efetiva": round(float((apos - doacao) / rendimentos), 4) if rendimentos else 0.0}
    return out


def simples(faturamento_mensal: int, pro_labore: int, regime: str) -> dict[str, Any] | None:
    """DAS estimado e fator R (Simples, Anexos III e V), com RBT12 = 12 × o faturamento do mês."""
    if not faturamento_mensal or regime not in {"simples_fator_r", "simples_iii", "simples_v"}:
        return None
    rbt12 = faturamento_mensal * 12
    fator = D(pro_labore * 12) / D(rbt12)

    def aliquota(anexo: str) -> Decimal | None:
        for limite, nominal, deduzir in SIMPLES[anexo]:
            if rbt12 <= limite:
                return (D(rbt12) * nominal - D(deduzir)) / D(rbt12)
        return None
    iii, v = aliquota("III"), aliquota("V")
    if iii is None:
        return {"fora_do_simples": True, "rbt12": rbt12}
    anexo = "III" if regime == "simples_iii" or (regime == "simples_fator_r" and fator >= FATOR_R) else "V"
    efetiva = iii if anexo == "III" else v
    das = centavos(D(faturamento_mensal) * efetiva)
    return {
        "rbt12": rbt12, "fator_r": round(float(fator), 4), "anexo": anexo, "aliquota_efetiva": round(float(efetiva), 4),
        "das_mensal": das, "das_anexo_iii": centavos(D(faturamento_mensal) * iii), "das_anexo_v": centavos(D(faturamento_mensal) * v),
        "pro_labore_minimo_fator_r": centavos(D(faturamento_mensal) * FATOR_R) if regime == "simples_fator_r" else None,
        "sobra_antes_de_despesas": faturamento_mensal - das - pro_labore,
    }


def estimar(member: int | None, ano: int, pgbl_extra: int = 0, hoje: date | None = None) -> dict[str, Any]:
    """Estimativa do ano. Centavos."""
    member = _membro(member)
    hoje = hoje or date.today()
    p = parametros.para(ano)
    fs = fontes(member, ano)
    deps = dependentes(member, ano)
    pf = perfil(member, ano)
    ded = deducoes(member, ano)
    aps = aportes(member, ano)
    rv = renda_variavel.apurar(member, ano, hoje)

    # PGBL do participante descontado em folha, por mês (já reduz o IRRF daquele mês)
    folha_pgbl: dict[int, int] = defaultdict(int)
    for a in aps:
        if a["payer"] == "participante" and a["payroll"] and (a["tipo_plano"] or "").upper() != "VGBL":
            folha_pgbl[int(a["paid_on"][5:7])] += int(a["amount_cents"])
    principal = max(fs, key=lambda f: f["gross_monthly_cents"], default=None)  # dependentes e PGBL em folha nesta

    rendimentos = inss_total = irrf_total = carne_leao = 0
    meses: list[dict[str, Any]] = []
    por_fonte: list[dict[str, Any]] = []
    decimo: list[dict[str, Any]] = []
    liquido_clt: dict[int, int] = defaultdict(int)  # líquido esperado do salário em cada mês (conciliação)
    for f in fs:
        acc = {"fonte": f, "rendimentos": 0, "inss": 0, "irrf": 0, "carne_leao": 0, "meses": 0}
        for m in range(f["first_month"], f["last_month"] + 1):
            bruto = f["gross_monthly_cents"] + (f["gross_monthly_cents"] // 3 if f["vacation_month"] == m else 0)
            if f["inss_monthly_cents"] is not None:
                inss = f["inss_monthly_cents"]
            elif f["kind"] == "clt":
                inss = parametros.inss_empregado(p, bruto)
            elif f["kind"] == "pro_labore":
                inss = parametros.inss_pro_labore(p, bruto)
            else:
                inss = 0
            deducoes_mes = inss + f["payroll_deductions_monthly_cents"]
            if f is principal:
                deducoes_mes += len(deps) * p.dependente_mensal + folha_pgbl.get(m, 0)
            calc = parametros.irrf_mensal(p, m, bruto, deducoes_mes)
            if f["kind"] == "clt":
                liquido_clt[m] += (bruto - inss - calc["irrf"] - f["payroll_deductions_monthly_cents"]
                                   - (folha_pgbl.get(m, 0) if f is principal else 0))
            acc["rendimentos"] += bruto
            acc["inss"] += inss
            if f["kind"] == "outro":
                acc["carne_leao"] += calc["irrf"]
            else:
                acc["irrf"] += calc["irrf"]
            acc["meses"] += 1
        if f["irrf_year_cents"] is not None and f["kind"] != "outro":
            acc["irrf"] = f["irrf_year_cents"]
        if f["kind"] == "clt" and f["thirteenth"]:
            bruto13 = f["gross_monthly_cents"] * (f["last_month"] - f["first_month"] + 1) // 12
            inss13 = parametros.inss_empregado(p, bruto13)
            base13 = max(0, bruto13 - inss13 - (len(deps) * p.dependente_mensal if f is principal else 0))
            imposto13 = imposto_tabela(base13, p.tabela_mensal[12])
            irrf13 = imposto13 - parametros.reducao_mensal(p, bruto13, imposto13)
            decimo.append({"fonte": f["payer"], "bruto": bruto13, "inss": inss13, "irrf": irrf13})
            liquido_clt[11] += bruto13 // 2                                  # 1ª parcela, sem desconto
            liquido_clt[12] += bruto13 - bruto13 // 2 - inss13 - irrf13      # 2ª parcela, com INSS e IRRF do 13º
            inss_total += inss13
        rendimentos += acc["rendimentos"]
        inss_total += acc["inss"]
        irrf_total += acc["irrf"]
        carne_leao += acc["carne_leao"]
        por_fonte.append({"id": f["id"], "tipo": f["kind"], "tipo_nome": TIPOS_FONTE[f["kind"]], "pagador": f["payer"],
                          "documento": formatar_doc(f["payer_doc"]), "bruto_mensal": f["gross_monthly_cents"],
                          "rendimentos": acc["rendimentos"], "inss": acc["inss"], "irrf": acc["irrf"],
                          "carne_leao": acc["carne_leao"], "meses": acc["meses"],
                          "irrf_informado": f["irrf_year_cents"] is not None,
                          "simples": simples(f["pj_revenue_monthly_cents"] or 0, f["gross_monthly_cents"], f["pj_regime"] or "")
                          if f["kind"] == "pro_labore" else None})
    # INSS do ajuste: o de cada mês, sem o do 13º (que é exclusivo)
    inss_ajuste = sum(x["inss"] for x in por_fonte)

    # deduções
    por_tipo: dict[str, int] = defaultdict(int)
    educacao_pessoa: dict[str, int] = defaultdict(int)
    for i in ded["itens"]:
        if i["tipo"] == "educacao":
            educacao_pessoa[i["beneficiario"]] += i["conta"]
        else:
            por_tipo[i["tipo"]] += i["conta"]
    educacao = sum(min(v, p.educacao_limite) for v in educacao_pessoa.values())
    pensao = por_tipo["pensao"] + sum(f["payroll_deductions_monthly_cents"] * (f["last_month"] - f["first_month"] + 1) for f in fs)
    dependentes_valor = len(deps) * p.dependente_anual

    # previdência
    pgbl_participante = sum(int(a["amount_cents"]) for a in aps if a["payer"] == "participante"
                            and (a["tipo_plano"] or "").upper() != "VGBL")
    empresa = sum(int(a["amount_cents"]) for a in aps if a["payer"] == "empresa")
    vgbl = sum(int(a["amount_cents"]) for a in aps if a["payer"] == "participante" and (a["tipo_plano"] or "").upper() == "VGBL")
    contribui = pf["contribui_previdencia_oficial"]
    contribui = bool(contribui) if contribui is not None else any(f["kind"] in {"clt", "pro_labore"} for f in fs)
    limite_pgbl = centavos(D(rendimentos) * p.pgbl_pct)

    def cenario(extra: int) -> dict[str, dict[str, int]]:
        pgbl = min(pgbl_participante + extra, limite_pgbl) if contribui else 0
        legais = inss_ajuste + dependentes_valor + por_tipo["saude"] + educacao + pensao + pgbl
        return _ajuste(p, rendimentos, legais, por_tipo["doacao"])

    atual = cenario(pgbl_extra)
    melhor = min(atual, key=lambda k: atual[k]["devido"])
    falta = max(0, limite_pgbl - pgbl_participante - pgbl_extra) if contribui else 0
    cheio = cenario(pgbl_extra + falta)
    base_melhor = min(atual["completo"]["devido"], atual["simplificado"]["devido"])
    economia = max(0, base_melhor - cheio["completo"]["devido"]) if falta else 0

    # dividendos (Lei 15.270, art. 6º-A) e tributação mínima
    retencao = 0
    lucros = 0
    for f in fs:
        if f["kind"] == "pro_labore" and f["pj_profit_monthly_cents"]:
            for _m in range(f["first_month"], f["last_month"] + 1):
                lucros += f["pj_profit_monthly_cents"]
                if p.dividendos_limite_mensal and f["pj_profit_monthly_cents"] > p.dividendos_limite_mensal:
                    retencao += centavos(D(f["pj_profit_monthly_cents"]) * p.dividendos_aliquota)
    dividendos_acoes = 0
    for (_, _), valor in renda_variavel.dividendos_por_empresa_mes(member, ano).items():
        dividendos_acoes += valor
        if p.dividendos_limite_mensal and valor > p.dividendos_limite_mensal:
            retencao += centavos(D(valor) * p.dividendos_aliquota)
    jcp = sum(x["jcp"] for x in rv["proventos"])
    ganhos_bolsa = rv["isentos_linha_20"] + sum(sum(m["base"].values()) for m in rv["meses"])
    renda_total = rendimentos + sum(x["bruto"] for x in decimo) + lucros + dividendos_acoes + jcp + ganhos_bolsa
    devido_ajuste = atual[melhor]["devido"]
    irpfm = None
    if p.irpfm_inicio and renda_total > p.irpfm_inicio:
        aliquota = parametros.aliquota_irpfm(p, renda_total)
        bruto = centavos(D(renda_total) * aliquota)
        exclusivo = sum(x["irrf"] for x in decimo) + centavos(D(jcp) * D(15) / D(85))
        definitivo = rv["imposto_ano"]
        irpfm = {"renda_total": renda_total, "aliquota": float(aliquota), "bruto": bruto,
                 "deducoes": devido_ajuste + exclusivo + definitivo,
                 "valor": max(0, bruto - devido_ajuste - exclusivo - definitivo), "retencao_dividendos": retencao,
                 "a_pagar": max(0, bruto - devido_ajuste - exclusivo - definitivo) - retencao}
    devolve_retencao = retencao if irpfm is None else 0
    saldo = devido_ajuste - irrf_total - carne_leao - devolve_retencao

    return {
        "ano": ano, "titular": member, "parametros_projetados": parametros.projetado(ano),
        "parametros_a_confirmar": list(p.a_confirmar), "parametros_fonte": p.fonte,
        "tem_fontes": bool(fs), "fontes": por_fonte, "dependentes": deps, "decimo_terceiro": decimo,
        "rendimentos_tributaveis": rendimentos, "inss": inss_ajuste, "irrf": irrf_total, "carne_leao": carne_leao,
        "deducoes": {"inss": inss_ajuste, "dependentes": dependentes_valor, "saude": por_tipo["saude"],
                     "educacao": educacao, "educacao_informada": sum(educacao_pessoa.values()), "pensao": pensao,
                     "previdencia": min(pgbl_participante + pgbl_extra, limite_pgbl) if contribui else 0,
                     "doacoes": por_tipo["doacao"]},
        "modelos": atual, "melhor": melhor, "devido": devido_ajuste, "saldo": saldo,
        "resultado": "restituir" if saldo < 0 else "pagar" if saldo > 0 else "zero",
        "previdencia": {"limite": limite_pgbl, "participante": pgbl_participante, "empresa": empresa, "vgbl": vgbl,
                        "extra_simulado": pgbl_extra, "falta": falta, "economia_completar": economia,
                        "economia_por_real": round(economia / falta, 4) if falta else 0.0,
                        "contribui_previdencia_oficial": contribui, "ajuda": economia > 0,
                        "devido_com_limite": cheio["completo"]["devido"]},
        "dividendos": {"lucros_pj": lucros, "dividendos_acoes": dividendos_acoes, "retencao": retencao,
                       "devolvida_no_ajuste": devolve_retencao},
        "irpfm": irpfm, "renda_total": renda_total,
        "obriga_declarar": rendimentos > p.obrigatoriedade.get("tributaveis", 0) or rv["obriga_declarar"],
        "conciliacao": conciliar_salario(member, ano, liquido_clt, hoje),
    }


def conciliar_salario(member: int, ano: int, liquido: dict[int, int], hoje: date) -> list[dict[str, Any]]:
    """Líquido esperado do salário CLT de cada mês (bruto − INSS − IRRF − pensão − PGBL em folha, com as férias no mês
    delas e o 13º em novembro e dezembro) contra o que entrou em "Salário" em cada mês passado. O pró-labore fica de
    fora: costuma cair na conta da empresa, não na pessoal."""
    if not liquido:
        return []
    recebido: dict[str, int] = defaultdict(int)
    for t in analytics.cash_transactions(member=member):
        if t["transaction_date"].startswith(str(ano)) and t["category"] == "Salário" and t["amount_cents"] > 0:
            recebido[t["transaction_date"][:7]] += int(t["amount_cents"])
    out = []
    for m in range(1, 13):
        mes = f"{ano}-{m:02d}"
        if mes >= hoje.isoformat()[:7]:
            break
        if m not in liquido:
            continue
        r, esperado_mes = recebido.get(mes, 0), liquido[m]
        diferenca = r - esperado_mes
        out.append({"mes": mes, "esperado": esperado_mes, "recebido": r, "diferenca": diferenca,
                    "aviso": bool(r) and abs(diferenca) > esperado_mes * 0.05})
    return out
