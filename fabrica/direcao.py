"""Cenas dirigidas: câmera, tipografia cinética, formas que se transformam, cartões em 3D e cenário, desenhados por
código e gravados quadro a quadro (pedido do usuário em 2026-10-12: sair do "slide de PowerPoint").

Não é um segundo sistema de gravação. É uma camada em cima do animation-ai: o mesmo HyperFrames (Chrome escondido,
quadro a quadro, FFmpeg), as mesmas conferências, o mesmo `_aplicar` que põe o clipe no lugar da foto, o mesmo
`regravar` e o mesmo som. O que muda é QUEM decide o desenho: no lugar de escolher um de 24 modelos prontos, o modelo
escreve uma especificação de direção (JSON, veja recursos/direcao/DIRETRIZES.md) e o motor (recursos/direcao/direcao.js)
a desenha. O modelo nunca escreve HTML: testado e descartado (CLAUDE.md, seção Animações).

Os cinco pontos do pedido:
1. Gravação invisível e quadro a quadro: HyperFrames, a 60 quadros por segundo (`animation_ai.direcao.fps`).
2. Direção cinematográfica: `planejar` (as diretrizes vão no pedido) e `conferir` (câmera que não para, textos curtos
   com palavras da fala, no máximo 3 textos, um cartão 3D, duas formas).
3. Determinismo: `quadro(t)` é função pura do tempo; o sorteio tem semente; `tests/test_direcao.py` grava duas vezes e
   compara os quadros.
4. Refinamento em linguagem natural: `refinar` ("deixa a transição mais suave", "faz o final emendar no começo").
5. Vários formatos: o mesmo desenho sai deitado (1920x1080) e em pé (1080x1920), recomposto pelo motor, não cortado.
"""
import copy
import hashlib
import json
import re
from pathlib import Path

from . import animacoes, animation_ai
from .util import rodar

VERSAO = 1  # suba quando mudar o desenho (direcao.js, direcao.css, PALETAS): os clipes são gravados de novo
RECURSOS = Path(__file__).parent / "recursos" / "direcao"
FORMATOS = {"horizontal": (1920, 1080), "vertical": (1080, 1920)}
PADRAO = {"fps": 60, "formatos": ["horizontal", "vertical"]}
PRIMEIRO = 0.8  # o primeiro elemento entra em até este segundo: a tela nunca fica só com o fundo

CORES_DA_PALETA = ("fundo", "fundo2", "txt", "txt2", "acc", "acc2", "mut")
_ESCURA = {"painel": "#161C28", "linha": "#2B3446", "vinheta": "rgba(0,0,0,.62)", "faixa": "rgba(0,0,0,.42)",
           "faixa-altura": "340px"}
PALETAS = {
    "misterio": {"fundo": "#0B0B10", "fundo2": "#17141C", "txt": "#F2EFEA", "txt2": "#CFC9BF", "acc": "#E23B3B",
                 "acc2": "#E8D5A3", "mut": "#8C877E", "painel": "#17171A", "linha": "#2E2E33"},
    "tensao": {"fundo": "#0A0F14", "fundo2": "#1A0E10", "txt": "#F4F1EC", "txt2": "#D2CCC4", "acc": "#FF4D2E",
               "acc2": "#FFB020", "mut": "#8D8880"},
    "urgencia": {"fundo": "#0D0D0F", "fundo2": "#1B1B22", "txt": "#FFFFFF", "txt2": "#D6D6DC", "acc": "#FFD60A",
                 "acc2": "#FF3B30", "mut": "#8E8E96"},
    "descoberta": {"fundo": "#0B1620", "fundo2": "#14304A", "txt": "#F3F8FB", "txt2": "#C9DAE6", "acc": "#5EEAD4",
                   "acc2": "#FDE68A", "mut": "#8AA2B3"},
    "calma": {"fundo": "#0C1B24", "fundo2": "#17394A", "txt": "#F1F8FA", "txt2": "#C4DCE4", "acc": "#7DD3FC",
              "acc2": "#A7F3D0", "mut": "#86A5B2"},
    "historia": {"fundo": "#17110B", "fundo2": "#2A1D12", "txt": "#F3E9D2", "txt2": "#D9CBAC", "acc": "#D9A441",
                 "acc2": "#E8D9B8", "mut": "#A39478"},
    "ciencia": {"fundo": "#0A1020", "fundo2": "#101F3F", "txt": "#F1F5FB", "txt2": "#C5D0E3", "acc": "#60A5FA",
                "acc2": "#34D399", "mut": "#8794AB"},
    "noite": {"fundo": "#0E1420", "fundo2": "#172236", "txt": "#F1F4F8", "txt2": "#C5CEDB", "acc": "#F5B83D",
              "acc2": "#4FD1C5", "mut": "#8794A8"},
}
for _p in PALETAS.values():
    for _k, _v in _ESCURA.items():
        _p.setdefault(_k, _v)

TIPOS = ("texto", "forma", "numero", "card3d", "linha")
ENTRADAS = ("sobe", "zoom", "desfoca", "revela", "giro3d", "digita", "mola")
MODOS = ("palavra", "letra", "linha", "bloco")
FORMAS = ("circulo", "quadrado", "triangulo", "hexagono", "losango", "estrela")
CENARIOS = ("nenhum", "grade", "pontos", "ondas", "particulas", "raios")
RITMOS = ("lento", "normal", "rapido")
EASES = ("suave", "sai", "entra", "mola", "linear", "organico")
TAMANHOS = ("xl", "g", "m", "p")
COR_TEXTO = ("txt", "txt2", "acc", "acc2", "mut")
ESTILOS_TEXTO = ("impacto", "serifa", "suave")
POSICOES = ("centro", "alto", "baixo", "esq", "dir", "alto-esq", "alto-dir", "baixo-esq", "baixo-dir")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def config(projeto) -> dict:
    return {**PADRAO, **(animation_ai.config(projeto).get("direcao") or {})}


def diretrizes() -> str:
    return (RECURSOS / "DIRETRIZES.md").read_text(encoding="utf-8")


def _num(v, padrao=None):
    try:
        x = float(v)
        return x if x == x and abs(x) != float("inf") else padrao
    except (TypeError, ValueError):
        return padrao


def _lim(v, a, b, padrao):
    x = _num(v, padrao)
    return max(a, min(b, x))


# ------------------------------------------------------------------------------------------------ conferência

def _posicao_ok(p) -> bool:
    if p is None or p in POSICOES:
        return True
    return isinstance(p, list) and len(p) == 2 and all(_num(x) is not None and 0 <= _num(x) <= 1 for x in p)


# a mesma composição do direcao.js (ANC_H, ANC_V, TAM), para o código achar sozinho o texto que bate numa forma, num número
# ou num cartão ANTES de gravar: no primeiro teste real (leite) o modelo pôs o texto no centro e um quadrado embaixo, e a
# palavra "caros" saiu escrita em cima do quadrado. A conferência do HyperFrames só lê texto contra texto
ANCORAS = {
    "horizontal": {"centro": (.5, .46), "alto": (.5, .25), "baixo": (.5, .62), "esq": (.27, .46), "dir": (.73, .46),
                   "alto-esq": (.27, .28), "alto-dir": (.73, .28), "baixo-esq": (.27, .64), "baixo-dir": (.73, .64)},
    "vertical": {"centro": (.5, .42), "alto": (.5, .26), "baixo": (.5, .58), "esq": (.5, .27), "dir": (.5, .57),
                 "alto-esq": (.5, .24), "alto-dir": (.5, .33), "baixo-esq": (.5, .5), "baixo-dir": (.5, .6)},
}
TAMANHO_DA_LETRA = {"horizontal": {"xl": 170, "g": 122, "m": 84, "p": 52}, "vertical": {"xl": 132, "g": 98, "m": 68, "p": 44}}
LARGURA_DA_LETRA = 0.47  # largura média de uma letra, em tamanhos de fonte (Playfair em negrito, medido)


def _centro(c, formato):
    pos = (c.get("pos_v") if formato == "vertical" and c.get("pos_v") else c.get("pos")) or "centro"
    if isinstance(pos, list) and len(pos) == 2:
        return max(.05, min(.95, _num(pos[0], .5))), max(.08, min(.78, _num(pos[1], .5))), str(pos)
    return (*ANCORAS[formato].get(pos, ANCORAS[formato]["centro"]), pos)


def caixa_da_camada(c, formato):
    """(esquerda, topo, direita, base) em pixels que a camada ocupa, por estimativa, ou None (linha não conta)."""
    largura, altura = FORMATOS[formato]
    em_pe = formato == "vertical"
    ax, ay, pos = _centro(c, formato)
    cx, cy = ax * largura, ay * altura
    t = c.get("tipo")
    if t == "texto":
        fs = TAMANHO_DA_LETRA[formato].get(c.get("tamanho", "g"), TAMANHO_DA_LETRA[formato]["g"])
        lado = not em_pe and isinstance(pos, str) and (pos in ("esq", "dir") or pos.endswith(("-esq", "-dir")))
        maxw = largura * (0.42 if lado else (0.86 if em_pe else 0.8))
        texto = str(c.get("texto") or "").replace("*", "")
        if c.get("modo") == "linha":
            partes = [l for l in texto.split("|") if l.strip()] or [""]
            linhas = len(partes)
            w = min(maxw, max(len(l) for l in partes) * LARGURA_DA_LETRA * fs)
        else:
            total = len(texto.replace("|", " ")) * LARGURA_DA_LETRA * fs
            linhas, w = max(1, -(-int(total) // int(maxw))), min(maxw, total)
        altura_do_texto = min(linhas * 1.2 * fs, (0.34 if em_pe else 0.4) * altura)
        topo, base = (0.14 if em_pe else 0.12) * altura, (0.70 if em_pe else 0.72) * altura
        cy = max(topo + altura_do_texto / 2, min(base - altura_do_texto / 2, cy))
        return cx - w / 2, cy - altura_do_texto / 2, cx + w / 2, cy + altura_do_texto / 2
    if t == "forma":
        r = _num(c.get("tamanho_px"), 330) * (0.86 if em_pe else 1) * 1.05
        return cx - r, cy - r, cx + r, cy + r
    if t == "numero":
        fs = TAMANHO_DA_LETRA[formato].get(c.get("tamanho", "g"), TAMANHO_DA_LETRA[formato]["g"]) * 1.15
        w = min(largura * 0.9, len(str(c.get("valor") or "")) * 0.62 * fs)
        return cx - w / 2, cy - fs * .55, cx + w / 2, cy + fs * (0.9 if c.get("legenda") else .55)
    if t == "card3d":
        fs = TAMANHO_DA_LETRA[formato].get(c.get("tamanho", "g"), TAMANHO_DA_LETRA[formato]["g"]) * .6
        w, h = largura * (0.76 if em_pe else 0.42), fs * (1.4 + (1.6 if c.get("texto") else 0)) + 88
        return cx - w / 2, cy - fs * 2, cx + w / 2, cy - fs * 2 + h
    return None


def colisoes(spec) -> list:
    """Camadas que se atropelam em algum dos formatos: o texto sobre uma forma, um número ou um cartão (ou dois textos
    um sobre o outro). Mede por estimativa o espaço de cada uma; só reprova quando passa de 8% da menor."""
    camadas = [c for c in spec.get("camadas") or [] if isinstance(c, dict)]
    erros = []
    for formato in FORMATOS:
        caixas = [(i, c, caixa_da_camada(c, formato)) for i, c in enumerate(camadas)]
        for a in range(len(caixas)):
            for b in range(a + 1, len(caixas)):
                (i, ca, ra), (j, cb, rb) = caixas[a], caixas[b]
                if ra is None or rb is None or "texto" not in (ca.get("tipo"), cb.get("tipo")):
                    continue
                dx = min(ra[2], rb[2]) - max(ra[0], rb[0])
                dy = min(ra[3], rb[3]) - max(ra[1], rb[1])
                if dx <= 0 or dy <= 0:
                    continue
                menor = min((ra[2] - ra[0]) * (ra[3] - ra[1]), (rb[2] - rb[0]) * (rb[3] - rb[1]))
                if dx * dy > 0.08 * menor:
                    erros.append(f"na tela {formato}, a camada {i + 1} ({ca.get('tipo')}, pos {ca.get('pos', 'centro')}) bate na "
                                 f"camada {j + 1} ({cb.get('tipo')}, pos {cb.get('pos', 'centro')}): dê outro 'pos' (ou "
                                 f"'pos_v' só para a tela em pé) a uma delas, para cada coisa ter o seu lugar")
    return list(dict.fromkeys(erros))


def assinatura_visual(spec) -> str:
    """O jeito da cena (paleta, cenário e entrada principal), para a próxima não repetir."""
    camadas = [c for c in (spec.get("camadas") or []) if isinstance(c, dict)]
    entrada = next((c.get("entrada") for c in camadas if c.get("tipo") == "texto"), "")
    return f"{spec.get('paleta') if isinstance(spec.get('paleta'), str) else 'custom'}|" \
           f"{(spec.get('cenario') or {}).get('estilo')}|{entrada}"


def textos_da_tela(spec) -> list:
    saida = []
    for c in spec.get("camadas") or []:
        if isinstance(c, dict):
            saida += [c.get("texto"), c.get("valor"), c.get("legenda"), c.get("titulo")]
    return [str(x) for x in saida if x not in (None, "")]


def conferir(spec, fala, extras="", anterior=None, permite_loop=False) -> list:
    """Os erros da especificação, para devolver ao modelo. Lista vazia: pode desenhar. O loop (o fim emenda no começo)
    só vale quando a pessoa pede: no primeiro teste real o diretor ligou o loop numa cena que segue para a próxima, e a
    cena inteira ganhou fade nas duas pontas."""
    if not isinstance(spec, dict):
        return ["a direção tem de ser um objeto"]
    erros = []
    pal = spec.get("paleta", "noite")
    if isinstance(pal, str):
        if pal not in PALETAS:
            erros.append(f"paleta '{pal}' não existe; use uma destas: {', '.join(PALETAS)}")
    elif isinstance(pal, dict):
        for k, v in pal.items():
            if k not in CORES_DA_PALETA or not _HEX.match(str(v)):
                erros.append(f"paleta personalizada: '{k}' tem de ser uma de {', '.join(CORES_DA_PALETA)} com cor #RRGGBB")
    else:
        erros.append("'paleta' é um nome ou um objeto com cores")
    if spec.get("ritmo", "normal") not in RITMOS:
        erros.append(f"'ritmo' é um de {', '.join(RITMOS)}")
    cen = spec.get("cenario", {})
    if not isinstance(cen, dict):
        erros.append("'cenario' é um objeto")
    else:
        if cen.get("estilo", "particulas") not in CENARIOS:
            erros.append(f"cenario.estilo é um de {', '.join(CENARIOS)}")
        ciclos = _num(cen.get("ciclos", 1))
        if ciclos is None or not 1 <= ciclos <= 4 or ciclos != int(ciclos):
            erros.append("cenario.ciclos é um inteiro de 1 a 4")
    cam = spec.get("camera")
    if not isinstance(cam, list) or len(cam) < 2:
        erros.append("a câmera nunca para: 'camera' tem de 2 a 8 marcações (a primeira é o ponto de partida)")
    elif len(cam) > 8:
        erros.append("'camera' tem no máximo 8 marcações")
    else:
        for k in cam:
            if not isinstance(k, dict) or (k.get("t") is None and not k.get("palavra")):
                erros.append("cada marcação de câmera tem 't' (segundos) ou 'palavra'")
                break
            if not 0.85 <= _num(k.get("zoom", 1), 1) <= 1.7:
                erros.append("camera.zoom vai de 0,85 a 1,7")
            if abs(_num(k.get("x", 0), 0)) > 15 or abs(_num(k.get("y", 0), 0)) > 15:
                erros.append("camera.x e camera.y vão de -15 a 15 (% da tela)")
            if abs(_num(k.get("rot", 0), 0)) > 8:
                erros.append("camera.rot vai de -8 a 8 graus")
            if k.get("ease", "suave") not in EASES:
                erros.append(f"camera.ease é um de {', '.join(EASES)}")
        if not erros and len({(_num(k.get('zoom', 1), 1), _num(k.get('x', 0), 0), _num(k.get('y', 0), 0),
                               _num(k.get('rot', 0), 0)) for k in cam if isinstance(k, dict)}) < 2:
            erros.append("a câmera está parada: as marcações têm de mudar zoom, posição ou giro")
    camadas = spec.get("camadas")
    if not isinstance(camadas, list) or not 1 <= len(camadas) <= 7:
        erros.append("'camadas' tem de 1 a 7 camadas")
        camadas = []
    tipos = [c.get("tipo") for c in camadas if isinstance(c, dict)]
    if tipos.count("texto") > 3:
        erros.append("no máximo 3 camadas de texto: uma ideia por vez")
    if tipos.count("card3d") > 1:
        erros.append("no máximo 1 card3d")
    if tipos.count("forma") > 2:
        erros.append("no máximo 2 formas")
    for c in camadas:
        if not isinstance(c, dict) or c.get("tipo") not in TIPOS:
            erros.append(f"cada camada tem 'tipo' de {', '.join(TIPOS)}")
            continue
        t = c["tipo"]
        if not _posicao_ok(c.get("pos")) or not _posicao_ok(c.get("pos_v")):
            erros.append(f"'pos' é um de {', '.join(POSICOES)} ou [x, y] entre 0 e 1")
        if not -1 <= _num(c.get("prof", 0), 0) <= 1:
            erros.append("'prof' vai de -1 a 1")
        if t == "texto":
            texto = str(c.get("texto") or "")
            if not texto.strip():
                erros.append("camada de texto sem 'texto'")
            if len(texto) > 90 or len(texto.split()) > 12:
                erros.append(f"texto comprido demais (até 90 letras e 12 palavras): \"{texto[:40]}...\"")
            if c.get("modo", "palavra") not in MODOS:
                erros.append(f"texto.modo é um de {', '.join(MODOS)}")
            if c.get("entrada", "sobe") not in ENTRADAS:
                erros.append(f"texto.entrada é uma de {', '.join(ENTRADAS)}")
            if c.get("tamanho", "g") not in TAMANHOS:
                erros.append(f"texto.tamanho é um de {', '.join(TAMANHOS)}")
            if c.get("cor", "txt") not in COR_TEXTO:
                erros.append(f"texto.cor é uma de {', '.join(COR_TEXTO)}")
            if c.get("estilo", "impacto") not in ESTILOS_TEXTO:
                erros.append(f"texto.estilo é um de {', '.join(ESTILOS_TEXTO)}")
        elif t == "forma":
            if c.get("forma", "circulo") not in FORMAS:
                erros.append(f"forma.forma é uma de {', '.join(FORMAS)}")
            for m in c.get("morph") or []:
                if not isinstance(m, dict) or m.get("para") not in FORMAS:
                    erros.append(f"forma.morph é uma lista de {{\"para\": forma, \"palavra\": ...}} com forma de {', '.join(FORMAS)}")
                    break
            if not 100 <= _num(c.get("tamanho_px", 330), 330) <= 520:
                erros.append("forma.tamanho_px vai de 100 a 520")
        elif t == "numero":
            if not str(c.get("valor") or "").strip():
                erros.append("camada numero sem 'valor'")
        elif t == "card3d":
            if not str(c.get("titulo") or "").strip() or len(str(c.get("titulo"))) > 40:
                erros.append("card3d precisa de 'titulo' de até 40 letras")
        elif t == "linha":
            for campo in ("de", "para"):
                v = c.get(campo)
                if v is not None and not _posicao_ok(v if isinstance(v, list) else "x"):
                    erros.append(f"linha.{campo} é [x, y] entre 0 e 1")
    if spec.get("loop") and not permite_loop:
        erros.append("'loop' só quando o pedido pede para o final emendar no começo: tire o 'loop' desta cena")
    if not erros:
        erros += colisoes(spec)
    textos = textos_da_tela(spec)
    if any("—" in t or "–" in t for t in textos):
        erros.append("nunca use travessão")
    ditos = animation_ai._numeros(fala) | animation_ai._numeros(extras)
    novos = [n for t in textos for n in animation_ai._numeros(t) if n not in ditos]
    if novos and not (animation_ai._EXTENSO.search(fala or "") and not animation_ai._numeros(fala)):
        erros.append(f"número que a fala não diz: {', '.join(f'{n:g}' for n in novos[:3])}")
    fora = animation_ai._inventadas(textos, f"{fala} {extras}")
    if len(fora) > 1:
        erros.append(f"palavras que a fala não diz: {', '.join(fora[:5])} (use as palavras da fala)")
    if anterior and not erros and assinatura_visual(spec) == anterior:
        erros.append("a cena anterior tem o mesmo jeito (paleta, cenário e entrada do texto): mude o cenário ou a entrada")
    return erros


def normalizar(spec) -> dict:
    """A especificação com os padrões preenchidos e os números dentro dos limites do motor."""
    s = copy.deepcopy(spec) if isinstance(spec, dict) else {}
    s["paleta"] = s.get("paleta") if (isinstance(s.get("paleta"), (str, dict))) else "noite"
    if isinstance(s["paleta"], str) and s["paleta"] not in PALETAS:
        s["paleta"] = "noite"
    s["ritmo"] = s.get("ritmo") if s.get("ritmo") in RITMOS else "normal"
    cen = s.get("cenario") if isinstance(s.get("cenario"), dict) else {}
    s["cenario"] = {"estilo": cen.get("estilo") if cen.get("estilo") in CENARIOS else "particulas",
                    "ciclos": int(_lim(cen.get("ciclos", 1), 1, 4, 1)), "seed": int(_lim(cen.get("seed", 7), 0, 99999, 7)),
                    "densidade": _lim(cen.get("densidade", 1), 0.2, 2, 1)}
    camera = []
    for k in s.get("camera") or []:
        if isinstance(k, dict):
            item = {"zoom": _lim(k.get("zoom", 1), 0.85, 1.7, 1), "x": _lim(k.get("x", 0), -15, 15, 0),
                    "y": _lim(k.get("y", 0), -15, 15, 0), "rot": _lim(k.get("rot", 0), -8, 8, 0),
                    "ease": k.get("ease") if k.get("ease") in EASES else "suave"}
            if k.get("palavra"):
                item["palavra"] = str(k["palavra"])
            if _num(k.get("t")) is not None:
                item["t"] = max(0.0, _num(k["t"]))
            camera.append(item)
    if not camera:
        camera = [{"t": 0, "zoom": 1.0, "x": 0, "y": 0, "rot": 0, "ease": "suave"}]
    s["camera"] = camera
    s["camadas"] = [c for c in (s.get("camadas") or []) if isinstance(c, dict) and c.get("tipo") in TIPOS]
    s["transicao"] = s.get("transicao") if isinstance(s.get("transicao"), dict) else {}
    s["loop"] = bool(s.get("loop"))
    return s


def cores_da_spec(spec) -> dict:
    pal = spec.get("paleta", "noite")
    base = dict(PALETAS["noite"])
    if isinstance(pal, str):
        base = dict(PALETAS.get(pal, base))
    elif isinstance(pal, dict):
        base.update({k: v for k, v in pal.items() if k in CORES_DA_PALETA and _HEX.match(str(v))})
    return base


# ------------------------------------------------------------------------------------------------ tempos e sons

def _palavras_do_texto(texto, modo) -> list:
    if modo == "linha":
        return [re.sub(r"\*", "", l).strip() for l in str(texto).split("|") if l.strip()]
    return [p for p in re.sub(r"\*", "", str(texto)).split() if p]


def _tempos_do_texto(palavras_texto, palavras_fala, inicio, fim, modo) -> list:
    """O segundo de cada palavra do texto: o da mesma palavra na fala, em sequência. Palavra que a fala não tem (ou que
    está longe demais da anterior, como um "de" repetido) entra logo depois da anterior. É a tipografia cinética: o
    texto aparece no ritmo da narração."""
    ts, depois, anterior = [], max(0.0, (inicio or 0.0) - 0.15), None
    for w in palavras_texto:
        alvo = w.split()[0] if modo == "linha" and w.split() else w
        t = animation_ai.tempo_da_palavra(alvo, palavras_fala, depois)
        perto = t is not None and (anterior is None or t - anterior <= 2.5)
        if perto and inicio is not None and anterior is None:
            t = max(t, inicio + 0.12)  # a primeira palavra respeita o `palavra` da camada
        if perto:
            depois = t + 0.01
            t = max(0.05, t - 0.1)  # entra um pouco antes da palavra chegar
        else:
            t = (anterior + 0.2) if anterior is not None else (inicio if inicio is not None else 0.3)
        if anterior is not None:
            t = max(t, anterior + 0.04)
        ts.append(round(min(t, fim), 3))
        anterior = ts[-1]
    return ts


def resolver_tempos(spec, palavras, dur):
    """(especificação com o segundo de cada elemento, sons). Quem acha o segundo de cada palavra é o Python; o motor
    só desenha. A câmera, a camada, cada palavra do texto e cada passo da forma têm o tempo da palavra da fala."""
    s = copy.deepcopy(spec)
    fim = max(0.6, dur - 0.6)

    def quando(palavra, padrao=None, depois=0.0):
        t = animation_ai.tempo_da_palavra(palavra, palavras, depois) if palavra else None
        if t is None:
            return padrao
        return round(min(max(0.05, t - 0.12), fim), 3)

    camera = []
    for k in s["camera"]:
        t = quando(k.get("palavra"), k.get("t"))
        camera.append({**k, "t": round(min(max(0.0, t if t is not None else 0.0), dur), 3)})
    camera.sort(key=lambda k: k["t"])
    if camera[0]["t"] > 0.001:
        camera.insert(0, {**camera[0], "t": 0.0})
    if len(camera) == 1:  # um ponto só não é movimento: o empurrão lento de sempre
        camera.append({**camera[0], "t": round(dur, 3), "zoom": round(camera[0]["zoom"] * 1.06, 4)})
    s["camera"] = camera

    for i, c in enumerate(s["camadas"]):
        t = quando(c.get("palavra"), None)
        if c["tipo"] == "texto":
            modo = c.get("modo") if c.get("modo") in MODOS else "palavra"
            c["modo"] = modo
            if modo == "bloco":
                c["ts"] = [t if t is not None else 0.3]
            else:
                c["ts"] = _tempos_do_texto(_palavras_do_texto(c.get("texto"), modo), palavras, t, fim, modo)
            t = c["ts"][0] if c["ts"] else (t if t is not None else 0.3)
        elif c["tipo"] == "forma":
            t = t if t is not None else round(0.3 + 0.15 * i, 3)
            anterior = t
            for m in c.get("morph") or []:
                tm = quando(m.get("palavra"), round(anterior + 1.2, 3), anterior)
                m["t"] = round(max(tm, anterior + 0.6), 3)
                anterior = m["t"]
        elif c["tipo"] == "numero":
            c["prefixo"], c["numero"], c["casas"], c["sufixo"], c["contar"] = animation_ai._partes_do_numero(c.get("valor"))
            if c["numero"] is not None:
                c["valor"] = "0" if c["contar"] else re.sub(r"^\D*?(\d[\d.]*(?:,\d+)?).*$", r"\1", str(c.get("valor")))
            t = t if t is not None else 0.4
        else:
            t = t if t is not None else round(0.4 + 0.3 * i, 3)
        c["t"] = round(min(t, fim), 3)
        ate = quando(c.get("palavra_fim"), None)
        if ate is None and _num(c.get("ate")) is not None:
            ate = _num(c["ate"])
        if ate is not None:
            c["ate"] = round(min(max(ate, c["t"] + 0.8), dur), 3)
        else:
            c.pop("ate", None)
    # a tela nunca fica só com o fundo
    if s["camadas"]:
        primeiro = min(range(len(s["camadas"])), key=lambda i: s["camadas"][i]["t"])
        c = s["camadas"][primeiro]
        if c["t"] > PRIMEIRO:
            deslocar = c["t"] - 0.45
            c["t"] = 0.45
            if c["tipo"] == "texto":
                c["ts"] = [round(max(0.45, x - deslocar), 3) for x in c["ts"]]
    return s, sons(s)


def sons(spec) -> list:
    """Os sons no tempo das entradas, no máximo 8, com 0,25 s entre eles (os mesmos nomes do animation-ai)."""
    ev = []
    for c in spec["camadas"]:
        if c["tipo"] == "texto":
            ev.append((c["ts"][0] if c.get("ts") else c["t"], "pop"))
            if c.get("modo") == "linha":
                ev += [(x, "risco") for x in (c.get("ts") or [])[1:]]
        elif c["tipo"] == "forma":
            ev.append((c["t"], "pop"))
            ev += [(m["t"], "risco") for m in c.get("morph") or []]
        elif c["tipo"] == "numero":
            ev += [(c["t"], "baque")] + ([(c["t"] + 0.05, "contagem")] if c.get("contar") else [])
        elif c["tipo"] == "card3d":
            ev.append((c["t"], "baque"))
        elif c["tipo"] == "linha":
            ev.append((c["t"], "risco"))
    saida = []
    for t, nome in sorted(ev):
        if saida and t - saida[-1][0] < 0.25:
            continue
        saida.append((round(max(0.0, t), 3), nome))
    return saida[:8]


# ------------------------------------------------------------------------------------------------ página e gravação

def montar_html(spec, dur, formato, cores, canal="") -> str:
    largura, altura = FORMATOS[formato]
    variaveis = "".join(f"--{k}:{v};" for k, v in cores.items()) + f"--W:{largura}px;--H:{altura}px;"
    dados_js = json.dumps({"spec": spec, "dur": round(dur, 3), "formato": formato, "canal": canal}, ensure_ascii=False)
    css = (RECURSOS / "direcao.css").read_text(encoding="utf-8")
    js = (RECURSOS / "direcao.js").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={largura}, height={altura}" />
    <script src="{animacoes.GSAP}"></script>
    <style>
      @font-face {{ font-family: "Titulo"; src: url("assets/fontes/PlayfairDisplay.ttf"); font-weight: 400 900; }}
      @font-face {{ font-family: "Texto"; src: url("assets/fontes/Inter.ttf"); font-weight: 100 900; }}
      :root {{ {variaveis} }}
{css}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{round(dur, 3)}" data-width="{largura}" data-height="{altura}">
      <section id="palco" class="clip" data-start="0" data-duration="{round(dur, 3)}" data-track-index="1"></section>
    </div>
    <script>window.DIR = {dados_js};</script>
    <script>
{js}
    </script>
  </body>
</html>
"""


def assinatura(resolvido, dur, cores, canal, fps, formatos) -> str:
    motor = (RECURSOS / "direcao.js").read_bytes() + (RECURSOS / "direcao.css").read_bytes()
    base = json.dumps([VERSAO, resolvido, round(dur, 3), cores, canal, fps, sorted(formatos)],
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(base.encode("utf-8") + motor).hexdigest()[:16]


def _nome_do_formato(destino: Path, formato: str) -> Path:
    return destino if formato == "horizontal" else destino.with_name(destino.stem + "_vertical.mp4")


def gravar(projeto, trecho, plano, log=print):
    """Grava o trecho nos formatos pedidos e devolve [(n, mp4 deitado, capa, duração, fotos)] de cada cena, como o
    animation_ai.gravar. O clipe em pé de cada cena fica ao lado, com `_vertical` no nome: o render em pé o acha."""
    if not animacoes.node_pronto():
        raise RuntimeError("falta o Node.js 22 ou mais (o HyperFrames grava a cena)")
    cfg = config(projeto)
    fps = int(cfg["fps"])
    formatos = [f for f in cfg["formatos"] if f in FORMATOS] or ["horizontal"]
    if "horizontal" not in formatos:
        formatos.insert(0, "horizontal")
    ini, fim = float(trecho[0]["ini"]), float(trecho[-1]["fim"])
    dur = max(fim - ini, 1.0)
    palavras = animation_ai.palavras_do_trecho(projeto, ini, fim)
    spec = normalizar(plano["dados"])
    resolvido, eventos = resolver_tempos(spec, palavras, dur)
    cores = cores_da_spec(spec)
    canal = str(animation_ai.config(projeto).get("canal") or "")
    pasta = animation_ai._pasta(projeto, trecho[0]["n"])
    marca = assinatura(resolvido, dur, cores, canal, fps, formatos)
    nome = f"{trecho[0]['n']:04d}_anim{'_trecho' if len(trecho) > 1 else ''}.mp4"
    destino = projeto.pasta / "midia" / nome
    destinos = {f: _nome_do_formato(destino, f) for f in formatos}
    partes = pasta / "partes.json"
    anterior = json.loads(partes.read_text(encoding="utf-8")) if partes.exists() else {}
    if anterior.get("assinatura") != marca or not all(d.exists() for d in destinos.values()):
        pasta.mkdir(parents=True, exist_ok=True)
        animacoes._preparar_pasta(pasta)
        destino.parent.mkdir(parents=True, exist_ok=True)
        for formato in formatos:
            (pasta / "index.html").write_text(montar_html(resolvido, dur, formato, cores, canal), encoding="utf-8")
            erros = animacoes._conferir(projeto, pasta, clipe=True)
            if erros:
                raise RuntimeError(f"a conferência do HyperFrames reprovou ({formato}): " + "; ".join(erros[:3]))
            temporario = destinos[formato].with_name(destinos[formato].stem + ".tmp.mp4")
            r = animacoes._hyperframes(projeto, ["render", "--output", str(temporario), "--format", "mp4", "--fps",
                                                 str(fps), "--workers", "1", "--quiet"], pasta, 1800)
            if r.returncode != 0 or not temporario.exists() or temporario.stat().st_size < 1000:
                temporario.unlink(missing_ok=True)
                raise RuntimeError(f"o HyperFrames não gravou a cena ({formato}): {(r.stderr or r.stdout or '')[-200:]}")
            parado = animation_ai._reprovado_por_quadro_morto(temporario, fps)
            if parado:
                temporario.unlink(missing_ok=True)
                raise RuntimeError(f"{parado} ({formato})")
            temporario.replace(destinos[formato])
        (pasta / "index.html").unlink(missing_ok=True)
        partes.write_text(json.dumps({"assinatura": marca, "tipo": "dirigida", "dados": spec, "resolvidos": resolvido,
                                      "sons": eventos, "dur": round(dur, 3), "cenas": [c["n"] for c in trecho],
                                      "fps": fps, "formatos": formatos}, ensure_ascii=False, indent=1), encoding="utf-8")
    saida = []
    for c in trecho:
        inicio = float(c["ini"]) - ini
        dur_c = max(float(c["fim"]) - float(c["ini"]), 0.5)
        pedaco = projeto.pasta / "midia" / f"{c['n']:04d}_anim.mp4"
        for formato in formatos:
            origem, alvo = destinos[formato], _nome_do_formato(pedaco, formato)
            if len(trecho) > 1:  # um trecho de várias cenas é cortado em um pedaço por cena
                rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-i", str(origem), "-t",
                       f"{dur_c + 0.05:.3f}", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "16",
                       "-pix_fmt", "yuv420p", str(alvo)])
        capa = pedaco.with_name(f"{c['n']:04d}_anim_capa.jpg")
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, min(dur_c * 0.7, dur_c - 0.1)):.2f}",
               "-i", str(pedaco), "-frames:v", "1", "-q:v", "3", str(capa)])
        saida.append((c["n"], pedaco, capa, dur_c, []))
    return saida


# ------------------------------------------------------------------------------------------------ o diretor (modelo)

ESQUEMA = {
    "type": "object",
    "properties": {"trechos": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "direcao": {"type": "object"}},
        "required": ["id", "direcao"]}}},
    "required": ["trechos"],
}
VERSAO_PLANO = 1  # suba quando mudar o pedido ou a conferência: os planos guardados são pedidos de novo


def instrucoes() -> str:
    return diretrizes()


def _marca_do_item(item) -> str:
    base = json.dumps([VERSAO_PLANO, item["fala"], item["posicao"] == 0, item["total"]], ensure_ascii=False)
    return hashlib.sha1(base.encode("utf-8") + diretrizes().encode("utf-8")).hexdigest()[:16]


def _pedido(lote, anteriores, erros_por_id) -> str:
    partes = []
    if anteriores:
        partes.append("JEITO DAS CENAS ANTERIORES (não repita o último): " + "; ".join(anteriores[-3:]))
    for item in lote:
        linha = (f"TRECHO {item['id']} ({item['dur']:.1f} s, bloco: {item['bloco'] or '-'}"
                 f"{', PRIMEIRO do vídeo' if item['posicao'] == 0 else ''}"
                 f"{', ÚLTIMO do vídeo' if item['posicao'] == item['total'] - 1 else ''}):\n{item['fala']}")
        if item["id"] in erros_por_id:
            linha += "\nA DIREÇÃO ANTERIOR DESTE TRECHO FOI RECUSADA: " + "; ".join(erros_por_id[item["id"]])
        partes.append(linha)
    return "\n\n".join(partes)


def direcao_de_reserva(fala, vez=0) -> dict:
    """Quando o modelo não acerta: a primeira frase da fala, com empurrão de câmera e a palavra mais longa em destaque.
    Varia o cenário e a entrada de uma cena para a outra. Sempre passa na conferência."""
    frase = re.split(r"(?<=[.!?…])\s+", (fala or "").strip())[0][:88]
    frase = frase.rsplit(" ", 1)[0] if len(frase) == 88 else frase
    palavras = [p for p in re.findall(r"[\wÀ-ú]+", frase) if len(p) >= 6]
    if palavras:
        maior = max(palavras, key=len)
        frase = re.sub(rf"\b{re.escape(maior)}\b", f"*{maior}*", frase, count=1)
    frase = " ".join(frase.replace("—", ",").replace("–", ",").split()[:12])
    giro = vez % 3
    return {"paleta": ("misterio", "ciencia", "historia")[giro], "ritmo": "normal",
            "cenario": {"estilo": ("particulas", "pontos", "ondas")[giro], "ciclos": 1, "seed": 11 + vez},
            "camera": [{"t": 0, "zoom": 1.0, "x": 0, "y": 0, "rot": 0},
                       {"t": 6, "zoom": 1.08, "x": (-2, 2, 0)[giro], "y": 1, "rot": (-1, 1, 0)[giro], "ease": "suave"}],
            "camadas": [{"tipo": "texto", "texto": frase, "modo": "palavra", "entrada": ("desfoca", "sobe", "revela")[giro],
                         "pos": "centro", "tamanho": "g"}]}


def planejar(projeto, itens, log=print, forcar=False) -> dict:
    """{id: especificação} para cada trecho, conferida; o que o modelo não acertar vira a direção de reserva. Os planos
    ficam em direcao/planos.json pela fala do trecho e pelas diretrizes: rodar de novo não pede ao modelo o que não mudou."""
    from . import openrouter_local

    cfg = animation_ai.config(projeto)
    arquivo = projeto.pasta / "direcao" / "planos.json"
    guardados = {} if forcar or not arquivo.exists() else json.loads(arquivo.read_text(encoding="utf-8"))
    planos = {item["id"]: guardados[_marca_do_item(item)] for item in itens if _marca_do_item(item) in guardados}
    if planos:
        log(f"  direção: {len(planos)} trecho(s) com a direção guardada")
    anteriores = [assinatura_visual(planos[i]) for i in sorted(planos)]
    por_lote = max(1, int(cfg.get("trechos_por_lote", 6)))
    novos = [item for item in itens if item["id"] not in planos]
    for k in range(0, len(novos), por_lote):
        lote = novos[k:k + por_lote]
        pendentes, erros = list(lote), {}
        for tentativa in range(1 + int(cfg.get("tentativas", 2))):
            try:
                resposta = openrouter_local.perguntar(
                    projeto, "direcao: cena dirigida", instrucoes(), _pedido(pendentes, anteriores, erros), ESQUEMA,
                    log=log, modelo=openrouter_local.principal(projeto))
            except (Exception, SystemExit) as erro:
                log(f"  direção: o diretor não respondeu ({str(erro)[:120]})")
                break
            vieram = {int(t.get("id", -1)): t for t in resposta.get("trechos") or [] if isinstance(t, dict)}
            erros, ainda = {}, []
            for item in pendentes:
                t = vieram.get(item["id"])
                if not t or not isinstance(t.get("direcao"), dict):
                    erros[item["id"]] = ["faltou este trecho na resposta"]
                    ainda.append(item)
                    continue
                problemas = conferir(t["direcao"], item["fala"], item["extras"], anteriores[-1] if anteriores else None)
                if problemas:
                    erros[item["id"]] = problemas
                    ainda.append(item)
                else:
                    planos[item["id"]] = normalizar(t["direcao"])
                    anteriores.append(assinatura_visual(planos[item["id"]]))
            pendentes = ainda
            if not pendentes:
                break
        for item in pendentes:
            log(f"  direção: trecho {item['id']} sem direção aceita ({'; '.join(erros.get(item['id'], ['sem resposta']))[:160]}); vai a de reserva")
            planos[item["id"]] = normalizar(direcao_de_reserva(item["fala"], len(planos)))
            anteriores.append(assinatura_visual(planos[item["id"]]))
        for item in lote:
            guardados[_marca_do_item(item)] = planos[item["id"]]
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(guardados, ensure_ascii=False, indent=1), encoding="utf-8")
    return planos


def fazer(projeto, cenas, log=print, forcar=False, spec=None) -> list:
    """Dirige as cenas pedidas (`fabrica direcao NOME --cenas`). Com `spec`, grava essa especificação em todas as
    cenas pedidas (para escrever à mão ou testar), sem perguntar ao modelo. Devolve as cenas feitas."""
    if not animacoes.node_pronto():
        log("  direção: falta o Node.js 22 ou mais")
        return []
    todas = projeto.ler_json("cenas.json")["cenas"]
    escolhidas = {c["n"] for c in cenas}
    grupos = [g for g in animation_ai.trechos([c for c in todas if c["n"] in escolhidas], animation_ai.config(projeto)) if g]
    if not grupos:
        return []
    log(f"  direção: {len(grupos)} cena(s) dirigida(s) para {sum(len(g) for g in grupos)} cena(s), de graça")
    itens = animation_ai._itens_para_planejar(projeto, grupos)
    if spec is not None:
        problemas = [e for g, item in zip(grupos, itens) for e in conferir(spec, item["fala"], item["extras"])]
        if problemas:
            raise SystemExit("A especificação não passou na conferência:\n  - " + "\n  - ".join(dict.fromkeys(problemas)))
        planos = {item["id"]: normalizar(spec) for item in itens}
    else:
        planos = planejar(projeto, itens, log, forcar)
    pares = [(g, {"tipo": "dirigida", "dados": planos.get(g[0]["n"]) or normalizar(direcao_de_reserva(
        " ".join(c.get("texto") or "" for c in g)))}) for g in grupos]
    return animation_ai._gravar_grupos(projeto, pares, log, frase_de_reserva=False)


# ------------------------------------------------------------------------------------------------ refinamento

def desacelerar(spec, fator=0.65) -> dict:
    """Câmera com menos deslocamento no mesmo tempo, entradas mais longas e cenário com menos voltas."""
    s = normalizar(spec)
    c0 = s["camera"][0]
    for k in s["camera"][1:]:
        for campo, neutro in (("zoom", c0["zoom"]), ("x", c0["x"]), ("y", c0["y"]), ("rot", c0["rot"])):
            k[campo] = round(neutro + (k[campo] - neutro) * fator, 4)
    s["ritmo"] = RITMOS[max(0, RITMOS.index(s["ritmo"]) - 1)]
    s["cenario"]["ciclos"] = max(1, s["cenario"]["ciclos"] - 1)
    return s


def acelerar(spec, fator=1.4) -> dict:
    s = normalizar(spec)
    c0 = s["camera"][0]
    for k in s["camera"][1:]:
        for campo, neutro, maximo in (("zoom", c0["zoom"], 1.7), ("x", c0["x"], 15), ("y", c0["y"], 15), ("rot", c0["rot"], 8)):
            v = neutro + (k[campo] - neutro) * fator
            k[campo] = round(max(0.85, min(maximo, v)) if campo == "zoom" else max(-maximo, min(maximo, v)), 4)
    s["ritmo"] = RITMOS[min(len(RITMOS) - 1, RITMOS.index(s["ritmo"]) + 1)]
    s["cenario"]["ciclos"] = min(4, s["cenario"]["ciclos"] + 1)
    return s


def suavizar(spec) -> dict:
    """Transições mais suaves: toda curva da câmera vira `suave`, entradas bruscas viram entradas que fluem."""
    s = normalizar(spec)
    for k in s["camera"]:
        k["ease"] = "suave"
    for c in s["camadas"]:
        if c.get("tipo") == "texto" and c.get("entrada") in ("zoom", "mola", "giro3d", "digita"):
            c["entrada"] = "desfoca"
    s["ritmo"] = "lento" if s["ritmo"] == "rapido" else s["ritmo"]
    s["transicao"] = {"entrada": "fade", "saida": "fade"}
    return s


def emendar_em_loop(spec) -> dict:
    s = normalizar(spec)
    s["loop"] = True
    return s


def com_as_cores_do_tema(spec, tema) -> dict:
    s = normalizar(spec)
    cores = {k: tema[k] for k in CORES_DA_PALETA if _HEX.match(str(tema.get(k, "")))}
    if "fundo" in cores and "fundo2" not in cores:
        cores["fundo2"] = cores["fundo"]
    s["paleta"] = cores
    return s


_AJUSTES = [
    (re.compile(r"\bloop\b|emend|repet(e|ir) (sem|no) fim", re.I), "o final emenda no começo", lambda s, p: emendar_em_loop(s)),
    (re.compile(r"desacelera|mais (devagar|lent)|mais calm", re.I), "mais devagar", lambda s, p: desacelerar(s)),
    (re.compile(r"acelera|mais (r[aá]pid|din[aâ]mic|agit)", re.I), "mais rápido", lambda s, p: acelerar(s)),
    (re.compile(r"(mais )?suav|suaviza", re.I), "transições mais suaves", lambda s, p: suavizar(s)),
    (re.compile(r"(padr[aã]o|cores?|paleta) do tema", re.I), "cores do tema do canal",
     lambda s, p: com_as_cores_do_tema(s, animation_ai.tema(p))),
]


def ajuste_rapido(spec, instrucao, projeto):
    """(nova especificação, o que mudou) para os pedidos simples que não precisam do modelo, ou None."""
    if len(instrucao.split()) > 9:
        return None
    for padrao, descricao, funcao in _AJUSTES:
        if padrao.search(instrucao):
            return funcao(spec, projeto), descricao
    return None


def _pedido_de_ajuste(spec, instrucao, fala) -> str:
    return (f"FALA DO TRECHO:\n{fala}\n\nESPECIFICAÇÃO ATUAL:\n{json.dumps(spec, ensure_ascii=False, indent=1)}\n\n"
            f"PEDIDO DE AJUSTE: {instrucao}\n\nDevolva a especificação INTEIRA já ajustada em "
            f"{{\"trechos\": [{{\"id\": 1, \"direcao\": {{...}}}}]}}. Mude só o que o pedido pede e mantenha o resto.")


def _trecho_da_cena(projeto, n):
    cenas = projeto.ler_json("cenas.json")["cenas"]
    por_n = {c["n"]: c for c in cenas}
    c = por_n.get(n)
    if not c or not animation_ai.e_animada(c):
        raise SystemExit(f"A cena {n} não é uma cena animada. Rode: uv run fabrica direcao {projeto.nome} --cenas {n}")
    # pelo trecho que a cena carrega, não pelos números: depois de renumerar, eles são os velhos
    for _, grupo in animation_ai.trechos_animados(cenas):
        if c in grupo:
            return grupo
    return [c]


def refinar(projeto, n, instrucao, log=print) -> dict:
    """Ajusta a cena dirigida n por uma frase ("deixa a transição mais suave", "faz o final emendar no começo"). Os
    pedidos simples saem do código, de graça e na hora; os outros vão ao modelo com a especificação atual, e a nova passa
    pela mesma conferência. A de antes fica em direcao/NNNN/historico, e `desfazer_ajuste` volta a ela."""
    from . import openrouter_local

    grupo = _trecho_da_cena(projeto, n)
    pasta = animation_ai._pasta(projeto, grupo[0]["n"])
    try:
        partes = json.loads((pasta / "partes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SystemExit(f"A cena {n} não tem uma direção guardada para ajustar.")
    if partes.get("tipo") != "dirigida":
        raise SystemExit(f"A cena {n} é uma cena de modelo pronto ({partes.get('tipo')}), não uma cena dirigida.")
    atual = normalizar(partes["dados"])
    fala = " ".join((c.get("texto") or "").strip() for c in grupo)
    rapido = ajuste_rapido(atual, instrucao, projeto)
    if rapido:
        novo, o_que = rapido
        log(f"  direção: ajuste direto ({o_que}), sem modelo")
    else:
        novo, erros = None, []
        for tentativa in range(3):
            pedido = _pedido_de_ajuste(atual, instrucao, fala)
            if erros:
                pedido += "\n\nO AJUSTE ANTERIOR FOI RECUSADO: " + "; ".join(erros)
            resposta = openrouter_local.perguntar(projeto, "direcao: ajuste", instrucoes(), pedido, ESQUEMA, log=log,
                                                  modelo=openrouter_local.principal(projeto))
            t = next((x for x in resposta.get("trechos") or [] if isinstance(x, dict)), None)
            candidato = (t or {}).get("direcao")
            erros = conferir(candidato, fala, "", None, permite_loop=True) if isinstance(candidato, dict) else ["sem direção na resposta"]
            if not erros:
                novo = normalizar(candidato)
                break
        if novo is None:
            raise SystemExit("O diretor não conseguiu fazer esse ajuste dentro das regras: " + "; ".join(erros[:3]))
    historico = pasta / "historico"
    historico.mkdir(parents=True, exist_ok=True)
    versao = len(list(historico.glob("spec_*.json"))) + 1
    (historico / f"spec_{versao:03d}.json").write_text(json.dumps(atual, ensure_ascii=False, indent=1), encoding="utf-8")
    plano = {"tipo": "dirigida", "dados": novo}
    feitas = animation_ai._gravar_grupos(projeto, [(grupo, plano)], log, frase_de_reserva=False)
    if not feitas:
        (historico / f"spec_{versao:03d}.json").unlink(missing_ok=True)
        raise SystemExit("O ajuste não saiu na gravação (veja acima); a cena ficou como estava.")
    return novo


def desfazer_ajuste(projeto, n, log=print) -> bool:
    """Volta a cena à direção de antes do último ajuste."""
    grupo = _trecho_da_cena(projeto, n)
    historico = animation_ai._pasta(projeto, grupo[0]["n"]) / "historico"
    versoes = sorted(historico.glob("spec_*.json"))
    if not versoes:
        log("  direção: não há ajuste para desfazer nesta cena")
        return False
    ultima = versoes[-1]
    anterior = json.loads(ultima.read_text(encoding="utf-8"))
    feitas = animation_ai._gravar_grupos(projeto, [(grupo, {"tipo": "dirigida", "dados": anterior})], log, frase_de_reserva=False)
    if feitas:
        ultima.unlink()
    return bool(feitas)
