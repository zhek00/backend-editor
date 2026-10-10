"""animation-ai: cenas animadas de modelos prontos que COMPLEMENTAM as fotos, onde explicam melhor que elas.

Pedido do usuário em 2026-10-09, depois de estudar o concorrente (Pipeline Canal Dark), que monta o vídeo com 24
modelos de cena animada em HTML (lista, número, linha do tempo, comparação...), cada elemento entrando na palavra
falada, desenhados quadro a quadro por um motor que é função do tempo. Reimplementado do zero aqui (a licença dele
proíbe copiar o código). **Aqui ele não faz o vídeo inteiro** (correção do usuário no mesmo dia: "não é um vídeo
completo de cenas animadas, seria complementar como o motion ai"): entra misturado com as fotos, como o Motion IA nas
cenas com dado (`motion_ia.nas_uteis`), e roda logo depois dele (passo 6b da criação, `etapa_motion` no `tudo`).

1. **Candidatas** (`frases_do_video` e `estrutura`, de graça): cada frase falada (as cenas dela, do mesmo bloco, até
   `duracao_maxima`) que tem estrutura que um modelo pronto mostra melhor que a foto: itens ditos em sequência (ou a
   `enumeracao` das cenas), duas datas ou mais, número, comparação, citação, definição, documento ou notícia, causa e
   consequência, ou uma cena que o agente marcou como diagrama, texto na tela, linha do tempo ou mapa. Narração pura
   nem vai ao modelo. Cena com personagem, imagem ou prompt da pessoa, ou que já é Motion IA, fica de fora.
2. **Decisão e plano numa chamada** (`decidir`, grátis pela cadeia de principais): o modelo lê a fala, as vizinhas e o
   que a foto de hoje mostra, dá a nota de utilidade (0 a 100) e, se valer, escolhe um dos 19 tipos de conteúdo do
   `CATALOGO` (abertura, capitulo, frase, pergunta e encerramento são só do modo de cenas pedidas) e escreve os textos
   curtos com a `palavra` da fala em que cada item entra. Ele NÃO escreve HTML. O código confere (`conferir`); o que
   reprovar volta uma vez com os erros. Fica em `animation_ai/decisoes.json` pela fala: rodar de novo não pergunta.
3. **Cadência** (`escolher`): das que passaram de `limiar` (70), as de nota maior primeiro, até `maximo_do_video`
   (12% da duração) e com `intervalo_minimo` (20 s) de qualquer outra cena animada ou clipe do Motion IA. Complemento
   que aparece toda hora vira o vídeo inteiro.
4. **Tempos** (`resolver_tempos`): o segundo de cada palavra no `alinhamento.json`, pronto para a página; o elemento
   principal entra em até 1 s. Os sons (pop, risco, baque, contagem) saem das mesmas entradas (`sons`).
5. **Desenho** (`recursos/animation_ai/motor.js` e `motor.css`): `quadro(t)` é função pura do tempo; o HyperFrames
   grava quadro a quadro por um relógio do GSAP. Texto comprido encolhe até caber. Cores do `TEMAS`.
6. **Gravação** (`gravar`): `hyperframes check`, MP4, um pedaço por cena (`midia/NNNN_anim.mp4`), mídia da cena com
   `fonte: animation_ai`; a foto fica em `anim_reserva` (`desfazer` volta). Falhou: a cena fica com a foto
   (`anim_falhou`, não tenta de novo na mesma fala). Nunca para o vídeo.

`fabrica animation-ai NOME` faz o mesmo no terminal; com `--cenas`, anima essas cenas sem perguntar se vale.
"""
import hashlib
import json
import re
import shutil
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import animacoes
from .util import rodar

FONTE = "animation_ai"
VERSAO = 1  # suba quando mudar o desenho (motor.js, motor.css ou TEMAS): os trechos são gravados de novo
RECURSOS = Path(__file__).parent / "recursos" / "animation_ai"
_TRAVA_CENAS = threading.Lock()

TEMAS = {
    # o visual do Motion IA, de produto da Apple (pedido do usuário em 2026-10-10: "o mesmo estilo visual de cores estilo
    # APPLE que o motion ia utilizava"): creme #F7F6F2 com pontos de 24 px, cards brancos de raio 20 sem borda com a
    # sombra suave e flutuando, título em Inter grafite, destaque em Playfair itálica azul, mola na entrada, sem
    # tremor, e a câmera que só aproxima 3%. As chaves com _ são o jeito de mexer (motor.js, E)
    "apple": {"fundo": "#F7F6F2", "painel": "#FFFFFF", "painel2": "#F1EFE9", "linha": "#E7E4DC", "txt": "#1A1A1A",
              "txt2": "#4A4843", "mut": "#8A867E", "acc": "#2563EB", "acc2": "#EA580C", "verm": "#C2410C",
              "ok": "#166534", "tinta": "#FFFFFF", "papel": "#FFFFFF", "brilho1": "transparent",
              "brilho2": "transparent", "ponto": "#d1d0c9", "ponto-r": "1px", "pontos-tam": "24px",
              "pontos-opac": "1", "sombra": "rgba(0,0,0,.06)", "sombra-card": "0 12px 32px rgba(0,0,0,.06)",
              "card-borda": "none", "raio-card": "20px", "raio-selo": "16px", "vinheta": "transparent",
              "faixa": "rgba(26,26,26,.5)", "faixa-altura": "230px", "f-tit": '"Texto"', "peso-tit": "700",
              "esp-tit": "-0.02em", "caixa": "none", "f-d": '"Titulo"', "estilo-d": "italic", "peso-d": "700",
              "f-num": '"Texto"', "f-txt": '"Texto"',
              "_flutuar": True, "_mola": True, "_tremer": False, "_assentar": False},
    # escuro, azul-noite com âmbar: serve para quase tudo
    "noite": {"fundo": "#0E1420", "painel": "#161F2E", "painel2": "#1E2A3D", "linha": "#2B3850", "txt": "#F1F4F8",
              "txt2": "#C5CEDB", "mut": "#8794A8", "acc": "#F5B83D", "acc2": "#4FD1C5", "verm": "#F0575D",
              "ok": "#43C58A", "tinta": "#0E1420", "papel": "#EFE8D8", "brilho1": "rgba(245,184,61,.10)",
              "brilho2": "rgba(79,209,197,.08)", "ponto": "rgba(255,255,255,.07)", "sombra": "rgba(0,0,0,.45)",
              "vinheta": "rgba(0,0,0,.55)", "faixa": "rgba(0,0,0,0)", "f-tit": '"Texto"', "peso-tit": "800",
              "esp-tit": "-0.01em", "caixa": "none", "f-d": '"Titulo"', "estilo-d": "italic", "peso-d": "700",
              "f-num": '"Texto"', "f-txt": '"Texto"'},
    # claro, papel creme do estilo editorial (o mesmo do Motion IA)
    "editorial": {"fundo": "#F7F6F2", "painel": "#FFFFFF", "painel2": "#EFEDE6", "linha": "#E2DFD6",
                  "txt": "#1A1A1A", "txt2": "#3D3A35", "mut": "#7A766D", "acc": "#2563EB", "acc2": "#EA580C",
                  "verm": "#C2410C", "ok": "#166534", "tinta": "#FFFFFF", "papel": "#FFFDF7",
                  "brilho1": "rgba(37,99,235,.06)", "brilho2": "rgba(234,88,12,.05)", "ponto": "rgba(0,0,0,.13)",
                  "sombra": "rgba(0,0,0,.08)", "vinheta": "rgba(0,0,0,.06)", "faixa": "rgba(26,26,26,.5)",
                  "f-tit": '"Titulo"', "peso-tit": "800", "esp-tit": "0", "caixa": "none", "f-d": '"Titulo"',
                  "estilo-d": "italic", "peso-d": "700", "f-num": '"Texto"', "f-txt": '"Texto"'},
    # preto e vermelho, para mistério, crime e história sombria
    "misterio": {"fundo": "#0B0B0C", "painel": "#17171A", "painel2": "#222226", "linha": "#2E2E33", "txt": "#F2EFEA",
                 "txt2": "#CFC9BF", "mut": "#8C877E", "acc": "#E23B3B", "acc2": "#E8D5A3", "verm": "#E23B3B",
                 "ok": "#7FB77E", "tinta": "#FFFFFF", "papel": "#E9E1CF", "brilho1": "rgba(226,59,59,.10)",
                 "brilho2": "rgba(232,213,163,.05)", "ponto": "rgba(255,255,255,.05)", "sombra": "rgba(0,0,0,.6)",
                 "vinheta": "rgba(0,0,0,.7)", "faixa": "rgba(0,0,0,0)", "f-tit": '"Texto"', "peso-tit": "900",
                 "esp-tit": "0.01em", "caixa": "uppercase", "f-d": '"Titulo"', "estilo-d": "italic", "peso-d": "700",
                 "f-num": '"Texto"', "f-txt": '"Texto"'},
}

# os 24 tipos: para que servem e os campos de cada um. "palavra" é a palavra da fala em que o elemento entra
CATALOGO = {
    "abertura": ("abertura do vídeo com o título; SÓ no primeiro trecho", "titulo, sub?, kicker?"),
    "capitulo": ("começo de uma parte nova do assunto", "titulo, kicker?, sub?, palavra?"),
    "pergunta": ("gancho, pergunta que o trecho faz", "texto (com *destaque*), kicker?, palavra?"),
    "frase": ("a ideia central dita no trecho, com a palavra-chave em *destaque*", "texto, palavra?"),
    "numero": ("UM número forte da fala, com o que ele mede", "valor (como dito: '150 milhões', 'R$ 2,5 bi'), legenda, nota?, palavra?"),
    "lista": ("itens numerados ditos em sequência", "titulo?, itens: [{texto, palavra?}] (2 a 6)"),
    "checklist": ("requisitos, condições ou um resumo que se cumpre", "titulo?, itens: [{texto, palavra?}] (2 a 6)"),
    "passos": ("etapas de um processo, em ordem", "titulo?, itens: [{texto, palavra?}] (2 a 5), destaque? (índice)"),
    "comparar": ("dois lados: mito x fato, antes x hoje, A x B", "esq: {titulo, itens:[{texto, palavra?}], palavra?}, dir: {o mesmo}, neutro? (true quando nenhum lado é o errado)"),
    "barras": ("comparação de 2 a 5 valores ditos na fala", "titulo?, itens: [{rotulo, valor (número), texto?, palavra?}], fonte?, destaque? (índice)"),
    "linha_do_tempo": ("datas e acontecimentos em ordem", "titulo?, itens: [{data, texto, palavra?}] (2 a 5)"),
    "citacao": ("frase de alguém, citada na fala", "texto, autor?, palavra?"),
    "definicao": ("o que é um termo, ou um alerta", "termo, definicao, pontos?: [{texto, palavra?}] (até 3), alerta? (true/false), palavra?"),
    "cartoes": ("2 ou 3 opções, caminhos ou grupos", "titulo?, itens: [{titulo, texto, palavra?}] (2 a 3)"),
    "destaques": ("até 4 coisas marcadas: erros, perigos, os melhores", "titulo?, itens: [{texto, palavra?}] (2 a 4), marca: errado|alerta|estrela|certo"),
    "fato": ("uma curiosidade, um dado surpreendente sem número central", "texto, kicker?, fonte?, icone? (lupa|alerta), palavra?"),
    "porcentagem": ("uma porcentagem dita na fala", "valor (0 a 100), legenda, palavra?"),
    "antes_depois": ("um valor que mudou: de X para Y", "antes: {rotulo, valor, palavra?}, depois: {rotulo, valor, palavra?}, legenda?"),
    "ranking": ("posições em ordem, com uma em destaque", "titulo?, itens: [{texto, palavra?}] (3 a 5, o 1º primeiro), destaque (índice)"),
    "causa_efeito": ("uma coisa que leva a outra, em cadeia", "itens: [{texto, palavra?}] (2 a 4, da causa à consequência)"),
    "proporcao": ("'1 em cada 10', parte de um total pequeno", "total (até 100), parte, rotulo? ('1 em 10'), legenda, palavra?"),
    "documento": ("um documento, carta, lei, relatório ou registro citado", "titulo, linhas: [{texto, palavra?}] (2 a 5), carimbo? (1 a 2 palavras ditas), palavra?"),
    "manchete": ("uma notícia, como manchete de jornal", "titulo (com *destaque*), veiculo?, data?, sub?, palavra?"),
    "encerramento": ("pedido de inscrição no fim do vídeo; SÓ se a fala pede", "texto, proximo?, palavra?"),
}
ITENS = {"lista": (2, 6), "checklist": (2, 6), "passos": (2, 5), "barras": (2, 5), "linha_do_tempo": (2, 5),
         "cartoes": (2, 3), "destaques": (2, 4), "ranking": (3, 5), "causa_efeito": (2, 4), "documento": (2, 5)}
LIMITES = {"titulo": 64, "texto": 120, "legenda": 90, "sub": 110, "kicker": 32, "nota": 80, "autor": 50,
           "definicao": 160, "termo": 40, "rotulo": 40, "data": 14, "valor": 24, "veiculo": 30, "fonte": 50,
           "proximo": 70, "carimbo": 18}
_ITEM_TEXTO = {"lista": 70, "checklist": 70, "passos": 46, "destaques": 70, "ranking": 60, "causa_efeito": 60,
               "documento": 64, "linha_do_tempo": 60, "cartoes": 110}
_PALAVRAS_LIVRES = {"mais", "menos", "como", "para", "pelo", "pela", "pelos", "pelas", "isso", "esse", "essa", "este",
                    "esta", "cada", "muito", "muita", "sobre", "entre", "quando", "onde", "sendo", "hoje", "antes",
                    "depois", "parte", "total", "fonte", "nunca", "sempre", "porque", "também", "tambem"}


def config(projeto) -> dict:
    padrao = {"ativo": True, "tema": "apple", "duracao_alvo": 8, "duracao_maxima": 12, "duracao_minima": 3,
              "limiar": 70, "maximo_do_video": 0.12, "intervalo_minimo": 20, "trechos_por_lote": 6,
              "tentativas": 2, "paralelo": 2, "fps": 30, "canal": "", "sons": True, "volume_sons_db": -20}
    return {**padrao, **(projeto.config.get("animation_ai") or {}),
            **((getattr(projeto, "perfil", None) or {}).get("animation_ai") or {})}


def ligado(projeto) -> bool:
    return bool(config(projeto).get("ativo")) and not projeto.offline


def e_animada(cena) -> bool:
    return (cena.get("midia") or {}).get("fonte") == FONTE


# ------------------------------------------------------------------------------------------------ trechos

def _fecha_frase(texto) -> bool:
    return bool(re.search(r"[.!?…]['\"”)]*\s*$", (texto or "").strip()))


def _elegivel(c) -> bool:
    return bool((c.get("texto") or "").strip()) and not (c.get("personagem") or c.get("imagem_da_pessoa")
                                                          or c.get("prompt_manual"))


def trechos(cenas, cfg) -> list:
    """Listas de cenas seguidas do mesmo bloco, de duracao_alvo a duracao_maxima segundos, fechando no fim da frase."""
    alvo, maximo, minimo = float(cfg["duracao_alvo"]), float(cfg["duracao_maxima"]), float(cfg["duracao_minima"])
    grupos, atual = [], []
    dur = lambda g: float(g[-1]["fim"]) - float(g[0]["ini"]) if g else 0.0
    for c in cenas:
        if not _elegivel(c):
            if atual:
                grupos.append(atual)
            atual = []
            continue
        if atual and (c.get("bloco") != atual[-1].get("bloco") or c["n"] != atual[-1]["n"] + 1
                      or float(c["fim"]) - float(atual[0]["ini"]) > maximo):
            grupos.append(atual)
            atual = []
        atual.append(c)
        if dur(atual) >= alvo and _fecha_frase(c.get("texto")):
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    # o resto curto do bloco junta com o trecho anterior, se ainda couber
    saida = []
    for g in grupos:
        if (saida and dur(g) < minimo and g[0].get("bloco") == saida[-1][-1].get("bloco")
                and g[0]["n"] == saida[-1][-1]["n"] + 1 and dur(saida[-1] + g) <= maximo + 2):
            saida[-1] = saida[-1] + g
        else:
            saida.append(g)
    return saida


# ------------------------------------------------------------------------------------------------ fala e palavras

def _normal(texto) -> str:
    texto = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")


def _chave(palavra) -> str:
    return re.sub(r"[^a-z0-9]", "", _normal(palavra))


def palavras_do_trecho(projeto, ini, fim) -> list:
    """[(palavra, segundo dentro do trecho)] das palavras faladas entre ini e fim."""
    alin = projeto.ler_json("alinhamento.json")
    return [(p["texto"], round(float(p["ini"]) - ini, 3)) for p in alin.get("palavras") or []
            if p.get("ini") is not None and ini - 0.05 <= float(p["ini"]) < fim]


def tempo_da_palavra(palavra, palavras, depois=0.0):
    """Segundo em que a palavra é falada no trecho (a primeira palavra dela; "palavra#2" é a 2ª vez), ou None."""
    if not palavra:
        return None
    vez = 1
    m = re.match(r"^(.*)#(\d+)$", str(palavra).strip())
    if m:
        palavra, vez = m.group(1), int(m.group(2))
    alvo = _chave(str(palavra).split()[0] if str(palavra).split() else palavra)
    if not alvo:
        return None
    achadas = [t for w, t in palavras if _chave(w) == alvo]
    if len(achadas) < vez:
        # aceita o plural e o gênero ("leão" e "leões" não, mas "fazenda" e "fazendas" sim)
        achadas = [t for w, t in palavras if len(alvo) >= 5 and _chave(w)[:len(alvo) - 1] == alvo[:-1]]
    candidatas = [t for t in achadas if t >= depois - 0.05] or achadas
    return candidatas[min(vez, len(candidatas)) - 1] if candidatas else None


# ------------------------------------------------------------------------------------------------ conferência

def _textos(tipo, d) -> list:
    """Todo texto que vai para a tela."""
    saida = [d.get(k) for k in ("titulo", "texto", "legenda", "sub", "kicker", "nota", "autor", "definicao", "termo",
                                "rotulo", "veiculo", "carimbo", "proximo", "valor")]
    for chave in ("itens", "pontos", "linhas"):
        for it in d.get(chave) or []:
            if isinstance(it, dict):
                saida += [it.get("texto"), it.get("titulo"), it.get("rotulo"), it.get("data")]
    for lado in ("esq", "dir", "antes", "depois"):
        if isinstance(d.get(lado), dict):
            saida += [d[lado].get("titulo"), d[lado].get("rotulo"), d[lado].get("valor")]
            saida += [it.get("texto") for it in d[lado].get("itens") or [] if isinstance(it, dict)]
    return [str(x) for x in saida if x not in (None, "")]


_EXTENSO = re.compile(r"\b(um|uma|dois|duas|tr[eê]s|quatro|cinco|seis|sete|oito|nove|dez|onze|doze|treze|catorze|"
                      r"quinze|dezesseis|dezessete|dezoito|dezenove|vinte|trinta|quarenta|cinquenta|sessenta|setenta|"
                      r"oitenta|noventa|cem|cento|duzent|trezent|quatrocent|quinhent|seiscent|setecent|oitocent|"
                      r"novecent|mil|milh|bilh|metade|dobro|triplo)", re.I)


def _numeros(texto) -> set:
    saida = set()
    for n in re.findall(r"\d+(?:[.,]\d+)*", texto or ""):
        try:
            saida.add(float(n.replace(".", "").replace(",", ".")) if re.fullmatch(r"[\d.]+(,\d+)?", n) else float(n))
        except ValueError:
            pass
    return saida


def _inventadas(textos, fala) -> list:
    ditas = {p[:5] for p in re.findall(r"[a-z]{4,}", _normal(fala))}
    fora = []
    for texto in textos:
        for p in re.findall(r"[a-z]{4,}", _normal(re.sub(r"\*", "", texto))):
            if p[:5] not in ditas and p not in _PALAVRAS_LIVRES:
                fora.append(p)
    return list(dict.fromkeys(fora))


SIMPLES = ("frase", "pergunta")


def conferir(tipo, d, fala, extras="", posicao=0, total=1, anteriores=(), simples=0) -> list:
    """Os erros do plano de um trecho, para devolver ao modelo. Lista vazia: pode desenhar.
    simples: quantos trechos do vídeo já são frase ou pergunta. No primeiro teste (leite), o modelo pôs frase em 10 de
    18 trechos, inclusive em "esquenta igual, engrossa igual e queima igual", que é uma lista."""
    erros = []
    if tipo in SIMPLES and simples + 1 > max(2, round(total * 0.34)):
        erros.append(f"frase e pergunta já são um terço do vídeo: escolha outro tipo (destaques, fato, lista, cartoes, "
                     f"citacao, numero, comparar, causa_efeito...) pelo que a fala diz")
    if tipo not in CATALOGO:
        return [f"o tipo '{tipo}' não existe; use um destes: {', '.join(CATALOGO)}"]
    if not isinstance(d, dict):
        return ["'dados' tem de ser um objeto"]
    if tipo == "abertura" and posicao != 0:
        erros.append("'abertura' só no primeiro trecho do vídeo")
    if tipo == "encerramento" and not re.search(r"inscrev|curt|like|sininho|pr[oó]ximo v[ií]deo|coment", _normal(fala)):
        erros.append("'encerramento' só quando a fala pede inscrição, curtida ou comentário")
    if len(anteriores) >= 2 and anteriores[-1] == anteriores[-2] == tipo:
        erros.append(f"'{tipo}' já foi usado nos dois trechos anteriores: escolha outro tipo")
    obrigatorios = {"abertura": ["titulo"], "capitulo": ["titulo"], "pergunta": ["texto"], "frase": ["texto"],
                    "numero": ["valor", "legenda"], "citacao": ["texto"], "definicao": ["termo", "definicao"],
                    "fato": ["texto"], "porcentagem": ["valor", "legenda"], "proporcao": ["total", "parte", "legenda"],
                    "documento": ["titulo", "linhas"], "manchete": ["titulo"], "encerramento": ["texto"],
                    "comparar": ["esq", "dir"], "antes_depois": ["antes", "depois"]}
    for campo in obrigatorios.get(tipo, []):
        if d.get(campo) in (None, "", [], {}):
            erros.append(f"falta '{campo}' em {tipo}")
    if tipo in ITENS:
        itens = d.get("linhas" if tipo == "documento" else "itens") or []
        menor, maior = ITENS[tipo]
        if not (menor <= len(itens) <= maior):
            erros.append(f"{tipo} pede de {menor} a {maior} itens (vieram {len(itens)})")
        limite = _ITEM_TEXTO.get(tipo, 70)
        for it in itens:
            if not isinstance(it, dict) or not str(it.get("texto") or it.get("titulo") or "").strip():
                erros.append(f"cada item de {tipo} é um objeto com 'texto'")
                break
            if len(str(it.get("texto") or "")) > limite:
                erros.append(f"item comprido demais em {tipo} (até {limite} letras): \"{str(it.get('texto'))[:50]}...\"")
    for campo, maximo in LIMITES.items():
        valor = d.get(campo)
        if isinstance(valor, str) and len(valor) > maximo:
            erros.append(f"'{campo}' passa de {maximo} letras")
    textos = _textos(tipo, d)
    if any("—" in t or "–" in t for t in textos):
        erros.append("nunca use travessão")
    if tipo == "comparar":
        for lado in ("esq", "dir"):
            c = d.get(lado) or {}
            titulo = _chave(c.get("titulo"))
            if any(_chave(it.get("texto")) == titulo for it in c.get("itens") or [] if isinstance(it, dict)):
                erros.append(f"em comparar, o item de '{lado}' repete o título do lado: escreva o que a fala diz dele")
    if tipo in ("barras",):
        for it in d.get("itens") or []:
            try:
                float(str(it.get("valor")).replace(",", "."))
            except (TypeError, ValueError):
                erros.append("em barras, 'valor' de cada item é um número")
                break
    if tipo == "porcentagem":
        try:
            if not 0 <= float(str(d.get("valor")).replace("%", "").replace(",", ".")) <= 100:
                erros.append("em porcentagem, 'valor' vai de 0 a 100")
        except (TypeError, ValueError):
            erros.append("em porcentagem, 'valor' é um número")
    # número na tela que a fala não diz: inventado (ano e índice de item não contam como dado novo se a fala diz)
    ditos = _numeros(fala) | _numeros(extras)
    tela = set()
    for t in textos:
        tela |= _numeros(t)
    for chave in ("valor", "total", "parte"):
        tela |= _numeros(str(d.get(chave) or ""))
    for it in d.get("itens") or []:
        if isinstance(it, dict):
            tela |= _numeros(str(it.get("valor") or ""))
    novos = [n for n in tela if n not in ditos]
    if novos and not (_EXTENSO.search(fala or "") and not _numeros(fala)):
        erros.append(f"número que a fala não diz: {', '.join(f'{n:g}' for n in novos[:3])}")
    fora = _inventadas(textos, f"{fala} {extras}")
    if len(fora) > 1:
        erros.append(f"palavras que a fala não diz: {', '.join(fora[:5])} (use as palavras da fala)")
    return erros


def planos_tipos(planos) -> list:
    return [p["tipo"] for p in planos.values()]


def plano_de_reserva(fala, vez=0) -> dict:
    """O trecho que o modelo não acertou vira a frase dele mesmo, com a palavra mais longa em destaque; de dois em
    dois, como fato (um cartão com ícone), para a reserva não deixar o vídeo todo igual."""
    frase = re.split(r"(?<=[.!?…])\s+", (fala or "").strip())[0][:118]
    frase = frase.rsplit(" ", 1)[0] if len(frase) == 118 else frase
    palavras = [p for p in re.findall(r"[\wÀ-ú]+", frase) if len(p) >= 6]
    if palavras:
        maior = max(palavras, key=len)
        frase = re.sub(rf"\b{re.escape(maior)}\b", f"*{maior}*", frase, count=1)
    frase = frase.replace("—", ",").replace("–", ",")
    if vez % 2:
        return {"tipo": "fato", "dados": {"texto": frase}}
    return {"tipo": "frase", "dados": {"texto": frase}}


# ------------------------------------------------------------------------------------------------ direção

ESQUEMA = {
    "type": "object",
    "properties": {"trechos": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "tipo": {"type": "string"}, "dados": {"type": "object"}},
        "required": ["id", "tipo", "dados"]}}},
    "required": ["trechos"],
}


def instrucoes() -> str:
    linhas = "\n".join(f"- {tipo}: {para}. Campos: {campos}" for tipo, (para, campos) in CATALOGO.items())
    return f"""Você é o diretor de motion graphics de um canal do YouTube. O vídeo é feito de cenas animadas prontas: para
CADA trecho de fala recebido, escolha um tipo de cena do catálogo e preencha os textos curtos que aparecem na tela.
Responda só em JSON: {{"trechos": [{{"id": N, "tipo": "...", "dados": {{...}}}}]}}, um item por trecho, na ordem.

CATÁLOGO (24 tipos):
{linhas}

REGRAS
- Escolha o tipo pelo que a fala DIZ: número dito vira numero, porcentagem ou barras; datas viram linha_do_tempo;
  itens ditos em sequência viram lista, passos ou checklist; dois lados viram comparar; uma ideia vira frase ou
  pergunta. Nunca invente um gráfico que a fala não sustenta.
- Varie: nunca o mesmo tipo três vezes seguidas; frase e pergunta juntas no máximo um terço do vídeo (o código
  recusa além disso). Coisas ditas em série ("esquenta igual, engrossa igual, queima igual") são lista ou
  destaques; um conselho é checklist ou destaques; um dado curioso é fato; o que alguém disse é citacao; uma
  marca, lei ou relatório é documento; uma notícia é manchete. frase é só para a ideia central do trecho.
- Texto de tela é CURTO e usa as palavras da própria fala. Nunca escreva dado, nome ou número que a fala não diz.
- Números na tela em algarismos ("150 milhões", "1875"). Em *asteriscos* a palavra em destaque (uma ou duas).
- "palavra" é UMA palavra que aparece na fala do trecho, escrita como está nela, no momento em que o elemento deve
  entrar. "palavra#2" é a segunda vez que ela é dita. Prefira dar a palavra de cada item.
- Nunca use travessão (—). Português do Brasil."""


def _pedido(lote, anterior, erros_por_id) -> str:
    partes = []
    if anterior:
        partes.append(f"TIPOS DOS TRECHOS ANTERIORES: {', '.join(anterior[-4:])}")
    for item in lote:
        linha = (f"TRECHO {item['id']} ({item['dur']:.1f} s, bloco: {item['bloco'] or '-'}"
                 f"{', PRIMEIRO do vídeo' if item['posicao'] == 0 else ''}"
                 f"{', ÚLTIMO do vídeo' if item['posicao'] == item['total'] - 1 else ''}):\n{item['fala']}")
        if item["id"] in erros_por_id:
            linha += "\nO PLANO ANTERIOR DESTE TRECHO FOI RECUSADO: " + "; ".join(erros_por_id[item["id"]])
        partes.append(linha)
    return "\n\n".join(partes)


def _marca_do_item(item) -> str:
    return hashlib.sha1(json.dumps([VERSAO_PLANO, item["fala"], item["posicao"] == 0, item["total"]],
                                   ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


VERSAO_PLANO = 1  # suba quando mudar as instruções ou a conferência: os planos guardados são pedidos de novo


def planejar(projeto, itens, log=print, forcar=False) -> dict:
    """{id: {"tipo", "dados"}} para cada trecho, conferido; o que não passar vira a frase da própria fala.
    Os planos ficam em animation_ai/planos.json pela fala do trecho: rodar de novo não pede ao modelo nem grava de novo
    o que não mudou (forcar pede tudo de novo)."""
    from . import openrouter_local

    cfg = config(projeto)
    arquivo = projeto.pasta / "animation_ai" / "planos.json"
    guardados = {} if forcar or not arquivo.exists() else json.loads(arquivo.read_text(encoding="utf-8"))
    planos = {item["id"]: guardados[_marca_do_item(item)] for item in itens if _marca_do_item(item) in guardados}
    if planos:
        log(f"  animation-ai: {len(planos)} trecho(s) com o plano guardado")
    anteriores = []
    por_lote = max(1, int(cfg.get("trechos_por_lote", 6)))
    novos = [item for item in itens if item["id"] not in planos]
    for k in range(0, len(novos), por_lote):
        lote = novos[k:k + por_lote]
        pendentes, erros = list(lote), {}
        for tentativa in range(1 + int(cfg.get("tentativas", 2))):
            try:
                resposta = openrouter_local.perguntar(
                    projeto, "animation-ai: direção", instrucoes(), _pedido(pendentes, anteriores, erros), ESQUEMA,
                    log=log, modelo=openrouter_local.principal(projeto))
            except (Exception, SystemExit) as erro:
                log(f"  animation-ai: a direção não respondeu ({str(erro)[:120]})")
                break
            vieram = {int(t.get("id", -1)): t for t in resposta.get("trechos") or [] if isinstance(t, dict)}
            erros, ainda = {}, []
            for item in pendentes:
                t = vieram.get(item["id"])
                if not t:
                    erros[item["id"]] = ["faltou este trecho na resposta"]
                    ainda.append(item)
                    continue
                tipo, dados = str(t.get("tipo") or "").strip(), t.get("dados") or {}
                feitos = [planos[i]["tipo"] for i in sorted(planos) if i < item["id"]]
                problemas = conferir(tipo, dados, item["fala"], item["extras"], item["posicao"], item["total"],
                                     tuple(feitos[-2:]), sum(t in SIMPLES for t in planos_tipos(planos)))
                if problemas:
                    erros[item["id"]] = problemas
                    ainda.append(item)
                else:
                    planos[item["id"]] = {"tipo": tipo, "dados": dados}
            pendentes = ainda
            if not pendentes:
                break
        for item in pendentes:
            log(f"  animation-ai: trecho {item['id']} sem plano aceito ({'; '.join(erros.get(item['id'], ['sem resposta']))[:160]}); vira a frase da fala")
            planos[item["id"]] = plano_de_reserva(item["fala"], len(planos))
        anteriores = [planos[i]["tipo"] for i in sorted(planos)]
        for item in lote:
            guardados[_marca_do_item(item)] = planos[item["id"]]
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(guardados, ensure_ascii=False, indent=1), encoding="utf-8")
    return planos


# ------------------------------------------------------------------------------------------------ tempos e sons

def _partes_do_numero(valor):
    """'R$ 2,5 bilhões' -> ('R$ ', 2.5, 1, ' bilhões', True). Ano sozinho não conta subindo."""
    m = re.match(r"^(\D*?)(\d[\d.]*(?:,\d+)?)(.*)$", str(valor or "").strip())
    if not m:
        return "", None, 0, str(valor or ""), False
    prefixo, numero, sufixo = m.groups()
    casas = len(numero.split(",")[1]) if "," in numero else 0
    try:
        n = float(numero.replace(".", "").replace(",", "."))
    except ValueError:
        return "", None, 0, str(valor), False
    ano = casas == 0 and 1000 <= n <= 2100 and not sufixo.strip() and "." not in numero
    return prefixo, n, casas, sufixo, not ano


# a tela nunca fica só com o fundo esperando a palavra: no leite, o fato e o causa_efeito esperavam até 2,5 s e o
# começo do trecho saía vazio. O elemento principal entra em até 1 s; com título na tela, o 1º item pode esperar 2,5 s
PRIMEIRO, PRIMEIRO_COM_TITULO = 1.0, 2.5


def resolver_tempos(tipo, dados, palavras, dur):
    """Os dados com o segundo de cada elemento (t, t_titulo, itens[i].t...) e os sons [(segundo, nome)]."""
    d = json.loads(json.dumps(dados))
    fim = max(0.6, dur - 1.0)

    def quando(palavra, padrao, depois=0.0):
        t = tempo_da_palavra(palavra, palavras, depois)
        t = padrao if t is None else max(0.05, t - 0.12)  # entra um pouco antes da palavra chegar
        return round(min(t, fim), 3)

    def distribuir(itens, inicio, ate):
        anterior = -1.0
        n = len(itens)
        for i, it in enumerate(itens):
            padrao = inicio + (ate - inicio) * (i / max(1, n - 1) if n > 1 else 0)
            t = quando(it.get("palavra"), padrao, max(0.0, anterior))
            if i == 0:
                t = min(t, PRIMEIRO_COM_TITULO if tem_cabeca else PRIMEIRO)
            t = max(t, anterior + 0.25) if anterior >= 0 else t
            it["t"] = round(min(t, fim), 3)
            anterior = it["t"]

    tem_cabeca = bool(d.get("titulo") or d.get("kicker"))
    d["t_kicker"], d["t_titulo"] = 0.1, 0.2
    d["t"] = min(quando(d.get("palavra"), 0.3), PRIMEIRO)
    for chave in ("itens", "pontos", "linhas"):
        if isinstance(d.get(chave), list):
            itens = [it for it in d[chave] if isinstance(it, dict)]
            d[chave] = itens
            distribuir(itens, 0.9 if tem_cabeca or chave != "itens" else 0.35, min(dur * 0.72, fim))
    if tipo == "comparar":
        for k, lado in enumerate(("esq", "dir")):
            c = d.get(lado) or {}
            c["t"] = quando(c.get("palavra"), 0.25 if k == 0 else round(dur * 0.42, 3))
            if k == 0:
                c["t"] = min(c["t"], PRIMEIRO)
            itens = [it for it in c.get("itens") or [] if isinstance(it, dict)]
            for i, it in enumerate(itens):
                it["t"] = quando(it.get("palavra"), round(c["t"] + 0.45 + i * 0.4, 3), c["t"])
            c["itens"] = itens
            d[lado] = c
    if tipo == "antes_depois":
        d["antes"] = {**(d.get("antes") or {}), "t": min(quando((d.get("antes") or {}).get("palavra"), 0.25), PRIMEIRO)}
        d["depois"] = {**(d.get("depois") or {}),
                       "t": max(quando((d.get("depois") or {}).get("palavra"), round(dur * 0.45, 3)), d["antes"]["t"] + 0.6)}
    if tipo == "numero":
        d["prefixo"], d["numero"], d["casas"], d["sufixo"], d["contar"] = _partes_do_numero(d.get("valor"))
        if d["numero"] is not None:
            d["valor"] = "0" if d["contar"] else re.sub(r"^\D*?(\d[\d.]*(?:,\d+)?).*$", r"\1", str(dados.get("valor")))
        d["t_legenda"] = round(min(d["t"] + 0.5, fim), 3)
        d["t_nota"] = round(min(d["t"] + 1.0, fim), 3)
    if tipo == "porcentagem":
        d["valor"] = float(str(d.get("valor")).replace("%", "").replace(",", "."))
        d["casas"] = 0 if float(d["valor"]).is_integer() else 1
        d["t_legenda"] = round(min(d["t"] + 0.5, fim), 3)
    if tipo == "barras":
        for it in d.get("itens") or []:
            it["valor"] = float(str(it.get("valor")).replace(",", "."))
    if tipo == "frase":
        d["t_destaque"] = round(min(d["t"] + 0.7, fim), 3)
    if tipo == "documento":
        d["t_carimbo"] = round(max(fim - 0.2, (d.get("linhas") or [{"t": 0}])[-1].get("t", 0) + 0.9), 3)
    if tipo == "encerramento":
        d["t_botao"] = round(min(d["t"] + 0.6, fim), 3)
        d["t_proximo"] = round(min(dur * 0.6, fim), 3)
    if tipo in ("abertura", "capitulo"):
        d["t_titulo"] = max(0.2, min(quando(d.get("palavra"), 0.25), 1.5))
        d["t_sub"] = round(min(d["t_titulo"] + 1.0, fim), 3)
    if tipo == "citacao":
        d["t_autor"] = round(min(d["t"] + 1.0, fim), 3)
    if tipo == "definicao":
        d["t_definicao"] = round(min(d["t"] + 0.6, fim), 3)
    if tipo == "proporcao":
        d["t_legenda"] = round(min(d["t"] + 1.7, fim), 3)
    return d, sons(tipo, d)


def sons(tipo, d) -> list:
    """Os sons no tempo das entradas (os mesmos movimentos do motor.js), no máximo 8, com 0,25 s entre eles."""
    ev = []
    itens = d.get("itens") or []
    if tipo == "abertura":
        ev += [(0.0, "risco"), (d["t_titulo"], "pop"), (d["t_titulo"] + 0.7, "baque")]
    elif tipo in ("capitulo", "pergunta", "manchete"):
        ev.append((d["t_titulo"] if tipo == "capitulo" else d["t"], "baque"))
    elif tipo == "frase":
        ev += [(d["t"], "pop"), (d["t_destaque"], "risco")]
    elif tipo == "numero":
        ev.append((d["t"], "baque"))
        if d.get("contar"):
            ev.append((d["t"] + 0.05, "contagem"))
    elif tipo in ("lista", "checklist", "barras", "ranking"):
        ev += [(it["t"], "risco") for it in itens]
        if tipo == "ranking" and isinstance(d.get("destaque"), int) and 0 <= d["destaque"] < len(itens):
            ev.append((itens[d["destaque"]]["t"], "baque"))
    elif tipo in ("passos", "cartoes", "causa_efeito", "linha_do_tempo"):
        ev += [(it["t"], "pop") for it in itens]
    elif tipo == "comparar":
        ev += [(d["esq"]["t"], "risco"), (d["dir"]["t"], "risco")]
    elif tipo == "destaques":
        ev += [(it["t"], "baque" if i == 0 else "pop") for i, it in enumerate(itens)]
    elif tipo in ("fato", "definicao", "citacao", "documento"):
        ev.append((d["t"], "pop"))
        if tipo == "fato":
            ev.append((d["t"] + 0.25, "baque"))
        if tipo == "documento" and d.get("carimbo"):
            ev.append((d["t_carimbo"], "baque"))
        if tipo == "definicao":
            ev += [(p["t"], "risco") for p in d.get("pontos") or []]
    elif tipo == "porcentagem":
        ev += [(d["t"], "pop"), (d["t"] + 0.05, "contagem")]
    elif tipo == "antes_depois":
        ev += [(d["antes"]["t"], "risco"), (d["depois"]["t"], "baque")]
    elif tipo == "proporcao":
        ev += [(d["t"], "contagem"), (d["t"] + 1.3, "baque")]
    elif tipo == "encerramento":
        ev += [(d["t_botao"], "pop"), (d["t_botao"] + 0.9, "pop")]
    saida = []
    for t, nome in sorted(ev):
        if saida and t - saida[-1][0] < 0.25:
            continue
        saida.append((round(max(0.0, t), 3), nome))
    return saida[:8]


# ------------------------------------------------------------------------------------------------ página e gravação

def tema(projeto) -> dict:
    cfg = config(projeto)
    base = TEMAS.get(cfg.get("tema") or "apple", TEMAS["apple"])
    return {**base, **(cfg.get("cores") or {})}


def montar_html(tipo, dados, dur, cores, canal="") -> str:
    variaveis = "".join(f"--{k}:{v};" for k, v in cores.items() if not k.startswith("_"))
    estilo = {k[1:]: v for k, v in cores.items() if k.startswith("_")}
    dados_js = json.dumps({"tipo": tipo, "s": dados, "dur": round(dur, 3), "canal": canal, "estilo": estilo},
                          ensure_ascii=False)
    css = (RECURSOS / "motor.css").read_text(encoding="utf-8")
    js = (RECURSOS / "motor.js").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="{animacoes.GSAP}"></script>
    <style>
      @font-face {{ font-family: "Titulo"; src: url("assets/fontes/PlayfairDisplay.ttf"); font-weight: 400 900; }}
      @font-face {{ font-family: "Texto"; src: url("assets/fontes/Inter.ttf"); font-weight: 100 900; }}
      :root {{ {variaveis} }}
{css}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{round(dur, 3)}" data-width="1920" data-height="1080">
      <section id="palco" class="clip" data-start="0" data-duration="{round(dur, 3)}" data-track-index="1"></section>
    </div>
    <script>window.AAI = {dados_js};</script>
    <script>
{js}
    </script>
  </body>
</html>
"""


def _pasta(projeto, n) -> Path:
    return projeto.pasta / "animation_ai" / f"{n:04d}"


def assinatura(tipo, dados, dur, cores, canal) -> str:
    motor = (RECURSOS / "motor.js").read_bytes() + (RECURSOS / "motor.css").read_bytes()
    base = json.dumps([VERSAO, tipo, dados, round(dur, 3), cores, canal], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(base.encode("utf-8") + motor).hexdigest()[:16]


def gravar(projeto, trecho, plano, log=print):
    """Grava o trecho e devolve [(n, mp4, capa, duração) de cada cena] e os sons. Levanta RuntimeError se falhar."""
    if not animacoes.node_pronto():
        raise RuntimeError("falta o Node.js 22 ou mais (o HyperFrames grava a cena)")
    cfg = config(projeto)
    ini, fim = float(trecho[0]["ini"]), float(trecho[-1]["fim"])
    dur = max(fim - ini, 1.0)
    palavras = palavras_do_trecho(projeto, ini, fim)
    tipo, dados = plano["tipo"], plano["dados"]
    resolvidos, eventos = resolver_tempos(tipo, dados, palavras, dur)
    cores = tema(projeto)
    canal = str(cfg.get("canal") or "")  # o nome do canal no canto, do perfil (animation_ai.canal); vazio, sem nome
    marca = assinatura(tipo, resolvidos, dur, cores, canal)
    pasta = _pasta(projeto, trecho[0]["n"])
    destino = projeto.pasta / "midia" / f"{trecho[0]['n']:04d}_anim{'_trecho' if len(trecho) > 1 else ''}.mp4"
    partes = pasta / "partes.json"
    anterior = json.loads(partes.read_text(encoding="utf-8")) if partes.exists() else {}
    if anterior.get("assinatura") != marca or not destino.exists():
        pasta.mkdir(parents=True, exist_ok=True)
        animacoes._preparar_pasta(pasta)
        (pasta / "index.html").write_text(montar_html(tipo, resolvidos, dur, cores, canal), encoding="utf-8")
        erros = animacoes._conferir(projeto, pasta, clipe=True)
        if erros:
            raise RuntimeError("a conferência do HyperFrames reprovou: " + "; ".join(erros[:3]))
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(destino.stem + ".tmp.mp4")
        r = animacoes._hyperframes(projeto, ["render", "--output", str(temporario), "--format", "mp4", "--fps",
                                             str(int(cfg.get("fps", 30))), "--workers", "1", "--quiet"], pasta, 900)
        if r.returncode != 0 or not temporario.exists() or temporario.stat().st_size < 1000:
            temporario.unlink(missing_ok=True)
            raise RuntimeError(f"o HyperFrames não gravou a cena: {(r.stderr or r.stdout or '')[-200:]}")
        temporario.replace(destino)
        (pasta / "index.html").unlink(missing_ok=True)
        partes.write_text(json.dumps({"assinatura": marca, "tipo": tipo, "dados": dados, "resolvidos": resolvidos,
                                      "sons": eventos, "dur": round(dur, 3), "cenas": [c["n"] for c in trecho]},
                                     ensure_ascii=False, indent=1), encoding="utf-8")
    saida = []
    for c in trecho:
        inicio = float(c["ini"]) - ini
        dur_c = max(float(c["fim"]) - float(c["ini"]), 0.5)
        if len(trecho) > 1:
            pedaco = projeto.pasta / "midia" / f"{c['n']:04d}_anim.mp4"
            rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-i", str(destino), "-t",
                   f"{dur_c + 0.05:.3f}", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "16",
                   "-pix_fmt", "yuv420p", str(pedaco)])
        else:
            pedaco = destino
        capa = pedaco.with_name(f"{c['n']:04d}_anim_capa.jpg")
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, min(dur_c * 0.7, dur_c - 0.1)):.2f}",
               "-i", str(pedaco), "-frames:v", "1", "-q:v", "3", str(capa)])
        saida.append((c["n"], pedaco, capa, dur_c))
    return saida


def _aplicar(projeto, n, destino, capa, dur, trecho, tipo) -> None:
    """A cena animada entra como a mídia da cena, igual a um vídeo de banco. O que a cena tinha fica em anim_reserva."""
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        c = next(x for x in dados["cenas"] if x["n"] == n)
        if not (e_animada(c) and c.get("anim_reserva")):
            c["anim_reserva"] = {k: c.get(k) for k in ("midia", "tipo", "busca", "captura", "conferencia", "ia_reserva")}
        c["midia"] = {"fonte": FONTE, "id": f"{n:04d}-{int(time.time())}", "tipo": "video",
                      "arquivo": destino.relative_to(projeto.pasta).as_posix(),
                      "capa": capa.relative_to(projeto.pasta).as_posix() if capa.exists() else None,
                      "autor": "", "licenca": "feito pela fábrica", "pagina": "", "duracao": round(dur, 2),
                      "modelo": tipo}
        c["tipo"] = "video_real"
        c["captura"] = {"conferida": True, "animation_ai": True}
        c["anim_trecho"] = list(trecho)
        for campo in ("sem_midia_real", "conferencia", "anim_falhou"):
            c.pop(campo, None)
        projeto.salvar_json("cenas.json", dados)


def _marcar_falha(projeto, numeros, motivo) -> None:
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        for c in dados["cenas"]:
            if c["n"] in numeros:
                c["anim_falhou"] = {"motivo": motivo[:300], "fala": _marca_fala(c)}
        projeto.salvar_json("cenas.json", dados)


def _itens_para_planejar(projeto, grupos) -> list:
    mapa = projeto.ler_json("roteiro_mapa.json") if projeto.existe("roteiro_mapa.json") else {}
    nomes = {b.get("id"): b.get("nome") or "" for b in mapa.get("blocos") or []}
    titulo = mapa.get("titulo") or ""
    canal = str(config(projeto).get("canal") or "")
    itens = []
    for i, g in enumerate(grupos):
        bloco = nomes.get(g[0].get("bloco"), "")
        itens.append({"id": g[0]["n"], "dur": float(g[-1]["fim"]) - float(g[0]["ini"]), "bloco": bloco,
                      "fala": " ".join((c.get("texto") or "").strip() for c in g), "posicao": i, "total": len(grupos),
                      "extras": f"{bloco} {titulo} {canal}" if i == 0 else bloco})
    return itens


def _gravar_grupos(projeto, pares, log=print, frase_de_reserva=True) -> list:
    """Grava cada (cenas, plano) e põe no lugar da mídia. Com frase_de_reserva, o desenho reprovado vai como a frase da
    fala (cenas pedidas pela pessoa); sem ela (complemento), a cena fica com a foto. Devolve as cenas feitas."""
    def um(par):
        g, plano = par
        try:
            try:
                pedacos = gravar(projeto, g, plano, log)
            except RuntimeError as erro:
                if not frase_de_reserva or plano["tipo"] == "frase":
                    raise
                # o desenho do modelo reprovou (texto saindo da tela, sobreposto): a frase da fala, que sempre cabe
                log(f"  animation-ai: cena {g[0]['n']} ({plano['tipo']}) reprovou ({str(erro)[:120]}); vai como frase")
                plano = plano_de_reserva(" ".join(c.get("texto") or "" for c in g))
                pedacos = gravar(projeto, g, plano, log)
            for n, destino, capa, dur in pedacos:
                _aplicar(projeto, n, destino, capa, dur, [c["n"] for c in g], plano["tipo"])
            return g, plano["tipo"], None
        except (Exception, SystemExit) as erro:
            return g, plano["tipo"], str(erro) or erro.__class__.__name__

    feitas = []
    with ThreadPoolExecutor(max(1, int(config(projeto).get("paralelo", 2)))) as executor:
        for g, tipo, erro in executor.map(um, pares):
            numeros = [c["n"] for c in g]
            onde = f"cena {numeros[0]}" if len(numeros) == 1 else f"cenas {numeros[0]} a {numeros[-1]}"
            if erro is None:
                feitas += numeros
                log(f"  animation-ai: {onde} pronta(s) ({tipo})")
            else:
                _marcar_falha(projeto, numeros, erro)
                log(f"  animation-ai: {onde} não saiu ({erro[:160]}); fica com a foto")
    return feitas


def fazer(projeto, cenas, log=print, forcar=False) -> list:
    """Anima as cenas pedidas pela pessoa (`fabrica animation-ai NOME --cenas`), sem perguntar se vale: o modelo só
    escolhe o tipo, com os 24 do catálogo. Devolve as cenas feitas."""
    if not animacoes.node_pronto():
        log("  animation-ai: falta o Node.js 22 ou mais")
        return []
    todas = projeto.ler_json("cenas.json")["cenas"]
    escolhidas = {c["n"] for c in cenas}
    grupos = [g for g in trechos([c for c in todas if c["n"] in escolhidas], config(projeto)) if g]
    if not grupos:
        return []
    log(f"  animation-ai: {len(grupos)} cena(s) animada(s) para {sum(len(g) for g in grupos)} cena(s), de graça")
    planos = planejar(projeto, _itens_para_planejar(projeto, grupos), log, forcar)
    pares = [(g, planos.get(g[0]["n"]) or plano_de_reserva(" ".join(c.get("texto") or "" for c in g))) for g in grupos]
    return _gravar_grupos(projeto, pares, log, frase_de_reserva=True)


# ------------------------------------------------------------------------------------------------ complemento

SO_PEDIDAS = ("abertura", "capitulo", "frase", "pergunta", "encerramento")  # texto da fala sobre fundo: a foto já diz
DE_COMPLEMENTO = [t for t in CATALOGO if t not in SO_PEDIDAS]
VISUAIS_DE_ANIMACAO = ("diagrama", "texto_tela", "linha_do_tempo", "mapa")

_ESTRUTURAS = [
    ("lista", re.compile(r"(?:[^,.;:!?]+,){2,}[^,.;:!?]*\be\b|\b(?:primeir[oa]|segund[oa]|terceir[oa])\b.*"
                         r"\b(?:segund[oa]|terceir[oa]|depois)\b|\b(?:dois|duas|tr[eê]s|quatro|cinco|seis|sete)\s+"
                         r"(?:coisas|motivos|passos|sinais|etapas|regras|tipos|formas|maneiras|erros|dicas|raz[õo]es|"
                         r"fatores|perguntas|segredos)\b", re.I)),
    ("comparação", re.compile(r"\b(?:contra|versus|enquanto|ao contr[aá]rio|diferente d[eoa]s?|em vez de|no lugar de)\b|"
                              r"\b(?:mais|menos)\s+\w+(?:\s+\w+)?\s+(?:que|do que)\b|\bantes\b.{1,60}\b(?:hoje|agora)\b",
                              re.I)),
    ("citação", re.compile(r"\b(?:disse|dizia|escreveu|afirmou|declarou|nas palavras|segundo (?:ele|ela)|como diz)\b|[“\"]",
                           re.I)),
    ("definição", re.compile(r"\b(?:significa|quer dizer|[ée] chamad[oa]|conhecid[oa]s? como|se chama|o termo)\b", re.I)),
    ("documento", re.compile(r"\b(?:lei|decreto|relat[óo]rio|manchete|jornal|reportagem|carta|documento|selo|certificado|"
                             r"patente|contrato|recall|aviso p[úu]blico|registro)\b", re.I)),
    ("causa", re.compile(r"\b(?:por isso|fez com que|levou a|levaram a|resultado|consequ[êe]ncia|acabou (?:com|por))\b",
                         re.I)),
]


def _marca_fala(c) -> str:
    return hashlib.sha1((c.get("texto") or "").encode()).hexdigest()[:10]


def frases_do_video(cenas, cfg) -> list:
    """Cada frase falada: as cenas seguidas do mesmo bloco até o ponto final, até duracao_maxima segundos. Frase
    curta demais (abaixo de duracao_minima) segue junto com a seguinte."""
    maximo, minimo = float(cfg["duracao_maxima"]), float(cfg["duracao_minima"])
    grupos, atual = [], []
    for c in cenas:
        if not _elegivel(c) or (c.get("midia") or {}).get("fonte") == "motion_ia":
            if atual:
                grupos.append(atual)
            atual = []
            continue
        if atual and (c.get("bloco") != atual[-1].get("bloco") or c["n"] != atual[-1]["n"] + 1
                      or float(c["fim"]) - float(atual[0]["ini"]) > maximo):
            grupos.append(atual)
            atual = []
        atual.append(c)
        if _fecha_frase(c.get("texto")) and float(c["fim"]) - float(atual[0]["ini"]) >= minimo:
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    return grupos


def estrutura(grupo) -> str:
    """O que a frase tem que um modelo pronto mostra melhor que a foto, ou "" (narração pura: nem vai ao modelo)."""
    from . import motion_ia

    fala = " ".join((c.get("texto") or "").strip() for c in grupo)
    for c in grupo:
        if c.get("visual") in VISUAIS_DE_ANIMACAO:
            return "o agente pediu " + c["visual"]
    if any(c.get("enumeracao") for c in grupo):
        return "lista"
    palavras = re.findall(r"[a-zà-ú]{4,}", fala.lower())
    if any(palavras.count(p) >= 3 for p in set(palavras)):
        return "lista"  # repetição paralela: "esquenta igual, engrossa igual e queima igual"
    if len(set(re.findall(r"\b(?:1[5-9]\d{2}|20\d{2})\b", fala))) >= 2:
        return "datas"
    for nome, padrao in _ESTRUTURAS:
        if padrao.search(fala):
            return nome
    if motion_ia.dado_na_fala(fala) or motion_ia._PODE_AJUDAR.search(fala):
        return "número"
    return ""


def _o_que_a_foto_mostra(c) -> str:
    texto = (c.get("conferencia") or {}).get("legenda") or (c.get("captura") or {}).get("legenda") or ""
    return re.sub(r"\s+", " ", str(texto))[:220]


ESQUEMA_UTIL = {
    "type": "object",
    "properties": {"trechos": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "nota": {"type": "integer"}, "tipo": {"type": "string"},
                       "dados": {"type": "object"}},
        "required": ["id", "nota", "tipo", "dados"]}}},
    "required": ["trechos"],
}
VERSAO_UTIL = 1  # suba quando mudar as instruções do complemento: as decisões guardadas são pedidas de novo


def instrucoes_util(tipos=None) -> str:
    tipos = tipos or DE_COMPLEMENTO
    linhas = "\n".join(f"- {tipo}: {CATALOGO[tipo][0]}. Campos: {CATALOGO[tipo][1]}" for tipo in tipos)
    return f"""Você é o editor de um documentário do YouTube feito de fotos e vídeos reais. Em alguns momentos, uma cena
animada de modelo pronto (texto e números na tela, entrando no tempo da fala) explica melhor que a foto. Para CADA
trecho recebido, decida se vale trocar a foto por uma cena animada e, se valer, monte a cena.

Responda só em JSON: {{"trechos": [{{"id": N, "nota": 0-100, "tipo": "...", "dados": {{...}}}}]}}, um item por trecho.
- nota: o quanto a cena animada ajuda quem assiste a entender ESTA fala, comparada à foto de hoje. 80 ou mais: a fala
  traz uma estrutura que a foto não mostra (itens ditos em sequência, datas, comparação com os dois lados ditos,
  número com o que ele mede, citação, definição, documento). Abaixo de 50: a foto já mostra o que a fala diz, ou a
  fala é narração, emoção ou cenário. Seja exigente: o vídeo é de fotos, e a cena animada é um complemento raro.
- Com nota abaixo de 50, devolva "tipo": "" e "dados": {{}}.

CATÁLOGO:
{linhas}

REGRAS DA CENA
- Escolha o tipo pelo que a fala DIZ. Nunca invente gráfico, número, nome ou palavra que a fala não diz.
- Texto de tela CURTO, com as palavras da própria fala. Números em algarismos ("150 milhões", "1875"). Em
  *asteriscos* a palavra em destaque (uma ou duas).
- "palavra" é UMA palavra da fala do trecho, escrita como está nela, no momento em que o elemento entra; "palavra#2" é
  a segunda vez que ela é dita. Dê a palavra de cada item.
- Nunca use travessão (—). Português do Brasil."""


def _itens_util(projeto, grupos, todas) -> list:
    mapa = projeto.ler_json("roteiro_mapa.json") if projeto.existe("roteiro_mapa.json") else {}
    nomes = {b.get("id"): b.get("nome") or "" for b in mapa.get("blocos") or []}
    por_n = {c["n"]: c for c in todas}
    itens = []
    for g in grupos:
        antes, depois = por_n.get(g[0]["n"] - 1) or {}, por_n.get(g[-1]["n"] + 1) or {}
        itens.append({"id": g[0]["n"], "grupo": g, "dur": float(g[-1]["fim"]) - float(g[0]["ini"]),
                      "ini": float(g[0]["ini"]), "fim": float(g[-1]["fim"]), "bloco": nomes.get(g[0].get("bloco"), ""),
                      "fala": " ".join((c.get("texto") or "").strip() for c in g), "motivo": estrutura(g),
                      "foto": _o_que_a_foto_mostra(g[0]), "antes": (antes.get("texto") or "")[-160:],
                      "depois": (depois.get("texto") or "")[:160], "extras": nomes.get(g[0].get("bloco"), "")})
    return itens


def _pedido_util(lote, erros) -> str:
    partes = []
    for it in lote:
        linha = (f"TRECHO {it['id']} ({it['dur']:.1f} s, bloco: {it['bloco'] or '-'}, sinal: {it['motivo']})\n"
                 f"antes: ...{it['antes']}\nFALA: {it['fala']}\ndepois: {it['depois']}...\n"
                 f"a foto de hoje mostra: {it['foto'] or '(sem descrição)'}")
        if it["id"] in erros:
            linha += "\nA CENA ANTERIOR DESTE TRECHO FOI RECUSADA: " + "; ".join(erros[it["id"]])
        partes.append(linha)
    return "\n\n".join(partes)


def _marca_util(item, tipos=None) -> str:
    base = [VERSAO_UTIL, item["fala"]] + ([sorted(tipos)] if tipos and list(tipos) != DE_COMPLEMENTO else [])
    return hashlib.sha1(json.dumps(base, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def decidir(projeto, itens, log=print, tipos=None) -> dict:
    """{id: {"nota", "tipo", "dados"}}: a nota de utilidade e, se valer, o plano conferido (sem plano: tipo "").
    Fica em animation_ai/decisoes.json pela fala: rodar de novo não pergunta de novo."""
    from . import openrouter_local

    cfg = config(projeto)
    limiar = float(cfg.get("limiar", 70))
    arquivo = projeto.pasta / "animation_ai" / "decisoes.json"
    guardadas = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}
    tipos = list(tipos or DE_COMPLEMENTO)
    saida = {it["id"]: guardadas[_marca_util(it, tipos)] for it in itens if _marca_util(it, tipos) in guardadas}
    novos = [it for it in itens if it["id"] not in saida]
    por_lote = max(1, int(cfg.get("trechos_por_lote", 6)))
    for k in range(0, len(novos), por_lote):
        pendentes, erros = novos[k:k + por_lote], {}
        for _ in range(2):
            try:
                resposta = openrouter_local.perguntar(projeto, "animation-ai: onde ajuda", instrucoes_util(tipos),
                                                      _pedido_util(pendentes, erros), ESQUEMA_UTIL, log=log,
                                                      modelo=openrouter_local.principal(projeto))
            except (Exception, SystemExit) as erro:
                log(f"  animation-ai: a decisão não respondeu ({str(erro)[:120]})")
                break
            vieram = {int(t.get("id", -1)): t for t in resposta.get("trechos") or [] if isinstance(t, dict)}
            erros, ainda = {}, []
            for it in pendentes:
                t = vieram.get(it["id"])
                if not t:
                    continue
                try:
                    nota = float(t.get("nota") or 0)
                except (TypeError, ValueError):
                    nota = 0.0
                tipo, dados = str(t.get("tipo") or "").strip(), t.get("dados") or {}
                if nota < limiar:
                    saida[it["id"]] = {"nota": nota, "tipo": "", "dados": {}}
                    continue
                problemas = (["use só os tipos do catálogo deste pedido"] if tipo not in tipos
                             else conferir(tipo, dados, it["fala"], it["extras"], 1, 99))
                if problemas:
                    erros[it["id"]] = problemas
                    ainda.append(it)
                    saida[it["id"]] = {"nota": nota, "tipo": "", "dados": {}, "recusada": problemas[:3]}
                else:
                    saida[it["id"]] = {"nota": nota, "tipo": tipo, "dados": dados}
            pendentes = ainda
            if not pendentes:
                break
        for it in novos[k:k + por_lote]:
            if it["id"] in saida:
                guardadas[_marca_util(it, tipos)] = saida[it["id"]]
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps(guardadas, ensure_ascii=False, indent=1), encoding="utf-8")
    return saida


def escolher(itens, decisoes, cfg, duracao_video, ocupados=()) -> list:
    """As que entram no vídeo: nota maior primeiro, até maximo_do_video da duração e longe intervalo_minimo de outra
    cena animada ou clipe de motion (ocupados: [(ini, fim)])."""
    limiar, intervalo = float(cfg.get("limiar", 70)), float(cfg.get("intervalo_minimo", 20))
    orcamento = float(cfg.get("maximo_do_video", 0.12)) * duracao_video
    validos = [it for it in itens if decisoes.get(it["id"], {}).get("tipo")
               and decisoes[it["id"]].get("nota", 0) >= limiar]
    validos.sort(key=lambda it: (-decisoes[it["id"]]["nota"], it["ini"]))
    ocupados, escolhidos = list(ocupados), []
    usado = sum(f - i for i, f in ocupados)
    for it in validos:
        if usado + it["dur"] > orcamento:
            continue
        if any(max(0.0, o_ini - it["fim"], it["ini"] - o_fim) < intervalo for o_ini, o_fim in ocupados):
            continue
        escolhidos.append(it)
        ocupados.append((it["ini"], it["fim"]))
        usado += it["dur"]
    return sorted(escolhidos, key=lambda it: it["ini"])


# o que o Motion IA fazia, no lugar dele (motion_ia.pausado): a cena que ia para a imagem de IA ou que tinha nota baixa
# é decidida sem o filtro de estrutura e sem o ritmo de complemento, com o catálogo inteiro (a ideia abstrata pede frase
# ou pergunta). abertura e encerramento seguem as regras do conferir
COMO_MOTION = [t for t in CATALOGO if t not in ("abertura", "encerramento", "capitulo")]


def nas_uteis(projeto, log=print, numeros=None, como_motion=False) -> list:
    """Troca a foto pela cena animada nas frases em que ela explica melhor, no ritmo de um complemento. Devolve as
    cenas feitas; falhou, a cena fica com a foto. numeros: só as frases que têm alguma dessas cenas. como_motion:
    no lugar do Motion IA (pausado), para as cenas que iam para a imagem de IA ou tinham nota baixa: sem o filtro de
    estrutura, sem o ritmo de complemento e com o catálogo inteiro, como o motion fazia."""
    if not ligado(projeto) or not projeto.existe("cenas.json") or not projeto.existe("alinhamento.json"):
        return []
    if not animacoes.node_pronto():
        log("  animation-ai: falta o Node.js 22 ou mais, as cenas seguem com a foto")
        return []
    cfg = config(projeto)
    todas = projeto.ler_json("cenas.json")["cenas"]
    grupos = []
    for g in frases_do_video(todas, cfg):
        if any(e_animada(c) or (c.get("anim_falhou") or {}).get("fala") == _marca_fala(c) for c in g):
            continue  # já animada, falhou ou a pessoa desfez nesta mesma fala
        if numeros is not None and not any(c["n"] in numeros for c in g):
            continue
        if como_motion or (float(g[-1]["fim"]) - float(g[0]["ini"]) >= float(cfg["duracao_minima"]) and estrutura(g)):
            grupos.append(g)
    if not grupos:
        return []
    itens = _itens_util(projeto, grupos, todas)
    log(f"  animation-ai: {len(itens)} frase(s) com lista, data, número ou comparação; o modelo diz onde a cena "
        f"animada explica melhor que a foto")
    decisoes = decidir(projeto, itens, log, COMO_MOTION if como_motion else None)
    ocupados = [(float(c["ini"]), float(c["fim"])) for c in todas
                if (c.get("midia") or {}).get("fonte") in ("motion_ia", FONTE)]
    duracao = float(projeto.ler_json("alinhamento.json").get("duracao") or todas[-1]["fim"])
    if como_motion:
        # sem teto nem intervalo, como o motion: toda frase que tirou a nota entra
        escolhidos = escolher(itens, decisoes, {**cfg, "maximo_do_video": 10.0, "intervalo_minimo": 0}, duracao)
    else:
        escolhidos = escolher(itens, decisoes, cfg, duracao, ocupados)
    if not escolhidos:
        log("  animation-ai: nenhuma frase pediu cena animada")
        return []
    log(f"  animation-ai: {len(escolhidos)} cena(s) animada(s), de graça: " + ", ".join(
        f"{it['id']} ({decisoes[it['id']]['tipo']}, nota {decisoes[it['id']]['nota']:.0f})" for it in escolhidos))
    pares = [(it["grupo"], {"tipo": decisoes[it["id"]]["tipo"], "dados": decisoes[it["id"]]["dados"]})
             for it in escolhidos]
    return _gravar_grupos(projeto, pares, log, frase_de_reserva=False)


def video_todo(projeto, log=print) -> list:
    """Perfil de vídeo todo em motion (motion-ai, motion-vox) com o Motion IA pausado: toda cena com fala vira cena
    animada antes da busca de fotos, como o motion fazia. A que falhar segue para a foto de banco e depois a IA."""
    todas = projeto.ler_json("cenas.json")["cenas"]
    cenas = [c for c in todas if not (c.get("midia") or {}).get("arquivo") and not c.get("anim_falhou")]
    if not cenas:
        return []
    log(f"  animation-ai: vídeo todo em cenas animadas (no lugar do motion IA), {len(cenas)} cena(s), de graça")
    return fazer(projeto, cenas, log)


def desfazer(projeto, numeros) -> list:
    """Volta as cenas para o que tinham antes da cena animada (anim_reserva)."""
    feitas = []
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        for c in dados["cenas"]:
            if c["n"] in numeros and e_animada(c):
                for k, v in (c.pop("anim_reserva", None) or {}).items():
                    c[k] = v
                if e_animada(c):
                    c["midia"] = None
                c["anim_falhou"] = {"motivo": "desfeita pela pessoa", "fala": _marca_fala(c)}
                c.pop("anim_trecho", None)
                feitas.append(c["n"])
        projeto.salvar_json("cenas.json", dados)
    return feitas


# ------------------------------------------------------------------------------------------------ sons no render

NIVEL = {"pop": 0.0, "risco": -4.0, "baque": 3.0, "contagem": -3.0}


def _sons_do_trecho(projeto, pasta):
    from . import trilha

    try:
        partes = json.loads((pasta / "partes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    eventos = [(t, nome) for t, nome in partes.get("sons") or [] if nome in NIVEL]
    if not eventos:
        return None
    marca = hashlib.sha1(json.dumps([VERSAO, trilha.VERSAO, eventos]).encode()).hexdigest()[:10]
    destino = pasta / f"sons-{marca}.wav"
    if destino.exists():
        return destino
    for velho in pasta.glob("sons-*.wav"):
        velho.unlink(missing_ok=True)
    entradas, grafo = [], []
    for k, (momento, nome) in enumerate(eventos):
        entradas += ["-i", str(trilha._efeito(nome))]
        atraso = round(momento * 1000)
        grafo.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,volume={NIVEL[nome] - 6}dB,"
                     f"adelay={atraso}|{atraso}[s{k}]")
    grafo.append("".join(f"[s{k}]" for k in range(len(eventos))) + f"amix=inputs={len(eventos)}:duration=longest:normalize=0[a]")
    temporario = destino.with_name(destino.stem + ".tmp.wav")
    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(grafo), "-map", "[a]",
           "-t", f"{float(partes.get('dur') or 10) + 1.0:.3f}", "-c:a", "pcm_s16le", str(temporario)])
    temporario.replace(destino)
    return destino


def sons_na_linha(projeto, cenas, log=print) -> list:
    """(segundo da narração, arquivo, volume em dB) dos sons de cada cena animada, para o render."""
    cfg = config(projeto)
    if not cfg.get("sons", True):
        return []
    saida = []
    for c in cenas:
        if not e_animada(c) or (c.get("anim_trecho") and c["n"] != c["anim_trecho"][0]):
            continue
        try:
            arquivo = _sons_do_trecho(projeto, _pasta(projeto, c["n"]))
        except Exception as erro:  # noqa: BLE001 - uma cena sem som não derruba o render
            log(f"  animation-ai: cena {c['n']} ficou sem som ({str(erro)[:100]})")
            continue
        if arquivo is not None:
            saida.append((round(float(c["ini"]), 3), arquivo, float(cfg.get("volume_sons_db", -20))))
    return saida


# ------------------------------------------------------------------------------------------------ catálogo visual

EXEMPLOS = {
    "abertura": {"titulo": "O ouro da Serra", "sub": "Uma riqueza que se mede em tempo", "kicker": "Documentário"},
    "capitulo": {"kicker": "Parte 2", "titulo": "A chegada dos *imigrantes*", "sub": "Encostas íngremes demais para máquinas"},
    "pergunta": {"kicker": "A pergunta", "texto": "Por que a terra mais difícil virou a mais *valiosa*?"},
    "frase": {"texto": "A riqueza não se mede em toneladas. Se mede em *tempo*."},
    "numero": {"valor": "150 milhões", "legenda": "de toneladas de soja por ano", "nota": "a maior safra do mundo"},
    "lista": {"titulo": "O que a serra produz", "itens": [{"texto": "Vinho fino de altitude"}, {"texto": "Charcutaria artesanal"},
                                                         {"texto": "Facas de aço damasco"}, {"texto": "Cachaça envelhecida"}]},
    "checklist": {"titulo": "Para virar Denominação de Origem", "itens": [{"texto": "Uvas da própria região"},
                  {"texto": "Produção controlada"}, {"texto": "Envelhecimento mínimo"}]},
    "passos": {"titulo": "Do parreiral à garrafa", "itens": [{"texto": "Colheita à mão"}, {"texto": "Fermentação"},
               {"texto": "Anos na barrica"}, {"texto": "Garrafa"}], "destaque": 2},
    "comparar": {"esq": {"titulo": "Soja", "itens": [{"texto": "Toneladas por hectare"}, {"texto": "Máquinas grandes"}]},
                 "dir": {"titulo": "Vinhedo", "itens": [{"texto": "Valor por garrafa"}, {"texto": "Trabalho à mão"}]}, "neutro": True},
    "barras": {"titulo": "Valor por hectare", "itens": [{"rotulo": "Vinhedo", "valor": 60, "texto": "R$ 60 mil"},
               {"rotulo": "Soja", "valor": 8, "texto": "R$ 8 mil"}], "fonte": "Embrapa"},
    "linha_do_tempo": {"titulo": "A história da serra", "itens": [{"data": "1875", "texto": "Chegam os imigrantes"},
                       {"data": "1931", "texto": "Primeira cooperativa"}, {"data": "2002", "texto": "Indicação de procedência"}]},
    "citacao": {"texto": "Aqui a gente não planta para colher amanhã. Planta para os *netos*.", "autor": "Produtor de Bento Gonçalves"},
    "definicao": {"termo": "Terroir", "definicao": "O conjunto de solo, clima e tradição que dá ao vinho o gosto do lugar.",
                  "pontos": [{"texto": "Solo de basalto"}, {"texto": "Noites frias"}]},
    "cartoes": {"titulo": "Três caminhos", "itens": [{"titulo": "Vinho", "texto": "Anos de espera, valor alto"},
                {"titulo": "Queijo", "texto": "Meses de cura na caverna"}, {"titulo": "Cachaça", "texto": "Barris de madeira nativa"}]},
    "destaques": {"titulo": "Os três erros", "itens": [{"texto": "Plantar soja na encosta"}, {"texto": "Colher cedo demais"},
                  {"texto": "Vender a granel"}], "marca": "errado"},
    "fato": {"kicker": "Curiosidade", "texto": "Há caves escavadas na rocha com mais de 100 anos que ainda guardam vinho.", "fonte": "IBRAVIN"},
    "porcentagem": {"valor": 85, "legenda": "do vinho fino brasileiro sai da Serra Gaúcha"},
    "antes_depois": {"antes": {"rotulo": "Granel", "valor": "R$ 3"}, "depois": {"rotulo": "Garrafa", "valor": "R$ 90"},
                     "legenda": "o mesmo litro, depois de envelhecer"},
    "ranking": {"titulo": "Maiores produtores", "itens": [{"texto": "Bento Gonçalves"}, {"texto": "Flores da Cunha"},
                {"texto": "Garibaldi"}, {"texto": "Caxias do Sul"}], "destaque": 0},
    "causa_efeito": {"itens": [{"texto": "Terra íngreme demais"}, {"texto": "Sem espaço para máquinas"},
                     {"texto": "Produzir menos e melhor"}, {"texto": "Valor alto por garrafa"}]},
    "proporcao": {"total": 10, "parte": 7, "rotulo": "7 em 10", "legenda": "garrafas de espumante do país vêm da serra"},
    "documento": {"titulo": "Indicação de Procedência", "linhas": [{"texto": "Vale dos Vinhedos, Rio Grande do Sul"},
                  {"texto": "Reconhecida em 2002"}, {"texto": "Primeira do Brasil"}], "carimbo": "Aprovado"},
    "manchete": {"veiculo": "Diário da Serra", "data": "22 nov 2002", "titulo": "Vale dos Vinhedos ganha o *primeiro selo* do Brasil",
                 "sub": "Região passa a ter origem reconhecida"},
    "encerramento": {"texto": "Gostou? *Se inscreva* para o próximo", "proximo": "A cachaça que envelhece 20 anos"},
}


def catalogo(projeto, destino: Path, tema_nome=None, log=print) -> Path:
    """Uma folha com um quadro de cada tipo, no tema do projeto (ou no pedido): para ver o visual sem gravar vídeo."""
    from PIL import Image, ImageDraw

    cores = TEMAS.get(tema_nome) if tema_nome else tema(projeto)
    pasta = destino.parent / f"_catalogo_animation_ai_{tema_nome or 'projeto'}"
    shutil.rmtree(pasta, ignore_errors=True)
    quadros = []
    for tipo, exemplo in EXEMPLOS.items():
        sub = pasta / tipo
        sub.mkdir(parents=True, exist_ok=True)
        animacoes._preparar_pasta(sub)
        dur = 6.0
        resolvidos, _ = resolver_tempos(tipo, exemplo, [], dur)
        (sub / "index.html").write_text(montar_html(tipo, resolvidos, dur, cores, "Canal"), encoding="utf-8")
        r = animacoes._hyperframes(projeto, ["snapshot", "--at", "5.8", "--describe=false", "-o", str(sub / "q"), "."], sub, 240)
        achado = sorted((sub / "q").glob("*.png")) + sorted((sub / "q").glob("*.jpg"))
        achado = [a for a in achado if "contact" not in a.name]
        if r.returncode != 0 or not achado:
            log(f"  {tipo}: o quadro não saiu ({(r.stderr or r.stdout or '')[-160:]})")
            continue
        quadros.append((tipo, achado[0]))
        log(f"  {tipo}: ok")
    colunas, w, h = 4, 640, 360
    folha = Image.new("RGB", (colunas * (w + 10) + 10, ((len(quadros) + colunas - 1) // colunas) * (h + 40) + 10), (20, 20, 24))
    desenho = ImageDraw.Draw(folha)
    for i, (tipo, arquivo) in enumerate(quadros):
        x, y = 10 + (i % colunas) * (w + 10), 10 + (i // colunas) * (h + 40)
        folha.paste(Image.open(arquivo).convert("RGB").resize((w, h)), (x, y + 30))
        desenho.text((x + 4, y + 8), tipo, fill=(240, 240, 240))
    folha.save(destino, quality=88)
    return destino
