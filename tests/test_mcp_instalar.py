"""Conectar o Tabimoney aos agentes de IA (app/mcp_server/instalar.py), a tela Configurações › Conectar à IA e
`financas mcp`. As pastas de configuração dos agentes ficam no home falso do conftest; `claude` e `codex` nunca
rodam de verdade.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from app import cli
from app.mcp_server import instalar

from .conftest import avisos, csrf


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- configuração e texto para a IA

@pytest.mark.parametrize("cliente", list(instalar.CLIENTES))
def test_configuracao_de_cada_cliente_traz_o_texto_para_a_ia(cliente):
    cfg = instalar.configuracao(cliente)
    assert cfg["entrada"]["command"] == sys.executable
    assert "app.mcp_server" in cfg["entrada"]["args"]  # rodando pelo código
    texto = cfg["texto_para_ia"]
    assert "tabimoney" in texto and "`status`" in texto and sys.executable.replace("\\", "\\\\") in texto
    assert "não leia nem envie meus dados" in texto


def test_executavel_usa_o_subcomando_mcp(monkeypatch):
    monkeypatch.setattr(instalar, "FROZEN", True)
    monkeypatch.setattr(instalar.sys, "executable", r"C:\Apps\Tabimoney.exe")
    assert instalar.entrada() == {"command": r"C:\Apps\Tabimoney.exe", "args": ["mcp"]}
    assert instalar.entrada(demo=True)["args"] == ["mcp", "--demo"]
    comando = instalar.comando_claude_code()
    assert comando.startswith("claude mcp add tabimoney --scope user -- ") and "Tabimoney.exe" in comando and comando.endswith(" mcp")


def test_links_de_instalacao_do_cursor_e_do_vscode():
    assert instalar.configuracao("cursor")["link"].startswith("cursor://anysphere.cursor-deeplink/mcp/install?name=tabimoney&config=")
    assert instalar.configuracao("vscode")["link"].startswith("vscode:mcp/install?")


# ---------------------------------------------------------------- instalar por arquivo

def test_claude_desktop_mescla_sem_apagar_os_outros_e_guarda_copia():
    path = instalar.arquivo_config("claude-desktop")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {"outro": {"command": "x"}}, "tema": "escuro"}), encoding="utf-8")
    feito = instalar.instalar("claude-desktop")
    dados = _json(path)
    assert dados["tema"] == "escuro" and dados["mcpServers"]["outro"] == {"command": "x"}
    assert dados["mcpServers"]["tabimoney"] == instalar.entrada()
    assert _json(Path(feito["copia"])) == {"mcpServers": {"outro": {"command": "x"}}, "tema": "escuro"}


def test_json_quebrado_nao_e_sobrescrito():
    path = instalar.arquivo_config("cursor")
    path.parent.mkdir(parents=True)
    path.write_text("{ quebrado", encoding="utf-8")
    with pytest.raises(ValueError, match="não é um JSON válido"):
        instalar.instalar("cursor")
    assert path.read_text(encoding="utf-8") == "{ quebrado"


def test_vscode_usa_servers_com_type_stdio():
    instalar.instalar("vscode")
    entrada = _json(instalar.arquivo_config("vscode"))["servers"]["tabimoney"]
    assert entrada["type"] == "stdio" and entrada["command"] == sys.executable


def test_demo_e_uma_entrada_separada():
    instalar.instalar("gemini")
    instalar.instalar("gemini", demo=True)
    servidores = _json(instalar.arquivo_config("gemini"))["mcpServers"]
    assert "--demo" not in servidores["tabimoney"]["args"] and "--demo" in servidores["tabimoney-demo"]["args"]


def test_codex_troca_so_a_tabela_do_tabimoney():
    path = instalar.arquivo_config("codex")
    path.parent.mkdir(parents=True)
    path.write_text('model = "gpt-5"\n\n[mcp_servers.outro]\ncommand = "x"\n\n[mcp_servers.tabimoney]\ncommand = "velho"\n'
                    'args = []\n\n[mcp_servers.tabimoney.env]\nA = "1"\n\n[perfil]\nnome = "eu"\n', encoding="utf-8")
    instalar.instalar("codex")
    instalar.instalar("codex")  # de novo: não duplica
    texto = path.read_text(encoding="utf-8")
    dados = tomllib.loads(texto)
    assert dados["model"] == "gpt-5" and dados["perfil"] == {"nome": "eu"} and dados["mcp_servers"]["outro"] == {"command": "x"}
    assert dados["mcp_servers"]["tabimoney"]["command"] == sys.executable
    assert dados["mcp_servers"]["tabimoney"]["env"]["PYTHONPATH"]
    assert texto.count("[mcp_servers.tabimoney]") == 1
    instalar.remover("codex")
    assert "tabimoney" not in tomllib.loads(path.read_text(encoding="utf-8"))["mcp_servers"]


def test_remover_tira_so_a_nossa_entrada():
    instalar.instalar("claude-desktop")
    path = instalar.arquivo_config("claude-desktop")
    dados = _json(path)
    dados["mcpServers"]["outro"] = {"command": "x"}
    path.write_text(json.dumps(dados), encoding="utf-8")
    instalar.remover("claude-desktop")
    assert _json(path)["mcpServers"] == {"outro": {"command": "x"}}


# ---------------------------------------------------------------- Claude Code (pelo comando claude)

def test_claude_code_pelo_comando(monkeypatch):
    chamadas = []
    monkeypatch.setattr(instalar, "_which", lambda comando: "/bin/claude" if comando == "claude" else None)
    monkeypatch.setattr(instalar.subprocess, "run", lambda args, **_k: chamadas.append(args) or
                        subprocess.CompletedProcess(args, 0, "", ""))
    instalar.instalar("claude-code")
    assert chamadas[0][:5] == ["/bin/claude", "mcp", "remove", "tabimoney", "--scope"]
    adicionar = chamadas[1]
    assert adicionar[:5] == ["/bin/claude", "mcp", "add", "tabimoney", "--scope"]
    assert adicionar[adicionar.index("--") + 1:] == [sys.executable, "-m", "app.mcp_server"]
    assert "-e" in adicionar  # rodando pelo código, leva o PYTHONPATH


def test_claude_code_sem_o_comando_pede_o_texto():
    with pytest.raises(ValueError, match="texto para colar"):
        instalar.instalar("claude-code")


def test_claude_code_que_recusa_mostra_o_motivo(monkeypatch):
    monkeypatch.setattr(instalar, "_which", lambda comando: "/bin/claude")
    monkeypatch.setattr(instalar.subprocess, "run", lambda args, **_k:
                        subprocess.CompletedProcess(args, 0 if "remove" in args else 1, "", "sem permissão"))
    with pytest.raises(ValueError, match="sem permissão"):
        instalar.instalar("claude-code")


# ---------------------------------------------------------------- situação e correção de caminho

def test_situacao_mostra_conectado_e_caminho_antigo():
    instalar.instalar("cursor")
    cursor = next(c for c in instalar.situacao() if c["cliente"] == "cursor")
    assert cursor["conectado"] and cursor["em_dia"] and cursor["detectado"]
    path = instalar.arquivo_config("cursor")
    dados = _json(path)
    dados["mcpServers"]["tabimoney"]["command"] = "C:/antigo/Tabimoney.exe"
    path.write_text(json.dumps(dados), encoding="utf-8")
    cursor = next(c for c in instalar.situacao() if c["cliente"] == "cursor")
    assert cursor["conectado"] and cursor["em_dia"] is False


def test_reparar_corrige_so_entradas_do_executavel(monkeypatch):
    path = instalar.arquivo_config("claude-desktop")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {
        "tabimoney": {"command": "C:/Downloads/v1/Tabimoney.exe", "args": ["mcp"]},
        "tabimoney-demo": {"command": "python", "args": ["-m", "app.mcp_server", "--demo"]},
    }}), encoding="utf-8")
    monkeypatch.setattr(instalar, "FROZEN", True)
    monkeypatch.setattr(instalar.sys, "executable", "C:/Apps/Tabimoney.exe")
    assert instalar.reparar() == [{"cliente": "claude-desktop", "servidor": "tabimoney"}]
    servidores = _json(path)["mcpServers"]
    assert servidores["tabimoney"]["command"] == "C:/Apps/Tabimoney.exe"
    assert servidores["tabimoney-demo"]["command"] == "python"  # feita pelo código: não é nossa
    assert instalar.reparar() == []


def test_reparar_nao_faz_nada_rodando_pelo_codigo():
    instalar.instalar("claude-desktop")
    assert instalar.reparar() == []


def test_uso_registrado_aparece_na_situacao():
    instalar.registrar_uso("claude-code", "2.1.0", False)
    claude = next(c for c in instalar.situacao() if c["cliente"] == "claude-code")
    assert claude["ultimo_uso"]["versao_cliente"] == "2.1.0" and claude["ultimo_uso"]["executavel_existe"]


# ---------------------------------------------------------------- tela

def test_tela_de_conexao(client):
    html = client.get("/configuracoes").text
    assert 'id="ia"' in html and "Conectar à IA" in html and "Texto para colar na IA" in html
    assert "Claude Desktop" in html and "Codex" in html


def test_conectar_pela_tela(client):
    r = client.post("/configuracoes/ia/conectar", data={"csrf_token": csrf(client), "cliente": "claude-desktop"})
    assert ("success", "Pronto: o Tabimoney está conectado ao Claude Desktop. Feche o Claude Desktop por completo "
            "(inclusive na bandeja) e abra de novo.") in avisos(r.text)
    assert "tabimoney" in _json(instalar.arquivo_config("claude-desktop"))["mcpServers"]
    r = client.post("/configuracoes/ia/desconectar", data={"csrf_token": csrf(client), "cliente": "claude-desktop"})
    assert "tabimoney" not in _json(instalar.arquivo_config("claude-desktop"))["mcpServers"]


def test_falha_ao_conectar_indica_o_texto(client):
    r = client.post("/configuracoes/ia/conectar", data={"csrf_token": csrf(client), "cliente": "claude-code"})
    tipo, mensagem = avisos(r.text)[0]
    assert tipo == "error" and "texto para colar na IA" in mensagem


def test_na_demo_conectar_fica_desligado_e_a_situacao_e_ficticia(client):
    instalar.registrar_uso("codex-de-verdade", "1", False)
    client.post("/demo/entrar", data={"csrf_token": csrf(client)})
    html = client.get("/configuracoes").text
    assert "Usou há 5 min" in html and "codex-de-verdade" not in html
    r = client.post("/configuracoes/ia/conectar", data={"csrf_token": csrf(client), "cliente": "cursor"})
    assert avisos(r.text)[0][0] == "warning"
    assert not instalar.arquivo_config("cursor").exists()


# ---------------------------------------------------------------- CLI

def test_cli_mcp(capsys):
    cli.main(["mcp", "config", "--cliente", "cursor"])
    assert json.loads(capsys.readouterr().out)["link"].startswith("cursor://")
    cli.main(["mcp", "instalar", "--cliente", "gemini", "--demo"])
    assert json.loads(capsys.readouterr().out)["servidor"] == "tabimoney-demo"
    cli.main(["mcp", "clientes"])
    gemini = next(c for c in json.loads(capsys.readouterr().out)["clientes"] if c["cliente"] == "gemini")
    assert gemini["demo_conectada"] and not gemini["conectado"]
