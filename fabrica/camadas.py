"""Camadas e sons que a própria fábrica desenha, sem baixar nem copiar nada.

- Camadas de partículas (brasas e poeira): um laço de 6 s feito com numpy, somado à imagem com `blend=screen`, que só
  clareia: o fundo preto do laço some. O movimento é periódico, então o laço fecha sem emenda.
- Sons de animação (pop, passagem e contador): sintetizados pelo FFmpeg.

Tudo fica em efeitos/gerados/ e é feito uma vez por máquina.
"""
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np

from .util import rodar

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "efeitos" / "gerados"
LARGURA, ALTURA, FPS, SEGUNDOS = 1280, 720, 30, 6
_trava = threading.Lock()  # as cenas renderizam em paralelo, e todas pedem o mesmo arquivo na primeira vez

# nome: quantas partículas, tamanho, cor (B, G, R), voltas que cada uma dá no laço, deriva lateral, brilho
PARTICULAS = {
    "brasas": {"quantas": 90, "tamanho": (1.0, 3.2), "cor": (40, 120, 255), "voltas": (1, 2), "deriva": 26, "brilho": 1.0},
    "poeira": {"quantas": 140, "tamanho": (0.8, 2.4), "cor": (205, 215, 225), "voltas": (1, 1), "deriva": 14, "brilho": 0.42},
}
SONS = {
    "pop": "aevalsrc='0.9*sin(2*PI*(520+900*exp(-40*t))*t)*exp(-26*t)':d=0.18:s=48000",
    "passagem": "anoisesrc=d=0.42:c=pink:r=48000:a=0.8,highpass=f=300,lowpass=f=4200,"
                "afade=t=in:d=0.2,afade=t=out:st=0.2:d=0.22",
    "contador": "aevalsrc='0.7*sin(2*PI*1500*t)*exp(-90*mod(t,0.07))':d=0.42:s=48000,afade=t=out:st=0.3:d=0.12",
}


def _quadro(cfg, sementes, t) -> np.ndarray:
    """Um quadro do laço. t vai de 0 a 1, e t=1 é igual a t=0: cada partícula dá um número inteiro de voltas."""
    x0, y0, voltas, fase, tamanho = sementes
    y = (y0 - voltas * t * ALTURA) % ALTURA
    x = (x0 + cfg["deriva"] * np.sin(2 * np.pi * (t * voltas + fase))) % LARGURA
    pisca = 0.65 + 0.35 * np.sin(2 * np.pi * (3 * t + fase))
    quadro = np.zeros((ALTURA, LARGURA, 3), np.float32)
    grade_y, grade_x = np.ogrid[-8:9, -8:9]
    for i in range(len(x0)):
        cx, cy = int(x[i]), int(y[i])
        forca = np.exp(-(grade_x ** 2 + grade_y ** 2) / (2 * tamanho[i] ** 2)) * pisca[i] * cfg["brilho"]
        a, b = max(cy - 8, 0), min(cy + 9, ALTURA)
        c, d = max(cx - 8, 0), min(cx + 9, LARGURA)
        recorte = forca[a - cy + 8:b - cy + 8, c - cx + 8:d - cx + 8, None]
        quadro[a:b, c:d] += recorte * np.array(cfg["cor"], np.float32)
    return np.clip(quadro, 0, 255).astype(np.uint8)


def laco(nome: str) -> Path:
    """O arquivo do laço, feito na primeira vez."""
    destino = PASTA / f"camada_{nome}.mp4"
    with _trava:
        if not destino.exists():
            _gravar_laco(nome, destino)
    return destino


def _gravar_laco(nome: str, destino: Path) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    cfg = PARTICULAS[nome]
    sorteio = np.random.default_rng(sum(map(ord, nome)))
    n = cfg["quantas"]
    sementes = (sorteio.uniform(0, LARGURA, n), sorteio.uniform(0, ALTURA, n),
                sorteio.integers(cfg["voltas"][0], cfg["voltas"][1] + 1, n), sorteio.uniform(0, 1, n),
                sorteio.uniform(*cfg["tamanho"], n))
    temporario = destino.with_suffix(".tmp.mp4")
    processo = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{LARGURA}x{ALTURA}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         str(temporario)], stdin=subprocess.PIPE)
    total = FPS * SEGUNDOS
    for k in range(total):
        processo.stdin.write(_quadro(cfg, sementes, k / total).tobytes())
    processo.stdin.close()
    if processo.wait():
        raise RuntimeError(f"o FFmpeg não gravou a camada {nome}")
    shutil.move(str(temporario), destino)


def som(nome: str) -> Path:
    """O arquivo do som de animação, feito na primeira vez."""
    destino = PASTA / f"som_{nome}.wav"
    with _trava:
        if not destino.exists():
            PASTA.mkdir(parents=True, exist_ok=True)
            rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", SONS[nome], "-ac", "2", destino])
    return destino
