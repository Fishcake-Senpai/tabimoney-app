@echo off
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
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo A instalacao das dependencias falhou. Confira sua conexao com a internet e tente novamente.
    pause
    exit /b 1
)

echo Iniciando em http://127.0.0.1:8765
.venv\Scripts\python.exe -m app.launch
if errorlevel 1 (
    echo O aplicativo encerrou com erro. Confira a mensagem acima.
    pause
)
endlocal
