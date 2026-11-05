# Gera dist\RoboDaFabrica-Instalar.exe com o IExpress, que vem no Windows: nada para instalar aqui.
# O .exe e so o comeco: ele pergunta o endereco do Radar e a chave da maquina e baixa a fabrica de la, como o instalador
# do Robo do Dotti, que tambem tem poucos MB. Nada de chave, cookie ou .env vai dentro dele.

$PASTA = $PSScriptRoot
$DIST = Join-Path $PASTA 'dist'
$OBRA = Join-Path $env:TEMP "instalador-robo-$PID"
New-Item -ItemType Directory -Force $DIST, $OBRA | Out-Null

Copy-Item (Join-Path $PASTA 'INSTALAR-ROBO.ps1') $OBRA
$cmd = @'
@echo off
title Robo da Fabrica
echo.
echo   Robo da Fabrica: instalacao
echo   A chave sai do Radar, em Acompanhar, Maquinas.
echo.
set /p RADAR=  Endereco do Radar:
set /p CHAVE=  Chave desta maquina:
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALAR-ROBO.ps1" -Radar "%RADAR%" -Chave "%CHAVE%"
echo.
pause
'@
Set-Content -Path (Join-Path $OBRA 'instalar.cmd') -Value $cmd -Encoding ascii

$saida = Join-Path $DIST 'RoboDaFabrica-Instalar.exe'
$sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$saida
FriendlyName=Robo da Fabrica
AppLaunched=cmd /c instalar.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
SourceFiles=SourceFiles
[Strings]
FILE0="instalar.cmd"
FILE1="INSTALAR-ROBO.ps1"
[SourceFiles]
SourceFiles0=$OBRA\
[SourceFiles0]
%FILE0%=
%FILE1%=
"@
$arquivo = Join-Path $OBRA 'robo.sed'
Set-Content -Path $arquivo -Value $sed -Encoding ascii
Start-Process -FilePath "$env:WINDIR\System32\iexpress.exe" -ArgumentList @('/N', '/Q', $arquivo) -Wait
Remove-Item $OBRA -Recurse -Force
if (-not (Test-Path $saida)) { throw 'O IExpress nao gerou o instalador.' }
Write-Host "Instalador: $saida ($([int]((Get-Item $saida).Length / 1KB)) KB)" -ForegroundColor Green
