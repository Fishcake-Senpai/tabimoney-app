"""O servidor MCP do Tabimoney: instruções, ferramentas (ferramentas.py), prompts (os roteiros) e resources.

Sobe por stdio: o cliente de IA abre o processo e conversa pela entrada e saída padrão. Enquanto serve, o SDK
desvia a saída padrão para o stderr, então um print perdido não quebra o protocolo. O log vai para
<pasta de dados>/logs/mcp.log.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.prompts.base import Prompt, PromptArgument

from app import __version__, agente, db
from app.mcp_server import ferramentas

ROOT = Path(__file__).resolve().parent.parent.parent  # no executável, a pasta extraída (sys._MEIPASS)

INSTRUCOES = """Tabimoney: finanças pessoais locais do usuário (gastos, orçamento, carteira, metas de alocação, \
análises fundamentalistas e recomendações). Valores em reais; percentuais como fração (0.15 = 15%).
Antes de uma tarefa com mais de um passo, chame `roteiro` com o nome da tarefa (ciclo, gastos, orcamento, metas, \
analise-ativo, analise-trimestral, recomendacoes; ou visao-geral para escolher) e siga os passos. Em investimentos, \
comece por `carteira_contexto`; as análises são de longo prazo e começam pelo horizonte (`perfil_investidor`). Pergunta simples se responde direto com a ferramenta certa.
Ferramentas destrutivas (metas_definir, orcamento_definir, orcamento_remover, gastos_excluir_categoria, \
gastos_remover_regra) só com pedido explícito do usuário. Nada apaga lançamentos, e o servidor faz backup antes \
da primeira mudança da sessão.
Não envie extratos, saldos ou identificadores (CPF, números de conta) a outros serviços; buscar informação \
pública sobre empresas e títulos é permitido."""

RESOURCES = {
    "tabimoney://docs/contrato": ("contrato", "Contrato: formatos e regras de cálculo", ROOT / "docs" / "agente-financeiro.md", "text/markdown"),
    "tabimoney://docs/modelo-relatorio-tese": ("modelo-relatorio-tese", "Modelo da tese de longo prazo",
                                               ROOT / "docs" / "agentes" / "modelo-relatorio-tese.md", "text/markdown"),
    "tabimoney://docs/modelo-relatorio-trimestral": ("modelo-relatorio-trimestral", "Modelo do acompanhamento trimestral",
                                                     ROOT / "docs" / "agentes" / "modelo-relatorio-trimestral.md", "text/markdown"),
    **{f"tabimoney://exemplos/{n}": (f"exemplo-{n}", f"Exemplo válido: {n}", ROOT / "docs" / "agentes" / "exemplos" / f"{n}.json",
                                     "application/json") for n in ("analise-ativo", "analise-trimestral", "recomendacoes", "orcamento")},
}

# prompt → (roteiro, título, argumentos com descrição)
PROMPTS = {
    "ciclo": ("ciclo", "Ciclo completo: atualizar, analisar, recomendar e resumir", {"titular": "Nome do titular (opcional)"}),
    "revisar_gastos": ("gastos", "Revisar gastos e corrigir categorias", {"mes": "Mês AAAA-MM (opcional)", "titular": "Nome do titular (opcional)"}),
    "orcamento": ("orcamento", "Análise orçamentária e onde economizar", {"mes": "Mês AAAA-MM (opcional)"}),
    "onde_aportar": ("metas", "Metas de alocação e para onde vai o aporte", {"aporte": "Valor do aporte em reais (opcional)", "titular": "Nome do titular (opcional)"}),
    "analise_ativo": ("analise-ativo", "Análise completa de um ativo (longo prazo)", {"ticker": "Ticker do ativo (ou nome do título de renda fixa)", "titular": "Nome do titular (opcional)"}),
    "analise_trimestral": ("analise-trimestral", "Acompanhamento trimestral das teses", {"tickers": "Tickers separados por vírgula (opcional; padrão: todos)", "titular": "Nome do titular (opcional)"}),
    "recomendacoes": ("recomendacoes", "Recomendações trimestrais da carteira", {"aporte": "Valor do aporte em reais (opcional)", "titular": "Nome do titular (opcional)"}),
}


def _leitor(path: Path):
    def ler() -> str:
        return path.read_text(encoding="utf-8")
    return ler


def _roteiro_texto(nome: str):
    def ler() -> str:
        return agente.roteiro(nome)["texto"]
    return ler


def _prompt(nome: str) -> Prompt:
    roteiro_nome, titulo, argumentos = PROMPTS[nome]

    def gerar(**kwargs: str | None) -> str:
        r = agente.roteiro(roteiro_nome)
        dados = [f"- {k}: {v}" for k, v in kwargs.items() if v]
        pedido = "\n".join(["Parâmetros do pedido:", *dados]) + "\n\n" if dados else ""
        return f"Siga este roteiro do Tabimoney com as ferramentas do servidor tabimoney.\n\n{pedido}{r['texto']}"

    return Prompt(name=nome, title=titulo, description=agente.roteiro(roteiro_nome)["descricao"], fn=gerar,
                  arguments=[PromptArgument(name=a, description=d, required=False) for a, d in argumentos.items()])


def criar(na_demo: bool = False) -> MCPServer:
    nome = "tabimoney-demo" if na_demo else "tabimoney"
    instrucoes = INSTRUCOES + ("\nESTA É A DEMONSTRAÇÃO: dados fictícios (Lucas e Marina). Nunca apresente estes "
                               "números como se fossem do usuário." if na_demo else "")
    server = MCPServer(nome, title="Tabimoney" + (" (demonstração)" if na_demo else ""),
                       description="Finanças pessoais locais: gastos, orçamento, carteira, metas e análises.",
                       instructions=instrucoes, version=__version__, website_url="https://github.com/Fishcake-Senpai/tabimoney-app",
                       log_level="WARNING")
    ferramentas.registrar(server, ferramentas.Sessao(na_demo))

    for nome_prompt in PROMPTS:
        server.add_prompt(_prompt(nome_prompt))

    for uri, (nome_res, titulo, path, mime) in RESOURCES.items():
        server.resource(uri, name=nome_res, title=titulo, mime_type=mime)(_leitor(path))
    for r in agente.ROTEIROS:
        info = agente.roteiro(r)
        server.resource(f"tabimoney://roteiros/{r}", name=f"roteiro-{r}", title=info["titulo"], description=info["descricao"],
                        mime_type="text/markdown")(_roteiro_texto(r))
    return server


def _log() -> None:
    folder = db.data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(folder / "mcp.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    for name in ("tabimoney", "mcp"):
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO if name == "tabimoney" else logging.WARNING)


def _esconder_console() -> None:
    """Windows: o Tabimoney.exe é um programa de console. Aberto por um app gráfico (Claude Desktop, Cursor), o
    Windows cria uma janela preta só para ele. Se o console é só nosso (este processo e o carregador do exe),
    escondemos a janela; se veio de um terminal (Claude Code, Codex), o console é do usuário e fica como está."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return
        pids = (ctypes.c_ulong * 16)()
        count = kernel32.GetConsoleProcessList(pids, 16)
        nossos = {os.getpid(), os.getppid()}
        if 0 < count <= 16 and all(pids[i] in nossos for i in range(count)):
            user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:  # noqa: BLE001 - esconder a janela é cortesia
        pass


def main(demo: bool = False) -> None:
    _esconder_console()
    _log()
    db.init_db()
    if demo:
        from app import demo as demo_mod

        demo_mod.ensure()
    logging.getLogger("tabimoney.mcp").info("servidor MCP %s iniciado (demo=%s)", __version__, demo)
    criar(demo).run("stdio")
