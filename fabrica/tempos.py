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


# segundos somados dentro de uma etapa, por pasta do projeto: busca em cada banco, espera de limite, download. Uma
# janela de 38 min na conferência do everything-you-need-to-answer teve só 4 min de modelo trabalhando, e sem isto
# não dava para saber onde foi o resto
_partes = {}


def somar(projeto, nome, segundos) -> None:
    try:
        chave = str(_pasta(projeto))
    except (TypeError, ValueError):  # projeto sem pasta (os testes): medir nunca derruba a produção
        return
    with _trava:
        por_nome = _partes.setdefault(chave, {})
        s, n = por_nome.get(nome, (0.0, 0))
        por_nome[nome] = (s + segundos, n + 1)


@contextlib.contextmanager
def parte(projeto, nome):
    """Soma o tempo do bloco na parte nome da etapa que estiver sendo medida."""
    inicio = time.time()
    try:
        yield
    finally:
        somar(projeto, nome, time.time() - inicio)


def _foto_das_partes(projeto) -> dict:
    try:
        chave = str(_pasta(projeto))
    except (TypeError, ValueError):
        return {}
    with _trava:
        return dict(_partes.get(chave, {}))


def _modelos_desde(projeto, inicio) -> dict:
    """Segundos de cada chamada de modelo (uso_*.json) que terminou desde inicio, somados pela etapa da chamada."""
    desde = datetime.fromtimestamp(inicio).isoformat(timespec="seconds")
    somas = {}
    for arquivo in _pasta(projeto).glob("uso_*.json"):
        try:
            registros = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in registros if isinstance(registros, list) else []:
            if str(r.get("quando") or "") >= desde and r.get("segundos"):
                nome = f"modelo: {r.get('etapa') or '?'}"
                s, n = somas.get(nome, (0.0, 0))
                somas[nome] = (s + float(r["segundos"]), n + 1)
    return somas


@contextlib.contextmanager
def medir(projeto, etapa, log=None, **extra):
    """Mede o bloco e grava em tempos.json, deu certo ou não. Com log, diz quanto levou. Junto vão as partes
    (segundos somados de cada banco, espera, download e modelo), que somam mais que a etapa quando correm juntas."""
    inicio = time.time()
    antes = _foto_das_partes(projeto)
    ok = False
    try:
        yield
        ok = True
    finally:
        segundos = time.time() - inicio
        depois = _foto_das_partes(projeto)
        partes = {nome: [round(s - antes.get(nome, (0.0, 0))[0], 1), n - antes.get(nome, (0.0, 0))[1]]
                  for nome, (s, n) in depois.items() if n > antes.get(nome, (0.0, 0))[1]}
        try:
            partes.update({nome: [round(s, 1), n] for nome, (s, n) in _modelos_desde(projeto, inicio).items()})
        except Exception:  # medir nunca derruba a produção
            pass
        if partes:
            extra = {**extra, "partes": dict(sorted(partes.items(), key=lambda x: -x[1][0]))}
        registrar(projeto, etapa, inicio, segundos, ok, **extra)
        if log and segundos >= 1:
            log(f"  [tempo] {etapa}: {duracao(segundos)}{'' if ok else ' (falhou)'}")


CHAMADAS = "chamadas.jsonl"


def anotar_chamada(projeto, tipo, etapa, inicio, ok=True, **extra) -> None:
    """Uma linha em chamadas.jsonl por chamada de IA que a fábrica esperou (texto pela cadeia, imagem de IA, voz):
    quando começou, quanto levou e, na cadeia, cada rota tentada (o que falhou, o que estava fora do ar, a espera
    pelo gratuito e pela confirmação do pago). Pedido do usuário em 2026-10-29: um vídeo de 30 min levou 4 h e o
    uso_*.json só guardava a rota que respondeu, sem o tempo perdido nas que falharam nem a espera parada.
    Uma linha por vez no fim do arquivo (são milhares por vídeo); nunca derruba a produção."""
    linha = {"inicio": datetime.fromtimestamp(inicio).isoformat(timespec="milliseconds"), "tipo": tipo,
             "etapa": etapa, "segundos": round(time.time() - inicio, 2), "ok": bool(ok), **extra}
    try:
        arquivo = _pasta(projeto) / CHAMADAS
        with _trava, open(arquivo, "a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass


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
