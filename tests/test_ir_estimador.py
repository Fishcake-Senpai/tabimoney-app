"""Estimador do IR do ano (app/services/ir/estimador.py): os exemplos da spec (§B.3.4) e as regras das deduções e
da previdência."""
from __future__ import annotations

from datetime import date

import pytest

from app import db
from app.services import pension
from app.services.ir import estimador as est

HOJE = date(2026, 10, 19)


def plano(nome: str = "Itaú Flexprev PGBL", tipo: str = "PGBL") -> str:
    pension.save_entry({"name": nome, "institution": "Itaú", "plan_type": tipo, "as_of_date": "2026-01-31", "gross": "1000"})
    return next(p["product_key"] for p in est.planos() if p["name"] == nome)


def clt(bruto: int, **extra) -> dict:
    return est.salvar_fonte(1, 2026, {"kind": "clt", "payer": "Empresa SA", "gross_monthly_cents": bruto,
                                      "thirteenth": True, **extra})


def test_clt_12_mil_completo_e_quanto_falta_de_pgbl():
    clt(1_200_000)
    dep = est.salvar_dependente(1, 2026, "Bia", "filho", 2015)
    est.adicionar_manual(1, {"kind": "saude", "paid_on": "2026-03-10", "amount_cents": 600_000,
                             "provider_name": "Clínica X", "provider_doc": "11.222.333/0001-81"})
    est.adicionar_manual(1, {"kind": "educacao", "paid_on": "2026-02-10", "amount_cents": 500_000,
                             "provider_name": "Escola Y", "beneficiary": f"dep:{dep['id']}"})
    est.registrar_aporte(plano(), "2026-06-10", 600_000)
    r = est.estimar(1, 2026, hoje=HOJE)
    assert r["rendimentos_tributaveis"] == 14_400_000 and r["inss"] == 1_185_708
    assert r["deducoes"]["educacao"] == 356_150                       # limite por pessoa
    assert r["modelos"]["completo"]["deducoes"] == 2_969_366
    assert r["modelos"]["completo"]["devido"] == 2_052_958
    assert r["modelos"]["simplificado"]["devido"] == 2_384_434
    assert r["melhor"] == "completo"
    prev = r["previdencia"]
    assert prev["limite"] == 1_728_000 and prev["falta"] == 1_128_000 and prev["economia_completar"] == 310_200
    assert r["decimo_terceiro"][0]["bruto"] == 1_200_000              # fora do ajuste


def test_clt_6500_pgbl_rende_pouco_contra_o_simplificado():
    clt(650_000)
    r = est.estimar(1, 2026, hoje=HOJE)
    assert r["modelos"]["completo"]["reducao"] == 97_488
    assert r["modelos"]["simplificado"]["devido"] == 528_046 and r["modelos"]["completo"]["devido"] == 722_248
    assert r["melhor"] == "simplificado"
    prev = r["previdencia"]
    assert prev["falta"] == 936_000 and prev["devido_com_limite"] == 464_848 and prev["economia_completar"] == 63_198


def test_pj_pro_labore_limite_do_pgbl_so_sobre_o_pro_labore():
    est.salvar_fonte(1, 2026, {"kind": "pro_labore", "payer": "Minha Empresa", "gross_monthly_cents": 840_000,
                               "pj_revenue_monthly_cents": 3_000_000, "pj_regime": "simples_fator_r",
                               "pj_profit_monthly_cents": 1_000_000})
    r = est.estimar(1, 2026, hoje=HOJE)
    fonte = r["fontes"][0]
    assert fonte["inss"] == 924 * 100 * 12 and fonte["irrf"] == 114_717 * 12
    assert r["modelos"]["simplificado"]["devido"] == 1_196_434 and r["modelos"]["completo"]["devido"] == 1_376_614
    assert r["previdencia"]["limite"] == 1_209_600 and r["previdencia"]["economia_completar"] == 152_460
    assert r["dividendos"]["lucros_pj"] == 12_000_000 and r["dividendos"]["retencao"] == 0
    simples = fonte["simples"]
    assert simples["anexo"] == "III" and simples["fator_r"] == 0.28 and simples["das_mensal"] == 258_000
    assert simples["das_anexo_v"] == 502_500


def test_aporte_da_empresa_e_vgbl_nao_deduzem():
    clt(1_200_000)
    pgbl = plano()
    est.registrar_aporte(pgbl, "2026-01-10", 300_000, pagador="empresa", repetir_ate_dezembro=True)
    est.registrar_aporte(plano("Itaú VGBL", "VGBL"), "2026-02-10", 500_000)
    r = est.estimar(1, 2026, hoje=HOJE)
    assert r["previdencia"]["empresa"] == 3_600_000 and r["previdencia"]["participante"] == 0
    assert r["previdencia"]["vgbl"] == 500_000 and r["deducoes"]["previdencia"] == 0


def test_sem_inss_o_pgbl_nao_deduz():
    est.salvar_fonte(1, 2026, {"kind": "outro", "payer": "Aluguel", "gross_monthly_cents": 800_000})
    est.registrar_aporte(plano(), "2026-03-10", 300_000)
    r = est.estimar(1, 2026, hoje=HOJE)
    assert r["previdencia"]["contribui_previdencia_oficial"] is False and r["deducoes"]["previdencia"] == 0
    assert r["carne_leao"] > 0
    est.definir_perfil(1, 2026, True)                                   # aposentado pelo INSS
    assert est.estimar(1, 2026, hoje=HOJE)["deducoes"]["previdencia"] == 300_000


def _lancamento(descricao: str, centavos: int, categoria: str, dia: str = "2026-05-10") -> int:
    with db.transaction() as con:
        if not con.execute("SELECT 1 FROM financial_account WHERE id = 1").fetchone():
            con.execute("INSERT INTO financial_account(id, institution, account_name, account_type, provider, external_key) "
                        "VALUES (1, 'Nubank', 'Nubank', 'BANK', 'pluggy', 'k1')")
        cur = con.execute("INSERT INTO cash_transaction(account_id, source, external_id, transaction_date, description, "
                          "amount_cents, category) VALUES (1, 'pluggy', ?, ?, ?, ?, ?)",
                          (f"t{descricao}{dia}", dia, descricao, centavos, categoria))
        return int(cur.lastrowid)


def test_deducao_pela_categoria_farmacia_fica_fora_e_marcacao_manda():
    medico = _lancamento("Dr. Fulano Consulta", -50_000, "Saúde")
    _lancamento("Drogaria São Paulo", -8_000, "Saúde")
    r = est.deducoes(1, 2026)
    assert r["itens"] == [] and r["sugestoes"][0]["categoria"] == "Saúde"      # sugerida, não conta sozinha
    est.definir_categoria("Saúde", "saude")
    itens = {i["descricao"]: i for i in est.deducoes(1, 2026)["itens"]}
    assert itens["Dr. Fulano Consulta"]["conta"] == 50_000
    assert itens["Drogaria São Paulo"]["conta"] == 0 and itens["Drogaria São Paulo"]["aviso"]
    assert any("CNPJ" in f for f in itens["Dr. Fulano Consulta"]["faltas"])
    est.marcar_lancamentos([medico], "saude", prestador="Dr. Fulano", documento="529.982.247-25", reembolso_cents=20_000)
    item = next(i for i in est.deducoes(1, 2026)["itens"] if i["id"] == medico)
    assert item["conta"] == 30_000 and item["documento_fmt"] == "529.982.247-25"
    est.marcar_lancamentos([medico], "nenhuma")
    assert all(i["id"] != medico for i in est.deducoes(1, 2026)["itens"])


def test_documento_invalido_e_beneficiario_inexistente():
    with pytest.raises(ValueError):
        est.adicionar_manual(1, {"kind": "saude", "paid_on": "2026-01-01", "amount_cents": 100, "provider_name": "X",
                                 "provider_doc": "123"})
    with pytest.raises(ValueError):
        est.adicionar_manual(1, {"kind": "saude", "paid_on": "2026-01-01", "amount_cents": 100, "provider_name": "X",
                                 "beneficiary": "dep:999"})


def test_dividendo_acima_de_50_mil_retem_10_e_volta_no_ajuste():
    est.salvar_fonte(1, 2026, {"kind": "pro_labore", "payer": "Holding", "gross_monthly_cents": 300_000,
                               "pj_profit_monthly_cents": 5_000_001, "first_month": 12, "last_month": 12})
    r = est.estimar(1, 2026, hoje=HOJE)
    assert r["dividendos"]["retencao"] == 500_000 and r["dividendos"]["devolvida_no_ajuste"] == 500_000
    assert r["irpfm"] is None


def test_irpfm_acima_de_600_mil():
    est.salvar_fonte(1, 2026, {"kind": "pro_labore", "payer": "Holding", "gross_monthly_cents": 2_500_000,
                               "pj_profit_monthly_cents": 5_000_000})
    r = est.estimar(1, 2026, hoje=HOJE)
    assert r["renda_total"] == 90_000_000
    assert r["irpfm"]["aliquota"] == 0.05 and r["irpfm"]["bruto"] == 4_500_000
    assert r["irpfm"]["valor"] == max(0, 4_500_000 - r["devido"])


def test_conciliacao_do_salario():
    clt(1_200_000)
    for m in range(1, 10):
        _lancamento("Salário Empresa", 870_000 if m != 3 else 500_000, "Salário", f"2026-{m:02d}-05")
    conc = est.estimar(1, 2026, hoje=HOJE)["conciliacao"]
    assert len(conc) == 9
    assert next(c for c in conc if c["mes"] == "2026-03")["aviso"] is True
    assert next(c for c in conc if c["mes"] == "2026-02")["aviso"] is False


def test_conciliacao_mes_a_mes_com_ferias_13o_e_pgbl_em_folha():
    # Regressão: o esperado era a média do ano (com o terço de férias e o PGBL diluídos em todos os meses) e o 13º
    # ficava de fora, então todo mês normal acusava diferença e novembro e dezembro sempre davam aviso.
    clt(1_500_000, vacation_month=12)
    est.registrar_aporte(plano(), "2026-05-20", 100_000, "participante", folha=True)
    esperado = {c["mes"]: c["esperado"] for c in est.estimar(1, 2026, hoje=date(2027, 1, 10))["conciliacao"]}
    assert esperado["2026-01"] == 1_500_000 - 98_809 - 294_455                       # bruto − INSS teto − IRRF
    assert esperado["2026-05"] == 1_500_000 - 98_809 - 266_955 - 100_000             # PGBL sai do líquido e do IRRF
    assert esperado["2026-11"] == esperado["2026-01"] + 750_000                       # 1ª parcela do 13º, sem desconto
    assert esperado["2026-12"] == (2_000_000 - 98_809 - 431_955) + (750_000 - 98_809 - 294_455)  # férias + 2ª parcela


def test_contagem_das_categorias_sugeridas_nao_vira_quantidade_de_ativo():
    # Regressão: a contagem saía como "quantidade" e o JSON dos agentes a dividia por um milhão (2 → 0.000002).
    from app.agente import operacoes as op
    _lancamento("Dr. Fulano Consulta", -50_000, "Saúde")
    _lancamento("Laboratório Exame", -20_000, "Saúde")
    assert est.deducoes(1, 2026)["sugestoes"][0]["lancamentos"] == 2
    sugestao = op.ir_contexto(2026)["deducoes"]["categorias_sugeridas_sem_tipo"][0]
    assert sugestao["lancamentos"] == 2 and sugestao["total"] == 700.0


def test_copiar_perfil_para_o_ano_seguinte():
    clt(1_000_000)
    est.salvar_dependente(1, 2026, "Bia")
    assert est.copiar_perfil(1, 2026, 2027) == 1
    assert est.fontes(1, 2027)[0]["payer"] == "Empresa SA" and est.dependentes(1, 2027)[0]["name"] == "Bia"
    with pytest.raises(ValueError):
        est.copiar_perfil(1, 2026, 2027)
