# Instala o robo nesta maquina. O RoboDaFabrica-Instalar.exe chama este arquivo; tambem da para rodar direto:
#   powershell -ExecutionPolicy Bypass -File INSTALAR-ROBO.ps1 -Radar https://endereco-do-radar -Chave rdm_...
# A chave sai do Radar, em Acompanhar > Maquinas. Se este arquivo nao estiver dentro de uma fabrica, ele baixa a fabrica
# do proprio Radar, instala o que falta (uv, FFmpeg) e deixa o robo ligando junto com o Windows.

param(
    [Parameter(Mandatory = $true)][string]$Radar,
    [Parameter(Mandatory = $true)][string]$Chave,
    [string]$Pasta = "$env:LOCALAPPDATA\FabricaRobo",
    [switch]$SemAtalho,
    [switch]$SemIniciar
)

$ErrorActionPreference = 'Stop'
$Radar = $Radar.TrimEnd('/')

if (Test-Path (Join-Path $PSScriptRoot 'pyproject.toml')) {
    $PASTA_FABRICA = $PSScriptRoot
} else {
    $PASTA_FABRICA = $Pasta
    Write-Host '  1/5  baixando a fabrica do Radar...' -ForegroundColor Cyan
    New-Item -ItemType Directory -Force $PASTA_FABRICA | Out-Null
    $zip = Join-Path $env:TEMP "fabrica-robo-$PID.zip"
    Invoke-WebRequest -Uri "$Radar/api/robo/pacote" -Headers @{ 'x-robo-chave' = $Chave } -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $PASTA_FABRICA -Force
    Remove-Item $zip -Force
}

Write-Host '  2/5  conferindo o uv...' -ForegroundColor Cyan
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $uv = "$env:USERPROFILE\.local\bin\uv.exe"
}

Write-Host '  3/5  conferindo o FFmpeg...' -ForegroundColor Cyan
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    winget install --id Gyan.FFmpeg -e --silent --accept-source-agreements --accept-package-agreements
}

Write-Host '  4/5  instalando a fabrica (leva uns minutos na primeira vez)...' -ForegroundColor Cyan
Push-Location $PASTA_FABRICA
& $uv sync --frozen --no-dev
$resultado = $LASTEXITCODE
Pop-Location
if ($resultado -ne 0) { throw "O uv nao instalou a fabrica (codigo $resultado)." }

$ENV_ARQUIVO = Join-Path $PASTA_FABRICA '.env'
if (-not (Test-Path $ENV_ARQUIVO)) { Copy-Item (Join-Path $PASTA_FABRICA '.env.exemplo') $ENV_ARQUIVO }
$linhas = @(Get-Content $ENV_ARQUIVO | Where-Object { $_ -notmatch '^ROBO_(RADAR|CHAVE)=' })
$linhas += "ROBO_RADAR=$Radar"
$linhas += "ROBO_CHAVE=$Chave"
Set-Content -Path $ENV_ARQUIVO -Value $linhas -Encoding utf8

Write-Host '  5/5  ligando junto com o Windows...' -ForegroundColor Cyan
$robo = Join-Path $PASTA_FABRICA 'ROBO.ps1'
if (-not $SemAtalho) {
    $atalho = Join-Path ([Environment]::GetFolderPath('Startup')) 'Robo da Fabrica.lnk'
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($atalho)
    $link.TargetPath = 'powershell.exe'
    $link.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$robo`""
    $link.WorkingDirectory = $PASTA_FABRICA
    $link.Save()
}
if (-not $SemIniciar) {
    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -WorkingDirectory $PASTA_FABRICA `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $robo)
}
Write-Host ''
Write-Host "  Pronto. A fabrica esta em $PASTA_FABRICA." -ForegroundColor Green
Write-Host '  Coloque as chaves de API desta maquina no .env dessa pasta. O log do robo fica em robo.log.' -ForegroundColor Green
