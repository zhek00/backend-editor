"""Thumbnails do vídeo: 3 opções de capa e a prancha com o teste do celular.

Pedido do usuário em 2026-10-09, da análise do concorrente (Pipeline Canal Dark), que entrega 3 thumbnails e uma
prancha com cada uma no tamanho do celular. Aqui, do jeito da fábrica e de graça:

- **Fotos** (`candidatas` e `escolher_fotos`): as imagens do próprio vídeo com a melhor nota do Jev (foto de banco,
  capa do vídeo de banco ou imagem de IA; nunca clipe de motion nem cena animada), até 12, numa folha numerada. A
  cadeia de visão, só nos gratuitos, escolhe as 3 que fazem a melhor capa para o título. Sem resposta, as de nota maior.
- **Texto**: as 3 opções do kit de publicação (`publicacao.json`, campo `thumbs`: l1 e l2 que completam o título, com
  *destaque*). Sem kit, o fim do título.
- **Desenho** (Pillow, fontes da fábrica): 3 layouts, um por opção: `foto_texto` (foto cheia com sombra à esquerda e
  o texto grande), `painel` (faixa escura com o texto e a foto ao lado) e `impacto` (foto escurecida, texto no centro
  com a palavra em destaque numa tarja). O recorte segue os rostos (`rostos.recorte`). Nada no canto de baixo à
  direita, onde o YouTube põe a duração.
- **Saída**: `thumbnail.jpg` (a escolhida, opção 1 até a pessoa trocar), `thumb_1.jpg` a `thumb_3.jpg`,
  `thumbs_prancha.jpg` (as três grandes e cada uma em 256x144, o tamanho no celular) e `thumbs.json`. 1280x720 e
  menos de 2 MB, o limite do YouTube.
"""
import json
import re
import shutil
from pathlib import Path

LARGURA, ALTURA = 1280, 720
FONTES = Path(__file__).parent / "recursos" / "fontes"
AMARELO, BRANCO, PRETO = (255, 212, 0), (255, 255, 255), (12, 12, 14)
LAYOUTS = ("foto_texto", "painel", "impacto")
_IMAGENS = (".jpg", ".jpeg", ".png", ".webp")


def _fonte(px, peso=900):
    from PIL import ImageFont
    f = ImageFont.truetype(str(FONTES / "Inter.ttf"), px)
    try:
        f.set_variation_by_axes([32, peso])
    except Exception:  # noqa: BLE001 - sem eixo variável, fica o peso padrão
        pass
    return f


# ------------------------------------------------------------------------------------------------ fotos

def candidatas(projeto, maximo=12) -> list:
    """[(cena, arquivo de imagem)] das cenas com imagem própria, a de nota maior primeiro, sem repetir arquivo."""
    from . import animation_ai

    saida, vistos = [], set()
    cenas = projeto.ler_json("cenas.json")["cenas"] if projeto.existe("cenas.json") else []

    def nota(c):
        conf, cap = c.get("conferencia") or {}, c.get("captura") or {}
        for v in (conf.get("nota"), cap.get("nota")):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
        return 50.0

    for c in sorted(cenas, key=lambda c: (-nota(c), c["n"])):
        m = c.get("midia") or {}
        if m.get("fonte") in ("motion_ia", animation_ai.FONTE):
            continue
        arquivo = None
        if m.get("arquivo") and Path(m["arquivo"]).suffix.lower() in _IMAGENS:
            arquivo = projeto.pasta / m["arquivo"]
        elif m.get("capa"):
            arquivo = projeto.pasta / m["capa"]
        elif projeto.imagem(c["n"]).exists():
            arquivo = projeto.imagem(c["n"])
        if not arquivo or not arquivo.exists() or arquivo in vistos:
            continue
        try:
            from PIL import Image
            with Image.open(arquivo) as im:
                if im.width < 640 or im.height < 360:
                    continue  # pequena demais para uma capa de 1280x720
        except Exception:  # noqa: BLE001 - arquivo que não abre não entra
            continue
        vistos.add(arquivo)
        saida.append((c, arquivo))
        if len(saida) >= maximo:
            break
    return saida


ESQUEMA_ESCOLHA = {"type": "object", "properties": {"escolhidas": {"type": "array", "items": {"type": "integer"}}},
                   "required": ["escolhidas"]}
INSTRUCOES_ESCOLHA = """Você escolhe fotos para a thumbnail de um vídeo do YouTube. A folha mostra fotos numeradas do
próprio vídeo. Escolha as 3 que fazem a melhor capa para o título: um assunto só e claro, de perto, com contraste,
rosto ou bicho olhando, ação ou emoção; que se entenda pequena, no celular. Evite foto escura, cheia de detalhe, com
texto ou marca d'água, ou que não tenha a ver com o título. Responda só em JSON: {"escolhidas": [n, n, n]}, a
melhor primeiro."""


def _folha(cands, destino) -> Path:
    from PIL import Image, ImageDraw
    colunas, w, h = 4, 320, 180
    linhas = (len(cands) + colunas - 1) // colunas
    folha = Image.new("RGB", (colunas * w, linhas * h), (30, 30, 34))
    desenho = ImageDraw.Draw(folha)
    for k, (_, arquivo) in enumerate(cands):
        with Image.open(arquivo) as im:
            quadro = _cobrir(im.convert("RGB"), w, h, arquivo)
        x, y = (k % colunas) * w, (k // colunas) * h
        folha.paste(quadro, (x, y))
        desenho.rectangle([x, y, x + 44, y + 36], fill=(0, 0, 0))
        desenho.text((x + 8, y + 4), str(k + 1), fill=AMARELO, font=_fonte(26))
    folha.save(destino, quality=85)
    return destino


def escolher_fotos(projeto, cands, titulo, log=print) -> list:
    """Os arquivos das 3 fotos para as capas, pela visão gratuita; sem ela, as de nota maior."""
    from . import openrouter_local

    if len(cands) <= 3:
        return [a for _, a in cands]
    try:
        folha = _folha(cands, projeto.caminho("thumbs", "candidatas.jpg"))
        resposta = openrouter_local.VISAO.perguntar(
            projeto, "thumbnail: escolha das fotos", INSTRUCOES_ESCOLHA,
            f"Título do vídeo: {titulo}. Há {len(cands)} fotos na folha.", ESQUEMA_ESCOLHA, log=log,
            imagens=[folha], temperatura=0, so_gratuitos=True)
        escolhidas = []
        for k in (resposta or {}).get("escolhidas") or []:
            try:
                k = int(k)
            except (TypeError, ValueError):
                continue
            if 1 <= k <= len(cands) and cands[k - 1][1] not in escolhidas:
                escolhidas.append(cands[k - 1][1])
        if escolhidas:
            resto = [a for _, a in cands if a not in escolhidas]
            return (escolhidas + resto)[:3]
    except (Exception, SystemExit) as erro:  # noqa: BLE001 - sem a visão, ficam as de nota maior
        log(f"  thumbnail: a escolha das fotos não respondeu ({str(erro)[:100]}); vão as de nota maior")
    return [a for _, a in cands[:3]]


# ------------------------------------------------------------------------------------------------ desenho

def _cobrir(im, w, h, arquivo=None):
    """A imagem cobrindo w x h, recortada pelos rostos quando há, senão pelo meio."""
    from PIL import Image
    from . import rostos

    caixa = None
    if arquivo is not None:
        try:
            caixa = rostos.recorte(im.width, im.height, w / h, rostos.rostos(arquivo))
        except Exception:  # noqa: BLE001 - sem detector, recorte pelo meio
            caixa = None
    if caixa is None:
        if im.width / im.height > w / h:
            cl = round(im.height * w / h)
            caixa = ((im.width - cl) // 2, 0, (im.width - cl) // 2 + cl, im.height)
        else:
            ca = round(im.width * h / w)
            caixa = (0, (im.height - ca) // 2, im.width, (im.height - ca) // 2 + ca)
    return im.crop(caixa).resize((w, h), Image.LANCZOS)


def _partes(linha):
    """[(texto, destaque?)] de uma linha com *destaque*."""
    saida = []
    for pedaco in re.split(r"(\*[^*]+\*)", linha or ""):
        if pedaco:
            saida.append((pedaco.strip("*"), pedaco.startswith("*") and pedaco.endswith("*")))
    return saida


def _medir(linha, fonte):
    texto = "".join(t for t, _ in _partes(linha)).upper()
    caixa = fonte.getbbox(texto, stroke_width=0)
    return caixa[2] - caixa[0], caixa[3] - caixa[1]


def _tamanho(linha, largura, maximo, minimo=44):
    px = maximo
    while px > minimo and _medir(linha, _fonte(px))[0] > largura:
        px -= 4
    return px


def _escrever(img, linha, x, y, px, centro=False, tarja=False, cor=BRANCO):
    """Escreve a linha em maiúsculas com contorno e sombra; o *destaque* em amarelo (ou numa tarja amarela).
    Duas passadas: a sombra desfocada embaixo de tudo, depois as letras."""
    from PIL import Image, ImageDraw, ImageFilter

    fonte = _fonte(px)
    largura, _ = _medir(linha, fonte)
    if centro:
        x = (LARGURA - largura) // 2
    pedacos, cursor = [], x
    for texto, forte in _partes(linha):
        texto = texto.upper()
        pedacos.append((texto, forte, cursor))
        cursor += fonte.getlength(texto)
    sombra = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(sombra)
    for texto, forte, cx in pedacos:
        if not (forte and tarja):
            ds.text((cx + 6, y + 9), texto, font=fonte, fill=(0, 0, 0, 190), stroke_width=9, stroke_fill=(0, 0, 0, 190))
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(7)))
    desenho = ImageDraw.Draw(img)
    for texto, forte, cx in pedacos:
        if forte and tarja:
            caixa = fonte.getbbox(texto)
            desenho.rounded_rectangle([cx - 16, y + caixa[1] - 12, cx + fonte.getlength(texto) + 16, y + caixa[3] + 14],
                                      radius=14, fill=AMARELO)
            desenho.text((cx, y), texto, font=fonte, fill=PRETO)
        else:
            desenho.text((cx, y), texto, font=fonte, fill=AMARELO if forte else cor, stroke_width=7, stroke_fill=PRETO)
    return largura


def _linhas(img, l1, l2, x, largura, centro_y, centro=False, tarja=False):
    """As duas linhas, a segunda maior, encaixadas na largura e centradas em centro_y."""
    p1 = _tamanho(l1, largura, 112) if l1 else 0
    p2 = _tamanho(l2, largura, 150) if l2 else 0
    if p1 and p2 and p1 > p2:
        p1 = p2  # a linha do destaque nunca fica menor que a primeira
    altura = (p1 * 1.08 if p1 else 0) + (p2 * 1.08 if p2 else 0)
    y = centro_y - altura / 2
    if l1:
        _escrever(img, l1, x, int(y), p1, centro)
        y += p1 * 1.08
    if l2:
        _escrever(img, l2, x, int(y), p2, centro, tarja)


def desenhar(foto, l1, l2, layout, destino) -> Path:
    from PIL import Image, ImageDraw, ImageEnhance

    with Image.open(foto) as im:
        base = im.convert("RGB")
    if layout == "painel":
        img = Image.new("RGBA", (LARGURA, ALTURA), (14, 16, 20, 255))
        lado = _cobrir(base, 760, ALTURA, foto)
        lado = ImageEnhance.Contrast(ImageEnhance.Color(lado).enhance(1.15)).enhance(1.08)
        img.paste(lado, (LARGURA - 760, 0))
        # a faixa escura entra na foto em diagonal
        mascara = Image.new("L", (LARGURA, ALTURA), 0)
        ImageDraw.Draw(mascara).polygon([(0, 0), (600, 0), (500, ALTURA), (0, ALTURA)], fill=255)
        faixa = Image.new("RGBA", (LARGURA, ALTURA), (14, 16, 20, 255))
        img.paste(faixa, (0, 0), mascara)
        ImageDraw.Draw(img).line([(600, 0), (500, ALTURA)], fill=AMARELO, width=10)
        _linhas(img, l1, l2, 48, 470, ALTURA * 0.5)
    else:
        img = _cobrir(base, LARGURA, ALTURA, foto)
        img = ImageEnhance.Contrast(ImageEnhance.Color(img).enhance(1.18)).enhance(1.1).convert("RGBA")
        sombra = Image.new("RGBA", (LARGURA, ALTURA), (0, 0, 0, 0))
        ds = ImageDraw.Draw(sombra)
        if layout == "impacto":
            ds.rectangle([0, 0, LARGURA, ALTURA], fill=(0, 0, 0, 105))
            for k in range(240):  # escurece embaixo, onde fica o texto
                ds.line([(0, ALTURA - k), (LARGURA, ALTURA - k)], fill=(0, 0, 0, int(150 * (1 - k / 240))))
            img.alpha_composite(sombra)
            # o texto embaixo, longe do rosto (que o recorte põe a 40% da altura)
            _linhas(img, l1, l2, 0, 1160, ALTURA * 0.71, centro=True, tarja=True)
        else:
            for x in range(0, 900):  # sombra da esquerda para o texto ser lido sobre qualquer foto
                ds.line([(x, 0), (x, ALTURA)], fill=(0, 0, 0, int(205 * (1 - x / 900) ** 1.6)))
            img.alpha_composite(sombra)
            _linhas(img, l1, l2, 56, 760, ALTURA * 0.52)
    final = img.convert("RGB")
    final.save(destino, quality=90, optimize=True)
    if destino.stat().st_size > 1_900_000:
        final.save(destino, quality=78, optimize=True)  # o YouTube recusa capa acima de 2 MB
    return destino


def _prancha(arquivos, destino) -> Path:
    """As opções grandes e, embaixo, cada uma em 256x144, o tamanho dela na lista do celular."""
    from PIL import Image, ImageDraw
    w, h = 640, 360
    prancha = Image.new("RGB", (len(arquivos) * (w + 20) + 20, h + 144 + 110), (24, 24, 28))
    desenho = ImageDraw.Draw(prancha)
    for k, arquivo in enumerate(arquivos):
        with Image.open(arquivo) as im:
            grande, celular = im.resize((w, h)), im.resize((256, 144))
        x = 20 + k * (w + 20)
        desenho.text((x, 8), f"opção {k + 1}", fill=BRANCO, font=_fonte(26, 700))
        prancha.paste(grande, (x, 44))
        prancha.paste(celular, (x, 44 + h + 30))
        desenho.text((x + 270, 44 + h + 80), "no celular", fill=(160, 160, 170), font=_fonte(22, 500))
    prancha.save(destino, quality=88)
    return destino


def _textos(projeto) -> tuple:
    """(título, [(l1, l2)] das 3 capas) do kit de publicação; sem kit, o fim do título."""
    kit = projeto.ler_json("publicacao.json") if projeto.existe("publicacao.json") else {}
    titulo = kit.get("titulo") or ((projeto.ler_json("roteiro_mapa.json").get("titulo") if projeto.existe(
        "roteiro_mapa.json") else "") or projeto.nome)
    opcoes = [(t.get("l1", ""), t.get("l2", "")) for t in kit.get("thumbs") or [] if t.get("l1") or t.get("l2")]
    if not opcoes:
        palavras = re.sub(r"[^\w\sÀ-ú?!]", "", titulo).split()
        meio = max(1, len(palavras) // 2)
        l2 = palavras[meio:][-3:]
        opcoes = [(" ".join(palavras[:meio][:3]), " ".join(l2[:-1] + [f"*{l2[-1]}*"]) if l2 else "")]
    while len(opcoes) < 3:
        opcoes.append(opcoes[len(opcoes) % len(opcoes)])
    return titulo, opcoes[:3]


def gerar(projeto, log=print) -> dict:
    """Desenha as 3 capas e a prancha. Grátis. Devolve o thumbs.json."""
    cands = candidatas(projeto)
    if not cands:
        raise RuntimeError("o vídeo não tem nenhuma imagem com tamanho para capa")
    titulo, opcoes = _textos(projeto)
    fotos = escolher_fotos(projeto, cands, titulo, log)
    while len(fotos) < 3:
        fotos.append(fotos[len(fotos) % len(fotos)])
    feitas = []
    for k, ((l1, l2), foto, layout) in enumerate(zip(opcoes, fotos, LAYOUTS), 1):
        destino = projeto.pasta / f"thumb_{k}.jpg"
        desenhar(foto, l1, l2, layout, destino)
        feitas.append({"arquivo": destino.name, "layout": layout, "l1": l1, "l2": l2,
                       "foto": Path(foto).relative_to(projeto.pasta).as_posix()})
    anterior = projeto.ler_json("thumbs.json") if projeto.existe("thumbs.json") else {}
    escolhida = int(anterior.get("escolhida") or 1)
    escolhida = escolhida if 1 <= escolhida <= len(feitas) else 1
    shutil.copyfile(projeto.pasta / f"thumb_{escolhida}.jpg", projeto.pasta / "thumbnail.jpg")
    _prancha([projeto.pasta / f["arquivo"] for f in feitas], projeto.pasta / "thumbs_prancha.jpg")
    dados = {"opcoes": feitas, "escolhida": escolhida, "thumbnail": "thumbnail.jpg", "prancha": "thumbs_prancha.jpg"}
    projeto.salvar_json("thumbs.json", dados)
    log(f"  thumbnails prontas: 3 opções e a prancha do celular em {projeto.pasta / 'thumbs_prancha.jpg'}")
    return dados


def escolher(projeto, opcao: int) -> dict:
    """A pessoa escolhe a capa: thumbnail.jpg passa a ser a opção pedida."""
    dados = projeto.ler_json("thumbs.json")
    if not 1 <= opcao <= len(dados["opcoes"]):
        raise SystemExit(f"Escolha uma opção de 1 a {len(dados['opcoes'])}.")
    shutil.copyfile(projeto.pasta / dados["opcoes"][opcao - 1]["arquivo"], projeto.pasta / "thumbnail.jpg")
    dados["escolhida"] = opcao
    projeto.salvar_json("thumbs.json", dados)
    return dados
