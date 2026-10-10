"""Conectar a fábrica a uma conta do YouTube, publicar o vídeo final e agendar
a publicação pra mais tarde.

A conta é uma só, da fábrica inteira (não por projeto nem por pessoa) — o mesmo
espírito das chaves de API que já existem no .env, só que aqui o "login" é feito
pelo fluxo OAuth do Google em vez de colar uma chave.

O agendamento (desde 2026-10-09, da análise do concorrente) é do próprio YouTube: o vídeo sobe como "Privado" com
a data de publicação (`status.publishAt`), e o YouTube publica sozinho na hora, mesmo com o computador desligado.
Antes um checador em segundo plano trocava para "Público" na hora marcada e a fábrica tinha de estar ligada; ele
continua só para os agendamentos feitos daquele jeito (`pelo_youtube` ausente no youtube.json).

`publicar_projeto` sobe o pacote inteiro do projeto: o vídeo com o kit de publicação (`publicacao.json`: título,
descrição com capítulos, tags, conteúdo sintético), a thumbnail escolhida (`thumbnails.set`), a legenda
(`captions.insert`, que pede o escopo youtube.force-ssl: conta conectada antes disso precisa reconectar) e, se
pedido, os shorts (`shorts/shorts.json`), agendados de `youtube.shorts_intervalo_horas` em
`youtube.shorts_intervalo_horas` depois do vídeo. `simular=True` só devolve o plano, sem enviar nada.

**Regra do Google**: vídeo enviado pela API por um projeto do Google Cloud que não passou pela auditoria da API do
YouTube fica travado como privado. Depois do envio público, a fábrica confere a visibilidade e avisa.
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

from .config import RAIZ

# youtube.force-ssl: a legenda (captions.insert) pede este escopo; conta conectada só com o primeiro precisa reconectar
ESCOPO = "https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/youtube.force-ssl"
URL_AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_REVOGAR = "https://oauth2.googleapis.com/revoke"
URL_API = "https://www.googleapis.com/youtube/v3"
URL_UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
URL_THUMBNAIL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
URL_LEGENDA = "https://www.googleapis.com/upload/youtube/v3/captions"

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
             categoria: str = "22", on_progresso=None, publicar_em: Optional[datetime] = None,
             sintetico: bool = False, idioma: str = "pt-BR") -> dict:
    """Sobe o vídeo pro YouTube em pedaços, chamando on_progresso(pct) a cada um.
    Devolve o recurso do vídeo criado (com o id) quando termina.

    publicar_em: o YouTube publica sozinho nessa hora (o vídeo sobe privado, com publishAt). sintetico: declara
    conteúdo alterado ou sintético realista (imagem de IA), como pede a política do YouTube."""
    access_token = _token_valido()
    metadados = {
        "snippet": {
            "title": titulo[:100],
            "description": descricao[:5000],
            "tags": tags[:500],
            "categoryId": categoria,
            "defaultLanguage": idioma,
            "defaultAudioLanguage": idioma,
        },
        "status": {"privacyStatus": privacidade, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": bool(sintetico)},
    }
    if publicar_em is not None:
        metadados["status"]["privacyStatus"] = "private"
        metadados["status"]["publishAt"] = publicar_em.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
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


def enviar_thumbnail(video_id: str, arquivo: Path) -> None:
    """A capa do vídeo (thumbnails.set). O canal precisa estar verificado por telefone."""
    r = httpx.post(URL_THUMBNAIL, params={"videoId": video_id, "uploadType": "media"},
                   headers={"Authorization": f"Bearer {_token_valido()}", "Content-Type": "image/jpeg"},
                   content=Path(arquivo).read_bytes(), timeout=60)
    if r.status_code >= 400:
        dica = " (o canal precisa estar verificado por telefone em youtube.com/verify)" if r.status_code == 403 else ""
        raise SystemExit(f"o YouTube recusou a thumbnail ({r.status_code}){dica}: {r.text[:200]}")


def enviar_legenda(video_id: str, arquivo: Path, idioma: str = "pt-BR", nome: str = "Português") -> None:
    """A legenda do vídeo (captions.insert), num pedido multipart com os dados e o .srt."""
    fronteira = "fabrica-legenda-" + str(int(time.time()))
    dados = json.dumps({"snippet": {"videoId": video_id, "language": idioma, "name": nome, "isDraft": False}})
    corpo = (f"--{fronteira}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{dados}\r\n"
             f"--{fronteira}\r\nContent-Type: application/octet-stream\r\n\r\n").encode("utf-8")
    corpo += Path(arquivo).read_bytes() + f"\r\n--{fronteira}--\r\n".encode("utf-8")
    r = httpx.post(URL_LEGENDA, params={"part": "snippet", "uploadType": "multipart"},
                   headers={"Authorization": f"Bearer {_token_valido()}",
                            "Content-Type": f"multipart/related; boundary={fronteira}"},
                   content=corpo, timeout=120)
    if r.status_code >= 400:
        dica = " (reconecte a conta do YouTube para dar a permissão de legendas)" if r.status_code in (401, 403) else ""
        raise SystemExit(f"o YouTube recusou a legenda ({r.status_code}){dica}: {r.text[:200]}")


def visibilidade(video_id: str) -> str:
    dados = _pedir_com_token(_token_valido(), "videos", part="status", id=video_id)
    itens = dados.get("items") or []
    return (itens[0].get("status") or {}).get("privacyStatus", "") if itens else ""


def _config() -> dict:
    from .config import config_geral
    return {"fuso_horas": -3, "categoria": "22", "shorts_intervalo_horas": 24, "idioma": "pt-BR",
            **(config_geral().get("youtube") or {})}


def quando_utc(texto) -> datetime:
    """'2026-10-12 18:00' na hora do canal (youtube.fuso_horas, -3 para Brasília) ou ISO com fuso, em UTC.
    O Brasil não tem horário de verão desde 2019, e o Windows não traz a base de fusos: o deslocamento é fixo."""
    t = datetime.fromisoformat(str(texto).strip().replace(" ", "T").replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone(timedelta(hours=float(_config()["fuso_horas"]))))
    return t.astimezone(timezone.utc)


def plano(projeto, quando=None, privacidade="public", com_shorts=False, com_thumbnail=True, com_legenda=True,
          titulo=None, descricao=None, tags=None) -> dict:
    """O que vai subir, com os horários, sem enviar nada."""
    from . import publicacao

    if not projeto.existe("final.mp4"):
        raise SystemExit("Esse projeto ainda não tem o vídeo final renderizado.")
    if not projeto.existe("publicacao.json"):
        publicacao.gerar(projeto)
    kit = projeto.ler_json("publicacao.json")
    cfg = _config()
    momento = quando_utc(quando) if quando else None
    if momento is not None and momento <= datetime.now(timezone.utc) + timedelta(minutes=10):
        raise SystemExit("A data de publicação precisa estar pelo menos 10 minutos no futuro.")
    tags_finais = list(tags if tags is not None else kit.get("tags") or [])
    video = {"arquivo": "final.mp4", "titulo": (titulo or kit.get("titulo") or projeto.nome)[:100],
             "descricao": descricao if descricao is not None else kit.get("descricao", ""), "tags": tags_finais,
             "privacidade": "private" if momento else privacidade,
             "publicar_em": momento.isoformat() if momento else None, "sintetico": bool(kit.get("sintetico")),
             "thumbnail": "thumbnail.jpg" if com_thumbnail and projeto.existe("thumbnail.jpg") else None,
             "legenda": kit.get("legenda") if com_legenda and kit.get("legenda") and projeto.existe(kit["legenda"]) else None,
             "comentario_fixado": kit.get("comentario_fixado", "")}
    curtos = []
    if com_shorts and projeto.existe("shorts/shorts.json"):
        for k, sh in enumerate(projeto.ler_json("shorts/shorts.json").get("shorts") or [], 1):
            if not projeto.existe(sh["arquivo"]):
                continue
            hora = momento + timedelta(hours=float(cfg["shorts_intervalo_horas"]) * k) if momento else None
            curtos.append({"id": sh["id"], "arquivo": sh["arquivo"], "titulo": sh["titulo_post"][:100],
                           "descricao": sh["descricao"], "tags": tags_finais[:10],
                           "privacidade": "private" if hora else privacidade,
                           "publicar_em": hora.isoformat() if hora else None})
    return {"video": video, "shorts": curtos, "categoria": str(cfg["categoria"]), "idioma": cfg["idioma"]}


def publicar_projeto(projeto, quando=None, privacidade="public", com_shorts=False, com_thumbnail=True,
                     com_legenda=True, titulo=None, descricao=None, tags=None, simular=False, on_progresso=None,
                     log=print) -> dict:
    """Sobe o vídeo do projeto com a capa e a legenda e, se pedido, os shorts. Grava youtube.json. Com simular,
    devolve só o plano. O que falhar depois do vídeo (capa, legenda, um short) vira aviso, não desfaz o envio."""
    pl = plano(projeto, quando, privacidade, com_shorts, com_thumbnail, com_legenda, titulo, descricao, tags)
    if simular:
        return {"simulacao": True, **pl}
    v, avisos = pl["video"], []
    momento = datetime.fromisoformat(v["publicar_em"]) if v["publicar_em"] else None
    total = 1 + len(pl["shorts"])

    def progresso_de(k):
        return (lambda pct: on_progresso(round((k + pct / 100) / total * 100, 1))) if on_progresso else None

    log(f"  enviando o vídeo: {v['titulo']}")
    recurso = publicar(projeto.pasta / v["arquivo"], v["titulo"], v["descricao"], v["tags"], v["privacidade"],
                       pl["categoria"], progresso_de(0), momento, v["sintetico"], pl["idioma"])
    video_id = recurso["id"]
    for etapa, funcao, arquivo in (("thumbnail", enviar_thumbnail, v["thumbnail"]),
                                   ("legenda", enviar_legenda, v["legenda"])):
        if not arquivo:
            continue
        try:
            funcao(video_id, projeto.pasta / arquivo)
            log(f"  {etapa} enviada")
        except (SystemExit, httpx.HTTPError) as erro:
            avisos.append(str(erro))
            log(f"  {etapa} não foi: {erro}")
    if not momento and privacidade == "public":
        try:
            if visibilidade(video_id) == "private":
                avisos.append("o YouTube deixou o vídeo privado: o projeto do Google Cloud ainda não passou pela "
                              "auditoria da API do YouTube (formulário 'YouTube API Services Audit'). Até lá, "
                              "publique pelo YouTube Studio")
        except SystemExit:
            pass
    dados = {"video_id": video_id, "url": f"https://youtu.be/{video_id}", "titulo": v["titulo"],
             "descricao": v["descricao"], "tags": v["tags"], "privacidade_alvo": privacidade,
             "agendado_para": v["publicar_em"], "pelo_youtube": True,
             "status": "agendado" if momento else "publicado", "enviado_em": datetime.now().isoformat(timespec="seconds"),
             "comentario_fixado": v["comentario_fixado"], "shorts": [], "avisos": avisos}
    projeto.salvar_json("youtube.json", dados)
    for k, sh in enumerate(pl["shorts"], 1):
        try:
            log(f"  enviando o short {sh['id']}: {sh['titulo']}")
            hora = datetime.fromisoformat(sh["publicar_em"]) if sh["publicar_em"] else None
            r = publicar(projeto.pasta / sh["arquivo"], sh["titulo"], sh["descricao"], sh["tags"], sh["privacidade"],
                         pl["categoria"], progresso_de(k), hora, v["sintetico"], pl["idioma"])
            dados["shorts"].append({"id": sh["id"], "video_id": r["id"], "url": f"https://youtube.com/shorts/{r['id']}",
                                    "titulo": sh["titulo"], "agendado_para": sh["publicar_em"]})
        except (SystemExit, httpx.HTTPError) as erro:
            avisos.append(f"short {sh['id']}: {erro}")
            log(f"  o short {sh['id']} não foi: {erro}")
        projeto.salvar_json("youtube.json", dados)
    if on_progresso:
        on_progresso(100)
    return dados


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
        if dados.get("status") != "agendado" or dados.get("pelo_youtube"):
            continue  # agendado com publishAt: quem publica é o próprio YouTube
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
