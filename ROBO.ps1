# Robo da fabrica: liga a fabrica desta maquina e pede videos ao Radar (fabrica/robo.py).
# Relanca depois de queda, com teto por hora. Saida 75 quer dizer "atualizei": relanca na hora, sem contar como queda.
# Saida 0 ou chave recusada encerram. O INSTALAR-ROBO.ps1 poe este arquivo na inicializacao do Windows.

$PASTA = $PSScriptRoot
$LOG   = Join-Path $PASTA 'robo.log'
$TETO  = 6
$quedas = @()

function FabricaNoAr {
    try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8080/' -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200 } catch { $false }
}

Set-Location $PASTA
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = "$env:USERPROFILE\.local\bin\uv.exe" }

while ($true) {
    if (-not (FabricaNoAr)) {
        Start-Process -FilePath $uv -ArgumentList @('run', '--no-sync', 'fabrica', 'servidor', '--porta', '8080') `
            -WorkingDirectory $PASTA -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $PASTA 'fabrica.log') -RedirectStandardError (Join-Path $PASTA 'fabrica.log.erros')
        foreach ($i in 1..40) { Start-Sleep -Seconds 1; if (FabricaNoAr) { break } }
    }
    & $uv run --no-sync fabrica maquina *>> $LOG
    $codigo = $LASTEXITCODE
    if ($codigo -eq 75) { continue }
    if ($codigo -eq 0) { break }
    $agora = Get-Date
    $quedas = @($quedas | Where-Object { ($agora - $_).TotalMinutes -lt 60 }) + $agora
    if ($quedas.Count -gt $TETO) {
        Add-Content $LOG "$agora o robo caiu $TETO vezes nesta hora e nao relanco mais. Veja o erro acima e reinicie."
        break
    }
    Add-Content $LOG "$agora o robo caiu com o codigo $codigo; relancando em 10 s"
    Start-Sleep -Seconds 10
}
