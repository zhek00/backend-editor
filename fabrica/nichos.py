"""Busca de nichos virais no YouTube: vídeos recentes com visualização muito acima
do tamanho do canal, o sinal mais forte de nicho quente. Usa só a API pública e
oficial do YouTube (visualizações, inscritos, quantidade de vídeos) — não o vidIQ,
que não abre esses dados pra fora do próprio produto.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

BASE = "https://www.googleapis.com/youtube/v3"

# Estados Unidos e Europa primeiro nos resultados — canais nesses países costumam
# valer mais por visualização (RPM mais alto), o que interessa mais pra achar nicho
# lucrativo. O canal precisa ter preenchido o país no YouTube pra entrar aqui; quem
# não preencheu fica no segundo grupo, não é descartado.
PAISES_PRIORIDADE = {
    "US", "CA",  # América do Norte
    "GB", "IE", "DE", "FR", "ES", "PT", "IT", "NL", "BE", "AT", "CH",
    "SE", "NO", "DK", "FI", "PL", "CZ", "GR", "RO", "HU", "SK",
}


def _chave() -> str:
    chave = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not chave:
        raise SystemExit("Falta a chave YOUTUBE_API_KEY no arquivo .env.")
    return chave


def _pedir(caminho: str, **params) -> dict:
    params = {k: v for k, v in params.items() if v not in (None, "")}
    params["key"] = _chave()
    r = httpx.get(f"{BASE}/{caminho}", params=params, timeout=20)
    if r.status_code in (401, 403):
        raise SystemExit(
            'O YouTube recusou a chave (YOUTUBE_API_KEY). Ela precisa ser uma "Chave de API" '
            'criada em APIs e Serviços > Credenciais no Google Cloud (começa com AIzaSy...), com a '
            'YouTube Data API v3 ativada pro mesmo projeto. Confira também se a cota diária não acabou.'
        )
    if r.status_code == 400:
        raise SystemExit(f"O YouTube recusou o pedido: {r.text[:300]}")
    if r.status_code >= 400:
        raise SystemExit(f"O YouTube respondeu com erro {r.status_code}: {r.text[:300]}")
    return r.json()


def _melhor_thumb(thumbs: dict) -> str:
    for tam in ("maxres", "high", "medium", "default"):
        if tam in thumbs:
            return thumbs[tam]["url"]
    return ""


def _buscar_ids(query: str, desde: str, duracao: str, quantidade: int) -> list:
    """IDs de vídeo pra uma faixa de duração do YouTube (medium = 4 a 20 min,
    long = mais de 20 min). Shorts entram só em 'short', que a fábrica nunca pede."""
    ids: list = []
    pagina = None
    while len(ids) < quantidade:
        dados = _pedir(
            "search",
            part="id", type="video", q=query, order="viewCount",
            publishedAfter=desde, videoDuration=duracao, regionCode="US",
            maxResults=min(50, quantidade - len(ids)),
            pageToken=pagina,
        )
        itens = dados.get("items", [])
        ids += [item["id"]["videoId"] for item in itens if item.get("id", {}).get("videoId")]
        pagina = dados.get("nextPageToken")
        if not pagina or not itens:
            break
    return ids


def buscar(query: str, dias: int = 30, maximo: int = 40) -> list:
    """Vídeos publicados nos últimos `dias` dias sobre o termo, ordenados pela
    visualização em relação ao tamanho do canal (visualizações ÷ inscritos) —
    quanto maior essa taxa, mais o vídeo performou acima do normal do canal.

    Nunca inclui Shorts: só vídeos de 4 minutos pra cima, no formato narrado que a
    fábrica produz, não o vertical rápido do Shorts."""
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%SZ")

    ids_video = list(dict.fromkeys(
        _buscar_ids(query, desde, "medium", maximo) + _buscar_ids(query, desde, "long", maximo)
    ))

    if not ids_video:
        return []

    videos = []
    for i in range(0, len(ids_video), 50):
        lote = ids_video[i:i + 50]
        dados = _pedir("videos", part="snippet,statistics", id=",".join(lote))
        videos += dados.get("items", [])

    ids_canal = list({v["snippet"]["channelId"] for v in videos})
    canais = {}
    for i in range(0, len(ids_canal), 50):
        lote = ids_canal[i:i + 50]
        dados = _pedir("channels", part="snippet,statistics", id=",".join(lote))
        for c in dados.get("items", []):
            canais[c["id"]] = c

    resultado = []
    agora = datetime.now(timezone.utc)
    for v in videos:
        canal = canais.get(v["snippet"]["channelId"])
        if not canal or canal["statistics"].get("hiddenSubscriberCount"):
            continue  # canal escondeu o número de inscritos, não dá pra calcular a taxa
        inscritos = int(canal["statistics"].get("subscriberCount", 0) or 0)
        visualizacoes = int(v["statistics"].get("viewCount", 0) or 0)
        if inscritos <= 0 or visualizacoes < 1000:
            continue  # vídeo pequeno demais pra dizer alguma coisa
        publicado = datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
        dias_no_ar = max((agora - publicado).total_seconds() / 86400, 0.5)
        pais = (canal["snippet"].get("country") or "").upper()
        resultado.append({
            "video_id": v["id"],
            "titulo": v["snippet"]["title"],
            "miniatura": _melhor_thumb(v["snippet"]["thumbnails"]),
            "publicado": v["snippet"]["publishedAt"],
            "dias_no_ar": round(dias_no_ar, 1),
            "visualizacoes": visualizacoes,
            "visualizacoes_por_dia": round(visualizacoes / dias_no_ar),
            "canal_id": canal["id"],
            "canal_nome": canal["snippet"]["title"],
            "canal_avatar": _melhor_thumb(canal["snippet"]["thumbnails"]),
            "canal_inscritos": inscritos,
            "canal_total_videos": int(canal["statistics"].get("videoCount", 0) or 0),
            "canal_pais": pais,
            "taxa": round(visualizacoes / inscritos, 2),
        })

    # EUA e Europa primeiro (por serem o mercado que mais interessa), e dentro de
    # cada grupo, do maior pro menor taxa de visualização
    resultado.sort(key=lambda r: (r["canal_pais"] not in PAISES_PRIORIDADE, -r["taxa"]))
    return resultado


def videos_do_canal(canal_id: str, pagina: Optional[str] = None, quantidade: int = 30) -> dict:
    """Miniatura, título e data dos vídeos mais recentes de um canal, paginado —
    a lista completa de um canal grande pode ter milhares de vídeos, então vem
    aos poucos, sob pedido, em vez de trazer tudo de uma vez pra cada resultado
    da busca (isso estouraria a cota da chave rapidinho)."""
    canal = _pedir("channels", part="contentDetails", id=canal_id)
    itens = canal.get("items", [])
    if not itens:
        raise SystemExit("Canal não encontrado.")
    uploads = itens[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    dados = _pedir("playlistItems", part="snippet", playlistId=uploads,
                    maxResults=quantidade, pageToken=pagina)
    videos = [
        {
            "video_id": item["snippet"]["resourceId"]["videoId"],
            "titulo": item["snippet"]["title"],
            "miniatura": _melhor_thumb(item["snippet"]["thumbnails"]),
            "publicado": item["snippet"]["publishedAt"],
        }
        for item in dados.get("items", [])
        if item["snippet"].get("resourceId", {}).get("videoId")
    ]
    return {"videos": videos, "proxima_pagina": dados.get("nextPageToken")}
