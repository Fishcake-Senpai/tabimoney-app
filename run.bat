@echo off
rem Abre o Tabimoney a partir do codigo (para quem clonou o repositorio). Quem recebeu o Tabimoney.exe usa o exe.
rem Clicar de novo reinicia o app. Para ver o log na tela: .venv\Scripts\python.exe -m app.launch --primeiro-plano
title Tabimoney
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando o ambiente local do aplicativo...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo Nao foi possivel criar o ambiente. Instale o Python 3.11 ou mais recente.
        pause
        exit /b 1
    )
)

echo Instalando ou atualizando as dependencias locais...
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo A instalacao das dependencias falhou. Confira sua conexao com a internet e tente novamente.
    pause
    exit /b 1
)

set "PYTHONIOENCODING=utf-8"
.venv\Scripts\python.exe -m app.launch
endlocal
