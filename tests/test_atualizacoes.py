"""Aviso de versão nova, com o GitHub simulado."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app import __version__, db
from app.services import updates

from .conftest import csrf


class Resposta:
    def __init__(self, status: int, dados: dict | None = None):
        self.status_code, self._dados = status, dados or {}

    def json(self):
        return self._dados

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erro", request=None, response=None)


def _release(versao: str) -> dict:
    base = f"https://github.com/Fishcake-Senpai/tabimoney-app/releases/download/v{versao}/Tabimoney-{versao}"
    return {
        "tag_name": f"v{versao}", "html_url": f"https://github.com/x/releases/tag/v{versao}", "published_at": "2026-10-01T00:00:00Z",
        "assets": [{"name": f"Tabimoney-{versao}-{s}.zip", "browser_download_url": f"{base}-{s}.zip"}
                   for s in ("windows", "mac-apple-silicon", "mac-intel")],
    }


def _maior(versao: str) -> str:
    a, b, c = updates.parse_version(versao)
    return f"{a}.{b + 1}.0"


@pytest.fixture
def github(monkeypatch):
    """Simula a API do GitHub e conta as consultas."""
    estado = {"resposta": Resposta(200, _release(__version__)), "consultas": 0}

    def get(*_args, **_kwargs):
        estado["consultas"] += 1
        if isinstance(estado["resposta"], Exception):
            raise estado["resposta"]
        return estado["resposta"]

    monkeypatch.setattr(updates.httpx, "get", get)
    return estado


def test_parse_version():
    assert updates.parse_version("v0.11.0") == (0, 11, 0)
    assert updates.parse_version("1.2.3") == (1, 2, 3)
    assert updates.parse_version("0.11") is None and updates.parse_version(None) is None


def test_em_dia_nao_avisa(github):
    assert updates.check(force=True)["version"] == __version__
    assert updates.status() is None


def test_versao_nova_avisa_com_o_zip_do_sistema(github, monkeypatch):
    monkeypatch.setattr(updates, "platform_suffix", lambda: "mac-intel")
    github["resposta"] = Resposta(200, _release(_maior(__version__)))
    updates.check(force=True)
    aviso = updates.status()
    assert aviso["version"] == _maior(__version__) and aviso["current"] == __version__
    assert aviso["download_url"].endswith("-mac-intel.zip")


def test_nao_consulta_de_novo_antes_de_12_horas(github):
    updates.check()
    updates.check()
    assert github["consultas"] == 1
    antigo = datetime.now(timezone.utc) - timedelta(hours=13)
    db.set_setting(updates.KEY_CHECKED, antigo.isoformat())
    updates.check()
    assert github["consultas"] == 2


def test_desligado_nao_consulta_nem_avisa(github):
    updates.set_enabled(False)
    updates.check()
    assert github["consultas"] == 0
    db.set_setting(updates.KEY_LATEST, json.dumps({"version": _maior(__version__)}))
    assert updates.status() is None


def test_sem_internet_guarda_o_erro_e_mantem_o_ultimo_resultado(github):
    db.set_setting(updates.KEY_LATEST, json.dumps({"version": "9.9.9"}))
    github["resposta"] = httpx.ConnectError("sem rede")
    assert updates.check(force=True)["version"] == "9.9.9"
    assert updates.summary()["error"]


def test_sem_release_publicado(github):
    github["resposta"] = Resposta(404)
    assert updates.check(force=True) == {}
    assert updates.status() is None


def test_dispensar_vale_so_para_aquela_versao():
    nova = _maior(__version__)
    db.set_setting(updates.KEY_LATEST, json.dumps({"version": nova}))
    updates.dismiss(nova)
    assert updates.status() is None
    db.set_setting(updates.KEY_LATEST, json.dumps({"version": _maior(nova)}))
    assert updates.status() is not None


def test_faixa_aparece_em_todas_as_paginas_e_some_ao_dispensar(client):
    nova = _maior(__version__)
    db.set_setting(updates.KEY_LATEST, json.dumps({"version": nova, "url": "https://github.com/x"}))
    for pagina in ("/", "/contas", "/configuracoes"):
        assert f"Tabimoney {nova} disponível" in client.get(pagina).text
    r = client.post("/atualizacao/dispensar", data={"csrf_token": csrf(client), "version": nova, "back": "/contas"})
    assert r.url.path == "/contas" and "update-banner" not in r.text


def test_verificar_agora_pela_interface(client, github):
    r = client.post("/atualizacao/verificar", data={"csrf_token": csrf(client)})
    assert "versão mais recente" in r.text
    assert github["consultas"] == 1


@pytest.mark.parametrize("sistema, chip, rosetta, esperado", [
    ("win32", "AMD64", False, "windows"),
    ("darwin", "arm64", False, "mac-apple-silicon"),
    ("darwin", "x86_64", False, "mac-intel"),
    ("darwin", "x86_64", True, "mac-apple-silicon"),  # app Intel num Mac com chip Apple (Rosetta)
    ("linux", "x86_64", False, None),
])
def test_sufixo_do_sistema(monkeypatch, sistema, chip, rosetta, esperado):
    # troca só o que o módulo enxerga; mexer no sys.platform global afetaria o próprio pytest
    monkeypatch.setattr(updates, "sys", SimpleNamespace(platform=sistema))
    monkeypatch.setattr(updates, "platform", SimpleNamespace(machine=lambda: chip))
    monkeypatch.setattr(updates, "_rosetta", lambda: rosetta)
    assert updates.platform_suffix() == esperado
