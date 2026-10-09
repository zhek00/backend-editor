"""O recorte do assunto da foto, no estilo colagem da Vox: o bicho sem o fundo, com a borda branca de figurinha.

Pedido do usuário em 2026-10-07: no motion do peso, "o animal em cima de uma balança mostrando 0,5 kg, estilo colagem
Vox". O recorte sai no próprio computador, de graça e sem modelo baixado: o GrabCut do OpenCV (que a fábrica já usa
para os rostos) parte de um retângulo no meio da foto e separa o que é assunto do que é fundo. Recorte que não convence
pelas contas (pouco ou quase tudo da foto, em pedaços, ou colado na borda) devolve None. Os que passam vão numa folha
para a visão escolher (motion_ia._recorte_da_cena): na primeira rodada, com as fotos do mico do 11-animais-do-brasil,
as contas aprovaram 8 de 8 e três ficaram com o fundo verde ou azul em volta. Sem recorte aprovado, o clipe usa a
foto inteira numa moldura de papel rasgado, que também é colagem.
"""
from pathlib import Path

import cv2
import numpy as np

LADO = 900          # a foto é reduzida a este lado maior antes do recorte (mais rápido, e o clipe não precisa de mais)
BORDA = 14          # a borda branca de figurinha, em px
MINIMO, MAXIMO = 0.10, 0.80   # a fração da foto que o recorte pode ocupar


def _maior_pedaco(mascara):
    n, rotulos, estat, _ = cv2.connectedComponentsWithStats(mascara, 8)
    if n <= 1:
        return None, 0.0
    areas = estat[1:, cv2.CC_STAT_AREA]
    k = int(np.argmax(areas)) + 1
    return (rotulos == k).astype(np.uint8) * 255, float(areas.max()) / float(areas.sum())


MARGENS = (0.04, 0.12, 0.22)  # o retângulo de partida do GrabCut: cada margem dá um recorte diferente


def variantes(foto, pasta) -> list:
    """Os recortes que convencem pelas contas, um por margem (recorte_1.png...), sem fundo grudado nem pontas
    (limpo). Quem escolhe entre eles é a visão (motion_ia._recorte_da_cena)."""
    saida = []
    for k, jeito in enumerate([dict(margem=m) for m in MARGENS] + [dict(margem=0.04, sem_verde=True)], 1):
        feito = recortar(foto, Path(pasta) / f"recorte_{k}.png", **jeito)
        if feito and limpo(feito):
            saida.append(feito)
    return saida


def fundo_grudado(arquivo) -> float:
    """A fração do recorte com uma cor viva muito diferente da cor principal do bicho: o fundo que ficou grudado (o
    azul do céu atrás do mico do 11-animais-do-brasil, que a visão gratuita aprovou duas vezes). Preto, branco e cinza
    não contam (pelo escuro, a borda branca da figurinha)."""
    imagem = cv2.imread(str(arquivo), cv2.IMREAD_UNCHANGED)
    if imagem is None or imagem.shape[2] < 4:
        return 0.0
    dentro = imagem[..., 3] > 200
    hsv = cv2.cvtColor(imagem[..., :3], cv2.COLOR_BGR2HSV)
    vivos = dentro & (hsv[..., 1] > 70) & (hsv[..., 2] > 60)
    if vivos.sum() < 200:
        return 0.0
    matizes = hsv[..., 0][vivos].astype(int)  # 0 a 179 no OpenCV
    contagem = np.bincount(matizes // 10, minlength=18)
    principal = int(np.argmax(contagem)) * 10 + 5
    distancia = np.minimum(np.abs(matizes - principal), 180 - np.abs(matizes - principal))
    return float((distancia > 30).sum()) / float(dentro.sum())


def pontas(arquivo) -> float:
    """Quanto do bicho some quando a borda é alisada: as folhas e gravetos espetados no recorte (o pirarucu da cena
    257 do 11-animais-do-brasil, "fica basicamente estranho"). Medido sem a borda branca da figurinha, que alisa as
    pontas: o pirarucu perdia 4%, os recortes bons de 0,1% a 1%."""
    imagem = cv2.imread(str(arquivo), cv2.IMREAD_UNCHANGED)
    if imagem is None or imagem.shape[2] < 4:
        return 0.0
    branco = (imagem[..., 0] > 245) & (imagem[..., 1] > 245) & (imagem[..., 2] > 245)
    bicho = ((imagem[..., 3] > 128) & ~branco).astype(np.uint8) * 255
    bicho, _ = _maior_pedaco(bicho)
    if bicho is None:
        return 1.0
    k = max(3, int(max(bicho.shape) * 0.03) | 1)
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    alisado = cv2.morphologyEx(cv2.morphologyEx(bicho, cv2.MORPH_OPEN, nucleo), cv2.MORPH_CLOSE, nucleo)
    return float(cv2.countNonZero(cv2.absdiff(bicho, alisado))) / float(max(cv2.countNonZero(bicho), 1))


PONTAS_MAXIMO = 0.02
FUNDO_MAXIMO = 0.04  # fundo_grudado: recortes limpos mediram de 0 a 1,7%; com fundo grudado, de 7% a 32%


def limpo(arquivo) -> bool:
    """O recorte passa nas contas de acabamento: sem fundo grudado e sem pontas espetadas."""
    return fundo_grudado(arquivo) <= FUNDO_MAXIMO and pontas(arquivo) <= PONTAS_MAXIMO


def folha(recortes, destino) -> Path:
    """Os recortes lado a lado, numerados, sobre um fundo liso que não se confunde com a foto."""
    from PIL import Image, ImageDraw, ImageFont
    lado = 420
    imagem = Image.new("RGB", (lado * len(recortes), lado + 60), (128, 140, 156))
    desenho = ImageDraw.Draw(imagem)
    fonte = ImageFont.load_default(size=44)
    for k, caminho in enumerate(recortes):
        figura = Image.open(caminho).convert("RGBA")
        figura.thumbnail((lado - 20, lado - 20))
        imagem.paste(figura, (k * lado + (lado - figura.width) // 2, 60 + (lado - figura.height) // 2), figura)
        desenho.text((k * lado + 16, 6), str(k + 1), fill=(255, 255, 255), font=fonte)
    imagem.save(destino, quality=88)
    return Path(destino)


def recortar(foto, destino, margem=0.06, caixa=None, sem_verde=False, espelhar=False, lado=LADO,
             borda=BORDA, folga=1.0) -> Path | None:
    """Grava em destino (PNG com transparência) o assunto da foto com a borda branca. None se o recorte não convence.

    caixa: onde o assunto está na foto (x0, y0, x1, y1, de 0 a 1), apontado pela visão; o GrabCut parte dela em vez
    do retângulo das margens. sem_verde: tira a vegetação que o GrabCut deixou grudada (o tufo de capim nas costas da
    ariranha da cena 191 do 11-animais-do-brasil, que só saiu à mão). espelhar: vira o recorte, para o bicho olhar
    para a direita em todo clipe de medida. lado: o lado maior da foto antes do recorte (o clipe de medida usa mais)."""
    imagem = cv2.imread(str(foto), cv2.IMREAD_COLOR)
    if imagem is None:
        return None
    alto, largo = imagem.shape[:2]
    escala = lado / max(alto, largo)
    if escala < 1:
        imagem = cv2.resize(imagem, (int(largo * escala), int(alto * escala)), interpolation=cv2.INTER_AREA)
        alto, largo = imagem.shape[:2]
    mascara = np.zeros((alto, largo), np.uint8)
    if caixa:
        x0, y0, x1, y1 = (max(0.0, min(1.0, float(v))) for v in caixa)
        # folga larga dos lados: a caixa da visão costuma começar depois da ponta da cauda (cortada reta na cena 191)
        folga_x, folga_y = (x1 - x0) * 0.10 * folga, (y1 - y0) * 0.08 * folga
        x0, y0, x1, y1 = max(0.0, x0 - folga_x), max(0.0, y0 - folga_y), min(1.0, x1 + folga_x), min(1.0, y1 + folga_y)
        retangulo = (int(x0 * largo), int(y0 * alto), max(8, int((x1 - x0) * largo)), max(8, int((y1 - y0) * alto)))
        area_ref = max((x1 - x0) * (y1 - y0), 1e-3)
    else:
        margem_x, margem_y = max(1, int(largo * margem)), max(1, int(alto * margem))
        retangulo = (margem_x, margem_y, largo - 2 * margem_x, alto - 2 * margem_y)
        area_ref = 1.0
    fundo, frente = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(imagem, mascara, retangulo, fundo, frente, 6, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    assunto = np.where((mascara == cv2.GC_FGD) | (mascara == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    if sem_verde:
        hsv = cv2.cvtColor(imagem, cv2.COLOR_BGR2HSV)
        assunto[(hsv[..., 0] > 25) & (hsv[..., 0] < 95) & (hsv[..., 1] > 55)] = 0
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    assunto = cv2.morphologyEx(cv2.morphologyEx(assunto, cv2.MORPH_OPEN, nucleo), cv2.MORPH_CLOSE, nucleo, iterations=2)
    assunto, parte = _maior_pedaco(assunto)
    if assunto is None or parte < (0.70 if sem_verde else 0.85):
        return None
    # tapa os buracos de dentro (a barriga clara, o reflexo no olho)
    contornos, _ = cv2.findContours(assunto, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    assunto = cv2.drawContours(np.zeros_like(assunto), contornos, -1, 255, cv2.FILLED)
    fracao = float((assunto > 0).mean()) / area_ref
    beirada = np.concatenate([assunto[0], assunto[-1], assunto[:, 0], assunto[:, -1]])
    if not MINIMO <= fracao <= (0.95 if caixa else MAXIMO) or float((beirada > 0).mean()) > 0.30:
        return None
    assunto = cv2.GaussianBlur(assunto, (3, 3), 0)
    if espelhar:
        imagem, assunto = cv2.flip(imagem, 1), cv2.flip(assunto, 1)
    # a borda branca de figurinha: o contorno engordado, pintado de branco por baixo do bicho
    pad = borda + 4
    imagem = cv2.copyMakeBorder(imagem, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    assunto = cv2.copyMakeBorder(assunto, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    contorno = cv2.dilate(assunto, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * borda + 1, 2 * borda + 1)))
    peso = (assunto.astype(np.float32) / 255.0)[..., None]
    cor = (imagem.astype(np.float32) * peso + 255.0 * (1 - peso)).astype(np.uint8)
    saida = np.dstack([cor, contorno])
    y, x = np.where(contorno > 0)
    saida = saida[y.min():y.max() + 1, x.min():x.max() + 1]
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    return destino if cv2.imwrite(str(destino), saida) else None
