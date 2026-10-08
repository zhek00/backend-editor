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
    """Os recortes que convencem pelas contas, um por margem (recorte_1.png...). Quem escolhe é a visão
    (motion_ia._recorte_da_cena): as contas não veem o fundo que sobrou entre os galhos."""
    saida = []
    for k, margem in enumerate(MARGENS, 1):
        feito = recortar(foto, Path(pasta) / f"recorte_{k}.png", margem)
        if feito:
            saida.append(feito)
    return saida


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


def recortar(foto, destino, margem=0.06) -> Path | None:
    """Grava em destino (PNG com transparência) o assunto da foto com a borda branca. None se o recorte não convence."""
    imagem = cv2.imread(str(foto), cv2.IMREAD_COLOR)
    if imagem is None:
        return None
    alto, largo = imagem.shape[:2]
    escala = LADO / max(alto, largo)
    if escala < 1:
        imagem = cv2.resize(imagem, (int(largo * escala), int(alto * escala)), interpolation=cv2.INTER_AREA)
        alto, largo = imagem.shape[:2]
    mascara = np.zeros((alto, largo), np.uint8)
    margem_x, margem_y = max(1, int(largo * margem)), max(1, int(alto * margem))
    retangulo = (margem_x, margem_y, largo - 2 * margem_x, alto - 2 * margem_y)
    fundo, frente = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(imagem, mascara, retangulo, fundo, frente, 6, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None
    assunto = np.where((mascara == cv2.GC_FGD) | (mascara == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    assunto = cv2.morphologyEx(cv2.morphologyEx(assunto, cv2.MORPH_OPEN, nucleo), cv2.MORPH_CLOSE, nucleo, iterations=2)
    assunto, parte = _maior_pedaco(assunto)
    if assunto is None or parte < 0.85:
        return None
    # tapa os buracos de dentro (a barriga clara, o reflexo no olho)
    contornos, _ = cv2.findContours(assunto, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    assunto = cv2.drawContours(np.zeros_like(assunto), contornos, -1, 255, cv2.FILLED)
    fracao = float((assunto > 0).mean())
    beirada = np.concatenate([assunto[0], assunto[-1], assunto[:, 0], assunto[:, -1]])
    if not MINIMO <= fracao <= MAXIMO or float((beirada > 0).mean()) > 0.30:
        return None
    assunto = cv2.GaussianBlur(assunto, (3, 3), 0)
    # a borda branca de figurinha: o contorno engordado, pintado de branco por baixo do bicho
    pad = BORDA + 4
    imagem = cv2.copyMakeBorder(imagem, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    assunto = cv2.copyMakeBorder(assunto, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    contorno = cv2.dilate(assunto, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * BORDA + 1, 2 * BORDA + 1)))
    peso = (assunto.astype(np.float32) / 255.0)[..., None]
    cor = (imagem.astype(np.float32) * peso + 255.0 * (1 - peso)).astype(np.uint8)
    saida = np.dstack([cor, contorno])
    y, x = np.where(contorno > 0)
    saida = saida[y.min():y.max() + 1, x.min():x.max() + 1]
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    return destino if cv2.imwrite(str(destino), saida) else None
