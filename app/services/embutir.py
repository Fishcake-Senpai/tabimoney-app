"""Arquivos do app embutidos num HTML que abre sozinho, offline e com dois cliques (relatório exportado, manual)."""
from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path

from markupsafe import Markup

STATIC = Path(__file__).resolve().parent.parent / "static"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".woff2": "font/woff2", ".svg": "image/svg+xml"}

# Mesmos recortes de app/static/style.css: o navegador só baixa (aqui, decodifica) o arquivo que o texto usa.
_LATIN = ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, "
          "U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD")
_LATIN_EXT = ("U+0100-02BA, U+02BD-02C5, U+02C7-02CC, U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, "
              "U+1D00-1DBF, U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, U+2113, U+2C60-2C7F, U+A720-A7FF")


def data_uri(path: Path) -> str:
    return f"data:{MIME[path.suffix]};base64,{base64.b64encode(path.read_bytes()).decode()}"


@lru_cache(maxsize=1)
def font_faces() -> Markup:
    """@font-face da Inter com os dois arquivos embutidos."""
    faces = []
    for name, ranges in (("inter-latin.woff2", _LATIN), ("inter-latin-ext.woff2", _LATIN_EXT)):
        faces.append(
            '@font-face { font-family: "Inter"; font-style: normal; font-weight: 100 900; font-display: swap; '
            f'src: url("{data_uri(STATIC / "fonts" / name)}") format("woff2"); unicode-range: {ranges}; }}'
        )
    return Markup("\n".join(faces))


@lru_cache(maxsize=1)
def _symbols() -> dict[str, str]:
    text = (STATIC / "icons.svg").read_text(encoding="utf-8")
    return {m.group(1): m.group(0) for m in re.finditer(r'<symbol id="i-([\w-]+)".*?</symbol>', text, re.S)}


def icon_sprite(names: set[str] | list[str]) -> Markup:
    """Só os <symbol> pedidos de app/static/icons.svg, para usar com <use href="#i-nome">."""
    symbols = _symbols()
    body = "".join(symbols[n] for n in sorted(set(names)) if n in symbols)
    return Markup(f'<svg xmlns="http://www.w3.org/2000/svg" class="sprite" aria-hidden="true">{body}</svg>')


def brand_image(name: str) -> str:
    return data_uri(STATIC / "brand" / name)
