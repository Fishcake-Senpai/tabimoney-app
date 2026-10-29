"""Parâmetros do IR por ano (app/services/ir/parametros.py): tabelas, redutor da Lei 15.270, INSS e o alerta de
calendário. Quando a Receita publicar a declaração nova, estes números são os primeiros a revisar."""
from __future__ import annotations

from datetime import date

from app.services.ir import parametros as pr

P26 = pr.para(2026)


def _continuidade(tabela) -> None:
    """Cada parcela a deduzir faz a faixa começar onde a anterior termina (centavo de arredondamento)."""
    for (lim_ant, aliq_ant, parc_ant), (_, aliq, parc) in zip(tabela, tabela[1:]):
        assert abs(parc - (parc_ant + lim_ant * (aliq - aliq_ant))) <= 1, (lim_ant, parc)


def test_tabelas_continuas_como_as_oficiais():
    # AC 2024, oficial: 26.963,20 / 33.919,80 / 45.012,60 / 55.976,16; parcelas 2.022,24 · 4.566,23 · 7.942,17 · 10.740,98
    _continuidade(pr._tabela(("26963.20", "0", "0"), ("33919.80", "0.075", "2022.24"), ("45012.60", "0.15", "4566.23"),
                             ("55976.16", "0.225", "7942.17"), (None, "0.275", "10740.98")))
    for p in pr.PARAMETROS.values():
        _continuidade(p.tabela_anual)
        for tabela in p.tabela_mensal.values():
            _continuidade(tabela)


def test_imposto_pela_tabela():
    assert pr.imposto(2_914_560, P26.tabela_anual) == 0
    assert pr.imposto(11_430_634, P26.tabela_anual) == 2_052_958     # 114.306,34 × 27,5% − 10.904,66


def test_retencao_mensal_com_redutor_exemplos_da_receita():
    assert pr.irrf_mensal(P26, 1, 450_000, 0)["irrf"] == 0
    seis = pr.irrf_mensal(P26, 1, 600_000, 0)
    assert seis["base"] == 539_280 and seis["imposto"] == 57_429 and seis["reducao"] == 17_975 and seis["irrf"] == 39_454
    assert pr.reducao_mensal(P26, 735_001, 100_000) == 0


def test_redutor_anual():
    assert pr.reducao_anual(P26, 7_800_000, 819_736) == 97_488
    assert pr.reducao_anual(P26, 6_000_000, 500_000) == 269_415      # até 60 mil: teto fixo
    assert pr.reducao_anual(P26, 6_000_000, 100_000) == 100_000      # limitado ao imposto
    assert pr.reducao_anual(P26, 8_820_000, 900_000) <= 2            # zera em 88.200 (a fórmula deixa R$ 0,015)
    assert pr.reducao_anual(P26, 8_820_001, 900_000) == 0
    assert pr.reducao_anual(pr.para(2025), 5_000_000, 100_000) == 0  # 2025 não tem redutor


def test_inss_2026():
    assert pr.inss_empregado(P26, 500_000) == 50_151
    assert pr.inss_empregado(P26, 1_200_000) == 98_809 == pr.inss_teto_empregado(P26)
    assert pr.inss_pro_labore(P26, 840_000) == 92_400
    assert pr.inss_pro_labore(P26, 2_000_000) == 93_231


def test_simplificado_e_irpfm():
    assert P26.simplificado_limite == 1_764_000 and pr.para(2025).simplificado_limite == 1_675_434
    assert pr.aliquota_irpfm(P26, 60_000_000) == 0
    assert float(pr.aliquota_irpfm(P26, 90_000_000)) == 0.05
    assert float(pr.aliquota_irpfm(P26, 120_000_000)) == 0.10
    assert pr.aliquota_irpfm(pr.para(2025), 200_000_000) == 0


def test_ano_sem_tabela_usa_o_mais_proximo_e_avisa():
    assert pr.para(2030) is pr.PARAMETROS[max(pr.PARAMETROS)] and pr.projetado(2030)
    assert not pr.projetado(2026)


def test_alerta_de_calendario_depois_de_marco(monkeypatch):
    monkeypatch.setattr(pr, "EXERCICIO_CONFIRMADO", 2026)
    assert pr.alerta_calendario(date(2026, 10, 19)) is None
    assert pr.alerta_calendario(date(2027, 3, 31)) is None          # março ainda não passou
    alerta = pr.alerta_calendario(date(2027, 4, 1))
    assert alerta and alerta["exercicio"] == "2027" and "Atualize" in alerta["texto"]
    monkeypatch.setattr(pr, "EXERCICIO_CONFIRMADO", 2027)            # versão nova com os parâmetros revisados
    assert pr.alerta_calendario(date(2027, 4, 1)) is None


def test_todo_ano_tem_fonte_e_tabelas_completas():
    for ano, p in pr.PARAMETROS.items():
        assert p.ano == ano and p.fonte
        assert set(p.tabela_mensal) == set(range(1, 13)) == set(p.desconto_simplificado_mensal)
        assert p.tabela_anual[-1][0] is None
