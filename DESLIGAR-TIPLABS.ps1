# TipLabs - desliga a fabrica (o tunel continua de pe, e servico do Windows).
# Como a fabrica agora roda escondida (sem janela), este e o jeito de para-la.

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$PORTA = 8080

Clear-Host
Write-Host ''
Write-Host '  TipLabs - desligando a fabrica' -ForegroundColor Cyan
Write-Host ''

$processos = Get-NetTCPConnection -LocalPort $PORTA -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique

if (-not $processos) {
    Write-Host '  A fabrica ja estava desligada.' -ForegroundColor Yellow
} else {
    $processos | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
    Write-Host '  Fabrica desligada.' -ForegroundColor Green
}

Write-Host ''
Write-Host '  O tunel continua ligado (nao afeta ele). O painel na internet' -ForegroundColor DarkGray
Write-Host '  vai mostrar erro ate voce rodar o LIGAR-TIPLABS.bat de novo.' -ForegroundColor DarkGray
Write-Host ''
Read-Host '  Aperte Enter para sair'
