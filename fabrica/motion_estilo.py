"""Estilo "colagem" do Motion IA (pedido do usuário em 2026-10-08, depois de estudar os vídeos de motion estilo Vox).

O esqueleto de motion_ia.montar_html desenha cards brancos sobre creme com pontos: parece interface de produto, não o
Vox de verdade, que é colagem de papel. Este módulo põe o estilo por cima do esqueleto, SEM mexer nos desenhos prontos
(motion_modelos) nem no HTML livre do modelo:

- fundo de papel kraft amassado e uma textura de papel com granulação por cima de tudo (mix-blend-mode: multiply), de modo
  que qualquer clipe, não importa o desenho, sai com a mesma textura tátil;
- paleta travada: amarelo, preto, azul-marinho, vermelho de tinta e creme (as variáveis --laranja, --azul e --verde dos
  desenhos prontos apontam para elas);
- cards viram recortes de papel: cantos secos, sombra dura, levemente tortos, com um pedaço de fita adesiva;
- três recortes de papel rasgado ao fundo andando em velocidades diferentes (paralaxe em 2D);
- entradas "em degraus" (stop-motion): a mola `back.out` vira `steps(6)`, como papel jogado na mesa;
- zoom lento de 1,0 a 1,05 na cena inteira.

Ligado por `motion_ia.estilo: colagem` (no perfil ou no config.yaml). Clipe já gravado não muda sozinho: troque o estilo
e refaça as cenas (`fabrica motion NOME --cenas N --aplicar`). Os ids e classes daqui não podem repetir os dos desenhos
prontos (o `#m-papel` da tipografia já colidiu uma vez com o fundo da colagem).
"""
import re

VERSAO = 1
NOME = "colagem"

CSS = """
      :root { --verde: #B3261E; --azul: #14213D; --laranja: #F2B705; --grafite: #111111; --creme: #EBE1CB; }
      html, body { background: #EBE1CB; }
      #root { background-color: #EBE1CB; background-image: none; }
      .m-card { background: #F8F2E2; border-radius: 3px; box-shadow: 8px 10px 0 rgba(17, 17, 17, 0.17);
                rotate: -0.7deg; position: relative; }
      .m-card:nth-of-type(even) { rotate: 0.8deg; }
      .m-card::before { content: ""; position: absolute; top: -16px; left: 50%; width: 120px; height: 34px;
                        margin-left: -60px; background: rgba(242, 183, 5, 0.78); rotate: -3deg;
                        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.18); }
      .m-card:nth-of-type(even)::before { rotate: 4deg; background: rgba(20, 33, 61, 0.55); }
      .m-destaque { color: #14213D; background: linear-gradient(transparent 62%, rgba(242, 183, 5, 0.75) 62%); }
      #m-colagem-fundo { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; overflow: hidden; }
      .m-recorte { position: absolute; }
      #m-rec-1 { left: -160px; top: -90px; width: 640px; height: 360px; background: #F2B705; rotate: -9deg;
                 clip-path: polygon(0 4%, 12% 0, 31% 5%, 52% 1%, 74% 6%, 100% 2%, 97% 28%, 100% 53%, 96% 79%, 99% 100%,
                            72% 96%, 49% 100%, 27% 95%, 6% 99%, 2% 70%, 0 44%); }
      #m-rec-2 { right: -190px; bottom: 180px; width: 700px; height: 420px; background: #14213D; rotate: 7deg;
                 clip-path: polygon(2% 0, 24% 5%, 47% 0, 70% 4%, 100% 1%, 96% 30%, 100% 58%, 97% 100%, 74% 95%, 50% 100%,
                            25% 96%, 0 100%, 4% 62%, 0 30%); opacity: 0.92; }
      #m-rec-3 { left: 1180px; top: -60px; width: 380px; height: 250px; background: #B3261E; rotate: 4deg;
                 clip-path: polygon(0 6%, 22% 0, 48% 5%, 76% 0, 100% 7%, 95% 38%, 100% 70%, 94% 100%, 66% 95%, 38% 100%,
                            12% 94%, 3% 100%, 6% 66%, 0 35%); opacity: 0.88; }
      #m-bolhas { display: none; }
      #m-ano { color: #B3261E !important; }
      .m-lado-rot { color: #111111 !important; border-bottom: 7px solid var(--cor); padding-bottom: 6px; }
      #m-ponto-0 .m-bola, .m-ultima .m-bola { color: #111111 !important; }
      #m-textura-papel { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; pointer-events: none;
                         mix-blend-mode: multiply; opacity: 0.55; }
"""

HTML_FUNDO = """      <div id="m-colagem-fundo"><div class="m-recorte" id="m-rec-1"></div><div class="m-recorte" id="m-rec-2"></div><div class="m-recorte" id="m-rec-3"></div></div>
"""

HTML_TEXTURA = """      <svg id="m-textura-papel" viewBox="0 0 1920 1080" preserveAspectRatio="none">
        <filter id="m-amassado" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="0.011 0.016" numOctaves="3" seed="11"/><feColorMatrix type="matrix" values="0 0 0 0 0.45  0 0 0 0 0.36  0 0 0 0 0.24  0 0 0 0.85 -0.18"/></filter>
        <filter id="m-grao-papel" x="0" y="0" width="100%" height="100%"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="5"/><feColorMatrix type="saturate" values="0"/></filter>
        <rect width="1920" height="1080" filter="url(#m-amassado)"/>
        <rect width="1920" height="1080" filter="url(#m-grao-papel)" opacity="0.35"/>
      </svg>
"""

# os recortes de fundo andam em velocidades diferentes (paralaxe); a mola back.out vira degraus (stop-motion) em aplicar()
JS = """
      tl.fromTo("#m-rec-1", { x: 0, y: 0 }, { x: 70, y: 24, duration: DUR, ease: "none" }, 0);
      tl.fromTo("#m-rec-2", { x: 0, y: 0 }, { x: -110, y: -30, duration: DUR, ease: "none" }, 0);
      tl.fromTo("#m-rec-3", { x: 0, y: 0 }, { x: 40, y: 38, duration: DUR, ease: "none" }, 0);
"""


def aplicar(html: str) -> str:
    """O esqueleto montado, com o estilo de colagem por cima."""
    marca_css = "      /* do modelo */"
    if marca_css not in html or '<section id="cena"' not in html or 'window.__timelines["main"] = tl;' not in html:
        return html  # esqueleto desconhecido: melhor o clipe no estilo de antes do que quebrado
    html = html.replace(marca_css, CSS + marca_css, 1)
    html = html.replace('      <section id="cena"', HTML_FUNDO + '      <section id="cena"', 1)
    html = html.replace('      <div id="m-faixa-legenda"></div>', HTML_TEXTURA + '      <div id="m-faixa-legenda"></div>', 1)
    html = html.replace('      window.__timelines["main"] = tl;', JS + '      window.__timelines["main"] = tl;', 1)
    html = re.sub(r'ease:\s*"back\.out\([0-9.]+\)"', 'ease: "steps(6)"', html)  # papel jogado na mesa, em degraus
    html = html.replace("scale: 1.03", "scale: 1.05")  # zoom lento de 1,0 a 1,05
    return html
