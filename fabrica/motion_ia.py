"""Motion IA: cena reprovada ou de nota baixa em que o Jev diz que o motion vale a pena vira um clipe de motion
graphics, no lugar da imagem (PRD-MOTION.txt).

Quando a imagem de uma cena é reprovada (ia para a imagem de IA) ou tirou nota baixa, o Jev lê o trecho do roteiro e dá
uma nota para "um infográfico explica esta fala melhor que uma foto?" (número com o que ele mede, comparação, causa e
consequência, etapas). Acima de motion_ia.nota_utilidade, a fábrica pede a um modelo gratuito o HTML
de uma animação no estilo editorial Vox / explicador de SaaS (fundo creme com grade de pontos, cards brancos de cantos
bem arredondados, linhas SVG que se desenham, barras que sobem, palavra de destaque em serifa colorida, entrada com
mola e flutuação contínua; PRD de 2026-10-05) e o HyperFrames grava um MP4 com a duração exata da cena, quadro a
quadro, num Chrome escondido. O MP4 entra como a mídia da cena (midia.fonte "motion_ia"), igual a um vídeo de banco, e o editor mostra o
selo "Motion IA". A pessoa continua podendo trocar a mídia como em qualquer cena.

Cena que cita um animal ou um nome exato só vira motion levando a própria foto, com o sujeito certo (o Jev deu 60 ou
mais), num card ao lado do dado: a regra de precisão literal não muda (o rinoceronte continua sendo um rinoceronte).
Sem foto certa, ela segue para a imagem de IA. Pedido do usuário em 2026-10-05 (antes, 2026-10-04: só cena abstrata).

Custo zero: só os modelos gratuitos da cadeia de principais (ou motion_ia.modelos no config.yaml), com no máximo
motion_ia.max_por_minuto pedidos por minuto. Nunca para o vídeo: falhou, a cena segue o caminho de antes (a imagem de
IA, se estava errada, ou a foto que tinha, se só tinha nota baixa).

O modelo escreve o HTML livre (decisão do usuário), dentro de um esqueleto fixo da fábrica que dá a ele a linha do
tempo do GSAP (tl), as fontes, o fundo, as peças prontas (m-card, m-destaque, m-linha, m-barra) e o tamanho da tela,
e expõe window.seekToFrame para a gravação. A flutuação dos cards e o traço escondido das linhas são do esqueleto. O código confere o que
volta (nada de animação CSS, relógio, sorteio, endereço externo ou emoji) e o HyperFrames confere texto saindo da tela
ou sobreposto; o que reprovar volta para o modelo, até motion_ia.tentativas.
"""
import hashlib
import json
import os
import re
import shutil
import threading
import time
import unicodedata
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import animacoes, motion_modelos
from .util import rodar

FONTE = "motion_ia"
TIPOS_SEM_MOTION = ("personagem",)
_TRAVA_PEDIDOS = threading.Lock()
_PEDIDOS = deque()  # horários dos últimos pedidos aos modelos, para o limite por minuto
_TRAVA_CENAS = threading.Lock()


def config(projeto) -> dict:
    """motion_ia do config.yaml, com JEV_MOTION_FALLBACK_ENABLED e JEV_MIN_SCORE_THRESHOLD (0 a 10) do .env por cima."""
    cfg = dict(projeto.config.get("motion_ia") or {})
    ligado = os.environ.get("JEV_MOTION_FALLBACK_ENABLED")
    if ligado is not None:
        cfg["ativo"] = ligado.strip().lower() in ("1", "true", "sim", "yes")
    limiar = os.environ.get("JEV_MIN_SCORE_THRESHOLD")
    if limiar:
        try:
            cfg["nota_minima"] = float(limiar) * 10  # o PRD fala de 0 a 10; o Jev da fábrica dá de 0 a 100
        except ValueError:
            pass
    return cfg


def ligado(projeto) -> bool:
    return bool(config(projeto).get("ativo", True)) and not projeto.offline


def nota_minima(projeto) -> float:
    from .midia import nota_minima_da_conferencia
    return float(config(projeto).get("nota_minima", nota_minima_da_conferencia(projeto)))


def e_motion(cena) -> bool:
    return (cena.get("midia") or {}).get("fonte") == FONTE


def _gratuito(modelo) -> bool:
    from .openrouter_local import gratuita
    return gratuita(modelo)


def modelos(projeto) -> list:
    """Só modelos gratuitos (custo zero, PRD item 8): OPENROUTER_FREE_MODELS do .env, a lista motion_ia.modelos ou os
    gratuitos da cadeia de principais. Modelo pago numa dessas listas é ignorado."""
    from .openrouter_local import principais
    do_env = [m.strip() for m in (os.environ.get("OPENROUTER_FREE_MODELS") or "").split(",")]
    lista = [m for m in do_env if m] or config(projeto).get("modelos") or principais(projeto)
    return [m for m in lista if m and _gratuito(m)]


def fps(projeto) -> int:
    """Quadros por segundo do clipe: MOTION_RENDER_FPS do .env, ou motion_ia.fps (30)."""
    try:
        return max(12, min(int(float(os.environ.get("MOTION_RENDER_FPS") or config(projeto).get("fps", 30))), 60))
    except ValueError:
        return 30


def _esperar_vez(projeto) -> None:
    """No máximo motion_ia.max_por_minuto pedidos por minuto aos modelos gratuitos (o PRD pede 15)."""
    limite = int(config(projeto).get("max_por_minuto", 15))
    while True:
        with _TRAVA_PEDIDOS:
            agora = time.time()
            while _PEDIDOS and agora - _PEDIDOS[0] > 60:
                _PEDIDOS.popleft()
            if len(_PEDIDOS) < limite:
                _PEDIDOS.append(agora)
                return
            espera = 60 - (agora - _PEDIDOS[0]) + 0.1
        time.sleep(max(espera, 0.5))


def _perguntar(projeto, etapa, instrucoes, pedido, esquema, log, temperatura=0.4):
    """Pergunta em cascata, só pelos modelos gratuitos: o que não atender passa a vez para o seguinte."""
    from . import openrouter_local
    erro = None
    lista = modelos(projeto)
    for k, modelo in enumerate(lista):
        _esperar_vez(projeto)
        try:
            return openrouter_local.uma_rota(projeto, etapa, instrucoes, pedido, esquema, log, modelo, (),
                                             temperatura, cadeia=k < len(lista) - 1)
        except (openrouter_local.RotaIndisponivel, RuntimeError, SystemExit) as e:
            erro = e
            log(f"  motion IA: {modelo} não atendeu ({str(e)[:100]})")
    raise RuntimeError(f"nenhum modelo gratuito atendeu: {erro}")


# ------------------------------------------------------------------------- o Jev diz se o motion vale a pena

# Pedido do usuário em 2026-10-05: quem decide se a cena vira motion é o Jev, lendo o ROTEIRO. Antes um modelo só
# separava "abstrata" de "concreta", e o motion caiu na cena 6 do natureza-teste-1min ("e o primeiro lugar vai te
# surpreender"), sem impacto, enquanto "pode passar dos 50 quilômetros por hora" e "pesa mais de uma tonelada"
# ficavam de fora por citar o rinoceronte.
#
# Na primeira rodada (natureza-teste-1min, 2026-10-05) o Jev deu 51% para "pode passar dos 50 quilômetros por hora",
# 43% para "um chifre que chega a mais de um metro" e 74% para "a ironia é que ele mesmo vive em perigo": a pergunta
# punha "a aparência de um animal" como motivo para dizer não, e toda cena do rinoceronte perdia. Agora o código acha
# o dado na fala (dado_na_fala) e o Jev responde duas perguntas na mesma chamada (mesmo preço): se a fala traz um dado
# de infográfico e se o clipe explica melhor que a imagem. A nota é a média das duas.
VERSAO_UTIL = 2  # suba quando mudar as perguntas: a nota guardada na cena é pedida de novo

PERGUNTA_DADO = {
    "type": "noul",
    "instructions": (
        "A fala desta cena (narracao_desta_cena, marcada entre >>> e <<< no trecho_do_roteiro) traz um DADO que se "
        "mostra num infográfico? Quando o estado traz dado_na_fala, o código achou na fala um número com o que ele "
        "mede: isso é um dado. Citar um animal, uma pessoa ou um lugar não conta contra nem a favor."),
    "criteria": {
        "true": ("um número com o que ele mede (50 quilômetros por hora, mais de uma tonelada, um chifre de mais de "
                 "um metro, 135 vítimas, cerca de 35 pessoas, 80 por cento), uma estatística, uma posição num ranking "
                 "com o critério, uma comparação de grandezas, uma causa e consequência (a caça ilegal levou a espécie "
                 "à beira da extinção) ou as etapas de um processo"),
        "false": ("só uma ação, um momento da história, uma descrição, uma opinião, uma transição, uma pergunta ao "
                  "espectador ou um pedido de like, sem número, comparação, causa ou etapas"),
    },
}

PERGUNTA_UTIL = {
    "type": "noul",
    "instructions": (
        "Você é editor de um documentário narrado. Leia o trecho do roteiro e decida se ESTA cena fica melhor como um "
        "clipe de motion graphics no estilo editorial da Vox (um infográfico animado: o número grande com o que ele "
        "mede, gráfico de barras, comparação lado a lado, diagrama de causa e consequência ou de etapas) do que só com "
        "a imagem de hoje. Quando o estado traz o_clipe_tem_a_foto, o clipe NÃO perde a imagem: a foto da cena entra "
        "num card ao lado do dado, então o animal, a pessoa ou o lugar continua aparecendo e a comparação é 'foto com "
        "o dado na tela' contra 'só a foto'. O motion vale quando o espectador entende ou guarda melhor a informação "
        "vendo o dado escrito e desenhado."),
    "criteria": {
        "true": ("o dado da fala ganha com o infográfico: velocidade, peso, tamanho, quantidade, porcentagem, ranking, "
                 "comparação, causa e consequência ou etapas, que a foto sozinha não diz"),
        "false": ("a força da cena está numa AÇÃO ou num MOMENTO que só a imagem mostra (o bicho atacando, a caça, uma "
                  "cena da história acontecendo) ou numa paisagem; ou é transição, suspense, pergunta ao espectador ou "
                  "pedido de like sem nenhum dado"),
    },
}

_NUMEROS = (r"\d+(?:[.,]\d+)?|uma?|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|quinze|vinte|"
            r"trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|duzent[oa]s|trezent[oa]s|"
            r"quinhent[oa]s|mil|milh[aã]o|milh[õo]es|bilh[aã]o|bilh[õo]es|metade|dobro|triplo|meio|meia")
_UNIDADES = (r"quil[ôo]metros?|km|metros?|cent[íi]metros?|mil[íi]metros?|toneladas?|quilos?|kg|gramas?|litros?|"
             r"anos?|meses|dias?|horas?|minutos?|segundos?|por\s+cento|%|vezes|graus|pessoas|v[íi]timas|mortes|"
             r"esp[ée]cies|indiv[íi]duos|exemplares|animais|filhotes|ovos|dentes|hectares|d[óo]lares|reais|habitantes")
_DADO = re.compile(rf"(?:(?:mais|menos)\s+de\s+|cerca\s+de\s+|quase\s+|at[ée]\s+)?"
                   rf"\b(?:{_NUMEROS})\b(?:\s+(?:mil|milh[õo]es|bilh[õo]es))?\s+(?:de\s+)?(?:{_UNIDADES})\b"
                   rf"(?:\s+por\s+(?:hora|dia|ano|segundo|minuto))?", re.I)


def dado_na_fala(texto) -> str:
    """O número com o que ele mede, achado pelo código ("50 quilômetros por hora", "mais de uma tonelada")."""
    achados = [m.group(0).strip() for m in _DADO.finditer(texto or "")]
    return "; ".join(dict.fromkeys(achados))


def _assinatura_fala(cena) -> str:
    return hashlib.sha1(" ".join((cena.get("texto") or "").split()).encode()).hexdigest()[:10]


def _assinatura_util(cena) -> str:
    return f"{_assinatura_fala(cena)}-v{VERSAO_UTIL}"


def limiar_util(projeto) -> float:
    """De 0 a 100: a nota do Jev a partir da qual a cena vira motion (motion_ia.nota_utilidade, 70)."""
    return float(config(projeto).get("nota_utilidade", 70))


def concreta(cena) -> bool:
    """A cena cita um animal ou um nome exato: o motion só entra levando a foto certa dela (regra de precisão)."""
    return bool((cena.get("animal") or "").strip() or (cena.get("exato") or "").strip())


_IMAGENS = (".jpg", ".jpeg", ".png", ".webp")
_VIDEOS = (".mp4", ".mov", ".webm", ".m4v")


def _como_imagem(projeto, n, caminho):
    """A imagem para o card: a própria foto, ou um quadro do meio do vídeo (guardado na pasta do clipe)."""
    caminho = Path(caminho)
    if not caminho.exists():
        return None
    if caminho.suffix.lower() in _IMAGENS:
        return caminho
    if caminho.suffix.lower() not in _VIDEOS:
        return None
    quadro = _pasta(projeto, n) / "quadro_do_video.jpg"
    if not quadro.exists():
        quadro.parent.mkdir(parents=True, exist_ok=True)
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", str(caminho), "-frames:v", "1", "-q:v", "2",
               str(quadro)])
    return quadro if quadro.exists() else None


def foto_da_cena(projeto, cena):
    """A imagem da cena com o sujeito certo (o Jev deu 60 ou mais), para o card do clipe: o rinoceronte continua
    sendo um rinoceronte. Sem foto certa, a cena concreta não vira motion.

    Procura na mídia de agora, na foto guardada para a imagem de IA (corrigir.mandar_para_ia move a foto para
    antigas/ antes do motion rodar, em ia_reserva) e na imagem de IA da cena."""
    if e_motion(cena):
        reserva = cena.get("motion_reserva") or {}
        if not (reserva.get("midia") or {}).get("arquivo"):
            return None
        # refazer um motion: a foto que a cena tinha antes dele (com a conferência dela)
        cena = {**cena, **{k: v for k, v in reserva.items() if k in ("midia", "conferencia", "ia_reserva")}}
    conf = cena.get("conferencia") or {}
    m = cena.get("midia") or {}
    if m.get("arquivo"):
        if (conf.get("sujeito") or 0) < 60:
            return None
        for arquivo in (m.get("arquivo"), m.get("capa")):
            if arquivo and Path(str(arquivo)).suffix.lower() in _IMAGENS:
                achada = _como_imagem(projeto, cena["n"], projeto.pasta / str(arquivo).replace("\\", "/"))
                if achada:
                    return achada
        return _como_imagem(projeto, cena["n"], projeto.pasta / str(m["arquivo"]).replace("\\", "/"))
    reserva = cena.get("ia_reserva") or {}
    if (reserva.get("sujeito") or 0) >= 60:
        movidos = [Path(antiga) for antiga, _ in reserva.get("movidos") or []]
        for antiga in sorted(movidos, key=lambda a: a.suffix.lower() not in _IMAGENS):
            achada = _como_imagem(projeto, cena["n"], antiga)
            if achada:
                return achada
    imagem = projeto.imagem(cena["n"])
    if imagem.exists() and (conf.get("sujeito") or 0) >= 60:
        return imagem
    return None


def _trecho_do_roteiro(todas, n) -> str:
    """A fala de duas cenas antes e duas depois, com a desta cena marcada: o Jev decide pelo roteiro, não pela frase."""
    partes = []
    for k in range(n - 2, n + 3):
        texto = ((todas.get(k) or {}).get("texto") or "").strip()
        if texto:
            partes.append(f">>> {texto} <<<" if k == n else texto)
    return " ".join(partes)


def _julgar_utilidade(projeto, cena, todas, foto, log):
    """A nota do Jev (0 a 100) para o motion nesta cena, ou None se ele não respondeu."""
    from . import corrigir, jev_local
    estado = {"narracao_desta_cena": (cena.get("texto") or "").strip(),
              "trecho_do_roteiro": _trecho_do_roteiro(todas, cena["n"])}
    bloco = corrigir._bloco_da_cena_no_mapa(projeto, cena)
    if bloco:
        estado["assunto_do_trecho"] = bloco
    if (cena.get("mostrar") or "").strip():
        estado["o_que_o_diretor_de_arte_pediu"] = cena["mostrar"].strip()
    conf = cena.get("conferencia") or {}
    if conf.get("legenda"):
        estado["o_que_a_imagem_de_hoje_mostra"] = str(conf["legenda"])[:600]
    if conf.get("nota") is not None:
        estado["nota_da_imagem_de_hoje"] = f"{conf['nota']} de 100"
    if concreta(cena):
        estado["a_cena_cita"] = (cena.get("exato") or cena.get("animal") or "").strip()
    if foto is not None:
        estado["o_clipe_tem_a_foto"] = "sim: a foto da cena entra num card do clipe, ao lado do dado"
    dado = dado_na_fala(cena.get("texto"))
    if dado:
        estado["dado_na_fala"] = dado
    try:
        respostas = jev_local.decidir(projeto, "motion IA: vale a pena", estado,
                                      {"dado": PERGUNTA_DADO, "util": PERGUNTA_UTIL}, log=log)
        tem_dado, util = (round(float(respostas[k]["noul"]) * 100) for k in ("dado", "util"))
        return round((tem_dado + util) / 2)
    except (Exception, SystemExit) as e:
        log(f"  motion IA: o Jev não julgou a cena {cena['n']} ({str(e)[:100]}); ela segue sem motion")
        return None


def classificar(projeto, cenas, log=print) -> dict:
    """{n: True se o motion vale a pena}. O Jev dá a nota pelo roteiro (motion_util, guardada na cena e só perguntada
    de novo se a fala mudar). A foto da cena é opcional: com ela, o clipe pode usar o modelo foto_dado."""
    todas = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}
    limiar = limiar_util(projeto)
    saida, notas = {}, {}
    for c in cenas:
        foto = foto_da_cena(projeto, c) if concreta(c) else None
        if c.get("personagem"):
            saida[c["n"]] = False
            continue
        if c.get("motion_util_fala") == _assinatura_util(c) and isinstance(c.get("motion_util"), (int, float)):
            nota = c["motion_util"]
        else:
            nota = _julgar_utilidade(projeto, c, todas, foto, log)
            if nota is None:
                saida[c["n"]] = False
                continue
            notas[c["n"]] = nota
        saida[c["n"]] = nota >= limiar
        log(f"  motion IA: cena {c['n']}, o Jev dá {nota}% de valer a pena"
            + (" (com a foto da cena)" if foto is not None else "") + (": vira motion" if saida[c["n"]] else ""))
    if notas:
        _gravar_classificacao(projeto, notas)
    return saida


def a_julgar(cenas) -> list:
    """As cenas que o Jev ainda vai julgar (as outras têm a nota guardada para a mesma fala)."""
    return [c for c in cenas if not (c.get("motion_util_fala") == _assinatura_util(c)
                                     and isinstance(c.get("motion_util"), (int, float)))]


def preco_do_jev(projeto) -> float:
    """Custo médio de uma chamada do Jev, medido no uso_jev.json do projeto (uns US$ 0,00005)."""
    try:
        chamadas = json.loads((projeto.pasta / "uso_jev.json").read_text(encoding="utf-8"))
        if chamadas:
            return sum(c.get("custo_usd", 0) or 0 for c in chamadas) / len(chamadas)
    except (OSError, ValueError):
        pass
    return 0.00005


def candidatas_do_projeto(projeto, numeros=None) -> list:
    """Onde o motion pode entrar: cena que iria para a imagem de IA sem ter imagem, com nota abaixo de
    motion_ia.nota_minima no Jev, ou com um dado na fala mesmo com a foto aprovada (uteis). Com numeros, só essas
    cenas (qualquer nota)."""
    from . import imagens
    cenas = projeto.ler_json("cenas.json")["cenas"]
    if numeros:
        return candidatas(projeto, [c for c in cenas if c["n"] in numeros], refazer=True)
    pendentes = {c["n"] for c in imagens.pendentes_ia(projeto, cenas)}
    limiar = nota_minima(projeto)
    escolhidas = {c["n"] for c in cenas if c["n"] in pendentes or (
        (c.get("conferencia") or {}).get("nota") is not None and c["conferencia"]["nota"] < limiar)}
    escolhidas |= {c["n"] for c in uteis(projeto, cenas)}
    return candidatas(projeto, [c for c in cenas if c["n"] in escolhidas])


# Pedido do usuário em 2026-10-07: "o motion deve entrar onde ele realmente vai ser útil para o roteiro, independente
# se a cena foi reprovada ou não". Antes ele só entrava na cena reprovada ou com nota abaixo de 40, e a cena com foto
# boa do mico ("pesa pouco mais de meio quilo") nunca virava a balança com o bicho, que precisa justamente da foto
# boa. Agora toda cena cuja fala traz um dado também é candidata, e o Jev decide pelo roteiro. O código separa antes
# quem tem chance (pode_ajudar), para o Jev não julgar as cenas de pura narração.
_PODE_AJUDAR = re.compile(
    r"por\s+cento|%|\b(?:primeiro|segundo|terceiro|quarto|quinto|sexto|s[ée]timo|oitavo|nono|d[ée]cimo)\s+lugar|"
    r"\bvezes\s+(?:mais|menos|maior|menor)|\b(?:dobro|triplo|metade)\b|\bmais\s+\w+\s+(?:que|do\s+que)\b|"
    r"\b(?:levou|levaram|leva|causou|causa|provocou)\s+(?:a|à|ao)\b|\bpor\s+isso\b|\bresultado\b|\bconsequ[êe]ncia|"
    # quantidade de qualquer coisa ("cerca de duzentos micos", "135 vítimas"), menos o ano ("em 1898 foi") e o código
    # de estrada ("BR-101 chegaram")
    r"(?<![-\w])(?:(?!1\d{3}\b|20\d{2}\b)\d{2,}[\d.,]*|dez|vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|"
    r"cem|cento|duzent[oa]s|trezent[oa]s|quatrocent[oa]s|quinhent[oa]s|milhares|milh[õo]es|mil)\s+(?:de\s+)?"
    r"[a-zà-ú]{3,}",
    re.I)


def pode_ajudar(cena, seguinte=None) -> str:
    """O dado da fala que um infográfico pode mostrar, ou "" (narração pura: o Jev nem é chamado). A fala é cortada
    no meio da frase ("pesa pouco mais de meio" | "quilo, tem uma juba..."), então vale a fala junto com as primeiras
    palavras da cena seguinte."""
    texto = (cena.get("texto") or "").strip()
    junto = " ".join([texto, " ".join(((seguinte or {}).get("texto") or "").split()[:4])])
    dado = dado_na_fala(junto)
    palavras = set(re.findall(r"\w+", texto.lower()))
    if dado and any(p in palavras for p in dado.lower().split()[:2]):
        return dado  # o dado começa NESTA cena: a seguinte, que só termina a frase, não repete o clipe
    achado = _PODE_AJUDAR.search(texto)
    return achado.group(0) if achado else ""


def uteis(projeto, cenas=None) -> list:
    """As cenas com foto (ou vídeo) que podem virar motion porque a fala traz um dado (pode_ajudar). Uma por dado:
    duas cenas seguidas com o mesmo dado ficam só com a primeira."""
    todas = cenas if cenas is not None else projeto.ler_json("cenas.json")["cenas"]
    por_n = {c["n"]: c for c in todas}
    saida, anterior = [], ("", -9)
    for c in todas:
        if not (c.get("midia") or {}).get("arquivo") and not projeto.imagem(c["n"]).exists():
            continue  # sem imagem: é a porta de entrada de antes (imagens._motion_antes_da_ia)
        if c.get("motion_reserva") and not e_motion(c):
            continue  # já foi motion e a pessoa trocou pela foto: a escolha dela fica
        dado = pode_ajudar(c, por_n.get(c["n"] + 1))
        if not dado:
            continue
        if dado.lower() == anterior[0] and c["n"] - anterior[1] <= 1:
            continue
        anterior = (dado.lower(), c["n"])
        saida.append(c)
    return candidatas(projeto, saida)


def nas_uteis(projeto, log=print) -> list:
    """Faz o motion nas cenas com dado em que o Jev diz que ele vale a pena, mesmo com a foto aprovada. A foto fica
    em motion_reserva (motion_ia.desfazer volta) e é ela que vira o bicho recortado na colagem. Devolve as feitas."""
    if not ligado(projeto) or not modelos(projeto) or not animacoes.node_pronto():
        return []
    cands = uteis(projeto)
    if not cands:
        return []
    log(f"  motion IA: {len(cands)} cena(s) com dado na fala, o Jev diz onde o motion ajuda o roteiro")
    tipos = classificar(projeto, cands, log)
    todas = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}
    escolhidas = [todas.get(c["n"], c) for c in cands if tipos.get(c["n"])]
    if not escolhidas:
        return []
    log(f"  motion IA: {len(escolhidas)} cena(s) viram clipe de motion, de graça: "
        + ", ".join(str(c["n"]) for c in escolhidas))
    return fazer(projeto, escolhidas, log)


def _gravar_classificacao(projeto, notas) -> None:
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        for c in dados["cenas"]:
            if c["n"] in notas:
                c["motion_util"], c["motion_util_fala"] = notas[c["n"]], _assinatura_util(c)
                c.pop("abstrata", None)
                c.pop("abstrata_fala", None)
        projeto.salvar_json("cenas.json", dados)


# ----------------------------------------------------------------------------------------- o HTML do modelo

INSTRUCOES_HTML = """Você é diretor de motion graphics no estilo editorial da Vox e das animações de produto de
SaaS. Escreve o código de UM clipe para uma cena de um documentário narrado, que vai entrar no vídeo NO LUGAR de uma
foto. A fala da cena traz um dado (um número com o que ele mede, uma comparação, uma causa e consequência, etapas)
ou uma ideia: o clipe explica isso com um diagrama limpo, como um infográfico animado.

Você devolve três campos: css, html e js. Eles entram num esqueleto pronto da fábrica:
- a tela tem 1920x1080 e o fundo já é creme (#F7F6F2) com grade de pontos: não pinte o fundo;
- o seu html vai dentro de <section id="cena">, que já ocupa a tela inteira (position: relative);
- já existe a linha do tempo do GSAP 3 numa variável tl (gsap.timeline paused) e a constante DUR (duração em segundos);
- fontes: "Texto" (Inter, sans-serif limpa, pesos 300 a 800) e "Titulo" (Playfair Display, serifa elegante);
- cores prontas em variáveis CSS: --verde (#166534), --azul (#2563EB), --laranja (#EA580C), --grafite (#1A1A1A);
- peças prontas (use as classes, não redefina a aparência delas):
  .m-card      card branco de cantos bem arredondados (squircle, raio 20px) com sombra suave; a fábrica faz ele
               flutuar sozinho (5px para cima e para baixo) depois de entrar. Você só posiciona o card (position:
               absolute, left, top, width, height). O card JÁ CENTRALIZA o que vai dentro, em coluna: dentro dele,
               NUNCA use position: absolute, left ou top (contariam da borda do card e o texto sairia da tela);
  .m-num       o número grande (168px, peso 800, linha justa), dentro de um .m-card;
  .m-rot       o que o número mede ("quilômetros por hora", "toneladas"), 44px, logo abaixo do .m-num;
  .m-sub       uma linha menor (34px) de complemento, se precisar;
  .m-frase     uma frase grande (76px), dentro de um card ou solta;
  .m-destaque  a palavra de ênfase: serifa Playfair, itálica, colorida (troque a cor com color: var(--laranja) etc.);
  .m-linha     um <path> de SVG que se desenha: a fábrica já deixa ele escondido no tamanho exato. Dê stroke e
               stroke-width no CSS e, para desenhar:
               tl.to(".m-linha-1", {strokeDashoffset: 0, duration: 0.8, ease: "power3.out"}, 1.2);
  .m-foto      SÓ quando o pedido disser que a cena tem foto: a foto da cena (o animal, a pessoa ou o lugar citado),
               já preenchendo o elemento. Use <div class="m-card m-foto"></div>, de 560x400 px ou maior, entrando
               primeiro; o dado vai ao lado dela, ligado por uma .m-linha. Nunca desenhe o bicho ou a coisa;
  .m-barra     barra de gráfico que cresce de baixo para cima: tl.fromTo(".m-barra-1", {scaleY: 0}, {scaleY: 1,
               duration: 0.7, ease: "back.out(1.7)"}, 0.9);

EXEMPLO, cena com foto e um dado ("pode passar dos 50 quilômetros por hora"):
  css:  #m-f { position: absolute; left: 190px; top: 230px; width: 700px; height: 470px; }
        #m-d { position: absolute; left: 1030px; top: 270px; width: 700px; height: 390px; }
        #m-l { position: absolute; left: 890px; top: 300px; width: 140px; height: 200px; }
        .m-linha-1 { stroke: var(--laranja); stroke-width: 4; }
  html: <div id="m-f" class="m-card m-foto"></div>
        <svg id="m-l" viewBox="0 0 140 200"><path class="m-linha m-linha-1" d="M 0 100 C 50 30, 90 30, 140 100"/></svg>
        <div id="m-d" class="m-card"><div class="m-num">50</div><div class="m-rot">quilômetros por
        <span class="m-destaque">hora</span></div></div>
  js:   tl.fromTo("#m-f", {y: 40, scale: 0.92, opacity: 0}, {y: 0, scale: 1, opacity: 1, duration: 0.7, ease: "back.out(1.7)"}, 0.1);
        tl.to(".m-linha-1", {strokeDashoffset: 0, duration: 0.6, ease: "power3.out"}, 0.6);
        tl.fromTo("#m-d", {y: 40, scale: 0.92, opacity: 0}, {y: 0, scale: 1, opacity: 1, duration: 0.7, ease: "back.out(1.7)"}, 0.8);
        tl.fromTo("#m-d .m-num, #m-d .m-rot", {y: 30, opacity: 0}, {y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.7)", stagger: 0.15}, 1.0);
Siga essa estrutura (card posicionado, conteúdo em fluxo dentro dele) e adapte à sua fala.

COMPOSIÇÃO (escolha UMA, pela fala):
- um número sozinho ("135 pessoas", "cerca de 24"): o número ENORME (160 a 240 px, peso 800) num .m-card, com o que
  ele mede logo abaixo (40 a 56 px). Nada de gráfico: barras ou seta sem os valores ditos na fala são invenção;
- crescimento ou vários valores citados na fala: um gráfico de barras (3 a 5 .m-barra subindo) com uma seta de
  tendência para cima em SVG (.m-linha) e o número principal num .m-card;
- fluxo, processo, causa e efeito: diagrama horizontal de 2 a 4 .m-card ligados por curvas de Bézier em SVG (.m-linha,
  path com C ou Q), cada card com um ícone geométrico simples em SVG (círculo, seta, check, losango) e um rótulo curto;
- comparação: dois .m-card lado a lado, com a diferença em destaque;
- ideia, conclusão ou chamada: a frase-chave grande, com a palavra de ênfase em .m-destaque, sobre um ou dois .m-card.
No topo pode vir um título curto: texto normal em "Texto" (grafite, peso 600) com UMA palavra em .m-destaque.
O conjunto fica CENTRALIZADO na área útil (de 140 a 1780 px na largura, de 140 a 820 px na altura) e ocupa de metade a
três quartos da largura: nada de diagrama encolhido num canto. Entre dois cards, no mínimo 60 px de espaço (a
linha que os liga passa nesse espaço): card encostado em card parece erro.

TAMANHOS MÍNIMOS (o vídeo é visto no celular): frase principal 72 px ou mais, número 140 px ou mais, título 56 px ou
mais, rótulo de card 36 px ou mais. Nenhum texto abaixo de 32 px.
FRASE: escreva a frase num bloco normal (display: block, text-align, white-space: nowrap se couber numa linha) com
cada palavra num <span class="m-p"> de display: inline-block. Nunca ponha as palavras como itens de um flex ou grid:
elas quebram em alturas diferentes. Frase comprida: quebre em no máximo 2 linhas com <br>.

REGRAS INEGOCIÁVEIS (o código confere e devolve o que quebrar):
1. TODA animação é feita no tl, com a posição em segundos: tl.fromTo(seletor, {de}, {para, duration, ease}, segundo).
   Nada de @keyframes, animation ou transition no CSS; nada de setTimeout, setInterval, requestAnimationFrame,
   Date, Math.random, fetch, imagens ou endereços externos. Tudo entra antes de DUR - 0.4.
2. Física de mola: cards, textos e barras entram com ease "back.out(1.7)". Card vem de y: 40, scale: 0.92 e
   opacity 0; palavra vem só de y: 30 e opacity 0 (sem scale: a mola faria uma palavra encostar na vizinha); barra
   vem de scaleY: 0. Linhas podem usar "power3.out". Proibido "linear", "none" e "power1.inOut". Nada aparece parado de uma vez.
3. Os elementos entram em sequência (0.12 a 0.3 s um do outro), na ordem em que a fala cita as coisas.
4. Texto: no máximo 14 palavras visíveis no clipe, TODAS tiradas da fala da cena (a palavra-chave, o número).
   Nada de frase inventada. Texto em grafite (var(--grafite)); destaque com .m-destaque.
5. Espaço: margem de 140 px dos lados e de cima, e os 260 px de baixo livres (é onde fica a legenda). Nada pode sair
   da tela nem encostar em outro elemento. Pelo menos 40% da tela fica vazia, só com o fundo de pontos.
6. Sem emojis, fotos, desenhos figurativos de objetos ou cliparts. Ícone só geométrico em SVG, de traço 3 a 4 px.
7. Use position: absolute só para os cards, os SVG e o que fica solto na tela, com left/top em px. O que vai dentro
   de um card fica em fluxo normal (.m-num, .m-rot, .m-sub, .m-frase). SVG com viewBox e tamanho em px.
8. Todo id e classe sua começa com "m-". Nada de position fixed. Não use transform no CSS dos .m-card nem das
   .m-barra (a animação cuida disso); para centralizar, calcule left e top."""

ESQUEMA_HTML = {
    "type": "object",
    "properties": {"css": {"type": "string"}, "html": {"type": "string"}, "js": {"type": "string"}},
    "required": ["css", "html", "js"],
}

_PROIBIDOS = [
    (r"@keyframes|(?<![-\w])animation\s*:|(?<![-\w])transition\s*:", "animação ou transição em CSS (tudo vai no tl)"),
    (r"setTimeout|setInterval|requestAnimationFrame", "relógio do navegador (tudo vai no tl)"),
    (r"Math\.random|Date\.now|new Date", "sorteio ou hora (o vídeo tem que sair igual sempre)"),
    (r"https?://|url\(\s*['\"]?(?!#)", "endereço externo ou imagem"),
    (r"fetch\(|XMLHttpRequest|import\s*\(", "chamada de rede"),
    (r"ease\s*:\s*['\"](?:linear|none|power1\.inOut)['\"]", "curva proibida (use back.out(1.7) nas entradas e power3.out nas linhas)"),
    (r"position\s*:\s*fixed", "position fixed"),
    (r"<script|</section|<body|<html|<head", "tag de documento dentro do html (só o conteúdo da cena)"),
]
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")


def problemas_do_codigo(partes) -> list:
    """O que o código acha de errado no que o modelo devolveu, antes de gastar um render."""
    erros = []
    tudo = "\n".join(str(partes.get(k) or "") for k in ("css", "html", "js"))
    for padrao, motivo in _PROIBIDOS:
        if re.search(padrao, tudo, re.I):
            erros.append(f"tem {motivo}")
    if _EMOJI.search(tudo):
        erros.append("tem emoji")
    if "tl." not in str(partes.get("js") or ""):
        erros.append("o js não anima nada no tl")
    elif not re.search(r"back\.out", str(partes.get("js") or "")):
        erros.append('as entradas não têm a mola: use ease "back.out(1.7)" nos cards, textos e barras')
    if not str(partes.get("html") or "").strip():
        erros.append("o html está vazio")
    # na cena 6 do natureza-teste-1min o css veio vazio: tudo caiu no canto esquerdo, com letra de 16px
    css = str(partes.get("css") or "")
    if not css.strip():
        erros.append("o css está vazio: posicione cada elemento (position: absolute, left, top, width) e dê o "
                     "tamanho de cada texto (font-size em px)")
    else:
        if not re.search(r"position\s*:\s*absolute", css + str(partes.get("html") or ""), re.I):
            erros.append("nada está posicionado: monte o diagrama com position: absolute, left e top em px")
        if re.sub(r"<[^>]+>", " ", str(partes.get("html") or "")).strip() and not any(
                int(t) >= 32 for t in re.findall(r"font-size\s*:\s*(\d+)", tudo)) and not re.search(
                r"\bm-(?:num|rot|sub|frase)\b", str(partes.get("html") or "")):
            erros.append("nenhum texto tem tamanho: use as peças .m-num, .m-rot, .m-sub e .m-frase, ou dê font-size "
                         "em px a cada texto (frase 72px ou mais, número 140px ou mais, rótulo 36px ou mais)")
    pequenos = sorted({int(t) for t in re.findall(r"font-size\s*:\s*(\d+)(?:\.\d+)?px", tudo) if int(t) < 32})
    if pequenos:
        erros.append(f"tem texto pequeno demais ({', '.join(str(t) + 'px' for t in pequenos)}): nenhum texto abaixo "
                     "de 32px (frase 72px ou mais, número 140px ou mais, rótulo 36px ou mais)")
    if len(tudo) > 20000:
        erros.append("o código passou de 20.000 caracteres: simplifique")
    return erros


def _palavras_inventadas(partes, fala) -> list:
    """Palavras do html que a fala não diz (tirando números, que podem vir escritos de outro jeito)."""
    texto = re.sub(r"<[^>]+>", " ", str(partes.get("html") or ""))
    normal = lambda t: unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
    ditas = set(re.findall(r"[a-z]+", normal(fala)))
    return [p for p in re.findall(r"[a-z]{4,}", normal(texto)) if p not in ditas][:6]


def montar_html(partes, dur, largura=1920, altura=1080, foto=None) -> str:
    """O esqueleto da fábrica com o que o modelo escreveu dentro: fundo creme com pontos, as peças prontas, a
    flutuação dos cards, o traço das linhas e a faixa da legenda."""
    dur = round(dur, 3)
    return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={largura}, height={altura}" />
    <script src="{animacoes.GSAP}"></script>
    <style>
      @font-face {{ font-family: "Titulo"; src: url("assets/fontes/PlayfairDisplay.ttf"); font-weight: 400 900; }}
      @font-face {{ font-family: "Texto"; src: url("assets/fontes/Inter.ttf"); font-weight: 100 900; }}
      :root {{ --verde: #166534; --azul: #2563EB; --laranja: #EA580C; --grafite: #1A1A1A; --creme: #F7F6F2; }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {largura}px; height: {altura}px; overflow: hidden; background: #F7F6F2; }}
      #root {{ position: relative; width: 100%; height: 100%; overflow: hidden; background-color: #F7F6F2;
               background-image: radial-gradient(#d1d0c9 1px, transparent 1px); background-size: 24px 24px;
               font-family: "Texto", system-ui, sans-serif; color: #1A1A1A; }}
      #cena {{ position: relative; width: 100%; height: 100%; transform-origin: 50% 42%; }}
      .m-card {{ background: #FFFFFF; border-radius: 20px; box-shadow: 0 12px 32px rgba(0, 0, 0, 0.06);
                 translate: 0 var(--m-fy, 0px); display: flex; flex-direction: column; align-items: center;
                 justify-content: center; gap: 10px; padding: 36px 44px; text-align: center; }}
      .m-num {{ font-size: 168px; font-weight: 800; line-height: 1; letter-spacing: -0.03em; color: #1A1A1A; }}
      .m-rot {{ font-size: 44px; font-weight: 600; line-height: 1.15; color: #1A1A1A; }}
      .m-sub {{ font-size: 34px; font-weight: 500; line-height: 1.2; color: #4A4843; }}
      .m-frase {{ font-size: 76px; font-weight: 600; line-height: 1.12; color: #1A1A1A; }}
      .m-destaque {{ font-family: "Titulo", Georgia, serif; font-style: italic; font-weight: 700; color: #2563EB; }}
      .m-linha {{ fill: none; stroke-linecap: round; }}
      .m-barra {{ transform-origin: 50% 100%; }}
      .m-foto {{ background: #ECEAE4 {f'url("assets/{foto}")' if foto else "none"} center / cover no-repeat; overflow: hidden; }}
      /* a legenda da fábrica é branca: a faixa de baixo escurece só o bastante para ela ser lida no fundo claro */
      #m-faixa-legenda {{ position: absolute; left: 0; right: 0; bottom: 0; height: 230px; pointer-events: none;
                          background: linear-gradient(to bottom, rgba(26, 26, 26, 0), rgba(26, 26, 26, 0.5)); }}
      /* do modelo */
{partes.get("css") or ""}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="{largura}" data-height="{altura}">
      <section id="cena" class="clip" data-start="0" data-duration="{dur}" data-track-index="1">
{partes.get("html") or ""}
      </section>
      <div id="m-faixa-legenda"></div>
    </div>
    <script>
      const DUR = {dur};
      const tl = gsap.timeline({{ paused: true }});
      // as linhas começam escondidas no tamanho exato: o modelo só leva strokeDashoffset a 0
      document.querySelectorAll(".m-linha").forEach(function (p) {{
        if (!p.getTotalLength) return;
        const L = Math.ceil(p.getTotalLength()) + 2;
        p.style.strokeDasharray = L + " " + L;
        p.style.strokeDashoffset = L;
      }});
      (function () {{
{partes.get("js") or ""}
      }})();
      // micro-movimento contínuo (PRD, item 3.C): cada card flutua 5px para cima e para baixo, fora de fase, e a cena
      // inteira aproxima de leve. A flutuação mexe no translate (CSS), que não briga com a entrada do modelo
      document.querySelectorAll(".m-card").forEach(function (el, i) {{
        const meio = 1.6, inicio = 0.15 * i;
        const vezes = Math.max(0, Math.ceil((DUR - inicio) / meio) - 1);
        tl.fromTo(el, {{ "--m-fy": "-5px" }}, {{ "--m-fy": "5px", duration: meio, ease: "sine.inOut", yoyo: true,
                                                 repeat: vezes }}, inicio);
      }});
      tl.fromTo("#cena", {{ scale: 1.0 }}, {{ scale: 1.03, duration: DUR, ease: "power1.out" }}, 0);
      window.__timelines["main"] = tl;
      // gravação quadro a quadro (PRD, item 6): o HyperFrames usa a linha do tempo; isto é para quem gravar por fora
      window.seekToFrame = function (frame, total, fps) {{ tl.seek(frame / (fps || 30)); }};
    </script>
  </body>
</html>
"""


def _pedido(cena, dur, vizinhas, erros, foto=False, direcao=None):
    linhas = [f"Fala desta cena: \"{(cena.get('texto') or '').strip()}\"",
              f"Duração: {dur:.2f} s (DUR)",
              f"Proporção: 16:9, 1920x1080"]
    if vizinhas[0]:
        linhas.append(f"Fala anterior (só contexto): \"{vizinhas[0]}\"")
    if vizinhas[1]:
        linhas.append(f"Fala seguinte (só contexto): \"{vizinhas[1]}\"")
    if direcao:
        # o desenho indicado é dos modelos prontos, que não serviram: aqui valem a leitura, o tom e o que é proibido
        linhas.append(texto_da_direcao({k: v for k, v in direcao.items() if k != "desenho"}))
    if (cena.get("mostrar") or "").strip():
        linhas.append(f"Ideia visual sugerida pelo diretor de arte (traduza num diagrama editorial, sem desenhar a coisa): {cena['mostrar'].strip()}")
    if foto:
        citado = (cena.get("exato") or cena.get("animal") or cena.get("sujeito") or "").strip()
        linhas.append(f"A cena TEM FOTO ({citado}): ponha um <div class=\"m-card m-foto\"></div> de 560x400 px ou "
                      "maior, entrando primeiro, e o dado da fala ao lado dela.")
    if erros:
        linhas.append("\nA resposta anterior foi REPROVADA por estes motivos. Corrija todos:\n- " + "\n- ".join(erros[:8]))
    return "\n".join(linhas)


# ------------------------------------------------------------------------------------------------- uma cena

INSTRUCOES_MODELO = """Você é diretor de motion graphics no estilo editorial da Vox. Para UMA cena de um
documentário narrado, escolha a demonstração visual que faz o espectador ENTENDER o dado da fala, e preencha os
campos dela. A fábrica desenha o clipe; você só escolhe o modelo e escreve os dados, tirados da fala.

""" + motion_modelos.CATALOGO + """

Regras:
1. Siga a DIREÇÃO DE ARTE do pedido (desenho indicado, tom e o que é proibido). Sem ela, escolha pelo SENTIDO do dado,
   não só pela unidade: velocidade é velocimetro; peso de um animal com foto é colagem_balanca (o próprio bicho na
   balança); sem foto, peso de coisa pesada é balanca e de coisa leve ou pequena é tipografia (nunca um peso de ferro
   para um bicho de meio quilo); tamanho é regua, quantidade de gente é contador,
   queda ou extinção é tendencia, causa e consequência é fluxo, posição é ranking. frase só quando a fala não tem
   número, comparação, causa nem posição.
2. Nada inventado: valor, rótulos, etapas, nome e frase saem da fala desta cena (ou das vizinhas, para dar sentido).
3. Variedade: quando a fala permitir mais de um modelo, não repita o que as cenas de motion vizinhas usaram.
4. Textos curtos: topo com até 7 palavras; etapas e rótulos com até 4 palavras."""

ESQUEMA_MODELO = {
    "type": "object",
    "properties": {
        "modelo": {"type": "string", "enum": list(motion_modelos.MODELOS)},
        "topo": {"type": "string"}, "destaque": {"type": "string"}, "valor": {"type": "number"},
        "unidade": {"type": "string"}, "prefixo": {"type": "string"}, "abreviacao": {"type": "string"},
        "forma": {"type": "string"}, "direcao": {"type": "string"}, "inicio": {"type": "string"},
        "fim": {"type": "string"}, "posicao": {"type": "integer"}, "total": {"type": "integer"},
        "nome": {"type": "string"}, "frase": {"type": "string"}, "texto": {"type": "string"},
        "tom": {"type": "string", "enum": list(motion_modelos.TONS)},
        "etapas": {"type": "array", "items": {"type": "string"}},
        "itens": {"type": "array", "items": {"type": "object", "properties": {
            "rotulo": {"type": "string"}, "valor": {"type": "number"}}}},
    },
    "required": ["modelo"],
}


# ------------------------------------------------------------------ a direção de arte, antes do desenho

# PRD Motion AI 2.0 (2026-10-07, pedido do usuário): o desenho saía da UNIDADE do dado. "Pesa pouco mais de meio
# quilo" achava "quilo", o código obrigava a balança e um peso de ferro despencava numa cena do mico-leão-dourado.
# Agora um diretor de arte lê a fala com o contexto (o assunto do bloco, o que a cena cita, as vizinhas) e decide o
# que o espectador tem de sentir, o tom do movimento, o desenho e o que fica proibido. A unidade virou só uma
# sugestão do código (motion_modelos.indicado), que ainda vale por cima numa regra: coisa leve nunca vai para a
# balança. Um pedido a mais por cena, só nos gratuitos; sem resposta, vale a direção do código (nunca para o vídeo).
VERSAO_DIRECAO = 1  # suba quando mudar as instruções: a direção guardada na pasta da cena é pedida de novo

INSTRUCOES_DIRECAO = """Você é o diretor de arte de um canal de documentários no estilo editorial da Vox. Uma cena
vai virar um clipe curto de motion graphics enquanto o narrador diz a fala dela. Antes de alguém desenhar, você
decide COMO mostrar, pelo sentido da fala no contexto do roteiro, e não pela unidade da medida.

Você decide:
- leitura: o que o espectador tem de sentir ou entender em 1 segundo (uma frase curta);
- tom: o movimento do clipe. "leve" (delicado, pequeno, frágil: entra devagar e flutua), "pesado" (enorme, maciço,
  brutal: despenca e assenta) ou "neutro" (o resto);
- desenho: UM dos desenhos do catálogo abaixo, o que demonstra o dado sem contradizer o assunto;
- desenhos_proibidos: os desenhos do catálogo que estragariam esta cena (vazio se nenhum);
- nao_mostrar: até 3 objetos ou imagens literais que contradizem o tom e não podem aparecer;
- motivo: por que, em até 20 palavras.

O erro que você existe para evitar: escolher pela unidade. "O mico-leão-dourado pesa pouco mais de meio quilo" fala
de peso, mas a ideia é a LEVEZA de um bicho pequeno: um peso de ferro caindo numa balança é o oposto disso. Aí vai
tipografia, tom leve, balanca proibida, e nada de peso de ferro, bigorna ou haltere. Já "o rinoceronte pesa mais de
uma tonelada" é a ideia de massa: balanca, tom pesado.
Quando a cena TEM FOTO do animal citado, o peso dele vira colagem_balanca: o próprio bicho recortado pousando numa
balança de cozinha, com o ponteiro e a etiqueta do valor (tom leve para o mico de meio quilo, pesado para a onça de
cem quilos). É o mais intuitivo, e é o próprio animal, não um objeto no lugar dele.
Sem foto, prefira tipografia quando o dado é uma qualidade (leveza, pequenez, raridade, fragilidade) e não uma medida
para comparar. Nunca escolha foto_dado nem colagem_balanca se o pedido disser que a cena não tem foto.

""" + motion_modelos.CATALOGO

ESQUEMA_DIRECAO = {
    "type": "object",
    "properties": {
        "leitura": {"type": "string"},
        "tom": {"type": "string", "enum": list(motion_modelos.TONS)},
        "desenho": {"type": "string", "enum": list(motion_modelos.MODELOS)},
        "desenhos_proibidos": {"type": "array", "items": {"type": "string"}},
        "nao_mostrar": {"type": "array", "items": {"type": "string"}},
        "motivo": {"type": "string"},
    },
    "required": ["leitura", "tom", "desenho"],
}


def direcao_pelo_codigo(cena, foto=False) -> dict:
    """A direção sem o diretor: o desenho que o dado da fala indica, com a regra de coisa leve (nunca a balança)."""
    texto = cena.get("texto") or ""
    dado = dado_na_fala(texto)
    desenho = motion_modelos.indicado(dado, texto, foto)
    direcao = {"desenho": desenho, "tom": "neutro", "desenhos_proibidos": [], "nao_mostrar": [], "origem": "codigo"}
    if desenho in ("tipografia", "colagem_balanca") and motion_modelos.leve(dado, texto):
        direcao.update(tom="leve", desenhos_proibidos=["balanca"], nao_mostrar=["peso de ferro", "bigorna"])
    elif desenho == "colagem_balanca" and motion_modelos.pesado(dado, texto):
        direcao["tom"] = "pesado"
    return direcao


def _limpar_direcao(resposta, cena, foto=False) -> dict:
    """A resposta do diretor conferida: desenho e proibidos só do catálogo, e a regra do código por cima."""
    base = direcao_pelo_codigo(cena, foto)
    modelos_validos = set(motion_modelos.MODELOS) - (set() if foto else set(motion_modelos.COM_FOTO))
    proibidos = [p for p in (resposta.get("desenhos_proibidos") or []) if p in motion_modelos.MODELOS]
    proibidos = list(dict.fromkeys(proibidos + base["desenhos_proibidos"]))
    desenho = str(resposta.get("desenho") or "").strip()
    if desenho not in modelos_validos or desenho in proibidos:
        desenho = base["desenho"] if base["desenho"] not in proibidos else ""
    tom = str(resposta.get("tom") or "").strip().lower()
    nao_mostrar = [" ".join(str(x).split())[:60] for x in resposta.get("nao_mostrar") or [] if str(x).strip()][:3]
    return {"leitura": " ".join(str(resposta.get("leitura") or "").split())[:200],
            "tom": tom if tom in motion_modelos.TONS else base["tom"], "desenho": desenho,
            "desenhos_proibidos": [p for p in proibidos if p != desenho],
            "nao_mostrar": nao_mostrar or base["nao_mostrar"],
            "motivo": " ".join(str(resposta.get("motivo") or "").split())[:200], "origem": "diretor"}


def _pedido_direcao(projeto, cena, vizinhas, foto) -> str:
    from . import corrigir
    texto = (cena.get("texto") or "").strip()
    linhas = [f"Fala desta cena: \"{texto}\""]
    if vizinhas[0]:
        linhas.append(f"Fala anterior (contexto): \"{vizinhas[0]}\"")
    if vizinhas[1]:
        linhas.append(f"Fala seguinte (contexto): \"{vizinhas[1]}\"")
    bloco = corrigir._bloco_da_cena_no_mapa(projeto, cena)
    if bloco:
        linhas.append(f"Assunto deste trecho do roteiro: {bloco}")
    citado = (cena.get("exato") or cena.get("animal") or cena.get("sujeito") or "").strip()
    if citado:
        linhas.append(f"A cena fala de: {citado}")
    dado = dado_na_fala(texto)
    if dado:
        linhas.append(f"Dado que o código achou na fala: {dado}")
        if motion_modelos.indicado(dado, texto, foto):
            linhas.append(f"Desenho que a unidade sugeriria (confira se combina com o sentido): "
                          f"{motion_modelos.indicado(dado, texto, foto)}")
    linhas.append("A cena TEM FOTO do assunto (foto_dado e colagem_balanca podem ser usados)." if foto else
                  "A cena NÃO tem foto: não use foto_dado nem colagem_balanca.")
    return "\n".join(linhas)


def dirigir(projeto, cena, vizinhas, foto=False, log=print) -> dict:
    """A direção de arte da cena, guardada na pasta do clipe (direcao.json) e só pedida de novo se a fala mudar.
    Sem resposta de nenhum modelo gratuito, vale a direção do código."""
    pasta = _pasta(projeto, cena["n"])
    marca = f"{_assinatura_fala(cena)}-v{VERSAO_DIRECAO}-{'foto' if foto else 'sem'}"
    arquivo = pasta / "direcao.json"
    try:
        guardada = json.loads(arquivo.read_text(encoding="utf-8"))
        if guardada.get("marca") == marca:
            return guardada["direcao"]
    except (OSError, ValueError, KeyError):
        pass
    try:
        resposta = _perguntar(projeto, "motion IA: direção de arte", INSTRUCOES_DIRECAO,
                              _pedido_direcao(projeto, cena, vizinhas, foto), ESQUEMA_DIRECAO, log, temperatura=0.2)
        direcao = _limpar_direcao(resposta or {}, cena, foto)
    except (RuntimeError, SystemExit) as e:
        log(f"  motion IA: cena {cena['n']}, sem direção de arte ({str(e)[:100]}); vale a do código")
        return direcao_pelo_codigo(cena, foto)
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps({"marca": marca, "direcao": direcao}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  motion IA: cena {cena['n']}, direção de arte: {direcao['desenho'] or 'livre'}, tom {direcao['tom']}"
        + (f", sem {', '.join(direcao['desenhos_proibidos'])}" if direcao["desenhos_proibidos"] else ""))
    return direcao


# ------------------------------------------------------------- o recorte do bicho para a colagem

INSTRUCOES_RECORTE = """Você aprova recortes para uma colagem de motion graphics no estilo da Vox. Cada número da
folha é um recorte diferente da MESMA foto, com a borda branca de figurinha, sobre um fundo cinza-azulado liso.
Um recorte serve quando mostra o assunto citado inteiro ou quase (cabeça e corpo), sem pedaços grandes do fundo da
foto (céu, folhagem, água, parede, outro bicho). O galho, a pedra ou o chão em que ele está apoiado pode ficar, se for
pouco. Responda o número do melhor recorte que serve, ou 0 se nenhum serve."""

ESQUEMA_RECORTE = {"type": "object", "properties": {"melhor": {"type": "integer"}, "motivo": {"type": "string"}},
                   "required": ["melhor"]}


def _recorte_da_cena(projeto, pasta, nome_foto, cena, log=print):
    """"recorte.png" (em assets/) se um recorte do bicho foi aprovado pela visão, ou None (o clipe usa a foto inteira
    na moldura). As contas do recorte.py aprovam recorte com fundo sobrando entre os galhos; quem olha é a cadeia de
    visão, só com os gratuitos. Guardado em recorte.json pela foto: não pergunta de novo."""
    from . import openrouter_local, recorte
    if not nome_foto:
        return None
    foto = pasta / "assets" / nome_foto
    marca = hashlib.sha1(foto.read_bytes()).hexdigest()[:12] if foto.exists() else ""
    arquivo = pasta / "recorte.json"
    try:
        guardado = json.loads(arquivo.read_text(encoding="utf-8"))
        if guardado.get("marca") == marca and (not guardado.get("arquivo")
                                               or (pasta / "assets" / guardado["arquivo"]).exists()):
            return guardado.get("arquivo") or None
    except (OSError, ValueError):
        pass
    escolhido, motivo = None, "nenhum recorte passou nas contas"
    opcoes = recorte.variantes(foto, pasta / "recortes") if marca else []
    if opcoes:
        citado = (cena.get("animal") or cena.get("exato") or cena.get("sujeito") or "o assunto da cena").strip()
        try:
            resposta = openrouter_local.VISAO.perguntar(
                projeto, "motion IA: recorte", INSTRUCOES_RECORTE,
                f"O assunto citado: {citado}. Há {len(opcoes)} recorte(s) na folha.", ESQUEMA_RECORTE, log=log,
                imagens=[recorte.folha(opcoes, pasta / "recortes" / "folha.jpg")], temperatura=0, so_gratuitos=True)
            k = int((resposta or {}).get("melhor") or 0)
            motivo = str((resposta or {}).get("motivo") or "")[:200]
            if 1 <= k <= len(opcoes):
                shutil.copy2(opcoes[k - 1], pasta / "assets" / "recorte.png")
                escolhido = "recorte.png"
        except (RuntimeError, SystemExit, ValueError, TypeError) as e:
            motivo = f"nenhum modelo de visão gratuito julgou o recorte ({str(e)[:100]})"
    log(f"  motion IA: cena {cena['n']}, " + ("bicho recortado para a colagem" if escolhido else
                                              f"sem recorte ({motivo}); vai a foto na moldura"))
    arquivo.write_text(json.dumps({"marca": marca, "arquivo": escolhido, "motivo": motivo}, ensure_ascii=False),
                       encoding="utf-8")
    return escolhido


def texto_da_direcao(direcao) -> str:
    """A direção de arte no pedido de quem desenha e de quem revisa."""
    if not direcao:
        return ""
    linhas = ["DIREÇÃO DE ARTE (siga):"]
    if direcao.get("leitura"):
        linhas.append(f"- o espectador tem de sentir: {direcao['leitura']}")
    linhas.append(f"- tom do movimento: {direcao.get('tom') or 'neutro'}")
    if direcao.get("desenho"):
        linhas.append(f"- desenho indicado: {direcao['desenho']}")
    if direcao.get("desenhos_proibidos"):
        linhas.append(f"- desenhos proibidos: {', '.join(direcao['desenhos_proibidos'])}")
    if direcao.get("nao_mostrar"):
        linhas.append(f"- nunca mostrar: {', '.join(direcao['nao_mostrar'])}")
    return "\n".join(linhas)


def _pedido_modelo(cena, dur, vizinhas, erros, foto, usados, direcao=None):
    texto = (cena.get("texto") or "").strip()
    linhas = [f"Fala desta cena: \"{texto}\"", f"Duração: {dur:.2f} s"]
    if vizinhas[0]:
        linhas.append(f"Fala anterior (contexto): \"{vizinhas[0]}\"")
    if vizinhas[1]:
        linhas.append(f"Fala seguinte (contexto): \"{vizinhas[1]}\"")
    dado = dado_na_fala(texto)
    if dado:
        linhas.append(f"Dado que o código achou na fala: {dado}")
        if motion_modelos.indicado(dado, texto, foto) and not (direcao or {}).get("desenho"):
            linhas.append(f"Modelo indicado para esse dado: {motion_modelos.indicado(dado, texto, foto)}")
    if direcao:
        linhas.append(texto_da_direcao(direcao))
    if (cena.get("mostrar") or "").strip():
        linhas.append(f"O que o agente de roteiro pediu para a imagem da cena (só contexto): {cena['mostrar'].strip()}")
    linhas.append("A cena TEM FOTO (os modelos foto_dado e colagem_balanca podem ser usados)." if foto else
                  "A cena NÃO tem foto: não use foto_dado nem colagem_balanca.")
    if usados:
        linhas.append("Modelos das cenas de motion vizinhas: " + ", ".join(usados) + ". Evite repetir.")
    if erros:
        linhas.append("\nA resposta anterior foi REPROVADA por estes motivos. Corrija todos:\n- " + "\n- ".join(erros[:8]))
    return "\n".join(linhas)


def _pelo_modelo_pronto(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, erros_iniciais=(),
                        direcao=None):
    """O modelo de linguagem escolhe a demonstração (motion_modelos) e preenche os dados; a fábrica desenha.
    Devolve as partes aprovadas, com o modelo e os dados, ou levanta RuntimeError.
    erros_iniciais: o que a crítica visual apontou no clipe anterior (vai no primeiro pedido).
    direcao: a direção de arte (dirigir): o desenho indicado, os proibidos e o tom."""
    texto = cena.get("texto") or ""
    fala = " ".join([vizinhas[0], texto, vizinhas[1]])
    direcao = direcao or direcao_pelo_codigo(cena, bool(nome_foto))
    sugerido = direcao.get("desenho") or motion_modelos.indicado(dado_na_fala(texto), texto, bool(nome_foto))
    erros = list(erros_iniciais)
    for tentativa in range(int(config(projeto).get("tentativas_modelo", 3))):
        resposta = _perguntar(projeto, "motion IA: modelo", INSTRUCOES_MODELO,
                              _pedido_modelo(cena, dur, vizinhas, erros, bool(nome_foto), usados, direcao),
                              ESQUEMA_MODELO, log, temperatura=0.4 if tentativa else 0.2)
        modelo = str(resposta.get("modelo") or "").strip()
        dados, erros = motion_modelos.conferir(modelo, resposta, fala, tem_foto=bool(nome_foto), fala_da_cena=texto,
                                               sugerido=sugerido, proibidos=direcao.get("desenhos_proibidos") or ())
        if erros:
            continue
        if modelo in ("tipografia", "colagem_balanca") and direcao.get("tom") in motion_modelos.TONS:
            dados["tom"] = direcao["tom"]  # o movimento é decisão da direção de arte
        figura = None
        if modelo == "colagem_balanca":
            figura = _recorte_da_cena(projeto, pasta, nome_foto, cena, log)
            dados["moldura"] = figura is None  # sem recorte aprovado, a foto inteira na moldura de papel rasgado
            figura = figura or nome_foto
        partes = motion_modelos.partes(modelo, dados, dur, figura)
        (pasta / "index.html").write_text(montar_html(partes, dur, foto=nome_foto if modelo == "foto_dado" else None),
                                          encoding="utf-8")
        erros = [e for e in animacoes._erros_para_o_modelo(animacoes._conferir(projeto, pasta, clipe=True))]
        if not erros:
            return {**partes, "modelo": modelo, "dados": dados, "versao_modelos": motion_modelos.VERSAO,
                    "foto": nome_foto if modelo == "foto_dado" else "", "direcao": direcao}
    raise RuntimeError("; ".join(erros)[:300] or "o modelo não respondeu")


def _pasta(projeto, n) -> Path:
    return projeto.pasta / "motion_ia" / f"{n:04d}"


# --------------------------------------------------------------------- a crítica visual, antes de gravar

# Do vídeo "Como Criar Motion Graphics INSANOS com Opus 5.5" (Felipe Borges), estudado a pedido do usuário em
# 2026-10-06: antes de gravar, tirar uns quadros do clipe numa folha de contato, OLHAR, dar nota de 1 a 10 e corrigir
# os piores problemas até tudo passar de 8; só então gravar. Até aqui ninguém olhava o clipe: o código conferia o HTML
# e o HyperFrames, texto sobreposto ou fora da tela. Quem olha é a cadeia de visão, só com os gratuitos (custo zero),
# e os quadros saem do `hyperframes snapshot` (uns 8 s, sem gravar o MP4).
CRITERIOS = {
    "legibilidade": "cada quadro da folha tem o tamanho de uma tela de celular: dá para ler TODO texto sem esforço?",
    "composicao": "o conjunto está equilibrado e ocupa bem a área útil? Nada cortado, sobreposto, encostado, nem "
                  "espremido num canto com o resto da tela vazio",
    "clareza": "olhando o último quadro por 1 segundo, a pessoa entende o dado ou a ideia da fala?",
    "fidelidade": "o que está escrito e desenhado é o que a fala diz? Número certo, palavras da fala, sem erro de "
                  "escrita, sem desenho que não combina com o dado (um velocímetro para um peso) nem objeto literal "
                  "que contradiz o tom da cena (um peso de ferro para um bicho de meio quilo) ou que a direção de "
                  "arte proibiu",
    "movimento": "comparando os quadros, a cena se monta ao longo do tempo, sem tela vazia ou parada demais, e o "
                 "último quadro está completo?",
    "acabamento": "parece motion graphics de um canal grande (Vox), e não um slide amador? Hierarquia clara, cores "
                  "contidas, uma cor de destaque",
}

INSTRUCOES_CRITICA = """Você é o diretor de arte que aprova os clipes de motion graphics de um canal de documentários
antes de eles serem gravados. Recebe a folha de contato de UM clipe (alguns quadros em ordem, com o segundo de cada um
no alto) e a fala da cena. O clipe entra no vídeo no lugar de uma foto, enquanto o narrador diz a fala.

O que é de propósito e NÃO é problema: o fundo creme com grade de pontos, a faixa que escurece a parte de baixo (é onde
a legenda vai entrar, por isso nada importante fica ali), os cards brancos de cantos arredondados, a palavra de
destaque em serifa itálica colorida, o primeiro quadro ainda incompleto (as coisas estão entrando).

Dê uma nota de 1 a 10 a cada critério (10 é pronto para publicar, 8 é bom, 5 é fraco, 1 é inaceitável):
""" + "\n".join(f"- {k}: {v}" for k, v in CRITERIOS.items()) + """

Seja exigente e justo: não invente problema, e não dê 9 ou 10 por educação. Em problemas, os até 3 piores, do pior
para o menos ruim, cada um com o critério, o que está errado (o que se vê, onde) e a correção concreta, em até 25
palavras, escrita para quem faz o clipe. Tudo em português."""

ESQUEMA_CRITICA = {
    "type": "object",
    "properties": {
        "notas": {"type": "object", "properties": {k: {"type": "integer"} for k in CRITERIOS},
                  "required": list(CRITERIOS)},
        "problemas": {"type": "array", "items": {"type": "object", "properties": {
            "criterio": {"type": "string"}, "problema": {"type": "string"}, "correcao": {"type": "string"}},
            "required": ["criterio", "problema", "correcao"]}},
    },
    "required": ["notas", "problemas"],
}


def critica_config(projeto) -> dict:
    """motion_ia.critica do config.yaml: ativa, nota (8), aceitavel (5) e rodadas (3)."""
    return {"ativa": True, "nota": 8, "aceitavel": 5, "rodadas": 3, **(config(projeto).get("critica") or {})}


def _folha_de_contato(projeto, pasta, dur):
    """Os quadros do clipe numa folha só, pelo `hyperframes snapshot`, sem gravar o MP4. None se não saiu."""
    destino = pasta / "quadros"
    shutil.rmtree(destino, ignore_errors=True)
    momentos = sorted({round(min(0.6, dur * 0.2), 2), round(dur * 0.45, 2), round(dur * 0.75, 2)})
    # --describe=false: sem isso o HyperFrames manda os quadros para o Gemini, que a fábrica não usa
    r = animacoes._hyperframes(projeto, ["snapshot", "--at", ",".join(f"{t:.2f}" for t in momentos),
                                         "--describe=false", "-o", str(destino), "."], pasta, 240)
    folha = destino / "contact-sheet.jpg"
    return folha if r.returncode == 0 and folha.exists() else None


def _pedido_critica(cena, dur, aprovado, vizinhas, direcao=None) -> str:
    linhas = [f"Fala desta cena: \"{(cena.get('texto') or '').strip()}\"", f"Duração do clipe: {dur:.2f} s"]
    if vizinhas[0]:
        linhas.append(f"Fala anterior (contexto): \"{vizinhas[0]}\"")
    if vizinhas[1]:
        linhas.append(f"Fala seguinte (contexto): \"{vizinhas[1]}\"")
    if direcao:
        linhas.append(texto_da_direcao(direcao).replace("(siga)", "(confira no clipe; algo proibido aparecendo é "
                                                                   "problema de fidelidade)"))
    if aprovado.get("modelo") and aprovado["modelo"] != "livre":
        linhas.append(f"O clipe usa o desenho pronto \"{aprovado['modelo']}\", com estes dados: "
                      + json.dumps(aprovado.get("dados") or {}, ensure_ascii=False)
                      + ". Quem corrige só pode trocar de desenho (" + ", ".join(motion_modelos.MODELOS)
                      + ") ou mudar os dados e textos: escreva a correção nesses termos.")
    else:
        linhas.append("O clipe foi escrito em HTML: a correção pode mudar posição, tamanho, textos e a ordem das entradas.")
    return "\n".join(linhas)


def _ler_critica(resposta):
    """As notas (1 a 10) e os até 3 piores problemas, do pior para o menos ruim. None se não veio nota nenhuma."""
    bruto = (resposta or {}).get("notas") or {}
    notas = {}
    for k in CRITERIOS:
        try:
            notas[k] = max(1, min(10, int(round(float(bruto.get(k))))))
        except (TypeError, ValueError):
            continue
    if not notas:
        return None
    problemas = []
    for p in (resposta or {}).get("problemas") or []:
        # o Qwen do Groq repetiu o mesmo problema duas vezes na primeira revisão de verdade (cena 76 do nunca-deve...)
        if isinstance(p, dict) and str(p.get("problema") or "").strip() and not any(
                " ".join(str(p["problema"]).split())[:240] == q["problema"] for q in problemas):
            criterio = str(p.get("criterio") or "").strip().lower()
            problemas.append({"criterio": criterio if criterio in notas else "",
                              "problema": " ".join(str(p["problema"]).split())[:240],
                              "correcao": " ".join(str(p.get("correcao") or "").split())[:240]})
    problemas.sort(key=lambda p: notas.get(p["criterio"], 10))
    return {"notas": notas, "menor": min(notas.values()), "media": round(sum(notas.values()) / len(notas), 1),
            "problemas": problemas[:3]}


def criticar(projeto, pasta, cena, dur, aprovado, vizinhas, log=print, direcao=None):
    """A nota do clipe que está em pasta/index.html, olhando a folha de contato. None quando não deu para olhar (o
    snapshot falhou, nenhum modelo de visão gratuito atendeu): o clipe segue sem a crítica, nunca para o vídeo."""
    from . import openrouter_local
    folha = _folha_de_contato(projeto, pasta, dur)
    if folha is None:
        log(f"  motion IA: cena {cena['n']}, os quadros para a revisão visual não saíram; segue sem ela")
        return None
    try:
        resposta = openrouter_local.VISAO.perguntar(projeto, "motion IA: revisão visual", INSTRUCOES_CRITICA,
                                                    _pedido_critica(cena, dur, aprovado, vizinhas, direcao),
                                                    ESQUEMA_CRITICA,
                                                    log=log, imagens=[folha], temperatura=0, so_gratuitos=True)
    except (RuntimeError, SystemExit) as e:
        log(f"  motion IA: cena {cena['n']}, nenhum modelo gratuito fez a revisão visual ({str(e)[:100]}); segue sem ela")
        return None
    critica = _ler_critica(resposta)
    if critica is not None:
        shutil.copy2(folha, pasta / "revisao.jpg")  # a folha da última revisão fica, para a pessoa ver o que foi julgado
    return critica


def erros_da_critica(critica, nota) -> list:
    """O que volta para quem faz o clipe: os problemas apontados, com a nota de cada um."""
    erros = []
    for p in critica["problemas"]:
        rotulo = f"{p['criterio']} {critica['notas'][p['criterio']]}/10" if p["criterio"] else "revisão visual"
        erros.append(f"revisão visual ({rotulo}): {p['problema']}" + (f" Correção: {p['correcao']}" if p["correcao"] else ""))
    if not erros:
        piores = [k for k, v in critica["notas"].items() if v < nota]
        erros.append("a revisão visual deu nota baixa em " + ", ".join(piores) + ": " + "; ".join(CRITERIOS[k] for k in piores))
    return erros


def _chave(critica) -> tuple:
    return critica["menor"], critica["media"]


def _resumo(critica) -> str:
    return " ".join(f"{k} {v}" for k, v in critica["notas"].items())


# ------------------------------------------------------------------------------------------------ o clipe

def _pelo_html_livre(projeto, cena, dur, vizinhas, pasta, nome_foto, log, erros_iniciais=(), direcao=None):
    """O HTML escrito pelo modelo dentro do esqueleto, de reserva. Devolve as partes aprovadas ou levanta RuntimeError."""
    erros = list(erros_iniciais)
    for tentativa in range(int(config(projeto).get("tentativas", 3))):
        resposta = _perguntar(projeto, "motion IA: html", INSTRUCOES_HTML,
                              _pedido(cena, dur, vizinhas, erros, foto=bool(nome_foto), direcao=direcao),
                              ESQUEMA_HTML, log, temperatura=0.5 if tentativa else 0.3)
        partes = {k: str(resposta.get(k) or "") for k in ("css", "html", "js")}
        erros = problemas_do_codigo(partes)
        if nome_foto and "m-foto" not in partes["html"]:
            erros.append('a cena tem foto e o html não a mostra: ponha um <div class="m-card m-foto"></div> de '
                         '560x400 px ou maior')
        inventadas = _palavras_inventadas(partes, " ".join([vizinhas[0], cena.get("texto") or "", vizinhas[1]]))
        if inventadas:
            erros.append("usa palavras que a fala não diz (" + ", ".join(inventadas) + "): só palavras da fala")
        if erros:
            continue
        (pasta / "index.html").write_text(montar_html(partes, dur, foto=nome_foto), encoding="utf-8")
        brutos = animacoes._conferir(projeto, pasta, clipe=True)
        erros = animacoes._erros_para_o_modelo(brutos)
        if any(e.startswith(animacoes._ESTOURO_NO_CLIPE) for e in brutos):
            erros.insert(0, "há texto fora da tela ou fora do card: um elemento com position: absolute DENTRO de um "
                            ".m-card conta left e top a partir da borda do card, não da tela. Dentro do card, use "
                            "left e top pequenos (ou nenhum, em fluxo normal) e confira que tudo cabe no card")
        if not erros:
            return {**partes, "modelo": "livre", "foto": nome_foto or "", "direcao": direcao or {}}
    raise RuntimeError("reprovado na conferência: " + "; ".join(erros)[:300])


def _um_clipe(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, erros_visuais=(), direcao=None):
    """Um clipe aprovado pelo código e pelo HyperFrames, ainda sem a revisão visual: primeiro um modelo pronto de
    demonstração; se nenhum servir, o HTML livre."""
    try:
        aprovado = _pelo_modelo_pronto(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, erros_visuais,
                                       direcao)
        log(f"  motion IA: cena {cena['n']}, modelo {aprovado['modelo']}")
        return aprovado
    except (RuntimeError, SystemExit) as e:
        log(f"  motion IA: cena {cena['n']}, nenhum modelo pronto serviu ({str(e)[:120]}); vai o HTML livre")
    return _pelo_html_livre(projeto, cena, dur, vizinhas, pasta, nome_foto, log, erros_visuais, direcao)


def _revisado(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, direcao=None):
    """O clipe que passou na revisão visual (todas as notas em critica.nota ou mais), em até critica.rodadas
    revisões. Sem passar, fica o de melhor nota se a pior nota dele chegar a critica.aceitavel; senão RuntimeError,
    e a cena segue o caminho de antes."""
    cfg = critica_config(projeto)
    aprovado = _um_clipe(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, direcao=direcao)
    if not cfg["ativa"]:
        return aprovado
    melhor, historico = None, []
    for rodada in range(max(1, int(cfg["rodadas"]))):
        critica = criticar(projeto, pasta, cena, dur, aprovado, vizinhas, log, direcao)
        if critica is None:
            break
        historico.append({"rodada": rodada + 1, "modelo": aprovado.get("modelo"), **critica})
        aprovado["critica"] = historico[-1]
        if melhor is None or _chave(critica) > _chave(melhor["critica"]):
            melhor = aprovado
        passou = critica["menor"] >= float(cfg["nota"])
        log(f"  motion IA: cena {cena['n']}, revisão visual {rodada + 1}: {_resumo(critica)}"
            + (" (aprovado)" if passou else ""))
        if passou or rodada == int(cfg["rodadas"]) - 1:
            break
        try:
            aprovado = _um_clipe(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log,
                                 erros_da_critica(critica, float(cfg["nota"])), direcao)
        except (RuntimeError, SystemExit) as e:
            log(f"  motion IA: cena {cena['n']}, a correção não saiu ({str(e)[:120]}); fica o de melhor nota")
            break
    if melhor is None:
        return aprovado
    if melhor["critica"]["menor"] < float(cfg["aceitavel"]):
        raise RuntimeError(f"reprovado na revisão visual ({_resumo(melhor['critica'])}): "
                           + "; ".join(p["problema"] for p in melhor["critica"]["problemas"])[:240])
    melhor["criticas"] = historico
    return melhor


def gerar_cena(projeto, cena, vizinhas, log=print, foto=None, usados=()):
    """Faz o clipe de uma cena. Devolve o caminho relativo do MP4, ou levanta RuntimeError com o motivo.

    Primeiro um modelo pronto de demonstração (motion_modelos: velocímetro, balança, régua...), escolhido e preenchido
    pelo modelo de linguagem; se nenhum servir, o HTML livre do modelo, de reserva. Antes de gravar, a revisão visual
    olha os quadros e devolve o que tirou nota baixa (_revisado).
    foto: a imagem da própria cena, opcional (o modelo foto_dado). usados: os modelos das cenas de motion vizinhas."""
    if not animacoes.node_pronto():
        raise RuntimeError("falta o Node.js 22 ou mais (o HyperFrames grava o clipe)")
    dur = max(float(cena["fim"]) - float(cena["ini"]), 1.0)
    pasta = _pasta(projeto, cena["n"])
    pasta.mkdir(parents=True, exist_ok=True)
    animacoes._preparar_pasta(pasta)
    nome_foto = None
    if foto is not None:
        nome_foto = f"foto{Path(foto).suffix.lower()}"
        shutil.copy2(foto, pasta / "assets" / nome_foto)
    direcao = dirigir(projeto, cena, vizinhas, bool(nome_foto), log)
    aprovado = _revisado(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, direcao)
    # a revisão pode ter ficado com um clipe de uma rodada anterior: a página gravada é sempre a dele
    (pasta / "index.html").write_text(montar_html(aprovado, dur, foto=aprovado.get("foto") or None), encoding="utf-8")
    (pasta / "partes.json").write_text(json.dumps(aprovado, ensure_ascii=False, indent=1), encoding="utf-8")
    destino = projeto.pasta / "midia" / f"{cena['n']:04d}_motion.mp4"
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.stem + ".tmp.mp4")
    r = animacoes._hyperframes(projeto, ["render", "--output", str(temporario), "--format", "mp4", "--fps",
                                         str(fps(projeto)), "--workers", "1", "--quiet"],
                               pasta, 900)
    if r.returncode != 0 or not temporario.exists() or temporario.stat().st_size < 1000:
        temporario.unlink(missing_ok=True)
        raise RuntimeError(f"o HyperFrames não gravou o clipe: {(r.stderr or r.stdout or '')[-200:]}")
    temporario.replace(destino)
    capa = destino.with_name(f"{cena['n']:04d}_motion_capa.jpg")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{min(dur * 0.6, dur - 0.1):.2f}", "-i", str(destino),
           "-frames:v", "1", "-q:v", "3", str(capa)])
    # o HTML é só um passo: fica o partes.json, para refazer ou conferir depois
    (pasta / "index.html").unlink(missing_ok=True)
    shutil.rmtree(pasta / "quadros", ignore_errors=True)
    return destino, capa, dur


def _aplicar(projeto, n, destino, capa, dur) -> None:
    """O clipe entra como a mídia da cena, igual a um vídeo de banco. O que a cena tinha fica em motion_reserva."""
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        c = next(x for x in dados["cenas"] if x["n"] == n)
        if not (e_motion(c) and c.get("motion_reserva")):  # refazer um motion: a reserva é a foto de antes dele
            c["motion_reserva"] = {k: c.get(k) for k in ("midia", "tipo", "busca", "captura", "conferencia", "ia_reserva")}
        c["midia"] = {"fonte": FONTE, "id": f"{n:04d}-{int(time.time())}", "tipo": "video",
                      "arquivo": destino.relative_to(projeto.pasta).as_posix(),
                      "capa": capa.relative_to(projeto.pasta).as_posix() if capa.exists() else None,
                      "autor": "", "licenca": "feito pela fábrica", "pagina": "", "duracao": round(dur, 2)}
        c["tipo"] = "video_real"
        c["captura"] = {"conferida": True, "motion_ia": True}
        for campo in ("sem_midia_real", "conferencia", "motion_ia_falhou", "motion_so"):
            c.pop(campo, None)
        projeto.salvar_json("cenas.json", dados)


def _marcar_falha(projeto, n, motivo) -> None:
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        c = next((x for x in dados["cenas"] if x["n"] == n), None)
        if c is not None:
            c["motion_ia_falhou"] = {"motivo": motivo[:300], "fala": _assinatura_fala(c)}
            projeto.salvar_json("cenas.json", dados)


# ---------------------------------------------------------------------------------------------- a etapa

def candidatas(projeto, cenas, refazer=False) -> list:
    """Cenas que iriam para a imagem de IA e podem virar motion: sem prompt ou imagem da pessoa, sem personagem e sem
    uma falha de motion na mesma fala. refazer=True (a pessoa pediu a cena pelo número): a cena que já é motion, ou
    que falhou ou foi desfeita, entra de novo."""
    saida = []
    for c in cenas:
        falha = c.get("motion_ia_falhou") or {}
        if (c.get("prompt_manual") or c.get("imagem_da_pessoa") or c.get("personagem")
                or not (c.get("texto") or "").strip()):
            continue
        if not refazer and (e_motion(c) or falha.get("fala") == _assinatura_fala(c)):
            continue
        saida.append(c)
    return saida


def resolver(projeto, pendentes, log=print) -> list:
    """As cenas pendentes de imagem de IA em que o Jev diz que o motion vale a pena viram clipe de motion. Devolve as
    cenas resolvidas.

    Chamado por imagens._gerar antes de gerar qualquer imagem: vale para a criação, a conferência e o diretor."""
    if not ligado(projeto) or not pendentes:
        return []
    cands = candidatas(projeto, pendentes)
    if not cands:
        return []
    if not modelos(projeto):
        log("  motion IA: nenhum modelo gratuito configurado, as cenas seguem para a imagem de IA")
        return []
    if not animacoes.node_pronto():
        log("  motion IA: falta o Node.js 22 ou mais, as cenas seguem para a imagem de IA")
        return []
    tipos = classificar(projeto, cands, log)
    todas = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}
    escolhidas = [todas.get(c["n"], c) for c in cands if tipos.get(c["n"])]
    if not escolhidas:
        return []
    log(f"  motion IA: {len(escolhidas)} cena(s) viram clipe de motion, de graça: "
        + ", ".join(str(c["n"]) for c in escolhidas))
    return fazer(projeto, escolhidas, log)


def fazer(projeto, escolhidas, log=print) -> list:
    """Grava o clipe de cada cena e põe no lugar da mídia. Devolve as que saíram; a que falhar fica como estava."""
    todas = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}

    def uma(c):
        antes, depois = todas.get(c["n"] - 1) or {}, todas.get(c["n"] + 1) or {}
        vizinhas = ((antes.get("texto") or "").strip()[-200:], (depois.get("texto") or "").strip()[:200])
        try:
            foto = foto_da_cena(projeto, c) if concreta(c) else None
            destino, capa, dur = gerar_cena(projeto, c, vizinhas, log, foto=foto,
                                            usados=modelos_vizinhos(projeto, todas, c["n"]))
            _aplicar(projeto, c["n"], destino, capa, dur)
            return c["n"], None
        except (Exception, SystemExit) as erro:
            return c["n"], str(erro) or erro.__class__.__name__

    feitas = []
    with ThreadPoolExecutor(max(1, int(config(projeto).get("paralelo", 2)))) as executor:
        for n, erro in executor.map(uma, escolhidas):
            if erro is None:
                feitas.append(n)
                log(f"  motion IA: cena {n} pronta")
            else:
                _marcar_falha(projeto, n, erro)
                log(f"  motion IA: cena {n} não saiu ({erro[:160]}); segue o caminho de antes")
    return feitas


def modelo_da_cena(projeto, n) -> str:
    """O modelo de demonstração do clipe de motion da cena (velocimetro, regua...), ou "" se não houver."""
    try:
        return json.loads((_pasta(projeto, n) / "partes.json").read_text(encoding="utf-8")).get("modelo") or "livre"
    except (OSError, ValueError):
        return ""


def modelos_vizinhos(projeto, todas, n, raio=4) -> list:
    """Os modelos dos clipes de motion nas cenas perto desta: o pedido avisa, para variar a demonstração."""
    return [f"{modelo_da_cena(projeto, k)} (cena {k})" for k in range(n - raio, n + raio + 1)
            if k != n and e_motion(todas.get(k) or {}) and modelo_da_cena(projeto, k)]


def desfazer(projeto, n) -> bool:
    """A cena volta para o que tinha antes do motion (o editor, ou um teste). O clipe fica em midia/."""
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        c = next((x for x in dados["cenas"] if x["n"] == n), None)
        if c is None or not e_motion(c) or not c.get("motion_reserva"):
            return False
        reserva = c.pop("motion_reserva")
        for campo, valor in reserva.items():
            if valor is None:
                c.pop(campo, None)
            else:
                c[campo] = valor
        # desfeito por alguém: a criação não faz o motion de novo nesta fala (candidatas)
        c["motion_ia_falhou"] = {"motivo": "desfeito", "fala": _assinatura_fala(c)}
        projeto.salvar_json("cenas.json", dados)
    return True


# ------------------------------------------------------------------- o som do clipe, no tempo do movimento

# Do mesmo vídeo estudado em 2026-10-06: o que mais muda o nível de um motion é o som batendo junto com cada
# movimento. Os clipes do Motion IA saíam mudos. Os momentos saem da própria linha do tempo do clipe (o js do
# partes.json): card ou texto entrando é um pop, linha se desenhando é um risco, número contando é a contagem e peso
# caindo é um baque. Os sons são tocados pelo código (trilha._efeito) e misturados num arquivo por clipe, que o render
# põe no segundo da cena (sons_na_linha). Vale também para os clipes já gravados, sem gravar de novo.
VERSAO_SONS = 1  # suba quando mudar a leitura dos momentos ou a mistura: os arquivos de som dos clipes são refeitos
PRIORIDADE_SONS = ("baque", "contagem", "risco", "pop")  # quando dois caem juntos, fica o da frente
NIVEL_SONS = {"pop": 0.0, "risco": -4.0, "baque": 3.0, "contagem": -3.0}  # dB entre eles, antes do volume do clipe
_INICIO_CHAMADA = re.compile(r"\btl\.(fromTo|from|to)\(")


def _chamadas(js):
    """(método, argumentos) de cada tl.fromTo/tl.from/tl.to do js, contando os parênteses fora das aspas."""
    saida = []
    for achado in _INICIO_CHAMADA.finditer(js or ""):
        k, nivel, aspa = achado.end(), 1, ""
        while k < len(js) and nivel:
            ch = js[k]
            if aspa:
                aspa = "" if ch == aspa and js[k - 1] != "\\" else aspa
            elif ch in "\"'`":
                aspa = ch
            elif ch == "(":
                nivel += 1
            elif ch == ")":
                nivel -= 1
            k += 1
        if not nivel:
            saida.append((achado.group(1), js[achado.end():k - 1]))
    return saida


def _som_da_chamada(metodo, args):
    """(segundos depois da posição, som) que a chamada pede, ou None (movimento contínuo, saída, ajuste)."""
    if re.search(r"\brepeat\s*:|\byoyo\b|sine\.inOut", args):
        return None  # flutuação, pulsar, respiração: movimento de fundo não tem som
    if "strokeDashoffset" in args:
        return 0.0, "risco"
    if "onUpdate" in args and re.search(r"\bv\s*:", args):
        return 0.0, "contagem"
    if "bounce" in args:
        duracao = re.search(r"duration\s*:\s*([\d.]+)", args)
        return round(float(duracao.group(1)) * 0.36, 3) if duracao else 0.25, "baque"  # o primeiro toque no chão
    de = args[args.find("{"):args.find("}") + 1] if "{" in args else ""
    if metodo == "from" or (metodo == "fromTo" and re.search(r"opacity\s*:\s*0(?:\.0+)?\s*[,}]|scale[XY]?\s*:\s*0(?:\.[0-5]\d*)?\s*[,}]", de)):
        return 0.0, "pop"
    return None


def eventos_de_som(js, dur, maximo=6):
    """(segundo do clipe, som) de cada movimento que merece som, no máximo `maximo`, com 0,3 s entre eles."""
    brutos = []
    for metodo, args in _chamadas(js):
        posicao = re.search(r",\s*([\d.]+)\s*$", args.strip())
        som = _som_da_chamada(metodo, args)
        if posicao and som:
            momento = round(float(posicao.group(1)) + som[0], 3)
            if 0 <= momento <= dur - 0.25:
                brutos.append((momento, som[1]))
    escolhidos = []
    for momento, nome in sorted(brutos):
        if escolhidos and momento - escolhidos[-1][0] < 0.3:
            if PRIORIDADE_SONS.index(nome) < PRIORIDADE_SONS.index(escolhidos[-1][1]):
                escolhidos[-1] = (momento, nome)
            continue
        escolhidos.append((momento, nome))
    if len(escolhidos) > maximo:
        # os mais importantes ficam, na ordem do tempo
        escolhidos = sorted(sorted(escolhidos, key=lambda e: (PRIORIDADE_SONS.index(e[1]), e[0]))[:maximo])
    return escolhidos


def sons_do_clipe(projeto, cena):
    """O arquivo com os sons do clipe de motion da cena, misturados no tempo de cada movimento (feito uma vez e
    guardado na pasta do clipe), ou None se o clipe não tem movimento com som."""
    from . import trilha

    pasta = _pasta(projeto, cena["n"])
    try:
        partes = json.loads((pasta / "partes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    dur = float((cena.get("midia") or {}).get("duracao") or (float(cena["fim"]) - float(cena["ini"])))
    eventos = eventos_de_som(partes.get("js") or "", dur)
    if not eventos:
        return None
    assinatura = hashlib.sha1(json.dumps([VERSAO_SONS, trilha.VERSAO, eventos]).encode()).hexdigest()[:10]
    destino = pasta / f"sons-{assinatura}.wav"
    if destino.exists():
        return destino
    for velho in pasta.glob("sons-*.wav"):
        velho.unlink(missing_ok=True)
    entradas, grafo = [], []
    for k, (momento, nome) in enumerate(eventos):
        entradas += ["-i", str(trilha._efeito(nome))]
        atraso = round(momento * 1000)
        # 6 dB de folga: dois sons juntos somados não estouram (o render leva o pico a -1 dB depois)
        grafo.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={NIVEL_SONS[nome] - 6}dB,"
                     f"adelay={atraso}|{atraso}[s{k}]")
    grafo.append("".join(f"[s{k}]" for k in range(len(eventos)))
                 + f"amix=inputs={len(eventos)}:duration=longest:normalize=0[a]")
    temporario = destino.with_name(destino.stem + ".tmp.wav")
    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(grafo), "-map", "[a]",
           "-t", f"{dur + 1.0:.3f}", "-c:a", "pcm_s16le", str(temporario)])
    temporario.replace(destino)
    return destino


def sons_na_linha(projeto, cenas, log=print) -> list:
    """(segundo da narração, arquivo, volume em dB) dos sons de cada clipe de motion, para o render (_trilha).
    motion_ia.sons: false desliga; motion_ia.volume_sons_db acerta o volume (o pico do clipe vai a -1 dB antes)."""
    cfg = config(projeto)
    if not cfg.get("sons", True):
        return []
    volume = float(cfg.get("volume_sons_db", -20))
    saida = []
    for c in cenas:
        if not e_motion(c):
            continue
        try:
            arquivo = sons_do_clipe(projeto, c)
        except Exception as erro:  # noqa: BLE001 - um clipe sem som não derruba o render
            log(f"  motion IA: cena {c['n']} ficou sem som ({str(erro)[:100]})")
            continue
        if arquivo is not None:
            saida.append((round(float(c["ini"]), 3), arquivo, volume))
    if saida:
        log(f"  motion IA: som no tempo do movimento em {len(saida)} clipe(s)")
    return saida
