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
   que a foto de hoje mostra, dá a nota de utilidade (0 a 100) e, se valer, escolhe um dos tipos de conteúdo do
   `CATALOGO` (30 layouts; abertura, capitulo, frase, pergunta, encerramento, palavra_chave e revelacao são só do modo
   de cenas pedidas). Cada layout sai em qualquer um dos 8 estilos do `TEMAS` (30 x 8 = 240 modelos prontos) e escreve os textos
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
VERSAO = 4  # suba quando mudar o desenho (motor.js, motor.css, motor_impacto.* ou TEMAS): os trechos são gravados de novo
# 4 (2026-10-13): kicker de 34 px sem caixa-alta espaçada; transição de cena com chegada desacelerando e saída acelerando
RECURSOS = Path(__file__).parent / "recursos" / "animation_ai"
_TRAVA_CENAS = threading.Lock()

TEMAS = {
    # o padrão desde 2026-10-13 (pedido do usuário: "transforme essas receitas em modelos que a fábrica monta sozinha e
    # fixo na fábrica"): motor próprio (motor_impacto.js), com a foto da cena atrás, letra gigante, uma cor de destaque
    # (amarelo; vermelho no outro lado da comparação), brilho, grão e a cena se montando peça por peça. Saiu do protótipo
    # em teste-estilos/prototipo. Os tipos sem receita própria não são oferecidos (TIPOS_IMPACTO)
    "impacto": {"fundo": "#07080A", "txt": "#F5F3EE", "txt2": "#D9D4CA", "acc": "#FFD23F", "acc2": "#FF4D3D",
                "brilho-a": "rgba(77,163,255,.20)", "brilho-b": "rgba(255,210,63,.14)", "_motor": "impacto"},
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
    # os 4 estilos completos de 2026-10-13 (pedido do usuário: mais de 200 modelos prontos = 30 layouts x 8 estilos). Cada
    # um traz cor, fundo animado (canvas, `_fundo`), jeitos de entrar (`_entradas`), de mexer a câmera (`_cameras`) e de
    # sair (`_saidas`); dentro do estilo, a cena escolhe entre eles pelo número dela (`variante`), então o vídeo fica
    # coerente e as cenas não se repetem. Ideias de categoria (câmera, transição, tipografia, efeitos) do video-shotcraft
    # (Apache-2.0); o código é nosso
    "neon": {"fundo": "#05070D", "painel": "#0B1220", "painel2": "#101B30", "linha": "#16314D", "txt": "#EAF6FF",
             "txt2": "#A9C4DA", "mut": "#6F8BA3", "acc": "#00E5FF", "acc2": "#FF2BD6", "verm": "#FF3B6B", "ok": "#3DFFA2",
             "tinta": "#04121A", "papel": "#EAF6FF", "brilho1": "transparent", "brilho2": "transparent",
             "ponto": "transparent", "sombra": "rgba(0,229,255,.18)", "sombra-card": "0 0 38px rgba(0,229,255,.16)",
             "card-borda": "1px solid rgba(0,229,255,.55)", "raio-card": "10px", "raio-selo": "8px",
             "vinheta": "transparent", "faixa": "rgba(0,0,0,0)", "f-tit": '"Texto"', "peso-tit": "900",
             "esp-tit": "0.01em", "caixa": "uppercase", "f-d": '"Texto"', "estilo-d": "normal", "peso-d": "900",
             "f-num": '"Texto"', "f-txt": '"Texto"', "sombra-txt": "0 0 26px rgba(0,229,255,.5)",
             "_fundo": "hud", "_entradas": ["scan", "glitch"], "_cameras": ["soco", "tilt"], "_saidas": ["wipe", "flash"]},
    "riso": {"fundo": "#F3EEE3", "painel": "#FFFBF2", "painel2": "#EFE7D6", "linha": "#1B1B1B", "txt": "#1B1B1B",
             "txt2": "#3A3A3A", "mut": "#7A7468", "acc": "#E11D48", "acc2": "#2547FF", "verm": "#E11D48", "ok": "#0E9F6E",
             "tinta": "#FFFBF2", "papel": "#FFFBF2", "brilho1": "transparent", "brilho2": "transparent",
             "ponto": "transparent", "sombra": "rgba(27,27,27,.3)", "sombra-card": "7px 7px 0 #1B1B1B",
             "card-borda": "3px solid #1B1B1B", "raio-card": "4px", "raio-selo": "4px", "vinheta": "transparent",
             "faixa": "rgba(27,27,27,.5)", "faixa-altura": "230px", "f-tit": '"Texto"', "peso-tit": "900",
             "esp-tit": "-0.03em", "caixa": "uppercase", "f-d": '"Texto"', "estilo-d": "normal", "peso-d": "900",
             "f-num": '"Texto"', "f-txt": '"Texto"',
             "_fundo": "papel", "_entradas": ["carimbo", "traco"], "_cameras": ["derivar"], "_saidas": ["wipe", "iris"],
             "_tremer": False},
    "blueprint": {"fundo": "#0A2A4D", "painel": "rgba(10,42,77,.72)", "painel2": "#103A66", "linha": "#4F86B8",
                  "txt": "#EAF3FF", "txt2": "#B5D0EC", "mut": "#7FA3C6", "acc": "#FFD166", "acc2": "#7FD6FF",
                  "verm": "#FF8A7A", "verm-papel": "#C8321F", "botao": "#D7392A", "botao-clicado": "#4F6A86", "ok": "#7DE3A8", "tinta": "#0A2A4D", "papel": "#EAF3FF", "brilho1": "transparent",
                  "brilho2": "transparent", "ponto": "transparent", "sombra": "rgba(0,0,0,.25)", "sombra-card": "none",
                  "card-borda": "2px dashed #7FB6E8", "raio-card": "4px", "raio-selo": "4px", "vinheta": "transparent",
                  "faixa": "rgba(0,0,0,0)", "f-tit": '"Texto"', "peso-tit": "800", "esp-tit": "0.02em", "caixa": "none",
                  "f-d": '"Texto"', "estilo-d": "normal", "peso-d": "800", "f-num": '"Texto"', "f-txt": '"Texto"',
                  "_fundo": "planta", "_entradas": ["traco", "desfoca"], "_cameras": ["derivar", "assentar"],
                  "_saidas": ["iris", "fade"], "_tremer": False},
    "cinema": {"fundo": "#110C09", "painel": "rgba(30,20,14,.78)", "painel2": "#241810", "linha": "#4A3622",
               "txt": "#F6EBDD", "txt2": "#D2BFA6", "mut": "#9C8870", "acc": "#E8A33D", "acc2": "#D1613B",
               "verm": "#D1613B", "ok": "#9CB86A", "tinta": "#110C09", "papel": "#F2E6D0", "brilho1": "transparent",
               "brilho2": "transparent", "ponto": "transparent", "sombra": "rgba(0,0,0,.55)",
               "sombra-card": "0 30px 70px rgba(0,0,0,.55)", "card-borda": "1px solid rgba(232,163,61,.35)",
               "raio-card": "14px", "raio-selo": "12px", "vinheta": "transparent", "faixa": "rgba(0,0,0,0)",
               "f-tit": '"Titulo"', "peso-tit": "700", "esp-tit": "-0.01em", "caixa": "none", "f-d": '"Titulo"',
               "estilo-d": "italic", "peso-d": "700", "f-num": '"Texto"', "f-txt": '"Texto"',
               "sombra-txt": "0 6px 40px rgba(0,0,0,.5)",
               "_fundo": "filme", "_entradas": ["desfoca", "scan"], "_cameras": ["derivar", "tilt"],
               "_saidas": ["fade", "flash"], "_tremer": False},
    # escuro, azul-noite com âmbar: serve para quase tudo
    "noite": {"fundo": "#0E1420", "painel": "#161F2E", "painel2": "#1E2A3D", "linha": "#2B3850", "txt": "#F1F4F8",
              "txt2": "#C5CEDB", "mut": "#8794A8", "acc": "#F5B83D", "acc2": "#4FD1C5", "verm": "#F0575D",
              "verm-papel": "#B3262E", "ok": "#43C58A", "tinta": "#0E1420", "papel": "#EFE8D8", "brilho1": "rgba(245,184,61,.10)",
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
                 "vinheta": "rgba(0,0,0,.5)", "faixa": "rgba(0,0,0,0)", "f-tit": '"Texto"', "peso-tit": "900",
                 "esp-tit": "0.01em", "caixa": "uppercase", "f-d": '"Titulo"', "estilo-d": "italic", "peso-d": "700",
                 "f-num": '"Texto"', "f-txt": '"Texto"'},
}

# os 30 tipos: para que servem e os campos de cada um. "palavra" é a palavra da fala em que o elemento entra
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
    # os 6 de 2026-10-13, das categorias de tipografia, dados, abertura e entrada de cartões do video-shotcraft
    "palavra_chave": ("UMA palavra que carrega o trecho, enorme, com palavras de apoio em volta",
                      "termo (a palavra-chave da fala, até 18 letras), kicker?, itens: [{texto, palavra?}] (2 a 4, curtos), palavra?"),
    "medidor": ("um valor num mostrador de ponteiro: nível, intensidade, risco, quanto de um máximo",
                "valor (como dito: '85%', '72 km/h'), legenda, maximo? (número só da escala; sem ele, % vai a 100), palavra?"),
    "grafico_linha": ("uma evolução ao longo do tempo ou das etapas, de 3 a 6 valores ditos",
                      "titulo?, itens: [{rotulo, valor (número), texto?, palavra?}] (3 a 6, na ordem), fonte?"),
    "deslizar": ("dois estados lado a lado revelados por uma régua que desliza: antes e depois, antigo e novo",
                 "antes: {rotulo, valor, palavra?}, depois: {rotulo, valor, palavra?}, legenda?"),
    "revelacao": ("título que se materializa, com um brilho que passa por cima; SÓ no modo de cenas pedidas",
                  "titulo (com *destaque*), sub?, kicker?, palavra?"),
    "pilha_cartoes": ("de 3 a 5 ideias empilhadas, cada uma cobrindo a anterior", "titulo?, itens: [{titulo, texto, palavra?}] (3 a 5)"),
}
ITENS = {"lista": (2, 6), "checklist": (2, 6), "passos": (2, 5), "barras": (2, 5), "linha_do_tempo": (2, 5),
         "cartoes": (2, 3), "destaques": (2, 4), "ranking": (3, 5), "causa_efeito": (2, 4), "documento": (2, 5),
         "palavra_chave": (2, 4), "grafico_linha": (3, 6), "pilha_cartoes": (3, 5)}
LIMITES = {"titulo": 64, "texto": 120, "legenda": 90, "sub": 110, "kicker": 32, "nota": 80, "autor": 50,
           "definicao": 160, "termo": 40, "rotulo": 40, "data": 14, "valor": 24, "veiculo": 30, "fonte": 50,
           "proximo": 70, "carimbo": 18}
_ITEM_TEXTO = {"lista": 70, "checklist": 70, "passos": 46, "destaques": 70, "ranking": 60, "causa_efeito": 60,
               "documento": 64, "linha_do_tempo": 60, "cartoes": 110, "palavra_chave": 24, "grafico_linha": 40,
               "pilha_cartoes": 100}
_PALAVRAS_LIVRES = {"mais", "menos", "como", "para", "pelo", "pela", "pelos", "pelas", "isso", "esse", "essa", "este",
                    "esta", "cada", "muito", "muita", "sobre", "entre", "quando", "onde", "sendo", "hoje", "antes",
                    "depois", "parte", "total", "fonte", "nunca", "sempre", "porque", "também", "tambem"}


def config(projeto) -> dict:
    padrao = {"ativo": True, "tema": "impacto", "duracao_alvo": 8, "duracao_maxima": 12, "duracao_minima": 3,
              "limiar": 70, "maximo_do_video": 0.12, "intervalo_minimo": 20, "trechos_por_lote": 6,
              "tentativas": 2, "paralelo": 2, "fps": 30, "canal": "", "sons": True, "volume_sons_db": -20,
              "fotos_nos_itens": True, "maximo_no_lugar_do_motion": 0.25}
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


SIMPLES = ("frase", "pergunta", "palavra_chave", "revelacao")


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
                    "palavra_chave": ["termo"], "medidor": ["valor", "legenda"], "deslizar": ["antes", "depois"],
                    "revelacao": ["titulo"],
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
            if not isinstance(it, dict) or not str(it.get("texto") or it.get("titulo") or it.get("rotulo") or "").strip():
                erros.append(f"cada item de {tipo} é um objeto com 'texto'")
                break
            if len(str(it.get("texto") or "")) > limite:
                erros.append(f"item comprido demais em {tipo} (até {limite} letras): \"{str(it.get('texto'))[:50]}...\"")
        # cena 47 do brasil-selvagem: "a cada dois ou três anos" em dois itens seguidos, só com outro destaque
        textos_itens = [_chave(str(it.get("texto") or it.get("titulo") or "").replace("*", ""))
                        for it in itens if isinstance(it, dict)]
        if len(set(textos_itens)) < len(textos_itens):
            erros.append(f"dois itens de {tipo} com o mesmo texto: cada item é uma coisa diferente dita na fala")
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
    if tipo == "palavra_chave" and len(str(d.get("termo") or "").replace("*", "")) > 18:
        erros.append("em palavra_chave, 'termo' é UMA palavra de até 18 letras")
    if tipo in ("barras", "grafico_linha"):
        for it in d.get("itens") or []:
            try:
                float(str(it.get("valor")).replace(",", "."))
            except (TypeError, ValueError):
                erros.append(f"em {tipo}, 'valor' de cada item é um número")
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

CATÁLOGO ({len(CATALOGO)} tipos):
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
- Em lista, checklist, destaques e cartoes, cada item entra na tela com a FOTO da coisa que ele cita (a cena em
  que ela é falada): dê a "palavra" de cada item no momento em que a COISA é dita, pelo nome dela ("castanheira",
  não "como"). Item é uma coisa diferente citada em série; nunca pique uma frase comum em pedaços nem repita o mesmo
  trecho em dois itens.
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


VERSAO_PLANO = 2  # suba quando mudar as instruções ou a conferência: os planos guardados são pedidos de novo


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
    if tipo in ("antes_depois", "deslizar"):
        d["antes"] = {**(d.get("antes") or {}), "t": min(quando((d.get("antes") or {}).get("palavra"), 0.25), PRIMEIRO)}
        d["depois"] = {**(d.get("depois") or {}),
                       "t": max(quando((d.get("depois") or {}).get("palavra"), round(dur * 0.45, 3)), d["antes"]["t"] + 0.6)}
    if tipo == "medidor":
        d["prefixo"], d["numero"], d["casas"], d["sufixo"], d["contar"] = _partes_do_numero(d.get("valor"))
        try:
            maximo = float(str(d.get("maximo")).replace(",", "."))
        except (TypeError, ValueError):
            maximo = 0.0
        if d["numero"] is None:
            d["fracao"] = 0.7
        elif maximo > 0:
            d["fracao"] = max(0.0, min(1.0, d["numero"] / maximo))
        elif "%" in str(d.get("valor") or ""):
            d["fracao"] = max(0.0, min(1.0, d["numero"] / 100))
        else:
            d["fracao"] = 0.72  # sem máximo dito, o ponteiro vai a três quartos: mostra que é "alto", sem inventar escala
        d["valor"] = "0" if d["contar"] and d["numero"] is not None else re.sub(
            r"^\D*?(\d[\d.]*(?:,\d+)?).*$", r"\1", str(dados.get("valor")))
        d["t_legenda"] = round(min(d["t"] + 0.9, fim), 3)
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
    if tipo in ("barras", "grafico_linha"):
        for it in d.get("itens") or []:
            it["valor"] = float(str(it.get("valor")).replace(",", "."))
    if tipo == "frase":
        d["t_destaque"] = round(min(d["t"] + 0.7, fim), 3)
    if tipo == "documento":
        d["t_carimbo"] = round(max(fim - 0.2, (d.get("linhas") or [{"t": 0}])[-1].get("t", 0) + 0.9), 3)
    if tipo == "encerramento":
        d["t_botao"] = round(min(d["t"] + 0.6, fim), 3)
        d["t_proximo"] = round(min(dur * 0.6, fim), 3)
    if tipo in ("abertura", "capitulo", "revelacao"):
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
    elif tipo in ("capitulo", "pergunta", "manchete", "revelacao"):
        ev.append((d["t_titulo"] if tipo in ("capitulo", "revelacao") else d["t"], "baque"))
    elif tipo == "palavra_chave":
        ev += [(d["t"], "baque")] + [(it["t"], "pop") for it in itens]
    elif tipo == "medidor":
        ev += [(d["t"], "pop"), (d["t"] + 0.05, "contagem")]
    elif tipo == "grafico_linha":
        ev += [(it["t"], "risco") for it in itens]
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
    elif tipo in ("passos", "cartoes", "causa_efeito", "linha_do_tempo", "pilha_cartoes"):
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
    elif tipo in ("antes_depois", "deslizar"):
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



def _t(v, padrao):
    """O T do motor do impacto: o segundo que veio nos dados ou, sem ele, o de sempre."""
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else padrao


def sons_impacto(tipo, d, dur) -> list:
    """Os sons no tempo das receitas do motor_impacto.js (QUAL): o baque no soco e no flash, o risco no que chega
    deslizando, o pop no que aparece, a contagem no número que sobe. No máximo 8, com 0,25 s entre eles."""
    ev = []
    itens = [it for it in d.get("itens") or [] if isinstance(it, dict)]
    if tipo in ("numero", "porcentagem", "medidor", "proporcao"):
        t = _t(d.get("t"), 0.3)
        ev.append((t, "baque"))
        if tipo == "porcentagem" or (tipo == "numero" and d.get("contar") and isinstance(d.get("numero"), (int, float))):
            ev.append((t + 0.3, "contagem"))
    elif tipo in ("lista", "destaques", "checklist", "cartoes", "pilha_cartoes", "ranking", "passos"):
        selo = tipo in ("lista", "passos", "ranking", "pilha_cartoes", "checklist") or d.get("marca")
        for i, it in enumerate(it for it in itens if it.get("texto") or it.get("titulo")):
            t = _t(it.get("t"), 0.4 + i * 0.8)
            ev.append((max(0.0, t - 0.1), "risco"))
            if selo:
                ev.append((t + 0.3, "pop"))
    elif tipo in ("comparar", "antes_depois", "deslizar"):
        lados = [d.get(k) or {} for k in (("esq", "dir") if tipo == "comparar" else ("antes", "depois"))]
        t0 = _t(lados[0].get("t"), 0.3)
        t1 = max(_t(lados[1].get("t"), dur * 0.45), t0 + 0.8)
        ev += [(max(0.0, t0 - 0.1), "risco"), (t1, "baque")]
        if tipo != "comparar":
            ev += [(t0 + 0.3, "contagem"), (t1 + 0.3, "contagem")]
    elif tipo in ("causa_efeito", "linha_do_tempo") and len([it for it in itens if it.get("texto") or it.get("data")]) >= 2:
        validos = [it for it in itens if it.get("texto") or it.get("data")]
        fontes, destino = validos[:-1], validos[-1]
        ev += [(_t(it.get("t"), 0.3 + i * 0.7), "pop") for i, it in enumerate(fontes)]
        t_dest = max(_t(destino.get("t"), dur * 0.6), _t(fontes[-1].get("t"), 0) + 0.6)
        ev += [(max(0.0, t_dest - 0.35), "risco"), (t_dest + 0.15, "baque")]
    elif tipo in ("abertura", "capitulo", "revelacao", "encerramento"):
        tt = _t(d.get("t_titulo"), _t(d.get("t"), 0.3))
        if d.get("kicker"):
            ev.append((_t(d.get("t_kicker"), 0.1), "risco"))
        ev.append((tt, "baque"))
        if d.get("sub") or d.get("proximo"):
            ev.append((_t(d.get("t_sub"), tt + 1.0), "pop"))
    else:  # a receita da frase (e quem cai nela)
        t = _t(d.get("t"), 0.3)
        ev.append((t, "baque"))
        if tipo == "palavra_chave":
            ev += [(_t(it.get("t"), t + 0.6 + i * 0.4), "pop") for i, it in enumerate(itens)]
    saida = []
    for t, nome in sorted(ev):
        if t >= dur or (saida and t - saida[-1][0] < 0.25):
            continue
        saida.append((round(max(0.0, t), 3), nome))
    return saida[:8]

# ------------------------------------------------------------------------------------------------ página e gravação

def tema(projeto) -> dict:
    cfg = config(projeto)
    base = TEMAS.get(cfg.get("tema") or "impacto", TEMAS["impacto"])
    return {**base, **(cfg.get("cores") or {})}


def e_impacto(cores) -> bool:
    """O tema desenha com o motor do impacto (motor_impacto.js): foto, letra gigante, cena que se monta."""
    return cores.get("_motor") == "impacto"


# os tipos que têm receita no motor do impacto (motor_impacto.js, QUAL). Barras, gráfico de linha e afins ficam de fora
# da escolha: no impacto eles virariam só uma frase
TIPOS_IMPACTO = ("numero", "porcentagem", "medidor", "proporcao", "frase", "pergunta", "fato", "palavra_chave",
                 "citacao", "definicao", "manchete", "documento", "lista", "destaques", "checklist", "cartoes",
                 "pilha_cartoes", "ranking", "passos", "comparar", "antes_depois", "deslizar", "causa_efeito",
                 "linha_do_tempo", "abertura", "capitulo", "revelacao", "encerramento")
# no impacto, toda receita de vários itens mostra a foto de cada um
COM_FOTO_IMPACTO = ("lista", "checklist", "destaques", "cartoes", "pilha_cartoes", "ranking", "passos",
                    "causa_efeito", "linha_do_tempo")


def tipos_do_tema(projeto, tipos=None) -> list:
    """Os tipos que o modelo pode escolher: no impacto, só os que têm receita."""
    base = list(tipos or DE_COMPLEMENTO)
    return [t for t in base if t in TIPOS_IMPACTO] if e_impacto(tema(projeto)) else base


def com_variante(cores) -> bool:
    """O estilo tem jeitos de entrar, de mexer a câmera ou de sair que variam de cena para cena."""
    return any(k in cores for k in ("_entradas", "_cameras", "_saidas", "_fundo"))


def montar_html(tipo, dados, dur, cores, canal="", variante=0) -> str:
    variaveis = "".join(f"--{k}:{v};" for k, v in cores.items() if not k.startswith("_"))
    estilo = {k[1:]: v for k, v in cores.items() if k.startswith("_")}
    dados_js = json.dumps({"tipo": tipo, "s": dados, "dur": round(dur, 3), "canal": canal, "estilo": estilo,
                           "variante": int(variante)}, ensure_ascii=False)
    motor = "motor_impacto" if e_impacto(cores) else "motor"
    css = (RECURSOS / f"{motor}.css").read_text(encoding="utf-8")
    js = (RECURSOS / f"{motor}.js").read_text(encoding="utf-8")
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


# ------------------------------------------------------------------------------------------------ fotos dos itens

# pedido do usuário em 2026-10-11 ("mostrar cenas do banco de imagens junto com esses motion, para as palavras não
# ficarem soltas"): na lista do ninho, da castanheira e da sumaúma (cenas 44 a 46 do brasil-selvagem) só havia texto
# num fundo creme. Cada item ganha a foto da coisa que ele cita, entrando junto com ele (motor.js, pilha e cartoes).
# A foto é a que a cena daquele momento já tinha (baixada e julgada pelo Jev, de graça); a cena sem foto boa busca
# uma nos bancos pelo pedido dela, e a visão confere que mostra a coisa
COM_FOTO = ("lista", "checklist", "destaques", "cartoes")
MINIMO_DE_FOTOS = 2  # menos que isso, a lista fica só com o texto: uma foto para cinco itens parece engano
FONTES_DA_FOTO = ("wikimedia", "inaturalist", "pexels", "pixabay", "unsplash")
VERSAO_FOTOS = 4  # suba quando mudar a busca ou a escolha: as fotos guardadas são buscadas de novo

INSTRUCOES_FOTO_ITEM = """Você escolhe a foto de um item de uma lista animada de um documentário. Cada número da folha
é uma foto. Ela entra ao lado do texto do item, no momento em que a narração cita a coisa, então tem de mostrar
EXATAMENTE a coisa citada (a espécie, a árvore, o lugar, o objeto), grande e bem visível, e o mínimo que a cena pede
(a fase, o comportamento: filhote no ninho, bicho caçando). Nunca outra coisa parecida, desenho, mapa, gráfico, texto,
colagem, montagem ou marca-d'água, e nunca pessoa, mão, luva, gaiola ou zoológico se o item não cita (a águia na luva
de um falcoeiro não é "aprendendo a caçar"). Responda o número da melhor foto, ou -1 se nenhuma mostra a coisa."""

ESQUEMA_FOTO_ITEM = {"type": "object", "properties": {"numero": {"type": "integer"}, "motivo": {"type": "string"}},
                     "required": ["numero"]}


def _o_que_a_cena_tinha(c) -> dict:
    """Os campos da cena antes da animação (a reserva, se ela já foi animada)."""
    return (c.get("anim_reserva") or {}) if e_animada(c) else c


def _foto_da_cena(projeto, c):
    """(arquivo, crédito) da foto ou do vídeo que a cena mostrava, se ninguém disse que é outra coisa; ou None."""
    from . import corrigir

    antes = _o_que_a_cena_tinha(c)
    m = antes.get("midia") or {}
    if not m.get("arquivo") or m.get("fonte") in (FONTE, "motion_ia"):
        return None
    captura = antes.get("captura") or {}
    if corrigir.errada(antes.get("conferencia")) or (captura.get("suspeita") and not antes.get("conferencia")):
        return None  # o tapa-buraco e o suspeito sem julgamento ficam de fora: na lista, foto errada salta aos olhos
    caminho = projeto.pasta / m["arquivo"]
    if not caminho.exists():
        return None
    credito = {k: m.get(k) for k in ("fonte", "id", "autor", "licenca", "pagina", "tipo")}
    return caminho, credito


def _preparar_foto(origem, destino, video=False, duracao=None) -> bool:
    """A foto em até 1400 px (o vídeo, um quadro do meio), em JPEG, para a página."""
    from PIL import Image

    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        if video:
            meio = max(0.0, float(duracao or 2.0) * 0.4)
            rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{meio:.2f}", "-i", str(origem), "-frames:v", "1",
                   "-vf", "scale='min(1400,iw)':-2", "-q:v", "3", str(destino)])
            return destino.exists()
        with Image.open(origem) as im:
            im = im.convert("RGB")
            im.thumbnail((1400, 1400))
            im.save(destino, quality=88)
        return True
    except Exception:  # noqa: BLE001 - foto que não abre: o item fica sem ela
        return False


def _usadas_no_video(projeto) -> set:
    chaves = set()
    for c in projeto.ler_json("cenas.json")["cenas"]:
        for m in (c.get("midia"), (c.get("anim_reserva") or {}).get("midia"), *(c.get("anim_fotos") or [])):
            if m and m.get("fonte") and m.get("id"):
                chaves.add(f"{m['fonte']}:{m['id']}")
    return chaves


def _foto_do_banco(projeto, pasta, c, item, usadas, log):
    """Busca nos bancos a foto da coisa que o item cita, pelo pedido da cena; a visão escolhe. (arquivo, crédito)."""
    from . import midia, motion_figura, openrouter_local

    antes = _o_que_a_cena_tinha(c)
    termos = [t for t in dict.fromkeys(str(antes.get(k) or c.get(k) or "").strip()
                                       for k in ("exato", "animal", "busca", "busca_alternativa")) if t]
    if not termos:
        return None
    coisa = antes.get("exato") or antes.get("sujeito") or termos[0]
    minimo = antes.get("aceitavel") or antes.get("mostrar") or ""
    texto = str(item.get("texto") or item.get("titulo") or "").replace("*", "")
    marca = hashlib.sha1(json.dumps([VERSAO_FOTOS, termos[:2], texto], ensure_ascii=False).encode()).hexdigest()[:12]
    destino = pasta / "assets" / "fotos" / f"banco_{marca}.jpg"
    guardadas_em = pasta / "fotos.json"
    try:
        guardadas = json.loads(guardadas_em.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        guardadas = {}
    if marca in guardadas:
        credito = guardadas[marca].get("credito")
        return (destino, credito) if credito and destino.exists() else None

    def guardar(credito, motivo):
        guardadas[marca] = {"credito": credito, "motivo": motivo, "termos": termos[:2], "item": texto}
        pasta.mkdir(parents=True, exist_ok=True)
        guardadas_em.write_text(json.dumps(guardadas, ensure_ascii=False, indent=1), encoding="utf-8")
        if not credito:
            log(f"  animation-ai: \"{texto[:40]}\" sem foto nos bancos ({motivo})")

    # o que as tags têm de citar. Bicho: a própria espécie ("eagle" de "harpy eagle", ou o gênero científico), nunca
    # só o tipo: com "bird" bastando, um urutau-australiano do Unsplash entrou como o filhote de harpia (cena 47)
    if antes.get("animal"):
        exigido = set(midia._cabeca_do_animal(antes["animal"])) | midia._generos_cientificos(
            f"{antes.get('busca_alternativa') or ''} {antes.get('exato') or ''}")
    else:
        mapa = projeto.ler_json("roteiro_mapa.json") if projeto.existe("roteiro_mapa.json") else {}
        bloco = next((b for b in mapa.get("blocos") or [] if b.get("id") == c.get("bloco")), {})
        exigido = midia.exigido_da_cena(bloco, antes)
    buscador = midia.Buscador(projeto, log)
    listas = []
    for termo in termos[:2]:
        for fonte in FONTES_DA_FOTO:
            try:
                achados = [x for x in buscador._buscar(fonte, "foto", termo) if x.get("miniatura")
                           and f"{x.get('fonte')}:{x.get('id')}" not in usadas and not midia.de_edicao(x)]
            except (Exception, SystemExit):  # noqa: BLE001 - banco fora do ar: segue com os outros
                continue
            listas.append([x for x in achados if midia._cita_o_assunto(exigido, x)] if exigido else achados)
    candidatos, vistos, rodada = [], set(), 0
    while len(candidatos) < 40 and any(rodada < len(lista) for lista in listas):
        for lista in listas:
            if rodada < len(lista) and (lista[rodada]["fonte"], lista[rodada]["id"]) not in vistos:
                vistos.add((lista[rodada]["fonte"], lista[rodada]["id"]))
                candidatos.append(lista[rodada])
        rodada += 1
    if antes.get("animal"):
        # quem cita a espécie inteira ("harpy eagle", Harpia) na frente de quem cita só o bicho ("two young eagles")
        generos = midia._generos_cientificos(f"{antes.get('busca_alternativa') or ''} {antes.get('exato') or ''}")
        candidatos.sort(key=lambda x: not (midia._cita_o_nome(antes["animal"], x)
                                           or (generos and midia._cita_o_assunto(generos, x))))
    candidatos = candidatos[:12]
    if not candidatos:
        guardar(None, "nenhum candidato")
        return None
    sub = pasta / f"busca_{marca}"
    sub.mkdir(parents=True, exist_ok=True)
    folha, validos = motion_figura._folha(projeto, sub, candidatos, buscador.http)
    if not validos:
        guardar(None, "nenhuma miniatura baixou")
        return None
    try:
        escolha = openrouter_local.VISAO.perguntar(
            projeto, "animation-ai: foto do item", INSTRUCOES_FOTO_ITEM,
            f"O item na tela: {texto}\nA coisa que a foto tem de mostrar: {coisa}\n"
            + (f"O mínimo que a cena pede: {minimo}\n" if minimo else "") +
            f"Números válidos: {', '.join(map(str, validos))}.", ESQUEMA_FOTO_ITEM, log=log, imagens=[folha],
            temperatura=0) or {}
        numero = int(escolha.get("numero", -1))
    except (Exception, SystemExit) as erro:  # noqa: BLE001 - sem visão, o item fica sem foto (não guarda: tenta depois)
        log(f"  animation-ai: a visão não escolheu a foto de \"{texto[:40]}\" ({str(erro)[:80]})")
        return None
    if numero not in validos:
        guardar(None, "nenhuma mostra a coisa")
        return None
    candidato = candidatos[numero]
    original = sub / "original.jpg"
    try:
        midia._baixar(buscador.http, candidato["arquivo"], original)
        midia._garantir_jpeg(original)
    except Exception as erro:  # noqa: BLE001 - o banco caiu: o item fica sem foto (não guarda: tenta depois)
        log(f"  animation-ai: o download da foto de \"{texto[:40]}\" falhou ({str(erro)[:80]})")
        return None
    if midia.fundo_de_chroma(original):
        guardar(None, "material de edição")
        return None
    igual = midia.cena_com_a_mesma_imagem(projeto, -1, original, f"{candidato['fonte']}:{candidato['id']}")
    if igual is not None:
        guardar(None, f"a mesma imagem da cena {igual}")  # jamais repetir imagem
        return None
    if not _preparar_foto(original, destino):
        guardar(None, "a foto não abriu")
        return None
    credito = {k: candidato.get(k) for k in ("fonte", "id", "autor", "licenca", "pagina")}
    credito["tipo"] = "foto"
    guardar(credito, "ok")
    log(f"  animation-ai: \"{texto[:40]}\" com foto do {candidato['fonte']}")
    return destino, credito


def _o_que_a_cena_mostra(c) -> str:
    """O que se sabe da foto da cena: a legenda da visão, o pedido da busca e a fala."""
    antes = _o_que_a_cena_tinha(c)
    partes = [str((antes.get("captura") or {}).get("legenda") or "")]
    partes += [str(antes.get(k) or c.get(k) or "") for k in ("exato", "animal", "sujeito", "busca")]
    return _normal(" ".join(partes + [str(c.get("texto") or "")]))


def _combina(item, mostra) -> int:
    """Quantas palavras do item (pelo radical de 5 letras: "macacos" acha "macaco") aparecem no que a cena mostra."""
    texto = _normal(str(item.get("texto") or item.get("titulo") or "").replace("*", ""))
    radicais = {p[:5] for p in re.findall(r"[a-z0-9]{4,}", texto)}
    return sum(1 for r in radicais if r in mostra)

def fotos_dos_itens(projeto, trecho, tipo, dados, ini, pasta, log=print, com_foto=COM_FOTO,
                    minimo=MINIMO_DE_FOTOS, exigir_combina=False) -> dict:
    """Põe em cada item (dados["itens"]) a foto da coisa que ele cita: a da cena em que a palavra do item é falada,
    ou uma dos bancos. Cada cena empresta a foto a um item só. Devolve {número da cena: [créditos]} das fotos que
    entram na tela durante cada cena."""
    itens = [it for it in dados.get("itens") or [] if isinstance(it, dict)]
    if tipo not in com_foto or not itens or not config(projeto).get("fotos_nos_itens", True):
        return {}
    usadas, achadas = _usadas_no_video(projeto), []

    def cena_do(it):
        momento = ini + float(it.get("t") or 0) + 0.12
        cena = next((c for c in trecho if float(c["ini"]) <= momento < float(c["fim"])), None)
        return cena or min(trecho, key=lambda c: abs(float(c["ini"]) - momento))

    # cada cena empresta a foto a um item só: ao que ela mostra, e não ao primeiro que cai nela. Cena 34 do
    # brasil-selvagem: "bichos-preguiça" e "macacos" falados na mesma cena, a do macaco-prego; o cartão dos
    # bichos-preguiça saía com o macaco
    por_cena = {}
    for it in itens:
        por_cena.setdefault(cena_do(it)["n"], []).append(it)
    escolhidos = []
    for cena in trecho:
        candidatos = por_cena.get(cena["n"])
        if candidatos:
            mostra = _o_que_a_cena_mostra(cena)
            melhor = max(candidatos, key=lambda it: (_combina(it, mostra), -candidatos.index(it)))
            # exigir_combina (impacto): vários itens na cena e a foto não mostra nenhum, ela não vai para cartão
            # nenhum ("onças" sobre o macaco-prego)
            if not (exigir_combina and len(candidatos) > 1 and not _combina(melhor, mostra)):
                escolhidos.append((melhor, cena))
    escolhidos.sort(key=lambda par: itens.index(par[0]))
    for it, cena in escolhidos:
        foto = _foto_da_cena(projeto, cena)
        if foto is None:
            foto = _foto_do_banco(projeto, pasta, cena, it, usadas, log)
            if foto is None:
                continue
            arquivo = foto[0]
        else:
            arquivo = pasta / "assets" / "fotos" / f"cena_{cena['n']:04d}.jpg"
            duracao = (_o_que_a_cena_tinha(cena).get("midia") or {}).get("duracao")
            if not _preparar_foto(foto[0], arquivo, foto[1].get("tipo") == "video", duracao):
                continue
        usadas.add(f"{foto[1].get('fonte')}:{foto[1].get('id')}")
        achadas.append((it, arquivo, foto[1], cena["n"]))
    if len(achadas) < min(minimo, len(itens)):
        return {}
    creditos = {}
    for it, arquivo, credito, n in achadas:
        it["foto"] = arquivo.relative_to(pasta).as_posix()
        it["foto_id"] = f"{credito.get('fonte')}:{credito.get('id')}"  # entra na assinatura: outra foto, outro clipe
        creditos.setdefault(n, []).append(credito)
    return creditos


def fotos_impacto(projeto, trecho, tipo, dados, ini, pasta, log=print) -> dict:
    """As fotos do motor do impacto: a foto que a cena já tinha vai para o fundo (dados["fundo"]), e cada item, lado da
    comparação ou passo da ligação ganha a foto da coisa que cita (fotos_dos_itens). Devolve os créditos por cena."""
    # no impacto cada cartão é a sua foto: a que achou entra, mesmo sozinha (com o mínimo de 2, a foto achada para
    # "Interrompe circulação" se perdia e os dois cartões da cena 71 do brasil-selvagem saíam vazios)
    creditos = fotos_dos_itens(projeto, trecho, tipo, dados, ini, pasta, log, com_foto=COM_FOTO_IMPACTO, minimo=1,
                               exigir_combina=True)
    if tipo in ("comparar", "antes_depois", "deslizar"):
        lados = [dados.get(k) for k in (("esq", "dir") if tipo == "comparar" else ("antes", "depois"))]
        if all(isinstance(l, dict) for l in lados):
            itens = [{"texto": l.get("titulo") or l.get("rotulo") or l.get("texto") or "", "t": l.get("t", 0)}
                     for l in lados]
            for n, lista in fotos_dos_itens(projeto, trecho, "lista", {"itens": itens}, ini, pasta, log,
                                            minimo=1).items():
                creditos.setdefault(n, []).extend(lista)
            for lado, it in zip(lados, itens):
                if it.get("foto"):
                    lado["foto"], lado["foto_id"] = it["foto"], it["foto_id"]
    for c in trecho:
        foto = _foto_da_cena(projeto, c)
        if foto is None:
            continue
        arquivo = pasta / "assets" / "fotos" / f"fundo_{c['n']:04d}.jpg"
        duracao = (_o_que_a_cena_tinha(c).get("midia") or {}).get("duracao")
        if _preparar_foto(foto[0], arquivo, foto[1].get("tipo") == "video", duracao):
            dados["fundo"] = arquivo.relative_to(pasta).as_posix()
            dados["fundo_id"] = f"{foto[1].get('fonte')}:{foto[1].get('id')}"  # outra foto, outro clipe
            if dados["fundo_id"] not in {f"{x.get('fonte')}:{x.get('id')}" for x in creditos.get(c["n"], [])}:
                creditos.setdefault(c["n"], []).append(foto[1])
            # nenhum item com foto própria: a do fundo vai para o cartão do item que ela mostra, e os outros ficam
            # sem foto (motor_impacto.js, baralho). Sem isso, todo cartão repetia o fundo com o nome de outra coisa
            # embaixo (cena 34 do brasil-selvagem: "bichos-preguiça" sobre o macaco-prego)
            itens = [it for it in dados.get("itens") or [] if isinstance(it, dict)]
            if tipo in COM_FOTO_IMPACTO and len(itens) > 1 and not any(it.get("foto") for it in itens):
                mostra = _o_que_a_cena_mostra(c)
                melhor = max(itens, key=lambda it: (_combina(it, mostra), -itens.index(it)))
                if _combina(melhor, mostra):
                    melhor["foto"], melhor["foto_id"] = dados["fundo"], dados["fundo_id"]
            break
    return creditos


def trechos_animados(cenas) -> list:
    """[(trecho, grupo)]: cada trecho animado (anim_trecho, os números de quando foi gravado, que dão a pasta do plano)
    com as cenas seguidas que ainda são essa animação. O grupo sai de quem carrega a mesma lista, não dos números:
    narrar de novo renumera as cenas e o anim_trecho fica com os números velhos (brasil-selvagem, 2026-10-13: a cena
    61 com o trecho 66 a 69; pelos números, 41 dos 45 trechos ficavam sem regravar e sem som). A cena que a pessoa
    trocou por foto ou imagem de IA no editor fica de fora e corta o grupo (cena 36, no meio do trecho 34 a 36); se
    era a primeira, o trecho todo fica como está."""
    saida, vistos = [], set()
    for i, c in enumerate(cenas):
        chave = tuple(c.get("anim_trecho") or ([c["n"]] if e_animada(c) else []))
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        if not e_animada(c):
            continue
        grupo = [c]
        for d in cenas[i + 1:]:
            if not (e_animada(d) and tuple(d.get("anim_trecho") or [d["n"]]) == chave and d["n"] == grupo[-1]["n"] + 1):
                break
            grupo.append(d)
        saida.append((list(chave), grupo))
    return saida


def _partes_do_trecho(projeto, trecho):
    """O plano gravado do trecho (partes.json da pasta do primeiro número), ou None. A pasta vai pelo número: depois
    de renumerar, outro trecho pode ter gravado por cima dela (brasil-selvagem: a 0034 virou o trecho [34], e a cena
    do [34, 35] velho ficou sem plano). O plano diz de quais cenas é, e só vale para elas."""
    pasta = _pasta_do_trecho(projeto, trecho)
    return None if pasta is None else _ler_partes(pasta)


def _ler_partes(pasta):
    try:
        return json.loads((pasta / "partes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _pasta_do_trecho(projeto, trecho):
    """A pasta com o plano destas cenas: a do primeiro número (animation_ai/0100) ou, se ela já era de outro trecho
    quando este foi gravado, a 0100_2, 0100_3... O plano sem a lista de cenas (de antes de 2026-10-13) vale."""
    base = _pasta(projeto, trecho[0])
    for pasta in [base, *sorted(base.parent.glob(f"{base.name}_*"))]:
        partes = _ler_partes(pasta)
        if partes is not None and (not partes.get("cenas") or list(partes["cenas"]) == list(trecho)):
            return pasta
    return None


def _pasta_para_gravar(projeto, numeros):
    """Onde gravar o plano das cenas numeros: a pasta do primeiro número, menos quando ela guarda o plano de outro
    trecho que alguma cena ainda mostra. Depois de renumerar, a cena 94 é o trecho 100 a 102 de antes; gravar a cena
    100 nova em animation_ai/0100 apagava o plano dela, e a 94 ficava sem som e sem como regravar (brasil-selvagem)."""
    em_uso = {tuple(c["anim_trecho"]) for c in projeto.ler_json("cenas.json")["cenas"]
              if c.get("anim_trecho") and e_animada(c) and c["n"] not in numeros}
    base, k = _pasta(projeto, numeros[0]), 1
    while True:
        pasta = base if k == 1 else base.with_name(f"{base.name}_{k}")
        partes = _ler_partes(pasta)
        if (partes is None or not partes.get("cenas") or list(partes["cenas"]) == list(numeros)
                or tuple(partes["cenas"]) not in em_uso):
            return pasta
        k += 1

def regravar(projeto, numeros=None, log=print) -> list:
    """Grava de novo as cenas animadas que já existem, com o plano delas (partes.json): pega as mudanças do desenho
    (as fotos dos itens, VERSAO) sem perguntar nada ao modelo. numeros: só os trechos que têm alguma dessas cenas.
    Falhou, a cena fica com a animação de antes."""
    todas = projeto.ler_json("cenas.json")["cenas"]
    pares = []
    for trecho, grupo in trechos_animados(todas):
        if numeros and not (set(trecho) | {c["n"] for c in grupo}) & set(numeros):
            continue
        partes = _partes_do_trecho(projeto, trecho)
        if partes is None:
            log(f"  animation-ai: cena {grupo[0]['n']} sem o plano do trecho dela; fica como estava")
            continue
        if partes.get("tipo"):
            dados = json.loads(json.dumps(partes["dados"]))
            if isinstance(dados.get("itens"), list):
                # plano de antes da conferência de item repetido ("a cada dois ou três anos" duas vezes, cena 47)
                vistos, itens = set(), []
                for it in dados["itens"]:
                    chave = _chave(str((it or {}).get("texto") or (it or {}).get("titulo") or "").replace("*", ""))
                    if chave not in vistos:
                        vistos.add(chave)
                        itens.append(it)
                dados["itens"] = itens
            pares.append((grupo, {"tipo": partes["tipo"], "dados": dados}))
    feitas = []
    for g, plano in pares:
        try:
            for n, destino, capa, dur, fotos in gravar(projeto, g, plano, log):
                _aplicar(projeto, n, destino, capa, dur, [c["n"] for c in g], plano["tipo"], fotos)
            feitas += [c["n"] for c in g]
            log(f"  animation-ai: cena {g[0]['n']} ({plano['tipo']}) gravada de novo")
        except (Exception, SystemExit) as erro:  # noqa: BLE001 - fica a animação de antes
            log(f"  animation-ai: cena {g[0]['n']} não foi gravada de novo ({str(erro)[:160]}); fica como estava")
    return feitas


def _pasta(projeto, n) -> Path:
    return projeto.pasta / "animation_ai" / f"{n:04d}"


def assinatura(tipo, dados, dur, cores, canal, variante=0) -> str:
    nome = "motor_impacto" if e_impacto(cores) else "motor"  # o motor que desenha a cena (montar_html)
    motor = (RECURSOS / f"{nome}.js").read_bytes() + (RECURSOS / f"{nome}.css").read_bytes()
    # a variante só conta nos estilos que variam de cena para cena: nos 4 de antes o nome do clipe não muda
    base = json.dumps([VERSAO, tipo, dados, round(dur, 3), cores, canal] + ([variante] if com_variante(cores) else []),
                      ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(base.encode("utf-8") + motor).hexdigest()[:16]


QUADRO_MORTO = 0.02       # diferença média (0 a 255) abaixo da qual dois quadros seguidos são o mesmo
MORTO_NO_MEIO = 0.8       # segundos parados, no começo ou no meio, a partir dos quais o clipe reprova
MORTO_NO_FIM = 2.5        # segundos parados no fim (o último elemento já ficou 1,5 s na tela de propósito)


def quadros_mortos(mp4, fps=30):
    """Mede os trechos parados do clipe gravado: (maior trecho parado no começo ou no meio, trecho parado no fim),
    em segundos. Ideia do motionmaxxing (quadro morto), com os limites medidos em 40 clipes reais da fábrica: com o
    limite deles, 3 quadros, quase todo clipe bom reprovava, porque o card parado entre duas palavras faz uns 13
    quadros (0,4 s). O maior trecho do meio dos bons foi 0,43 s e o do fim 0,4 s."""
    import subprocess

    import numpy as np

    largura, altura = 96, 54
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(mp4), "-vf", f"scale={largura}:{altura},format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    quadros = np.frombuffer(p.stdout, np.uint8)
    quadros = quadros[: len(quadros) // (largura * altura) * (largura * altura)].reshape(-1, largura * altura)
    # a 60 quadros por segundo dois quadros seguidos quase não mudam; compara de 1/30 s em 1/30 s, como nos clipes
    # medidos (a 30 quadros por segundo o passo é 1)
    passo = max(1, round(fps / 30))
    quadros = quadros[::passo]
    fps = fps / passo
    if len(quadros) < 2:
        return 0.0, 0.0
    parado = np.abs(np.diff(quadros.astype(np.int16), axis=0)).mean(axis=1) < QUADRO_MORTO
    fim = 0
    for x in parado[::-1]:
        if not x:
            break
        fim += 1
    no_meio = atual = 0
    for x in parado[: len(parado) - fim]:
        atual = atual + 1 if x else 0
        no_meio = max(no_meio, atual)
    return no_meio / fps, fim / fps


def _reprovado_por_quadro_morto(mp4, fps=30):
    """Texto do motivo se o clipe tem tela parada demais, ou "" se está bom. Nunca derruba por falha da medida."""
    try:
        no_meio, no_fim = quadros_mortos(mp4, fps)
    except Exception:  # noqa: BLE001 - a medida é um extra: sem ela o clipe segue
        return ""
    if no_meio > MORTO_NO_MEIO:
        return f"a tela fica parada {no_meio:.1f} s no meio do clipe (quadro morto)"
    if no_fim > MORTO_NO_FIM:
        return f"a tela fica parada {no_fim:.1f} s no fim do clipe"
    return ""


def gravar(projeto, trecho, plano, log=print):
    """Grava o trecho e devolve [(n, mp4, capa, duração, créditos das fotos dos itens) de cada cena]. Levanta
    RuntimeError se falhar. O plano de tipo "dirigida" é uma cena dirigida (direcao.py): câmera, tipografia cinética e
    formato em pé, gravada a 60 quadros por segundo."""
    if plano.get("tipo") == "dirigida":
        from . import direcao

        return direcao.gravar(projeto, trecho, plano, log)
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
    pasta = _pasta_para_gravar(projeto, [c["n"] for c in trecho])
    if e_impacto(cores):
        creditos = fotos_impacto(projeto, trecho, tipo, resolvidos, ini, pasta, log)
        eventos = sons_impacto(tipo, resolvidos, dur)  # o motor do impacto mexe em outros momentos que o motor.js
    else:
        creditos = fotos_dos_itens(projeto, trecho, tipo, resolvidos, ini, pasta, log)
    variante = trecho[0]["n"]
    marca = assinatura(tipo, resolvidos, dur, cores, canal, variante)
    from .midia import nome_livre

    # o nome pelo número da cena, mas nunca o de um arquivo que outra cena usa: depois de renumerar, a cena 33 mostra o
    # midia/0034_anim.mp4, e gravar a cena 34 nova com esse nome trocava a animação da 33 (brasil-selvagem, 2026-10-13)
    sufixos = ("_anim.mp4", "_anim_capa.jpg")
    base = nome_livre(projeto, trecho[0]["n"], sufixos)
    destino = projeto.pasta / "midia" / f"{base}_anim{'_trecho' if len(trecho) > 1 else ''}.mp4"
    partes = pasta / "partes.json"
    anterior = json.loads(partes.read_text(encoding="utf-8")) if partes.exists() else {}
    if anterior.get("assinatura") != marca or not destino.exists():
        pasta.mkdir(parents=True, exist_ok=True)
        animacoes._preparar_pasta(pasta)
        (pasta / "index.html").write_text(montar_html(tipo, resolvidos, dur, cores, canal, variante), encoding="utf-8")
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
        parado = _reprovado_por_quadro_morto(temporario, int(cfg.get("fps", 30)))
        if parado:
            temporario.unlink(missing_ok=True)
            raise RuntimeError(parado)
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
            pedaco = projeto.pasta / "midia" / f"{nome_livre(projeto, c['n'], sufixos)}_anim.mp4"
            rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-i", str(destino), "-t",
                   f"{dur_c + 0.05:.3f}", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "16",
                   "-pix_fmt", "yuv420p", str(pedaco)])
        else:
            pedaco = destino
        capa = pedaco.with_name(pedaco.name.replace("_anim.mp4", "_anim_capa.jpg"))
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0.0, min(dur_c * 0.7, dur_c - 0.1)):.2f}",
               "-i", str(pedaco), "-frames:v", "1", "-q:v", "3", str(capa)])
        saida.append((c["n"], pedaco, capa, dur_c, creditos.get(c["n"], [])))
    return saida


def _aplicar(projeto, n, destino, capa, dur, trecho, tipo, fotos=()) -> None:
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
        for campo in ("sem_midia_real", "conferencia", "anim_falhou", "anim_fotos"):
            c.pop(campo, None)
        if fotos:
            c["anim_fotos"] = list(fotos)  # as fotos de banco dos itens que entram nesta cena: vão para os créditos
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
            for n, destino, capa, dur, fotos in pedacos:
                _aplicar(projeto, n, destino, capa, dur, [c["n"] for c in g], plano["tipo"], fotos)
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
    escolhe o tipo, com os 30 do catálogo. Devolve as cenas feitas."""
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

SO_PEDIDAS = ("abertura", "capitulo", "frase", "pergunta", "encerramento", "palavra_chave", "revelacao")  # texto da fala sobre fundo: a foto já diz
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
VERSAO_UTIL = 2  # suba quando mudar as instruções do complemento: as decisões guardadas são pedidas de novo


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
- Em lista, checklist, destaques e cartoes, cada item entra na tela com a FOTO da coisa que ele cita (a cena em
  que ela é falada): dê a "palavra" de cada item no momento em que a COISA é dita, pelo nome dela ("castanheira",
  não "como"). Item é uma coisa diferente citada em série; nunca pique uma frase comum em pedaços nem repita o mesmo
  trecho em dois itens.
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
    decisoes = decidir(projeto, itens, log, tipos_do_tema(projeto, COMO_MOTION if como_motion else None))
    ocupados = [(float(c["ini"]), float(c["fim"])) for c in todas
                if (c.get("midia") or {}).get("fonte") in ("motion_ia", FONTE)]
    duracao = float(projeto.ler_json("alinhamento.json").get("duracao") or todas[-1]["fim"])
    if como_motion:
        # no lugar do motion: sem o intervalo (a cena reprovada precisa de uma saída), mas com teto próprio, contando as
        # cenas já animadas. Sem teto, o brasil-selvagem ficou com 118 cenas animadas, 31% do vídeo, quase o triplo do
        # maximo_do_video. As de nota maior entram primeiro; as que passam do teto seguem para a imagem de IA ou voltam
        # para a foto que tinham (imagens._motion_antes_da_ia)
        teto = float(cfg.get("maximo_no_lugar_do_motion", 0.25))
        escolhidos = escolher(itens, decisoes, {**cfg, "maximo_do_video": teto, "intervalo_minimo": 0}, duracao, ocupados)
        aprovadas = sum(1 for it in itens if decisoes.get(it["id"], {}).get("tipo")
                        and decisoes[it["id"]].get("nota", 0) >= float(cfg.get("limiar", 70)))
        if aprovadas > len(escolhidos):
            log(f"  animation-ai: {aprovadas - len(escolhidos)} cena(s) ficaram fora pelo teto de {teto:.0%} do vídeo em "
                "cenas animadas; seguem para a imagem de IA ou voltam para a foto")
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
                c.pop("anim_fotos", None)
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
    for trecho, grupo in trechos_animados(cenas):
        c, pasta = grupo[0], _pasta_do_trecho(projeto, trecho)
        if pasta is None:
            continue
        try:
            arquivo = _sons_do_trecho(projeto, pasta)
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
    "palavra_chave": {"kicker": "O que mede tudo", "termo": "TEMPO", "itens": [{"texto": "anos de barrica"}, {"texto": "paciência"},
                                                                          {"texto": "colheita à mão"}]},
    "medidor": {"valor": "85%", "legenda": "do vinho fino brasileiro sai da Serra Gaúcha"},
    "grafico_linha": {"titulo": "Garrafas por ano", "itens": [{"rotulo": "1990", "valor": 2, "texto": "2 mi"},
                      {"rotulo": "2000", "valor": 5, "texto": "5 mi"}, {"rotulo": "2010", "valor": 9, "texto": "9 mi"},
                      {"rotulo": "2020", "valor": 14, "texto": "14 mi"}], "fonte": "IBRAVIN"},
    "deslizar": {"antes": {"rotulo": "Granel", "valor": "R$ 3"}, "depois": {"rotulo": "Garrafa", "valor": "R$ 90"},
                 "legenda": "o mesmo litro, depois de envelhecer"},
    "revelacao": {"kicker": "Documentário", "titulo": "O ouro da *Serra*", "sub": "Uma riqueza que se mede em tempo"},
    "pilha_cartoes": {"titulo": "O caminho do vinho", "itens": [{"titulo": "Colheita", "texto": "Uvas colhidas à mão em fevereiro"},
                      {"titulo": "Fermentação", "texto": "Semanas em tanques de aço"},
                      {"titulo": "Barrica", "texto": "Anos de madeira nativa"},
                      {"titulo": "Garrafa", "texto": "Descanso antes de chegar à mesa"}]},
}


def catalogo(projeto, destino: Path, tema_nome=None, log=print, variante=0, so=None) -> Path:
    """Uma folha com um quadro de cada tipo, no tema do projeto (ou no pedido): para ver o visual sem gravar vídeo.
    `so`: só esses tipos; `variante`: o jeito de entrar, mexer a câmera e sair dos estilos que variam (0, 1...)."""
    from PIL import Image, ImageDraw

    cores = TEMAS.get(tema_nome) if tema_nome else tema(projeto)
    pasta = destino.parent / f"_catalogo_animation_ai_{tema_nome or 'projeto'}"
    shutil.rmtree(pasta, ignore_errors=True)

    def um(item):
        tipo, exemplo = item
        sub = pasta / tipo
        sub.mkdir(parents=True, exist_ok=True)
        animacoes._preparar_pasta(sub)
        dur = 6.0
        resolvidos, _ = resolver_tempos(tipo, exemplo, [], dur)
        (sub / "index.html").write_text(montar_html(tipo, resolvidos, dur, cores, "Canal", variante), encoding="utf-8")
        r = animacoes._hyperframes(projeto, ["snapshot", "--at", "4.8", "--describe=false", "-o", str(sub / "q"), "."], sub, 240)
        achado = sorted((sub / "q").glob("*.png")) + sorted((sub / "q").glob("*.jpg"))
        achado = [a for a in achado if "contact" not in a.name]
        if r.returncode != 0 or not achado:
            log(f"  {tipo}: o quadro não saiu ({(r.stderr or r.stdout or '')[-160:]})")
            return tipo, None
        log(f"  {tipo}: ok")
        return tipo, achado[0]

    itens = [(t, e) for t, e in EXEMPLOS.items() if not so or t in so]
    with ThreadPoolExecutor(3) as executor:
        quadros = [(t, a) for t, a in executor.map(um, itens) if a is not None]
    colunas, w, h = 4, 640, 360
    folha = Image.new("RGB", (colunas * (w + 10) + 10, ((len(quadros) + colunas - 1) // colunas) * (h + 40) + 10), (20, 20, 24))
    desenho = ImageDraw.Draw(folha)
    for i, (tipo, arquivo) in enumerate(quadros):
        x, y = 10 + (i % colunas) * (w + 10), 10 + (i // colunas) * (h + 40)
        folha.paste(Image.open(arquivo).convert("RGB").resize((w, h)), (x, y + 30))
        desenho.text((x + 4, y + 8), tipo, fill=(240, 240, 240))
    folha.save(destino, quality=88)
    return destino
