"""Gera o manual de conexões num arquivo HTML só, com fonte e imagens embutidas (abre offline, com dois cliques).

    .venv\\Scripts\\python.exe packaging\\manual\\gerar.py [destino]      (padrão: dist\\Manual de conexões.html)

As capturas vêm de packaging/manual/imagens, já com os dados pessoais cobertos (ver redigir.py).
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
SOURCES = [HERE / "imagens", ROOT / "app" / "static" / "brand"]
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".woff2": "font/woff2"}


def _data_uri(path: Path) -> str:
    return f"data:{MIME[path.suffix]};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _image(name: str) -> str:
    for folder in SOURCES:
        if (folder / name).exists():
            return _data_uri(folder / name)
    raise FileNotFoundError(f"Imagem do manual não encontrada: {name}")


def build(target: Path) -> Path:
    version = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")).group(1)
    html = (HERE / "manual.html").read_text(encoding="utf-8")
    html = html.replace("{{VERSAO}}", version)
    html = re.sub(r'img:([\w.-]+\.png)', lambda m: _image(m.group(1)), html)
    html = re.sub(r'font:([\w.-]+\.woff2)', lambda m: _data_uri(ROOT / "app" / "static" / "fonts" / m.group(1)), html)
    leftover = re.findall(r'(?:img|font):[\w.-]+', html)
    if leftover:
        raise ValueError(f"Referências não resolvidas: {leftover}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


if __name__ == "__main__":
    out = build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "Manual-de-conexoes.html")
    print(f"{out} ({out.stat().st_size // 1024} KB)")
