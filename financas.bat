@echo off
rem Linha de comando das finanças (para você e para agentes de IA). Ex.: financas gastos resumo
setlocal
set "PYTHONPATH=%~dp0"
set "PYTHONIOENCODING=utf-8"
"%~dp0.venv\Scripts\python.exe" -m app.cli %*
