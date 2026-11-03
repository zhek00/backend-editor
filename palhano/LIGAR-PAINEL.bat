@echo off
chcp 65001 >nul
title Robô PALHANO - painel
cd /d "%~dp0.."
echo Ligando o painel do Robô PALHANO em http://127.0.0.1:8300
echo Deixe esta janela aberta. Para desligar, feche a janela.
start "" http://127.0.0.1:8300
if exist .venv (uv run --no-sync fabrica painel) else (uv run fabrica painel)
pause
