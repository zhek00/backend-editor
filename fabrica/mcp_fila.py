"""O MCP no modo da produção em massa (FABRICA_MODO=fila, PLANO-VPS.md): criar_video só põe o roteiro na fila do
banco, e acompanhar, esperar, entregar_video e cancelar leem o banco. Quem produz são os trabalhadores
(`fabrica trabalhador`), em qualquer máquina; o MCP não roda produção nenhuma dentro dele.

Cada cliente do MCP (o token, clientes_mcp.py) é um cliente no banco com id "mcp:NOME". Mandar o mesmo roteiro de
novo, com o vídeo ainda em andamento, devolve o mesmo vídeo em vez de começar outro (como no MCP de antes)."""
import hashlib
import os
from datetime import datetime, timezone

from . import armazenamento, fila


def ativo() -> bool:
    return os.environ.get("FABRICA_MODO", "").strip().lower() == "fila"


def _id(cliente: str) -> str:
    return fila.garantir_cliente(f"mcp:{cliente}", cliente)


def _marca(roteiro: str) -> str:
    return hashlib.sha1(" ".join(roteiro.split()).encode("utf-8")).hexdigest()[:16]


def criar(roteiro: str, cliente: str, nome_automatico) -> str:
    roteiro = roteiro or ""
    if len(roteiro.strip()) < 20:
        return "O roteiro está vazio ou curto demais."
    cid, marca = _id(cliente), _marca(roteiro)
    for v in fila.videos_do_cliente(cid, 50):
        if v["estado"] in ("na_fila", "produzindo"):
            completo = fila.video(v["id"])
            if (completo.get("opcoes") or {}).get("marca") == marca:
                return f"{v['projeto']} já está em produção. NOME: {v['projeto']}."
    v = fila.enfileirar(roteiro, cliente_id=cid, titulo=None, opcoes={"marca": marca}, projeto=nome_automatico(roteiro))
    return f"Vídeo começou. NOME: {v['projeto']} (as outras ferramentas pedem este nome)."


def e_meu(nome: str, cliente: str) -> bool:
    v = fila.video_do_projeto(nome) if nome else None
    return bool(v) and v.get("cliente_id") == f"mcp:{cliente}"


def progresso(nome: str, etapas: int) -> dict:
    v = fila.video_do_projeto(nome) or {}
    estado = v.get("estado")
    if estado == "pronto":
        return {"estado": "pronto", "etapa": etapas, "total": etapas, "titulo": "Vídeo pronto", "porcentagem": 100,
                "frase": "Seu vídeo está pronto. Chame entregar_video para o link."}
    if estado in ("erro", "cancelado", "expirado"):
        frase = {"erro": "A produção parou com erro.", "cancelado": "A produção foi cancelada.",
                 "expirado": "O vídeo expirou: os arquivos são apagados 3 dias depois de prontos."}[estado]
        return {"estado": "erro" if estado == "expirado" else estado, "etapa": 0, "total": etapas,
                "titulo": "Produção interrompida", "porcentagem": 0, "frase": frase}
    if estado == "na_fila":
        posicao = fila.posicao_na_fila(v["id"])
        esperando = (v.get("mensagem") or "").startswith("esperando")
        return {"estado": "produzindo", "etapa": 1, "total": etapas, "porcentagem": int(v.get("progresso") or 0),
                "titulo": "Esperando um serviço voltar" if esperando else f"Na fila (posição {posicao})",
                "frase": v.get("mensagem") or "na fila"}
    porcentagem = int(v.get("progresso") or 0)
    return {"estado": "produzindo", "etapa": max(1, min(etapas, 1 + porcentagem * etapas // 100)), "total": etapas,
            "titulo": (v.get("mensagem") or v.get("etapa") or "Produzindo")[:80], "porcentagem": porcentagem,
            "frase": v.get("mensagem") or ""}


def estado_curto(nome: str) -> str:
    v = fila.video_do_projeto(nome) or {}
    estado = v.get("estado")
    if estado in ("pronto", "cancelado"):
        return estado
    if estado == "erro":
        return "erro: " + (v.get("erro") or "")[:600]
    if estado == "expirado":
        return "erro: o vídeo expirou (3 dias)"
    return "trabalhando" if estado else "sem produção"


def tempo(nome: str) -> str:
    v = fila.video_do_projeto(nome) or {}
    if not v.get("iniciado_em"):
        return ""
    ler = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)  # noqa: E731
    fim = ler(v["concluido_em"]) if v.get("concluido_em") else datetime.now(timezone.utc)
    segundos = int(max(0, (fim - ler(v["iniciado_em"])).total_seconds()))
    return f"{segundos // 3600}h{segundos % 3600 // 60:02d}min" if segundos >= 3600 else f"{segundos // 60}min{segundos % 60:02d}s"


def entregar(nome: str, url_publica: str) -> str:
    v = fila.video_do_projeto(nome) or {}
    if v.get("estado") != "pronto" or not v.get("objeto"):
        return f"{nome} ainda não tem o vídeo pronto."
    fim = datetime.strptime(v["expira_em"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    restante = int((fim - datetime.now(timezone.utc)).total_seconds())
    url = armazenamento.link(v["objeto"], restante, f"{nome}.mp4")
    if not url:
        url = (url_publica or "").rstrip("/") + f"/v1/videos/{v['id']}/arquivo"
    return (f"Vídeo: {url}\nBaixe para a pasta atual do usuário (por exemplo, curl -L -o {nome}.mp4 \"LINK\"). "
            f"O link vale até {v['expira_em']} (3 dias depois de pronto); depois o vídeo é apagado.")


def cancelar(nome: str) -> str:
    v = fila.video_do_projeto(nome) or {}
    return "Cancelado." if v and fila.cancelar(v["id"]) else f"{nome} já terminou ({v.get('estado')})."
