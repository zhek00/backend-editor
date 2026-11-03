"""Imagens pela assinatura do ChatGPT, sem chave de API e sem custo por imagem.

Pedido do usuário em 2026-11-01, no mesmo formato do Robô do Dotti: "criar as imagens pela assinatura". É o mesmo
caminho que o Radar já usa para o roteiro (o Claude Code deste computador pela assinatura do claude.ai, veja
radar/roteiro_claude.py): aqui quem entra é o Codex deste computador, logado com `codex login` na conta ChatGPT da
pessoa. O login fica em ~/.codex-fabrica/auth.json (o Radar grava pelo "Conectar outra conta") e a fábrica só o
lê — a chave OPENAI_API_KEY nunca entra nesta conta, senão a OpenAI cobraria por fora da assinatura.

A rota é a mesma que o Codex usa (https://chatgpt.com/backend-api/codex/responses), com a ferramenta de imagem
ligada. Ela NÃO é uma API pública da OpenAI: é a mesma porta do aplicativo, e a OpenAI pode mudá-la sem aviso. Por
isso nada aqui é obrigatório: quando a assinatura não responde (sem login, limite estourado, porta mudada), o perfil
cai no provedor de chave de API de sempre (imagens._gerar_uma).

O que gasta é o limite da assinatura, nas duas janelas que o ChatGPT conta: a de 5 horas e a da semana. Elas voltam
na resposta de cada pedido (cabeçalhos x-codex-*) e ficam guardadas em chatgpt_limites.json, para o Radar mostrar
quanto já foi usado sem precisar gerar nada."""
import base64
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .config import RAIZ

PASTA_CODEX = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))   # só para ler a versão do Codex
# O login é só da fábrica (2026-11-02): no ~/.codex ele era o mesmo do Robô do Dotti, e os dois renovando o mesmo
# login fizeram a OpenAI revogá-lo (token_revoked). O Radar grava nesta pasta (radar/chatgpt_conta.py).
PASTA_LOGIN = Path(os.environ.get("FABRICA_CODEX_HOME") or (Path.home() / ".codex-fabrica"))
LOGIN = PASTA_LOGIN / "auth.json"
LIMITES = RAIZ / "chatgpt_limites.json"

RESPOSTAS = "https://chatgpt.com/backend-api/codex/responses"
RENOVAR = "https://auth.openai.com/oauth/token"
CLIENTE_CODEX = "app_EMoamEEZ73f0CkXaXp7hrann"   # o client_id publicado do Codex CLI, o mesmo do `codex login`
VERSAO_CODEX_MINIMA = "0.163.0"
# o modelo da conversa só existe para chamar a ferramenta de imagem: o barato primeiro. A porta do Codex só aceita
# os modelos que o ChatGPT libera para a assinatura (models_cache.json do Codex), e eles mudam com o tempo — por
# isso a lista, e não um nome só: "model_not_found" passa para o próximo
MODELOS_CONVERSA = ("gpt-5.6-luna", "gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol")
MODELO_IMAGEM = "gpt-image-2"
TAMANHOS = {"16:9": "1536x1024", "3:2": "1536x1024", "1:1": "1024x1024", "9:16": "1024x1536"}
QUALIDADES = ("low", "medium", "high")
SOBRA_DO_TOKEN = 300                             # renova o token com 5 minutos de sobra

_trava = threading.Lock()


class SemLogin(RuntimeError):
    """Não há login do ChatGPT neste computador (ou ele venceu de vez): `codex login` resolve."""


class LimiteDaAssinatura(RuntimeError):
    """A assinatura bateu no limite da janela de 5 horas ou da semana."""


class SemImagemNaResposta(RuntimeError):
    """O ChatGPT respondeu, mas sem imagem (em geral o filtro de conteúdo recusou o pedido)."""


# ---------------------------------------------------------------- o login do Codex


def _ler_login() -> dict:
    try:
        return json.loads(LOGIN.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SemLogin(f"Não achei o login do ChatGPT em {LOGIN}. Ligue a conta em Radar › Integrações › "
                       "Conectar outra conta.")
    except (OSError, ValueError) as erro:
        raise SemLogin(f"Não consegui ler {LOGIN}: {str(erro)[:160]}")


def _gravar_login(dados: dict) -> None:
    """Grava por cima sem deixar o arquivo pela metade: o Codex lê o mesmo arquivo."""
    temporario = LOGIN.with_suffix(".gravando")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(LOGIN)
    try:
        os.chmod(LOGIN, 0o600)
    except OSError:
        pass                                     # no Windows a permissão não muda nada; o arquivo já é do usuário


def _dentro_do_jwt(token: str) -> dict:
    """O que o token diz, sem conferir assinatura nenhuma: só para saber quando vence, de quem é e qual plano."""
    partes = (token or "").split(".")
    if len(partes) < 2:
        return {}
    corpo = partes[1] + "=" * (-len(partes[1]) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(corpo))
    except (ValueError, TypeError):
        return {}


def _venceu(token: str) -> bool:
    fim = _dentro_do_jwt(token).get("exp")
    return not isinstance(fim, (int, float)) or time.time() > fim - SOBRA_DO_TOKEN


def _renovar(dados: dict) -> dict:
    """Troca o refresh_token por um access_token novo e grava os dois de volta, como o próprio Codex faz."""
    tokens = dados.get("tokens") or {}
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise SemLogin("O login do ChatGPT não tem refresh_token. Ligue a conta de novo em Radar › Integrações.")
    r = httpx.post(RENOVAR, timeout=30,
                   headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
                   data={"client_id": CLIENTE_CODEX, "grant_type": "refresh_token", "refresh_token": refresh,
                         "scope": "openid profile email"})
    if r.status_code in (400, 401):
        raise SemLogin("O login do ChatGPT venceu. Ligue a conta de novo em Radar › Integrações › Conectar outra conta.")
    if r.status_code != 200:
        raise RuntimeError(f"Não consegui renovar o login do ChatGPT ({r.status_code}): {r.text[:200]}")
    novo = r.json()
    for campo in ("access_token", "refresh_token", "id_token"):
        if novo.get(campo):
            tokens[campo] = novo[campo]
    dados["tokens"] = tokens
    dados["last_refresh"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    _gravar_login(dados)
    return dados


def _credenciais() -> tuple[str, str, dict]:
    """O access_token válido, o id da conta e o que o id_token conta (e-mail e plano)."""
    with _trava:
        dados = _ler_login()
        tokens = dados.get("tokens") or {}
        if not tokens.get("access_token"):
            raise SemLogin("O login do ChatGPT está sem token. Rode `codex login` neste computador.")
        if _venceu(tokens["access_token"]):
            dados = _renovar(dados)
            tokens = dados.get("tokens") or {}
        return tokens["access_token"], tokens.get("account_id") or "", _dentro_do_jwt(tokens.get("id_token") or "")


# ---------------------------------------------------------------- quanto da assinatura já foi usado


def _guardar_limites(cabecalhos) -> dict:
    """As janelas que o ChatGPT devolve em cada pedido (x-codex-*). Guardadas para o Radar mostrar depois."""
    def numero(nome):
        try:
            return float(cabecalhos.get(nome))
        except (TypeError, ValueError):
            return None

    janelas = {}
    for lado, rotulo in (("primary", "janela"), ("secondary", "semana")):
        usado = numero(f"x-codex-{lado}-used-percent")
        if usado is None:
            continue
        minutos = numero(f"x-codex-{lado}-window-minutes")
        volta = numero(f"x-codex-{lado}-reset-after-seconds")
        janelas[rotulo] = {"usado_pct": round(usado, 1), "minutos": int(minutos) if minutos else None,
                           "volta_em": time.time() + volta if volta else None}
    if not janelas:
        return {}
    limites = {"em": time.time(), "janelas": janelas}
    try:
        LIMITES.write_text(json.dumps(limites, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return limites


def _limites_guardados() -> dict:
    try:
        return json.loads(LIMITES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


PLANOS = {"plus": "ChatGPT Plus", "pro": "ChatGPT Pro", "team": "ChatGPT Team",
          "enterprise": "ChatGPT Enterprise", "free": "ChatGPT grátis"}


def estado() -> dict:
    """Para a tela: se a assinatura está ligada, de quem é, qual plano e quanto já foi usado das janelas."""
    try:
        _, conta, quem = _credenciais()
    except (SemLogin, RuntimeError) as erro:
        return {"conectada": False, "motivo": str(erro)[:300], "arquivo": str(LOGIN)}
    autor = quem.get("https://api.openai.com/auth") or {}
    plano = str(autor.get("chatgpt_plan_type") or "").strip()
    return {"conectada": True, "email": quem.get("email") or "", "conta": conta,
            "plano": PLANOS.get(plano, plano or "ChatGPT"), "arquivo": str(LOGIN), **_limites_guardados()}


# ---------------------------------------------------------------- gerar a imagem


def _versao_do_codex() -> str:
    """A versão do Codex deste computador, que vai no cabeçalho `version`. O ChatGPT recusa versões velhas demais."""
    numeros = lambda v: tuple(int(p) for p in re.findall(r"\d+", v))
    for arquivo, campo in ((PASTA_CODEX / "version.json", "latest_version"),
                           (PASTA_CODEX / "models_cache.json", "client_version")):
        try:
            versao = str(json.loads(arquivo.read_text(encoding="utf-8")).get(campo) or "")
        except (OSError, ValueError):
            continue
        if versao and numeros(versao) >= numeros(VERSAO_CODEX_MINIMA):
            return versao
    return VERSAO_CODEX_MINIMA


def _cabecalhos(token: str, conta: str) -> dict:
    pedido = str(uuid.uuid4())
    versao = _versao_do_codex()
    cabecalhos = {"Content-Type": "application/json", "Authorization": f"Bearer {token}",
                  "Accept": "text/event-stream", "OpenAI-Beta": "responses=experimental",
                  "originator": "codex_cli_rs", "version": versao,
                  "session_id": pedido, "x-client-request-id": pedido,
                  "User-Agent": f"codex_cli_rs/{versao} (fabrica-videos)"}
    if conta:
        cabecalhos["chatgpt-account-id"] = conta
    return cabecalhos


def _corpo(modelo: str, prompt: str, qualidade: str, tamanho: str, referencias) -> dict:
    conteudo = [{"type": "input_text", "text": prompt}]
    for dados, tipo in referencias or []:
        conteudo.append({"type": "input_image", "detail": "auto",
                         "image_url": f"data:{tipo};base64,{base64.b64encode(dados).decode()}"})
    return {"model": modelo, "stream": True, "store": False, "parallel_tool_calls": False,
            "instructions": "You generate images. Always answer the request by calling the image_generation tool.",
            "input": [{"type": "message", "role": "user", "content": conteudo}],
            "tools": [{"type": "image_generation", "model": MODELO_IMAGEM, "quality": qualidade, "size": tamanho}],
            "tool_choice": {"type": "image_generation"}}


def _imagem_do_fluxo(resposta) -> bytes:
    """Lê os eventos (SSE) até a imagem aparecer. Ela vem inteira em response.output_item.done, no item
    image_generation_call, campo result (base64)."""
    recusa = ""
    linhas: list[str] = []
    for linha in resposta.iter_lines():
        if linha.startswith("data:"):
            linhas.append(linha[5:].strip())
            continue
        if linha.strip():
            continue                             # event:, id:, comentário
        bruto = "".join(linhas)
        linhas = []
        if not bruto or bruto == "[DONE]":
            continue
        try:
            evento = json.loads(bruto)
        except ValueError:
            continue
        tipo = evento.get("type") or ""
        if tipo == "response.output_item.done":
            item = evento.get("item") or {}
            if item.get("type") == "image_generation_call" and item.get("result"):
                return base64.b64decode(item["result"], validate=True)
            if item.get("type") == "message":
                recusa = " ".join(p.get("text") or "" for p in (item.get("content") or []))[:300]
        elif tipo in ("response.failed", "error"):
            detalhe = (evento.get("response") or {}).get("error") or evento.get("error") or {}
            raise RuntimeError(f"O ChatGPT recusou o pedido: {str(detalhe.get('message') or detalhe)[:250]}")
    raise SemImagemNaResposta("O ChatGPT respondeu sem imagem" + (f": {recusa}" if recusa else ""))


def _quando_volta() -> str:
    janelas = _limites_guardados().get("janelas") or {}
    partes = []
    for chave, nome in (("janela", "a janela de 5 horas"), ("semana", "a semana")):
        volta = (janelas.get(chave) or {}).get("volta_em")
        if volta and volta > time.time():
            partes.append(f"{nome} volta {datetime.fromtimestamp(volta).strftime('%d/%m às %H:%M')}")
    return ("Pelo que o ChatGPT informou, " + " e ".join(partes) + ".") if partes else ""


_modelo_que_atende = None       # o primeiro modelo que a conta aceitou, para não tentar os recusados a cada imagem


def gerar(prompt: str, qualidade: str = "low", proporcao: str = "16:9", referencias=()) -> tuple[bytes, dict]:
    """A imagem pronta e o registro dela. Gasta o limite da assinatura, nunca crédito de API."""
    global _modelo_que_atende
    token, conta, _ = _credenciais()
    qualidade = qualidade if qualidade in QUALIDADES else "low"
    tamanho = TAMANHOS.get(proporcao, TAMANHOS["16:9"])
    tentar = [_modelo_que_atende] if _modelo_que_atende else list(MODELOS_CONVERSA)
    recusados = []
    renovado = False
    with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0), follow_redirects=True) as cliente:
        while tentar:
            modelo = tentar[0]
            corpo = _corpo(modelo, prompt, qualidade, tamanho, referencias)
            with cliente.stream("POST", RESPOSTAS, json=corpo, headers=_cabecalhos(token, conta)) as r:
                if r.status_code == 429:
                    r.read()
                    _guardar_limites(r.headers)
                    raise LimiteDaAssinatura("A assinatura do ChatGPT bateu no limite (janela de 5 horas ou da "
                                             "semana). " + _quando_volta())
                if r.status_code == 401 and not renovado:
                    # 2026-11-02: o ChatGPT deu "token_expired" para um access_token com 10 dias pela frente (o login
                    # tinha sido refeito no Radar) e os vídeos foram para a reserva sem crédito. O exp do JWT não
                    # basta: recusado, renova uma vez e pede de novo
                    r.read()
                    renovado = True
                    with _trava:
                        dados = _renovar(_ler_login())
                    token = dados["tokens"]["access_token"]
                    conta = dados["tokens"].get("account_id") or conta
                    continue
                if r.status_code in (401, 403):
                    r.read()
                    raise SemLogin("O ChatGPT recusou o login da assinatura. Rode `codex login` neste computador.")
                if r.status_code != 200:
                    r.read()
                    if r.status_code == 400 and "model_not_found" in r.text:
                        recusados.append(tentar.pop(0))
                        continue        # a conta não tem este modelo: o próximo da lista
                    raise RuntimeError(f"A assinatura do ChatGPT falhou ({r.status_code}): {r.text[:300]}")
                limites = _guardar_limites(r.headers)
                dados = _imagem_do_fluxo(r)
            _modelo_que_atende = modelo
            return dados, {"provedor": "assinatura", "modelo": MODELO_IMAGEM, "modelo_da_conversa": modelo,
                           "qualidade": qualidade, "tamanho": tamanho, "prompt": prompt,
                           "custo_usd": 0.0, "custo_medido": True, "limites": (limites or {}).get("janelas") or {}}
    raise RuntimeError("A assinatura do ChatGPT não aceitou nenhum dos modelos conhecidos "
                       f"({', '.join(recusados)}). A OpenAI deve ter trocado os nomes; atualize MODELOS_CONVERSA.")


def disponivel() -> bool:
    """Se dá para contar com a assinatura agora (o login existe e não venceu de vez)."""
    try:
        _credenciais()
        return True
    except (SemLogin, RuntimeError):
        return False
