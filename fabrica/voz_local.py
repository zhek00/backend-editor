"""Vozes open source do VoiceStudio e do voicebox, rodando dentro da fábrica, no lugar das narrações pagas.

Pedidos do usuário em 2026-10-28: "vamos cancelar assinaturas de narração pagas e utilizar as opensource" e "não quero
instalar, quero ter todas as vozes dos dois github disponíveis na nossa fábrica". Os apps não são instalados: a
fábrica roda os mesmos motores abertos que eles usam (motores_voz/servidor.py), na placa de vídeo, sem chave e sem
custo. As vozes:

- **VoiceStudio** (motor OmniVoice): as vozes desenhadas da galeria dele (manifest da omnivoice-gallery, com nome:
  "The Documentarian", "Portuguese Narrator"...), as gravadas da comunidade (Lucas e Thalia, pt-BR, CC-BY-4.0, clonadas
  da gravação) e qualquer combinação de gênero, idade, tom, sussurro e sotaque (`omnivoice:male, middle-aged, low
  pitch`), que é o que o "Browse all" dele gera.
- **voicebox**: as 54 vozes prontas do Kokoro (`kokoro:pm_alex`, 3 em português), as 9 do Qwen3-TTS CustomVoice
  (`qwen:Ryan`) e a voz por descrição livre do Qwen VoiceDesign (`qwen_design:voz masculina grave e calma`).

O perfil escolhe a voz pelo código em `voz.voz_local` (sem ele, `voz_local.voz` do config.yaml). O servidor do motor
é ligado na primeira fala e desligado no fim da narração (`desligar`), para liberar a placa para o resto do vídeo. O
tempo de cada palavra vem do Whisper do Groq (grátis); sem ele, das pausas do áudio (narracao._palavras_estimadas).
"""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from .config import RAIZ

PASTA = RAIZ / "motores_voz"
PROVEDORES = ("local",)
# cada ambiente roda um servidor (pedem versões diferentes do transformers)
AMBIENTES = {
    "omnivoice": {"porta": 3931, "motores": ["omnivoice", "kokoro"]},
    "qwen": {"porta": 3932, "motores": ["qwen", "qwen_design"]},
}
MOTOR_NO_AMBIENTE = {m: amb for amb, d in AMBIENTES.items() for m in d["motores"]}
ORIGEM = {"omnivoice": "VoiceStudio", "kokoro": "voicebox", "qwen": "voicebox", "qwen_design": "voicebox"}
VOZ_PADRAO = "omnivoice:community_pt_br_lucas"
URL_GALERIA = "https://cdn.jsdelivr.net/gh/debpalash/omnivoice-gallery@main/manifest.json"

# Vozes prontas do voicebox (backend/backends/kokoro_backend.py e qwen_custom_voice_backend.py): código, nome,
# gênero e língua nativa. São os nomes das vozes dos próprios modelos (Kokoro-82M e Qwen3-TTS CustomVoice)
KOKORO = [
    ("af_alloy", "Alloy", "f", "en"), ("af_aoede", "Aoede", "f", "en"), ("af_bella", "Bella", "f", "en"),
    ("af_heart", "Heart", "f", "en"), ("af_jessica", "Jessica", "f", "en"), ("af_kore", "Kore", "f", "en"),
    ("af_nicole", "Nicole", "f", "en"), ("af_nova", "Nova", "f", "en"), ("af_river", "River", "f", "en"),
    ("af_sarah", "Sarah", "f", "en"), ("af_sky", "Sky", "f", "en"), ("am_adam", "Adam", "m", "en"),
    ("am_echo", "Echo", "m", "en"), ("am_eric", "Eric", "m", "en"), ("am_fenrir", "Fenrir", "m", "en"),
    ("am_liam", "Liam", "m", "en"), ("am_michael", "Michael", "m", "en"), ("am_onyx", "Onyx", "m", "en"),
    ("am_puck", "Puck", "m", "en"), ("am_santa", "Santa", "m", "en"), ("bf_alice", "Alice", "f", "en-gb"),
    ("bf_emma", "Emma", "f", "en-gb"), ("bf_isabella", "Isabella", "f", "en-gb"), ("bf_lily", "Lily", "f", "en-gb"),
    ("bm_daniel", "Daniel", "m", "en-gb"), ("bm_fable", "Fable", "m", "en-gb"), ("bm_george", "George", "m", "en-gb"),
    ("bm_lewis", "Lewis", "m", "en-gb"), ("ef_dora", "Dora", "f", "es"), ("em_alex", "Alex", "m", "es"),
    ("em_santa", "Santa", "m", "es"), ("ff_siwis", "Siwis", "f", "fr"), ("hf_alpha", "Alpha", "f", "hi"),
    ("hf_beta", "Beta", "f", "hi"), ("hm_omega", "Omega", "m", "hi"), ("hm_psi", "Psi", "m", "hi"),
    ("if_sara", "Sara", "f", "it"), ("im_nicola", "Nicola", "m", "it"), ("jf_alpha", "Alpha", "f", "ja"),
    ("jf_gongitsune", "Gongitsune", "f", "ja"), ("jf_nezumi", "Nezumi", "f", "ja"),
    ("jf_tebukuro", "Tebukuro", "f", "ja"), ("jm_kumo", "Kumo", "m", "ja"), ("pf_dora", "Dora", "f", "pt"),
    ("pm_alex", "Alex", "m", "pt"), ("pm_santa", "Santa", "m", "pt"), ("zf_xiaobei", "Xiaobei", "f", "zh"),
    ("zf_xiaoni", "Xiaoni", "f", "zh"), ("zf_xiaoxiao", "Xiaoxiao", "f", "zh"), ("zf_xiaoyi", "Xiaoyi", "f", "zh"),
    ("zm_yunjian", "Yunjian", "m", "zh"), ("zm_yunxi", "Yunxi", "m", "zh"), ("zm_yunxia", "Yunxia", "m", "zh"),
    ("zm_yunyang", "Yunyang", "m", "zh"),
]
QWEN = [
    ("Vivian", "f", "zh", "jovem, brilhante e um pouco ousada"), ("Serena", "f", "zh", "jovem, quente e suave"),
    ("Uncle_Fu", "m", "zh", "madura, grave e aveludada"), ("Dylan", "m", "zh", "jovem de Pequim, clara e natural"),
    ("Eric", "m", "zh", "de Chengdu, viva e levemente rouca"), ("Ryan", "m", "en", "dinâmica, com ritmo forte"),
    ("Aiden", "m", "en", "americana ensolarada, médios claros"), ("Ono_Anna", "f", "ja", "japonesa, leve e ágil"),
    ("Sohee", "f", "ko", "coreana, quente e emotiva"),
]
# Vocabulário da voz desenhada do OmniVoice (k2-fsa/OmniVoice, omnivoice/utils/voice_design.py): um de cada grupo
GENEROS = ["male", "female"]
IDADES = ["child", "teenager", "young adult", "middle-aged", "elderly"]
TONS = ["very low pitch", "low pitch", "moderate pitch", "high pitch", "very high pitch"]
SOTAQUES = ["american accent", "australian accent", "british accent", "canadian accent", "chinese accent",
            "indian accent", "japanese accent", "korean accent", "portuguese accent", "russian accent"]
_IMPLAUSIVEL = {"child": {"very low pitch", "low pitch"}, "teenager": {"very low pitch"},
                "elderly": {"very high pitch"}}
LINGUAS = {"English": "en", "Portuguese": "pt", "Spanish": "es", "French": "fr", "German": "de", "Italian": "it",
           "Russian": "ru", "Hindi": "hi", "Japanese": "ja", "Korean": "ko", "Chinese": "zh"}


class ErroVozLocal(RuntimeError):
    pass


def config() -> dict:
    from .config import config_geral
    return config_geral().get("voz_local") or {}


def e_local(voz: dict) -> bool:
    return (voz or {}).get("provedor") in PROVEDORES


def codigo_da_voz(voz: dict) -> str:
    return str((voz or {}).get("voz_local") or config().get("voz") or VOZ_PADRAO).strip()


# ── catálogo ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _galeria() -> list:
    """Itens da galeria do VoiceStudio (omnivoice-gallery). Guardada em motores_voz/vozes/galeria.json; sem rede,
    vale a cópia guardada."""
    guardada = PASTA / "vozes" / "galeria.json"
    if not guardada.exists() or time.time() - guardada.stat().st_mtime > 86400:
        try:
            r = httpx.get(URL_GALERIA, timeout=20, follow_redirects=True)
            r.raise_for_status()
            itens = r.json().get("items") or []
            guardada.parent.mkdir(parents=True, exist_ok=True)
            guardada.write_text(json.dumps(itens, ensure_ascii=False), encoding="utf-8")
        except (httpx.HTTPError, ValueError, OSError):
            pass
    try:
        return json.loads(guardada.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _genero(g) -> str:
    return {"male": "masculina", "m": "masculina", "female": "feminina", "f": "feminina"}.get(g or "", "")


def catalogo() -> list:
    """Todas as vozes: as da galeria do VoiceStudio, as desenhadas por combinação, as do Kokoro e as do Qwen."""
    vozes = []
    for item in _galeria():
        facetas = item.get("facets") or {}
        base = {"motor": "omnivoice", "origem": "VoiceStudio", "nome": item.get("name"),
                "idioma": LINGUAS.get(item.get("language"), str(item.get("language") or "").lower()),
                "genero": _genero(facetas.get("gender")),
                "uso": item.get("use_case") or "", "licenca": item.get("license") or "",
                "autor": item.get("author") or ""}
        if item.get("type") == "voice" and (item.get("audio") or {}).get("url"):
            vozes.append({**base, "id": f"omnivoice:{item['id']}", "tipo": "gravada",
                          "descricao": f"voz gravada por {item.get('author')}, clonada da gravação"})
        elif item.get("instruct"):
            vozes.append({**base, "id": f"omnivoice:{item['id']}", "tipo": "desenhada",
                          "descricao": item["instruct"]})
    for genero in GENEROS:
        for idade in IDADES:
            for tom in TONS:
                if tom in _IMPLAUSIVEL.get(idade, ()):
                    continue
                extras = [None] + SOTAQUES
                if idade in ("young adult", "middle-aged", "elderly") and tom in ("low pitch", "moderate pitch"):
                    extras.append("whisper")
                for extra in extras:
                    atributos = ", ".join(x for x in (genero, idade, tom, extra) if x)
                    vozes.append({"id": f"omnivoice:{atributos}", "motor": "omnivoice", "origem": "VoiceStudio",
                                  "tipo": "desenhada", "nome": atributos, "idioma": "", "genero": _genero(genero),
                                  "descricao": "voz desenhada pelo OmniVoice (fala qualquer língua)"})
    for codigo, nome, genero, lingua in KOKORO:
        vozes.append({"id": f"kokoro:{codigo}", "motor": "kokoro", "origem": "voicebox", "tipo": "pronta",
                      "nome": nome, "idioma": lingua.split("-")[0], "genero": _genero(genero),
                      "descricao": f"Kokoro, voz {'britânica' if lingua == 'en-gb' else 'nativa'} ({lingua})"})
    for codigo, genero, lingua, desc in QWEN:
        vozes.append({"id": f"qwen:{codigo}", "motor": "qwen", "origem": "voicebox", "tipo": "pronta",
                      "nome": codigo.replace("_", " "), "idioma": "", "nativa": lingua, "genero": _genero(genero),
                      "descricao": f"Qwen3-TTS, {desc} (fala 10 línguas, português incluído)"})
    vozes.append({"id": "qwen_design:", "motor": "qwen_design", "origem": "voicebox", "tipo": "por descrição",
                  "nome": "Voz por descrição", "idioma": "", "genero": "",
                  "descricao": "escreva a voz depois dos dois-pontos: qwen_design:voz masculina grave e calma"})
    return vozes


def resolver(codigo: str) -> tuple:
    """(motor, voz para o servidor) a partir do código do catálogo."""
    motor, _, resto = (codigo or VOZ_PADRAO).partition(":")
    resto = resto.strip()
    if motor == "kokoro":
        if resto not in {c for c, *_ in KOKORO}:
            raise ErroVozLocal(f"o Kokoro não tem a voz '{resto}'")
        return "kokoro", {"codigo": resto}
    if motor == "qwen":
        if resto not in {c for c, *_ in QWEN}:
            raise ErroVozLocal(f"o Qwen3-TTS não tem a voz '{resto}'")
        return "qwen", {"codigo": resto}
    if motor == "qwen_design":
        if not resto:
            raise ErroVozLocal("a voz por descrição precisa da descrição: qwen_design:voz masculina grave e calma")
        return "qwen_design", {"descricao": resto[:500]}
    if motor == "omnivoice":
        item = next((i for i in _galeria() if i.get("id") == resto), None)
        if item and item.get("type") == "voice":
            return "omnivoice", {"referencia": str(_gravacao(item)),
                                 "texto_referencia": (item.get("audio") or {}).get("ref_text") or ""}
        if item:
            return "omnivoice", {"atributos": item.get("instruct") or ""}
        validos = set(GENEROS + IDADES + TONS + SOTAQUES + ["whisper"])
        partes = [p.strip().lower() for p in resto.split(",") if p.strip()]
        if not partes or any(p not in validos for p in partes):
            raise ErroVozLocal(f"voz do OmniVoice desconhecida: '{resto}' (use um item da galeria ou atributos "
                               f"como 'male, middle-aged, low pitch')")
        return "omnivoice", {"atributos": ", ".join(partes)}
    raise ErroVozLocal(f"voz local desconhecida: '{codigo}'")


def _gravacao(item) -> Path:
    """A gravação de uma voz da comunidade, baixada uma vez e conferida pelo SHA-256 da galeria."""
    audio = item.get("audio") or {}
    destino = PASTA / "vozes" / f"{item['id']}.wav"
    if destino.exists() and hashlib.sha256(destino.read_bytes()).hexdigest() == audio.get("sha256"):
        return destino
    r = httpx.get(audio["url"], timeout=120, follow_redirects=True)
    r.raise_for_status()
    if audio.get("sha256") and hashlib.sha256(r.content).hexdigest() != audio["sha256"]:
        raise ErroVozLocal(f"a gravação da voz {item['id']} não confere com a galeria")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(r.content)
    return destino


def credito(codigo: str) -> str:
    """Crédito da voz para a descrição do vídeo (vozes da comunidade são CC-BY-4.0: pedem o autor)."""
    motor, _, resto = (codigo or "").partition(":")
    item = next((i for i in _galeria() if i.get("id") == resto), None) if motor == "omnivoice" else None
    if item and item.get("type") == "voice":
        return f"Voz: {item.get('name')}, por {item.get('author')} ({item.get('license')}), via VoiceStudio Gallery"
    return ""


# ── servidor de voz ───────────────────────────────────────────────────────────────────────────────────────────────

def _url(ambiente) -> str:
    return f"http://127.0.0.1:{AMBIENTES[ambiente]['porta']}"


def _no_ar(ambiente) -> bool:
    try:
        return httpx.get(_url(ambiente) + "/saude", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def _python(ambiente) -> Path:
    pasta = PASTA / ambiente / ".venv"
    return pasta / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def instalado(ambiente) -> bool:
    return _python(ambiente).exists()


def ligar(ambiente, log=print, espera=180) -> None:
    """Liga o servidor do ambiente (e desliga o outro, para a placa caber um modelo só)."""
    if _no_ar(ambiente):
        return
    for outro in AMBIENTES:
        if outro != ambiente:
            desligar(outro)
    if not instalado(ambiente):
        raise ErroVozLocal(f"o motor de voz '{ambiente}' não está preparado. Rode uma vez: "
                           f"uv sync --project motores_voz/{ambiente}")
    ambiente_os = {**os.environ, "HF_HOME": str(PASTA / "modelos"), "PYTHONIOENCODING": "utf-8",
                   "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"}
    registro = open(PASTA / f"{ambiente}.log", "a", encoding="utf-8")
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
    processo = subprocess.Popen(
        [str(_python(ambiente)), "-I", "-X", "utf8", str(PASTA / "servidor.py"), "--porta", str(AMBIENTES[ambiente]["porta"]),
         "--motores", ",".join(AMBIENTES[ambiente]["motores"])],
        cwd=str(PASTA), env=ambiente_os, stdout=registro, stderr=registro, creationflags=flags)
    (PASTA / f"{ambiente}.pid").write_text(str(processo.pid))
    log(f"  ligando o motor de voz {ambiente} (primeira vez baixa o modelo, alguns minutos)")
    limite = time.time() + espera
    while time.time() < limite:
        if processo.poll() is not None:
            raise ErroVozLocal(f"o motor de voz {ambiente} fechou ao ligar (veja motores_voz/{ambiente}.log)")
        if _no_ar(ambiente):
            return
        time.sleep(1)
    raise ErroVozLocal(f"o motor de voz {ambiente} não respondeu em {espera} s (veja motores_voz/{ambiente}.log)")


def desligar(ambiente=None) -> None:
    """Desliga o servidor (todos, sem dizer qual), liberando a placa de vídeo."""
    for amb in ([ambiente] if ambiente else list(AMBIENTES)):
        # o servidor sai sozinho a pedido (no Windows, matar pelo número guardado deixava vivo o segundo processo
        # que o python do .venv abre, segurando a placa de vídeo); o número guardado fica de reserva
        try:
            httpx.post(_url(amb) + "/desligar", timeout=3)
            for _ in range(20):
                if not _no_ar(amb):
                    break
                time.sleep(0.5)
        except httpx.HTTPError:
            pass
        arquivo = PASTA / f"{amb}.pid"
        if not arquivo.exists():
            continue
        try:
            pid = int(arquivo.read_text().strip())
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.kill(pid, 15)
        except (ValueError, OSError):
            pass
        arquivo.unlink(missing_ok=True)


def passos_omnivoice() -> int:
    """Passos do OmniVoice: 16, o padrão do próprio VoiceStudio. Medido num trecho de 91 s de fala (RTX 2060): 32
    passos 35 s, 16 passos 19 s, os dois 100% iguais ao roteiro na transcrição; 8 passos 10 s, mas só 67% igual."""
    return max(8, min(64, int(config().get("passos_omnivoice") or 16)))


def preparar(voz: dict, log=print) -> dict:
    """Resolve a voz do perfil e liga o motor dela. Devolve o que narrar() precisa."""
    codigo = codigo_da_voz(voz)
    motor, dados = resolver(codigo)
    if motor == "omnivoice":
        dados = {**dados, "passos": passos_omnivoice()}
    ambiente = MOTOR_NO_AMBIENTE[motor]
    with _usando():
        ligar(ambiente, log)
    return {"codigo": codigo, "motor": motor, "voz": dados, "ambiente": ambiente}


def narrar(texto: str, voz: dict, saida: Path, preparada: dict, log=print) -> None:
    """Grava o texto em `saida` (wav) no motor local. Velocidade diferente de 1 que o motor não aplica vai pelo
    atempo do FFmpeg, que não muda o tom."""
    velocidade = round(min(max(float(voz.get("velocidade") or 1.0), 0.7), 1.3), 2)
    corpo = {"motor": preparada["motor"], "texto": texto, "idioma": (voz.get("idioma") or "pt")[:2],
             "voz": {**preparada["voz"], **({"instrucao": voz["instrucao"]} if voz.get("instrucao") else {})},
             "velocidade": velocidade, "saida": str(saida)}
    ultimo = ""
    for tentativa in range(3):
        try:
            with _usando():
                r = httpx.post(_url(preparada["ambiente"]) + "/falar", json=corpo, timeout=3600)
        except httpx.HTTPError as erro:
            ultimo = str(erro)[:150]
            ligar(preparada["ambiente"], log)  # o servidor pode ter caído: liga de novo
            continue
        if r.status_code == 200 and saida.exists():
            resposta = r.json()
            if abs(velocidade - 1.0) > 0.001 and not resposta.get("velocidade_aplicada"):
                from .util import rodar
                tmp = saida.with_suffix(".lento.wav")
                rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", saida, "-af", f"atempo={velocidade}", tmp])
                tmp.replace(saida)
            return
        ultimo = f"{r.status_code} {r.text[:300]}"
        if r.status_code == 400:
            break
        time.sleep(3 * (tentativa + 1))
    raise ErroVozLocal(f"o motor de voz {preparada['motor']} não gravou o áudio ({ultimo})")


# ── tempo de cada palavra ─────────────────────────────────────────────────────────────────────────────────────────

def palavras_com_tempo(audio, texto: str, idioma: str = "pt", log=print) -> tuple:
    """([(palavra do roteiro, início, fim)], de onde veio), pelo Whisper do Groq (grátis)."""
    palavras = _groq(audio, idioma, log)
    if palavras:
        return _casar(texto, palavras), "Whisper do Groq"
    raise ErroVozLocal("sem transcrição com tempo por palavra (Groq)")


def _groq(audio, idioma, log):
    """Palavras com tempo pelo Whisper do Groq, revezando as chaves gratuitas. None se não deu."""
    from . import groq_local
    from .util import rodar
    leve = audio.with_name(audio.stem + ".tempo.mp3")
    try:
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", audio, "-ac", "1", "-ar", "16000", "-b:a", "32k", leve])
        try:
            chaves = groq_local._chaves()
        except SystemExit:
            return None
        for tentativa in range(min(len(chaves) + 2, 8)):
            chave = chaves[groq_local._escolher_chave(chaves)]
            try:
                with open(leve, "rb") as f:
                    r = httpx.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                   headers={"Authorization": f"Bearer {chave}"},
                                   files={"file": (leve.name, f, "audio/mpeg")},
                                   data={"model": "whisper-large-v3-turbo", "language": idioma or "pt",
                                         "response_format": "verbose_json", "timestamp_granularities[]": "word",
                                         "temperature": "0"}, timeout=180)
            except httpx.HTTPError:
                time.sleep(2)
                continue
            if r.status_code == 200:
                return r.json().get("words") or None
            if r.status_code == 429:
                if tentativa >= len(chaves) - 1:
                    time.sleep(min(30, groq_local._espera(r, tentativa)))
                continue
            if r.status_code in (400, 401, 413):
                return None
            time.sleep(2)
        return None
    finally:
        leve.unlink(missing_ok=True)


def _normal(palavra: str) -> str:
    return re.sub(r"[^\w]", "", palavra.lower())


def _casar(texto: str, ouvidas: list) -> list:
    """Casa as palavras ouvidas com as do roteiro: só as que casam ganham tempo (o resto é interpolado)."""
    ouvidas = [(w.get("word") or w.get("text") or "", float(w.get("start") or 0), float(w.get("end") or 0))
               for w in ouvidas]
    roteiro = [m.group() for m in re.finditer(r"\S+", texto)]
    a = [_normal(p) for p in roteiro]
    b = [_normal(p) for p, _, _ in ouvidas]
    casadas = []
    for bloco in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(bloco.size):
            _, t0, t1 = ouvidas[bloco.b + k]
            casadas.append((roteiro[bloco.a + k], t0, t1))
    return casadas


# ── prévia para o editor ──────────────────────────────────────────────────────────────────────────────────────────

TEXTOS_PREVIA = {
    "pt": "Muito antes de qualquer registro, este lugar já guardava um segredo. E hoje você vai descobrir qual era.",
    "en": "Long before anyone wrote it down, this place was already keeping a secret. Today, you will find out what.",
    "es": "Mucho antes de cualquier registro, este lugar ya guardaba un secreto. Y hoy vas a descubrir cuál era.",
}


def previa(codigo: str, idioma="pt", log=print) -> Path:
    """Um trecho curto na voz pedida, guardado em motores_voz/vozes/previas (gerado uma vez por voz e língua)."""
    idioma = idioma if idioma in TEXTOS_PREVIA else "pt"
    nome = hashlib.sha1(f"{codigo}|{idioma}".encode("utf-8")).hexdigest()[:16]
    destino = PASTA / "vozes" / "previas" / f"{nome}.wav"
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    preparada = preparar({"voz_local": codigo}, log)
    narrar(TEXTOS_PREVIA[idioma], {"idioma": idioma}, destino, preparada, log)
    _desligar_quando_parado()
    return destino


# ── o motor ligado por prévias sai sozinho da placa ───────────────────────────────────────────────────────────────
# A narração desliga o motor no fim. A prévia (o editor e o Radar ouvindo vozes) não tem "fim": sem isso o motor ficava
# na placa de vídeo até a próxima narração, e o render e as animações dividiam os 6 GB com ele.
PARADO_PARA_DESLIGAR = 300  # segundos sem nenhuma fala
_uso = {"ultimo": 0.0, "em_andamento": 0}
_trava_uso = threading.Lock()
_vigia = {"timer": None}


class _usando:
    """Marca o motor como em uso enquanto liga ou grava: o vigia das prévias nunca desliga no meio."""

    def __enter__(self):
        with _trava_uso:
            _uso["em_andamento"] += 1
            _uso["ultimo"] = time.time()

    def __exit__(self, *_):
        with _trava_uso:
            _uso["em_andamento"] -= 1
            _uso["ultimo"] = time.time()


def _desligar_quando_parado() -> None:
    with _trava_uso:
        if _vigia["timer"]:
            _vigia["timer"].cancel()
        _vigia["timer"] = threading.Timer(PARADO_PARA_DESLIGAR, _talvez_desligar)
        _vigia["timer"].daemon = True
        _vigia["timer"].start()


def _talvez_desligar() -> None:
    with _trava_uso:
        _vigia["timer"] = None
        ocupado = _uso["em_andamento"] > 0 or time.time() - _uso["ultimo"] < PARADO_PARA_DESLIGAR - 1
    if ocupado:
        _desligar_quando_parado()  # uma narração começou depois da prévia: ela desliga no fim, ou confere de novo
    else:
        desligar()
