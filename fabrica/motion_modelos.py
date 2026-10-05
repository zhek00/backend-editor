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

VERSAO = 1  # suba quando mudar o desenho de algum modelo

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


MODELOS = {"velocimetro": velocimetro, "balanca": balanca, "regua": regua, "contador": contador,
           "porcentagem": porcentagem, "comparacao": comparacao, "tendencia": tendencia, "fluxo": fluxo,
           "ranking": ranking, "frase": frase, "foto_dado": foto_dado}

CATALOGO = """MODELOS (escolha o que DEMONSTRA o dado da fala; cada um tem um desenho próprio):
- velocimetro: velocidade ("50 quilômetros por hora"). Campos: valor, unidade ("km/h"), prefixo ("mais de", ou vazio).
- balanca: peso ("mais de uma tonelada"). Um peso de ferro cai na balança. Campos: valor, unidade ("tonelada"),
  prefixo, abreviacao (o que vai escrito no peso, curto: "1 t", "200 kg").
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


_QUANTIFICADOR = re.compile(r"^(mais de|menos de|cerca de|quase|até|ate|aproximadamente|perto de|acima de|abaixo de|"
                            r"uns|umas|em torno de|por volta de)$")


def conferir(modelo, dados, fala, tem_foto=False, fala_da_cena=None):
    """Os dados limpos para o modelo, e a lista do que está errado (vazia quando está tudo certo).

    fala: o texto de onde as palavras podem sair (a cena e as vizinhas). fala_da_cena: só a desta cena, de onde sai o
    número (na cena 12 do natureza-teste-1min, o "50" da vizinha fazia o "1 metro" do chifre ser recusado)."""
    numeros = _numeros_da_fala(fala if fala_da_cena is None else fala_da_cena)
    erros = []
    if modelo not in MODELOS:
        return None, [f"modelo desconhecido: {modelo}. Use um destes: {', '.join(MODELOS)}"]
    d = {k: v for k, v in (dados or {}).items() if v not in (None, "", [])}
    for campo in ("topo", "destaque", "prefixo", "unidade", "abreviacao", "nome", "frase", "inicio", "fim"):
        if campo in d:
            d[campo] = " ".join(str(d[campo]).split())[:80]
    if d.get("prefixo") and not _QUANTIFICADOR.match(d["prefixo"].lower()):
        d.pop("prefixo")  # só "mais de", "cerca de", "quase"...: no velocímetro, "passar dos" repetia o topo
    if d.get("topo") and len(d["topo"].split()) > 8:
        d["topo"] = " ".join(d["topo"].split()[:8])
    precisa_valor = modelo in ("velocimetro", "balanca", "regua", "contador", "porcentagem")
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
    if modelo == "fluxo":
        d["etapas"] = [" ".join(str(e).split())[:60] for e in d.get("etapas") or [] if str(e).strip()][:4]
        if len(d["etapas"]) < 2:
            erros.append("fluxo precisa de 2 a 4 etapas")
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
    if modelo == "tendencia":
        d["direcao"] = "sobe" if str(d.get("direcao", "")).lower().startswith("s") else "desce"
    if modelo == "foto_dado" and not tem_foto:
        erros.append("foto_dado só vale quando a cena tem foto: escolha um desenho")
    if modelo in ("regua",):
        d["forma"] = "cone" if d.get("forma") == "cone" else "barra"
    if modelo == "contador":
        d["forma"] = "pessoa" if d.get("forma") == "pessoa" else "ponto"
    textos = [d.get(k) or "" for k in ("topo", "nome", "frase", "inicio", "fim")]
    textos += [d.get("unidade") or ""] if modelo not in ("velocimetro",) else []
    textos += d.get("etapas") or []
    textos += [i["rotulo"] for i in d.get("itens") or []]
    inventadas = _inventadas(textos, fala)
    if inventadas:
        erros.append("usa palavras que a fala não diz (" + ", ".join(inventadas) + "): só palavras da fala")
    return d, erros


def partes(modelo, dados, dur, foto=None):
    return MODELOS[modelo](dados, dur, foto)
