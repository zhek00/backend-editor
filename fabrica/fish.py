"""Voz da Fish Audio pelo OpenRouter (fish-audio/s2.1-pro-free:free, grátis), no lugar do Edge-TTS.

A voz sai do POST /audio/speech do OpenRouter. As vozes são as da biblioteca pública da Fish Audio (api.fish.audio,
sem chave): o código da voz vai no campo voice. Sem voz, sai a voz padrão do modelo.

A Fish devolve só o áudio, sem o tempo de cada palavra, e a fábrica precisa dele para a legenda, os cortes das cenas
e os textos que entram na palavra falada. O tempo vem de uma transcrição com tempo por palavra
(POST /audio/transcriptions, Whisper turbo por padrão, uns centavos por vídeo): as palavras ouvidas são casadas com
as do roteiro. Sem saldo para a transcrição (o OpenRouter pede US$ 0,50 de saldo para áudio), o tempo é estimado
pelas pausas do áudio (narracao._palavras_estimadas), mais grosso, mas o vídeo nunca para.
"""
import base64
import difflib
import re
import time

import httpx

from . import openrouter_local

URL_FALA = "https://openrouter.ai/api/v1/audio/speech"
URL_TRANSCRICAO = "https://openrouter.ai/api/v1/audio/transcriptions"
URL_VOZES = "https://api.fish.audio/model"
MODELO_PADRAO = "fish-audio/s2.1-pro-free:free"
TRANSCRICAO_PADRAO = "openai/whisper-large-v3-turbo"
VELOCIDADE_MIN, VELOCIDADE_MAX = 0.7, 1.3


class ErroFish(RuntimeError):
    pass


def config() -> dict:
    from .config import config_geral
    return config_geral().get("fish") or {}


def modelo(voz=None) -> str:
    return (voz or {}).get("modelo_fish") or config().get("modelo") or MODELO_PADRAO


def vozes(busca=None, idioma="pt", genero=None, quantidade=30) -> list:
    """Vozes da biblioteca pública da Fish Audio, as mais usadas primeiro, no formato do seletor do editor."""
    parametros = {"page_size": min(max(quantidade, 1), 100), "type": "tts", "sort_by": "score"}
    if idioma:
        parametros["language"] = idioma
    if busca:
        parametros["title"] = busca
    try:
        r = httpx.get(URL_VOZES, params=parametros, timeout=30)
        r.raise_for_status()
        itens = r.json().get("items") or []
    except (httpx.HTTPError, ValueError) as erro:
        raise ErroFish(f"Não consegui ler a biblioteca de vozes da Fish Audio ({str(erro)[:120]}).")
    lista = []
    for m in itens:
        tags = [str(t).lower() for t in (m.get("tags") or [])]
        sexo = "male" if "male" in tags else "female" if "female" in tags else ""
        if genero and sexo and genero != sexo:
            continue
        amostra = next((s.get("audio") for s in (m.get("samples") or []) if s.get("audio")), None)
        lista.append({
            "voice_id": m.get("_id"),
            "nome": (m.get("title") or "").strip() or "Voz sem nome",
            "descricao": (m.get("description") or "").strip()[:220],
            "genero": {"male": "masculina", "female": "feminina"}.get(sexo, ""),
            "idade": next((t for t in tags if t in ("young", "middle-aged", "old")), ""),
            "previa": amostra,
            "usos": m.get("task_count") or 0,
        })
    return lista


def narrar(texto: str, voz: dict, mp3, log=print) -> None:
    """Grava o texto em mp3 pela Fish Audio no OpenRouter. Grátis; tenta de novo em segundos quando o servidor
    gratuito está cheio, e só então desiste."""
    corpo = {"model": modelo(voz), "input": texto, "response_format": "mp3"}
    voice_id = str(voz.get("voice_id") or "").strip()
    if voice_id:
        corpo["voice"] = voice_id
    velocidade = float(voz.get("velocidade") or 1.0)
    if abs(velocidade - 1.0) > 0.001:
        corpo["speed"] = round(min(max(velocidade, VELOCIDADE_MIN), VELOCIDADE_MAX), 2)
    cabecalho = {"Authorization": f"Bearer {openrouter_local._chave()}"}
    ultimo = ""
    for tentativa in range(5):
        try:
            r = httpx.post(URL_FALA, json=corpo, headers=cabecalho, timeout=600)
        except httpx.HTTPError as erro:
            ultimo = str(erro)[:150]
            time.sleep(3 * (tentativa + 1))
            continue
        if r.status_code == 200 and len(r.content) > 1000:
            mp3.write_bytes(r.content)
            return
        ultimo = f"{r.status_code} {r.text[:200]}"
        if r.status_code in (400, 401, 403) and "voice" in corpo and tentativa >= 1:
            # a voz pode ter saído da biblioteca: grava com a voz padrão em vez de parar o vídeo
            log(f"    a Fish recusou a voz {voice_id} ({r.status_code}); gravando com a voz padrão")
            corpo.pop("voice")
            continue
        if r.status_code in (401,):
            raise ErroFish("A chave do OpenRouter foi recusada. Confira o arquivo .env.")
        time.sleep(3 * (tentativa + 1))
    raise ErroFish(f"A Fish Audio não gravou o áudio ({ultimo}). Rode de novo: o que já foi gravado fica guardado.")


def palavras_com_tempo(audio, texto: str, idioma: str = "pt") -> tuple:
    """([(palavra do roteiro, início, fim)], custo em US$) pela transcrição com tempo por palavra.

    As palavras ouvidas são casadas com as do roteiro (a transcrição escreve "1070" por extenso, tira pontuação,
    erra um nome): só as que casam ganham tempo, e _alinhar_pelas_palavras interpola o resto."""
    dados = base64.b64encode(audio.read_bytes()).decode()
    corpo = {"model": config().get("transcricao") or TRANSCRICAO_PADRAO,
             "input_audio": {"data": dados, "format": audio.suffix.lstrip(".") or "mp3"},
             "language": idioma or "pt", "response_format": "verbose_json", "timestamp_granularities": ["word"]}
    cabecalho = {"Authorization": f"Bearer {openrouter_local._chave()}"}
    ultimo = ""
    for tentativa in range(3):
        try:
            r = httpx.post(URL_TRANSCRICAO, json=corpo, headers=cabecalho, timeout=600)
        except httpx.HTTPError as erro:
            ultimo = str(erro)[:150]
            time.sleep(3 * (tentativa + 1))
            continue
        if r.status_code == 200:
            resposta = r.json()
            ouvidas = [(w.get("word") or "", float(w.get("start") or 0), float(w.get("end") or 0))
                       for w in (resposta.get("words") or [])]
            if not ouvidas:
                raise ErroFish("a transcrição voltou sem o tempo das palavras")
            return _casar_com_o_roteiro(texto, ouvidas), float((resposta.get("usage") or {}).get("cost") or 0)
        ultimo = f"{r.status_code} {r.text[:200]}"
        if r.status_code in (400, 401, 402, 403):
            break  # sem saldo ou pedido recusado: esperar não resolve
        time.sleep(3 * (tentativa + 1))
    raise ErroFish(f"a transcrição não respondeu ({ultimo})")


def _normal(palavra: str) -> str:
    return re.sub(r"[^\w]", "", palavra.lower())


def _casar_com_o_roteiro(texto: str, ouvidas: list) -> list:
    roteiro = [m.group() for m in re.finditer(r"\S+", texto)]
    a = [_normal(p) for p in roteiro]
    b = [_normal(p) for p, _, _ in ouvidas]
    casadas = []
    for bloco in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(bloco.size):
            _, t0, t1 = ouvidas[bloco.b + k]
            casadas.append((roteiro[bloco.a + k], t0, t1))
    return casadas
