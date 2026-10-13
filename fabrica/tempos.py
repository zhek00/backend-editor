"""Quanto tempo cada etapa da produção levou, em projetos/NOME/tempos.json.

Pedido do usuário em 2026-10-13, para acelerar a criação sem perder qualidade: antes de mexer, medir. O que havia era
a data dos arquivos, que mistura produção com edição, regravação e a fábrica desligada (a "noite inteira" do
nunca-deve-ter-dentro-de-casa-parte-2 foi a fábrica desligada, não a produção). Cada linha é uma etapa que terminou
(ou falhou), com o começo e os segundos; a criação que retoma depois de um reinício só soma linhas novas. Cada chamada
de modelo guarda os segundos dela no uso_*.json (openrouter_local, groq_local, gemini_local, jev_local,
claude_local): somadas por etapa, mostram quanto da busca, por exemplo, foi esperando modelo.
"""
import contextlib
import json
import threading
import time
from datetime import datetime
from pathlib import Path

ARQUIVO = "tempos.json"
_trava = threading.Lock()


def _pasta(projeto) -> Path:
    return Path(getattr(projeto, "pasta", projeto))


def registrar(projeto, etapa, inicio, segundos, ok=True, **extra) -> None:
    """Uma linha em tempos.json. inicio é o time.time() do começo. Nunca derruba a produção."""
    linha = {"etapa": etapa, "inicio": datetime.fromtimestamp(inicio).isoformat(timespec="seconds"),
             "segundos": round(segundos, 1), "ok": bool(ok), **extra}
    arquivo = _pasta(projeto) / ARQUIVO
    try:
        with _trava:
            historico = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
            historico.append(linha)
            temporario = arquivo.with_name(ARQUIVO + ".tmp")
            temporario.write_text(json.dumps(historico, ensure_ascii=False, indent=1), encoding="utf-8")
            temporario.replace(arquivo)
    except (OSError, ValueError):
        pass


@contextlib.contextmanager
def medir(projeto, etapa, log=None, **extra):
    """Mede o bloco e grava em tempos.json, deu certo ou não. Com log, diz quanto levou."""
    inicio = time.time()
    ok = False
    try:
        yield
        ok = True
    finally:
        segundos = time.time() - inicio
        registrar(projeto, etapa, inicio, segundos, ok, **extra)
        if log and segundos >= 1:
            log(f"  [tempo] {etapa}: {duracao(segundos)}{'' if ok else ' (falhou)'}")


def duracao(segundos) -> str:
    segundos = int(round(segundos))
    if segundos < 60:
        return f"{segundos}s"
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}h{m:02d}min" if h else f"{m}min{s:02d}s"


def resumo(projeto, desde=None) -> list:
    """[(etapa, segundos somados, vezes)] do tempos.json, da etapa mais demorada para a menos. desde: só as linhas
    que começaram a partir desse texto ISO (a criação atual, sem as de antes)."""
    arquivo = _pasta(projeto) / ARQUIVO
    try:
        historico = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    somas = {}
    for linha in historico:
        if desde and str(linha.get("inicio") or "") < desde:
            continue
        s, n = somas.get(linha["etapa"], (0.0, 0))
        somas[linha["etapa"]] = (s + float(linha.get("segundos") or 0), n + 1)
    return sorted(((e, s, n) for e, (s, n) in somas.items()), key=lambda x: -x[1])


def texto_do_resumo(projeto, desde=None) -> str:
    partes = [f"{etapa} {duracao(s)}" + (f" ({n}x)" if n > 1 else "") for etapa, s, n in resumo(projeto, desde)]
    return "Tempo por etapa: " + "; ".join(partes) if partes else ""
