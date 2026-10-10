# TipLabs - liga tudo o que o sistema precisa, num clique.
#
# Faz, nesta ordem:
#   0. baixa a ultima versao do GitHub (git pull) e, se chegou versao nova com a fabrica
#      ja ligada, pergunta se pode reiniciar: o programa que esta rodando so pega o codigo
#      novo quando sobe de novo
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

$PASTA  = $PSScriptRoot   # a pasta onde este arquivo esta: serve em qualquer computador
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
    # o MCP so sobe em quem vende (tem os tokens dos clientes); na fabrica de um amigo ele fica desligado
    if (-not (Test-Path (Join-Path $PASTA 'clientes_mcp.json'))) { return }
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

# Sobe o vigia escondido (VIGIA-TIPLABS.ps1): a cada minuto ele confere a fabrica e o MCP e religa o que cair ou
# travar. Se ja houver um vigia, o novo sai sozinho.
function LigarVigia {
    Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', (Join-Path $PASTA 'VIGIA-TIPLABS.ps1')) `
        -WindowStyle Hidden
    Passo '  Vigia ligado: religa a fabrica e o MCP se cairem.' Green
}

# Roda o git nesta pasta e devolve o que ele escreveu (saida e erro juntos, em texto).
function RodarGit { (& git -C $PASTA @args 2>&1 | ForEach-Object { "$_" } | Out-String).Trim() }

# Para o processo que escuta na porta e os de cima dele que sao da fabrica (o fabrica.exe e o python do .venv
# ficavam vivos quando so o de baixo morria).
function PararPorta($porta) {
    $ids = Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique
    foreach ($id in $ids) {
        $topo = $id
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
        while ($proc) {
            $pai = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)" -ErrorAction SilentlyContinue
            if (-not $pai -or $pai.CommandLine -notmatch 'fabrica') { break }
            $topo = $pai.ProcessId
            $proc = $pai
        }
        & taskkill /T /F /PID $topo 2>&1 | Out-Null
    }
}

# Desliga vigia, MCP e fabrica, como o DESLIGAR-TIPLABS, para subirem de novo ja na versao nova.
function DesligarTudo {
    $pidVigia = Join-Path $PASTA 'vigia.pid'
    if (Test-Path $pidVigia) {
        $idVigia = (Get-Content $pidVigia -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($idVigia) { Stop-Process -Id ([int]$idVigia) -Force -ErrorAction SilentlyContinue }
        Remove-Item $pidVigia -Force -ErrorAction SilentlyContinue
    }
    PararPorta $PORTA_MCP
    PararPorta $PORTA
    Start-Sleep -Seconds 2
}

# Baixa a ultima versao do GitHub. Devolve $true se chegou versao nova.
# Pedido do usuario em 2026-10-10: o PC de um amigo seguia com uma versao antiga (o Haiku julgando as fotos, que a
# fabrica deixou de fazer em 09/10), porque ninguem dava git pull. Mudanca local em arquivo do Git (o e-mail do
# Wikimedia no config.yaml) e guardada antes e posta de volta depois; se ela bater com a versao nova, o arquivo fica
# na versao nova e a mudanca fica guardada no git stash. Sem internet, sem RodarGit ou com commit local que o GitHub nao
# tem, segue com a versao de agora: atualizar nunca impede de ligar.
function Atualizar {
    if (-not (Get-Command git -ErrorAction SilentlyContinue) -or -not (Test-Path (Join-Path $PASTA '.git'))) {
        Passo '  Atualizacao: esta pasta nao veio do GitHub (sem o Git), seguindo com a versao atual' Yellow
        return $false
    }
    $env:GIT_TERMINAL_PROMPT = '0'   # sem senha guardada, falha na hora em vez de ficar esperando
    $saida = RodarGit fetch --quiet
    if ($LASTEXITCODE -ne 0) {
        Passo '  Atualizacao: nao consegui falar com o GitHub, seguindo com a versao atual' Yellow
        Passo "        $(($saida -split "`r?`n")[-1])" DarkGray
        return $false
    }
    $novos = RodarGit rev-list --count 'HEAD..@{u}'
    if ($LASTEXITCODE -ne 0) {
        Passo '  Atualizacao: este ramo nao segue nenhum ramo do GitHub, seguindo com a versao atual' Yellow
        return $false
    }
    if ($novos -eq '0') {
        Passo '  Atualizacao: ja esta na ultima versao' Green
        return $false
    }

    Passo "  Atualizacao: $novos mudanca(s) nova(s) no GitHub, baixando..." Yellow
    $antes = RodarGit rev-parse HEAD
    $guardou = $false
    if (RodarGit status --porcelain --untracked-files=no) {
        RodarGit stash push --quiet -m 'LIGAR-TIPLABS: mudancas locais antes de atualizar' | Out-Null
        $guardou = ($LASTEXITCODE -eq 0)
    }
    $saida = RodarGit merge --ff-only --quiet '@{u}'
    $atualizou = ($LASTEXITCODE -eq 0)
    if ($guardou) {
        RodarGit stash pop --quiet | Out-Null
        if ($LASTEXITCODE -ne 0) {
            # a mudanca local bate com a versao nova: o arquivo fica na versao nova, a mudanca fica no stash
            $conflitos = @((RodarGit diff --name-only --diff-filter=U) -split "`r?`n" | Where-Object { $_ })
            RodarGit reset --quiet | Out-Null
            foreach ($arquivo in $conflitos) { RodarGit checkout HEAD '--' $arquivo | Out-Null }
            Passo "        sua mudanca em $($conflitos -join ', ') bateu com a versao nova: o arquivo ficou na versao nova" Yellow
            Passo '        e a sua mudanca ficou guardada (git stash list). Confira se precisa refazer.' Yellow
        }
    }
    if (-not $atualizou) {
        Passo '        nao deu para atualizar (esta pasta tem commit que o GitHub nao tem), seguindo com a versao atual' Red
        Passo "        $(($saida -split "`r?`n")[-1])" DarkGray
        return $false
    }

    (RodarGit log --oneline --no-decorate "$antes..HEAD" -n 8) -split "`r?`n" | ForEach-Object { Passo "        $_" DarkGray }
    # dependencia nova (pyproject.toml ou uv.lock): instala antes de subir; o MCP sobe com --no-sync
    if (RodarGit diff --name-only $antes HEAD '--' pyproject.toml uv.lock) {
        Passo '        dependencias mudaram, instalando...' Yellow
        & $uv sync --directory $PASTA 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Passo '        o uv sync falhou: rode "uv sync" nesta pasta com a fabrica desligada' Red }
    }
    Passo '        fabrica atualizada' Green
    return $true
}

# ---------------------------------------------------------------
# 0. Atualizacao
# ---------------------------------------------------------------
if (Atualizar) {
    $ligada = (Get-NetTCPConnection -LocalPort $PORTA -State Listen -ErrorAction SilentlyContinue) -or
              (Get-NetTCPConnection -LocalPort $PORTA_MCP -State Listen -ErrorAction SilentlyContinue)
    if ($ligada) {
        Write-Host ''
        Passo '  A fabrica ja estava ligada, com a versao antiga. Ela so usa a nova depois de reiniciar.' Yellow
        Passo '  Um video sendo criado pelo site para (retome pelo editor); os do MCP voltam sozinhos.' DarkGray
        $resposta = Read-Host '  Reiniciar agora? (S/n)'
        if ($resposta -notmatch '^\s*n') {
            DesligarTudo
            Passo '  Fabrica desligada, subindo de novo na versao nova.' Green
        } else {
            Passo '  Seguindo com a versao antiga ligada. Para usar a nova: DESLIGAR e LIGAR de novo.' Yellow
        }
    }
}
Write-Host ''

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
    LigarVigia
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
    LigarVigia
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
