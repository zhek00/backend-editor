"""A fila de produção: cada vídeo pedido (pelo MCP ou pela API /v1) é uma linha em `videos`, e os trabalhadores
(fabrica trabalhador) pegam o próximo, produzem e entregam, sem ninguém (PLANO-VPS.md).

Estados: na_fila -> produzindo -> pronto | erro | cancelado, e depois expirado (limpeza_vps, 3 dias depois de terminar).
- pegar: o próximo da fila, de forma que dois trabalhadores nunca peguem o mesmo (FOR UPDATE SKIP LOCKED no PostgreSQL,
  um escritor por vez no SQLite).
- sinal de vida: o trabalhador marca a cada minuto; o vídeo de quem parou de marcar (a máquina caiu) volta à fila.
- esperar: problema que passa sozinho (crédito acabou, chave recusada, serviço fora do ar) devolve o vídeo à fila
  para depois, em vez de parar esperando uma pessoa (o everything-you-need-to-answer ficou 3 h parado sem crédito).
"""
import hashlib
import secrets
import uuid
from datetime import timedelta

from .banco import agora, banco, json_de

DIAS_ATE_EXPIRAR = 3          # pedido do usuário: vídeo e arquivos apagados em no máximo 3 dias
TENTATIVAS_MAXIMAS = 4        # falhas de verdade (não as esperas) até o vídeo ficar com erro
MINUTOS_SEM_SINAL = 10        # trabalhador que não marca há mais que isso morreu: o vídeo volta à fila
TERMINAIS = ("pronto", "erro", "cancelado", "expirado")


# ------------------------------------------------------------------------------------------------ clientes
def _hash(chave: str) -> str:
    return hashlib.sha256(chave.encode("utf-8")).hexdigest()


def criar_cliente(nome: str, limite_por_dia=None) -> tuple:
    """(id, chave). A chave só aparece aqui: o banco guarda o hash dela."""
    cid, chave = uuid.uuid4().hex, "fab_" + secrets.token_urlsafe(32)
    banco().executar("INSERT INTO clientes (id, nome, chave_hash, ativo, limite_por_dia, criado_em) "
                     "VALUES (%s, %s, %s, 1, %s, %s)", (cid, nome, _hash(chave), limite_por_dia, agora()))
    return cid, chave


def garantir_cliente(cid: str, nome: str) -> str:
    """O cliente com este id (os do MCP entram como "mcp:NOME", pelo token do MCP, sem chave da /v1)."""
    if banco().um("SELECT id FROM clientes WHERE id = %s", (cid,)) is None:
        try:
            banco().executar("INSERT INTO clientes (id, nome, chave_hash, ativo, criado_em) VALUES (%s, %s, %s, 1, %s)",
                             (cid, nome, _hash(secrets.token_hex(32)), agora()))
        except Exception:  # noqa: BLE001 - outro pedido criou ao mesmo tempo
            pass
    return cid


def cliente_da_chave(chave: str):
    if not chave:
        return None
    return banco().um("SELECT * FROM clientes WHERE chave_hash = %s AND ativo = 1", (_hash(chave.strip()),))


def pedidos_hoje(cliente_id: str) -> int:
    linha = banco().um("SELECT COUNT(*) AS n FROM videos WHERE cliente_id = %s AND criado_em >= %s",
                       (cliente_id, agora(-timedelta(days=1))))
    return int(linha["n"]) if linha else 0


# ------------------------------------------------------------------------------------------------ entrada
def enfileirar(roteiro: str, cliente_id=None, titulo=None, opcoes=None, prioridade=0, projeto=None) -> dict:
    """Põe o pedido na fila e devolve a linha do vídeo. projeto: o nome da pasta (único); sem ele, um a partir do id."""
    if not (roteiro or "").strip():
        raise ValueError("o roteiro está vazio")
    vid = uuid.uuid4().hex
    nome = projeto or f"v-{vid[:12]}"
    banco().executar(
        "INSERT INTO videos (id, cliente_id, projeto, titulo, roteiro, opcoes, estado, etapa, progresso, prioridade, "
        "criado_em) VALUES (%s, %s, %s, %s, %s, %s, 'na_fila', 'na fila', 0, %s, %s)",
        (vid, cliente_id, nome, titulo, roteiro, _json(opcoes), prioridade, agora()))
    evento(vid, "fila", "pedido recebido")
    return video(vid)


def _json(dados) -> str:
    import json

    return json.dumps(dados or {}, ensure_ascii=False)


# ------------------------------------------------------------------------------------------------ trabalhador
def pegar(trabalhador: str):
    """O próximo vídeo da fila para este trabalhador (já marcado como produzindo), ou None."""
    b = banco()
    trava = "FOR UPDATE SKIP LOCKED" if b.postgres else ""
    with b.transacao() as c:
        linha = c.um(
            "SELECT id FROM videos WHERE estado = 'na_fila' AND (proxima_tentativa IS NULL OR proxima_tentativa <= %s) "
            f"ORDER BY prioridade DESC, criado_em ASC LIMIT 1 {trava}", (agora(),))
        if linha is None:
            return None
        c.executar(
            "UPDATE videos SET estado = 'produzindo', trabalhador = %s, sinal_de_vida = %s, "
            "iniciado_em = COALESCE(iniciado_em, %s), proxima_tentativa = NULL, mensagem = %s WHERE id = %s",
            (trabalhador, agora(), agora(), "começando", linha["id"]))
    evento(linha["id"], "fila", f"pego por {trabalhador}")
    return video(linha["id"])


def sinal_de_vida(video_id: str, trabalhador: str) -> bool:
    """Marca que o trabalhador segue vivo com o vídeo. False: o vídeo não é mais dele (cancelado, devolvido)."""
    return banco().executar("UPDATE videos SET sinal_de_vida = %s WHERE id = %s AND trabalhador = %s "
                            "AND estado = 'produzindo'", (agora(), video_id, trabalhador)) > 0


def atualizar(video_id: str, **campos) -> None:
    """etapa, progresso, mensagem, custo_usd, duracao_s..."""
    permitidos = {"etapa", "progresso", "mensagem", "custo_usd", "duracao_s", "titulo"}
    campos = {k: v for k, v in campos.items() if k in permitidos}
    if not campos:
        return
    sets = ", ".join(f"{k} = %s" for k in campos)
    banco().executar(f"UPDATE videos SET {sets} WHERE id = %s", (*campos.values(), video_id))


def concluir(video_id: str, objeto=None, url_video=None, custo_usd=None, duracao_s=None) -> None:
    banco().executar(
        "UPDATE videos SET estado = 'pronto', etapa = 'pronto', progresso = 100, mensagem = 'vídeo pronto', erro = NULL, "
        "concluido_em = %s, expira_em = %s, objeto = %s, url_video = %s, custo_usd = %s, duracao_s = %s, "
        "trabalhador = NULL WHERE id = %s",
        (agora(), agora(timedelta(days=DIAS_ATE_EXPIRAR)), objeto, url_video, custo_usd, duracao_s, video_id))
    evento(video_id, "fila", "pronto")


def esperar(video_id: str, motivo: str, minutos: float) -> None:
    """Devolve à fila para depois, sem contar como falha: o problema passa sozinho (crédito, chave, serviço fora)."""
    banco().executar(
        "UPDATE videos SET estado = 'na_fila', trabalhador = NULL, proxima_tentativa = %s, mensagem = %s WHERE id = %s "
        "AND estado = 'produzindo'", (agora(timedelta(minutes=minutos)), f"esperando: {motivo}"[:500], video_id))
    evento(video_id, "espera", f"{motivo} (de novo em {minutos:g} min)")


def falhar(video_id: str, erro: str, definitivo: bool = False) -> str:
    """Falha de verdade: volta à fila com espera crescente até TENTATIVAS_MAXIMAS; depois fica com erro (e expira em 3
    dias). definitivo: erro na hora, sem tentar de novo (consumo alto: tentar de novo gastaria de novo). Devolve o estado
    novo."""
    b = banco()
    with b.transacao() as c:
        linha = c.um("SELECT tentativas FROM videos WHERE id = %s", (video_id,))
        tentativas = int((linha or {}).get("tentativas") or 0) + 1
        if definitivo or tentativas >= TENTATIVAS_MAXIMAS:
            c.executar("UPDATE videos SET estado = 'erro', tentativas = %s, erro = %s, mensagem = 'erro', trabalhador = NULL, "
                       "concluido_em = %s, expira_em = %s WHERE id = %s",
                       (tentativas, erro[:4000], agora(), agora(timedelta(days=DIAS_ATE_EXPIRAR)), video_id))
            estado = "erro"
        else:
            c.executar("UPDATE videos SET estado = 'na_fila', tentativas = %s, erro = %s, trabalhador = NULL, "
                       "proxima_tentativa = %s, mensagem = %s WHERE id = %s",
                       (tentativas, erro[:4000], agora(timedelta(minutes=5 * tentativas)),
                        f"falhou, tentando de novo ({tentativas + 1} de {TENTATIVAS_MAXIMAS})", video_id))
            estado = "na_fila"
    evento(video_id, "erro", erro[:1000])
    return estado


def cancelar(video_id: str) -> bool:
    n = banco().executar("UPDATE videos SET estado = 'cancelado', mensagem = 'cancelado', trabalhador = NULL, "
                         "concluido_em = %s, expira_em = %s WHERE id = %s AND estado IN ('na_fila', 'produzindo')",
                         (agora(), agora(timedelta(days=DIAS_ATE_EXPIRAR)), video_id))
    if n:
        evento(video_id, "fila", "cancelado")
    return n > 0


def devolver_abandonados(minutos: float = MINUTOS_SEM_SINAL) -> list:
    """Os vídeos de trabalhador que parou de dar sinal (a máquina caiu, o processo morreu) voltam à fila."""
    limite = agora(-timedelta(minutes=minutos))
    b = banco()
    with b.transacao() as c:
        linhas = c.todos("SELECT id FROM videos WHERE estado = 'produzindo' AND (sinal_de_vida IS NULL OR sinal_de_vida < %s)",
                         (limite,))
        for linha in linhas:
            c.executar("UPDATE videos SET estado = 'na_fila', trabalhador = NULL, mensagem = %s WHERE id = %s",
                       ("o trabalhador parou; voltou à fila", linha["id"]))
    for linha in linhas:
        evento(linha["id"], "fila", "trabalhador parou de responder; voltou à fila")
    return [linha["id"] for linha in linhas]


# ------------------------------------------------------------------------------------------------ leitura
def video(video_id: str):
    linha = banco().um("SELECT * FROM videos WHERE id = %s", (video_id,))
    if linha is not None:
        linha["opcoes"] = json_de(linha.get("opcoes"))
    return linha


def video_do_projeto(projeto: str):
    linha = banco().um("SELECT id FROM videos WHERE projeto = %s", (projeto,))
    return video(linha["id"]) if linha else None


def videos_do_cliente(cliente_id: str, limite: int = 50) -> list:
    return banco().todos("SELECT id, projeto, titulo, estado, etapa, progresso, mensagem, criado_em, concluido_em, "
                         "expira_em, url_video FROM videos WHERE cliente_id = %s ORDER BY criado_em DESC LIMIT %s",
                         (cliente_id, limite))


def expirados() -> list:
    """Os que passaram do prazo (pronto, erro ou cancelado) e ainda não foram apagados."""
    return banco().todos("SELECT * FROM videos WHERE estado IN ('pronto', 'erro', 'cancelado') AND expira_em IS NOT NULL "
                         "AND expira_em <= %s", (agora(),))


def marcar_expirado(video_id: str) -> None:
    banco().executar("UPDATE videos SET estado = 'expirado', url_video = NULL, apagado_em = %s, roteiro = '' WHERE id = %s",
                     (agora(), video_id))
    evento(video_id, "limpeza", "arquivos apagados (3 dias)")


def posicao_na_fila(video_id: str):
    v = video(video_id)
    if not v or v["estado"] != "na_fila":
        return None
    linha = banco().um("SELECT COUNT(*) AS n FROM videos WHERE estado = 'na_fila' AND "
                       "(prioridade > %s OR (prioridade = %s AND criado_em < %s))",
                       (v["prioridade"], v["prioridade"], v["criado_em"]))
    return int(linha["n"]) + 1


def resumo() -> dict:
    """Quantos vídeos em cada estado: para a saúde (/v1/saude) e o monitoramento."""
    linhas = banco().todos("SELECT estado, COUNT(*) AS n FROM videos GROUP BY estado")
    return {l["estado"]: int(l["n"]) for l in linhas}


# ------------------------------------------------------------------------------------------------ eventos
def evento(video_id: str, tipo: str, texto: str) -> None:
    banco().executar("INSERT INTO eventos (video_id, quando, tipo, texto) VALUES (%s, %s, %s, %s)",
                     (video_id, agora(), tipo, str(texto)[:2000]))


def eventos(video_id: str, ultimos: int = 30) -> list:
    linhas = banco().todos("SELECT quando, tipo, texto FROM eventos WHERE video_id = %s ORDER BY id DESC LIMIT %s",
                           (video_id, ultimos))
    return list(reversed(linhas))


def apagar_eventos_de(video_id: str) -> None:
    banco().executar("DELETE FROM eventos WHERE video_id = %s", (video_id,))
