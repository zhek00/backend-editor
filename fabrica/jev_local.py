"""Chamadas ao Jev, o modelo de decisão da TypeSafe, pelo OpenRouter.

Ele não escreve texto: recebe um estado e perguntas tipadas e devolve respostas com probabilidade.
- noul: verdadeiro ou falso, de 0 a 1.
- score: uma nota numa escala que você descreve.
- choice: escolher entre opções.

Por isso ele é muito mais barato que um modelo de linguagem (uns US$ 0,04 por milhão de tokens lidos,
sem cobrar a saída), mas só entende texto. Quem olha as imagens é o modelo de visão, que descreve o
que aparece, e o Jev julga a descrição contra a narração.
"""
import json
import os
import threading
import time
from datetime import datetime

import httpx

from .openrouter_local import _chave

URL = "https://openrouter.ai/api/alpha/decisions"
MODELO_PADRAO = "typesafe/jev-1.13"
_trava = threading.Lock()


def _registrar(projeto, etapa, uso, modelo):
    uso = uso or {}
    linha = {"quando": datetime.now().isoformat(timespec="seconds"), "etapa": etapa, "modelo": modelo,
             "tokens_lidos": uso.get("input_tokens", 0), "tokens_escritos": uso.get("output_tokens", 0),
             "custo_usd": uso.get("cost", 0) or 0}
    with _trava:
        arquivo = projeto.caminho("uso_jev.json")
        historico = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
        historico.append(linha)
        arquivo.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")


def resumo_uso(projeto):
    arquivo = projeto.pasta / "uso_jev.json"
    if not arquivo.exists():
        return None
    historico = json.loads(arquivo.read_text(encoding="utf-8"))
    return {"chamadas": len(historico), "lidos": sum(h["tokens_lidos"] for h in historico),
            "escritos": sum(h["tokens_escritos"] for h in historico),
            "custo": sum(h["custo_usd"] for h in historico)}


def _pelo_mimo(projeto, etapa, estado, perguntas, log, motivo):
    """O servidor do Jev caiu ou está lento: o MiMo responde as mesmas perguntas, no mesmo formato, na hora.

    Parado é pior: com 456 cenas, dormir e repetir a cada 503 do Jev travava a conferência por muito tempo."""
    from . import openrouter_local

    propriedades, instrucoes = {}, []
    for chave, p in perguntas.items():
        tipo = p.get("type", "noul")
        if tipo == "noul":
            propriedades[chave] = {"type": "number"}
            instrucoes.append(f"- {chave}: probabilidade de 0 a 1 de ser verdadeiro. {p.get('instructions', '')} "
                              f"Verdadeiro quando: {(p.get('criteria') or {}).get('true', '')}. "
                              f"Falso quando: {(p.get('criteria') or {}).get('false', '')}.")
        elif tipo == "choice":
            propriedades[chave] = {"type": "string"}
            instrucoes.append(f"- {chave}: escolha uma das opções {p.get('options')}. {p.get('instructions', '')}")
        else:
            propriedades[chave] = {"type": "number"}
            instrucoes.append(f"- {chave}: uma nota. {p.get('instructions', '')} {json.dumps(p, ensure_ascii=False)}")
    esquema = {"type": "object", "properties": propriedades, "required": list(propriedades), "additionalProperties": False}
    resposta = openrouter_local.pelo_mimo(
        projeto, f"{etapa} (no lugar do Jev)", "Você julga com rigor e responde só o JSON pedido.\n" + "\n".join(instrucoes),
        "ESTADO:\n" + json.dumps(estado, ensure_ascii=False, indent=1), esquema, log=log, temperatura=0, motivo=motivo)
    saida = {}
    for chave, p in perguntas.items():
        tipo = p.get("type", "noul")
        valor = resposta.get(chave)
        if tipo == "noul":
            valor = min(1.0, max(0.0, float(valor or 0)))
        saida[chave] = {"type": tipo, tipo: valor}
    return saida


def decidir(projeto, etapa, estado: dict, perguntas: dict, log=print, modelo=None):
    """Devolve as respostas do Jev para esse estado. Uma chamada responde todas as perguntas de uma vez.

    Se o servidor do Jev cair (503, tempo esgotado), a mesma pergunta vai para o MiMo na hora, sem dormir.

    Com jev.julgar_com: principal no config.yaml, ou FABRICA_JULGAR_COM=principal no ambiente (vale só para aquele
    processo, sem mexer no servidor que está no ar), quem julga é o modelo principal, que hoje é gratuito."""
    cfg = projeto.config.get("jev") or {}
    if (os.environ.get("FABRICA_JULGAR_COM") or cfg.get("julgar_com") or "jev").strip().lower() == "principal":
        try:
            return _pelo_mimo(projeto, etapa, estado, perguntas, log, "")
        except (Exception, SystemExit) as e:
            raise RuntimeError(f"O modelo principal não julgou na etapa {etapa} ({e}).") from None
    modelo = modelo or cfg.get("modelo", MODELO_PADRAO)
    corpo = {"model": modelo, "state": estado, "questions": perguntas}
    cabecalho = {"Authorization": f"Bearer {_chave()}"}

    ultimo_erro = ""
    for tentativa in range(cfg.get("tentativas", 2)):
        try:
            r = httpx.post(URL, json=corpo, headers=cabecalho, timeout=cfg.get("tempo_maximo", 60))
        except httpx.HTTPError as e:
            ultimo_erro = f"o servidor do Jev não respondeu ({str(e)[:80] or type(e).__name__})"
            continue
        if r.status_code == 401:
            raise SystemExit("A chave do OpenRouter foi recusada pelo Jev. Confira o arquivo .env.")
        if r.status_code == 402:
            raise SystemExit("Acabou o crédito no OpenRouter. Adicione saldo em openrouter.ai/credits.")
        if r.status_code in (429, 500, 502, 503, 504, 529):
            ultimo_erro = f"o servidor do Jev caiu ({r.status_code})"
            continue
        if r.status_code != 200:
            ultimo_erro = f"o Jev recusou o pedido ({r.status_code} {r.text[:120]})"
            break
        dados = r.json()
        _registrar(projeto, etapa, dados.get("usage"), dados.get("model", modelo))
        respostas = dados.get("answers")
        if not respostas:
            ultimo_erro = "o Jev respondeu sem answers"
            continue
        return respostas
    try:
        return _pelo_mimo(projeto, etapa, estado, perguntas, log, ultimo_erro)
    except (Exception, SystemExit) as e:
        raise RuntimeError(f"Nem o Jev nem o MiMo responderam na etapa {etapa} ({ultimo_erro}; {e}).") from None
