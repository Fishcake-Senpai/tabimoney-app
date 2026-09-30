"""Conecta o servidor MCP do Tabimoney aos agentes de IA: configuração, instalação, situação e registro de uso.

Cada cliente guarda os servidores MCP de um jeito. Os que usam arquivo (Claude Desktop, Cursor, VS Code, Gemini
CLI, Codex) são editados aqui: só a entrada `tabimoney` (ou `tabimoney-demo`) muda, o resto do arquivo fica
igual e uma cópia é guardada antes. O Claude Code é configurado pelo próprio comando `claude mcp add`.

Para quando nada disso funcionar, `configuracao()` também monta um texto pronto para colar na IA: ela mesma
faz a configuração.

Os formatos seguem a documentação de cada cliente (setembro de 2026); se um mudar, ajuste só o cartão dele em
CLIENTES e os testes em tests/test_mcp_instalar.py.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from base64 import b64encode
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from app import __version__, db

NOME, NOME_DEMO = "tabimoney", "tabimoney-demo"
ROOT = Path(__file__).resolve().parent.parent.parent
FROZEN = getattr(sys, "frozen", False)
EXE_NAMES = {"tabimoney.exe", "tabimoney"}  # o que identifica uma entrada gravada pelo executável
USO_ARQUIVO = "mcp-uso.json"

# modo: "arquivo" (editamos a configuração), "comando" (rodamos o CLI do cliente) ou "manual" (só o texto)
CLIENTES: dict[str, dict[str, str]] = {
    "claude-desktop": {"nome": "Claude Desktop", "modo": "arquivo", "chave": "mcpServers",
                       "depois": "Feche o Claude Desktop por completo (inclusive na bandeja) e abra de novo."},
    "claude-code": {"nome": "Claude Code", "modo": "comando",
                    "depois": "Abra uma sessão nova do Claude Code; o /mcp lista o Tabimoney."},
    "codex": {"nome": "Codex", "modo": "arquivo", "chave": "mcp_servers",
              "depois": "Abra uma sessão nova do Codex."},
    "cursor": {"nome": "Cursor", "modo": "arquivo", "chave": "mcpServers",
               "depois": "No Cursor, confira em Settings › MCP se o Tabimoney está ligado."},
    "vscode": {"nome": "VS Code (Copilot)", "modo": "arquivo", "chave": "servers",
               "depois": "No VS Code, rode o comando “MCP: List Servers” e inicie o Tabimoney."},
    "gemini": {"nome": "Gemini CLI", "modo": "arquivo", "chave": "mcpServers",
               "depois": "Abra uma sessão nova do Gemini CLI; o /mcp lista o Tabimoney."},
    "outro": {"nome": "Outro agente", "modo": "manual",
              "depois": "Cole o texto no agente: ele mesmo configura."},
}


# ---------------------------------------------------------------- o comando que sobe o servidor

def entrada(demo: bool = False) -> dict[str, Any]:
    """Como o cliente sobe o servidor: o executável com `mcp`, ou o Python do projeto rodando pelo código."""
    extra = ["--demo"] if demo else []
    if FROZEN:
        return {"command": sys.executable, "args": ["mcp", *extra]}
    return {"command": sys.executable, "args": ["-m", "app.mcp_server", *extra],
            "env": {"PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}}


def _nome(demo: bool) -> str:
    return NOME_DEMO if demo else NOME


# ---------------------------------------------------------------- onde cada cliente guarda a configuração

def _appdata() -> Path:
    return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")


def _app_support() -> Path:
    """Pasta de configuração de apps de desktop: %APPDATA%, ~/Library/Application Support ou ~/.config."""
    if os.name == "nt":
        return _appdata()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def arquivo_config(cliente: str) -> Path | None:
    if cliente == "claude-desktop":
        if os.name == "nt":
            # o Claude da Microsoft Store grava numa pasta virtualizada
            local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            for store in sorted((local / "Packages").glob("Claude_*")):
                folder = store / "LocalCache" / "Roaming" / "Claude"
                if folder.is_dir():
                    return folder / "claude_desktop_config.json"
        return _app_support() / "Claude" / "claude_desktop_config.json"
    if cliente == "cursor":
        return Path.home() / ".cursor" / "mcp.json"
    if cliente == "vscode":
        return _app_support() / "Code" / "User" / "mcp.json"
    if cliente == "gemini":
        return Path.home() / ".gemini" / "settings.json"
    if cliente == "codex":
        return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "config.toml"
    if cliente == "claude-code":
        return Path.home() / ".claude.json"  # só leitura: a escrita é pelo `claude mcp add`
    return None


def _detectado(cliente: str) -> bool:
    """Há sinal de que o cliente está instalado nesta máquina?"""
    if cliente == "claude-code":
        return _which("claude") is not None or (Path.home() / ".claude.json").exists()
    if cliente == "codex":
        return _which("codex") is not None or (arquivo_config("codex") or Path()).parent.is_dir()
    path = arquivo_config(cliente)
    return bool(path and path.parent.is_dir())


# ---------------------------------------------------------------- ler e gravar

def _ler_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path} não é um JSON válido ({exc}). Corrija o arquivo ou use o texto para colar na IA.") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} não tem o formato esperado.")
    return data


def _ler_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path} não é um TOML válido ({exc}). Corrija o arquivo ou use o texto para colar na IA.") from exc


def _servidores(cliente: str) -> dict[str, Any]:
    """As entradas de servidores MCP já gravadas no cliente (vazio se não houver arquivo)."""
    path = arquivo_config(cliente)
    if not path:
        return {}
    data = _ler_toml(path) if cliente == "codex" else _ler_json(path)
    key = CLIENTES[cliente].get("chave", "mcpServers")
    found = data.get(key)
    return found if isinstance(found, dict) else {}


def _entrada_do_cliente(cliente: str, demo: bool) -> dict[str, Any]:
    item = entrada(demo)
    if cliente == "vscode":
        return {"type": "stdio", **item}
    return item


def _toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # string básica do TOML usa os mesmos escapes


def _toml_bloco(nome: str, item: dict[str, Any]) -> str:
    lines = [f"[mcp_servers.{nome}]", f"command = {_toml_str(item['command'])}",
             "args = [" + ", ".join(_toml_str(a) for a in item["args"]) + "]"]
    if item.get("env"):
        lines += ["", f"[mcp_servers.{nome}.env]"] + [f"{k} = {_toml_str(v)}" for k, v in item["env"].items()]
    return "\n".join(lines) + "\n"


def _sem_bloco_toml(text: str, nome: str) -> str:
    """Tira as tabelas [mcp_servers.<nome>] e [mcp_servers.<nome>.*] de um config.toml, sem tocar no resto."""
    header = re.compile(r"^\s*\[\s*mcp_servers\s*\.\s*(\"?)" + re.escape(nome) + r"\1\s*(\.[^\]]*)?\]\s*$")
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("["):
            skipping = bool(header.match(line))
        if not skipping:
            out.append(line)
    return "".join(out).rstrip() + ("\n" if out else "")


def _copia(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(path.name + ".antes-do-tabimoney")
    shutil.copy2(path, backup)
    return backup


def _gravar_arquivo(cliente: str, nome: str, item: dict[str, Any] | None) -> dict[str, Any]:
    """Grava (ou remove, com item None) a entrada no arquivo do cliente. Devolve o que foi feito."""
    path = arquivo_config(cliente)
    assert path is not None
    if cliente == "codex":
        _ler_toml(path)  # recusa um arquivo quebrado antes de mexer
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        new = _sem_bloco_toml(text, nome)
        if item is not None:
            new = (new + "\n" if new.strip() else "") + _toml_bloco(nome, item)
    else:
        data = _ler_json(path)
        key = CLIENTES[cliente]["chave"]
        servers = data.get(key) if isinstance(data.get(key), dict) else {}
        if item is None:
            servers.pop(nome, None)
        else:
            servers[nome] = item
        data[key] = servers
        new = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    backup = _copia(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new, encoding="utf-8", newline="\n")
    return {"arquivo": str(path), "copia": str(backup) if backup else None}


def _which(command: str) -> str | None:
    return shutil.which(command)


def _claude(*args: str) -> subprocess.CompletedProcess:
    exe = _which("claude")
    if not exe:
        raise ValueError("O comando `claude` não está no PATH. Use o comando ou o texto para colar na IA.")
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=60,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def comando_claude_code(demo: bool = False) -> str:
    item = entrada(demo)
    env = " ".join(f"-e {k}={_quote(v)}" for k, v in item.get("env", {}).items())
    return " ".join(p for p in ["claude mcp add", _nome(demo), "--scope user", env, "--",
                                _quote(item["command"]), *(_quote(a) for a in item["args"])] if p)


def _quote(value: str) -> str:
    if os.name == "nt":
        return f'"{value}"' if re.search(r"[\s&()^|<>]", value) else value
    return shlex.quote(value)


# ---------------------------------------------------------------- o que a tela e a CLI usam

def configuracao(cliente: str, demo: bool = False) -> dict[str, Any]:
    """Tudo para conectar um cliente à mão: a entrada, o trecho do arquivo, o comando, o link e o texto para a IA."""
    if cliente not in CLIENTES:
        raise ValueError(f"Cliente desconhecido: {cliente}. Use {', '.join(CLIENTES)}.")
    info, nome = CLIENTES[cliente], _nome(demo)
    item = _entrada_do_cliente(cliente, demo)
    path = arquivo_config(cliente)
    result: dict[str, Any] = {"cliente": cliente, "nome": info["nome"], "servidor": nome, "entrada": item,
                              "modo": info["modo"], "depois": info["depois"]}
    if info["modo"] == "arquivo" and path:
        result["arquivo"] = str(path)
        result["trecho"] = (_toml_bloco(nome, item) if cliente == "codex"
                            else json.dumps({info["chave"]: {nome: item}}, ensure_ascii=False, indent=2))
    if cliente == "claude-code":
        result["comando"] = comando_claude_code(demo)
    elif cliente == "codex":
        e = entrada(demo)
        env = " ".join(f"--env {k}={_quote(v)}" for k, v in e.get("env", {}).items())
        result["comando"] = " ".join(p for p in ["codex mcp add", nome, env, "--", _quote(e["command"]),
                                                 *(_quote(a) for a in e["args"])] if p)
    elif cliente == "cursor":
        config = b64encode(json.dumps(entrada(demo)).encode()).decode()
        result["link"] = f"cursor://anysphere.cursor-deeplink/mcp/install?name={nome}&config={quote(config)}"
    elif cliente == "vscode":
        result["link"] = "vscode:mcp/install?" + quote(json.dumps({"name": nome, **item}, ensure_ascii=False))
    result["texto_para_ia"] = texto_para_ia(cliente, demo)
    return result


def texto_para_ia(cliente: str = "outro", demo: bool = False) -> str:
    """Um pedido pronto para colar no agente, que então configura o servidor MCP sozinho."""
    item, nome = entrada(demo), _nome(demo)
    json_entry = json.dumps({"command": item["command"], "args": item["args"], **({"env": item["env"]} if "env" in item else {})},
                            ensure_ascii=False, indent=2)
    alvo = "" if cliente == "outro" else f" Você é o {CLIENTES[cliente]['nome']}."
    demo_line = (" Esta entrada é a demonstração do Tabimoney (dados fictícios), separada da entrada dos dados reais."
                 if demo else "")
    return f"""Conecte o Tabimoney, meu aplicativo local de finanças, a você como servidor MCP.{alvo}{demo_line}

Nome do servidor: {nome}
Transporte: stdio (você inicia o processo; não há URL nem porta)
Configuração:
{json_entry}

Passos:
1. Descubra onde fica a sua configuração de servidores MCP no escopo do usuário (vale em qualquer pasta).
2. Acrescente o servidor acima sem apagar os outros. Se já existir um "{nome}", troque só ele. Faça uma cópia do
   arquivo antes de editar.
   - Claude Code: rode `{comando_claude_code(demo)}`
   - Claude Desktop: arquivo {arquivo_config("claude-desktop")}, chave "mcpServers".
   - Codex: arquivo {arquivo_config("codex")}, tabela [mcp_servers.{nome}].
   - Cursor: arquivo {arquivo_config("cursor")}, chave "mcpServers".
   - VS Code: arquivo {arquivo_config("vscode")}, chave "servers", com "type": "stdio".
   - Gemini CLI: arquivo {arquivo_config("gemini")}, chave "mcpServers".
   - Outro cliente: use o equivalente na documentação dele.
3. Diga se preciso reiniciar o aplicativo. Depois, chame a ferramenta `status` do servidor {nome} para
   confirmar que funcionou.

Durante a configuração, não leia nem envie meus dados financeiros.
"""


def instalar(cliente: str, demo: bool = False) -> dict[str, Any]:
    """Grava a configuração no cliente. Levanta ValueError com a explicação se não der."""
    if cliente not in CLIENTES:
        raise ValueError(f"Cliente desconhecido: {cliente}. Use {', '.join(CLIENTES)}.")
    info, nome = CLIENTES[cliente], _nome(demo)
    if info["modo"] == "manual":
        raise ValueError("Para esse agente, use o texto para colar na IA.")
    if cliente == "claude-code":
        item = entrada(demo)
        _claude("mcp", "remove", nome, "--scope", "user")  # se não existia, só avisa; segue
        env = [x for k, v in item.get("env", {}).items() for x in ("-e", f"{k}={v}")]
        done = _claude("mcp", "add", nome, "--scope", "user", *env, "--", item["command"], *item["args"])
        if done.returncode != 0:
            raise ValueError(f"O Claude Code recusou: {(done.stderr or done.stdout).strip()[:300]}")
        return {"cliente": cliente, "nome": info["nome"], "servidor": nome, "instalado": True, "depois": info["depois"]}
    done = _gravar_arquivo(cliente, nome, _entrada_do_cliente(cliente, demo))
    return {"cliente": cliente, "nome": info["nome"], "servidor": nome, "instalado": True, **done, "depois": info["depois"]}


def remover(cliente: str, demo: bool = False) -> dict[str, Any]:
    nome = _nome(demo)
    if cliente == "claude-code":
        _claude("mcp", "remove", nome, "--scope", "user")
        return {"cliente": cliente, "servidor": nome, "removido": True}
    if CLIENTES.get(cliente, {}).get("modo") != "arquivo":
        raise ValueError("Esse agente não é configurado pelo Tabimoney.")
    return {"cliente": cliente, "servidor": nome, "removido": True, **_gravar_arquivo(cliente, nome, None)}


def _mesmo_comando(found: dict[str, Any], demo: bool) -> bool:
    want = entrada(demo)
    return found.get("command") == want["command"] and list(found.get("args") or []) == want["args"]


def situacao() -> list[dict[str, Any]]:
    """Para cada cliente: se foi detectado, se o Tabimoney está conectado e se o caminho está em dia."""
    uso = ultimo_uso()
    out = []
    for cliente, info in CLIENTES.items():
        item: dict[str, Any] = {"cliente": cliente, "nome": info["nome"], "modo": info["modo"],
                                "detectado": _detectado(cliente) if cliente != "outro" else None}
        try:
            servers = _servidores(cliente) if cliente != "outro" else {}
            found = servers.get(NOME)
            item["conectado"] = bool(found)
            item["em_dia"] = _mesmo_comando(found, False) if isinstance(found, dict) else None
            item["demo_conectada"] = NOME_DEMO in servers
            item["erro"] = None
        except (ValueError, OSError) as exc:
            item.update(conectado=None, em_dia=None, demo_conectada=None, erro=str(exc))
        item["pode_instalar"] = info["modo"] == "arquivo" or (cliente == "claude-code" and _which("claude") is not None)
        item["ultimo_uso"] = next((u for u in uso if u["cliente_id"] == cliente), None)
        out.append(item)
    return out


def reparar() -> list[dict[str, Any]]:
    """Ao abrir o executável: se ele mudou de pasta, corrige o caminho nas configurações que o Tabimoney gravou.
    Só mexe em entradas `tabimoney`/`tabimoney-demo` que apontam para um executável do Tabimoney."""
    if not FROZEN:
        return []
    fixed = []
    for cliente, info in CLIENTES.items():
        if info["modo"] != "arquivo":
            continue
        try:
            servers = _servidores(cliente)
        except (ValueError, OSError):
            continue
        for demo in (False, True):
            found = servers.get(_nome(demo))
            if not isinstance(found, dict) or _mesmo_comando(found, demo):
                continue
            if Path(str(found.get("command", ""))).name.lower() not in EXE_NAMES:
                continue  # entrada de quem roda pelo código, ou feita à mão: não é nossa
            try:
                _gravar_arquivo(cliente, _nome(demo), _entrada_do_cliente(cliente, demo))
                fixed.append({"cliente": cliente, "servidor": _nome(demo)})
            except (ValueError, OSError):
                continue
    return fixed


# ---------------------------------------------------------------- registro de uso (para a tela mostrar)

def _cliente_id(nome_cliente: str) -> str:
    """Traduz o clientInfo.name que o cliente manda para a chave de CLIENTES, quando dá."""
    n = nome_cliente.lower()
    for key, needle in (("claude-code", "claude-code"), ("claude-desktop", "claude-ai"), ("claude-desktop", "claude desktop"),
                        ("codex", "codex"), ("cursor", "cursor"), ("vscode", "visual studio code"),
                        ("vscode", "vscode"), ("gemini", "gemini")):
        if needle in n:
            return key
    return "outro"


def registrar_uso(nome_cliente: str, versao_cliente: str | None, demo: bool) -> None:
    path = db.data_dir() / USO_ARQUIVO
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        data = {}
    data[nome_cliente] = {"cliente_id": _cliente_id(nome_cliente), "versao_cliente": versao_cliente,
                          "quando": datetime.now().astimezone().isoformat(timespec="seconds"),
                          "executavel": sys.executable, "versao_app": __version__, "demo": demo}
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def ultimo_uso() -> list[dict[str, Any]]:
    """Os agentes que usaram o servidor, do mais recente ao mais antigo."""
    path = db.data_dir() / USO_ARQUIVO
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return []
    items = [{"cliente": k, **v, "executavel_existe": Path(v.get("executavel", "")).exists()} for k, v in data.items()]
    return sorted(items, key=lambda u: u.get("quando", ""), reverse=True)
