"""Imagens de IA, troca de cenas e página de revisão.

O provedor padrão é o Google, com o Nano Banana 2 direto pela API do Gemini.
A fal.ai continua disponível trocando imagens.provedor para fal no perfil.
"""
import copy
import html
import json
import random
import re
import shutil
import textwrap
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import fal_client
import httpx
from google import genai
from google.genai import errors as erros_google
from google.genai import types

from . import custos, midia
from .config import RAIZ, caminho_relativo, chave
from .util import mmss

ARGUMENTOS_FAL = {"aspect_ratio": "16:9", "resolution": "1K", "output_format": "png"}
MODELO_GOOGLE = "gemini-3.1-flash-image"
MODELO_KIE = "grok-imagine-image-2-0/text-to-image"  # Grok Imagine Image 2.0 via Kie.ai
MODELO_OPENROUTER = "x-ai/grok-imagine-image-2.0"  # o mesmo Grok Imagine 2, pelo OpenRouter (a chave que a fábrica já usa)
TIPOS_IMAGEM = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
ESTADOS_FINAIS_LOTE = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}
LIMITE_LOTE_BYTES = 18 * 1024 * 1024  # o Google aceita até 20 MB de pedidos em linha por lote

_google = None
_trava_google = threading.Lock()


class SemImagem(Exception):
    """O provedor respondeu, mas não entregou imagem, em geral por bloqueio de conteúdo."""


class SemCota(Exception):
    """O Google recusou por falta de cota, em geral porque o faturamento do projeto não está ativo."""


def provedor(perfil):
    return ((perfil.get("imagens") or {}).get("provedor") or "google").lower()


def pendentes_ia(projeto, cenas):
    return [c for c in cenas if midia.precisa_ia(c) and not projeto.imagem(c["n"]).exists()]


def gerar(projeto, apenas=None, log=print, direto=False, conferir=True):
    """Gera as imagens de IA que faltam e, com a IA ligada, o Jev confere cada uma (corrigir.conferir_ia): imagem que
    mostra outra coisa é feita de novo. conferir=False quando a pessoa pediu a imagem com o próprio prompt."""
    resultado = _gerar(projeto, apenas, log, direto)
    from .midia import ia_ativa

    if conferir and ia_ativa(projeto) and not projeto.offline:
        from . import corrigir
        try:
            corrigir.conferir_ia(projeto, set(apenas) if apenas is not None else None, log)
        except (Exception, SystemExit) as erro:
            # a conferência melhora o vídeo, nunca o para
            log(f"  a conferência das imagens de IA falhou, seguindo sem ela: {str(erro)[:160]}")
    return resultado


def _gerar(projeto, apenas=None, log=print, direto=False):
    cenas = [c for c in projeto.ler_json("cenas.json")["cenas"] if apenas is None or c["n"] in apenas]
    pendentes = pendentes_ia(projeto, cenas)
    from .midia import ia_ativa

    if pendentes and not ia_ativa(projeto):
        # ia.ativa: false no config.yaml: o vídeo sai só com acervo, e a cena sem material fica para o editor
        log(f"  IA desligada no config.yaml: {len(pendentes)} cena(s) sem material ficam sem imagem de IA")
        return gerar_revisao(projeto)
    if not pendentes:
        log("  nenhuma imagem de IA pendente")
        return gerar_revisao(projeto)

    if not projeto.offline:
        # cenas de IA seguidas ganham prompts escritos juntos, cada um no momento da própria fala
        try:
            if prompts_em_sequencia(projeto, {c["n"] for c in pendentes}, log):
                cenas = [c for c in projeto.ler_json("cenas.json")["cenas"] if apenas is None or c["n"] in apenas]
                pendentes = pendentes_ia(projeto, cenas)
        except (Exception, SystemExit) as erro:
            # deixa as imagens saírem com os prompts que já tinham
            log(f"  a revisão dos prompts em sequência falhou, seguindo com os prompts atuais: {str(erro)[:160]}")

    referencias = []
    if not projeto.offline:
        prov = provedor(projeto.perfil)
        if prov == "google":
            chave("GEMINI_API_KEY")
        elif prov in ("kie", "kie.ai"):
            chave("KIE_API_KEY")
        elif prov == "openrouter":
            from .openrouter_local import _chave
            _chave()
        else:
            chave("FAL_KEY")
        if any(c["personagem"] for c in pendentes):
            referencias = _referencias(projeto.perfil, log)

    geral = projeto.config.get("imagens") or {}
    if (custos.em_lote_no_google(projeto) and not projeto.offline and not direto
            and len(pendentes) >= geral.get("minimo_lote", 8)):
        falhas = _gerar_em_lote(projeto, pendentes, referencias, log)
        if falhas:
            log(f"  {len(falhas)} imagens ficaram sem resultado ({', '.join(map(str, sorted(falhas)))}). "
                "Rode o mesmo comando para tentar só essas.")
        return gerar_revisao(projeto)

    falhas = []
    with ThreadPoolExecutor(geral.get("processos", 6)) as executor:
        futuros = {
            executor.submit(_gerar_uma, projeto, c, referencias, geral.get("tentativas", 3)): c
            for c in pendentes
        }
        for i, futuro in enumerate(as_completed(futuros), 1):
            cena = futuros[futuro]
            try:
                futuro.result()
            except SemCota as erro:
                executor.shutdown(wait=False, cancel_futures=True)
                raise SystemExit(str(erro))
            except Exception as erro:
                falhas.append(cena["n"])
                log(f"  cena {cena['n']} falhou. {str(erro)[:200]}")
            else:
                if i % 5 == 0 or i == len(futuros):
                    log(f"  imagens {i}/{len(futuros)}")
    if falhas:
        log(f"  {len(falhas)} imagens falharam ({', '.join(map(str, sorted(falhas)))}). "
            "Rode o mesmo comando para tentar só essas, ou troque a descrição com fabrica refazer --prompt.")
    return gerar_revisao(projeto)


# ------------------------------------------------------------------------- prompts de cenas de IA seguidas

INSTRUCOES_SEQUENCIA = """Você é diretor de fotografia de um documentário narrado para o YouTube. Escreve os prompts das
imagens de IA de um TRECHO de cenas seguidas, que aparecem uma depois da outra, de 3 a 5 segundos cada.

O problema que você resolve: cenas seguidas do mesmo assunto saíam com a MESMA imagem (o mesmo homem de costas
andando para a mesma ponte, quatro vezes). O espectador vê isso como repetição.

Regras:
1. Cada imagem mostra o que a fala DAQUELA cena diz, no momento dela. Leia a fala de cada cena: ela avança a história
   (alguém chega, é apresentado, é descrito, se engana). A imagem acompanha esse avanço.
2. Nunca repita a composição da cena vizinha: mude a ação, o momento, o objeto, o lugar ou a hora. Uma pessoa pode
   aparecer em cenas seguidas, mas fazendo coisas diferentes, em lugares ou momentos diferentes.
   O PLANO É OBRIGATORIAMENTE DIFERENTE DA CENA ANTERIOR: "geral" (o lugar inteiro, a pessoa pequena nele), "medio"
   (a pessoa da cintura para cima, ou o grupo), "detalhe" (as mãos, um objeto citado, pegadas, uma ferramenta, um
   documento, sem o rosto). Pessoa real que não pode mostrar o rosto rende bem em "detalhe".
   Também não repita a imagem de duas cenas antes. Uma mesma pose (por exemplo, a pessoa de costas olhando a obra)
   aparece no máximo UMA vez no trecho.
3. Precisão literal: o que a fala cita aparece. Nada de metáfora nem de imagem sem relação. Fala abstrata ("ele estava
   muito enganado", "ninguém imaginava") mostra a pessoa ou o lugar de que a fala trata, num momento concreto e
   diferente, com a emoção da fala (luz, expressão corporal, clima).
4. Respeite o que o pedido exige: época, lugar, roupas, a espécie exata, e pessoa real vista de costas ou sem o rosto
   quando o pedido diz isso. Mesma época e mesmos personagens em todo o trecho, coerentes entre si.
5. Cenas marcadas "JÁ TEM IMAGEM" não mudam: só servem para você não repetir o que elas mostram.
6. Prompt em inglês, de 1 a 3 frases: sujeito, ação, enquadramento e ambiente. Nunca peça texto escrito na imagem.
   Responda um item para cada cena que pode mudar."""

ESQUEMA_SEQUENCIA = {
    "type": "object",
    "properties": {"cenas": {"type": "array", "items": {
        "type": "object",
        "properties": {"n": {"type": "integer"}, "plano": {"type": "string", "enum": ["geral", "medio", "detalhe"]},
                       "prompt": {"type": "string"}},
        "required": ["n", "plano", "prompt"]}}},
    "required": ["cenas"],
}
_TRECHO_MAXIMO = 8  # cenas por pedido; trecho maior vai em partes, cada parte vendo o fim da anterior


def _palavras_do_prompt(texto) -> set:
    return {w for w in re.findall(r"[a-z]+", (texto or "").lower()) if len(w) > 3}


def parecidos(a, b) -> float:
    """Quanto dois prompts dividem as mesmas palavras (0 a 1). Acima de 0,5 é praticamente o mesmo pedido."""
    pa, pb = _palavras_do_prompt(a), _palavras_do_prompt(b)
    return len(pa & pb) / max(1, len(pa | pb))


def _trechos_de_ia(cenas, pendentes) -> list:
    """Cenas de IA seguidas, do mesmo bloco, com duas ou mais cenas e pelo menos uma imagem por fazer."""
    trechos, atual = [], []
    for c in sorted(cenas, key=lambda c: c["n"]):
        if midia.precisa_ia(c) and atual and c["n"] == atual[-1]["n"] + 1 and c.get("bloco") == atual[-1].get("bloco"):
            atual.append(c)
            continue
        if len(atual) >= 2 and any(x["n"] in pendentes for x in atual):
            trechos.append(atual)
        atual = [c] if midia.precisa_ia(c) else []
    if len(atual) >= 2 and any(x["n"] in pendentes for x in atual):
        trechos.append(atual)
    return trechos


def _linha_da_cena(c, muda) -> str:
    linhas = [f"Cena {c['n']} ({c['fim'] - c['ini']:.1f} s)" + ("" if muda else " - JÁ TEM IMAGEM, não muda"),
              f"  Fala: \"{(c.get('texto') or '').strip()}\""]
    for rotulo, campo in (("O agente pediu para esta frase", "mostrar"), ("Mínimo para estar certa", "aceitavel"),
                          ("Tem que mostrar", "exato"), ("Espécie", "animal"), ("Época", "epoca")):
        if (c.get(campo) or "").strip():
            linhas.append(f"  {rotulo}: {c[campo].strip()}")
    if c.get("plano"):
        linhas.append(f"  Plano: {c['plano']}")
    prompt = (c.get("prompt_manual") or c.get("prompt") or "").strip()
    if prompt:
        linhas.append(f"  Prompt {'atual' if muda else 'da imagem'}: {prompt}")
    return "\n".join(linhas)


def prompts_em_sequencia(projeto, pendentes, log=print) -> int:
    """Reescreve juntos os prompts de cenas de IA seguidas, cada um no momento da própria fala e sem repetir a
    vizinha. Grátis (modelo principal). Devolve quantos prompts mudaram.

    Antes cada prompt era escrito sozinho (pelo agente, pela conferência ou pelo diretor): as cenas 23 a 26 do
    virou-filme-em-1996 saíram como quatro imagens do mesmo engenheiro de costas andando para a mesma ponte. Só muda
    cena sem imagem ainda e sem prompt da pessoa (prompt_manual)."""
    from . import openrouter_local

    dados = projeto.ler_json("cenas.json")
    cenas = dados["cenas"]
    por_n = {c["n"]: c for c in cenas}
    blocos = {}
    if projeto.existe("roteiro_mapa.json"):
        try:
            blocos = {b.get("id"): b for b in projeto.ler_json("roteiro_mapa.json").get("blocos") or []}
        except (OSError, ValueError):
            blocos = {}
    mudaram = 0
    for trecho in _trechos_de_ia(cenas, pendentes):
        for k in range(0, len(trecho), _TRECHO_MAXIMO):
            parte = trecho[max(0, k - 1):k + _TRECHO_MAXIMO]  # a última da parte anterior entra como contexto
            podem = [c["n"] for c in parte if c["n"] in pendentes and not (c.get("prompt_manual") or "").strip()
                     and c["n"] in [x["n"] for x in trecho[k:k + _TRECHO_MAXIMO]]]
            # já reescritos numa rodada anterior (a imagem não saiu, por exemplo sem saldo): não pede de novo
            if not podem or all("prompt_antes_da_sequencia" in por_n[n] for n in podem):
                continue
            bloco = blocos.get(parte[0].get("bloco")) or {}
            antes, depois = por_n.get(parte[0]["n"] - 1), por_n.get(parte[-1]["n"] + 1)
            pedido = []
            if bloco:
                pedido.append(f"Assunto do bloco: {bloco.get('nome', '')}; imagem-âncora: {bloco.get('ancora', '')}"
                              + (f"; época: {bloco['epoca']}" if bloco.get("epoca") else ""))
            if antes:
                pedido.append(f"Antes do trecho (só contexto), a fala: \"{(antes.get('texto') or '').strip()}\"")
            pedido += [_linha_da_cena(c, c["n"] in podem) for c in parte]
            if depois:
                pedido.append(f"Depois do trecho (só contexto), a fala: \"{(depois.get('texto') or '').strip()}\"")
            pedido.append(f"Escreva o prompt das cenas {', '.join(map(str, podem))}.")
            novos, planos, queixa = {}, {}, ""
            for _ in range(2):
                resposta = openrouter_local.perguntar(
                    projeto, "prompts de IA em sequência", INSTRUCOES_SEQUENCIA, "\n\n".join(pedido) + queixa,
                    ESQUEMA_SEQUENCIA, log=log, modelo=openrouter_local.principal(projeto), temperatura=0.5)
                novos = {int(i["n"]): " ".join(str(i.get("prompt") or "").split())
                         for i in (resposta.get("cenas") or []) if isinstance(i, dict) and str(i.get("n", "")).isdigit()}
                novos = {n: t for n, t in novos.items() if n in podem and len(t.split()) >= 8}
                planos = {int(i["n"]): str(i.get("plano") or "").strip().lower()
                          for i in (resposta.get("cenas") or []) if isinstance(i, dict) and str(i.get("n", "")).isdigit()}
                # o código confere: duas cenas seguidas com quase o mesmo pedido ou no mesmo plano voltam uma vez
                final = [novos.get(c["n"]) or c.get("prompt_manual") or c.get("prompt") or "" for c in parte]
                plano = [planos.get(c["n"]) if c["n"] in novos else c.get("plano") for c in parte]
                iguais = [(parte[i]["n"], parte[i + 1]["n"]) for i in range(len(parte) - 1)
                          if parecidos(final[i], final[i + 1]) >= 0.5
                          or (plano[i] and plano[i] == plano[i + 1] and (parte[i]["n"] in novos or parte[i + 1]["n"] in novos))]
                # e com a de duas antes: as cenas 24 e 26 do virou-filme (0,41) saíram com a mesma pose
                iguais += [(parte[i]["n"], parte[i + 2]["n"]) for i in range(len(parte) - 2)
                           if parecidos(final[i], final[i + 2]) >= 0.4
                           and (parte[i]["n"] in novos or parte[i + 2]["n"] in novos)]
                if not iguais:
                    break
                queixa = ("\n\nA resposta anterior repetiu o pedido ou o plano entre as cenas "
                          + ", ".join(f"{a} e {b}" for a, b in iguais)
                          + ". Cenas seguidas têm planos diferentes e mostram ações ou momentos diferentes.")
            for n, texto in novos.items():
                if planos.get(n) in ("geral", "medio", "detalhe"):
                    por_n[n]["plano"] = planos[n]
                if texto != (por_n[n].get("prompt") or "").strip():
                    por_n[n]["prompt_antes_da_sequencia"] = por_n[n].get("prompt") or ""
                    por_n[n]["prompt"] = texto
                    mudaram += 1
    if mudaram:
        projeto.salvar_json("cenas.json", dados)
        log(f"  {mudaram} prompt(s) de cenas de IA seguidas reescritos, cada um no momento da própria fala")
    return mudaram


def prompt_final(cena, perfil, com_referencia):
    img = perfil.get("imagens") or {}
    personagem = perfil.get("personagem") or {}
    partes = []
    if cena["personagem"] and com_referencia:
        partes.append(
            "Create a new photograph. The person in the reference image is the character of this scene. "
            "Keep exactly the same face, hair and age, with a new pose, setting and framing as described."
        )
    elif cena["personagem"] and personagem.get("descricao"):
        partes.append(f"Main character: {personagem['descricao'].strip()}")
    partes.append(f"Scene: {(cena.get('prompt_manual') or cena['prompt']).strip()}")
    if midia.e_de_epoca(cena):
        # cena de época junto de fotos de arquivo: a imagem de IA tem cara de foto daquele tempo, não de cinema atual
        partes.append(f"Style: authentic photograph taken around {cena['epoca']}, period-accurate clothing, objects and "
                      "buildings, black and white or faded sepia, film grain, natural light of the time, documentary "
                      "framing. Nothing modern in the image.")
    elif img.get("estilo"):
        partes.append(f"Style: {img['estilo'].strip()}")
    if cena.get("ia_motivo") and (cena.get("mostrar") or "").strip():
        # a cena veio para a IA porque a foto do banco mostrava outra coisa: o que ela tem que mostrar, sem erro
        partes.append(f"The image must clearly show: {cena['mostrar'].strip()}")
    if img.get("evitar"):
        partes.append(f"Do not include: {img['evitar'].strip()}")
    return "\n".join(partes)


def _gerar_uma(projeto, cena, referencias, tentativas):
    destino = projeto.imagem(cena["n"])
    if projeto.offline:
        _imagem_de_teste(cena, destino)
        return
    img = projeto.perfil.get("imagens") or {}
    com_referencia = bool(cena["personagem"] and referencias)
    prompt = prompt_final(cena, projeto.perfil, com_referencia)
    usar = referencias if com_referencia else []

    erro = None
    for tentativa in range(tentativas):
        try:
            prov = provedor(projeto.perfil)
            if prov == "google":
                dados = _imagem_google(prompt, img, usar, img.get("proporcao", "16:9"), img.get("resolucao", "1K"))
                registro = {"provedor": "google", "modelo": img.get("modelo", MODELO_GOOGLE), "prompt": prompt}
            elif prov in ("kie", "kie.ai"):
                dados, registro = _imagem_kie(prompt, img)
            elif prov == "openrouter":
                dados, registro = _imagem_openrouter(prompt, img)
            else:
                dados, registro = _imagem_fal(prompt, img, usar)
            temporario = destino.with_name(destino.stem + ".baixando")
            temporario.write_bytes(dados)
            temporario.replace(destino)
            destino.with_suffix(".json").write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
            from . import custos_reais

            custos_reais.registrar(
                projeto, "imagem", f"imagem de IA da cena {cena['n']}", custos.preco_da_imagem(projeto),
                unidades=1, detalhes={"cena": cena["n"], "provedor": registro.get("provedor", prov),
                                      "modelo": registro.get("modelo", "")})
            return
        except SemImagem as e:
            raise e  # repetir o mesmo pedido bloqueado não adianta
        except erros_google.APIError as e:
            if _sem_cota(e):
                raise SemCota(
                    "O Google recusou as imagens por falta de cota. Ative o faturamento do projeto da sua chave "
                    "no Google AI Studio e rode o mesmo comando de novo."
                )
            erro = e
            time.sleep((20 if e.code == 429 else 4) * (tentativa + 1))
        except Exception as e:
            erro = e
            time.sleep(4 * (tentativa + 1))
    raise erro


def _cliente_google():
    global _google
    with _trava_google:
        if _google is None:
            _google = genai.Client(api_key=chave("GEMINI_API_KEY"))
    return _google


def _partes_google(prompt, referencias):
    partes = [types.Part.from_text(text=prompt)]
    return partes + [types.Part.from_bytes(data=dados, mime_type=tipo) for dados, tipo in referencias]


def _config_google(proporcao, resolucao):
    return types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=proporcao, image_size=resolucao),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )


def _imagem_google(prompt, img, referencias, proporcao, resolucao):
    resposta = _cliente_google().models.generate_content(
        model=img.get("modelo", MODELO_GOOGLE),
        contents=_partes_google(prompt, referencias),
        config=_config_google(proporcao, resolucao),
    )
    return _extrair_imagem(resposta)


def _extrair_imagem(resposta):
    for candidato in resposta.candidates or []:
        for parte in (candidato.content.parts if candidato.content else None) or []:
            if parte.inline_data and parte.inline_data.data:
                return parte.inline_data.data
    motivos = [str(c.finish_reason) for c in resposta.candidates or [] if c.finish_reason]
    if resposta.prompt_feedback and resposta.prompt_feedback.block_reason:
        motivos.append(str(resposta.prompt_feedback.block_reason))
    raise SemImagem(f"o Google não entregou imagem ({', '.join(motivos) or 'sem motivo informado'}). Troque a descrição da cena.")


def _sem_cota(erro):
    return erro.code == 429 and ("billing" in str(erro) or "limit: 0" in str(erro))


def _gerar_em_lote(projeto, pendentes, referencias, log):
    """Manda as imagens de uma vez para o modo lote do Google, pela metade do preço, e espera.

    O Google promete o resultado em até 24 horas e costuma entregar em minutos. Cada lote
    enviado fica registrado em imagens/lotes, então se o programa parar no meio, rodar o
    mesmo comando continua esperando o mesmo lote, sem pagar de novo.
    """
    img = projeto.perfil.get("imagens") or {}
    geral = projeto.config.get("imagens") or {}
    cliente = _cliente_google()
    pasta = projeto.caminho("imagens", "lotes", "_").parent
    por_cena = {c["n"]: c for c in pendentes}

    lotes = [(arquivo, json.loads(arquivo.read_text(encoding="utf-8"))) for arquivo in sorted(pasta.glob("lote_*.json"))]
    cobertas = {item["n"] for _, dados in lotes for item in dados["cenas"]}
    if lotes:
        log(f"  {len(lotes)} lote(s) já enviados ao Google, esperando por eles")

    # novos lotes, respeitando o tamanho máximo de pedido em linha
    grupos, grupo, tamanho = [], [], 0
    for c in pendentes:
        if c["n"] in cobertas:
            continue
        com_referencia = bool(c["personagem"] and referencias)
        usar = referencias if com_referencia else []
        prompt = prompt_final(c, projeto.perfil, com_referencia)
        peso = len(prompt.encode()) + 600 + sum(int(len(dados) * 1.4) for dados, _ in usar)
        if grupo and tamanho + peso > LIMITE_LOTE_BYTES:
            grupos.append(grupo)
            grupo, tamanho = [], 0
        grupo.append((c, prompt, usar))
        tamanho += peso
    if grupo:
        grupos.append(grupo)
    for grupo in grupos:
        pedidos = [
            types.InlinedRequest(
                contents=[types.Content(role="user", parts=_partes_google(prompt, usar))],
                config=_config_google(img.get("proporcao", "16:9"), img.get("resolucao", "1K")),
            )
            for _, prompt, usar in grupo
        ]
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        try:
            tarefa = cliente.batches.create(
                model=img.get("modelo", MODELO_GOOGLE), src=pedidos,
                config={"display_name": f"fabrica-{projeto.nome}-{carimbo}"},
            )
        except erros_google.APIError as e:
            if _sem_cota(e):
                raise SystemExit("O Google recusou o lote por falta de cota. Ative o faturamento do projeto da sua chave "
                                 "no Google AI Studio e rode o mesmo comando de novo.")
            raise
        dados = {"nome": tarefa.name, "criado": carimbo, "modelo": img.get("modelo", MODELO_GOOGLE),
                 "cenas": [{"n": c["n"], "prompt": prompt} for c, prompt, _ in grupo]}
        arquivo = pasta / f"lote_{carimbo}.json"
        arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        lotes.append((arquivo, dados))
        log(f"  lote de {len(grupo)} imagens enviado ao Google")

    inicio, ultimo_aviso = time.time(), time.time()
    limite = float(geral.get("espera_lote_horas", 24)) * 3600
    falhas, prontas = [], 0
    while lotes:
        restantes = []
        for arquivo, dados in lotes:
            tarefa = cliente.batches.get(name=dados["nome"])
            estado = tarefa.state.name if tarefa.state else ""
            if estado not in ESTADOS_FINAIS_LOTE:
                restantes.append((arquivo, dados))
                continue
            if estado != "JOB_STATE_SUCCEEDED":
                log(f"  um lote terminou com estado {estado}, as cenas dele voltam para a fila")
                falhas += [item["n"] for item in dados["cenas"]]
                arquivo.unlink()
                continue
            respostas = (tarefa.dest.inlined_responses if tarefa.dest else None) or []
            if len(respostas) != len(dados["cenas"]):
                log(f"  o Google devolveu {len(respostas)} respostas para {len(dados['cenas'])} pedidos")
            for item, resposta in zip(dados["cenas"], respostas):
                cena = por_cena.get(item["n"])
                if cena is None:
                    continue
                try:
                    if resposta.error:
                        raise SemImagem(str(resposta.error))
                    imagem = _extrair_imagem(resposta.response)
                except SemImagem as e:
                    falhas.append(item["n"])
                    log(f"  cena {item['n']} sem imagem. {str(e)[:160]}")
                    continue
                destino = projeto.imagem(item["n"])
                temporario = destino.with_name(destino.stem + ".baixando")
                temporario.write_bytes(imagem)
                temporario.replace(destino)
                registro = {"provedor": "google", "modelo": dados["modelo"], "prompt": item["prompt"], "lote": dados["nome"]}
                destino.with_suffix(".json").write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
                prontas += 1
            falhas += [item["n"] for item in dados["cenas"][len(respostas):]]
            arquivo.unlink()
            log(f"  lote pronto, {prontas} imagens gravadas")
        lotes = restantes
        if not lotes:
            break
        if time.time() - inicio > limite:
            raise SystemExit("O Google passou do tempo de espera com o lote ainda em andamento. Rode o mesmo comando mais tarde.")
        if time.time() - ultimo_aviso >= 300:
            log(f"  esperando o Google terminar {len(lotes)} lote(s), {mmss(time.time() - inicio)} de espera")
            ultimo_aviso = time.time()
        time.sleep(30)
    return falhas


def _imagem_fal(prompt, img, referencias):
    if referencias:
        modelo = img.get("modelo_com_referencia", "fal-ai/nano-banana-2/edit")
        argumentos = {**ARGUMENTOS_FAL, **(img.get("argumentos_com_referencia") or {})}
        argumentos[img.get("campo_referencia", "image_urls")] = referencias
    else:
        modelo = img.get("modelo_fal", "fal-ai/nano-banana-2")
        argumentos = {**ARGUMENTOS_FAL, **(img.get("argumentos") or {})}
    argumentos["prompt"] = prompt
    resultado = fal_client.subscribe(modelo, arguments=argumentos)
    url = resultado["images"][0]["url"]
    r = httpx.get(url, timeout=120, follow_redirects=True)
    r.raise_for_status()
    return r.content, {"provedor": "fal", "modelo": modelo, "argumentos": argumentos, "url": url}


def _referencias(perfil, log):
    """Fotos de referência da personagem. O Google recebe os bytes e a fal.ai recebe links."""
    caminhos = (perfil.get("personagem") or {}).get("referencias") or []
    referencias = []
    for c in caminhos:
        arquivo = caminho_relativo(c)
        if not arquivo.exists():
            raise SystemExit(f"Imagem de referência não encontrada em {arquivo}")
        if provedor(perfil) == "google":
            referencias.append((arquivo.read_bytes(), TIPOS_IMAGEM.get(arquivo.suffix.lower(), "image/png")))
        else:
            referencias.append(fal_client.upload_file(arquivo))
    if not referencias:
        log("  aviso, o perfil não tem foto de referência e a personagem pode mudar de rosto entre as cenas")
    return referencias


def _imagem_openrouter(prompt, img):
    """Gera imagem por um modelo de imagem do OpenRouter (padrão: Grok Imagine Image 2.0). A imagem volta na própria
    resposta, em base64 ou como endereço. Usa a chave do OpenRouter que a fábrica já tem no .env."""
    import base64
    from .openrouter_local import _chave

    modelo = img.get("modelo_openrouter") or (img.get("modelo") if "/" in str(img.get("modelo") or "")
                                              and not str(img.get("modelo")).startswith("grok-imagine-image-2-0/")
                                              else MODELO_OPENROUTER)
    corpo = {"model": modelo, "messages": [{"role": "user", "content": prompt}], "modalities": ["image"],
             "image_config": {"aspect_ratio": img.get("proporcao", "16:9")}, "usage": {"include": True}}
    with httpx.Client(timeout=180.0, follow_redirects=True) as cliente:
        r = cliente.post("https://openrouter.ai/api/v1/chat/completions", json=corpo,
                         headers={"Authorization": f"Bearer {_chave()}"})
        if r.status_code == 402:
            raise SemCota("OpenRouter: acabou o crédito. Adicione saldo em openrouter.ai/credits.")
        if r.status_code in (401, 403):
            raise RuntimeError(f"OpenRouter recusou a chave ({r.status_code}). Confira o .env.")
        if r.status_code != 200:
            raise RuntimeError(f"OpenRouter falhou ao gerar a imagem ({r.status_code}): {r.text[:300]}")
        dados = r.json()
        if dados.get("error"):
            raise RuntimeError(f"OpenRouter falhou ao gerar a imagem: {str(dados['error'])[:300]}")
        mensagem = ((dados.get("choices") or [{}])[0].get("message") or {})
        figuras = mensagem.get("images") or []
        if not figuras:
            raise SemImagem(f"OpenRouter respondeu sem imagem ({str(mensagem.get('content') or '')[:200]})")
        endereco = (figuras[0].get("image_url") or {}).get("url") or ""
        if endereco.startswith("data:"):
            conteudo = base64.b64decode(endereco.split(",", 1)[1])
        else:
            baixado = cliente.get(endereco)
            baixado.raise_for_status()
            conteudo = baixado.content
    custo = (dados.get("usage") or {}).get("cost")
    return conteudo, {"provedor": "openrouter", "modelo": modelo, "prompt": prompt, "custo_usd": custo}


def _imagem_kie(prompt, img):
    """Gera imagem pela API da Kie.ai (Grok Imagine Image 2.0)."""
    api_key = chave("KIE_API_KEY")
    modelo = img.get("modelo", MODELO_KIE)
    proporcao = img.get("proporcao", "16:9")

    payload = {
        "model": modelo,
        "input": {"aspect_ratio": proporcao, "prompt": prompt},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        resp = client.post("https://api.kie.ai/api/v1/jobs/createTask", json=payload, headers=headers)
        if resp.status_code in (401, 403):
            raise RuntimeError(f"Kie.ai: chave de API não autorizada ou inválida (HTTP {resp.status_code}).")
        if resp.status_code == 402:
            raise SemCota("Kie.ai: créditos insuficientes na conta. Recarregue seu saldo para gerar novas imagens com IA.")
        if resp.status_code != 200:
            raise RuntimeError(f"Erro ao criar tarefa na Kie.ai ({resp.status_code}): {resp.text[:300]}")

        try:
            res_data = resp.json()
        except Exception:
            raise RuntimeError(f"Kie.ai retornou resposta não-JSON: {resp.text[:300]}")

        codigo = res_data.get("code")
        msg = str(res_data.get("msg") or res_data.get("message") or "")
        msg_lower = msg.lower()
        if codigo == 402 or "insufficient" in msg_lower or "credit" in msg_lower or "top up" in msg_lower:
            raise SemCota(f"Kie.ai: saldo de créditos insuficiente. {msg or 'Recarregue seu saldo na Kie.ai para continuar.'}")
        if codigo not in (0, 200, None):
            raise RuntimeError(f"Kie.ai recusou o pedido (código {codigo}): {msg}")

        task_id = None
        if isinstance(res_data.get("data"), dict):
            task_id = res_data["data"].get("taskId") or res_data["data"].get("task_id")
        if not task_id:
            task_id = res_data.get("taskId") or res_data.get("task_id") or (res_data.get("data") if isinstance(res_data.get("data"), str) else None)

        if not task_id or not isinstance(task_id, str):
            raise RuntimeError(f"Kie.ai não retornou um taskId válido: {resp.text[:300]}")

        inicio = time.time()
        while time.time() - inicio < 300:
            time.sleep(4)
            r = client.get(f"https://api.kie.ai/api/v1/jobs/recordInfo?taskId={task_id}", headers=headers)
            if r.status_code != 200:
                continue
            try:
                rec = r.json()
            except Exception:
                continue
            dados = rec.get("data") if isinstance(rec.get("data"), dict) else rec

            status = str(dados.get("state") or dados.get("status") or "").lower()
            success_flag = dados.get("successFlag") == 1
            if status in ("1", "success", "succeeded") or success_flag:
                resp_obj = dados.get("response")
                if isinstance(resp_obj, str) and resp_obj.strip().startswith("{"):
                    try:
                        resp_obj = json.loads(resp_obj)
                    except Exception:
                        pass
                result_json = dados.get("resultJson")
                if isinstance(result_json, str) and result_json.strip().startswith("{"):
                    try:
                        result_json = json.loads(result_json)
                    except Exception:
                        pass

                urls = (
                    (resp_obj.get("resultUrls") if isinstance(resp_obj, dict) else None)
                    or (result_json.get("resultUrls") if isinstance(result_json, dict) else None)
                    or dados.get("resultUrls")
                    or dados.get("result_urls")
                    or [dados.get("resultUrl")]
                    or [dados.get("result_url")]
                    or dados.get("images")
                )
                if isinstance(urls, str):
                    urls = [urls]
                if isinstance(urls, list) and urls and urls[0]:
                    url = urls[0]
                    if isinstance(url, dict):
                        url = url.get("url") or url.get("image") or url.get("fileUrl")
                    if not url or not isinstance(url, str):
                        raise SemImagem("Kie.ai concluiu a tarefa mas o link da imagem retornado é inválido.")
                    dl = client.get(url, timeout=60.0)
                    dl.raise_for_status()
                    return dl.content, {
                        "provedor": "kie",
                        "modelo": modelo,
                        "prompt": prompt,
                        "task_id": task_id,
                        "url": url,
                    }
                raise SemImagem(f"Kie.ai concluiu a tarefa mas não retornou URL da imagem: {r.text[:300]}")
            elif status in ("2", "3", "fail", "failed", "error") or dados.get("failCode") is not None:
                msg = dados.get("failMsg") or dados.get("errorMessage") or dados.get("error") or dados.get("msg") or "Falha na geração"
                raise SemImagem(f"Kie.ai falhou ao gerar imagem: {msg}")

        raise RuntimeError(f"Tempo limite excedido na Kie.ai aguardando a tarefa {task_id}")



def _fonte(tamanho):
    from PIL import ImageFont

    for caminho in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(caminho, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(tamanho)


def _imagem_de_teste(cena, destino):
    """Imagem com número e texto da cena, para testar o fluxo sem gastar."""
    from PIL import Image, ImageDraw

    largura, altura = 1920, 1080
    cor = tuple(random.Random(cena["n"]).randint(40, 130) for _ in range(3))
    clara = tuple(min(255, c + 35) for c in cor)
    imagem = Image.new("RGB", (largura, altura), cor)
    desenho = ImageDraw.Draw(imagem)
    for x in range(0, largura, 120):
        desenho.line([(x, 0), (x, altura)], fill=clara, width=2)
    for y in range(0, altura, 120):
        desenho.line([(0, y), (largura, y)], fill=clara, width=2)
    titulo = f"CENA {cena['n']}  ·  IA" + ("  ·  PERSONAGEM" if cena["personagem"] else "")
    desenho.text((120, 120), titulo, font=_fonte(80), fill="white")
    y = 260
    for linha in textwrap.wrap(cena["texto"], 55)[:12]:
        desenho.text((120, y), linha, font=_fonte(48), fill="white")
        y += 64
    imagem.save(destino)


def refazer(projeto, numeros, prompt=None, busca=None, forcar_ia=False, log=print, tipo=None):
    """Troca o que aparece nas cenas indicadas.

    Sem opções, cena real ganha outro candidato e cena de IA ganha outra imagem.
    Com busca, a cena procura material real com os novos termos.
    Com prompt ou forcar_ia, a cena passa a usar imagem de IA.
    Com tipo foto_real ou video_real, a pessoa escolheu material de acervo: a cena só procura em acervo,
    e se não achar nada avisa, sem gerar uma imagem de IA no lugar.
    """
    # termos de busca sem prompt e sem pedido de IA também são escolha de acervo, mesmo sem o tipo informado
    escolheu_real = not forcar_ia and (tipo in midia.TIPOS_REAIS or bool(busca and not prompt and tipo is None))
    dados = projeto.ler_json("cenas.json")
    existentes = {c["n"] for c in dados["cenas"]}
    invalidas = [n for n in numeros if n not in existentes]
    if invalidas:
        raise SystemExit(f"Essas cenas não existem: {', '.join(map(str, invalidas))}")
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    # a busca digitada pela pessoa vale em inglês, que é a língua dos bancos ("geada na grama" -> "frost covered grass")
    digitada = busca if busca and not prompt and not forcar_ia else None
    busca = midia.busca_em_ingles(projeto, busca, log) if digitada else busca
    reais = []
    buscas_pedidas = {}
    anteriores = {}  # o que cada cena tinha, para devolver se a busca não achar nada
    for c in dados["cenas"]:
        if c["n"] not in numeros:
            continue
        anteriores[c["n"]] = (copy.deepcopy(c.get("midia")), c.get("tipo"), c.get("busca"), list(c.get("rejeitadas") or []),
                              _guardar_versao_antiga(projeto, c, carimbo))
        if c.get("midia"):
            c.setdefault("rejeitadas", []).append(f"{c['midia']['fonte']}:{c['midia']['id']}")
            c["midia"] = None
        if digitada:
            _a_busca_da_pessoa_manda(c, digitada, busca)
            from . import aprendizados
            aprendizados.registrar(projeto, c, "busca", digitada)
        if escolheu_real:
            c["tipo"] = tipo if tipo in midia.TIPOS_REAIS else (c.get("tipo") if c.get("tipo") in midia.TIPOS_REAIS else "foto_real")
            # uma cena que era de IA não tem busca: os termos saem do prompt ou do texto dela
            c["busca"] = (busca or c.get("busca") or _busca_da_cena(c)).strip()
            buscas_pedidas[c["n"]] = c["busca"]
            c.pop("sem_midia_real", None)
            reais.append(c["n"])
        elif prompt or forcar_ia:
            c["tipo"], c["busca"] = "ia", ""
            c.pop("sem_midia_real", None)
            if prompt:
                c["prompt_manual"] = prompt
        elif busca:
            c["busca"] = busca
            if c.get("tipo") not in midia.TIPOS_REAIS:
                c["tipo"] = "foto_real"
            c.pop("sem_midia_real", None)
            reais.append(c["n"])
        elif midia.pendente(c):
            reais.append(c["n"])
    projeto.salvar_json("cenas.json", dados)
    if reais:
        midia.buscar(projeto, apenas=set(reais), log=log, permissivo=escolheu_real)
    if escolheu_real:
        dados = projeto.ler_json("cenas.json")
        faltando = [c for c in dados["cenas"] if c["n"] in numeros and not c.get("midia")]
        if faltando:
            # a cena volta a ter o que tinha antes: uma busca sem resultado não pode deixar um buraco no vídeo
            for c in faltando:
                midia_antiga, tipo_antigo, busca_antiga, rejeitadas, movidos = anteriores[c["n"]]
                for origem, destino in movidos:
                    if Path(origem).exists() and not Path(destino).exists():
                        shutil.move(origem, destino)
                c["midia"], c["tipo"], c["busca"], c["rejeitadas"] = midia_antiga, tipo_antigo, busca_antiga, rejeitadas
                c.pop("sem_midia_real", None)
            projeto.salvar_json("cenas.json", dados)
            termos = ", ".join(f"'{buscas_pedidas.get(c['n'], '')}'" for c in faltando)
            raise RuntimeError(f"Não achei foto ou vídeo no acervo para {termos}. Tente outros termos de busca, em inglês.")
        return []
    return gerar(projeto, apenas=set(numeros), log=log, conferir=False)


def _a_busca_da_pessoa_manda(cena, digitada, em_ingles):
    """A pessoa digitou o que quer ver: isso passa a ser o assunto da cena, para a busca, a escolha e o Jev.

    Antes só a busca mudava, e o resto continuava do agente: na cena 15 do ouro-da-serra-gaucha a pessoa pediu
    "frosted plant", o sujeito antigo "campos com geada" pôs Campo Mourão, Campos dos Goytacazes e Campo Grande na
    frente das fotos de geada, e o pedido "campos de uva da Serra Gaúcha" fez a planta com geada ser recusada.
    O pedido do agente fica guardado em pedido_original, na primeira troca."""
    cena.setdefault("pedido_original", {k: cena.get(k) for k in
                                        ("busca", "busca_alternativa", "sujeito", "mostrar", "exato", "animal")})
    cena["busca"] = em_ingles
    cena["busca_alternativa"] = digitada if digitada.strip().lower() != em_ingles.strip().lower() else ""
    cena["sujeito"] = em_ingles
    cena["mostrar"] = digitada
    cena["exato"] = ""
    # o bicho que o agente escolheu também sai: sem o exato, o filtro de espécie usa o campo animal, e a cena que o
    # agente marcou como "impala" só aceitava foto de impala mesmo com a pessoa buscando "leão" (três impalas
    # seguidas na cena 190 de um amigo). Quem confere se a foto mostra o que a pessoa pediu é o Jev
    cena["animal"] = ""
    cena["busca_manual"] = digitada


def _busca_da_cena(cena):
    from .cenas import _extrair_busca_do_prompt

    return _extrair_busca_do_prompt(cena.get("prompt_manual") or cena.get("prompt") or "", cena.get("texto", ""))


def _guardar_versao_antiga(projeto, cena, carimbo):
    """A versão anterior fica guardada caso a nova saia pior."""
    arquivos = [projeto.imagem(cena["n"])]
    if cena.get("midia"):
        arquivos.append(projeto.pasta / cena["midia"]["arquivo"])
        if cena["midia"].get("capa"):
            arquivos.append(projeto.pasta / cena["midia"]["capa"])
    movidos = []
    for arquivo in dict.fromkeys(arquivos):
        if arquivo.exists():
            destino = projeto.caminho("antigas", f"{arquivo.stem}-{carimbo}{arquivo.suffix}")
            shutil.move(arquivo, destino)
            movidos.append((str(destino), str(arquivo)))
    projeto.imagem(cena["n"]).with_suffix(".json").unlink(missing_ok=True)
    return movidos


def candidatos_personagem(perfil, quantidade, log=print):
    personagem = perfil.get("personagem") or {}
    if not personagem.get("descricao"):
        raise SystemExit("O perfil não tem personagem.descricao.")
    img = perfil.get("imagens") or {}
    prompt = (
        f"Head and shoulders portrait photograph of {personagem['descricao'].strip()} "
        "Facing the camera, eyes open, gentle neutral expression, even soft light, simple background.\n"
        f"Style: {(img.get('estilo') or '').strip()}"
    )
    nome = unicodedata.normalize("NFKD", personagem.get("nome", "personagem")).encode("ascii", "ignore").decode()
    pasta = RAIZ / "personagens" / "candidatos" / (re.sub(r"[^a-z0-9]+", "-", nome.lower()).strip("-") or "personagem")
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    log(f"  gerando {quantidade} rostos")

    if provedor(perfil) == "google":
        chave("GEMINI_API_KEY")
        with ThreadPoolExecutor(quantidade) as executor:
            imagens = list(executor.map(lambda _: _imagem_google(prompt, img, [], "1:1", "2K"), range(quantidade)))
    else:
        chave("FAL_KEY")
        argumentos = {**ARGUMENTOS_FAL, **(img.get("argumentos") or {})}
        argumentos.update({"prompt": prompt, "num_images": quantidade, "aspect_ratio": "1:1", "resolution": "2K"})
        resultado = fal_client.subscribe(img.get("modelo_fal", "fal-ai/nano-banana-2"), arguments=argumentos)
        imagens = [httpx.get(item["url"], timeout=120, follow_redirects=True).content for item in resultado["images"]]

    arquivos = []
    for i, dados in enumerate(imagens, 1):
        destino = pasta / f"{carimbo}-{i}.png"
        destino.write_bytes(dados)
        arquivos.append(destino)
    return pasta, arquivos


def gerar_revisao(projeto):
    cartoes = []
    for c in projeto.ler_json("cenas.json")["cenas"]:
        m = c.get("midia")
        if m:
            arquivo = projeto.pasta / (m.get("capa") or m["arquivo"])
            selo, classe = f"{'vídeo' if m['tipo'] == 'video' else 'foto'} real do {m['fonte']}", "real"
        else:
            arquivo = projeto.imagem(c["n"])
            selo, classe = "IA", "ia"
            if c.get("sem_midia_real"):
                selo += ", sem material real"
        if c["personagem"]:
            selo += " · personagem"
        versao = arquivo.stat().st_mtime_ns if arquivo.exists() else 0
        detalhes = ""
        if c.get("busca"):
            detalhes += f"<p><b>busca</b> {html.escape(c['busca'])}</p>"
        detalhes += f"<p><b>prompt</b> {html.escape(c.get('prompt_manual') or c['prompt'])}</p>"
        if m:
            detalhes += f'<p><b>fonte</b> <a href="{html.escape(m["pagina"])}">{html.escape(m.get("licenca") or "ver página")}</a></p>'
        texto_tela = c.get("texto_tela")
        if texto_tela:
            resumo = texto_tela.get("texto") or texto_tela.get("titulo") or ""
            if texto_tela["tipo"] == "lista":
                resumo = " · ".join([texto_tela.get("titulo", "")] + [i["texto"] for i in texto_tela["itens"]])
            detalhes += f"<p><b>texto na tela</b> {texto_tela['tipo']}, {html.escape(resumo)}</p>"
            selo += f" · texto {texto_tela['tipo']}"
        efeito = c.get("efeito")
        if efeito:
            detalhes += (f"<p><b>efeito</b> {html.escape(efeito['descricao'])}, {efeito['duracao']:.0f}s, "
                         f"na palavra {html.escape(efeito.get('palavra') or '')}</p>")
            selo += " · som"
        cartoes.append(
            f'<figure id="cena-{c["n"]}"><img loading="lazy" src="{arquivo.relative_to(projeto.pasta)}?v={versao}" alt="">'
            f'<figcaption><div class="topo"><b>{c["n"]}</b><span class="selo {classe}">{selo}</span>'
            f'<span>{mmss(c["ini"])} a {mmss(c["fim"])}</span></div>'
            f'<p>{html.escape(c["texto"])}</p><details><summary>detalhes</summary>{detalhes}</details></figcaption></figure>'
        )
    pagina = projeto.caminho("revisao.html")
    conteudo = (
        MODELO_REVISAO.replace("%%NOME%%", html.escape(projeto.nome))
        .replace("%%TOTAL%%", str(len(cartoes)))
        .replace("%%CARTOES%%", "\n".join(cartoes))
    )
    pagina.write_text(conteudo, encoding="utf-8")
    return pagina


MODELO_REVISAO = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revisão %%NOME%%</title>
<style>
  body { margin: 0; padding: 24px 16px; background: #121212; color: #e8e8e8; font: 15px/1.45 -apple-system, BlinkMacSystemFont, sans-serif; }
  header { max-width: 1400px; margin: 0 auto 20px; }
  h1 { margin: 0 0 6px; font-size: 22px; }
  header p { margin: 4px 0; color: #bdbdbd; }
  code { background: #262626; padding: 2px 6px; border-radius: 4px; color: #e8e8e8; }
  main { max-width: 1400px; margin: 0 auto; display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 18px; }
  figure { margin: 0; background: #1d1d1d; border-radius: 8px; overflow: hidden; }
  img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: #2a2a2a; }
  figcaption { padding: 10px 12px 12px; }
  .topo { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
  .topo span { color: #9a9a9a; font-size: 13px; }
  .selo { padding: 1px 8px; border-radius: 10px; font-size: 12px !important; }
  .selo.real { background: #1f4d3a; color: #a6e3c4 !important; }
  .selo.ia { background: #3b3350; color: #d6c7f7 !important; }
  figcaption p { margin: 6px 0 0; font-size: 14px; }
  details { margin-top: 8px; color: #c9b58a; font-size: 13px; }
  details p { font-size: 13px; }
  a { color: #8ab4f8; }
  summary { cursor: pointer; }
</style>
<header>
  <h1>%%NOME%%, %%TOTAL%% cenas</h1>
  <p>Outro candidato ou outra imagem <code>uv run fabrica refazer %%NOME%% 12 31</code></p>
  <p>Buscar material real com outros termos <code>uv run fabrica refazer %%NOME%% 12 --busca "qumran caves"</code></p>
  <p>Trocar por imagem de IA <code>uv run fabrica refazer %%NOME%% 12 --ia</code> ou <code>--prompt "nova descrição"</code></p>
  <p>Depois <code>uv run fabrica render %%NOME%%</code></p>
</header>
<main>
%%CARTOES%%
</main>
"""
