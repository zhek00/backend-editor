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
_esgotados = {}  # modelo -> até quando a cota dele está esgotada (time.time())


def _esgotado(modelo) -> bool:
    return _esgotados.get(modelo, 0) > time.time()


def _volta_em(texto) -> float:
    """Segundos até a cota voltar, pelo "Please retry in 4h27m37.4s" do Google (ou "retry in 20s"); 0 sem o aviso."""
    achado = re.search(r"retry in ((?:\d+h)?(?:\d+m)?(?:[\d.]+s)?)", str(texto), re.I)
    if not achado or not achado.group(1):
        return 0
    partes = dict((u, float(v)) for v, u in re.findall(r"([\d.]+)([hms])", achado.group(1)))
    return partes.get("h", 0) * 3600 + partes.get("m", 0) * 60 + partes.get("s", 0)


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


def _partes(types, pedido, imagens):
    """O pedido em partes: texto e imagens. O pedido da escolha das fotos já vem montado (texto e imagens em base64
    intercalados, como no OpenRouter); as imagens soltas vão no fim, pelo caminho do arquivo."""
    import base64
    import mimetypes

    partes = []
    if isinstance(pedido, list):
        for parte in pedido:
            if parte.get("type") == "text":
                partes.append(types.Part.from_text(text=parte.get("text", "")))
            elif parte.get("type") == "image_url":
                url = (parte.get("image_url") or {}).get("url", "")
                if url.startswith("data:") and "," in url:
                    cabeca, dados = url.split(",", 1)
                    partes.append(types.Part.from_bytes(data=base64.b64decode(dados),
                                                        mime_type=cabeca[5:].split(";")[0] or "image/jpeg"))
    else:
        partes.append(types.Part.from_text(text=str(pedido)))
    for caminho in imagens or ():
        with open(caminho, "rb") as arquivo:
            partes.append(types.Part.from_bytes(data=arquivo.read(),
                                                mime_type=mimetypes.guess_type(str(caminho))[0] or "image/jpeg"))
    return partes


RESOLUCOES = {"baixa": "MEDIA_RESOLUTION_LOW", "media": "MEDIA_RESOLUTION_MEDIUM", "alta": "MEDIA_RESOLUTION_HIGH"}


def perguntar(projeto, etapa, instrucoes, pedido, esquema, log=print, modelo=None, imagens=(), temperatura=None,
              na_cadeia=False, raciocinio=None, resolucao=None, max_tokens=None):
    """imagens é uma lista de caminhos de imagem enviados junto do pedido.

    na_cadeia=True: é uma rota da cadeia de visão ("gemini:MODELO", openrouter_local.uma_rota). Quem não responde
    levanta RotaIndisponivel e a cadeia passa para o seguinte, em vez de cair no MiMo, que saiu da fábrica.
    resolucao (baixa, media, alta): quantos tokens cada imagem gasta; na baixa, uma miniatura de 640x360 leu 856
    tokens contra 1.692. max_tokens: o teto da resposta no lugar de gemini.max_tokens."""
    from google.genai import errors, types

    cfg = projeto.config.get("gemini") or {}
    modelo = modelo or cfg.get("modelo", MODELO_PADRAO)
    partes = _partes(types, pedido, imagens)
    def config_de(nome):
        # o pensamento conta como token escrito, o mais caro. A família 2.5 não aceita o nível (thinking_level) e
        # desliga pelo orçamento zero; a 3 usa o nível baixo, que basta para escolher cenas e descrever imagens
        pensamento = (types.ThinkingConfig(thinking_budget=0) if nome.startswith("gemini-2")
                      else types.ThinkingConfig(thinking_level=str(raciocinio or cfg.get("raciocinio", "low")).upper()))
        extras = {"media_resolution": RESOLUCOES[resolucao]} if resolucao in RESOLUCOES else {}
        return types.GenerateContentConfig(
            system_instruction=instrucoes,
            temperature=cfg.get("temperatura", 0.3) if temperatura is None else temperatura,
            response_mime_type="application/json",
            response_json_schema=esquema,
            max_output_tokens=max_tokens or cfg.get("max_tokens", 16000),
            thinking_config=pensamento,
            **extras,
        )
    def mimo(motivo):
        # nunca esperar cota: o Gemini que não responde agora passa a vez para o MiMo na hora
        from . import openrouter_local
        if na_cadeia:
            raise openrouter_local.RotaIndisponivel(f"Gemini: {motivo}")
        return openrouter_local.pelo_mimo(projeto, etapa, instrucoes, pedido, esquema, log=log, imagens=imagens,
                                          temperatura=temperatura, motivo=motivo)

    try:
        cliente = _cliente()
    except SystemExit as e:
        return mimo(f"Gemini indisponível ({str(e)[:90]})")

    # se a cota do dia de um modelo acaba, tenta o próximo da lista de reserva em vez de esperar até amanhã
    modelos = [m for m in [modelo] + list(cfg.get("modelos_reserva", ["gemini-3.1-flash-lite"])) if not _esgotado(m)]
    if not modelos:
        return mimo("a cota diária dos modelos Gemini acabou")
    ultimo_erro = ""
    tentativa = 0
    while tentativa < cfg.get("tentativas", 6):
        modelo = modelos[0]
        try:
            resposta = cliente.models.generate_content(model=modelo, contents=partes, config=config_de(modelo))
        except errors.APIError as e:
            codigo = getattr(e, "code", 0)
            if codigo in (401, 403):
                return mimo("a GEMINI_API_KEY foi recusada")
            if codigo == 404:
                if na_cadeia:
                    return mimo(f"o modelo {modelo} não existe para a sua chave")
                raise RuntimeError(f"O modelo {modelo} não existe para a sua chave.")
            volta = _volta_em(e)
            if codigo == 429 and ("PerDay" in str(e) or volta > 120):
                # a cota do dia (500 pedidos no plano grátis) acabou: fica de lado até ela voltar, em vez de cada
                # descrição tentar de novo e perder 1,5 s (pedido do usuário em 2026-10-10, para acelerar)
                log(f"  a cota diária do {modelo} acabou (plano gratuito do Google)")
                _esgotados[modelos.pop(0)] = time.time() + (volta or 3600)
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
