@echo off
rem Gera dist\Tabimoney.exe (um arquivo so, com Python dentro) e dist\Tabimoney-<versao>.zip para enviar.
title Tabimoney - gerar executavel
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Rode o run.bat uma vez antes, para criar o ambiente .venv.
    pause
    exit /b 1
)

echo Instalando dependencias e o PyInstaller...
.venv\Scripts\python.exe -m pip install -q -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto erro

echo Gerando o executavel (leva 1 a 3 minutos)...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\tabimoney.spec
if errorlevel 1 goto erro

for /f %%v in ('.venv\Scripts\python.exe -c "from app import __version__; print(__version__)"') do set VERSAO=%%v
echo Conferindo o executavel...
dist\Tabimoney.exe --versao
if errorlevel 1 goto erro

copy /y packaging\LEIA-ME.txt dist\LEIA-ME.txt >nul
powershell -NoProfile -Command "Compress-Archive -Force -Path dist\Tabimoney.exe, dist\LEIA-ME.txt -DestinationPath dist\Tabimoney-%VERSAO%.zip"
if errorlevel 1 goto erro

echo.
echo Pronto:
echo   dist\Tabimoney.exe             (pode mandar direto)
echo   dist\Tabimoney-%VERSAO%.zip    (se o WhatsApp ou o e-mail recusar o .exe)
pause
exit /b 0

:erro
echo.
echo A geracao falhou. Confira as mensagens acima.
pause
exit /b 1
