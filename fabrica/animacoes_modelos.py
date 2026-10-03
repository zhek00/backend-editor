"""Os modelos de animação que a fábrica sabe desenhar, com o design pronto e testado.

O modelo de linguagem só escolhe o modelo e preenche os textos curtos e o segundo em que cada um entra. Escrevendo
o HTML livre ele errava o tempo (elemento aparecendo antes de ser falado), esquecia elementos e embolava o layout;
a conferência do HyperFrames pega texto sobreposto, mas não pega design ruim. Aqui o design é sempre o mesmo, no
padrão editorial do canal, e o código confere que cada tempo cai numa palavra falada.

Cada modelo recebe os dados já conferidos e devolve as partes da página: css, html e js (as entradas na linha do
tempo `tl`). A tela útil é a área de #conteudo: 1700 x 760 px (110 px de margem nas laterais e no topo, 210 px
embaixo para a legenda do vídeo).
"""
import html as _html
import json
import math
import re

VERSAO = 2  # suba quando mudar o design: as animações feitas com o design antigo são refeitas (sem pedir de novo ao modelo)

CSS_BASE = """
.rotulo { font-family: "Texto", sans-serif; font-weight: 600; font-size: 30px; letter-spacing: 0.26em;
          text-transform: uppercase; color: var(--destaque); }
.titulo { font-family: "Titulo", serif; font-weight: 700; color: var(--texto); line-height: 1.08; }
.apoio { font-family: "Texto", sans-serif; font-weight: 500; font-size: 34px; line-height: 1.3; color: var(--secundaria); }
.cartao { background: var(--painel); border: 2px solid rgba(255, 255, 255, 0.14); border-radius: 8px; }
.traco { display: block; height: 4px; background: var(--destaque); transform-origin: left center; }
"""


def esc(texto) -> str:
    return _html.escape(str(texto or ""), quote=True)


def _tam(texto, faixas) -> int:
    """Tamanho de fonte pelo comprimento do texto: [(até N letras, px), ...]; o último vale para o resto."""
    n = len(str(texto or ""))
    for limite, px in faixas:
        if n <= limite:
            return px
    return faixas[-1][1]


def _entra(seletor, t, de="{opacity: 0, y: 26}", dur=0.45, ease="power3.out") -> str:
    t = max(float(t), 0.0)
    return f'tl.fromTo("{seletor}", {de}, {{opacity: 1, x: 0, y: 0, scale: 1, duration: {dur}, ease: "{ease}"}}, {t:.2f});'


# ------------------------------------------------------------------------------------------------ frase

def frase(d, dur):
    """Uma frase forte, palavra por palavra no tempo da fala, com as palavras-chave na cor de destaque."""
    palavras = d["palavras"]
    total = sum(len(p["texto"]) + 1 for p in palavras)
    px = _tam("x" * total, [(18, 120), (30, 100), (45, 84), (70, 68), (999, 58)])
    css = f"""
#f-caixa {{ width: 100%; height: 100%; display: flex; flex-direction: column; justify-content: center; gap: 30px; }}
#f-linha {{ display: flex; flex-wrap: wrap; column-gap: 0.28em; row-gap: 0.1em; max-width: 1500px;
           font-family: "Titulo", serif; font-weight: 700; font-size: {px}px; line-height: 1.1; color: var(--texto); }}
.f-p {{ display: inline-block; }}
.f-p.f-d {{ color: var(--destaque); }}
#f-traco {{ width: 280px; }}
"""
    partes = "".join(f'<span id="f-p{i}" class="f-p{" f-d" if p.get("destaque") else ""}">{esc(p["texto"])}</span>'
                     for i, p in enumerate(palavras))
    rotulo = f'<div id="f-rotulo" class="rotulo">{esc(d["rotulo"]["texto"])}</div>' if d.get("rotulo") else ""
    html = f'<div id="f-caixa">{rotulo}<div id="f-traco" class="traco"></div><div id="f-linha">{partes}</div></div>'
    js = []
    if d.get("rotulo"):
        js.append(_entra("#f-rotulo", d["rotulo"]["t"], "{opacity: 0, x: -30}"))
    t0 = min(p["t"] for p in palavras)
    js.append(f'tl.fromTo("#f-traco", {{scaleX: 0}}, {{scaleX: 1, duration: 0.6, ease: "power2.inOut"}}, {max(t0 - 0.1, 0):.2f});')
    js += [_entra(f"#f-p{i}", p["t"], "{opacity: 0, y: 34}", 0.4) for i, p in enumerate(palavras)]
    return css, html, "\n".join(js)


# ------------------------------------------------------------------------------------------------ número

def _numero_valor(texto):
    limpo = str(texto).strip().replace(".", "").replace(",", ".")
    try:
        return float(limpo)
    except ValueError:
        return None


def numero(d, dur):
    """Um número grande que sobe até o valor no tempo da fala, com o que ele mede e, se for percentual, um medidor."""
    valor = _numero_valor(d["numero"]["texto"])
    casas = len(str(d["numero"]["texto"]).replace(".", "").split(",")[1]) if "," in str(d["numero"]["texto"]) else 0
    texto_final = f'{d.get("prefixo", "")}{d["numero"]["texto"]}{d.get("sufixo", "")}'
    px = _tam(texto_final, [(5, 250), (8, 200), (11, 160), (999, 130)])
    medidor = d.get("medidor")
    css = f"""
#n-caixa {{ width: 100%; height: 100%; display: flex; flex-direction: column; justify-content: center; gap: 26px; }}
#n-traco {{ width: 520px; }}
#n-linha {{ display: flex; align-items: center; gap: 56px; }}
#n-numero {{ font-family: "Titulo", serif; font-weight: 700; font-size: {px}px; line-height: 1.05; color: var(--texto);
            font-variant-numeric: tabular-nums; }}
#n-medidor {{ position: relative; width: 50px; height: {int(px * 0.85)}px; border: 3px solid rgba(243, 235, 221, 0.5);
             border-radius: 25px; overflow: hidden; }}
#n-nivel {{ position: absolute; left: 0; right: 0; bottom: 0; height: 100%; display: block;
           background: linear-gradient(0deg, #b4521c, var(--destaque)); transform-origin: bottom center; }}
#n-legenda {{ font-family: "Texto", sans-serif; font-weight: 600; font-size: 52px; letter-spacing: 0.06em;
             color: var(--texto); max-width: 1400px; }}
"""
    partes = []
    if d.get("rotulo"):
        partes.append(f'<div id="n-rotulo" class="rotulo">{esc(d["rotulo"]["texto"])}</div>')
    partes.append('<div id="n-traco" class="traco"></div>')
    inicial = f'{d.get("prefixo", "")}0{d.get("sufixo", "")}' if valor is not None else texto_final
    linha = f'<div id="n-numero">{esc(inicial)}</div>'
    if medidor is not None:
        linha += '<div id="n-medidor"><div id="n-nivel"></div></div>'
    partes.append(f'<div id="n-linha">{linha}</div>')
    if d.get("legenda"):
        partes.append(f'<div id="n-legenda">{esc(d["legenda"]["texto"])}</div>')
    html = f'<div id="n-caixa">{"".join(partes)}</div>'
    t = d["numero"]["t"]
    js = []
    if d.get("rotulo"):
        js.append(_entra("#n-rotulo", d["rotulo"]["t"], "{opacity: 0, x: -30}"))
        js.append(f'tl.fromTo("#n-traco", {{scaleX: 0}}, {{scaleX: 1, duration: 0.7, ease: "power2.inOut"}}, {d["rotulo"]["t"] + 0.1:.2f});')
    else:
        js.append(f'tl.fromTo("#n-traco", {{scaleX: 0}}, {{scaleX: 1, duration: 0.6, ease: "power2.inOut"}}, {max(t - 0.4, 0):.2f});')
    js.append(_entra("#n-linha", max(t - 0.12, 0), "{opacity: 0, y: 30}", 0.35))
    if valor is not None:
        prefixo, sufixo = json.dumps(d.get("prefixo", "")), json.dumps(d.get("sufixo", ""))
        js.append(f"""const contador = {{ v: 0 }};
tl.to(contador, {{ v: {valor}, duration: 0.8, ease: "power2.out", onUpdate: () => {{
  document.getElementById("n-numero").textContent = {prefixo} + contador.v.toLocaleString("pt-BR", {{
    minimumFractionDigits: {casas}, maximumFractionDigits: {casas} }}) + {sufixo};
}} }}, {t:.2f});""")
    if medidor is not None:
        js.append(f'tl.fromTo("#n-nivel", {{scaleY: 0}}, {{scaleY: {max(0.0, min(float(medidor), 100.0)) / 100:.3f}, '
                  f'duration: 0.8, ease: "power2.out"}}, {t:.2f});')
    if d.get("legenda"):
        js.append(_entra("#n-legenda", d["legenda"]["t"], "{opacity: 0, y: 18}", 0.4, "power2.out"))
    return css, html, "\n".join(js)


# ------------------------------------------------------------------------------------------------ contraste

def contraste(d, dur):
    """Dois lados frente a frente (artesanal × industrial, antes × depois). O lado vencido é riscado e apaga."""
    lados = ("esquerda", "direita")
    maior = max(len(d[l]["titulo"]["texto"]) for l in lados)
    px = _tam("x" * maior, [(10, 100), (16, 84), (24, 68), (999, 56)])
    css = f"""
#c-lados {{ width: 100%; height: 100%; display: grid; grid-template-columns: 1fr 110px 1fr; align-items: center; }}
.c-cartao {{ height: 540px; padding: 56px 54px; display: flex; flex-direction: column; justify-content: center; gap: 24px; }}
#c-esquerda {{ border-color: rgba(232, 163, 61, 0.65); }}
.c-titulo-caixa {{ position: relative; }}
.c-titulo {{ font-size: {px}px; }}
.c-risco {{ position: absolute; left: -8px; right: -8px; top: 50%; height: 9px; margin-top: -4px; display: block;
           background: var(--alerta); transform-origin: left center; }}
.c-selo {{ align-self: flex-start; padding: 10px 22px; border: 3px solid var(--destaque); font-family: "Texto", sans-serif;
          font-weight: 600; font-size: 28px; letter-spacing: 0.18em; text-transform: uppercase; color: var(--destaque); }}
#c-meio {{ display: flex; justify-content: center; font-family: "Titulo", serif; font-weight: 700; font-size: 60px;
          color: var(--secundaria); }}
"""
    blocos = []
    for lado in lados:
        x = d[lado]
        selo = f'<div id="c-{lado}-selo" class="c-selo">{esc(x["selo"]["texto"])}</div>' if x.get("selo") else ""
        detalhe = f'<div id="c-{lado}-detalhe" class="apoio">{esc(x["detalhe"]["texto"])}</div>' if x.get("detalhe") else ""
        rotulo = f'<div class="rotulo">{esc(x["rotulo"])}</div>' if x.get("rotulo") else ""
        blocos.append(f'<div id="c-{lado}" class="cartao c-cartao">{rotulo}<div class="c-titulo-caixa">'
                      f'<div class="titulo c-titulo">{esc(x["titulo"]["texto"])}</div><div id="c-{lado}-risco" '
                      f'class="c-risco"></div></div>{detalhe}{selo}</div>')
    html = f'<div id="c-lados">{blocos[0]}<div id="c-meio"><div id="c-x">×</div></div>{blocos[1]}</div>'
    js = [_entra("#c-esquerda", d["esquerda"]["titulo"]["t"], "{opacity: 0, x: -60}", 0.5),
          _entra("#c-x", d["direita"]["titulo"]["t"] - 0.25, "{opacity: 0}", 0.3),
          _entra("#c-direita", d["direita"]["titulo"]["t"], "{opacity: 0, x: 60}", 0.5),
          'tl.set(".c-risco", {scaleX: 0}, 0);']
    for lado in lados:
        x = d[lado]
        if x.get("detalhe"):
            js.append(_entra(f"#c-{lado}-detalhe", x["detalhe"]["t"], "{opacity: 0, y: 14}", 0.35, "power2.out"))
        if x.get("selo"):
            js.append(_entra(f"#c-{lado}-selo", x["selo"]["t"], "{opacity: 0, scale: 1.35}", 0.3, "back.out(2)"))
    if d.get("vencido"):
        perdedor, t = d["vencido"]["lado"], d["vencido"]["t"]
        vencedor = "direita" if perdedor == "esquerda" else "esquerda"
        js.append(f'tl.fromTo("#c-{perdedor}-risco", {{scaleX: 0}}, {{scaleX: 1, duration: 0.3, ease: "power2.in"}}, {t:.2f});')
        js.append(f'tl.to("#c-{perdedor}", {{opacity: 0.45, duration: 0.3}}, {t + 0.15:.2f});')
        js.append(f'tl.to("#c-{vencedor}", {{scale: 1.03, duration: 0.3, ease: "power2.out"}}, {t + 0.15:.2f});')
    return css, html, "\n".join(js)


# ------------------------------------------------------------------------------------------------ radial

def radial(d, dur):
    """Um centro (o assunto) com os elementos ligados a ele, cada linha desenhada quando o elemento é falado."""
    itens = d["itens"]
    cx, cy = 850, 330  # centro dentro de #conteudo (1700 x 760, com a legenda opcional embaixo)
    rx, ry = 560, 230
    n = len(itens)
    angulos = [(-90 + 360 * i / n) if n != 4 else (-150, -30, 30, 150)[i] for i in range(n)]
    pontos = [(cx + rx * math.cos(math.radians(a)), cy + ry * math.sin(math.radians(a))) for a in angulos]
    maior = max(len(i["texto"]) for i in itens)
    no_px = _tam("x" * maior, [(8, 34), (13, 30), (999, 26)])
    centro_px = _tam(d["centro"]["texto"], [(10, 48), (16, 40), (999, 34)])
    css = f"""
#r-area {{ position: relative; width: 1700px; height: 660px; }}
#r-linhas {{ position: absolute; left: 0; top: 0; width: 1700px; height: 660px; }}
.r-linha {{ fill: none; stroke: var(--destaque); stroke-opacity: 0.85; stroke-width: 4; }}
#r-centro {{ position: absolute; left: {cx - 160}px; top: {cy - 160}px; width: 320px; height: 320px; border-radius: 50%;
            display: flex; align-items: center; justify-content: center; text-align: center; padding: 30px;
            background: radial-gradient(circle, rgba(255, 176, 70, 0.95) 0%, rgba(205, 80, 25, 0.92) 58%, rgba(120, 28, 12, 0.92) 100%);
            box-shadow: 0 0 90px rgba(255, 130, 40, 0.6); font-family: "Titulo", serif; font-weight: 700;
            font-size: {centro_px}px; line-height: 1.1; color: #fff7ea; }}
.r-no {{ position: absolute; width: 300px; height: 92px; margin-left: -150px; margin-top: -46px; border-radius: 46px;
        display: flex; align-items: center; justify-content: center; text-align: center; padding: 0 18px;
        font-family: "Texto", sans-serif; font-weight: 600; font-size: {no_px}px; letter-spacing: 0.1em;
        text-transform: uppercase; color: var(--texto); border-color: rgba(232, 163, 61, 0.8); }}
#r-legenda {{ display: flex; justify-content: center; flex-wrap: wrap; column-gap: 0.4em; margin-top: 30px;
             font-family: "Texto", sans-serif; font-weight: 600; font-size: 48px; letter-spacing: 0.08em;
             text-transform: uppercase; color: var(--texto); }}
.r-p {{ display: inline-block; }}
.r-p.r-d {{ color: var(--destaque); }}
"""
    linhas = "".join(f'<line id="r-l{i}" class="r-linha" x1="{cx}" y1="{cy}" x2="{x:.0f}" y2="{y:.0f}" '
                     f'stroke-dasharray="{math.hypot(x - cx, y - cy):.0f}" stroke-dashoffset="{math.hypot(x - cx, y - cy):.0f}" />'
                     for i, (x, y) in enumerate(pontos))
    nos = "".join(f'<div id="r-n{i}" class="cartao r-no" style="left: {x:.0f}px; top: {y:.0f}px;">{esc(item["texto"])}</div>'
                  for i, (item, (x, y)) in enumerate(zip(itens, pontos)))
    legenda = ""
    if d.get("legenda"):
        legenda = '<div id="r-legenda">' + "".join(
            f'<span id="r-p{i}" class="r-p{" r-d" if p.get("destaque") else ""}">{esc(p["texto"])}</span>'
            for i, p in enumerate(d["legenda"])) + "</div>"
    html = (f'<div id="r-area"><svg id="r-linhas" viewBox="0 0 1700 660">{linhas}</svg>{nos}'
            f'<div id="r-centro">{esc(d["centro"]["texto"])}</div></div>{legenda}')
    js = [_entra("#r-centro", d["centro"]["t"], "{opacity: 0, scale: 0.6}", 0.5, "back.out(1.6)")]
    anterior = d["centro"]["t"]
    for i, item in enumerate(itens):
        # itens falados juntos (ou antes da cena) entram um depois do outro, nunca todos no mesmo quadro
        t = max(item["t"], anterior + 0.15)
        anterior = t
        js.append(f'tl.to("#r-l{i}", {{strokeDashoffset: 0, duration: 0.35, ease: "power2.out"}}, {max(t - 0.15, 0):.2f});')
        js.append(_entra(f"#r-n{i}", t, "{opacity: 0, scale: 0.8}", 0.3, "back.out(1.8)"))
    for i, p in enumerate(d.get("legenda") or []):
        js.append(_entra(f"#r-p{i}", p["t"], "{opacity: 0, y: 24}", 0.3, "power2.out"))
    return css, html, "\n".join(js)


# ------------------------------------------------------------------------------------------------ lista

def lista(d, dur):
    """Itens que entram um a um, cada um quando é falado, com um título opcional."""
    itens = d["itens"]
    maior = max(len(i["texto"]) for i in itens)
    px = _tam("x" * maior, [(14, 64), (24, 54), (36, 46), (999, 40)])
    css = f"""
#l-caixa {{ width: 100%; height: 100%; display: flex; flex-direction: column; justify-content: center; gap: 30px; }}
#l-titulo {{ font-size: 76px; max-width: 1500px; }}
#l-itens {{ display: flex; flex-direction: column; gap: 22px; }}
.l-item {{ display: flex; align-items: center; gap: 30px; max-width: 1500px; }}
.l-marca {{ display: block; flex: 0 0 auto; width: 22px; height: 22px; border-radius: 50%; background: var(--destaque); }}
.l-texto {{ font-family: "Texto", sans-serif; font-weight: 600; font-size: {px}px; line-height: 1.2; color: var(--texto); }}
"""
    titulo = f'<div id="l-titulo" class="titulo">{esc(d["titulo"]["texto"])}</div><div id="l-traco" class="traco" style="width: 300px;"></div>' if d.get("titulo") else ""
    itens_html = "".join(f'<div id="l-i{i}" class="l-item"><div class="l-marca"></div><div class="l-texto">{esc(it["texto"])}</div></div>'
                         for i, it in enumerate(itens))
    html = f'<div id="l-caixa">{titulo}<div id="l-itens">{itens_html}</div></div>'
    js = []
    if d.get("titulo"):
        js.append(_entra("#l-titulo", d["titulo"]["t"], "{opacity: 0, y: 26}"))
        js.append(f'tl.fromTo("#l-traco", {{scaleX: 0}}, {{scaleX: 1, duration: 0.6, ease: "power2.inOut"}}, {d["titulo"]["t"] + 0.15:.2f});')
    js += [_entra(f"#l-i{i}", it["t"], "{opacity: 0, x: -40}", 0.4) for i, it in enumerate(itens)]
    return css, html, "\n".join(js)


# ------------------------------------------------------------------------------------------------ fluxo

def fluxo(d, dur):
    """Etapas de um processo, da esquerda para a direita, ligadas por setas que se desenham no tempo da fala."""
    etapas = d["etapas"]
    n = len(etapas)
    largura = {2: 520, 3: 420, 4: 330, 5: 270}[n]
    maior = max(len(e["texto"]) for e in etapas)
    px = _tam("x" * maior, [(10, 42 if n <= 3 else 36), (18, 36 if n <= 3 else 30), (999, 30 if n <= 3 else 26)])
    css = f"""
#x-caixa {{ width: 100%; height: 100%; display: flex; flex-direction: column; justify-content: center; gap: 46px; }}
#x-titulo {{ font-size: 72px; text-align: center; }}
#x-etapas {{ display: flex; align-items: center; justify-content: center; gap: 0; }}
.x-etapa {{ width: {largura}px; min-height: 190px; padding: 26px 24px; display: flex; flex-direction: column;
           align-items: center; justify-content: center; gap: 12px; text-align: center; }}
.x-numero {{ font-family: "Titulo", serif; font-weight: 700; font-size: 40px; color: var(--destaque); }}
.x-texto {{ font-family: "Texto", sans-serif; font-weight: 600; font-size: {px}px; line-height: 1.2; color: var(--texto); }}
.x-seta {{ display: block; width: 70px; height: 40px; }}
.x-seta path {{ fill: none; stroke: var(--destaque); stroke-width: 5; stroke-linecap: round; stroke-linejoin: round;
               stroke-dasharray: 90; stroke-dashoffset: 90; }}
"""
    pedacos = []
    for i, e in enumerate(etapas):
        if i:
            pedacos.append(f'<svg id="x-s{i}" class="x-seta" viewBox="0 0 70 40"><path d="M6 20 H60 M46 8 L62 20 L46 32" /></svg>')
        pedacos.append(f'<div id="x-e{i}" class="cartao x-etapa"><div class="x-numero">{i + 1}</div>'
                       f'<div class="x-texto">{esc(e["texto"])}</div></div>')
    titulo = f'<div id="x-titulo" class="titulo">{esc(d["titulo"]["texto"])}</div>' if d.get("titulo") else ""
    html = f'<div id="x-caixa">{titulo}<div id="x-etapas">{"".join(pedacos)}</div></div>'
    js = [_entra("#x-titulo", d["titulo"]["t"])] if d.get("titulo") else []
    for i, e in enumerate(etapas):
        if i:
            js.append(f'tl.to("#x-s{i} path", {{strokeDashoffset: 0, duration: 0.3, ease: "power2.out"}}, {max(e["t"] - 0.25, 0):.2f});')
        js.append(_entra(f"#x-e{i}", e["t"], "{opacity: 0, y: 30}", 0.4))
    return css, html, "\n".join(js)


# ------------------------------------------------------------------------------------------------ linha do tempo

def linha_do_tempo(d, dur):
    """Um eixo que se desenha, com 2 a 4 marcos (ano e o que aconteceu) entrando no tempo da fala."""
    marcos = d["marcos"]
    n = len(marcos)
    posicoes = [150 + (1400 * i / (n - 1) if n > 1 else 700) for i in range(n)]
    css = """
#t-caixa { position: relative; width: 1700px; height: 760px; }
#t-titulo { position: absolute; left: 0; right: 0; top: 40px; text-align: center; font-size: 70px; }
#t-eixo { position: absolute; left: 100px; top: 380px; width: 1500px; height: 5px; display: block;
          background: rgba(243, 235, 221, 0.55); transform-origin: left center; }
.t-marco { position: absolute; top: 300px; width: 360px; margin-left: -180px; display: flex; flex-direction: column;
           align-items: center; gap: 18px; text-align: center; }
.t-ponto { display: block; width: 34px; height: 34px; border-radius: 50%; background: var(--destaque);
           box-shadow: 0 0 30px rgba(232, 163, 61, 0.7); margin-top: 63px; }
.t-ano { position: absolute; top: -10px; font-family: "Titulo", serif; font-weight: 700; font-size: 58px; color: var(--texto); }
.t-texto { font-family: "Texto", sans-serif; font-weight: 600; font-size: 32px; line-height: 1.25; color: var(--secundaria);
           max-width: 340px; }
"""
    titulo = f'<div id="t-titulo" class="titulo">{esc(d["titulo"]["texto"])}</div>' if d.get("titulo") else ""
    marcos_html = "".join(f'<div id="t-m{i}" class="t-marco" style="left: {x:.0f}px;"><div class="t-ano">{esc(m["rotulo"])}</div>'
                          f'<div class="t-ponto"></div><div class="t-texto">{esc(m.get("texto", ""))}</div></div>'
                          for i, (m, x) in enumerate(zip(marcos, posicoes)))
    html = f'<div id="t-caixa">{titulo}<div id="t-eixo"></div>{marcos_html}</div>'
    primeiro = min(m["t"] for m in marcos)
    js = [_entra("#t-titulo", d["titulo"]["t"])] if d.get("titulo") else []
    js.append(f'tl.fromTo("#t-eixo", {{scaleX: 0}}, {{scaleX: 1, duration: 0.9, ease: "power2.inOut"}}, {max(primeiro - 0.5, 0):.2f});')
    js += [_entra(f"#t-m{i}", m["t"], "{opacity: 0, y: 30}", 0.4) for i, m in enumerate(marcos)]
    return css, html, "\n".join(js)


# ------------------------------------------------------------------------------------------------ mapa

_DIRECOES = {"norte": (0, -1), "sul": (0, 1), "leste": (1, 0), "oeste": (-1, 0), "nordeste": (0.8, -0.7),
             "noroeste": (-0.8, -0.7), "sudeste": (0.8, 0.7), "sudoeste": (-0.8, 0.7)}


def mapa(d, dur):
    """Sem contorno de país (sairia errado): um marcador pulsando no lugar, com o nome, e setas para as referências."""
    cx, cy = 850, 330
    lugar = d["lugar"]
    px = _tam(lugar["nome"], [(12, 92), (20, 76), (999, 60)])
    # o nome fica do lado do marcador que não tem seta: embaixo, ou em cima se só houver referências ao sul
    verticais = [{"norte": "nordeste", "sul": "sudeste"}.get(r.get("direcao"), r.get("direcao"))
                 for r in d.get("referencias") or []]
    ao_sul = any(_DIRECOES.get(v, (0, 0))[1] > 0 for v in verticais)
    ao_norte = any(_DIRECOES.get(v, (0, 0))[1] < 0 for v in verticais)
    nome_em_cima = ao_sul and not ao_norte
    altura_nome = px + (60 if lugar.get("detalhe") else 0)
    topo_nome = cy - 80 - altura_nome if nome_em_cima else cy + 70
    css = f"""
#m-area {{ position: relative; width: 1700px; height: 760px; }}
#m-anel1, #m-anel2 {{ position: absolute; left: {cx - 70}px; top: {cy - 70}px; width: 140px; height: 140px; display: block;
                     border-radius: 50%; border: 3px solid var(--destaque); }}
#m-ponto {{ position: absolute; left: {cx - 22}px; top: {cy - 22}px; width: 44px; height: 44px; display: block;
           border-radius: 50%; background: var(--destaque); box-shadow: 0 0 40px rgba(232, 163, 61, 0.9); }}
#m-nome {{ position: absolute; left: 0; right: 0; top: {topo_nome}px; text-align: center; font-size: {px}px; }}
#m-detalhe {{ position: absolute; left: 0; right: 0; top: {topo_nome + px + 10}px; text-align: center; }}
#m-setas {{ position: absolute; left: 0; top: 0; width: 1700px; height: 760px; }}
.m-seta {{ fill: none; stroke: rgba(243, 235, 221, 0.75); stroke-width: 4; stroke-linecap: round; }}
.m-ref {{ position: absolute; width: 320px; margin-left: -160px; text-align: center; font-family: "Texto", sans-serif;
         font-weight: 600; font-size: 34px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--texto); }}
#m-distancia {{ position: absolute; right: 0; top: 0; padding: 18px 28px; font-family: "Titulo", serif; font-weight: 700;
               font-size: 52px; color: var(--destaque); }}
"""
    setas, refs = [], []
    for i, r in enumerate(d.get("referencias") or []):
        direcao = r.get("direcao", "norte")
        # norte e sul viram diagonais: o nome do lugar fica logo abaixo do marcador e a seta passaria por cima dele
        direcao = {"norte": "nordeste", "sul": "sudeste"}.get(direcao, direcao)
        dx, dy = _DIRECOES.get(direcao, (0.8, -0.7))
        if dy > 0 and ao_norte:
            # o nome está embaixo do marcador: a seta do sul sai pela lateral, por fora do bloco do nome
            lado = 1 if dx >= 0 else -1
            x1, y1 = cx + lado * 400, cy + 20
            x2, y2 = cx + dx * 620, cy + dy * 330
        else:
            x1, y1 = cx + dx * 120, cy + dy * 110
            x2, y2 = cx + dx * 500, cy + dy * 250
        comprimento = math.hypot(x2 - x1, y2 - y1)
        setas.append(f'<line id="m-s{i}" class="m-seta" x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                     f'stroke-dasharray="{comprimento:.0f}" stroke-dashoffset="{comprimento:.0f}" />')
        # o rótulo fica além da ponta da seta, sem encostar nela
        tx = x2 + (dx * 190 if dy == 0 else dx * 30)
        ty = y2 - 64 if dy < 0 else (y2 + 18 if dy > 0 else y2 - 22)
        refs.append(f'<div id="m-r{i}" class="m-ref" style="left: {tx:.0f}px; top: {ty:.0f}px;">{esc(r["nome"])}</div>')
    detalhe = f'<div id="m-detalhe" class="apoio">{esc(lugar["detalhe"])}</div>' if lugar.get("detalhe") else ""
    distancia = f'<div id="m-distancia" class="cartao">{esc(d["distancia"]["texto"])}</div>' if d.get("distancia") else ""
    html = (f'<div id="m-area"><svg id="m-setas" viewBox="0 0 1700 760">{"".join(setas)}</svg>'
            f'<div id="m-anel1"></div><div id="m-anel2"></div><div id="m-ponto"></div>'
            f'<div id="m-nome" class="titulo">{esc(lugar["nome"])}</div>{detalhe}{"".join(refs)}{distancia}</div>')
    t = lugar["t"]
    js = [_entra("#m-ponto", t, "{opacity: 0, scale: 0}", 0.4, "back.out(2)"),
          f'tl.fromTo("#m-anel1", {{opacity: 0.9, scale: 0.3}}, {{opacity: 0, scale: 2.2, duration: 1.4, ease: "power1.out"}}, {t:.2f});',
          f'tl.fromTo("#m-anel2", {{opacity: 0.9, scale: 0.3}}, {{opacity: 0, scale: 2.2, duration: 1.4, ease: "power1.out"}}, {t + 0.7:.2f});',
          _entra("#m-nome", t + 0.1, "{opacity: 0, y: 24}")]
    if lugar.get("detalhe"):
        js.append(_entra("#m-detalhe", lugar.get("t_detalhe", t + 0.4), "{opacity: 0, y: 16}", 0.4, "power2.out"))
    for i, r in enumerate(d.get("referencias") or []):
        js.append(f'tl.to("#m-s{i}", {{strokeDashoffset: 0, duration: 0.5, ease: "power2.out"}}, {r["t"]:.2f});')
        js.append(_entra(f"#m-r{i}", r["t"] + 0.3, "{opacity: 0}", 0.3))
    if d.get("distancia"):
        js.append(_entra("#m-distancia", d["distancia"]["t"], "{opacity: 0, x: 40}", 0.4))
    return css, html, "\n".join(js)


MODELOS = {"frase": frase, "numero": numero, "contraste": contraste, "radial": radial, "lista": lista,
           "fluxo": fluxo, "linha_do_tempo": linha_do_tempo, "mapa": mapa}

# o que o modelo de linguagem lê para escolher e preencher: o formato exato de "dados" de cada modelo
CATALOGO = """
- frase: a IDEIA da fala em 2 a 6 palavras-chave, como um título de capa. Nunca a narração inteira: a legenda do
  vídeo já mostra a fala, e repetir tudo fica redundante. Use para afirmação de impacto sem número nem estrutura.
  dados: {"rotulo": {"texto", "t"} (opcional, 1 a 3 palavras), "palavras": [{"texto", "t", "destaque": true/false}]}
  (cada palavra com o segundo em que é falada; 1 ou 2 com destaque)
- numero: um número grande que sobe até o valor, com o que ele mede.
  dados: {"rotulo": {"texto", "t"} (opcional), "numero": {"texto": "45" ou "1.200" ou "3,5", "t"}, "prefixo": "R$ " (opcional),
          "sufixo": "%" ou " mil" (opcional), "legenda": {"texto": "de volume alcoólico", "t"}, "medidor": 45 (opcional, só percentual)}
- contraste: dois lados frente a frente (artesanal × industrial, antes × depois, mito × fato).
  dados: {"esquerda": {"rotulo": "ARTESANAL", "titulo": {"texto", "t"}, "detalhe": {"texto", "t"} (opcional), "selo": {"texto", "t"} (opcional)},
          "direita": {mesmo formato}, "vencido": {"lado": "esquerda" ou "direita", "t"} (opcional: o lado que a narração nega)}
- radial: um centro com 3 a 6 elementos concretos ligados a ele, citados nesta fala ou nas frases anteriores (ex.:
  centro "Fogo de chão" e itens vinho, cachaça, carne, terra). O centro é o ASSUNTO de que a fala trata, nunca a
  metáfora (em "o fogo é o altar da fazenda", o centro é o fogo, não o altar). Itens diferentes entre si. Item que vem das frases anteriores
  entra junto com a palavra desta cena que fala do conjunto.
  dados: {"centro": {"texto", "t"}, "itens": [{"texto", "t"}], "legenda": [{"texto", "t", "destaque"}] (opcional, até 6 palavras)}
- lista: 2 a 5 itens que entram um a um.
  dados: {"titulo": {"texto", "t"} (opcional), "itens": [{"texto", "t"}]}
- fluxo: 2 a 5 etapas de um processo, ligadas por setas.
  dados: {"titulo": {"texto", "t"} (opcional), "etapas": [{"texto", "t"}]}
- linha_do_tempo: 2 a 4 marcos no tempo.
  dados: {"titulo": {"texto", "t"} (opcional), "marcos": [{"rotulo": "1875", "texto": "chegada dos imigrantes", "t"}]}
- mapa: um lugar com marcador, sem desenhar contornos. Use para lugares, distâncias e rotas.
  dados: {"lugar": {"nome", "detalhe" (opcional), "t"}, "referencias": [{"nome", "direcao": "norte|sul|leste|oeste|nordeste|noroeste|sudeste|sudoeste", "t"}] (opcional, até 3),
          "distancia": {"texto": "1.200 km", "t"} (opcional)}
"""


# ------------------------------------------------------------------------------------------------ conferência dos dados

def _texto(valor, limite):
    texto = re.sub(r"\s+", " ", str(valor or "")).strip()
    return texto if len(texto) <= limite else texto[:limite].rsplit(" ", 1)[0]


def _normal(texto) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", str(texto).lower()).encode("ascii", "ignore").decode()


def _inventadas(palavras, fala) -> list:
    """As palavras que não aparecem na fala (desta cena ou das vizinhas)."""
    ditas = set(re.findall(r"[a-z0-9]+", _normal(fala)))
    if not ditas:
        return []
    return [p["texto"] for p in palavras if any(w not in ditas for w in re.findall(r"[a-z0-9]+", _normal(p["texto"])))]


def conferir_dados(modelo, dados, dur, tempos, fala=""):
    """Arruma e confere os dados que o modelo de linguagem preencheu. Devolve (dados, erros).

    Cada tempo vai para o começo da palavra falada mais próxima (o modelo erra por décimos) e nunca passa do fim da
    cena; texto comprido é cortado. Falta de campo obrigatório vira erro, para o modelo preencher de novo."""
    erros = []
    fim = max(dur - 0.35, 0.1)

    def tempo(t):
        try:
            t = float(t)
        except (TypeError, ValueError):
            t = 0.0
        if tempos:
            perto = min(tempos, key=lambda x: abs(x - t))
            if abs(perto - t) <= 0.6:
                t = perto
        return round(max(0.0, min(t, fim)), 2)

    def item(x, limite, campo="texto"):
        if not isinstance(x, dict) or not str(x.get(campo) or "").strip():
            return None
        return {**x, campo: _texto(x[campo], limite), "t": tempo(x.get("t"))}

    if modelo not in MODELOS:
        return None, [f"o modelo {modelo!r} não existe; escolha um destes: {', '.join(MODELOS)}"]
    d = dict(dados or {})
    if modelo == "frase":
        palavras = [p for p in (item(p, 24) for p in (d.get("palavras") or [])[:10]) if p]
        if len(palavras) < 2:
            erros.append("frase precisa de 2 a 6 palavras, cada uma com texto e t")
        elif len(palavras) > 6:
            erros.append(f"frase veio com {len(palavras)} palavras: reduza para a ideia em 2 a 6 palavras-chave, "
                         "sem repetir a narração inteira (a legenda já mostra a fala)")
        if _inventadas(palavras, fala):
            erros.append("a frase usa palavras que não foram ditas (" + ", ".join(_inventadas(palavras, fala)[:4])
                         + "): use só palavras da narração")
        d = {"rotulo": item(d.get("rotulo"), 30), "palavras": [{**p, "destaque": bool(p.get("destaque"))} for p in palavras]}
    elif modelo == "numero":
        numero_ = item(d.get("numero"), 12)
        if not numero_ or _numero_valor(numero_["texto"]) is None:
            erros.append('numero precisa de {"texto": só o número, como "45" ou "1.200", "t"}')
        medidor = d.get("medidor")
        try:
            medidor = float(medidor) if medidor not in (None, "") else None
        except (TypeError, ValueError):
            medidor = None
        d = {"rotulo": item(d.get("rotulo"), 30), "numero": numero_, "prefixo": _texto(d.get("prefixo"), 4),
             "sufixo": _texto(d.get("sufixo"), 8), "legenda": item(d.get("legenda"), 40), "medidor": medidor}
    elif modelo == "contraste":
        novo = {}
        for lado in ("esquerda", "direita"):
            x = d.get(lado) or {}
            titulo = item(x.get("titulo"), 30)
            if not titulo:
                erros.append(f'contraste precisa de {lado}.titulo = {{"texto", "t"}}')
            novo[lado] = {"rotulo": _texto(x.get("rotulo"), 20), "titulo": titulo, "detalhe": item(x.get("detalhe"), 40),
                          "selo": item(x.get("selo"), 22)}
        vencido = d.get("vencido")
        if isinstance(vencido, dict) and vencido.get("lado") in ("esquerda", "direita"):
            novo["vencido"] = {"lado": vencido["lado"], "t": tempo(vencido.get("t"))}
        d = novo
    elif modelo == "radial":
        itens = [i for i in (item(i, 18) for i in (d.get("itens") or [])[:6]) if i]
        # tira o item que só repete outro ("estrutura" ao lado de "estrutura social")
        itens = [i for i in itens if not any(i is not j and i["texto"].lower() in j["texto"].lower() for j in itens)]
        centro = item(d.get("centro"), 24)
        if not centro or len(itens) < 3:
            erros.append('radial precisa de centro = {"texto", "t"} e de 3 a 6 itens concretos, citados nesta fala '
                         'ou nas frases anteriores')
        legenda = [p for p in (item(p, 16) for p in (d.get("legenda") or [])[:6]) if p]
        legenda = [p for p in legenda if not any(p is not q and p["texto"].lower() in q["texto"].lower() for q in legenda)]
        if _inventadas(legenda, fala):
            erros.append("a legenda usa palavras que não foram ditas (" + ", ".join(_inventadas(legenda, fala)[:4])
                         + "): use só palavras da narração, ou deixe a legenda vazia")
        d = {"centro": centro, "itens": itens, "legenda": [{**p, "destaque": bool(p.get("destaque"))} for p in legenda]}
    elif modelo == "lista":
        itens = [i for i in (item(i, 48) for i in (d.get("itens") or [])[:5]) if i]
        if len(itens) < 2:
            erros.append("lista precisa de 2 a 5 itens")
        d = {"titulo": item(d.get("titulo"), 40), "itens": itens}
    elif modelo == "fluxo":
        etapas = [e for e in (item(e, 30) for e in (d.get("etapas") or [])[:5]) if e]
        if len(etapas) < 2:
            erros.append("fluxo precisa de 2 a 5 etapas")
        d = {"titulo": item(d.get("titulo"), 40), "etapas": etapas}
    elif modelo == "linha_do_tempo":
        marcos = [m for m in (item(m, 12, "rotulo") for m in (d.get("marcos") or [])[:4]) if m]
        marcos = [{**m, "texto": _texto(m.get("texto"), 40)} for m in marcos]
        if len(marcos) < 2:
            erros.append("linha_do_tempo precisa de 2 a 4 marcos com rotulo e t")
        d = {"titulo": item(d.get("titulo"), 40), "marcos": marcos}
    elif modelo == "mapa":
        lugar = item(d.get("lugar"), 28, "nome")
        if not lugar:
            erros.append('mapa precisa de lugar = {"nome", "t"}')
        else:
            lugar["detalhe"] = _texto(lugar.get("detalhe"), 50)
        refs = [r for r in (item(r, 24, "nome") for r in (d.get("referencias") or [])[:3]) if r]
        d = {"lugar": lugar, "referencias": refs, "distancia": item(d.get("distancia"), 16)}
    return d, erros


def partes(modelo, dados, dur):
    """(css, html, js) do modelo já com os dados conferidos."""
    css, html, js = MODELOS[modelo](dados, dur)
    return {"css": CSS_BASE + css, "html": html, "js": js}
