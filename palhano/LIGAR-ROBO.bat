@echo off
chcp 65001 >nul
title Robô PALHANO - robô
cd /d "%~dp0.."
rem Para usar um painel na internet, troque o endereço abaixo (ex.: https://painel.seudominio.com)
if "%PALHANO_PAINEL%"=="" set PALHANO_PAINEL=http://127.0.0.1:8300
echo Robô PALHANO. Deixe esta janela aberta enquanto quiser produzir.
if exist .venv (uv run --no-sync fabrica robo --painel %PALHANO_PAINEL%) else (uv run fabrica robo --painel %PALHANO_PAINEL%)
pause
