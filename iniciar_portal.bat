@echo off
chcp 65001 > nul
title Portal Apuração PIS/COFINS — MSB Medical

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   Portal Web — Apuração PIS/COFINS               ║
echo  ║   MSB Medical System do Brasil                   ║
echo  ╚══════════════════════════════════════════════════╝
echo.

set PYTHON="C:\Program Files\TacticalAgent\python\py3.11.9_amd64\python.exe"
set PYTHONIOENCODING=utf-8

echo  [*] Verificando dependencias...
%PYTHON% -m pip install fastapi uvicorn python-multipart pandas openpyxl --quiet
if errorlevel 1 (
    echo  [!] Falha ao instalar dependencias. Verifique sua conexao.
    pause
    exit /b 1
)
echo  [*] Dependencias OK.

echo  [*] Iniciando servidor em http://localhost:8000
echo  [*] Pressione Ctrl+C para encerrar.
echo.

cd /d "%~dp0"
%PYTHON% iniciar_portal.py

pause
