"""Chamadas ao Groq, uma rota gratuita da cadeia de modelos (prefixo "groq:" em openrouter.principais e
midia.modelos_visao). Pedido do usuário em 2026-10-05: o máximo de API gratuita. 11 chaves no .env, cada uma com
1.000 pedidos por dia e 8.000 tokens por minuto por modelo; o qwen/qwen3.8-27b enxerga imagem (a folha de
candidatos em 1,1 s).

Mesmo formato do claude_local.perguntar: recebe instruções, pedido e esquema JSON e devolve
o dicionário já lido. O Groq tem plano gratuito, então o limite de pedidos por minuto é o
que mais atrapalha. Quando ele estoura, a chamada espera o tempo que o próprio Groq manda
esperar e tenta de novo.
"""
import base64
import json
import os
import re
import threading
import time
from datetime import datetime

import httpx

URL = "https://api.groq.com/openai/v1/chat/completions"
MODELO_PADRAO = "openai/gpt-oss-120b"


_trava = threading.Lock()
_proxima = 0
_NUMERO = {}  # chave -> nome dela no .env (GROQ_API_KEY3...), para o registro dizer qual chave foi
_mortas = {}  # chave -> momento em que ela volta. A cota do Groq é uma janela móvel de 24h, não zera à meia-noite


def _chaves():
    """GROQ_API_KEY e as extras GROQ_API_KEY1, GROQ_API_KEY2 e assim por diante. Cada chave tem o próprio limite."""
    # todas as GROQ_API_KEY com número, sem teto (antes parava na 9 e a GROQ_API_KEY10 ficava de fora),
    # em qualquer caixa, em ordem de número e sem repetir a mesma chave colada duas vezes
    achadas = []
    for nome, valor in os.environ.items():
        numero = re.fullmatch(r"GROQ_API_KEY(\d*)", nome.strip().upper())
        if numero and valor.strip():
            achadas.append((int(numero.group(1) or 0), valor.strip(), nome.strip()))
    todas = list(dict.fromkeys(valor for _, valor, _ in sorted(achadas)))
    for _, valor, nome in sorted(achadas, reverse=True):
        _NUMERO[valor] = nome
    if not todas:
        raise SystemExit("Falta a GROQ_API_KEY no arquivo .env. Crie uma em console.groq.com/keys.")
    agora = time.time()
    chaves = [c for c in todas if _mortas.get(c, 0) <= agora]
    if not chaves:
        volta = min(_mortas.values()) - agora
        raise SystemExit(f"A cota de 24 horas de todas as chaves do Groq está cheia. A primeira volta em cerca de "
                         f"{max(1, volta / 60):.0f} minuto(s): rode o mesmo comando depois disso, ele continua de onde parou.")
    return chaves


def _escolher_chave(chaves):
    """Revezamento entre as chaves, para dividir os pedidos igualmente entre elas."""
    global _proxima
    with _trava:
        indice = _proxima % len(chaves)
        _proxima += 1
    return indice


def _espera(resposta, tentativa):
    """Segundos a esperar depois de um 429. Usa o que o Groq pediu, senão espera cada vez mais."""
    pedido = resposta.headers.get("retry-after")
    if pedido:
        try:
            return float(pedido) + 1
        except ValueError:
            pass
    achado = re.search(r"try again in (?:(\d+)m)?(?:([\d.]+)s)?", resposta.text)
    if achado and (achado.group(1) or achado.group(2)):
        return int(achado.group(1) or 0) * 60 + float(achado.group(2) or 0) + 1
    return min(60, 5 * 2 ** tentativa)


def _registrar(projeto, etapa, modelo, uso):
    """Cada chamada fica em uso_groq.json, para dar para ver quanto da cota diária o projeto gastou."""
    uso = uso or {}
    linha = {"quando": datetime.now().isoformat(timespec="seconds"), "etapa": etapa, "modelo": modelo,
             "tokens_lidos": uso.get("prompt_tokens", 0), "tokens_escritos": uso.get("completion_tokens", 0)}
    with _trava:
        arquivo = projeto.caminho("uso_groq.json")
        historico = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
        historico.append(linha)
        arquivo.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")


def resumo_uso(projeto):
    arquivo = projeto.pasta / "uso_groq.json"
    if not arquivo.exists():
        return None
    historico = json.loads(arquivo.read_text(encoding="utf-8"))
    return {"chamadas": len(historico), "lidos": sum(h["tokens_lidos"] for h in historico),
            "escritos": sum(h["tokens_escritos"] for h in historico)}


def _esforco(modelo, raciocinio):
    """O raciocínio do Groq pela mesma tabela da cadeia ("nenhum", "low"...): o Qwen aceita none e default, o GPT-OSS
    low, medium e high."""
    pedido = next((v for prefixo, v in (raciocinio or {}).items()
                   if modelo.startswith(prefixo) or f"groq:{modelo}".startswith(prefixo)), None)
    if "qwen" in modelo:
        return "none" if pedido in (None, "nenhum", "low") else "default"
    if "gpt-oss" in modelo:
        return "low" if pedido in ("nenhum", "low") else (pedido or None)
    return None


def perguntar(projeto, etapa, instrucoes, pedido, esquema, log=print, modelo=None, imagens=(), temperatura=None,
              na_cadeia=False, raciocinio=None):
    """imagens é uma lista de caminhos de JPG enviados junto do pedido, para modelos com visão.

    na_cadeia=True: é uma rota da cadeia de openrouter_local. O que não atender (todas as chaves no limite, fora do
    ar, chave recusada) levanta RotaIndisponivel, e a cadeia passa na hora para o seguinte."""
    cfg = projeto.config.get("groq") or {}
    modelo = modelo or cfg.get("modelo", MODELO_PADRAO)
    if imagens:
        conteudo = [{"type": "text", "text": pedido}] + [
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.standard_b64encode(open(caminho, "rb").read()).decode()}}
            for caminho in imagens]
    else:
        conteudo = pedido
    # o Groq conta o espaço reservado para a resposta dentro do limite de tokens por minuto, então
    # reservar o limite inteiro fazia qualquer pedido ser recusado com 413
    entrada = (len(instrucoes) + len(pedido) + len(json.dumps(esquema))) / 3.3 + len(imagens) * 800
    saida = int(cfg.get("tokens_por_minuto", 8000) - entrada - 200)
    if saida < cfg.get("saida_minima", 700):
        # não sobra espaço para a resposta: quem chamou divide o pedido e tenta de novo
        raise RuntimeError(f"413 pedido grande demais na etapa {etapa}: a entrada consome quase todo o "
                           f"limite de {cfg.get('tokens_por_minuto', 8000)} tokens por minuto do Groq.")
    corpo = {
        "model": modelo,
        "temperature": cfg.get("temperatura", 0.3) if temperatura is None else temperatura,
        "max_completion_tokens": min(saida, cfg.get("max_tokens", 8000)),
        "messages": [
            {"role": "system", "content": instrucoes},
            {"role": "user", "content": conteudo},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "cenas", "strict": "gpt-oss" in modelo, "schema": esquema},
        },
    }
    if na_cadeia:
        esforco = _esforco(modelo, raciocinio)
        if esforco:
            corpo["reasoning_effort"] = esforco
    elif "gpt-oss" in modelo:
        corpo["reasoning_effort"] = cfg.get("raciocinio", "medium")

    def mimo(motivo, minutos=1):
        if na_cadeia:
            from . import openrouter_local
            with _trava:
                openrouter_local._FORA_DO_AR[f"groq:{modelo}"] = time.time() + minutos * 60
            raise openrouter_local.RotaIndisponivel(f"Groq: {motivo}")
        # nunca esperar cota: o Groq que não responde agora passa a vez para o MiMo na hora
        from . import openrouter_local
        return openrouter_local.pelo_mimo(projeto, etapa, instrucoes, pedido, esquema, log=log, imagens=imagens,
                                          temperatura=temperatura, motivo=motivo)

    try:
        chaves = _chaves()
    except SystemExit as e:
        return mimo(f"Groq indisponível ({str(e)[:90]})")
    indice = _escolher_chave(chaves)
    limitadas = set()  # chaves que já pediram para esperar nesta rodada

    ultimo_erro = ""
    inicio = time.time()
    orcamento = cfg.get("espera_maxima", 900)  # o limite por minuto do plano gratuito é normal, então esperar não é falha
    erros = 0
    for tentativa in range(1000):
        if erros >= cfg.get("tentativas", 6) or time.time() - inicio > orcamento:
            break
        cabecalho = {"Authorization": f"Bearer {chaves[indice]}"}
        try:
            r = httpx.post(URL, json=corpo, headers=cabecalho, timeout=cfg.get("tempo_maximo", 180))
        except httpx.HTTPError as e:
            ultimo_erro = str(e)
            erros += 1
            if erros >= 2:
                return mimo(f"o Groq não responde ({ultimo_erro[:80]})")
            time.sleep(3)
            continue

        if r.status_code == 429 and re.search(r"per day|\(TPD\)|\(RPD\)", r.text, re.I):
            # a cota de 24h dessa chave encheu. A janela é móvel, não zera à meia-noite: o Groq diz
            # em quanto tempo volta a caber um pedido deste tamanho, e a chave sai da fila até lá
            espera = _espera(r, 0)
            with _trava:
                _mortas[chaves[indice]] = time.time() + espera
            log(f"  a cota de 24 horas da chave {_NUMERO.get(chaves[indice], indice + 1)} do Groq encheu, ela volta em {espera / 60:.0f} min")
            chaves.pop(indice)
            if not chaves:
                return mimo("a cota de 24 horas de todas as chaves do Groq está cheia",
                            max(1, (min(_mortas.values()) - time.time()) / 60))
            indice = 0
            limitadas.clear()
            continue
        if r.status_code == 429:
            ultimo_erro = "limite de pedidos"
            limitadas.add(indice)
            if len(limitadas) < len(chaves):
                # a outra chave ainda tem folga, então troca na hora em vez de esperar
                indice = next(i for i in (_escolher_chave(chaves) for _ in range(len(chaves) * 2)) if i not in limitadas)
                continue
            return mimo("o Groq pediu para esperar em todas as chaves", min(1, _espera(r, 0) / 60))
        if r.status_code == 401:
            if len(chaves) > 1:
                log(f"  a chave {_NUMERO.get(chaves[indice], indice + 1)} do Groq foi recusada, usando a outra")
                _mortas[chaves[indice]] = float("inf")  # chave inválida, fora até o fim da execução
                chaves.pop(indice)
                indice = 0
                limitadas.clear()
                continue
            return mimo("a GROQ_API_KEY foi recusada")
        if r.status_code >= 500:
            return mimo(f"o Groq está fora do ar (erro {r.status_code})")
        if r.status_code == 400:
            texto = r.text.lower()
            # modelo sem suporte a esquema: pede só JSON e descreve o formato no texto
            if "json_schema" in texto and corpo["response_format"]["type"] == "json_schema":
                corpo["response_format"] = {"type": "json_object"}
                corpo["messages"][0]["content"] += (
                    "\n\nResponda somente com um JSON neste esquema:\n" + json.dumps(esquema, ensure_ascii=False))
                continue
            # o modelo devolveu um JSON que não segue o esquema, uma nova tentativa costuma resolver
            if "json_validate_failed" in texto or "failed to generate" in texto:
                ultimo_erro = "o modelo devolveu um JSON inválido"
                erros += 1
                continue
            raise RuntimeError(f"O Groq recusou o pedido na etapa {etapa}. {r.text[:400]}")
        if r.status_code == 413:
            # a estimativa de tamanho errou para menos: o Groq diz quanto pediu e qual o limite, e a reserva da resposta encolhe
            pedido_real = re.search(r"Requested (\d+)", r.text)
            limite = re.search(r"Limit (\d+)", r.text)
            if pedido_real and limite:
                nova = corpo["max_completion_tokens"] - (int(pedido_real.group(1)) - int(limite.group(1))) - 150
                if nova >= cfg.get("saida_minima", 700):
                    corpo["max_completion_tokens"] = nova
                    continue
            raise RuntimeError(f"413 pedido grande demais na etapa {etapa}: {r.text[:200]}")
        if r.status_code != 200:
            raise RuntimeError(f"O Groq falhou na etapa {etapa}. {r.status_code} {r.text[:300]}")

        _registrar(projeto, etapa, modelo, r.json().get("usage"))
        try:
            conteudo = r.json()["choices"][0]["message"]["content"]
            return json.loads(conteudo)
        except (KeyError, IndexError, json.JSONDecodeError, TypeError):
            ultimo_erro = "resposta fora do formato"
            erros += 1
            continue

    return mimo(f"o Groq não respondeu direito ({ultimo_erro})")
