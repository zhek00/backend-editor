"""Fotos e vídeos reais para as cenas que pedem material real.

As fontes são legais e têm API.
Wikimedia Commons, sem chave, só com domínio público ou licença aberta.
Pexels e Pixabay, com chave grátis, liberados para uso comercial.

O trabalho acontece em três passos. Primeiro o sistema busca candidatos para cada cena.
Depois monta uma folha com as miniaturas numeradas e o Claude escolhe, várias cenas por vez.
Por fim baixa o escolhido, sem repetir o mesmo material em duas cenas.
Se nada servir, a cena passa a usar imagem de IA.
"""
import base64
import copy
import hashlib
import html
import io
import json
import os
import re
import threading
from pathlib import Path
from typing import Optional
import unicodedata
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import anthropic
import httpx

from . import claude_local
from .util import mmss

TIPOS_REAIS = ("foto_real", "video_real")

ESQUEMA_ESCOLHA = {
    "type": "object",
    "properties": {
        "cenas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "cena": {"type": "integer"},
                    "escolhas": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["cena", "escolhas"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cenas"],
    "additionalProperties": False,
}

# O que o modelo que VÊ a imagem entrega ao Jev, que só lê texto. Uma frase solta ("serpente marrom com a língua de
# fora") não dizia se era a espécie certa, se era foto ou desenho, nem se servia para o que a cena pede; quem sabe
# isso é quem vê a imagem, então ele responde campo a campo e, no fim, confere com o pedido da cena.
CAMPOS_DO_QUE_SE_VE = {
    "o_que_e": {"type": "string"},
    "certeza": {"type": "string", "enum": ["alta", "media", "baixa"]},
    "detalhes": {"type": "string"},
    "cenario": {"type": "string"},
    "acao": {"type": "string"},
    "tipo_imagem": {"type": "string", "enum": ["foto real", "quadro de video", "ilustracao", "render 3D",
                                               "mapa ou grafico", "outro"]},
    "texto_visivel": {"type": "string"},
    "epoca_aparente": {"type": "string", "enum": ["antiga", "atual", "indefinida"]},
    "confere": {"type": "string", "enum": ["sim", "parcial", "nao"]},
    "motivo": {"type": "string"},
}

INSTRUCOES_DO_QUE_SE_VE = """Para cada imagem, responda o que VOCÊ VÊ nela, campo a campo, em português:
- o_que_e: o sujeito principal. Dê o nome da espécie, do lugar ou do objeto só se reconhecer de verdade; senão, descreva a aparência ("cobra marrom de capuz aberto", não um palpite de espécie). NUNCA tire um nome do pedido: nome de pessoa, de lugar ou de obra só entra se estiver escrito na imagem (vá para texto_visivel) ou se for um monumento inconfundível. Pessoa nunca é identificada pelo rosto: diga "homem de uniforme militar", não o nome dele. Uma cidade no litoral não vira "Lago Vitória" porque o pedido fala do lago.
- certeza: alta, media ou baixa, sobre o que_e. Um nome errado dito com convicção estraga o julgamento.
- detalhes: as marcas que identificam o sujeito (capuz, faixas, chifres, formato, cor, estrutura), em até 15 palavras.
- cenario: onde está (floresta, sala, laboratório, rua, fundo branco de estúdio).
- acao: o que o sujeito faz, ou "parado".
- tipo_imagem: foto real, quadro de video, ilustracao, render 3D, mapa ou grafico, outro.
- texto_visivel: placas, legendas, logotipos ou marca d'água que aparecem, ou "nenhum".
- epoca_aparente: "antiga" se é foto antiga (preto e branco, sépia, desbotada), gravura, pintura ou ilustração de época, ou mostra roupas, veículos e construções do passado; "atual" se mostra roupas, carros, aparelhos, obras ou acabamentos de hoje, ou é foto digital moderna de gente e cidade; "indefinida" quando não dá para dizer (bicho, paisagem, céu).
- confere: compare a imagem com o que a cena deve mostrar (vem no pedido). "sim" se mostra exatamente aquilo; "parcial" se é do mesmo assunto mas falta algo (outra espécie parecida, sem a ação citada, espécie que não dá para confirmar); "nao" se é outra coisa.
- motivo: em até 15 palavras, por que confere ou não.
Descreva só o que aparece, sem inventar e sem copiar o texto do pedido."""


# a mesma descrição, sem comparar com o pedido: o Corrigir descreve sem mostrar o que a cena deveria ter (quem compara
# é o Jev). Vendo o pedido, o modelo escrevia o nome que estava nele ("Lago Vitória" para uma cidade no litoral)
CAMPOS_SEM_PEDIDO = {k: v for k, v in CAMPOS_DO_QUE_SE_VE.items() if k not in ("confere", "motivo")}
INSTRUCOES_SEM_PEDIDO = "\n".join(
    linha for linha in INSTRUCOES_DO_QUE_SE_VE.splitlines()
    if not linha.startswith(("- confere:", "- motivo:"))).replace(" e sem copiar o texto do pedido", "")


def compor_o_que_se_ve(v) -> str:
    """O texto que o Jev lê, montado dos campos. Aceita a frase antiga, de projetos e respostas de antes."""
    if not isinstance(v, dict):
        return str(v or "").strip()
    if not (v.get("o_que_e") or "").strip():
        return (v.get("frase") or v.get("legenda") or "").strip()
    partes = [f"O que é: {v['o_que_e'].strip()} (certeza {v.get('certeza') or 'media'})"]
    for rotulo, chave in (("Detalhes", "detalhes"), ("Cenário", "cenario"), ("Ação", "acao"),
                          ("Tipo de imagem", "tipo_imagem"), ("Texto visível", "texto_visivel"),
                          ("Época aparente", "epoca_aparente")):
        if (v.get(chave) or "").strip():
            partes.append(f"{rotulo}: {v[chave].strip()}")
    if (v.get("confere") or "").strip():
        partes.append(f"Quem viu a imagem diz que confere com o pedido: {v['confere']}"
                      + (f" ({v['motivo'].strip()})" if (v.get("motivo") or "").strip() else ""))
    return ". ".join(partes) + "."


def _esquema_escolha(com_descricao):
    """O esquema da escolha, com um campo a mais quando o modelo também descreve o que vê em cada candidato."""
    if not com_descricao:
        return ESQUEMA_ESCOLHA
    item = json.loads(json.dumps(ESQUEMA_ESCOLHA["properties"]["cenas"]["items"]))
    item["properties"]["vejo"] = {"type": "array", "items": {
        "type": "object",
        "properties": {"indice": {"type": "integer"}, **CAMPOS_DO_QUE_SE_VE},
        "required": ["indice", *CAMPOS_DO_QUE_SE_VE], "additionalProperties": False}}
    item["required"] = ["cena", "escolhas", "vejo"]
    esquema = json.loads(json.dumps(ESQUEMA_ESCOLHA))
    esquema["properties"]["cenas"]["items"] = item
    return esquema


INSTRUCOES_DESCRICAO = """
Em vejo, devolva um item para CADA número que você colocou em escolhas, com indice igual ao número, olhando só aquela miniatura (não confunda com a vizinha).
""" + INSTRUCOES_DO_QUE_SE_VE

INSTRUCOES_ESCOLHA = """Você escolhe fotos e vídeos reais para as cenas de um vídeo do canal {canal}.
Cada cena traz a narração, o que ela deveria mostrar e uma imagem com os candidatos numerados no canto.
Olhe a imagem de cada cena e liste em escolhas os números que remetem ao que a narração fala, do melhor para o pior.
O SUJEITO É OBRIGATÓRIO: animal, lugar, pessoa ou objeto citado pelo nome tem que ser aquele (outra espécie de cobra não serve para a naja). Só o que existe apenas como tipo genérico (o gráfico de um estudo, um documento, uma pessoa anônima) aceita uma imagem direta do mesmo tipo.
A AÇÃO E O CENÁRIO SÓ ORDENAM: ponha primeiro o candidato que mostra o sujeito fazendo o que a cena pede, mas um candidato com o sujeito certo em outra pose ou outro lugar (o crocodilo-do-nilo na margem, quando a cena pede ele na água) ENTRA NA LISTA, depois dos melhores. Uma foto boa do sujeito certo é sempre melhor do que nenhuma.
Deixe a lista vazia SÓ quando nenhum candidato mostra o sujeito: a fábrica busca de novo em vez de usar outra coisa.
Descarte candidatos com marca d'água, logotipos em destaque ou imagens que contradizem a narração.
Entre os que servem, dê preferência a imagens com impacto, luz forte e boa composição.
Um vídeo mais curto que a cena ainda serve, porque ele é desacelerado.
Responda todas as cenas recebidas, usando o número de cada cena."""


class FonteIndisponivel(Exception):
    pass


# parado é pior: um banco no limite por mais que isso fica de fora da busca, e os outros seguem na hora
ESPERA_CURTA_FONTE = 20
ESPERAS_QUEDA = (2, 5)  # segundos antes de tentar de novo um banco cuja conexão caiu
QUEDAS_PARA_PAUSAR = 3  # buscas seguidas com o banco caído, depois das tentativas, para ele ficar de fora um tempo
PAUSA_DEPOIS_DE_QUEDAS = 180  # segundos fora; depois ele volta sozinho


class LimiteAtingido(Exception):
    """A fonte devolveu 429. O Pexels libera 200 buscas por hora e o Pixabay 100 por minuto."""

    def __init__(self, fonte, segundos):
        super().__init__(f"limite de buscas do {fonte}")
        self.fonte = fonte
        self.segundos = segundos


def _captura_ligada(projeto) -> bool:
    """O Jev confere cada candidato pela descrição feita na própria escolha, antes de baixar (midia.conferir_na_captura)."""
    cfg = projeto.config.get("midia") or {}
    # o MiMo também descreve o que vê na mesma chamada; antes ele ficava de fora e a conferência desligava sozinha
    return bool(cfg.get("conferir_na_captura")) and cfg.get("escolha") in ("mimo", "groq", "gemini")


# (projeto, cena, candidato) -> julgamento que o Claude do cliente deu na própria escolha (projeto do MCP)
_JUIZOS_DO_CLIENTE: dict = {}


def _nota_do_candidato(projeto, cena, candidato, frase, vizinhas, log):
    """O julgamento do Jev para o que o candidato mostra ({nota, sujeito, epoca...}), ou None se ele não puder julgar.

    No projeto do MCP o Claude do cliente já julgou o candidato na própria escolha (_escolher_pelo_cliente): vale esse
    julgamento, sem outra tarefa."""
    from . import corrigir

    juizo = _JUIZOS_DO_CLIENTE.get((projeto.nome, cena["n"], _chave(candidato)))
    if juizo is not None:
        return corrigir.veredito(frase, juizo["nota"], juizo.get("sujeito"), juizo.get("epoca"), quem="o Claude do cliente")

    # o Jev também lê o que o autor escreveu sobre o arquivo, que vem do endereço da página
    cena_do_candidato = {**cena, "midia": {"pagina": candidato.get("pagina", "")}}
    try:
        resultado = corrigir._julgar_com_jev(projeto, cena_do_candidato, frase, vizinhas, log)
    except (RuntimeError, SystemExit) as erro:
        log(f"  o Jev não julgou um candidato da cena {cena['n']} ({str(erro)[:80]})")
        return None
    return resultado or None


NOTA_MINIMA_FIXA = 40  # abaixo disso a imagem não combina com a fala, em qualquer perfil e roteiro
NOTA_OUTRA_COISA = 15  # abaixo disso o juiz viu outra coisa (elefantes para "pé de elefante"): nunca fica no vídeo


def nota_minima_da_conferencia(projeto) -> int:
    """A nota que uma cena precisa para ficar como está. O config.yaml pode pedir mais, nunca menos."""
    return max(NOTA_MINIMA_FIXA, int((projeto.config.get("corrigir") or {}).get("nota_minima", NOTA_MINIMA_FIXA)))


def _escolher_conferindo(projeto, cena, ordem, candidatos_da_cena, frases, usados, vizinhas, log):
    """Percorre a ordem do modelo e devolve (candidato, dados da conferência) do primeiro que o Jev aprova.

    Sem descrição não há como julgar, então esse candidato passa como antes. Se nenhum dos testados for
    aprovado, fica o de maior nota, marcado como suspeito, porque uma cena sem material custa uma imagem de IA."""
    cfg = projeto.config.get("midia") or {}
    # regra fixa: a captura nunca aceita menos do que a conferência final aceita. Com a captura em 30 e a
    # conferência em 40, uma cobra no lugar do pangolim (nota 38) passava nas duas sem ninguém ver
    corte = max(cfg.get("nota_minima_captura", 50), nota_minima_da_conferencia(projeto))
    limite = cfg.get("candidatos_conferidos", 3)
    testados = []
    for i in ordem:
        candidato = candidatos_da_cena[i]
        if _chave(candidato) in usados:
            continue
        frase = (frases or {}).get(i)
        if not frase:
            return candidato, {"conferida": False}
        julgamento = _nota_do_candidato(projeto, cena, candidato, frase, vizinhas, log)
        if julgamento is None:
            return candidato, {"conferida": False, "legenda": frase}
        nota = julgamento["nota"]
        if nota >= corte:
            return candidato, {"conferida": True, "nota": nota, "legenda": frase, "reprovados_antes": len(testados)}
        testados.append((nota, i, frase, julgamento))
        if len(testados) >= limite:
            break
    if not testados:
        return None, {}
    # nenhum passou no juiz: o melhor só fica se for do assunto da cena (as tags citam o assunto). Nota baixa de
    # outra coisa nunca entra "porque era o melhor que havia": a cena vai para o tapa-buraco, que busca o assunto
    assunto = (exigido_da_cena({}, cena, nomes_do_roteiro(projeto))
               or _radicais(sujeito_da_busca(cena)))
    # e com nota de "na dúvida", não de outra coisa: uma manada de elefantes tem "elephant" nas tags, mas nota 2
    # para "pé de elefante" (a massa derretida no reator) quer dizer que o juiz viu outra coisa
    do_assunto = [t for t in testados if t[0] >= NOTA_OUTRA_COISA and _cita_o_assunto(assunto, candidatos_da_cena[t[1]])]
    # a mesma regra da conferência (corrigir.errada): sujeito certo com nota baixa é cena genérica e fica. As leoas
    # andando para "caçam em grupo, cercando a presa" tiravam nota baixa e a cena ia para a IA
    from .corrigir import errada
    do_assunto += [t for t in testados if t not in do_assunto and not errada(t[3])
                   and (t[3].get("sujeito") or 0) >= 60]
    if not do_assunto:
        return None, {}
    nota, i, frase, _ = max(do_assunto, key=lambda t: ((t[3].get("sujeito") or 0) >= 60, t[0]))
    return candidatos_da_cena[i], {"conferida": True, "nota": nota, "legenda": frase, "suspeita": True,
                                    "reprovados_antes": len(testados) - 1}


def _chaves_do_env(prefixo):
    """Todas as chaves de um banco no .env, em ordem: PEXELS_API_KEY, PEXELS_API_KEY1, PEXELS_API_KEY2...

    Sem teto de quantidade, em qualquer caixa, e sem repetir a mesma chave colada duas vezes."""
    achadas = []
    for nome, valor in os.environ.items():
        numero = re.fullmatch(prefixo + r"(\d*)", nome.strip().upper())
        if numero and valor.strip():
            achadas.append((int(numero.group(1) or 0), valor.strip()))
    return list(dict.fromkeys(valor for _, valor in sorted(achadas)))


def ia_ativa(projeto) -> bool:
    """ia.ativa no config.yaml. Desligada, o vídeo sai só com banco de imagens e nenhuma cena pede IA."""
    return bool((projeto.config.get("ia") or {}).get("ativa", True))


def precisa_ia(cena) -> bool:
    return cena.get("tipo", "ia") not in TIPOS_REAIS or bool(cena.get("sem_midia_real"))


# palavras de enquadramento e de estilo, que não dizem o que a cena mostra
_SO_ESTILO = {"close", "closeup", "macro", "detail", "view", "shot", "angle", "wide", "aerial", "dark", "dramatic",
              "cinematic", "footage", "video", "photo", "scene", "background", "with", "from", "that", "this",
              "lighting", "light", "slow", "motion", "real", "stock", "high", "very", "into", "over", "under"}


def _radicais(texto):
    """Palavras que dizem o que é a coisa, reduzidas às quatro primeiras letras para aceitar o plural."""
    palavras = re.findall(r"[a-z]{3,}", unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode())
    return {p[:4] for p in palavras if p not in _SO_ESTILO}


_PALAVRAS_DE_ESPACO = {"space", "galaxy", "galaxies", "nebula", "planet", "planets", "star", "stars", "asteroid",
                       "comet", "moon", "mars", "jupiter", "saturn", "orbit", "astronaut", "rocket", "satellite",
                       "cosmic", "universe", "telescope", "milky", "supernova", "magnetar", "pulsar", "quasar",
                       "spacecraft", "iss", "hubble", "webb", "solar", "eclipse", "meteor", "nasa"}


def _e_de_espaco(busca: str) -> bool:
    return bool(set(re.findall(r"[a-z]+", (busca or "").lower())) & _PALAVRAS_DE_ESPACO)


# palavras (em inglês, como a busca, e em português, como o "mostrar" do agente) de assunto de museu ou arquivo
_PALAVRAS_DE_ACERVO = {
    "painting", "paintings", "engraving", "etching", "lithograph", "woodcut", "manuscript", "ancient", "antique",
    "vintage", "historic", "historical", "history", "century", "medieval", "renaissance", "baroque", "museum",
    "artifact", "artifacts", "artefact", "archive", "archival", "fossil", "fossils", "specimen", "specimens",
    "skeleton", "taxidermy", "sculpture", "statue", "roman", "greek", "egyptian", "pharaoh", "aztec", "maya", "inca",
    "viking", "victorian", "colonial", "empire", "dynasty", "pottery", "relic", "daguerreotype", "illuminated",
    "pintura", "gravura", "manuscrito", "antigo", "antiga", "antigos", "antigas", "historico", "historica", "seculo",
    "medieval", "museu", "artefato", "artefatos", "fossil", "fosseis", "esqueleto", "especime", "escultura", "estatua",
    "romano", "romana", "grego", "grega", "egipcio", "egipcia", "farao", "imperio", "dinastia", "ceramica", "reliquia",
    "vitoriano", "colonial", "epoca", "extinct", "extinto", "extinta",
}

_PALAVRAS_DE_ACERVO_ANIMAL = {"fossil", "fossils", "skeleton", "specimen", "specimens", "taxidermy", "extinct",
                              "museum", "fosseis", "esqueleto", "especime", "extinto", "extinta", "museu", "taxidermia"}


def _e_de_acervo(cena) -> bool:
    """A cena pede material de museu ou arquivo: o agente mandou buscar na Wikimedia (lugar, artefato ou espécie
    pouco conhecida), a busca ou a descrição falam de história, arte ou acervo, ou citam um ano antes de 1950.

    Só nessas cenas os bancos de acervo (bancos.ACERVO) entram; nas outras eles só tomariam vagas com quadros."""
    if e_de_epoca(cena):
        return "epoca"  # só arquivo: Wikimedia e os bancos de acervo, nunca a foto moderna dos bancos de stock
    texto = " ".join(str(cena.get(c) or "") for c in ("busca", "busca_alternativa", "mostrar", "sujeito"))
    texto = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    palavras = set(re.findall(r"[a-z]+", texto))
    if cena.get("animal"):
        # bicho vivo é foto de campo (iNaturalist, Wikimedia), não quadro: o Harvard traria pintura de lince. Museu só
        # quando a cena fala do que só existe em acervo, como fóssil, esqueleto ou espécie extinta
        return bool(palavras & _PALAVRAS_DE_ACERVO_ANIMAL)
    if cena.get("fonte_sugerida") == "wikimedia" or palavras & _PALAVRAS_DE_ACERVO:
        return True
    return any(1000 <= int(a) < 1950 for a in re.findall(r"\b(1\d{3})s?\b", texto))


def e_de_epoca(cena) -> bool:
    """A cena mostra gente, roupa, construção, veículo, documento ou acontecimento do passado (campo epoca do agente,
    um ano antes de 1950). Só existe em material de arquivo: foto da época, gravura, ilustração de livro ou jornal,
    mapa antigo, objeto de museu. No virou-filme-em-1996 (Tsavo, 1898) os bancos de stock puseram obras modernas,
    estação de trem atual e homem de jaqueta com rifle no lugar do acampamento e da caçada."""
    return bool(re.search(r"\b1\d{3}\b", str(cena.get("epoca") or "")))


class _Todos(set):
    """Exigência em que a foto precisa citar todas as palavras, não uma delas (nome próprio composto)."""


def _cita_o_assunto(assunto, candidato) -> bool:
    """As tags ou a descrição do candidato citam alguma palavra do assunto ("ant" e "ants" contam iguais).
    Com _Todos, precisam citar todas."""
    descricao = _radicais(candidato.get("descricao") or "")
    bate = lambda a: any(a.startswith(d) or d.startswith(a) for d in descricao)
    if isinstance(assunto, _Todos):
        return bool(descricao) and bool(assunto) and all(bate(a) for a in assunto)
    return bool(descricao) and any(bate(a) for a in assunto)


def _cita_bastante(assunto, candidato) -> bool:
    """Como _cita_o_assunto, mas um assunto de três palavras ou mais precisa de duas delas nas tags. Uma só deixava
    passar qualquer coisa no tapa-buraco: "human bones dry savanna" aceitou um Mustang, "worker striking metal tin"
    latas de spray e "historical railway camp construction" a vista de uma cidade com igreja."""
    if isinstance(assunto, _Todos) or len(assunto or ()) < 3:
        return _cita_o_assunto(assunto, candidato)
    descricao = _radicais(candidato.get("descricao") or "")
    batem = sum(1 for a in assunto if any(a.startswith(d) or d.startswith(a) for d in descricao))
    return batem >= 2


# bichos que os bancos citam nas tags. Cena que não é de animal nunca recebe foto de bicho no tapa-buraco: o filtro
# "Tsavo" pôs elefante no acampamento, girafa nos "dois machos enormes" e galinha na conta das vítimas
_BICHOS = {
    "elephant", "zebra", "giraffe", "lion", "lioness", "tiger", "leopard", "cheetah", "jaguar", "puma", "cougar",
    "lynx", "antelope", "gazelle", "impala", "buffalo", "bison", "hippo", "hippopotamus", "rhino", "rhinoceros",
    "hyena", "jackal", "wildebeest", "warthog", "baboon", "gorilla", "chimpanzee", "orangutan", "camel", "horse",
    "pony", "donkey", "cow", "cows", "cattle", "ox", "goat", "sheep", "pig", "chicken", "hen", "rooster",
    "duck", "goose", "deer", "elk", "moose", "reindeer", "kangaroo", "koala", "panda", "vulture", "ostrich",
    "flamingo", "penguin", "pelican", "heron", "stork", "squirrel", "rabbit", "hare", "mouse", "rat", "hamster",
    "bear", "wolf", "fox", "dog", "puppy", "cat", "kitten", "monkey", "lemur", "snake", "lizard", "crocodile",
    "alligator", "turtle", "tortoise", "frog", "bird", "parrot", "eagle", "owl", "hawk", "falcon", "fish", "shark",
    "whale", "dolphin", "insect", "butterfly", "bee", "spider", "crab", "lobster",
}


def _bichos_citados(texto) -> set:
    palavras = re.findall(r"[a-z]+", unicodedata.normalize("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode())
    return {p.rstrip("s") if p.rstrip("s") in _BICHOS else p for p in palavras if p in _BICHOS or p.rstrip("s") in _BICHOS}


def _mostra_outro_bicho(cena, candidato) -> bool:
    """As tags do candidato citam um bicho que a cena não cita em nenhum dos campos em inglês do agente."""
    da_cena = _bichos_citados(" ".join(str(cena.get(c) or "") for c in (
        "busca", "busca_alternativa", "exato", "animal", "sujeito", "prompt", "item_citado")))
    return bool(_bichos_citados(candidato.get("descricao") or "") - da_cena)


def _cita_o_nome(nome, candidato) -> bool:
    """O nome inteiro, palavra por palavra, nas tags. Pelas 4 primeiras letras, "Patterson" aceitava "pattern"."""
    descricao = unicodedata.normalize("NFKD", (candidato.get("descricao") or "").lower()).encode("ascii", "ignore").decode()
    palavras = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", (nome or "").lower()).encode("ascii", "ignore").decode())
    return bool(palavras) and all(re.search(rf"\b{re.escape(p)}\b", descricao) for p in palavras)


def contexto_do_bloco(bloco: dict, busca: str) -> str:
    """A palavra que diz o que o assunto do bloco é, para uma busca ambígua não trazer outra coisa.

    "sugar glider" sozinho traz açúcar; "sugar glider marsupial" traz o bicho. Vem do campo contexto do mapa
    do agente (roteirista.completar_contexto preenche os mapas antigos). Só entra a palavra que a busca não tem,
    comparando pelo radical ("monkeys" já cobre "monkey")."""
    if not bloco:
        return ""
    ja_tem = _radicais(busca)
    palavras = re.findall(r"[a-zA-Z-]+", bloco.get("contexto") or "")
    return " ".join(p.lower() for p in palavras if not (_radicais(p) & ja_tem) and _radicais(p))


_FIM_DO_NUCLEO = {"on", "in", "at", "inside", "outside", "between", "with", "under", "over", "near", "from", "of",
                  "and", "or", "com", "dentro", "de", "em", "no", "na", "sobre", "entre", "numa", "num"}
_NUCLEO_GENERICO = {"silh", "pers", "peop", "hand", "woma", "mont", "scen", "grou", "coll", "vari", "seve", "many",
                    "larg", "smal", "youn", "adul", "baby", "like", "escu", "red", "blue", "whit", "blac", "gree",
                    "yell", "oran", "brow", "gray", "grey"}


def _assunto_do_bloco(bloco: dict) -> set:
    """Radicais do que o bloco é: o núcleo da âncora (antes da primeira preposição ou verbo em -ing, como
    "sugar glider marsupial" em "sugar glider marsupial gliding between trees") e o contexto."""
    nucleo = []
    for palavra in re.findall(r"[a-z]+", (bloco.get("ancora") or "").lower()):
        if palavra in _FIM_DO_NUCLEO or palavra.endswith("ing"):
            break
        nucleo.append(palavra)
    return (_radicais(" ".join(nucleo)) | _radicais(bloco.get("contexto") or "")) - _NUCLEO_GENERICO


# categorias que, no contexto do bloco, dizem que o assunto é um bicho. Animal é a única coisa que precisa ser
# exata: para coisas, lugares e ideias a imagem só remete, mas outro bicho no lugar do citado é gafe
_CATEGORIAS_ANIMAL = {
    "animal", "animals", "mammal", "marsupial", "bird", "birds", "parrot", "macaw", "owl", "eagle", "fish", "shark",
    "ray", "stingray", "eel", "snake", "serpent", "cobra", "viper", "lizard", "reptile", "turtle", "tortoise",
    "crocodile", "alligator", "amphibian", "frog", "toad", "salamander", "axolotl", "monkey", "primate", "ape",
    "lemur", "cat", "feline", "dog", "canine", "wolf", "bear", "rodent", "bat", "insect", "spider", "scorpion", "ant",
    "wasp", "bee", "hornet", "beetle", "caterpillar", "moth", "butterfly", "octopus", "squid", "jellyfish", "slug",
    "snail", "mollusk", "crab", "shrimp", "whale", "dolphin", "seal", "coati", "raccoon", "tardigrade", "wildlife",
    "species", "creature",
}
# palavras que não dizem QUAL é o animal (categoria, habitat, ação), e por isso não servem para conferir as tags:
# com "sea" valendo, qualquer foto de mar passaria como peixe-bolha
_CATEGORIAS_GERAIS = {"animal", "animals", "mammal", "marsupial", "bird", "birds", "fish", "reptile", "amphibian",
                      "insect", "primate", "rodent", "feline", "canine", "mollusk", "creature", "species", "wildlife",
                      "microanimal", "pet", "pets", "beast",
                      # adjetivos do nome comum: o bicho é "wolf" em "gray wolf" e "lynx" em "Eurasian lynx"
                      "gray", "grey", "common", "european", "eurasian", "american", "african", "asian", "giant",
                      "golden", "spotted", "wild", "northern", "southern", "great", "lesser", "little"}
_GENERICAS_ANIMAL = {p[:4] for p in _CATEGORIAS_GERAIS} | {
    "wild", "spec", "crea", "exot", "veno", "pois", "fres", "mari", "deep", "sea", "ocea", "wate", "rive", "lake",
    "fore", "tree", "bran", "grou", "land", "sand", "rock", "floo", "rain", "nigh", "ball", "micr", "hand", "cage",
    "home", "hous", "room", "zoo", "baby", "adul", "youn", "smal", "larg", "head", "face", "body", "full", "skin",
    "open", "mout", "jaws", "eyes", "tail", "legs", "swim", "walk", "roll", "eati", "hunt", "flyi", "sitt", "rest",
    "habi", "port", "habitat", "indo", "outd", "blue", "red", "pink", "gree", "blac", "whit", "brow", "yell"}


def _tipo_do_bicho(texto: str) -> set:
    """O tipo de bicho que a própria busca diz ("snake" em "cobra snake close up"). Os bancos descrevem as fotos
    pelo tipo ("a snake on the ground"), então exigir só o nome da espécie jogava fora dezenas de fotos boas;
    quem confere a espécie exata é o julgamento, que vê a foto descrita."""
    palavras = re.findall(r"[a-z]+", unicodedata.normalize("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode())
    return {p[:4] for p in palavras if p in _CATEGORIAS_ANIMAL and p not in _CATEGORIAS_GERAIS}


def bloco_de_animal(bloco: dict) -> bool:
    return bool(bloco) and bool(set(re.findall(r"[a-z]+", (bloco.get("contexto") or "").lower())) & _CATEGORIAS_ANIMAL)


def _generos_cientificos(texto: str) -> set:
    """O gênero do nome científico ("Daubentonia" em "Daubentonia madagascariensis"). Só o gênero: o epíteto
    ("madagascariensis", "atlanticus") deixaria passar uma paisagem de Madagascar ou o Atlântico."""
    return {genero.lower()[:4] for genero, epiteto in re.findall(r"\b([A-Z][a-z]{2,}) ([a-z]{3,})\b", texto or "")
            if re.search(r"(us|is|um|a|ae|i|ensis|oides|ops|ata|atus)$", epiteto)}


def _ordem_dos_radicais(texto: str) -> list:
    return [r[:4] for r in re.findall(r"[a-z]{3,}", unicodedata.normalize("NFKD", (texto or "").lower())
                                      .encode("ascii", "ignore").decode())]


# palavras em maiúscula na busca que não são nome de nada ("New", "Old", o começo de uma frase em inglês)
_NAO_E_NOME = {"new", "old", "great", "big", "small", "north", "south", "east", "west", "the", "a", "an", "ancient",
               "modern", "early", "late", "first", "last", "old", "young", "red", "blue", "green", "black", "white"}


_NOMES_DO_ROTEIRO = {}


def nomes_do_roteiro(projeto) -> set:
    """Nomes próprios do roteiro inteiro: palavra com maiúscula no meio da frase ("a cidade de Pripyat",
    "contadores Geiger"). Servem para reconhecer o nome mesmo quando a busca veio em minúscula."""
    chave = str(projeto.pasta)
    if chave not in _NOMES_DO_ROTEIRO:
        nomes = set()
        try:
            texto = projeto.roteiro()
        except (Exception, SystemExit):
            texto = ""
        for frase in re.split(r"[.!?\n]\s*", texto):
            nomes |= set(re.findall(r"(?<=\s)([A-ZÁÉÍÓÚÂÊÔÃÕ][\wÀ-ÿ'-]{3,})", frase))
        _NOMES_DO_ROTEIRO[chave] = nomes
    return _NOMES_DO_ROTEIRO[chave]


def assunto_do_video(projeto) -> str:
    """O nome próprio mais citado no roteiro ("Chernobyl"): a última camada do assunto, depois da coisa exata,
    do sujeito e do bloco. Uma foto de Chernobyl é do assunto num vídeo sobre Chernobyl; um elefante nunca é."""
    try:
        texto = projeto.roteiro()
    except (Exception, SystemExit):
        return ""
    # nome de pessoa nunca é o assunto: "Patterson" (o caçador dos leões de Tsavo) trouxe a cidade de Patterson em
    # Ohio, uma estação de trem, uma ginasta e fichas de soldados americanos para 20 cenas do virou-filme-em-1996
    pessoas = set()
    try:
        if projeto.existe("roteiro_mapa.json"):
            for pessoa in projeto.ler_json("roteiro_mapa.json").get("pessoas_reais") or []:
                pessoas |= {p.lower() for p in re.findall(r"[\wÀ-ÿ'-]+", str(pessoa))}
    except (OSError, ValueError):
        pass
    contagem = {}
    for nome in nomes_do_roteiro(projeto):
        if nome.lower() not in pessoas:
            contagem[nome] = len(re.findall(rf"\b{re.escape(nome)}\b", texto))
    return max(contagem, key=contagem.get) if contagem else ""


def nome_proprio_da_cena(cena: dict, nomes_roteiro=()) -> set:
    """O nome próprio que identifica a cena (Pripyat, Chernobyl, Geiger), se a busca cita um.

    É como o animal: tem que ser exato. "Pripyat evacuated empty street" não pode virar qualquer rua vazia só
    porque as tags dizem "empty street". Vale o nome em maiúscula na busca, ou um nome próprio do roteiro que
    a busca cita (mesmo em minúscula); fica o mais longo, que é o mais específico."""
    busca = cena.get("busca") or ""
    na_busca = {r for r in _radicais(busca)}
    candidatos = re.findall(r"\b([A-Z][A-Za-z'-]{3,})", busca) + list(nomes_roteiro)
    # na narração, maiúscula no meio da frase é nome ("a cidade de Pripyat", "contadores Geiger")
    for frase in re.split(r"[.!?]\s+", cena.get("texto") or ""):
        candidatos += re.findall(r"(?<=\s)([A-ZÁÉÍÓÚÂÊÔÃÕ][\wÀ-ÿ'-]{3,})", frase)
    nomes = []
    for n in candidatos:
        normal = unicodedata.normalize("NFKD", n.lower()).encode("ascii", "ignore").decode()
        if normal in _NAO_E_NOME or len(normal) < 4 or normal[:4] not in na_busca:
            continue
        nomes.append(normal)
    if not nomes:
        return set()
    return {max(nomes, key=len)[:4]}


def _identificador(exato: str) -> set:
    """A palavra do campo exato que uma foto precisa citar: o nome próprio ("Geiger" em "Geiger counter",
    "Confinement" em "New Safe Confinement") ou, sem maiúscula, o substantivo principal ("camera" em "trail
    camera"). Adjetivos ("Eurasian", "gray") e palavras vazias ("New") não identificam nada."""
    palavras = re.findall(r"[A-Za-zÀ-ÿ'-]{3,}", exato or "")
    # palavra que _radicais tira das tags (_SO_ESTILO) nunca é exigida: "Stock" em "New York Stock Exchange" não
    # existia em tag nenhuma, e todas as fotos da bolsa caíam no filtro (cena 35 do mcp-cafe-5min)
    uteis = [p for p in palavras if unicodedata.normalize("NFKD", p.lower()).encode("ascii", "ignore").decode()
             not in _NAO_E_NOME | _CATEGORIAS_GERAIS | _SO_ESTILO]
    if not uteis:
        return set()
    normal = lambda p: unicodedata.normalize("NFKD", p.lower()).encode("ascii", "ignore").decode()[:4]
    maiusculas = [p for p in uteis if p[0].isupper()]
    if len(maiusculas) > 1:
        # nome composto ("Chernobyl Elephant's Foot"): a foto cita TODAS as palavras, senão um elefante passaria
        return _Todos(normal(p) for p in maiusculas)
    minusculas = [p for p in uteis if not p[0].isupper()]
    if maiusculas and minusculas:
        # um nome e a coisa ("Tsavo railway workers camp", "Geiger counter"): a foto cita os dois. Só o nome deixava
        # passar qualquer foto do lugar (elefante e jipe de safari de Tsavo no lugar do acampamento)
        return _Todos({normal(maiusculas[0]), normal(minusculas[-1])})
    return {normal(maiusculas[0] if maiusculas else uteis[-1])}


def exigido_da_cena(bloco: dict, cena: dict, nomes_roteiro=()) -> set:
    """O que uma foto precisa citar nas tags para ser da cena.

    Com o campo exato (o agente diz o que a foto obrigatoriamente mostra), vale ele, mais o tipo do bicho e o
    gênero científico quando é animal. Sem o campo (projeto antigo), a fábrica deduz o animal ou o nome próprio."""
    if "exato" in cena:
        exato = (cena.get("exato") or "").strip()
        if _parece_portugues(exato):
            exato = ""  # "Palácio de Westminster": os bancos descrevem em inglês e nenhuma foto passaria
        animal = animal_da_cena(bloco, cena)
        if not exato:
            return animal  # o agente disse que qualquer representação direta serve
        if animal and not _generos_cientificos(exato):
            # cena de animal: o bicho é obrigatório. Somado ao nome do lugar ("Tsavo" de "Tsavo lion"), qualquer
            # um dos dois bastava, e zebra, elefante e gazela de Tsavo passaram por leão
            return animal
        exigido = _identificador(exato)
        if cena.get("animal"):
            exigido = set(exigido) | animal
        if re.fullmatch(r"[A-Z][a-z]+ [a-z]+", exato) and (_generos_cientificos(exato) or not cena.get("animal")):
            # nome científico ("Naja haje"): os bancos descrevem a foto pelo nome comum ("cobra", "snake"), então
            # vale também o nome comum da busca e o tipo do bicho; a espécie exata quem confere é o juiz
            comum = [r for r in _ordem_dos_radicais(f"{cena.get('sujeito') or ''} {cena.get('busca') or ''}")
                     if r not in _GENERICAS_ANIMAL]
            exigido = set(exigido) | set(comum[:1]) | _tipo_do_bicho(f"{cena.get('sujeito') or ''} {cena.get('busca') or ''}")
        return exigido
    return animal_da_cena(bloco, cena) or nome_proprio_da_cena(cena, nomes_roteiro)


def _cabeca_do_animal(nome: str) -> list:
    """A palavra que diz QUE bicho é: o substantivo, a última palavra do nome comum em inglês ("lion" em "maneless
    Tsavo lion", "cobra" em "spectacled cobra", "frog" em "glass frog").

    Antes valia a primeira palavra, e com qualquer palavra bastando, o lugar ("Tsavo") e o adjetivo ("maneless",
    "plains", "glass") deixavam passar zebra de Tsavo, leão com juba e paisagem de planície. Nome com maiúscula no meio
    de um nome comum é lugar ou gentílico, e palavra em -less é adjetivo; a espécie exata quem confere é o juiz."""
    palavras = re.findall(r"[A-Za-zÀ-ÿ]{3,}", nome)
    tem_minuscula = any(p[0].islower() for p in palavras)
    uteis = []
    for p in palavras:
        normal = unicodedata.normalize("NFKD", p.lower()).encode("ascii", "ignore").decode()
        if (tem_minuscula and p[0].isupper()) or normal.endswith("less") or normal[:4] in _GENERICAS_ANIMAL:
            continue
        uteis.append(normal[:4])
    if not uteis and palavras:
        # nada sobrou ("Komodo" sozinho): vale a última palavra, para a cena não deixar de ser de animal
        uteis = [unicodedata.normalize("NFKD", palavras[-1].lower()).encode("ascii", "ignore").decode()[:4]]
    return uteis[-1:]


def animal_da_cena(bloco: dict, cena: dict) -> set:
    """Palavras que uma foto precisa citar para ser do animal da cena; vazio se a cena não é de animal.

    Vale o nome da espécie (a palavra que a identifica: "glass" em "glass frog"), o tipo do bicho ("snake" para
    uma cobra, porque os bancos descrevem as fotos assim) e o gênero do nome científico da busca alternativa.
    O código só barra o bicho de outro tipo (gato no lugar do pangolim); a espécie exata o julgamento confere."""
    bloco = bloco or {}
    if "animal" in cena:
        # o agente disse qual é o bicho (ou que não é cena de animal): vale o que ele disse, sem adivinhar
        nome = (cena.get("animal") or "").strip()
        if not nome:
            return set()
        cabeca = _cabeca_do_animal(nome)
    else:
        # projeto antigo: adivinha pelo bloco. Só é cena de animal a que fala do bicho do bloco
        if not bloco_de_animal(bloco):
            return set()
        busca = f"{cena.get('sujeito') or ''} {cena.get('busca') or ''}"
        do_bloco = (_radicais(busca) & _assunto_do_bloco(bloco)) - _GENERICAS_ANIMAL
        if not do_bloco:
            return set()
        cabeca = [next(r for r in _ordem_dos_radicais(busca) if r in do_bloco)]
        nome = busca
    tipo = _tipo_do_bicho(f"{nome} {cena.get('busca') or ''} {bloco.get('contexto') or ''}")
    return set(cabeca) | tipo | _generos_cientificos(cena.get("busca_alternativa") or "")


_PALAVRAS_PT = {"de", "da", "do", "das", "dos", "na", "no", "nas", "nos", "com", "em", "um", "uma", "e", "ao", "aos",
                "pela", "pelo", "sobre", "entre", "para"}
_TRADUCOES = {}


def _parece_portugues(texto: str) -> bool:
    """Acento, palavra de ligação ou terminação do português ("fogo de chão", "lince euroasiático")."""
    texto = (texto or "").lower()
    palavras = re.findall(r"[a-zà-ÿ]+", texto)
    return bool(re.search(r"[ãõçáéíóúâêôà]", texto) or set(palavras) & _PALAVRAS_PT
                or any(p.endswith(("ção", "ções", "ões")) for p in palavras))


def sujeito_da_busca(cena) -> str:
    """O assunto da cena em inglês, a língua das tags e descrições dos bancos.

    O agente escreve o sujeito em português em boa parte das cenas (62 de 217 no ouro-da-serra-gaucha), e ele era
    usado para ordenar, filtrar e buscar: "fogo de chão" marcou como fora do assunto as 6 fotos de fogueira (as tags
    dizem "fire", "hearth") e, buscado na Wikimedia, "fogo" trouxe a ilha vulcânica do Fogo, em Cabo Verde; "campos
    com geada" pôs Campo Mourão na frente das fotos de geada. Sujeito em português cede lugar à busca, que o agente
    sempre escreve em inglês."""
    sujeito = (cena.get("sujeito") or "").strip()
    if sujeito and not _parece_portugues(sujeito):
        # português sem acento nem palavra de ligação ("tranca quebrada") passava por inglês, e "quebrada" trouxe o
        # cânion Quebrada de las Conchas. Sujeito que não divide nenhuma palavra com os campos em inglês da cena cede
        ingles = _radicais(" ".join(str(cena.get(c) or "") for c in ("busca", "busca_alternativa", "prompt", "exato", "animal")))
        if not ingles or _radicais(sujeito) & ingles:
            return sujeito
    return (cena.get("busca") or "").strip() or sujeito


def busca_em_ingles(projeto, termo: str, log=print) -> str:
    """O termo que a pessoa digitou, em inglês, a língua em que os bancos indexam as fotos.

    "geada na grama" no Pexels sem idioma trazia um piquenique; em inglês vêm as fotos de geada. Quem traduz é o
    modelo principal (hoje gratuito), uma vez por termo. Termo que já parece inglês, ou falha do modelo, volta igual."""
    termo = (termo or "").strip()
    if not termo or projeto.offline:
        return termo
    palavras = re.findall(r"[a-zà-ÿ]+", termo.lower())
    if not (re.search(r"[ãõçáéíóúâêôà]", termo.lower()) or set(palavras) & _PALAVRAS_PT
            or any(p.endswith(("ção", "ções", "ões", "inho", "inha")) for p in palavras) or len(palavras) <= 2):
        return termo  # frase de três palavras ou mais, sem nada de português: já está em inglês
    if termo.lower() in _TRADUCOES:
        return _TRADUCOES[termo.lower()]
    from . import openrouter_local

    esquema = {"type": "object", "properties": {"ingles": {"type": "string"}}, "required": ["ingles"],
               "additionalProperties": False}
    try:
        resposta = openrouter_local.perguntar(
            projeto, "traduzir busca", "Você traduz termos de busca de banco de imagens para o inglês. Responda só o "
            "JSON pedido. Se o termo já estiver em inglês, devolva igual. Mantenha nomes próprios. De 1 a 5 palavras, "
            "substantivos concretos, como alguém digitaria no Pexels.",
            f"Termo: {termo}", esquema, log=log, modelo=openrouter_local.principal(projeto), temperatura=0)
        ingles = re.sub(r"\s+", " ", str(resposta.get("ingles") or "")).strip()[:80]
    except (Exception, SystemExit) as erro:
        log(f"  não consegui traduzir '{termo}' ({str(erro)[:80]}), buscando como foi escrito")
        return termo
    if ingles:
        _TRADUCOES[termo.lower()] = ingles
        if ingles.lower() != termo.lower():
            log(f"  busca '{termo}' em inglês: '{ingles}'")
    return ingles or termo


def busca_com_contexto(bloco: dict, busca: str) -> str:
    """Junta o contexto do bloco só quando a busca fala do assunto do bloco.

    Uma cena que fala de outra coisa dentro do bloco (a caixa de soro no bloco da naja, uma gaiola no bloco
    do celular) fica como está."""
    busca = (busca or "").strip()
    if not busca or not bloco:
        return busca
    if not (_radicais(busca) & _assunto_do_bloco(bloco)):
        return busca
    extra = contexto_do_bloco(bloco, busca)
    return f"{busca} {extra}" if extra else busca


def _so_do_animal(cena, animal, candidatos, log=print):
    """Cena de animal: só fica o candidato cujas tags ou título citam o próprio animal. Sem devolver todos se
    nenhum citar, como no filtro geral: aí a busca segue para a Wikimedia, para o nome científico e para a
    âncora, e um bicho qualquer nunca entra no lugar do citado."""
    ficam = [c for c in candidatos if _cita_o_assunto(animal, c)]
    if len(ficam) < len(candidatos):
        log(f"  cena {cena['n']}: {len(candidatos) - len(ficam)} candidato(s) sem o animal nas tags "
            f"({cena.get('sujeito') or cena.get('busca')})")
    return ficam


def _so_do_assunto(cena, candidatos, log=print):
    """Tira os candidatos cujas tags ou descrição não têm relação nenhuma com o assunto da cena.

    Uma busca frouxa devolve o parente mais próximo (uma vespa para "lonomia caterpillar", uma aranha para
    "fire ants"), e um modelo barato de visão às vezes o aceita. As tags do Pixabay e o texto do Pexels e do
    Wikimedia já dizem o que a foto é, então quem não cita nenhuma palavra do assunto sai antes da escolha.
    """
    assunto = _radicais(sujeito_da_busca(cena))
    if not assunto or not candidatos:
        return candidatos
    # sem descrição não há como julgar, fica para o modelo
    ficam = [c for c in candidatos if not (c.get("descricao") or "").strip() or _cita_o_assunto(assunto, c)]
    if not ficam:
        # nenhum candidato cita o assunto nas tags: em vez de deixar a cena vazia, quem olha a imagem decide,
        # porque a foto pode remeter ao assunto mesmo sem as palavras certas na descrição
        return candidatos
    if len(ficam) < len(candidatos):
        log(f"  cena {cena['n']}: {len(candidatos) - len(ficam)} candidato(s) fora do assunto ({sujeito_da_busca(cena)})")
    return ficam


def pendente(cena) -> bool:
    return cena.get("tipo") in TIPOS_REAIS and not cena.get("midia") and not cena.get("sem_midia_real")


def buscar(projeto, apenas=None, log=print, permissivo=False):
    _buscar(projeto, apenas, log, permissivo)
    if apenas is None and not permissivo:
        # o projeto inteiro: as cenas que o agente marcou "não existe" ganham uma busca antes de virar imagem de IA
        try:
            tentar_banco_nas_nao_existe(projeto, log)
        except (Exception, SystemExit) as erro:
            # é uma economia, nunca para o vídeo: as cenas seguem para a IA como o agente decidiu
            log(f"  a busca nas cenas marcadas como inexistentes falhou, seguem para a IA: {str(erro)[:120]}")


def tentar_banco_nas_nao_existe(projeto, log=print) -> list:
    """As cenas que o agente marcou "não existe" (ninguém fotografou) passam por uma busca no acervo antes da IA.

    O agente erra para os dois lados: no natureza-nos-ensina marcou 13 de 92 cenas assim, entre elas um elefante
    derrubando uma árvore, que os bancos têm. Como ele achou que não existe, a regra é estrita: só fica a foto que o
    Jev aprovou antes de baixar, com a nota mínima e sem suspeita; o resto volta para a IA. Cada cena é tentada uma
    vez (banco_tentado). Devolve as cenas que ficaram com material real."""
    if projeto.offline or not ia_ativa(projeto):
        return []  # sem IA, cenas.py já devolve essas cenas ao acervo
    dados = projeto.ler_json("cenas.json")
    alvo = [c for c in dados["cenas"]
            if c.get("onde_existe") == "nao_existe" and c.get("tipo") == "ia" and not c.get("banco_tentado")
            and not c.get("personagem") and not c.get("prompt_manual") and not c.get("imagem_da_pessoa")
            and (c.get("busca_reserva") or "").strip() and not projeto.imagem(c["n"]).exists()]
    if not alvo:
        return []
    for c in alvo:
        c["banco_tentado"] = True
        c["tipo"], c["busca"] = "foto_real", c["busca_reserva"].strip()
        c.pop("sem_midia_real", None)
    projeto.salvar_json("cenas.json", dados)
    numeros = {c["n"] for c in alvo}
    log(f"  {len(alvo)} cena(s) que o agente marcou como inexistentes no acervo: uma busca antes da IA")
    try:
        _buscar(projeto, numeros, log, False)
    finally:
        aceitas = _so_as_aprovadas(projeto, numeros, log)
    return aceitas


def _so_as_aprovadas(projeto, numeros, log) -> list:
    """Das cenas "não existe" que passaram pela busca, só fica a foto aprovada pelo Jev; as outras voltam para a IA."""
    minima = nota_minima_da_conferencia(projeto)
    dados = projeto.ler_json("cenas.json")
    aceitas = []
    for c in dados["cenas"]:
        if c["n"] not in numeros:
            continue
        cap = c.get("captura") or {}
        if c.get("midia") and cap.get("conferida") and not cap.get("suspeita") and (cap.get("nota") or 0) >= minima:
            aceitas.append(c["n"])
            continue
        m = c.pop("midia", None) or {}
        for campo in ("arquivo", "capa"):
            if m.get(campo):
                (projeto.pasta / m[campo]).unlink(missing_ok=True)
        if m.get("fonte") and m.get("id"):
            c.setdefault("rejeitadas", []).append(f"{m['fonte']}:{m['id']}")
        c["tipo"], c["busca"] = "ia", ""
        c.pop("sem_midia_real", None)
        c.pop("captura", None)
    projeto.salvar_json("cenas.json", dados)
    log(f"  {len(aceitas)} de {len(numeros)} cena(s) marcadas como inexistentes acharam foto aprovada no acervo"
        + (f": {', '.join(map(str, sorted(aceitas)))}" if aceitas else "; seguem para a IA"))
    return aceitas


def _buscar(projeto, apenas=None, log=print, permissivo=False):
    dados = projeto.ler_json("cenas.json")
    alvo = [c for c in dados["cenas"] if pendente(c) and (apenas is None or c["n"] in apenas)]
    if not alvo:
        log("  nenhuma cena esperando material real")
        return
    geral = projeto.config.get("midia") or {}
    buscador = Buscador(projeto, log)

    # 1. candidatos de cada cena, já com a segunda leva: a mesma busca traz o dobro, sem pedido a mais aos bancos.
    # O modelo vê os 12 primeiros; se ele (ou o Jev) recusar todos, vê os 12 seguintes antes de a cena ir para a IA
    leva = buscador.quantidade
    buscador.quantidade = leva * 2
    with ThreadPoolExecutor(geral.get("processos", 4)) as executor:
        candidatos = dict(zip((c["n"] for c in alvo), executor.map(lambda c: _candidatos_da_cena(buscador, c), alvo)))
    buscador.quantidade = leva
    for c in alvo:
        animal = exigido_da_cena(buscador.blocos.get(c.get("bloco")), c, buscador.nomes)
        candidatos[c["n"]] = (_so_do_animal(c, animal, candidatos[c["n"]], log) if animal
                              else _so_do_assunto(c, candidatos[c["n"]], log))
    segunda_leva = {}
    for c in alvo:
        todos = candidatos[c["n"]]
        candidatos[c["n"]], segunda_leva[c["n"]] = todos[:leva], todos[leva:]
    com_opcoes = [c for c in alvo if candidatos[c["n"]]]
    log(f"  candidatos encontrados para {len(com_opcoes)} de {len(alvo)} cenas")

    # 2 e 3. escolha e download juntos, lote a lote: o que já foi decidido é baixado e gravado na
    # hora, então uma interrupção no meio (cota diária do modelo, queda de rede) não perde o que
    # já estava pronto — o mesmo comando depois continua só do que falta
    por_n = {c["n"]: c for c in alvo}
    usados = {_chave(c["midia"]) for c in dados["cenas"] if c.get("midia")}
    falhas_de_download, decididas = set(), set()
    conferir = _captura_ligada(projeto) and not permissivo and not projeto.offline
    descricoes = {}  # n -> {número do candidato: frase do que o modelo viu nele}
    vizinhas = {c["n"]: c.get("texto", "") for c in dados["cenas"]}
    infos = {}
    recusou_tudo = set()  # cenas em que o modelo recusou todos e entraram os candidatos do assunto pelas tags
    adiadas, na_segunda = set(), set()  # cenas que recusaram a primeira leva, e as que já viram a segunda
    contagem = {"conferidas": 0, "reprovados": 0, "suspeitas": 0}

    def aplicar(ordens_parciais):
        """Baixa o material escolhido dessas cenas, sem repetir o de outra, e grava o cenas.json."""
        escolhidos = {}
        for n, ordem in ordens_parciais.items():
            decididas.add(n)
            if not ordem and not permissivo and segunda_leva.get(n) and n not in na_segunda and not projeto.offline:
                # o modelo recusou os 12 primeiros: antes de cair nas tags, ele vê os 12 seguintes
                adiadas.add(n)
                decididas.discard(n)
                continue
            if not ordem and not permissivo:
                ordem = _do_assunto_quando_recusou(projeto, por_n[n], candidatos[n])
                if ordem:
                    recusou_tudo.add(n)
            if permissivo:
                # a pessoa escolheu os termos: depois dos preferidos do modelo, o resto do que a busca achou vale mais do
                # que nada (a escolha dele pode ter caído em imagens já usadas em outra cena), e ela decide olhando
                ordem = list(ordem) + [i for i in range(len(candidatos[n])) if i not in ordem]
            if conferir and descricoes.get(n):
                candidato, info = _escolher_conferindo(projeto, por_n[n], ordem, candidatos[n], descricoes[n],
                                                       usados, vizinhas, log)
                if candidato is not None:
                    usados.add(_chave(candidato))
                    escolhidos[n] = candidato
                    infos[n] = info
                    if info.get("conferida"):
                        contagem["conferidas"] += 1
                        contagem["reprovados"] += info.get("reprovados_antes", 0)
                    contagem["suspeitas"] += 1 if info.get("suspeita") else 0
                elif segunda_leva.get(n) and n not in na_segunda and not projeto.offline:
                    # o Jev reprovou os escolhidos da primeira leva: a cena vê a segunda
                    adiadas.add(n)
                    decididas.discard(n)
                continue
            for i in ordem:
                candidato = candidatos[n][i]
                if _chave(candidato) not in usados:
                    usados.add(_chave(candidato))
                    escolhidos[n] = candidato
                    if n in recusou_tudo:
                        # ninguém viu essa imagem ainda: a conferência depois do download julga
                        infos[n] = {"conferida": False, "suspeita": True, "recusada_pelo_escolhedor": True}
                    break
        if not escolhidos:
            return
        with ThreadPoolExecutor(geral.get("processos", 4)) as executor:
            futuros = {executor.submit(_baixar_midia, projeto, por_n[n], esc, buscador.http): n
                       for n, esc in escolhidos.items()}
            for futuro in as_completed(futuros):
                n = futuros[futuro]
                try:
                    por_n[n]["midia"] = futuro.result()
                    if infos.get(n):
                        por_n[n]["captura"] = infos[n]
                except ImagemRepetida as erro:
                    # jamais repetir: a cena fica sem mídia e o tapa-buraco busca outra imagem do assunto
                    log(f"  cena {n}: recusada porque {erro}; buscando outra")
                except (httpx.HTTPError, OSError, ValueError) as erro:
                    falhas_de_download.add(n)
                    log(f"  cena {n} não conseguiu baixar o material. {str(erro)[:150]}")
        projeto.salvar_json("cenas.json", dados)

    if projeto.offline:
        aplicar({c["n"]: list(range(len(candidatos[c["n"]]))) for c in com_opcoes})
    else:
        with ThreadPoolExecutor(geral.get("processos", 4)) as executor:
            folhas = dict(zip((c["n"] for c in com_opcoes),
                              executor.map(lambda c: _folha_de_contato(projeto, c, candidatos[c["n"]], buscador.http), com_opcoes)))
        tamanho = geral.get("cenas_por_escolha", 6)
        lotes = [com_opcoes[i:i + tamanho] for i in range(0, len(com_opcoes), tamanho)]
        log(f"  a escolha será feita em {len(lotes)} rodada(s)")
        # lotes de escolha ao mesmo tempo. Quem escolhe é o modelo principal (gratuito); o claude.processos antigo
        # (2) deixava a troca de narração do zz_teste_animacoes buscando 138 cenas a menos de 2 por minuto
        processos = geral.get("escolhas_ao_mesmo_tempo") or (projeto.config.get("claude") or {}).get("processos", 2)
        # um lote que falha (cota do modelo, rede) não derruba os outros: cada um é tratado à parte,
        # e os que já estavam decididos em cache continuam sendo baixados
        interrupcao = None
        with ThreadPoolExecutor(processos) as executor:
            futuros = [executor.submit(_escolher_lote, projeto, lote, candidatos, folhas, descricoes if conferir else None)
                       for lote in lotes]
            for futuro in futuros:
                try:
                    aplicar(futuro.result())
                except BaseException as erro:
                    interrupcao = interrupcao or erro
        if interrupcao is not None:
            prontas = sum(1 for c in alvo if c.get("midia"))
            log(f"  {prontas} de {len(alvo)} cena(s) baixadas e gravadas antes da interrupção")
            raise interrupcao

    if adiadas and not projeto.offline:
        _segunda_leva(projeto, [por_n[n] for n in sorted(adiadas)], candidatos, segunda_leva, na_segunda,
                      buscador, descricoes if conferir else None, aplicar, log)

    if not projeto.offline and not ia_ativa(projeto):
        # sem IA, uma cena vazia vira buraco no vídeo: melhor uma imagem na dúvida do que nenhuma
        _preencher_vazias(projeto, dados, alvo, candidatos, buscador, usados, falhas_de_download, log, descricoes)

    encontrados, sem_resposta = 0, 0
    for cena in alvo:
        if cena.get("midia"):
            encontrados += 1
        elif cena["n"] in falhas_de_download:
            # o download falhou, o que costuma ser passageiro: a cena continua pendente
            sem_resposta += 1
        elif cena["n"] in decididas or not candidatos[cena["n"]]:
            # ou o modelo olhou e não gostou de nenhum, ou a busca não achou nada: vale imagem de IA
            cena["sem_midia_real"] = True
        else:
            # a escolha falhou, então a cena continua pendente e a próxima rodada tenta de novo
            sem_resposta += 1
    projeto.salvar_json("cenas.json", dados)
    if conferir and contagem["conferidas"]:
        log(f"  Jev conferiu {contagem['conferidas']} cena(s) antes de baixar: {contagem['reprovados']} candidato(s) "
            f"reprovados e trocados pelo próximo, {contagem['suspeitas']} cena(s) ficaram com o melhor que havia, sob suspeita")
    log(f"  {encontrados} cenas com material real, {len(alvo) - encontrados - sem_resposta} vão usar imagem de IA")
    if sem_resposta:
        log(f"  {sem_resposta} cena(s) ficaram pendentes por falha de escolha, de miniatura ou de download. Rode o mesmo comando de novo para tentar outra vez")
    escrever_creditos(projeto)


def _segunda_leva(projeto, cenas, candidatos, segunda_leva, na_segunda, buscador, descricoes, aplicar, log):
    """As cenas que recusaram os 12 primeiros candidatos veem os 12 seguintes, que a mesma busca já trouxe.

    Os 12 seguintes ficam na frente da lista da cena (os números da imagem de candidatos são deles) e os primeiros
    atrás, para o filtro pelas tags olhar os 24 se o modelo recusar de novo. A escolha e a imagem de candidatos da
    segunda leva ficam em arquivos próprios (_2), sem apagar os da primeira."""
    for c in cenas:
        na_segunda.add(c["n"])
    log(f"  {len(cenas)} cena(s) sem nada aproveitável nos 12 primeiros candidatos: mostrando os 12 seguintes")
    folhas = {}
    for c in cenas:
        folhas[c["n"]] = _folha_de_contato(projeto, c, segunda_leva[c["n"]], buscador.http, sufixo="_2")
        candidatos[c["n"]] = segunda_leva[c["n"]] + candidatos[c["n"]]
    tamanho = (projeto.config.get("midia") or {}).get("cenas_por_escolha", 6)
    for i in range(0, len(cenas), tamanho):
        try:
            aplicar(_escolher_lote(projeto, cenas[i:i + tamanho], candidatos, folhas, descricoes, sufixo="_2"))
        except Exception as erro:
            # a segunda leva melhora a captura, nunca a para: a cena segue para as tags ou para a IA
            log(f"  a segunda leva de candidatos falhou para {len(cenas[i:i + tamanho])} cena(s): {str(erro)[:120]}")


def _do_assunto_quando_recusou(projeto, cena, candidatos_da_cena) -> list:
    """O modelo que escolhe recusou todos os candidatos: os que citam o assunto da cena nas tags, na ordem da busca.

    No natureza-nos-ensina ele recusou 11 fotos boas de crocodilo-do-nilo porque nenhuma era "imóvel na água,
    só olhos e narinas", e 22 cenas foram para a IA sem ninguém julgar. Esses candidatos seguem para a conferência
    do Jev depois do download, como suspeitos; nenhum entra sem citar o assunto (o animal, o nome exato)."""
    assunto = exigido_da_cena({}, cena, nomes_do_roteiro(projeto)) or _radicais(sujeito_da_busca(cena))
    if not assunto:
        return []
    return [i for i, c in enumerate(candidatos_da_cena) if _cita_o_assunto(assunto, c)]


def _preencher_vazias(projeto, dados, alvo, candidatos, buscador, usados, falhas_de_download, log, descricoes=None):
    """Garante material em toda cena quando a IA está desligada, do melhor para o pior:

    1. um candidato ainda não usado da própria cena cujas tags citam o assunto dela ou do bloco. Candidato que
       não cita o assunto nunca entra às cegas: era assim que um trem ou um morango caíam no lugar de um animal;
    2. uma busca mais ampla pela âncora do bloco no mapa do agente e pelo sujeito com o contexto do bloco,
       também só com candidatos que citam o assunto;
    3. a mídia da cena vizinha mais próxima, de preferência do mesmo bloco.
    Toda cena preenchida assim fica marcada como suspeita, para aparecer na revisão do editor."""
    blocos = buscador.blocos
    principal = assunto_do_video(projeto)
    vazias = [c for c in alvo if not c.get("midia") and c["n"] not in falhas_de_download]
    if not vazias:
        return
    por_candidato = por_busca = por_vizinha = 0
    for cena in vazias:
        bloco = blocos.get(cena.get("bloco")) or {}
        assunto = _radicais(sujeito_da_busca(cena))
        do_bloco = _assunto_do_bloco(bloco) if bloco else set()
        animal = animal_da_cena(bloco, cena)
        exigido = exigido_da_cena(bloco, cena, buscador.nomes)
        acervo = _e_de_acervo(cena)

        # cena de animal ou de nome próprio: só entra foto que cita o próprio bicho ou o próprio nome. Nas outras,
        # o assunto com duas palavras, e nunca um bicho que a cena não cita
        def cita(x, exigido=exigido, assunto=assunto, do_bloco=do_bloco, animal=animal, cena=cena):
            if not animal and _mostra_outro_bicho(cena, x):
                return False
            if exigido:
                return _cita_o_assunto(exigido, x)
            return _cita_bastante(assunto, x) or _cita_bastante(do_bloco, x)

        # o modelo que escolhe olhou estes candidatos; o que ele descreveu como "não confere" fica de fora (o elefante
        # da cena 3 do virou-filme-em-1996 foi recusado por ele e posto no vídeo pelo tapa-buraco)
        recusados = {i for i, frase in ((descricoes or {}).get(cena["n"]) or {}).items() if _disse_que_nao(frase)}
        opcoes = [x for i, x in enumerate(candidatos.get(cena["n"]) or [])
                  if i not in recusados and _chave(x) not in usados and cita(x)]
        origem = "candidato não escolhido, do assunto"
        if not opcoes:
            tipo = "foto" if acervo == "epoca" or cena["tipo"] != "video_real" else "video"
            curta = " ".join(sujeito_da_busca(cena).split()[:2])
            # antes de repetir a vizinha, a busca da própria cena com uma página bem maior: bicho que aparece em
            # muitas cenas (o petauro em 25 cenas) esgota os 8 candidatos de cada busca, mas o banco tem dezenas
            normal = buscador.quantidade
            buscador.quantidade = max(normal, 30)
            # todos os nomes do MESMO assunto, do mais exato ao mais amplo: nunca outra coisa para tapar o buraco
            termos = [cena.get("exato") or "", cena.get("busca") or "", cena.get("busca_alternativa") or "",
                      cena.get("animal") or "",
                      sujeito_da_busca(cena), busca_com_contexto(bloco, curta), bloco.get("ancora", "")]
            if not animal:
                # coisa, lugar ou ideia: o sujeito em uma palavra e o contexto do bloco ainda são o mesmo assunto;
                # para bicho não, porque "snake" traria outra cobra
                termos += [" ".join(sujeito_da_busca(cena).split()[:1]), bloco.get("contexto", "")]
            vistos = set()
            try:
                for termo in termos:
                    if termo.strip().lower() in vistos:
                        continue
                    vistos.add(termo.strip().lower())
                    if termo.strip():
                        opcoes = [x for x in buscador._das_fontes(tipo, termo.strip(), acervo=acervo)
                                  or buscador._das_fontes("foto", termo.strip(), acervo=acervo)
                                  if _chave(x) not in usados and cita(x)]
                        if opcoes:
                            origem = f"busca ampla '{termo.strip()}'"
                            break
                if not opcoes and principal:
                    # 4ª camada: o assunto do vídeo inteiro ("Chernobyl"). Sem foto do corium, a do reator de
                    # Chernobyl é do assunto; um elefante nunca seria. O nome inteiro, palavra por palavra, e o bicho
                    # da cena continua obrigatório
                    for termo in (f"{principal} {bloco.get('ancora', '')}", f"{principal} {curta}", principal):
                        opcoes = [x for x in buscador._das_fontes("foto", termo.strip(), "wikimedia", acervo)
                                  if _chave(x) not in usados
                                  and _serve_pelo_assunto_do_video(cena, x, principal, animal, exigido)]
                        if opcoes:
                            origem = f"assunto do vídeo '{termo.strip()}'"
                            break
            finally:
                buscador.quantidade = normal
        for candidato in opcoes[:3]:
            try:
                cena["midia"] = _baixar_midia(projeto, cena, candidato, buscador.http)
            except (httpx.HTTPError, OSError, ValueError):
                continue
            usados.add(_chave(candidato))
            cena["captura"] = {**(cena.get("captura") or {}), "suspeita": True, "preenchida": origem}
            cena.pop("sem_midia_real", None)
            if origem.startswith("candidato não escolhido"):
                por_candidato += 1
            else:
                por_busca += 1
            break
    # último recurso: uma imagem NOVA pelo assunto do bloco e do vídeo, nunca a cópia de outra cena. Repetir a
    # mesma imagem em várias cenas deixava o vídeo com cara de pobre (19 repetidas no lince2)
    for cena in vazias:
        if cena.get("midia"):
            continue
        bloco = blocos.get(cena.get("bloco")) or {}
        ancora = bloco.get("ancora", "")
        animal = animal_da_cena(bloco, cena)
        exigido = exigido_da_cena(bloco, cena, buscador.nomes)
        do_bloco = _assunto_do_bloco(bloco) if bloco else set()
        termos = [f"{principal} {ancora}".strip(), ancora, bloco.get("contexto", ""), principal]
        opcoes, origem = [], ""
        for termo in dict.fromkeys(t.strip() for t in termos if t and t.strip()):
            # nunca às cegas: o primeiro resultado da busca "Patterson" era uma ginasta, uma rodovia ou uma placa de
            # estação. Só entra o que cita o assunto do vídeo ou o do bloco, sem bicho que a cena não cita
            opcoes = [x for x in buscador._das_fontes("foto", termo, "wikimedia", _e_de_acervo(cena))
                      if _chave(x) not in usados
                      and (_serve_pelo_assunto_do_video(cena, x, principal, animal, exigido)
                           or (_cita_bastante(do_bloco, x) and (not exigido or _cita_o_assunto(exigido, x))
                               and (not animal or _cita_o_assunto(animal, x))
                               and (animal or not _mostra_outro_bicho(cena, x))))]
            if opcoes:
                origem = f"imagem nova pelo assunto '{termo}'"
                break
        for candidato in opcoes[:3]:
            try:
                cena["midia"] = _baixar_midia(projeto, cena, candidato, buscador.http)
            except (httpx.HTTPError, OSError, ValueError):
                continue
            usados.add(_chave(candidato))
            cena["captura"] = {**(cena.get("captura") or {}), "suspeita": True, "preenchida": origem}
            cena.pop("sem_midia_real", None)
            por_vizinha += 1
            break
        if not cena.get("midia"):
            log(f"  cena {cena['n']}: nenhuma imagem nova do assunto em nenhum banco; fica para a revisão "
                f"({cena.get('sujeito') or cena.get('busca')})")
    projeto.salvar_json("cenas.json", dados)
    log(f"  cenas preenchidas para o vídeo não ter buraco: {por_candidato} com um candidato não escolhido, "
        f"{por_busca} por uma busca mais ampla, {por_vizinha} por uma imagem nova do assunto do bloco ou do vídeo "
        "(todas marcadas como suspeitas; nenhuma repetida)")


def _disse_que_nao(frase) -> bool:
    """O modelo que viu o candidato disse que ele não confere com o pedido da cena."""
    if isinstance(frase, dict):
        return frase.get("confere") == "nao"
    return bool(re.search(r"confere com o pedido: n[aã]o\b", str(frase or "")))


def _serve_pelo_assunto_do_video(cena, candidato, principal, animal, exigido=None) -> bool:
    """A última camada do tapa-buraco: cita o assunto do vídeo pelo nome inteiro, o bicho da cena se ela for de
    animal, o que a cena exige (o exato) e nenhum bicho que a cena não cita.

    Sem o exato, a cena 35 do mcp-cafe-5min ("a bolsa de Nova York", exato "New York Stock Exchange") recebeu o túnel
    da Mantiqueira só porque ele cita o assunto do vídeo: é outra coisa, e a cena vazia vai para a revisão."""
    if not principal or not _cita_o_nome(principal, candidato):
        return False
    if exigido and not _cita_o_assunto(exigido, candidato):
        return False
    if animal:
        return _cita_o_assunto(animal, candidato)
    return not _mostra_outro_bicho(cena, candidato)


def _candidatos_da_cena(buscador, cena):
    rejeitadas = set(cena.get("rejeitadas", []))
    return [c for c in buscador.candidatos(cena) if _chave(c) not in rejeitadas]


class Buscador:
    def __init__(self, projeto, log):
        self.projeto = projeto
        self.cfg = projeto.perfil.get("midia_real") or {}
        self.log = log
        geral = projeto.config.get("midia") or {}
        # o Wikimedia só aceita pedidos que dizem quem está buscando
        self.contato = str(geral.get("contato") or "").strip()
        agente = f"FabricaVideos/0.1 ({self.contato})" if self.contato else "FabricaVideos/0.1"
        self.http = httpx.Client(headers={"User-Agent": agente}, timeout=60, follow_redirects=True)
        self.quantidade = geral.get("candidatos", 8)
        self.espera_maxima = float(geral.get("espera_maxima", 3600))
        self.desligadas = set()
        self.bloqueada_ate = {}
        self.quedas = {}  # fonte -> quedas seguidas (conexão caiu, 5xx) depois das tentativas
        # várias chaves por banco: revezam a cada busca, e uma chave no limite ou recusada sai da vez
        self.chave_bloqueada_ate = {}
        self.chaves_recusadas = set()
        self.proxima_chave = {}
        self.trava = threading.Lock()
        # os blocos do mapa do agente: a âncora e o contexto de cada assunto desambiguam as buscas
        self.nomes = nomes_do_roteiro(projeto)
        self.blocos = {}
        if projeto.existe("roteiro_mapa.json"):
            if not projeto.offline:
                from . import roteirista
                try:
                    roteirista.completar_contexto(projeto, log=log)
                except (Exception, SystemExit) as erro:
                    # sem o contexto a busca só fica menos precisa, então nunca para a fábrica por isso
                    log(f"  não consegui completar o contexto dos blocos ({str(erro)[:100]}), buscando sem ele")
            self.blocos = {b["id"]: b for b in projeto.ler_json("roteiro_mapa.json").get("blocos", [])}

    def candidatos(self, cena):
        # vídeo de banco é sempre de hoje: cena de época busca foto de arquivo
        tipo = "video" if cena["tipo"] == "video_real" and not e_de_epoca(cena) else "foto"
        # o agente marca "wikimedia" quando o assunto é um lugar ou objeto específico, que os bancos de stock não têm
        preferida = "wikimedia" if cena.get("fonte_sugerida") == "wikimedia" else None
        # do mais exato para o mais amplo: a busca da cena com o contexto do bloco ("sugar glider marsupial", para não
        # vir açúcar), a busca sozinha, a alternativa do agente e o assunto em duas palavras, também com o contexto.
        # A imagem só precisa remeter ao que é falado, então uma busca mais geral é melhor que uma cena vazia
        bloco = self.blocos.get(cena.get("bloco"))
        animal = exigido_da_cena(bloco, cena, self.nomes)
        if animal and tipo == "foto":
            # espécie: o iNaturalist, que indexa pelo nome comum e científico; lugar ou objeto com nome próprio: a
            # Wikimedia. Pexels e Pixabay quase não têm nenhum dos dois
            preferida = "inaturalist" if animal_da_cena(bloco, cena) else "wikimedia"
        curta = " ".join(sujeito_da_busca(cena).split()[:2])
        assunto = animal or (_radicais(sujeito_da_busca(cena)) - _SO_ESTILO)
        especie = set(_cabeca_do_animal(cena.get("animal") or "")) if animal_da_cena(bloco, cena) else set()
        acervo = _e_de_acervo(cena)
        # o que a foto obrigatoriamente mostra vem primeiro como BUSCA, não só como filtro: a cena 11 do
        # aparte2-2min-v2 exigia "Instituto Butantan", buscava "antivenom vials corridor" e descartava tudo
        exato = (cena.get("exato") or "").strip()
        # o exato dentro de uma busca maior também é buscado sozinho, logo depois dela: a cena 35 do mcp-cafe-5min
        # buscava "New York stock exchange screen", a Wikimedia não achava nada com "screen", e o exato "New York
        # Stock Exchange" (40 fotos lá) nunca era buscado. Os 24 candidatos caíram no filtro e entrou um túnel de trem
        contido = bool(exato) and exato.lower() in cena["busca"].lower()
        tentativas = [exato if exato and not contido else "",
                      busca_com_contexto(bloco, cena["busca"]), cena["busca"], exato if contido else "",
                      busca_com_contexto(bloco, cena.get("busca_alternativa") or ""),
                      busca_com_contexto(bloco, curta)]
        vistas = set()
        achados = []
        for busca in tentativas:
            busca = busca.strip()
            if not busca or busca.lower() in vistas:
                continue
            vistas.add(busca.lower())
            novos = self._das_fontes(tipo, busca, preferida, acervo)
            # em cena de animal vale a própria espécie: "snake" nas tags de vídeos de píton e de cobra-do-milho
            # passava por mamba-negra, e a foto da mamba nunca era procurada
            if tipo == "video" and not [n for n in novos if _cita_o_assunto(especie or assunto, n)]:
                # nenhum vídeo do assunto: coisa com nome próprio (o Novo Confinamento Seguro, o "pé de elefante")
                # só existe em foto, e quase sempre na Wikimedia, que a busca de vídeo não consulta
                # espécie: o iNaturalist, que tem foto de quase todo bicho (a mamba-negra do natureza-nos-ensina não
                # existe em vídeo no Pexels nem no Pixabay, e a Wikimedia não achava nada pela busca da cena)
                foto_de = "inaturalist" if animal_da_cena(bloco, cena) else "wikimedia"
                novos = novos + self._das_fontes("foto", busca, foto_de, acervo)
            # soma em vez de trocar: os achados da busca mais exata ficam na frente e não se perdem
            ja = {_chave(a) for a in achados}
            achados += [n for n in novos if _chave(n) not in ja]
            # só para de procurar com 3 candidatos que citam o assunto (o próprio animal, se for bicho)
            uteis = [a for a in achados if _cita_o_assunto(assunto, a)]
            if len(uteis) >= 3:
                break
        # os que citam o assunto vão na frente, para não ficarem de fora do corte da quantidade
        # e quem cita a própria espécie vem antes de quem cita só o tipo do bicho ("mamba" antes de "snake")
        achados.sort(key=lambda a: (bool(especie) and not _cita_o_assunto(especie, a), not _cita_o_assunto(assunto, a)))
        return achados[:self.quantidade]

    def _das_fontes(self, tipo, busca, preferida=None, acervo=False):
        """Busca em todos os bancos do perfil AO MESMO TEMPO e intercala os resultados (o 1º de cada banco, depois o
        2º de cada...). Antes a lista era cortada na ordem dos bancos, e com vários bancos só os primeiros entravam.

        Bancos especializados só onde fazem sentido: o iNaturalist (o melhor para espécies) vem primeiro em cena de
        animal, a NASA só entra em cena de espaço (senão "cobra" traria o helicóptero AH-1 Cobra) e os bancos de
        acervo (Harvard, Europeana, Smithsonian, NYPL, Te Papa) só em cena de acervo. No lince2 o Harvard trouxe
        4.303 candidatos, quase todos quadros, e só 1 entrou no vídeo: nas cenas comuns ele só tomava vaga."""
        from . import bancos

        padrao = ["pexels", "pixabay"] if tipo == "video" else ["wikimedia", "pexels", "pixabay"]
        if acervo == "epoca":
            tipo = "foto"  # cena de época: vídeo de banco é sempre de hoje
        fontes = list(self.cfg.get("fontes_video" if tipo == "video" else "fontes_foto") or padrao)
        if not acervo:
            fontes = [f for f in fontes if f not in bancos.ACERVO]
        elif acervo == "epoca":
            # Pexels, Pixabay e Unsplash só têm foto de hoje: a cena de época busca no arquivo e na Wikimedia, também
            # pelas categorias do assunto (o acervo inteiro dele, como as fotos de um livro da época)
            fontes = ["wikimedia", "wikimedia_categoria"] + [f for f in fontes if f in bancos.ACERVO and f != "wikimedia"]
        if tipo == "foto":
            if _e_de_espaco(busca) and "nasa" not in fontes:
                fontes.append("nasa")
            elif not _e_de_espaco(busca):
                fontes = [f for f in fontes if f != "nasa"]
            if preferida != "inaturalist":
                fontes = [f for f in fontes if f != "inaturalist"]
            if preferida:
                fontes = [preferida] + [f for f in fontes if f != preferida]
        with ThreadPoolExecutor(max(1, len(fontes))) as executor:
            por_fonte = list(executor.map(lambda f: self._buscar(f, tipo, busca), fontes))
        # a fonte preferida entra com o dobro de vagas: duas dela a cada rodada
        achados, rodada = [], 0
        while len(achados) < self.quantidade and any(rodada < len(lista) for lista in por_fonte) or (
                len(achados) < self.quantidade and preferida and por_fonte and rodada * 2 < len(por_fonte[0])):
            for i, lista in enumerate(por_fonte):
                vezes = 2 if (i == 0 and preferida and tipo == "foto") else 1
                for k in range(vezes):
                    j = rodada * vezes + k
                    if j < len(lista):
                        achados.append(lista[j])
            rodada += 1
        return achados[:self.quantidade]

    def _buscar(self, fonte, tipo, busca):
        if not busca or fonte in self.desligadas:
            return []
        from . import bancos
        funcoes = {"wikimedia": self._wikimedia, "wikimedia_categoria": self._wikimedia_categoria,
                   "pexels": self._pexels, "pixabay": self._pixabay,
                   # os bancos extras (iNaturalist, NASA, Unsplash, Smithsonian, Europeana, Harvard)
                   **{nome: (lambda t, b, _f=funcao: _f(self, t, b)) for nome, funcao in bancos.FONTES.items()}}
        if fonte not in funcoes:
            raise SystemExit(f"Fonte desconhecida no perfil: {fonte}")
        codigo = hashlib.sha1(f"{fonte}|{tipo}|{busca}".encode()).hexdigest()[:16]
        cache = self.projeto.caminho("midia", "buscas", f"{codigo}.json")
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        for tentativa in range(3):
            if not self._aguardar(fonte):
                # a fonte está no limite por mais tempo que vale esperar: esta busca segue com os outros bancos,
                # sem gravar o cache vazio, e a fonte volta a ser usada sozinha quando o limite dela liberar
                return []
            try:
                achados = funcoes[fonte](tipo, busca)
                break
            except LimiteAtingido as limite:
                if tentativa == 2:
                    return []
                with self.trava:
                    ate = time.time() + limite.segundos
                    if ate > self.bloqueada_ate.get(fonte, 0) + 5:
                        self.bloqueada_ate[fonte] = ate
                        acao = (f"esperando {mmss(limite.segundos)}" if limite.segundos <= ESPERA_CURTA_FONTE
                                else f"seguindo com os outros bancos até ele liberar ({mmss(limite.segundos)})")
                        self.log(f"  o {fonte} atingiu o limite de buscas, {acao}")
            except FonteIndisponivel as motivo:
                self._desligar(fonte, str(motivo))
                return []
            except httpx.HTTPError as erro:
                # queda passageira (conexão caiu, demorou demais, erro 5xx do banco): tenta de novo em segundos.
                # Antes desistia na hora, e o iNaturalist ficou de fora justo nas buscas da mamba e do búfalo
                passageira = isinstance(erro, httpx.TransportError) or (
                    isinstance(erro, httpx.HTTPStatusError) and erro.response.status_code >= 500)
                if passageira and tentativa < 2:
                    time.sleep(ESPERAS_QUEDA[tentativa])
                    continue
                self.log(f"  busca no {fonte} falhou para '{busca}'. {str(erro)[:120]}")
                if passageira:
                    self._caiu(fonte)
                return []
            except (ValueError, KeyError) as erro:
                self.log(f"  busca no {fonte} falhou para '{busca}'. {str(erro)[:120]}")
                return []
        with self.trava:
            self.quedas.pop(fonte, None)
        cache.write_text(json.dumps(achados, ensure_ascii=False), encoding="utf-8")
        return achados

    def _caiu(self, fonte):
        """O banco caiu de novo depois das tentativas. Três vezes seguidas: fica de fora um tempo e volta sozinho,
        para as outras buscas não perderem segundos esperando um banco fora do ar."""
        with self.trava:
            self.quedas[fonte] = self.quedas.get(fonte, 0) + 1
            if self.quedas[fonte] < QUEDAS_PARA_PAUSAR:
                return
            self.quedas[fonte] = 0
            self.bloqueada_ate[fonte] = time.time() + PAUSA_DEPOIS_DE_QUEDAS
        self.log(f"  o {fonte} caiu {QUEDAS_PARA_PAUSAR} vezes seguidas: fica de fora por "
                 f"{mmss(PAUSA_DEPOIS_DE_QUEDAS)} e volta sozinho")

    def _aguardar(self, fonte) -> bool:
        """Espera só limites curtos (o Pixabay libera a cada minuto). Devolve False se não vale esperar."""
        falta = self.bloqueada_ate.get(fonte, 0) - time.time()
        if falta > ESPERA_CURTA_FONTE:
            return False
        if falta > 0:
            time.sleep(falta)
        return True

    def _desligar(self, fonte, motivo):
        with self.trava:
            if fonte not in self.desligadas:
                self.desligadas.add(fonte)
                self.log(f"  {fonte} fora desta rodada, {motivo}")

    def _checar(self, resposta, nome):
        if resposta.status_code in (401, 403):
            if nome == "Wikimedia":
                raise FonteIndisponivel("o Wikimedia bloqueou o acesso, confira midia.contato no config.yaml")
            raise FonteIndisponivel(f"a chave do {nome} foi recusada")
        if resposta.status_code == 429:
            raise LimiteAtingido(nome, _segundos_ate_liberar(resposta))
        resposta.raise_for_status()

    def _pedir_com_chaves(self, nome, prefixo, pedir):
        """Faz a busca com a próxima chave livre do banco. Com 429 ou chave recusada, tenta a seguinte na hora.

        Só avisa o limite (e a fábrica espera) quando todas as chaves estão no limite ao mesmo tempo."""
        chaves = _chaves_do_env(prefixo)
        if not chaves:
            raise FonteIndisponivel(f"falta {prefixo} no .env")
        with self.trava:
            inicio = self.proxima_chave.get(nome, 0)
            self.proxima_chave[nome] = inicio + 1  # revezamento: cada busca começa por uma chave diferente
        espera = None
        for passo in range(len(chaves)):
            numero = (inicio + passo) % len(chaves)
            chave = chaves[numero]
            if chave in self.chaves_recusadas:
                continue
            falta = self.chave_bloqueada_ate.get(chave, 0) - time.time()
            if falta > 0:
                espera = falta if espera is None else min(espera, falta)
                continue
            r = pedir(chave)
            rotulo = prefixo + (str(numero) if numero else "")
            if r.status_code in (401, 403):
                with self.trava:
                    if chave not in self.chaves_recusadas:
                        self.chaves_recusadas.add(chave)
                        self.log(f"  a chave {rotulo} do {nome} foi recusada, usando as outras")
                continue
            if r.status_code == 429:
                segundos = _segundos_ate_liberar(r)
                with self.trava:
                    self.chave_bloqueada_ate[chave] = time.time() + segundos
                espera = segundos if espera is None else min(espera, segundos)
                continue
            return r
        if all(c in self.chaves_recusadas for c in chaves):
            raise FonteIndisponivel(f"todas as chaves do {nome} foram recusadas")
        raise LimiteAtingido(nome, espera or 60)

    def _wikimedia(self, tipo, busca):
        if tipo != "foto":
            return []
        if not self.contato:
            raise FonteIndisponivel("falta seu e-mail ou site em midia.contato no config.yaml, exigência do Wikimedia")
        r = self.http.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
            "gsrsearch": f"{busca} filetype:bitmap", "gsrlimit": 40,
            "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1920,
            "iiextmetadatafilter": "License|LicenseShortName|Artist|ImageDescription",
        })
        self._checar(r, "Wikimedia")
        return self._paginas_wikimedia(r)

    def _wikimedia_categoria(self, tipo, busca):
        """As fotos das categorias da Wikimedia que o assunto tem, só em cena de época. A busca por palavra acha o
        arquivo que cita a palavra; a categoria junta o acervo inteiro do assunto: "The Man-eaters of Tsavo" tem as
        fotos do livro de 1907 (acampamento, ponte, armadilha, os leões mortos), e a fábrica achou só uma delas."""
        if tipo != "foto" or not self.contato:
            return []
        r = self.http.get("https://commons.wikimedia.org/w/api.php", params={
            "action": "query", "format": "json", "list": "search", "srnamespace": 14, "srsearch": busca, "srlimit": 2})
        self._checar(r, "Wikimedia")
        categorias = [c["title"] for c in (r.json().get("query") or {}).get("search", [])]
        achados = []
        for categoria in categorias:
            r = self.http.get("https://commons.wikimedia.org/w/api.php", params={
                "action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": categoria,
                "gcmtype": "file", "gcmlimit": 50,
                "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1920,
                "iiextmetadatafilter": "License|LicenseShortName|Artist|ImageDescription",
            })
            self._checar(r, "Wikimedia")
            achados += [a for a in self._paginas_wikimedia(r) if a["id"] not in {x["id"] for x in achados}]
        return achados

    def _paginas_wikimedia(self, r):
        paginas = sorted(((r.json().get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 0))
        achados = []
        for p in paginas:
            info = (p.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            if info.get("mime") not in ("image/jpeg", "image/png") or info.get("width", 0) < 900:
                continue
            if not self._licenca_aceita(_texto(meta.get("License")).lower()):
                continue
            arquivo = info.get("thumburl") or info["url"]
            achados.append({
                "fonte": "wikimedia", "id": str(p["pageid"]), "tipo": "foto",
                "miniatura": re.sub(r"/\d+px-", "/500px-", arquivo) if "/thumb/" in arquivo else arquivo,
                "arquivo": arquivo,
                "duracao": None,
                "pagina": info.get("descriptionurl", ""),
                "autor": _texto(meta.get("Artist"))[:120],
                "licenca": _texto(meta.get("LicenseShortName")),
                "descricao": (p.get("title", "").removeprefix("File:") + ". " + _texto(meta.get("ImageDescription")))[:300],
            })
        return achados

    def _licenca_aceita(self, licenca):
        if licenca.startswith("pd") or licenca == "cc0":
            return True
        if licenca.startswith("cc-by-sa"):
            return bool(self.cfg.get("aceitar_cc_by_sa", False))
        if licenca.startswith("cc-by-") and "-nc" not in licenca and "-nd" not in licenca:
            return bool(self.cfg.get("aceitar_cc_by", True))
        return False

    def _pexels(self, tipo, busca):
        if tipo == "foto":
            r = self._pedir_com_chaves("Pexels", "PEXELS_API_KEY", lambda chave: self.http.get(
                "https://api.pexels.com/v1/search", headers={"Authorization": chave},
                params={"query": busca, "orientation": "landscape", "per_page": 40}))
            self._checar(r, "Pexels")
            return [{
                "fonte": "pexels", "id": str(f["id"]), "tipo": "foto",
                "miniatura": f["src"]["medium"],
                "arquivo": f["src"]["original"] + "?auto=compress&cs=tinysrgb&w=2560",
                "duracao": None, "pagina": f["url"], "autor": f.get("photographer", ""),
                "licenca": "Licença Pexels", "descricao": f.get("alt") or "",
            } for f in r.json().get("photos", [])]

        parametros = {"query": busca, "orientation": "landscape", "size": "medium", "per_page": 40}

        def pedir_videos(chave):
            r = self.http.get("https://api.pexels.com/videos/search", headers={"Authorization": chave}, params=parametros)
            if r.status_code == 404:
                r = self.http.get("https://api.pexels.com/v1/videos/search", headers={"Authorization": chave},
                                  params=parametros)
            return r

        r = self._pedir_com_chaves("Pexels", "PEXELS_API_KEY", pedir_videos)
        self._checar(r, "Pexels")
        achados = []
        for v in r.json().get("videos", []):
            opcoes = [(a.get("width") or 0, a.get("height") or 0, a["link"])
                      for a in v.get("video_files", []) if a.get("file_type") == "video/mp4" and a.get("link")]
            escolhido = _melhor_arquivo(opcoes)
            if not escolhido:
                continue
            achados.append({
                "fonte": "pexels", "id": str(v["id"]), "tipo": "video",
                "miniatura": v["image"], "arquivo": escolhido[2], "duracao": v.get("duration"),
                "pagina": v["url"], "autor": (v.get("user") or {}).get("name", ""), "licenca": "Licença Pexels",
                "descricao": re.sub(r"[-/\d]+", " ", v["url"].rstrip("/").rsplit("/", 1)[-1]).strip(),
            })
        return achados

    def _pixabay(self, tipo, busca):
        parametros = {"q": busca[:100], "safesearch": "true", "per_page": 40}
        if tipo == "foto":
            parametros.update({"image_type": "photo", "orientation": "horizontal", "min_width": 1280})
            endereco = "https://pixabay.com/api/"
        else:
            parametros.update({"video_type": "film", "min_width": 1280})
            endereco = "https://pixabay.com/api/videos/"
        r = self._pedir_com_chaves("Pixabay", "PIXABAY_API_KEY",
                                   lambda chave: self.http.get(endereco, params={**parametros, "key": chave}))
        self._checar(r, "Pixabay")
        achados = []
        for h in r.json().get("hits", []):
            comum = {"fonte": "pixabay", "id": str(h["id"]), "pagina": h["pageURL"], "autor": h.get("user", ""),
                     "licenca": "Licença Pixabay", "descricao": h.get("tags", "")}
            if tipo == "foto":
                achados.append({**comum, "tipo": "foto", "miniatura": h["webformatURL"],
                                "arquivo": h["largeImageURL"], "duracao": None})
                continue
            versoes = h.get("videos") or {}
            escolhido = _melhor_arquivo([(v.get("width") or 0, v.get("height") or 0, v["url"])
                                         for v in versoes.values() if v.get("url")])
            miniatura = next((v.get("thumbnail") for v in versoes.values() if v.get("thumbnail")), None)
            if escolhido and miniatura:
                achados.append({**comum, "tipo": "video", "miniatura": miniatura,
                                "arquivo": escolhido[2], "duracao": h.get("duration")})
        return achados


def _folha_de_contato(projeto, cena, candidatos, http, sufixo=""):
    """Uma imagem só com todos os candidatos da cena, cada um com seu número."""
    from PIL import Image, ImageDraw

    celula_l, celula_a, colunas = 480, 270, 4
    linhas = -(-len(candidatos) // colunas)
    folha = Image.new("RGB", (colunas * celula_l, linhas * celula_a), (18, 18, 18))
    desenho = ImageDraw.Draw(folha)
    fonte = _fonte(36)
    validos = []
    for i, candidato in enumerate(candidatos):
        x, y = (i % colunas) * celula_l, (i // colunas) * celula_a
        miniatura = _miniatura(http, candidato["miniatura"])
        if miniatura is None:
            continue
        miniatura.thumbnail((celula_l - 8, celula_a - 8))
        folha.paste(miniatura, (x + (celula_l - miniatura.width) // 2, y + (celula_a - miniatura.height) // 2))
        rotulo = str(i) + (f"  vídeo {candidato['duracao']:.0f}s" if candidato["tipo"] == "video" and candidato.get("duracao") else "")
        desenho.rectangle([x + 6, y + 6, x + 22 + fonte.getlength(rotulo), y + 52], fill=(0, 0, 0))
        desenho.text((x + 14, y + 8), rotulo, font=fonte, fill=(255, 214, 0))
        validos.append(i)
    destino = projeto.caminho("midia", "escolha", f"cena_{cena['n']:04d}{sufixo}.jpg")
    folha.save(destino, quality=85)
    return destino, validos


# suba quando mudar a regra da escolha (INSTRUCOES_ESCOLHA): as escolhas guardadas com a regra antiga são refeitas
VERSAO_ESCOLHA = 2


def _escolher_lote(projeto, lote, candidatos, folhas, descricoes=None, sufixo=""):
    """Pergunta ao modelo as escolhas de várias cenas de uma vez. As respostas ficam guardadas.

    Com descricoes (um dicionário), o modelo também diz o que vê em cada candidato indicado, e essas frases
    são guardadas junto, para o Jev conferir antes do download."""
    from . import cliente

    resultado, pendentes = {}, []
    com_descricao = descricoes is not None
    pelo_cliente = cliente.ativo(projeto)
    for cena in lote:
        cache = projeto.caminho("midia", "escolha", f"cena_{cena['n']:04d}{sufixo}.json")
        assinatura = hashlib.sha1(
            (json.dumps([_chave(c) for c in candidatos[cena["n"]]]) + ("|descricao" if com_descricao else "")
             + (f"|v{VERSAO_ESCOLHA}" if VERSAO_ESCOLHA > 1 else "") + ("|cliente" if pelo_cliente else "")).encode()
        ).hexdigest()[:12]
        if cache.exists():
            salvo = json.loads(cache.read_text(encoding="utf-8"))
            if salvo.get("assinatura") == assinatura:
                resultado[cena["n"]] = salvo["escolhas"]
                if com_descricao:
                    descricoes[cena["n"]] = {int(i): f for i, f in (salvo.get("vejo") or {}).items()}
                _lembrar_juizos(projeto, cena["n"], candidatos[cena["n"]], salvo.get("juizo") or {})
                continue
        if not folhas[cena["n"]][1]:
            # nenhuma miniatura carregou: pode ser falha de rede, então a cena fica sem resposta e tenta de novo depois
            continue
        pendentes.append((cena, cache, assinatura))
    if not pendentes:
        return resultado

    blocos = []
    for cena, _, _ in pendentes:
        folha, validos = folhas[cena["n"]]
        opcoes = []
        for i in validos:
            c = candidatos[cena["n"]][i]
            linha = f"  {i}. {c['tipo']} do {c['fonte']}"
            if c.get("duracao"):
                linha += f", {c['duracao']:.0f} segundos"
            if c.get("descricao"):
                linha += f". {c['descricao'][:150]}"
            opcoes.append(linha)
        blocos.append(
            f"Cena {cena['n']}\n"
            f"Narração \"{cena['texto']}\"\n"
            f"O que deveria mostrar {cena.get('mostrar') or cena['prompt']}\n"
            f"Assunto que tem que aparecer {cena.get('sujeito') or cena['busca']}\n"
            + (f"Época {cena['epoca']}: só serve imagem daquela época (foto antiga, gravura, ilustração ou objeto de "
               "museu); foto de hoje não serve\n" if e_de_epoca(cena) else "")
            + f"Termos buscados {cena['busca']}\n"
            f"Duração {cena['fim'] - cena['ini']:.1f} segundos\n"
            f"Imagem com os candidatos {folha}\n"
            "Candidatos\n" + "\n".join(opcoes)
        )

    cfg = projeto.config.get("claude") or {}
    instrucoes = INSTRUCOES_ESCOLHA.format(canal=projeto.perfil.get("nome", "")) + (
        INSTRUCOES_DESCRICAO if com_descricao else "")
    vejos, juizos = {}, {}
    if pelo_cliente:
        respostas = _escolher_pelo_cliente(projeto, pendentes, candidatos, folhas, instrucoes, com_descricao, vejos,
                                           juizos)
    elif (projeto.config.get("midia") or {}).get("escolha") not in (None, "", "claude"):
        respostas = _escolher_pelo_modelo(projeto, pendentes, blocos, folhas, instrucoes,
                                          _esquema_escolha(com_descricao), vejos)
    elif cfg.get("via", "assinatura") == "api":
        respostas = _escolher_pela_api(pendentes, blocos, folhas, instrucoes, cfg)
    else:
        pedido = "\n\n".join(blocos) + "\n\nAbra cada imagem de candidatos com a ferramenta Read antes de decidir."
        dados = claude_local.perguntar(projeto, "escolha de material real", instrucoes, pedido, ESQUEMA_ESCOLHA,
                                       esforco=cfg.get("esforco_escolha", "medium"), ler_arquivos=True)
        respostas = {item["cena"]: item["escolhas"] for item in dados.get("cenas", [])}

    for cena, cache, assinatura in pendentes:
        if cena["n"] not in respostas:
            # sem resposta (falha, limite de uso, cena omitida): não grava nada, para a próxima rodada tentar de novo
            continue
        validos = folhas[cena["n"]][1]
        escolhas = [i for i in respostas[cena["n"]] if i in validos]
        vejo = {i: f for i, f in (vejos.get(cena["n"]) or {}).items() if i in validos}
        juizo = {str(i): j for i, j in (juizos.get(cena["n"]) or {}).items() if i in validos}
        cache.write_text(json.dumps({"assinatura": assinatura, "escolhas": escolhas,
                                     "vejo": {str(i): f for i, f in vejo.items()},
                                     **({"juizo": juizo} if juizo else {})}), encoding="utf-8")
        _lembrar_juizos(projeto, cena["n"], candidatos[cena["n"]], juizo)
        resultado[cena["n"]] = escolhas
        if com_descricao:
            descricoes[cena["n"]] = vejo
    return resultado


def _lembrar_juizos(projeto, n, candidatos_da_cena, juizo):
    """Guarda o julgamento que o cliente deu a cada candidato, para _nota_do_candidato usar no lugar do Jev."""
    for i, j in (juizo or {}).items():
        i = int(i)
        if 0 <= i < len(candidatos_da_cena):
            _JUIZOS_DO_CLIENTE[(projeto.nome, n, _chave(candidatos_da_cena[i]))] = j


def _esquema_escolha_do_cliente():
    """O esquema da escolha com as notas do juiz em cada candidato descrito."""
    esquema = _esquema_escolha(True)
    vejo = esquema["properties"]["cenas"]["items"]["properties"]["vejo"]["items"]
    vejo["properties"].update({"combina": {"type": "integer"}, "sujeito": {"type": "integer"},
                               "epoca": {"type": "integer"}})
    vejo["required"] = [*vejo["required"], "combina", "sujeito"]
    return esquema


def _folha_leve(projeto, folha):
    """A folha de candidatos menor, para o Claude do cliente: 1280 px de largura em vez de 1920.

    O Claude cobra a imagem pela área (uns 1.380 tokens a folha cheia, uns 920 a de 1280 px). Cada miniatura fica com
    320 x 180 px, o bastante para reconhecer o bicho, o lugar e o objeto, e o número continua legível. A escolha das
    fotos foi 43% do consumo do mcp-cafe-5min, quase tudo nas folhas."""
    from PIL import Image

    largura = int((projeto.config.get("cliente") or {}).get("largura_da_folha", 1280))
    folha = Path(folha)
    destino = folha.with_name(folha.stem + "_leve.jpg")
    try:
        with Image.open(folha) as im:
            if im.width <= largura:
                return folha
            if not destino.exists() or destino.stat().st_mtime < folha.stat().st_mtime:
                im.convert("RGB").resize((largura, round(im.height * largura / im.width)), Image.LANCZOS).save(
                    destino, quality=85)
    except OSError:
        return folha  # a folha que não abre vai como está
    return destino


def _palavras_unicas(texto, limite=90):
    """A descrição do arquivo sem as tags repetidas ("coffee, coffee, coffee, coffee bean") e curta."""
    vistas, saida = set(), []
    for parte in re.split(r",\s*", str(texto or "").strip()):
        chave = parte.strip().lower()
        if chave and chave not in vistas:
            vistas.add(chave)
            saida.append(parte.strip())
    texto = ", ".join(saida)
    return texto if len(texto) <= limite else texto[:limite].rsplit(" ", 1)[0] + "…"


def _bloco_do_cliente(projeto, cena, candidatos, validos, numero_da_imagem):
    """O pedido de uma cena na escolha pelo Claude do cliente, só com o que decide a escolha.

    Sai o que não muda a decisão: os termos buscados, a duração, os trechos vizinhos e a descrição repetida (o "O que
    deveria mostrar" vinha duas vezes). A lista de candidatos fica com o tipo, o banco e a descrição sem tags
    repetidas, em até 90 letras (antes 150)."""
    from . import corrigir

    linhas = [f"Cena {cena['n']}", f"Narração: \"{cena['texto']}\"",
              f"Deveria mostrar: {cena.get('mostrar') or cena['prompt']}"]
    if (cena.get("aceitavel") or "").strip():
        linhas.append(f"Mínimo para estar certa: {cena['aceitavel'].strip()}")
    if cena.get("exato"):
        linhas.append(f"Tem que ser: {cena['exato']}")
    if e_de_epoca(cena):
        linhas.append(f"Época {cena['epoca']}: só imagem daquela época (foto antiga, gravura, ilustração, museu)")
    pessoa = corrigir._pessoa_da_cena(projeto, cena)
    if pessoa:
        linhas.append(f"Pessoa citada: {pessoa}")
    if cena.get("item_citado"):
        linhas.append(f"Item da lista nesta cena: {cena['item_citado']}")
    bloco = corrigir._bloco_da_cena_no_mapa(projeto, cena)
    if bloco:
        linhas.append(f"Assunto do bloco: {bloco}")
    linhas.append(f"Candidatos: [imagem {numero_da_imagem}]")
    for i in validos:
        c = candidatos[i]
        tipo = f"vídeo {c['duracao']:.0f}s" if c["tipo"] == "video" and c.get("duracao") else c["tipo"]
        linhas.append(f"  {i}. {tipo}, {c['fonte']}: {_palavras_unicas(c.get('descricao'))}")
    return "\n".join(linhas)


def _escolher_pelo_cliente(projeto, pendentes, candidatos, folhas, instrucoes, com_descricao, vejos, juizos):
    """Projeto do MCP: o Claude do cliente escolhe as fotos de todas as cenas do lote numa tarefa só e já julga cada
    escolhida, com a régua do Jev (corrigir.instrucoes_do_juizo).

    No caminho dos modelos são uma chamada por cena para escolher e mais uma ao Jev por candidato antes do download; no
    teste do MCP (mcp-pangolim) isso deu 6 tarefas para 3 cenas, e aqui é uma. A folha vai menor (_folha_leve) e o
    texto só com o que decide (_bloco_do_cliente)."""
    from . import cliente, corrigir

    textos, imagens = [], []
    for cena, _, _ in pendentes:
        folha, validos = folhas[cena["n"]]
        imagens.append(_folha_leve(projeto, folha))
        textos.append(_bloco_do_cliente(projeto, cena, candidatos[cena["n"]], validos, len(imagens)))
    pedido = (f"Responda as {len(pendentes)} cenas abaixo, uma por item, com o número de cada uma. A descrição de cada "
              "candidato é como o autor descreveu o arquivo.\n\n" + "\n\n".join(textos))
    esquema = _esquema_escolha_do_cliente() if com_descricao else ESQUEMA_ESCOLHA
    if com_descricao:
        instrucoes += corrigir.instrucoes_do_juizo()
    try:
        dados = cliente.pedir(projeto, "escolha das fotos (escolher e julgar)", instrucoes, pedido, esquema, imagens)
    except cliente.Cancelada:
        raise
    except (RuntimeError, SystemExit):
        return {}  # as cenas ficam para a próxima rodada
    numeros = {c["n"] for c, _, _ in pendentes}
    respostas = {}
    for item in dados.get("cenas", []):
        if not isinstance(item, dict) or item.get("cena") not in numeros:
            continue
        n = item["cena"]
        respostas[n] = item.get("escolhas", [])
        for v in item.get("vejo", []):
            frase = compor_o_que_se_ve(v)
            if not frase:
                continue
            vejos.setdefault(n, {})[int(v["indice"])] = frase
            if v.get("combina") is not None:
                juizos.setdefault(n, {})[int(v["indice"])] = {
                    "nota": max(0, min(100, int(v["combina"]))), "sujeito": v.get("sujeito"), "epoca": v.get("epoca")}
    return respostas


def _escolher_pelo_modelo(projeto, pendentes, blocos, folhas, instrucoes, esquema=None, vejos=None):
    """Uma chamada por cena, com a folha de contato dela, num modelo do Groq que enxerga imagens.

    Se uma cena falhar, ela fica sem escolha e o Claude ou uma próxima rodada decide depois.
    """
    from . import gemini_local, groq_local, openrouter_local

    # quem olha as miniaturas e escolhe: a cadeia de visão (midia.modelos_visao), os gratuitos primeiro e o Qwen pago
    # por último, sem raciocínio. MiMo, Groq e Gemini não são mais usados
    modulo, modelo = openrouter_local.VISAO, None
    # o escolhido que veio sem a frase do que se vê não é pedido de novo: passa sem o Jev antes do download e a
    # conferência depois do download (descrição grátis + Jev) julga a cena, porque ela não foi aprovada na captura
    # (api._esteira, cli). O pedido repetido era 551 das 1.570 chamadas da escolha no nunca-deve-ter-dentro-de-
    # casa-parte-2 (US$ 0,97 no Qwen pago), pedido do usuário em 2026-10-06

    def escolher(par):
        (cena, _, _), bloco = par
        pedido = f"{bloco}\n\nA imagem anexada é a folha com os candidatos numerados. Responda com a cena {cena['n']}."
        try:
            try:
                dados = modulo.perguntar(projeto, "escolha de material real", instrucoes, pedido,
                                         esquema or ESQUEMA_ESCOLHA, modelo=modelo, imagens=[folhas[cena["n"]][0]])
            except SystemExit:
                return None  # a cena fica para a próxima rodada
        except RuntimeError:
            return None
        for item in dados.get("cenas", []):
            if item.get("cena") == cena["n"]:
                if vejos is not None:
                    vejos[cena["n"]] = {int(v["indice"]): compor_o_que_se_ve(v)
                                        for v in item.get("vejo", []) if compor_o_que_se_ve(v)}
                return cena["n"], item.get("escolhas", [])
        return None

    paralelas = int((projeto.config.get("midia") or {}).get("paralelo_escolha", 4))
    with ThreadPoolExecutor(paralelas) as executor:
        return dict(r for r in executor.map(escolher, zip(pendentes, blocos)) if r)


def _escolher_pela_api(pendentes, blocos, folhas, instrucoes, cfg):
    conteudo = []
    for (cena, _, _), bloco in zip(pendentes, blocos):
        imagem = base64.standard_b64encode(folhas[cena["n"]][0].read_bytes()).decode()
        conteudo.append({"type": "text", "text": bloco})
        conteudo.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": imagem}})
    try:
        resposta = anthropic.Anthropic().beta.messages.create(
            model=cfg.get("modelo", "claude-opus-5"),
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={
                "effort": cfg.get("esforco_escolha", "medium"),
                "format": {"type": "json_schema", "schema": ESQUEMA_ESCOLHA},
            },
            system=instrucoes,
            messages=[{"role": "user", "content": conteudo}],
        )
    except anthropic.AuthenticationError:
        raise SystemExit("A chave ANTHROPIC_API_KEY é inválida. Confira o arquivo .env.")
    if resposta.stop_reason in ("refusal", "max_tokens"):
        return {}
    texto = next((b.text for b in resposta.content if b.type == "text"), "")
    return {item["cena"]: item["escolhas"] for item in json.loads(texto).get("cenas", [])} if texto else {}


def _fonte(tamanho):
    from PIL import ImageFont

    for caminho in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(caminho, tamanho)
        except OSError:
            continue
    return ImageFont.load_default(tamanho)


def _miniatura(http, url):
    from PIL import Image

    try:
        r = http.get(url)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except (httpx.HTTPError, OSError):
        return None


class ImagemRepetida(ValueError):
    """A imagem baixada é igual (ou quase igual) à de outra cena do vídeo: jamais repetir imagem."""


_IMPRESSOES = {}          # (caminho, data do arquivo) -> impressão digital visual
_TRAVA_IMPRESSOES = threading.Lock()
DISTANCIA_REPETIDA = 6    # quantos dos 64 pontos podem mudar e a imagem ainda ser "a mesma"


def _impressao(caminho) -> Optional[int]:
    """Impressão digital visual (dHash de 64 pontos): a mesma foto dá a mesma impressão mesmo vinda de outro
    banco, em outro tamanho ou com outra compressão. Foto quase idêntica (outro corte da mesma cena) fica perto."""
    from PIL import Image

    try:
        chave = (str(caminho), caminho.stat().st_mtime)
    except OSError:
        return None
    with _TRAVA_IMPRESSOES:
        if chave in _IMPRESSOES:
            return _IMPRESSOES[chave]
    try:
        with Image.open(caminho) as im:
            cinza = im.convert("L").resize((9, 8))
            px = list(cinza.getdata())
    except Exception:
        return None
    valor = 0
    for linha in range(8):
        for col in range(8):
            valor = (valor << 1) | (px[linha * 9 + col] > px[linha * 9 + col + 1])
    with _TRAVA_IMPRESSOES:
        _IMPRESSOES[chave] = valor
    return valor


def _imagem_de_comparar(projeto, midia_info) -> Optional[Path]:
    """O que se compara de cada mídia: a foto, ou a capa do vídeo."""
    if not midia_info:
        return None
    for chave in ("capa", "arquivo"):
        rel = midia_info.get(chave)
        if rel and not str(rel).lower().endswith((".mp4", ".mov", ".webm", ".m4v")):
            caminho = projeto.pasta / rel
            if caminho.exists():
                return caminho
    return None


def cena_com_a_mesma_imagem(projeto, n, caminho, chave=None) -> Optional[int]:
    """Número da outra cena do vídeo que já mostra esta mesma imagem (ou uma quase igual), ou None."""
    minha = _impressao(caminho)
    if minha is None or not projeto.existe("cenas.json"):
        return None
    for outra in projeto.ler_json("cenas.json").get("cenas", []):
        if outra.get("n") == n:
            continue
        if chave and (outra.get("midia") or {}).get("fonte") and \
                f"{outra['midia'].get('fonte')}:{outra['midia'].get('id')}" == chave:
            return outra["n"]  # a mesma foto do mesmo banco
        dela = _imagem_de_comparar(projeto, outra.get("midia"))
        h = _impressao(dela) if dela else None
        if h is not None and bin(minha ^ h).count("1") <= DISTANCIA_REPETIDA:
            return outra["n"]
    return None


def cenas_repetidas(projeto) -> list[int]:
    """Cenas cuja imagem já apareceu numa cena ANTERIOR do vídeo: a mesma foto (mesmo banco e número, mesmo
    arquivo) ou uma imagem igual ou quase igual pela impressão digital. A primeira fica; as seguintes saem."""
    vistas_chave, vistas_arquivo, vistas_impressao, repetidas = {}, {}, [], []
    for c in sorted(projeto.ler_json("cenas.json").get("cenas", []), key=lambda x: x["n"]):
        m = c.get("midia") or {}
        if not m.get("arquivo"):
            continue
        chave = f"{m.get('fonte')}:{m.get('id')}" if m.get("fonte") and m.get("id") else None
        caminho = _imagem_de_comparar(projeto, m)
        h = _impressao(caminho) if caminho else None
        if (chave and chave in vistas_chave) or m["arquivo"] in vistas_arquivo or (
                h is not None and any(bin(h ^ outra).count("1") <= DISTANCIA_REPETIDA for outra in vistas_impressao)):
            repetidas.append(c["n"])
            continue
        if chave:
            vistas_chave[chave] = c["n"]
        vistas_arquivo[m["arquivo"]] = c["n"]
        if h is not None:
            vistas_impressao.append(h)
    return repetidas


def tirar_repetidas(projeto, log=print) -> list[int]:
    """Varredura final, regra fixa: JAMAIS repetir imagem. Cena com imagem repetida perde a cópia (que entra em
    rejeitadas) e busca uma imagem nova do assunto. Roda no fim da conferência e no fim da criação."""
    repetidas = soltar_repetidas(projeto)
    if not repetidas:
        return []
    log(f"  {len(repetidas)} cena(s) com imagem repetida: buscando imagem nova ({', '.join(map(str, repetidas))})")
    buscar(projeto, apenas=set(repetidas), log=log)
    return repetidas


def soltar_repetidas(projeto) -> list[int]:
    """A cena com imagem repetida perde a cópia (que entra em rejeitadas) e volta a esperar material, sem buscar."""
    repetidas = cenas_repetidas(projeto)
    if not repetidas:
        return []
    dados = projeto.ler_json("cenas.json")
    for c in dados["cenas"]:
        if c["n"] in repetidas:
            m = c.pop("midia", None) or {}
            if m.get("fonte") and m.get("id"):
                c.setdefault("rejeitadas", []).append(f"{m['fonte']}:{m['id']}")
            c.pop("conferencia", None)
            c["captura"] = {}
    projeto.salvar_json("cenas.json", dados)
    return repetidas


def nome_livre(projeto, n: int, sufixos: tuple) -> str:
    """Base do nome (midia/NNNN, midia/NNNN_2...) cujos arquivos nenhuma OUTRA cena usa.

    O material baixado leva o número da cena no nome. Depois que a narração muda e as cenas são renumeradas, a cena
    129 pode estar usando midia/0111.jpg: gravar a foto nova da cena 111 com esse nome trocaria a foto da 129."""
    usados = set()
    try:
        for c in projeto.ler_json("cenas.json").get("cenas", []):
            if c.get("n") == n:
                continue
            m = c.get("midia") or {}
            for chave in ("arquivo", "capa"):
                if m.get(chave):
                    usados.add(str(m[chave]).replace("\\", "/"))
    except (OSError, ValueError, KeyError):
        pass
    k = 1
    while True:
        base = f"{n:04d}" if k == 1 else f"{n:04d}_{k}"
        if not any(f"midia/{base}{s}" in usados for s in sufixos):
            return base
        k += 1


def _baixar_midia(projeto, cena, candidato, http):
    n = cena["n"]
    if candidato["tipo"] == "video":
        base = nome_livre(projeto, n, (".mp4", "_capa.jpg"))
        arquivo = projeto.caminho("midia", f"{base}.mp4")
        _baixar(http, candidato["arquivo"], arquivo)
        capa = projeto.caminho("midia", f"{base}_capa.jpg")
        try:
            _baixar(http, candidato["miniatura"], capa)
        except httpx.HTTPError:
            capa = None
    else:
        arquivo = projeto.caminho("midia", f"{nome_livre(projeto, n, ('.jpg',))}.jpg")
        _baixar(http, candidato["arquivo"], arquivo)
        _garantir_jpeg(arquivo)
        capa = arquivo
    # jamais repetir imagem: a mesma foto pode vir de dois bancos (Wikimedia e Pixabay) com números diferentes,
    # ou em duas versões quase iguais. Olha a imagem em si e recusa a que já está em outra cena do vídeo
    comparar = capa if capa and capa.exists() else (arquivo if candidato["tipo"] != "video" else None)
    igual = cena_com_a_mesma_imagem(projeto, n, comparar or arquivo, _chave(candidato))
    if igual is not None:
        for f in {arquivo, capa} - {None}:
            f.unlink(missing_ok=True)
        cena.setdefault("rejeitadas", []).append(_chave(candidato))
        raise ImagemRepetida(f"a imagem é a mesma da cena {igual}")
    registro = {chave: candidato.get(chave) for chave in ("fonte", "id", "tipo", "pagina", "autor", "licenca", "duracao")}
    registro["arquivo"] = str(arquivo.relative_to(projeto.pasta))
    registro["capa"] = str(capa.relative_to(projeto.pasta)) if capa else None
    return registro


def _baixar(http, url, destino):
    temporario = destino.with_name(destino.name + ".baixando")
    with http.stream("GET", url) as r:
        r.raise_for_status()
        with open(temporario, "wb") as f:
            for parte in r.iter_bytes():
                f.write(parte)
    temporario.replace(destino)


def _garantir_jpeg(arquivo):
    from PIL import Image

    with Image.open(arquivo) as imagem:
        if imagem.format == "JPEG":
            return
        convertida = imagem.convert("RGB")
    convertida.save(arquivo, "JPEG", quality=92)


def _segundos_ate_liberar(resposta):
    """Quanto esperar depois de um 429. O Pexels manda o instante em que o limite zera e o Pixabay manda segundos."""
    cabecalhos = {k.lower(): v for k, v in resposta.headers.items()}
    for nome in ("x-ratelimit-reset", "retry-after"):
        try:
            valor = float(cabecalhos[nome])
        except (KeyError, ValueError):
            continue
        segundos = valor - time.time() if valor > 1e9 else valor
        return max(5.0, min(segundos, 24 * 3600))
    return 60.0


def _melhor_arquivo(opcoes):
    """Menor versão horizontal com pelo menos 1920 de largura, ou a maior que existir."""
    horizontais = [o for o in opcoes if o[0] and o[0] >= o[1]]
    if not horizontais:
        return None
    grandes = [o for o in horizontais if o[0] >= 1920]
    return min(grandes) if grandes else max(horizontais)


def _texto(campo):
    valor = campo.get("value", "") if isinstance(campo, dict) else ""
    return html.unescape(re.sub(r"<[^>]+>", "", str(valor))).strip()


def _chave(item):
    return f"{item['fonte']}:{item['id']}"


def escrever_creditos(projeto):
    linhas = []
    for c in projeto.ler_json("cenas.json")["cenas"]:
        m = c.get("midia")
        if not m or m.get("fonte") == "motion_ia":
            continue
        autor = f" por {m['autor']}" if m.get("autor") else ""
        tipo = "Vídeo" if m["tipo"] == "video" else "Foto"
        linhas.append(f"{mmss(c['ini'])} {tipo} do {m['fonte'].capitalize()}{autor}, {m['licenca']}. {m['pagina']}")
    destino = projeto.caminho("creditos.txt")
    destino.write_text("Créditos de fotos e vídeos\n\n" + "\n".join(linhas) + "\n", encoding="utf-8")
    return destino
