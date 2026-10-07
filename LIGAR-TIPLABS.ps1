# TipLabs - liga tudo o que o sistema precisa, num clique.
#
# Faz, nesta ordem:
#   1. confere o tunel da Cloudflare (servico do Windows, costuma subir sozinho)
#   2. mata processo velho travado na porta, se houver
#   3. sobe a fabrica sem janela visivel, com a saida gravada num arquivo de log
#   4. espera ela responder de verdade e abre o painel no navegador
#   5. sobe o MCP (https://mcp.bbnews.cc), que o Claude Code dos clientes usa
#
# A fabrica roda escondida de proposito: uma janela de console do Windows trava
# o programa inteiro se alguem clicar dentro dela sem querer (entra em "modo de
# selecao de texto" e pausa a saida). Ja aconteceu. Sem janela, nao tem como.
#
# Para desligar, use o DESLIGAR-TIPLABS.bat.
#
# Quem chama este arquivo e o LIGAR-TIPLABS.bat, que e o de clicar duas vezes.

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$PASTA  = 'E:\fabrica-para-amigo'
$PORTA  = 8080
$PAINEL = 'https://editor-video-dark.vercel.app'
$LOG    = Join-Path $PASTA 'fabrica.log'
$PORTA_MCP = 8092
$URL_MCP   = 'https://mcp.bbnews.cc'
$LOG_MCP   = Join-Path $PASTA 'mcp.log'

function Passo($texto, $cor = 'Gray') { Write-Host $texto -ForegroundColor $cor }

Clear-Host
Write-Host ''
Passo '  ================================================' DarkCyan
Passo '   TipLabs - ligando o sistema' Cyan
Passo '  ================================================' DarkCyan
Write-Host ''

# Diz se a fabrica esta viva. O 401 conta como viva: e ela recusando por falta
# de token, ou seja, respondeu.
function FabricaResponde {
    try {
        Invoke-WebRequest "http://localhost:$PORTA/api/projetos" -UseBasicParsing -TimeoutSec 5 | Out-Null
        return $true
    } catch {
        return ($_.Exception.Response.StatusCode.value__ -eq 401)
    }
}

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = "$env:USERPROFILE\.local\bin\uv.exe" }

# Sobe o MCP escondido, se ele nao estiver de pe. Ele usa a mesma pasta da
# fabrica, entao os dois estao sempre na mesma versao.
function LigarMcp {
    if (Get-NetTCPConnection -LocalPort $PORTA_MCP -State Listen -ErrorAction SilentlyContinue) {
        Passo "  MCP: ja estava rodando ($URL_MCP)" Green
        return
    }
    if (Test-Path $LOG_MCP) { Remove-Item $LOG_MCP -Force -ErrorAction SilentlyContinue }
    Start-Process -FilePath $uv `
        -ArgumentList @('run', '--no-sync', 'fabrica', 'mcp', '--porta', "$PORTA_MCP", '--url-publica', $URL_MCP) `
        -WorkingDirectory $PASTA `
        -WindowStyle Hidden `
        -RedirectStandardOutput $LOG_MCP `
        -RedirectStandardError "$LOG_MCP.erros"
    foreach ($i in 1..20) {
        Start-Sleep -Seconds 1
        if (Get-NetTCPConnection -LocalPort $PORTA_MCP -State Listen -ErrorAction SilentlyContinue) {
            Passo "  MCP no ar: $URL_MCP" Green
            return
        }
    }
    Passo "  O MCP nao subiu. Veja $LOG_MCP.erros" Red
}

# ---------------------------------------------------------------
# 1. Tunel
# ---------------------------------------------------------------
$svc = Get-Service cloudflared -ErrorAction SilentlyContinue
if (-not $svc) {
    Passo '  [1/3] Tunel: nao instalado nesta maquina' Red
    Passo '        O painel na internet nao vai alcancar a fabrica.' DarkGray
} elseif ($svc.Status -ne 'Running') {
    Passo '  [1/3] Tunel: estava parado, iniciando...' Yellow
    try {
        Start-Service cloudflared
        Passo '        tunel de pe' Green
    } catch {
        Passo '        nao consegui iniciar (precisa de administrador)' Red
    }
} else {
    Passo '  [1/3] Tunel: de pe' Green
}

# ---------------------------------------------------------------
# 2. Porta livre?
# ---------------------------------------------------------------
$emUso = Get-NetTCPConnection -LocalPort $PORTA -State Listen -ErrorAction SilentlyContinue

if ($emUso -and (FabricaResponde)) {
    Passo '  [2/3] Fabrica: ja estava rodando' Green
    Passo '  [3/3] Nada a fazer' Green
    LigarMcp
    Write-Host ''
    Passo "  Abrindo $PAINEL" Cyan
    Start-Process $PAINEL
    Write-Host ''
    Passo '  Tudo pronto. Pode fechar esta janela.' Green
    Write-Host ''
    Read-Host '  Aperte Enter para sair'
    exit
}

if ($emUso) {
    # porta ocupada por algo que nao responde: processo velho preso.
    # Se nao matar, a fabrica nova nem sobe, e a velha segue respondendo
    # com configuracao antiga - foi exatamente o que ja nos atrapalhou antes.
    Passo '  [2/3] Havia um processo travado na porta, encerrando...' Yellow
    Get-NetTCPConnection -LocalPort $PORTA -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
} else {
    Passo '  [2/3] Porta livre' Green
}

# ---------------------------------------------------------------
# 3. Sobe a fabrica ESCONDIDA, sem janela para clicar sem querer
# ---------------------------------------------------------------
Passo '  [3/3] Subindo a fabrica...' Yellow

if (Test-Path $LOG) { Remove-Item $LOG -Force -ErrorAction SilentlyContinue }

Start-Process -FilePath $uv `
    -ArgumentList @('run', 'fabrica', 'servidor', '--porta', "$PORTA") `
    -WorkingDirectory $PASTA `
    -WindowStyle Hidden `
    -RedirectStandardOutput $LOG `
    -RedirectStandardError "$LOG.erros"

# espera responder de verdade, em vez de confiar que subiu
$pronta = $false
foreach ($i in 1..40) {
    Start-Sleep -Seconds 1
    if (FabricaResponde) { $pronta = $true; break }
}

Write-Host ''
if ($pronta) {
    Passo '  Fabrica no ar (rodando escondida, sem janela).' Green
    LigarMcp
    Write-Host ''
    Passo "  Abrindo $PAINEL" Cyan
    Start-Process $PAINEL
    Write-Host ''
    Passo '  Tudo pronto!' Green
    Passo '  Para desligar depois, use o DESLIGAR-TIPLABS.bat.' DarkGray
} else {
    Passo '  A fabrica nao respondeu a tempo.' Red
    Passo "  Veja o que aconteceu em: $LOG" DarkGray
    Passo "  E em: $LOG.erros" DarkGray
}

Write-Host ''
Read-Host '  Aperte Enter para sair'
