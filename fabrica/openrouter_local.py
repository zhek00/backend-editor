"""Chamadas ao OpenRouter, usado para o Jev (typesafe/jev-router), que escolhe o modelo a cada pedido.

Mesma interface do groq_local e do gemini_local. Como o roteador não garante esquema JSON estrito,
o esquema vai descrito no prompt e a resposta é lida como JSON. O preço varia com o modelo que o
roteador escolhe, então cada chamada grava em uso_openrouter.json o custo real que o OpenRouter informa.
"""
import base64
import json
import os
import random
import re
import threading
import time
from datetime import datetime

import httpx

URL = "https://openrouter.ai/api/v1/chat/completions"
MODELO_PADRAO = "typesafe/jev-router"
# o modelo de texto e visão de toda a fábrica: openrouter.modelo_principal no config.yaml
MODELO_PRINCIPAL_PADRAO = "google/gemma-4-31b-it:free"
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


# O nome da fábrica em toda chamada ao OpenRouter. Pedido do usuário em 2026-10-15: o painel mostrava todo o uso como
# "App: Unknown", e US$ 12 de uma semana não estavam em nenhum registro da fábrica (que registra 100% do que faz,
# conferido hora a hora): com o nome, o que aparecer como Unknown não é a fábrica.
APP = {"HTTP-Referer": "https://tiplabs.fabrica", "X-Title": "Fabrica TipLabs"}


def cabecalhos(chave=None) -> dict:
    return {"Authorization": f"Bearer {chave or _chave()}", **APP}


def sessao(projeto) -> str:
    """O session_id do OpenRouter: o nome do projeto. Na aba Sessions do painel, o custo de cada vídeo."""
    nome = getattr(projeto, "nome", None) or str(projeto or "fora-de-projeto")
    return re.sub(r"[^A-Za-z0-9_.-]", "-", nome)[:120]


def credito_reservado(r) -> bool:
    """402 que não é falta de saldo: o OpenRouter reserva o custo máximo de cada pedido em andamento e recusa o que
    passaria do saldo (in_flight_budget_exhausted). Medido em 2026-10-29 com US$ 7 de saldo: de 8 imagens pedidas
    juntas, 2 voltaram 402 e as outras saíram. Esperar os pedidos em andamento terminarem resolve; a fábrica tratava
    como "acabou o crédito" e largava todas as imagens de IA do vídeo."""
    return r.status_code == 402 and ("in_flight" in r.text or "in-flight" in r.text)


def postar_com_sessao(post, url, corpo, projeto, **kw):
    """POST com o session_id do projeto no corpo (Jev e imagens também aparecem na aba Sessions). Se a interface
    recusar o campo (400 ou 422 citando session), manda de novo sem ele: a sessão nunca trava a produção.
    O 402 de crédito reservado (credito_reservado) espera os outros pedidos e tenta de novo, por até 3 minutos."""
    enviado = {**corpo, "session_id": sessao(projeto)}
    r = post(url, json=enviado, **kw)
    if r.status_code in (400, 422) and "session" in r.text.lower():
        enviado = corpo
        r = post(url, json=enviado, **kw)
    limite = time.time() + 180
    while credito_reservado(r) and time.time() < limite:
        time.sleep(random.uniform(3, 10))  # sorteado: as 6 imagens juntas não voltam todas no mesmo segundo
        r = post(url, json=enviado, **kw)
    return r


def _registrar(projeto, etapa, uso, modelo_usado, segundos=None):
    uso = uso or {}
    linha = {"quando": datetime.now().isoformat(timespec="seconds"), "etapa": etapa, "modelo": modelo_usado,
             "tokens_lidos": uso.get("prompt_tokens", 0), "tokens_escritos": uso.get("completion_tokens", 0),
             "custo_usd": uso.get("cost", 0) or 0}
    if segundos is not None:
        linha["segundos"] = round(segundos, 1)  # o que a fábrica esperou, com as novas tentativas (tempos.py)
    # projeto apagado no meio da chamada: não recria a pasta só com este arquivo (o editor não a mostra e ela atrapalha
    # restaurar da lixeira); o registro central abaixo guarda o consumo
    if (projeto.pasta / "projeto.json").exists():
        with _trava:
            arquivo = projeto.caminho("uso_openrouter.json")
            historico = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
            historico.append(linha)
            arquivo.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")
    if not str(modelo_usado).startswith("aimlapi:"):
        # o registro central (consumo.py): fica mesmo depois de o projeto ser apagado ou entregue
        from . import consumo
        consumo.registrar(projeto, "texto", etapa, modelo_usado, linha["tokens_lidos"], linha["tokens_escritos"],
                          linha["custo_usd"])


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


def visao(projeto) -> list:
    """Quem olha as imagens (escolha das fotos, descrição para o Jev, revisão do vídeo pronto): midia.modelos_visao,
    os gratuitos que enxergam imagem primeiro e o pago por último; sem a lista, a cadeia de principais.

    Pedido do usuário em 2026-10-05: no nunca-deve-ter-dentro-de-casa-parte-2 (30 min, 457 cenas) a escolha das
    fotos caiu toda no Qwen Flash pago, porque o Gemma gratuito estava em 429, e custou US$ 2,44: 1.351 chamadas,
    2.500 tokens de raciocínio em cada. A análise da mídia tem que ser gratuita; o pago é só a reserva, sem pensar."""
    lista = [m for m in ((projeto.config.get("midia") or {}).get("modelos_visao") or []) if m]
    return lista or principais(projeto)


class _Visao:
    """Mesma cara de openrouter_local (perguntar), pela cadeia de visao() e com midia.raciocinio_visao por cima do
    raciocinio_por_modelo: o Dots e o Qwen sem raciocínio escolhem as fotos em 25 a 30 s, em vez de 99 s e 2.500
    tokens pagos."""

    @staticmethod
    def perguntar(projeto, etapa, instrucoes, pedido, esquema, log=print, modelo=None, imagens=(), temperatura=None,
                  so_gratuitos=False):
        """so_gratuitos=True: só as rotas gratuitas, sem o pago de reserva (a crítica do Motion IA e as thumbnails,
        que são custo zero), pela lista midia.visao_gratuitos: os gratuitos lentos (Dots, Gemma, Nemotron,
        openrouter/free) saíram de modelos_visao em 2026-10-10 para a escolha ir do Groq direto ao pago rápido. Sem
        nenhuma, levanta RuntimeError."""
        cfg_midia = projeto.config.get("midia") or {}
        lista = visao(projeto)
        if so_gratuitos:
            lista = [r for r in (cfg_midia.get("visao_gratuitos") or lista)
                     if gratuita(r) and (not imagens or ve_imagem(projeto, r))]
            if not lista:
                raise RuntimeError("nenhum modelo de visão gratuito em midia.visao_gratuitos")
        cfg = projeto.config.get("openrouter") or {}
        raciocinio = {**(cfg.get("raciocinio_por_modelo") or {}), **(cfg_midia.get("raciocinio_visao") or {})}
        return perguntar(projeto, etapa, instrucoes, pedido, esquema, log=log, modelo=lista[0], imagens=imagens,
                         temperatura=temperatura, cadeia_de=lista, raciocinio=raciocinio,
                         espera=cfg_midia.get("espera_pelo_gratis"))


VISAO = _Visao()


def gratuita(rota) -> bool:
    """A rota não cobra: os :free e o roteador gratuito do OpenRouter, os stealth e o Groq."""
    return rota.endswith(":free") or rota == "openrouter/free" or rota.startswith(("groq:", "stealth/"))


def _espera_por_melhor(projeto, rotas, rota, limite_gratis=None):
    """(segundos, rota) até uma rota MELHOR que esta voltar, se ela está fora só por pouco (o limite do minuto);
    (None, None) se não há o que esperar, ou se a volta demora mais do que vale a pena.

    Melhor é a que vem antes na cadeia: os gratuitos na frente e, entre os pagos, a ordem da lista, do mais rápido ao
    de reserva. Esperar pelo gratuito é para não pagar (openrouter.espera_pelo_gratis, 60 s; ou o limite que a cadeia
    de visão passa em limite_gratis, midia.espera_pelo_gratis). Esperar pela paga rápida é para não cair na de
    reserva, muito mais lenta (openrouter.espera_pela_rapida, 30 s): medido nos 26 vídeos de outubro, na escolha das
    fotos e nas descrições, o Qwen 3.7 Flash de reserva levou 22,9 s por chamada contra 2,1 s do Gemini 2.5
    Flash-Lite. Eram 15% das chamadas e 66% de todo o tempo de modelo; no 25-animais-estranhos-e-raros-da-china,
    487 escolhas no Qwen levaram 9.587 s, que o Gemini faria em uns 1.000."""
    cfg = projeto.config.get("openrouter") or {}
    if limite_gratis is None:
        limite_gratis = cfg.get("espera_pelo_gratis", 60)
    limite_rapida = cfg.get("espera_pela_rapida", 30)
    agora = time.time()
    candidatas = []
    for melhor in (rotas[:rotas.index(rota)] if rota in rotas else []):
        volta = _FORA_DO_AR.get(melhor, 0) - agora
        if volta <= 0:
            continue  # essa já voltou: a volta do laço tenta ela antes desta
        if volta <= float(limite_gratis if gratuita(melhor) else limite_rapida):
            candidatas.append((volta, melhor))
    if not candidatas:
        return None, None
    volta, melhor = min(candidatas)
    # um pingo de sorteio na espera: com 6 a 8 cenas escolhendo ao mesmo tempo, todas voltavam no mesmo instante,
    # estouravam o limite do minuto de novo na hora e a escolha inteira caía na rota de reserva por minutos
    return max(volta, 0) + 0.5 + random.uniform(0, 2.5), melhor


def perguntar(projeto, etapa, instrucoes, pedido, esquema, log=print, modelo=None, imagens=(), temperatura=None,
              cadeia_de=None, raciocinio=None, _esperas=0, espera=None):
    """imagens é uma lista de caminhos de JPG enviados junto do pedido.

    Com um modelo da cadeia de principais (ou de cadeia_de), quem não atender passa a vez para o seguinte na hora
    (nunca esperar). raciocinio: a tabela de esforço por modelo no lugar de openrouter.raciocinio_por_modelo."""
    from . import pago

    cfg = projeto.config.get("openrouter") or {}
    modelo = modelo or cfg.get("modelo", MODELO_PADRAO)
    cadeia = cadeia_de or principais(projeto)
    rotas = cadeia[cadeia.index(modelo):] if modelo in cadeia else [modelo]
    if imagens:
        # pedido com imagem não vai para quem só lê texto (o GPT-OSS do Groq, o Nemotron Super)
        rotas = [r for r in rotas if ve_imagem(projeto, r)] or rotas
    # todos os gratuitos antes de qualquer pago, na ordem da lista: na cadeia do agente o DeepSeek pago vinha antes
    # do Groq e dos gratuitos do OpenRouter
    gratis = [r for r in rotas if gratuita(r)]
    rotas = gratis + [r for r in rotas if not gratuita(r)]
    # o que a chamada passou, para tempos.anotar_chamada: cada rota tentada, as puladas por estarem fora do ar e as
    # esperas paradas (pela rota melhor que esta e pela confirmação do pago)
    comeco, tentadas, puladas, esperas, ok = time.time(), [], set(), {}, False
    try:
        while True:
            agora = time.time()
            vivas = [r for r in rotas if _FORA_DO_AR.get(r, 0) <= agora] or rotas[-1:]
            puladas.update(r for r in rotas if r not in vivas)
            erro, de_novo = None, False
            for k, rota in enumerate(vivas):
                ultima = k == len(vivas) - 1
                if _esperas < 3 and not gratuita(rota) and rota != rotas[0]:
                    # antes de usar uma rota PAGA que não é a primeira escolha: se uma melhor está fora só pelo limite
                    # do minuto, espera uns segundos por ela. Vale para não pagar (no nunca-deve-ter-dentro-de-casa-
                    # parte-2 um pico da conferência, com o Groq e os gratuitos do OpenRouter no limite do minuto ao
                    # mesmo tempo, mandou 27 descrições para o Qwen pago em 1 minuto) e, desde 2026-10-25, para não
                    # cair na rota paga de RESERVA, 11x mais lenta que a paga rápida: era disso que vinham os 66% do
                    # tempo de modelo da escolha das fotos e das descrições (_espera_por_melhor). Um gratuito
                    # disponível nunca espera: ele entra na hora, porque trocar um gratuito por outro só custaria tempo
                    segundos, melhor = _espera_por_melhor(projeto, rotas, rota, espera)
                    if segundos is not None:
                        log(f"  o {melhor} está no limite do minuto: esperando {segundos:.0f} s em vez de usar o {rota}")
                        time.sleep(segundos)
                        chave = "pelo gratuito" if gratuita(melhor) else "pela paga rápida"
                        esperas[chave] = round(esperas.get(chave, 0) + segundos, 2)
                        _esperas += 1
                        de_novo = True
                        break
                if not gratuita(rota) and gratis:
                    # todos os gratuitos esgotaram: o pago só com a confirmação da pessoa (pago.py)
                    fora = {r: _FORA_DO_AR[r] for r in gratis if _FORA_DO_AR.get(r, 0) > time.time()}
                    t = time.time()
                    liberado = pago.autorizar(projeto, rota, etapa, fora, log)
                    if time.time() - t >= 1:
                        esperas["pela confirmação do pago"] = round(
                            esperas.get("pela confirmação do pago", 0) + time.time() - t, 2)
                    if not liberado:
                        de_novo = True
                        break
                t = time.time()
                try:
                    resposta = uma_rota(projeto, etapa, instrucoes, pedido, esquema, log, rota, imagens, temperatura,
                                        cadeia=not ultima, raciocinio=raciocinio)
                    tentadas.append({"rota": rota, "segundos": round(time.time() - t, 2), "resultado": "ok"})
                    if gratuita(rota):
                        pago.gratis_atendeu(projeto)
                    ok = True
                    return resposta
                except RotaIndisponivel as e:
                    tentadas.append({"rota": rota, "segundos": round(time.time() - t, 2),
                                     "resultado": "não atende", "motivo": str(e)[:160]})
                    erro = e
                    if not ultima:
                        log(f"  {rota} não atende agora ({str(e)[:100]}): seguindo com {vivas[k + 1]}")
                except (RuntimeError, SystemExit) as e:
                    tentadas.append({"rota": rota, "segundos": round(time.time() - t, 2),
                                     "resultado": "falhou", "motivo": str(e)[:160]})
                    erro = e
                    if ultima:
                        raise
                    log(f"  {rota} falhou ({str(e)[:100]}): seguindo com {vivas[k + 1]}")
            if not de_novo:
                raise RuntimeError(f"Nenhum modelo da cadeia atendeu na etapa {etapa}: {erro}")
    finally:
        try:
            from . import tempos
            tempos.anotar_chamada(projeto.pasta, "texto" if not imagens else "visão", etapa, comeco, ok,
                                  modelo=tentadas[-1]["rota"] if ok else None, rotas=tentadas,
                                  puladas=sorted(puladas), esperas=esperas)
        except Exception:  # medir nunca derruba a produção
            pass


def ve_imagem(projeto, rota) -> bool:
    """A rota aceita imagem? Não, se começa por um dos prefixos de openrouter.so_texto."""
    so_texto = (projeto.config.get("openrouter") or {}).get("so_texto") or []
    return not any(rota.startswith(p) for p in so_texto)


def uma_rota(projeto, etapa, instrucoes, pedido, esquema, log, rota, imagens, temperatura, cadeia=False,
             raciocinio=None):
    """Uma rota da cadeia: "groq:MODELO" vai pelo Groq (as 11 chaves do .env, de graça); o resto, pelo OpenRouter."""
    if rota.startswith("gemini:"):
        # a API do Google com a GEMINI_API_KEY (faturamento do AI Studio), sem pensar (gemini.raciocinio_na_cadeia):
        # o pensamento é cobrado como escrita. Quem não responde passa a vez na cadeia
        from . import gemini_local
        resposta = gemini_local.perguntar(projeto, etapa, instrucoes + regra_do_idioma(projeto), pedido, esquema, log=log,
                                          modelo=rota[7:], imagens=imagens, temperatura=temperatura, na_cadeia=True,
                                          raciocinio=(projeto.config.get("gemini") or {}).get("raciocinio_na_cadeia"))
        faltam = [k for k in (esquema or {}).get("required", []) if not isinstance(resposta, dict) or k not in resposta]
        if faltam:
            raise RotaIndisponivel(f"o Gemini não trouxe as chaves {', '.join(faltam)} na etapa {etapa}")
        return _sem_outro_alfabeto(resposta, projeto)
    if not rota.startswith("groq:"):
        return _perguntar_rota(projeto, etapa, instrucoes, pedido, esquema, log, rota, imagens, temperatura,
                               cadeia=cadeia, raciocinio=raciocinio)
    from . import groq_local
    tabela = raciocinio if raciocinio is not None else ((projeto.config.get("openrouter") or {}).get("raciocinio_por_modelo") or {})
    sistema = instrucoes + regra_do_idioma(projeto)
    obrigatorias = (esquema or {}).get("required", [])
    resposta = None
    for tentativa in range(2):
        resposta = groq_local.perguntar(projeto, etapa, sistema, pedido, esquema, log=log, modelo=rota[5:],
                                        imagens=imagens, temperatura=temperatura, na_cadeia=True, raciocinio=tabela)
        faltam = [k for k in obrigatorias if not isinstance(resposta, dict) or k not in resposta]
        quebrados = [] if faltam else _trechos_de_outro_alfabeto(resposta, projeto)
        if not faltam and not quebrados:
            return resposta
        # as mesmas conferências da rota do OpenRouter: chaves que faltaram e pedaços de outro alfabeto
        sistema = instrucoes + regra_do_idioma(projeto) + (
            f"\n\nATENÇÃO: a resposta anterior não trouxe as chaves {', '.join(faltam)}. Use exatamente os nomes de "
            "chave do esquema." if faltam else
            "\n\nATENÇÃO: a resposta anterior misturou caracteres de outros alfabetos no meio do texto. Escreva tudo "
            "só com o alfabeto latino, em português ou em inglês.")
    faltam = [k for k in obrigatorias if not isinstance(resposta, dict) or k not in resposta]
    if faltam:
        raise RuntimeError(f"o Groq ({rota[5:]}) não trouxe as chaves {', '.join(faltam)} na etapa {etapa}")
    return _sem_outro_alfabeto(resposta, projeto)


def _fora_do_ar(rota, minutos, motivo):
    _FORA_DO_AR[rota] = time.time() + minutos * 60
    raise RotaIndisponivel(motivo)


def _perguntar_rota(projeto, etapa, instrucoes, pedido, esquema, log, modelo, imagens, temperatura, cadeia=False,
                    traduzir=True, raciocinio=None):
    """Uma rota da cadeia. Com cadeia=True (há outra depois), o que não volta logo vira RotaIndisponivel.
    traduzir=False é a própria chamada de tradução dos trechos de outro alfabeto, que não traduz de novo."""
    cfg = projeto.config.get("openrouter") or {}
    # o Space Bunny e o Qwen misturam chinês no meio da resposta: o aviso vai antes, em todo pedido
    instrucoes = instrucoes + regra_do_idioma(projeto)
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
    tabela = raciocinio if raciocinio is not None else (cfg.get("raciocinio_por_modelo") or {})
    esforco = next((v for prefixo, v in tabela.items() if modelo.startswith(prefixo)), None)
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
    if provedor == "aimlapi":
        cabecalho = {"Authorization": f"Bearer {chave}"}
    else:
        cabecalho = cabecalhos(chave)
        corpo["session_id"] = sessao(projeto)  # o custo de cada vídeo na aba Sessions do painel do OpenRouter

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
        if credito_reservado(r):
            # há saldo, só está reservado para os pedidos em andamento: espera eles terminarem, sem gastar tentativa
            log("  OpenRouter com o saldo reservado pelos pedidos em andamento, esperando")
            time.sleep(random.uniform(3, 10))
            continue
        if cadeia and (r.status_code in (402, 404) or (r.status_code == 403 and ("fund" in texto_erro or "balance" in texto_erro))):
            # sem saldo nesta conta, ou o modelo saiu do ar: as próximas chamadas já vão direto para o seguinte
            # 404 por causa da imagem (o openrouter/free mandou para um modelo que só lê texto) não é modelo retirado
            # do ar: fica de lado 5 minutos, não um dia inteiro
            por_imagem = r.status_code == 404 and "image" in texto_erro
            _fora_do_ar(rota, 5 if por_imagem else 24 * 60 if r.status_code == 404 else 30, f"{r.status_code} {r.text[:120]}")
        if cadeia and r.status_code == 429:
            # limite do dia dos modelos gratuitos não volta em minutos; limite por minuto volta logo, em segundos
            # (openrouter.espera_no_limite_do_minuto). Era um minuto inteiro, mais do que qualquer espera que
            # _espera_por_melhor aceita: a rota rápida saía de cena e a escolha das fotos ia toda para a de reserva
            por_dia = "per-day" in texto_erro or "per day" in texto_erro or "daily" in texto_erro
            fora = 60 * 60 if por_dia else cfg.get("espera_no_limite_do_minuto", 15)
            _fora_do_ar(rota, fora / 60, f"429 {r.text[:120]}")
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
        _registrar(projeto, etapa, dados.get("usage"), ("aimlapi:" if provedor == "aimlapi" else "") + str(dados.get("model") or modelo),
                   time.time() - inicio)
        escolha = (dados.get("choices") or [{}])[0]
        if escolha.get("finish_reason") == "length" or not (escolha.get("message") or {}).get("content"):
            # o modelo gastou tudo pensando e não chegou a responder: tenta de novo UMA vez, já com o teto. Antes
            # subia em dois degraus (10 mil, 20 mil, 24 mil): no nunca-deve-ter-dentro-de-casa-parte-2 o DeepSeek
            # estourava nos três, cada volta levava minutos, e a criação ficou quase uma hora parada nos 15%
            if corpo["max_tokens"] >= cfg.get("max_tokens_teto", 16000):
                ultimo_erro, erros = "o modelo gastou o limite de tokens só raciocinando", cfg.get("tentativas", 5)
            else:
                corpo["max_tokens"] = cfg.get("max_tokens_teto", 16000)
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
        quebrados = _trechos_de_outro_alfabeto(resposta, projeto)
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
        return _sem_outro_alfabeto(resposta, projeto)
    raise RuntimeError(f"O OpenRouter não respondeu direito na etapa {etapa} ({ultimo_erro}).")


REGRA_DO_ALFABETO = (
    "\n\nIDIOMA: escreva todo o texto da resposta em português do Brasil (ou em inglês só onde o pedido mandar "
    "inglês, como nos termos de busca), sempre com o alfabeto latino. Nunca escreva em chinês, japonês, coreano, "
    "cirílico ou outro alfabeto, nem no meio de uma palavra. Não comente o seu raciocínio na resposta.")


def regra_do_idioma(projeto) -> str:
    """A REGRA_DO_ALFABETO e, num roteiro em outra língua, a exceção do que aparece na tela: o texto interno da fábrica
    (descrições, motivos, notas) segue em português, mas o que o público vê vai na língua do roteiro. Antes, a regra
    mandava TUDO em português, e o overlay do roteirista saiu "10 SUPERMERCADOS • 3 SEMANAS" num vídeo para americanos
    (cena 8 do everything-you-need-to-answer, 2026-10-14)."""
    from . import idioma

    try:
        codigo = idioma.lingua(projeto)
    except Exception:  # noqa: BLE001
        codigo = "pt"
    if codigo == "pt":
        return REGRA_DO_ALFABETO
    if codigo in _ALFABETO_DA_LINGUA:
        return (f"\n\nIDIOMA: este vídeo é em {idioma.nome(codigo)}. Todo texto que vai aparecer na tela ou para o "
                f"público (overlay, texto na tela, títulos, rótulos, legendas, título e descrição do YouTube, tags, "
                f"comentário fixado, shorts, thumbnail) vai em {idioma.nome(codigo)}, no alfabeto dessa língua, nunca em "
                "português nem transliterado. O texto interno da fábrica (descrições, motivos, notas) segue em "
                "português, e os termos de busca e os prompts de imagem em inglês. Não comente o seu raciocínio.")
    return (REGRA_DO_ALFABETO + f"\nEXCEÇÃO OBRIGATÓRIA: este vídeo é em {idioma.nome(codigo)}. Todo texto que vai "
            f"aparecer na tela ou para o público (overlay, texto na tela, títulos, rótulos, legendas, título e descrição "
            f"do YouTube, shorts, thumbnail) vai em {idioma.nome(codigo)}, nunca em português.")


def _traduzir_trechos(projeto, etapa, resposta, quebrados, log, rota):
    """Pede ao modelo a tradução de cada trecho de outro alfabeto, no idioma do texto em volta, e troca na resposta.
    Comentário do modelo sobre ele mesmo ("não posso mostrar meu raciocínio") volta vazio. Se falhar, segue
    sem traduzir (o que sobrar é apagado depois)."""
    trechos, vistos = [], set()
    proibido = _alfabeto_proibido(projeto)
    for texto in _textos(resposta):
        for m in proibido.finditer(texto):
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
# ... a não ser no vídeo daquela língua: para o Japão, este filtro apagava ou traduzia para o português todo texto de
# tela, descrição e título (roteiro-2, 2026-11-04: "Avaliação Elenco Pessoal Opinião" na tela e a descrição só com 、)
_ALFABETO_DA_LINGUA = {
    "ja": re.compile(r"[Ѐ-ӿ֐-׿؀-ۿऀ-ॿ฀-๿ᄀ-ᇿ가-힯]+"),
    "ko": re.compile(r"[Ѐ-ӿ֐-׿؀-ۿऀ-ॿ฀-๿぀-ヿ＀-￯]+"),
}


def _alfabeto_proibido(projeto=None):
    if projeto is None:
        return _OUTRO_ALFABETO
    from . import idioma
    try:
        return _ALFABETO_DA_LINGUA.get(idioma.lingua(projeto), _OUTRO_ALFABETO)
    except Exception:  # noqa: BLE001
        return _OUTRO_ALFABETO


def _textos(valor):
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for v in valor.values():
            yield from _textos(v)
    elif isinstance(valor, list):
        for v in valor:
            yield from _textos(v)


def _trechos_de_outro_alfabeto(resposta, projeto=None) -> list:
    proibido = _alfabeto_proibido(projeto)
    return [m.group() for texto in _textos(resposta) for m in proibido.finditer(texto)]


def _sem_outro_alfabeto(valor, projeto=None):
    """Tira os pedaços de outro alfabeto que sobraram, sem mexer no resto da resposta."""
    proibido = _alfabeto_proibido(projeto)
    if isinstance(valor, str):
        return re.sub(r"[ \t]{2,}", " ", proibido.sub(" ", valor)).strip() if proibido.search(valor) else valor
    if isinstance(valor, dict):
        return {k: _sem_outro_alfabeto(v, projeto) for k, v in valor.items()}
    if isinstance(valor, list):
        return [_sem_outro_alfabeto(v, projeto) for v in valor]
    return valor
