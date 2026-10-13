"""Funções pequenas usadas em várias etapas."""
import json
import subprocess
import sys
import threading
import time


def gravar_cache(arquivo, dados, indent=2) -> None:
    """Grava o JSON do cache inteiro ou nada: escreve num arquivo temporário e troca, para uma queda no meio não deixar
    meio arquivo. O temporário leva o número da thread, porque lotes diferentes gravam ao mesmo tempo."""
    temporario = arquivo.with_name(f"{arquivo.name}.{threading.get_ident()}.tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=indent), encoding="utf-8")
    for tentativa in range(8):
        try:
            temporario.replace(arquivo)
            return
        except PermissionError:
            # no Windows a troca falha enquanto outra thread troca ou lê o mesmo arquivo: tenta de novo em instantes
            if tentativa == 7:
                temporario.unlink(missing_ok=True)
                raise
            time.sleep(0.02 * (tentativa + 1))


def ler_cache(arquivo):
    """O JSON do cache, ou None quando não existe ou está corrompido (aí a etapa roda de novo, em vez de parar)."""
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
