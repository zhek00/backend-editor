"""Modelo do cliente: as decisões da fábrica respondidas pelo Claude de quem usa o MCP.

Pedido do usuário em 2026-10-06 (teste do MCP): quem compra o MCP usa a assinatura do próprio Claude para "pensar" o
vídeo (mapa e cenas do roteiro, escolha das fotos, descrição e julgamento das imagens, trilha, animações, revisão do
vídeo pronto). A fábrica fica só com o que o Claude não faz: narração, imagens de IA, busca nos bancos e render.

Projeto com "modelo": "cliente" no projeto.json não chama nenhum modelo de linguagem. Todo pedido que iria a um
modelo (openrouter_local.perguntar, uma_rota e o Jev em modo principal) vira uma tarefa nesta fila, com o mesmo texto,
as mesmas imagens e o mesmo formato de resposta, e a produção espera a resposta. O MCP (mcp_servidor.py) entrega as
tarefas ao Claude do cliente (proximas) e recebe as respostas (responder). Todas as regras da fábrica (precisão
literal, nunca repetir imagem, a conferência, o tapa-buraco) continuam valendo: só muda quem responde.
"""
import base64
import itertools
import json
import threading
import time
from pathlib import Path

ENTREGA_VENCE = 900  # segundos: tarefa entregue e não respondida volta para a fila (o cliente fechou a sessão)

_TRAVA = threading.Lock()
_TAREFAS: dict = {}
# por projeto: tarefas e imagens por etapa, e o tempo em que a produção ficou parada esperando o cliente (algum pedido
# na fila sem resposta). No teste mcp-pangolim-2 o andamento dizia "produzindo" havia 2h24 com a fábrica parada desde
# os primeiros 3 minutos, esperando a escolha das fotos
_MEDIDAS: dict = {}
_NUMEROS = itertools.count(1)
_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}


# Os dois grupos de tarefa, para o Claude do cliente mandar cada um ao modelo certo (o comando /fabrica-video do MCP).
# "roteiro" é ler o roteiro inteiro e decidir as cenas (o mapa, as cenas e o diretor): o julgamento pesa mais, vai ao
# Opus. "visual" é olhar imagens e escolher, conferir, revisar, e preencher animação e trilha: vai ao Sonnet.
ROTEIRO, VISUAL = "roteiro", "visual"


def grupo(etapa) -> str:
    etapa = str(etapa or "").lower()
    return ROTEIRO if etapa.startswith("roteirista") or "diretor" in etapa else VISUAL


class Cancelada(RuntimeError):
    """A produção desse projeto foi cancelada enquanto esperava a resposta."""


def ativo(projeto) -> bool:
    """O projeto é pensado pelo Claude do cliente? (projeto.json: "modelo": "cliente")"""
    return (getattr(projeto, "dados", None) or {}).get("modelo") == "cliente"


def _imagens_do_pedido(pedido, imagens):
    """(texto, imagens) de um pedido. O pedido montado com texto e imagens intercalados (a escolha das fotos) vira
    texto com marcas [imagem N], e as imagens vão na ordem em que aparecem."""
    saida, texto = [], pedido
    if isinstance(pedido, list):
        partes = []
        for parte in pedido:
            if parte.get("type") == "text":
                partes.append(parte.get("text", ""))
            elif parte.get("type") == "image_url":
                url = (parte.get("image_url") or {}).get("url", "")
                if url.startswith("data:") and "," in url:
                    cabeca, dados = url.split(",", 1)
                    saida.append({"mime": cabeca[5:].split(";")[0] or "image/jpeg", "dados": dados})
                    partes.append(f"[imagem {len(saida)}]")
        texto = "\n".join(partes)
    for caminho in imagens or ():
        caminho = Path(caminho)
        saida.append({"mime": _MIME.get(caminho.suffix.lower(), "image/jpeg"),
                      "dados": base64.standard_b64encode(caminho.read_bytes()).decode()})
    return str(texto), saida


def pedir(projeto, etapa, instrucoes, pedido, esquema, imagens=(), log=print) -> dict:
    """Põe o pedido na fila e espera o Claude do cliente responder. Devolve a resposta (um dicionário)."""
    texto, figuras = _imagens_do_pedido(pedido, imagens)
    tarefa = {"id": f"t{next(_NUMEROS)}", "projeto": projeto.nome, "etapa": etapa, "instrucoes": instrucoes,
              "pedido": texto, "esquema": esquema or {}, "imagens": figuras, "criada": time.time(), "entregue": 0.0,
              "evento": threading.Event(), "resposta": None, "cancelada": False}
    with _TRAVA:
        if not any(t["projeto"] == projeto.nome for t in _TAREFAS.values()):
            _medidas(projeto.nome)["esperando_desde"] = time.time()
        _TAREFAS[tarefa["id"]] = tarefa
        m = _medidas(projeto.nome)
        por_etapa = m["por_etapa"].setdefault(etapa, {"tarefas": 0, "imagens": 0})
        por_etapa["tarefas"] += 1
        por_etapa["imagens"] += len(figuras)
    log(f"  esperando o Claude do cliente: {etapa} ({tarefa['id']})")
    tarefa["evento"].wait()
    with _TRAVA:
        _TAREFAS.pop(tarefa["id"], None)
        m = _medidas(projeto.nome)
        if m["esperando_desde"] and not any(t["projeto"] == projeto.nome for t in _TAREFAS.values()):
            m["espera"] += time.time() - m["esperando_desde"]
            m["esperando_desde"] = None
    if tarefa["cancelada"]:
        raise Cancelada(f"a produção de {projeto.nome} foi cancelada")
    return tarefa["resposta"]


def proximas(projeto=None, limite=3, tipo=None) -> list:
    """As tarefas que esperam resposta, as mais antigas primeiro (só as do grupo `tipo`, se dado). Cada uma fica
    reservada por ENTREGA_VENCE segundos: se não vier resposta nesse tempo, ela volta para a fila."""
    agora = time.time()
    with _TRAVA:
        livres = [t for t in _TAREFAS.values() if (projeto is None or t["projeto"] == projeto)
                  and (not tipo or grupo(t["etapa"]) == tipo) and agora - t["entregue"] >= ENTREGA_VENCE]
        livres.sort(key=lambda t: t["criada"])
        escolhidas = livres[:max(1, limite)]
        for t in escolhidas:
            t["entregue"] = agora
        return [{k: v for k, v in t.items() if k not in ("evento", "resposta", "cancelada")} for t in escolhidas]


def _faltam(esquema, resposta) -> list:
    if not isinstance(resposta, dict):
        return ["(a resposta tem de ser um objeto JSON)"]
    return [k for k in (esquema or {}).get("required", []) if k not in resposta]


def responder(tarefa_id, resposta) -> dict:
    """Entrega a resposta de uma tarefa. Resposta sem as chaves obrigatórias do esquema é recusada, e a tarefa
    continua esperando (o Claude do cliente corrige e responde de novo)."""
    if isinstance(resposta, str):
        try:
            resposta = json.loads(resposta)
        except json.JSONDecodeError as e:
            return {"ok": False, "erro": f"a resposta não é um JSON válido: {e}"}
    with _TRAVA:
        tarefa = _TAREFAS.get(tarefa_id)
        if tarefa is None:
            return {"ok": False, "erro": f"a tarefa {tarefa_id} não existe ou já foi respondida"}
        faltam = _faltam(tarefa["esquema"], resposta)
        if faltam:
            return {"ok": False, "erro": f"faltam as chaves obrigatórias {', '.join(faltam)} do esquema"}
        tarefa["resposta"] = resposta
        tarefa["evento"].set()
    return {"ok": True}


def _medidas(nome) -> dict:
    return _MEDIDAS.setdefault(nome, {"por_etapa": {}, "espera": 0.0, "esperando_desde": None})


def medidas(nome) -> dict:
    """Tarefas e imagens por etapa e os segundos esperando o cliente (contando a espera de agora, se houver)."""
    with _TRAVA:
        m = _medidas(nome)
        agora = time.time() - m["esperando_desde"] if m["esperando_desde"] else 0.0
        return {"por_etapa": {k: dict(v) for k, v in m["por_etapa"].items()}, "espera": m["espera"] + agora,
                "esperando_agora": agora,
                "tarefas": sum(v["tarefas"] for v in m["por_etapa"].values()),
                "imagens": sum(v["imagens"] for v in m["por_etapa"].values())}


def projeto_da_tarefa(tarefa_id):
    """O projeto de uma tarefa que espera resposta, ou None."""
    with _TRAVA:
        tarefa = _TAREFAS.get(tarefa_id)
        return tarefa["projeto"] if tarefa else None


def pendentes(projeto=None, tipo=None, livres=False) -> int:
    """Tarefas esperando resposta (do grupo `tipo`, se dado). Com livres, só as que ninguém está respondendo agora."""
    agora = time.time()
    with _TRAVA:
        return sum(1 for t in _TAREFAS.values() if (projeto is None or t["projeto"] == projeto)
                   and (not tipo or grupo(t["etapa"]) == tipo)
                   and (not livres or agora - t["entregue"] >= ENTREGA_VENCE))


def cancelar(projeto) -> int:
    """Solta as tarefas que esperam resposta desse projeto: a produção para com Cancelada."""
    with _TRAVA:
        alvo = [t for t in _TAREFAS.values() if t["projeto"] == projeto]
        for t in alvo:
            t["cancelada"] = True
            t["evento"].set()
    return len(alvo)
