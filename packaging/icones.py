"""Gera app/static/icons.svg (sprite de ícones Lucide) a partir da lista abaixo.

    python packaging/icones.py

Baixa cada ícone do pacote lucide-static (versão fixa, licença ISC) e grava um <symbol id="i-NOME"> por ícone.
O app usa com o macro icon("nome") de app/templates/_ui.html. Ícone novo: acrescente o nome aqui e rode de novo.
Nomes em https://lucide.dev/icons. A licença vai junto, em app/static/LICENSE-lucide.txt.
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

VERSAO = "1.49.0"
BASE = f"https://unpkg.com/lucide-static@{VERSAO}"
ROOT = Path(__file__).resolve().parents[1]
DESTINO = ROOT / "app" / "static" / "icons.svg"
LICENCA = ROOT / "app" / "static" / "LICENSE-lucide.txt"

ICONES = sorted(set("""
    house wallet trending-up trending-down sparkles settings upload download eye eye-off refresh-cw bell plus
    chevron-down chevron-up chevron-left chevron-right arrow-right arrow-left arrow-up-right arrow-down-right
    arrow-up arrow-down x check circle-check circle-alert triangle-alert circle-help info search filter
    calendar pencil trash-2 columns-3 landmark credit-card piggy-bank banknote coins chart-line chart-column
    target shield-check scale file-text inbox arrow-left-right database palette tag history clock external-link
    copy lock key-round globe building-2 briefcase receipt repeat repeat-2 ticket graduation-cap plane paw-print
    heart-pulse shopping-cart shopping-bag utensils car circle-dashed gift fuel smartphone dumbbell baby
    book-open music film coffee bus bike wrench shirt gamepad-2 pill wifi zap droplet tv laptop scissors sprout
    sun moon monitor log-out power panel-left-close panel-left-open menu more-horizontal user-round users-round
    layers percent hand-coins calculator calendar-clock file-spreadsheet folder-open lightbulb star flag
    list-filter sliders-horizontal circle-dot cloud-upload hourglass
""".split()))


def baixar(caminho: str) -> str:
    with urllib.request.urlopen(f"{BASE}/{caminho}", timeout=30) as resposta:  # noqa: S310 - endereço fixo
        return resposta.read().decode("utf-8")


def miolo(svg: str) -> str:
    """Só os elementos de desenho, sem o <svg> de fora nem o comentário de licença."""
    corpo = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S)
    if not corpo:
        raise ValueError("SVG sem conteúdo")
    return " ".join(linha.strip() for linha in corpo.group(1).strip().splitlines() if linha.strip())


def main() -> int:
    simbolos, faltando = [], []
    for nome in ICONES:
        try:
            simbolos.append(f'<symbol id="i-{nome}" viewBox="0 0 24 24">{miolo(baixar(f"icons/{nome}.svg"))}</symbol>')
        except Exception as exc:  # noqa: BLE001 - lista o que falhou e segue
            faltando.append(f"{nome} ({exc})")
    if faltando:
        print("Não encontrados:\n  " + "\n  ".join(faltando), file=sys.stderr)
        return 1
    DESTINO.write_text(
        f"<!-- Ícones Lucide {VERSAO} (ISC, ver LICENSE-lucide.txt). Gerado por packaging/icones.py: não edite. -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg">\n' + "\n".join(simbolos) + "\n</svg>\n",
        encoding="utf-8", newline="\n",
    )
    LICENCA.write_text(baixar("LICENSE"), encoding="utf-8", newline="\n")
    print(f"{len(simbolos)} ícones em {DESTINO.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
