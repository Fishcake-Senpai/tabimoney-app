"""Atualização com um clique (app/services/atualizador.py), com o GitHub e os processos simulados.

O executável de verdade é testado no CI (packaging/teste_atualizacao.py, no workflow Gerar executáveis); aqui os
"executáveis" são arquivos de texto numa pasta temporária, e a troca, a reversão e a limpeza mexem neles de verdade.
"""
from __future__ import annotations

import functools
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import __version__, db, launch
from app.services import atualizador, updates

from .conftest import avisos, csrf

ZIP_NOME = "Tabimoney-9.9.9-windows.zip"
BASE = "https://github.com/Fishcake-Senpai/tabimoney-app/releases/download/v9.9.9"
ROOT = Path(__file__).resolve().parents[1]


def _zip(conteudo: bytes = b"exe novo", nome: str = "Tabimoney.exe") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr(nome, conteudo)
        z.writestr("LEIA-ME.txt", "leia")
    return buffer.getvalue()


def _info(**extra) -> dict:
    return {"version": "9.9.9", "download_url": f"{BASE}/{ZIP_NOME}", "asset_name": ZIP_NOME, "size": 1000,
            "sums_url": f"{BASE}/SHA256SUMS.txt", **extra}


@pytest.fixture
def app_congelado(tmp_path, monkeypatch):
    """Um "Tabimoney.exe" numa pasta própria, visto pelo atualizador como o executável congelado que roda."""
    pasta = tmp_path / "app"
    pasta.mkdir()
    exe = pasta / "Tabimoney.exe"
    exe.write_bytes(b"exe velho")
    monkeypatch.setattr(atualizador, "sys", SimpleNamespace(platform="win32", frozen=True, executable=str(exe)))
    monkeypatch.setattr(atualizador, "_is_temporary", lambda _p: False)  # tmp_path fica na pasta temporária
    monkeypatch.setattr(atualizador, "_rename", functools.partial(atualizador._rename, timeout=0))
    return exe


@pytest.fixture
def github(monkeypatch):
    """Serve o zip e o SHA256SUMS.txt; `estado` deixa trocar o conteúdo e conta os pedidos."""
    estado = {"zip": _zip(), "somas": None, "hosts": []}

    def responder(request: httpx.Request) -> httpx.Response:
        estado["hosts"].append(request.url.host)
        if request.url.path.endswith(".zip"):
            return httpx.Response(200, content=estado["zip"])
        if request.url.path.endswith("SHA256SUMS.txt"):
            soma = estado["somas"] or hashlib.sha256(estado["zip"]).hexdigest()
            return httpx.Response(200, text=f"{soma}  {ZIP_NOME}\n{'0' * 64}  outro.zip\n")
        return httpx.Response(404)

    monkeypatch.setattr(atualizador, "_transport", httpx.MockTransport(responder))
    return estado


@pytest.fixture
def processos(monkeypatch):
    """Registra os processos que o atualizador abriria, sem abrir nada."""
    abertos: list[list[str]] = []

    def abrir(comando):
        abertos.append(comando)
        return SimpleNamespace(poll=lambda: 0, pid=0)

    monkeypatch.setattr(atualizador, "detached", abrir)
    monkeypatch.setattr(atualizador, "verificar_executavel", lambda exe, versao: None)
    return abertos


# ---------------------------------------------------------------- peças

def test_hash_esperado_vem_da_linha_do_arquivo():
    soma = "a" * 64
    assert atualizador.expected_hash(f"{'b' * 64}  outro.zip\n{soma} *{ZIP_NOME}\n", ZIP_NOME) == soma
    with pytest.raises(atualizador.UpdateError):
        atualizador.expected_hash("lixo\n", ZIP_NOME)
    with pytest.raises(atualizador.UpdateError, match="não tem"):
        atualizador.expected_hash(f"{'a' * 64}  outro.zip\n", ZIP_NOME)


@pytest.mark.parametrize("url, aceito", [
    ("https://github.com/x/releases/download/v1/a.zip", True),
    ("https://objects.githubusercontent.com/abc", True),
    ("https://release-assets.githubusercontent.com/abc", True),
    ("http://github.com/x", False),                       # sem HTTPS
    ("https://github.com.exemplo.com/x", False),
    ("https://githubusercontent.com.exemplo.com/x", False),
    ("http://127.0.0.1:8799/release.json", False),        # só no teste do CI (variável abaixo)
])
def test_so_baixa_do_github(url, aceito):
    assert atualizador._allowed(url) is aceito


def test_api_local_so_vale_em_127_0_0_1(monkeypatch):
    monkeypatch.setenv(updates.ENV_TEST_API, "http://exemplo.com/release.json")
    assert updates.local_test_api() is None and not updates.is_newer(__version__)
    monkeypatch.setenv(updates.ENV_TEST_API, "http://127.0.0.1:8799/release.json")
    assert updates.local_test_api() and updates.is_newer(__version__)  # a mesma versão conta como nova
    assert atualizador._allowed("http://127.0.0.1:8799/x.zip")


@pytest.mark.parametrize("porta, esperado", [("8766", "8766"), (None, "8765")])
def test_porta_do_app_vem_de_tabimoney_porta(porta, esperado):
    """packaging/teste_atualizacao.py roda o app em outra porta, sem fechar o Tabimoney do dia a dia."""
    ambiente = {chave: valor for chave, valor in os.environ.items() if chave != "TABIMONEY_PORTA"}
    if porta:
        ambiente["TABIMONEY_PORTA"] = porta
    saida = subprocess.run([sys.executable, "-c", "from app.launch import PORT; print(PORT)"],
                           capture_output=True, text=True, cwd=ROOT, env=ambiente, check=True).stdout
    assert saida.strip() == esperado


def test_download_recusa_arquivo_maior_que_o_limite(tmp_path, monkeypatch):
    monkeypatch.setattr(atualizador, "MAX_BYTES", 10)
    monkeypatch.setattr(atualizador, "_transport",
                        httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 50)))
    with pytest.raises(atualizador.UpdateError, match="maior"):
        atualizador.download(f"{BASE}/{ZIP_NOME}", tmp_path / "a.zip")


def test_download_corta_quando_passa_do_limite_sem_tamanho_anunciado(tmp_path, monkeypatch):
    """Sem Content-Length (transferência em pedaços), o limite vale do mesmo jeito."""
    monkeypatch.setattr(atualizador, "MAX_BYTES", 10)
    pedacos = (b"x" * 4 for _ in range(5))
    monkeypatch.setattr(atualizador, "_transport", httpx.MockTransport(lambda r: httpx.Response(200, content=pedacos)))
    with pytest.raises(atualizador.UpdateError, match="maior"):
        atualizador.download(f"{BASE}/{ZIP_NOME}", tmp_path / "a.zip")


def test_redirecionamento_para_fora_do_github_e_recusado(tmp_path, monkeypatch):
    def responder(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"location": "https://exemplo.com/malicioso.zip"})
        return httpx.Response(200, content=b"x")

    monkeypatch.setattr(atualizador, "_transport", httpx.MockTransport(responder))
    with pytest.raises(atualizador.UpdateError, match="inesperado"):
        atualizador.download(f"{BASE}/{ZIP_NOME}", tmp_path / "a.zip")


def test_extrai_so_o_executavel(tmp_path):
    arquivo = tmp_path / "a.zip"
    arquivo.write_bytes(_zip(b"novo"))
    assert atualizador.extract(arquivo, tmp_path).read_bytes() == b"novo"
    assert not (tmp_path / "LEIA-ME.txt").exists()
    arquivo.write_bytes(_zip(nome="../Tabimoney.exe"))
    with pytest.raises(atualizador.UpdateError, match="não tem"):
        atualizador.extract(arquivo, tmp_path)
    arquivo.write_bytes(b"isto nao e zip")
    with pytest.raises(atualizador.UpdateError, match="zip válido"):
        atualizador.extract(arquivo, tmp_path)


def test_troca_e_desfaz_se_o_segundo_renome_falhar(app_congelado):
    exe = app_congelado
    novo, anterior = exe.with_name("Tabimoney.novo.exe"), exe.with_name("Tabimoney.anterior.exe")
    novo.write_bytes(b"exe novo")
    atualizador.swap(exe, novo, anterior)
    assert exe.read_bytes() == b"exe novo" and anterior.read_bytes() == b"exe velho" and not novo.exists()

    anterior.unlink()
    with pytest.raises(OSError):
        atualizador.swap(exe, exe.with_name("nao-existe.exe"), anterior)
    assert exe.read_bytes() == b"exe novo" and not anterior.exists()  # nunca fica sem o executável


def test_nome_livre_quando_o_anterior_esta_preso(app_congelado, monkeypatch):
    preso = app_congelado.with_name("Tabimoney.anterior.exe")
    preso.write_bytes(b"preso")
    original = type(preso).unlink

    def unlink(self, *args, **kwargs):
        if self == preso:
            raise PermissionError("em uso")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(preso), "unlink", unlink)
    assert atualizador._free_name(preso).name == "Tabimoney.anterior-2.exe"


# ---------------------------------------------------------------- dá para atualizar?

def test_da_para_atualizar_num_exe_comum(app_congelado):
    assert atualizador.blocker(_info()) is None
    assert atualizador.availability(_info()) == {"auto": True, "motivo": None}


@pytest.mark.parametrize("ajuste, trecho", [
    (lambda m, exe: m.setattr(atualizador, "sys", SimpleNamespace(platform="win32", executable=str(exe))), "código"),
    (lambda m, exe: m.setattr(atualizador, "sys", SimpleNamespace(platform="darwin", frozen=True,
                                                                  executable=str(exe))), "Mac"),
    (lambda m, exe: m.setattr(atualizador, "_is_temporary", lambda _p: True), "pasta sua"),
    (lambda m, exe: m.setattr(atualizador, "_writable", lambda _p: False), "gravar"),
])
def test_quando_nao_da_o_aviso_volta_ao_baixar(app_congelado, monkeypatch, ajuste, trecho):
    ajuste(monkeypatch, app_congelado)
    assert trecho in atualizador.blocker(_info())


def test_versao_que_ja_foi_revertida_nao_tenta_de_novo(app_congelado):
    atualizador._save(estado="revertida", de=__version__, para="9.9.9")
    assert "não abriu" in atualizador.blocker(_info())
    assert atualizador.blocker(_info(version="9.9.10")) is None


def test_versao_igual_ou_menor_nao_atualiza(app_congelado):
    assert "mais recente" in atualizador.blocker(_info(version=__version__))
    assert "mais recente" in atualizador.blocker(_info(version="0.0.1"))


def test_start_recusa_versao_que_nao_e_mais_nova(app_congelado, monkeypatch):
    monkeypatch.setattr(updates, "check", lambda force=False: _info(version=__version__))
    with pytest.raises(atualizador.UpdateError, match="mais recente"):
        atualizador.start(lambda: None)
    assert atualizador.marker() == {}  # nada foi gravado


def test_falta_espaco_no_disco_volta_ao_baixar(app_congelado, monkeypatch):
    monkeypatch.setattr(atualizador.shutil, "disk_usage", lambda _p: SimpleNamespace(free=100, total=0, used=0))
    assert "espaço em disco" in atualizador.blocker(_info(size=1000))
    monkeypatch.setattr(atualizador.shutil, "disk_usage", lambda _p: SimpleNamespace(free=10**12, total=0, used=0))
    assert atualizador.blocker(_info(size=1000)) is None


def test_pasta_gravavel(tmp_path):
    assert atualizador._writable(tmp_path) is True
    assert atualizador._writable(tmp_path / "nao-existe") is False


def test_release_sem_arquivo_para_este_computador(app_congelado):
    assert "não tem o arquivo" in atualizador.blocker(_info(download_url=None))


def test_erro_ao_conferir_a_pasta_volta_ao_baixar(app_congelado, monkeypatch):
    def quebrar(_info):
        raise OSError("disco ocupado")

    monkeypatch.setattr(atualizador, "blocker", quebrar)
    aviso = atualizador.availability(_info())
    assert aviso["auto"] is False and "disco ocupado" in aviso["motivo"]


def test_caminho_temporario():
    assert atualizador._is_temporary(atualizador.Path(atualizador.tempfile.gettempdir()) / "x" / "Tabimoney.exe")
    assert atualizador._is_temporary(atualizador.Path("/private/var/AppTranslocation/X/d/Tabimoney.app"))


def test_pasta_temporaria_e_comparada_pelo_caminho_real(tmp_path, monkeypatch):
    """No Mac, /var é um link para /private/var: a pasta temporária aparece pelos dois nomes. E uma pasta chamada
    'temp' fora da temporária não conta."""
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("sem permissão para criar link simbólico nesta máquina")
    monkeypatch.setattr(atualizador.tempfile, "gettempdir", lambda: str(link))
    assert atualizador._is_temporary(link / "x" / "Tabimoney.exe")
    assert atualizador._is_temporary(real / "x" / "Tabimoney.exe")
    assert not atualizador._is_temporary(tmp_path / "Projetos" / "temp" / "Tabimoney.exe")


# ---------------------------------------------------------------- o servidor antigo

def test_atualizacao_completa_ate_o_vigia(app_congelado, github, processos):
    exe = app_congelado
    atualizador._save(estado="baixando", de=__version__, para="9.9.9", pid_antigo=1, exe=str(exe))
    encerrou = []
    atualizador.run(_info(), lambda: encerrou.append(True))

    estado = atualizador.marker()
    anterior = exe.with_name("Tabimoney.anterior.exe")
    assert estado["estado"] == "reiniciando" and estado["progresso"] == 1.0
    assert exe.read_bytes() == b"exe novo" and anterior.read_bytes() == b"exe velho"
    assert processos == [[str(anterior), "--vigiar-atualizacao"]] and encerrou == [True]
    assert atualizador.Path(estado["backup"]).is_file()
    assert set(github["hosts"]) == {"github.com"}


def test_hash_que_nao_bate_nao_troca_nada(app_congelado, github, processos):
    github["somas"] = "f" * 64
    atualizador._save(estado="baixando", para="9.9.9")
    atualizador.run(_info(), lambda: None)
    estado = atualizador.marker()
    assert estado["estado"] == "falhou" and "não confere" in estado["motivo"]
    assert [p.name for p in app_congelado.parent.iterdir()] == ["Tabimoney.exe"]
    assert app_congelado.read_bytes() == b"exe velho" and processos == []
    assert not (db.data_dir() / atualizador.STAGING / "9.9.9").exists()


def test_sem_internet_no_meio(app_congelado, processos):
    atualizador.run(_info(), lambda: None)  # o conftest deixa o transporte sem rede
    assert atualizador.marker()["motivo"] == "A conexão caiu no meio do download."


def test_executavel_novo_que_nao_responde_a_versao(app_congelado, github, processos, monkeypatch):
    def recusar(exe, versao):
        raise atualizador.UpdateError("O executável novo respondeu a versão 1.0.0, não a 9.9.9.")

    monkeypatch.setattr(atualizador, "verificar_executavel", recusar)
    atualizador.run(_info(), lambda: None)
    assert "1.0.0" in atualizador.marker()["motivo"] and app_congelado.read_bytes() == b"exe velho"


def test_verificar_executavel_pega_arquivo_ausente_versao_errada_e_travamento(tmp_path, monkeypatch):
    with pytest.raises(atualizador.UpdateError, match="antivírus"):
        atualizador.verificar_executavel(tmp_path / "nao-existe.exe", "9.9.9")
    exe = tmp_path / "Tabimoney.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(atualizador.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="1.0.0\n"))
    with pytest.raises(atualizador.UpdateError, match="1.0.0"):
        atualizador.verificar_executavel(exe, "9.9.9")
    monkeypatch.setattr(atualizador.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="9.9.9\n"))
    atualizador.verificar_executavel(exe, "9.9.9")  # a versão certa passa sem erro

    def travar(*_a, **_k):
        raise subprocess.TimeoutExpired("Tabimoney.exe", 1)

    monkeypatch.setattr(atualizador.subprocess, "run", travar)
    with pytest.raises(atualizador.UpdateError, match="não abriu"):
        atualizador.verificar_executavel(exe, "9.9.9")


def test_erro_do_github_no_download_vira_mensagem_clara(app_congelado, processos, monkeypatch):
    monkeypatch.setattr(atualizador, "_transport", httpx.MockTransport(lambda r: httpx.Response(503)))
    atualizador._save(estado="baixando", para="9.9.9")
    atualizador.run(_info(), lambda: None)
    assert "erro 503" in atualizador.marker()["motivo"]
    assert app_congelado.read_bytes() == b"exe velho" and processos == []


def test_se_o_vigia_nao_abre_desfaz_a_troca(app_congelado, github, processos, monkeypatch):
    def falhar(_comando):
        raise OSError("acesso negado")

    monkeypatch.setattr(atualizador, "detached", falhar)
    atualizador.run(_info(), lambda: None)
    assert atualizador.marker()["estado"] == "falhou"
    assert app_congelado.read_bytes() == b"exe velho"


def test_nao_comeca_duas_vezes(app_congelado, monkeypatch):
    monkeypatch.setattr(updates, "check", lambda force=False: _info())
    monkeypatch.setattr(atualizador, "run", lambda info, stop: None)
    atualizador.start(lambda: None)
    assert atualizador.marker()["estado"] == "baixando"
    with pytest.raises(atualizador.UpdateError, match="andamento"):
        atualizador.start(lambda: None)


def test_release_sem_sha256sums_nao_comeca(app_congelado, monkeypatch):
    monkeypatch.setattr(updates, "check", lambda force=False: _info(sums_url=None))
    with pytest.raises(atualizador.UpdateError, match="SHA256SUMS"):
        atualizador.start(lambda: None)


def test_em_andamento_parado_ha_muito_vira_falha():
    atualizador._save(estado="baixando", para="9.9.9")
    assert atualizador.current()["estado"] == "baixando"
    dados = atualizador.marker()
    dados["atualizado_em"] = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
    atualizador.marker_path().write_text(json.dumps(dados), encoding="utf-8")
    assert atualizador.current()["estado"] == "falhou"


def test_em_andamento_com_data_ilegivel_vira_falha():
    atualizador._save(estado="baixando", para="9.9.9")
    dados = atualizador.marker()
    dados["atualizado_em"] = "nao-e-data"
    atualizador.marker_path().write_text(json.dumps(dados), encoding="utf-8")
    assert atualizador.current()["estado"] == "falhou"


def test_gravar_o_marcador_tenta_de_novo_se_o_windows_segurar_o_arquivo(monkeypatch):
    trocas = []
    original = atualizador.os.replace

    def travado_uma_vez(origem, destino):
        trocas.append(1)
        if len(trocas) == 1:
            raise PermissionError("em uso")
        return original(origem, destino)

    monkeypatch.setattr(atualizador.os, "replace", travado_uma_vez)
    monkeypatch.setattr(atualizador.time, "sleep", lambda _s: None)
    atualizador._save(estado="baixando")
    assert len(trocas) == 2 and atualizador.marker()["estado"] == "baixando"


# ---------------------------------------------------------------- o vigia

@pytest.fixture
def troca_feita(app_congelado, monkeypatch, processos):
    """Como o servidor antigo deixa as coisas: exe novo no lugar, anterior ao lado, backup e marcador."""
    exe = app_congelado
    anterior = exe.with_name("Tabimoney.anterior.exe")
    exe.rename(anterior)
    exe.write_bytes(b"exe novo")
    db.set_setting("antes", "1")
    backup = db.create_backup()
    db.set_setting("depois", "1")  # o que a versão nova (ou um agente) gravou depois do backup
    atualizador._save(estado="reiniciando", de=__version__, para="9.9.9", pid_antigo=111, exe=str(exe),
                      anterior=str(anterior), backup=str(backup))
    monkeypatch.setattr(atualizador, "_setup_log", lambda: None)
    monkeypatch.setattr(atualizador, "NEW_UP_TIMEOUT", 0.3)
    monkeypatch.setattr(launch, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(launch, "_port_open", lambda: False)
    monkeypatch.setattr(launch, "_kill", lambda pid: None)
    monkeypatch.setattr(launch, "_read_lock", lambda: None)
    return exe, anterior


def test_vigia_confirma_a_versao_nova(troca_feita, processos, monkeypatch):
    exe, _ = troca_feita
    monkeypatch.setattr(atualizador, "new_is_up", lambda estado: True)
    atualizador.watch()
    assert atualizador.marker()["estado"] == "concluida"
    assert processos == [[str(exe), "--apos-atualizacao"]]
    assert db.get_setting("depois") == "1"


def test_vigia_desfaz_se_a_versao_nova_nao_sobe(troca_feita, processos, monkeypatch):
    exe, anterior = troca_feita
    monkeypatch.setattr(atualizador, "new_is_up", lambda estado: False)
    atualizador.watch()
    estado = atualizador.marker()
    assert estado["estado"] == "revertida" and "não abriu" in estado["motivo"]
    assert exe.read_bytes() == b"exe velho" and not anterior.exists()
    assert exe.with_name("Tabimoney.falhou.exe").read_bytes() == b"exe novo"
    assert db.get_setting("antes") == "1" and db.get_setting("depois") == ""  # base de volta ao backup
    assert processos[-1] == [str(exe), "--apos-atualizacao"]  # reabre o antigo


def test_versao_nova_no_ar_confere_pid_versao_e_caminho(troca_feita, monkeypatch):
    exe, _ = troca_feita
    estado = atualizador.marker()
    trava = {"pid": 222, "version": "9.9.9", "exe": str(exe)}
    monkeypatch.setattr(launch, "_port_open", lambda: True)
    monkeypatch.setattr(launch, "_read_lock", lambda: trava)
    assert atualizador.new_is_up(estado)
    for errado in ({"pid": 111}, {"version": __version__}, {"exe": str(exe.with_name("outro.exe"))}):
        monkeypatch.setattr(launch, "_read_lock", lambda e=errado: {**trava, **e})
        assert not atualizador.new_is_up(estado)


def test_vigia_mata_o_antigo_que_nao_sai(troca_feita, processos, monkeypatch):
    mortos = []
    monkeypatch.setattr(atualizador, "OLD_EXIT_TIMEOUT", 0.1)
    monkeypatch.setattr(launch, "_pid_alive", lambda pid: pid == 111)  # o servidor antigo ficou vivo
    monkeypatch.setattr(launch, "_kill", lambda pid: mortos.append(pid))
    monkeypatch.setattr(atualizador, "new_is_up", lambda estado: True)
    atualizador.watch()
    assert mortos == [111] and atualizador.marker()["estado"] == "concluida"


def test_revertida_derruba_a_versao_nova_que_ficou_no_ar_sem_confirmar(troca_feita, processos, monkeypatch):
    mortos = []
    monkeypatch.setattr(launch, "_read_lock", lambda: {"pid": 333, "token": "t"})
    monkeypatch.setattr(launch, "_pid_alive", lambda pid: pid == 333)
    monkeypatch.setattr(launch, "_kill", lambda pid: mortos.append(pid))
    monkeypatch.setattr(atualizador, "new_is_up", lambda estado: False)
    atualizador.watch()
    assert mortos == [333] and atualizador.marker()["estado"] == "revertida"


def test_se_nao_da_para_voltar_o_app_antigo_avisa_onde_ele_esta(troca_feita, processos, monkeypatch):
    _exe, anterior = troca_feita
    monkeypatch.setattr(atualizador, "new_is_up", lambda estado: False)

    def sem_permissao(*_args):
        raise PermissionError("em uso")

    monkeypatch.setattr(atualizador, "swap", sem_permissao)
    atualizador.watch()
    estado = atualizador.marker()
    assert estado["estado"] == "falhou" and str(anterior) in estado["motivo"]


def test_se_a_base_nao_volta_o_executavel_volta_e_o_aviso_aponta_o_backup(troca_feita, processos, monkeypatch):
    exe, _ = troca_feita
    monkeypatch.setattr(atualizador, "new_is_up", lambda estado: False)

    def falhar(_backup):
        raise sqlite3.OperationalError("base em uso")

    monkeypatch.setattr(atualizador, "restore", falhar)
    atualizador.watch()
    estado = atualizador.marker()
    assert estado["estado"] == "revertida" and "A base não foi restaurada" in estado["motivo"]
    assert exe.read_bytes() == b"exe velho"


def test_vigia_grava_o_log_da_atualizacao(monkeypatch):
    import logging

    raiz = logging.getLogger()
    handlers, nivel = list(raiz.handlers), raiz.level
    try:
        atualizador._setup_log()
        logging.getLogger("tabimoney.atualizador").info("linha de teste")
        for handler in raiz.handlers:
            handler.flush()
        assert "linha de teste" in (db.data_dir() / "logs" / "atualizacao.log").read_text(encoding="utf-8")
    finally:
        for handler in raiz.handlers:
            if handler not in handlers:
                handler.close()
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)


def test_vigia_sem_atualizacao_em_andamento_nao_faz_nada(monkeypatch, processos):
    monkeypatch.setattr(atualizador, "_setup_log", lambda: None)
    atualizador.watch()
    assert processos == []


# ---------------------------------------------------------------- a versão nova

def test_aviso_de_atualizado_aparece_uma_vez():
    atualizador._save(estado="concluida", de="0.1.0", para=__version__)
    tipo, texto = atualizador.pending_notice()
    assert tipo == "success" and __version__ in texto
    assert atualizador.pending_notice() is None


def test_aviso_de_atualizado_sem_erro_mesmo_se_a_ia_nao_responder(monkeypatch):
    from app.mcp_server import instalar

    def quebrar():
        raise RuntimeError("config ilegível")

    atualizador._save(estado="concluida", de="0.1.0", para=__version__)
    monkeypatch.setattr(instalar, "situacao", quebrar)
    tipo, texto = atualizador.pending_notice()
    assert tipo == "success" and "reinicie" not in texto


def test_aviso_de_revertido_so_na_versao_antiga():
    atualizador._save(estado="revertida", de="0.1.0", para="9.9.9", motivo="A versão 9.9.9 não abriu.")
    assert atualizador.pending_notice() is None  # esta não é a 0.1.0
    atualizador._save(de=__version__)
    tipo, texto = atualizador.pending_notice()
    assert tipo == "warning" and "Voltamos" in texto


def test_limpeza_apaga_as_sobras_so_depois_de_terminar(app_congelado):
    pasta = app_congelado.parent
    for nome in ("Tabimoney.anterior.exe", "Tabimoney.anterior-2.exe", "Tabimoney.falhou.exe", "Tabimoney.novo.exe"):
        (pasta / nome).write_bytes(b"x")
    (db.data_dir() / atualizador.STAGING / "9.9.9").mkdir(parents=True)
    atualizador._save(estado="reiniciando", para="9.9.9")
    assert atualizador.cleanup() is False and len(list(pasta.iterdir())) == 5  # o vigia ainda pode precisar
    atualizador._save(estado="concluida")
    assert atualizador.cleanup() is True
    assert [p.name for p in pasta.iterdir()] == ["Tabimoney.exe"]
    assert not (db.data_dir() / atualizador.STAGING).exists()


def test_limpeza_nao_acaba_com_arquivo_preso(app_congelado, monkeypatch):
    preso = app_congelado.parent / "Tabimoney.anterior.exe"
    preso.write_bytes(b"x")
    atualizador._save(estado="concluida", para=__version__)
    original = Path.unlink

    def travado(self, *args, **kwargs):
        if self == preso:
            raise PermissionError("em uso")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", travado)
    assert atualizador.cleanup() is False and preso.exists()
    monkeypatch.setattr(Path, "unlink", original)
    assert atualizador.cleanup() is True and not preso.exists()


def test_janitor_para_quando_nao_sobra_nada(app_congelado):
    sobra = app_congelado.parent / "Tabimoney.falhou.exe"
    sobra.write_bytes(b"x")
    atualizador._save(estado="concluida", para=__version__)
    rodadas = []

    class Relogio:
        def wait(self, _segundos):
            rodadas.append(1)
            return False  # nada de parar: o janitor sai sozinho depois da limpeza

    atualizador.janitor(Relogio())
    assert len(rodadas) == 1 and not sobra.exists()


def test_janitor_sai_se_o_app_for_fechado(app_congelado):
    sobra = app_congelado.parent / "Tabimoney.falhou.exe"
    sobra.write_bytes(b"x")

    class Fechou:
        def wait(self, _segundos):
            return True

    atualizador.janitor(Fechou())
    assert sobra.exists()  # saiu antes de limpar


def test_janitor_nao_derruba_o_app_se_a_limpeza_falhar(monkeypatch):
    def quebrar():
        raise RuntimeError("disco sumiu")

    monkeypatch.setattr(atualizador, "cleanup", quebrar)

    class Relogio:
        def __init__(self):
            self.rodadas = 0

        def wait(self, _segundos):
            self.rodadas += 1
            return self.rodadas > 3

    relogio = Relogio()
    atualizador.janitor(relogio)  # não levanta exceção
    assert relogio.rodadas == 4


@pytest.mark.parametrize("flag, chamada", [("--apos-atualizacao", "abrir"), ("--vigiar-atualizacao", "vigiar")])
def test_flags_do_executavel(monkeypatch, flag, chamada):
    feito = []
    monkeypatch.setattr(launch, "open_app", lambda open_browser=True: feito.append(("abrir", open_browser)))
    monkeypatch.setattr(atualizador, "watch", lambda: feito.append(("vigiar", None)))
    launch.main([flag])
    assert feito == [(chamada, False if chamada == "abrir" else None)]


@pytest.mark.parametrize("flag, abre_aba", [("--apos-atualizacao", False), (None, True)])
def test_depois_da_atualizacao_nao_abre_aba_nova(monkeypatch, flag, abre_aba):
    """A página de progresso já está aberta: reabrir com --apos-atualizacao não pode abrir outra aba."""
    abas = []
    monkeypatch.setattr(launch, "FROZEN", False)
    monkeypatch.setattr(launch, "stop_previous", lambda say=print: None)
    monkeypatch.setattr(launch, "_port_open", lambda: True)
    monkeypatch.setattr(launch, "_has_console", lambda: False)
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(launch.webbrowser, "open", lambda *a, **k: abas.append(a))
    launch.main([flag] if flag else [])
    assert bool(abas) is abre_aba


def test_resumo_da_ultima_tentativa():
    assert atualizador.summary() is None
    atualizador._save(estado="concluida", de="0.1.0", para="0.2.0")
    assert "Atualizado da 0.1.0 para a 0.2.0" in atualizador.summary()
    atualizador._save(estado="falhou", para="0.2.0", motivo="Sem internet.")
    assert "não deu certo" in atualizador.summary() and "Sem internet." in atualizador.summary()
    atualizador._save(estado="baixando", para="0.2.0")
    assert "Atualizando para a 0.2.0" in atualizador.summary()


def test_aviso_de_atualizado_lembra_de_reiniciar_o_agente(monkeypatch):
    from app.mcp_server import instalar

    atualizador._save(estado="concluida", de="0.1.0", para=__version__)
    monkeypatch.setattr(instalar, "situacao", lambda: [{"cliente": "claude-code", "conectado": True}])
    assert "reinicie o agente" in atualizador.pending_notice()[1]


def test_aviso_de_atualizado_sem_agente_conectado(monkeypatch):
    from app.mcp_server import instalar

    atualizador._save(estado="concluida", de="0.1.0", para=__version__)
    monkeypatch.setattr(instalar, "situacao", lambda: [{"cliente": "claude-code", "conectado": False}])
    assert "reinicie" not in atualizador.pending_notice()[1]


@pytest.mark.parametrize("estado", ["baixando", "conferindo", "preparando", "trocando", "reiniciando", "concluida",
                                    "revertida", "falhou"])
def test_estado_e_pagina_de_progresso_em_cada_etapa(client, estado):
    atualizador._save(estado=estado, de=__version__, para="9.9.9", motivo="motivo de teste")
    dados = client.get("/atualizacao/estado").json()
    assert dados["estado"] == estado and dados["motivo"] == "motivo de teste" and dados["versao_em_uso"] == __version__
    assert client.get("/atualizacao").status_code == 200


# ---------------------------------------------------------------- interface

@pytest.fixture
def aviso(monkeypatch):
    """Versão nova conhecida, com o app rodando como executável."""
    db.set_setting(updates.KEY_LATEST, json.dumps({**_info(), "url": "https://github.com/x"}))
    monkeypatch.setattr(updates, "sys", SimpleNamespace(frozen=True))
    monkeypatch.setattr(atualizador, "_availability_cache", {})


def test_aviso_oferece_atualizar_agora(client, aviso, monkeypatch):
    monkeypatch.setattr(atualizador, "blocker", lambda info: None)
    pagina = client.get("/").text
    assert "Atualizar agora" in pagina and 'action="/atualizacao/instalar"' in pagina
    assert "ou baixe manualmente" in pagina and "(0 MB)" not in pagina
    assert "Atualizar para a 9.9.9" in client.get("/configuracoes").text


def test_aviso_volta_ao_baixar_com_o_motivo(client, aviso, monkeypatch):
    monkeypatch.setattr(atualizador, "blocker", lambda info: "A pasta do Tabimoney não deixa gravar arquivos.")
    pagina = client.get("/").text
    assert "Atualizar agora" not in pagina and ">Baixar</a>" in pagina
    assert "não deixa gravar" in pagina


def test_instalar_pela_interface(client, monkeypatch):
    from app import main

    comecou = []
    monkeypatch.setattr(main.app.state, "server", SimpleNamespace(should_exit=False), raising=False)
    monkeypatch.setattr(atualizador, "start", lambda parar: comecou.append(parar))
    r = client.post("/atualizacao/instalar", data={"csrf_token": csrf(client), "back": "/"})
    assert r.url.path == "/atualizacao" and len(comecou) == 1
    comecou[0]()
    assert main.app.state.server.should_exit is True


def test_instalar_mostra_o_motivo_quando_nao_da(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main.app.state, "server", SimpleNamespace(should_exit=False), raising=False)

    def recusar(_parar):
        raise atualizador.UpdateError("Já tem uma atualização em andamento.")

    monkeypatch.setattr(atualizador, "start", recusar)
    r = client.post("/atualizacao/instalar", data={"csrf_token": csrf(client), "back": "/contas"})
    assert r.url.path == "/contas"
    assert ("warning", "Não deu para atualizar: Já tem uma atualização em andamento.") in avisos(r.text)


def test_instalar_aberto_pelo_terminal(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main.app.state, "server", None, raising=False)
    r = client.post("/atualizacao/instalar", data={"csrf_token": csrf(client)})
    assert any("git pull" in texto for _tipo, texto in avisos(r.text))


def test_instalar_exige_csrf_e_fica_desligado_na_demo(client):
    assert client.post("/atualizacao/instalar", data={"csrf_token": "errado"}).status_code in (400, 403)
    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    r = client.post("/atualizacao/instalar", data={"csrf_token": csrf(client)})
    assert any("demonstração" in texto for _tipo, texto in avisos(r.text))


def test_pagina_de_progresso_e_estado(client):
    vazia = client.get("/atualizacao")
    assert "Nenhuma atualização em andamento" in vazia.text
    assert "connect-src 'self'" in vazia.headers["content-security-policy"]
    assert "connect-src 'none'" in client.get("/").headers["content-security-policy"]

    atualizador._save(estado="baixando", de=__version__, para="9.9.9", progresso=0.5, baixado=5, total=10)
    assert "Atualizando para a 9.9.9" in client.get("/atualizacao").text
    estado = client.get("/atualizacao/estado").json()
    assert estado == {"estado": "baixando", "de": __version__, "para": "9.9.9", "progresso": 0.5, "baixado": 5,
                      "total": 10, "motivo": None, "versao_em_uso": __version__}


def test_resultado_aparece_como_aviso_e_nas_configuracoes(client):
    atualizador._save(estado="concluida", de="0.1.0", para=__version__)
    pagina = client.get("/configuracoes").text
    assert f"Tabimoney atualizado para a {__version__}" in pagina
    assert f"Atualizado da 0.1.0 para a {__version__}" in pagina
    assert f"Tabimoney atualizado para a {__version__}" not in client.get("/").text  # uma vez só


def test_verificacao_guarda_tamanho_e_somas(monkeypatch):
    release = {"tag_name": "v9.9.9", "html_url": "https://github.com/x", "assets": [
        {"name": ZIP_NOME, "size": 123, "browser_download_url": f"{BASE}/{ZIP_NOME}"},
        {"name": "SHA256SUMS.txt", "browser_download_url": f"{BASE}/SHA256SUMS.txt"},
    ]}
    monkeypatch.setattr(updates, "platform_suffix", lambda: "windows")
    monkeypatch.setattr(updates.httpx, "get", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: release, raise_for_status=lambda: None))
    info = updates.check(force=True)
    assert info["size"] == 123 and info["asset_name"] == ZIP_NOME and info["sums_url"].endswith("SHA256SUMS.txt")
