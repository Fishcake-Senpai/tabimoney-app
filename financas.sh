#!/bin/sh
# Linha de comando das finanças no Mac/Linux (para você e para agentes de IA). Ex.: ./financas.sh gastos resumo
DIR=$(cd "$(dirname "$0")" && pwd)
PYTHONPATH="$DIR" PYTHONIOENCODING=utf-8 exec "$DIR/.venv/bin/python" -m app.cli "$@"
