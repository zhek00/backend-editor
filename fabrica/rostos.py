"""Rostos nas fotos, para o recorte nunca cortar a cabeça de quem aparece.

A foto que preenche a tela perde um pedaço em cima e embaixo (ou dos lados), e o corte era sempre pelo meio: no
retrato do jogador da cena 16 do virou-filme-em-1996, o editor mostrava só o tronco. Aqui o OpenCV acha os rostos
(YuNet, no próprio computador, grátis e sem chamar modelo de IA pago) e o recorte é posicionado para que
eles fiquem dentro, um pouco acima do meio, como num enquadramento de fotógrafo.

O resultado fica guardado em .rostos.json, na pasta da foto, pela data do arquivo: cada foto é olhada uma vez só.
"""
import json
import os
import threading

_TRAVA = threading.Lock()
VERSAO = 2  # sobe quando o jeito de achar rostos muda, para as fotos serem olhadas de novo


MODELO = os.path.join(os.path.dirname(__file__), "recursos", "rostos", "face_detection_yunet_2023mar.onnx")


def _achar(caminho) -> list:
    """Rostos da foto em frações da largura e da altura: [(x, y, largura, altura)]. Vazio se não há.

    Usa o YuNet do OpenCV (modelo de 230 KB, licença MIT, em recursos/rostos). O detector clássico (Haar) foi
    testado antes e errou 10 de 12 fotos do virou-filme-em-1996: achava rosto em folha, abutre, fachada, mapa e
    manuscrito, e perdia o rapaz deitado na barraca. O YuNet acertou todos os rostos visíveis e não inventou nenhum."""
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError:
        return []  # sem o OpenCV instalado, o recorte segue pelo meio, como antes
    if not hasattr(cv2, "FaceDetectorYN") or not os.path.exists(MODELO):
        return []
    with Image.open(caminho) as imagem:
        imagem = imagem.convert("RGB")
        imagem.thumbnail((960, 960))
    matriz = cv2.cvtColor(np.array(imagem), cv2.COLOR_RGB2BGR)
    altura, largura = matriz.shape[:2]
    detector = cv2.FaceDetectorYN.create(MODELO, "", (largura, altura), 0.7, 0.3, 5000)
    _, achados = detector.detect(matriz)
    if achados is None or len(achados) == 0:
        return []
    # pessoa bem pequena no fundo não puxa o recorte: vale quem tem ao menos 40% da altura do maior rosto
    maior = max(float(r[3]) for r in achados)
    return [(round(float(r[0]) / largura, 4), round(float(r[1]) / altura, 4),
             round(float(r[2]) / largura, 4), round(float(r[3]) / altura, 4))
            for r in achados if float(r[3]) >= 0.4 * maior]


def rostos(caminho) -> list:
    """Rostos da foto, guardados por foto e data em .rostos.json na mesma pasta."""
    caminho = os.fspath(caminho)
    try:
        marca = f"{VERSAO}:{os.stat(caminho).st_mtime_ns}"
    except OSError:
        return []
    arquivo = os.path.join(os.path.dirname(caminho), ".rostos.json")
    nome = os.path.basename(caminho)
    with _TRAVA:
        try:
            with open(arquivo, encoding="utf-8") as f:
                guardado = json.load(f)
        except (OSError, ValueError):
            guardado = {}
    item = guardado.get(nome)
    if item and item.get("marca") == marca:
        return [tuple(r) for r in item.get("rostos", [])]
    try:
        achados = _achar(caminho)
    except Exception:
        achados = []
    with _TRAVA:
        try:
            with open(arquivo, encoding="utf-8") as f:
                guardado = json.load(f)
        except (OSError, ValueError):
            guardado = {}
        guardado[nome] = {"marca": marca, "rostos": achados}
        try:
            with open(arquivo, "w", encoding="utf-8") as f:
                json.dump(guardado, f)
        except OSError:
            pass
    return achados


def recorte(largura, altura, proporcao, achados):
    """Caixa (x0, y0, x1, y1) com a proporção pedida, a maior que cabe na foto, posicionada nos rostos.

    Sem rostos, None (o recorte segue pelo meio, como antes). Com rostos, o centro deles fica a 40% da altura da
    caixa (cabeça um pouco acima do meio) e no meio da largura, sem sair da foto."""
    if not achados:
        return None
    if largura / altura > proporcao:
        caixa_l, caixa_a = round(altura * proporcao), altura
    else:
        caixa_l, caixa_a = largura, round(largura / proporcao)
    x0 = min(r[0] for r in achados) * largura
    x1 = max(r[0] + r[2] for r in achados) * largura
    y0 = min(r[1] for r in achados) * altura
    y1 = max(r[1] + r[3] for r in achados) * altura
    centro_x, centro_y = (x0 + x1) / 2, (y0 + y1) / 2
    esquerda = min(max(round(centro_x - caixa_l / 2), 0), largura - caixa_l)
    topo = min(max(round(centro_y - caixa_a * 0.4), 0), altura - caixa_a)
    return esquerda, topo, esquerda + caixa_l, topo + caixa_a


def corta_rosto_no_meio(largura, altura, proporcao, achados) -> bool:
    """O recorte pelo meio deixaria algum rosto de fora (mais de 15% dele)?"""
    if not achados:
        return False
    if largura / altura > proporcao:
        caixa_l, caixa_a = round(altura * proporcao), altura
    else:
        caixa_l, caixa_a = largura, round(largura / proporcao)
    cx0, cy0 = (largura - caixa_l) / 2, (altura - caixa_a) / 2
    cx1, cy1 = cx0 + caixa_l, cy0 + caixa_a
    for x, y, w, h in achados:
        rx0, ry0, rx1, ry1 = x * largura, y * altura, (x + w) * largura, (y + h) * altura
        dentro = max(0, min(rx1, cx1) - max(rx0, cx0)) * max(0, min(ry1, cy1) - max(ry0, cy0))
        if dentro < 0.85 * (rx1 - rx0) * (ry1 - ry0):
            return True
    return False
