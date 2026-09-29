"""Chamadas ao Claude pela sua assinatura, usando o Claude Code instalado no Mac.

O programa roda `claude -p` com a resposta presa a um esquema JSON. Nada sai dos
créditos de API. O consumo entra no limite de uso do plano, e cada chamada fica
registrada em uso_claude.json dentro do projeto para você acompanhar.
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime

_trava = threading.Lock()


def executavel():
    caminho = os.environ.get("FABRICA_CLAUDE_BIN") or shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
    if not os.path.exists(caminho):
        raise SystemExit("Não achei o Claude Code neste Mac. Instale em https://claude.com/claude-code e faça login.")
    return caminho


def perguntar(projeto, etapa, instrucoes, pedido, esquema, esforco="high", ler_arquivos=False):
    cfg = projeto.config.get("claude") or {}
    # o prompt de sistema pode ser grande (leva o roteiro inteiro), e no Windows o `claude`
    # é um .cmd executado via interpretador de comandos, com limite de ~8191 caracteres por
    # linha; por isso ele vai num arquivo temporário em vez de argumento de linha de comando
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as arq:
        arq.write(instrucoes)
        arquivo_sistema = arq.name

    comando = [
        executavel(), "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(esquema),
        "--append-system-prompt-file", arquivo_sistema,
        "--model", cfg.get("modelo_assinatura", "opus"),
        "--effort", esforco,
        "--no-session-persistence",
        "--permission-mode", "dontAsk",
    ]
    if ler_arquivos:
        comando += ["--tools", "Read", "--allowedTools", "Read"]
    else:
        comando += ["--tools", ""]
    # com uma chave de API no ambiente o Claude Code cobraria créditos em vez de usar a assinatura
    ambiente = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    try:
        r = subprocess.run(comando, input=pedido, capture_output=True, text=True, encoding="utf-8",
                           cwd=projeto.pasta, env=ambiente, timeout=cfg.get("tempo_maximo", 1800))
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"O Claude Code passou do tempo limite na etapa {etapa}.")
    finally:
        os.remove(arquivo_sistema)

    linhas = r.stdout.strip().splitlines()
    try:
        dados = json.loads(linhas[-1]) if linhas else {}
    except json.JSONDecodeError:
        raise RuntimeError(f"Resposta inesperada do Claude Code na etapa {etapa}. {r.stdout[-300:]} {r.stderr[-300:]}")

    mensagem = str(dados.get("result") or r.stderr or "")
    if dados.get("is_error") or r.returncode != 0 or not dados:
        texto = mensagem.lower()
        if "not logged in" in texto or "/login" in texto:
            raise SystemExit("O Claude Code não está conectado à sua conta. Abra o Terminal, rode claude e digite /login.")
        if "limit" in texto:
            raise SystemExit("O limite de uso da sua assinatura acabou por agora. Rode o mesmo comando mais tarde, a fábrica continua de onde parou.")
        raise RuntimeError(f"O Claude Code falhou na etapa {etapa}. {mensagem[:400]}")

    _registrar(projeto, etapa, dados)
    resposta = dados.get("structured_output")
    if resposta is None:
        try:
            resposta = json.loads(dados.get("result") or "")
        except json.JSONDecodeError:
            raise RuntimeError(f"O Claude Code não devolveu o formato esperado na etapa {etapa}.")
    return resposta


def _registrar(projeto, etapa, dados):
    uso = dados.get("usage") or {}
    linha = {
        "quando": datetime.now().isoformat(timespec="seconds"),
        "etapa": etapa,
        "tokens_lidos": sum(uso.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
        "tokens_escritos": uso.get("output_tokens") or 0,
        "equivalente_api_usd": dados.get("total_cost_usd") or 0,
    }
    with _trava:
        arquivo = projeto.caminho("uso_claude.json")
        historico = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
        historico.append(linha)
        arquivo.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")


def resumo_uso(projeto):
    arquivo = projeto.pasta / "uso_claude.json"
    if not arquivo.exists():
        return None
    historico = json.loads(arquivo.read_text(encoding="utf-8"))
    return {
        "chamadas": len(historico),
        "lidos": sum(h["tokens_lidos"] for h in historico),
        "escritos": sum(h["tokens_escritos"] for h in historico),
        "equivalente": sum(h["equivalente_api_usd"] for h in historico),
    }
