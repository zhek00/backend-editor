"""Efeitos sonoros curtos, gerados na ElevenLabs e guardados numa biblioteca do canal.

O Claude marca nas cenas onde bate um som e descreve esse som em inglês. Cada descrição
vira um arquivo na biblioteca e volta a ser usada em qualquer vídeo que peça o mesmo som,
então o custo cai com o tempo. No modo offline o som é um ruído de teste feito no FFmpeg.
"""
import hashlib
import re

import httpx

from .config import caminho_relativo, chave
from .util import rodar

URL = "https://api.elevenlabs.io/v1/sound-generation"


def ativo(perfil) -> bool:
    return bool((perfil.get("efeitos") or {}).get("ativo"))


def arquivo(perfil, efeito, offline=False):
    pasta = caminho_relativo((perfil.get("efeitos") or {}).get("pasta", "efeitos"))
    if offline:
        pasta = pasta / "teste"  # o ruído de teste não se mistura com os sons de verdade
    descricao = " ".join(efeito["descricao"].lower().split())
    base = re.sub(r"[^a-z0-9]+", "-", descricao).strip("-")[:50] or "efeito"
    codigo = hashlib.sha1(f"{descricao}|{efeito['duracao']:.1f}".encode()).hexdigest()[:6]
    return pasta / f"{base}-{efeito['duracao']:.0f}s-{codigo}.mp3"


def pendentes(projeto):
    """Efeitos pedidos pelas cenas que ainda não estão na biblioteca, sem repetir o mesmo som."""
    if not ativo(projeto.perfil) or not projeto.existe("cenas.json"):
        return []
    vistos, lista = set(), []
    for c in projeto.ler_json("cenas.json")["cenas"]:
        efeito = c.get("efeito")
        if not efeito:
            continue
        destino = arquivo(projeto.perfil, efeito, projeto.offline)
        if destino.exists() or destino in vistos:
            continue
        vistos.add(destino)
        lista.append((efeito, destino))
    return lista


def segundos_pendentes(projeto) -> float:
    return sum(efeito["duracao"] for efeito, _ in pendentes(projeto))


def gerar(projeto, log=print) -> int:
    lista = pendentes(projeto)
    if not lista:
        log("  nenhum efeito novo, os que o vídeo pede já estão na biblioteca")
        return 0
    cfg = projeto.perfil.get("efeitos") or {}
    for i, (efeito, destino) in enumerate(lista, 1):
        destino.parent.mkdir(parents=True, exist_ok=True)
        if projeto.offline:
            _som_de_teste(efeito["duracao"], destino)
        else:
            _elevenlabs(efeito, destino, cfg)
            from . import custos_reais

            preco = (projeto.config.get("precos") or {}).get("efeito_por_minuto", 0.12)
            custos_reais.registrar(
                projeto, "efeito", f"efeito sonoro '{efeito['descricao'][:60]}'",
                efeito["duracao"] / 60 * preco, unidades=efeito["duracao"],
                detalhes={"descricao": efeito["descricao"], "segundos": efeito["duracao"]})
        if i % 5 == 0 or i == len(lista):
            log(f"  efeitos {i}/{len(lista)}")
    return len(lista)


def _elevenlabs(efeito, destino, cfg):
    r = httpx.post(
        URL,
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": chave("ELEVENLABS_API_KEY")},
        json={"text": efeito["descricao"], "duration_seconds": efeito["duracao"],
              "prompt_influence": cfg.get("fidelidade", 0.5)},
        timeout=180,
    )
    if r.status_code in (401, 403):
        raise SystemExit(f"A ElevenLabs recusou o efeito ({r.status_code}). A chave precisa de acesso a Sound Effects. {r.text[:200]}")
    if r.status_code != 200:
        raise RuntimeError(f"A ElevenLabs falhou no efeito '{efeito['descricao']}' ({r.status_code}). {r.text[:200]}")
    temporario = destino.with_name(destino.name + ".baixando")
    temporario.write_bytes(r.content)
    temporario.replace(destino)
    destino.with_suffix(".txt").write_text(efeito["descricao"] + "\n", encoding="utf-8")


def _som_de_teste(duracao, destino):
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anoisesrc=d={duracao}:c=brown:a=0.5",
           "-af", f"afade=t=in:d=0.05,afade=t=out:st={max(duracao - 0.6, 0):.2f}:d=0.6",
           "-c:a", "libmp3lame", "-b:a", "128k", destino])


def na_linha_do_tempo(projeto, cenas):
    """Segundo da narração e arquivo de cada efeito que já está na biblioteca."""
    if not ativo(projeto.perfil):
        return []
    resultado = []
    for c in cenas:
        efeito = c.get("efeito")
        if not efeito:
            continue
        destino = arquivo(projeto.perfil, efeito, projeto.offline)
        if destino.exists():
            resultado.append((c["ini"] + efeito.get("inicio", 0.0), destino))
    return resultado
