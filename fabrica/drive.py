"""Entrega no Google Drive: o vídeo pronto sobe sozinho para a pasta "Fábrica/NOME DO CANAL".

Opcional: sem conta conectada o vídeo fica só no computador, como sempre. Usa o mesmo cliente do Google do YouTube
(GOOGLE_CLIENT_ID) e a mesma URL de retorno, com state=drive, então não há URL nova para cadastrar. A Drive API precisa
estar ativada nesse projeto do Google Cloud.

O escopo é drive.file: a fábrica só enxerga o que ela mesma criou, nunca o resto do Drive da pessoa.
"""
import json
import threading
import time
from pathlib import Path

import httpx

from .config import RAIZ
from .util import gravar_atomico

ESCOPO = "https://www.googleapis.com/auth/drive.file"
ESTADO = "drive"
URL_AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_API = "https://www.googleapis.com/drive/v3"
URL_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
ARQUIVO_CONTA = RAIZ / "drive_conta.json"
PASTA_RAIZ = "Fábrica"
PEDACO = 32 * 2**20  # múltiplo de 256 KB, como o Drive exige
PASTA_MIME = "application/vnd.google-apps.folder"

_trava = threading.Lock()


def _credenciais_app() -> tuple:
    from .youtube_publicar import _credenciais_app as credenciais

    return credenciais()


def conta() -> dict | None:
    try:
        return json.loads(ARQUIVO_CONTA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def conectada() -> bool:
    return bool((conta() or {}).get("refresh_token"))


def desconectar() -> None:
    ARQUIVO_CONTA.unlink(missing_ok=True)


def _salvar(dados: dict) -> None:
    gravar_atomico(ARQUIVO_CONTA, json.dumps(dados, ensure_ascii=False, indent=2))


def url_autorizacao(redirect_uri: str) -> str:
    client_id, _ = _credenciais_app()
    params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": ESCOPO,
              "access_type": "offline", "prompt": "consent", "state": ESTADO}
    return f"{URL_AUTORIZAR}?{httpx.QueryParams(params)}"


def concluir_autorizacao(code: str, redirect_uri: str, http=httpx) -> dict:
    client_id, client_secret = _credenciais_app()
    r = http.post(URL_TOKEN, data={"code": code, "client_id": client_id, "client_secret": client_secret,
                                   "redirect_uri": redirect_uri, "grant_type": "authorization_code"}, timeout=20)
    if r.status_code != 200:
        raise SystemExit(f"O Google recusou a autorização: {r.text[:300]}")
    tokens = r.json()
    anterior = conta() or {}
    dados = {"refresh_token": tokens.get("refresh_token") or anterior.get("refresh_token"),
             "access_token": tokens["access_token"], "expira_em": time.time() + tokens.get("expires_in", 3600)}
    _salvar(dados)
    return dados


def _token(http=httpx) -> str:
    with _trava:
        dados = conta() or {}
        if dados.get("access_token") and dados.get("expira_em", 0) - time.time() > 60:
            return dados["access_token"]
        client_id, client_secret = _credenciais_app()
        r = http.post(URL_TOKEN, data={"refresh_token": dados.get("refresh_token"), "client_id": client_id,
                                       "client_secret": client_secret, "grant_type": "refresh_token"}, timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"O Google recusou renovar o acesso ao Drive: {r.text[:200]}")
        novo = r.json()
        dados.update(access_token=novo["access_token"], expira_em=time.time() + novo.get("expires_in", 3600))
        _salvar(dados)
        return dados["access_token"]


def _pasta(http, token: str, nome: str, pai: str | None = None) -> str:
    """A pasta com esse nome, criada se ainda não existir. Com drive.file a busca só vê as que a fábrica criou."""
    seguro = nome.replace("\\", "\\\\").replace("'", "\\'")
    busca = f"name='{seguro}' and mimeType='{PASTA_MIME}' and trashed=false"
    if pai:
        busca += f" and '{pai}' in parents"
    cabecalho = {"Authorization": f"Bearer {token}"}
    r = http.get(f"{URL_API}/files", params={"q": busca, "fields": "files(id)"}, headers=cabecalho, timeout=30)
    r.raise_for_status()
    achadas = r.json().get("files") or []
    if achadas:
        return achadas[0]["id"]
    corpo = {"name": nome, "mimeType": PASTA_MIME, **({"parents": [pai]} if pai else {})}
    r = http.post(f"{URL_API}/files", json=corpo, params={"fields": "id"}, headers=cabecalho, timeout=30)
    r.raise_for_status()
    return r.json()["id"]


def _subir(http, token: str, arquivo: Path, nome: str, pasta: str) -> str:
    """Envio em pedaços: um vídeo de 2 GB não cabe numa requisição, e a rede pode cair no meio."""
    tamanho = arquivo.stat().st_size
    r = http.post(URL_UPLOAD, params={"uploadType": "resumable", "fields": "id"}, json={"name": nome, "parents": [pasta]},
                  headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
                           "X-Upload-Content-Length": str(tamanho)}, timeout=30)
    r.raise_for_status()
    sessao = r.headers["location"]
    with open(arquivo, "rb") as f:
        enviado = 0
        while True:
            bloco = f.read(PEDACO)
            fim = enviado + len(bloco) - 1
            r = http.put(sessao, content=bloco, timeout=600,
                         headers={"Content-Range": f"bytes {enviado}-{fim}/{tamanho}", "Content-Length": str(len(bloco))})
            if r.status_code in (200, 201):
                return r.json()["id"]
            if r.status_code != 308:
                raise RuntimeError(f"O Drive parou o envio ({r.status_code}): {r.text[:200]}")
            enviado = fim + 1


def enviar(projeto, log=print, http=None) -> str | None:
    """Sobe o final.mp4. Nunca para a entrega: sem conta ou com erro, o vídeo continua no computador."""
    if not conectada():
        log("  drive: nenhuma conta conectada; o vídeo fica só no computador")
        return None
    final = projeto.pasta / "final.mp4"
    if not final.is_file():
        return None
    cliente = http or httpx.Client(timeout=60)
    try:
        token = _token(cliente)
        raiz = _pasta(cliente, token, PASTA_RAIZ)
        canal = str(projeto.perfil.get("nome") or "Sem canal")
        pasta = _pasta(cliente, token, canal, raiz)
        titulo = str(projeto.dados.get("titulo_entrega") or projeto.nome)
        arquivo_id = _subir(cliente, token, final, f"{titulo}.mp4", pasta)
    except (httpx.HTTPError, RuntimeError, OSError, KeyError, ValueError) as erro:
        log(f"  drive: o envio não deu certo, o vídeo fica no computador ({str(erro)[:160]})")
        return None
    projeto.salvar_json("drive.json", {"arquivo": arquivo_id, "pasta": pasta})
    log(f"  drive: vídeo enviado para {PASTA_RAIZ}/{canal}")
    return arquivo_id
