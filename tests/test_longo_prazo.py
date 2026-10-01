"""Análise de longo prazo: o perfil do investidor (horizonte e objetivo) que as análises perguntam antes de começar.

Spec: docs/superpowers/specs/2026-09-30-analise-longo-prazo.md.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from app import cli
from app.agente import operacoes as op
from app.services import household, investor_profile

from .conftest import avisos, csrf


def _cli(capsys, *args: str) -> dict:
    capsys.readouterr()
    cli.main(list(args))
    return json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------- perfil do investidor

def test_sem_perfil_a_ia_sabe_que_precisa_perguntar():
    perfil = op.perfil_investidor()
    assert perfil["configurado"] is False and perfil["horizonte"] is None
    assert "10-20" in perfil["opcoes"]["horizonte"] and "renda" in perfil["opcoes"]["objetivo"]
    assert op.carteira_contexto()["perfil"]["configurado"] is False


def test_grava_e_volta_no_contexto_da_carteira():
    op.perfil_definir("mais-de-20", "crescimento")
    perfil = op.carteira_contexto()["perfil"]
    assert perfil["configurado"] is True
    assert perfil["horizonte_texto"] == "mais de 20 anos" and perfil["objetivo_texto"] == "crescimento do patrimônio"
    assert perfil["atualizado_em"] == date.today().isoformat() and perfil["vencido"] is False


@pytest.mark.parametrize(("horizonte", "objetivo"), [("15", "renda"), ("10-20", "especular")])
def test_valores_fora_das_opcoes_sao_recusados(horizonte, objetivo):
    with pytest.raises(ValueError):
        op.perfil_definir(horizonte, objetivo)


def test_perfil_com_mais_de_um_ano_esta_vencido():
    investor_profile.save("5-10", "renda", today=date(2025, 1, 10))
    assert investor_profile.load(today=date(2026, 1, 9))["stale"] is False
    assert investor_profile.load(today=date(2026, 1, 11))["stale"] is True


def test_titular_usa_o_da_casa_ate_ter_o_proprio():
    ana = household.add_member("Ana")["id"]
    op.perfil_definir("10-20", "os-dois")
    assert op.perfil_investidor(ana)["horizonte"] == "10-20"
    assert op.perfil_investidor(ana)["de"] == "casa (titular sem perfil próprio)"
    op.perfil_definir("5-10", "renda", member=ana)
    assert op.perfil_investidor(ana)["horizonte"] == "5-10" and op.perfil_investidor(ana)["de"] == "titular"
    assert op.perfil_investidor()["horizonte"] == "10-20"
    investor_profile.clear(ana)
    assert op.perfil_investidor(ana)["horizonte"] == "10-20"


def test_cli_mostra_e_define(capsys):
    assert _cli(capsys, "perfil", "definir", "10-20", "crescimento")["horizonte"] == "10-20"
    assert _cli(capsys, "perfil", "mostrar")["objetivo"] == "crescimento"


def test_tela_de_metas_mostra_e_grava_o_perfil(client):
    assert "Definir horizonte" in client.get("/metas").text
    page = client.post("/metas/perfil", data={"csrf_token": csrf(client), "horizon": "mais-de-20", "goal": "renda"},
                       follow_redirects=True)
    assert ("success", "Horizonte e objetivo salvos.") in avisos(page.text)
    assert "Horizonte: mais de 20 anos · renda passiva" in page.text


def test_tela_de_metas_recusa_horizonte_invalido(client):
    page = client.post("/metas/perfil", data={"csrf_token": csrf(client), "horizon": "2", "goal": "renda"},
                       follow_redirects=True)
    assert avisos(page.text)[0][0] == "error"
    assert op.perfil_investidor()["configurado"] is False
