"""Chamadas ao OpenRouter, usado para o Jev (typesafe/jev-router), que escolhe o modelo a cada pedido.

Mesma interface do groq_local e do gemini_local. Como o roteador não garante esquema JSON estrito,
o esquema vai descrito no prompt e a resposta é lida como JSON. O preço varia com o modelo que o
roteador escolhe, então cada chamada grava em uso_openrouter.json o custo real que o OpenRouter informa.
"""
import base64
import json
import os
import re
import threading
import time
from datetime import datetime

import httpx

URL = "https://openrouter.ai/api/v1/chat/completions"
MODELO_PADRAO = "typesafe/jev-router"
# o modelo de texto e visão de toda a fábrica: openrouter.modelo_principal no config.yaml
MODELO_PRINCIPAL_PADRAO = "stealth/space-bunny-alpha"
MIMO = MODELO_PRINCIPAL_PADRAO  # nome antigo, mantido para quem ainda importa


def principal(projeto=None) -> str:
    """O modelo que a fábrica usa para tudo que não é o juiz (Jev)."""
    if projeto is not None:
        return (projeto.config.get("openrouter") or {}).get("modelo_principal") or MODELO_PRINCIPAL_PADRAO
    from .config import config_geral
    return (config_geral().get("openrouter") or {}).get("modelo_principal") or MODELO_PRINCIPAL_PADRAO
_trava = threading.Lock()


def pelo_mimo(projeto, etapa, instrucoes, pedido, esquema, log=print, imagens=(), temperatura=None, motivo=""):
    """Reserva imediata do Groq e do Gemini: cota cheia ou pedido para esperar não pode parar a fábrica.

    O MiMo não tem cota diária, enxerga imagens e custa frações de centavo por pedido."""
    log(f"  {motivo}: seguindo pelo modelo principal agora, sem esperar" if motivo else "  seguindo pelo modelo principal")
    return perguntar(projeto, etapa, instrucoes, pedido, esquema, log=log, modelo=principal(projeto), imagens=imagens,
                     temperatura=temperatura)


def _chave():
    # o nome no .env pode estar em maiúsculas ou minúsculas (OpenRouter_key, OPENROUTER_API_KEY...)
    for nome, valor in os.environ.items():
        if nome.lower() in ("openrouter_key", "openrouter_api_key") and valor.strip():
            return valor.strip()
    raise SystemExit("Falta a chave do OpenRouter no arquivo .env (OPENROUTER_API_KEY).")


def _registrar(projeto, etapa, uso, modelo_usado):
    uso = uso or {}
    linha = {"quando": datetime.now().isoformat(timespec="seconds"), "etapa": etapa, "modelo": modelo_usado,
             "tokens_lidos": uso.get("prompt_tokens", 0), "tokens_escritos": uso.get("completion_tokens", 0),
             "custo_usd": uso.get("cost", 0) or 0}
    with _trava:
        arquivo = projeto.caminho("uso_openrouter.json")
        historico = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
        historico.append(linha)
        arquivo.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")


def resumo_uso(projeto):
    arquivo = projeto.pasta / "uso_openrouter.json"
    if not arquivo.exists():
        return None
    historico = json.loads(arquivo.read_text(encoding="utf-8"))
    return {"chamadas": len(historico), "lidos": sum(h["tokens_lidos"] for h in historico),
            "escritos": sum(h["tokens_escritos"] for h in historico),
            "custo": sum(h["custo_usd"] for h in historico)}


def _ler_json(texto):
    texto = (texto or "").strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        achado = re.search(r"\{.*\}", texto, re.S)
        if not achado:
            raise
        return json.loads(achado.group(0))


def parte_de_imagem(caminho):
    """Uma imagem no formato que o OpenRouter espera, para montar um pedido com texto e imagem intercalados."""
    with open(caminho, "rb") as arquivo:
        return {"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.standard_b64encode(arquivo.read()).decode()}}


def perguntar(projeto, etapa, instrucoes, pedido, esquema, log=print, modelo=None, imagens=(), temperatura=None):
    """imagens é uma lista de caminhos de JPG enviados junto do pedido."""
    cfg = projeto.config.get("openrouter") or {}
    modelo = modelo or cfg.get("modelo", MODELO_PADRAO)
    if isinstance(pedido, list):
        conteudo = pedido  # já vem montado, com texto e imagens intercalados
    elif imagens:
        conteudo = [{"type": "text", "text": pedido}] + [
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.standard_b64encode(open(caminho, "rb").read()).decode()}}
            for caminho in imagens]
    else:
        conteudo = pedido
    # o esquema vai no campo próprio do OpenRouter, e não colado no texto: alguns modelos, como o
    # MiMo, devolviam o próprio esquema de volta em vez dos dados quando ele vinha no prompt
    sistema = instrucoes
    if modelo.startswith("stealth/"):
        # esse modelo ignora o response_format e inventa os nomes das chaves ("searches" no lugar de "cenas")
        sistema = (instrucoes + "\n\nResponda SOMENTE com um JSON válido que siga EXATAMENTE este esquema, com estes "
                   "nomes de chave, sem texto fora dele:\n" + json.dumps(esquema, ensure_ascii=False))
    corpo = {
        "model": modelo,
        "max_tokens": cfg.get("max_tokens", 6000),  # o roteador pode escolher um modelo que raciocina, e o raciocínio conta aqui
        "temperature": cfg.get("temperatura", 0.2) if temperatura is None else temperatura,
        "usage": {"include": True},
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": conteudo}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "resposta", "strict": True, "schema": esquema}},
    }
    # o esforço de raciocínio é por modelo: nem todos aceitam desligar o pensamento (o deepseek recusa com 400)
    esforco = next((v for prefixo, v in (cfg.get("raciocinio_por_modelo") or {}).items() if modelo.startswith(prefixo)), None)
    if esforco:
        corpo["reasoning"] = {"enabled": False} if esforco == "nenhum" else {"effort": esforco}
    cabecalho = {"Authorization": f"Bearer {_chave()}"}

    ultimo_erro, erros = "", 0
    inicio, orcamento = time.time(), cfg.get("espera_maxima", 300)
    while erros < cfg.get("tentativas", 5) and time.time() - inicio < orcamento:
        try:
            r = httpx.post(URL, json=corpo, headers=cabecalho, timeout=cfg.get("tempo_maximo", 180))
        except httpx.HTTPError as e:
            ultimo_erro, erros = str(e), erros + 1
            time.sleep(min(30, 3 * 2 ** erros))
            continue
        if r.status_code == 401:
            raise SystemExit("A chave do OpenRouter foi recusada. Confira o arquivo .env.")
        if r.status_code == 402:
            raise SystemExit("Acabou o crédito no OpenRouter. Adicione saldo em openrouter.ai/credits.")
        if r.status_code in (429, 500, 502, 503, 504):
            ultimo_erro, erros = f"erro {r.status_code} do OpenRouter", erros + 1
            log(f"  OpenRouter pediu para esperar ({r.status_code})")
            time.sleep(min(30, 3 * 2 ** erros))
            continue
        if r.status_code == 400 and "reasoning" in corpo and "reasoning" in r.text.lower():
            # o modelo não aceita esse esforço de raciocínio: segue com o padrão dele em vez de falhar o pedido
            del corpo["reasoning"]
            continue
        if r.status_code in (400, 404) and "response_format" in corpo:
            # modelo que não aceita esquema nativo: o esquema volta a ir no texto
            del corpo["response_format"]
            corpo["messages"][0]["content"] = instrucoes + (
                "\n\nResponda somente com um JSON válido neste esquema, sem texto fora dele:\n"
                + json.dumps(esquema, ensure_ascii=False))
            log("  o modelo não aceita esquema nativo, mandando o esquema no texto")
            continue
        if r.status_code != 200:
            raise RuntimeError(f"O OpenRouter falhou na etapa {etapa}. {r.status_code} {r.text[:300]}")
        dados = r.json()
        if dados.get("error"):
            ultimo_erro, erros = str(dados["error"])[:200], erros + 1
            time.sleep(min(30, 3 * 2 ** erros))
            continue
        _registrar(projeto, etapa, dados.get("usage"), dados.get("model"))
        escolha = (dados.get("choices") or [{}])[0]
        if escolha.get("finish_reason") == "length" or not (escolha.get("message") or {}).get("content"):
            # o modelo gastou tudo pensando e não chegou a responder: tenta de novo com o dobro de folga
            if corpo["max_tokens"] >= cfg.get("max_tokens_teto", 16000):
                ultimo_erro, erros = "o modelo gastou o limite de tokens só raciocinando", erros + 1
            else:
                corpo["max_tokens"] = min(corpo["max_tokens"] * 2, cfg.get("max_tokens_teto", 16000))
                log(f"  o modelo estourou o limite pensando, tentando de novo com {corpo['max_tokens']} tokens")
            continue
        try:
            resposta = _ler_json(dados["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            ultimo_erro, erros = "resposta fora do formato", erros + 1
            continue
        faltam = [k for k in (esquema or {}).get("required", []) if not isinstance(resposta, dict) or k not in resposta]
        if faltam:
            # veio JSON, mas com outras chaves: pede de novo, dizendo quais faltaram
            ultimo_erro, erros = f"a resposta não trouxe {', '.join(faltam)}", erros + 1
            corpo["messages"][0]["content"] = sistema + (
                f"\n\nATENÇÃO: a resposta anterior não trouxe as chaves {', '.join(faltam)}. Use exatamente os nomes "
                "de chave do esquema.")
            continue
        return resposta
    raise RuntimeError(f"O OpenRouter não respondeu direito na etapa {etapa} ({ultimo_erro}).")
