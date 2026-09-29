@echo off
REM TipLabs - clique duas vezes neste arquivo para ligar o sistema.
REM Ele so chama o LIGAR-TIPLABS.ps1, que e quem faz o trabalho.
REM O -ExecutionPolicy Bypass e necessario porque o Windows, por padrao,
REM nao deixa rodar script do PowerShell com dois cliques.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0LIGAR-TIPLABS.ps1"
