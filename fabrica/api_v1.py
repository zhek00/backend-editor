"""A API REST /v1 da produção em massa (PLANO-VPS.md): o cliente manda o roteiro, acompanha e baixa o vídeo.

Autenticação: a chave do cliente (fabrica cliente-criar) no cabeçalho `Authorization: Bearer fab_...`. O banco guarda
só o hash dela. Cada cliente vê só os próprios vídeos e respeita o limite por dia dele (429 ao passar).

    POST   /v1/videos                {"roteiro": "...", "titulo": "..."}   -> 202 {id, estado, posicao_na_fila}
    GET    /v1/videos                os pedidos do cliente
    GET    /v1/videos/{id}           estado, etapa, andamento, mensagem, eventos e, pronto, o link para baixar
    DELETE /v1/videos/{id}           cancela (na fila ou produzindo)
    GET    /v1/videos/{id}/arquivo   o vídeo, quando o armazenamento é local (sem R2)
    GET    /v1/saude                 a fila por estado (sem chave: para o monitoramento)

O link do R2 é feito na hora do pedido, válido até o vídeo expirar (3 dias depois de pronto)."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import armazenamento, fila

roteador = APIRouter(prefix="/v1", tags=["produção em massa"])

ROTEIRO_MAXIMO = 200_000  # caracteres: ~3 horas de narração


class PedidoDeVideo(BaseModel):
    roteiro: str = Field(..., min_length=20, max_length=ROTEIRO_MAXIMO)
    titulo: Optional[str] = Field(None, max_length=200)


def _cliente(authorization: Optional[str]):
    chave = (authorization or "").removeprefix("Bearer").strip()
    cliente = fila.cliente_da_chave(chave)
    if cliente is None:
        raise HTTPException(status_code=401, detail="Chave inválida ou ausente (Authorization: Bearer fab_...).")
    return cliente


def _do_cliente(video_id: str, cliente) -> dict:
    v = fila.video(video_id)
    if v is None or v.get("cliente_id") != cliente["id"]:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado.")
    return v


def _segundos_ate(expira_em: str) -> int:
    fim = datetime.strptime(expira_em, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return int((fim - datetime.now(timezone.utc)).total_seconds())


def _publico(v, com_eventos=False) -> dict:
    saida = {k: v.get(k) for k in ("id", "titulo", "estado", "etapa", "progresso", "mensagem", "criado_em",
                                   "iniciado_em", "concluido_em", "expira_em", "duracao_s")}
    if v["estado"] == "na_fila":
        saida["posicao_na_fila"] = fila.posicao_na_fila(v["id"])
    if v["estado"] == "erro":
        saida["erro"] = (v.get("erro") or "").splitlines()[0][:300] if v.get("erro") else None
    if v["estado"] == "pronto" and v.get("objeto") and v.get("expira_em"):
        restante = _segundos_ate(v["expira_em"])
        url = armazenamento.link(v["objeto"], restante, f"{v.get('titulo') or v['projeto']}.mp4") if restante > 0 else None
        saida["url_video"] = url or f"/v1/videos/{v['id']}/arquivo"
    if com_eventos:
        saida["eventos"] = fila.eventos(v["id"], 15)
    return saida


@roteador.post("/videos", status_code=202)
def pedir_video(pedido: PedidoDeVideo, authorization: Optional[str] = Header(None)):
    cliente = _cliente(authorization)
    limite = cliente.get("limite_por_dia")
    if limite and fila.pedidos_hoje(cliente["id"]) >= int(limite):
        raise HTTPException(status_code=429, detail=f"Limite de {limite} vídeos nas últimas 24 horas.")
    v = fila.enfileirar(pedido.roteiro, cliente_id=cliente["id"], titulo=pedido.titulo)
    return _publico(v)


@roteador.get("/videos")
def listar_videos(authorization: Optional[str] = Header(None), limite: int = 50):
    cliente = _cliente(authorization)
    return {"videos": fila.videos_do_cliente(cliente["id"], max(1, min(limite, 200)))}


@roteador.get("/videos/{video_id}")
def ver_video(video_id: str, authorization: Optional[str] = Header(None)):
    return _publico(_do_cliente(video_id, _cliente(authorization)), com_eventos=True)


@roteador.delete("/videos/{video_id}")
def cancelar_video(video_id: str, authorization: Optional[str] = Header(None)):
    v = _do_cliente(video_id, _cliente(authorization))
    if not fila.cancelar(v["id"]):
        raise HTTPException(status_code=409, detail=f"O vídeo já terminou ({v['estado']}).")
    return {"id": v["id"], "estado": "cancelado"}


@roteador.get("/videos/{video_id}/arquivo")
def baixar_video(video_id: str, authorization: Optional[str] = Header(None)):
    v = _do_cliente(video_id, _cliente(authorization))
    caminho = armazenamento.caminho_local(v.get("objeto") or "") if v["estado"] == "pronto" else None
    if caminho is None:
        raise HTTPException(status_code=404, detail="O vídeo não está disponível (ainda não ficou pronto ou expirou).")
    return FileResponse(caminho, media_type="video/mp4", filename=f"{v.get('titulo') or v['projeto']}.mp4")


@roteador.get("/saude")
def saude():
    return {"fila": fila.resumo()}
