"""Camadas desenhadas por cima das cenas: os cartões de título ([TITULO]) e o símbolo do canal ([SIMBOLO]).

Cada uma vira camadas PNG transparentes, recortadas no tamanho do desenho, e o render sobrepõe cada camada no clipe
com uma entrada suave no momento marcado.

O texto na tela (destaque, lista, capítulo e rótulo) saiu da fábrica em 2026-10-05, a pedido do usuário: era
desenhado pelo FFmpeg, ficava amador e caía por cima dos clipes de motion. O texto curto que o agente sugere (overlay)
continua, como texto da animação em camada (animacoes.py), que segue as REGRAS_QUALIDADE abaixo.
"""
import hashlib
import json
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SUPLEMENTAR = "/System/Library/Fonts/Supplemental/"
FONTES_PADRAO = {
    "documentario": {
        "destaque": SUPLEMENTAR + "Arial Black.ttf",
        "capitulo": SUPLEMENTAR + "DIN Condensed Bold.ttf",
        "rotulo": SUPLEMENTAR + "Arial Bold.ttf",
        "lista_titulo": SUPLEMENTAR + "Arial Black.ttf",
        "lista_item": SUPLEMENTAR + "Bradley Hand Bold.ttf",
        "numero": SUPLEMENTAR + "Arial Bold.ttf",
    },
    "selado": {
        "destaque": SUPLEMENTAR + "Copperplate.ttc#2",
        "capitulo": SUPLEMENTAR + "Didot.ttc#2",
        "rotulo": SUPLEMENTAR + "Copperplate.ttc#2",
        "lista_titulo": SUPLEMENTAR + "Copperplate.ttc#2",
        "lista_item": SUPLEMENTAR + "Cochin.ttc#0",
        "numero": SUPLEMENTAR + "Copperplate.ttc#2",
    },
}
ENTRADA = 0.35  # duração da animação de entrada, em segundos
ROMANOS = ("I", "II", "III", "IV", "V", "VI", "VII")


# Regras do texto curto que o agente de roteiro sugere (overlay), usado pela animação em camada (animacoes.py).
# O texto na tela desenhado pelo FFmpeg saiu da fábrica em 2026-10-05, a pedido do usuário.
REGRAS_QUALIDADE = """QUALIDADE DO TEXTO NA TELA
O texto serve para quem assiste sem som entender o ponto do trecho. Só use quando o trecho traz um FATO que vale fixar; a maioria dos trechos fica sem texto.
Um bom texto tem fundamento: diz QUEM ou O QUÊ junto com o dado que importa, de 3 a 8 palavras, com as palavras da própria narração do trecho.
Use para:
- número, data, medida ou estatística junto do que ela mede: "700 MILHÕES DE ANOS-LUZ", "1 CÔVADO = COTOVELO ATÉ O DEDO MÉDIO", "VIVE DE 12 A 15 ANOS"
- nome próprio com a identificação dele: "SGR 1806-20 · MAGNETAR", "IRVING FINKEL · MUSEU BRITÂNICO", "DURUPINAR · TURQUIA, 1948"
- a entrada de um item de lista ou contagem, sempre com o nome do item: "Nº 10 · PETAURO-DO-AÇÚCAR"
- a revelação ou conclusão do trecho: "O MAMÍFERO MAIS TRAFICADO DO PLANETA"
Nunca:
- metadados do vídeo ou do roteiro: "PARTE 2", "INTRODUÇÃO", "NÚMERO 8" sem o nome do item, "TERCEIRO", "VAMOS COMEÇAR"
- uma palavra solta, um lugar sozinho ou um pedaço de frase sem dado: "BETUME", "TASMÂNIA", "JUNCO E CORDA", "PRIMEIRO EXEMPLAR NA INGLATERRA"
- palavras que a narração do trecho não diz, nem grafias inventadas: copie a grafia exata do roteiro
- opinião, pergunta ou frase de efeito vazia: "INACREDITÁVEL", "VOCÊ SABIA?", "ASSUSTADOR"
Na dúvida, deixe sem texto: um texto fraco é pior que nenhum."""

def assinatura_simbolos(simbolos, perfil) -> str:
    cfg = perfil.get("simbolo") or {}
    if not simbolos or not cfg.get("imagem"):
        return ""
    from .config import caminho_relativo

    arquivo = caminho_relativo(cfg["imagem"])
    carimbo = arquivo.stat().st_mtime_ns if arquivo.exists() else 0
    dados = json.dumps([simbolos, cfg, carimbo], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(dados.encode()).hexdigest()[:10]


def assinatura_titulos(titulos, perfil) -> str:
    if not titulos:
        return ""
    dados = json.dumps([titulos, perfil.get("titulos"), perfil.get("textos_na_tela")], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(dados.encode()).hexdigest()[:10]


def camadas_titulo(titulos, perfil, pasta, duracao, largura=1920, altura=1080):
    """Título de uma parte da aula. Um cartão centralizado que surge devagar e some sozinho."""
    if not titulos:
        return []
    cfg = perfil.get("titulos") or {}
    tema = (perfil.get("textos_na_tela") or {}).get("tema", "documentario")
    cores = perfil.get("textos_na_tela") or {}
    escala = largura / 1920
    transicao = float(cfg.get("transicao", 0.8))
    duracao_titulo = float(cfg.get("duracao", 7))
    if tema == "selado":
        ouro, creme, painel_cor = _cores(cores)
    else:
        ouro, creme, painel_cor = cores.get("cor_destaque", "#D32F2F"), "#FFFFFF", (0, 0, 0, 200)
    fonte_titulo = _fonte({"tema": tema, "fontes": cores.get("fontes")}, "lista_item" if tema == "selado" else "lista_titulo", 64 * escala)
    fonte_parte = _fonte({"tema": tema, "fontes": cores.get("fontes")}, "rotulo", 24 * escala)
    pasta.mkdir(parents=True, exist_ok=True)
    resultado = []
    for k, t in enumerate(titulos):
        inicio = float(t["inicio"])
        fim = min(inicio + duracao_titulo, duracao - 0.2)
        if fim - inicio < transicao or not (t.get("texto") or "").strip():
            continue
        linhas = _quebrar(t["texto"].strip(), fonte_titulo, largura * 0.5)
        parte = f"PARTE {ROMANOS[t['numero'] - 1] if 0 < t.get('numero', 0) <= len(ROMANOS) else t.get('numero', '')}" if cfg.get("numerar", True) else ""
        tracking = 5 * escala
        folga_x, folga_y = 60 * escala, 44 * escala
        altura_linha = fonte_titulo.size * 1.2
        largura_texto = max([fonte_titulo.getlength(l) for l in linhas] + [_largura_espacada(parte, fonte_parte, tracking)])
        altura_cabecalho = (fonte_parte.size + 34 * escala) if parte else 0
        largura_cartao = largura_texto + folga_x * 2
        altura_cartao = altura_cabecalho + len(linhas) * altura_linha + folga_y * 2
        x0 = (largura - largura_cartao) / 2
        y0 = altura * 0.42 - altura_cartao / 2

        camada = _tela(largura, altura)
        sombra = _tela(largura, altura)
        ImageDraw.Draw(sombra).rounded_rectangle([x0 + 6 * escala, y0 + 12 * escala, x0 + largura_cartao + 6 * escala, y0 + altura_cartao + 12 * escala],
                                                 radius=18 * escala, fill=(0, 0, 0, 160))
        camada = Image.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(18 * escala)), camada)
        desenho = ImageDraw.Draw(camada)
        desenho.rounded_rectangle([x0, y0, x0 + largura_cartao, y0 + altura_cartao], radius=18 * escala, fill=painel_cor,
                                  outline=_rgba(ouro, 210) if tema == "selado" else None, width=max(1, round(2 * escala)))
        centro = largura / 2
        y = y0 + folga_y
        if parte:
            _escrever_espacado(desenho, centro - _largura_espacada(parte, fonte_parte, tracking) / 2, y, parte, fonte_parte, ouro, tracking)
            _ornamento(desenho, centro, y + fonte_parte.size + 16 * escala, min(largura_cartao * 0.5, 320 * escala), _rgba(ouro, 235), escala)
            y += altura_cabecalho
        for linha in linhas:
            desenho.text((centro - fonte_titulo.getlength(linha) / 2, y), linha, font=fonte_titulo, fill=creme)
            y += altura_linha
        arquivo = pasta / f"titulo_{k}.png"
        camada.save(arquivo)
        resultado.append({"arquivo": arquivo, "x": 0, "y": 0, "inicio": round(inicio, 3), "fim": round(fim, 3),
                          "transicao": transicao, "animacao": "subir"})
    return resultado


def camadas_simbolo(simbolos, perfil, pasta, duracao, largura=1920, altura=1080):
    """O símbolo de pausa do roteiro. Uma imagem PNG do perfil que surge devagar e some sozinha."""
    cfg = perfil.get("simbolo") or {}
    if not simbolos or not cfg.get("imagem"):
        return []
    from .config import caminho_relativo

    arquivo = caminho_relativo(cfg["imagem"])
    if not arquivo.exists():
        raise SystemExit(f"Imagem do símbolo não encontrada em {arquivo}")
    tamanho = round(largura * float(cfg.get("largura", 0.12)))
    transicao = float(cfg.get("transicao", 0.6))
    duracao_simbolo = float(cfg.get("duracao", 6))
    margem = round(float(cfg.get("margem", 70)) * largura / 1920)
    with Image.open(arquivo) as imagem:
        imagem = imagem.convert("RGBA")
        imagem.thumbnail((tamanho, tamanho))
        pasta.mkdir(parents=True, exist_ok=True)
        desenho = pasta / "simbolo.png"
        imagem.save(desenho)
        l, a = imagem.size
    posicao = cfg.get("posicao", "centro")
    x = {"centro": (largura - l) // 2, "esquerda": margem, "direita": largura - l - margem}.get(posicao.split("-")[-1], (largura - l) // 2)
    y = {"centro": (altura - a) // 2, "superior": margem, "inferior": altura - a - margem}.get(posicao.split("-")[0], (altura - a) // 2)
    resultado = []
    for inicio in simbolos:
        fim = min(inicio + duracao_simbolo, duracao - 0.2)
        if fim - inicio < transicao:
            continue
        resultado.append({"arquivo": desenho, "x": x, "y": y, "inicio": round(inicio, 3), "fim": round(fim, 3),
                          "transicao": transicao, "animacao": "surgir"})
    return resultado


def para_vertical(camadas_horizontais, largura, altura, pasta, prefixo="v"):
    """Leva camadas desenhadas para a tela deitada (1920x1080) para a tela em pé (1080x1920).

    Os desenhos de cada tema foram pensados para a tela deitada: em vez de refazer cada um, o grupo inteiro de
    camadas (o cartão e os itens de uma lista andam juntos) é reduzido só o necessário para caber na largura,
    centralizado, e levado para a faixa do meio da tela, longe da legenda e dos botões do Shorts e do Reels."""
    if not camadas_horizontais:
        return []
    recortadas = []
    for camada in camadas_horizontais:
        with Image.open(camada["arquivo"]) as imagem:
            imagem = imagem.convert("RGBA")
            caixa = imagem.getbbox()
            if not caixa:
                continue
            recortadas.append((camada, imagem.crop(caixa), camada["x"] + caixa[0], camada["y"] + caixa[1]))
    if not recortadas:
        return []
    x0 = min(x for _, _, x, _ in recortadas)
    y0 = min(y for _, _, _, y in recortadas)
    x1 = max(x + img.width for _, img, x, _ in recortadas)
    y1 = max(y + img.height for _, img, _, y in recortadas)
    escala = min(1.0, largura * 0.9 / max(x1 - x0, 1), altura * 0.45 / max(y1 - y0, 1))
    # o centro do grupo segue a altura que tinha na tela deitada, preso entre 22% e 62% da tela em pé
    centro = min(max((y0 + y1) / 2 / 1080, 0.22), 0.62) * altura
    novo_x0 = (largura - (x1 - x0) * escala) / 2
    novo_y0 = centro - (y1 - y0) * escala / 2
    pasta.mkdir(parents=True, exist_ok=True)
    resultado = []
    for k, (camada, imagem, x, y) in enumerate(recortadas):
        if escala < 0.999:
            imagem = imagem.resize((max(1, round(imagem.width * escala)), max(1, round(imagem.height * escala))), Image.LANCZOS)
        arquivo = pasta / f"{prefixo}_{k}.png"
        imagem.save(arquivo)
        resultado.append({**camada, "arquivo": arquivo, "x": round(novo_x0 + (x - x0) * escala),
                          "y": round(novo_y0 + (y - y0) * escala)})
    return resultado


# ferramentas de desenho

# Fontes do Windows usadas quando a fonte do Mac não existe. A fonte padrão do Pillow não tem
# acentos como Ã e Á, que saem como quadrados.
VERSAO_FONTES = 2  # sobe quando a escolha de fontes muda, para o render refazer os textos já prontos
PASTA_WINDOWS = "C:/Windows/Fonts/"
FONTES_WINDOWS = {
    "documentario": {
        "destaque": ["ariblk.ttf", "arialbd.ttf"],
        "capitulo": ["bahnschrift.ttf", "arialbd.ttf"],
        "rotulo": ["arialbd.ttf"],
        "lista_titulo": ["ariblk.ttf", "arialbd.ttf"],
        "lista_item": ["segoepr.ttf", "arial.ttf"],
        "numero": ["arialbd.ttf"],
    },
    "selado": {nome: ["georgiab.ttf", "georgia.ttf"] for nome in ("destaque", "capitulo", "rotulo", "lista_titulo", "lista_item", "numero")},
}


def _fonte(cfg, nome, tamanho):
    tema = cfg.get("tema", "documentario")
    valor = (cfg.get("fontes") or {}).get(nome) or FONTES_PADRAO.get(tema, {}).get(nome) or FONTES_PADRAO["documentario"][nome]
    caminho, _, indice = str(valor).partition("#")
    tamanho = max(8, round(tamanho))
    try:
        return ImageFont.truetype(caminho, tamanho, index=int(indice or 0))
    except OSError:
        pass
    for arquivo in FONTES_WINDOWS.get(tema, FONTES_WINDOWS["documentario"]).get(nome, []):
        try:
            return ImageFont.truetype(PASTA_WINDOWS + arquivo, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(tamanho)


def _tela(largura, altura):
    return Image.new("RGBA", (largura, altura), (0, 0, 0, 0))


def _rgba(cor, alfa=255):
    cor = cor.lstrip("#")
    return tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4)) + (alfa,)


def _quebrar(texto, fonte, largura_maxima):
    linhas, atual = [], ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}".strip()
        if atual and fonte.getlength(tentativa) > largura_maxima:
            linhas.append(atual)
            atual = palavra
        else:
            atual = tentativa
    return linhas + ([atual] if atual else [])


def _largura_espacada(texto, fonte, espaco):
    return sum(fonte.getlength(letra) for letra in texto) + espaco * max(len(texto) - 1, 0)


def _escrever_espacado(desenho, x, y, texto, fonte, cor, espaco):
    for letra in texto:
        desenho.text((x, y), letra, font=fonte, fill=cor)
        x += fonte.getlength(letra) + espaco


def _ornamento(desenho, centro_x, y, largura, cor, escala):
    """Linha dourada com um losango no meio."""
    raio = 6 * escala
    espessura = max(1, round(2 * escala))
    desenho.line([(centro_x - largura / 2, y), (centro_x - raio * 2, y)], fill=cor, width=espessura)
    desenho.line([(centro_x + raio * 2, y), (centro_x + largura / 2, y)], fill=cor, width=espessura)
    desenho.polygon([(centro_x, y - raio), (centro_x + raio, y), (centro_x, y + raio), (centro_x - raio, y)], fill=cor)


def _cores(cfg):
    return cfg.get("cor_ouro", "#C9A45C"), cfg.get("cor_texto", "#F2E8D5"), _rgba(cfg.get("cor_painel", "#0C0906"), 215)


