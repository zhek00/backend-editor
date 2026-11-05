"""Chaves de API do cliente: cifradas no banco, testadas com uma chamada barata e entregues só à máquina dele."""
import os

import httpx
from cryptography.fernet import Fernet, InvalidToken

from . import banco

ARQUIVO_SEGREDO = banco.PASTA / "segredo.key"

# provedor -> o que a tela mostra e o nome da variável que a fábrica lê.
# "pool": aceita várias chaves (a fábrica reveza as do Groq; das outras, usa a primeira).
PROVEDORES = {
    "openrouter": {"nome": "OpenRouter", "obrigatoria": True, "env": "OPENROUTER_API_KEY",
                   "para": "Roteiro, escolha das fotos, conferência das cenas, imagens de IA e a voz grátis da Fish.",
                   "link": "https://openrouter.ai/settings/keys"},
    "groq": {"nome": "Groq", "obrigatoria": True, "env": "GROQ_API_KEY", "pool": True,
             "para": "Modelos gratuitos e o tempo de cada palavra da narração. Mais chaves, mais vídeos por dia.",
             "link": "https://console.groq.com/keys"},
    "pexels": {"nome": "Pexels", "obrigatoria": True, "env": "PEXELS_API_KEY",
               "para": "Fotos e vídeos reais (grátis).", "link": "https://www.pexels.com/api/"},
    "pixabay": {"nome": "Pixabay", "obrigatoria": True, "env": "PIXABAY_API_KEY",
                "para": "Fotos e vídeos reais (grátis).", "link": "https://pixabay.com/api/docs/"},
    "genaipro": {"nome": "GenAI Pro", "obrigatoria": False, "env": "GENAIPRO_API",
                 "para": "Narração realista. Só é usada quando o narrador é a GenAI Pro.",
                 "link": "https://genaipro.io"},
    "gemini": {"nome": "Google Gemini", "obrigatoria": False, "env": "GEMINI_API_KEY",
               "para": "Descreve as imagens para a conferência (o plano grátis do Google serve).",
               "link": "https://aistudio.google.com/apikey"},
    "coverr": {"nome": "Coverr", "obrigatoria": False, "env": "COVERR_API_KEY",
               "para": "Mais um banco de vídeos reais, livres para uso comercial (grátis).",
               "link": "https://coverr.co/developers"},
    "unsplash": {"nome": "Unsplash", "obrigatoria": False, "env": "UNSPLASH_ACCESS_KEY",
                 "para": "Mais um banco de fotos.", "link": "https://unsplash.com/developers"},
    "kie": {"nome": "Kie.ai", "obrigatoria": False, "env": "KIE_API_KEY",
            "para": "Imagens de IA pelo Grok Imagine (opcional).", "link": "https://kie.ai/api-key"},
    "elevenlabs": {"nome": "ElevenLabs", "obrigatoria": False, "env": "ELEVENLABS_API_KEY",
                   "para": "Efeitos sonoros e música (opcional).", "link": "https://elevenlabs.io/app/settings/api-keys"},
}


def _fernet() -> Fernet:
    segredo = os.environ.get("PALHANO_SEGREDO", "").strip()
    if not segredo:
        banco.PASTA.mkdir(parents=True, exist_ok=True)
        if not ARQUIVO_SEGREDO.exists():
            ARQUIVO_SEGREDO.write_bytes(Fernet.generate_key())
        segredo = ARQUIVO_SEGREDO.read_bytes().decode().strip()
    return Fernet(segredo.encode())


def cifrar(valor: str) -> str:
    return _fernet().encrypt(valor.encode()).decode()


def decifrar(cifrada: str) -> str:
    try:
        return _fernet().decrypt(cifrada.encode()).decode()
    except InvalidToken:
        return ""


def final(valor: str) -> str:
    return valor[-4:] if len(valor) > 8 else "••"


def testar(provedor: str, valor: str) -> tuple[str, str]:
    """('testada' | 'recusada' | 'sem_teste', detalhe). Cada teste é de graça."""
    ua = {"User-Agent": "Mozilla/5.0 (robo-palhano)"}
    try:
        if provedor == "openrouter":
            r = httpx.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {valor}"}, timeout=20)
            if r.status_code == 200:
                d = r.json().get("data") or {}
                uso, limite = d.get("usage"), d.get("limit")
                info = f"usado US$ {uso:.2f}" if isinstance(uso, (int, float)) else ""
                if isinstance(limite, (int, float)):
                    info += f" de US$ {limite:.2f}"
                return "testada", info
        elif provedor == "groq":
            r = httpx.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {valor}"}, timeout=20)
        elif provedor == "pexels":
            r = httpx.get("https://api.pexels.com/v1/search", params={"query": "forest", "per_page": 1},
                          headers={"Authorization": valor}, timeout=20)
        elif provedor == "pixabay":
            r = httpx.get("https://pixabay.com/api/", params={"key": valor, "q": "forest", "per_page": 3}, timeout=20)
        elif provedor == "genaipro":
            r = httpx.get("https://genaipro.io/api/v2/me", headers={"Authorization": f"Bearer {valor}", **ua}, timeout=20)
            if r.status_code == 200:
                d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                saldo = d.get("balance") or d.get("credits") or (d.get("data") or {}).get("balance")
                return "testada", f"saldo {saldo}" if saldo is not None else ""
        elif provedor == "gemini":
            r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": valor},
                          timeout=20)
        elif provedor == "coverr":
            # em 2026-10-12 o Coverr respondia igual com a chave certa, a errada ou sem chave: não dá para testar
            return "sem_teste", "o Coverr ainda não confere a chave; ela fica guardada e vai junto em toda busca"
        elif provedor == "unsplash":
            r = httpx.get("https://api.unsplash.com/search/photos", params={"query": "forest", "per_page": 1},
                          headers={"Authorization": f"Client-ID {valor}"}, timeout=20)
        elif provedor == "kie":
            r = httpx.get("https://api.kie.ai/api/v1/chat/credit", headers={"Authorization": f"Bearer {valor}"}, timeout=20)
            if r.status_code == 200 and (r.json() or {}).get("code") not in (None, 200):
                return "recusada", f"a Kie respondeu {r.json().get('msg', '')}"
        elif provedor == "elevenlabs":
            r = httpx.get("https://api.elevenlabs.io/v1/user", headers={"xi-api-key": valor}, timeout=20)
        else:
            return "sem_teste", ""
    except httpx.HTTPError as e:
        return "sem_teste", f"sem resposta do provedor ({type(e).__name__}); tente de novo"
    if r.status_code == 200:
        return "testada", ""
    if r.status_code in (401, 403):
        return "recusada", f"o provedor recusou a chave ({r.status_code})"
    return "sem_teste", f"o provedor respondeu {r.status_code}; tente de novo mais tarde"


def ambiente_do_usuario(usuario_id: int) -> dict:
    """As variáveis que a fábrica lê, com as chaves decifradas. Só vai para a máquina do próprio dono."""
    env: dict = {}
    for prov, info in PROVEDORES.items():
        linhas = banco.todos("SELECT cifrada FROM chaves WHERE usuario_id=? AND provedor=? AND estado!='recusada' "
                             "ORDER BY id", usuario_id, prov)
        valores = [v for v in (decifrar(x["cifrada"]) for x in linhas) if v]
        if not valores:
            continue
        if prov == "groq":
            for i, v in enumerate(valores):
                env[info["env"] + ("" if i == 0 else str(i))] = v
        else:
            env[info["env"]] = valores[0]
    return env


def faltando(usuario_id: int, narrador: str) -> list:
    """Nomes das chaves obrigatórias que o cliente ainda não cadastrou."""
    tem = {x["provedor"] for x in banco.todos(
        "SELECT DISTINCT provedor FROM chaves WHERE usuario_id=? AND estado!='recusada'", usuario_id)}
    precisa = [p for p, i in PROVEDORES.items() if i["obrigatoria"]]
    if narrador == "genaipro":
        precisa.append("genaipro")
    return [PROVEDORES[p]["nome"] for p in precisa if p not in tem]
