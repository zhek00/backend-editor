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

from . import animacoes, motion_estilo, motion_modelos
from .util import rodar

FONTE = "motion_ia"
TIPOS_SEM_MOTION = ("personagem",)
_TRAVA_PEDIDOS = threading.Lock()
_PEDIDOS = deque()  # horários dos últimos pedidos aos modelos, para o limite por minuto
_TRAVA_CENAS = threading.Lock()


def config(projeto) -> dict:
    """motion_ia do config.yaml, com JEV_MOTION_FALLBACK_ENABLED e JEV_MIN_SCORE_THRESHOLD (0 a 10) do .env por cima."""
    cfg = {**(projeto.config.get("motion_ia") or {}), **((getattr(projeto, "perfil", None) or {}).get("motion_ia") or {})}  # o perfil manda
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


def pausado(projeto) -> bool:
    """Motion IA fora da produção (motion_ia.pausado no config.yaml, pedido do usuário em 2026-10-09: "vamos tirar da
    produção o motion ai até ajustar ele"). Vale por cima do perfil: os perfis motion-ai e motion-vox ligam o motion
    no perfil, e a pausa é da fábrica inteira. No lugar dele entra o animation-ai (animation_ai.py)."""
    return bool((projeto.config.get("motion_ia") or {}).get("pausado"))


def ligado(projeto) -> bool:
    return not pausado(projeto) and bool(config(projeto).get("ativo", True)) and not projeto.offline


def tudo_pedido(projeto) -> bool:
    """O perfil pede o vídeo todo em motion (motion-ai, motion-vox), esteja o motion pausado ou não."""
    return bool(config(projeto).get("ativo", True)) and bool(config(projeto).get("tudo")) and not projeto.offline


def tudo_em_motion(projeto) -> bool:
    """Perfil de vídeo todo em motion (`motion_ia.tudo: true` no perfil): toda cena vira clipe, sem o Jev decidir."""
    return ligado(projeto) and bool(config(projeto).get("tudo"))


def todas_as_cenas(projeto, log=print) -> list:
    """Perfil de vídeo todo em motion: antes de buscar fotos, toda cena com fala vira clipe de motion. A que falhar
    (sem Node, modelo fora do ar, reprovada) segue o caminho de sempre: foto de banco e, por último, imagem de IA."""
    if not tudo_em_motion(projeto):
        return []
    if not modelos(projeto):
        log("  motion IA: nenhum modelo gratuito configurado, o vídeo segue com fotos")
        return []
    if not animacoes.node_pronto():
        log("  motion IA: falta o Node.js 22 ou mais, o vídeo segue com fotos")
        return []
    cands = candidatas(projeto, [c for c in projeto.ler_json("cenas.json")["cenas"] if not (c.get("midia") or {}).get("arquivo")])
    if not cands:
        return []
    log(f"  motion IA: vídeo todo em motion, {len(cands)} cena(s) viram clipe, de graça")
    if livre(projeto):
        try:  # a orquestradora lê o roteiro inteiro e diz o que o motion precisa mostrar em cada trecho, de uma vez
            orquestrar(projeto, log=log)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - sem briefing, cada clipe o pede sozinho
            log(f"  motion IA: a orquestradora falhou ({str(e)[:120]}); cada trecho pede o próprio briefing")
    return fazer(projeto, cands, log)


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


def estilo(projeto) -> str:
    """O estilo visual dos clipes: "colagem" (papel, recortes, stop-motion; motion_estilo.py) ou o editorial de sempre."""
    nome = str(config(projeto).get("estilo") or "").strip().lower()
    return motion_estilo.NOME if nome in (motion_estilo.NOME, "vox") else ""


def linha_do_estilo(projeto) -> str:
    """O que o modelo precisa saber do estilo do projeto (no estilo editorial de sempre, nada)."""
    if estilo(projeto) != motion_estilo.NOME:
        return ""
    return ("\n\nESTILO DOS CLIPES DESTE PROJETO: colagem de jornal envelhecido, no jeito do Vox (folhas, notas, carimbo "
            "vermelho, barbante, foto em meio-tom). Com a foto da cena e sem número na fala, prefira foto_recortada; "
            "afirmação que merece destaque é documento; relação ou ciclo entre coisas é barbante. foto_dado só quando a "
            "fala traz número.")


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
    if tudo_em_motion(projeto):  # perfil todo em motion: o Jev não decide, toda cena vira clipe
        return {c["n"]: not c.get("personagem") for c in cenas}
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
    (r"<script\b|</section\b|<body\b|<html\b|<head\b", "tag de documento dentro do html (só o conteúdo da cena)"),
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


def montar_html(partes, dur, largura=1920, altura=1080, foto=None, estilo=None) -> str:
    """O esqueleto da fábrica com o que o modelo escreveu dentro: fundo creme com pontos, as peças prontas, a
    flutuação dos cards, o traço das linhas e a faixa da legenda."""
    dur = round(dur, 3)
    html = f"""<!doctype html>
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
    return motion_estilo.aplicar(html) if estilo == motion_estilo.NOME else html



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
   balança); comprimento ou altura de animal com foto é medida_colagem (o bicho com a fita métrica); sem foto, peso
   de coisa pesada é balanca e de coisa leve ou pequena é tipografia (nunca um peso de ferro para um bicho de meio
   quilo); tamanho é regua, quantidade de gente é contador,
   queda ou extinção é tendencia, causa e consequência é fluxo, posição é ranking. Sem número: afirmação para carimbar é documento, relação ou ciclo entre coisas é barbante, enumeração ou
   argumento em pontos é topicos, dois lados opostos é contraste, fato num ano ou época é marco. frase só quando a
   fala não tem número, comparação, causa, pontos, lados nem época.
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
        "marco": {"type": "string"}, "carimbo": {"type": "string"}, "etiqueta": {"type": "string"},
        "linhas": {"type": "array", "items": {"type": "string"}},
        "parte": {"type": "string"}, "funcao": {"type": "string"}, "palavra_valor": {"type": "string"},
        "palavra_parte": {"type": "string"}, "palavra_funcao": {"type": "string"}, "rotulo_valor": {"type": "string"},
        "valor2": {"type": "number"}, "unidade2": {"type": "string"}, "prefixo2": {"type": "string"},
        "palavra_valor2": {"type": "string"},
        "tom": {"type": "string", "enum": list(motion_modelos.TONS)},
        "etapas": {"type": "array", "items": {"type": "string"}},
        "itens": {"type": "array", "items": {"type": "object", "properties": {
            "rotulo": {"type": "string"}, "valor": {"type": "number"}, "unidade": {"type": "string"},
            "prefixo": {"type": "string"}, "palavra": {"type": "string"}, "texto": {"type": "string"}}}},
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
VERSAO_DIRECAO = 3  # suba quando mudar as instruções: a direção guardada na pasta da cena é pedida de novo

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
cem quilos). É o mais intuitivo, e é o próprio animal, não um objeto no lugar dele. Do mesmo jeito, o comprimento
ou a altura dele vira medida_colagem: o bicho recortado com uma fita métrica até o valor, e a parte do corpo que a
fala cita ("contando a cauda achatada que funciona como leme") em destaque, com a função anotada.
Fala SEM número (origem, história, argumento, comparação de ideias, conclusão): não use a tipografia nem a
balança. Enumeração ou argumento em pontos é topicos; dois lados opostos é contraste; um fato num ano ou época é
marco; causa e consequência é fluxo; uma afirmação que merece destaque é documento (carimbo vermelho); relação ou
ciclo entre coisas é barbante. frase é o último recurso, para uma única ideia que não cabe em nenhum desses, e
nunca coloque topicos, contraste, marco ou fluxo em desenhos_proibidos: desenho de narração nunca estraga uma cena.
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


SEMPRE_PERMITIDOS = ("topicos", "contraste", "marco", "fluxo", "documento", "barbante")


def _limpar_direcao(resposta, cena, foto=False) -> dict:
    """A resposta do diretor conferida: desenho e proibidos só do catálogo, e a regra do código por cima."""
    base = direcao_pelo_codigo(cena, foto)
    modelos_validos = set(motion_modelos.MODELOS) - (set() if foto else set(motion_modelos.COM_FOTO))
    proibidos = [p for p in (resposta.get("desenhos_proibidos") or []) if p in motion_modelos.MODELOS]
    proibidos = [p for p in proibidos if p not in SEMPRE_PERMITIDOS]  # os desenhos de narração nunca estragam a cena
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


def _pedido_modelo(cena, dur, vizinhas, erros, foto, usados, direcao=None, figura=False):
    texto = (cena.get("texto") or "").strip()
    linhas = [f"Fala desta cena: \"{texto}\"", f"Duração: {dur:.2f} s"]
    if vizinhas[0]:
        linhas.append(f"Fala anterior (contexto): \"{vizinhas[0]}\"")
    if vizinhas[1]:
        linhas.append(f"Fala seguinte (contexto): \"{vizinhas[1]}\"")
    dado = dado_na_fala(texto)
    if dado:
        linhas.append(f"Dado que o código achou na fala: {dado}")
        indicado = motion_modelos.indicado(dado, texto, foto or figura)
        if indicado and not (direcao or {}).get("desenho"):
            linhas.append(f"Modelo indicado para esse dado: {indicado}")
    if direcao:
        linhas.append(texto_da_direcao(direcao))
    if (cena.get("mostrar") or "").strip():
        linhas.append(f"O que o agente de roteiro pediu para a imagem da cena (só contexto): {cena['mostrar'].strip()}")
    if foto:
        linhas.append("A cena TEM FOTO (foto_dado pode ser usado).")
    if foto or figura:
        citado = (cena.get("animal") or cena.get("exato") or cena.get("sujeito") or "").strip()
        linhas.append(f"Dá para recortar o sujeito ({citado}) de uma foto: colagem_balanca (peso) e medida_colagem "
                      "(comprimento, altura) podem ser usados.")
    else:
        linhas.append("Não há foto do sujeito: não use foto_dado, colagem_balanca nem medida_colagem.")
    if usados:
        linhas.append("Modelos das cenas de motion vizinhas: " + ", ".join(usados) + ". Evite repetir.")
    if (direcao or {}).get("usados_no_video"):
        linhas.append("Já usados no vídeo: " + direcao["usados_no_video"] + ". Os que chegaram ao limite estão nos "
                      "proibidos: a mesma demonstração repetida cansa quem assiste.")
    if erros:
        linhas.append("\nA resposta anterior foi REPROVADA por estes motivos. Corrija todos:\n- " + "\n- ".join(erros[:8]))
    return "\n".join(linhas)


def pode_ter_figura(cena) -> bool:
    """A cena cita um animal ou uma coisa exata: dá para buscar a foto própria dele nos bancos (motion_figura)."""
    return bool((cena.get("animal") or cena.get("exato") or "").strip())


def _normal(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto or "").lower()).encode("ascii", "ignore").decode()


def segundos_das_palavras(projeto, cena, palavras) -> dict:
    """{chave: o segundo, desde o começo da cena, em que a palavra é falada}, pelo alinhamento.json. As palavras são
    as que o modelo apontou ("dois", "cauda", "leme"); a que não aparece na fala da cena fica de fora."""
    try:
        faladas = projeto.ler_json("alinhamento.json").get("palavras") or []
    except (OSError, ValueError, AttributeError):
        return {}
    ini, fim = float(cena["ini"]), float(cena["fim"])
    trecho = [w for w in faladas if ini - 0.15 <= float(w.get("ini", -1)) < fim]
    saida = {}
    for chave, palavra in palavras.items():
        alvo = re.sub(r"[^a-z0-9]", "", _normal(palavra))[:5]
        if not alvo:
            continue
        achada = next((w for w in trecho if re.sub(r"[^a-z0-9]", "", _normal(w.get("texto")))[:5] == alvo), None)
        if achada is not None:
            saida[chave] = round(max(0.05, float(achada["ini"]) - ini), 2)
    return saida


def _dimensoes(arquivo):
    """(largura, altura) da figurinha e onde o bicho começa e termina na largura dela (de 0 a 1)."""
    from PIL import Image
    with Image.open(arquivo) as imagem:
        largura, altura = imagem.size
        alfa = imagem.convert("RGBA").getchannel("A").point(lambda v: 255 if v > 128 else 0)
        caixa = alfa.getbbox() or (0, 0, largura, altura)
    return (largura, altura), (round(caixa[0] / largura, 3), round(caixa[2] / largura, 3))


def _completar_pela_fala(dados, texto) -> None:
    """O que o modelo esqueceu e a fala diz: o quantificador logo antes do número ("apenas cerca de duzentos micos":
    "cerca de") vira o prefixo, e a palavra do número vira a palavra_valor (o tempo em que ele entra). Na cena 21 do
    11-animais-do-brasil o clipe saiu sem o "cerca de" e com o número em tempo chutado."""
    if dados.get("valor"):
        dados["valor"], palavra, prefixo = _ajustar_pela_fala(
            dados["valor"], dados.get("palavra_valor") or dados.get("rotulo_valor") or "", dados.get("prefixo"), texto)
        dados["prefixo"] = prefixo or dados.get("prefixo") or ""
        if palavra and not dados.get("palavra_valor"):
            dados["palavra_valor"] = palavra
    for item in dados.get("itens") or []:
        if isinstance(item, dict) and item.get("valor"):
            item["valor"], palavra, prefixo = _ajustar_pela_fala(item["valor"], item.get("palavra") or "",
                                                                 item.get("prefixo"), texto)
            item["prefixo"] = prefixo or item.get("prefixo") or ""
            item["palavra"] = item.get("palavra") or palavra


# "pode passar de dois metros": passar de é mais de
_ANTES_DO_NUMERO = {"passar de": "mais de", "passa de": "mais de", "passar dos": "mais de", "chegar a": "até"}


def _ajustar_pela_fala(valor, palavra, prefixo, texto):
    """(valor, palavra do número, prefixo) conferidos na fala: "dois metros e meio" é 2,5 (no pirarucu da cena 257 o
    modelo escreveu 2), e o quantificador logo antes do número vira o prefixo, se o modelo não deu um."""
    palavra = (palavra or "").split()
    numero = re.escape(palavra[0]) if palavra else _NUMEROS
    achado = re.search(rf"\b((?:mais|menos)\s+de|cerca\s+de|quase|apenas|s[óo]|at[ée]|pouco\s+mais\s+de|"
                       rf"aproximadamente|perto\s+de|passar?\s+d[eo]s?|chegar\s+a)\s+({numero})\b", texto or "", re.I)
    solto = achado or re.search(rf"\b({numero})\b", texto or "", re.I)
    if not solto:
        return valor, "", ""
    palavra_achada = solto.group(2) if achado else solto.group(1)
    novo_prefixo = ""
    if achado and not prefixo:
        dito = " ".join(achado.group(1).split()).lower()
        novo_prefixo = _ANTES_DO_NUMERO.get(dito, dito)
    if abs(valor - round(valor)) < 1e-9 and re.search(rf"\b{re.escape(palavra_achada)}\s+\w+\s+e\s+mei[oa]\b",
                                                      texto or "", re.I):
        valor += 0.5
    return valor, palavra_achada, novo_prefixo


# Pedido do usuário em 2026-10-08: "mudar a balança, que já apareceu umas 10x". No 11-animais-do-brasil eram 3
# balanças e 4 tipografias em 16 clipes, porque o pedido só citava as 4 cenas vizinhas. Agora cada desenho entra no
# máximo motion_ia.repetir_no_maximo vezes (2) no vídeo inteiro; os parecidos contam juntos (FAMILIAS).
FAMILIAS = {"colagem_balanca": "balanca", "foto_dado": "foto_dado", "tipografia": "tipografia"}


def usados_no_video(projeto, exceto=()) -> dict:
    """{desenho: quantas vezes} nos clipes de motion do vídeo, pela família (balança e bicho na balança juntos)."""
    from collections import Counter
    contagem = Counter()
    for c in projeto.ler_json("cenas.json")["cenas"]:
        if not e_motion(c) or c["n"] in exceto or (c.get("motion_trecho") and c["n"] != c["motion_trecho"][0]):
            continue
        modelo = modelo_da_cena(projeto, c["n"])
        if modelo and modelo != "livre":
            contagem[FAMILIAS.get(modelo, modelo)] += 1
    return dict(contagem)


def com_esgotados(direcao, projeto, exceto=()) -> dict:
    """A direção de arte com os desenhos que já chegaram ao limite no vídeo entre os proibidos."""
    limite = int(config(projeto).get("repetir_no_maximo", 2))
    try:
        usados = usados_no_video(projeto, exceto)
    except (OSError, ValueError, KeyError):
        return direcao
    familias = {f for f, k in usados.items() if k >= limite}
    esgotados = [m for m in motion_modelos.MODELOS if FAMILIAS.get(m, m) in familias]
    if not esgotados and not usados:
        return direcao
    saida = {**direcao, "esgotados": esgotados,
             "usados_no_video": ", ".join(f"{f} {k}x" for f, k in sorted(usados.items(), key=lambda x: -x[1])),
             "desenhos_proibidos": list(dict.fromkeys((direcao.get("desenhos_proibidos") or []) + esgotados))}
    if saida.get("desenho") in esgotados:
        saida["desenho"] = ""
    return saida


# o desenho simples de cada desenho com o bicho recortado, para quando não há foto que sirva
SIMPLES = {"medida_colagem": "regua", "contagem_colagem": "contador", "colagem_balanca": "balanca",
           "ficha_colagem": "tipografia"}


def _pelo_modelo_pronto(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, erros_iniciais=(),
                        direcao=None):
    """O modelo de linguagem escolhe a demonstração (motion_modelos) e preenche os dados; a fábrica desenha.
    Devolve as partes aprovadas, com o modelo e os dados, ou levanta RuntimeError.
    erros_iniciais: o que a crítica visual apontou no clipe anterior (vai no primeiro pedido).
    direcao: a direção de arte (dirigir): o desenho indicado, os proibidos e o tom."""
    from . import motion_figura
    texto = cena.get("texto") or ""
    fala = " ".join([vizinhas[0], texto, vizinhas[1]])
    figura_possivel = pode_ter_figura(cena)
    com_figura = bool(nome_foto) or figura_possivel
    direcao = direcao or direcao_pelo_codigo(cena, com_figura)
    sugerido = direcao.get("desenho") or motion_modelos.indicado(dado_na_fala(texto), texto, com_figura)
    if sugerido in (direcao.get("desenhos_proibidos") or []):
        sugerido = ""  # o desenho que a unidade indicaria já se esgotou no vídeo
    erros = list(erros_iniciais)
    for tentativa in range(int(config(projeto).get("tentativas_modelo", 3))):
        resposta = _perguntar(projeto, "motion IA: modelo", INSTRUCOES_MODELO,
                              _pedido_modelo(cena, dur, vizinhas, erros, bool(nome_foto), usados, direcao,
                                             figura=figura_possivel) + linha_do_estilo(projeto),
                              ESQUEMA_MODELO, log, temperatura=0.4 if tentativa else 0.2)
        modelo = str(resposta.get("modelo") or "").strip()
        dados, erros = motion_modelos.conferir(modelo, resposta, fala, tem_foto=bool(nome_foto), fala_da_cena=texto,
                                               sugerido=sugerido, proibidos=direcao.get("desenhos_proibidos") or (),
                                               figura=figura_possivel)
        if erros:
            continue
        _completar_pela_fala(dados, texto)
        if modelo in ("tipografia", "colagem_balanca", "medida_colagem") and direcao.get("tom") in motion_modelos.TONS:
            dados["tom"] = direcao["tom"]  # o movimento é decisão da direção de arte
        figura, credito = None, None
        if modelo in ("colagem_balanca", "medida_colagem", "contagem_colagem", "ficha_colagem"):
            # a foto própria do sujeito, buscada nos bancos para o desenho; sem ela, o recorte da foto da cena
            propria = motion_figura.figura(projeto, pasta, cena, parte=dados.get("parte") or "", log=log) \
                if figura_possivel else None
            moldura = False
            if propria:
                figura, credito = propria["arquivo"], propria.get("credito")
                moldura = bool(propria.get("moldura"))  # sem recorte limpo: a foto inteira, numa moldura
                if modelo == "medida_colagem":
                    dados["parte_caixa"] = propria.get("parte")
            elif nome_foto:
                figura = _recorte_da_cena(projeto, pasta, nome_foto, cena, log)
                if figura is None:
                    figura, moldura = nome_foto, True
                if modelo == "medida_colagem":
                    dados["parte_caixa"] = motion_figura.parte_padrao(dados.get("parte"))
            if figura is None or (moldura and modelo == "medida_colagem"):
                # a medida precisa do bicho recortado: sem ele, vale o desenho simples, mesmo que a direção de arte
                # o tenha proibido (cena 21 do 11-animais-do-brasil: contagem sem recorte e contador proibido, e
                # sobrou só o HTML livre)
                simples = SIMPLES[modelo]
                if simples in (direcao.get("esgotados") or []):
                    simples = ""  # o simples também já se esgotou no vídeo: o modelo escolhe outro desenho
                direcao = {**direcao, "desenho": simples,
                           "desenhos_proibidos": [d for d in direcao.get("desenhos_proibidos") or [] if d != simples]
                           + [modelo]}
                sugerido = simples
                erros = [f"não há foto do sujeito para o {modelo}: " + (f"use o modelo {simples}" if simples else
                                                                          "escolha outro desenho que a fala permita")]
                continue
            dados["moldura"] = moldura
            if modelo == "ficha_colagem":
                # o formato da própria foto, também na moldura: o pirarucu comprido da Wikimedia, espremido em 4:3,
                # saía cortado ao meio
                dados["fig"] = _dimensoes(pasta / "assets" / figura)[0]
                dados["tempos"] = segundos_das_palavras(projeto, cena, {
                    f"item{k}": item.get("palavra") or "" for k, item in enumerate(dados["itens"])})
            if modelo == "contagem_colagem":
                dados["fig"] = _dimensoes(pasta / "assets" / figura)[0]
                dados["tempos"] = segundos_das_palavras(projeto, cena, {"valor": dados.get("palavra_valor") or ""})
            if modelo == "medida_colagem":
                dados["fig"], dados["ext"] = _dimensoes(pasta / "assets" / figura)
                dados["tempos"] = segundos_das_palavras(projeto, cena, {
                    "valor": dados.get("palavra_valor") or "", "parte": dados.get("palavra_parte") or "",
                    "funcao": dados.get("palavra_funcao") or "", "valor2": dados.get("palavra_valor2") or ""})
        partes = motion_modelos.partes(modelo, dados, dur, figura)
        (pasta / "index.html").write_text(montar_html(partes, dur, foto=nome_foto if modelo in ("foto_dado", "foto_recortada") else None, estilo=estilo(projeto)),
                                          encoding="utf-8")
        erros = [e for e in animacoes._erros_para_o_modelo(animacoes._conferir(projeto, pasta, clipe=True))]
        if not erros:
            return {**partes, "modelo": modelo, "dados": dados, "versao_modelos": motion_modelos.VERSAO,
                    "foto": nome_foto if modelo == "foto_dado" else "", "direcao": direcao, "credito": credito}
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
                  "contidas, uma cor de destaque. Bicho recortado com borda serrilhada, pontas espetadas (folhas, "
                  "gravetos), pedaços do fundo grudados ou partes do corpo cortadas fica estranho: nota baixa",
}

INSTRUCOES_CRITICA = """Você é o diretor de arte que aprova os clipes de motion graphics de um canal de documentários
antes de eles serem gravados. Recebe a folha de contato de UM clipe (alguns quadros em ordem, com o segundo de cada um
no alto) e a fala da cena. O clipe entra no vídeo no lugar de uma foto, enquanto o narrador diz a fala.

O que é de propósito e NÃO é problema: o fundo creme com grade de pontos, a faixa que escurece a parte de baixo (é onde
a legenda vai entrar, por isso nada importante fica ali), os cards brancos de cantos arredondados, a palavra de
destaque em serifa itálica colorida, o primeiro quadro ainda incompleto (as coisas estão entrando), e o número
que ainda está contando (subindo do zero) nos quadros do meio: o número que vale é o do ÚLTIMO quadro.

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
    # o último quadro é o fim do clipe, já parado: com o quadro a 75%, a revisão gratuita via o número ainda
    # contando ("48 quilos" no lugar de 100, cena 257 do 11-animais-do-brasil) e reprovava a fidelidade
    momentos = sorted({round(min(0.6, dur * 0.2), 2), round(dur * 0.45, 2), round(max(dur * 0.5, dur - 0.12), 2)})
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
    if (critica is not None and aprovado.get("modelo") not in (None, "livre")
            and critica["menor"] < float(critica_config(projeto)["aceitavel"])):
        # segunda opinião antes de jogar fora um desenho pronto: a revisão gratuita reprovou o pirarucu da cena 257
        # por "foto e texto cortados" que não existiam. Fica a melhor das duas
        try:
            outra = _ler_critica(openrouter_local.VISAO.perguntar(
                projeto, "motion IA: revisão visual (segunda opinião)", INSTRUCOES_CRITICA,
                _pedido_critica(cena, dur, aprovado, vizinhas, direcao), ESQUEMA_CRITICA, log=log, imagens=[folha],
                temperatura=0.5, so_gratuitos=True))
        except (RuntimeError, SystemExit):
            outra = None
        if outra is not None and _chave(outra) > _chave(critica):
            log(f"  motion IA: cena {cena['n']}, a segunda opinião deu mais: {_resumo(outra)}")
            critica = outra
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
        (pasta / "index.html").write_text(montar_html(partes, dur, foto=nome_foto, estilo=estilo(projeto)), encoding="utf-8")
        brutos = animacoes._conferir(projeto, pasta, clipe=True)
        erros = animacoes._erros_para_o_modelo(brutos)
        if any(e.startswith(animacoes._ESTOURO_NO_CLIPE) for e in brutos):
            erros.insert(0, "há texto fora da tela ou fora do card: um elemento com position: absolute DENTRO de um "
                            ".m-card conta left e top a partir da borda do card, não da tela. Dentro do card, use "
                            "left e top pequenos (ou nenhum, em fluxo normal) e confira que tudo cabe no card")
        if not erros:
            return {**partes, "modelo": "livre", "foto": nome_foto or "", "direcao": direcao or {}}
    raise RuntimeError("reprovado na conferência: " + "; ".join(erros)[:300])


# ------------------------------------------------------------- a IA orquestradora (pedido de 2026-10-08)

# Pedido do usuário em 2026-10-08: "deve ter um auxílio da IA orquestradora, que ela basicamente vai dizer o que
# realmente o motion precisa mostrar na cena, para auxiliar corretamente o roteiro". Quem desenha cada clipe só via a
# fala da cena e as vizinhas: não sabia qual o papel daquela frase no argumento, nem o que as outras cenas já mostraram.
# A orquestradora é o agente de roteiro (roteirista._modelo_agente): lê o roteiro inteiro e o mapa, e para cada trecho
# (uma frase falada) diz O QUE o motion precisa mostrar. O gerador livre decide COMO desenhar e a revisão visual confere
# o clipe contra esse briefing.
VERSAO_ORQUESTRA = 1  # suba quando mudar as instruções: os briefings guardados são pedidos de novo

INSTRUCOES_ORQUESTRA = """Você é o diretor-orquestrador de um vídeo explicativo feito só de motion graphics (sem fotos
nem filmagens). Você leu o roteiro inteiro. Para cada TRECHO (uma frase falada) abaixo, decida o que o motion
PRECISA mostrar para o roteiro ser entendido e sentido naquele ponto. Quem desenha o clipe segue o seu briefing: você
diz O QUE, ele decide COMO desenhar.

Regras:
1. Serve ao argumento. Diga primeiro a função do trecho no roteiro (abre o assunto, prova, contrasta, vira a história,
   dá a consequência, fecha), depois o que o espectador precisa ver para essa função se cumprir. Motion não decora:
   mostra a ideia.
2. Concreto. Escreva o que aparece, o que se move e como as partes se relacionam (uma pilha maior que a outra, um
   líquido que sobe, um caminho que se bifurca, um relógio que acelera). Nada de "um visual bonito" ou "algo dinâmico".
3. Fiel. Nada que contradiga a fala ou o roteiro, nenhum fato ou número que o roteiro não diga. Metáfora é bem-vinda
   quando explica; se pode ser lida como fato falso, evite e diga em "evitar".
4. Continuidade e variedade. A lista "JÁ DECIDIDO" mostra o que os trechos anteriores mostram. Não repita a mesma
   metáfora nem a mesma estrutura em trechos próximos; quando o roteiro RETOMA um tema (o contraste do começo volta
   no fim), retome o mesmo motivo visual para dar unidade.
5. Momentos. Diga em que palavra da fala cada coisa importante acontece ("na palavra 1875 o ano aparece").
6. Texto na tela: no máximo 8 palavras, todas da fala (um número, um nome, a palavra-chave). Vazio se o desenho basta.
7. Intensidade: "rica" quando o trecho carrega a ideia central ou um dado; "simples" quando é só transição curta, e
   então o briefing é uma imagem única e limpa.
Responda em português, com um item para CADA trecho, pelo número n."""

ESQUEMA_ORQUESTRA = {
    "type": "object",
    "properties": {"trechos": {"type": "array", "items": {"type": "object", "properties": {
        "n": {"type": "integer"}, "funcao": {"type": "string"}, "o_que_mostrar": {"type": "string"},
        "elementos": {"type": "array", "items": {"type": "string"}},
        "momentos": {"type": "array", "items": {"type": "object", "properties": {
            "palavra": {"type": "string"}, "acontece": {"type": "string"}}}},
        "evitar": {"type": "array", "items": {"type": "string"}}, "texto_na_tela": {"type": "string"},
        "intensidade": {"type": "string"}},
        "required": ["n", "funcao", "o_que_mostrar"]}}},
    "required": ["trechos"],
}


def _arquivo_da_orquestra(projeto):
    return projeto.pasta / "motion_ia" / "orquestra.json"


def _marca_do_trecho(trecho) -> str:
    texto = " ".join((c.get("texto") or "").strip() for c in trecho)
    return hashlib.sha1(f"v{VERSAO_ORQUESTRA}|{texto}".encode("utf-8")).hexdigest()[:12]


def _briefings(projeto) -> dict:
    try:
        return json.loads(_arquivo_da_orquestra(projeto).read_text(encoding="utf-8")).get("trechos") or {}
    except (OSError, ValueError):
        return {}


def _guardar_briefings(projeto, novos) -> None:
    with _TRAVA_CENAS:
        guardados = _briefings(projeto)
        guardados.update(novos)
        arquivo = _arquivo_da_orquestra(projeto)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps({"versao": VERSAO_ORQUESTRA, "trechos": guardados}, ensure_ascii=False, indent=1),
                           encoding="utf-8")


def trechos_do_projeto(projeto) -> list:
    """Os trechos (frases) do vídeo, como o `fazer` os corta: cada um é a lista das cenas que um clipe cobre."""
    todas = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}
    trechos, cobertas = [], set()
    for n in sorted(todas):
        c = todas[n]
        if n in cobertas or c.get("personagem") or not (c.get("texto") or "").strip():
            continue
        trecho = frase_da_cena(projeto, c, todas)
        cobertas.update(x["n"] for x in trecho)
        trechos.append(trecho)
    return trechos


def briefing_do_trecho(projeto, trecho):
    """O briefing guardado do trecho (a mesma fala), ou None."""
    achado = _briefings(projeto).get(str(trecho[0]["n"]))
    return achado if achado and achado.get("marca") == _marca_do_trecho(trecho) else None


def _linha_do_briefing(b) -> str:
    return f"trecho {b['n']}: {b.get('o_que_mostrar', '')}"[:260]


def _limpar_briefing(item, trecho) -> dict:
    lista = lambda v: [" ".join(str(x).split())[:120] for x in (v or []) if str(x).strip()][:8]
    momentos = [{"palavra": " ".join(str(m.get("palavra") or "").split())[:30],
                 "acontece": " ".join(str(m.get("acontece") or "").split())[:140]}
                for m in item.get("momentos") or [] if isinstance(m, dict) and str(m.get("acontece") or "").strip()][:6]
    texto = " ".join(str(item.get("texto_na_tela") or "").split()[:8])
    return {"n": trecho[0]["n"], "marca": _marca_do_trecho(trecho),
            "funcao": " ".join(str(item.get("funcao") or "").split())[:160],
            "o_que_mostrar": " ".join(str(item.get("o_que_mostrar") or "").split())[:500],
            "elementos": lista(item.get("elementos")), "momentos": momentos, "evitar": lista(item.get("evitar")),
            "texto_na_tela": texto,
            "intensidade": "simples" if str(item.get("intensidade") or "").lower().startswith("s") else "rica"}


def orquestrar(projeto, trechos=None, log=print) -> dict:
    """A orquestradora (o agente de roteiro) lê o roteiro e o mapa e diz, trecho a trecho, o que o motion precisa
    mostrar. Guardado em motion_ia/orquestra.json; só pede de novo o trecho cuja fala mudou. Devolve {n: briefing}.
    Nunca para o vídeo: o trecho sem briefing segue só com a fala e as vizinhas."""
    from . import corrigir, roteirista
    trechos = trechos if trechos is not None else trechos_do_projeto(projeto)
    guardados = _briefings(projeto)
    faltam = [t for t in trechos if not (guardados.get(str(t[0]["n"])) or {}).get("marca") == _marca_do_trecho(t)]
    if not faltam:
        return {int(k): v for k, v in guardados.items()}
    mapa = roteirista._mapa_para_o_modelo(projeto.ler_json("roteiro_mapa.json")) if projeto.existe("roteiro_mapa.json") else ""
    roteiro = projeto.roteiro()
    log(f"  motion IA: a orquestradora decide o que o motion mostra em {len(faltam)} trecho(s)")
    ja = [_linha_do_briefing(b) for k, b in sorted(guardados.items(), key=lambda x: int(x[0]))][-14:]
    por_bloco, lote = [], []
    for t in faltam:  # lotes de até 8 trechos do mesmo bloco
        if lote and (len(lote) >= 8 or lote[0][0].get("bloco") != t[0].get("bloco")):
            por_bloco.append(lote)
            lote = []
        lote.append(t)
    if lote:
        por_bloco.append(lote)
    agente = roteirista._modelo_agente(projeto)
    for lote in por_bloco:
        linhas = []
        for t in lote:
            fala = " ".join((c.get("texto") or "").strip() for c in t)
            bloco = corrigir._bloco_da_cena_no_mapa(projeto, t[0])
            dur = float(t[-1]["fim"]) - float(t[0]["ini"])
            linhas.append(f"[trecho {t[0]['n']}] ({dur:.1f} s, assunto: {bloco or 'geral'}) \"{fala}\"")
        pedido = (f"ROTEIRO INTEIRO (para entender o argumento):\n{roteiro}\n\n"
                  + (f"MAPA DO VÍDEO:\n{mapa}\n\n" if mapa else "")
                  + ("JÁ DECIDIDO NOS TRECHOS ANTERIORES (não repita, retome quando o roteiro retoma):\n"
                     + "\n".join(f"- {x}" for x in ja) + "\n\n" if ja else "")
                  + "TRECHOS PARA DECIDIR AGORA:\n" + "\n".join(linhas))
        try:
            resposta = agente.perguntar(projeto, "motion IA: orquestradora", INSTRUCOES_ORQUESTRA, pedido,
                                        ESQUEMA_ORQUESTRA, log=log, temperatura=0.4)
        except (RuntimeError, SystemExit) as e:
            log(f"  motion IA: a orquestradora não respondeu ({str(e)[:120]}); estes trechos seguem sem briefing")
            continue
        por_n = {int(i.get("n")): i for i in (resposta or {}).get("trechos") or [] if str(i.get("n", "")).lstrip("-").isdigit()}
        novos = {}
        for t in lote:
            item = por_n.get(t[0]["n"])
            if item and str(item.get("o_que_mostrar") or "").strip():
                b = _limpar_briefing(item, t)
                novos[str(t[0]["n"])] = b
                ja.append(_linha_do_briefing(b))
        if novos:
            _guardar_briefings(projeto, novos)
        log(f"  motion IA: orquestradora decidiu {len(novos)} de {len(lote)} trecho(s)")
    return {int(k): v for k, v in _briefings(projeto).items()}


def texto_do_briefing(b) -> str:
    """O briefing da orquestradora, no pedido de quem desenha e de quem revisa."""
    if not b:
        return ""
    linhas = ["BRIEFING DA ORQUESTRADORA (o que o motion PRECISA mostrar; você decide como desenhar):"]
    if b.get("funcao"):
        linhas.append(f"- papel do trecho no roteiro: {b['funcao']}")
    linhas.append(f"- o que mostrar: {b['o_que_mostrar']}")
    if b.get("elementos"):
        linhas.append("- elementos que têm de aparecer: " + "; ".join(b["elementos"]))
    for m in b.get("momentos") or []:
        linhas.append(f"- na palavra \"{m['palavra']}\": {m['acontece']}")
    if b.get("evitar"):
        linhas.append("- evitar: " + "; ".join(b["evitar"]))
    if b.get("texto_na_tela"):
        linhas.append(f"- texto na tela (da fala): {b['texto_na_tela']}")
    linhas.append("- intensidade: " + ("imagem única e limpa, sem excesso" if b.get("intensidade") == "simples"
                                        else "demonstração rica, com várias partes se movendo"))
    return "\n".join(linhas)


# ------------------------------------------------------------------ a demonstração livre (pedido de 2026-10-08)

# Pedido do usuário em 2026-10-08: "a demonstração que o motion deve fazer é livre, não templates prontos como está
# hoje". Os desenhos prontos (motion_modelos) saíam repetidos e só serviam para dado com número; o roteiro de economia
# da Serra Gaúcha tinha 96 cenas quase sem número, e cada cena virava `frase` ou um HTML reprovado. Com
# `motion_ia.demonstracao: livre` (no perfil), o modelo INVENTA a demonstração de cada cena: pensa a ideia visual que faz
# o espectador entender e sentir a fala e a desenha em SVG, CSS e GSAP, com objetos figurativos e metáforas. Sem direção
# de arte por catálogo, sem desenho pronto, sem teto de repetição. O código só confere o que protege o vídeo.

INSTRUCOES_LIVRE = """Você é diretor de motion graphics e ilustrador de um canal de documentários explicativos. Para UMA
cena, invente a DEMONSTRAÇÃO VISUAL que faz o espectador entender e sentir o que a narração diz naquele momento, e
escreva o código dela. Não existem modelos prontos: a ideia é sua. A fala não traz só números: traz origem, história,
causa, contraste, processo, espera, valor, tradição. Ache a imagem mental certa e anime-a.

COMO PENSAR (campo "ideia", escreva ANTES do código, em 2 ou 3 frases):
- o que a fala quer que a pessoa veja e sinta em 1 segundo;
- a demonstração: o que aparece, o que se move e em que palavra, e por que isso explica a fala melhor que um texto;
- varie: metáfora literal (uma garrafa que enche, um barril que envelhece), diagrama vivo (camadas de terreno, linha do
  tempo que cresce, setas que se cruzam), comparação de escala (uma pilha contra outra), mapa estilizado, objeto que se
  monta peça a peça, balança, relógio ou ampulheta, mãos de recorte, ilustração de papel com personagens simples.
  Nada de "card com frase": se a fala só pede uma ideia, desenhe a ideia, e use o texto como legenda do desenho.

O QUE VOCÊ PODE FAZER (liberdade total dentro do esqueleto):
- desenhar com SVG (path, circle, rect, polygon, gradientes, clip-path, máscaras, filtros simples), CSS e HTML;
  objetos figurativos e ilustrações são BEM-VINDOS (garrafa, barril, parreira, faca, montanha em camadas, moeda,
  engrenagem, balança, casa, pessoa de recorte). Faça formas com personalidade: cantos irregulares, sombras duras,
  detalhes (rótulo da garrafa, nível do líquido, veios da madeira), não só retângulos;
- animar qualquer coisa no tl (linha do tempo do GSAP 3): entrar, crescer, encher (height, scaleY, clip-path),
  desenhar traço (strokeDashoffset), girar, empilhar, cair, derramar, mover a "câmera" (x, y, scale de um grupo),
  paralaxe entre camadas, contar um número (objeto {v:0} com onUpdate dentro do tl), trocar de cena dentro do clipe
  (uma coisa sai, outra entra) quando a fala tem duas partes;
- sincronizar com a fala: o pedido traz o segundo de cada palavra (relativo ao começo do clipe). Faça cada coisa
  aparecer NA palavra que a cita ("1875" entra em 1,2 s porque o narrador o diz em 1,2 s).

O ESQUELETO (já pronto, não repita):
- tela 1920x1080; o fundo, a textura e os recortes de papel já existem: não pinte o fundo;
- o seu html entra dentro de <section id="cena"> (position: relative, tela inteira);
- existem o tl (gsap.timeline paused) e a constante DUR (duração em segundos);
- fontes: "Texto" (Inter, pesos 300 a 800) e "Titulo" (Playfair Display, serifa);
- cores em variáveis: --verde, --azul, --laranja, --grafite (use e combine; veja o ESTILO abaixo);
- peças opcionais: .m-card (papel/cartão, posicione com position: absolute; o conteúdo dentro fica em fluxo normal),
  .m-num, .m-rot, .m-sub, .m-frase (tipografia pronta), .m-destaque (palavra de ênfase), .m-linha (path SVG que se
  desenha com tl.to(".m-linha-1", {strokeDashoffset: 0, ...}) e já vem escondido), .m-foto (só se o pedido disser que a
  cena tem foto).

REGRAS QUE O CÓDIGO CONFERE (o resto é liberdade):
1. TODA animação no tl, com o segundo na posição: tl.fromTo("#m-x", {de}, {para, duration, ease}, segundo). Nada de
   @keyframes, animation ou transition no CSS; nada de setTimeout, setInterval, requestAnimationFrame, Date,
   Math.random, fetch, imagens ou endereços externos, emoji. O clipe tem que sair igual toda vez. Pode usar qualquer ease
   do GSAP (power2.out, back.out, elastic.out, steps(6) para stop-motion...). Tudo termina de entrar antes de DUR - 0.4 e
   fica parado até o fim (movimento leve contínuo é bem-vindo).
2. Texto: poucas palavras (no máximo 14 visíveis), TODAS tiradas da fala (números, nomes, palavra-chave). Nada de frase
   inventada. Nenhum texto com menos de 32 px (rótulos 36 px ou mais, o texto principal 64 px ou mais). Texto dentro de
   SVG com font-size em px ou no atributo font-size, também 32 ou mais.
3. Espaço: margem de 140 px nos lados e em cima; os 260 px de baixo ficam livres (legenda). Nada sai da tela, nenhum
   texto fica sobre outro texto, e o desenho ocupa boa parte da tela (nada de miniatura num canto).
4. Todo id e classe seus começa com "m-". Nada de position: fixed. Dentro de um .m-card não use position absolute.
5. O código tem no máximo 30.000 caracteres: faça desenhos ricos, mas enxutos (use <defs> e <use> para repetir).
6. Se o pedido disser que a cena tem foto, mostre-a em <div class="m-card m-foto"></div> (560x400 ou maior).

Devolva: ideia, css, html, js."""

ESTILOS_LIVRE = {
    "colagem": """ESTILO "COLAGEM DE PAPEL" (Vox): tudo parece recortado e colado numa mesa. Fundo de papel kraft amassado
com textura por cima (já pronto), recortes de papel rasgado ao fundo (já prontos). Desenhe com formas de papel: cantos
levemente irregulares (polygon, clip-path), sombra dura deslocada (box-shadow 6px 8px 0 rgba(17,17,17,.2) ou
filter: drop-shadow), borda branca de figurinha, fita adesiva (retângulo translúcido amarelo no canto), carimbos e riscos
de caneta. Paleta contida: preto #111, vermelho de tinta #B3261E, azul-marinho #14213D, amarelo #F2B705, creme
#F8F2E2. Movimento de stop-motion: prefira ease "steps(6)" ou "steps(8)" nas entradas, como papel jogado na mesa; pode
misturar com paralaxe lenta entre camadas. Sem degradês brilhantes, sem 3D liso, sem vetor corporativo de banco de
imagens.""",
    "": """ESTILO EDITORIAL LIMPO: fundo creme com grade de pontos (pronto), formas simples e bem acabadas, cores
--laranja, --azul e --verde, sombra suave, movimento com mola (back.out(1.7)) e linhas que se desenham.""",
}

ESQUEMA_LIVRE = {
    "type": "object",
    "properties": {"ideia": {"type": "string"}, "css": {"type": "string"}, "html": {"type": "string"},
                   "js": {"type": "string"}},
    "required": ["ideia", "css", "html", "js"],
}


def livre(projeto) -> bool:
    """O perfil pede a demonstração livre (o modelo inventa) no lugar dos desenhos prontos."""
    return str(config(projeto).get("demonstracao") or "").strip().lower() == "livre"


def instrucoes_livre(projeto) -> str:
    return INSTRUCOES_LIVRE + "\n\n" + ESTILOS_LIVRE.get(estilo(projeto), ESTILOS_LIVRE[""])


def palavras_da_cena(projeto, cena, limite=60) -> list:
    """[(palavra, segundo desde o começo do clipe)] das palavras faladas na cena, pelo alinhamento.json."""
    try:
        faladas = projeto.ler_json("alinhamento.json").get("palavras") or []
    except (OSError, ValueError, AttributeError):
        return []
    ini, fim = float(cena["ini"]), float(cena["fim"])
    return [(str(w.get("texto") or ""), round(max(0.0, float(w["ini"]) - ini), 2)) for w in faladas
            if ini - 0.15 <= float(w.get("ini", -1)) < fim][:limite]


def _pedido_livre(projeto, cena, dur, vizinhas, erros, foto=False, briefing=None):
    linhas = [f"Fala desta cena: \"{(cena.get('texto') or '').strip()}\"", f"Duração: {dur:.2f} s (DUR)",
              "Proporção: 16:9, 1920x1080"]
    palavras = palavras_da_cena(projeto, cena)
    if palavras:
        linhas.append("Segundo em que cada palavra é falada (desde o começo do clipe): "
                      + ", ".join(f"{t} {seg:.2f}" for t, seg in palavras))
    if vizinhas[0]:
        linhas.append(f"Fala anterior (só contexto): \"{vizinhas[0]}\"")
    if vizinhas[1]:
        linhas.append(f"Fala seguinte (só contexto): \"{vizinhas[1]}\"")
    try:
        from . import corrigir
        bloco = corrigir._bloco_da_cena_no_mapa(projeto, cena)
    except Exception:  # noqa: BLE001 - o assunto do bloco é só contexto
        bloco = ""
    if bloco:
        linhas.append(f"Assunto deste trecho do roteiro: {bloco}")
    if briefing:
        linhas.append(texto_do_briefing(briefing))
    elif (cena.get("mostrar") or "").strip():
        linhas.append(f"O diretor de arte do roteiro sugeriu (inspiração, não obrigação): {cena['mostrar'].strip()}")
    if foto:
        citado = (cena.get("exato") or cena.get("animal") or cena.get("sujeito") or "").strip()
        linhas.append(f"A cena TEM FOTO ({citado}): se ajudar a demonstração, mostre-a em <div class=\"m-card m-foto\"></div>.")
    if erros:
        linhas.append("\nA resposta anterior foi REPROVADA por estes motivos. Corrija todos, mantendo a ideia:\n- "
                      + "\n- ".join(erros[:8]))
    return "\n".join(linhas)


def problemas_do_codigo_livre(partes) -> list:
    """O que o código confere na demonstração livre: o que protege o vídeo, sem exigir mola nem componentes prontos."""
    erros = []
    tudo = "\n".join(str(partes.get(k) or "") for k in ("css", "html", "js"))
    for padrao, motivo in _PROIBIDOS:
        if "ease" in padrao:
            continue  # a curva é livre na demonstração livre
        if re.search(padrao, tudo, re.I):
            erros.append(f"tem {motivo}")
    if _EMOJI.search(tudo):
        erros.append("tem emoji")
    if "tl." not in str(partes.get("js") or ""):
        erros.append("o js não anima nada no tl")
    if not str(partes.get("html") or "").strip():
        erros.append("o html está vazio")
    if not str(partes.get("css") or "").strip():
        erros.append("o css está vazio: posicione cada elemento (position: absolute, left, top, width) e dê o tamanho "
                     "de cada texto (font-size em px)")
    pequenos = sorted({int(t) for t in re.findall(r"font-size\s*[:=]\s*[\"']?(\d+)(?:\.\d+)?(?:px)?", tudo)
                       if int(t) < 32})
    if pequenos:
        erros.append(f"tem texto pequeno demais ({', '.join(str(t) + 'px' for t in pequenos)}): nenhum texto abaixo "
                     "de 32px (rótulos 36px ou mais, texto principal 64px ou mais)")
    if len(tudo) > 30000:
        erros.append("o código passou de 30.000 caracteres: simplifique (use <defs> e <use> para repetir)")
    return erros


def _pela_demonstracao_livre(projeto, cena, dur, vizinhas, pasta, nome_foto, log, erros_iniciais=(), direcao=None):
    """O modelo inventa a demonstração (ideia, css, html, js); o código e o HyperFrames conferem; a revisão visual
    (_revisado) olha o resultado. Levanta RuntimeError se nenhuma tentativa passar."""
    erros = list(erros_iniciais)
    for tentativa in range(int(config(projeto).get("tentativas", 4))):
        resposta = _perguntar(projeto, "motion IA: demonstração livre", instrucoes_livre(projeto),
                              _pedido_livre(projeto, cena, dur, vizinhas, erros, foto=bool(nome_foto),
                                           briefing=(direcao or {}).get("briefing")),
                              ESQUEMA_LIVRE, log, temperatura=0.8 if tentativa else 0.6)
        partes = {k: str(resposta.get(k) or "") for k in ("css", "html", "js")}
        ideia = " ".join(str(resposta.get("ideia") or "").split())[:400]
        erros = problemas_do_codigo_livre(partes)
        if nome_foto and "m-foto" not in partes["html"]:
            pass  # a foto é opcional na demonstração livre
        inventadas = _palavras_inventadas(partes, " ".join([vizinhas[0], cena.get("texto") or "", vizinhas[1]]))
        if inventadas:
            erros.append("usa palavras que a fala não diz (" + ", ".join(inventadas) + "): só palavras da fala")
        if erros:
            continue
        (pasta / "index.html").write_text(montar_html(partes, dur, foto=nome_foto, estilo=estilo(projeto)),
                                          encoding="utf-8")
        brutos = animacoes._conferir(projeto, pasta, clipe=True)
        erros = animacoes._erros_para_o_modelo(brutos)
        if any(e.startswith(animacoes._ESTOURO_NO_CLIPE) for e in brutos):
            erros.insert(0, "há texto ou desenho fora da tela (ou fora do card que o contém): confira posições e "
                            "tamanhos, e que tudo cabe na área de 140 a 1780 px de largura e 140 a 820 px de altura")
        if not erros:
            log(f"  motion IA: cena {cena['n']}, ideia: {ideia[:140]}")
            return {**partes, "modelo": "livre", "ideia": ideia, "foto": nome_foto or "", "direcao": direcao or {}}
    raise RuntimeError("reprovado na conferência: " + "; ".join(erros)[:300])



def _direcao_do_briefing(projeto, trecho, log=print) -> dict:
    """Na demonstração livre a direção é o briefing da orquestradora (pedido agora, se ainda não houver). A revisão
    visual também lê: "leitura" é o que o clipe precisa mostrar, e "nao_mostrar" o que evitar."""
    b = briefing_do_trecho(projeto, trecho)
    if b is None:
        try:
            orquestrar(projeto, [trecho], log)
        except (Exception, SystemExit) as e:  # noqa: BLE001 - sem orquestradora o clipe sai só com a fala
            log(f"  motion IA: sem briefing da orquestradora ({str(e)[:100]})")
        b = briefing_do_trecho(projeto, trecho)
    if not b:
        return {}
    return {"leitura": b["o_que_mostrar"], "tom": "neutro", "desenhos_proibidos": [], "nao_mostrar": b.get("evitar") or [],
            "origem": "orquestradora", "briefing": b}


def _um_clipe(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, erros_visuais=(), direcao=None):
    """Um clipe aprovado pelo código e pelo HyperFrames, ainda sem a revisão visual: primeiro um modelo pronto de
    demonstração; se nenhum servir, o HTML livre. Com `motion_ia.demonstracao: livre`, só a demonstração livre."""
    if livre(projeto):
        return _pela_demonstracao_livre(projeto, cena, dur, vizinhas, pasta, nome_foto, log, erros_visuais, direcao)
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
        antes = (aprovado.get("modelo"), json.dumps(aprovado.get("dados"), sort_keys=True, ensure_ascii=False))
        try:
            aprovado = _um_clipe(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log,
                                 erros_da_critica(critica, float(cfg["nota"])), direcao)
        except (RuntimeError, SystemExit) as e:
            log(f"  motion IA: cena {cena['n']}, a correção não saiu ({str(e)[:120]}); fica o de melhor nota")
            break
        if aprovado.get("modelo") != "livre" and antes == (
                aprovado.get("modelo"), json.dumps(aprovado.get("dados"), sort_keys=True, ensure_ascii=False)):
            # o desenho pronto saiu igual: revisar de novo só repetiria a nota (cena 191 do 11-animais-do-brasil,
            # três revisões iguais, uns 4 minutos à toa). O que a revisão apontou é do desenho, não dos dados
            log(f"  motion IA: cena {cena['n']}, a correção saiu igual; fica o de melhor nota")
            break
    if melhor is None:
        return aprovado
    if melhor["critica"]["menor"] < float(cfg["aceitavel"]):
        raise RuntimeError(f"reprovado na revisão visual ({_resumo(melhor['critica'])}): "
                           + "; ".join(p["problema"] for p in melhor["critica"]["problemas"])[:240])
    melhor["criticas"] = historico
    return melhor


def frase_da_cena(projeto, cena, todas) -> list:
    """As cenas que o clipe cobre: da cena até o fim da frase, no mesmo bloco, até motion_ia.duracao_maxima (8 s).
    Pedido do usuário em 2026-10-08: "pode chegar a quase dois metros de comprimento, contando a | a cauda achatada
    que funciona como leme" é uma frase em duas cenas (191 e 192 do 11-animais-do-brasil); com só os 3 s da 191, a
    cauda ficava de fora do clipe. Cena com personagem, imagem ou prompt da pessoa encerra o trecho."""
    maximo = float(config(projeto).get("duracao_maxima", 8))
    trecho = [cena]
    while not re.search(r"[.!?…]['\"”)]*\s*$", (trecho[-1].get("texto") or "").strip()):
        seguinte = todas.get(trecho[-1]["n"] + 1)
        if (not seguinte or seguinte.get("personagem") or seguinte.get("imagem_da_pessoa") or seguinte.get("prompt_manual")
                or seguinte.get("bloco") != cena.get("bloco") or float(seguinte["fim"]) - float(cena["ini"]) > maximo):
            break
        trecho.append(seguinte)
    return trecho


def gerar_cena(projeto, cena, vizinhas, log=print, foto=None, usados=(), trecho=None):
    """Faz o clipe de uma cena, ou da frase inteira (trecho: as cenas que ele cobre, frase_da_cena). Devolve
    ([(n, mp4, capa, duração) de cada cena], o crédito da foto própria do sujeito, se houve) ou levanta RuntimeError.

    Primeiro um modelo pronto de demonstração (motion_modelos: velocímetro, balança, régua...), escolhido e preenchido
    pelo modelo de linguagem; se nenhum servir, o HTML livre do modelo, de reserva. Antes de gravar, a revisão visual
    olha os quadros e devolve o que tirou nota baixa (_revisado).
    foto: a imagem da própria cena, opcional (o modelo foto_dado). usados: os modelos das cenas de motion vizinhas."""
    if not animacoes.node_pronto():
        raise RuntimeError("falta o Node.js 22 ou mais (o HyperFrames grava o clipe)")
    trecho = trecho or [cena]
    if len(trecho) > 1:
        # a frase inteira: a fala junta e o tempo do começo da primeira cena ao fim da última
        cena = {**cena, "texto": " ".join((c.get("texto") or "").strip() for c in trecho), "fim": trecho[-1]["fim"]}
    dur = max(float(cena["fim"]) - float(cena["ini"]), 1.0)
    pasta = _pasta(projeto, cena["n"])
    pasta.mkdir(parents=True, exist_ok=True)
    animacoes._preparar_pasta(pasta)
    nome_foto = None
    if foto is not None:
        nome_foto = f"foto{Path(foto).suffix.lower()}"
        shutil.copy2(foto, pasta / "assets" / nome_foto)
    # demonstração livre: sem direção de arte por catálogo de desenhos (o modelo pensa a ideia dentro do pedido)
    direcao = _direcao_do_briefing(projeto, trecho, log) if livre(projeto) else com_esgotados(
        dirigir(projeto, cena, vizinhas, bool(nome_foto) or pode_ter_figura(cena), log), projeto,
        [c["n"] for c in trecho])
    aprovado = _revisado(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, direcao)
    aprovado["trecho"] = [c["n"] for c in trecho]
    # a revisão pode ter ficado com um clipe de uma rodada anterior: a página gravada é sempre a dele
    (pasta / "index.html").write_text(montar_html(aprovado, dur, foto=aprovado.get("foto") or None, estilo=estilo(projeto)), encoding="utf-8")
    (pasta / "partes.json").write_text(json.dumps(aprovado, ensure_ascii=False, indent=1), encoding="utf-8")
    destino = projeto.pasta / "midia" / f"{cena['n']:04d}_motion{'_frase' if len(trecho) > 1 else ''}.mp4"
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.stem + ".tmp.mp4")
    r = animacoes._hyperframes(projeto, ["render", "--output", str(temporario), "--format", "mp4", "--fps",
                                         str(fps(projeto)), "--workers", "1", "--quiet"],
                               pasta, 900)
    if r.returncode != 0 or not temporario.exists() or temporario.stat().st_size < 1000:
        temporario.unlink(missing_ok=True)
        raise RuntimeError(f"o HyperFrames não gravou o clipe: {(r.stderr or r.stdout or '')[-200:]}")
    temporario.replace(destino)
    # o HTML é só um passo: fica o partes.json, para refazer ou conferir depois
    (pasta / "index.html").unlink(missing_ok=True)
    shutil.rmtree(pasta / "quadros", ignore_errors=True)
    saida = []
    for c in trecho:
        inicio = float(c["ini"]) - float(cena["ini"])
        dur_c = max(float(c["fim"]) - float(c["ini"]), 0.5)
        if len(trecho) > 1:
            # um pedaço por cena, no tempo dela: o render monta cena a cena, e os pedaços tocam em sequência
            pedaco = projeto.pasta / "midia" / f"{c['n']:04d}_motion.mp4"
            rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-i", str(destino), "-t",
                   f"{dur_c + 0.05:.3f}", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "16",
                   "-pix_fmt", "yuv420p", str(pedaco)])
        else:
            pedaco = destino
        capa = pedaco.with_name(f"{c['n']:04d}_motion_capa.jpg")
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{min(dur_c * 0.6, dur_c - 0.1):.2f}", "-i", str(pedaco),
               "-frames:v", "1", "-q:v", "3", str(capa)])
        saida.append((c["n"], pedaco, capa, dur_c))
    return saida, aprovado.get("credito")


def _aplicar(projeto, n, destino, capa, dur, trecho=None, credito=None, duracao_frase=None) -> None:
    """O clipe entra como a mídia da cena, igual a um vídeo de banco. O que a cena tinha fica em motion_reserva.
    trecho: as cenas da frase que o clipe cobre (motion_trecho); credito: a foto própria do sujeito, que vai para os
    créditos do vídeo (motion_foto, lido por midia.escrever_creditos)."""
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
        for campo in ("sem_midia_real", "conferencia", "motion_ia_falhou", "motion_so", "motion_trecho", "motion_foto"):
            c.pop(campo, None)
        if trecho and len(trecho) > 1:
            c["motion_trecho"] = list(trecho)
            if n == trecho[0] and duracao_frase:
                c["midia"]["duracao_frase"] = round(duracao_frase, 3)  # os sons do clipe vão até o fim da frase
        if credito and n == (trecho or [n])[0]:
            c["motion_foto"] = credito
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
    # cada clipe cobre a frase inteira: a cena que já cai na frase de uma escolhida anterior não ganha clipe próprio
    trechos, cobertas = {}, set()
    for c in sorted(escolhidas, key=lambda x: x["n"]):
        if c["n"] in cobertas:
            continue
        trechos[c["n"]] = frase_da_cena(projeto, todas.get(c["n"], c), todas)
        cobertas.update(x["n"] for x in trechos[c["n"]])
    escolhidas = [c for c in escolhidas if c["n"] in trechos]

    def uma(c):
        trecho = trechos[c["n"]]
        antes, depois = todas.get(c["n"] - 1) or {}, todas.get(trecho[-1]["n"] + 1) or {}
        vizinhas = ((antes.get("texto") or "").strip()[-200:], (depois.get("texto") or "").strip()[:200])
        try:
            foto = foto_da_cena(projeto, c) if concreta(c) else None
            pedacos, credito = gerar_cena(projeto, c, vizinhas, log, foto=foto,
                                          usados=modelos_vizinhos(projeto, todas, c["n"]), trecho=trecho)
            total = sum(p[3] for p in pedacos)
            for n, destino, capa, dur in pedacos:
                _aplicar(projeto, n, destino, capa, dur, trecho=[x["n"] for x in trecho], credito=credito,
                         duracao_frase=total)
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
    midia = cena.get("midia") or {}
    # o clipe da frase inteira (motion_trecho): os sons vão até o fim dela, não só até o fim da primeira cena
    dur = float(midia.get("duracao_frase") or midia.get("duracao") or (float(cena["fim"]) - float(cena["ini"])))
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
        if c.get("motion_trecho") and c["n"] != c["motion_trecho"][0]:
            continue  # o pedaço de um clipe de frase: o som dele já entra com a primeira cena
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
