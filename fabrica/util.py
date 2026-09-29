"""Funções pequenas usadas em várias etapas."""
import json
import subprocess
import sys


def rodar(comando: list) -> subprocess.CompletedProcess:
    comando = [str(c) for c in comando]
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"Falhou {' '.join(comando[:4])} ...\n{resultado.stderr[-2000:]}")
    return resultado


def duracao_audio(caminho) -> float:
    r = rodar(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", caminho])
    return float(json.loads(r.stdout)["format"]["duration"])


def mmss(segundos: float) -> str:
    m, s = divmod(int(round(segundos)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def confirmar(pergunta: str, sim: bool = False) -> bool:
    if sim:
        return True
    if not sys.stdin.isatty():
        raise SystemExit(f"{pergunta}\nSem terminal para responder. Rode de novo com --sim para aprovar o gasto.")
    return input(f"{pergunta} [s/N] ").strip().lower() in ("s", "sim")
