"""Servidor MCP da fábrica (teste de 2026-10-06): o Claude Code do cliente manda o roteiro e pensa o vídeo.

`fabrica mcp --porta 8092` sobe o MCP em http://HOST:PORTA/mcp. No Claude Code do cliente:
    claude mcp add --transport http fabrica http://HOST:PORTA/mcp

O ciclo: criar_video (primeiro só a estimativa; com confirmar=true a produção começa), e então o Claude do cliente
pede proximas_tarefas e responde cada uma com responder, até andamento dizer que o vídeo ficou pronto; por fim,
entregar_video manda o pacote do projeto para a pasta do cliente e o servidor fica só com o MP4 (pacote.py).

Cada tarefa é um pedido que a fábrica faria a um modelo de linguagem (cliente.py): o mapa e as cenas do roteiro, a
escolha das fotos pelas miniaturas, a descrição e o julgamento de cada imagem, a trilha, as animações e a revisão do
vídeo pronto. As instruções de uma etapa vão inteiras uma vez por chamada (cada subagente nasce sem a conversa); quem
já tem a marca diz em instrucoes_que_ja_tenho, e ver_instrucoes devolve de novo.

O comando /tiplabs (o arquivo ~/.claude/commands/tiplabs.md que instalar_tiplabs entrega; sem ele, o prompt
"tiplabs" deste servidor, /mcp__fabrica__tiplabs) faz o ciclo inteiro: esperar no servidor, e cada lote de tarefas num
subagente descartável (Opus no roteiro, Sonnet no visual), para o contexto não crescer na conversa do cliente.
"""
import argparse
import base64
import hashlib
import json
import re
import tempfile
import unicodedata
import secrets
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import Image, MCPServer

from . import cli, cliente, clientes_mcp, custos, pacote
from .config import RAIZ, carregar_perfil
from .projeto import PROJETOS, Projeto

INSTRUCOES_DO_SERVIDOR = """Fábrica de vídeos narrados. Você é quem toma as decisões criativas do vídeo; a fábrica faz
narração, busca nos bancos de imagem e render.

O usuário só manda o roteiro e recebe o vídeo: estilo, voz e nome são decididos pela fábrica, e ele não aprova nada.
O jeito certo de produzir é o comando /tiplabs: ele cria o vídeo, responde as tarefas num operador em segundo plano e
mostra ao usuário só a porcentagem (acompanhar), sem o maquinário. Se o usuário ainda não tem o /tiplabs, chame instalar_tiplabs e grave o arquivo
que ela devolve no caminho indicado (uma vez só).

Sem o comando:
1. criar_video(roteiro) começa a produção e devolve o nome do vídeo. Mandar o mesmo roteiro de novo continua o vídeo
   que parou, sem começar outro.
2. Repita esperar(nome) e, quando houver tarefas, proximas_tarefas -> responder cada uma. Cada tarefa traz instruções,
   um pedido (às vezes com imagens) e o esquema JSON da resposta. Responda com um JSON que siga o esquema, com
   exatamente as chaves dele. Siga as instruções à risca: são as regras da fábrica (o que a narração cita tem de
   aparecer, o animal certo, nada de imagem de outra coisa). A produção só anda quando você responde.
3. Quando esperar disser "pronto", chame entregar_video(nome): ele devolve o link do vídeo e o do pacote do projeto
   (o que guarda as decisões e o material pago, para editar depois). Baixe os dois para a pasta atual do usuário."""

servidor = MCPServer("fabrica-de-videos", instructions=INSTRUCOES_DO_SERVIDOR)

_TRAVA = threading.Lock()
_PRODUCOES: dict = {}       # nome -> {"estado", "log", "inicio", "fim", "erro"}
_INSTRUCOES: dict = {}      # marca -> texto das instruções de uma etapa
_local = threading.local()
_NOME_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{2,59}$")
VOZ_FISH_PADRAO = "0ba1afd27db44eb2b4cb27fd331b93aa"  # "Narrador de Histórias e Ciências", a do virou-filme-em-1996
_URL_PUBLICA = ""  # com URL pública, o MCP exige o token de cada cliente (clientes_mcp.py)


def _cliente() -> str:
    """Quem está chamando: o cliente do token, ou "local" no MCP sem URL pública (teste na mesma máquina)."""
    if not _URL_PUBLICA:
        return "local"
    token = get_access_token()
    return token.client_id if token else ""


def _dono(nome: str) -> str:
    for arquivo in (PROJETOS / nome / "projeto.json", pacote.ENTREGAS / nome / "entrega.json"):
        try:
            return json.loads(arquivo.read_text(encoding="utf-8")).get("dono") or ""
        except (OSError, ValueError):
            continue
    return ""


def _e_meu(nome: str) -> bool:
    """O projeto é de quem chama? Um cliente nunca vê, responde nem baixa o projeto de outro."""
    return not _URL_PUBLICA or (bool(nome) and _dono(nome) == _cliente())


NAO_ACHEI = "Projeto não encontrado nesta conta."


class _Opcoes(argparse.Namespace):
    """As opções do `tudo`, como na linha de comando; a que não foi dada vale None."""

    def __getattr__(self, nome):
        return None


def _log_da_producao(mensagem):
    """O log do cli vai também para o andamento da produção da thread que escreveu."""
    nome = getattr(_local, "nome", None)
    if nome and nome in _PRODUCOES:
        with _TRAVA:
            linhas = _PRODUCOES[nome]["log"]
            linhas.append(str(mensagem))
            del linhas[:-200]
    print(mensagem, flush=True)


cli.log = _log_da_producao


# Os perfis que o cliente do MCP pode usar (pedido do usuário em 2026-10-09): o vídeo é feito com banco de imagens e IA,
# e o motion só apoia, nas cenas em que explica melhor o roteiro. Os perfis todo em motion (motion-ai, motion-vox) e os
# canais pessoais ficam fora. Ordem: o primeiro é o padrão.
PERFIS_DO_MCP = ("documentario", "documentario-vox")


def _perfis_do_mcp() -> list:
    from .config import config_geral
    lista = (config_geral().get("mcp") or {}).get("perfis") or PERFIS_DO_MCP
    return [n for n in lista if (RAIZ / "perfis" / f"{n}.yaml").is_file()]


def _escolhas_da_fabrica() -> tuple:
    """O perfil e a voz de todo vídeo do MCP, decididos por quem vende (mcp.perfil e mcp.voz no config.yaml), nunca
    pelo cliente (pedido do usuário em 2026-10-09: "o cliente não deve escolher nada, somente receber o vídeo")."""
    from .config import config_geral
    cfg = config_geral().get("mcp") or {}
    perfis = _perfis_do_mcp()
    perfil = cfg.get("perfil") if cfg.get("perfil") in perfis else (perfis[0] if perfis else "documentario")
    return perfil, str(cfg.get("voz") or "").strip()


def _nome_automatico(roteiro: str) -> str:
    """O nome do vídeo a partir das primeiras palavras do roteiro, com um final que não repete."""
    palavras = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", roteiro.lower()).encode("ascii", "ignore").decode())
    base = "-".join(palavras[:5])[:40].strip("-") or "video"
    return f"{base}-{datetime.now():%m%d}-{secrets.token_hex(2)}"


def _marca_do_roteiro(roteiro: str) -> str:
    return hashlib.sha1(" ".join(roteiro.split()).encode("utf-8")).hexdigest()[:16]


def _video_em_andamento(marca: str) -> str:
    """O vídeo deste cliente com o mesmo roteiro que ainda não foi entregue: mandar o roteiro de novo continua ele."""
    for pasta in sorted(PROJETOS.iterdir(), key=lambda q: q.stat().st_mtime, reverse=True) if PROJETOS.exists() else ():
        try:
            dados = json.loads((pasta / "projeto.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if dados.get("modelo") == "cliente" and dados.get("roteiro_marca") == marca and _e_meu(pasta.name):
            return pasta.name
    return ""


def _perfil(nome_do_perfil: str) -> Path:
    nome = Path(nome_do_perfil or "").stem
    if nome not in _perfis_do_mcp():
        raise ValueError(f"o perfil {nome_do_perfil} não está disponível. Disponíveis: {', '.join(_perfis_do_mcp())}")
    return RAIZ / "perfis" / f"{nome}.yaml"


def _marca(instrucoes: str) -> str:
    return hashlib.sha1(instrucoes.encode("utf-8")).hexdigest()[:8]


def listar_perfis() -> str:
    """Os perfis de canal (a identidade de cada canal: voz, estilo das imagens, regras) disponíveis na fábrica."""
    linhas = []
    for caminho in (RAIZ / "perfis" / f"{n}.yaml" for n in _perfis_do_mcp()):
        try:
            perfil = carregar_perfil(caminho)
        except (Exception, SystemExit):
            continue
        linhas.append(f"- {caminho.stem}: {perfil.get('nome', '')} {perfil.get('descricao', '')}".rstrip())
    return "\n".join(linhas) or "nenhum perfil"


@servidor.tool(structured_output=False)
def criar_video(roteiro: str, nome: str = "", confirmar: bool = True, voz_do_computador: bool = False,
                imagens_de_ia: bool = True, voz: str = "") -> str:
    """Começa o vídeo a partir do roteiro (o texto) e devolve o nome dele, que as outras ferramentas pedem. O estilo, a
    voz e o nome são da fábrica: não pergunte nada ao usuário. Mandar o mesmo roteiro de novo continua o vídeo que
    parou (limite de uso, terminal fechado) em vez de começar outro.

    nome, voz, voz_do_computador, imagens_de_ia e confirmar=false (só a estimativa) são para os testes de quem vende,
    na própria máquina; pela internet eles são ignorados."""
    roteiro = roteiro or ""
    perfil, voz_da_fabrica = _escolhas_da_fabrica()
    if _URL_PUBLICA:
        nome, voz, voz_do_computador, imagens_de_ia, confirmar = "", "", False, True, True
    voz = (voz or "").strip() or voz_da_fabrica
    if voz and not re.fullmatch(r"fish(:[0-9a-f]{32})?", voz):
        return 'Voz inválida: use "fish" ou "fish:CODIGO_DA_VOZ" (32 letras e números), ou deixe vazio.'
    if not nome:
        if not roteiro.strip():
            return "O roteiro está vazio."
        nome = _video_em_andamento(_marca_do_roteiro(roteiro)) or _nome_automatico(roteiro)
    if not _NOME_VALIDO.match(nome):
        return "Nome inválido: use de 3 a 60 letras minúsculas, números e hífen (ex.: animais-perigosos-1)."
    if ((PROJETOS / nome).exists() or (pacote.ENTREGAS / nome).exists()) and not _e_meu(nome):
        return f"Já existe um vídeo chamado {nome}. Escolha outro nome."
    if not (PROJETOS / nome).exists():
        if not roteiro.strip():
            return "O roteiro está vazio."
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "roteiro.txt"
            arquivo.write_text(roteiro, encoding="utf-8")
            p = Projeto.criar(nome, str(arquivo), str(_perfil(perfil)), offline=False)
        p.dados["modelo"] = "cliente"
        p.dados["dono"] = _cliente()
        p.dados["roteiro_marca"] = _marca_do_roteiro(roteiro)
        if voz_do_computador:
            p.dados["voz_override"] = {"provedor": "computador"}
        elif voz:
            p.dados["voz_override"] = {"provedor": "fish", "voice_id": voz.partition(":")[2] or VOZ_FISH_PADRAO,
                                       "idioma": "pt", "velocidade": 1.0}
        if not imagens_de_ia:
            p.dados["config_override"] = {"ia": {"ativa": False}}
        p.salvar_json("projeto.json", p.dados)
    p = Projeto(nome)
    if not cliente.ativo(p):
        return f"O projeto {nome} já existe e não é um projeto do MCP. Escolha outro nome."
    if not confirmar:
        return (custos.formatar(custos.estimar(p)) + f"\n\nNada foi gasto. Nome do vídeo: {nome}. Para começar, "
                f"chame criar_video(roteiro='', nome='{nome}', confirmar=true).")
    if (_PRODUCOES.get(nome) or {}).get("estado") == "produzindo":
        return f"{nome} já está em produção. NOME: {nome}."
    if _URL_PUBLICA and not p.dados.get("producao_contada"):
        # o limite de vídeos por dia conta o vídeo começado; retomar o mesmo vídeo depois de uma queda não conta de novo
        motivo = clientes_mcp.pode_comecar(_cliente())
        if motivo:
            return f"Não posso começar: {motivo}"
        clientes_mcp.registrar_producao(_cliente(), nome)
        p.dados["producao_contada"] = True
        p.salvar_json("projeto.json", p.dados)
    with _TRAVA:
        if (_PRODUCOES.get(nome) or {}).get("estado") == "produzindo":
            return f"{nome} já está em produção. Siga com esperar('{nome}')."
        _PRODUCOES[nome] = {"estado": "produzindo", "log": [], "inicio": datetime.now().isoformat(timespec="seconds"),
                            "fim": None, "erro": None}
    threading.Thread(target=_produzir, args=(nome,), daemon=True, name=f"producao-{nome}").start()
    return f"Vídeo começou. NOME: {nome} (as outras ferramentas pedem este nome)."


def _produzir(nome):
    _local.nome = nome
    try:
        cli.cmd_tudo(_Opcoes(nome=nome, sim=True))
        estado, erro = "pronto", None
    except cliente.Cancelada:
        estado, erro = "cancelado", None
    except BaseException as e:  # SystemExit da fábrica também para a produção, com o motivo
        estado, erro = "erro", f"{e}\n{traceback.format_exc()[-1500:]}"
    with _TRAVA:
        _PRODUCOES[nome].update(estado=estado, erro=erro, fim=datetime.now().isoformat(timespec="seconds"))


def _minutos(segundos: float) -> str:
    segundos = int(max(0, segundos))
    return f"{segundos // 3600}h{segundos % 3600 // 60:02d}" if segundos >= 3600 else f"{segundos // 60}min{segundos % 60:02d}s"


@servidor.tool(structured_output=False)
def andamento(nome: str) -> str:
    """Em que pé está a produção: estado (produzindo, pronto, erro, cancelado), tarefas esperando você e as últimas
    linhas do que a fábrica fez."""
    if not _e_meu(nome):
        return NAO_ACHEI
    with _TRAVA:
        prod = dict(_PRODUCOES.get(nome) or {})
        linhas = list(prod.get("log") or [])[-12:]
    if not prod:
        pronto = (PROJETOS / nome / "final.mp4").exists() or (pacote.ENTREGAS / nome / "final.mp4").exists()
        return f"{nome}: {'pronto' if pronto else 'sem produção em andamento neste servidor'}."
    m = cliente.medidas(nome)
    inicio = datetime.fromisoformat(prod["inicio"])
    fim = datetime.fromisoformat(prod["fim"]) if prod.get("fim") else datetime.now()
    total = (fim - inicio).total_seconds()
    estado = prod["estado"]
    if estado == "produzindo" and m["esperando_agora"]:
        estado = f"esperando você há {_minutos(m['esperando_agora'])} ({cliente.pendentes(nome)} tarefa(s) na fila)"
        if m.get("pausado"):
            estado += (f". PAUSADO: você parou com {m['pausado']['feito']:.0%} do vídeo feito (a fábrica só segue "
                       "sozinha a partir de 60%). Quando o limite do seu Claude voltar, rode /tiplabs de novo com o "
                       "mesmo nome")
    elif estado == "produzindo":
        estado = "a fábrica está trabalhando (narração, downloads ou render)"
    if m.get("reserva"):
        estado += ". A fábrica está terminando sozinha as tarefas visuais (você parou depois de 60% do vídeo)"
    texto = [f"{nome}: {estado}",
             f"Tempo desde o início: {_minutos(total)}; a fábrica trabalhou {_minutos(total - m['espera'])} e esperou "
             f"você {_minutos(m['espera'])}.",
             f"Tarefas até agora: {m['tarefas']} ({m['imagens']} imagens): "
             + ", ".join(f"{etapa} {v['tarefas']}" for etapa, v in m["por_etapa"].items())]
    if prod.get("erro"):
        texto.append("Erro: " + prod["erro"][:1500])
    texto.append("Últimas linhas:\n" + "\n".join(linhas))
    return "\n".join(texto)


def _estado_curto(nome: str) -> str:
    """Uma linha: pronto, erro, cancelado, as tarefas esperando por grupo, ou a fábrica trabalhando."""
    with _TRAVA:
        prod = dict(_PRODUCOES.get(nome) or {})
    if not prod:
        pronto = (PROJETOS / nome / "final.mp4").exists() or (pacote.ENTREGAS / nome / "final.mp4").exists()
        return "pronto" if pronto else "sem produção"
    if prod["estado"] != "produzindo":
        return prod["estado"] + (f": {prod['erro'][:600]}" if prod.get("erro") else "")
    roteiro = cliente.pendentes(nome, cliente.ROTEIRO, livres=True)
    visual = cliente.pendentes(nome, cliente.VISUAL, livres=True)
    if roteiro or visual:
        return f"tarefas: roteiro {roteiro}, visual {visual}"
    if cliente.pendentes(nome):
        return "tarefas já entregues, esperando as respostas"
    return "trabalhando"


def _tempo_de_producao(nome: str) -> str:
    """Quanto tempo o vídeo já leva sendo produzido, do começo da produção até agora (ou até o fim)."""
    with _TRAVA:
        prod = dict(_PRODUCOES.get(nome) or {})
    if not prod.get("inicio"):
        return ""
    fim = datetime.fromisoformat(prod["fim"]) if prod.get("fim") else datetime.now()
    segundos = int(max(0, (fim - datetime.fromisoformat(prod["inicio"])).total_seconds()))
    return f"{segundos // 3600}h{segundos % 3600 // 60:02d}min" if segundos >= 3600 else f"{segundos // 60}min{segundos % 60:02d}s"


def _linha_de_progresso(e: dict, tempo: str = "") -> str:
    tempo = f" · {tempo}" if tempo else ""
    if e["estado"] == "pronto":
        return f"PRONTO · 100%{tempo}"
    if e["estado"] in ("erro", "cancelado", "desconhecido"):
        return f"PAROU · {e['frase']}"
    if e["estado"] == "pausado":
        return f"PAUSADO · {e['frase']}"
    return f"{e['titulo']} · {e['porcentagem']}% (etapa {e['etapa']} de {e['total']}){tempo}"


@servidor.tool(structured_output=False)
def acompanhar(nome: str, ultima: int = -1, segundos: int = 50) -> str:
    """O andamento do vídeo para mostrar ao usuário, numa linha pronta, com o tempo real de produção até agora:
    "Escolhendo as imagens · 45% (etapa 4 de 7) · 6min12s", "PRONTO · 100% · 18min40s", "PAUSADO · ..." ou "PAROU · ...". Espera no servidor (até `segundos`, no máximo 55) o andamento
    avançar desde a porcentagem `ultima` que você já mostrou: uma etapa nova ou 5% a mais. Se nada mudou, devolve
    "SEM MUDANÇA" e não há nada a mostrar."""
    if not _e_meu(nome):
        return NAO_ACHEI
    fim = time.time() + max(1, min(int(segundos), 55))
    inicio = progresso(nome)
    while True:
        e = progresso(nome)
        mudou = (e["estado"] != "produzindo" or e["porcentagem"] >= ultima + 5 or e["etapa"] != inicio["etapa"]
                 or ultima < 0)
        if mudou:
            return _linha_de_progresso(e, _tempo_de_producao(nome))
        if time.time() >= fim:
            return "SEM MUDANÇA"
        time.sleep(2)


@servidor.tool(structured_output=False)
def esperar(nome: str, segundos: int = 50) -> str:
    """Espera (até `segundos`, no máximo 55) a fábrica precisar de você ou terminar, e devolve uma linha: "pronto",
    "erro: ...", "cancelado", "tarefas: roteiro N, visual M" ou "trabalhando" (chame de novo). Use no lugar de dormir
    e de chamar andamento em ciclo: não gasta nada enquanto espera."""
    if not _e_meu(nome):
        return NAO_ACHEI
    fim = time.time() + max(1, min(int(segundos), 55))
    while True:
        estado = _estado_curto(nome)
        if estado != "trabalhando" or time.time() >= fim:
            return estado
        time.sleep(2)


@servidor.tool(structured_output=False)
def proximas_tarefas(limite: int = 3, nome: str = "", tipo: str = "", instrucoes_que_ja_tenho: str = "") -> list:
    """As próximas decisões que a fábrica espera de você (até `limite`, no máximo 8). Responda cada uma com
    responder(tarefa_id, resposta_json). Uma tarefa entregue e não respondida em 15 minutos volta para a fila.

    tipo: "roteiro" (mapa e cenas do roteiro), "visual" (fotos, conferência, revisão, animação, trilha) ou vazio
    para todas. instrucoes_que_ja_tenho: as marcas (separadas por vírgula) das instruções que você já recebeu nesta
    conversa; as dessas etapas não vêm de novo. Sem elas, cada etapa vem com as instruções inteiras uma vez."""
    if _URL_PUBLICA and not nome:
        return "Diga o nome do vídeo: proximas_tarefas(nome='...')."
    if nome and not _e_meu(nome):
        return NAO_ACHEI
    tarefas = cliente.proximas(nome or None, max(1, min(limite, 8)), tipo=(tipo or "").strip().lower() or None)
    if not tarefas:
        with _TRAVA:
            produzindo = [n for n, p in _PRODUCOES.items() if p["estado"] == "produzindo"]
        if produzindo:
            return (f"Nenhuma tarefa agora: a fábrica está trabalhando em {', '.join(produzindo)} (narração, downloads "
                    "ou render). Espere uns 20 segundos e chame de novo.")
        return "Nenhuma tarefa e nenhuma produção em andamento."
    # as instruções vão inteiras uma vez por chamada, a não ser que quem pede diga que já tem: cada subagente do
    # comando nasce sem a conversa, e o "já entregue" global de antes deixava o segundo subagente sem as regras
    ja_tenho = {m.strip() for m in (instrucoes_que_ja_tenho or "").split(",") if m.strip()}
    saida = []
    for t in tarefas:
        marca = _marca(t["instrucoes"])
        with _TRAVA:
            _INSTRUCOES[marca] = t["instrucoes"]
        primeira = marca not in ja_tenho
        ja_tenho.add(marca)
        instrucoes = (t["instrucoes"] if primeira else
                      f"(as mesmas da etapa '{t['etapa']}', marca {marca}; ver_instrucoes('{marca}') mostra de novo)")
        saida.append(
            f"=== TAREFA {t['id']} | projeto {t['projeto']} | etapa: {t['etapa']}\n"
            f"--- INSTRUÇÕES (marca {marca}):\n{instrucoes}\n"
            f"--- ESQUEMA DA RESPOSTA (JSON):\n{json.dumps(t['esquema'], ensure_ascii=False)}\n"
            f"--- PEDIDO:\n{t['pedido']}\n"
            + (f"--- {len(t['imagens'])} IMAGEM(NS) A SEGUIR, na ordem [imagem 1], [imagem 2]...\n" if t["imagens"] else ""))
        for figura in t["imagens"]:
            saida.append(Image(data=base64.standard_b64decode(figura["dados"]), format=figura["mime"].split("/")[-1]))
    return saida


@servidor.tool(structured_output=False)
def responder(tarefa_id: str, resposta_json: str) -> str:
    """Entrega a sua resposta a uma tarefa: um JSON que siga o esquema dela, com todas as chaves obrigatórias."""
    if not _e_meu(cliente.projeto_da_tarefa(tarefa_id) or ""):
        return f"Recusada: a tarefa {tarefa_id} não existe ou já foi respondida."
    r = cliente.responder(tarefa_id, resposta_json)
    return "ok" if r["ok"] else f"Recusada: {r['erro']}. Corrija e responda de novo a mesma tarefa."


@servidor.tool(structured_output=False)
def ver_instrucoes(marca: str) -> str:
    """As instruções completas de uma etapa, pela marca que aparece nas tarefas."""
    return _INSTRUCOES.get(marca) or f"Não conheço a marca {marca}."


@servidor.tool(structured_output=False)
def entregar_video(nome: str, pasta_do_cliente: str = "") -> str:
    """Fim da produção: devolve o link do vídeo (MP4) e o do pacote do projeto (o que custa refazer: as decisões e o
    material pago, para editar depois). Baixe os dois para a pasta do usuário. Os links valem 7 dias."""
    if not _e_meu(nome):
        return NAO_ACHEI
    destino = pacote.ENTREGAS / nome
    local = not _URL_PUBLICA and pasta_do_cliente
    if (PROJETOS / nome).exists():
        r = pacote.entregar(Projeto(nome), Path(pasta_do_cliente) if local else destino, log=lambda *_: None)
        info = json.loads((destino / "entrega.json").read_text(encoding="utf-8"))
        info["dono"] = _cliente()
        (destino / "entrega.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        if local:
            return (f"Entregue. Pacote do projeto: {r['pacote']} ({r['pacote_mb']} MB; o projeto tinha "
                    f"{r['projeto_mb']} MB). Vídeo: {r['video']}")
    if not (destino / "final.mp4").exists():
        return f"{nome} ainda não tem o vídeo pronto."
    base = (_URL_PUBLICA or "http://127.0.0.1:8092").rstrip("/") + "/baixar/"
    linhas = [f"Vídeo: {base}{clientes_mcp.link(destino / 'final.mp4', _cliente())}"]
    zip_ = destino / f"{nome}.zip"
    if zip_.exists():
        linhas.append(f"Pacote do projeto ({zip_.stat().st_size / 1e6:.0f} MB): "
                      f"{base}{clientes_mcp.link(zip_, _cliente())}")
    return ("\n".join(linhas) + "\nBaixe os dois para a pasta atual do usuário (por exemplo, curl -L -o ARQUIVO LINK). "
            "Os links valem 7 dias.")


@servidor.tool(structured_output=False)
def importar_pacote(caminho_do_pacote: str, nome: str = "") -> str:
    """Devolve à fábrica um projeto entregue antes (o .zip do pacote), para editar e renderizar de novo, sem gastar."""
    if _URL_PUBLICA:
        return "Indisponível pela internet nesta versão: o envio do pacote ainda não existe."
    p = pacote.importar(Path(caminho_do_pacote), nome=nome or None, log=lambda *_: None)
    return f"Projeto {p.nome} de volta à fábrica, pronto para editar e renderizar."


@servidor.tool(structured_output=False)
def cancelar(nome: str) -> str:
    """Para a produção do projeto (as tarefas esperando resposta são soltas)."""
    if not _e_meu(nome):
        return NAO_ACHEI
    soltas = cliente.cancelar(nome)
    return f"Cancelado: {soltas} tarefa(s) soltas. O que já foi feito fica salvo."


AJUDANTE = """Você é o operador da fábrica de vídeos TipLabs (ferramentas do MCP fabrica) no vídeo {nome}. Trabalhe em
silêncio até o vídeo ficar pronto: não escreva nada para o usuário no caminho.

Repita:
1. esperar(nome="{nome}"). Ele devolve uma linha:
   - "trabalhando" ou "tarefas já entregues": chame esperar de novo.
   - "tarefas: ...": chame proximas_tarefas(nome="{nome}", limite=3, instrucoes_que_ja_tenho="<as marcas das
     instruções que você já recebeu, separadas por vírgula>") e responda cada tarefa com responder(tarefa_id,
     resposta_json): um JSON só com as chaves do esquema dela, seguindo as instruções à risca. Se for recusada,
     corrija e responda de novo. Decida direto: as instruções já dizem como julgar, não delibere longamente nem reveja
     a resposta. Depois volte ao passo 1.
   - "pronto", "erro ..." ou "cancelado": pare.
2. No fim, devolva uma linha só: a última linha do esperar ("pronto", "erro ..." ou "cancelado")."""

COMANDO = """Produza um vídeo com a fábrica TipLabs (MCP fabrica). O usuário só mandou o roteiro e quer receber o vídeo:
não mostre a ele ferramentas, tarefas nem detalhes técnicos, e não pergunte nada.
{argumentos}

1. Se o roteiro acima for o caminho de um arquivo, leia o arquivo; senão ele é o próprio texto. Chame
   criar_video(roteiro=<o texto>) e guarde o NOME que ele devolve. Se o mesmo roteiro já estava em produção, ele
   devolve o mesmo nome e o vídeo continua de onde parou.
2. Diga ao usuário só: "Seu vídeo está sendo produzido. Vou mostrando o andamento aqui."
3. Lance UM subagente com a ferramenta Agent (subagent_type "general-purpose", model "sonnet",
   run_in_background true, description "Produzindo o vídeo") com o texto OPERADOR abaixo, trocando o nome. Não
   responda tarefa nesta conversa e não chame esperar, andamento nem proximas_tarefas aqui: o operador faz tudo.
4. Enquanto o operador trabalha, repita acompanhar(nome, ultima=<a última porcentagem que você mostrou, ou -1 na
   primeira vez>):
   - "SEM MUDANÇA": chame de novo, sem escrever nada.
   - Uma linha de andamento ("Escolhendo as imagens · 45% (etapa 4 de 7) · 6min12s"): mostre ao usuário exatamente essa linha,
     sozinha, sem comentário, e chame de novo com a porcentagem nova.
   - "PRONTO · 100% · <tempo>": guarde o tempo e siga para o passo 5.
   - "PAUSADO · ..." ou "PAROU · ...": mostre a frase ao usuário e pare.
5. Quando estiver pronto (o acompanhar disse PRONTO ou o operador terminou com "pronto"): chame entregar_video(nome),
   baixe o vídeo e o pacote do projeto para a pasta atual (curl -L -o ARQUIVO LINK) e diga ao usuário, em uma ou duas
   linhas, que o vídeo está pronto, em quanto tempo foi produzido e onde ficou o arquivo. Se o operador terminar com "erro" ou "cancelado": diga,
   numa linha, que a produção parou e que basta mandar o mesmo roteiro de novo com /tiplabs para continuar.

OPERADOR:
{ajudante}"""


def texto_do_comando(roteiro="") -> str:
    """O texto do /tiplabs. Sem argumentos, é o do arquivo de comando, que recebe $ARGUMENTS do Claude Code."""
    if roteiro:
        argumentos = f"Roteiro: {roteiro}"
    else:
        argumentos = ("Roteiro: $ARGUMENTS\n(o caminho de um arquivo de texto ou o próprio texto do roteiro; se vier "
                      "vazio, peça só o roteiro ao usuário)")
    return COMANDO.format(argumentos=argumentos, ajudante=AJUDANTE.format(nome="<o nome que o criar_video devolveu>"))


# model: sonnet. Quem coordena só espera a fábrica e lança subagentes: no teste do ouro-serra-1min o coordenador no
# Opus custou US$ 0,83 (equivalente em API) de US$ 2,22 sem tomar nenhuma decisão do vídeo
ARQUIVO_DO_COMANDO = """---
description: Produz um vídeo narrado com a fábrica TipLabs, do roteiro ao MP4
argument-hint: <roteiro.txt ou o texto do roteiro>
model: sonnet
---
{texto}
"""


@servidor.prompt(name="tiplabs", title="TipLabs: produzir um vídeo",
                 description="Produz o vídeo do roteiro até o fim, com as tarefas em subagentes (Opus no roteiro, "
                             "Sonnet nas imagens). Argumento: o roteiro (arquivo ou texto).")
def comando_tiplabs(roteiro: str) -> str:
    return texto_do_comando(roteiro)


@servidor.tool(structured_output=False)
def instalar_tiplabs() -> str:
    """O arquivo do comando /tiplabs para o Claude Code do usuário. Grave o conteúdo devolvido, exatamente como está,
    em ~/.claude/commands/tiplabs.md (na pasta do usuário; crie a pasta se faltar). Depois disso o usuário produz um
    vídeo com /tiplabs roteiro.txt."""
    return ("Grave o texto entre as linhas ===== em ~/.claude/commands/tiplabs.md, sem mudar nada:\n=====\n"
            + ARQUIVO_DO_COMANDO.format(texto=texto_do_comando()) + "=====")


# A produção em macro-etapas, na linguagem de quem faz vídeo (pedido do usuário em 2026-10-09: o cliente não vê o
# maquinário, só o andamento, dentro do próprio Claude Code, pela ferramenta acompanhar). Cada etapa começa quando a fábrica escreve um destes títulos no log; a narração e a
# leitura do roteiro correm juntas, e vale a etapa mais adiantada.
ETAPAS = (
    ("Lendo o roteiro", ("Mapa do roteiro", "JSON de cenas")),
    ("Gravando a narração", ("Narração",)),
    ("Dividindo em cenas", ("Cenas",)),
    ("Escolhendo as imagens", ("Material real", "Conferindo", "Imagens de IA", "Motion em todas", "Motion onde ajuda")),
    ("Criando animações e trilha", ("Efeitos sonoros", "Animações", "Trilha")),
    ("Montando o vídeo", ("Render",)),
    ("Revisão final", ("Revisão do vídeo pronto",)),
)
def _video_pronto(nome: str):
    for caminho in (pacote.ENTREGAS / nome / "final.mp4", PROJETOS / nome / "final.mp4"):
        if caminho.is_file():
            return caminho
    return None


def progresso(nome: str) -> dict:
    """O andamento em linguagem de produção: a etapa, quantas são, a porcentagem e uma frase."""
    with _TRAVA:
        prod = dict(_PRODUCOES.get(nome) or {})
        linhas = list(prod.get("log") or [])
    total = len(ETAPAS)
    if prod.get("estado") == "pronto" or (not prod and _video_pronto(nome)):
        return {"estado": "pronto", "etapa": total, "total": total, "titulo": "Vídeo pronto", "porcentagem": 100,
                "frase": "Seu vídeo está pronto e chegando na sua pasta."}
    if prod.get("estado") in ("erro", "cancelado"):
        return {"estado": prod["estado"], "etapa": 0, "total": total, "titulo": "Produção interrompida",
                "porcentagem": 0, "frase": "A produção parou. Mande o mesmo roteiro de novo para continuar."}
    if not prod:
        return {"estado": "desconhecido", "etapa": 0, "total": total, "titulo": "Aguardando", "porcentagem": 0,
                "frase": "Este vídeo não está em produção agora. Mande o roteiro de novo para continuar."}
    etapa = 0
    for linha in linhas:
        texto = str(linha).strip()
        for i, (_, titulos) in enumerate(ETAPAS):
            if any(texto.startswith(t) for t in titulos):
                etapa = max(etapa, i)
    # dentro da etapa: o andamento do render ("clipes 10/16") ou o de quem está escolhendo as imagens
    dentro = 0.0
    for linha in reversed(linhas):
        achado = re.search(r"(?:clipes|imagens|revisadas)\s+(\d+)\s*(?:/|de)\s*(\d+)", str(linha))
        if achado and int(achado.group(2)):
            dentro = min(1.0, int(achado.group(1)) / int(achado.group(2)))
            break
    porcentagem = int(100 * (etapa + dentro * 0.95) / total)
    m = cliente.medidas(nome)
    titulo = ETAPAS[etapa][0]
    if m.get("pausado"):
        return {"estado": "pausado", "etapa": etapa + 1, "total": total, "titulo": titulo, "porcentagem": porcentagem,
                "frase": "Pausado: o limite de uso do seu Claude acabou. Quando ele voltar, mande o mesmo roteiro de "
                         "novo com /tiplabs e o vídeo continua daqui."}
    return {"estado": "produzindo", "etapa": etapa + 1, "total": total, "titulo": titulo, "porcentagem": porcentagem,
            "frase": f"{titulo}…"}


class _Verificador:
    """Confere o token de cada chamada (cabeçalho Authorization: Bearer). O client_id é o nome do cliente."""

    async def verify_token(self, token: str):
        nome = clientes_mcp.quem(token)
        return AccessToken(token=token, client_id=nome, scopes=[]) if nome else None


@servidor.custom_route("/baixar/{codigo}/{arquivo}", methods=["GET"])
async def baixar(request):
    """O download do vídeo e do pacote: o código do link é o segredo (o curl não manda o token)."""
    from starlette.responses import FileResponse, PlainTextResponse

    caminho = clientes_mcp.arquivo_do_link(request.path_params["codigo"], request.path_params["arquivo"])
    if caminho is None:
        return PlainTextResponse("Link inválido ou vencido.", status_code=404)
    return FileResponse(caminho, filename=caminho.name)


def rodar(host="127.0.0.1", porta=8092, url_publica=""):
    """Sem url_publica, o MCP de teste na mesma máquina, sem senha. Com ela (https://mcp.exemplo.com), cada chamada
    precisa do token de um cliente (fabrica mcp-cliente criar NOME), e só o Host da URL é aceito."""
    global _URL_PUBLICA
    if not url_publica:
        servidor.run(transport="streamable-http", host=host, port=porta)
        return
    from urllib.parse import urlparse

    import uvicorn
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.transport_security import TransportSecuritySettings

    _URL_PUBLICA = url_publica.rstrip("/")
    # o token é nosso (não vem de um servidor OAuth), então não há "resource" para conferir nele
    servidor.settings.auth = AuthSettings(issuer_url=_URL_PUBLICA, resource_server_url=f"{_URL_PUBLICA}/mcp",
                                          validate_token_resource=False)
    servidor._token_verifier = _Verificador()
    publico = urlparse(_URL_PUBLICA).netloc
    app = servidor.streamable_http_app(host=host, transport_security=TransportSecuritySettings(
        allowed_hosts=[publico, f"127.0.0.1:{porta}", f"localhost:{porta}"],
        allowed_origins=[_URL_PUBLICA, f"http://127.0.0.1:{porta}", f"http://localhost:{porta}"]))
    uvicorn.run(app, host=host, port=porta, log_level="info")
