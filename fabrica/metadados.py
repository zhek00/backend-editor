"""Metadados do YouTube dentro dos arquivos e nomes pelo título (pedido do usuário em 2026-10-20: "gerar nome na base
dos vídeos com metadados para o YouTube ... já programado com o nome do título, e não nomes genéricos").

- **Dentro do MP4** (`gravar`): o final.mp4, o final_vertical.mp4 e os shorts levam o título, a descrição, as tags
  (`keywords`), o canal (`artist`), o ano, os direitos e a língua do áudio, tirados do kit de publicação. O FFmpeg
  copia as faixas sem recodificar (segundos, mesmo num vídeo de 30 min). A data do arquivo é devolvida depois da troca:
  a revisão do vídeo pronto e a checagem do FFmpeg reconhecem o final.mp4 pela data, e um render novo (data nova) faz
  os metadados serem gravados de novo. O que já foi gravado fica em `metadados.json`, e rodar de novo sem mudança não
  mexe no arquivo.
- **Nomes pelo título** (`nomes`): o título exato, como a entrega dá ao MP4 (`entrega_pc.nome_do_titulo`, com os
  parecidos no lugar do que o Windows recusa, porque o YouTube usa o nome do arquivo como título ao subir), dá nome ao
  vídeo, à versão em pé, à thumbnail e à legenda; cada short leva o título dele. Vale na pasta de entrega e no download
  pelo editor (`nome_para_baixar`). Dentro do projeto os arquivos seguem final.mp4 e S01.mp4, que o resto da fábrica
  usa.

Nunca para o vídeo: arquivo aberto em outro programa (o Windows não deixa trocar) ou FFmpeg com erro, o arquivo fica
como estava e a próxima entrega tenta de novo."""
import hashlib
import json
import os
import re
import time
from datetime import date
from pathlib import Path

from .entrega_pc import nome_do_titulo
from .util import rodar

ARQUIVO = "metadados.json"
LINGUA_DO_AUDIO = {"pt": "por", "en": "eng", "es": "spa"}  # ISO 639-2, o que o MP4 guarda


def titulo(projeto) -> str:
    """O título do vídeo: o que a pessoa deu (editor e robô gravam em titulo_entrega), exatamente como ela escreveu,
    vence o do kit."""
    kit = projeto.ler_json("publicacao.json") if projeto.existe("publicacao.json") else {}
    escolhido = str((getattr(projeto, "dados", None) or {}).get("titulo_entrega") or "").strip()
    return escolhido or kit.get("titulo") or projeto.nome


def _shorts(projeto) -> list:
    if not projeto.existe("shorts/shorts.json"):
        return []
    return [s for s in projeto.ler_json("shorts/shorts.json").get("shorts") or [] if projeto.existe(s["arquivo"])]


def _titulo_do_short(short) -> str:
    texto = re.sub(r"\*", "", str(short.get("titulo_post") or short.get("titulo") or ""))
    return re.sub(r"\s*#shorts\b", "", texto, flags=re.I).strip()


def nomes(projeto, base: str = "") -> dict:
    """Caminho no projeto -> nome do arquivo pelo título. Só os arquivos que existem. `base` troca o nome do título
    (a entrega encurta quando o caminho passa do que o Windows aceita)."""
    base = base or nome_do_titulo(titulo(projeto))
    saida = {}
    for arquivo, nome in (("final.mp4", f"{base}.mp4"), ("final_vertical.mp4", f"{base} (em pé).mp4"),
                          ("thumbnail.jpg", f"{base}.jpg"), ("legendas_final.srt", f"{base}.srt")):
        if projeto.existe(arquivo):
            saida[arquivo] = nome
    usados = set()
    for k, s in enumerate(_shorts(projeto), 1):
        nome = nome_do_titulo(_titulo_do_short(s) or f"{base} short {k}", 80)
        if nome.lower() in usados:  # dois shorts com o mesmo título não se sobrescrevem
            nome = f"{nome} {k}"
        usados.add(nome.lower())
        saida[s["arquivo"]] = f"{nome}.mp4"
    return saida


def nome_para_baixar(projeto, caminho: str) -> str | None:
    return nomes(projeto).get(caminho.replace("\\", "/"))


def _canal(projeto) -> str:
    return str((getattr(projeto, "perfil", None) or {}).get("nome") or "").strip()


def _lingua(projeto) -> str:
    from . import idioma

    return LINGUA_DO_AUDIO.get(idioma.lingua(projeto), "")


def metadados(projeto) -> dict:
    """Caminho no projeto -> as etiquetas do MP4. O vídeo e a versão em pé levam o kit; cada short, o texto dele."""
    kit = projeto.ler_json("publicacao.json") if projeto.existe("publicacao.json") else {}
    canal, ano = _canal(projeto), str(date.today().year)
    comum = {"artist": canal, "album_artist": canal, "date": ano,
             "copyright": f"© {ano} {canal}".strip() if canal else ""}
    principal = {"title": titulo(projeto), "description": kit.get("descricao") or "",
                 "comment": kit.get("descricao") or "", "keywords": ", ".join(kit.get("tags") or []), **comum}
    saida = {a: principal for a in ("final.mp4", "final_vertical.mp4") if projeto.existe(a)}
    for s in _shorts(projeto):
        descricao = str(s.get("descricao") or "")
        saida[s["arquivo"]] = {"title": _titulo_do_short(s) or principal["title"], "description": descricao,
                               "comment": descricao, "keywords": ", ".join((kit.get("tags") or [])[:10]), **comum}
    return {a: {k: v for k, v in m.items() if v} for a, m in saida.items()}


def _marca(etiquetas: dict, lingua: str) -> str:
    return hashlib.sha1(json.dumps([etiquetas, lingua], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _embutir(arquivo: Path, etiquetas: dict, lingua: str) -> None:
    antes = arquivo.stat()
    temporario = arquivo.with_name(f"{arquivo.stem}.meta.tmp{arquivo.suffix}")  # ".tmp." os shorts não apagam
    comando = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(arquivo), "-map", "0:v?", "-map", "0:a?",
               "-c", "copy", "-map_metadata", "-1"]
    for chave, valor in etiquetas.items():
        comando += ["-metadata", f"{chave}={valor}"]
    if lingua:
        comando += ["-metadata:s:a:0", f"language={lingua}"]
    comando += ["-movflags", "+faststart", str(temporario)]
    try:
        rodar(comando)
        for tentativa in range(40):  # no Windows a troca falha enquanto outro programa lê o arquivo
            try:
                temporario.replace(arquivo)
                break
            except PermissionError:
                if tentativa == 39:
                    raise
                time.sleep(0.25)
    finally:
        temporario.unlink(missing_ok=True)
    os.utime(arquivo, ns=(antes.st_atime_ns, antes.st_mtime_ns))  # a revisão e a checagem seguem valendo


def gravar(projeto, log=print) -> int:
    """Grava os metadados nos MP4 que mudaram desde a última vez. Devolve quantos arquivos foram gravados."""
    feitos = projeto.ler_json(ARQUIVO) if projeto.existe(ARQUIVO) else {}
    lingua, gravados = _lingua(projeto), 0
    for arquivo, etiquetas in metadados(projeto).items():
        caminho = projeto.pasta / arquivo
        marca = _marca(etiquetas, lingua)
        anterior = feitos.get(arquivo) or {}
        if anterior.get("marca") == marca and anterior.get("data") == caminho.stat().st_mtime_ns:
            continue
        try:
            _embutir(caminho, etiquetas, lingua)
        except (Exception, SystemExit) as erro:
            log(f"  metadados de {arquivo} não gravados ({str(erro)[:120]}); a próxima entrega tenta de novo")
            continue
        feitos[arquivo] = {"marca": marca, "data": caminho.stat().st_mtime_ns, "titulo": etiquetas.get("title", "")}
        gravados += 1
    if gravados:
        projeto.salvar_json(ARQUIVO, feitos)
        log(f"  metadados do YouTube gravados em {gravados} arquivo(s): título, descrição, tags e canal")
    return gravados
