"""O que os agentes de IA leem e gravam no Tabimoney, num lugar só.

`operacoes` monta os JSONs (em reais, percentuais como fração) e grava correções, análises e recomendações.
A CLI (`app/cli.py`) e o servidor MCP (`app/mcp_server`) são duas portas para as mesmas funções.
`roteiros/` guarda os roteiros passo a passo (a fonte única; o servidor MCP os entrega como prompts, pela
ferramenta `roteiro` e como resources). No executável, a pasta entra em `datas` de packaging/tabimoney.spec.
"""
from __future__ import annotations

from pathlib import Path

ROTEIROS_DIR = Path(__file__).resolve().parent / "roteiros"
# ordem de exibição; o nome é o arquivo sem .md
ROTEIROS = ("visao-geral", "ciclo", "gastos", "orcamento", "metas", "analise-ativo", "analise-trimestral", "recomendacoes")


def roteiro(nome: str) -> dict[str, str]:
    """Um roteiro: título, descrição (do cabeçalho) e o texto em Markdown."""
    nome = nome.strip().lower().replace("_", "-").removesuffix(".md")
    if nome not in ROTEIROS:
        raise ValueError(f"Roteiro desconhecido: {nome}. Use {', '.join(ROTEIROS)}.")
    raw = (ROTEIROS_DIR / f"{nome}.md").read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    if raw.startswith("---"):
        head, _, raw = raw[3:].partition("\n---")
        for line in head.strip().splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
        raw = raw.lstrip("\n")
    return {"nome": nome, "titulo": meta.get("titulo", nome), "descricao": meta.get("descricao", ""), "texto": raw}
