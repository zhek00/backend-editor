"""Servidor de voz da fábrica: roda os motores open source do VoiceStudio e do voicebox sem os apps.

Pedido do usuário em 2026-10-28: "não quero instalar, quero ter todas as vozes dos dois github disponíveis na nossa
fábrica". Os apps são só a casca: as vozes vêm de motores abertos, que rodam aqui direto na placa de vídeo.

- omnivoice (k2-fsa/OmniVoice, Apache-2.0): o motor do VoiceStudio. Voz desenhada por atributos ("male, middle-aged,
  low pitch") ou clonada de uma gravação curta com o texto dela.
- kokoro (hexgrad/Kokoro-82M, Apache-2.0): as 54 vozes prontas do voicebox (3 em português).
- qwen e qwen_design (Qwen3-TTS, Apache-2.0): as 9 vozes prontas do voicebox (CustomVoice) e a voz por descrição em
  texto livre (VoiceDesign).

Cada ambiente (motores_voz/omnivoice e motores_voz/qwen, que pedem versões diferentes do transformers) roda uma cópia
deste arquivo numa porta; fabrica/voz_local.py liga o servidor certo quando precisa e conversa por HTTP local:
GET /saude e POST /falar {motor, texto, idioma, voz, velocidade, saida}. O áudio é gravado em `saida` (wav).
Um pedido por vez (a placa é uma só); o modelo fica carregado entre os blocos e sai quando outro motor entra.
"""
import argparse
import gc
import json
import os
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import soundfile as sf

IDIOMAS_QWEN = {"pt": "Portuguese", "en": "English", "es": "Spanish", "fr": "French", "de": "German",
                "it": "Italian", "ru": "Russian", "ja": "Japanese", "ko": "Korean", "zh": "Chinese"}
KOKORO_LINGUA = {"en": "a", "en-gb": "b", "es": "e", "fr": "f", "hi": "h", "it": "i", "pt": "p", "ja": "j",
                 "zh": "z"}

_trava = threading.Lock()
_carregado = {"motor": None, "modelo": None, "extra": {}}


def _dispositivo():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def _descarregar():
    if _carregado["modelo"] is None:
        return
    _carregado.update(motor=None, modelo=None, extra={})
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _tipo_qwen(dev):
    """bfloat16 só na placa que faz ele direto. A RTX 2060 (Turing) só simula: uma frase de 5 s levava 32 s."""
    import torch
    escolha = os.environ.get("QWEN_TIPO", "")
    if escolha in ("float16", "bfloat16", "float32"):
        return getattr(torch, escolha)
    if dev != "cuda":
        return torch.float32
    return torch.bfloat16 if torch.cuda.is_bf16_supported(including_emulation=False) else torch.float16


def _modelo(motor):
    """O modelo do motor, carregado uma vez; outro motor carregado antes sai da placa."""
    if _carregado["motor"] == motor:
        return _carregado["modelo"]
    _descarregar()
    import torch
    dev = _dispositivo()
    if motor == "omnivoice":
        from omnivoice import OmniVoice
        modelo = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=dev,
                                           dtype=torch.float16 if dev == "cuda" else torch.float32)
    elif motor == "kokoro":
        from kokoro import KModel
        modelo = KModel(repo_id="hexgrad/Kokoro-82M").to(dev).eval()
    elif motor in ("qwen", "qwen_design"):
        from qwen_tts import Qwen3TTSModel
        repo = os.environ.get("QWEN_CUSTOM_REPO", "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice") if motor == "qwen" \
            else os.environ.get("QWEN_DESIGN_REPO", "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign")
        modelo = Qwen3TTSModel.from_pretrained(repo, device_map=dev, torch_dtype=_tipo_qwen(dev))
    else:
        raise ValueError(f"motor desconhecido: {motor}")
    _carregado.update(motor=motor, modelo=modelo, extra={})
    return modelo


def _numpy(audio):
    if hasattr(audio, "detach"):
        audio = audio.detach().float().cpu().numpy()
    return np.asarray(audio, dtype=np.float32).squeeze()


def _omnivoice(texto, idioma, voz):
    modelo = _modelo("omnivoice")
    args = {"text": texto, "language": idioma or "pt", "num_step": int(voz.get("passos") or 32)}
    if voz.get("referencia"):
        # voz clonada: o prompt da gravação é feito uma vez e guardado enquanto o modelo está carregado
        chave = (voz["referencia"], voz.get("texto_referencia") or "")
        prompts = _carregado["extra"].setdefault("prompts", {})
        if chave not in prompts:
            prompts[chave] = modelo.create_voice_clone_prompt(ref_audio=voz["referencia"],
                                                              ref_text=voz.get("texto_referencia") or None)
        args["voice_clone_prompt"] = prompts[chave]
    elif voz.get("atributos"):
        args["instruct"] = voz["atributos"]
    audios = modelo.generate(**args)
    return _numpy(audios[0]), int(getattr(modelo, "sampling_rate", 24000))


def _kokoro(texto, idioma, voz, velocidade):
    import torch
    from kokoro import KPipeline
    modelo = _modelo("kokoro")
    codigo = voz.get("codigo") or "pm_alex"
    lingua = KOKORO_LINGUA.get(idioma, "") or {"p": "p", "e": "e", "f": "f", "h": "h", "i": "i", "j": "j",
                                                "z": "z", "b": "b"}.get(codigo[0], "a")
    pipes = _carregado["extra"].setdefault("pipes", {})
    if lingua not in pipes:
        pipes[lingua] = KPipeline(lang_code=lingua, repo_id="hexgrad/Kokoro-82M", model=modelo)
    pedacos = []
    with torch.inference_mode():
        for r in pipes[lingua](texto, voice=codigo, speed=velocidade):
            if r.audio is not None:
                pedacos.append(_numpy(r.audio))
    if not pedacos:
        raise RuntimeError("o Kokoro não gerou áudio")
    return np.concatenate(pedacos), 24000


def _qwen(motor, texto, idioma, voz):
    import torch
    modelo = _modelo(motor)
    lingua = IDIOMAS_QWEN.get(idioma, "Auto")
    with torch.inference_mode():
        if motor == "qwen":
            args = {"text": texto, "language": lingua, "speaker": voz.get("codigo") or "Ryan"}
            if voz.get("instrucao"):
                args["instruct"] = voz["instrucao"]
            wavs, taxa = modelo.generate_custom_voice(**args)
        else:
            wavs, taxa = modelo.generate_voice_design(text=texto, language=lingua,
                                                      instruct=voz.get("descricao") or "")
    return _numpy(wavs[0]), int(taxa)


def falar(pedido):
    motor = pedido["motor"]
    texto = pedido["texto"]
    idioma = (pedido.get("idioma") or "pt").lower()
    voz = pedido.get("voz") or {}
    velocidade = float(pedido.get("velocidade") or 1.0)
    if pedido.get("semente") is not None:
        import torch
        torch.manual_seed(int(pedido["semente"]))
    if motor == "omnivoice":
        audio, taxa = _omnivoice(texto, idioma, voz)
    elif motor == "kokoro":
        audio, taxa = _kokoro(texto, idioma, voz, velocidade)
        velocidade = 1.0  # o Kokoro já fala na velocidade pedida
    elif motor in ("qwen", "qwen_design"):
        audio, taxa = _qwen(motor, texto, idioma, voz)
    else:
        raise ValueError(f"motor desconhecido: {motor}")
    pico = float(np.max(np.abs(audio))) if audio.size else 0.0
    if pico > 0.99:
        audio = audio / pico * 0.95
    sf.write(pedido["saida"], audio, taxa, subtype="PCM_16")
    return {"ok": True, "segundos": round(len(audio) / taxa, 3), "taxa": taxa, "velocidade_aplicada": velocidade == 1.0}


class Pedidos(BaseHTTPRequestHandler):
    motores = []

    def _responder(self, codigo, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path.startswith("/saude"):
            # sem importar o torch aqui: a primeira importação leva segundos e a fábrica pergunta com 2 s de espera
            self._responder(200, {"ok": True, "motores": self.motores, "carregado": _carregado["motor"],
                                  "pid": os.getpid()})
        else:
            self._responder(404, {"erro": "rota desconhecida"})

    def do_POST(self):
        if self.path.startswith("/desligar"):
            # a fábrica pede para sair: no Windows o python do .venv abre um segundo processo, e matar pelo número
            # guardado deixava esse segundo vivo, segurando a placa de vídeo
            self._responder(200, {"ok": True})
            threading.Timer(0.3, lambda: os._exit(0)).start()
            return
        if not self.path.startswith("/falar"):
            self._responder(404, {"erro": "rota desconhecida"})
            return
        try:
            pedido = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if pedido.get("motor") not in self.motores:
                self._responder(400, {"erro": f"este servidor não tem o motor {pedido.get('motor')}"})
                return
            inicio = time.time()
            with _trava:
                resposta = falar(pedido)
            resposta["tempo"] = round(time.time() - inicio, 2)
            self._responder(200, resposta)
        except Exception as erro:
            traceback.print_exc()
            self._responder(500, {"erro": f"{type(erro).__name__}: {str(erro)[:400]}"})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--porta", type=int, required=True)
    p.add_argument("--motores", required=True, help="lista separada por vírgula")
    a = p.parse_args()
    Pedidos.motores = [m.strip() for m in a.motores.split(",") if m.strip()]
    servidor = ThreadingHTTPServer(("127.0.0.1", a.porta), Pedidos)
    print(f"servidor de voz pronto na porta {a.porta}: {', '.join(Pedidos.motores)}", flush=True)
    servidor.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
