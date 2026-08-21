@echo off
REM Clique duas vezes neste arquivo para abrir o programa no navegador.
cd /d "%~dp0"
title Promocoes Mercado Livre

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo  Python nao encontrado.
    echo.
    echo  Instale em https://www.python.org/downloads/
    echo  IMPORTANTE: marque "Add Python to PATH" na primeira tela do instalador.
    echo.
    pause
    exit /b 1
)

echo  Preparando (so demora na primeira vez)...
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo  Nao consegui instalar os componentes. Verifique sua conexao.
    pause
    exit /b 1
)

if not exist "config\custos.xlsx" (
    echo.
    echo  ATENCAO: falta a sua tabela de custos.
    echo  Copie sua planilha de precificacao para:  config\custos.xlsx
    echo.
    echo  Da para seguir assim mesmo: a pagina deixa voce enviar a tabela junto.
    echo.
)

start "" http://127.0.0.1:8000
echo.
echo  Abrindo no navegador: http://127.0.0.1:8000
echo  Deixe esta janela aberta enquanto usa. Feche-a para encerrar.
echo.
python -m promoml web
pause
