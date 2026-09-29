"""Textos animados por cima das cenas.

Tipos
destaque   frase grande com palavras em evidência
lista      cartão com título e itens que surgem quando são narrados
capitulo   referência grande no canto de baixo, como CAP 104
rotulo     etiqueta pequena com o nome de um livro ou fonte citada

Temas
documentario   letras brancas grossas e caixa vermelha
selado         preto translúcido, dourado e letras com serifa, na identidade do O Livro Selado

Cada texto vira camadas PNG transparentes, recortadas no tamanho do desenho.
O render sobrepõe cada camada no clipe com uma entrada suave no momento marcado.
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
TIPOS = ("destaque", "lista", "capitulo", "rotulo")
ENTRADA = 0.35  # duração da animação de entrada, em segundos
ROMANOS = ("I", "II", "III", "IV", "V", "VI", "VII")


def ativo(perfil) -> bool:
    return bool((perfil.get("textos_na_tela") or {}).get("ativo"))


# As mesmas regras valem para o agente de roteiro (overlay) e para a passada dos textos na tela.
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

# texto que só diz em que parte do vídeo estamos, sem dizer nada do assunto
_METADADO = re.compile(
    r"^(parte|part|episodio|ep|capitulo|cap|numero|n|no|top|lista|item|primeiro|primeira|segundo|segunda|terceiro|"
    r"terceira|quarto|quarta|quinto|quinta|sexto|setimo|oitavo|nono|decimo|ultimo|ultima|final|introducao|conclusao|"
    r"inicio|fim|vamos comecar|continua)\b[\s\d.ºª°#:-]*$")


def _normal(texto):
    import unicodedata

    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().casefold()


def palavras_normais(texto) -> list:
    return re.findall(r"[a-z]+", _normal(texto))


def _foi_falada(palavra, faladas):
    """A palavra está na narração, aceitando plural e flexões (mordida/mordidas, apagar/apagariam).

    Basta as duas dividirem a mesma raiz de pelo menos 5 letras (ou a palavra inteira, se for mais curta)."""
    if palavra in faladas:
        return True
    raiz = palavra[:max(4, min(len(palavra) - 1, 6))] if len(palavra) > 5 else palavra[:4]
    return any(f.startswith(raiz) and abs(len(f) - len(palavra)) <= 4 for f in faladas if len(f) >= 4)


def motivo_para_recusar(texto_tela, faladas) -> str:
    """Por que um texto na tela não tem fundamento, ou "" se ele vale. faladas: palavras normalizadas da narração
    da cena e das vizinhas. Barra metadados ("PARTE 2"), palavra solta sem número e palavra que não foi falada."""
    tipo = texto_tela.get("tipo")
    if tipo == "lista":
        partes = [texto_tela.get("titulo") or ""] + [i.get("texto") or "" for i in texto_tela.get("itens") or []]
    elif tipo == "rotulo":
        partes = [texto_tela.get("titulo") or texto_tela.get("texto") or ""]
    elif tipo == "capitulo":
        # "CAP 104" com o nome do livro vale; "NÚMERO 8" ou "TERCEIRO" sem dizer do que se trata, não
        if not (texto_tela.get("titulo") or "").strip() and _METADADO.match(_normal(texto_tela.get("texto")).strip()):
            return "só diz a parte do vídeo, sem o assunto"
        partes = [texto_tela.get("titulo") or ""]
    else:
        partes = [texto_tela.get("texto") or ""]
    principal = " ".join(p for p in partes if p).strip()
    if not principal:
        return "vazio"
    normal = _normal(principal).strip()
    if tipo != "capitulo":
        if _METADADO.match(normal) or re.search(r"\bparte\s*\d+\b", normal):
            return "só diz a parte do vídeo, sem o assunto"
        if len(palavras_normais(principal)) <= 1 and not re.search(r"\d", principal):
            return "palavra solta, sem dado"
    faladas = set(faladas)
    for palavra in palavras_normais(principal):
        if len(palavra) >= 4 and not _foi_falada(palavra, faladas):
            return f"'{palavra}' não foi falada nesse trecho"
    return ""


def assinatura(texto_tela, perfil) -> str:
    if not texto_tela:
        return ""
    dados = json.dumps([texto_tela, perfil.get("textos_na_tela"), VERSAO_FONTES], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(dados.encode()).hexdigest()[:10]


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


def camadas(texto_tela, perfil, pasta, duracao, largura=1920, altura=1080):
    """Desenha as camadas e devolve arquivo, posição, momento de entrada e tipo de animação de cada uma."""
    if not texto_tela or texto_tela.get("tipo") not in TIPOS:
        return []
    cfg = perfil.get("textos_na_tela") or {}
    tema = cfg.get("tema", "documentario")
    desenhar = DESENHOS.get(tema, DESENHOS["documentario"])[texto_tela["tipo"]]
    escala = largura / 1920
    pasta.mkdir(parents=True, exist_ok=True)
    limite = max(0.0, duracao - ENTRADA - 0.3)
    resultado = []
    for i, (imagem, inicio, animacao) in enumerate(desenhar(texto_tela, cfg, escala, largura, altura)):
        caixa = imagem.getbbox()
        if not caixa:
            continue
        arquivo = pasta / f"camada_{i}.png"
        imagem.crop(caixa).save(arquivo)
        resultado.append({
            "arquivo": arquivo, "x": caixa[0], "y": caixa[1],
            "inicio": round(min(max(inicio, 0.0), limite), 3), "animacao": animacao,
        })
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


def _com_sombra(largura, altura, desenho, raio, opacidade=190):
    """Desenha a mesma coisa em preto desfocado por baixo, para o texto ler sobre qualquer imagem."""
    sombra = _tela(largura, altura)
    desenho(ImageDraw.Draw(sombra), (0, 0, 0, opacidade))
    sombra = sombra.filter(ImageFilter.GaussianBlur(raio))
    frente = _tela(largura, altura)
    desenho(ImageDraw.Draw(frente), None)
    return Image.alpha_composite(sombra, frente)


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


def _limpar(palavra):
    return re.sub(r"[^\w]", "", palavra).casefold()


def _palavras_marcadas(palavras, destaque):
    """Índices das palavras do texto que formam o trecho em destaque."""
    alvo = [_limpar(p) for p in destaque.split() if _limpar(p)]
    limpas = [_limpar(p) for p in palavras]
    if not alvo:
        return set()
    for k in range(len(limpas) - len(alvo) + 1):
        if limpas[k:k + len(alvo)] == alvo:
            return set(range(k, k + len(alvo)))
    return {i for i, p in enumerate(limpas) if p in alvo and len(p) > 3}


# tema documentario

def _destaque(t, cfg, escala, largura, altura):
    fonte = _fonte(cfg, "destaque", 76 * escala)
    palavras = t["texto"].upper().split()
    marcadas = _palavras_marcadas(palavras, t.get("destaque", ""))
    espaco = fonte.getlength(" ")
    altura_linha = fonte.size * 1.25
    largura_maxima = largura * 0.52

    linhas, atual, ocupado = [], [], 0.0
    for i, palavra in enumerate(palavras):
        w = fonte.getlength(palavra)
        if atual and ocupado + espaco + w > largura_maxima:
            linhas.append(atual)
            atual, ocupado = [], 0.0
        ocupado += (espaco if atual else 0) + w
        atual.append((i, palavra, w))
    if atual:
        linhas.append(atual)

    topo = (altura - len(linhas) * altura_linha) / 2 - 40 * escala
    posicoes = []
    for n, linha in enumerate(linhas):
        x = 110 * escala
        for i, palavra, w in linha:
            posicoes.append((i, palavra, x, topo + n * altura_linha, w))
            x += w + espaco

    def escrever(desenho, cor):
        for _, palavra, x, y, _ in posicoes:
            desenho.text((x, y), palavra, font=fonte, fill=cor or "white")

    texto = _com_sombra(largura, altura, escrever, 10 * escala)
    inicio = t.get("inicio", 0.0)
    resultado = [(texto, inicio, "subir")]
    if marcadas:
        caixa = _tela(largura, altura)
        desenho = ImageDraw.Draw(caixa)
        folga = 10 * escala
        for i, palavra, x, y, w in posicoes:
            if i in marcadas:
                _, cima, _, baixo = fonte.getbbox(palavra)
                desenho.rectangle([x - folga, y + cima - folga, x + w + folga, y + baixo + folga],
                                  fill=cfg.get("cor_destaque", "#D32F2F"))
                desenho.text((x, y), palavra, font=fonte, fill="white")
        resultado.append((caixa, inicio + 0.45, "surgir"))
    return resultado


def _lista(t, cfg, escala, largura, altura):
    cor = cfg.get("cor_destaque", "#D32F2F")
    x0, y0, largura_cartao = largura * (0.06 if cfg.get("lista_lado") == "esquerda" else 0.60), altura * 0.14, largura * 0.34
    folga, lado_caixa, barra = 28 * escala, 30 * escala, 72 * escala
    tamanho_item = 38 * escala

    for _ in range(5):
        fonte_item = _fonte(cfg, "lista_item", tamanho_item)
        largura_texto = largura_cartao - folga * 2 - lado_caixa - 18 * escala
        itens, y = [], y0 + barra + folga
        for item in t["itens"]:
            linhas = _quebrar(item["texto"], fonte_item, largura_texto)
            h = len(linhas) * fonte_item.size * 1.15
            itens.append((item, linhas, y))
            y += h + 20 * escala
        fim = y - 20 * escala + folga
        if fim < altura - 150 * escala:
            break
        tamanho_item *= 0.85

    cartao = _tela(largura, altura)
    sombra = _tela(largura, altura)
    ImageDraw.Draw(sombra).rectangle([x0 + 10 * escala, y0 + 14 * escala, x0 + largura_cartao + 10 * escala, fim + 14 * escala],
                                     fill=(0, 0, 0, 150))
    cartao = Image.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(12 * escala)), cartao)
    desenho = ImageDraw.Draw(cartao)
    desenho.rectangle([x0, y0, x0 + largura_cartao, fim], fill=cfg.get("cor_papel", "#F1E9DB"))
    desenho.rectangle([x0, y0, x0 + largura_cartao, y0 + barra], fill=cor)
    fonte_titulo = _fonte(cfg, "lista_titulo", 30 * escala)
    titulo = t.get("titulo", "").upper()
    while titulo and fonte_titulo.getlength(titulo) > largura_cartao - folga * 2 and fonte_titulo.size > 16:
        fonte_titulo = _fonte(cfg, "lista_titulo", fonte_titulo.size * 0.9)
    _, cima, _, baixo = fonte_titulo.getbbox(titulo or "A")
    desenho.text((x0 + folga, y0 + (barra - (baixo + cima)) / 2), titulo, font=fonte_titulo, fill="white")

    inicio = t.get("inicio", 0.0)
    resultado = [(cartao, inicio, "subir")]
    anterior = inicio + 0.4
    for item, linhas, y in itens:
        camada = _tela(largura, altura)
        desenho = ImageDraw.Draw(camada)
        bx, by = x0 + folga, y + 6 * escala
        desenho.rectangle([bx, by, bx + lado_caixa, by + lado_caixa], outline="#2B2B2B", width=max(2, round(3 * escala)))
        desenho.line([(bx + 5 * escala, by + 15 * escala), (bx + 13 * escala, by + 25 * escala), (bx + 34 * escala, by - 4 * escala)],
                     fill=cor, width=max(3, round(6 * escala)), joint="curve")
        for k, linha in enumerate(linhas):
            desenho.text((bx + lado_caixa + 18 * escala, y + k * fonte_item.size * 1.15), linha, font=fonte_item, fill="#2B2B2B")
        anterior = max(item.get("inicio", 0.0), anterior)
        resultado.append((camada, anterior, "esquerda"))
        anterior += 0.3
    return resultado


def _capitulo(t, cfg, escala, largura, altura):
    fonte = _fonte(cfg, "capitulo", 150 * escala)
    fonte_titulo = _fonte(cfg, "rotulo", 30 * escala)
    texto = t["texto"].upper()
    _, cima, _, baixo = fonte.getbbox(texto)
    x, y = 80 * escala, altura - 170 * escala - baixo

    def escrever(desenho, cor):
        desenho.text((x, y), texto, font=fonte, fill=cor or "white")
        if t.get("titulo"):
            desenho.text((x + 6 * escala, y + cima - fonte_titulo.size - 12 * escala), t["titulo"].upper(),
                         font=fonte_titulo, fill=cor or "white")

    return [(_com_sombra(largura, altura, escrever, 10 * escala), t.get("inicio", 0.0), "esquerda")]


def _rotulo(t, cfg, escala, largura, altura):
    fonte = _fonte(cfg, "rotulo", 30 * escala)
    texto = (t.get("titulo") or t.get("texto") or "").upper()
    folga_x, folga_y = 18 * escala, 12 * escala
    x, y = 60 * escala, 56 * escala
    _, cima, direita, baixo = fonte.getbbox(texto)
    camada = _tela(largura, altura)
    desenho = ImageDraw.Draw(camada)
    desenho.rectangle([x, y, x + direita + folga_x * 2, y + (baixo - cima) + folga_y * 2], fill=cfg.get("cor_rotulo", "#111111"))
    desenho.text((x + folga_x, y + folga_y - cima), texto, font=fonte, fill=cfg.get("cor_texto_rotulo", "#FFFFFF"))
    return [(camada, t.get("inicio", 0.0), "surgir")]


# tema selado

def _cores(cfg):
    return cfg.get("cor_ouro", "#C9A45C"), cfg.get("cor_texto", "#F2E8D5"), _rgba(cfg.get("cor_painel", "#0C0906"), 215)


def _selado_destaque(t, cfg, escala, largura, altura):
    ouro, creme, _ = _cores(cfg)
    fonte = _fonte(cfg, "destaque", 72 * escala)
    tracking = 2 * escala
    palavras = t["texto"].upper().split()
    marcadas = _palavras_marcadas(palavras, t.get("destaque", ""))
    espaco = fonte.getlength(" ") + tracking * 2
    altura_linha = fonte.size * 1.3
    largura_maxima = largura * 0.5
    margem = 150 * escala

    linhas, atual, ocupado = [], [], 0.0
    for i, palavra in enumerate(palavras):
        w = _largura_espacada(palavra, fonte, tracking)
        if atual and ocupado + espaco + w > largura_maxima:
            linhas.append(atual)
            atual, ocupado = [], 0.0
        ocupado += (espaco if atual else 0) + w
        atual.append((i, palavra, w))
    if atual:
        linhas.append(atual)

    topo = (altura - len(linhas) * altura_linha) / 2 - 40 * escala
    posicoes = []
    for n, linha in enumerate(linhas):
        x = margem
        for i, palavra, w in linha:
            posicoes.append((i, palavra, x, topo + n * altura_linha, w))
            x += w + espaco

    barra = _tela(largura, altura)
    ImageDraw.Draw(barra).rectangle(
        [margem - 42 * escala, topo + 6 * escala, margem - 36 * escala, topo + len(linhas) * altura_linha - 18 * escala],
        fill=_rgba(ouro, 235))

    def escrever(desenho, cor):
        for _, palavra, x, y, _ in posicoes:
            _escrever_espacado(desenho, x, y, palavra, fonte, cor or creme, tracking)

    texto = _com_sombra(largura, altura, escrever, 12 * escala, 210)
    inicio = t.get("inicio", 0.0)
    resultado = [(barra, inicio, "surgir"), (texto, inicio + 0.1, "subir")]
    if marcadas:
        brilho = _tela(largura, altura)
        desenho = ImageDraw.Draw(brilho)
        for i, palavra, x, y, w in posicoes:
            if i in marcadas:
                _escrever_espacado(desenho, x, y, palavra, fonte, ouro, tracking)
                base = y + fonte.size * 1.08
                desenho.line([(x, base), (x + w, base)], fill=_rgba(ouro, 230), width=max(2, round(3 * escala)))
        resultado.append((brilho, inicio + 0.55, "surgir"))
    return resultado


def _selado_lista(t, cfg, escala, largura, altura):
    ouro, creme, painel_cor = _cores(cfg)
    largura_cartao = largura * 0.33
    x0 = largura * (0.05 if cfg.get("lista_lado") == "esquerda" else 0.62)  # à esquerda quando o avatar ocupa a direita
    folga = 42 * escala
    coluna_numero = 60 * escala
    tracking_titulo = 4 * escala
    fonte_numero = _fonte(cfg, "numero", 32 * escala)
    fonte_titulo = _fonte(cfg, "lista_titulo", 30 * escala)
    titulo = t.get("titulo", "").upper()
    while titulo and _largura_espacada(titulo, fonte_titulo, tracking_titulo) > largura_cartao - folga * 2 and fonte_titulo.size > 16:
        fonte_titulo = _fonte(cfg, "lista_titulo", fonte_titulo.size * 0.92)
    altura_titulo = fonte_titulo.size * 1.1

    tamanho_item = 40 * escala
    for _ in range(5):
        fonte_item = _fonte(cfg, "lista_item", tamanho_item)
        largura_texto = largura_cartao - folga * 2 - coluna_numero
        itens, y = [], folga + altura_titulo + 44 * escala
        for n, item in enumerate(t["itens"]):
            linhas = _quebrar(item["texto"].capitalize(), fonte_item, largura_texto)
            h = len(linhas) * fonte_item.size * 1.2
            itens.append((n, item, linhas, y, h))
            y += h + 28 * escala
        altura_cartao = y - 28 * escala + folga
        if altura_cartao < altura * 0.72:
            break
        tamanho_item *= 0.88
    y0 = (altura - altura_cartao) / 2 - 30 * escala
    raio = 18 * escala

    painel = _tela(largura, altura)
    sombra = _tela(largura, altura)
    ImageDraw.Draw(sombra).rounded_rectangle(
        [x0 + 8 * escala, y0 + 16 * escala, x0 + largura_cartao + 8 * escala, y0 + altura_cartao + 16 * escala], radius=raio, fill=(0, 0, 0, 170))
    painel = Image.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(20 * escala)), painel)
    desenho = ImageDraw.Draw(painel)
    desenho.rounded_rectangle([x0, y0, x0 + largura_cartao, y0 + altura_cartao], radius=raio, fill=painel_cor,
                              outline=_rgba(ouro, 210), width=max(2, round(2 * escala)))
    recuo = 10 * escala
    desenho.rounded_rectangle([x0 + recuo, y0 + recuo, x0 + largura_cartao - recuo, y0 + altura_cartao - recuo],
                              radius=raio * 0.6, outline=_rgba(ouro, 70), width=1)

    cabecalho = _tela(largura, altura)
    desenho = ImageDraw.Draw(cabecalho)
    centro = x0 + largura_cartao / 2
    largura_titulo = _largura_espacada(titulo, fonte_titulo, tracking_titulo)
    _escrever_espacado(desenho, centro - largura_titulo / 2, y0 + folga - 6 * escala, titulo, fonte_titulo, ouro, tracking_titulo)
    _ornamento(desenho, centro, y0 + folga + altura_titulo + 16 * escala, largura_cartao * 0.6, _rgba(ouro, 235), escala)

    inicio = t.get("inicio", 0.0)
    resultado = [(painel, inicio, "surgir"), (cabecalho, inicio + 0.2, "subir")]
    anterior = inicio + 0.6
    for n, item, linhas, y, h in itens:
        camada = _tela(largura, altura)
        desenho = ImageDraw.Draw(camada)
        topo_item = y0 + y
        numero = ROMANOS[n] if n < len(ROMANOS) else str(n + 1)
        desenho.text((x0 + folga, topo_item + 8 * escala), numero, font=fonte_numero, fill=ouro)
        for k, linha in enumerate(linhas):
            desenho.text((x0 + folga + coluna_numero, topo_item + k * fonte_item.size * 1.2), linha, font=fonte_item, fill=creme)
        if n < len(itens) - 1:
            base = topo_item + h + 14 * escala
            desenho.line([(x0 + folga + coluna_numero, base), (x0 + largura_cartao - folga, base)], fill=_rgba(ouro, 60), width=1)
        anterior = max(item.get("inicio", 0.0), anterior)
        resultado.append((camada, anterior, "esquerda"))
        anterior += 0.3
    return resultado


def _selado_capitulo(t, cfg, escala, largura, altura):
    ouro, creme, _ = _cores(cfg)
    fonte_numero = _fonte(cfg, "capitulo", 140 * escala)
    fonte_pequena = _fonte(cfg, "rotulo", 26 * escala)
    tracking = 6 * escala
    texto = t["texto"].upper()
    achado = re.match(r"\s*CAP(?:[IÍ]TULO)?\.?\s*(.+)", texto)
    numero = achado.group(1).strip() if achado else texto
    partes = [p for p in (t.get("titulo", "").upper(), "CAPÍTULO" if achado else "") if p]
    linha_topo = "  ·  ".join(partes)

    _, cima, _, baixo = fonte_numero.getbbox(numero)
    x = 90 * escala
    y_numero = altura - 175 * escala - baixo
    y_regua = y_numero + cima - 22 * escala
    y_topo = y_regua - fonte_pequena.size - 16 * escala
    largura_numero = fonte_numero.getlength(numero)
    largura_topo = _largura_espacada(linha_topo, fonte_pequena, tracking)
    largura_regua = max(largura_numero, largura_topo)

    def escrever(desenho, cor):
        if linha_topo:
            _escrever_espacado(desenho, x + 4 * escala, y_topo, linha_topo, fonte_pequena, cor or ouro, tracking)
        desenho.line([(x + 4 * escala, y_regua), (x + largura_regua, y_regua)], fill=cor or _rgba(ouro, 220),
                     width=max(1, round(2 * escala)))
        desenho.text((x, y_numero), numero, font=fonte_numero, fill=cor or creme)

    return [(_com_sombra(largura, altura, escrever, 12 * escala, 200), t.get("inicio", 0.0), "esquerda")]


def _selado_rotulo(t, cfg, escala, largura, altura):
    ouro, _, painel_cor = _cores(cfg)
    fonte = _fonte(cfg, "rotulo", 24 * escala)
    tracking = 5 * escala
    texto = (t.get("titulo") or t.get("texto") or "").upper()
    folga_x, folga_y = 24 * escala, 14 * escala
    x, y = 60 * escala, 56 * escala
    _, cima, _, baixo = fonte.getbbox("A")
    largura_texto = _largura_espacada(texto, fonte, tracking)
    camada = _tela(largura, altura)
    desenho = ImageDraw.Draw(camada)
    desenho.rounded_rectangle([x, y, x + largura_texto + folga_x * 2, y + (baixo - cima) + folga_y * 2], radius=8 * escala,
                              fill=painel_cor, outline=_rgba(ouro, 200), width=max(1, round(2 * escala)))
    _escrever_espacado(desenho, x + folga_x, y + folga_y - cima, texto, fonte, ouro, tracking)
    return [(camada, t.get("inicio", 0.0), "surgir")]


DESENHOS = {
    "documentario": {"destaque": _destaque, "lista": _lista, "capitulo": _capitulo, "rotulo": _rotulo},
    "selado": {"destaque": _selado_destaque, "lista": _selado_lista, "capitulo": _selado_capitulo, "rotulo": _selado_rotulo},
}
