"""Os modelos de demonstração do Motion IA (motion_ia.py): cada tipo de dado tem um desenho próprio.

Pedido do usuário em 2026-10-05: os clipes saíam todos iguais (a foto num card à esquerda e o número num card à
direita), porque o modelo escrevia o HTML livre e copiava o único exemplo do pedido. Agora a fábrica desenha a
demonstração que explica o dado (o velocímetro para a velocidade, a balança para o peso, a régua com o chifre para o
comprimento, os bonecos para a quantidade de pessoas...) e o modelo de linguagem só escolhe o modelo e preenche os
dados tirados da fala. A foto da cena é opcional (modelo foto_dado).

Cada modelo recebe os dados já conferidos e devolve as partes da página (css, html e js na linha do tempo `tl`), que
entram no esqueleto de motion_ia.montar_html: fundo creme com grade de pontos, as fontes, as cores (--verde, --azul,
--laranja, --grafite), as peças .m-card, .m-destaque e .m-num, a flutuação dos cards e window.seekToFrame. A tela útil
vai de 140 a 1780 px na largura e de 110 a 820 px na altura: os 260 px de baixo ficam para a legenda.
"""
import html as _html
import math
import re
import unicodedata

VERSAO = 2  # suba quando mudar o desenho de algum modelo

CINZA = "#E4E1D8"
TINTA = "#1A1A1A"
CORES = ("var(--laranja)", "var(--azul)", "var(--verde)", "#7C3AED")


def esc(texto) -> str:
    return _html.escape(str(texto or ""), quote=True)


def fmt(valor) -> str:
    """Número no jeito brasileiro: 1.000, 2,5."""
    if abs(valor - round(valor)) < 1e-9:
        return f"{int(round(valor)):,}".replace(",", ".")
    return f"{valor:.1f}".replace(".", ",")


def teto(valor) -> float:
    """O fim da escala: um número redondo um pouco acima do valor (50 vira 80, 1 vira 1,5)."""
    alvo = max(valor * 1.25, 1e-9)
    base = 10 ** math.floor(math.log10(alvo))
    for passo in (1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if passo * base >= alvo:
            return passo * base
    return 10 * base


def _tam(texto, faixas) -> int:
    n = len(str(texto or ""))
    for limite, px in faixas:
        if n <= limite:
            return px
    return faixas[-1][1]


def _tempos(dur):
    """O ritmo do clipe: tudo entra até `fim`, que deixa a última parte parada uns 0,5 s antes do corte."""
    fim = max(1.4, dur - 0.55)
    return lambda fracao: round(min(fracao * fim, fim), 3)


def _entra(seletor, t, de="{opacity: 0, y: 40, scale: 0.94}", para="{opacity: 1, y: 0, scale: 1}", dur=0.6,
           ease="back.out(1.7)", extra="") -> str:
    para = para[:-1] + f", duration: {dur}, ease: \"{ease}\"{extra}}}"
    return f'tl.fromTo("{seletor}", {de}, {para}, {t});'


def _conta(seletor, ate, t, dur=0.9, casas=0) -> str:
    """O número sobe do zero até o valor. O texto começa em 0 no HTML: a gravação vai do começo para o fim."""
    return (f'(function () {{ const el = document.querySelector("{seletor}"); const o = {{ v: 0 }};'
            f' tl.to(o, {{ v: {ate}, duration: {dur}, ease: "power3.out", onUpdate: function () {{'
            f' el.textContent = (Math.round(o.v * {10 ** casas}) / {10 ** casas}).toLocaleString("pt-BR"); }} }}, {t}); }})();')


def _topo(d) -> tuple:
    """A frase curta do topo, com a palavra de destaque em serifa colorida."""
    texto = (d.get("topo") or "").strip()
    if not texto:
        return "", ""
    destaque = (d.get("destaque") or "").strip().lower()
    partes = []
    for palavra in texto.split():
        limpa = re.sub(r"[^\w-]", "", palavra.lower())
        classe = ' class="m-p m-destaque"' if destaque and limpa == destaque else ' class="m-p"'
        partes.append(f"<span{classe}>{esc(palavra)}</span>")
    px = _tam(texto, [(26, 60), (40, 52), (99, 44)])
    css = (f"#m-topo {{ position: absolute; left: 140px; top: 110px; width: 1640px; font-size: {px}px; "
           f"font-weight: 600; color: {TINTA}; line-height: 1.15; }} #m-topo .m-p {{ display: inline-block; "
           f"margin-right: 0.24em; }}")
    return css, f'<div id="m-topo">{"".join(partes)}</div>'


def _js_topo(t) -> str:
    return _entra("#m-topo .m-p", t, de="{opacity: 0, y: 30}", para="{opacity: 1, y: 0}", dur=0.5,
                  extra=", stagger: 0.07")


def _valor_html(d, ident, px, contar) -> str:
    inicial = "0" if contar else esc(fmt(d["valor"]))
    return f'<span id="{ident}" style="font-size: {px}px">{inicial}</span>'


# ---------------------------------------------------------------------------------------------- os modelos

def velocimetro(d, dur, foto=None):
    """Velocidade: o ponteiro sobe até o valor num mostrador, e o número conta junto."""
    t = _tempos(dur)
    valor, maximo = d["valor"], teto(d["valor"])
    cx, cy, r = 960, 610, 270
    fracao = valor / maximo
    marcas, rotulos = [], []
    for i in range(6):
        ang = math.pi - math.pi * i / 5
        x1, y1 = cx + (r + 26) * math.cos(ang), cy - (r + 26) * math.sin(ang)
        x2, y2 = cx + (r + 50) * math.cos(ang), cy - (r + 50) * math.sin(ang)
        xl, yl = cx + (r + 92) * math.cos(ang), cy - (r + 92) * math.sin(ang)
        marcas.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{TINTA}" stroke-width="4" '
                      f'stroke-linecap="round"/>')
        rotulos.append(f'<text x="{xl:.1f}" y="{yl + 11:.1f}" text-anchor="middle" class="m-escala">'
                       f'{esc(fmt(maximo * i / 5))}</text>')
    arco = f"M {cx - r} {cy} A {r} {r} 0 0 1 {cx + r} {cy}"
    css_topo, html_topo = _topo(d)
    contar = valor >= 10
    css = css_topo + f"""
#m-svg {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: visible; }}
.m-escala {{ font-family: "Texto", sans-serif; font-size: 30px; font-weight: 500; fill: #6B6860; }}
#m-leitura {{ position: absolute; left: 460px; top: 640px; width: 1000px; text-align: center; color: {TINTA};
             font-weight: 800; line-height: 1; letter-spacing: -0.02em; }}
#m-leitura small {{ font-size: 48px; font-weight: 600; letter-spacing: 0; margin-left: 14px; }}
#m-leitura em {{ display: block; font-style: normal; font-size: 34px; font-weight: 500; color: #6B6860;
                letter-spacing: 0; margin-bottom: 6px; }}"""
    html = html_topo + f"""
<svg id="m-svg" viewBox="0 0 1920 1080">
  <path d="{arco}" fill="none" stroke="{CINZA}" stroke-width="40" stroke-linecap="round"/>
  <path id="m-arco" d="{arco}" fill="none" stroke="var(--laranja)" stroke-width="40" stroke-linecap="round"/>
  <g id="m-marcas">{"".join(marcas)}{"".join(rotulos)}</g>
  <line id="m-agulha" x1="{cx}" y1="{cy}" x2="{cx - r + 70}" y2="{cy}" stroke="{TINTA}" stroke-width="12"
        stroke-linecap="round"/>
  <circle cx="{cx}" cy="{cy}" r="24" fill="{TINTA}"/>
</svg>
<div id="m-leitura">{f'<em>{esc(d.get("prefixo"))}</em>' if d.get("prefixo") else ""}{_valor_html(d, "m-valor", 150, contar)}<small>{esc(d["unidade"])}</small></div>"""
    js = "\n".join([
        _js_topo(t(0.02)),
        _entra("#m-marcas", t(0.12), de="{opacity: 0, scale: 0.9}", para="{opacity: 1, scale: 1}",
               extra=', svgOrigin: "960 610"'),
        'const m_arco = document.querySelector("#m-arco"); const m_L = m_arco.getTotalLength();',
        'm_arco.style.strokeDasharray = m_L + " " + m_L; m_arco.style.strokeDashoffset = m_L;',
        f'tl.to("#m-arco", {{ strokeDashoffset: m_L * {1 - fracao:.4f}, duration: 1.1, ease: "power3.out" }}, {t(0.3)});',
        f'tl.fromTo("#m-agulha", {{ rotation: 0, svgOrigin: "{cx} {cy}" }}, {{ rotation: {180 * fracao:.2f}, '
        f'svgOrigin: "{cx} {cy}", duration: 1.1, ease: "back.out(1.4)" }}, {t(0.3)});',
        _entra("#m-leitura", t(0.36)),
        _conta("#m-valor", valor, t(0.36), 1.0) if contar else "",
    ])
    return {"css": css, "html": html, "js": js}


def balanca(d, dur, foto=None):
    """Peso: um peso de ferro cai na balança, a balança afunda e o card mostra o valor."""
    t = _tempos(dur)
    css_topo, html_topo = _topo(d)
    rotulo_peso = (d.get("abreviacao") or fmt(d["valor"])).strip()
    contar = d["valor"] >= 10
    css = css_topo + f"""
#m-svg {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: visible; }}
#m-peso-txt {{ font-family: "Texto", sans-serif; font-weight: 800; font-size: {_tam(rotulo_peso, [(4, 92), (7, 70), (99, 52)])}px;
              fill: #F7F6F2; }}
#m-dado {{ position: absolute; left: 1100px; top: 270px; width: 600px; height: 420px; }}
#m-dado em {{ font-style: normal; font-size: 40px; font-weight: 500; color: #6B6860; }}
#m-dado .m-num {{ font-size: 190px; }}
#m-dado .m-rot {{ font-size: 52px; }}"""
    html = html_topo + f"""
<svg id="m-svg" viewBox="0 0 1920 1080">
  <ellipse id="m-sombra" cx="620" cy="752" rx="300" ry="22" fill="rgba(26,26,26,0.10)"/>
  <g id="m-plataforma">
    <rect x="360" y="672" width="520" height="44" rx="14" fill="#2B2B2B"/>
    <rect x="410" y="716" width="40" height="34" rx="6" fill="#2B2B2B"/>
    <rect x="790" y="716" width="40" height="34" rx="6" fill="#2B2B2B"/>
  </g>
  <g id="m-peso" data-layout-allow-overflow>
    <path d="M 560 352 C 560 272, 680 272, 680 352" fill="none" stroke="#3A3A3A" stroke-width="30" stroke-linecap="round"/>
    <path d="M 490 360 L 750 360 L 820 672 L 420 672 Z" fill="#3A3A3A" stroke="#1A1A1A" stroke-width="6" stroke-linejoin="round"/>
    <text id="m-peso-txt" x="620" y="560" text-anchor="middle" data-layout-allow-overflow>{esc(rotulo_peso)}</text>
  </g>
  <g id="m-poeira" fill="#C9C4B6">
    <circle cx="380" cy="736" r="14"/><circle cx="340" cy="722" r="9"/><circle cx="860" cy="736" r="14"/><circle cx="900" cy="722" r="9"/>
  </g>
</svg>
<div id="m-dado" class="m-card">{f'<em>{esc(d.get("prefixo"))}</em>' if d.get("prefixo") else ""}<div class="m-num">{_valor_html(d, "m-valor", 190, contar)}</div><div class="m-rot">{esc(d["unidade"])}</div></div>"""
    queda = t(0.12)
    js = "\n".join([
        _js_topo(t(0.02)),
        _entra("#m-plataforma", t(0.04), de="{opacity: 0, y: 30}", para="{opacity: 1, y: 0}", dur=0.5),
        f'tl.fromTo("#m-peso", {{ y: -760 }}, {{ y: 0, duration: 0.7, ease: "bounce.out" }}, {queda});',
        f'tl.fromTo("#m-plataforma", {{ y: 0 }}, {{ y: 16, duration: 0.12, ease: "power2.out", yoyo: true, repeat: 1 }}, {queda + 0.32});',
        f'tl.fromTo("#m-sombra", {{ scaleX: 0.4, opacity: 0, svgOrigin: "620 752" }}, {{ scaleX: 1, opacity: 1, '
        f'svgOrigin: "620 752", duration: 0.5, ease: "power2.out" }}, {queda});',
        f'tl.fromTo("#m-poeira circle", {{ opacity: 0, scale: 0.2, transformOrigin: "50% 50%" }}, {{ opacity: 0.9, '
        f'scale: 1.3, duration: 0.35, ease: "power2.out", stagger: 0.03 }}, {queda + 0.32});',
        f'tl.to("#m-poeira circle", {{ opacity: 0, duration: 0.4, ease: "power1.in" }}, {queda + 0.7});',
        _entra("#m-dado", t(0.42)),
        _conta("#m-valor", d["valor"], t(0.42), 0.9) if contar else "",
    ])
    return {"css": css, "html": html, "js": js}


def _cone(x0, xv, y):
    """Um chifre (ou presa, dente, garra) deitado na régua: base larga à esquerda, afinando e curvando para cima."""
    w = xv - x0
    centro = lambda s: (x0 + w * s, y - 82 - 118 * s ** 2)
    meia = lambda s: 70 * (1 - s) ** 1.15 + 2
    cima, baixo = [], []
    for k in range(25):
        s = k / 24
        cx, cy = centro(s)
        dx, dy = w, -236 * s  # a direção da linha do meio, para afastar as bordas na perpendicular
        n = math.hypot(dx, dy) or 1
        nx, ny = -dy / n, dx / n
        cima.append((cx - nx * meia(s), cy - ny * meia(s)))
        baixo.append((cx + nx * meia(s), cy + ny * meia(s)))
    contorno = cima + baixo[::-1]
    caminho = "M " + " L ".join(f"{x:.1f} {yy:.1f}" for x, yy in contorno) + " Z"
    veio = "M " + " L ".join(f"{centro(k / 24)[0]:.1f} {centro(k / 24)[1] + 18 * (1 - k / 24):.1f}" for k in range(2, 22))
    return (f'<path d="{caminho}" fill="#CDBFA6" stroke="{TINTA}" stroke-width="4" stroke-linejoin="round"/>'
            f'<path d="{veio}" fill="none" stroke="#B3A386" stroke-width="5" stroke-linecap="round"/>')


def regua(d, dur, foto=None):
    """Comprimento: a coisa (uma barra, ou um chifre, presa ou dente) cresce ao longo de uma régua até a marca."""
    t = _tempos(dur)
    valor, maximo = d["valor"], teto(d["valor"])
    x0, largura, y = 240, 1440, 640
    xv = x0 + largura * valor / maximo
    marcas = []
    for i in range(21):
        x = x0 + largura * i / 20
        alto = 46 if i % 4 == 0 else 24
        marcas.append(f'<line x1="{x:.1f}" y1="{y}" x2="{x:.1f}" y2="{y + alto}" stroke="{TINTA}" stroke-width="3"/>')
        if i % 4 == 0:
            marcas.append(f'<text x="{x:.1f}" y="{y + 92}" text-anchor="middle" class="m-escala">{esc(fmt(maximo * i / 20))}</text>')
    if d.get("forma") == "cone":
        forma = _cone(x0, xv, y)
    else:
        forma = f'<rect x="{x0}" y="{y - 112}" width="{xv - x0:.1f}" height="96" rx="20" fill="var(--laranja)"/>'
    css_topo, html_topo = _topo(d)
    medida = f"{fmt(valor)} {d['unidade']}".strip()
    css = css_topo + f"""
#m-svg {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: visible; }}
.m-escala {{ font-family: "Texto", sans-serif; font-size: 30px; font-weight: 500; fill: #6B6860; }}
#m-medida {{ position: absolute; left: {x0}px; top: 268px; width: {xv - x0:.0f}px; min-width: 420px; text-align: center;
            color: {TINTA}; font-weight: 800; font-size: {_tam(medida, [(12, 84), (20, 68), (99, 52)])}px; line-height: 1; }}
#m-medida em {{ display: block; font-style: normal; font-size: 34px; font-weight: 500; color: #6B6860; margin-bottom: 6px; }}"""
    html = html_topo + f"""
<svg id="m-svg" viewBox="0 0 1920 1080">
  <defs><clipPath id="m-corte"><rect id="m-corte-r" x="{x0 - 10}" y="{y - 240}" width="0" height="250"/></clipPath></defs>
  <g id="m-regua"><rect x="{x0 - 30}" y="{y}" width="{largura + 60}" height="110" rx="12" fill="#F3DFA0"/>{"".join(marcas)}</g>
  <g clip-path="url(#m-corte)">{forma}</g>
  <g id="m-cota" stroke="{TINTA}" stroke-width="4" stroke-linecap="round">
    <line x1="{x0}" y1="{y - 196 - 30}" x2="{xv:.1f}" y2="{y - 196 - 30}"/>
    <line x1="{x0}" y1="{y - 196 - 46}" x2="{x0}" y2="{y - 196 - 14}"/>
    <line x1="{xv:.1f}" y1="{y - 196 - 46}" x2="{xv:.1f}" y2="{y - 196 - 14}"/>
  </g>
</svg>
<div id="m-medida">{f'<em>{esc(d.get("prefixo"))}</em>' if d.get("prefixo") else ""}{esc(medida)}</div>"""
    js = "\n".join([
        _js_topo(t(0.02)),
        _entra("#m-regua", t(0.08), de="{opacity: 0, y: 40}", para="{opacity: 1, y: 0}"),
        f'tl.to("#m-corte-r", {{ attr: {{ width: {xv - x0 + 20:.1f} }}, duration: 1.0, ease: "power3.out" }}, {t(0.25)});',
        f'tl.fromTo("#m-cota", {{ opacity: 0, scaleX: 0, svgOrigin: "{x0} {y - 226}" }}, {{ opacity: 1, scaleX: 1, '
        f'svgOrigin: "{x0} {y - 226}", duration: 0.8, ease: "power3.out" }}, {t(0.4)});',
        _entra("#m-medida", t(0.5)),
    ])
    return {"css": css, "html": html, "js": js}


def _icone(forma, x, y, s, cor):
    if forma == "pessoa":
        return (f'<g class="m-ic" fill="{cor}"><circle cx="{x + s / 2:.1f}" cy="{y + s * 0.2:.1f}" r="{s * 0.17:.1f}"/>'
                f'<path d="M {x + s * 0.2:.1f} {y + s * 0.95:.1f} L {x + s * 0.2:.1f} {y + s * 0.62:.1f} '
                f'Q {x + s * 0.2:.1f} {y + s * 0.42:.1f} {x + s / 2:.1f} {y + s * 0.42:.1f} '
                f'Q {x + s * 0.8:.1f} {y + s * 0.42:.1f} {x + s * 0.8:.1f} {y + s * 0.62:.1f} '
                f'L {x + s * 0.8:.1f} {y + s * 0.95:.1f} Z"/></g>')
    return f'<circle class="m-ic" cx="{x + s / 2:.1f}" cy="{y + s / 2:.1f}" r="{s * 0.34:.1f}" fill="{cor}"/>'


def contador(d, dur, foto=None):
    """Quantidade: um ícone por unidade (ou por grupo, se forem muitas) aparece em grade, e o número conta junto."""
    t = _tempos(dur)
    valor = int(round(d["valor"]))
    cada = 1
    if valor > 60:
        for passo in (2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 100000, 1000000):
            if math.ceil(valor / passo) <= 60:
                cada = passo
                break
    n = math.ceil(valor / cada)
    area_x, area_y, area_l, area_a = 760, 190, 1000, 600
    colunas = max(1, math.ceil(math.sqrt(n * area_l / area_a)))
    linhas = math.ceil(n / colunas)
    s = min(area_l / colunas, area_a / linhas, 120)
    x_ini = area_x + (area_l - colunas * s) / 2
    y_ini = area_y + (area_a - linhas * s) / 2
    forma = d.get("forma") if d.get("forma") in ("pessoa", "ponto") else "ponto"
    icones = "".join(_icone(forma, x_ini + (k % colunas) * s, y_ini + (k // colunas) * s, s * 0.9, TINTA)
                     for k in range(n))
    css_topo, html_topo = _topo(d)
    legenda = f"cada ícone = {fmt(cada)}" if cada > 1 else ""
    css = css_topo + f"""
#m-svg {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: visible; }}
#m-dado {{ position: absolute; left: 140px; top: 280px; width: 540px; height: 400px; }}
#m-dado em {{ font-style: normal; font-size: 38px; font-weight: 500; color: #6B6860; }}
#m-dado .m-num {{ font-size: {_tam(fmt(valor), [(3, 190), (5, 150), (99, 120)])}px; color: var(--laranja); }}
#m-legenda {{ position: absolute; left: {area_x}px; top: 795px; width: {area_l}px; text-align: center; font-size: 32px;
             font-weight: 500; color: #6B6860; }}"""
    html = html_topo + f"""
<svg id="m-svg" viewBox="0 0 1920 1080">{icones}</svg>
<div id="m-dado" class="m-card">{f'<em>{esc(d.get("prefixo"))}</em>' if d.get("prefixo") else ""}<div class="m-num"><span id="m-valor">0</span></div><div class="m-rot">{esc(d["unidade"])}</div></div>
{f'<div id="m-legenda">{esc(legenda)}</div>' if legenda else ""}"""
    espalha = round(min(1.2, max(0.4, t(0.55) - t(0.2))) / max(n, 1), 4)
    js = "\n".join([
        _js_topo(t(0.02)),
        _entra("#m-dado", t(0.08)),
        f'tl.fromTo(".m-ic", {{ opacity: 0, scale: 0.3, transformOrigin: "50% 50%" }}, {{ opacity: 1, scale: 1, '
        f'duration: 0.4, ease: "back.out(2)", stagger: {espalha} }}, {t(0.2)});',
        _conta("#m-valor", valor, t(0.2), max(0.6, espalha * n + 0.3)),
        _entra("#m-legenda", t(0.6), de="{opacity: 0, y: 20}", para="{opacity: 1, y: 0}") if legenda else "",
    ])
    return {"css": css, "html": html, "js": js}


def porcentagem(d, dur, foto=None):
    """Porcentagem: um anel enche até o valor, e a frase do que ela mede entra ao lado."""
    t = _tempos(dur)
    valor = min(max(d["valor"], 0), 100)
    cx, cy, r = 600, 470, 230
    css_topo, html_topo = _topo(d)
    texto = (d.get("unidade") or "").strip()
    css = css_topo + f"""
#m-svg {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: visible; }}
#m-pct {{ position: absolute; left: {cx - 230}px; top: {cy - 95}px; width: 460px; text-align: center; font-size: 170px;
         font-weight: 800; line-height: 1; color: {TINTA}; letter-spacing: -0.03em; }}
#m-pct small {{ font-size: 80px; }}
#m-texto {{ position: absolute; left: 960px; top: 330px; width: 780px; font-size: {_tam(texto, [(20, 76), (40, 60), (99, 48)])}px;
           font-weight: 600; line-height: 1.15; color: {TINTA}; }}"""
    html = html_topo + f"""
<svg id="m-svg" viewBox="0 0 1920 1080">
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{CINZA}" stroke-width="54"/>
  <circle id="m-anel" cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="var(--azul)" stroke-width="54" stroke-linecap="round"
          transform="rotate(-90 {cx} {cy})"/>
</svg>
<div id="m-pct"><span id="m-valor">0</span><small>%</small></div>
<div id="m-texto">{esc(texto)}</div>"""
    circ = 2 * math.pi * r
    js = "\n".join([
        _js_topo(t(0.02)),
        f'tl.set("#m-anel", {{ strokeDasharray: "{circ:.1f} {circ:.1f}", strokeDashoffset: {circ:.1f} }}, 0);',
        f'tl.to("#m-anel", {{ strokeDashoffset: {circ * (1 - valor / 100):.1f}, duration: 1.2, ease: "power3.out" }}, {t(0.15)});',
        _entra("#m-pct", t(0.12)),
        _conta("#m-valor", valor, t(0.15), 1.2, 0 if valor == int(valor) else 1),
        _entra("#m-texto", t(0.45)),
    ])
    return {"css": css, "html": html, "js": js}


def comparacao(d, dur, foto=None):
    """Comparação: uma barra por item, do tamanho do valor, crescendo uma depois da outra."""
    t = _tempos(dur)
    itens = d["itens"][:4]
    maior = max(i["valor"] for i in itens)
    altura = min(130, 560 / len(itens))
    y0 = 230 + (560 - altura * len(itens)) / 2
    css_topo, html_topo = _topo(d)
    linhas = []
    for k, item in enumerate(itens):
        y = y0 + k * altura
        largura = 900 * item["valor"] / maior
        linhas.append(f'<div class="m-lin" id="m-lin-{k}" style="top: {y:.0f}px; height: {altura * 0.7:.0f}px">'
                      f'<div class="m-rot-c">{esc(item["rotulo"])}</div>'
                      f'<div class="m-barra-c" style="width: {largura:.0f}px; background: {CORES[k % len(CORES)]}"></div>'
                      f'<div class="m-val-c">{esc(fmt(item["valor"]))} {esc(d.get("unidade") or "")}</div></div>')
    css = css_topo + f"""
.m-lin {{ position: absolute; left: 140px; width: 1640px; display: flex; align-items: center; gap: 28px; }}
.m-rot-c {{ width: 360px; text-align: right; font-size: {_tam(max((i["rotulo"] for i in itens), key=len), [(14, 44), (22, 36), (99, 32)])}px;
           font-weight: 600; color: {TINTA}; }}
.m-barra-c {{ height: 100%; border-radius: 16px; transform-origin: 0 50%; }}
.m-val-c {{ font-size: 44px; font-weight: 800; color: {TINTA}; white-space: nowrap; }}"""
    js = [_js_topo(t(0.02))]
    for k in range(len(itens)):
        inicio = t(0.12 + 0.12 * k)
        js.append(_entra(f"#m-lin-{k} .m-rot-c", inicio, de="{opacity: 0, x: -30}", para="{opacity: 1, x: 0}", dur=0.45))
        js.append(f'tl.fromTo("#m-lin-{k} .m-barra-c", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.8, ease: "back.out(1.4)" }}, {inicio + 0.1});')
        js.append(_entra(f"#m-lin-{k} .m-val-c", inicio + 0.45, de="{opacity: 0, x: -20}", para="{opacity: 1, x: 0}", dur=0.4))
    return {"css": css, "html": html_topo + "".join(linhas), "js": "\n".join(js)}


def _suave(pontos):
    """Caminho suave (Catmull-Rom em Bézier) pelos pontos."""
    caminho = f"M {pontos[0][0]:.1f} {pontos[0][1]:.1f}"
    for i in range(len(pontos) - 1):
        p0, p1, p2 = pontos[max(i - 1, 0)], pontos[i], pontos[i + 1]
        p3 = pontos[min(i + 2, len(pontos) - 1)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        caminho += f" C {c1[0]:.1f} {c1[1]:.1f}, {c2[0]:.1f} {c2[1]:.1f}, {p2[0]:.1f} {p2[1]:.1f}"
    return caminho


def tendencia(d, dur, foto=None):
    """Queda ou subida: a linha de um gráfico se desenha até o fim, onde um marcador pulsa com o que ela atinge."""
    t = _tempos(dur)
    desce = d.get("direcao") != "sobe"
    x0, x1, ytopo, ybase = 260, 1500, 250, 740
    forma = [(0, 0.08), (0.14, 0.16), (0.27, 0.12), (0.42, 0.34), (0.56, 0.42), (0.7, 0.66), (0.85, 0.82), (1, 0.93)]
    pontos = [(x0 + (x1 - x0) * fx, ytopo + (ybase - ytopo) * (fy if desce else 1 - fy)) for fx, fy in forma]
    linha = _suave(pontos)
    area = linha + f" L {x1} {ybase} L {x0} {ybase} Z"
    cor = "var(--laranja)" if desce else "var(--verde)"
    xf, yf = pontos[-1]
    css_topo, html_topo = _topo(d)
    fim, inicio = (d.get("fim") or "").strip(), (d.get("inicio") or "").strip()
    css = css_topo + f"""
#m-svg {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: visible; }}
#m-fim {{ position: absolute; left: {xf - 520:.0f}px; top: {yf - (150 if desce else -40):.0f}px; width: 760px; text-align: right;
         font-family: "Titulo", serif; font-style: italic; font-weight: 700; color: {cor};
         font-size: {_tam(fim, [(12, 72), (22, 56), (99, 44)])}px; line-height: 1.05; }}
#m-ini {{ position: absolute; left: {x0 + 30}px; top: {pontos[0][1] + (40 if desce else -100):.0f}px; width: 600px;
         font-size: 36px; font-weight: 600; color: #6B6860; }}"""
    html = html_topo + f"""
<svg id="m-svg" viewBox="0 0 1920 1080">
  <defs><linearGradient id="m-grad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{'#EA580C' if desce else '#166534'}" stop-opacity="0.22"/>
  <stop offset="1" stop-color="{'#EA580C' if desce else '#166534'}" stop-opacity="0"/></linearGradient></defs>
  <g id="m-eixos" stroke="{TINTA}" stroke-width="4" stroke-linecap="round">
    <line x1="{x0 - 30}" y1="{ytopo - 40}" x2="{x0 - 30}" y2="{ybase + 20}"/>
    <line x1="{x0 - 30}" y1="{ybase + 20}" x2="{x1 + 60}" y2="{ybase + 20}"/>
  </g>
  <path id="m-area" d="{area}" fill="url(#m-grad)"/>
  <path id="m-curva" d="{linha}" fill="none" stroke="{cor}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
  <circle id="m-onda" cx="{xf:.1f}" cy="{yf:.1f}" r="20" fill="none" stroke="{cor}" stroke-width="5"/>
  <circle id="m-ponto" cx="{xf:.1f}" cy="{yf:.1f}" r="20" fill="{cor}"/>
</svg>
{f'<div id="m-ini">{esc(inicio)}</div>' if inicio else ""}
{f'<div id="m-fim">{esc(fim)}</div>' if fim else ""}"""
    js = "\n".join([
        _js_topo(t(0.02)),
        _entra("#m-eixos", t(0.06), de="{opacity: 0}", para="{opacity: 1}", dur=0.4, ease="power2.out"),
        'const m_c = document.querySelector("#m-curva"); const m_L = m_c.getTotalLength();',
        'm_c.style.strokeDasharray = m_L + " " + m_L; m_c.style.strokeDashoffset = m_L;',
        _entra("#m-ini", t(0.1), de="{opacity: 0, y: 20}", para="{opacity: 1, y: 0}", dur=0.4) if inicio else "",
        f'tl.to("#m-curva", {{ strokeDashoffset: 0, duration: 1.3, ease: "power2.inOut" }}, {t(0.14)});',
        f'tl.fromTo("#m-area", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.8, ease: "power2.out" }}, {t(0.5)});',
        f'tl.fromTo("#m-ponto", {{ scale: 0, svgOrigin: "{xf:.1f} {yf:.1f}" }}, {{ scale: 1, svgOrigin: "{xf:.1f} {yf:.1f}", '
        f'duration: 0.5, ease: "back.out(3)" }}, {t(0.62)});',
        f'tl.fromTo("#m-onda", {{ scale: 1, opacity: 0.9, svgOrigin: "{xf:.1f} {yf:.1f}" }}, {{ scale: 3, opacity: 0, '
        f'svgOrigin: "{xf:.1f} {yf:.1f}", duration: 0.9, ease: "power2.out", repeat: 3 }}, {t(0.66)});',
        _entra("#m-fim", t(0.66)) if fim else "",
    ])
    return {"css": css, "html": html, "js": js}


def fluxo(d, dur, foto=None):
    """Causa e consequência, ou etapas: cards numerados ligados por setas, o último em destaque."""
    t = _tempos(dur)
    etapas = [e.strip() for e in d["etapas"] if e.strip()][:4]
    n = len(etapas)
    vao = 130
    largura = (1640 - vao * (n - 1)) / n
    y, altura = 330, 320
    css_topo, html_topo = _topo(d)
    cards, setas = [], []
    for k, etapa in enumerate(etapas):
        x = 140 + k * (largura + vao)
        ultimo = k == n - 1
        cards.append(f'<div class="m-card m-etapa{" m-ultima" if ultimo else ""}" id="m-etapa-{k}" '
                     f'style="left: {x:.0f}px; width: {largura:.0f}px"><div class="m-bola">{k + 1}</div>'
                     f'<div class="m-et-txt" style="font-size: {_tam(etapa, [(14, 50), (26, 42), (40, 36), (99, 32)])}px">'
                     f'{esc(etapa)}</div></div>')
        if not ultimo:
            xa, xb = x + largura + 16, x + largura + vao - 16
            setas.append(f'<path class="m-seta" id="m-seta-{k}" d="M {xa:.0f} {y + altura / 2} L {xb - 10:.0f} {y + altura / 2}" '
                         f'fill="none" stroke="{TINTA}" stroke-width="6" stroke-linecap="round"/>'
                         f'<path class="m-ponta" id="m-ponta-{k}" d="M {xb - 30:.0f} {y + altura / 2 - 20} L {xb:.0f} {y + altura / 2} '
                         f'L {xb - 30:.0f} {y + altura / 2 + 20}" fill="none" stroke="{TINTA}" stroke-width="6" '
                         f'stroke-linecap="round" stroke-linejoin="round"/>')
    css = css_topo + f"""
#m-svg {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: visible; }}
.m-etapa {{ position: absolute; top: {y}px; height: {altura}px; justify-content: flex-start; padding-top: 44px; }}
.m-ultima {{ box-shadow: 0 0 0 5px var(--laranja), 0 12px 32px rgba(0, 0, 0, 0.08); }}
.m-bola {{ width: 76px; height: 76px; border-radius: 50%; background: {TINTA}; color: #F7F6F2; font-size: 38px;
          font-weight: 800; display: flex; align-items: center; justify-content: center; margin-bottom: 18px; }}
.m-ultima .m-bola {{ background: var(--laranja); }}
.m-et-txt {{ font-weight: 600; line-height: 1.15; color: {TINTA}; }}"""
    html = html_topo + f'<svg id="m-svg" viewBox="0 0 1920 1080">{"".join(setas)}</svg>' + "".join(cards)
    passo = 0.6 / max(n, 1)
    js = [_js_topo(t(0.02))]
    for k in range(n):
        js.append(_entra(f"#m-etapa-{k}", t(0.1 + passo * k)))
        if k < n - 1:
            js.append(f'tl.fromTo("#m-seta-{k}", {{ opacity: 0, scaleX: 0, transformOrigin: "0% 50%" }}, '
                      f'{{ opacity: 1, scaleX: 1, duration: 0.35, ease: "power3.out" }}, {t(0.1 + passo * k) + 0.25});')
            js.append(_entra(f"#m-ponta-{k}", t(0.1 + passo * k) + 0.45, de="{opacity: 0, x: -14}",
                             para="{opacity: 1, x: 0}", dur=0.3))
    return {"css": css, "html": html, "js": "\n".join(js)}


ORDINAIS = {1: "º", 2: "º"}


def ranking(d, dur, foto=None):
    """Posição num ranking: a posição em número grande e a lista de posições, com a dele acesa."""
    t = _tempos(dur)
    total, posicao = int(d["total"]), int(d["posicao"])
    nome = (d.get("nome") or "").strip()
    altura = min(76, 600 / total)
    y0 = 190 + (620 - altura * total) / 2
    css_topo, html_topo = _topo(d)
    linhas = []
    for k in range(1, total + 1):
        y = y0 + (k - 1) * altura
        largura = 820 - (k - 1) * (360 / max(total - 1, 1))
        aceso = k == posicao
        linhas.append(f'<div class="m-pos{" m-aceso" if aceso else ""}" id="m-pos-{k}" style="top: {y:.0f}px; '
                      f'height: {altura * 0.78:.0f}px"><span class="m-pos-n">{k}º</span><span class="m-pos-b" '
                      f'style="width: {largura:.0f}px">{esc(nome) if aceso and nome else ""}</span></div>')
    css = css_topo + f"""
#m-grande {{ position: absolute; left: 140px; top: 190px; width: 600px; height: 380px; text-align: center;
            font-family: "Titulo", serif; font-weight: 800; font-size: 300px; line-height: 1.2; color: var(--laranja); }}
#m-lugar {{ position: absolute; left: 140px; top: 620px; width: 600px; text-align: center; font-size: 54px; font-weight: 600;
           color: {TINTA}; }}
.m-pos {{ position: absolute; left: 820px; width: 960px; display: flex; align-items: center; gap: 22px; }}
.m-pos-n {{ width: 76px; text-align: right; font-size: {min(40, altura * 0.5):.0f}px; font-weight: 700; color: #8A867C; }}
.m-pos-b {{ height: 100%; border-radius: 14px; background: {CINZA}; transform-origin: 0 50%; display: flex;
           align-items: center; padding-left: 26px; font-size: {min(40, altura * 0.46):.0f}px; font-weight: 700; color: #FFFFFF;
           white-space: nowrap; overflow: hidden; }}
.m-aceso .m-pos-n {{ color: var(--laranja); }}
.m-aceso .m-pos-b {{ background: var(--laranja); }}"""
    html = html_topo + f'<div id="m-grande">{posicao}º</div><div id="m-lugar">lugar</div>' + "".join(linhas)
    js = [_js_topo(t(0.02)),
          f'tl.fromTo(".m-pos .m-pos-b", {{ scaleX: 0 }}, {{ scaleX: 1, duration: 0.6, ease: "power3.out", stagger: 0.05 }}, {t(0.08)});',
          f'tl.fromTo(".m-pos .m-pos-n", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.3, ease: "power2.out", stagger: 0.05 }}, {t(0.08)});',
          _entra("#m-grande", t(0.32), de="{opacity: 0, scale: 0.6}", para="{opacity: 1, scale: 1}", dur=0.7,
                 ease="back.out(2)"),
          _entra("#m-lugar", t(0.42), de="{opacity: 0, y: 24}", para="{opacity: 1, y: 0}", dur=0.45),
          f'tl.fromTo("#m-pos-{posicao}", {{ x: 0 }}, {{ x: 30, duration: 0.5, ease: "back.out(2)" }}, {t(0.45)});']
    return {"css": css, "html": html, "js": "\n".join(js)}


def frase(d, dur, foto=None):
    """Ideia ou conclusão: a frase grande, palavra por palavra, com a palavra-chave em serifa e um traço que a sublinha."""
    t = _tempos(dur)
    texto = d["frase"].strip()
    destaque = (d.get("destaque") or "").strip().lower()
    px = _tam(texto, [(24, 104), (45, 88), (70, 74), (999, 62)])
    palavras = []
    for palavra in texto.split():
        limpa = re.sub(r"[^\w-]", "", palavra.lower())
        if destaque and limpa == destaque:
            palavras.append(f'<span class="m-p m-chave"><span class="m-destaque">{esc(palavra)}</span>'
                            f'<svg class="m-sublinha" viewBox="0 0 200 24" preserveAspectRatio="none"><path id="m-traco" '
                            f'd="M 4 16 C 50 6, 120 6, 196 14" fill="none" stroke="var(--laranja)" stroke-width="7" '
                            f'stroke-linecap="round"/></svg></span>')
        else:
            palavras.append(f'<span class="m-p">{esc(palavra)}</span>')
    css = f"""
#m-bolhas {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; }}
#m-frase {{ position: absolute; left: 200px; top: 200px; width: 1520px; height: 560px; display: flex; flex-wrap: wrap;
           align-content: center; justify-content: center; text-align: center; font-size: {px}px; font-weight: 700;
           line-height: 1.18; color: {TINTA}; }}
#m-frase .m-p {{ display: inline-block; margin: 0 0.16em; }}
.m-chave {{ position: relative; }}
.m-sublinha {{ position: absolute; left: 0; bottom: -0.12em; width: 100%; height: 0.26em; overflow: visible; }}"""
    html = f"""
<svg id="m-bolhas" viewBox="0 0 1920 1080">
  <circle id="m-b1" cx="330" cy="260" r="150" fill="var(--azul)" fill-opacity="0.07"/>
  <circle id="m-b2" cx="1620" cy="700" r="210" fill="var(--laranja)" fill-opacity="0.07"/>
</svg>
<div id="m-frase">{"".join(palavras)}</div>"""
    js = "\n".join([
        _entra("#m-b1, #m-b2", t(0.0), de="{opacity: 0, scale: 0.6, transformOrigin: \"50% 50%\"}",
               para="{opacity: 1, scale: 1}", dur=0.9, ease="power3.out"),
        _entra("#m-frase .m-p", t(0.06), de="{opacity: 0, y: 46}", para="{opacity: 1, y: 0}", dur=0.55,
               extra=", stagger: 0.08"),
        'const m_t = document.querySelector("#m-traco");',
        'if (m_t) { const L = m_t.getTotalLength(); m_t.style.strokeDasharray = L + " " + L; m_t.style.strokeDashoffset = L; }',
        f'if (m_t) tl.to("#m-traco", {{ strokeDashoffset: 0, duration: 0.6, ease: "power3.out" }}, {t(0.55)});',
        f'tl.to("#m-b1", {{ x: 40, y: 20, duration: {max(dur, 1):.2f}, ease: "sine.inOut" }}, 0);',
        f'tl.to("#m-b2", {{ x: -30, y: -24, duration: {max(dur, 1):.2f}, ease: "sine.inOut" }}, 0);',
    ])
    return {"css": css, "html": html, "js": js}


# Desenhos de narração, sem número e sem foto (perfil todo em motion, 2026-10-08): o vídeo de economia da Serra Gaúcha
# tinha 96 cenas e quase nenhum dado. Sem eles, tudo virava `frase`, que esgotava, e sobrava o HTML livre, reprovado.
def topicos(d, dur, foto=None):
    """Dois a quatro pontos da fala, em linhas que entram da esquerda uma a uma, cada uma com a cor e o número dela."""
    t = _tempos(dur)
    pontos = [e.strip() for e in d["etapas"] if e.strip()][:4]
    n = len(pontos)
    altura = 150 if n >= 4 else 170
    vao = 28
    total = n * altura + (n - 1) * vao
    topo = 120 if d.get("topo") else 0
    y0 = 140 + topo + max(0, (640 - topo - total) // 2)
    css_topo, html_topo = _topo(d)
    linhas = []
    for k, ponto in enumerate(pontos):
        px = _tam(ponto, [(22, 58), (36, 50), (56, 42), (99, 36)])
        linhas.append(f'<div class="m-card m-ponto" id="m-ponto-{k}" style="top: {y0 + k * (altura + vao)}px; '
                      f'height: {altura}px; --cor: {CORES[k % len(CORES)]}"><div class="m-bola">{k + 1}</div>'
                      f'<div class="m-pt-txt" style="font-size: {px}px">{esc(ponto)}</div></div>')
    css = css_topo + f"""
.m-ponto {{ position: absolute; left: 260px; width: 1400px; flex-direction: row; justify-content: flex-start;
           gap: 36px; padding: 0 44px 0 0; text-align: left; overflow: hidden; border-left: 18px solid var(--cor); }}
.m-ponto .m-bola {{ flex: none; width: 84px; height: 84px; margin-left: 30px; border-radius: 50%; background: var(--cor);
                   color: #FFFFFF; font-size: 44px; font-weight: 800; display: flex; align-items: center;
                   justify-content: center; }}
.m-pt-txt {{ font-weight: 700; line-height: 1.12; color: {TINTA}; }}"""
    js = [_js_topo(t(0.02))] if d.get("topo") else []
    passo = 0.7 / max(n, 1)
    for k in range(n):
        js.append(_entra(f"#m-ponto-{k}", t(0.08 + passo * k), de="{opacity: 0, x: -140}", para="{opacity: 1, x: 0}",
                         dur=0.6))
    return {"css": css, "html": html_topo + "".join(linhas), "js": "\n".join(js)}


def contraste(d, dur, foto=None):
    """Dois lados lado a lado ("a soja" contra "a Serra"): dois cards com a cor e o rótulo de cada um e um × no meio."""
    t = _tempos(dur)
    lados = (d.get("itens") or [])[:2]
    css_topo, html_topo = _topo(d)
    cards = []
    for k, lado in enumerate(lados):
        px = _tam(lado.get("texto") or "", [(18, 62), (34, 52), (60, 44), (99, 38)])
        cards.append(f'<div class="m-card m-lado" id="m-lado-{k}" style="left: {160 + k * 880}px; '
                     f'--cor: {CORES[k]}"><div class="m-lado-rot">{esc(lado.get("rotulo"))}</div>'
                     f'<div class="m-lado-txt" style="font-size: {px}px">{esc(lado.get("texto"))}</div></div>')
    css = css_topo + f"""
.m-lado {{ position: absolute; top: 250px; width: 720px; height: 460px; border-top: 16px solid var(--cor); gap: 26px; }}
.m-lado-rot {{ font-size: 40px; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase; color: var(--cor); }}
.m-lado-txt {{ font-weight: 700; line-height: 1.14; color: {TINTA}; }}
#m-vs {{ position: absolute; left: 860px; top: 420px; width: 200px; height: 120px; display: flex; align-items: center;
        justify-content: center; font-family: "Titulo", Georgia, serif; font-style: italic; font-weight: 700;
        font-size: 120px; color: {TINTA}; }}"""
    html = html_topo + "".join(cards) + '<div id="m-vs">×</div>'
    js = [_js_topo(t(0.02))] if d.get("topo") else []
    js += [_entra("#m-lado-0", t(0.1), de="{opacity: 0, x: -160}", para="{opacity: 1, x: 0}", dur=0.7),
           _entra("#m-lado-1", t(0.4), de="{opacity: 0, x: 160}", para="{opacity: 1, x: 0}", dur=0.7),
           _entra("#m-vs", t(0.3), de="{opacity: 0, scale: 0.2, rotation: -40}",
                  para="{opacity: 1, scale: 1, rotation: 0}", dur=0.6)]
    return {"css": css, "html": html, "js": "\n".join(js)}


def marco(d, dur, foto=None):
    """Um marco no tempo ("1875", "2012"): o ano grande em serifa à esquerda, a linha que se desenha e o fato ao lado."""
    t = _tempos(dur)
    texto = (d.get("texto") or "").strip()
    ano = (d.get("marco") or "").strip()
    px_ano = _tam(ano, [(4, 250), (8, 170), (99, 120)])
    px = _tam(texto, [(30, 76), (60, 64), (90, 56), (999, 48)])
    css = f"""
#m-ano {{ position: absolute; left: 120px; top: 270px; width: 760px; height: 380px; display: flex; align-items: center;
         justify-content: center; font-family: "Titulo", Georgia, serif; font-style: italic; font-weight: 800;
         font-size: {px_ano}px; color: var(--laranja); line-height: 1; text-align: center; }}
#m-eixo {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: visible; }}
.m-linha-1 {{ stroke: {TINTA}; stroke-width: 7; }}
#m-fato {{ position: absolute; left: 1010px; top: 250px; width: 780px; height: 420px; align-items: flex-start;
          text-align: left; padding: 40px 54px; }}
#m-fato .m-frase {{ font-size: {px}px; font-weight: 700; text-align: left; }}"""
    html = (f'<svg id="m-eixo" viewBox="0 0 1920 1080"><path class="m-linha m-linha-1" d="M 900 460 L 990 460"/>'
            f'<circle id="m-ponto" cx="900" cy="460" r="16" fill="var(--laranja)"/></svg>'
            f'<div id="m-ano">{esc(ano)}</div>'
            f'<div class="m-card" id="m-fato"><div class="m-frase">{esc(texto)}</div></div>')
    js = [_entra("#m-ano", t(0.02), de="{opacity: 0, scale: 0.7}", para="{opacity: 1, scale: 1}", dur=0.8),
          _entra("#m-ponto", t(0.3), de='{opacity: 0, scale: 0, transformOrigin: "50% 50%"}',
                 para="{opacity: 1, scale: 1}", dur=0.4),
          f'tl.to(".m-linha-1", {{ strokeDashoffset: 0, duration: 0.5, ease: "power3.out" }}, {t(0.35)});',
          _entra("#m-fato", t(0.45), de="{opacity: 0, x: 90}", para="{opacity: 1, x: 0}", dur=0.7)]
    return {"css": css, "html": html, "js": "\n".join(js)}


def foto_dado(d, dur, foto=None):
    """A foto da cena num card, ligada por uma curva ao dado (o desenho de antes, agora só uma das opções)."""
    t = _tempos(dur)
    css_topo, html_topo = _topo(d)
    tem_valor = d.get("valor") is not None
    principal = fmt(d["valor"]) if tem_valor else (d.get("frase") or "")
    css = css_topo + f"""
#m-f {{ position: absolute; left: 160px; top: 230px; width: 760px; height: 500px; }}
#m-d {{ position: absolute; left: 1060px; top: 270px; width: 680px; height: 420px; }}
#m-l {{ position: absolute; left: 920px; top: 330px; width: 140px; height: 200px; overflow: visible; }}
#m-d em {{ font-style: normal; font-size: 38px; font-weight: 500; color: #6B6860; }}
#m-d .m-frase {{ font-size: {_tam(principal, [(20, 64), (40, 52), (99, 42)])}px; }}"""
    if tem_valor:
        miolo = (f'{f"<em>{esc(d.get("prefixo"))}</em>" if d.get("prefixo") else ""}<div class="m-num">{esc(principal)}</div>'
                 f'<div class="m-rot">{esc(d.get("unidade") or "")}</div>')
    else:
        miolo = f'<div class="m-frase">{esc(principal)}</div>'
    html = html_topo + f"""
<div id="m-f" class="m-card m-foto"></div>
<svg id="m-l" viewBox="0 0 140 200"><path class="m-linha" id="m-linha-1" d="M 0 100 C 50 30, 90 30, 140 100"
     stroke="var(--laranja)" stroke-width="5"/></svg>
<div id="m-d" class="m-card">{miolo}</div>"""
    js = "\n".join([
        _js_topo(t(0.02)),
        _entra("#m-f", t(0.05)),
        f'tl.to("#m-linha-1", {{ strokeDashoffset: 0, duration: 0.6, ease: "power3.out" }}, {t(0.3)});',
        _entra("#m-d", t(0.38)),
        _entra("#m-d > *", t(0.48), de="{opacity: 0, y: 26}", para="{opacity: 1, y: 0}", dur=0.45, extra=", stagger: 0.12"),
    ])
    return {"css": css, "html": html, "js": js}


# o papel recortado da tipografia: a borda rasgada é fixa (o vídeo sai igual sempre), em porcentagem da caixa
_RASGO_CIMA = (0, 2.2, 0.6, 3.1, 1.2, 0.3, 2.6, 1.0, 3.4, 0.8, 1.9, 0.2, 2.8, 1.4, 0.5, 2.4, 3.2, 0.9, 1.7, 0.4, 2.1)
_RASGO_BAIXO = (99.2, 97.1, 98.6, 96.8, 99.5, 97.9, 96.6, 98.9, 97.4, 99.7, 96.9, 98.3, 97.6, 99.1, 96.7, 98.5,
                97.2, 99.4, 97.8, 96.5, 98.8)
TONS = ("leve", "pesado", "neutro")

# o grão de papel por cima do fundo creme: o filtro é fixo (seed), o vídeo sai igual sempre
_TEXTURA_CSS = "#m-textura { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; opacity: 0.08; }"
_TEXTURA_HTML = """
<svg id="m-textura" viewBox="0 0 1920 1080"><filter id="m-grao"><feTurbulence type="fractalNoise" baseFrequency="0.85"
  numOctaves="2" seed="7"/><feColorMatrix type="saturate" values="0"/></filter>
  <rect width="1920" height="1080" filter="url(#m-grao)"/></svg>"""


def _papel_rasgado() -> str:
    passo = 100 / (len(_RASGO_CIMA) - 1)
    cima = [f"{i * passo:.1f}% {y}%" for i, y in enumerate(_RASGO_CIMA)]
    baixo = [f"{100 - i * passo:.1f}% {y}%" for i, y in enumerate(_RASGO_BAIXO)]
    return "polygon(" + ", ".join(cima + baixo) + ")"


def tipografia(d, dur, foto=None):
    """Tipografia cinética editorial: o dado escrito grande em serifa, letra por letra, num recorte de papel sobre uma
    textura de papel. O movimento diz o tom que a direção de arte escolheu: "leve" pousa e flutua (o meio quilo de um
    mico-leão), "pesado" despenca e assenta, "neutro" entra com a mola. Nenhum objeto desenhado: é para o dado que um
    desenho literal estragaria (a balança com o peso de ferro para um bicho de meio quilo, PRD Motion AI 2.0)."""
    t = _tempos(dur)
    tom = d.get("tom") if d.get("tom") in TONS else "neutro"
    texto = d["texto"].strip()
    css_topo, html_topo = _topo(d)
    px = _tam(texto, [(8, 230), (12, 190), (18, 150), (26, 112), (999, 92)])
    destaque = (d.get("destaque") or "").strip().lower()
    palavras = []
    for palavra in texto.split():
        limpa = re.sub(r"[^\w-]", "", palavra.lower())
        cor = ' style="color: var(--laranja)"' if destaque and limpa == destaque else ""
        letras = "".join(f'<span class="m-l">{esc(letra)}</span>' for letra in palavra)
        palavras.append(f'<span class="m-pal"{cor}>{letras}</span>')
    prefixo = (d.get("prefixo") or "").strip()
    css = css_topo + f"""
{_TEXTURA_CSS}
#m-centro {{ position: absolute; left: 140px; top: {200 if html_topo else 140}px; width: 1640px;
            height: {620 if html_topo else 680}px; display: flex; flex-direction: column; align-items: center;
            justify-content: center; gap: 28px; }}
#m-prefixo {{ font-size: 44px; font-weight: 600; letter-spacing: 0.22em; text-transform: uppercase; color: #6B6860; }}
#m-sombra {{ filter: drop-shadow(0 14px 22px rgba(60, 50, 30, 0.14)); }}
#m-papel {{ background: #FFFDF7; clip-path: {_papel_rasgado()}; padding: 56px 96px 92px; max-width: 1640px;
           text-align: center; }}
#m-valor {{ position: relative; display: inline-block; font-family: "Titulo", Georgia, serif; font-style: italic;
           font-weight: 700; font-size: {px}px; line-height: 1.05; color: {TINTA}; }}
#m-valor .m-pal {{ display: inline-block; white-space: nowrap; margin: 0 0.12em; }}
#m-valor .m-l {{ display: inline-block; }}
#m-sub {{ position: absolute; left: 4%; bottom: -0.34em; width: 92%; height: 0.2em; overflow: visible; }}"""
    html = html_topo + _TEXTURA_HTML + f"""
<div id="m-centro">
  {f'<div id="m-prefixo">{esc(prefixo)}</div>' if prefixo else ""}
  <div id="m-sombra"><div id="m-papel"><span id="m-valor">{"".join(palavras)}<svg id="m-sub" viewBox="0 0 400 24"
    preserveAspectRatio="none"><path id="m-traco" d="M 4 15 C 90 5, 260 5, 396 13" fill="none" stroke="var(--laranja)"
    stroke-width="6" stroke-linecap="round"/></svg></span></div></div>
</div>"""
    js = [_js_topo(t(0.0)) if html_topo else "",
          'const m_t = document.querySelector("#m-traco");',
          'if (m_t) { const L = m_t.getTotalLength(); m_t.style.strokeDasharray = L + " " + L; m_t.style.strokeDashoffset = L; }']
    if prefixo:
        js.append(_entra("#m-prefixo", t(0.04), de="{opacity: 0, y: 20}", para="{opacity: 1, y: 0}", dur=0.6,
                         ease="power2.out"))
    letras = max(1, len(texto.replace(" ", "")))
    if tom == "leve":
        # pousa como uma folha: o papel desce girando pouco, as letras sobem devagar e o conjunto segue flutuando
        js += [_entra("#m-papel", t(0.08), de="{opacity: 0, y: -50, rotation: 5}",
                      para="{opacity: 1, y: 0, rotation: -1.5}", dur=1.1, ease="power2.out"),
               _entra("#m-valor .m-l", t(0.2), de="{opacity: 0, y: 34}", para="{opacity: 1, y: 0}", dur=0.8,
                      ease="power2.out", extra=f", stagger: {min(0.05, 0.6 / letras):.3f}"),
               f'tl.to("#m-sombra", {{ y: -16, duration: {max(dur - t(0.1), 0.5):.2f}, ease: "sine.inOut" }}, {t(0.1)});']
    elif tom == "pesado":
        # despenca e assenta: cada letra cai (de dentro do papel, que recorta o que sai dele), o papel dá um tranco
        js += [_entra("#m-papel", t(0.06), de="{opacity: 0, scale: 1.08, rotation: 0}",
                      para="{opacity: 1, scale: 1, rotation: -1.5}", dur=0.45, ease="power3.out"),
               _entra("#m-valor .m-l", t(0.16), de="{opacity: 0, y: -44}", para="{opacity: 1, y: 0}", dur=0.4,
                      ease="power4.in", extra=f", stagger: {min(0.05, 0.5 / letras):.3f}"),
               f'tl.fromTo("#m-sombra", {{ y: 0 }}, {{ y: 8, duration: 0.12, ease: "power2.out", yoyo: true, '
               f'repeat: 1 }}, {t(0.62)});']
    else:
        js += [_entra("#m-papel", t(0.06), de="{opacity: 0, y: 40, scale: 0.94, rotation: 2}",
                      para="{opacity: 1, y: 0, scale: 1, rotation: -1.5}", dur=0.7),
               _entra("#m-valor .m-l", t(0.18), de="{opacity: 0, y: 40}", para="{opacity: 1, y: 0}", dur=0.55,
                      extra=f", stagger: {min(0.04, 0.5 / letras):.3f}")]
    js.append(f'if (m_t) tl.to("#m-traco", {{ strokeDashoffset: 0, duration: 0.7, ease: "power3.out" }}, {t(0.7)});')
    return {"css": css, "html": html, "js": "\n".join(x for x in js if x)}


LEME_SVG = (f'<svg viewBox="0 0 120 150" width="92" height="115" style="overflow:visible">'
            f'<path d="M10 22 H110" stroke="var(--azul)" stroke-width="6" stroke-linecap="round" stroke-dasharray="14 10"/>'
            f'<path d="M60 0 V44" stroke="{TINTA}" stroke-width="9" stroke-linecap="round"/>'
            f'<path d="M44 44 H96 Q108 44 108 56 V118 Q108 142 84 142 H62 Q44 142 44 124 Z" fill="var(--laranja)" '
            f'stroke="{TINTA}" stroke-width="6" stroke-linejoin="round"/></svg>')
ICONES = {"leme": LEME_SVG}  # a função dita na fala que tem desenho próprio ("funciona como leme")


def _passo(maximo) -> float:
    """O intervalo das marcas grandes da fita: um número redondo que dá de 3 a 6 marcas até o fim."""
    for passo in (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if maximo / passo <= 6:
            return passo
    return 1000


def _abreviacao(unidade) -> str:
    u = _normal(unidade)
    for chave, abrev in (("centimetro", "cm"), ("milimetro", "mm"), ("quilometro", "km"), ("metro", "m"),
                         ("cm", "cm"), ("mm", "mm"), ("km", "km"), ("m", "m")):
        if u.startswith(chave):
            return abrev
    return unidade[:4]


def medida_colagem(d, dur, foto=None):
    """Comprimento ou altura com o próprio bicho, no caderno de campo: o animal recortado como figurinha (a foto
    própria dos bancos, motion_figura), uma fita métrica amarela desenrola da ponta da cauda ao focinho até o valor
    dito, o "quase / 2 metros" no alto; na parte citada ("a cauda achatada") o resto do corpo apaga, a parte fica em
    destaque com um círculo à mão, uma seta e a anotação; na função ("funciona como leme") a parte balança e entra o
    ícone. É o clipe 1 dos 5 da ariranha (cena 191 do 11-animais-do-brasil), o que o usuário escolheu em 2026-10-08.

    Dados além dos do modelo: fig (largura, altura da figurinha em px), ext (onde o bicho começa e termina na largura
    dela, de 0 a 1), parte_caixa (a caixa da parte na figurinha) e tempos (o segundo de "valor", "parte" e "funcao"
    na fala, achados pela palavra; sem eles, frações do clipe)."""
    t = _tempos(dur)
    tempos = d.get("tempos") or {}
    t_valor = tempos.get("valor", t(0.12))
    t_parte = tempos.get("parte", t(0.5))
    t_funcao = tempos.get("funcao", t(0.72))
    t_quase = max(0.05, t_valor - 0.3)
    largura_f, altura_f = d.get("fig") or (1026, 396)
    ext0, ext1 = d.get("ext") or (0.03, 0.97)
    proporcao = largura_f / altura_f
    FW = min(1180.0, 420 * proporcao)
    FH = FW / proporcao
    X, Y = 960 - FW / 2, 660 - FH
    ponta, nariz = X + ext0 * FW, X + ext1 * FW
    valor = d["valor"]
    quase = bool(re.search(r"quase|cerca|perto|aproximadamente", d.get("prefixo") or "", re.I))
    comprimento = valor * (0.955 if quase else 1.0)
    por_un = (nariz - ponta) / comprimento
    maximo = valor * 1.06
    passo = _passo(maximo)
    abrev = _abreviacao(d.get("unidade") or "m")
    largura_fita = maximo * por_un
    marcas, rotulos, k = [], [], 0
    menor = passo / 5
    while k * menor <= maximo + 1e-9:
        x = k * menor * por_un
        grande = k % 5 == 0
        marcas.append(f'<line x1="{x:.1f}" y1="0" x2="{x:.1f}" y2="{34 if grande else 18}" stroke="{TINTA}" '
                      f'stroke-width="{4 if grande else 2.5}"/>')
        if grande:
            numero = k * menor
            texto = "0" if k == 0 else (f"{fmt(numero)} {abrev}" if numero + passo > maximo + 1e-9 else fmt(numero))
            rotulos.append(f'<text x="{x + 6:.1f}" y="68" font-size="34" font-weight="700" fill="{TINTA}" '
                           f'font-family="Texto">{esc(texto)}</text>')
        k += 1
    css = f"""
{_TEXTURA_CSS}
#m-sombra {{ position:absolute; left:0; top:0; width:1920px; height:1080px; filter: drop-shadow(0 18px 22px rgba(60,40,20,.25)); }}
#m-corpo, #m-parte {{ position:absolute; left:{X:.0f}px; top:{Y:.0f}px; width:{FW:.0f}px; height:{FH:.0f}px;
  background:url("assets/{foto}") center/100% 100% no-repeat; }}
#m-caixa {{ position:absolute; left:{ponta - 84:.0f}px; top:{Y + FH + 8:.0f}px; width:96px; height:96px; border-radius:22px; background:{TINTA}; }}
#m-caixa i {{ position:absolute; left:30px; top:30px; width:36px; height:36px; border-radius:50%; background:var(--laranja); }}
#m-janela {{ position:absolute; left:{ponta:.0f}px; top:{Y + FH + 18:.0f}px; width:0px; height:76px; overflow:hidden; }}
#m-fita {{ position:absolute; left:0; top:0; width:{largura_fita:.0f}px; height:76px; background:#F2C230;
  border-top:3px solid {TINTA}; border-bottom:3px solid {TINTA}; }}
#m-leitura {{ position:absolute; left:{max(140, min(X + FW * 0.45 - 350, 1080)):.0f}px; top:{max(96, Y - 150):.0f}px; width:700px; text-align:center; }}
#m-leitura em {{ display:block; font-style:normal; font-size:40px; font-weight:600; letter-spacing:.22em; color:#6B6860; margin-bottom:14px; }}
#m-leitura b {{ display:inline-block; font-family:"Titulo"; font-style:italic; font-weight:700; font-size:{_tam(fmt(valor) + d.get('unidade', ''), [(10, 104), (16, 92), (99, 80)])}px; color:{TINTA}; line-height:1.05; }}
#m-traco {{ position:absolute; left:0; top:0; width:1920px; height:1080px; overflow:visible; }}"""
    prefixo = f"<em>{esc(d['prefixo'])}</em>" if d.get("prefixo") else ""
    leitura = f'<div id="m-leitura">{prefixo}<b>{esc(fmt(valor))} {esc(d.get("unidade") or "")}</b></div>'
    html = _TEXTURA_HTML + f"""
<div id="m-sombra"><div id="m-corpo"></div><div id="m-parte"></div></div>
<div id="m-caixa"><i></i></div>
<div id="m-janela"><svg id="m-fita" viewBox="0 0 {largura_fita:.0f} 76">{"".join(marcas)}{"".join(rotulos)}</svg></div>
{leitura}"""
    if d.get("valor2"):
        # o segundo dado da mesma frase ("e pesar mais de cem quilos"), embaixo da fita, sem outra balança
        segundo = " ".join(x for x in (d.get("prefixo2") or "", fmt(d["valor2"]), d.get("unidade2") or "") if x)
        css += f"""
#m-segundo {{ position:absolute; left:340px; top:{Y + FH + 104:.0f}px; width:1240px; text-align:center;
  font-family:"Titulo"; font-style:italic; font-weight:700; font-size:54px; color:var(--laranja); }}"""
        html += f'\n<div id="m-segundo">{esc(segundo)}</div>'
        t_valor2 = tempos.get("valor2", t(0.6))
    js = [_entra("#m-corpo, #m-parte", 0.0, de="{x: 160, opacity: 0, rotation: 3}", para="{x: 0, opacity: 1, rotation: -1}",
                 dur=0.7),
          'tl.set("#m-parte", {opacity: 0}, 0);',
          _entra("#m-caixa", min(0.25, t_quase), de="{scale: 0, opacity: 0}", para="{scale: 1, opacity: 1}", dur=0.45),
          f'tl.to("#m-janela", {{width: {nariz - ponta + 0.04 * comprimento * por_un:.0f}, duration: 1.0, '
          f'ease: "power2.out"}}, {t_quase:.2f});']
    if d.get("prefixo"):
        js.append(_entra("#m-leitura em", t_quase, de="{y: 20, opacity: 0}", para="{y: 0, opacity: 1}", dur=0.45))
    js.append(_entra("#m-leitura b", t_valor, de="{y: 40, scale: 0.85, opacity: 0}", para="{y: 0, scale: 1, opacity: 1}",
                     dur=0.55))
    if d.get("valor2"):
        js.append(_entra("#m-segundo", t_valor2, de="{y: 24, opacity: 0}", para="{y: 0, opacity: 1}", dur=0.5))
    caixa = d.get("parte_caixa")
    if d.get("parte") and caixa:
        px0, py0, px1, py1 = (X + caixa[0] * FW, Y + caixa[1] * FH, X + caixa[2] * FW, Y + caixa[3] * FH)
        cx, cy, rx, ry = (px0 + px1) / 2, (py0 + py1) / 2, max(90.0, (px1 - px0) * 0.62), max(60.0, (py1 - py0) * 0.62)
        my = (cy - Y) / FH * 100
        mascara = (f"radial-gradient(ellipse {rx * 1.15:.0f}px {ry * 1.25:.0f}px at {cx - X:.0f}px {cy - Y:.0f}px, "
                   f"#000 62%, transparent 100%)")
        # o eixo do balanço: o lado da parte que encosta no corpo
        eixo_x = px1 if cx < X + FW / 2 else px0
        esquerda = cx < 960
        rot_x = 130 if esquerda else 1780 - 620
        rot_y = max(250, min(py0 - 200, 470))
        css += f"""
#m-parte {{ -webkit-mask-image:{mascara}; mask-image:{mascara}; transform-origin:{(eixo_x - X) / FW * 100:.1f}% {my:.1f}%; }}
#m-rotulo {{ position:absolute; left:{rot_x}px; top:{rot_y:.0f}px; width:620px; text-align:{'left' if esquerda else 'right'}; }}
#m-rotulo b {{ display:block; font-family:"Titulo"; font-style:italic; font-size:{_tam(d['parte'], [(16, 64), (24, 54), (99, 46)])}px; color:var(--laranja); line-height:1.1; }}
#m-rotulo span {{ display:inline-block; font-size:48px; font-weight:700; color:{TINTA}; margin-top:6px; }}
#m-icone {{ position:absolute; left:{rot_x if esquerda else rot_x + 528}px; top:{rot_y + 160:.0f}px; }}"""
        seta_ini = (rot_x + 170, rot_y + 140) if esquerda else (rot_x + 450, rot_y + 140)
        alvo = (cx - rx * 0.55 if esquerda else cx + rx * 0.55, cy - ry * 0.6)
        html += f"""
<svg id="m-traco" viewBox="0 0 1920 1080">
  <path class="m-linha" id="m-circ" d="M {cx - rx:.0f} {cy - 10:.0f} C {cx - rx * 0.92:.0f} {cy - ry * 1.2:.0f}, {cx + rx * 0.92:.0f} {cy - ry * 1.25:.0f}, {cx + rx * 1.03:.0f} {cy - 5:.0f}
   S {cx - rx * 0.32:.0f} {cy + ry * 1.25:.0f}, {cx - rx * 0.95:.0f} {cy + ry * 0.25:.0f}" stroke="var(--laranja)" stroke-width="7"/>
  <path class="m-linha" id="m-seta" d="M {seta_ini[0]:.0f} {seta_ini[1]:.0f} C {seta_ini[0] + 20:.0f} {seta_ini[1] + 60:.0f}, {alvo[0] - 40:.0f} {alvo[1] - 40:.0f}, {alvo[0]:.0f} {alvo[1]:.0f}"
   stroke="{TINTA}" stroke-width="4"/>
</svg>
<div id="m-rotulo"><b>{esc(d['parte'])}</b>{f'<span id="m-func">{esc(d["funcao"])}</span>' if d.get("funcao") else ""}</div>"""
        icone = next((svg for chave, svg in ICONES.items() if chave in _normal(d.get("funcao") or "")), "")
        if icone:
            html += f'\n<div id="m-icone">{icone}</div>'
        js += [f'tl.to("#m-corpo", {{opacity: 0.4, duration: 0.4, ease: "power2.out"}}, {t_parte - 0.1:.2f});',
               f'tl.set("#m-parte", {{opacity: 1}}, {t_parte - 0.1:.2f});',
               f'tl.to("#m-circ", {{strokeDashoffset: 0, duration: 0.55, ease: "power3.out"}}, {t_parte:.2f});',
               _entra("#m-rotulo b", t_parte + 0.1, de="{y: 24, opacity: 0}", para="{y: 0, opacity: 1}", dur=0.5),
               f'tl.to("#m-seta", {{strokeDashoffset: 0, duration: 0.4, ease: "power3.out"}}, {t_parte + 0.35:.2f});']
        if d.get("funcao"):
            inicio_funcao = max(t_parte + 0.6, t_funcao - 0.6)
            js += ['tl.set("#m-func", {opacity: 0}, 0);',
                   _entra("#m-func", inicio_funcao, de="{y: 20, opacity: 0}", para="{y: 0, opacity: 1}", dur=0.45),
                   f'tl.fromTo("#m-parte", {{rotation: 0}}, {{rotation: {8 if esquerda else -8}, duration: 0.22, '
                   f'ease: "sine.inOut", yoyo: true, repeat: 5}}, {t_funcao - 0.1:.2f});']
            if icone:
                js += [_entra("#m-icone", t_funcao, de="{scale: 0, rotation: -30, opacity: 0, transformOrigin: '50% 0%'}",
                              para="{scale: 1, rotation: 0, opacity: 1}", dur=0.55),
                       f'tl.fromTo("#m-icone", {{rotation: 0}}, {{rotation: -14, duration: 0.22, ease: "sine.inOut", '
                       f'yoyo: true, repeat: 3, transformOrigin: "50% 0%"}}, {t_funcao + 0.5:.2f});']
    return {"css": css, "html": html, "js": "\n".join(js)}


def _grade(total, largura, altura, proporcao):
    """(colunas, linhas, largura e altura da célula) para `total` silhuetas de proporção largura/altura caberem."""
    colunas = max(1, math.ceil(math.sqrt(total * largura / (altura * proporcao))))
    while True:
        celula_l = largura / colunas
        celula_a = celula_l / proporcao
        linhas = math.ceil(total / colunas)
        if linhas * celula_a <= altura or colunas > total:
            return colunas, linhas, celula_l, min(celula_a, altura / max(linhas, 1))
        colunas += 1


def contagem_colagem(d, dur, foto=None):
    """Quantidade de bichos, no caderno de campo: o próprio animal em cor à esquerda (a figura própria dos bancos) e,
    ao lado, ele mesmo em miniatura repetido numa grade, um por unidade, enchendo no tempo do número falado, enquanto o
    número conta. Acima de 200, cada silhueta vale mais de um, e a legenda diz quanto. "Restavam apenas cerca de
    duzentos micos" (11-animais-do-brasil, 2026-10-08) virava bolinhas genéricas no contador.

    Dados além dos do modelo: fig (largura, altura da figurinha), moldura (sem recorte: a foto inteira numa moldura e
    pontos na grade), tempos ("valor": o segundo do número na fala) e rotulo_valor (o número como foi dito, quando não é exato:
    "milhares")."""
    t = _tempos(dur)
    tempos = d.get("tempos") or {}
    t_valor = tempos.get("valor", t(0.2))
    largura_f, altura_f = d.get("fig") or (1026, 396)
    proporcao = largura_f / altura_f
    valor = d["valor"]
    unidade = d.get("unidade") or ""
    proporcao_icone = 1.0 if d.get("moldura") else proporcao
    # no máximo uns 50 bichos na grade, para cada silhueta ser legível no celular; acima disso cada uma vale um número
    # redondo (na cena 21 do 11-animais-do-brasil, 200 silhuetas de mico viraram borrões, "parecem cachorros")
    cada = next(c for c in (1, 2, 4, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000, 10000, 1e9)
                if valor / c <= 40)
    icones = max(2, math.ceil(valor / cada))
    # o protagonista: o animal em cor, à esquerda
    PH = min(520.0, 620 / proporcao)
    PW = PH * proporcao
    PX, PY = 130 + (620 - PW) / 2, 250 + (520 - PH) / 2
    GX, GY, GW, GH = 800, 280, 980, 470
    colunas, linhas, cl, ca = _grade(icones, GW, GH, proporcao_icone)
    celulas = []
    for k in range(icones):
        x = GX + (k % colunas) * cl + (GW - colunas * cl) / 2
        y = GY + (k // colunas) * ca + (GH - linhas * ca) / 2
        celulas.append(f'<i class="m-ic" style="left:{x:.1f}px;top:{y:.1f}px"></i>')
    if d.get("moldura"):
        # sem recorte limpo: a foto inteira numa moldura de papel rasgado, e as unidades são pontos
        figura_css = (f'background:url("assets/{foto}") center/cover no-repeat; border:14px solid #FFFDF7; '
                      f'clip-path:{_papel_rasgado()};')
        lado = min(cl, ca) * 0.7
        icone_css = f"width:{lado:.1f}px; height:{lado:.1f}px; border-radius:50%; background:var(--laranja);"
    else:
        figura_css = f'background:url("assets/{foto}") center/100% 100% no-repeat;'
        # o próprio bicho em miniatura, colorido: a silhueta preta do mico sentado virou borrão ("parece cachorro")
        icone_css = f'background:url("assets/{foto}") center/contain no-repeat;'
    prefixo = (d.get("prefixo") or "").strip()
    numero = d.get("rotulo_valor") or ""
    contar = not numero
    numero_html = f'<span id="m-num">{"0" if contar else esc(numero)}</span>'
    legenda = f"cada um = {fmt(cada)} {unidade}".strip() if cada > 1 else ""
    css = f"""
{_TEXTURA_CSS}
#m-sombra {{ position:absolute; left:0; top:0; width:1920px; height:1080px; filter: drop-shadow(0 18px 22px rgba(60,40,20,.25)); }}
#m-bicho {{ position:absolute; left:{PX:.0f}px; top:{PY:.0f}px; width:{PW:.0f}px; height:{PH:.0f}px;
  {figura_css} }}
.m-ic {{ position:absolute; width:{cl * 0.86:.1f}px; height:{ca * 0.86:.1f}px; display:block; {icone_css} }}
#m-leitura {{ position:absolute; left:{GX}px; top:96px; width:{GW}px; text-align:center; }}
#m-leitura em {{ display:block; font-style:normal; font-size:40px; font-weight:600; letter-spacing:.22em; color:#6B6860;
  margin-bottom:10px; text-transform:uppercase; }}
#m-leitura b {{ font-family:"Titulo"; font-style:italic; font-weight:700; font-size:110px; color:{TINTA}; line-height:1.0; }}
#m-leitura b span {{ color:var(--laranja); }}
#m-legenda {{ position:absolute; left:{GX}px; top:{GY + GH + 8}px; width:{GW}px; text-align:right; font-size:40px;
  font-weight:600; color:#6B6860; }}"""
    html = _TEXTURA_HTML + f"""
<div id="m-sombra"><div id="m-bicho"></div></div>
<div id="m-grade">{"".join(celulas)}</div>
<div id="m-leitura">{f"<em>{esc(prefixo)}</em>" if prefixo else ""}<b>{numero_html} {esc(unidade)}</b></div>
{f'<div id="m-legenda">{esc(legenda)}</div>' if legenda else ""}"""
    duracao_grade = min(1.4, max(0.6, dur - t_valor - 0.8))
    js = [_entra("#m-bicho", 0.0, de="{x: -120, opacity: 0, rotation: -3}", para="{x: 0, opacity: 1, rotation: -1}", dur=0.7)]
    if prefixo:
        js.append(_entra("#m-leitura em", max(0.1, t_valor - 0.35), de="{y: 20, opacity: 0}", para="{y: 0, opacity: 1}",
                         dur=0.45))
    js += [_entra("#m-leitura b", t_valor, de="{y: 40, scale: 0.85, opacity: 0}", para="{y: 0, scale: 1, opacity: 1}",
                  dur=0.55),
           f'tl.fromTo(".m-ic", {{scale: 0, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.35, ease: "back.out(2)", '
           f'stagger: {{each: {duracao_grade / max(icones, 1):.4f}, from: "start"}}}}, {t_valor:.2f});']
    if contar:
        js.append(_conta("#m-num", valor, t_valor, duracao_grade + 0.3))
    if legenda:
        js.append(_entra("#m-legenda", t_valor + duracao_grade, de="{opacity: 0, y: 12}", para="{opacity: 1, y: 0}",
                         dur=0.4, ease="power2.out"))
    return {"css": css, "html": html, "js": "\n".join(js)}


ICONES_FICHA = {
    # pequenos desenhos de traço, no tom de caderno de campo, um por tipo de dado
    "comprimento": '<path d="M6 38 H74" /><path d="M6 30 V46 M74 30 V46 M24 34 V42 M40 32 V44 M56 34 V42" />',
    "altura": '<path d="M40 6 V74" /><path d="M32 6 H48 M32 74 H48 M36 24 H44 M34 40 H46 M36 56 H44" />',
    "peso": '<path d="M14 64 Q40 20 66 64 Z" /><path d="M40 64 V48" /><circle cx="40" cy="46" r="4" />',
    "velocidade": '<path d="M10 58 A32 32 0 0 1 70 58" /><path d="M40 58 L58 34" /><circle cx="40" cy="58" r="4" />',
    "tempo": '<circle cx="40" cy="42" r="28" /><path d="M40 42 V24 M40 42 L54 50" />',
    "quantidade": '<circle cx="22" cy="28" r="7" /><circle cx="44" cy="28" r="7" /><circle cx="33" cy="50" r="7" />'
                  '<circle cx="58" cy="50" r="7" />',
}


def _tipo_do_dado(unidade) -> str:
    u = _normal(unidade)
    for padrao, tipo in ((r"metro|\bm\b|cm|mm|pes|polegada", "comprimento"), (r"quilo|kg|tonelada|grama|\bt\b", "peso"),
                         (r"por hora|km/h|/h|por segundo", "velocidade"),
                         (r"ano|mes|dia|hora|minuto|segundo|seculo", "tempo")):
        if re.search(padrao, u):
            return tipo
    return "quantidade"


def ficha_colagem(d, dur, foto=None):
    """Dois ou três dados do mesmo bicho numa ficha de caderno de campo: a foto dele à esquerda (recortada, ou na
    moldura de papel rasgado) e, à direita, uma linha por dado com um ícone de traço e o número contando, cada uma no
    segundo em que é falada. "Pode passar de dois metros e meio e pesar mais de cem quilos" (o pirarucu, cena 257 do
    11-animais-do-brasil, 2026-10-08) virava a terceira balança do vídeo, ou a régua sem o peso.

    Dados: itens [{valor, unidade, prefixo, palavra}], fig (largura, altura da figura), moldura e tempos {"item0",
    "item1"...}."""
    t = _tempos(dur)
    tempos = d.get("tempos") or {}
    itens = d["itens"][:3]
    largura_f, altura_f = d.get("fig") or (4, 3)
    proporcao = largura_f / altura_f
    deitado = proporcao > 2.2  # bicho comprido (o pirarucu): a figura em cima, larga, e os dados lado a lado embaixo
    if deitado:
        FW = min(1500.0, 360 * proporcao)
        FH = FW / proporcao
        FX, FY = 960 - FW / 2, 120
    else:
        FW = min(900.0, 560 * proporcao)
        FH = FW / proporcao
        FX, FY = 130 + (900 - FW) / 2, 150 + (580 - FH) / 2
    if d.get("moldura"):
        figura_css = (f'background:url("assets/{foto}") center/cover no-repeat; border:14px solid #FFFDF7; '
                      f'clip-path:{_papel_rasgado()};')
    else:
        figura_css = f'background:url("assets/{foto}") center/100% 100% no-repeat;'
    LX, LW = 1090, 700
    altura_linha = 230 if len(itens) <= 2 else 170
    topo = 150 + (580 - altura_linha * len(itens)) / 2
    coluna = 1640 / max(len(itens), 1)
    linhas, js = [], [_entra("#m-figura", 0.0, de="{x: -140, opacity: 0, rotation: -3}",
                             para="{x: 0, opacity: 1, rotation: -1.5}", dur=0.7)]
    for k, item in enumerate(itens):
        y = topo + k * altura_linha
        posicao = (f"left:{140 + k * coluna:.0f}px; top:{FY + FH + 40:.0f}px; width:{coluna - 20:.0f}px; "
                   f"justify-content:center" if deitado else f"top:{y:.0f}px")
        tipo = _tipo_do_dado(item.get("unidade") or "")
        casas = 0 if abs(item["valor"] - round(item["valor"])) < 1e-9 else 1
        prefixo = (item.get("prefixo") or "").strip()
        linhas.append(f"""
<div class="m-linha-f" id="m-l{k}" style="{posicao}">
  <svg class="m-icone-f" viewBox="0 0 80 80">{ICONES_FICHA[tipo]}</svg>
  <div class="m-texto-f">{f'<em>{esc(prefixo)}</em>' if prefixo else ''}<b><span id="m-n{k}">0</span> {esc(item.get("unidade") or "")}</b></div>
</div>""")
        # o número tem de terminar de contar antes do corte: o "cem" do pirarucu é dito no fim da cena, e o último
        # quadro mostrava "82 quilos"
        quando = min(tempos.get(f"item{k}", t(0.15 + 0.3 * k)), max(0.1, dur - 1.0))
        contagem = max(0.3, min(0.8, dur - quando - 0.35))
        js += [_entra(f"#m-l{k}", quando, de="{x: 40, opacity: 0}", para="{x: 0, opacity: 1}", dur=0.45),
               f'tl.fromTo("#m-l{k} .m-icone-f", {{rotation: -25, scale: 0.6}}, {{rotation: 0, scale: 1, duration: 0.45, '
               f'ease: "back.out(2)"}}, {quando:.2f});',
               _conta(f"#m-n{k}", item["valor"], quando + 0.05, contagem, casas)]
        if k < len(itens) - 1 and not deitado:
            js.append(_entra(f"#m-r{k}", quando + 0.3, de="{scaleX: 0, transformOrigin: '0% 50%'}", para="{scaleX: 1}",
                             dur=0.5, ease="power3.out"))
            linhas.append(f'<i class="m-regra" id="m-r{k}" style="top:{y + altura_linha - 12:.0f}px"></i>')
    css = f"""
{_TEXTURA_CSS}
#m-sombra {{ position:absolute; left:0; top:0; width:1920px; height:1080px; filter: drop-shadow(0 18px 22px rgba(60,40,20,.25)); }}
#m-figura {{ position:absolute; left:{FX:.0f}px; top:{FY:.0f}px; width:{FW:.0f}px; height:{FH:.0f}px; {figura_css} }}
.m-linha-f {{ position:absolute; left:{LX}px; width:{LW}px; height:{altura_linha - 24}px; display:flex; align-items:center; gap:30px; }}
.m-icone-f {{ width:120px; height:120px; flex:none; fill:none; stroke:var(--laranja); stroke-width:7; stroke-linecap:round;
  stroke-linejoin:round; overflow:visible; }}
.m-texto-f em {{ display:block; font-style:normal; font-size:44px; font-weight:700; letter-spacing:.16em; color:#6B6860;
  text-transform:uppercase; }}
.m-texto-f b {{ font-family:"Titulo"; font-style:italic; font-weight:700; font-size:{118 if len(itens) <= 2 else 92}px;
  color:{TINTA}; line-height:1.05; white-space:nowrap; }}
.m-regra {{ position:absolute; left:{LX}px; width:{LW}px; height:3px; display:block; background:#D9D4C7; }}"""
    html = _TEXTURA_HTML + f"""
<div id="m-sombra"><div id="m-figura"></div></div>
{"".join(linhas)}"""
    return {"css": css, "html": html, "js": "\n".join(js)}


def colagem_balanca(d, dur, foto=None):
    """Peso com a foto do animal, em colagem estilo Vox: o próprio bicho recortado (figurinha de borda branca) pousa
    numa balança de cozinha, o prato afunda, o ponteiro gira até o valor e uma etiqueta presa por um fio mostra o
    número contando. Pedido do usuário em 2026-10-07 ("ele em cima de uma balança mostrando 0,5 kg"). foto: o
    recorte aprovado (recorte.png) ou, com dados["moldura"], a foto inteira numa moldura de papel rasgado. O tom muda
    a chegada: "leve" pousa devagar, "pesado" despenca e o prato afunda fundo, "neutro" entra com a mola."""
    tom = d.get("tom") if d.get("tom") in TONS else "neutro"
    valor = d["valor"]
    css_topo, html_topo = _topo(d)
    cx, cy = 760, 704
    angulo = round(-135 + 270 * min(valor / teto(valor), 1.0), 1)
    marcas = []
    for i in range(11):
        a = math.radians(-135 + 27 * i)
        r1 = 50 if i % 5 == 0 else 56
        marcas.append(f'<line x1="{cx + r1 * math.sin(a):.1f}" y1="{cy - r1 * math.cos(a):.1f}" '
                      f'x2="{cx + 64 * math.sin(a):.1f}" y2="{cy - 64 * math.cos(a):.1f}" stroke="{TINTA}" '
                      f'stroke-width="{5 if i % 5 == 0 else 3}" stroke-linecap="round"/>')
    topo_bicho = 210 if html_topo else 130
    if d.get("moldura"):
        figura = (f"width: 470px; height: 340px; background: url(\"assets/{foto}\") center / cover no-repeat; "
                  f"border: 14px solid #FFFDF7; clip-path: {_papel_rasgado()};")
    else:
        figura = f"width: 100%; height: 100%; background: url(\"assets/{foto}\") center bottom / contain no-repeat;"
    casas = 0 if abs(valor - round(valor)) < 1e-9 else 1
    prefixo = (d.get("prefixo") or "").strip()
    css = css_topo + f"""
{_TEXTURA_CSS}
#m-balanca {{ position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: visible; }}
#m-bicho-caixa {{ position: absolute; left: 440px; top: {topo_bicho}px; width: 640px; height: {558 - topo_bicho}px;
                 display: flex; align-items: flex-end; justify-content: center; }}
#m-bicho {{ {figura} filter: drop-shadow(0 16px 18px rgba(40, 30, 20, 0.22)); }}
#m-dado {{ position: absolute; left: 1190px; top: 300px; width: 500px; height: 360px; }}
#m-dado em {{ font-style: normal; font-size: 40px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase;
             color: #6B6860; }}
#m-dado .m-num {{ font-size: {_tam(fmt(valor), [(3, 190), (5, 160), (99, 130)])}px; }}
#m-dado .m-rot {{ font-size: 56px; }}
#m-fio-linha {{ stroke: {TINTA}; stroke-width: 3; }}"""
    html = html_topo + _TEXTURA_HTML + f"""
<svg id="m-balanca" viewBox="0 0 1920 1080">
  <ellipse id="m-chao" cx="{cx}" cy="812" rx="270" ry="18" fill="rgba(26,26,26,0.10)"/>
  <path class="m-linha" id="m-fio-linha" d="M 1190 480 C 1110 480, 1070 700, 992 706"/>
  <g id="m-corpo">
    <path d="M 590 606 L 930 606 Q 948 606 952 624 L 990 784 Q 994 802 976 802 L 544 802 Q 526 802 530 784 L 568 624
             Q 572 606 590 606 Z" fill="var(--laranja)" stroke="{TINTA}" stroke-width="6" stroke-linejoin="round"/>
    <circle cx="{cx}" cy="{cy}" r="74" fill="#FFFDF7" stroke="{TINTA}" stroke-width="6"/>
    {"".join(marcas)}
    <g id="m-ponteiro"><line x1="{cx}" y1="{cy + 10}" x2="{cx}" y2="{cy - 58}" stroke="var(--azul)" stroke-width="6"
       stroke-linecap="round"/></g>
    <circle cx="{cx}" cy="{cy}" r="10" fill="{TINTA}"/>
  </g>
  <g id="m-bandeja">
    <rect x="742" y="576" width="36" height="32" fill="{TINTA}"/>
    <rect x="500" y="554" width="520" height="26" rx="13" fill="#2B2B2B"/>
  </g>
</svg>
<div id="m-bicho-caixa"><div id="m-bicho"></div></div>
<div id="m-dado" class="m-card">{f"<em>{esc(prefixo)}</em>" if prefixo else ""}<div class="m-num"><span id="m-valor">0</span></div><div class="m-rot">{esc(d["unidade"])}</div></div>"""
    k = min(1.0, max(0.55, (dur - 0.6) / 2.6))  # cena curta: tudo mais depressa, nada fica para depois do corte
    inicio = round(0.15 * k, 3)
    if tom == "leve":
        queda = ('{opacity: 0, y: -170, rotation: 6}', '{opacity: 1, y: 0, rotation: -3', 0.95, "power2.out", 0.8)
        afunda, mola = 6, "back.out(1.4)"
    elif tom == "pesado":
        queda = ('{opacity: 0, y: -560, rotation: 0}', '{opacity: 1, y: 0, rotation: -2', 0.75, "bounce.out", 0.27)
        afunda, mola = 18, "back.out(2.6)"
    else:
        queda = ('{opacity: 0, y: -220, rotation: 4}', '{opacity: 1, y: 0, rotation: -3', 0.7, "back.out(1.7)", 0.5)
        afunda, mola = 10, "back.out(1.7)"
    de, para, duracao, curva, toque = queda
    pousa = round(inicio + toque * k, 3)
    js = [_js_topo(0.0) if html_topo else "",
          _entra("#m-corpo, #m-bandeja", 0.0, de="{opacity: 0, y: 30}", para="{opacity: 1, y: 0}", dur=0.5,
                 ease="power2.out"),
          f'tl.fromTo("#m-chao", {{ scaleX: 0.4, opacity: 0, svgOrigin: "{cx} 812" }}, {{ scaleX: 1, opacity: 1, '
          f'svgOrigin: "{cx} 812", duration: 0.5, ease: "power2.out" }}, 0);',
          f'tl.fromTo("#m-bicho", {de}, {para}, duration: {round(duracao * k, 3)}, ease: "{curva}" }}, {inicio});',
          f'tl.fromTo("#m-bandeja, #m-bicho-caixa", {{ y: 0 }}, {{ y: {afunda}, duration: 0.16, ease: "power2.out", '
          f'yoyo: true, repeat: 1 }}, {pousa});',
          f'tl.fromTo("#m-ponteiro", {{ rotation: -135, svgOrigin: "{cx} {cy}" }}, {{ rotation: {angulo}, '
          f'svgOrigin: "{cx} {cy}", duration: {round(0.8 * k, 3)}, ease: "{mola}" }}, {pousa});',
          f'tl.to("#m-fio-linha", {{ strokeDashoffset: 0, duration: {round(0.5 * k, 3)}, ease: "power3.out" }}, '
          f'{round(pousa + 0.1 * k, 3)});',
          _entra("#m-dado", round(pousa + 0.25 * k, 3), dur=round(0.6 * k, 3)),
          _conta("#m-valor", valor, round(pousa + 0.3 * k, 3), round(0.9 * k, 3), casas)]
    return {"css": css, "html": html, "js": "\n".join(x for x in js if x)}


MODELOS = {"velocimetro": velocimetro, "balanca": balanca, "regua": regua, "contador": contador,
           "porcentagem": porcentagem, "comparacao": comparacao, "tendencia": tendencia, "fluxo": fluxo,
           "ranking": ranking, "frase": frase, "topicos": topicos,
           "contraste": contraste, "marco": marco, "foto_dado": foto_dado, "tipografia": tipografia,
           "colagem_balanca": colagem_balanca, "medida_colagem": medida_colagem, "contagem_colagem": contagem_colagem,
           "ficha_colagem": ficha_colagem}
COM_FOTO = ("foto_dado", "colagem_balanca", "medida_colagem", "contagem_colagem", "ficha_colagem")  # os desenhos que só existem com a foto da cena

CATALOGO = """MODELOS (escolha o que DEMONSTRA o dado da fala; cada um tem um desenho próprio):
- velocimetro: velocidade ("50 quilômetros por hora"). Campos: valor, unidade ("km/h"), prefixo ("mais de", ou vazio).
- balanca: peso GRANDE de coisa pesada ("mais de uma tonelada", um elefante). Um peso de ferro cai na balança.
  Campos: valor, unidade ("tonelada"), prefixo, abreviacao (o que vai escrito no peso, curto: "1 t", "200 kg").
  NUNCA para coisa pequena ou leve (um mico de meio quilo, um beija-flor de gramas). Com a foto da cena, use
  colagem_balanca.
- colagem_balanca: peso de um ANIMAL (ou coisa) quando a cena TEM FOTO dele. O próprio bicho, recortado como
  figurinha, pousa numa balança de cozinha; o ponteiro gira e uma etiqueta mostra o número. Serve para leve e para
  pesado (o tom muda a chegada). Campos: valor (meio quilo = 0.5), unidade curta ("kg", "t", "g"), prefixo
  ("pouco mais de", "até"), tom ("leve", "pesado" ou "neutro"), topo, destaque.
- medida_colagem: comprimento ou altura de um ANIMAL (ou coisa) citado, quando a cena TEM FOTO. O próprio bicho,
  recortado, com uma fita métrica até o valor; se a fala cita uma parte do corpo ("contando a cauda achatada"), ela
  ganha destaque com anotação, e a função dela ("funciona como leme") entra depois. Campos: valor, unidade ("metros",
  "centímetros"), prefixo ("quase", "até"), parte (a parte do corpo citada, com as palavras da fala: "cauda
  achatada"; vazio se não cita), funcao (o que a parte faz, da fala: "funciona como leme"; vazio se não diz),
  palavra_valor, palavra_parte, palavra_funcao (a palavra da fala em que cada coisa aparece: "dois", "cauda", "leme").
  Se a mesma fala traz um segundo dado do bicho ("e pesar mais de cem quilos"): valor2, unidade2, prefixo2,
  palavra_valor2; ele entra embaixo da fita, sem precisar de outra balança.
- contagem_colagem: quantos ANIMAIS (de uma espécie citada) existem, restam, nascem ("restavam apenas cerca de
  duzentos micos", "alguns milhares de indivíduos"), quando dá para recortar o bicho. O próprio animal à esquerda e a
  silhueta dele repetida numa grade, uma por unidade. Campos: valor (o número dito: duzentos = 200; "milhares" =
  1000), unidade (o que se conta, da fala: "micos", "indivíduos"), prefixo ("apenas", "cerca de"), rotulo_valor (o
  número como foi dito quando não é exato: "milhares"; vazio se é exato), palavra_valor (a palavra do número na fala).
  Gente (pessoas, vítimas, mortes) é contador, nunca este.
- ficha_colagem: DOIS ou TRÊS dados do mesmo bicho na mesma fala ("pode passar de dois metros e meio e pesar mais
  de cem quilos"), quando dá para mostrar a foto dele: a foto à esquerda e uma linha por dado, com ícone e o número.
  Campos: itens [{valor, unidade (da fala: "metros", "quilos"), prefixo ("mais de", "até"), palavra (a palavra do
  número na fala: "dois", "cem")}].
- regua: comprimento, altura ou tamanho ("um chifre de mais de um metro"). A coisa cresce numa régua. Campos: valor,
  unidade ("metro"), prefixo, forma: "cone" para chifre, presa, dente, garra ou bico; "barra" para o resto.
- contador: quantidade de pessoas, animais ou coisas ("135 pessoas", "cerca de 35 pessoas"). Um ícone por unidade
  aparece em grade e o número conta. Campos: valor, unidade ("pessoas"), prefixo, forma: "pessoa" para gente,
  "ponto" para o resto.
- porcentagem: uma porcentagem ("80% dos ataques"). Campos: valor (0 a 100), unidade (o que ela mede, da fala).
- comparacao: dois a quatro valores ditos na fala, comparados. Campos: itens [{rotulo, valor}], unidade.
- tendencia: queda ou subida, declínio, crescimento, à beira da extinção. Campos: direcao ("desce" ou "sobe"),
  fim (onde chega, da fala: "extinção"), inicio (opcional).
- fluxo: causa e consequência, ou etapas de um processo. Campos: etapas (2 a 4 textos curtos, da fala, na ordem).
- ranking: posição numa contagem ("em oitavo lugar"). Campos: posicao, total (quantos na lista), nome (quem está na
  posição, da fala).
- frase: uma ideia, conclusão ou virada sem número. Campos: frase (até 12 palavras da fala), destaque (uma palavra
  dela, a mais forte).
- tipografia: o dado escrito grande em serifa, letra por letra, num recorte de papel, sem nenhum objeto desenhado.
  Para quando um desenho literal contradiz a cena (peso de ferro para um bicho leve) ou quando o que importa é a
  qualidade do dado (leveza, pequenez, raridade). Campos: texto (o dado com as palavras da fala, até 6 palavras:
  "meio quilo", "três gramas"), prefixo ("pouco mais de", "só", "menos de"), tom ("leve", "pesado" ou "neutro": o
  movimento das letras), topo, destaque (uma palavra do texto). Sem foto, é o desenho do peso de coisa leve.
- topicos: dois a quatro pontos de uma enumeração ou de um argumento, sem número obrigatório ("os três pilares", "o
  solo é pobre, o frio castiga, a planta sofre"). Linhas numeradas que entram uma a uma. Campos: etapas (2 a 4 textos
  curtos, até 6 palavras, da fala, na ordem).
- contraste: dois lados opostos ("soja contra vinho", "antes e depois", "quem produz mais contra quem espera mais").
  Dois cards lado a lado com um × no meio. Campos: itens [{rotulo (o lado, até 3 palavras), texto (até 8 palavras,
  da fala)}], exatamente 2.
- marco: um fato num momento ("em 1875 chegam os imigrantes", "em 2012, a primeira Denominação de Origem"). O ano grande
  em serifa, uma linha e o fato ao lado. Campos: marco (o ano ou período dito na fala), texto (o fato, até 12 palavras
  da fala).
- foto_dado: SÓ se o pedido disser que a cena tem foto e nenhum desenho acima servir. A foto da cena ao lado do dado.
  Campos: valor, unidade, prefixo (ou frase).
Todos aceitam topo: uma frase curta da fala que vai no alto da tela (até 7 palavras), e destaque: uma palavra do topo.
Os textos saem da fala, com as palavras dela. O valor é o número que a fala diz (uma tonelada = 1)."""


# ------------------------------------------------------------------------------------------- a conferência

def _normal(texto) -> str:
    return unicodedata.normalize("NFKD", str(texto or "").lower()).encode("ascii", "ignore").decode()


def _inventadas(textos, fala) -> list:
    """Palavras de 4 letras ou mais que a fala não diz (pelas 5 primeiras letras, para aceitar plural e gênero)."""
    ditas = {p[:5] for p in re.findall(r"[a-z]{4,}", _normal(fala))}
    fora = []
    for texto in textos:
        for p in re.findall(r"[a-z]{4,}", _normal(texto)):
            if p[:5] not in ditas and p not in ("cada", "icone", "lugar"):
                fora.append(p)
    return list(dict.fromkeys(fora))[:6]


def _numero(valor):
    try:
        if isinstance(valor, str):
            valor = valor.replace(".", "").replace(",", ".") if re.fullmatch(r"[\d.]+,\d+", valor.strip()) else valor
        return float(valor)
    except (TypeError, ValueError):
        return None


def _numeros_da_fala(fala) -> set:
    return {float(n.replace(".", "").replace(",", ".")) for n in re.findall(r"\d+(?:[.,]\d+)*", fala or "")}


# o dado achado na fala aponta o desenho: na cena 11 do natureza-teste-1min o modelo escolheu a foto com o número para
# "50 quilômetros por hora", com o velocímetro pronto para isso
_INDICADO = [(r"por hora|km/h|por segundo", "velocimetro"), (r"tonelada|quilo|\bkg\b|grama", "balanca"),
             (r"metro|cent[íi]metro|mil[íi]metro", "regua"), (r"por cento|%", "porcentagem"),
             (r"pessoas|v[íi]timas|mortes|habitantes|trabalhadores|indiv[íi]duos|animais|filhotes", "contador")]


# coisa leve ou pequena: a balança com o peso de ferro estraga a cena (PRD Motion AI 2.0, "pesa pouco mais de meio
# quilo", o mico-leão-dourado). Antes a unidade dizia "peso" e o código obrigava a balança.
_LEVE = re.compile(r"\b(?:leve|levinh|lev[íi]ssim|pouco mais de|apenas|s[óo]\b|pequen|min[úu]scul|mi[úu]d|cabem? na|"
                   r"palma da m[ãa]o|pena\b|meio quilo|gramas?\b|mil[íi]gramas?)", re.I)
_KG = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:quilos?|kg)\b", re.I)


def leve(dado, fala="") -> bool:
    """O peso da fala é de coisa leve ou pequena (gramas, meio quilo, menos de 10 kg, "só", "pouco mais de")."""
    if re.search(r"tonelada", dado or "", re.I):
        return False
    texto = f"{dado or ''} {fala or ''}"
    kg = _KG.search(texto)
    if kg:
        return float(kg.group(1).replace(",", ".")) < 10
    return bool(_LEVE.search(texto))


def pesado(dado, fala="") -> bool:
    """O peso da fala é de coisa pesada (tonelada, cem quilos ou mais): a chegada na balança despenca."""
    texto = f"{dado or ''} {fala or ''}"
    kg = _KG.search(texto)
    return bool(re.search(r"tonelada|\bcem\b|\bcentenas?\b|\bduzent|\btrezent|\bquinhent|\bmil\b", dado or "", re.I)
                or (kg and float(kg.group(1).replace(",", ".")) >= 100))


_GENTE = r"pessoas|v[íi]timas|mortes|habitantes|trabalhadores"


def indicado(dado, fala="", tem_foto=False) -> str:
    """O modelo que o dado da fala pede ("50 quilômetros por hora" pede o velocímetro), ou "" se nenhum. Peso com a
    foto da cena pede a colagem do bicho na balança; sem foto, coisa leve pede a tipografia, nunca o peso de ferro.
    Dois dados do mesmo bicho na mesma fala, com foto, pedem a ficha (não duas demonstrações, nem a terceira balança)."""
    dados_da_fala = [x for x in (dado or "").split(";") if x.strip()]
    if tem_foto and len(dados_da_fala) >= 2 and not re.search(_GENTE, dado or "", re.I):
        return "ficha_colagem"
    for padrao, modelo in _INDICADO:
        if re.search(padrao, dado or "", re.I):
            if modelo == "balanca" and tem_foto:
                return "colagem_balanca"
            if modelo == "regua" and tem_foto:
                return "medida_colagem"
            if modelo == "contador" and tem_foto and not re.search(_GENTE, dado or "", re.I):
                return "contagem_colagem"
            return "tipografia" if modelo == "balanca" and leve(dado, fala) else modelo
    return ""


_QUANTIFICADOR = re.compile(r"^(mais de|menos de|cerca de|quase|até|ate|aproximadamente|perto de|acima de|abaixo de|"
                            r"uns|umas|em torno de|por volta de|pouco mais de|pouco menos de|só|so|apenas)$")


def conferir(modelo, dados, fala, tem_foto=False, fala_da_cena=None, sugerido="", proibidos=(), figura=False):
    """Os dados limpos para o modelo, e a lista do que está errado (vazia quando está tudo certo).

    sugerido: o desenho que a direção de arte (ou o dado da fala) indica; proibidos: os desenhos que ela proíbe.

    fala: o texto de onde as palavras podem sair (a cena e as vizinhas). fala_da_cena: só a desta cena, de onde sai o
    número (na cena 12 do natureza-teste-1min, o "50" da vizinha fazia o "1 metro" do chifre ser recusado)."""
    numeros = _numeros_da_fala(fala if fala_da_cena is None else fala_da_cena)
    erros = []
    if modelo not in MODELOS:
        return None, [f"modelo desconhecido: {modelo}. Use um destes: {', '.join(MODELOS)}"]
    if modelo in proibidos:
        return None, [f"a direção de arte proibiu o desenho {modelo} nesta cena: use "
                      + (sugerido if sugerido and sugerido not in proibidos else "outro")]
    if sugerido and modelo != sugerido and modelo in ("foto_dado", "frase"):
        return None, [f"a fala traz um dado que o modelo {sugerido} demonstra: use o modelo {sugerido}"]
    d = {k: v for k, v in (dados or {}).items() if v not in (None, "", [])}
    for campo in ("topo", "destaque", "prefixo", "unidade", "abreviacao", "nome", "frase", "inicio", "fim", "texto",
                  "parte", "funcao", "palavra_valor", "palavra_parte", "palavra_funcao", "rotulo_valor",
                  "unidade2", "prefixo2", "palavra_valor2", "marco", "carimbo", "etiqueta"):
        if campo in d:
            d[campo] = " ".join(str(d[campo]).split())[:80]
    if d.get("prefixo") and not _QUANTIFICADOR.match(d["prefixo"].lower()):
        d.pop("prefixo")  # só "mais de", "cerca de", "quase"...: no velocímetro, "passar dos" repetia o topo
    if d.get("topo") and len(d["topo"].split()) > 8:
        d["topo"] = " ".join(d["topo"].split()[:8])
    precisa_valor = modelo in ("velocimetro", "balanca", "regua", "contador", "porcentagem", "colagem_balanca",
                               "medida_colagem", "contagem_colagem")
    if precisa_valor or (modelo == "foto_dado" and "valor" in d):
        d["valor"] = _numero(d.get("valor"))
        if d["valor"] is None or d["valor"] <= 0:
            erros.append(f"o modelo {modelo} precisa de valor, o número que a fala diz")
        elif numeros and d["valor"] not in numeros:
            erros.append(f"o valor {fmt(d['valor'])} não é um número que a fala diz ({', '.join(fmt(n) for n in sorted(numeros))})")
        if not d.get("unidade") and modelo != "foto_dado":
            erros.append(f"o modelo {modelo} precisa de unidade (o que o número mede, como a fala diz)")
    if modelo == "porcentagem" and d.get("valor") and d["valor"] > 100:
        erros.append("porcentagem vai de 0 a 100")
    if d.get("rotulo_valor") and not re.search(r"\d|milhar|milh[õo]|centena|dezena|bilh|mil\b|cem|duzent|trezent|"
                                              r"quinhent|vinte|trinta|quarenta|cinquenta|sessenta|setenta|"
                                              r"oitenta|noventa", d["rotulo_valor"], re.I):
        # "cerca de" no lugar do número (cena 21 do 11-animais-do-brasil): o quantificador vai para o prefixo
        if not d.get("prefixo") and _QUANTIFICADOR.match(d["rotulo_valor"].lower()):
            d["prefixo"] = d["rotulo_valor"]
        d.pop("rotulo_valor")
    elif d.get("rotulo_valor") and not re.search(r"milhar|milh[õo]es|centena|dezena|bilh", d["rotulo_valor"], re.I):
        # número exato por extenso ("duzentos"): o algarismo conta subindo; o rótulo é só para o que não é exato
        d.setdefault("palavra_valor", d["rotulo_valor"].split()[0])
        d.pop("rotulo_valor")
    if modelo == "contagem_colagem" and d.get("valor") and d["valor"] < 2:
        erros.append("contagem_colagem precisa de 2 ou mais")
    if modelo == "contador" and d.get("valor") and d["valor"] < 2:
        erros.append("contador precisa de 2 ou mais: para um número só, use outro modelo")
    if modelo == "comparacao":
        itens = []
        for item in d.get("itens") or []:
            if isinstance(item, dict) and _numero(item.get("valor")) and str(item.get("rotulo") or "").strip():
                itens.append({"rotulo": " ".join(str(item["rotulo"]).split())[:40], "valor": _numero(item["valor"])})
        d["itens"] = itens
        if not 2 <= len(itens) <= 4:
            erros.append("comparacao precisa de 2 a 4 itens com rotulo e valor ditos na fala")
    if modelo in ("fluxo", "barbante"):
        d["etapas"] = [" ".join(str(e).split())[:60] for e in d.get("etapas") or [] if str(e).strip()][:4]
        if len(d["etapas"]) < 2:
            erros.append(f"{modelo} precisa de 2 a 4 etapas")
    if modelo == "topicos":
        d["etapas"] = [" ".join(str(e).split())[:70] for e in d.get("etapas") or [] if str(e).strip()][:4]
        if len(d["etapas"]) < 2:
            erros.append("topicos precisa de 2 a 4 pontos em etapas")
    if modelo == "contraste":
        lados = []
        for item in d.get("itens") or []:
            if isinstance(item, dict) and str(item.get("rotulo") or "").strip() and str(item.get("texto") or "").strip():
                lados.append({"rotulo": " ".join(str(item["rotulo"]).split())[:30],
                              "texto": " ".join(str(item["texto"]).split())[:80]})
        d["itens"] = lados[:2]
        if len(lados) < 2:
            erros.append("contraste precisa de 2 itens, cada um com rotulo e texto, tirados da fala")
    if modelo == "marco":
        d["marco"] = " ".join(str(d.get("marco") or "").split())[:20]
        if not d["marco"] or not d.get("texto"):
            erros.append("marco só serve quando a fala diz um ano ou época (campo marco) e o fato (campo texto): sem ano dito, use outro desenho (topicos, contraste, fluxo ou frase)")
        elif any(n not in numeros for n in _numeros_da_fala(d["marco"])):
            erros.append("o marco tem um número que a fala não diz")
        elif len((d.get("texto") or "").split()) > 14:
            erros.append("o texto do marco passou de 14 palavras: encurte, com as palavras da fala")
    if modelo == "documento":
        d["carimbo"] = " ".join(str(d.get("carimbo") or "").split())[:40]
        d["linhas"] = [" ".join(str(x).split())[:70] for x in d.get("linhas") or [] if str(x).strip()][:3]
        if not d["carimbo"]:
            erros.append("documento precisa do campo carimbo (até 4 palavras da fala)")
        elif len(d["carimbo"].split()) > 5:
            erros.append("o carimbo passou de 5 palavras: encurte, com as palavras da fala")
        elif any(n not in numeros for n in _numeros_da_fala(d["carimbo"])):
            erros.append("o carimbo tem um número que a fala não diz")
    if modelo == "foto_recortada":
        d["etiqueta"] = " ".join(str(d.get("etiqueta") or "").split())[:40]
        d["carimbo"] = " ".join(str(d.get("carimbo") or "").split())[:40]
        if not d["etiqueta"]:
            erros.append("foto_recortada precisa do campo etiqueta (até 4 palavras da fala)")
        elif any(n not in numeros for n in _numeros_da_fala(d["etiqueta"] + " " + d["carimbo"])):
            erros.append("a etiqueta ou o carimbo tem um número que a fala não diz")
    if modelo == "ranking":
        posicao, total = _numero(d.get("posicao")), _numero(d.get("total"))
        if not posicao or not total or not 1 <= posicao <= total <= 12 or total < 2:
            erros.append("ranking precisa de posicao e total (de 2 a 12), com a posição dentro do total")
        else:
            d["posicao"], d["total"] = int(posicao), int(total)
    if modelo == "frase":
        if not d.get("frase"):
            erros.append("frase precisa do campo frase")
        elif len(d["frase"].split()) > 14:
            erros.append("a frase passou de 14 palavras: encurte, com as palavras da fala")
    if modelo == "tipografia":
        if not d.get("texto"):
            erros.append('tipografia precisa do campo texto (o dado com as palavras da fala: "meio quilo")')
        elif len(d["texto"].split()) > 6:
            erros.append("o texto da tipografia passou de 6 palavras: só o dado, com as palavras da fala")
        elif any(n not in numeros for n in _numeros_da_fala(d["texto"])):
            erros.append("o texto da tipografia tem um número que a fala não diz")
    if modelo in ("tipografia", "colagem_balanca"):
        tom = str(d.get("tom") or "").lower()
        d["tom"] = tom if tom in TONS else "neutro"
    if modelo == "tendencia":
        d["direcao"] = "sobe" if str(d.get("direcao", "")).lower().startswith("s") else "desce"
    # figura: dá para buscar a foto própria do sujeito nos bancos (motion_figura); o foto_dado precisa da foto da cena
    if modelo in COM_FOTO and not tem_foto and (modelo in ("foto_dado", "foto_recortada") or not figura):
        erros.append(f"{modelo} só vale quando a cena tem foto: escolha um desenho")
    if modelo in ("regua",):
        d["forma"] = "cone" if d.get("forma") == "cone" else "barra"
    if modelo == "contador":
        d["forma"] = "pessoa" if d.get("forma") == "pessoa" else "ponto"
    if modelo == "ficha_colagem":
        itens = []
        for item in d.get("itens") or []:
            if not isinstance(item, dict):
                continue
            valor = _numero(item.get("valor"))
            unidade = " ".join(str(item.get("unidade") or "").split())[:24]
            if not valor or valor <= 0 or not unidade or (numeros and valor not in numeros):
                continue
            prefixo = " ".join(str(item.get("prefixo") or "").split()).lower()
            itens.append({"valor": valor, "unidade": unidade,
                          "prefixo": prefixo if _QUANTIFICADOR.match(prefixo) else "",
                          "palavra": " ".join(str(item.get("palavra") or "").split())[:24]})
        d["itens"] = itens[:3]
        if len(d["itens"]) < 2:
            erros.append("ficha_colagem precisa de 2 ou 3 itens, cada um com o valor e a unidade ditos na fala")
    if modelo == "medida_colagem" and "valor2" in d:
        d["valor2"] = _numero(d.get("valor2"))
        if not d["valor2"] or d["valor2"] <= 0 or not d.get("unidade2") or (numeros and d["valor2"] not in numeros):
            for campo in ("valor2", "unidade2", "prefixo2", "palavra_valor2"):
                d.pop(campo, None)  # segundo dado que não se sustenta sai; o clipe segue com o primeiro
        elif d.get("prefixo2") and not _QUANTIFICADOR.match(d["prefixo2"].lower()):
            d.pop("prefixo2")
    textos = [d.get(k) or "" for k in ("topo", "nome", "frase", "inicio", "fim", "texto", "parte", "funcao",
                                       "rotulo_valor", "unidade2", "carimbo", "etiqueta")]
    textos += [d.get("unidade") or ""] if modelo not in ("velocimetro",) else []
    textos += d.get("etapas") or []
    textos += d.get("linhas") or []
    textos += [i.get("rotulo") or i.get("unidade") or "" for i in d.get("itens") or []]
    textos += [i.get("texto") or "" for i in d.get("itens") or []]
    inventadas = _inventadas(textos, fala)
    if inventadas:
        erros.append("usa palavras que a fala não diz (" + ", ".join(inventadas) + "): só palavras da fala")
    return d, erros


def partes(modelo, dados, dur, foto=None):
    return MODELOS[modelo](dados, dur, foto)


try:  # documento, barbante e foto_recortada: o módulo não está na pasta (sumiu na troca de sessões); sem ele os desenhos prontos seguem sem esses três
    from . import motion_colagem  # noqa: E402
    motion_colagem.registrar()
except ImportError:
    pass
