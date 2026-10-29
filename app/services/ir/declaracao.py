"""Passo a passo da declaração: o que vai em cada ficha do programa da Receita, na ordem do programa, com o valor
pronto para copiar. Não gera arquivo para importar (decisão do usuário): o formato do programa é fechado e muda todo
ano. Os códigos de linha e de bens foram conferidos nos guias da declaração 2026; os marcados "a confirmar" mudam de
um ano para o outro com mais frequência.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from app.db import rows
from app.services.ir import estimador, renda_variavel
from app.services.ir.estimador import formatar_doc

MESES = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro",
         "Novembro", "Dezembro")


def reais(cents: int | None) -> str:
    """Formato do programa da Receita: 1.234,56 (sem R$)."""
    value = (cents or 0) / 100
    text = f"{abs(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if value < 0 else "") + text


def _campo(rotulo: str, valor: str | None, copiar: bool = True) -> dict[str, Any]:
    return {"rotulo": rotulo, "valor": valor or "—", "copiar": bool(copiar and valor)}


def _dinheiro(rotulo: str, cents: int | None) -> dict[str, Any]:
    return _campo(rotulo, reais(cents))


def montar(member: int | None, ano: int, hoje: date | None = None) -> dict[str, Any]:
    hoje = hoje or date.today()
    est = estimador.estimar(member, ano, hoje=hoje)
    rv = renda_variavel.apurar(member, ano, hoje)
    ded = estimador.deducoes(member, ano)
    aps = estimador.aportes(est["titular"], ano)
    secoes: list[dict[str, Any]] = []

    def secao(id_: str, titulo: str, ficha: str, itens: list[dict[str, Any]], nota: str = "") -> None:
        if itens:
            secoes.append({"id": id_, "titulo": titulo, "ficha": ficha, "nota": nota, "itens": itens})

    # ------------------------------------------------ dependentes
    secao("dependentes", "Dependentes", "Dependentes", [
        {"titulo": d["name"], "campos": [_campo("Parentesco", d["kinship"], False),
                                         _campo("Ano de nascimento", str(d["birth_year"] or ""), False)],
         "aviso": "Informe o CPF do dependente no programa (o app não guarda CPF)."}
        for d in est["dependentes"]],
        "Cada dependente deduz R$ 2.275,08. A renda dele entra na sua declaração.")

    # ------------------------------------------------ rendimentos tributáveis
    decimo = {d["fonte"]: d for d in est["decimo_terceiro"]}
    pj = []
    pf = []
    for f in est["fontes"]:
        d13 = decimo.get(f["pagador"])
        campos = [_campo("CNPJ da fonte pagadora", f["documento"] or None), _campo("Nome da fonte pagadora", f["pagador"]),
                  _dinheiro("Rendimentos recebidos de pessoa jurídica", f["rendimentos"]),
                  _dinheiro("Contribuição previdenciária oficial", f["inss"]),
                  _dinheiro("Imposto retido na fonte", f["irrf"])]
        if d13:
            campos += [_dinheiro("13º salário", d13["bruto"]), _dinheiro("IRRF sobre o 13º salário", d13["irrf"])]
        item = {"titulo": f"{f['pagador']} · {f['tipo_nome']}", "campos": campos,
                "aviso": None if f["irrf_informado"] else "Valores estimados: copie os do informe de rendimentos."}
        (pf if f["tipo"] == "outro" else pj).append(item)
    secao("tributaveis-pj", "Rendimentos tributáveis recebidos de pessoa jurídica",
          "Rendimentos Tributáveis Recebidos de Pessoa Jurídica", pj,
          "Use o informe de rendimentos de cada empresa; aqui estão as estimativas para conferir.")
    secao("tributaveis-pf", "Rendimentos tributáveis de pessoa física (carnê-leão)",
          "Rendimentos Tributáveis Recebidos de Pessoa Física e do Exterior", pf,
          "Aluguel e trabalho sem vínculo: mês a mês, com o carnê-leão pago (DARF 0190).")

    # ------------------------------------------------ isentos
    isentos = []
    for p in rv["proventos"]:
        if p["dividendos"]:
            isentos.append({"titulo": f"09 · Lucros e dividendos · {p['ticker']}",
                            "campos": [_campo("CNPJ da fonte pagadora", formatar_doc(_so_digitos(p["cnpj"]))),
                                       _campo("Nome da fonte pagadora", p["nome"]), _dinheiro("Valor", p["dividendos"])],
                            "aviso": None if p["cnpj"] else "Sem o CNPJ da empresa: confira no informe da corretora."})
    for f in est["fontes"]:
        lucro = next((x for x in estimador.fontes(est["titular"], ano) if x["id"] == f["id"]), {}).get("pj_profit_monthly_cents")
        if f["tipo"] == "pro_labore" and lucro:
            isentos.append({"titulo": f"09 · Lucros e dividendos · {f['pagador']}",
                            "campos": [_campo("CNPJ da fonte pagadora", f["documento"] or None),
                                       _campo("Nome da fonte pagadora", f["pagador"]),
                                       _dinheiro("Valor", lucro * f["meses"])], "aviso": "Estimado: use o informe da empresa."})
    if rv["isentos_linha_20"]:
        isentos.append({"titulo": "20 · Ganhos líquidos em ações até R$ 20 mil por mês",
                        "campos": [_dinheiro("Valor", rv["isentos_linha_20"])],
                        "aviso": "Soma dos lucros de ações e units nos meses com vendas de ações até R$ 20 mil."})
    for p in rv["proventos"]:
        if p["rendimentos_fii"]:
            isentos.append({"titulo": f"99 · Outros · rendimentos de {p['ticker']}",
                            "campos": [_campo("CNPJ do fundo", formatar_doc(_so_digitos(p["cnpj"]))),
                                       _campo("Nome", p["nome"]), _campo("Descrição", "Rendimentos de FII"),
                                       _dinheiro("Valor", p["rendimentos_fii"])],
                            "aviso": "O código da linha de FII muda de ano para ano (26 ou 99): use o que o programa trouxer."})
    for p in rv["proventos"]:
        if p["outros"]:
            isentos.append({"titulo": f"09 ou 10? · Provento sem tipo · {p['ticker']}",
                            "campos": [_campo("CNPJ da fonte pagadora", formatar_doc(_so_digitos(p["cnpj"]))),
                                       _campo("Nome da fonte pagadora", p["nome"]), _dinheiro("Valor", p["outros"])],
                            "aviso": "A corretora não disse se é dividendo ou JCP. Confira no informe de rendimentos: "
                                     "dividendo vai aqui (linha 09); JCP vai em Tributação exclusiva (linha 10), "
                                     "pelo valor líquido."})
    secao("isentos", "Rendimentos isentos e não tributáveis", "Rendimentos Isentos e Não Tributáveis", isentos)

    # ------------------------------------------------ exclusivos
    exclusivos = [{"titulo": f"01 · 13º salário · {d['fonte']}",
                   "campos": [_dinheiro("Valor (13º menos o IRRF dele)", d["bruto"] - d["irrf"])], "aviso": None}
                  for d in est["decimo_terceiro"]]
    exclusivos += [{"titulo": f"10 · Juros sobre capital próprio · {p['ticker']}",
                    "campos": [_campo("CNPJ da fonte pagadora", formatar_doc(_so_digitos(p["cnpj"]))),
                               _campo("Nome da fonte pagadora", p["nome"]), _dinheiro("Valor (líquido)", p["jcp"])],
                    "aviso": "JCP vai pelo valor líquido, depois dos 15% retidos."} for p in rv["proventos"] if p["jcp"]]
    secao("exclusivos", "Rendimentos sujeitos à tributação exclusiva", "Rendimentos Sujeitos à Tributação Exclusiva/Definitiva",
          exclusivos)

    # ------------------------------------------------ renda variável
    comuns, fii = [], []
    for m in rv["meses"]:
        nome = MESES[int(m["mes"][5:7]) - 1]
        if m["resultado"]["comum"] or m["resultado"]["day_trade"] or m["resultado_acoes"] or m["irrf"]["comum"] or m["irrf"]["day_trade"]:
            comuns.append({"titulo": nome, "campos": [
                _dinheiro("Mercado à vista · ações (comum)", 0 if m["isento"] else m["resultado_acoes"]),
                _dinheiro("Mercado à vista · outros: ETF e BDR (comum)", m["resultado_outros"]),
                _dinheiro("Day trade (resultado do mês)", m["resultado"]["day_trade"]),
                _dinheiro("IRRF (Lei 11.033)", m["irrf"]["comum"] + m["irrf"]["day_trade"]),
                _dinheiro("Imposto pago (DARF)", m["pago"] if m["pago"] is not None else m["darf"])],
                "aviso": ("Mês isento: o lucro das ações vai em Isentos, linha 20." if m["isento"] else None)})
        if m["resultado"]["fii"] or m["irrf"]["fii"]:
            fii.append({"titulo": nome, "campos": [_dinheiro("Resultado líquido do mês", m["resultado"]["fii"]),
                                                   _dinheiro("IRRF", m["irrf"]["fii"]),
                                                   _dinheiro("Imposto pago (DARF)", m["pago"] if m["pago"] is not None else m["darf"])],
                        "aviso": None})
    nota_rv = ""
    if any(rv["prejuizo_inicio"].values()):
        nota_rv = (f"Em janeiro, informe o prejuízo a compensar de anos anteriores: comum {reais(rv['prejuizo_inicio']['comum'])}, "
                   f"day trade {reais(rv['prejuizo_inicio']['day_trade'])}.")
    secao("renda-variavel", "Renda variável · operações comuns e day trade", "Renda Variável › Operações Comuns/Day-Trade",
          comuns, nota_rv or "Um mês por linha. Prejuízo entra com sinal negativo.")
    secao("renda-variavel-fii", "Renda variável · fundos imobiliários", "Renda Variável › Operações Fundos Invest. Imob.", fii,
          f"Prejuízo de FII de anos anteriores: {reais(rv['prejuizo_inicio']['fii'])}." if rv["prejuizo_inicio"]["fii"] else "")

    # ------------------------------------------------ bens e direitos
    bens = [{"titulo": f"{b['grupo']} – {b['codigo']} · {b['ticker']}",
             "campos": [_campo("Grupo", b["grupo"]), _campo("Código", f"{b['codigo']} – {b['codigo_nome']}", False),
                        _campo("CNPJ", formatar_doc(_so_digitos(b["cnpj"]))), _campo("Discriminação", b["discriminacao"]),
                        _dinheiro(f"Situação em 31/12/{ano - 1}", b["anterior"]), _dinheiro(f"Situação em 31/12/{ano}", b["atual"])],
             "aviso": ("A corretora mostra mais do que o histórico explica: informe a posição inicial antes de copiar."
                       if b["quantidade_sem_historico"]
                       else "Dispensado (custo abaixo de R$ 1.000); declarar é opcional." if b["dispensado"]
                       else None if b["custo_conhecido"] else "Custo incompleto: resolva as pendências antes.")}
            for b in rv["bens"]]
    for vg in _vgbl(est["titular"], ano):
        bens.append({"titulo": f"99 – 06 · {vg['name']}", "campos": [
            _campo("Grupo", "99"), _campo("Código", "06 – VGBL", False),
            _campo("Discriminação", f"VGBL {vg['name']}, {vg['issuer']}. Valor aplicado (prêmios pagos), sem os rendimentos."),
            _dinheiro(f"Situação em 31/12/{ano - 1}", vg["anterior"]), _dinheiro(f"Situação em 31/12/{ano}", vg["atual"])],
            "aviso": "Use o informe da seguradora; o app soma o que foi registrado como aplicado."})
    secao("bens", "Bens e direitos", "Bens e Direitos", bens,
          "Sempre pelo custo de aquisição, nunca pelo valor de mercado.")

    # ------------------------------------------------ pagamentos efetuados
    pagamentos = []
    grupos: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for i in ded["itens"]:
        if not i["conta"] and not i["reembolso"]:
            continue
        if i["tipo"] == "doacao":
            continue
        chave = (i["tipo"], i["documento"] or i["prestador"], i["beneficiario"], i["subtipo"] or "")
        g = grupos.setdefault(chave, {"item": i, "valor": 0, "reembolso": 0, "n": 0})
        g["valor"] += i["valor"]
        g["reembolso"] += i["reembolso"]
        g["n"] += 1
    for (kind, _, _, subtipo), g in sorted(grupos.items(), key=lambda kv: (kv[0][0], kv[1]["item"]["prestador"])):
        i = g["item"]
        tipo = {"saude": subtipo or "Saúde: escolha no programa (médico, dentista, plano…)",
                "educacao": "Instrução no Brasil", "pensao": "Pensão alimentícia judicial"}.get(kind, kind)
        pagamentos.append({"titulo": f"{tipo} · {i['prestador']}", "campos": [
            _campo("Código", tipo, False), _campo("Beneficiário", i["beneficiario_nome"], False),
            _campo("CPF/CNPJ do prestador", i["documento_fmt"] or None), _campo("Nome do prestador", i["prestador"]),
            _dinheiro("Valor pago", g["valor"]), _dinheiro("Parcela não dedutível / reembolsada", g["reembolso"])],
            "aviso": None if i["documento"] else "Falta o CPF ou CNPJ do prestador."})
    for plano, total in _pgbl_por_plano(aps).items():
        pagamentos.append({"titulo": f"36 · Previdência complementar · {plano[0]}", "campos": [
            _campo("Código", "36 – Previdência complementar (PGBL, FAPI)", False),
            _campo("Nome da seguradora", plano[1]), _campo("CNPJ", None),
            _dinheiro("Valor pago (só o que você aportou)", total)],
            "aviso": "CNPJ no informe da seguradora. O aporte da empresa não entra. Dedução limitada a 12% (o programa aplica)."})
    secao("pagamentos", "Pagamentos efetuados", "Pagamentos Efetuados", pagamentos,
          "Um item por prestador e beneficiário. Guarde as notas por 5 anos.")

    doacoes = [{"titulo": i["prestador"], "campos": [_campo("CNPJ", i["documento_fmt"] or None), _campo("Nome", i["prestador"]),
                                                     _dinheiro("Valor", i["conta"])], "aviso": None}
               for i in ded["itens"] if i["tipo"] == "doacao" and i["conta"]]
    secao("doacoes", "Doações efetuadas", "Doações Efetuadas", doacoes,
          "Só doações incentivadas deduzem, até 6% do imposto devido no modelo completo.")

    resumo = {"modelo": est["melhor"], "devido": est["devido"], "saldo": est["saldo"], "resultado": est["resultado"],
              "darf_bolsa": rv["darf_total"], "pendencias_bolsa": len(rv["pendencias"]),
              "obriga_declarar": est["obriga_declarar"] or rv["obriga_declarar"]}
    return {"ano": ano, "exercicio": ano + 1, "titular": est["titular"], "resumo": resumo, "secoes": secoes,
            "checklist": checklist(est, rv, ded, aps)}


def _so_digitos(value: str | None) -> str | None:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return digits or None


def _pgbl_por_plano(aps: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = defaultdict(int)
    for a in aps:
        if a["payer"] == "participante" and (a["tipo_plano"] or "").upper() != "VGBL":
            out[(a["plano"], a["seguradora"] or "")] += int(a["amount_cents"])
    return out


def _vgbl(member: int, ano: int) -> list[dict[str, Any]]:
    out = []
    for p in estimador.planos():
        if (p["plan_type"] or "").upper() != "VGBL" or p["member_id"] != member:
            continue

        def aplicado(ate: str) -> int:
            snap = rows("SELECT invested_cents FROM fixed_income_snapshot WHERE product_key = ? AND as_of_date <= ? "
                        "AND invested_cents IS NOT NULL ORDER BY as_of_date DESC LIMIT 1", (p["product_key"], ate))
            soma = sum(int(r["amount_cents"]) for r in rows(
                "SELECT amount_cents FROM previdencia_aporte WHERE product_key = ? AND paid_on <= ? AND deleted_at IS NULL "
                "AND payer = 'participante'", (p["product_key"], ate)))
            return max(int(snap[0]["invested_cents"]) if snap else 0, soma)
        out.append({**p, "anterior": aplicado(f"{ano - 1}-12-31"), "atual": aplicado(f"{ano}-12-31")})
    return out


def checklist(est: dict[str, Any], rv: dict[str, Any], ded: dict[str, Any], aps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Documentos para juntar antes de declarar, com o que já está no app."""
    itens = [{"texto": f"Informe de rendimentos de {f['pagador']}", "feito": f["irrf_informado"]} for f in est["fontes"]
             if f["tipo"] != "outro"]
    if rv["meses"] or rv["bens"] or rv["proventos"]:
        itens.append({"texto": "Informe de rendimentos de cada corretora (posição, proventos e IRRF)", "feito": False})
    if rv["darfs"]:
        n = len(rv["darfs"])
        itens.append({"texto": "Comprovante do DARF da bolsa" if n == 1 else f"Comprovantes dos {n} DARFs da bolsa",
                      "feito": all(m["pago"] is not None for m in rv["darfs"])})
    if aps:
        itens.append({"texto": "Informe da previdência (aportes do ano, CNPJ da seguradora)", "feito": False})
    faltam_doc = sum(1 for g in estimador.por_prestador(ded["itens"])["grupos"]
                     if g["conta"] and g["tipo"] in {"saude", "educacao", "pensao"} and not g["documento_fmt"])
    if ded["itens"]:
        falta = (" (1 prestador sem CPF/CNPJ)" if faltam_doc == 1 else f" ({faltam_doc} prestadores sem CPF/CNPJ)") if faltam_doc else ""
        itens.append({"texto": "Notas e recibos de saúde e educação" + falta,
                      "feito": not faltam_doc})
    if est["dependentes"]:
        itens.append({"texto": "CPF de cada dependente", "feito": False})
    itens.append({"texto": "Recibo da declaração do ano passado (número para a declaração nova)", "feito": False})
    return itens
