"""Chamadas ao Gemini para a divisão em cenas, os textos na tela e a escolha de material real.

Mesma interface do groq_local.perguntar: recebe instruções, pedido e esquema JSON e devolve o
dicionário já lido. Cada chamada registra os tokens gastos em uso_gemini.json dentro do projeto,
para dar para conferir o consumo. Quando o Google devolve limite de uso, a chamada espera e tenta de novo.
"""
import json
import os
import re
import threading
import time
from datetime import datetime

MODELO_PADRAO = "gemini-3.8-flash"
_trava = threading.Lock()
_esgotados = set()  # modelos cuja cota do dia já acabou nesta execução


def _cliente():
    from google import genai

    chave = os.environ.get("GEMINI_API_KEY", "").strip()
    if not chave:
        raise SystemExit("Falta a GEMINI_API_KEY no arquivo .env. Crie uma em aistudio.google.com/apikey.")
    return genai.Client(api_key=chave)


def _espera(erro, tentativa):
    achado = re.search(r"retry in ([\d.]+)s", str(erro), re.I) or re.search(r"retryDelay['\": ]+([\d.]+)s", str(erro))
    return float(achado.group(1)) + 1 if achado else min(60, 5 * 2 ** tentativa)


def _registrar(projeto, etapa, modelo, uso):
    if uso is None:
        return {}
    linha = {
        "quando": datetime.now().isoformat(timespec="seconds"),
        "etapa": etapa,
        "modelo": modelo,
        "tokens_lidos": getattr(uso, "prompt_token_count", 0) or 0,
        "tokens_escritos": getattr(uso, "candidates_token_count", 0) or 0,
        "tokens_pensamento": getattr(uso, "thoughts_token_count", 0) or 0,
    }
    with _trava:
        arquivo = projeto.caminho("uso_gemini.json")
        historico = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
        historico.append(linha)
        arquivo.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")
    return linha


def resumo_uso(projeto):
    arquivo = projeto.pasta / "uso_gemini.json"
    if not arquivo.exists():
        return None
    historico = json.loads(arquivo.read_text(encoding="utf-8"))
    return {
        "chamadas": len(historico),
        "lidos": sum(h["tokens_lidos"] for h in historico),
        "escritos": sum(h["tokens_escritos"] for h in historico),
        "pensamento": sum(h["tokens_pensamento"] for h in historico),
    }


def perguntar(projeto, etapa, instrucoes, pedido, esquema, log=print, modelo=None, imagens=(), temperatura=None):
    """imagens é uma lista de caminhos de JPG enviados junto do pedido."""
    from google.genai import errors, types

    cfg = projeto.config.get("gemini") or {}
    modelo = modelo or cfg.get("modelo", MODELO_PADRAO)
    partes = [types.Part.from_text(text=pedido)]
    for caminho in imagens:
        with open(caminho, "rb") as arquivo:
            partes.append(types.Part.from_bytes(data=arquivo.read(), mime_type="image/jpeg"))
    config = types.GenerateContentConfig(
        system_instruction=instrucoes,
        temperature=cfg.get("temperatura", 0.3) if temperatura is None else temperatura,
        response_mime_type="application/json",
        response_json_schema=esquema,
        max_output_tokens=cfg.get("max_tokens", 16000),
        # o pensamento conta como token escrito, o mais caro. Nível baixo basta para escolher cenas e buscas
        thinking_config=types.ThinkingConfig(thinking_level=str(cfg.get("raciocinio", "low")).upper()),
    )
    def mimo(motivo):
        # nunca esperar cota: o Gemini que não responde agora passa a vez para o MiMo na hora
        from . import openrouter_local
        return openrouter_local.pelo_mimo(projeto, etapa, instrucoes, pedido, esquema, log=log, imagens=imagens,
                                          temperatura=temperatura, motivo=motivo)

    try:
        cliente = _cliente()
    except SystemExit as e:
        return mimo(f"Gemini indisponível ({str(e)[:90]})")

    # se a cota do dia de um modelo acaba, tenta o próximo da lista de reserva em vez de esperar até amanhã
    modelos = [m for m in [modelo] + list(cfg.get("modelos_reserva", ["gemini-3.1-flash-lite"])) if m not in _esgotados]
    if not modelos:
        return mimo("a cota diária dos modelos Gemini acabou")
    ultimo_erro = ""
    tentativa = 0
    while tentativa < cfg.get("tentativas", 6):
        modelo = modelos[0]
        try:
            resposta = cliente.models.generate_content(model=modelo, contents=partes, config=config)
        except errors.APIError as e:
            codigo = getattr(e, "code", 0)
            if codigo in (401, 403):
                return mimo("a GEMINI_API_KEY foi recusada")
            if codigo == 404:
                raise RuntimeError(f"O modelo {modelo} não existe para a sua chave.")
            if codigo == 429 and "PerDay" in str(e):
                log(f"  a cota diária do {modelo} acabou (plano gratuito do Google)")
                _esgotados.add(modelos.pop(0))
                if not modelos:
                    return mimo("a cota diária de todos os modelos Gemini acabou")
                log(f"  usando o {modelos[0]}")
                continue
            if codigo in (429, 500, 502, 503, 504):
                return mimo(f"o Gemini pediu para esperar (erro {codigo})")
            raise RuntimeError(f"O Gemini recusou o pedido na etapa {etapa}. {str(e)[:400]}")
        except Exception as e:  # queda de rede e afins
            tentativa += 1
            ultimo_erro = f"{type(e).__name__}: {str(e)[:200]}"
            if tentativa >= 2:
                return mimo(f"o Gemini não responde ({ultimo_erro[:80]})")
            time.sleep(3)
            continue

        _registrar(projeto, etapa, modelo, resposta.usage_metadata)
        try:
            return json.loads(resposta.text)
        except (TypeError, json.JSONDecodeError):
            tentativa += 1
            ultimo_erro = "resposta fora do formato"
            continue

    return mimo(f"o Gemini não respondeu direito ({ultimo_erro})")
