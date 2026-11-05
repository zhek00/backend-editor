# TipLabs - vigia. Roda escondido, ligado pelo LIGAR-TIPLABS, e confere a cada minuto se a fabrica (porta 8080)
# esta de pe E respondendo. Se caiu, ou ficou travada sem responder duas vezes seguidas, e religada sozinha.
# O DESLIGAR-TIPLABS para o vigia antes de desligar o resto (senao ele religaria tudo).

$PASTA     = $PSScriptRoot
$PORTA     = 8080
$LOG       = Join-Path $PASTA 'vigia.log'
$PID_FILE  = Join-Path $PASTA 'vigia.pid'

# um vigia so: o segundo que abrir sai na hora
$criado = $false
$mutex = New-Object System.Threading.Mutex($true, 'Global\TipLabsVigia', [ref]$criado)
if (-not $criado) { exit }
Set-Content -Path $PID_FILE -Value $PID -Encoding ascii

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = "$env:USERPROFILE\.local\bin\uv.exe" }

function Anotar($texto) {
    Add-Content -Path $LOG -Value ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $texto) -Encoding utf8
}

# Responde? Qualquer resposta HTTP conta (401 sem token): so o silencio e problema.
function Responde($url) {
    try {
        Invoke-WebRequest $url -Method Get -UseBasicParsing -TimeoutSec 20 | Out-Null
        return $true
    } catch {
        return [bool]$_.Exception.Response
    }
}

function Escutando($porta) {
    return [bool](Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue)
}

function Matar($porta) {
    Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

# o editor servido pela fabrica, procurado como no LIGAR-TIPLABS (PastaDoEditor): religada sem ele, o editor sumiria
function ArgsDoEditor {
    $acima = Split-Path $PASTA -Parent
    foreach ($p in @((Join-Path $PASTA 'front-editor'), (Join-Path $acima 'front-editor'), (Join-Path $acima 'tiplabs\front-editor'))) {
        if (Test-Path (Join-Path $p 'index.html')) { return @('--frontend', $p) }
    }
    return @()
}

function LigarFabrica {
    Start-Process -FilePath $uv -ArgumentList (@('run', '--no-sync', 'fabrica', 'servidor', '--porta', "$PORTA") + (ArgsDoEditor)) `
        -WorkingDirectory $PASTA -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $PASTA 'fabrica.log') -RedirectStandardError (Join-Path $PASTA 'fabrica.log.erros')
}

$servicos = @(
    # /api/saude responde na hora; a /api/projetos passava dos 20 s com a criacao ocupada e o vigia reiniciava a
    # fabrica no meio do video (2026-10-27). Fabrica antiga, sem a /api/saude, responde 404: conta como viva
    @{ Nome = 'fabrica'; Porta = $PORTA;     Url = "http://localhost:$PORTA/api/saude"; Ligar = ${function:LigarFabrica}; Falhas = 0 }
)

Anotar 'vigia ligado'
while ($true) {
    foreach ($s in $servicos) {
        if (-not (Escutando $s.Porta)) {
            Anotar "$($s.Nome) caiu: ligando de novo"
            & $s.Ligar
            $s.Falhas = 0
            continue
        }
        if (Responde $s.Url) {
            $s.Falhas = 0
            continue
        }
        $s.Falhas++
        # reiniciar mata o video que esta sendo feito: so depois de 3 minutos seguidos sem nenhuma resposta
        if ($s.Falhas -ge 3) {
            Anotar "$($s.Nome) travado (sem responder 3 vezes seguidas): reiniciando"
            Matar $s.Porta
            & $s.Ligar
            $s.Falhas = 0
        }
    }
    # o tunel da Cloudflare e servico do Windows; se parou, tenta subir (precisa de administrador)
    $svc = Get-Service cloudflared -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -ne 'Running') {
        try { Start-Service cloudflared -ErrorAction Stop; Anotar 'tunel parado: ligado de novo' } catch { }
    }
    Start-Sleep -Seconds 60
}
