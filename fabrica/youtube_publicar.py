"""Conectar a fábrica a uma conta do YouTube, publicar o vídeo final e agendar
a publicação pra mais tarde.

A conta é uma só, da fábrica inteira (não por projeto nem por pessoa) — o mesmo
espírito das chaves de API que já existem no .env, só que aqui o "login" é feito
pelo fluxo OAuth do Google em vez de colar uma chave.

O agendamento funciona assim: o vídeo sobe pro YouTube na hora, mas marcado como
"Privado". Um checador que roda junto com a fábrica (thread em segundo plano,
sem precisar de n8n ou cron externo) confere a cada alguns minutos se chegou a
hora marcada e, quando chega, troca pra "Público" sozinho.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from .config import RAIZ

ESCOPO = "https://www.googleapis.com/auth/youtube"
URL_AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_REVOGAR = "https://oauth2.googleapis.com/revoke"
URL_API = "https://www.googleapis.com/youtube/v3"
URL_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"

ARQUIVO_CONTA = RAIZ / "youtube_conta.json"

_trava = threading.Lock()


def _credenciais_app() -> tuple[str, str]:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise SystemExit(
            "Faltam GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET no arquivo .env, "
            "criados no Google Cloud como um 'ID do cliente OAuth' do tipo aplicativo da Web."
        )
    return client_id, client_secret


# -----------------------------------------------------------------------------
# Conta conectada (arquivo único, fábrica inteira)
# -----------------------------------------------------------------------------

def conectada() -> bool:
    return ARQUIVO_CONTA.exists()


def conta() -> Optional[dict]:
    if not ARQUIVO_CONTA.exists():
        return None
    return json.loads(ARQUIVO_CONTA.read_text(encoding="utf-8"))


def _salvar_conta(dados: dict) -> None:
    with _trava:
        ARQUIVO_CONTA.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def desconectar() -> None:
    dados = conta()
    if dados and dados.get("refresh_token"):
        try:
            httpx.post(URL_REVOGAR, params={"token": dados["refresh_token"]}, timeout=15)
        except httpx.HTTPError:
            pass  # revogar é cortesia; se o Google não responder, apagamos o arquivo mesmo assim
    ARQUIVO_CONTA.unlink(missing_ok=True)


def url_autorizacao(redirect_uri: str) -> str:
    client_id, _ = _credenciais_app()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ESCOPO,
        "access_type": "offline",
        "prompt": "consent",  # sempre devolve refresh_token, mesmo numa reconexão
    }
    return f"{URL_AUTORIZAR}?{httpx.QueryParams(params)}"


def concluir_autorizacao(code: str, redirect_uri: str) -> dict:
    """Troca o código de autorização pelos tokens e guarda a conta conectada."""
    client_id, client_secret = _credenciais_app()
    r = httpx.post(URL_TOKEN, data={
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }, timeout=20)
    if r.status_code != 200:
        raise SystemExit(f"O Google recusou a autorização: {r.text[:300]}")
    tokens = r.json()

    canal = _pedir_com_token(tokens["access_token"], "channels", part="snippet", mine="true")
    itens = canal.get("items", [])
    if not itens:
        raise SystemExit("Login feito, mas essa conta do Google não tem nenhum canal do YouTube.")
    info = itens[0]

    dados = {
        "refresh_token": tokens.get("refresh_token"),
        "access_token": tokens["access_token"],
        "expira_em": (datetime.now(timezone.utc).timestamp() + tokens.get("expires_in", 3600)),
        "canal_id": info["id"],
        "canal_nome": info["snippet"]["title"],
        "canal_avatar": (info["snippet"].get("thumbnails", {}).get("default") or {}).get("url", ""),
        "conectado_em": datetime.now().isoformat(timespec="seconds"),
    }
    # numa reconexão o Google só manda refresh_token de novo às vezes; sem isso,
    # perder o antigo travaria o agendamento (não dá pra renovar o access_token sozinho)
    if not dados["refresh_token"]:
        anterior = conta()
        if anterior and anterior.get("refresh_token"):
            dados["refresh_token"] = anterior["refresh_token"]
        else:
            raise SystemExit(
                "O Google não devolveu a permissão de renovação (refresh_token). "
                "Revogue o acesso em myaccount.google.com/permissions e conecte de novo."
            )
    _salvar_conta(dados)
    return dados


def _token_valido() -> str:
    """Devolve um access_token que ainda vale, renovando com o refresh_token se preciso."""
    dados = conta()
    if not dados:
        raise SystemExit("Conecte uma conta do YouTube antes de publicar (aba Publicar no YouTube).")
    if dados["expira_em"] - datetime.now(timezone.utc).timestamp() > 60:
        return dados["access_token"]

    client_id, client_secret = _credenciais_app()
    r = httpx.post(URL_TOKEN, data={
        "refresh_token": dados["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }, timeout=20)
    if r.status_code != 200:
        raise SystemExit(
            "O Google recusou renovar o acesso à conta do YouTube. Pode ser que o acesso tenha "
            "sido revogado — reconecte a conta na aba Publicar no YouTube."
        )
    novo = r.json()
    dados["access_token"] = novo["access_token"]
    dados["expira_em"] = datetime.now(timezone.utc).timestamp() + novo.get("expires_in", 3600)
    _salvar_conta(dados)
    return dados["access_token"]


def _pedir_com_token(access_token: str, caminho: str, **params) -> dict:
    r = httpx.get(f"{URL_API}/{caminho}", params=params,
                  headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
    if r.status_code >= 400:
        raise SystemExit(f"O YouTube recusou o pedido ({r.status_code}): {r.text[:300]}")
    return r.json()


# -----------------------------------------------------------------------------
# Envio do vídeo (upload resumable, em pedaços, com progresso)
# -----------------------------------------------------------------------------

TAMANHO_PEDACO = 8 * 1024 * 1024  # 8 MB por pedaço, o mínimo exigido pelo Google é 256 KB


def publicar(arquivo: Path, titulo: str, descricao: str, tags: list, privacidade: str,
             categoria: str = "22", on_progresso=None) -> dict:
    """Sobe o vídeo pro YouTube em pedaços, chamando on_progresso(pct) a cada um.
    Devolve o recurso do vídeo criado (com o id) quando termina."""
    access_token = _token_valido()
    metadados = {
        "snippet": {
            "title": titulo[:100],
            "description": descricao[:5000],
            "tags": tags[:500],
            "categoryId": categoria,
        },
        "status": {"privacyStatus": privacidade, "selfDeclaredMadeForKids": False},
    }
    tamanho_total = arquivo.stat().st_size

    r = httpx.post(
        URL_UPLOAD,
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(tamanho_total),
            "X-Upload-Content-Type": "video/mp4",
        },
        json=metadados, timeout=30,
    )
    if r.status_code != 200:
        raise SystemExit(f"O YouTube recusou iniciar o envio: {r.text[:300]}")
    url_envio = r.headers["Location"]

    with open(arquivo, "rb") as f, httpx.Client(timeout=120) as cliente:
        enviado = 0
        while enviado < tamanho_total:
            pedaco = f.read(TAMANHO_PEDACO)
            inicio, fim = enviado, enviado + len(pedaco) - 1
            resp = cliente.put(
                url_envio,
                content=pedaco,
                headers={
                    "Content-Length": str(len(pedaco)),
                    "Content-Range": f"bytes {inicio}-{fim}/{tamanho_total}",
                },
            )
            if resp.status_code in (200, 201):
                if on_progresso:
                    on_progresso(100)
                return resp.json()
            if resp.status_code != 308:
                raise SystemExit(f"O envio pro YouTube falhou no meio do caminho ({resp.status_code}): {resp.text[:300]}")
            enviado = fim + 1
            if on_progresso:
                on_progresso(round(enviado / tamanho_total * 100, 1))

    raise SystemExit("O envio terminou sem o YouTube confirmar o vídeo.")


def trocar_privacidade(video_id: str, privacidade: str) -> None:
    access_token = _token_valido()
    r = httpx.put(
        f"{URL_API}/videos",
        params={"part": "status"},
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"id": video_id, "status": {"privacyStatus": privacidade}},
        timeout=20,
    )
    if r.status_code >= 400:
        raise SystemExit(f"O YouTube recusou trocar a visibilidade do vídeo: {r.text[:300]}")


# -----------------------------------------------------------------------------
# Checador de agendamentos: roda em segundo plano junto com a fábrica
# -----------------------------------------------------------------------------

def _agendamentos_pendentes():
    """Vídeos de todo projeto com status 'agendado' e a hora já chegou."""
    from .projeto import PROJETOS  # import tardio: projeto.py também usa config.py, evita ciclo

    if not PROJETOS.exists():
        return
    agora = datetime.now(timezone.utc)
    for pasta in PROJETOS.iterdir():
        arquivo = pasta / "youtube.json"
        if not arquivo.exists():
            continue
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except Exception:
            continue
        if dados.get("status") != "agendado":
            continue
        agendado_para = datetime.fromisoformat(dados["agendado_para"])
        if agendado_para.tzinfo is None:
            agendado_para = agendado_para.replace(tzinfo=timezone.utc)
        if agendado_para <= agora:
            yield arquivo, dados


def executar_agendamentos_pendentes(log=print) -> None:
    for arquivo, dados in list(_agendamentos_pendentes()):
        try:
            trocar_privacidade(dados["video_id"], dados["privacidade_alvo"])
            dados["status"] = "publicado"
            dados["publicado_em"] = datetime.now().isoformat(timespec="seconds")
            arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"  agendamento do YouTube publicado: {dados.get('titulo', dados['video_id'])}")
        except SystemExit as e:
            dados["status"] = "falha"
            dados["erro"] = str(e)
            arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"  falha ao publicar agendamento do YouTube: {e}")


def iniciar_checador(intervalo_segundos: int = 300) -> None:
    """Chamada uma vez, na subida da fábrica. Roda pro resto da vida do processo,
    numa thread separada, sem travar o servidor."""
    def loop():
        while True:
            try:
                executar_agendamentos_pendentes()
            except Exception as e:
                print(f"[agendador youtube] erro inesperado: {e}")
            time.sleep(intervalo_segundos)

    threading.Thread(target=loop, daemon=True, name="checador-youtube").start()
