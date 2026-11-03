"""Painel do Robô PALHANO: conta, canais, chaves, máquinas, fila de produções e custos.

Rodar: uv run fabrica painel (porta 8300) ou palhano/LIGAR-PAINEL.bat."""
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import banco, chaves, estilos

WEB = Path(__file__).resolve().parent / "web"
COOKIE = "palhano_sessao"
ONLINE_SEGUNDOS = 30          # a máquina avisa a cada 5 s; sem aviso por 30 s, fica desconectada
LINHAS_GUARDADAS = 40

app = FastAPI(title="Robô PALHANO", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------- contas e sessões

def _usuario_da_sessao(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    sessao = banco.um("SELECT usuario_id FROM sessoes WHERE token_hash=?", banco.hash_token(token))
    return banco.um("SELECT * FROM usuarios WHERE id=?", sessao["usuario_id"]) if sessao else None


def usuario(request: Request) -> dict:
    u = _usuario_da_sessao(request)
    if not u:
        raise HTTPException(401, "Entre na sua conta.")
    return u


def liberado(u: dict = Depends(usuario)) -> dict:
    """Conta aprovada e com plano em dia. A administração passa sempre."""
    if u["admin"]:
        return u
    if not u["aprovado"]:
        raise HTTPException(403, "Seu cadastro está em análise. Você recebe acesso quando a administração aprovar.")
    if not u["plano"]:
        raise HTTPException(402, "Sua conta ainda não tem um plano ativo.")
    if u["vence"] and u["vence"] < banco.hoje_brasilia():
        raise HTTPException(402, "Seu plano venceu. Renove para continuar produzindo.")
    return u


def admin(u: dict = Depends(usuario)) -> dict:
    if not u["admin"]:
        raise HTTPException(403, "Só a administração.")
    return u


def _abrir_sessao(resposta: Response, usuario_id: int) -> None:
    token = banco.novo_token()
    banco.executar("INSERT INTO sessoes (token_hash, usuario_id, criado) VALUES (?,?,?)",
                   banco.hash_token(token), usuario_id, banco.agora())
    resposta.set_cookie(COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 60,
                        secure=os.environ.get("PALHANO_HTTPS") == "1")


def _publico(u: dict) -> dict:
    limite = banco.limite_do_dia(u)
    return {
        "id": u["id"], "email": u["email"], "nome": u["nome"], "admin": bool(u["admin"]),
        "aprovado": bool(u["aprovado"]), "plano": u["plano"],
        "plano_nome": banco.PLANOS.get(u["plano"], {}).get("nome", ""), "vence": u["vence"],
        "limite_dia": limite, "usadas_hoje": banco.usadas_hoje(u["id"]),
    }


@app.post("/api/cadastro")
async def cadastro(request: Request):
    d = await request.json()
    email = str(d.get("email", "")).strip().lower()
    senha = str(d.get("senha", ""))
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(400, "E-mail inválido.")
    if len(senha) < 8:
        raise HTTPException(400, "A senha precisa de pelo menos 8 caracteres.")
    if banco.um("SELECT id FROM usuarios WHERE email=?", email):
        raise HTTPException(400, "Já existe uma conta com esse e-mail.")
    # a primeira conta do painel é a da administração
    primeira = banco.um("SELECT COUNT(*) AS n FROM usuarios")["n"] == 0
    uid = banco.executar(
        "INSERT INTO usuarios (email, nome, senha_hash, aprovado, admin, plano, criado) VALUES (?,?,?,?,?,?,?)",
        email, str(d.get("nome", "")).strip()[:80], banco.hash_senha(senha), int(primeira), int(primeira),
        "ilimitado" if primeira else "", banco.agora())
    resposta = JSONResponse({"ok": True, "admin": primeira})
    _abrir_sessao(resposta, uid)
    return resposta


@app.post("/api/entrar")
async def entrar(request: Request):
    d = await request.json()
    u = banco.um("SELECT * FROM usuarios WHERE email=?", str(d.get("email", "")).strip().lower())
    if not u or not banco.senha_confere(str(d.get("senha", "")), u["senha_hash"]):
        raise HTTPException(401, "E-mail ou senha não conferem.")
    resposta = JSONResponse({"ok": True})
    _abrir_sessao(resposta, u["id"])
    return resposta


@app.post("/api/sair")
def sair(request: Request):
    token = request.cookies.get(COOKIE)
    if token:
        banco.executar("DELETE FROM sessoes WHERE token_hash=?", banco.hash_token(token))
    resposta = JSONResponse({"ok": True})
    resposta.delete_cookie(COOKIE)
    return resposta


@app.get("/api/eu")
def eu(u: dict = Depends(usuario)):
    return _publico(u)


@app.get("/api/catalogo")
def catalogo():
    return {
        "estilos": estilos.ESTILOS, "narradores": estilos.NARRADORES, "padrao": estilos.PADRAO,
        "provedores": {k: {c: v[c] for c in ("nome", "obrigatoria", "para", "link")} | {"pool": bool(v.get("pool"))}
                       for k, v in chaves.PROVEDORES.items()},
        "planos": banco.PLANOS,
    }


# ---------------------------------------------------------------- canais (presets)

def _canal(linha: dict | None) -> dict | None:
    if not linha:
        return None
    linha = dict(linha)
    linha["ajustes"] = banco.json_de(linha.get("ajustes"), {})
    return linha


def _dados_do_canal(d: dict) -> tuple:
    nome = str(d.get("nome", "")).strip()[:80]
    if not nome:
        raise HTTPException(400, "Dê um nome ao canal.")
    ajustes = {k: d["ajustes"][k] for k in estilos.CAMPOS if k in (d.get("ajustes") or {}) and k not in ("destino",)}
    velocidade = d.get("velocidade")
    velocidade = min(1.2, max(0.7, float(velocidade))) if velocidade not in (None, "") else None
    narrador = d.get("narrador") if d.get("narrador") in estilos.NARRADORES else ""
    estilo = d.get("estilo") if d.get("estilo") in estilos.ESTILOS else ""
    return (nome, str(d.get("descricao", ""))[:500], str(d.get("diretrizes", ""))[:4000],
            str(d.get("descricao_fixa", ""))[:1500], narrador, str(d.get("voice_id", "")).strip()[:80], velocidade,
            estilo, json.dumps(ajustes))


@app.get("/api/canais")
def listar_canais(u: dict = Depends(liberado)):
    return [_canal(c) for c in banco.todos("SELECT * FROM canais WHERE usuario_id=? ORDER BY nome", u["id"])]


@app.post("/api/canais")
async def criar_canal(request: Request, u: dict = Depends(liberado)):
    campos = _dados_do_canal(await request.json())
    cid = banco.executar("INSERT INTO canais (usuario_id, nome, descricao, diretrizes, descricao_fixa, narrador, voice_id, "
                         "velocidade, estilo, ajustes, criado) VALUES (?,?,?,?,?,?,?,?,?,?,?)", u["id"], *campos,
                         banco.agora())
    return _canal(banco.um("SELECT * FROM canais WHERE id=?", cid))


@app.put("/api/canais/{cid}")
async def salvar_canal(cid: int, request: Request, u: dict = Depends(liberado)):
    if not banco.um("SELECT id FROM canais WHERE id=? AND usuario_id=?", cid, u["id"]):
        raise HTTPException(404, "Canal não encontrado.")
    campos = _dados_do_canal(await request.json())
    banco.executar("UPDATE canais SET nome=?, descricao=?, diretrizes=?, descricao_fixa=?, narrador=?, voice_id=?, "
                   "velocidade=?, estilo=?, ajustes=? WHERE id=?", *campos, cid)
    return _canal(banco.um("SELECT * FROM canais WHERE id=?", cid))


@app.delete("/api/canais/{cid}")
def excluir_canal(cid: int, u: dict = Depends(liberado)):
    banco.executar("DELETE FROM canais WHERE id=? AND usuario_id=?", cid, u["id"])
    return {"ok": True}


# ---------------------------------------------------------------- chaves de API

def _chave_publica(c: dict) -> dict:
    return {k: c[k] for k in ("id", "provedor", "final", "estado", "detalhe", "testada_em")}


@app.get("/api/chaves")
def listar_chaves(u: dict = Depends(liberado)):
    return {
        "chaves": [_chave_publica(c) for c in banco.todos("SELECT * FROM chaves WHERE usuario_id=? ORDER BY id", u["id"])],
        "faltando": chaves.faltando(u["id"], "fish"),
    }


@app.post("/api/chaves")
async def adicionar_chave(request: Request, u: dict = Depends(liberado)):
    d = await request.json()
    prov, valor = str(d.get("provedor", "")), str(d.get("valor", "")).strip()
    if prov not in chaves.PROVEDORES:
        raise HTTPException(400, "Provedor desconhecido.")
    if len(valor) < 8:
        raise HTTPException(400, "Essa chave parece incompleta.")
    estado, detalhe = chaves.testar(prov, valor)
    if estado == "recusada":
        raise HTTPException(400, f"Não salvei: {detalhe}. Confira se copiou a chave inteira.")
    if not chaves.PROVEDORES[prov].get("pool"):
        banco.executar("DELETE FROM chaves WHERE usuario_id=? AND provedor=?", u["id"], prov)
    elif banco.um("SELECT COUNT(*) AS n FROM chaves WHERE usuario_id=? AND provedor=?", u["id"], prov)["n"] >= 20:
        raise HTTPException(400, "Limite de 20 chaves por provedor.")
    banco.executar("INSERT INTO chaves (usuario_id, provedor, cifrada, final, estado, detalhe, testada_em, criada) "
                   "VALUES (?,?,?,?,?,?,?,?)", u["id"], prov, chaves.cifrar(valor), chaves.final(valor), estado, detalhe,
                   banco.agora(), banco.agora())
    return {"ok": True, "estado": estado, "detalhe": detalhe}


@app.post("/api/chaves/{kid}/testar")
def testar_chave(kid: int, u: dict = Depends(liberado)):
    c = banco.um("SELECT * FROM chaves WHERE id=? AND usuario_id=?", kid, u["id"])
    if not c:
        raise HTTPException(404, "Chave não encontrada.")
    estado, detalhe = chaves.testar(c["provedor"], chaves.decifrar(c["cifrada"]))
    banco.executar("UPDATE chaves SET estado=?, detalhe=?, testada_em=? WHERE id=?", estado, detalhe, banco.agora(), kid)
    return {"estado": estado, "detalhe": detalhe}


@app.delete("/api/chaves/{kid}")
def excluir_chave(kid: int, u: dict = Depends(liberado)):
    banco.executar("DELETE FROM chaves WHERE id=? AND usuario_id=?", kid, u["id"])
    return {"ok": True}


# ---------------------------------------------------------------- máquinas

def _online(m: dict) -> bool:
    if not m.get("visto_em"):
        return False
    visto = datetime.fromisoformat(m["visto_em"])
    return datetime.now(timezone.utc) - visto < timedelta(seconds=ONLINE_SEGUNDOS)


def _maquina_publica(m: dict) -> dict:
    return {"id": m["id"], "nome": m["nome"], "sistema": m["sistema"], "versao": m["versao"], "criada": m["criada"],
            "visto_em": m["visto_em"], "online": _online(m), "ocupada": bool(m["ocupada"]),
            "produzindo": int(m["ocupada"] or 0),
            "pasta_padrao": m["pasta_padrao"]}


@app.get("/api/maquinas")
def listar_maquinas(u: dict = Depends(liberado)):
    return [_maquina_publica(m) for m in banco.todos("SELECT * FROM maquinas WHERE usuario_id=? ORDER BY id", u["id"])]


@app.post("/api/maquinas/codigo")
def codigo_de_conexao(u: dict = Depends(liberado)):
    """Código de 8 letras que o robô pede na primeira vez. Vale 15 minutos."""
    banco.executar("DELETE FROM pareamentos WHERE usuario_id=?", u["id"])
    codigo = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    banco.executar("INSERT INTO pareamentos (codigo, usuario_id, criado) VALUES (?,?,?)", codigo, u["id"], banco.agora())
    return {"codigo": codigo, "minutos": 15}


@app.delete("/api/maquinas/{mid}")
def desconectar_maquina(mid: int, u: dict = Depends(liberado)):
    banco.executar("DELETE FROM maquinas WHERE id=? AND usuario_id=?", mid, u["id"])
    return {"ok": True}


# ---------------------------------------------------------------- produções

def _producao_publica(p: dict, com_roteiro=False) -> dict:
    d = {k: p[k] for k in ("id", "canal_id", "canal_nome", "nome", "estado", "etapa", "progresso", "maquina_id", "criada",
                           "iniciada", "terminada", "duracao_s", "custo_usd", "arquivo", "erro")}
    d["config"] = banco.json_de(p["config"], {})
    d["linhas"] = banco.json_de(p["linhas"], [])
    d["custo"] = banco.json_de(p["custo"], {})
    d["palavras"] = len(p["roteiro"].split())
    d["minutos_estimados"] = estilos.minutos_estimados(p["roteiro"])
    if p["iniciada"]:
        fim = datetime.fromisoformat(p["terminada"]) if p["terminada"] else datetime.now(timezone.utc)
        d["trabalho_s"] = int((fim - datetime.fromisoformat(p["iniciada"])).total_seconds())
    if com_roteiro:
        d["roteiro"] = p["roteiro"]
    return d


def _minha_producao(pid: int, u: dict) -> dict:
    p = banco.um("SELECT * FROM producoes WHERE id=? AND usuario_id=?", pid, u["id"])
    if not p:
        raise HTTPException(404, "Produção não encontrada.")
    return p


@app.post("/api/producoes/previa")
async def previa(request: Request, u: dict = Depends(liberado)):
    """O que vai ser produzido, com os avisos, antes de enviar ao robô."""
    d = await request.json()
    canal = _canal(banco.um("SELECT * FROM canais WHERE id=? AND usuario_id=?", d.get("canal_id") or 0, u["id"]))
    ajustes = estilos.misturar(canal, d.get("ajustes") or {})
    return {"ajustes": ajustes, "avisos": _avisos(u, ajustes, str(d.get("roteiro", ""))),
            "minutos_estimados": estilos.minutos_estimados(str(d.get("roteiro", "")))}


def _avisos(u: dict, ajustes: dict, roteiro: str) -> list:
    avisos = []
    if not ajustes["teste"]:
        falta = chaves.faltando(u["id"], ajustes["narrador"])
        if falta:
            avisos.append({"tipo": "bloqueia", "texto": "Faltam chaves em Integrações: " + ", ".join(falta) + "."})
    if ajustes["narrador"] == "genaipro" and not ajustes.get("voice_id") and not ajustes["teste"]:
        avisos.append({"tipo": "bloqueia", "texto": "A GenAI Pro precisa do código da voz (voice_id), no canal ou "
                                                     "nos ajustes deste vídeo."})
    if len(roteiro.split()) < 30:
        avisos.append({"tipo": "bloqueia", "texto": "O roteiro está muito curto (mínimo de 30 palavras)."})
    maquinas = [m for m in banco.todos("SELECT * FROM maquinas WHERE usuario_id=?", u["id"]) if _online(m)]
    if not maquinas:
        avisos.append({"tipo": "aviso", "texto": "Nenhuma máquina conectada agora. O vídeo entra na fila e começa "
                                                 "quando o robô ligar."})
    limite = banco.limite_do_dia(u)
    if limite > 0 and banco.usadas_hoje(u["id"]) >= limite:
        avisos.append({"tipo": "bloqueia", "texto": f"Você já usou os {limite} vídeos de hoje. A contagem recomeça à "
                                                     "meia-noite (horário de Brasília)."})
    if ajustes["teste"]:
        avisos.append({"tipo": "info", "texto": "Modo teste: voz do computador e imagens de teste, sem gastar nada."})
    if not ajustes["ia"]:
        avisos.append({"tipo": "info", "texto": "Sem imagens de IA: cena que o acervo não resolver fica com a imagem "
                                                "mais próxima do assunto."})
    return avisos


@app.post("/api/producoes")
async def criar_producao(request: Request, u: dict = Depends(liberado)):
    d = await request.json()
    roteiro = str(d.get("roteiro", "")).strip()
    canal = _canal(banco.um("SELECT * FROM canais WHERE id=? AND usuario_id=?", d.get("canal_id") or 0, u["id"]))
    ajustes = estilos.misturar(canal, d.get("ajustes") or {})
    bloqueios = [a["texto"] for a in _avisos(u, ajustes, roteiro) if a["tipo"] == "bloqueia"]
    if bloqueios:
        raise HTTPException(400, " ".join(bloqueios))
    nome = str(d.get("nome", "")).strip()[:120] or roteiro.split("\n")[0][:60] or "Vídeo sem nome"
    config = {"ajustes": ajustes, "fabrica": estilos.para_fabrica(ajustes, canal)}
    pid = banco.executar(
        "INSERT INTO producoes (usuario_id, canal_id, canal_nome, nome, roteiro, config, estado, criada, dia) "
        "VALUES (?,?,?,?,?,?,?,?,?)", u["id"], canal["id"] if canal else None, canal["nome"] if canal else "", nome,
        roteiro, json.dumps(config, ensure_ascii=False), "fila", banco.agora(), banco.hoje_brasilia())
    return _producao_publica(banco.um("SELECT * FROM producoes WHERE id=?", pid))


@app.get("/api/producoes")
def listar_producoes(u: dict = Depends(liberado)):
    linhas = banco.todos("SELECT * FROM producoes WHERE usuario_id=? AND escondida=0 ORDER BY id DESC LIMIT 500", u["id"])
    return [_producao_publica(p) for p in linhas]


@app.get("/api/producoes/{pid}")
def ver_producao(pid: int, u: dict = Depends(liberado)):
    return _producao_publica(_minha_producao(pid, u), com_roteiro=True)


def _comando(maquina_id, tipo: str, dados: dict) -> None:
    if maquina_id:
        banco.executar("INSERT INTO comandos (maquina_id, tipo, dados, criado) VALUES (?,?,?,?)",
                       maquina_id, tipo, json.dumps(dados, ensure_ascii=False), banco.agora())


@app.post("/api/producoes/{pid}/cancelar")
def cancelar(pid: int, u: dict = Depends(liberado)):
    p = _minha_producao(pid, u)
    if p["estado"] in ("entregue", "cancelado"):
        return {"ok": True}
    if p["estado"] == "produzindo":
        _comando(p["maquina_id"], "cancelar", {"producao_id": pid})
    banco.executar("UPDATE producoes SET estado='cancelado', terminada=? WHERE id=?", banco.agora(), pid)
    return {"ok": True}


@app.post("/api/producoes/{pid}/retomar")
def retomar(pid: int, u: dict = Depends(liberado)):
    """Volta para a fila. O robô continua de onde parou, sem pagar de novo o que já foi feito."""
    p = _minha_producao(pid, u)
    if p["estado"] not in ("falhou", "cancelado", "atencao"):
        raise HTTPException(400, "Só dá para retomar uma produção que parou.")
    banco.executar("UPDATE producoes SET estado='fila', erro='', terminada='', dia=? WHERE id=?",
                   banco.hoje_brasilia() if p["estado"] == "cancelado" else p["dia"], pid)
    return {"ok": True}


@app.post("/api/producoes/{pid}/{acao}")
def acao_na_maquina(pid: int, acao: str, u: dict = Depends(liberado)):
    if acao not in ("abrir", "assistir"):
        raise HTTPException(404, "Ação desconhecida.")
    p = _minha_producao(pid, u)
    if not p["arquivo"] or not p["maquina_id"]:
        raise HTTPException(400, "Esse vídeo ainda não foi entregue.")
    m = banco.um("SELECT * FROM maquinas WHERE id=?", p["maquina_id"])
    if not m or not _online(m):
        raise HTTPException(400, "A máquina que fez esse vídeo não está conectada agora.")
    _comando(m["id"], acao, {"arquivo": p["arquivo"]})
    return {"ok": True}


@app.delete("/api/producoes/{pid}")
def tirar_da_lista(pid: int, u: dict = Depends(liberado)):
    """Só some da lista: o MP4 continua no computador e a vaga do dia não volta."""
    p = _minha_producao(pid, u)
    if p["estado"] in ("fila", "produzindo"):
        raise HTTPException(400, "Cancele a produção antes de tirá-la da lista.")
    banco.executar("UPDATE producoes SET escondida=1 WHERE id=?", pid)
    return {"ok": True}


@app.get("/api/custos")
def custos(u: dict = Depends(liberado)):
    linhas = banco.todos("SELECT * FROM producoes WHERE usuario_id=? AND estado='entregue' ORDER BY id DESC", u["id"])
    lista = [_producao_publica(p) for p in linhas]
    total = sum(p["custo_usd"] or 0 for p in lista)
    minutos = sum((p["custo"].get("duracao_segundos") or 0) for p in lista) / 60
    por_categoria: dict = {}
    for p in lista:
        for k, v in (p["custo"].get("por_categoria") or {}).items():
            por_categoria[k] = round(por_categoria.get(k, 0) + v, 4)
    return {"total_usd": round(total, 4), "minutos": round(minutos, 1),
            "por_minuto_usd": round(total / minutos, 4) if minutos else 0, "videos": len(lista),
            "por_categoria": por_categoria, "producoes": lista}


# ---------------------------------------------------------------- administração

@app.get("/api/admin/usuarios")
def admin_usuarios(_: dict = Depends(admin)):
    return [_publico(u) | {"criado": u["criado"]} for u in banco.todos("SELECT * FROM usuarios ORDER BY id DESC")]


@app.post("/api/admin/usuarios/{uid}")
async def admin_salvar(uid: int, request: Request, _: dict = Depends(admin)):
    d = await request.json()
    u = banco.um("SELECT * FROM usuarios WHERE id=?", uid)
    if not u:
        raise HTTPException(404, "Conta não encontrada.")
    plano = d.get("plano", u["plano"])
    if plano and plano not in banco.PLANOS:
        raise HTTPException(400, "Plano desconhecido.")
    vence = str(d.get("vence", u["vence"]) or "")
    if vence and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", vence):
        raise HTTPException(400, "Use a data como AAAA-MM-DD.")
    banco.executar("UPDATE usuarios SET aprovado=?, plano=?, vence=? WHERE id=?",
                   int(bool(d.get("aprovado", u["aprovado"]))), plano, vence, uid)
    return {"ok": True}


# ---------------------------------------------------------------- Kiwify (pagamento)

PLANO_DA_OFERTA = (("anual", "anual"), ("mensal", "mensal"), ("básico", "basico"), ("basico", "basico"))


@app.post("/api/kiwify")
async def kiwify(request: Request):
    """Webhook da Kiwify. Configure na Kiwify a URL /api/kiwify com o token da conta igual a KIWIFY_TOKEN no .env.

    A Kiwify assina o corpo com HMAC-SHA1 do token e manda em ?signature=. Pedido aprovado libera o plano pelo nome
    da oferta; reembolso, chargeback e assinatura cancelada fecham o acesso. Ainda não testado com um pedido real."""
    segredo = os.environ.get("KIWIFY_TOKEN", "")
    corpo = await request.body()
    assinatura = request.query_params.get("signature", "")
    esperada = hmac.new(segredo.encode(), corpo, hashlib.sha1).hexdigest() if segredo else ""
    if not segredo or not hmac.compare_digest(assinatura, esperada):
        raise HTTPException(401, "assinatura inválida")
    d = json.loads(corpo or b"{}")
    email = str((d.get("Customer") or {}).get("email") or "").strip().lower()
    estado = str(d.get("order_status") or d.get("webhook_event_type") or "").lower()
    oferta = " ".join(str(x) for x in ((d.get("Product") or {}).get("product_name"),
                                       (d.get("Subscription") or {}).get("plan", {}).get("name"))).lower()
    u = banco.um("SELECT * FROM usuarios WHERE email=?", email) if email else None
    if not u:
        return {"ok": True, "aviso": "nenhuma conta com esse e-mail; cadastre e aprove à mão"}
    if estado in ("paid", "approved", "order_approved", "subscription_renewed"):
        plano = next((p for termo, p in PLANO_DA_OFERTA if termo in oferta), "mensal")
        dias = 366 if plano == "anual" else 31
        vence = (datetime.now(banco.BRASILIA).date() + timedelta(days=dias)).isoformat()
        banco.executar("UPDATE usuarios SET plano=?, vence=?, aprovado=1 WHERE id=?", plano, vence, u["id"])
    elif estado in ("refunded", "chargedback", "subscription_canceled", "order_refunded", "chargeback"):
        banco.executar("UPDATE usuarios SET vence=? WHERE id=?", banco.hoje_brasilia(), u["id"])
    return {"ok": True}


# ---------------------------------------------------------------- o robô (máquina do cliente)

def maquina(request: Request) -> dict:
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    m = banco.um("SELECT * FROM maquinas WHERE token_hash=?", banco.hash_token(token)) if token else None
    if not m:
        raise HTTPException(401, "Máquina desconectada. Rode o robô de novo e use um código novo.")
    return m


@app.post("/api/robo/parear")
async def parear(request: Request):
    d = await request.json()
    codigo = str(d.get("codigo", "")).strip().upper().replace("-", "").replace(" ", "")
    par = banco.um("SELECT * FROM pareamentos WHERE codigo=?", codigo)
    if not par or datetime.now(timezone.utc) - datetime.fromisoformat(par["criado"]) > timedelta(minutes=15):
        raise HTTPException(400, "Código inválido ou vencido. Gere outro em Máquinas, no painel.")
    banco.executar("DELETE FROM pareamentos WHERE codigo=?", codigo)
    token = banco.novo_token()
    banco.executar("INSERT INTO maquinas (usuario_id, nome, sistema, versao, token_hash, criada, visto_em, pasta_padrao) "
                   "VALUES (?,?,?,?,?,?,?,?)", par["usuario_id"], str(d.get("nome", "Computador"))[:80],
                   str(d.get("sistema", ""))[:80], str(d.get("versao", ""))[:20], banco.hash_token(token), banco.agora(),
                   banco.agora(), str(d.get("pasta_padrao", ""))[:300])
    return {"token": token}


@app.post("/api/robo/ping")
async def ping(request: Request, m: dict = Depends(maquina)):
    """O robô avisa que está vivo, recebe os comandos e, se estiver livre, o próximo vídeo da fila."""
    d = await request.json()
    # o robô diz quantas vagas tem livres (vários vídeos ao mesmo tempo); robô antigo só diz se está ocupado
    livres = d.get("livres")
    livres = int(livres) if isinstance(livres, int) else (0 if d.get("ocupada") else 1)
    produzindo = int(d.get("produzindo") or (1 if d.get("ocupada") else 0))
    banco.executar("UPDATE maquinas SET visto_em=?, ocupada=?, versao=?, pasta_padrao=? WHERE id=?", banco.agora(),
                   produzindo, str(d.get("versao", m["versao"]))[:20],
                   str(d.get("pasta_padrao", m["pasta_padrao"]))[:300], m["id"])
    comandos = banco.todos("SELECT id, tipo, dados FROM comandos WHERE maquina_id=? AND feito=0 ORDER BY id", m["id"])
    for c in comandos:
        c["dados"] = banco.json_de(c["dados"], {})
    banco.executar("UPDATE comandos SET feito=1 WHERE maquina_id=? AND feito=0", m["id"])
    trabalho = None
    if livres > 0:
        dono = banco.um("SELECT * FROM usuarios WHERE id=?", m["usuario_id"])
        p = banco.um("SELECT * FROM producoes WHERE usuario_id=? AND estado='fila' ORDER BY id LIMIT 1", m["usuario_id"])
        try:
            liberado(dono)
        except HTTPException:
            p = None
        if p:
            banco.executar("UPDATE producoes SET estado='produzindo', maquina_id=?, iniciada=?, etapa='Começando', "
                           "progresso=1 WHERE id=? AND estado='fila'", m["id"], banco.agora(), p["id"])
            config = banco.json_de(p["config"], {})
            trabalho = {
                "id": p["id"], "nome": p["nome"], "roteiro": p["roteiro"], "ajustes": config.get("ajustes", {}),
                "fabrica": config.get("fabrica", {}),
                "ambiente": {} if config.get("ajustes", {}).get("teste") else chaves.ambiente_do_usuario(m["usuario_id"]),
            }
    return {"comandos": comandos, "trabalho": trabalho}


@app.post("/api/robo/producoes/{pid}/andamento")
async def andamento(pid: int, request: Request, m: dict = Depends(maquina)):
    d = await request.json()
    p = banco.um("SELECT * FROM producoes WHERE id=? AND maquina_id=?", pid, m["id"])
    if not p:
        raise HTTPException(404, "produção de outra máquina")
    if p["estado"] == "cancelado":
        return {"cancelar": True}
    linhas = (banco.json_de(p["linhas"], []) + [str(x)[:300] for x in d.get("linhas", [])])[-LINHAS_GUARDADAS:]
    banco.executar("UPDATE producoes SET etapa=?, progresso=?, linhas=? WHERE id=?", str(d.get("etapa", p["etapa"]))[:80],
                   max(0, min(99, int(d.get("progresso", p["progresso"])))), json.dumps(linhas, ensure_ascii=False), pid)
    return {"cancelar": False}


@app.post("/api/robo/producoes/{pid}/fim")
async def fim(pid: int, request: Request, m: dict = Depends(maquina)):
    d = await request.json()
    p = banco.um("SELECT * FROM producoes WHERE id=? AND maquina_id=?", pid, m["id"])
    if not p:
        raise HTTPException(404, "produção de outra máquina")
    estado = d.get("estado") if d.get("estado") in ("entregue", "falhou", "atencao", "cancelado") else "falhou"
    if p["estado"] == "cancelado":
        estado = "cancelado"
    custo = d.get("custo") or {}
    linhas = (banco.json_de(p["linhas"], []) + [str(x)[:300] for x in d.get("linhas", [])])[-LINHAS_GUARDADAS:]
    banco.executar("UPDATE producoes SET estado=?, etapa=?, progresso=?, terminada=?, duracao_s=?, custo_usd=?, custo=?, "
                   "arquivo=?, erro=?, linhas=? WHERE id=?", estado,
                   "Entregue" if estado == "entregue" else p["etapa"], 100 if estado == "entregue" else p["progresso"],
                   banco.agora(), float(d.get("duracao_s") or 0),
                   custo.get("total_usd") if isinstance(custo, dict) else None, json.dumps(custo, ensure_ascii=False),
                   str(d.get("arquivo", ""))[:500], str(d.get("erro", ""))[:1000], json.dumps(linhas, ensure_ascii=False),
                   pid)
    return {"ok": True}


# ---------------------------------------------------------------- página

app.mount("/web", StaticFiles(directory=WEB), name="web")


@app.get("/")
@app.get("/{caminho:path}")
def pagina(caminho: str = ""):
    if caminho.startswith("api/"):
        raise HTTPException(404, "não existe")
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})
