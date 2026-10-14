"""Avisos para quem cuida da fábrica, na produção em massa (PLANO-VPS.md): crédito acabou, chave recusada, vídeo com
consumo alto, trabalhador com erro em série. Sem eles, os vídeos ficam esperando e ninguém sabe por quê.

FABRICA_ALERTA_WEBHOOK no .env: o endereço de um webhook (Discord, Slack ou outro que aceite JSON com "content" e
"text"). Sem ele, o aviso só vai para o registro. O mesmo motivo avisa no máximo uma vez a cada 30 minutos: quando o
crédito acaba, dezenas de vídeos esperam juntos, e um aviso basta.
"""
import os
import threading
import time

import httpx

INTERVALO = 30 * 60
_ULTIMO: dict = {}
_TRAVA = threading.Lock()


def avisar(chave: str, texto: str, log=print) -> bool:
    """Manda o aviso, se este motivo não avisou nos últimos 30 minutos. Nunca falha: um aviso perdido não para nada."""
    with _TRAVA:
        if time.time() - _ULTIMO.get(chave, 0) < INTERVALO:
            return False
        _ULTIMO[chave] = time.time()
    log(f"  ALERTA: {texto}")
    url = os.environ.get("FABRICA_ALERTA_WEBHOOK", "").strip()
    if not url:
        return True
    try:
        httpx.post(url, json={"content": f"[fábrica] {texto}"[:1900], "text": f"[fábrica] {texto}"[:1900]}, timeout=15)
    except Exception:  # noqa: BLE001
        pass
    return True


def chave_do_motivo(texto: str) -> str:
    """Agrupa os avisos parecidos (o mesmo provedor sem crédito em vários vídeos vira um aviso só)."""
    texto = (texto or "").lower()
    for marca in ("openrouter", "genaipro", "groq", "gemini", "jev", "fal", "kie", "elevenlabs", "fish", "r2", "postgres"):
        if marca in texto:
            return f"{marca}:{'credito' if 'crédito' in texto or 'saldo' in texto else 'chave' if 'chave' in texto else 'outro'}"
    return texto[:60]
