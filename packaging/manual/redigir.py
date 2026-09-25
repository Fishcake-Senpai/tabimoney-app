"""Cobre dados pessoais das capturas de tela do manual e grava as versões limpas em packaging/manual/imagens.

Uso (uma vez, quando as capturas mudarem):
    .venv\\Scripts\\python.exe packaging\\manual\\redigir.py <pasta-com-as-capturas-originais>

As capturas originais têm Client ID, Item IDs, final de conta/cartão e chave da brapi: não versione a pasta
original, só o resultado deste script.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent / "imagens"

# arquivo original (sufixo) -> (nome limpo, [áreas a cobrir (x0, y0, x1, y1)])
# CROP_TOP: pixels a cortar no topo (barra do navegador do autor, com as extensões dele)
CROP_TOP = {"220324.png": 40}
SHOTS = {
    "220324.png": ("01-meupluggy-inicio.png", []),
    "220406.png": ("02-meupluggy-conexoes.png", []),
    "220459.png": ("03-dashboard-aplicacoes.png", [(340, 452, 592, 478)]),
    "220526.png": ("04-demo-app-credenciais.png", [(82, 62, 332, 90)]),
    "220558.png": ("05-demo-conectar-conta.png", []),
    "220627.png": ("06-conector-meupluggy.png", []),
    "220746.png": ("07-item-conectado.png", [(412, 112, 652, 134)]),
    "220757.png": ("08-item-id.png", [(82, 35, 322, 58)]),
    "221019.png": ("09-tabimoney-configuracoes.png", [(333, 438, 940, 468), (322, 520, 976, 630)]),
    "221122.png": ("10-brapi-painel.png", [(560, 370, 730, 398)]),
}


def _font(size: int):
    for name in ("segoeui.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def redact(image: Image.Image, box: tuple[int, int, int, int]) -> None:
    """Tampa sólida (não borrão, que pode ser revertido) na cor do fundo ao redor, com a palavra 'oculto'."""
    x0, y0, x1, y1 = box
    background = image.getpixel((max(0, x0 - 4), min(image.height - 1, y0 + 2)))
    draw = ImageDraw.Draw(image)
    luminance = sum(background[:3]) / 3
    fill = tuple(int(c * 0.9) for c in background[:3]) if luminance > 128 else tuple(min(255, c + 22) for c in background[:3])
    draw.rounded_rectangle(box, radius=6, fill=fill)
    label = "oculto"
    font = _font(max(11, min(16, (y1 - y0) - 8)))
    w = draw.textlength(label, font=font)
    ink = (120, 130, 128) if luminance > 128 else (150, 163, 160)
    draw.text(((x0 + x1 - w) / 2, (y0 + y1) / 2), label, font=font, fill=ink, anchor="lm")


def main(source: Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for original in sorted(source.glob("*.png")):
        match = next((v for k, v in SHOTS.items() if original.name.endswith(k)), None)
        if not match:
            continue
        name, boxes = match
        image = Image.open(original).convert("RGB")
        top = next((v for k, v in CROP_TOP.items() if original.name.endswith(k)), 0)
        if top:
            image = image.crop((0, top, image.width, image.height))
        for box in boxes:
            redact(image, box)
        image.save(OUT / name, optimize=True)
        print(f"{original.name} -> {name} ({len(boxes)} área(s) coberta(s))")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "dist/images"))
