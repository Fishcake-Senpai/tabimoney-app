"""Teste do executável no CI: a atualização com um clique de ponta a ponta, com um Release falso nesta máquina.

    python packaging/teste_atualizacao.py EXE PASTA_DO_RELEASE ZIP VERSAO
    python packaging/teste_atualizacao.py --reverter EXE PASTA_DO_RELEASE ZIP VERSAO

EXE é uma cópia do executável gerado, numa pasta que não seja temporária (o app recusa atualizar de %TEMP%).
PASTA_DO_RELEASE tem o ZIP com o mesmo executável. O script publica release.json e SHA256SUMS.txt num servidor HTTP
local e abre o app com TABIMONEY_ATUALIZACAO_API apontando para ele (só aceito em 127.0.0.1; ali a mesma versão conta
como nova). A pasta de dados e as configurações de IA ficam numa pasta temporária do próprio teste: nunca tocam nos
dados de quem roda.

Sem --reverter, clica em "Atualizar agora" pela interface e confere a troca, o backup, a reabertura e a limpeza.
Com --reverter, a versão nova não consegue subir: o script ocupa a porta do app assim que o antigo sai. Confere que o
vigia desfez a troca (executável original de volta, base restaurada do backup), que o app antigo voltou com o aviso
de "não abriu" e que a tela não oferece a mesma versão de novo.

A porta é a do launcher (TABIMONEY_PORTA, padrão 8765). Para rodar com o Tabimoney do dia a dia aberto, use outra:
    TABIMONEY_PORTA=8766 python packaging/teste_atualizacao.py ...
Se a porta estiver ocupada, o script para sem mexer em nada.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.launch import PORT, URL, _pid_alive, _port_open, _read_lock  # noqa: E402
from app.services import atualizador  # noqa: E402

RELEASE_PORT = 8799
ESTADOS_FINAIS = ("concluida", "revertida", "falhou")


def esperar(condicao, segundos: float, o_que: str):
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        resultado = condicao()
        if resultado:
            return resultado
        time.sleep(0.5)
    raise SystemExit(f"FALHOU: {o_que} (esperou {segundos:.0f} s)")


def conferir(verificacoes: list[tuple[bool, str]]) -> None:
    falhas = [texto for ok, texto in verificacoes if not ok]
    if falhas:
        raise SystemExit("FALHOU:\n  - " + "\n  - ".join(falhas))


def sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def isolar() -> Path:
    """Pastas de dados e de configurações de IA só deste teste: o app grava e lê ali, nunca no computador de quem
    roda. Tem que rodar antes de qualquer chamada que procure a pasta de dados."""
    base = Path(tempfile.mkdtemp(prefix="tabimoney-teste-"))
    casa = base / "casa"
    pastas = {
        "LOCALAPPDATA": base / "localappdata", "APPDATA": base / "appdata", "USERPROFILE": casa, "HOME": casa,
        "XDG_DATA_HOME": base / "xdg", "XDG_CONFIG_HOME": base / "xdg-config",
    }
    for pasta in pastas.values():
        pasta.mkdir(parents=True, exist_ok=True)
    os.environ.update({chave: str(pasta) for chave, pasta in pastas.items()})
    os.environ.pop("CODEX_HOME", None)
    return base


def porta_livre() -> None:
    if _port_open():
        raise SystemExit(f"A porta {PORT} está ocupada: feche o Tabimoney aberto ou use outra com TABIMONEY_PORTA. "
                         "Nada foi mexido.")


class _Quieto(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass


def publicar_release(pasta: Path, zip_nome: str, versao: str) -> tuple[str, http.server.ThreadingHTTPServer]:
    """Publica um Release falso num servidor local. Devolve a URL da API e o servidor (para desligar no fim)."""
    zip_path = pasta / zip_nome
    (pasta / "SHA256SUMS.txt").write_text(f"{sha256(zip_path)}  {zip_nome}\n", encoding="utf-8")
    base = f"http://127.0.0.1:{RELEASE_PORT}"
    release = {"tag_name": f"v{versao}", "html_url": base, "published_at": "2026-01-01T00:00:00Z", "assets": [
        {"name": zip_nome, "size": zip_path.stat().st_size, "browser_download_url": f"{base}/{zip_nome}"},
        {"name": "SHA256SUMS.txt", "browser_download_url": f"{base}/SHA256SUMS.txt"},
    ]}
    (pasta / "release.json").write_text(json.dumps(release), encoding="utf-8")
    servidor = http.server.ThreadingHTTPServer(
        ("127.0.0.1", RELEASE_PORT), functools.partial(_Quieto, directory=str(pasta)))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return f"{base}/release.json", servidor


def subir_app_antigo(exe: Path, api: str) -> int:
    """Sobe o app antigo como o launcher sobe o servidor, apontando a atualização para o Release falso."""
    env = dict(os.environ, TABIMONEY_ATUALIZACAO_API=api)
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    subprocess.Popen([str(exe), "--servidor"], env=env, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    esperar(_port_open, 90, "o app antigo subir")
    return _read_lock()["pid"]


def pedir_atualizacao(cliente: httpx.Client) -> None:
    """Faz pela interface o que a pessoa faria: verificar, ver o botão Atualizar agora e clicar nele."""
    token = re.search(r'name="csrf_token" value="([^"]+)"', cliente.get("/configuracoes").text).group(1)
    cliente.post("/atualizacao/verificar", data={"csrf_token": token})
    pagina = cliente.get("/configuracoes").text
    if "Atualizar agora" not in pagina:
        motivo = re.search(r'class="update-why">([^<]*)<', pagina)
        raise SystemExit(f"FALHOU: o aviso não ofereceu Atualizar agora ({motivo.group(1) if motivo else '?'})")
    resposta = cliente.post("/atualizacao/instalar", data={"csrf_token": token, "back": "/"})
    assert resposta.url.path == "/atualizacao", f"esperava a página de progresso, veio {resposta.url}"
    print("Atualizar agora: clicado; acompanhando o progresso")


def estado_do_app(cliente: httpx.Client) -> dict | None:
    try:
        return cliente.get("/atualizacao/estado").json()
    except (httpx.HTTPError, ValueError):
        return None  # o app está reiniciando


def acompanhar(cliente: httpx.Client) -> dict:
    """Espera a atualização terminar, mostrando cada etapa. Devolve o estado final."""
    vistos: list[str] = []

    def terminou():
        s = estado_do_app(cliente)
        atual = s["estado"] if s else "(reiniciando)"
        if not vistos or vistos[-1] != atual:
            vistos.append(atual)
            print("  estado:", atual, (s or {}).get("motivo") or "")
        return s if s and s["estado"] in ESTADOS_FINAIS else None

    return esperar(terminou, 300, "a atualização terminar")


def imprimir_log() -> None:
    log = db.data_dir() / "logs" / "atualizacao.log"
    print(log.read_text(encoding="utf-8", errors="replace") if log.exists() else "(sem atualizacao.log)")


def encerrar_app() -> None:
    """Pede ao app que está no ar para encerrar, com o token da trava, e espera a porta fechar."""
    trava = _read_lock()
    if trava and _port_open():
        httpx.post(f"{URL}/_sistema/encerrar", headers={"X-Tabimoney-Token": trava["token"]}, timeout=10)
        esperar(lambda: not _port_open(), 30, "o app encerrar")


def cenario_sucesso(exe: Path, api: str) -> None:
    pid_antigo = subir_app_antigo(exe, api)
    backups_antes = set((db.data_dir() / "backups").glob("*.sqlite3"))
    with httpx.Client(base_url=URL, follow_redirects=True, timeout=30) as cliente:
        pedir_atualizacao(cliente)
        final = acompanhar(cliente)
    if final["estado"] != "concluida":
        imprimir_log()
        raise SystemExit(f"FALHOU: a atualização terminou em {final['estado']}: {final.get('motivo')}")
    trava = _read_lock()
    conferir([
        (trava is not None and trava["pid"] != pid_antigo, "o servidor que respondeu ainda é o antigo"),
        (trava is not None and os.path.normcase(trava["exe"]) == os.path.normcase(str(exe)),
         "a versão nova não roda do mesmo caminho"),
        (bool(set((db.data_dir() / "backups").glob("*.sqlite3")) - backups_antes), "a base não ganhou backup"),
    ])
    anterior = exe.with_name(f"{exe.stem}.anterior{exe.suffix}")
    esperar(lambda: not anterior.exists(), 120, "a versão nova apagar o executável anterior")
    print("atualização com um clique: baixou, conferiu, trocou, reabriu e limpou")
    encerrar_app()


def segurar_porta() -> socket.socket:
    """Ocupa a porta do app: a versão nova não consegue subir enquanto o socket estiver aberto."""
    fim = time.monotonic() + 30
    while True:
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", PORT))
            sock.listen()
            return sock
        except OSError:
            sock.close()
            if time.monotonic() > fim:
                raise SystemExit(f"FALHOU: não deu para ocupar a porta {PORT}")
            time.sleep(0.05)


def cenario_reversao(exe: Path, api: str) -> None:
    original = sha256(exe)
    pid_antigo = subir_app_antigo(exe, api)
    db.set_setting("marca_do_teste", "antes")  # entra no backup: a reversão tem que trazer de volta
    with httpx.Client(base_url=URL, follow_redirects=True, timeout=30) as cliente:
        pedir_atualizacao(cliente)
    esperar(lambda: atualizador.marker().get("estado") == "reiniciando", 120, "a troca acontecer")
    db.set_setting("marca_do_teste", "depois")  # gravado depois do backup: a reversão tem que desfazer
    esperar(lambda: not _pid_alive(pid_antigo) and not _port_open(), 60, "o app antigo sair")
    segurador = segurar_porta()
    try:
        print("porta ocupada: a versão nova não vai conseguir subir")
        log = db.data_dir() / "logs" / "atualizacao.log"
        esperar(lambda: log.exists() and "Revertendo" in log.read_text(encoding="utf-8", errors="replace"),
                300, "o vigia reverter")
    finally:
        segurador.close()  # o vigia espera a porta livre para reabrir o app antigo
    print("o vigia reverteu: porta solta para o app antigo voltar")
    esperar(lambda: atualizador.marker().get("estado") == "revertida", 60, "a reversão terminar")
    esperar(_port_open, 120, "o app antigo voltar")
    with httpx.Client(base_url=URL, follow_redirects=True, timeout=30) as cliente:
        estado_atual = cliente.get("/atualizacao/estado").json()
        pagina = cliente.get("/").text
        configuracoes = cliente.get("/configuracoes").text
    conferir([
        (sha256(exe) == original, "o executável original não voltou"),
        (exe.with_name("Tabimoney.falhou.exe").exists(), "a versão nova não ficou em Tabimoney.falhou.exe"),
        (not exe.with_name("Tabimoney.anterior.exe").exists(), "sobrou Tabimoney.anterior.exe"),
        (db.get_setting("marca_do_teste") == "antes", "a base não voltou ao backup"),
        (db.get_setting("depois") == "", "o que foi gravado depois do backup continuou na base"),
        (estado_atual["estado"] == "revertida", f"o estado é {estado_atual['estado']}, não revertida"),
        (f"Voltamos para a {estado_atual['versao_em_uso']}" in pagina, "o aviso de 'não abriu' não apareceu"),
        ("Atualizar agora" not in configuracoes, "a tela ofereceu Atualizar agora para a mesma versão"),
    ])
    print("reversão: executável original de volta, base do backup, aviso na tela e sem botão para tentar de novo")
    encerrar_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Atualização com um clique, de ponta a ponta, com um Release falso.")
    parser.add_argument("--reverter", action="store_true", help="a versão nova não sobe: confere a reversão")
    parser.add_argument("exe", type=Path)
    parser.add_argument("pasta", type=Path)
    parser.add_argument("zip")
    parser.add_argument("versao")
    args = parser.parse_args()
    exe = args.exe.resolve()
    porta_livre()
    base = isolar()
    api, servidor = publicar_release(args.pasta.resolve(), args.zip, args.versao)
    try:
        if args.reverter:
            cenario_reversao(exe, api)
        else:
            cenario_sucesso(exe, api)
    finally:
        try:
            encerrar_app()  # se algo falhou no meio, não deixa o app de teste aberto
        except (httpx.HTTPError, SystemExit):
            pass
        servidor.shutdown()
        servidor.server_close()
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
