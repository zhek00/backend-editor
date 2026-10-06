"""
API HTTP REST da Fábrica de Vídeos (FastAPI).
Permite integrar a fábrica com qualquer frontend web para trocar cenas,
regerar imagens de IA, buscar material de acervo, fazer upload manual e refazer áudio.
"""

import asyncio
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as EsperaEsgotada
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import animacoes, aprendizados, cenas, corrigir, diretor, fish, pago, qualidade, rostos, revisao_video, trilha, custos, custos_reais, genaipro, imagens, limpeza, midia, narracao, nichos, render, roteirista, verificar
from . import texto as tx
from . import youtube_publicar as ytpub
from .config import RAIZ, carregar_perfil, config_geral
from .projeto import PROJETOS, Projeto

# -----------------------------------------------------------------------------
# Adaptações para compatibilidade com o Projeto canônico de fabrica-para-amigo
# -----------------------------------------------------------------------------

def _definir_override(self, secao: str, ajustes: dict) -> None:
    limpo = {k: v for k, v in ajustes.items() if v is not None}
    if not limpo:
        return
    chave = f"{secao}_override"
    self.dados[chave] = {**(self.dados.get(chave) or {}), **limpo}
    arquivo = self.pasta / "projeto.json"
    arquivo.write_text(json.dumps(self.dados, ensure_ascii=False, indent=2), encoding="utf-8")
    self.perfil[secao] = {**(self.perfil.get(secao) or {}), **limpo}

def _definir_voz_override(self, ajustes: dict) -> None:
    self.definir_override("voz", ajustes)

def _definir_imagens_override(self, ajustes: dict) -> None:
    self.definir_override("imagens", ajustes)

if not hasattr(Projeto, "definir_override"):
    Projeto.definir_override = _definir_override
if not hasattr(Projeto, "definir_voz_override"):
    Projeto.definir_voz_override = _definir_voz_override
if not hasattr(Projeto, "definir_imagens_override"):
    Projeto.definir_imagens_override = _definir_imagens_override

_orig_projeto_init = Projeto.__init__
def _projeto_init_overrides(self, nome: str):
    _orig_projeto_init(self, nome)
    for secao in ("voz", "imagens"):
        override = self.dados.get(f"{secao}_override")
        if override:
            self.perfil[secao] = {**(self.perfil.get(secao) or {}), **override}
Projeto.__init__ = _projeto_init_overrides

IDIOMAS_VOZ = getattr(narracao, "IDIOMAS_VOZ", [
    {"id": "pt", "nome": "Português", "bandeira": "🇧🇷"},
    {"id": "es", "nome": "Español", "bandeira": "🇪🇸"},
    {"id": "en", "nome": "English", "bandeira": "🇺🇸"},
])

# Os quatro modelos que a GenAIPro aceita. Todos gastam 1 crédito por caractere (medido em 30/09/2026),
# então o que muda entre eles é só o jeito de falar.
MODELOS_NARRACAO = [
    {"id": "eleven_multilingual_v2", "nome": "Multilingual v2",
     "descricao": "o mais natural e estável para narração longa", "recomendado": True},
    {"id": "eleven_v3", "nome": "Eleven v3",
     "descricao": "o mais expressivo e dramático, aceita tags como [whispers]; ignora a velocidade", "recomendado": False},
    {"id": "eleven_turbo_v2_5", "nome": "Turbo v2.5",
     "descricao": "mais rápido de gerar, quase tão natural quanto o v2", "recomendado": False},
    {"id": "eleven_flash_v2_5", "nome": "Flash v2.5",
     "descricao": "o mais rápido de gerar, um pouco menos natural", "recomendado": False},
]

MODELO_GOOGLE = getattr(imagens, "MODELO_GOOGLE", "gemini-3.1-flash-lite-image")
MODELO_KIE = getattr(imagens, "MODELO_KIE", "grok-imagine-image-2-0/text-to-image")
MODELO_OPENROUTER_IMAGEM = getattr(imagens, "MODELO_OPENROUTER", "openai/gpt-5.4-image-2")
PROVEDORES_IMAGEM = {"google": MODELO_GOOGLE, "kie": MODELO_KIE, "openrouter": MODELO_OPENROUTER_IMAGEM}

def _frame_do_video(video: Path, saida: Path, tempo: float = 0.5):
    cmd = ["ffmpeg", "-y", "-ss", str(tempo), "-i", str(video), "-vframes", "1", "-q:v", "2", str(saida)]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


app = FastAPI(
    title="Fábrica de Vídeos API",
    description="API HTTP para controle e edição de projetos de vídeo",
    version="0.1.0"
)

# Habilita CORS completo para qualquer frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


@app.middleware("http")
async def exigir_token(request: Request, call_next):
    """Tranca a API com FABRICA_TOKEN, sempre — local ou exposta na internet.

    Sem isso, qualquer um que alcançasse o endereço (nem precisa ser pela
    internet: a mesma rede Wi-Fi já bastaria) poderia apagar projetos, gastar
    as chaves pagas e até gravar chaves novas no .env. O front-end (painel)
    só mostra e esconde telas; quem decide se o token vale é sempre este
    middleware, nunca o que o navegador diz que já validou.

    garantir_token() já garante que FABRICA_TOKEN sempre existe no .env a
    partir do primeiro boot da fábrica, então esperado nunca vem vazio aqui.

    O token vai no cabeçalho X-Fabrica-Token. Imagem, áudio e vídeo são
    carregados pelo próprio navegador em <img> e <video>, que não mandam
    cabeçalho, então nesses casos ele também vale como ?token= na URL."""
    esperado = os.environ.get("FABRICA_TOKEN", "").strip()
    caminho = request.url.path
    # o Google chama essa de volta depois do login, sem como mandar nosso token —
    # quem protege essa rota é o "code" de uso único que só o Google emite, não o token
    protegido = (caminho.startswith("/api/") or caminho.startswith("/arquivos")) and caminho != "/api/youtube/oauth/callback"

    # o navegador manda a consulta de permissão (preflight) sem cabeçalho nenhum
    if esperado and protegido and request.method != "OPTIONS":
        recebido = (request.headers.get("x-fabrica-token") or request.query_params.get("token") or "").strip()
        if recebido:
            if not secrets.compare_digest(recebido, esperado):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Token inválido. Configure a conexão com a fábrica no painel."},
                    headers={"Access-Control-Allow-Origin": request.headers.get("origin", "*")},
                )
        else:
            # Sem token: permite health check local do server.py (127.0.0.1) em /api/projetos
            cliente_ip = request.client.host if request.client else ""
            if cliente_ip in ("127.0.0.1", "::1", "localhost", "testclient") and caminho == "/api/projetos":
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"detail": "Token inválido ou ausente. Configure a conexão com a fábrica no painel."},
                headers={"Access-Control-Allow-Origin": request.headers.get("origin", "*")},
            )

    return await call_next(request)

# Estado em memória de tarefas de renderização e processamento
TAREFAS: Dict[str, Dict[str, Any]] = {}
TAREFAS_LOCK = threading.Lock()


# -----------------------------------------------------------------------------
# Esteira de criação: do roteiro até todas as cenas com imagem, sem parar no meio
# -----------------------------------------------------------------------------
# O andamento fica gravado em projetos/NOME/criacao.json. Se a fábrica reiniciar, a criação
# volta sozinha de onde parou (cada etapa já guarda o que fez, então nada é pago de novo).
# Nada fica esperando cota: Groq e Gemini sem cota passam a vez na hora para o MiMo (groq_local e
# gemini_local). Uma falha que sobrar tenta de novo em segundos, e a etapa continua de onde parou.
# Só para de verdade com erro que precisa da pessoa (chave errada, crédito acabou).

ARQ_CRIACAO = "criacao.json"
CRIACOES_ATIVAS: set = set()
TENTATIVAS_POR_ETAPA = 6              # falha que não é de chave: tenta de novo em segundos antes de desistir
RODADAS_PARA_COMPLETAR = 3

# erros que esperar não resolve: a pessoa precisa mexer em chave, crédito ou configuração
_ERRO_PERMANENTE = re.compile(
    r"inválid|recusou a chave|foi recusada|pediu uma chave|falta a chave|falta a \w+_key|acabou o crédito|"
    r"adicione saldo|saldo de créditos insuficiente|credits insufficient|não achei o claude|não está conectado|defina voz|está vazio|só aceita|desconhecid|herda de",
    re.I)
_ESPERAS = [5, 10, 20, 30, 45, 60]   # segundos: parado é pior, então nunca espera muito


class ParadaPrecisaDeVoce(Exception):
    """Erro que a esteira não resolve sozinha, esperando."""


def _salvar_criacao(task_id: str) -> None:
    with TAREFAS_LOCK:
        t = TAREFAS.get(task_id)
        if not t or t.get("tipo") != "criacao":
            return
        copia = {**t, "logs": list(t.get("logs", []))[-300:]}
        t["_salvo_em"] = time.time()
    pasta = PROJETOS / copia["projeto"]
    if not pasta.exists():
        return
    copia.pop("_salvo_em", None)
    tmp = pasta / (ARQ_CRIACAO + ".tmp")
    try:
        tmp.write_text(json.dumps(copia, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        tmp.replace(pasta / ARQ_CRIACAO)
    except OSError:
        pass


def _ler_criacao(nome: str) -> Optional[Dict[str, Any]]:
    arq = PROJETOS / nome / ARQ_CRIACAO
    if not arq.exists():
        return None
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except Exception:
        return None


def _atualizar(task_id: str, **campos) -> None:
    with TAREFAS_LOCK:
        if task_id in TAREFAS:
            TAREFAS[task_id].update(campos)
    _salvar_criacao(task_id)


def _log_tarefa(task_id: str, msg) -> None:
    salvar = False
    with TAREFAS_LOCK:
        t = TAREFAS.get(task_id)
        if t is not None:
            t.setdefault("logs", []).append(str(msg))
            salvar = t.get("tipo") == "criacao" and time.time() - t.get("_salvo_em", 0) > 5
    if salvar:
        _salvar_criacao(task_id)


def _etapa(task_id: str, rotulo: str, funcao):
    """Roda uma etapa até dar certo, tentando de novo em segundos. A etapa continua de onde parou."""
    for tentativa in range(TENTATIVAS_POR_ETAPA):
        try:
            return funcao()
        except (Exception, SystemExit) as err:
            msg = str(err) or err.__class__.__name__
            if _ERRO_PERMANENTE.search(msg):
                raise ParadaPrecisaDeVoce(msg) from None
            if tentativa == TENTATIVAS_POR_ETAPA - 1:
                raise
            espera = _ESPERAS[min(tentativa, len(_ESPERAS) - 1)]
            _log_tarefa(task_id, f"  {rotulo}: {msg}")
            _log_tarefa(task_id, f"  tentando de novo em {espera}s, de onde parou (tentativa {tentativa + 2})")
            _atualizar(task_id, mensagem=f"{rotulo}: um serviço falhou, tentando de novo em {espera}s...")
            time.sleep(espera)
            _atualizar(task_id, mensagem=f"{rotulo}: retomando...")


def cenas_sem_arquivo(p: Projeto) -> List[int]:
    """Cenas que o render recusaria: a mesma regra do render.origem_da_cena."""
    faltam = []
    for c in p.ler_json("cenas.json")["cenas"]:
        m = c.get("midia")
        if m and m.get("arquivo"):
            if not (p.pasta / m["arquivo"]).exists():
                faltam.append(c["n"])
        elif not p.imagem(c["n"]).exists():
            faltam.append(c["n"])
    return faltam


def _soltar_midia_sumida(p: Projeto) -> None:
    """Cena que aponta para um arquivo que não existe mais volta a esperar material, para a busca pegar ela."""
    dados = p.ler_json("cenas.json")
    mexeu = False
    for c in dados["cenas"]:
        m = c.get("midia")
        if m and m.get("arquivo") and not (p.pasta / m["arquivo"]).exists():
            c.pop("midia", None)
            mexeu = True
    if mexeu:
        p.salvar_json("cenas.json", dados)


def _executar_criacao(nome: str, task_id: str) -> None:
    """A esteira inteira. Pode ser chamada de novo a qualquer momento: pula o que já foi feito."""
    with TAREFAS_LOCK:
        if nome in CRIACOES_ATIVAS:
            return
        CRIACOES_ATIVAS.add(nome)
    try:
        _esteira(nome, task_id)
    except ParadaPrecisaDeVoce as err:
        _atualizar(task_id, status="erro", etapa="erro", concluido=False, pronto_para_edicao=False, precisa_voce=True,
                   erro=str(err), mensagem=f"Parado, precisa de você: {err}")
        _log_tarefa(task_id, f"[ERRO]: {err}")
    except (Exception, SystemExit) as err:
        _atualizar(task_id, status="erro", etapa="erro", concluido=False, pronto_para_edicao=False,
                   erro=str(err), mensagem=f"Erro no processamento: {err}")
        _log_tarefa(task_id, f"[ERRO]: {err}")
    finally:
        _salvar_criacao(task_id)
        with TAREFAS_LOCK:
            CRIACOES_ATIVAS.discard(nome)


def _esteira(nome: str, task_id: str) -> None:
    p = Projeto(nome)
    log_w = lambda msg: _log_tarefa(task_id, msg)
    with TAREFAS_LOCK:
        feitas = set(TAREFAS[task_id].setdefault("feitas", []))
    # projeto de antes da esteira: o que já está no disco conta como feito
    with TAREFAS_LOCK:
        # depois de uma troca de narração: as cenas que ficaram sem imagem ou mudaram de fala (conferir_cenas) e,
        # delas, as que mudaram de fala com a foto antiga (conferir_forcadas), que o Jev julga de novo
        conferir_cenas = TAREFAS[task_id].get("conferir_cenas")
        conferir_forcadas = set(TAREFAS[task_id].get("conferir_forcadas") or [])
    if p.existe("cenas.json"):
        feitas |= {"mapa", "narracao", "cenas"}
        if (p.pasta / "conferir").exists() and conferir_cenas is None:
            feitas.add("conferir")  # a conferência paga o Jev: a que já rodou não roda de novo

    def marcar(etapa):
        feitas.add(etapa)
        _atualizar(task_id, feitas=sorted(feitas))

    _atualizar(task_id, status="processando", erro=None, precisa_voce=False, aguardando_ate=None)

    # PASSO 0: o agente de roteiro lê o roteiro inteiro e devolve o mapa do vídeo, que guia as cenas
    agente = cenas_prontas = None
    if "cenas" not in feitas and roteirista.ativo(p):
        _atualizar(task_id, etapa="mapa", progresso_pct=8, mensagem="Lendo o roteiro inteiro e montando o mapa do vídeo...")
        mapa_video = _etapa(task_id, "Mapa do roteiro", lambda: roteirista.mapa(p, log=log_w))
        _atualizar(task_id, mapa=mapa_video)
        marcar("mapa")

        # o JSON de todas as cenas sai do texto, então o agente trabalha enquanto a narração é gravada
        def montar_cenas():
            dados = _etapa(task_id, "JSON de cenas", lambda: roteirista.roteiro_de_cenas(p, log=log_w))
            _atualizar(task_id, cenas_planejadas=len(dados["cenas"]))
            return dados

        agente = ThreadPoolExecutor(max_workers=1)
        cenas_prontas = agente.submit(montar_cenas)
    elif "cenas" not in feitas:
        # sem isso, parecia que o agente tinha travado: ele só não entra nesses casos
        log_w("  agente de roteiro desligado neste projeto (perfil com personagem ou efeitos, modo offline "
              "ou roteirista.ativo: false no config.yaml): as cenas seguem pelo caminho antigo")

    # PASSO 1: Narração (junto com o JSON de cenas do agente)
    if "narracao" not in feitas:
        _atualizar(task_id, etapa="narracao", passo_atual=1, progresso_pct=15,
                   mensagem=("Gravando a narração enquanto o agente monta o JSON das cenas..."
                             if agente else "Gerando áudio da narração e marcando tempo das palavras..."))
        try:
            _etapa(task_id, "Narração", lambda: narracao.narrar(p, log=log_w))
        finally:
            if agente:
                agente.shutdown(wait=False)
        marcar("narracao")
    if cenas_prontas is not None:
        _atualizar(task_id, mensagem="Narração pronta! Esperando o agente terminar o JSON das cenas...")
        # enquanto espera, a barra anda com os lotes que o agente já decidiu (de 15% a 35%): antes ela ficava parada
        # nos 15% e a criação parecia travada
        while True:
            try:
                cenas_prontas.result(timeout=5)  # o agente já tentou de novo sozinho; um erro que sobrou aparece aqui
                break
            except EsperaEsgotada:
                andamento = roteirista.PROGRESSO.get(p.nome) or {}
                if andamento.get("total"):
                    feitos, total = andamento["feitos"], andamento["total"]
                    _atualizar(task_id, progresso_pct=15 + int(20 * feitos / total),
                               mensagem=f"Narração pronta! O agente já decidiu {feitos} de {total} lotes de cenas...")

    # PASSO 2: Direção de Arte e Divisão de Cenas
    if "cenas" not in feitas:
        _atualizar(task_id, etapa="cenas", passo_atual=2, progresso_pct=40,
                   mensagem="Encaixando o JSON de cenas no tempo da narração...")
        _etapa(task_id, "Divisão de cenas", lambda: cenas.planejar(p, log=log_w))
        marcar("cenas")

    # PASSO 3: Mídia de Acervo (Pexels / Pixabay / Wikimedia). A busca pula as cenas que já têm material.
    _atualizar(task_id, etapa="midia", passo_atual=3, progresso_pct=65,
               mensagem="Buscando fotos e vídeos de acervo (Pexels, Pixabay e Wikimedia)...")
    _soltar_midia_sumida(p)
    _etapa(task_id, "Busca de acervo", lambda: midia.buscar(p, log=log_w))
    marcar("midia")

    # PASSO 4: Conferência das cenas de acervo. Vem antes das imagens de IA de propósito: o
    # que a conferência conserta de graça no acervo deixa de virar imagem paga logo depois
    cfg_corr = p.config.get("corrigir") or {}
    # a cena que o Jev já aprovou na captura (antes de baixar) não é conferida de novo: só as que ficaram na
    # dúvida, foram preenchidas no aperto ou não passaram pela conferência. É isso que tira a necessidade do
    # botão Corrigir Mídia sem repetir centenas de julgamentos
    # regra fixa: na dúvida é também toda cena com nota abaixo da mínima, e na criação a conferência troca
    # sozinha tudo o que ficar abaixo dela (buscando no acervo, sem custo de imagem), sem deixar para o botão
    minima = midia.nota_minima_da_conferencia(p)

    def aprovada_na_captura(c):
        cap = c.get("captura") or {}
        return cap.get("conferida") and not cap.get("suspeita") and (cap.get("nota") or 0) >= minima

    if conferir_cenas is None:
        na_duvida = {c["n"] for c in corrigir.conferiveis(p) if not aprovada_na_captura(c)}
    else:
        na_duvida = {c["n"] for c in corrigir.conferiveis(p, numeros=set(conferir_cenas))
                     if c["n"] in conferir_forcadas or not aprovada_na_captura(c)}
    if "conferir" not in feitas and cfg_corr.get("automatico", True) and na_duvida:
        _atualizar(task_id, etapa="conferir", passo_atual=4, progresso_pct=78,
                   mensagem=f"Conferindo as {len(na_duvida)} cena(s) que ficaram na dúvida na captura...")
        log_w(f"  {len(na_duvida)} cena(s) na dúvida vão para a conferência; as aprovadas na captura ficam como estão")
        try:
            resultado_conf = _etapa(task_id, "Conferência", lambda: corrigir.corrigir(
                p, numeros=na_duvida, rodadas=cfg_corr.get("rodadas", corrigir.RODADAS),
                nota_minima=minima, nota_para_trocar=minima, log=log_w))
            _atualizar(task_id, conferencia={
                "avaliadas": resultado_conf["avaliadas"], "trocadas": resultado_conf["trocadas"],
                "para_revisar": resultado_conf.get("para_revisar", []),
                "precisam_ia": resultado_conf.get("precisam_ia", [])})
        except ParadaPrecisaDeVoce:
            raise
        except (Exception, SystemExit) as erro_conf:
            # a conferência é uma melhoria, não um bloqueio: o vídeo segue mesmo se ela falhar
            log_w(f"  a conferência das cenas falhou, seguindo sem ela: {erro_conf}")
        marcar("conferir")

    # PASSO 5: Imagens de IA para o que o acervo não resolveu
    _atualizar(task_id, etapa="imagens", passo_atual=5, progresso_pct=88, mensagem="Gerando imagens de IA...")
    _etapa(task_id, "Imagens de IA", lambda: imagens.gerar(p, log=log_w))
    marcar("imagens")

    # PASSO 6: nenhuma cena pode ficar sem imagem, senão o render recusa
    for rodada in range(1, RODADAS_PARA_COMPLETAR + 1):
        faltam = cenas_sem_arquivo(p)
        if not faltam:
            break
        _atualizar(task_id, progresso_pct=94,
                   mensagem=f"Completando {len(faltam)} cena(s) que ficaram sem imagem (rodada {rodada})...")
        log_w(f"  {len(faltam)} cena(s) sem imagem: " + ", ".join(map(str, faltam[:30])))
        _soltar_midia_sumida(p)
        _etapa(task_id, "Completar cenas", lambda: corrigir.preparar_gratis(p, log=log_w))
        _etapa(task_id, "Imagens de IA", lambda: imagens.gerar(p, log=log_w))
    faltam = cenas_sem_arquivo(p)
    if faltam:
        # nunca copiar a imagem de outra cena: mais uma busca de imagem NOVA do assunto, nos 9 bancos
        _soltar_midia_sumida(p)
        _etapa(task_id, "Completar cenas", lambda: midia.buscar(p, apenas=set(faltam), log=log_w, permissivo=True))
    # regra fixa: jamais repetir imagem, conferido na imagem em si, antes de dizer que está pronto
    _etapa(task_id, "Sem imagens repetidas", lambda: midia.tirar_repetidas(p, log=log_w))
    if cenas_sem_arquivo(p) and midia.ia_ativa(p):
        # a repetida que não achou foto nova nos bancos vai para a imagem de IA (ia.ativa). Antes a criação parava
        # pedindo uma foto (cena 79 do nunca-deve-ter-dentro-de-casa-parte-2, o petauro-do-açúcar, com a IA ligada)
        _etapa(task_id, "Imagens de IA", lambda: imagens.gerar(p, log=log_w))
    if cenas_sem_arquivo(p):
        # nada do assunto nos bancos nem em outra cena do mesmo assunto: pôr outra coisa seria gafe, então pede ajuda
        por_n = {c["n"]: c for c in p.ler_json("cenas.json")["cenas"]}
        lista = "; ".join(f"cena {n} ({por_n[n].get('sujeito') or por_n[n].get('busca')})" for n in cenas_sem_arquivo(p)[:15])
        raise ParadaPrecisaDeVoce(
            f"Os bancos de imagens não têm nenhuma foto destes assuntos: {lista}. Suba uma foto dessas cenas no editor "
            "(ou ligue a IA no config.yaml) e clique em Retomar.")

    # PASSO 7: diagramas, textos na tela, linhas do tempo e mapas viram animação (HyperFrames, gratuito). É uma
    # melhoria: a cena que não der para animar continua com a foto, e uma falha aqui nunca para o vídeo
    if animacoes.ligada(p):
        _atualizar(task_id, etapa="animacoes", progresso_pct=97,
                   mensagem="Animando os diagramas, textos na tela e mapas no tempo da narração...")
        try:
            resumo_anim = animacoes.gerar(p, log=log_w, trava=trava_do_projeto(nome))
            _atualizar(task_id, animacoes={"feitas": resumo_anim["feitas"], "prontas": resumo_anim["prontas"],
                                           "ficaram_com_foto": sorted(resumo_anim["falharam"])})
        except (Exception, SystemExit) as erro_anim:
            log_w(f"  as animações falharam, as cenas seguem com foto: {erro_anim}")

    # PASSO 8: o modelo compõe a trilha pelos blocos do roteiro e o código toca (gratuito). Se falhar aqui, o render
    # tenta de novo; e o vídeo nunca deixa de sair por causa dela
    if trilha.ligada(p):
        _atualizar(task_id, etapa="trilha", progresso_pct=98, mensagem="Compondo a trilha sonora do vídeo...")
        try:
            trilha.gerar(p, log=log_w)
        except (Exception, SystemExit) as erro_trilha:
            log_w(f"  a trilha não saiu agora, o render tenta de novo: {erro_trilha}")

    try:
        _atualizar(task_id, qualidade=qualidade.registrar(p, "criação", log_w))
    except (Exception, SystemExit) as erro_q:
        log_w(f"  a nota de qualidade não saiu: {erro_q}")
    _atualizar(task_id, status="concluido", etapa="concluido", passo_atual=5, total_passos=5, progresso_pct=100,
               mensagem="Cenas prontas com sucesso! Tudo pronto para renderizar.", pronto_para_edicao=True,
               concluido=True, aguardando_ate=None)


def iniciar_criacao(nome: str, tarefa: Optional[Dict[str, Any]] = None) -> str:
    """Põe a esteira para rodar numa linha própria. Com tarefa=None, continua a última criação gravada."""
    if tarefa is None:
        tarefa = _ler_criacao(nome) or {}
        tarefa = {**tarefa, "logs": tarefa.get("logs", [])}
        tarefa.setdefault("tarefa_id", f"criar_{nome}_{datetime.now():%Y%m%d_%H%M%S}")
        tarefa.update(projeto=nome, tipo="criacao", status="processando", concluido=False,
                      pronto_para_edicao=False, erro=None, precisa_voce=False,
                      mensagem="Retomando de onde parou...")
        tarefa.setdefault("inicio", datetime.now().isoformat())
        tarefa.setdefault("passo_atual", 1)
        tarefa.setdefault("total_passos", 5)
        tarefa.setdefault("progresso_pct", 5)
    task_id = tarefa["tarefa_id"]
    with TAREFAS_LOCK:
        TAREFAS[task_id] = tarefa
    _salvar_criacao(task_id)
    threading.Thread(target=_executar_criacao, args=(nome, task_id), name=f"criacao-{nome}", daemon=True).start()
    return task_id


def retomar_criacoes_interrompidas() -> None:
    """Na partida da fábrica: toda criação que estava andando quando ela desligou volta a andar."""
    if not PROJETOS.exists():
        return
    for pasta in sorted(PROJETOS.iterdir()):
        estado = _ler_criacao(pasta.name) if pasta.is_dir() else None
        if estado and estado.get("status") in ("processando", "aguardando"):
            print(f"  retomando a criação de {pasta.name}, que foi interrompida")
            iniciar_criacao(pasta.name)


# -----------------------------------------------------------------------------
# Modelos Pydantic (Payloads)
# -----------------------------------------------------------------------------

class CriarProjetoPayload(BaseModel):
    nome: str
    roteiro: str
    perfil: Optional[str] = "perfis/livro-de-enoque.yaml"
    voz: Optional[str] = "pt-BR-AntonioNeural"  # nome de voz Edge-TTS, usado quando voz_provedor não é "genaipro"
    voz_provedor: Optional[str] = None  # None/"edge-tts" usa a voz acima; "genaipro" usa os campos abaixo
    voz_id: Optional[str] = None
    voz_modelo: Optional[str] = None
    voz_idioma: Optional[str] = None  # "pt", "es" ou "en" — só pra lembrar a aba certa ao reabrir
    voz_nome: Optional[str] = None  # nome da voz, pra mostrar no editor sem buscar de novo
    # nomes antigos, de quando a narração era pela ElevenLabs direta: um editor desatualizado ainda manda assim
    voz_elevenlabs_id: Optional[str] = None
    voz_elevenlabs_modelo: Optional[str] = None
    voz_elevenlabs_idioma: Optional[str] = None
    voz_estabilidade: Optional[float] = None
    voz_similaridade: Optional[float] = None
    voz_estilo: Optional[float] = None
    voz_velocidade: Optional[float] = None
    imagens_provedor: Optional[str] = None  # "openrouter" (Grok Imagine 2), "google" (Nano Banana 2) ou "kie" (Kie.ai). None usa o perfil


class RefazerCenaPayload(BaseModel):
    tipo: Optional[str] = None  # "ia", "foto_real", "video_real"
    prompt: Optional[str] = None
    busca: Optional[str] = None
    forcar_ia: bool = False


class ImagensAjustesPayload(BaseModel):
    """Ajuste de provedor de imagem de IA só deste projeto, sem tocar no perfil do canal."""
    provedor: Optional[str] = None  # "openrouter" (Grok Imagine 2), "google" (Nano Banana 2) ou "kie" (Kie.ai)
    modelo: Optional[str] = None  # se não vier, assume o modelo padrão do provedor escolhido


class VozAjustesPayload(BaseModel):
    """Ajustes de voz só deste projeto (GenAIPro ou Edge-TTS), sem tocar no perfil do canal."""
    provedor: Optional[str] = None  # "genaipro", "fish" (grátis) ou "edge-tts" (antigo; "elevenlabs" = GenAIPro)
    voice_id: Optional[str] = None
    nome: Optional[str] = None
    idioma: Optional[str] = None  # "pt", "es" ou "en" — só pra lembrar a aba certa ao reabrir
    modelo: Optional[str] = None
    estabilidade: Optional[float] = None
    similaridade: Optional[float] = None
    estilo: Optional[float] = None
    velocidade: Optional[float] = None
    continuidade: Optional[bool] = None
    voz_edge: Optional[str] = None
    velocidade_edge: Optional[str] = None
    tom_edge: Optional[str] = None


class NarracaoPayload(BaseModel):
    roteiro: Optional[str] = None
    velocidade: Optional[str] = None  # "-10%", "+0%", "+10%" (Edge-TTS)
    nova_voz: bool = False
    voz: Optional[VozAjustesPayload] = None  # ajustes de voz a aplicar antes de regerar


class RenderOpcoesPayload(BaseModel):
    fps: Optional[int] = 30
    resolucao: Optional[str] = "1080p"
    legenda: Optional[bool] = True
    musica: Optional[bool] = True
    volume_musica_db: Optional[float] = -16.0
    movimento_camera: Optional[bool] = True


class CenaConfirmada(BaseModel):
    n: int
    tipo: Optional[str] = "ia"
    arquivo: Optional[str] = None
    ini: Optional[float] = 0.0
    fim: Optional[float] = 0.0


class RenderPayload(BaseModel):
    projeto: Optional[str] = None
    opcoes: Optional[RenderOpcoesPayload] = None
    cenas_confirmadas: Optional[List[CenaConfirmada]] = None
    sem_avatar: bool = True
    vertical: bool = False  # versão em pé (9:16) para Reels e Shorts, em final_vertical.mp4; a deitada fica como está


class SalvarCenasPayload(BaseModel):
    cenas: List[Dict[str, Any]]


class PublicarYoutubePayload(BaseModel):
    titulo: str
    descricao: str = ""
    tags: List[str] = []
    privacidade: str = "public"  # "public", "unlisted" ou "private"
    agendado_para: Optional[str] = None  # ISO 8601; quando vem preenchido, sobe como "private" e agenda a troca


# -----------------------------------------------------------------------------
# Funções Auxiliares de Mídia
# -----------------------------------------------------------------------------

def definir_midia_manual(projeto: Projeto, cena_n: int, arquivo_bytes: bytes, nome_original: str) -> Dict[str, Any]:
    """Substitui manualmente a imagem ou vídeo de uma cena por arquivo enviado pelo usuário."""
    dados = projeto.ler_json("cenas.json")
    cena = next((c for c in dados["cenas"] if c["n"] == cena_n), None)
    if not cena:
        raise HTTPException(status_code=404, detail=f"Cena {cena_n} não encontrada.")

    ext = Path(nome_original).suffix.lower() if nome_original else ".png"
    is_video = ext in (".mp4", ".mov", ".webm", ".mkv", ".avi")
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")

    # Guardar versão anterior na pasta antigas/
    antigas_dir = projeto.caminho("antigas")
    antigas_dir.mkdir(parents=True, exist_ok=True)

    img_ia = projeto.imagem(cena_n)
    if img_ia.exists():
        shutil.move(str(img_ia), str(antigas_dir / f"{cena_n:04d}_ia_{carimbo}.png"))

    if cena.get("midia") and cena["midia"].get("arquivo"):
        arq_antigo = projeto.pasta / cena["midia"]["arquivo"]
        if arq_antigo.exists():
            shutil.move(str(arq_antigo), str(antigas_dir / f"{arq_antigo.stem}_{carimbo}{arq_antigo.suffix}"))

    if is_video:
        rel_path = f"midia/{cena_n:04d}_manual{ext}"
        abs_path = projeto.pasta / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(arquivo_bytes)

        cena["tipo"] = "video_real"
        cena["midia"] = {
            "fonte": "upload_manual",
            "id": f"manual_{cena_n}_{carimbo}",
            "tipo": "video",
            "arquivo": rel_path,
            "capa": rel_path,
            "autor": "Manual",
            "licenca": "Própria",
        }
    else:
        abs_path = projeto.imagem(cena_n)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(arquivo_bytes)

        cena["tipo"] = "ia"
        cena["midia"] = None
        # a foto fica em imagens/NNNN.png, pelo número da cena: a marca faz ela acompanhar a cena e vencer o acervo
        # quando a narração muda e as cenas são renumeradas (cenas._levar_imagens_numeradas)
        cena["imagem_da_pessoa"] = True

    projeto.salvar_json("cenas.json", dados)
    return cena


def _url_com_versao(url: str, arquivo: Path) -> str:
    """Acrescenta a data de modificação do arquivo na URL, pra o navegador nunca reaproveitar
    do cache uma versão antiga quando o mesmo nome de arquivo é sobrescrito (restaurar,
    regerar, refazer cena — todos gravam por cima do mesmo caminho)."""
    try:
        versao = int(arquivo.stat().st_mtime)
    except OSError:
        return url
    return f"{url}?v={versao}"


def enriquecer_cena(projeto: Projeto, cena: Dict[str, Any], motion: Optional[list] = None) -> Dict[str, Any]:
    """Adiciona URLs e status de existência aos assets da cena."""
    n = cena["n"]
    tipo = cena.get("tipo", "ia")
    midia_info = cena.get("midia")

    # Imagem IA
    img_ia = projeto.imagem(n)
    img_ia_existe = img_ia.exists()
    img_ia_url = _url_com_versao(f"/arquivos/{projeto.nome}/imagens/{n:04d}.png", img_ia) if img_ia_existe else None

    # Mídia Real
    midia_existe = False
    midia_url = None
    capa_url = None
    if midia_info and midia_info.get("arquivo"):
        arq = projeto.pasta / midia_info["arquivo"]
        midia_existe = arq.exists()
        if midia_existe:
            midia_url = _url_com_versao(f"/arquivos/{projeto.nome}/{midia_info['arquivo'].replace(os.sep, '/')}", arq)
    if midia_info and midia_info.get("capa"):
        arq_capa = projeto.pasta / midia_info["capa"]
        if arq_capa.exists():
            capa_url = _url_com_versao(f"/arquivos/{projeto.nome}/{midia_info['capa'].replace(os.sep, '/')}", arq_capa)

    # URL principal a ser exibida no frontend
    # a mesma regra do render (origem_da_cena): sem imagem de IA, a cena com material real mostra o material, mesmo
    # com tipo "ia". Na junção de cenas o tipo de uma vinha para a outra sem o material, e a cena com foto de banco
    # aparecia como "sem arquivo" no editor, embora o render usasse a foto
    url_principal = midia_url if (midia_url and (tipo in ("foto_real", "video_real") or not img_ia_existe)) else img_ia_url
    # a animação é uma faixa própria por cima das cenas (lista "motion" de GET /cenas): a cena mostra a imagem dela.
    # animada: alguma animação passa por cima dela, e o texto na tela da cena sai (a mesma regra do render)
    try:
        ligada = animacoes.config(projeto).get("ativo", True)
        motion = (animacoes.validas(projeto) if motion is None else motion) if ligada else []
        animada = any(animacoes.sobreposta(item, cena) for item in motion)
        situacao_animacao = animacoes.situacao(projeto, cena, motion) if ligada else ""
    except (OSError, KeyError, TypeError, ValueError):
        animada, situacao_animacao = False, ""

    # versões leves para o editor: miniatura da timeline e prévia do player, em vez do original pesado
    thumb_url = previa_url = None
    origem_previa = _origem_da_previa(projeto, cena)
    if origem_previa is not None:
        try:
            v = int(origem_previa.stat().st_mtime)
            thumb_url = f"/arquivos_previas/{projeto.nome}/mini/{n}.jpg?v={v}"
            previa_url = f"/arquivos_previas/{projeto.nome}/tela/{n}.jpg?v={v}"
        except OSError:
            pass
    # o vídeo de banco tem prévia leve própria: 480p, só o trecho que a cena usa
    previa_video_url = None
    video = _video_da_cena(projeto, cena)
    if video is not None:
        try:
            v = f"{int(video.stat().st_mtime)}-{int(round((cena['fim'] - cena['ini']) * 10))}"
            previa_video_url = f"/arquivos_previas/{projeto.nome}/video/{n}.mp4?v={v}"
        except (OSError, KeyError, TypeError):
            pass

    # A cena pode ter sido planejada como real e não ter achado material (sem_midia_real):
    # o tipo continua "foto_real"/"video_real" no cenas.json, mas o que aparece de fato é a
    # imagem de IA gerada como reserva. O rótulo tem que refletir isso, senão mostra "Foto Real"
    # numa cena que é IA de verdade.
    tipo_efetivo = "ia" if cena.get("sem_midia_real") else tipo

    # Badge descritivo da origem
    if tipo_efetivo == "ia":
        origem_badge = "IA"
    elif tipo_efetivo == "video_real":
        fonte_nome = (midia_info.get("fonte") or "acervo").capitalize() if midia_info else "Acervo"
        origem_badge = f"Vídeo Real ({fonte_nome})"
    elif tipo_efetivo == "foto_real":
        fonte_nome = (midia_info.get("fonte") or "acervo").capitalize() if midia_info else "Acervo"
        origem_badge = f"Foto Real ({fonte_nome})"
    else:
        origem_badge = tipo_efetivo
    if midia_info and midia_info.get("fonte") == "motion_ia":
        origem_badge = "Motion IA"  # clipe de motion feito pela fábrica no lugar da foto reprovada (motion_ia.py)

    # Efeito sonoro (SFX)
    efeito_url = None
    efeito = cena.get("efeito")
    if efeito and efeito.get("descricao"):
        desc = " ".join(efeito["descricao"].lower().split())
        base = re.sub(r"[^a-z0-9]+", "-", desc).strip("-")[:50] or "efeito"
        # Procura arquivo correspondente
        for pasta in (RAIZ / "efeitos", RAIZ / "efeitos" / "teste"):
            if pasta.exists():
                for arq_sfx in pasta.glob(f"{base}*.mp3"):
                    efeito_url = f"/arquivos_raiz/{arq_sfx.relative_to(RAIZ).as_posix()}"
                    break
            if efeito_url:
                break

    return {
        **cena,
        "texto_tela": None,  # o texto na tela do FFmpeg saiu da fábrica (2026-10-05): o editor não desenha mais
        "url_midia": url_principal,
        "thumb_url": thumb_url,      # miniatura de 320px, para a timeline e a lista de cenas
        "previa_url": previa_url,    # prévia de 1280px, para o player mostrar fotos sem baixar o original
        "previa_video_url": previa_video_url,  # vídeo de banco em 480p, só o trecho da cena, para o player
        "img_ia_url": img_ia_url,
        "img_ia_existe": img_ia_existe,
        "midia_url": midia_url,
        "capa_url": capa_url,
        "midia_existe": midia_existe,
        # nenhum arquivo para mostrar: material real que não baixou e imagem de IA que ainda não foi gerada
        "sem_arquivo": url_principal is None,
        "origem_badge": origem_badge,
        "efeito_url": efeito_url,
        # "pronta", "desatualizada" (a cena mudou depois), "desligada" (a pessoa preferiu a foto), "possivel" ou ""
        "animacao_situacao": situacao_animacao,
        "animada": animada,
        # o que a revisão do vídeo pronto apontou nesta cena (vale para o final.mp4 de agora)
        "revisao": revisao_video.problemas_da_cena(projeto, n, _revisao_atual(projeto)),
    }


def obter_legendas_projeto(p: Projeto) -> List[Dict[str, Any]]:
    """Lê legendas_tela.srt (ou legendas.srt) e retorna lista estruturada de legendas de 1 linha."""
    for nome_srt in ("legendas_tela.srt", "legendas.srt"):
        caminho = p.pasta / nome_srt
        if caminho.exists():
            try:
                conteudo = caminho.read_text(encoding="utf-8")
                padrao = re.compile(
                    r"(\d+)\s*\n(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)",
                    re.DOTALL
                )
                itens = []
                for m in padrao.finditer(conteudo):
                    _, h1, m1, s1, ms1, h2, m2, s2, ms2, txt = m.groups()
                    t_ini = int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000.0
                    t_fim = int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000.0
                    limpo = re.sub(r"\[.*?\]", "", txt).strip()
                    limpo = " ".join(limpo.split())
                    if limpo:
                        itens.append({"ini": round(t_ini, 3), "fim": round(t_fim, 3), "texto": limpo})
                if itens:
                    return itens
            except Exception:
                pass
    return []


# -----------------------------------------------------------------------------
# Rotas REST da API
# -----------------------------------------------------------------------------

@app.post("/api/projetos/criar")
def criar_projeto(payload: CriarProjetoPayload, bg_tasks: BackgroundTasks):
    """
    Cria um novo projeto a partir de roteiro, perfil e voz.
    Dispara as 4 etapas de geração em background e retorna 202 Accepted.
    """
    nome = payload.nome.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", nome):
        raise HTTPException(
            status_code=400,
            detail="Nome inválido. Use apenas letras minúsculas, números, hífen e sublinhado."
        )
    if not payload.roteiro or not payload.roteiro.strip():
        raise HTTPException(status_code=400, detail="O roteiro não pode estar vazio.")
    with TAREFAS_LOCK:
        if nome in CRIACOES_ATIVAS:
            raise HTTPException(status_code=409, detail=f"O vídeo '{nome}' ainda está sendo criado. Use outro nome "
                                                        "ou espere terminar.")

    # Resolver perfil YAML
    perfil_caminho = payload.perfil or "perfis/documentario.yaml"
    if perfil_caminho in ("perfis/padrao.yaml", "padrao.yaml", "padrao"):
        perfil_caminho = "perfis/documentario.yaml"
    perfil_path = Path(perfil_caminho)
    if not perfil_path.is_absolute():
        perfil_path = RAIZ / perfil_caminho
    if not perfil_path.exists():
        alt = RAIZ / "perfis" / Path(perfil_caminho).name
        if alt.exists():
            perfil_path = alt
        else:
            perfil_path = RAIZ / "perfis" / "documentario.yaml"
    if _perfil_de_avatar(perfil_path):
        # antes a criação ia até 94% e parava com "cenas sem imagem": o vídeo desse perfil é o personagem
        raise HTTPException(
            status_code=400,
            detail=(f"O perfil '{perfil_path.stem}' é de personagem (avatar do HeyGen) e precisa de vídeos gravados "
                    "fora da fábrica. Escolha um perfil de documentário, como 'Documentário'."))

    # Sem teto de duração: roteiro de qualquer tamanho é aceito. Abaixo do alvo de 20 min também
    # não tem bloqueio, porque o editor não tem como pedir confirmação interativa como o terminal.
    pasta = PROJETOS / nome
    havia_projeto = pasta.exists()
    pasta.mkdir(parents=True, exist_ok=True)

    if havia_projeto:
        shutil.rmtree(pasta / "cenas_lotes", ignore_errors=True)
        (pasta / "cenas.json").unlink(missing_ok=True)
        carimbo = f"{datetime.now():%Y%m%d-%H%M%S}"
        for sub in ("imagens", "midia"):
            if (pasta / sub).exists():
                (pasta / sub).rename(pasta / f"{sub}_antigas_{carimbo}")

    # Gravar roteiro.txt
    (pasta / "roteiro.txt").write_text(payload.roteiro.strip(), encoding="utf-8")

    # Normaliza voz para garantir compatibilidade total com Edge-TTS
    voz_req = (payload.voz or "pt-BR-AntonioNeural").strip()
    if "Thalita" in voz_req:
        voz_req = "pt-BR-ThalitaMultilingualNeural"
    elif voz_req not in {"pt-BR-AntonioNeural", "pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural", "pt-PT-DuarteNeural", "pt-PT-RaquelNeural"}:
        voz_req = "pt-BR-AntonioNeural"

    dados_projeto = {
        "nome": nome,
        "perfil": str(perfil_path.resolve()),
        "offline": False,
        "criado": datetime.now().isoformat(timespec="seconds"),
        "voz": voz_req,
    }
    (pasta / "projeto.json").write_text(json.dumps(dados_projeto, ensure_ascii=False, indent=2), encoding="utf-8")

    # Ajuste de voz e de imagens só deste projeto, sem tocar no perfil do canal. Fica no projeto.json,
    # então vale também quando a criação é retomada depois de um reinício
    p = Projeto(nome)
    if payload.voz_provedor == "fish":
        # a voz grátis: Fish Audio pelo OpenRouter, no lugar do Edge-TTS
        p.definir_voz_override({
            "provedor": "fish",
            "voice_id": payload.voz_id,
            "nome": payload.voz_nome,
            "idioma": payload.voz_idioma,
            "velocidade": payload.voz_velocidade,
        })
    elif payload.voz_provedor in ("genaipro", "elevenlabs"):
        p.definir_voz_override({
            "provedor": "genaipro",
            "voice_id": payload.voz_id or payload.voz_elevenlabs_id,
            "nome": payload.voz_nome,
            "idioma": payload.voz_idioma or payload.voz_elevenlabs_idioma,
            "modelo": payload.voz_modelo or payload.voz_elevenlabs_modelo,
            "estabilidade": payload.voz_estabilidade,
            "similaridade": payload.voz_similaridade,
            "estilo": payload.voz_estilo,
            "velocidade": payload.voz_velocidade,
        })
    elif payload.voz:
        p.definir_voz_override({"provedor": "edge-tts", "voz_edge": voz_req})
    if payload.imagens_provedor in PROVEDORES_IMAGEM:
        p.definir_imagens_override({
            "provedor": payload.imagens_provedor,
            "modelo": PROVEDORES_IMAGEM[payload.imagens_provedor],
        })

    task_id = iniciar_criacao(nome, {
        "tarefa_id": f"criar_{nome}_{datetime.now():%Y%m%d_%H%M%S}",
        "projeto": nome,
        "tipo": "criacao",
        "status": "processando",
        "etapa": "narracao",
        "passo_atual": 1,
        "total_passos": 5,
        "progresso_pct": 5,
        "mensagem": "Iniciando criação do projeto e gerando narração...",
        "pronto_para_edicao": False,
        "concluido": False,
        "feitas": [],
        "logs": [],
        "inicio": datetime.now().isoformat(),
    })
    return JSONResponse(
        status_code=202,
        content={
            "sucesso": True,
            "projeto": nome,
            "status": "processando",
            "mensagem": "Projeto iniciado. Acompanhe o progresso.",
            "tarefa_id": task_id,
        }
    )


class RetomarPayload(BaseModel):
    confirmar: bool = False  # sem isto só devolve o que falta e quanto pode custar


@app.post("/api/projetos/{nome}/retomar")
def retomar_criacao(nome: str, payload: Optional[RetomarPayload] = None):
    """Faz a criação andar de novo de onde parou: depois de um erro, de um reinício ou num projeto antigo parado."""
    if not (PROJETOS / nome).exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    with TAREFAS_LOCK:
        ativa = nome in CRIACOES_ATIVAS
    if ativa:
        return {"status": "processando", "mensagem": "A criação deste vídeo já está andando."}
    p = Projeto(nome)
    resumo = {"sem_acervo": 0, "sem_imagem_ia": 0, "custo_estimado_usd": 0.0}
    if p.existe("cenas.json"):
        lista = p.ler_json("cenas.json")["cenas"]
        sem_acervo = sum(1 for c in lista if midia.pendente(c))
        sem_ia = len(imagens.pendentes_ia(p, lista))
        preco = custos.preco_da_imagem(p)
        resumo = {"sem_acervo": sem_acervo, "sem_imagem_ia": sem_ia, "preco_por_imagem_usd": preco,
                  "custo_estimado_usd": round((sem_ia + 0.15 * sem_acervo) * preco, 2)}
    if not (payload and payload.confirmar):
        return {**resumo, "status": "aguardando_confirmacao"}
    task_id = iniciar_criacao(nome)
    return JSONResponse(status_code=202, content={**resumo, "status": "processando", "tarefa_id": task_id})


@app.get("/api/projetos/{nome}/mapa")
def mapa_do_roteiro(nome: str):
    """O JSON que o agente de roteiro montou: blocos, âncoras, armadilhas de busca, pessoas reais e proibidos."""
    p = Projeto(nome) if (PROJETOS / nome).exists() else None
    if p is None or not p.existe("roteiro_mapa.json"):
        raise HTTPException(status_code=404, detail="Este projeto ainda não tem o mapa do roteiro.")
    return p.ler_json("roteiro_mapa.json")


@app.get("/api/projetos/{nome}/roteiro-cenas")
def roteiro_de_cenas(nome: str):
    """O JSON completo das cenas que o agente montou pelo texto, antes de encaixar na narração."""
    p = Projeto(nome) if (PROJETOS / nome).exists() else None
    if p is None or not p.existe("roteiro_cenas.json"):
        raise HTTPException(status_code=404, detail="Este projeto ainda não tem o JSON de cenas do agente.")
    return p.ler_json("roteiro_cenas.json")


@app.get("/api/perfis")
def listar_perfis():
    """Retorna lista de perfis disponíveis na pasta perfis/."""
    pasta_perfis = RAIZ / "perfis"
    if not pasta_perfis.exists():
        return {"perfis": []}

    nomes_bonitos = {
        "documentario": "Documentário (qualquer assunto)",
        "animais-exoticos": "Animais Exóticos",
        "apresentacao": "Apresentação e Corporativo",
        "asteroide": "Ciência, Espaço & Documentário",
        "livro-de-enoque": "História Antiga & Mistérios Bíblicos",
        "meditacao": "Meditação & Relaxamento Guiado",
        "vo-cida": "Receitas & Histórias da Vovó",
        "workshop": "Workshop & Educacional",
    }

    itens = []
    for f in sorted(pasta_perfis.glob("*.yaml")):
        stem = f.stem
        if stem.startswith("base-"):
            continue  # perfil-base, herdado pelos canais, não é um canal para escolher
        if _perfil_de_avatar(f):
            continue  # precisa dos vídeos do HeyGen, que não vêm no pacote: pelo site nunca ficaria pronto
        desc = nomes_bonitos.get(stem, stem.replace("-", " ").title())
        itens.append({
            "id": stem,
            "caminho": f"perfis/{f.name}",
            "titulo": desc,
            "arquivo": f.name
        })

    # o documentário genérico vem primeiro: é o padrão de quem não escolhe
    itens.sort(key=lambda i: i["id"] != "documentario")
    return {"perfis": itens}


def _perfil_de_avatar(caminho: Path) -> bool:
    """Perfil com personagem do HeyGen: o vídeo depende de clipes gravados fora da fábrica."""
    try:
        return bool((carregar_perfil(str(caminho)).get("avatar") or {}).get("ativo"))
    except (Exception, SystemExit):
        return False


@app.get("/api/vozes")
def listar_vozes():
    """Retorna lista de vozes pt-BR disponíveis para narração no Edge-TTS."""
    vozes = [
        {"id": "pt-BR-AntonioNeural", "nome": "Antônio - pt-BR (Voz Masculina Natural)", "genero": "masculino"},
        {"id": "pt-BR-FranciscaNeural", "nome": "Francisca - pt-BR (Voz Feminina Expressiva)", "genero": "feminino"},
        {"id": "pt-BR-ThalitaMultilingualNeural", "nome": "Thalita - pt-BR (Voz Feminina Suave)", "genero": "feminino"},
        {"id": "pt-PT-DuarteNeural", "nome": "Duarte - pt-PT (Voz Masculina Portugal)", "genero": "masculino"},
        {"id": "pt-PT-RaquelNeural", "nome": "Raquel - pt-PT (Voz Feminina Portugal)", "genero": "feminino"},
    ]
    return {"vozes": vozes}


_CACHE_VOZES: Dict[tuple, tuple] = {}
_CACHE_VOZES_SEGUNDOS = 3600


@app.get("/api/vozes/genaipro")
@app.get("/api/vozes/elevenlabs")  # nome antigo, pra editor desatualizado
def listar_vozes_genaipro(idioma: str = "pt", busca: str = "", genero: str = "", pagina: int = 0):
    """Vozes da biblioteca da GenAIPro, com prévia em áudio. Sem busca, traz as de narração mais usadas do idioma.

    Não gasta créditos. A resposta fica guardada por uma hora pra não repetir a consulta."""
    idioma = idioma if any(i["id"] == idioma for i in IDIOMAS_VOZ) else "pt"
    genero = genero if genero in ("male", "female") else ""
    busca = (busca or "").strip()[:60]
    base = {"modelos": MODELOS_NARRACAO, "idiomas": IDIOMAS_VOZ, "idioma_atual": idioma,
            "preco_por_mil": round(custos_reais.preco_por_caractere(config_geral())[0] * 1000, 4)}
    if not genaipro.tem_chave():
        return {**base, "vozes": [], "erro": "Falta a chave da GenAIPro. Cole em GENAIPRO_API no .env."}
    chave_cache = (idioma, busca.lower(), genero, pagina)
    guardado = _CACHE_VOZES.get(chave_cache)
    if guardado and time.time() - guardado[0] < _CACHE_VOZES_SEGUNDOS:
        return {**base, "vozes": guardado[1]}
    try:
        vozes = genaipro.vozes(busca=busca or None, idioma=idioma, genero=genero or None,
                               uso=None if busca else "narrative_story", quantidade=30, pagina=pagina)
    except SystemExit as e:
        return {**base, "vozes": [], "erro": str(e)}
    _CACHE_VOZES[chave_cache] = (time.time(), vozes)
    return {**base, "vozes": vozes}


_CACHE_VOZES_FISH: Dict[tuple, tuple] = {}


@app.get("/api/vozes/fish")
def listar_vozes_fish(idioma: str = "pt", busca: str = "", genero: str = ""):
    """Vozes da biblioteca pública da Fish Audio, com amostra em áudio, para a voz grátis (no lugar do Edge-TTS).

    Não gasta nada. A resposta fica guardada por uma hora."""
    idioma = idioma if any(i["id"] == idioma for i in IDIOMAS_VOZ) else "pt"
    genero = genero if genero in ("male", "female") else ""
    busca = (busca or "").strip()[:60]
    base = {"modelos": [], "idiomas": IDIOMAS_VOZ, "idioma_atual": idioma, "preco_por_mil": 0}
    chave_cache = (idioma, busca.lower(), genero)
    guardado = _CACHE_VOZES_FISH.get(chave_cache)
    if guardado and time.time() - guardado[0] < _CACHE_VOZES_SEGUNDOS:
        return {**base, "vozes": guardado[1]}
    try:
        vozes = fish.vozes(busca=busca or None, idioma=idioma, genero=genero or None, quantidade=40)
    except fish.ErroFish as e:
        return {**base, "vozes": [], "erro": str(e)}
    _CACHE_VOZES_FISH[chave_cache] = (time.time(), vozes)
    return {**base, "vozes": vozes}


@app.get("/api/genaipro/creditos")
def creditos_genaipro():
    """Saldo da GenAIPro, quando vence e quanto isso rende em minutos de narração. Não gasta nada."""
    if not genaipro.tem_chave():
        return {"configurada": False, "creditos": 0, "pacotes": []}
    try:
        conta = genaipro.conta()
    except SystemExit as e:
        raise HTTPException(status_code=502, detail=str(e))
    por_caractere, origem = custos_reais.preco_por_caractere(config_geral())
    creditos_por_caractere, _ = custos_reais.creditos_por_caractere(config_geral())
    ritmo = 900  # caracteres por minuto de uma narração típica
    return {**conta, "configurada": True,
            "minutos_de_narracao": int(conta["creditos"] / (creditos_por_caractere * ritmo)),
            "preco_por_minuto_usd": round(por_caractere * ritmo, 4), "origem_do_preco": origem}


@app.get("/api/imagens/provedores")
def listar_provedores_imagem():
    """Os provedores de imagem de IA que o usuário pode escolher por projeto. O padrão é o OpenRouter."""
    precos = (config_geral().get("precos") or {})
    preco_google = precos.get("imagem", 0.0336)
    preco_google_lote = precos.get("imagem_lote", 0.0168)
    return {
        "provedores": [
            {
                "id": "openrouter",
                "nome": "GPT-5.4 Image 2 (OpenRouter)",
                "modelo": MODELO_OPENROUTER_IMAGEM,
                "custo": f"US$ {precos.get('imagem_openrouter', 0.005):.4f}/imagem em qualidade baixa, no saldo do OpenRouter que a fábrica já usa",
                "descricao": "O padrão da fábrica: o GPT-5.4 Image 2 da OpenAI, em 16:9 e qualidade baixa, pela chave do OpenRouter.",
                "recomendado": True,
            },
            {
                "id": "google",
                "nome": "Nano Banana 2 Lite (Google)",
                "modelo": "gemini-3.1-flash-lite-image",
                "custo": f"US$ {preco_google:.4f}/imagem (ou US$ {preco_google_lote:.4f} no modo lote, metade do preço)",
                "descricao": "Ótima qualidade fotorrealista cobrada na mesma chave GEMINI_API_KEY que o resto da fábrica já usa.",
                "recomendado": False,
            },
            {
                "id": "kie",
                "nome": "Kie.ai (Grok Imagine 2.0)",
                "modelo": "grok-imagine-image-2-0/text-to-image",
                "custo": "cobrado à parte, em créditos da sua conta na Kie.ai",
                "descricao": "Geração fotorrealista com Grok Imagine 2.0 via Kie.ai, precisa de KIE_API_KEY no .env e saldo na Kie.",
                "recomendado": False,
            },
        ]
    }


@app.get("/api/nichos/buscar")
def buscar_nichos(q: str, dias: int = 30, limite: int = 40):
    """Vídeos recentes sobre o termo com visualização muito acima do tamanho do canal."""
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Digite um termo para buscar.")
    try:
        resultado = nichos.buscar(q.strip(), dias=dias, maximo=min(limite, 100))
    except SystemExit as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"videos": resultado}


@app.get("/api/nichos/canal/{canal_id}/videos")
def videos_do_canal_nicho(canal_id: str, pagina: Optional[str] = None):
    """Miniatura e título dos vídeos de um canal, paginado sob pedido."""
    try:
        return nichos.videos_do_canal(canal_id, pagina=pagina)
    except SystemExit as e:
        raise HTTPException(status_code=502, detail=str(e))


CHAVES_CONHECIDAS = [
    {
        "env": "GENAIPRO_API",
        "nome": "GenAIPro",
        "para_que": "Narração com as vozes e os modelos da ElevenLabs, pagando por créditos.",
        "obrigatoria": True,
        "sem_ela": "Só dá pra narrar com a voz grátis do Edge-TTS.",
        "onde": "genaipro.io",
    },
    {
        "env": "ELEVENLABS_API_KEY",
        "nome": "ElevenLabs (opcional)",
        "para_que": "Só efeitos sonoros e música, que a GenAIPro não faz.",
        "obrigatoria": False,
        "sem_ela": "Os vídeos saem sem efeitos sonoros novos.",
        "onde": "elevenlabs.io",
    },
    {
        "env": "GEMINI_API_KEY",
        "nome": "Google Gemini",
        "para_que": "Planeja as cenas e confere se o conteúdo bate com a narração (Corrigir Mídia).",
        "obrigatoria": False,
        "sem_ela": "O planejamento de cenas cai para o Claude Code pela assinatura.",
        "onde": "aistudio.google.com/apikey",
    },
    {
        "env": "GEMINI_API_KEY_IMAGE",
        "nome": "Google Gemini (imagens)",
        "para_que": "Gera as imagens de IA (Nano Banana), separada da chave de planejamento acima.",
        "obrigatoria": False,
        "sem_ela": "Usa a mesma GEMINI_API_KEY de cima pra gerar imagem também.",
        "onde": "aistudio.google.com/apikey",
    },
    {
        "env": "PEXELS_API_KEY",
        "nome": "Pexels",
        "para_que": "Banco de fotos e vídeos reais, de graça.",
        "obrigatoria": True,
        "sem_ela": "Perde uma das fontes de material real.",
        "onde": "pexels.com/api",
    },
    {
        "env": "PIXABAY_API_KEY",
        "nome": "Pixabay",
        "para_que": "Banco de fotos e vídeos reais, de graça.",
        "obrigatoria": True,
        "sem_ela": "Perde uma das fontes de material real.",
        "onde": "pixabay.com/api/docs",
    },
    {
        "env": "KIE_API_KEY",
        "nome": "Kie.ai",
        "para_que": "Geração de imagens com Grok Imagine 2.0.",
        "obrigatoria": False,
        "sem_ela": "As imagens são geradas pelo Google Gemini.",
        "onde": "kie.ai",
    },
    {
        "env": "YOUTUBE_API_KEY",
        "nome": "YouTube Data API",
        "para_que": "Procurar Nichos: achar vídeos virais e comparar canais.",
        "obrigatoria": False,
        "sem_ela": "A página Procurar Nichos não funciona.",
        "onde": "console.cloud.google.com",
    },
]


def _mascarar(valor: str) -> str:
    """Mostra só as pontas da chave. O valor cheio nunca sai do servidor."""
    v = (valor or "").strip()
    if not v:
        return ""
    if len(v) <= 10:
        return v[:2] + "…" * 6
    return f"{v[:4]}{'…' * 8}{v[-4:]}"


@app.get("/api/config/chaves")
def listar_chaves():
    """Diz quais chaves estão configuradas, sem devolver nenhuma delas por inteiro."""
    itens = []
    for c in CHAVES_CONHECIDAS:
        valor = os.environ.get(c["env"], "").strip()
        valida = bool(valor) and not valor.startswith("gsk_")
        itens.append({**c, "configurada": valida, "previa": _mascarar(valor) if valida else ""})
    return {"chaves": itens, "arquivo": str(RAIZ / ".env")}


def mesclar_env(texto: str, novas: Dict[str, str]) -> str:
    """Devolve o conteúdo do .env com as chaves novas aplicadas."""
    restantes = dict(novas)
    ja_escritas = set()
    saida = []
    for linha in texto.splitlines():
        crua = linha.strip()
        if crua and not crua.startswith("#") and "=" in crua:
            nome = crua.split("=", 1)[0].strip()
            if nome in novas:
                if nome in ja_escritas:
                    continue
                saida.append(f"{nome}={novas[nome]}")
                ja_escritas.add(nome)
                restantes.pop(nome, None)
                continue
        saida.append(linha)

    for nome, valor in restantes.items():
        saida.append(f"{nome}={valor}")

    return "\n".join(saida) + "\n"


def garantir_token() -> None:
    """Garante que sempre existe um FABRICA_TOKEN, mesmo na primeira vez que a fábrica roda."""
    if os.environ.get("FABRICA_TOKEN", "").strip():
        return
    token = secrets.token_urlsafe(32)
    env = RAIZ / ".env"
    atual = env.read_text(encoding="utf-8") if env.exists() else ""
    env.write_text(mesclar_env(atual, {"FABRICA_TOKEN": token}), encoding="utf-8")
    os.environ["FABRICA_TOKEN"] = token


garantir_token()
ytpub.iniciar_checador()


class ChavesEntrada(BaseModel):
    chaves: Dict[str, str]


@app.post("/api/config/chaves")
def salvar_chaves(entrada: ChavesEntrada):
    """Grava as chaves no .env, preservando o resto do arquivo."""
    conhecidas = {c["env"] for c in CHAVES_CONHECIDAS}
    novas = {}
    for nome, valor in (entrada.chaves or {}).items():
        if nome not in conhecidas:
            raise HTTPException(status_code=400, detail=f"Chave desconhecida: {nome}")
        valor = (valor or "").strip()
        if not valor:
            continue
        novas[nome] = "" if valor.lower() == "limpar" else valor

    if not novas:
        return {"ok": True, "atualizadas": []}

    env = RAIZ / ".env"
    atual = env.read_text(encoding="utf-8") if env.exists() else ""
    env.write_text(mesclar_env(atual, novas), encoding="utf-8")

    for nome, valor in novas.items():
        os.environ[nome] = valor

    return {"ok": True, "atualizadas": sorted(novas)}


@app.get("/api/projetos")
def listar_projetos():
    """Lista todos os projetos existentes em projetos/."""
    if not PROJETOS.exists():
        return {"projetos": []}

    lista = []
    for p in sorted(PROJETOS.iterdir()):
        if p.is_dir() and (p / "projeto.json").exists():
            try:
                info = json.loads((p / "projeto.json").read_text(encoding="utf-8"))
            except Exception:
                info = {}

            cenas_count = 0
            cenas_completas = False
            if (p / "cenas.json").exists():
                try:
                    cenas = json.loads((p / "cenas.json").read_text(encoding="utf-8")).get("cenas", [])
                    cenas_count = len(cenas)
                    # com a esteira ainda trabalhando não conta como pronto: a conferência tira e põe imagens
                    cenas_completas = (cenas_count > 0 and p.name not in CRIACOES_ATIVAS
                                       and not cenas_sem_arquivo(Projeto(p.name)))
                except (Exception, SystemExit):
                    pass

            duracao = 0.0
            if (p / "alinhamento.json").exists():
                try:
                    duracao = json.loads((p / "alinhamento.json").read_text(encoding="utf-8")).get("duracao", 0.0)
                except Exception:
                    pass

            lista.append({
                "nome": p.name,
                "perfil": info.get("perfil", ""),
                "offline": info.get("offline", False),
                "criado": info.get("criado", ""),
                "cenas_count": cenas_count,
                "duracao": duracao,
                "tem_final": (p / "final.mp4").exists(),
                "tem_narracao": (p / "narracao.wav").exists(),
                # o painel só libera o "Editar" quando nenhuma cena está sem imagem ou vídeo
                "cenas_completas": cenas_completas,
                # o que a esteira de criação está fazendo agora, para o painel não mostrar "processando" à toa
                "criacao": _resumo_criacao(p.name),
                "capa": _capa_do_projeto(p),
            })

    return {"projetos": lista}


def _resumo_criacao(nome: str) -> Dict[str, Any]:
    """rodando: a esteira está trabalhando neste vídeo agora. Senão, o último estado gravado dela."""
    with TAREFAS_LOCK:
        rodando = nome in CRIACOES_ATIVAS
        na_memoria = next((dict(t) for t in reversed(list(TAREFAS.values()))
                           if t.get("projeto") == nome and t.get("tipo") == "criacao"), None)
    estado = na_memoria or _ler_criacao(nome) or {}
    return {
        "rodando": rodando,
        "status": estado.get("status"),
        "mensagem": estado.get("mensagem"),
        "progresso_pct": estado.get("progresso_pct"),
        "aguardando_ate": estado.get("aguardando_ate"),
        "precisa_voce": bool(estado.get("precisa_voce")),
    }


def _capa_do_projeto(pasta: Path) -> Optional[str]:
    """Miniatura do projeto para o painel."""
    for sub, padroes in (("midia", ("*_capa.jpg", "*.jpg", "*.png")), ("imagens", ("*.png",))):
        origem = pasta / sub
        if not origem.is_dir():
            continue
        for padrao in padroes:
            achados = sorted(origem.glob(padrao))
            if achados:
                return f"/arquivos/{pasta.name}/{sub}/{achados[len(achados) // 2].name}"
    return None


@app.get("/api/projetos/{nome}")
def obter_projeto(nome: str):
    """Devolve status geral do projeto, tempo total e configurações."""
    pasta = PROJETOS / nome
    if not pasta.exists() or not (pasta / "projeto.json").exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")

    p = Projeto(nome)
    duracao = 0.0
    if p.existe("alinhamento.json"):
        duracao = p.ler_json("alinhamento.json").get("duracao", 0.0)

    cenas_count = 0
    if p.existe("cenas.json"):
        cenas_count = len(p.ler_json("cenas.json").get("cenas", []))

    roteiro_texto = ""
    if p.existe("roteiro.txt"):
        try:
            roteiro_texto = (pasta / "roteiro.txt").read_text(encoding="utf-8")
        except Exception:
            pass

    return {
        "nome": p.nome,
        "offline": p.offline,
        "duracao": duracao,
        "cenas_count": cenas_count,
        "perfil": p.perfil.get("nome", "?"),
        "roteiro": roteiro_texto,
        "tem_final": p.existe("final.mp4"),
        "tem_narracao": p.existe("narracao.wav"),
        "url_final": _url_com_versao(f"/arquivos/{nome}/final.mp4", p.caminho("final.mp4")) if p.existe("final.mp4") else None,
        "tem_final_vertical": p.existe("final_vertical.mp4"),
        "url_final_vertical": (_url_com_versao(f"/arquivos/{nome}/final_vertical.mp4", p.caminho("final_vertical.mp4"))
                               if p.existe("final_vertical.mp4") else None),
        "url_narracao": f"/arquivos/{nome}/narracao.wav" if p.existe("narracao.wav") else None,
        # MP3 leve para o player do editor; o WAV original continua para o render e para baixar
        # com a data da narração no endereço: trocar a voz troca o endereço, e o navegador não toca a gravação antiga
        "url_narracao_leve": (_url_com_versao(f"/arquivos_narracao/{nome}.mp3", p.pasta / "narracao.wav")
                              if p.existe("narracao.wav") else None),
        "legendas": obter_legendas_projeto(p),
        "voz": p.perfil.get("voz") or {},
        "imagens": p.perfil.get("imagens") or {},
        # enquanto a esteira trabalha, as cenas mudam por baixo: o editor mostra "em produção" e não renderiza
        "criacao": _resumo_criacao(nome),
    }


def _recusar_se_criando(nome: str, acao: str) -> None:
    """Renderizar ou salvar no meio da criação pega cenas trocando de imagem (sem arquivo por instantes) e,
    ao salvar, grava por cima o estado antigo que o editor carregou."""
    with TAREFAS_LOCK:
        criando = nome in CRIACOES_ATIVAS
    if criando:
        estado = _resumo_criacao(nome)
        raise HTTPException(status_code=409, detail=(
            f"O vídeo ainda está sendo criado ({estado.get('progresso_pct') or 0}%: {estado.get('mensagem') or ''}). "
            f"Espere terminar para {acao}; o editor avisa quando ficar pronto."))


# tarefas que trocam a imagem das cenas: o render não pode rodar junto (nem elas junto do render)
_MEXEM_NA_MIDIA = ("corrigir_", "continuar_", "limpeza_")


def _recusar_se_ocupado(nome: str, prefixos: tuple, acao: str) -> None:
    """O render lê o arquivo de cada cena minutos depois de montar a lista; o Corrigir Mídia troca esses arquivos.

    No nunca-deve-ter-dentro-de-casa-parte-2 os dois rodaram juntos: a cena 166 passou de imagem de IA para foto do
    Pexels no meio do render, o FFmpeg não achou imagens/0166.png e a tela ficou 20 min parada nos 32%."""
    with TAREFAS_LOCK:
        ativa = next((t for tid, t in TAREFAS.items() if t.get("projeto") == nome and tid.startswith(prefixos)
                      and t.get("status") in ("processando", "renderizando")), None)
    if ativa:
        andamento = ativa.get("mensagem") or ativa.get("etapa_atual") or ""
        raise HTTPException(status_code=409, detail=(
            f"Outra tarefa está mexendo neste vídeo ({ativa.get('progresso_pct') or 0}%: {andamento}). "
            f"Espere terminar para {acao}."))


@app.delete("/api/projetos/{nome}")
def apagar_projeto(nome: str):
    """Apaga a pasta inteira do projeto em projetos/<nome>."""
    pasta = PROJETOS / nome
    if not pasta.exists() or not (pasta / "projeto.json").exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")

    pasta_resolvida = pasta.resolve()
    raiz_resolvida = PROJETOS.resolve()
    if raiz_resolvida not in pasta_resolvida.parents:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    ultimo_erro = None
    for tentativa in range(5):
        try:
            shutil.rmtree(pasta_resolvida)
            return {"ok": True, "nome": nome}
        except PermissionError as e:
            ultimo_erro = e
            time.sleep(0.4)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Não foi possível apagar o projeto: {e}")

    raise HTTPException(
        status_code=409,
        detail=f"Não foi possível apagar o projeto: um arquivo ainda está em uso ({ultimo_erro}).",
    )


@app.get("/api/projetos/{nome}/custos")
def custos_reais_projeto(nome: str):
    """Gasto real (dinheiro de verdade já cobrado) deste vídeo."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    return custos_reais.resumo(Projeto(nome))


@app.get("/api/projetos/{nome}/legendas")
def obter_legendas(nome: str):
    """Devolve as legendas cronometradas a partir do legendas_tela.srt."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    p = Projeto(nome)
    return {"legendas": obter_legendas_projeto(p)}


@app.get("/api/projetos/{nome}/cenas")
def listar_cenas(nome: str):
    """Lê o cenas.json e devolve a lista completa de cenas enriquecida com URLs de mídia."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")

    p = Projeto(nome)
    if not p.existe("cenas.json"):
        return {"cenas": []}

    dados = p.ler_json("cenas.json")
    cenas_brutas = dados.get("cenas", [])
    motion = _motion_do_projeto(p)
    cenas_enriquecidas = [enriquecer_cena(p, c, motion) for c in cenas_brutas]
    # o editor abriu o projeto: as prévias de vídeo que faltam começam a ser feitas, na ordem das cenas
    if motion or any(c.get("previa_video_url") for c in cenas_enriquecidas):
        preparar_previas_video(nome)

    return {"cenas": cenas_enriquecidas, "sem_arquivo": sum(1 for c in cenas_enriquecidas if c["sem_arquivo"]),
            "motion": [_motion_para_o_editor(p, item) for item in motion]}


def _motion_do_projeto(p: Projeto) -> list:
    """As animações em dia do projeto (a camada por cima das cenas), ou [] se a etapa está desligada."""
    try:
        return animacoes.validas(p) if animacoes.config(p).get("ativo", True) else []
    except (OSError, KeyError, TypeError, ValueError):
        return []


def _motion_para_o_editor(p: Projeto, item: Dict[str, Any]) -> Dict[str, Any]:
    """Um bloco da faixa Motion do editor: onde começa e termina, o que mostra e a prévia transparente dela."""
    return {
        "id": item["id"], "ini": item["ini"], "fim": item["fim"],
        "modelo": item.get("modelo"), "visual": item.get("visual"), "texto": item.get("texto", ""),
        # a assinatura do render no endereço: animação refeita, endereço novo
        "url": f"/arquivos_previas/{p.nome}/motion/{item['id']}.webm?v={item.get('render') or ''}",
    }


@app.post("/api/projetos/{nome}/imagens/provedor")
def definir_provedor_imagem(nome: str, payload: ImagensAjustesPayload):
    """Troca qual IA gera as imagens só neste projeto."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    if payload.provedor not in PROVEDORES_IMAGEM:
        raise HTTPException(status_code=400, detail="provedor precisa ser 'openrouter', 'google' ou 'kie'.")
    p = Projeto(nome)
    p.definir_imagens_override({
        "provedor": payload.provedor,
        "modelo": payload.modelo or PROVEDORES_IMAGEM[payload.provedor],
    })
    return {"sucesso": True, "imagens": p.perfil.get("imagens") or {}}


_TRAVAS_DOS_PROJETOS: Dict[str, threading.Lock] = {}
_TRAVA_DAS_TRAVAS = threading.Lock()


def trava_do_projeto(nome: str) -> threading.Lock:
    """Uma alteração de cada vez no cenas.json de um projeto.

    Cada alteração lê o arquivo inteiro, trabalha e grava o arquivo inteiro de volta. Com duas trocas de cena ao
    mesmo tempo (cenas 123 e 124 do ouro-da-serra-gaucha), a segunda tinha lido o arquivo com a 123 ainda vazia,
    no meio da troca dela, e gravou essa cópia por cima: a 123 ficava sem imagem. Agora a segunda espera a
    primeira terminar e só então lê o arquivo."""
    with _TRAVA_DAS_TRAVAS:
        return _TRAVAS_DOS_PROJETOS.setdefault(nome, threading.Lock())


_REVISOES = {}  # projeto -> (data do revisao_video.json, dados): o editor lista centenas de cenas por vez
_REVISANDO = set()


def _revisao_atual(p: Projeto):
    arquivo = p.pasta / "revisao_video.json"
    if not arquivo.exists():
        return None
    chave = arquivo.stat().st_mtime_ns
    guardada = _REVISOES.get(p.nome)
    if not guardada or guardada[0] != chave:
        try:
            _REVISOES[p.nome] = (chave, revisao_video.resultado(p))
        except (OSError, ValueError):
            return None
    return _REVISOES[p.nome][1]


def iniciar_revisao_video(nome: str) -> bool:
    """Revisa o vídeo pronto numa linha à parte. Nunca atrapalha: se falhar, o vídeo está pronto do mesmo jeito."""
    p = Projeto(nome)
    if not revisao_video.ligada(p) or not p.existe("final.mp4"):
        return False
    with TAREFAS_LOCK:
        if nome in _REVISANDO:
            return True
        _REVISANDO.add(nome)

    def trabalhar():
        try:
            revisao_video.revisar(Projeto(nome), log=print)
        except (Exception, SystemExit) as erro:
            print(f"[revisão do vídeo] {nome}: {str(erro)[:160]}")
        finally:
            with TAREFAS_LOCK:
                _REVISANDO.discard(nome)

    threading.Thread(target=trabalhar, daemon=True, name=f"revisao-{nome}").start()
    return True


@app.get("/api/projetos/{nome}/revisao-video")
def ver_revisao_video(nome: str):
    """O que a revisão do vídeo pronto apontou, se ela é do final.mp4 de agora, e se ela está rodando."""
    if not (PROJETOS / nome).exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    p = Projeto(nome)
    dados = revisao_video.resultado(p) or {}
    return {"rodando": nome in _REVISANDO, "tem_video": p.existe("final.mp4"), "revisadas": dados.get("revisadas", 0),
            "cenas": dados.get("cenas", {}), "graves": dados.get("graves", []), "quando": dados.get("quando")}


@app.post("/api/projetos/{nome}/revisao-video")
def rodar_revisao_video(nome: str):
    """Revisa de novo o vídeo pronto, em segundo plano. Gratuito."""
    if not (PROJETOS / nome).exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    if not Projeto(nome).existe("final.mp4"):
        raise HTTPException(status_code=400, detail="Renderize o vídeo antes de revisar.")
    iniciar_revisao_video(nome)
    return {"rodando": True}


class AnimacaoPayload(BaseModel):
    acao: str = "gerar"  # "gerar" ou "remover" (a cena volta para a foto e fica assim)
    forcar: bool = False  # pede uma animação nova ao modelo mesmo se a atual estiver em dia


@app.post("/api/projetos/{nome}/cenas/{n}/animacao")
def animacao_da_cena(nome: str, n: int, payload: AnimacaoPayload):
    """Anima a cena (diagrama, texto na tela, linha do tempo ou mapa) ou faz ela voltar para a foto. Gratuito."""
    if not (PROJETOS / nome).exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    p = Projeto(nome)
    cena = next((c for c in p.ler_json("cenas.json").get("cenas", []) if c["n"] == n), None)
    if cena is None:
        raise HTTPException(status_code=404, detail=f"A cena {n} não existe.")
    trava = trava_do_projeto(nome)
    if payload.acao == "remover":
        animacoes.remover(p, n, trava=trava)
        resumo = {}
    else:
        if cena.get("visual") not in animacoes.tipos(p):
            raise HTTPException(status_code=400, detail="Só cenas de diagrama, texto na tela, linha do tempo ou mapa "
                                                        "viram animação.")
        if not animacoes.node_pronto():
            raise HTTPException(status_code=400, detail="Falta o Node.js 22 ou mais na máquina da fábrica "
                                                        "(nodejs.org) para fazer animações.")
        try:
            resumo = animacoes.gerar(p, numeros={n}, forcar=payload.forcar, log=print, trava=trava)
        except (Exception, SystemExit) as e:
            raise HTTPException(status_code=500, detail=f"Não consegui animar a cena: {e}")
        if n in resumo.get("falharam", {}):
            raise HTTPException(status_code=422, detail=f"A animação não passou na conferência e a cena ficou com a "
                                                        f"foto: {resumo['falharam'][n]}")
    cena = next(c for c in p.ler_json("cenas.json")["cenas"] if c["n"] == n)
    item = animacoes.da_cena(p, cena)
    if item is not None:
        try:
            # a prévia transparente que o editor toca na faixa Motion já sai pronta
            animacoes.previa_da_camada(p, item, criar=True)
        except (OSError, KeyError, TypeError, ValueError, RuntimeError) as erro:
            print(f"[animação] prévia da cena {n} de {nome}: {str(erro)[:160]}")
    preparar_previas_video(nome)
    return {"sucesso": True, "cena": enriquecer_cena(p, cena), "resumo": resumo}


@app.delete("/api/projetos/{nome}/motion/{ident}")
def excluir_motion(nome: str, ident: str):
    """Exclui uma animação da faixa Motion (ou todas, com ident "todos"). Gratuito; vale no próximo render."""
    if not (PROJETOS / nome).exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    p = Projeto(nome)
    excluidas = animacoes.remover_item(p, ident)
    if not excluidas:
        raise HTTPException(status_code=404, detail="Essa animação não existe ou já foi excluída.")
    return {"sucesso": True, "excluidas": excluidas,
            "motion": [_motion_para_o_editor(p, item) for item in _motion_do_projeto(p)]}


@app.post("/api/projetos/{nome}/cenas/{n}/refazer")
def refazer_cena(nome: str, n: int, payload: RefazerCenaPayload):
    """Executa imagens.refazer() para a cena n com novos termos de busca ou prompt."""
    with trava_do_projeto(nome):
        return _refazer_cena(nome, n, payload)


def _refazer_cena(nome: str, n: int, payload: RefazerCenaPayload):
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")

    p = Projeto(nome)
    forcar_ia = payload.forcar_ia or payload.tipo == "ia"
    prompt = payload.prompt
    busca = payload.busca
    tipo = payload.tipo

    try:
        imagens.refazer(p, [n], prompt=prompt, busca=busca, forcar_ia=forcar_ia, log=print, tipo=tipo)
        if tipo in ("foto_real", "video_real"):
            dados = p.ler_json("cenas.json")
            for c in dados.get("cenas", []):
                if c["n"] == n:
                    c["tipo"] = tipo
                    break
            p.salvar_json("cenas.json", dados)
    except imagens.SemCota as e:
        raise HTTPException(status_code=402, detail=str(e))
    except (Exception, SystemExit) as e:
        msg = str(e)
        if any(w in msg.lower() for w in ("saldo", "crédito", "credito", "cota", "insufficient", "balance")):
            raise HTTPException(status_code=402, detail=msg)
        raise HTTPException(status_code=500, detail=f"Erro ao refazer cena: {msg}")

    dados = p.ler_json("cenas.json")
    cena = next((c for c in dados.get("cenas", []) if c["n"] == n), None)
    if not cena:
        raise HTTPException(status_code=500, detail="Cena não encontrada após recriação.")

    cena_info = enriquecer_cena(p, cena)
    return {
        "sucesso": True,
        "cena": n,
        "tipo": cena_info["tipo"],
        "url_midia": cena_info["url_midia"],
        "ini": cena_info["ini"],
        "fim": cena_info["fim"],
        "origem_badge": cena_info["origem_badge"],
    }


@app.post("/api/projetos/{nome}/cenas/{n}/upload")
async def upload_cena_midia(nome: str, n: int, file: UploadFile = File(...)):
    """Recebe um arquivo (multipart/form-data) e substitui a mídia da cena n."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")

    p = Projeto(nome)
    conteudo = await file.read()
    def com_trava():
        with trava_do_projeto(nome):
            antes = next((c for c in p.ler_json("cenas.json").get("cenas", []) if c["n"] == n), None)
            resultado = definir_midia_manual(p, n, conteudo, file.filename or "upload.png")
            if antes:
                aprendizados.registrar(p, antes, "upload")
            return resultado

    cena_atualizada = await asyncio.to_thread(com_trava)
    cena_info = enriquecer_cena(p, cena_atualizada)

    return {
        "sucesso": True,
        "cena": n,
        "tipo": cena_info["tipo"],
        "url_midia": cena_info["url_midia"],
        "ini": cena_info["ini"],
        "fim": cena_info["fim"],
        "origem_badge": cena_info["origem_badge"],
    }


class RestoreAntigaPayload(BaseModel):
    name: str
    n: int
    filename: str


@app.get("/api/project/scene/antigas")
def listar_antigas(name: str = Query(...), n: int = Query(...)):
    """Lista versões anteriores de mídia salvas na pasta antigas/ para a cena n."""
    pasta = PROJETOS / name
    if not pasta.exists():
        return {"antigas": []}
    antigas_dir = pasta / "antigas"
    if not antigas_dir.exists():
        return {"antigas": []}

    padrao = f"{n:04d}*"
    resultado = []
    for arq in sorted(antigas_dir.glob(padrao), reverse=True):
        ext = arq.suffix.lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".webm"):
            is_video = ext in (".mp4", ".mov", ".webm")
            resultado.append({
                "filename": arq.name,
                "url": f"/arquivos/{name}/antigas/{arq.name}",
                "is_video": is_video,
            })
    return {"antigas": resultado}


@app.post("/api/project/scene/restore-antiga")
def restaurar_antiga(payload: RestoreAntigaPayload):
    """Restaura um arquivo da pasta antigas/ como a mídia ativa da cena n."""
    with trava_do_projeto(payload.name):
        return _restaurar_antiga(payload)


def _restaurar_antiga(payload: RestoreAntigaPayload):
    pasta = PROJETOS / payload.name
    if not pasta.exists():
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    arq_antigo = pasta / "antigas" / payload.filename
    if not arq_antigo.exists():
        raise HTTPException(status_code=404, detail="Arquivo antigo não encontrado.")

    p = Projeto(payload.name)
    dados = p.ler_json("cenas.json")
    cena = next((c for c in dados.get("cenas", []) if c["n"] == payload.n), None)
    if not cena:
        raise HTTPException(status_code=404, detail="Cena não encontrada.")

    ext = arq_antigo.suffix.lower()
    is_video = ext in (".mp4", ".mov", ".webm")

    if is_video:
        rel_path = f"midia/{payload.n:04d}{ext}"
        destino = p.pasta / rel_path
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(arq_antigo), str(destino))

        capa_antiga = arq_antigo.with_name(arq_antigo.stem + "_capa.jpg")
        capa_rel = f"midia/{payload.n:04d}_capa.jpg"
        if capa_antiga.exists():
            shutil.copy2(str(capa_antiga), str(p.pasta / capa_rel))
        else:
            try:
                _frame_do_video(destino, p.pasta / capa_rel, 0.5)
            except Exception:
                capa_rel = None

        cena["tipo"] = "video_real"
        cena["midia"] = {
            "fonte": "restaurado",
            "id": f"restaurado_{payload.n}",
            "tipo": "video",
            "arquivo": rel_path,
            "capa": capa_rel or rel_path,
        }
    else:
        destino = p.imagem(payload.n)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(arq_antigo), str(destino))
        cena["tipo"] = "ia"
        cena["midia"] = None

    p.salvar_json("cenas.json", dados)
    return {"sucesso": True, "cena": payload.n, "tipo": cena["tipo"]}


@app.post("/api/projetos/{nome}/narracao")
def refazer_narracao(nome: str, payload: NarracaoPayload):
    """Atualiza o roteiro (se fornecido) e regera a narração."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")

    _recusar_se_criando(nome, "trocar a narração")
    p = Projeto(nome)
    antes = corrigir.falas_do_material(p)

    if payload.roteiro is not None:
        (pasta / "roteiro.txt").write_text(payload.roteiro, encoding="utf-8")

    if payload.voz is not None:
        p.definir_voz_override(payload.voz.dict(exclude_unset=True))
    if payload.velocidade and not (payload.voz and payload.voz.velocidade_edge):
        p.definir_voz_override({"velocidade_edge": payload.velocidade})

    if payload.nova_voz:
        shutil.rmtree(pasta / "narracao", ignore_errors=True)

    try:
        duracao = narracao.narrar(p, log=print)
        if p.existe("cenas.json"):
            cenas.atualizar_tempos(p)
    except (Exception, SystemExit) as e:
        raise HTTPException(status_code=500, detail=f"Falha ao gerar narração: {str(e)}")

    preenchendo = _completar_depois_da_narracao(p, antes) if p.existe("cenas.json") else None
    alinhamento = p.ler_json("alinhamento.json") if p.existe("alinhamento.json") else {}
    motion = _motion_do_projeto(p)
    cenas_atualizadas = [enriquecer_cena(p, c, motion) for c in p.ler_json("cenas.json").get("cenas", [])]

    return {
        "sucesso": True,
        "duracao": duracao,
        "cenas": cenas_atualizadas,
        "alinhamento": alinhamento,
        "preenchendo": preenchendo,
    }


def _completar_depois_da_narracao(p: Projeto, antes: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Trocar a narração nunca pode deixar o vídeo com cena faltando nem com imagem que não combina.

    A voz nova muda o ritmo: as cenas se dividem, se juntam e mudam de fala. Aqui a mesma esteira da criação volta a
    andar a partir da busca, sozinha: busca de acervo com a conferência na captura, conferência do Jev, imagens de
    IA (se ligada), cenas completadas, nenhuma imagem repetida, animações e trilha. O Jev julga só o que mudou: as
    cenas sem imagem e as que continuam com a foto antiga mas com outra fala. O editor mostra "Em produção" e o
    render fica travado até terminar."""
    mudou = corrigir.depois_da_narracao(p, antes)
    vazias, mudaram, repetidas, alvo = mudou["vazias"], mudou["mudaram"], mudou["repetidas"], mudou["alvo"]
    if not alvo:
        return None
    with trava_do_projeto(p.nome):
        midia.soltar_repetidas(p)  # a cópia sai antes: o Jev não gasta julgando uma foto que vai sair
    task_id = f"criar_{p.nome}_{datetime.now():%Y%m%d_%H%M%S}"
    iniciar_criacao(p.nome, {
        "tarefa_id": task_id, "projeto": p.nome, "tipo": "criacao", "status": "processando", "concluido": False,
        "pronto_para_edicao": False, "erro": None, "precisa_voce": False, "inicio": datetime.now().isoformat(),
        "mensagem": "A narração mudou: completando e conferindo as cenas...", "passo_atual": 3, "total_passos": 5,
        "progresso_pct": 60, "logs": [f"Narração trocada: {len(vazias)} cena(s) sem imagem, {len(mudaram)} com outra "
                                      f"fala e {len(repetidas)} com imagem repetida voltam para a esteira"],
        "feitas": ["mapa", "narracao", "cenas"],
        "conferir_cenas": sorted(alvo), "conferir_forcadas": sorted(mudaram - vazias),
    })
    return {"tarefa_id": task_id, "sem_imagem": sorted(vazias), "outra_fala": sorted(mudaram),
            "repetidas": sorted(repetidas)}


@app.post("/api/projetos/{nome}/cenas/salvar")
def salvar_cenas(nome: str, payload: SalvarCenasPayload):
    """Salva diretamente alterações no array de cenas em cenas.json."""
    with trava_do_projeto(nome):
        return _salvar_cenas(nome, payload)


def _salvar_cenas(nome: str, payload: SalvarCenasPayload):
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    _recusar_se_criando(nome, "salvar alterações")

    p = Projeto(nome)
    cenas_file = pasta / "cenas.json"

    # Backup de segurança
    if cenas_file.exists():
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(cenas_file, pasta / f"cenas_backup_{carimbo}.json")

    # Limpa campos transitórios injetados pela API
    cenas_limpas = []
    for c in payload.cenas:
        c_copia = {k: v for k, v in c.items() if not k.startswith("url_") and k not in ("img_ia_existe", "midia_existe", "origem_badge")}
        cenas_limpas.append(c_copia)

    p.salvar_json("cenas.json", {"cenas": cenas_limpas})
    return {"sucesso": True, "cenas_count": len(cenas_limpas)}


@app.post("/api/projetos/{nome}/render")
def disparar_render(nome: str, payload: RenderPayload, bg_tasks: BackgroundTasks):
    """Dispara a montagem e renderização do vídeo (FFmpeg) em segundo plano."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    _recusar_se_criando(nome, "renderizar")
    _recusar_se_ocupado(nome, _MEXEM_NA_MIDIA, "renderizar")

    p = Projeto(nome)
    task_id = f"render_{nome}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if payload.opcoes:
        cfg = p.config.get("render") or {}
        if payload.opcoes.fps:
            cfg["fps"] = payload.opcoes.fps
        p.config["render"] = cfg

    with TAREFAS_LOCK:
        TAREFAS[task_id] = {
            "projeto": nome,
            "status": "renderizando",
            "progresso_pct": 5,
            "etapa_atual": "Iniciando a versão em pé (9:16)..." if payload.vertical else "Iniciando montagem com FFmpeg...",
            "concluido": False,
            "logs": ["Iniciando renderização da versão em pé..." if payload.vertical else "Iniciando renderização..."],
            "vertical": payload.vertical,
            "inicio": time.time(),
            "sucesso": False,
            "tarefa_id": task_id,
        }

    def render_worker():
        try:
            total_clipes = 1
            clipes_prontos = 0

            def log_fn(msg):
                nonlocal total_clipes, clipes_prontos
                msg_str = str(msg)
                with TAREFAS_LOCK:
                    if task_id in TAREFAS:
                        TAREFAS[task_id]["logs"].append(msg_str)
                        if "clipes para renderizar" in msg_str:
                            m = re.search(r"(\d+)\s+clipes para renderizar", msg_str)
                            if m:
                                total_clipes = max(1, int(m.group(1)))
                                TAREFAS[task_id]["progresso_pct"] = 10
                                TAREFAS[task_id]["etapa_atual"] = f"Preparando {total_clipes} cenas para renderizar..."
                        elif "clipes " in msg_str and "/" in msg_str:
                            m = re.search(r"clipes\s+(\d+)/(\d+)", msg_str)
                            if m:
                                cur = int(m.group(1))
                                tot = max(1, int(m.group(2)))
                                pct = int(10 + (cur / tot) * 75)
                                TAREFAS[task_id]["progresso_pct"] = min(88, pct)
                                TAREFAS[task_id]["etapa_atual"] = f"Montando clipe da cena {cur} de {tot} com FFmpeg"
                        elif "juntando" in msg_str:
                            TAREFAS[task_id]["progresso_pct"] = 90
                            TAREFAS[task_id]["etapa_atual"] = "Concatenando cenas e aplicando transições..."
                        elif "mixando" in msg_str or "música" in msg_str:
                            TAREFAS[task_id]["progresso_pct"] = 95
                            TAREFAS[task_id]["etapa_atual"] = "Mixando áudio final e trilha sonora..."

            sem_avatar = payload.sem_avatar
            final_path = render.renderizar(p, log=log_fn, sem_avatar=sem_avatar, vertical=payload.vertical)

            tamanho_mb = 0.0
            if Path(final_path).exists():
                tamanho_mb = round(Path(final_path).stat().st_size / (1024 * 1024), 1)

            dur = 0.0
            if p.existe("alinhamento.json"):
                try:
                    dur = p.ler_json("alinhamento.json").get("duracao", 0.0)
                except Exception:
                    pass
            m = int(dur // 60)
            s = int(dur % 60)
            dur_str = f"{m:02d}:{s:02d}"

            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id]["status"] = "concluido"
                    TAREFAS[task_id]["sucesso"] = True
                    TAREFAS[task_id]["concluido"] = True
                    TAREFAS[task_id]["progresso_pct"] = 100
                    TAREFAS[task_id]["etapa_atual"] = ("Versão em pé renderizada com sucesso!" if payload.vertical
                                                       else "Vídeo final renderizado com sucesso!")
                    TAREFAS[task_id]["final_mp4"] = str(final_path)
                    TAREFAS[task_id]["video_url"] = _url_com_versao(f"/arquivos/{nome}/{Path(final_path).name}", Path(final_path))
                    TAREFAS[task_id]["duracao"] = dur_str
                    TAREFAS[task_id]["tamanho_mb"] = tamanho_mb
                    TAREFAS[task_id]["logs"].append("Vídeo renderizado com sucesso!")
            try:
                if not payload.vertical:  # a revisão olha o final.mp4; a versão em pé tem as mesmas cenas
                    iniciar_revisao_video(nome)  # o modelo olha o vídeo pronto em segundo plano; nunca falha o render
            except (Exception, SystemExit) as erro_rev:
                print(f"[revisão do vídeo] {nome}: {str(erro_rev)[:160]}")
        except (Exception, SystemExit) as err:
            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id]["status"] = "erro"
                    TAREFAS[task_id]["concluido"] = False
                    TAREFAS[task_id]["erro"] = str(err)
                    TAREFAS[task_id]["etapa_atual"] = f"Erro na renderização: {str(err)}"
                    TAREFAS[task_id]["logs"].append(f"[ERRO]: {str(err)}")

    bg_tasks.add_task(render_worker)
    return JSONResponse(
        status_code=202,
        content={
            "sucesso": True,
            "status": "renderizando",
            "mensagem": "Renderização iniciada em segundo plano.",
            "tarefa_id": task_id,
        }
    )


@app.get("/api/projetos/{nome}/verificar")
def verificar_midia(nome: str):
    """Aponta mídia suspeita nas cenas (id inventado, arquivo duplicado ou sumido), sem mudar nada."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    p = Projeto(nome)
    return {
        "avisos": verificar.verificar(p),
        "avisos_contexto": verificar.verificar_contexto_visual(p),
    }


class CorrigirMidiaPayload(BaseModel):
    """Tudo opcional: o botão Corrigir Mídia do editor chama sem corpo."""
    cenas: Optional[List[int]] = None  # só essas cenas
    rodadas: Optional[int] = None
    nota_minima: Optional[int] = None
    ia: bool = False  # só gera imagem de IA nas que sobrarem se isto vier true, o que quem chama confirma como custo
    # o diretor (diretor.py) lê o roteiro inteiro e decide o que muda antes da conferência do Jev. Sem o campo, ele
    # entra quando a IA está ligada (ia.ativa), porque a cena que mostra outra coisa recebe IA obrigatoriamente
    diretor: Optional[bool] = None


def _atualizar_progresso(task_id: str, msg: str):
    with TAREFAS_LOCK:
        t = TAREFAS.get(task_id)
        if not t:
            return
        t["logs"].append(str(msg))
        m = str(msg)
        rodada = re.search(r"rodada (\d+)", m)
        if "buscando outro material" in m:
            t["mensagem"] = "Buscando outro material real, de graça..."
        elif rodada:
            t["progresso_pct"] = min(90, 30 + 20 * int(rodada.group(1)))
            t["mensagem"] = "Conferindo se o material combina com a narração..."
        elif "cena(s) de material real ainda sem arquivo" in m:
            t["progresso_pct"] = 15
            t["mensagem"] = "Buscando material real para as cenas sem arquivo..."


@app.get("/api/projetos/{nome}/qualidade")
def qualidade_do_projeto(nome: str):
    """A nota do vídeo: quanto das cenas mostra o que a fala diz, quantas mostram outra coisa, de onde veio cada
    imagem, e o histórico (fim da criação, de cada Corrigir). Grátis: só lê as notas que o Jev já deu."""
    if not (PROJETOS / nome).exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    p = Projeto(nome)
    historico = p.ler_json("qualidade.json").get("historico", []) if p.existe("qualidade.json") else []
    return {"atual": qualidade.calcular(p), "historico": historico,
            "texto": qualidade.formatar(qualidade.calcular(p))}


@app.post("/api/projetos/{nome}/limpar-midia")
@app.post("/api/projetos/{nome}/corrigir-midia")
def corrigir_midia(nome: str, bg_tasks: BackgroundTasks, payload: Optional[CorrigirMidiaPayload] = None):
    """Botão Corrigir Mídia: confere se o material real de cada cena combina com a narração e troca o que não combina.

    Só olha foto e vídeo de acervo. Imagens de IA são ignoradas. As trocas são de graça (outra busca em Pexels, Pixabay
    e Wikimedia). Só gera imagem de IA se o corpo trouxer ia=true. O resultado mantém as chaves que o editor já lê."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    payload = payload or CorrigirMidiaPayload()
    _recusar_se_ocupado(nome, ("render_",) + _MEXEM_NA_MIDIA, "corrigir a mídia")
    p = Projeto(nome)
    task_id = f"corrigir_{nome}_{datetime.now():%Y%m%d_%H%M%S}"
    with TAREFAS_LOCK:
        TAREFAS[task_id] = {
            "tarefa_id": task_id, "projeto": nome, "tipo": "limpeza", "status": "processando",
            "mensagem": "Preparando a conferência de mídia...", "progresso_pct": 5, "logs": [],
            "resultado": None, "inicio": datetime.now().isoformat(),
        }

    def trabalho():
        from . import gemini_local, groq_local, openrouter_local

        def log_w(msg):
            _atualizar_progresso(task_id, msg)

        try:
            cfg = p.config.get("corrigir") or {}
            usos = {"groq": groq_local, "gemini": gemini_local, "jev": openrouter_local}
            modulo_uso = usos.get(corrigir.provedor(p), groq_local)
            antes = modulo_uso.resumo_uso(p) or {}
            numeros = set(payload.cenas) if payload.cenas else None

            prep = corrigir.preparar_gratis(p, log=log_w)
            # primeira ação: o diretor, que conhece o roteiro inteiro, aponta e resolve as cenas que mostram outra coisa
            usar_diretor = payload.diretor if payload.diretor is not None else midia.ia_ativa(p)
            resultado_diretor = None
            if usar_diretor:
                _atualizar_progresso(task_id, "  o diretor está lendo o roteiro inteiro e revisando as cenas")
                decisoes = diretor.revisar(p, log=log_w)
                if numeros:
                    decisoes = {**decisoes, "mudar": [m for m in decisoes["mudar"] if m["n"] in numeros]}
                resultado_diretor = {**diretor.aplicar(p, decisoes, log=log_w), "decisoes": decisoes["mudar"]}
            total = len(corrigir.conferiveis(p, numeros))
            log_w(f"  conferindo {total} cena(s) de material real (cenas de IA ficam de fora)")
            resumo = corrigir.corrigir(
                p, numeros=numeros, rodadas=payload.rodadas or cfg.get("rodadas", corrigir.RODADAS),
                nota_minima=payload.nota_minima or cfg.get("nota_minima", corrigir.NOTA_MINIMA), log=log_w)

            # com a IA ligada, as cenas que mostravam outra coisa já saíram com imagem de IA (corrigir.resolver_com_ia)
            geradas = len(resumo.get("geradas_com_ia") or []) + len((resultado_diretor or {}).get("ia") or [])
            if payload.ia and resumo["precisam_ia"]:
                log_w(f"  gerando {len(resumo['precisam_ia'])} imagem(ns) de IA, pedido explícito de quem chamou")
                corrigir.regerar_com_ia(p, resumo["precisam_ia"], log=log_w)
                geradas += len(resumo["precisam_ia"])

            depois = modulo_uso.resumo_uso(p) or {}
            reprovadas = resumo["avaliadas"] - resumo["aprovadas_de_primeira"]
            resolvidas = max(0, reprovadas - len(resumo["precisam_ia"]) + geradas)
            resultado = {
                # chaves que o editor já lê
                "cenas_com_problema_no_inicio": prep["suspeitas"],
                "cenas_resolvidas_com_material_real": prep["resolvidas"],
                "sem_arquivo_antes": prep.get("sem_arquivo_antes", 0),
                "sem_arquivo_resolvidas": prep.get("sem_arquivo_resolvidas", 0),
                "imagens_ia_geradas": geradas,
                "imagens_ia_com_falha": [],
                "avisos_restantes": [],
                "cenas_conteudo_incompativel": reprovadas,
                "cenas_conteudo_corrigidas": resolvidas,
                # novas
                "avaliadas": resumo["avaliadas"],
                "trocadas": resumo["trocadas"],
                "restauradas": resumo.get("restauradas", []),
                "precisam_ia": resumo["precisam_ia"],
                "para_revisar": resumo.get("para_revisar", []),
                "sem_conferencia": resumo["sem_conferencia"],
                "provedor": corrigir.provedor(p),
                "custo_usd": round(depois.get("custo", 0) - antes.get("custo", 0), 4),
                "mensagem": corrigir.formatar(resumo),
                "diretor": resultado_diretor,
                "qualidade": qualidade.registrar(p, "corrigir mídia", log_w),
            }
            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id].update(status="concluido", progresso_pct=100,
                                            mensagem="Conferência concluída.", resultado=resultado)
        except (Exception, SystemExit) as err:
            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id].update(status="erro", erro=str(err), mensagem=f"Erro na conferência: {err}")

    bg_tasks.add_task(trabalho)
    return JSONResponse(status_code=202, content={
        "sucesso": True, "status": "processando",
        "mensagem": "Conferência de mídia iniciada em segundo plano.", "tarefa_id": task_id})


def _preco_medio_do_jev(p: Projeto) -> float:
    """Custo médio de uma chamada do Jev, medido no uso_jev.json do projeto (uns US$ 0,00005)."""
    try:
        chamadas = json.loads((p.pasta / "uso_jev.json").read_text(encoding="utf-8"))
        if chamadas:
            return sum(c.get("custo_usd", 0) or 0 for c in chamadas) / len(chamadas)
    except (OSError, ValueError):
        pass
    return 0.00005


class ContinuarPayload(BaseModel):
    confirmar: bool = False  # sem isto só devolve o que falta e quanto custa, sem fazer nada


@app.post("/api/projetos/{nome}/continuar")
def continuar_carregamento(nome: str, bg_tasks: BackgroundTasks, payload: Optional[ContinuarPayload] = None):
    """Botão Continuar carregamento: termina o que faltou depois de uma interrupção (servidor reiniciado, cota, queda).

    Busca o material real das cenas que ainda esperam por ele e gera as imagens de IA que faltam. Cada etapa continua
    de onde parou, sem refazer o que já está pronto. Sem confirmar=true só calcula o que falta e o custo."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    p = Projeto(nome)
    if not p.existe("cenas.json"):
        raise HTTPException(status_code=409, detail="O projeto ainda não tem cenas. Crie o projeto de novo.")
    cenas_lista = p.ler_json("cenas.json")["cenas"]
    sem_acervo = [c["n"] for c in cenas_lista if midia.pendente(c)]
    sem_ia = [c["n"] for c in imagens.pendentes_ia(p, cenas_lista)]
    preco = custos.preco_da_imagem(p)
    # das cenas que ainda vão ao acervo, uma parte não acha material e cai para IA; com a IA desligada, nenhuma cai
    custo_ia = (len(sem_ia) + (0.15 * len(sem_acervo) if midia.ia_ativa(p) else 0)) * preco
    # a busca nos bancos é grátis; o Jev confere até candidatos_conferidos fotos por cena, e mais uma conferência
    por_jev = _preco_medio_do_jev(p)
    conferidos = int((p.config.get("midia") or {}).get("candidatos_conferidos", 3))
    custo = round(custo_ia + len(sem_acervo) * (conferidos + 1) * por_jev, 4)
    resumo = {"sem_acervo": len(sem_acervo), "sem_imagem_ia": len(sem_ia), "custo_estimado_usd": custo,
              "preco_por_imagem_usd": preco, "nada_a_fazer": not sem_acervo and not sem_ia}
    if not (payload and payload.confirmar) or resumo["nada_a_fazer"]:
        return resumo
    _recusar_se_ocupado(nome, ("render_",) + _MEXEM_NA_MIDIA, "continuar o carregamento")

    task_id = f"continuar_{nome}_{datetime.now():%Y%m%d_%H%M%S}"
    with TAREFAS_LOCK:
        TAREFAS[task_id] = {
            "tarefa_id": task_id, "projeto": nome, "tipo": "limpeza", "status": "processando",
            "mensagem": "Continuando o carregamento...", "progresso_pct": 5, "logs": [],
            "resultado": None, "inicio": datetime.now().isoformat(),
        }

    def trabalho():
        def log_w(msg):
            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id]["logs"].append(str(msg))

        try:
            if sem_acervo:
                with TAREFAS_LOCK:
                    TAREFAS[task_id].update(progresso_pct=20, mensagem="Buscando fotos e vídeos de acervo...")
                midia.buscar(p, log=log_w)
            with TAREFAS_LOCK:
                TAREFAS[task_id].update(progresso_pct=60, mensagem="Gerando as imagens de IA que faltam...")
            imagens.gerar(p, log=log_w)
            depois = imagens.pendentes_ia(p, p.ler_json("cenas.json")["cenas"])
            with TAREFAS_LOCK:
                TAREFAS[task_id].update(status="concluido", progresso_pct=100, mensagem="Carregamento concluído.",
                                        resultado={**resumo, "ainda_faltam": [c["n"] for c in depois]})
        except (Exception, SystemExit) as err:
            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id].update(status="erro", erro=str(err), mensagem=f"Erro ao continuar: {err}")

    bg_tasks.add_task(trabalho)
    return JSONResponse(status_code=202, content={**resumo, "sucesso": True, "status": "processando", "tarefa_id": task_id})


@app.post("/api/projetos/{nome}/limpar-midia-completo")
def limpar_midia(nome: str, bg_tasks: BackgroundTasks):
    """Fluxo antigo: varre mídia suspeita e, no fim, gera imagem de IA sem pedir confirmação de custo. Não é o botão."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")

    _recusar_se_ocupado(nome, ("render_",) + _MEXEM_NA_MIDIA, "limpar a mídia")
    p = Projeto(nome)
    task_id = f"limpeza_{nome}_{datetime.now():%Y%m%d_%H%M%S}"
    with TAREFAS_LOCK:
        TAREFAS[task_id] = {
            "tarefa_id": task_id,
            "projeto": nome,
            "tipo": "limpeza",
            "status": "processando",
            "mensagem": "Procurando mídia suspeita...",
            "progresso_pct": 5,
            "logs": [],
            "resultado": None,
            "inicio": datetime.now().isoformat(),
        }

    def limpeza_worker():
        def log_w(msg):
            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id]["logs"].append(str(msg))
                    msg_str = str(msg)
                    if "cena(s) com m" in msg_str:
                        TAREFAS[task_id]["progresso_pct"] = 15
                        TAREFAS[task_id]["mensagem"] = "Buscando material real de graça..."
                    elif "precisam de imagem de IA" in msg_str:
                        TAREFAS[task_id]["progresso_pct"] = 55
                        TAREFAS[task_id]["mensagem"] = "Gerando imagens de IA pro que sobrou..."
                    elif "analisando o conte" in msg_str:
                        TAREFAS[task_id]["progresso_pct"] = 75
                        TAREFAS[task_id]["mensagem"] = "Gemini conferindo se o conteúdo bate com a narração..."
                    elif "conteúdo incompat" in msg_str and "corrigindo" in msg_str:
                        TAREFAS[task_id]["progresso_pct"] = 90
                        TAREFAS[task_id]["mensagem"] = "Corrigindo cenas com conteúdo incompatível..."
                    elif "tentativa" in msg_str:
                        TAREFAS[task_id]["progresso_pct"] = max(TAREFAS[task_id]["progresso_pct"], 60)

        prov_atual = ((p.perfil.get("imagens") or {}).get("provedor") or "kie").lower()
        mod_atual = (p.perfil.get("imagens") or {}).get("modelo") or (MODELO_KIE if prov_atual in ("kie", "kie.ai") else MODELO_GOOGLE)
        imagens_original = dict(p.perfil.get("imagens") or {})
        p.perfil["imagens"] = {**imagens_original, "provedor": prov_atual, "modelo": mod_atual}
        try:
            resultado = limpeza.limpar(p, log=log_w)
            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id]["status"] = "concluido"
                    TAREFAS[task_id]["progresso_pct"] = 100
                    TAREFAS[task_id]["mensagem"] = "Limpeza concluída."
                    TAREFAS[task_id]["resultado"] = resultado
        except (Exception, SystemExit) as err:
            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id]["status"] = "erro"
                    TAREFAS[task_id]["erro"] = str(err)
                    TAREFAS[task_id]["mensagem"] = f"Erro na limpeza: {err}"
        finally:
            p.perfil["imagens"] = imagens_original

    bg_tasks.add_task(limpeza_worker)
    return JSONResponse(
        status_code=202,
        content={
            "sucesso": True,
            "status": "processando",
            "mensagem": "Limpeza de mídia iniciada em segundo plano.",
            "tarefa_id": task_id,
        }
    )


@app.get("/api/projetos/{nome}/status")
def status_projeto(nome: str, task_id: Optional[str] = None):
    """Retorna o progresso em tempo real da tarefa de renderização ou criação.

    pago_pendente: os gratuitos esgotaram e a tarefa espera a pessoa liberar o modelo pago (pago.py). Vai em toda
    resposta, porque o editor acompanha cada tarefa por aqui."""
    resposta = _status_projeto(nome, task_id)
    if isinstance(resposta, dict):
        resposta["pago_pendente"] = pago.pendente(nome)
    return resposta


class PagoPayload(BaseModel):
    liberar: bool = False


@app.get("/api/projetos/{nome}/pago")
def pago_do_projeto(nome: str):
    """Os gratuitos esgotaram? (o pedido em aberto, ou None) e se o pago já está liberado hoje."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    p = Projeto(nome)
    return {"pendente": pago.pendente(nome), "liberado_hoje": pago.liberado(p), "confirmar_pago": pago.confirmar(p)}


@app.post("/api/projetos/{nome}/pago")
def liberar_pago(nome: str, payload: PagoPayload):
    """A pessoa liberou o modelo pago neste projeto até o fim do dia: a tarefa que esperava segue na hora."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    p = Projeto(nome)
    if payload.liberar:
        pago.liberar(p)
    return {"pendente": pago.pendente(nome), "liberado_hoje": pago.liberado(p)}


def _status_projeto(nome: str, task_id: Optional[str] = None):
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")

    tarefa_alvo = None
    with TAREFAS_LOCK:
        if task_id and task_id in TAREFAS:
            tarefa_alvo = dict(TAREFAS[task_id])
        else:
            tarefas_do_proj = [t for t in TAREFAS.values() if t.get("projeto") == nome]
            if tarefas_do_proj:
                tarefa_alvo = dict(tarefas_do_proj[-1])
    if tarefa_alvo is None and (task_id or "").startswith("criar_"):
        # a fábrica reiniciou no meio: o andamento da criação está gravado no disco
        tarefa_alvo = _ler_criacao(nome)
    if tarefa_alvo is None and (task_id or "").startswith("render_"):
        # a fábrica reiniciou no meio do render: o FFmpeg morreu junto, e a tela não pode esperar para sempre
        return {"status": "erro", "concluido": False, "progresso_pct": 0, "tarefa_id": task_id,
                "erro": ("A renderização foi interrompida porque a fábrica reiniciou. Clique em Renderizar de novo: "
                         "as cenas já montadas são reaproveitadas e vai bem mais rápido."),
                "etapa_atual": "Renderização interrompida"}

    if tarefa_alvo:
        tipo = tarefa_alvo.get("tipo", "render")
        if tipo == "limpeza":
            return {
                "status": tarefa_alvo.get("status", "processando"),
                "mensagem": tarefa_alvo.get("mensagem", "Processando..."),
                "progresso_pct": tarefa_alvo.get("progresso_pct", 5),
                "logs": tarefa_alvo.get("logs", []),
                "resultado": tarefa_alvo.get("resultado"),
                "erro": tarefa_alvo.get("erro"),
                "tarefa_id": tarefa_alvo.get("tarefa_id"),
            }
        if tipo == "criacao":
            return {
                "etapa": tarefa_alvo.get("etapa", "narracao"),
                "passo_atual": tarefa_alvo.get("passo_atual", 1),
                "total_passos": tarefa_alvo.get("total_passos", 5),
                "progresso_pct": tarefa_alvo.get("progresso_pct", 10),
                "mensagem": tarefa_alvo.get("mensagem", "Processando..."),
                "pronto_para_edicao": tarefa_alvo.get("pronto_para_edicao", False),
                "tarefa_id": tarefa_alvo.get("tarefa_id"),
                "status": tarefa_alvo.get("status", "processando"),
                "mapa": tarefa_alvo.get("mapa"),  # o JSON do agente de roteiro, assim que ficar pronto
                "cenas_planejadas": tarefa_alvo.get("cenas_planejadas"),  # quantas cenas o JSON do agente tem
                "conferencia": tarefa_alvo.get("conferencia"),
                "aguardando_ate": tarefa_alvo.get("aguardando_ate"),  # esperando cota: volta sozinha nessa hora
                "erro": tarefa_alvo.get("erro"),
                "precisa_voce": bool(tarefa_alvo.get("precisa_voce")),
            }

        st = tarefa_alvo.get("status")
        if st == "renderizando":
            return {
                "status": "renderizando",
                "progresso_pct": tarefa_alvo.get("progresso_pct", 10),
                "etapa_atual": tarefa_alvo.get("etapa_atual", "Montando clipe com FFmpeg..."),
                "concluido": False,
                "tarefa_id": tarefa_alvo.get("tarefa_id"),
            }
        elif st == "concluido":
            return {
                "status": "concluido",
                "progresso_pct": 100,
                "concluido": True,
                "video_url": tarefa_alvo.get("video_url", f"/arquivos/{nome}/final.mp4"),
                "vertical": bool(tarefa_alvo.get("vertical")),
                "duracao": tarefa_alvo.get("duracao", "01:02"),
                "tamanho_mb": tarefa_alvo.get("tamanho_mb", 15.0),
                "tarefa_id": tarefa_alvo.get("tarefa_id"),
            }
        elif st == "erro":
            return {
                "status": "erro",
                "progresso_pct": tarefa_alvo.get("progresso_pct", 0),
                "concluido": False,
                "erro": tarefa_alvo.get("erro", "Erro desconhecido"),
                "etapa_atual": tarefa_alvo.get("etapa_atual", "Erro na operação"),
                "tarefa_id": tarefa_alvo.get("tarefa_id"),
            }

    p = Projeto(nome)
    pronto = p.existe("cenas.json") and p.existe("alinhamento.json")
    return {
        "status": "pronto" if pronto else "incompleto",
        "concluido": p.existe("final.mp4"),
        "pronto_para_edicao": pronto,
        "progresso_pct": 100 if pronto else 0,
        "mensagem": "Projeto pronto para edição" if pronto else "Aguardando geração de cenas",
        "etapa": "concluido" if pronto else "pendente",
        "passo_atual": 4 if pronto else 1,
        "total_passos": 5,
    }


@app.get("/api/sfx-library")
def listar_sfx():
    """Retorna lista de efeitos sonoros disponíveis na pasta efeitos/."""
    pasta_efeitos = RAIZ / "efeitos"
    if not pasta_efeitos.exists():
        return {"sfx": []}

    itens = []
    for f in sorted(pasta_efeitos.glob("**/*.mp3")):
        rel = f.relative_to(RAIZ).as_posix()
        desc = ""
        txt_file = f.with_suffix(".txt")
        if txt_file.exists():
            try:
                desc = txt_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        itens.append({
            "nome": f.stem,
            "caminho": rel,
            "url": f"/arquivos_raiz/{rel}",
            "descricao": desc or f.stem.replace("-", " "),
        })

    return {"sfx": itens}


@app.get("/api/music-library")
def listar_musicas():
    """Retorna lista de trilhas musicais disponíveis na pasta musicas/."""
    pasta_musicas = RAIZ / "musicas"
    if not pasta_musicas.exists():
        return {"musicas": []}

    itens = []
    for f in sorted(pasta_musicas.glob("**/*")):
        if f.is_file() and f.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac"):
            rel = f.relative_to(RAIZ).as_posix()
            itens.append({
                "nome": f.stem,
                "categoria": f.parent.name,
                "caminho": rel,
                "url": f"/arquivos_raiz/{rel}",
            })

    return {"musicas": itens}


def _redirect_uri(request: Request) -> str:
    return str(request.base_url) + "api/youtube/oauth/callback"


@app.get("/api/youtube/conectar")
def youtube_conectar(request: Request):
    """Manda a pessoa pra tela de login do Google."""
    try:
        url = ytpub.url_autorizacao(_redirect_uri(request))
    except SystemExit as e:
        raise HTTPException(status_code=500, detail=str(e))
    return RedirectResponse(url)


@app.get("/api/youtube/oauth/callback")
def youtube_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    """O Google volta pra cá depois do login."""
    def pagina(titulo: str, corpo: str) -> HTMLResponse:
        return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>{titulo}</title><style>
body {{ font-family: -apple-system, sans-serif; background: #0a0c10; color: #f8fafc;
  display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }}
div {{ text-align: center; max-width: 380px; padding: 24px; }}
h1 {{ font-size: 18px; }} p {{ color: #94a3b8; font-size: 13px; }}
</style></head><body><div><h1>{titulo}</h1><p>{corpo}</p></div></body></html>""")

    if error:
        return pagina("Não deu para conectar", f"O Google recusou: {error}. Pode fechar esta aba e tentar de novo.")
    if not code:
        return pagina("Não deu para conectar", "Faltou o código de autorização. Feche esta aba e tente de novo.")
    try:
        ytpub.concluir_autorizacao(code, _redirect_uri(request))
    except SystemExit as e:
        return pagina("Não deu para conectar", f"{e} Pode fechar esta aba e tentar de novo.")
    return pagina("Conectado!", "Sua conta do YouTube já está ligada à fábrica. Pode fechar esta aba e voltar ao painel.")


@app.get("/api/youtube/status")
def youtube_status():
    return {"conectado": ytpub.conectada(), "conta": ytpub.conta()}


@app.post("/api/youtube/desconectar")
def youtube_desconectar():
    ytpub.desconectar()
    return {"sucesso": True}


@app.post("/api/projetos/{nome}/youtube/publicar")
def youtube_publicar(nome: str, payload: PublicarYoutubePayload, bg_tasks: BackgroundTasks):
    """Sobe o final.mp4 do projeto pro YouTube em segundo plano."""
    p = Projeto(nome) if (PROJETOS / nome).exists() else None
    if p is None:
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")
    if not p.existe("final.mp4"):
        raise HTTPException(status_code=400, detail="Esse projeto ainda não tem um vídeo final renderizado.")
    if not ytpub.conectada():
        raise HTTPException(status_code=400, detail="Conecte uma conta do YouTube antes de publicar.")
    if payload.privacidade not in ("public", "unlisted", "private"):
        raise HTTPException(status_code=400, detail="Privacidade precisa ser public, unlisted ou private.")

    task_id = f"youtube_{nome}_{datetime.now():%Y%m%d_%H%M%S}"
    with TAREFAS_LOCK:
        TAREFAS[task_id] = {
            "tarefa_id": task_id, "projeto": nome, "tipo": "youtube",
            "status": "enviando", "progresso_pct": 0,
            "mensagem": "Enviando vídeo para o YouTube...",
            "concluido": False, "erro": None,
        }

    def worker():
        try:
            def progresso(pct):
                with TAREFAS_LOCK:
                    if task_id in TAREFAS:
                        TAREFAS[task_id]["progresso_pct"] = pct

            privacidade_upload = "private" if payload.agendado_para else payload.privacidade
            resultado = ytpub.publicar(
                p.pasta / "final.mp4", payload.titulo, payload.descricao, payload.tags,
                privacidade_upload, on_progresso=progresso,
            )
            video_id = resultado["id"]
            dados_youtube = {
                "video_id": video_id,
                "url": f"https://youtu.be/{video_id}",
                "titulo": payload.titulo,
                "descricao": payload.descricao,
                "tags": payload.tags,
                "privacidade_alvo": payload.privacidade,
                "agendado_para": payload.agendado_para,
                "status": "agendado" if payload.agendado_para else "publicado",
                "enviado_em": datetime.now().isoformat(timespec="seconds"),
            }
            p.salvar_json("youtube.json", dados_youtube)
            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id]["status"] = "concluido"
                    TAREFAS[task_id]["concluido"] = True
                    TAREFAS[task_id]["progresso_pct"] = 100
                    TAREFAS[task_id]["mensagem"] = "Agendado com sucesso!" if payload.agendado_para else "Publicado com sucesso!"
                    TAREFAS[task_id]["youtube"] = dados_youtube
        except (Exception, SystemExit) as err:
            with TAREFAS_LOCK:
                if task_id in TAREFAS:
                    TAREFAS[task_id]["status"] = "erro"
                    TAREFAS[task_id]["erro"] = str(err)
                    TAREFAS[task_id]["mensagem"] = f"Falha ao publicar: {err}"

    bg_tasks.add_task(worker)
    return JSONResponse(status_code=202, content={"sucesso": True, "tarefa_id": task_id})


@app.get("/api/projetos/{nome}/youtube/status")
def youtube_publicar_status(nome: str, task_id: Optional[str] = None):
    """Progresso do envio em andamento e status do agendamento/publicação."""
    pasta = PROJETOS / nome
    if not pasta.exists():
        raise HTTPException(status_code=404, detail=f"Projeto '{nome}' não encontrado.")

    tarefa = None
    if task_id:
        with TAREFAS_LOCK:
            tarefa = dict(TAREFAS[task_id]) if task_id in TAREFAS else None

    p = Projeto(nome)
    publicado = p.ler_json("youtube.json") if p.existe("youtube.json") else None
    return {"tarefa": tarefa, "publicado": publicado}


# -----------------------------------------------------------------------------
# Streaming de Arquivos Estáticos com suporte nativo a Range Requests
# -----------------------------------------------------------------------------

@app.api_route("/arquivos/{nome}/{caminho:path}", methods=["GET", "HEAD"])
def servir_arquivo_projeto(nome: str, caminho: str, baixar: bool = False):
    """Serve qualquer arquivo do projeto com suporte a Range requests (HTTP 206)."""
    arquivo = PROJETOS / nome / caminho
    if not arquivo.exists() or not arquivo.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    # Proteção de Path Traversal
    try:
        arquivo.resolve().relative_to((PROJETOS / nome).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    mime_type, _ = mimetypes.guess_type(str(arquivo))
    # o Cloudflare do túnel guardava o vídeo por horas: depois de um novo render, o player recebia pedaços
    # do arquivo antigo misturados com o novo e travava em 0:00. no-cache obriga a conferir se mudou.
    cabecalho = {"Cache-Control": "no-cache"} if arquivo.suffix.lower() in (".mp4", ".wav", ".mp3") else None
    if baixar:
        return FileResponse(arquivo, media_type=mime_type or "application/octet-stream", filename=arquivo.name, headers=cabecalho)
    return FileResponse(arquivo, media_type=mime_type or "application/octet-stream", headers=cabecalho)


TAMANHOS_PREVIA = {"mini": 320, "tela": 1280}
_TRAVA_LEVES = threading.Lock()


def _origem_da_previa(p: Projeto, cena: Dict[str, Any]) -> Optional[Path]:
    """O arquivo de onde sai a prévia: a foto da cena, a capa do vídeo, ou a imagem de IA."""
    m = cena.get("midia") or {}
    if m.get("arquivo"):
        arq = p.pasta / m["arquivo"]
        if arq.exists() and arq.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            return arq
        if m.get("capa") and (p.pasta / m["capa"]).exists():
            return p.pasta / m["capa"]
        if arq.exists():
            return arq  # vídeo sem capa: a prévia sai de um quadro dele
    img = p.imagem(cena["n"])
    return img if img.exists() else None


def _gerar_previa(origem: Path, destino: Path, largura: int) -> None:
    """Reduz a imagem (ou um quadro do vídeo) para a largura pedida. O editor carrega isso em vez do original,
    que numa foto da Wikimedia chega a 20 MB e pelo túnel travava a timeline."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp.jpg")
    if origem.suffix.lower() in (".mp4", ".mov", ".webm", ".m4v"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", str(origem), "-vframes", "1",
                        "-vf", f"scale='min({largura},iw)':-2", "-q:v", "4", str(tmp)], check=True)
    else:
        # a foto do jeito que ela entra no vídeo (moldura do retrato, recorte pelos rostos), e não a foto esticada
        # pelo meio: o editor mostrava só o tronco do jogador da cena 16 do virou-filme-em-1996
        try:
            quadro = render.quadro_da_foto(origem, largura)
        except Exception:
            from PIL import Image
            with Image.open(origem) as im:
                quadro = im.convert("RGB")
                quadro.thumbnail((largura, largura * 4))
        quadro.save(tmp, "JPEG", quality=82, optimize=True)
    tmp.replace(destino)


@app.api_route("/arquivos_previas/{nome}/{tamanho}/{n}.jpg", methods=["GET", "HEAD"])
def servir_previa(nome: str, tamanho: str, n: int):
    """Miniatura (mini, 320px) ou prévia (tela, 1280px) da cena, feita uma vez e guardada em _previas.
    O nome do arquivo guardado leva a data da origem, então uma mídia trocada ganha prévia nova sozinha."""
    if tamanho not in TAMANHOS_PREVIA or not (PROJETOS / nome).exists():
        raise HTTPException(status_code=404, detail="Prévia não encontrada.")
    p = Projeto(nome)
    cena = next((c for c in p.ler_json("cenas.json").get("cenas", []) if c.get("n") == n), None)
    origem = _origem_da_previa(p, cena) if cena else None
    if origem is None:
        raise HTTPException(status_code=404, detail="Essa cena ainda não tem imagem.")
    # a versão do enquadramento entra no nome: mudou o jeito de montar a prévia, ela é feita de novo
    versao = f"{int(origem.stat().st_mtime)}q{rostos.VERSAO}"
    destino = p.pasta / "_previas" / tamanho / f"{n:04d}_{versao}.jpg"
    if not destino.exists():
        with _TRAVA_LEVES:
            if not destino.exists():
                for velho in destino.parent.glob(f"{n:04d}_*.jpg") if destino.parent.exists() else []:
                    velho.unlink(missing_ok=True)
                try:
                    _gerar_previa(origem, destino, TAMANHOS_PREVIA[tamanho])
                except Exception:
                    # não deu para reduzir (formato estranho): serve o original, que ao menos aparece
                    return FileResponse(origem)
    return FileResponse(destino, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


EXTENSOES_VIDEO = (".mp4", ".mov", ".webm", ".m4v")


ALTURA_PREVIA_VIDEO = 480
_PREPARANDO_PREVIAS = set()  # projetos com as prévias de vídeo sendo feitas em segundo plano


def _video_da_cena(p: Projeto, cena: Dict[str, Any], criar: bool = False) -> Optional[Path]:
    m = cena.get("midia") or {}
    arq = p.pasta / m["arquivo"] if m.get("arquivo") else None
    return arq if arq and arq.exists() and arq.suffix.lower() in EXTENSOES_VIDEO else None


def _destino_previa_video(p: Projeto, cena: Dict[str, Any], origem: Path) -> Path:
    """O nome leva a data da origem e a duração da cena: mídia trocada ou corte mudado ganham prévia nova."""
    decimos = int(round((cena["fim"] - cena["ini"]) * 10))
    return p.pasta / "_previas" / "video" / f"{cena['n']:04d}_{int(origem.stat().st_mtime)}_{decimos}.mp4"


def _gerar_previa_video(origem: Path, destino: Path, duracao_cena: float) -> None:
    """Corta do vídeo de banco só o trecho que a cena usa, em 480p e sem som.

    O original é 1080p de 9 a 18 Mbps e chega a 111 MB, mas a cena mostra 3 a 5 segundos dele: pelo túnel do
    Cloudflare o player esperava o download do arquivo inteiro e travava. O começo segue a mesma regra do render
    (render._entrada_video), para o editor mostrar o mesmo trecho que vai sair no vídeo final."""
    from .util import duracao_audio

    disponivel = duracao_audio(origem)
    inicio = min(1.0, (disponivel - duracao_cena) / 2) if disponivel >= duracao_cena + 1 else 0.0
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(f"{destino.stem}.{threading.get_ident()}.tmp.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-i", str(origem),
                    "-t", f"{duracao_cena + 1.5:.3f}", "-an", "-vf", f"scale=-2:{ALTURA_PREVIA_VIDEO},fps=30",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-maxrate", "1200k", "-bufsize", "2400k",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)], check=True)
    for velho in destino.parent.glob(f"{destino.name.split('_')[0]}_*.mp4"):
        if velho != destino and not velho.name.endswith(".tmp.mp4"):
            velho.unlink(missing_ok=True)
    tmp.replace(destino)


def _previa_video_pronta(p: Projeto, cena: Dict[str, Any]) -> Optional[Path]:
    """Devolve a prévia leve do vídeo da cena, fazendo agora se ainda não existir. None se a cena não é vídeo."""
    origem = _video_da_cena(p, cena, criar=True)
    if origem is None:
        return None
    destino = _destino_previa_video(p, cena, origem)
    if not destino.exists():
        _gerar_previa_video(origem, destino, max(0.5, cena["fim"] - cena["ini"]))
    return destino


def preparar_previas_video(nome: str) -> None:
    """Faz em segundo plano as prévias de vídeo que faltam, na ordem das cenas, para o player já achar prontas."""
    with _TRAVA_LEVES:
        if nome in _PREPARANDO_PREVIAS:
            return
        _PREPARANDO_PREVIAS.add(nome)

    def trabalhar():
        try:
            p = Projeto(nome)
            # primeiro as prévias das animações: são poucas e leves, e o player toca todas por cima das cenas
            for item in _motion_do_projeto(p):
                try:
                    animacoes.previa_da_camada(p, item, criar=True)
                except Exception as erro:
                    print(f"[prévias de animação] {item.get('id')} de {nome}: {str(erro)[:120]}")
            for cena in p.ler_json("cenas.json").get("cenas", []):
                try:
                    _previa_video_pronta(p, cena)
                except Exception as erro:
                    print(f"[prévias de vídeo] cena {cena.get('n')} de {nome}: {str(erro)[:120]}")
        except (Exception, SystemExit) as erro:
            print(f"[prévias de vídeo] {nome}: {str(erro)[:120]}")
        finally:
            with _TRAVA_LEVES:
                _PREPARANDO_PREVIAS.discard(nome)

    threading.Thread(target=trabalhar, daemon=True, name=f"previas-video-{nome}").start()


@app.api_route("/arquivos_previas/{nome}/video/{n}.mp4", methods=["GET", "HEAD"])
def servir_previa_video(nome: str, n: int):
    """Prévia leve do vídeo da cena para o player do editor (480p, só o trecho da cena, sem som)."""
    if not (PROJETOS / nome).exists():
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    p = Projeto(nome)
    cena = next((c for c in p.ler_json("cenas.json").get("cenas", []) if c.get("n") == n), None)
    origem = _video_da_cena(p, cena, criar=True) if cena else None
    if origem is None:
        raise HTTPException(status_code=404, detail="Essa cena não tem vídeo.")
    try:
        destino = _previa_video_pronta(p, cena)
    except Exception:
        # não deu para reduzir: serve o original, que ao menos toca
        return FileResponse(origem, media_type=mimetypes.guess_type(str(origem))[0] or "video/mp4",
                            headers={"Cache-Control": "no-cache"})
    # o endereço muda quando a mídia ou o corte mudam (?v=), então o navegador pode guardar a prévia
    return FileResponse(destino, media_type="video/mp4", headers={"Cache-Control": "private, max-age=604800"})


@app.api_route("/arquivos_previas/{nome}/motion/{ident}.webm", methods=["GET", "HEAD"])
def servir_previa_motion(nome: str, ident: str):
    """A animação inteira em WebM transparente, para a faixa Motion do player do editor (feita agora se faltar)."""
    if not (PROJETOS / nome).exists():
        raise HTTPException(status_code=404, detail="Projeto não encontrado.")
    p = Projeto(nome)
    item = next((i for i in _motion_do_projeto(p) if i["id"] == ident), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Essa animação não existe ou está desatualizada.")
    try:
        destino = animacoes.previa_da_camada(p, item, criar=True)
    except Exception as erro:
        raise HTTPException(status_code=500, detail=f"Não consegui preparar a prévia da animação: {str(erro)[:160]}")
    if destino is None:
        raise HTTPException(status_code=404, detail="A animação ainda não foi desenhada.")
    return FileResponse(destino, media_type="video/webm", headers={"Cache-Control": "private, max-age=604800"})


@app.api_route("/arquivos_narracao/{nome}.mp3", methods=["GET", "HEAD"])
def servir_narracao_leve(nome: str):
    """A narração em MP3 leve para o editor: o WAV de um vídeo de 28 min passa de 140 MB e, pelo túnel, o
    player não conseguia tocar o vídeo inteiro. Gerada uma vez; refeita só se a narração mudar."""
    wav = PROJETOS / nome / "narracao.wav"
    if not wav.exists():
        raise HTTPException(status_code=404, detail="Esse projeto ainda não tem narração.")
    mp3 = PROJETOS / nome / "narracao_editor.mp3"
    if not mp3.exists() or mp3.stat().st_mtime < wav.stat().st_mtime:
        with _TRAVA_LEVES:
            if not mp3.exists() or mp3.stat().st_mtime < wav.stat().st_mtime:
                tmp = mp3.with_suffix(".tmp.mp3")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", "-b:a", "80k",
                                str(tmp)], check=True)
                tmp.replace(mp3)
    return FileResponse(mp3, media_type="audio/mpeg", headers={"Cache-Control": "no-cache"})


@app.api_route("/arquivos_raiz/{caminho:path}", methods=["GET", "HEAD"])
def servir_arquivo_raiz(caminho: str):
    """Serve arquivos da raiz (efeitos/, musicas/)."""
    arquivo = RAIZ / caminho
    if not arquivo.exists() or not arquivo.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    try:
        arquivo.resolve().relative_to(RAIZ.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    mime_type, _ = mimetypes.guess_type(str(arquivo))
    return FileResponse(arquivo, media_type=mime_type or "application/octet-stream")


def criar_app(frontend_dir: Optional[str] = None):
    """Cria e configura o app FastAPI, opcionalmente montando os estáticos do frontend."""
    if not frontend_dir:
        padrao = Path("G:/editor-video-dark")
        if padrao.exists() and (padrao / "index.html").exists():
            frontend_dir = str(padrao)
    if frontend_dir and Path(frontend_dir).exists():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    retomar_criacoes_interrompidas()
    return app
