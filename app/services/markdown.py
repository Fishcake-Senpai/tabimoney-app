"""Markdown mínimo e seguro para os relatórios do agente.

Todo o texto é escapado antes da formatação, então HTML vindo do agente nunca é executado. Suporta títulos,
parágrafos, listas (inclusive de tarefas), citações, tabelas, blocos de código, linha horizontal, **negrito**,
*itálico*, `código` e links http(s).
"""
from __future__ import annotations

import html
import re

from markupsafe import Markup

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")
_CODE = re.compile(r"`([^`]+)`")
_TABLE_RULE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


def _inline(text: str) -> str:
    codes: list[str] = []

    def keep(match: re.Match[str]) -> str:
        codes.append(f"<code>{match.group(1)}</code>")
        return f"\x00{len(codes) - 1}\x00"

    out = _CODE.sub(keep, html.escape(text, quote=False))
    # o texto já foi escapado (& vira &amp;); só as aspas precisam sair do atributo
    out = _LINK.sub(lambda m: f'<a class="link" href="{m.group(2).replace(chr(34), "%22")}" target="_blank" '
                              f'rel="noreferrer">{m.group(1)}</a>', out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], out)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def render(text: str | None) -> Markup:
    if not text:
        return Markup("")
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    list_type: str | None = None
    i = 0

    def flush_paragraph() -> None:
        if paragraph:
            out.append("<p>" + "<br>".join(_inline(p) for p in paragraph) + "</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph(); close_list()
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(html.escape(lines[i], quote=False))
                i += 1
            out.append("<pre><code>" + "\n".join(block) + "</code></pre>")
        elif not stripped:
            flush_paragraph(); close_list()
        elif heading := re.match(r"^(#{1,4})\s+(.*)$", stripped):
            flush_paragraph(); close_list()
            level = min(len(heading.group(1)) + 2, 6)  # o título do relatório já é h2
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
        elif re.fullmatch(r"[-*_]{3,}", stripped):
            flush_paragraph(); close_list()
            out.append("<hr>")
        elif stripped.startswith("|") and i + 1 < len(lines) and _TABLE_RULE.match(lines[i + 1].strip()):
            flush_paragraph(); close_list()
            header = _cells(stripped)
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append(_cells(lines[i]))
                i += 1
            numeric = re.compile(r"^[−\-+R$\s\d.,%x]+$")
            rows_html = "".join(
                "<tr>" + "".join(f'<td class="{"num" if numeric.match(c or "x") else ""}">{_inline(c)}</td>' for c in row) + "</tr>"
                for row in body
            )
            out.append('<div class="table-wrap"><table class="data"><thead><tr>'
                       + "".join(f"<th>{_inline(h)}</th>" for h in header) + f"</tr></thead><tbody>{rows_html}</tbody></table></div>")
            continue
        elif stripped.startswith(">"):
            flush_paragraph(); close_list()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(_inline(lines[i].strip()[1:].strip()))
                i += 1
            out.append("<blockquote>" + "<br>".join(quote) + "</blockquote>")
            continue
        elif item := re.match(r"^([-*+]|\d+[.)])\s+(.*)$", stripped):
            flush_paragraph()
            wanted = "ol" if item.group(1)[0].isdigit() else "ul"
            if list_type != wanted:
                close_list()
                out.append(f"<{wanted}>")
                list_type = wanted
            content = item.group(2)
            task = re.match(r"^\[([ xX])\]\s+(.*)$", content)
            if task:
                mark = "☑" if task.group(1).lower() == "x" else "☐"
                out.append(f'<li class="task">{mark} {_inline(task.group(2))}</li>')
            else:
                out.append(f"<li>{_inline(content)}</li>")
        else:
            close_list()
            paragraph.append(stripped)
        i += 1
    flush_paragraph(); close_list()
    return Markup('<div class="md">' + "".join(out) + "</div>")
