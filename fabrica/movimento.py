"""Regras de movimento dos clipes de motion graphics que o modelo escreve (motion_ia: html e demonstração livre).

Tiradas do motionmaxxing (github.com/Tejashmakwana/motionmaxxing, Apache-2.0), que mediu quadro a quadro 53 momentos de
motion design profissional (cerca de 4.300 movimentos) e listou os sinais de vídeo de IA "com cara de slide". Entram aqui
só as que não brigam com o PRD-MOTION: a mola (back.out) nas entradas e as barras que sobem de scaleY 0 são do estilo da
fábrica e continuam valendo. O que vem de lá:

- nada de cara de slide: contador "02 / 05", barra de progresso, rótulo em caixa-alta espaçada, título digitado letra
  por letra (os sinais que mais denunciavam "ninguém decidiu nada" na análise deles);
- a coisa chega se movendo, não só aparecendo: eles contaram 3.392 entradas com movimento contra 584 só de opacidade;
- nada cresce de um ponto: chega de um pouco maior ou de um pouco menor, ou entra pela borda (barra de gráfico com
  scaleY é outra coisa e continua);
- quem sai acelera (ease de saída "in"), quem chega desacelera.

O texto entra nos pedidos (REGRAS) e o código confere o que dá para conferir sem ver o vídeo (problemas)."""
import re

REGRAS = """MOVIMENTO DE PROFISSIONAL (medido em motion design de verdade; o código confere os itens marcados com *):
- * Nada de cara de slide: sem contador de etapas ("02 / 05"), sem barra de progresso, sem rótulo pequeno em caixa-alta
  com letras espaçadas acima do título, sem título digitado letra por letra com cursor. Isso denuncia vídeo feito por
  máquina; o dado e o desenho bastam.
- * Cada coisa CHEGA se movendo (de y, x, scale ou desenhando o traço), não só aparecendo: opacidade sozinha é o
  recurso mais fraco. Use opacidade junto com o movimento, nunca no lugar dele.
- * Nada cresce de um ponto (scale 0): chega de um pouco maior (scale 1.15 a 1) ou um pouco menor (0.85 a 1), ou entra
  pela borda. Barra de gráfico subindo de scaleY 0 continua certa.
- Quem chega desacelera (ease ".out"; no estilo colagem, o steps de stop-motion continua valendo); quem sai acelera
  (ease ".in", como "power2.in"), e sai antes de a próxima coisa ocupar o lugar dela.
- O movimento típico dura de 0,3 a 0,7 s. Nada fica parado por muito tempo sem motivo: a cena continua viva até o fim."""

# chaves de tween que movem, desenham ou revelam: a entrada com qualquer uma delas não é "só opacidade"
_MOVE = {"x", "y", "xpercent", "ypercent", "scale", "scalex", "scaley", "rotation", "rotate", "rotationx", "rotationy",
         "skewx", "skewy", "clippath", "strokedashoffset", "strokedasharray", "height", "width", "top", "left",
         "bottom", "right", "filter", "attr", "drawsvg", "motionpath", "transform", "translate", "z", "fontsize",
         "letterspacing", "backgroundposition", "--m-fy"}

_CONTADOR = re.compile(r"(?<![\d/.,])0\d\s*/\s*\d{2}(?![\d/.,])")
_PROGRESSO = re.compile(r"<progress\b|role\s*=\s*[\"']progressbar|(?:class|id)\s*=\s*[\"'][^\"']*\b"
                        r"(?:progress|progresso|barra-de-progresso|m-progresso)\w*", re.I)
_DIGITADO = re.compile(r"\.split\(\s*([\"'])\1\s*\)|\btypewriter\b|\bcaret\b|maquina-de-escrever|\bm-cursor\b", re.I)
_DE_OBJETO = re.compile(r"\.(?:fromTo|from)\(\s*(?:[^,()]|\([^()]*\))+?,\s*\{([^{}]*)\}")


def _texto_visivel(html, js) -> str:
    """O texto que aparece: o do html sem as tags e as strings do js (que podem escrever texto na tela)."""
    return re.sub(r"<[^>]+>", " ", html) + " " + " ".join(re.findall(r"[\"'`]([^\"'`\n]{1,80})[\"'`]", js))


def _caixa_alta_espacada(css) -> bool:
    """Um bloco de CSS com texto em caixa-alta e letras espaçadas (0,08em ou 3px ou mais): o rótulo-kicker de slide."""
    for bloco in re.findall(r"\{([^{}]*)\}", css):
        if not re.search(r"text-transform\s*:\s*uppercase", bloco, re.I):
            continue
        espaco = re.search(r"letter-spacing\s*:\s*(-?[\d.]+)\s*(em|px|rem)?", bloco, re.I)
        if espaco:
            valor, unidade = float(espaco.group(1)), (espaco.group(2) or "px").lower()
            if (unidade in ("em", "rem") and valor >= 0.08) or (unidade == "px" and valor >= 3):
                return True
    return False


def _entradas(js) -> list:
    """As chaves do objeto de partida ({de}) de cada fromTo/from do js, em minúsculas."""
    return [{k.lower() for k in re.findall(r"[\"']?([A-Za-z_$-][\w$-]*)[\"']?\s*:", obj)}
            for obj in _DE_OBJETO.findall(js)]


_CHAMADA = re.compile(r"\.(?:fromTo|from)\((.*?)\)\s*;", re.S)


def _escala_de_partida(js) -> list:
    """O valor de scale (uniforme, não scaleX nem scaleY) no objeto de partida de cada fromTo/from de UM elemento.

    Os que entram em sequência (stagger) ficam de fora: ícones de contagem e partículas surgindo de um ponto um atrás do
    outro são recurso de infográfico. O sinal de IA é um elemento só (uma caixa, um card, um logo) crescendo do nada."""
    valores = []
    for chamada in _CHAMADA.findall(js):
        if "stagger" in chamada:
            continue
        partida = re.search(r"\{([^{}]*)\}", chamada)
        if not partida:
            continue
        for v in re.findall(r"(?<![\w-])[\"']?scale[\"']?\s*:\s*(-?[\d.]+)", partida.group(1)):
            try:
                valores.append(float(v))
            except ValueError:
                continue
    return valores


def problemas(partes) -> list:
    """O que o código acha das regras de movimento no css, html e js que o modelo escreveu. Lista vazia: tudo certo."""
    css, html, js = (str(partes.get(k) or "") for k in ("css", "html", "js"))
    erros = []
    if _CONTADOR.search(_texto_visivel(html, js)):
        erros.append('tem contador de slide ("02 / 05"): tire, o dado e o desenho bastam')
    if _PROGRESSO.search(html + css + js):
        erros.append("tem barra de progresso: tire, isso é cara de slide")
    if _caixa_alta_espacada(css):
        erros.append("tem rótulo em caixa-alta com letras espaçadas (cara de slide): escreva em caixa normal, sem "
                     "letter-spacing, ou tire o rótulo")
    if _DIGITADO.search(js + html):
        erros.append("tem texto digitado letra por letra: faça a palavra inteira chegar se movendo (y 30 a 0)")
    entradas = [chaves for chaves in _entradas(js) if "opacity" in chaves or chaves & _MOVE]
    so_opacidade = [chaves for chaves in entradas if "opacity" in chaves and not chaves & _MOVE]
    # uma entrada só de opacidade passa (um brilho, o fundo); o erro é quando esse é o jeito do clipe
    if len(so_opacidade) >= 2 and 2 * len(so_opacidade) >= len(entradas):
        erros.append(f"{len(so_opacidade)} de {len(entradas)} entradas são só de opacidade: cada coisa chega se movendo "
                     "(y, x, scale ou traço), com a opacidade junto")
    pontos = [v for v in _escala_de_partida(js) if 0 <= v < 0.3]
    if pontos:
        erros.append("tem coisa crescendo de um ponto (scale perto de 0): chegue de 0.85 ou de 1.15 até 1, ou entre pela "
                     "borda (barra de gráfico com scaleY continua valendo)")
    return erros
