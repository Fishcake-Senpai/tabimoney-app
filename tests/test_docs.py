"""A documentação pública: links relativos válidos e todas as páginas no índice.

Não testa o conteúdo, só a estrutura: um link quebrado ou um guia novo fora do índice aparecem aqui antes de
chegar em quem lê.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
INDEX = DOCS / "README.md"
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def _relative_links(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    links = []
    for target in LINK.findall(text):
        target = target.strip().split(" ")[0]
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = unquote(target.split("#", 1)[0])
        if target:
            links.append(target)
    return links


def test_links_relativos_existem():
    files = [ROOT / "README.md", *DOCS.rglob("*.md")]
    quebrados = []
    for path in files:
        for target in _relative_links(path):
            if not (path.parent / target).exists():
                quebrados.append(f"{path.relative_to(ROOT)} -> {target}")
    assert not quebrados, "Links relativos quebrados:\n" + "\n".join(quebrados)


def test_todas_as_paginas_estao_no_indice():
    linked = {(INDEX.parent / target).resolve() for target in _relative_links(INDEX)}
    fora = []
    for path in DOCS.rglob("*.md"):
        if path != INDEX and path.resolve() not in linked:
            fora.append(str(path.relative_to(ROOT)))
    assert not fora, "Documentos fora de docs/README.md:\n" + "\n".join(fora)
