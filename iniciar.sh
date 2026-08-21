#!/usr/bin/env bash
# Clique duas vezes (ou rode ./iniciar.sh) para abrir o programa no navegador.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo
    echo "  Python nao encontrado. Instale em https://www.python.org/downloads/"
    echo
    read -rp "  Enter para fechar..."
    exit 1
fi

echo "  Preparando (so demora na primeira vez)..."
python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt

if [ ! -f "config/custos.xlsx" ]; then
    echo
    echo "  ATENCAO: falta a sua tabela de custos em config/custos.xlsx"
    echo "  Da para seguir assim mesmo: a pagina deixa voce enviar a tabela junto."
    echo
fi

( sleep 2; (command -v open >/dev/null && open http://127.0.0.1:8000) \
    || (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:8000) || true ) &

echo
echo "  Abrindo no navegador: http://127.0.0.1:8000"
echo "  Deixe esta janela aberta enquanto usa. Ctrl+C para encerrar."
echo
python3 -m promoml web
