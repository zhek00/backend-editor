"""Teste de ouvido das vozes mais baratas que a GenAIPro (pedido do usuário em 2026-11-07).

O mesmo trecho em português, coreano e japonês, tirado do começo de um bloco que a GenAIPro já narrou num vídeo de
verdade, gravado em cada voz candidata, numa página para ouvir lado a lado com a voz de hoje. Nada muda na fábrica.

    uv run python -m fabrica.teste_vozes

Precisa das chaves no .env da fábrica (as que faltarem são puladas e a página diz qual faltou):
- OPENAI_API_KEY: gpt-4o-mini-tts, uns US$ 0,015 por minuto de áudio (voz OPENAI_VOZ, padrão onyx)
- INWORLD_API_KEY: a chave em Basic (base64) do painel da Inworld (modelo INWORLD_MODELO, padrão inworld-tts-2;
  voz INWORLD_VOZ, padrão Dennis)
- SPEECHIFY_API_KEY: Simba multilíngue (voz SPEECHIFY_VOZ, padrão george)

Os preços por milhão de caracteres vêm de comparativos da web que não concordam entre si: são só a ordem de grandeza.
Cada amostra tem uns 350 caracteres; o teste inteiro custa centavos.
"""
import base64
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "teste_vozes"
AMOSTRA = 350        # caracteres de cada trecho

# o bloco já narrado pela GenAIPro de onde sai o trecho de cada língua
FONTES = {
    "português": ("15-animais-pre-historicos-fossilizados-n", "pt-BR"),
    "coreano": ("roteiro-6", "ko-KR"),
    "japonês": ("roteiro-7", "ja-JP"),
}
INSTRUCAO = {"português": "Narrador de documentário em português do Brasil, voz grave, calma e envolvente.",
             "coreano": "다큐멘터리 내레이터처럼, 차분하고 몰입감 있는 한국어로 읽어 주세요.",
             "japonês": "ドキュメンタリーのナレーターのように、落ち着いた日本語で読んでください。"}
PRECO = {"GenAIPro (hoje)": "~US$ 22 / 1M caracteres", "OpenAI gpt-4o-mini-tts": "~US$ 0,015 / min de áudio",
         "Inworld": "~US$ 10 a 25 / 1M caracteres", "Speechify Simba": "~US$ 6,60 / 1M caracteres (preço da própria Speechify)"}


def _env(nome, padrao=""):
    return (os.environ.get(nome) or padrao).strip().strip('"').strip("'")


def _ler_env():
    arquivo = RAIZ / ".env"
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                k, v = linha.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _trecho(texto: str) -> str:
    """O começo do bloco cortado no fim de uma frase, perto de AMOSTRA caracteres."""
    texto = " ".join(texto.split())
    corte = texto[:AMOSTRA + 120]
    fins = [m.end() for m in re.finditer(r"[.!?。！？]", corte) if m.end() >= AMOSTRA * 0.6]
    return corte[:fins[0]] if fins else texto[:AMOSTRA]


def _referencia(projeto: str, trecho: str, texto: str, destino: Path) -> str | None:
    """O começo do bloco que a GenAIPro gravou, cortado na mesma proporção do texto (uma aproximação)."""
    mp3 = RAIZ / "projetos" / projeto / "narracao" / "bloco_000.mp3"
    if not mp3.exists():
        return None
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
                                   capture_output=True, text=True, timeout=30).stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError):
        return None
    segundos = dur * len(trecho) / max(1, len(" ".join(texto.split()))) + 0.6
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-t", f"{segundos:.2f}", "-c:a", "libmp3lame",
                    "-q:a", "3", str(destino)], timeout=60)
    return destino.name if destino.exists() else None


def openai(texto, lingua, codigo):
    chave = _env("OPENAI_API_KEY")
    if not chave:
        raise LookupError("falta OPENAI_API_KEY no .env")
    r = httpx.post("https://api.openai.com/v1/audio/speech", timeout=120, headers={"Authorization": f"Bearer {chave}"},
                   json={"model": _env("OPENAI_MODELO", "gpt-4o-mini-tts"), "voice": _env("OPENAI_VOZ", "onyx"),
                         "input": texto, "instructions": INSTRUCAO[lingua], "response_format": "mp3"})
    r.raise_for_status()
    return r.content


def inworld(texto, lingua, codigo):
    chave = _env("INWORLD_API_KEY")
    if not chave:
        raise LookupError("falta INWORLD_API_KEY no .env")
    r = httpx.post("https://api.inworld.ai/tts/v1/voice", timeout=120, headers={"Authorization": f"Basic {chave}"},
                   json={"text": texto, "voiceId": _env("INWORLD_VOZ", "Dennis"), "modelId": _env("INWORLD_MODELO", "inworld-tts-2"),
                         "audioConfig": {"audioEncoding": "MP3"}})
    r.raise_for_status()
    return base64.b64decode(r.json()["audioContent"])


def speechify(texto, lingua, codigo):
    chave = _env("SPEECHIFY_API_KEY")
    if not chave:
        raise LookupError("falta SPEECHIFY_API_KEY no .env")
    r = httpx.post("https://api.speechify.ai/v1/audio/speech", timeout=120, headers={"Authorization": f"Bearer {chave}"},
                   json={"input": texto, "voice_id": _env("SPEECHIFY_VOZ", "george"), "model": "simba-multilingual",
                         "audio_format": "mp3", "language": codigo})
    r.raise_for_status()
    return base64.b64decode(r.json()["audio_data"])


CANDIDATAS = {"OpenAI gpt-4o-mini-tts": openai, "Inworld": inworld, "Speechify Simba": speechify}


def rodar() -> Path:
    _ler_env()
    pasta = SAIDA / datetime.now().strftime("%Y-%m-%d-%H%M")
    pasta.mkdir(parents=True, exist_ok=True)
    linhas = []
    for lingua, (projeto, codigo) in FONTES.items():
        bloco = json.loads((RAIZ / "projetos" / projeto / "narracao" / "bloco_000.json").read_text(encoding="utf-8"))
        trecho = _trecho(bloco["texto"])
        celulas = [("GenAIPro (hoje)", _referencia(projeto, trecho, bloco["texto"], pasta / f"{codigo}-genaipro.mp3"), "")]
        for nome, gravar in CANDIDATAS.items():
            arquivo = pasta / f"{codigo}-{re.sub(r'[^a-z0-9]+', '-', nome.lower())}.mp3"
            try:
                arquivo.write_bytes(gravar(trecho, lingua, codigo))
                celulas.append((nome, arquivo.name, ""))
                print(f"{lingua}: {nome} ok")
            except LookupError as falta:
                celulas.append((nome, None, str(falta)))
            except httpx.HTTPStatusError as erro:
                celulas.append((nome, None, f"{erro.response.status_code}: {erro.response.text[:200]}"))
            except Exception as erro:  # noqa: BLE001 (uma voz que falha não para as outras)
                celulas.append((nome, None, str(erro)[:200]))
        linhas.append((lingua, trecho, celulas))
    pagina = pasta / "ouvir.html"
    pagina.write_text(_html(linhas), encoding="utf-8")
    return pagina


def _html(linhas) -> str:
    partes = ['<!doctype html><meta charset="utf-8"><title>Teste de vozes</title><style>body{font:15px system-ui;'
              'background:#111;color:#eee;max-width:980px;margin:24px auto;padding:0 16px}h2{margin-top:32px}'
              '.t{opacity:.8;font-size:13px;background:#1c1c1c;padding:10px;border-radius:8px}table{width:100%;'
              'border-collapse:collapse}td{padding:8px;border-bottom:1px solid #2a2a2a;vertical-align:middle}'
              'small{opacity:.6}.erro{color:#f5b301;font-size:12px}audio{width:320px}</style>',
              "<h1>Teste de vozes</h1><p>O mesmo trecho em cada voz. A primeira é a GenAIPro de hoje, cortada do vídeo "
              "que já saiu (o corte é aproximado).</p>"]
    for lingua, trecho, celulas in linhas:
        partes.append(f"<h2>{html.escape(lingua.capitalize())}</h2><div class='t'>{html.escape(trecho)}</div><table>")
        for nome, arquivo, erro in celulas:
            som = f"<audio controls src='{html.escape(arquivo)}'></audio>" if arquivo else f"<span class='erro'>{html.escape(erro or 'não gerou')}</span>"
            partes.append(f"<tr><td><b>{html.escape(nome)}</b><br><small>{html.escape(PRECO.get(nome, ''))}</small></td><td>{som}</td></tr>")
        partes.append("</table>")
    return "".join(partes)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("Página:", rodar())
