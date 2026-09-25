#!/bin/sh
# Abre o Tabimoney a partir do código no Mac (ou Linux). Quem baixou o Tabimoney.app não precisa disto.
# Dois cliques no Finder abrem o Terminal e rodam este arquivo. Clicar de novo reinicia o app.
cd "$(dirname "$0")" || exit 1

pausar() { printf '\nPressione Enter para fechar.'; read -r _; }

if [ ! -x .venv/bin/python ]; then
    echo "Criando o ambiente local do aplicativo..."
    if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        echo "Instale o Python 3.11 ou mais recente (python.org) e abra de novo."
        pausar; exit 1
    fi
    python3 -m venv .venv || { echo "Não foi possível criar o ambiente."; pausar; exit 1; }
fi

echo "Instalando ou atualizando as dependências locais..."
if ! .venv/bin/python -m pip install -q -r requirements.txt; then
    echo "A instalação das dependências falhou. Confira sua conexão com a internet e tente novamente."
    pausar; exit 1
fi

PYTHONIOENCODING=utf-8 exec .venv/bin/python -m app.launch
