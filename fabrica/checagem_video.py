"""Checagem técnica do vídeo pronto: trecho congelado, tela preta e silêncio, medidos pelo FFmpeg, de graça.

A revisão do vídeo (revisao_video.py) pede a um modelo que olhe um quadro de cada cena: ela vê o que a cena mostra, mas
não vê o que acontece ENTRE os quadros. Aqui o FFmpeg lê o final.mp4 inteiro, quadro a quadro, e aponta onde a imagem
parou de mexer (foto sem o movimento lento, clipe que travou), onde a tela ficou preta e onde o som sumiu (narração ou
música faltando). Ideia do video-use e do motionmaxxing (gate de "quadro morto"), adaptada aos cortes da fábrica.

Calibrado em 2026-10-13: num vídeo sintético acha os três defeitos plantados e não acusa a foto com zoom lento; no
final.mp4 do virou-filme-em-1996 (8,5 min) levou 33 s e não acusou nada. Só aponta, não troca nada: o resultado fica em
checagem_video.json e vale para o final.mp4 de quando rodou (como a revisão do vídeo)."""
import re
from datetime import datetime

from .util import mmss, rodar

# segundos mínimos de cada defeito para ele entrar: abaixo disso é corte, pausa de respiração ou fim de fade
PADRAO = {"congelado": 2.0, "preto": 0.5, "silencio": 1.5}
TIPOS = {"congelado": "imagem parada (nada se mexe)", "preto": "tela preta", "silencio": "sem som"}


def config(projeto) -> dict:
    return {**PADRAO, "ativo": True, **(projeto.config.get("checagem_video") or {})}


def ligada(projeto) -> bool:
    return bool(config(projeto).get("ativo", True))


def _duracao(caminho) -> float:
    r = rodar(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", caminho])
    return float((r.stdout or "0").strip() or 0)


def medir(caminho, congelado=PADRAO["congelado"], preto=PADRAO["preto"], silencio=PADRAO["silencio"]) -> list:
    """[{tipo, ini, fim}] dos trechos com defeito, numa passada só do FFmpeg pelo vídeo.

    A imagem é reduzida a 320 px antes de comparar: mais rápido, e o ruído de compressão não conta como movimento.
    O congelado usa tolerância 0,003: o zoom mais lento da fábrica (1,12x numa cena de 3 a 5 s) passa longe dela."""
    duracao = _duracao(caminho)
    r = rodar(["ffmpeg", "-hide_banner", "-nostats", "-i", caminho,
               "-vf", f"scale=320:-2,freezedetect=n=0.003:d={congelado},blackdetect=d={preto}:pix_th=0.10",
               "-af", f"silencedetect=noise=-50dB:d={silencio}", "-f", "null", "-"])
    texto = r.stderr or ""
    trechos, abertos = [], {}
    for linha in texto.splitlines():
        if m := re.search(r"freeze_start:\s*([\d.]+)", linha):
            abertos["congelado"] = float(m.group(1))
        elif (m := re.search(r"freeze_end:\s*([\d.]+)", linha)) and "congelado" in abertos:
            trechos.append({"tipo": "congelado", "ini": abertos.pop("congelado"), "fim": float(m.group(1))})
        elif m := re.search(r"silence_start:\s*(-?[\d.]+)", linha):
            abertos["silencio"] = max(0.0, float(m.group(1)))
        elif (m := re.search(r"silence_end:\s*([\d.]+)", linha)) and "silencio" in abertos:
            trechos.append({"tipo": "silencio", "ini": abertos.pop("silencio"), "fim": float(m.group(1))})
        elif m := re.search(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)", linha):
            trechos.append({"tipo": "preto", "ini": float(m.group(1)), "fim": float(m.group(2))})
    # o defeito que vai até o fim do vídeo não ganha linha de fim: fecha na duração
    for tipo, ini in abertos.items():
        trechos.append({"tipo": tipo, "ini": ini, "fim": duracao})
    for t in trechos:
        t["ini"], t["fim"] = round(t["ini"], 2), round(t["fim"], 2)
    return sorted(trechos, key=lambda t: (t["ini"], t["tipo"]))


def _gravidade(trecho, duracao) -> str:
    """Alta: o espectador nota com certeza. Baixa: provavelmente de propósito (o fim do vídeo apaga)."""
    tamanho = trecho["fim"] - trecho["ini"]
    if trecho["ini"] >= duracao - 1.5:
        return "baixa"  # o fade de saída do fim do vídeo
    if trecho["tipo"] == "preto":
        return "alta"
    if trecho["tipo"] == "congelado":
        return "alta" if tamanho >= 4 else "media"
    return "alta" if tamanho >= 3 else "media"


def _assinatura(arquivo) -> str:
    return f"{arquivo.stat().st_mtime_ns}" if arquivo.exists() else ""


def _cenas_do_trecho(cenas, atraso, ini, fim) -> list:
    """As cenas (pelo tempo da narração, mais o atraso da abertura) que o trecho cobre."""
    return [c["n"] for c in cenas if atraso + c["ini"] < fim and atraso + c["fim"] > ini]


def checar(projeto, log=print, arquivo="final.mp4") -> dict:
    """Mede o vídeo pronto, liga cada defeito às cenas que ele cobre e grava checagem_video.json. Devolve o resultado."""
    from .revisao_video import _atraso

    final = projeto.pasta / arquivo
    if not final.exists():
        raise SystemExit(f"Ainda não há vídeo pronto. Rode uv run fabrica render {projeto.nome}")
    cfg = config(projeto)
    duracao = _duracao(final)
    log(f"  lendo o {arquivo} inteiro ({mmss(duracao)}) atrás de imagem parada, tela preta e falta de som")
    trechos = medir(final, cfg["congelado"], cfg["preto"], cfg["silencio"])
    cenas = projeto.ler_json("cenas.json").get("cenas", []) if projeto.existe("cenas.json") else []
    atraso = _atraso(projeto) if arquivo == "final.mp4" else 0.0
    por_cena = {}
    for t in trechos:
        t["gravidade"] = _gravidade(t, duracao)
        t["cenas"] = _cenas_do_trecho(cenas, atraso, t["ini"], t["fim"])
        t["abertura"] = t["ini"] < atraso
        for n in t["cenas"]:
            por_cena.setdefault(str(n), []).append(t["tipo"])
    dados = {"quando": datetime.now().isoformat(timespec="seconds"), "arquivo": arquivo, "final": _assinatura(final),
             "duracao": round(duracao, 2), "trechos": trechos, "cenas": por_cena,
             "graves": sorted({n for t in trechos if t["gravidade"] == "alta" for n in t["cenas"]})}
    projeto.salvar_json(f"checagem_{arquivo.rsplit('.', 1)[0]}.json" if arquivo != "final.mp4" else "checagem_video.json",
                        dados)
    log("  " + resumo(dados))
    for t in trechos[:15]:
        onde = f"cenas {', '.join(map(str, t['cenas'][:6]))}" if t["cenas"] else ("abertura" if t["abertura"] else "fora das cenas")
        log(f"    {mmss(t['ini'])} a {mmss(t['fim'])} [{t['gravidade']}] {TIPOS[t['tipo']]} ({t['fim'] - t['ini']:.1f} s), {onde}")
    if len(trechos) > 15:
        log(f"    e mais {len(trechos) - 15} trecho(s) em checagem_video.json")
    return dados


def resultado(projeto):
    """A checagem guardada, se ela é do final.mp4 que está no projeto agora; senão None."""
    if not projeto.existe("checagem_video.json"):
        return None
    dados = projeto.ler_json("checagem_video.json")
    return dados if dados.get("final") == _assinatura(projeto.pasta / "final.mp4") else None


def resumo(dados) -> str:
    trechos = dados.get("trechos") or []
    if not trechos:
        return "checagem técnica: nenhuma imagem parada, tela preta ou falta de som"
    conta = {tipo: sum(1 for t in trechos if t["tipo"] == tipo) for tipo in TIPOS}
    partes = [f"{conta[tipo]} {TIPOS[tipo]}" for tipo in TIPOS if conta[tipo]]
    graves = dados.get("graves") or []
    return ("checagem técnica: " + ", ".join(partes)
            + (f"; {len(graves)} cena(s) com defeito grave: {', '.join(map(str, graves[:20]))}" if graves else ""))
