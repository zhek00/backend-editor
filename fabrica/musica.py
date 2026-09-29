"""Trilha instrumental gerada na ElevenLabs Music.

Cada geração consome créditos do plano da ElevenLabs e rende um trecho de até 5 minutos.
A fábrica emenda faixas com transição suave, então um trecho curto cobre um áudio longo.
O arquivo de texto salvo ao lado da faixa entra nos créditos do projeto.
"""
import re
from pathlib import Path

import httpx

from .config import caminho_relativo, chave

URL = "https://api.elevenlabs.io/v1/music"
MODELOS = ("music_v1", "music_v2", "music_v2_5")
MAXIMO_MINUTOS = 5


def gerar(descricao: str, minutos: float, pasta: str, nome: str | None = None, modelo: str = "music_v2_5") -> Path:
    if not 0.05 <= minutos <= MAXIMO_MINUTOS:
        raise SystemExit(f"A duração precisa ficar entre 3 segundos e {MAXIMO_MINUTOS} minutos.")
    if modelo not in MODELOS:
        raise SystemExit(f"Modelo desconhecido. Use um destes: {', '.join(MODELOS)}")
    destino_pasta = caminho_relativo(pasta)
    destino_pasta.mkdir(parents=True, exist_ok=True)
    nome = nome or re.sub(r"[^a-z0-9]+", "-", descricao.lower()).strip("-")[:40] or "trilha"
    mp3 = destino_pasta / f"{nome}.mp3"
    if mp3.exists():
        raise SystemExit(f"Já existe {mp3}. Escolha outro --nome.")

    r = httpx.post(
        URL,
        headers={"xi-api-key": chave("ELEVENLABS_API_KEY")},
        json={"prompt": descricao, "music_length_ms": int(minutos * 60_000), "model_id": modelo,
              "force_instrumental": True},
        timeout=900,
    )
    if r.status_code in (401, 403):
        raise SystemExit(f"A ElevenLabs recusou ({r.status_code}). A música só existe nos planos pagos, e a chave "
                         f"precisa de acesso a Music. {r.text[:300]}")
    if r.status_code != 200:
        raise SystemExit(f"A ElevenLabs recusou gerar a música ({r.status_code}). {r.text[:400]}")
    mp3.write_bytes(r.content)
    mp3.with_suffix(".txt").write_text(
        f"Trilha gerada com Eleven Music, da ElevenLabs, modelo {modelo}.\nDescrição usada: {descricao}\n",
        encoding="utf-8",
    )
    return mp3
