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
MODELO_PRINCIPAL_PADRAO = "qwen/qwen3.8-27b:free"
MIMO = MODELO_PRINCIPAL_PADRAO  # nome antigo, mantido para quem ainda importa


URL_AIMLAPI = "https://api.aimlapi.com/v1/chat/completions"


def principais(projeto=None) -> list:
    """Os modelos principais, em ordem (openrouter.principais no config.yaml). Quando um esgota (saldo, limite do
    dia, modelo retirado do ar), a chamada passa na hora para o seguinte. "aimlapi:" na frente vai pela AIMLAPI."""
    if projeto is not None:
        cfg = projeto.config.get("openrouter") or {}
    else:
        from .config import config_geral
        cfg = config_geral().get("openrouter") or {}
    lista = [m for m in (cfg.get("principais") or []) if m]
    return lista or [cfg.get("modelo_principal") or MODELO_PRINCIPAL_PADRAO]


def principal(projeto=None) -> str:
    """O modelo que a fábrica usa para tudo que não é o juiz (Jev): o primeiro da cadeia de principais."""
    return principais(projeto)[0]


class RotaIndisponivel(RuntimeError):
    """O modelo não atende agora (sem saldo, limite do dia, retirado do ar): a cadeia segue para o próximo."""


# rota -> segundo até quando ela fica de lado. Saldo zerado ou limite do dia não voltam em segundos: as próximas
# chamadas vão direto para o modelo seguinte, sem perder tempo batendo no que caiu
_FORA_DO_AR: dict = {}


def _rota(modelo: str):
    """(url, chave, nome do modelo na API, provedor) de uma rota da cadeia."""
    if modelo.startswith("aimlapi:"):
        return URL_AIMLAPI, _chave_aimlapi(), modelo.split(":", 1)[1], "aimlapi"
    return URL, _chave(), modelo, "openrouter"


def _chave_aimlapi():
    for nome, valor in os.environ.items():
        if nome.lower().startswith("aimlapi") and valor.strip():
            return valor.strip().strip('"').strip("'")
    raise RotaIndisponivel("falta a chave da AIMLAPI no .env (aimlapi_api)")
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
    """imagens é uma lista de caminhos de JPG enviados junto do pedido.

    Com um modelo da cadeia de principais, quem não atender passa a vez para o seguinte na hora (nunca esperar)."""
    cfg = projeto.config.get("openrouter") or {}
    modelo = modelo or cfg.get("modelo", MODELO_PADRAO)
    cadeia = principais(projeto)
    rotas = cadeia[cadeia.index(modelo):] if modelo in cadeia else [modelo]
    agora = time.time()
    vivas = [r for r in rotas if _FORA_DO_AR.get(r, 0) <= agora] or rotas[-1:]
    erro = None
    for k, rota in enumerate(vivas):
        ultima = k == len(vivas) - 1
        try:
            return _perguntar_rota(projeto, etapa, instrucoes, pedido, esquema, log, rota, imagens, temperatura,
                                   cadeia=not ultima)
        except RotaIndisponivel as e:
            erro = e
            if not ultima:
                log(f"  {rota} não atende agora ({str(e)[:100]}): seguindo com {vivas[k + 1]}")
        except (RuntimeError, SystemExit) as e:
            erro = e
            if ultima:
                raise
            log(f"  {rota} falhou ({str(e)[:100]}): seguindo com {vivas[k + 1]}")
    raise RuntimeError(f"Nenhum modelo principal atendeu na etapa {etapa}: {erro}")


def _fora_do_ar(rota, minutos, motivo):
    _FORA_DO_AR[rota] = time.time() + minutos * 60
    raise RotaIndisponivel(motivo)


def _perguntar_rota(projeto, etapa, instrucoes, pedido, esquema, log, modelo, imagens, temperatura, cadeia=False,
                    traduzir=True):
    """Uma rota da cadeia. Com cadeia=True (há outra depois), o que não volta logo vira RotaIndisponivel.
    traduzir=False é a própria chamada de tradução dos trechos de outro alfabeto, que não traduz de novo."""
    cfg = projeto.config.get("openrouter") or {}
    # o Space Bunny e o Qwen misturam chinês no meio da resposta: o aviso vai antes, em todo pedido
    instrucoes = instrucoes + REGRA_DO_ALFABETO
    rota = modelo
    url, chave, modelo, provedor = _rota(rota)
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
    if provedor == "aimlapi":
        # a AIMLAPI fala o formato da OpenAI: o raciocínio é reasoning_effort, e os campos do OpenRouter saem
        corpo.pop("usage", None)
        if modelo.startswith("stealth/"):
            corpo.pop("response_format", None)  # o esquema já vai no texto
        raciocinio = corpo.pop("reasoning", None)
        if raciocinio and raciocinio.get("effort"):
            corpo["reasoning_effort"] = raciocinio["effort"]
    cabecalho = {"Authorization": f"Bearer {chave}"}

    ultimo_erro, erros, pediu_sem_quebra = "", 0, False
    inicio, orcamento = time.time(), cfg.get("espera_maxima", 300)
    while erros < cfg.get("tentativas", 5) and time.time() - inicio < orcamento:
        try:
            r = httpx.post(url, json=corpo, headers=cabecalho, timeout=cfg.get("tempo_maximo", 180))
        except httpx.HTTPError as e:
            ultimo_erro, erros = str(e), erros + 1
            if cadeia and erros >= 2:
                _fora_do_ar(rota, 2, f"sem resposta ({ultimo_erro[:80]})")
            time.sleep(min(30, 3 * 2 ** erros))
            continue
        texto_erro = r.text.lower() if r.status_code != 200 else ""
        if cadeia and (r.status_code in (402, 404) or (r.status_code == 403 and ("fund" in texto_erro or "balance" in texto_erro))):
            # sem saldo nesta conta, ou o modelo saiu do ar: as próximas chamadas já vão direto para o seguinte
            _fora_do_ar(rota, 24 * 60 if r.status_code == 404 else 30, f"{r.status_code} {r.text[:120]}")
        if cadeia and r.status_code == 429:
            # limite do dia dos modelos gratuitos não volta em minutos; limite por minuto volta logo
            por_dia = "per-day" in texto_erro or "per day" in texto_erro or "daily" in texto_erro
            _fora_do_ar(rota, 60 if por_dia else 1, f"429 {r.text[:120]}")
        if cadeia and r.status_code in (500, 502, 503, 504) and erros >= 1:
            _fora_do_ar(rota, 2, f"{r.status_code} do servidor")
        if r.status_code == 401:
            if cadeia:
                _fora_do_ar(rota, 60, "chave recusada")
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
        if r.status_code not in (200, 201):
            raise RuntimeError(f"O {'AIMLAPI' if provedor == 'aimlapi' else 'OpenRouter'} falhou na etapa {etapa}. "
                               f"{r.status_code} {r.text[:300]}")
        dados = r.json()
        if dados.get("error"):
            ultimo_erro, erros = str(dados["error"])[:200], erros + 1
            time.sleep(min(30, 3 * 2 ** erros))
            continue
        _registrar(projeto, etapa, dados.get("usage"), ("aimlapi:" if provedor == "aimlapi" else "") + str(dados.get("model") or modelo))
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
        quebrados = _trechos_de_outro_alfabeto(resposta)
        if not traduzir:
            return resposta  # a tradução: o que vier de outro alfabeto é descartado em _traduzir_trechos
        if quebrados and not pediu_sem_quebra:
            # o modelo às vezes mistura pedaços de outros alfabetos no meio do texto ("carvalhočekades",
            # "uma composição清楚的"): pede de novo uma vez, e no fim tira o que sobrar
            pediu_sem_quebra = True
            log(f"  a resposta veio com texto de outro alfabeto ({', '.join(quebrados[:3])}), pedindo de novo")
            corpo["messages"][0]["content"] = sistema + (
                "\n\nATENÇÃO: a resposta anterior misturou caracteres de outros alfabetos (chinês, japonês, coreano, "
                "cirílico) no meio do texto. Escreva tudo só com o alfabeto latino, em português ou em inglês.")
            continue
        if quebrados and traduzir:
            # sobrou outro alfabeto depois de pedir de novo: traduz os trechos em vez de só apagar, senão some a
            # informação ("分布于岩石和灌木之间" é "entre rochas e arbustos", e o Jev só lê o texto)
            resposta = _traduzir_trechos(projeto, etapa, resposta, quebrados, log, rota)
        return _sem_outro_alfabeto(resposta)
    raise RuntimeError(f"O OpenRouter não respondeu direito na etapa {etapa} ({ultimo_erro}).")


REGRA_DO_ALFABETO = (
    "\n\nIDIOMA: escreva todo o texto da resposta em português do Brasil (ou em inglês só onde o pedido mandar "
    "inglês, como nos termos de busca), sempre com o alfabeto latino. Nunca escreva em chinês, japonês, coreano, "
    "cirílico ou outro alfabeto, nem no meio de uma palavra. Não comente o seu raciocínio na resposta.")


def _traduzir_trechos(projeto, etapa, resposta, quebrados, log, rota):
    """Pede ao modelo a tradução de cada trecho de outro alfabeto, no idioma do texto em volta, e troca na resposta.
    Comentário do modelo sobre ele mesmo ("não posso mostrar meu raciocínio") volta vazio. Se falhar, segue
    sem traduzir (o que sobrar é apagado depois)."""
    trechos, vistos = [], set()
    for texto in _textos(resposta):
        for m in _OUTRO_ALFABETO.finditer(texto):
            if m.group() not in vistos and len(trechos) < 40:
                vistos.add(m.group())
                trechos.append({"trecho": m.group(), "texto_em_volta": texto[max(0, m.start() - 80):m.end() + 80]})
    if not trechos:
        return resposta
    instrucoes = (
        "Você traduz trechos que um modelo escreveu em outro alfabeto (chinês, japonês, coreano, cirílico) no meio "
        "de um texto em português ou em inglês. Para cada trecho, devolva a tradução no MESMO idioma do texto em "
        "volta, curta, para encaixar no lugar do trecho. Se o trecho não faz parte do conteúdo (o modelo comentando "
        "o próprio raciocínio, uma recusa, lixo), devolva a tradução vazia. Devolva só as traduções, uma por "
        "trecho, na mesma ordem dos trechos (sem repetir o trecho original).")
    esquema = {"type": "object", "additionalProperties": False, "required": ["traducoes"], "properties": {
        "traducoes": {"type": "array", "items": {"type": "string"}}}}
    try:
        volta = _perguntar_rota(projeto, f"{etapa} (tradução)", instrucoes, json.dumps(trechos, ensure_ascii=False),
                                esquema, log, rota, (), 0, traduzir=False)
    except (RuntimeError, SystemExit, RotaIndisponivel) as e:
        log(f"  não deu para traduzir os trechos de outro alfabeto ({str(e)[:80]}), apagando")
        return resposta
    lista = volta.get("traducoes") if isinstance(volta, dict) else None
    if not isinstance(lista, list) or len(lista) != len(trechos):
        log("  a tradução dos trechos de outro alfabeto veio incompleta, apagando")
        return resposta
    traducoes = {t["trecho"]: (v if isinstance(v, str) else "").strip() for t, v in zip(trechos, lista)}
    traducoes = {k: v for k, v in traducoes.items() if not _OUTRO_ALFABETO.search(v)}
    if traducoes:
        log(f"  {len(traducoes)} trecho(s) de outro alfabeto traduzido(s) "
            f"({', '.join(f'{k} = {v or "(vazio)"}' for k, v in list(traducoes.items())[:2])})")

    def trocar(valor):
        if isinstance(valor, str):
            mudou = False
            for trecho in sorted(traducoes, key=len, reverse=True):
                if trecho in valor:
                    valor, mudou = valor.replace(trecho, f" {traducoes[trecho]} "), True
            if mudou:
                valor = re.sub(r"\s+([,.;:!?)])", r"\1", re.sub(r"[ \t]{2,}", " ", valor)).strip()
            return valor
        if isinstance(valor, dict):
            return {k: trocar(v) for k, v in valor.items()}
        if isinstance(valor, list):
            return [trocar(v) for v in valor]
        return valor
    return trocar(resposta)


# chinês, japonês, coreano, cirílico, árabe, hebraico, tailandês e devanágari: nada disso cabe num roteiro em
# português, e quando aparece é ruído do modelo no meio de uma palavra
_OUTRO_ALFABETO = re.compile(r"[Ѐ-ӿ֐-׿؀-ۿऀ-ॿ฀-๿ᄀ-ᇿ"
                             r"぀-ヿ㐀-䶿一-鿿가-힯＀-￯]+")


def _textos(valor):
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for v in valor.values():
            yield from _textos(v)
    elif isinstance(valor, list):
        for v in valor:
            yield from _textos(v)


def _trechos_de_outro_alfabeto(resposta) -> list:
    return [m.group() for texto in _textos(resposta) for m in _OUTRO_ALFABETO.finditer(texto)]


def _sem_outro_alfabeto(valor):
    """Tira os pedaços de outro alfabeto que sobraram, sem mexer no resto da resposta."""
    if isinstance(valor, str):
        return re.sub(r"[ \t]{2,}", " ", _OUTRO_ALFABETO.sub(" ", valor)).strip() if _OUTRO_ALFABETO.search(valor) else valor
    if isinstance(valor, dict):
        return {k: _sem_outro_alfabeto(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_sem_outro_alfabeto(v) for v in valor]
    return valor
