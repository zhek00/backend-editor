"""Áudio de meditação guiada. Fala curta, silêncio longo e música baixa.

O roteiro é texto comum com a marcação [SILENCIO 90] numa linha própria. O tempo vai em
segundos, ou em minutos e segundos como [SILENCIO 1:30]. A ElevenLabs narra só as falas,
uma chamada por fala, e o silêncio vem do FFmpeg, sem custo. Cada fala gravada fica
guardada pelo texto e pela voz, então mudar uma fala só regrava aquela.
"""
import hashlib
import re

from . import texto as tx
from .config import caminho_relativo
from .narracao import TAXA, _elevenlabs, _voz_do_mac
from .render import EXTENSOES_AUDIO, _musica, _normalizar
from .util import duracao_audio, rodar

SILENCIO = re.compile(r"\[SIL[EÊ]NCIO\s+(\d+(?::[0-5]?\d)?)\s*\]", re.IGNORECASE)
ENTRADA = 0.5  # silêncio antes da primeira fala, para nenhum tocador engolir o começo


def trechos(roteiro: str) -> list[dict]:
    """Falas e silêncios na ordem em que aparecem no roteiro."""
    lista, linhas = [], []

    def fechar_fala():
        fala = tx.extrair_marcadores("\n".join(linhas))[0]
        if fala:
            lista.append({"tipo": "fala", "texto": fala})
        linhas.clear()

    for linha in roteiro.replace("\r\n", "\n").split("\n"):
        m = SILENCIO.fullmatch(linha.strip())
        if not m:
            linhas.append(linha)
            continue
        fechar_fala()
        segundos = _segundos(m.group(1))
        if lista and lista[-1]["tipo"] == "silencio":
            lista[-1]["segundos"] += segundos
        else:
            lista.append({"tipo": "silencio", "segundos": segundos})
    fechar_fala()
    return lista


def _segundos(valor: str) -> float:
    if ":" in valor:
        minutos, segundos = valor.split(":")
        return int(minutos) * 60 + int(segundos)
    return float(valor)


def estimar(projeto) -> dict:
    lista = trechos(_roteiro(projeto))
    voz = projeto.perfil.get("voz") or {}
    falas = [_com_tom(t["texto"], voz) for t in lista if t["tipo"] == "fala"]
    caracteres = sum(len(f) for f in falas)
    silencio = sum(t["segundos"] for t in lista if t["tipo"] == "silencio")
    por_minuto = (projeto.perfil.get("ritmo") or {}).get("caracteres_por_minuto") or 500
    preco = (projeto.config.get("precos") or {}).get("elevenlabs_por_mil_caracteres", 0.10)
    faltam = sum(not _arquivo_fala(projeto, f, voz).exists() for f in falas)
    return {
        "falas": len(falas),
        "faltam": faltam,
        "caracteres": caracteres,
        "silencio": silencio,
        "duracao": ENTRADA + caracteres / por_minuto * 60 + silencio,
        "voz": caracteres / 1000 * preco,
    }


def gerar(projeto, imagem=None, log=print):
    """Grava as falas que faltam, emenda com os silêncios, mistura a música e salva o áudio."""
    lista = trechos(_roteiro(projeto))
    if not any(t["tipo"] == "fala" for t in lista):
        raise SystemExit("O roteiro não tem nenhuma fala.")
    voz = projeto.perfil.get("voz") or {}
    total = sum(t["tipo"] == "fala" for t in lista)
    wavs, n = [_silencio(projeto, ENTRADA)], 0
    for t in lista:
        if t["tipo"] == "silencio":
            wavs.append(_silencio(projeto, t["segundos"]))
            continue
        n += 1
        texto = _com_tom(t["texto"], voz)
        wav = _arquivo_fala(projeto, texto, voz)
        if not wav.exists():
            log(f"  narrando fala {n} de {total}")
            if projeto.offline:
                _voz_do_mac(texto, voz, wav)
            else:
                _elevenlabs(texto, None, None, voz, wav)
        wavs.append(wav)

    emendada = _juntar(projeto, wavs)
    duracao = duracao_audio(emendada)
    pronta = projeto.caminho("meditacao", "voz_pronta.wav")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", emendada, "-af",
           f"{_normalizar(emendada)},aresample=48000,aformat=channel_layouts=stereo", "-c:a", "pcm_s16le", pronta])

    mp3 = projeto.caminho("meditacao.mp3")
    musica = _musica(projeto, duracao) if _tem_musica(projeto, log) else None
    if musica:
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", pronta, "-i", musica, "-filter_complex",
               "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]", "-map", "[a]",
               "-c:a", "libmp3lame", "-b:a", "192k", mp3])
    else:
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", pronta, "-c:a", "libmp3lame", "-b:a", "192k", mp3])
    saida = _video(projeto, mp3, imagem) if imagem else mp3
    return saida, duracao


def _roteiro(projeto) -> str:
    return (projeto.pasta / "roteiro.txt").read_text(encoding="utf-8")


def _com_tom(texto: str, voz: dict) -> str:
    """O perfil pode pedir uma tag do v3 antes de cada fala, como [softly]."""
    tom = str(voz.get("tom") or "").strip()
    return f"{tom} {texto}" if tom else texto


def _arquivo_fala(projeto, texto: str, voz: dict):
    chave = "offline" if projeto.offline else f"{voz.get('voice_id')}|{voz.get('modelo')}|{voz.get('estabilidade')}"
    codigo = hashlib.sha1(f"{chave}|{texto}".encode()).hexdigest()[:10]
    return projeto.caminho("meditacao", f"fala_{codigo}_bruto.wav")


def _silencio(projeto, segundos: float):
    wav = projeto.caminho("meditacao", f"silencio_{segundos:g}.wav")
    if not wav.exists():
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r={TAXA}:cl=mono",
               "-t", f"{segundos:.3f}", "-c:a", "pcm_s16le", wav])
    return wav


def _juntar(projeto, wavs):
    lista = projeto.caminho("meditacao", "lista.txt")
    lista.write_text("".join(f"file '{w}'\n" for w in wavs), encoding="utf-8")
    destino = projeto.caminho("meditacao", "voz.wav")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lista, "-c:a", "pcm_s16le", destino])
    return destino


def _tem_musica(projeto, log) -> bool:
    origem = projeto.perfil.get("musica")
    if not origem:
        return False
    caminho = caminho_relativo(origem)
    if caminho.is_file():
        return True
    if caminho.is_dir() and any(f.suffix.lower() in EXTENSOES_AUDIO for f in caminho.iterdir()):
        return True
    log(f"  sem música, porque não há nenhum áudio em {caminho}")
    return False


def _video(projeto, audio, imagem):
    """MP4 com a imagem parada e o áudio, para plataforma que só aceita vídeo."""
    cfg = projeto.config.get("render") or {}
    largura, altura = cfg.get("largura", 1920), cfg.get("altura", 1080)
    destino = projeto.caminho("meditacao.mp4")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "1", "-i", imagem, "-i", audio,
           "-vf", f"scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
                  f"pad={largura}:{altura}:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
           "-r", "24", "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "192k", "-shortest", destino])
    return destino
