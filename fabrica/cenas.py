"""Divisão da narração em cenas e decisão do que aparece em cada uma.

O Claude recebe as frases com a duração de cada uma e devolve grupos de frases
consecutivas. Cada grupo diz o tipo da cena (foto real, vídeo real ou imagem de IA),
os termos de busca do material real, o prompt da imagem de IA e o texto animado,
se houver. No modo offline as cenas são agrupadas só pelo tempo, sem chamar a API.
"""
import hashlib
import json
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from . import claude_local, efeitos, gemini_local, groq_local, openrouter_local, roteirista, textos
from . import texto as tx

# Estilo de vídeo único da fábrica, igual para qualquer nicho de canal: cenas de 3 a 5 segundos e
# 90% do material vindo de acervo real (o resto em imagem de IA). Fixo aqui, não no perfil, porque
# é o formato do vídeo em si, não uma escolha de conteúdo — todo perfil novo já nasce com ele.
ESTILO_ALVO_SEGUNDOS = 4.0
ESTILO_MINIMO_SEGUNDOS = 3.0
ESTILO_MAXIMO_SEGUNDOS = 5.0
ESTILO_PROPORCAO_REAL = 0.9
ESTILO_MINIMO_FOTOS = 0.70  # do material real, pelo menos isso tem que ser foto
# nos primeiros minutos, esta fatia do material real é vídeo, para prender a atenção: (até o segundo, fatia)
ESTILO_VIDEO_NO_INICIO = ((180.0, 0.80), (420.0, 0.40))
# Sem teto de IA (desde 2026-10-03, pedido do usuário): cena que não existe em foto ou que veio errada recebe imagem de
# IA, quantas forem. O teto de 15% transformava em foto de banco as cenas que o agente marcou como IA, e foi assim que
# o virou-filme-em-1996 saiu com 86 cenas de outra coisa. Com a IA desligada (ia.ativa: false), nenhuma cena é de IA
# quando a narração enumera coisas ("tigres, tubarões, crocodilos, aranhas"), uma imagem só para a
# lista inteira desperdiça o trecho. Nesses momentos a cena é quebrada item a item e pode ficar mais
# curta que o mínimo normal, porque cada nome dura menos de um segundo na fala
ESTILO_MINIMO_ENUMERACAO = 1.0
TIPOS_REAIS_CENA = ("foto_real", "video_real")
ENUMERACAO_MINIMA_DE_ITENS = 3
ENUMERACAO_MAXIMO_DE_PALAVRAS = 3  # "cobras venenosas" conta, "que podem matar em minutos" não
ESTILO_DURACAO_MINIMA_MINUTOS = 20.0  # abaixo disso só avisa e deixa passar com confirmação

TEXTO_TELA = {
    "type": "object",
    "properties": {
        "tipo": {"type": "string", "enum": ["nenhum", "destaque", "lista", "capitulo", "rotulo"]},
        "texto": {"type": "string"},
        "destaque": {"type": "string"},
        "titulo": {"type": "string"},
        "frase": {"type": "integer"},
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"texto": {"type": "string"}, "frase": {"type": "integer"}},
                "required": ["texto", "frase"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["tipo", "texto", "destaque", "titulo", "frase", "itens"],
    "additionalProperties": False,
}

EFEITO = {
    "type": "object",
    "properties": {
        "descricao": {"type": "string"},
        "palavra": {"type": "string"},
        "duracao": {"type": "number"},
    },
    "required": ["descricao", "palavra", "duracao"],
    "additionalProperties": False,
}

ESQUEMA = {
    "type": "object",
    "properties": {
        "cenas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "primeira_frase": {"type": "integer"},
                    "ultima_frase": {"type": "integer"},
                    "tipo": {"type": "string", "enum": ["foto_real", "video_real", "ia"]},
                    "busca": {"type": "string"},
                    "personagem": {"type": "boolean"},
                    "prompt": {"type": "string"},
                    "texto_tela": TEXTO_TELA,
                    "efeito": EFEITO,
                },
                "required": ["primeira_frase", "ultima_frase", "tipo", "busca", "personagem", "prompt", "texto_tela",
                             "efeito"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cenas"],
    "additionalProperties": False,
}

SISTEMA = """Você é o diretor de arte de um canal do YouTube. A narração de um vídeo chega dividida em frases numeradas, com a duração de cada uma, e você decide a sequência do que aparece na tela.

Regras
1. Agrupe frases consecutivas em cenas. Cada cena mostra uma única imagem ou vídeo enquanto as frases dela são narradas.
2. Toda frase pertence a exatamente uma cena. Não pule frases e não sobreponha cenas.
3. REGRA ABSOLUTA DE DURAÇÃO (3s a 5s): Cada cena DEVE ter duração estritamente entre {minimo:.1f} e {maximo:.1f} segundos (com alvo em {alvo:.1f}s). É ESTRITAMENTE PROIBIDO criar cenas com mais de {maximo:.1f} segundos ou com menos de {minimo:.1f} segundos. NUNCA passe de {maximo:.1f} segundos sob hipótese alguma — nem mesmo com listas na tela, citações ou personagens.
4. O que aparece na tela ilustra de forma concreta e específica o que a narração diz naquele momento. Quando a frase for abstrata, escolha um detalhe visual que traduza a ideia.
5. Escreva o prompt em inglês, como a descrição de uma fotografia. Diga o sujeito, a ação, o enquadramento, o ambiente e os detalhes importantes. Não descreva o estilo geral da imagem, ele é acrescentado depois.
6. Nunca peça texto escrito, letras, placas legíveis ou logotipos dentro da imagem.
7. Varie o enquadramento entre cenas vizinhas para o vídeo não ficar monótono.
8. Cada cena precisa prender o olho de quem assiste. Prefira composições de cartaz de cinema, com luz dramática, contraste forte, close em rostos, mãos e objetos, ângulos baixos e sensação de escala. Fuja da imagem genérica de banco de imagens.

{secao_midia}

{secao_bancos}

{secao_textos}

{secao_efeitos}

{secao_personagem}

Diretrizes do canal
{diretrizes}

Roteiro completo, para você entender o contexto
<roteiro>
{roteiro}
</roteiro>"""

SECAO_SEM_IA = """Material real de banco de imagens
REGRA OBRIGATÓRIA: este canal usa só foto e vídeo de banco de imagens. NUNCA use o tipo ia, em nenhuma cena.
- foto_real para objetos, artefatos, manuscritos, lugares, mapas, estruturas, animais, documentos, fotos de época e pessoas.
- video_real para cenas de ação, natureza, pessoas em movimento, atmosfera, cidades, tecnologia.
- Para ideias abstratas escolha um detalhe concreto e fotografável que as traduza.
Em busca escreva SEMPRE de 2 a 4 palavras-chave simples e diretas em inglês, com substantivos concretos que existam em bancos de imagens (ex: 'ancient ruins wall', 'hands holding seeds', 'forest river sunset'). Se o assunto é uma espécie ou um objeto raro, use o nome pelo qual um banco o indexaria, e não uma descrição longa.
Escreva o prompt em todas as cenas: ele descreve o que a foto deveria mostrar e ajuda a escolher entre os candidatos."""

SECAO_MIDIA = """Material real de acervo ou imagem de IA
REGRA OBRIGATÓRIA DE EDIÇÃO: Use material real de acervo (Pixabay e Pexels) sempre que existir o assunto de verdade. Imagem de IA quando o acervo não teria o assunto: um momento que ninguém fotografou, uma cena do passado com ação específica.
- foto_real para objetos, artefatos, manuscritos, lugares, mapas, estruturas, animais, documentos, fotos de época e pessoas.
- video_real para cenas de ação, natureza, pessoas em movimento, atmosfera, elementos visuais, cidades, tecnologia.
- ia para o que não existe em banco de imagens. Nunca troque por uma foto de outra coisa só para evitar a IA: foto errada é o pior erro.
Em busca escreva SEMPRE de 2 a 4 palavras-chave simples e diretas em inglês que existam com fartura no Pixabay e Pexels (ex: 'ancient ruins wall', 'hands holding seeds', 'golden coins desk', 'forest river sunset'). Em cenas ia deixe busca vazia.
Escreva o prompt em todas as cenas, inclusive nas reais, porque ele é usado caso seja necessário gerar uma imagem."""

SEM_MIDIA = "Tipo das cenas\nTodas as cenas são do tipo ia, com busca vazia."


SECAO_TEXTOS = """Textos na tela
Algumas cenas ganham um texto animado por cima da imagem. Em texto_tela escolha o tipo.
- destaque é uma frase curta de impacto em letras grandes. Em texto escreva de 3 a 9 palavras e em destaque copie 1 ou 2 palavras seguidas desse texto, que ganham uma caixa colorida.
- lista é um cartão com título e itens que surgem um a um. Em titulo escreva um título curto e em itens cada item com poucas palavras e o número da frase em que ele é narrado. Todos os itens precisam estar dentro das frases da cena.
- capitulo é uma referência grande no canto, como CAP 104. Escreva a referência em texto e, se fizer sentido, o nome do livro em titulo.
- rotulo é uma etiqueta pequena com o nome de um livro, documento ou fonte citada, escrito em titulo.
- nenhum vale para a maioria das cenas.
Em frase coloque o número da frase em que o texto deve surgir. Escreva em português e em maiúsculas, sem afirmar nada que a narração não diga. Nos campos que não se aplicam use texto vazio, lista vazia e o número da primeira frase da cena."""

SEM_TEXTOS = (
    "Textos na tela\nEste canal não usa textos na tela. Em texto_tela use tipo nenhum, "
    "textos vazios, lista vazia e o número da primeira frase da cena."
)

SECAO_EFEITOS = """Efeitos sonoros
Algumas cenas ganham um efeito sonoro curto por baixo da narração. Em efeito, descricao é o pedido do som em inglês, como alguém pediria a um banco de sons, com o som e a textura, por exemplo distant rolling thunder, deep ceremonial horn blast, crackling bonfire, heavy stone door grinding shut. Em palavra copie a palavra da narração em que o som deve bater, e em duracao os segundos do efeito, de 1 a 6.
Use efeito só quando a narração mostrar algo que tem som de verdade, como trovão, trombeta, fogo, vento, água, correntes, passos, multidão, espadas ou sino. A maioria das cenas fica sem efeito, com descricao e palavra vazias e duracao 0. Nunca peça música nem voz no efeito."""

SEM_EFEITOS = "Efeitos sonoros\nEste canal não usa efeitos. Em efeito use descricao e palavra vazias e duracao 0."


STOPWORDS_BUSCA = {
    'extreme', 'close-up', 'closeup', 'wide', 'shot', 'cinematic', 'dramatic', 'lighting',
    'photo', 'photography', 'image', 'photorealistic', 'ultra', 'detailed', 'hyper-realistic',
    'view', 'angle', 'low', 'high', 'background', 'foreground', 'of', 'a', 'an', 'the', 'in',
    'on', 'at', 'with', 'and', 'or', 'to', 'for', 'by', 'from', 'is', 'are', 'was', 'were',
    'showing', 'depicting', 'captured', 'style', 'real', 'shallow', 'depth', 'field',
    'close', 'small', 'tiny', 'weathered', 'dark', 'light', 'warm', 'cold', 'slow', 'motion'
}


def _extrair_busca_do_prompt(prompt, texto_cena=""):
    if prompt:
        palavras = re.findall(r'[a-zA-Z]{3,}', prompt.lower())
        uteis = [p for p in palavras if p not in STOPWORDS_BUSCA]
        if len(uteis) >= 2:
            return " ".join(uteis[:3])
        elif uteis:
            return uteis[0]
    palavras_texto = re.findall(r'[a-zA-ZáéíóúÁÉÍÓÚñÑãõÃÕçÇ]{4,}', texto_cena)
    return " ".join(palavras_texto[:3]) if palavras_texto else "documentary cinematic"


def _itens_enumerados(texto):
    """Devolve os itens quando o texto é uma enumeração, ou uma lista vazia quando não é.

    Vale como enumeração uma sequência de três ou mais nomes curtos separados por vírgula ou por "e",
    como "tigres, tubarões, crocodilos, aranhas e cobras venenosas"."""
    pedacos = [p.strip(" .,;:") for p in re.split(r",|\be\b", texto)]
    itens = [p for p in pedacos if p and len(p.split()) <= ENUMERACAO_MAXIMO_DE_PALAVRAS and len(p) >= 4]
    # a enumeração precisa dominar a frase, e não ser dois nomes soltos no meio de uma explicação
    return itens if len(itens) >= ENUMERACAO_MINIMA_DE_ITENS and len(itens) >= len(pedacos) - 1 else []


def _dividir_enumeracoes(cenas, alinhamento, minimo=ESTILO_MINIMO_ENUMERACAO, log=print):
    """Quebra em várias cenas os trechos em que a narração enumera coisas, uma imagem por item.

    Usa o tempo de cada palavra falada para achar onde cada item começa. Itens vizinhos são juntados
    até a fatia alcançar o mínimo, porque um nome sozinho costuma durar menos de um segundo."""
    palavras = alinhamento.get("palavras") or []
    if not palavras:
        return cenas
    resultado, quebradas = [], 0
    for cena in cenas:
        citacoes = cena.pop("citacoes", None) or []
        if len(citacoes) >= 2:
            itens = [c["palavra"] for c in citacoes]  # o modelo listou o que a narração cita, na ordem
        else:
            citacoes = []
            itens = _itens_enumerados(cena.get("texto", "")) if cena["fim"] - cena["ini"] >= 2 * minimo else []
        if not itens:
            resultado.append(cena)
            continue
        # onde cada item começa a ser falado, procurando a primeira palavra dele na fala da cena
        da_cena = [p for p in palavras if p.get("ini") is not None and cena["ini"] - 0.15 <= p["ini"] < cena["fim"]]
        inicios, quem, k = [], [], 0
        for n_item, item in enumerate(itens):
            alvo = _simplificar(item.split()[0])
            achado = next((p["ini"] for p in da_cena[k:] if _simplificar(p["texto"]).startswith(alvo[:5])), None)
            if achado is None:
                continue
            k = next(i for i, p in enumerate(da_cena) if p["ini"] == achado) + 1
            inicios.append(max(achado, cena["ini"]))
            quem.append(n_item)
        # cada item ganha a própria fatia. Item curto ("alces" dura 0,6s) não engole o seguinte: o corte do
        # próximo item é empurrado só o necessário para o curto ter o mínimo. Só junta quando nem assim cabe
        # (o que sobra no fim da cena não teria o mínimo)
        cortes, de_quem = [cena["ini"]], quem[:1]
        for t, n_item in zip(inicios[1:], quem[1:]):
            t = max(t, cortes[-1] + minimo)
            if cena["fim"] - t >= minimo:
                cortes.append(round(t, 3))
                de_quem.append(n_item)
        if len(cortes) < 2:
            resultado.append(cena)
            continue
        quebradas += 1
        for i, ini in enumerate(cortes):
            fim = cortes[i + 1] if i + 1 < len(cortes) else cena["fim"]
            fatia = dict(cena)
            fatia["ini"], fatia["fim"] = round(ini, 3), round(fim, 3)
            fatia["texto"] = _extrair_texto_palavras(palavras, ini, fim, fallback=cena["texto"])
            fatia["enumeracao"] = True
            if citacoes and cena.get("tipo") in TIPOS_REAIS_CENA and citacoes[de_quem[i]].get("busca"):
                fatia["busca"] = citacoes[de_quem[i]]["busca"]  # cada fatia mostra a coisa que ela cita
                fatia["busca_alternativa"] = ""
                fatia["prompt"] = citacoes[de_quem[i]].get("prompt") or fatia.get("prompt", "")
                # o sujeito, o animal, o exato e o que deve aparecer são os da coisa citada, não os da cena inteira:
                # a fatia dos alces herdava animal "gray wolf" e a descrição dos lobos, e o Jev cobrava lobo nela
                cit = citacoes[de_quem[i]]
                fatia["sujeito"] = " ".join(fatia["busca"].split()[:3])
                fatia.pop("animal", None)
                fatia.pop("exato", None)
                for campo in ("animal", "exato"):
                    if (cit.get(campo) or "").strip():
                        fatia[campo] = cit[campo].strip()
                fatia["mostrar"] = (cit.get("descricao") or "").strip() or f"{cit.get('palavra', '')}: {fatia['busca']}"
                fatia["item_citado"] = (cit.get("palavra") or "").strip()
            if i > 0:  # o texto na tela e o efeito ficam na primeira fatia, as outras só ilustram
                fatia["texto_tela"] = None
                fatia["efeito"] = None
            resultado.append(fatia)
    if quebradas:
        log(f"  {quebradas} cena(s) com enumeração quebradas em uma imagem por item")
    for i, c in enumerate(resultado, start=1):
        c["n"] = i
    return resultado


def _balancear_proporcao_90_10(cenas, log=print, sem_ia=False):
    """Com a IA desligada (ia.ativa: false no config.yaml), toda cena de IA vira foto ou vídeo de acervo. Ligada, nada
    muda: não existe teto de IA, e a cena que não existe em foto fica com a IA."""
    if not cenas or not sem_ia:
        return cenas
    teto_ia = 0
    cenas_ia = [c for c in cenas if c.get("tipo") == "ia"]
    if len(cenas_ia) > teto_ia:
        excesso = len(cenas_ia) - teto_ia
        log(f"  ajustando proporção: {len(cenas_ia)} eram IA, convertendo {excesso} para acervo real (teto de {round(teto_ia / len(cenas) * 100) if teto_ia else 0}% de IA)")
        candidatas = [c for c in cenas_ia if not c.get("personagem")]
        if len(candidatas) < excesso:
            candidatas += [c for c in cenas_ia if c not in candidatas]
        for idx, c in enumerate(candidatas[:excesso]):
            c["tipo"] = "video_real" if idx % 2 == 0 else "foto_real"
            if not c.get("busca"):
                c["busca"] = c.get("busca_reserva") or _extrair_busca_do_prompt(c.get("prompt", ""), c.get("texto", ""))
    return cenas


def _balancear_foto_e_video(cenas, log=print):
    """Do material real, pelo menos 70% é foto, mas o começo é de vídeo: 80% nos 3 primeiros minutos e 40% até os 7.

    Os 30% de vídeo permitidos no total são gastos primeiro no começo. Se as metas do começo não cabem neles,
    os 3 primeiros minutos têm prioridade. Só troca o tipo (foto_real por video_real e o contrário), espalhando
    as trocas pelo trecho, e a busca continua a mesma."""
    # cena de época é foto de arquivo: vídeo de banco é sempre de hoje (obras modernas no lugar da ferrovia de 1898)
    for c in cenas:
        if c.get("tipo") == "video_real" and re.search(r"\b1\d{3}\b", str(c.get("epoca") or "")):
            c["tipo"] = "foto_real"
    # vídeo de banco só para o que existe em banco: o que só existe em arquivo (retrato, foto de época) nunca vira vídeo
    for c in cenas:
        if c.get("tipo") == "video_real" and c.get("onde_existe") == "arquivo":
            c["tipo"] = "foto_real"
    reais = [c for c in cenas if c.get("tipo") in TIPOS_REAIS_CENA and not c.get("personagem")
             and not re.search(r"\b1\d{3}\b", str(c.get("epoca") or "")) and c.get("onde_existe") != "arquivo"]
    if len(reais) < 10:
        return cenas
    limite = int(len(reais) * (1 - ESTILO_MINIMO_FOTOS))  # vídeos permitidos no total
    faixas, inicio_da_faixa = [], 0.0
    for fim, fatia in ESTILO_VIDEO_NO_INICIO:
        faixas.append([c for c in reais if inicio_da_faixa <= c["ini"] < fim])
        inicio_da_faixa = fim
    faixas.append([c for c in reais if c["ini"] >= inicio_da_faixa])  # o resto do vídeo

    def ajustar(grupo, quantos_videos):
        trocar = quantos_videos - sum(1 for c in grupo if c["tipo"] == "video_real")
        if trocar == 0 or not grupo:
            return 0
        de, para = ("foto_real", "video_real") if trocar > 0 else ("video_real", "foto_real")
        # cenas de enumeração não viram vídeo: cada uma dura só um ou dois segundos. Vídeo nelas pode virar foto
        candidatas = [c for c in grupo if c["tipo"] == de and (para == "foto_real" or not c.get("enumeracao"))]
        trocar = min(abs(trocar), len(candidatas))
        for k in range(trocar):
            candidatas[int(k * len(candidatas) / trocar)]["tipo"] = para
        return trocar

    mudou, restante = 0, limite
    for grupo, (_, fatia) in zip(faixas, ESTILO_VIDEO_NO_INICIO):
        meta = min(round(len(grupo) * fatia), restante)
        mudou += ajustar(grupo, meta)
        restante -= meta
    resto = faixas[-1]
    if sum(1 for c in resto if c["tipo"] == "video_real") > restante:
        mudou += ajustar(resto, restante)
    if mudou:
        fotos = sum(1 for c in reais if c["tipo"] == "foto_real")
        log(f"  ajustando foto e vídeo: {mudou} cena(s) trocadas, {fotos / len(reais):.0%} do material real é foto")
    return cenas


# palavras que só dizem clima ou enquadramento: nos bancos de imagens elas mais atrapalham que ajudam
_SO_CLIMA = {"dark", "moody", "cinematic", "dramatic", "silhouette", "glowing", "mysterious", "eerie", "gloomy",
             "atmospheric", "low-key", "lit", "lighting", "light", "shadow", "shadows", "night", "close", "closeup",
             "close-up", "up", "macro", "portrait", "wide", "shot", "angle", "view", "detail", "focus", "movement",
             "action", "footage", "photo", "image", "style", "background", "scene"}


def limpar_busca(busca, maximo=6):
    """A busca só com o assunto: sem palavras de clima ou enquadramento e com no máximo 6 palavras.

    "spectacled cobra Naja naja hood spread dark apartment" vira "spectacled cobra Naja naja hood spread"."""
    palavras = [w for w in (busca or "").split() if w.lower().strip(",.;:") not in _SO_CLIMA]
    return " ".join((palavras or (busca or "").split())[:maximo])


def _variar_termo_busca(busca, k_var=1, alternativa=""):
    """Outra busca do MESMO assunto para uma cena vizinha ou uma fatia de cena dividida.

    Primeiro a busca alternativa que o agente escreveu (nome científico, sinônimo), depois a própria busca com
    um enquadramento diferente. Nunca descarta o assunto: antes, "antivenom serum box" virava "antivenom movement
    action" e qualquer busca com snake virava uma frase fixa, e essas cenas quase nunca achavam acervo."""
    if not busca:
        return busca
    nucleo = " ".join(limpar_busca(busca).split()[:4])
    opcoes = [limpar_busca(alternativa)] if alternativa and limpar_busca(alternativa) != limpar_busca(busca) else []
    opcoes += [f"{nucleo} close up", f"{nucleo} wide shot"]
    return opcoes[(max(1, k_var) - 1) % len(opcoes)]


def _extrair_texto_palavras(palavras, t_ini, t_fim, fallback=""):
    if not palavras:
        return fallback
    pts = [p['texto'] for p in palavras if p.get('ini') is not None and (t_ini - 0.15) <= p['ini'] < (t_fim - 0.05)]
    res = ' '.join(pts).strip()
    return res if len(res) > 3 else fallback


def _sem_a_imagem_da_original(fatia) -> None:
    """O pedaço novo de uma cena dividida não leva a foto ou o vídeo da original: JAMAIS repetir imagem.

    Antes cada pedaço levava uma cópia do material. Narrar de novo com uma voz mais lenta divide as cenas longas, e
    o zz_teste_animacoes, narrado três vezes, chegou a 68 cenas repetindo a imagem da vizinha. O pedaço fica sem
    arquivo, com a foto da original em rejeitadas, até a busca ("Continuar carregamento") trazer uma nova."""
    m = fatia.pop("midia", None) or {}
    if m.get("fonte") and m.get("id"):
        fatia["rejeitadas"] = list(fatia.get("rejeitadas") or []) + [f"{m['fonte']}:{m['id']}"]
    for campo in ("captura", "conferencia", "animacao", "imagem_da_pessoa"):
        fatia.pop(campo, None)


def _tem_material(cena) -> bool:
    return bool((cena.get("midia") or {}).get("arquivo"))


def _fica_o_visual_de(sai, fica, texto_sai, texto_fica) -> bool:
    """Na junção de duas cenas, se a que sai passa a busca (e o material) para a que fica.

    Material que já existe vence: só uma das duas com foto ou vídeo, fica o visual dela (antes, a cena "E onde há fogo
    e carne" do zz_teste_animacoes perdeu a foto da carne no fogo para a busca de um pedaço vizinho sem foto, de texto
    mais longo). As duas com material, ou nenhuma, vale o texto mais longo, como sempre foi."""
    if _tem_material(sai) != _tem_material(fica):
        return _tem_material(sai)
    return len(texto_sai) > len(texto_fica) or (not fica.get("busca") and bool(sai.get("busca")))


def _garantir_limites_estritos(cenas, duracao_total, minimo=ESTILO_MINIMO_SEGUNDOS, maximo=ESTILO_MAXIMO_SEGUNDOS, alvo=ESTILO_ALVO_SEGUNDOS, log=print, alinhamento=None):
    """Garante de forma absoluta que TODAS as cenas tenham duração entre minimo (3.0s) e maximo (5.0s).
    Nenhuma cena ultrapassará 5.0 segundos e nenhuma ficará abaixo de 3.0 segundos.
    Desduplica termos de busca e sincroniza textos falados de fatias.
    """
    if not cenas:
        return []

    palavras = []
    if isinstance(alinhamento, dict):
        palavras = alinhamento.get("palavras") or []
    elif isinstance(alinhamento, list):
        palavras = alinhamento

    # 1. Garantir ini e fim contínuos
    for i in range(len(cenas)):
        cenas[i]["ini"] = 0.0 if i == 0 else cenas[i - 1]["fim"]
        cenas[i]["fim"] = cenas[i + 1]["ini"] if i + 1 < len(cenas) else duracao_total

    # 2. Dividir qualquer cena que passe de maximo (5.0s)
    fatiadas = []
    for c in cenas:
        d = c["fim"] - c["ini"]
        if d <= maximo + 0.001:
            fatiadas.append(dict(c))
        else:
            qtd = max(2, int(round(d / alvo)))
            while d / qtd > maximo:
                qtd += 1
            dur_fatia = d / qtd
            for k in range(qtd):
                fatia = dict(c)
                f_ini = round(c["ini"] + k * dur_fatia, 3)
                f_fim = round(c["ini"] + (k + 1) * dur_fatia, 3) if k + 1 < qtd else c["fim"]
                fatia["ini"] = f_ini
                fatia["fim"] = f_fim
                fatia["texto"] = _extrair_texto_palavras(palavras, f_ini, f_fim, fallback=c.get("texto", ""))
                if k > 0:
                    fatia["texto_tela"] = None
                    fatia["efeito"] = None
                    fatia["_grupo_dividido"] = c.get("n", 0)
                    _sem_a_imagem_da_original(fatia)
                    if fatia.get("busca"):
                        fatia["busca"] = _variar_termo_busca(fatia["busca"], k_var=k, alternativa=fatia.get("busca_alternativa", ""))
                    if fatia.get("prompt"):
                        fatia["prompt"] = f"Dynamic alternative angle, {fatia['prompt']}"
                fatiadas.append(fatia)

    # 3. Eliminar cenas curtas (< minimo) com fusão e balanceamento de cortes entre vizinhas
    for _ in range(40):
        mudou = False
        i = 0
        while i < len(fatiadas):
            d = fatiadas[i]["fim"] - fatiadas[i]["ini"]
            # cena de enumeração tem um mínimo próprio, menor: cada nome dura menos de um segundo
            minimo_aqui = (ESTILO_MINIMO_ENUMERACAO if fatiadas[i].get("enumeracao") or fatiadas[i].get("_curta_aceita")
                           else minimo)
            if d < minimo_aqui - 0.001 and len(fatiadas) > 1:
                # Caso 0: item de lista curto ao lado de OUTRO item citado ("alces" dura 0,6s antes de "cavalos-de-
                # przewalski"). Juntar as duas mostraria um bicho só para os dois nomes: empresta tempo da vizinha
                # mais longa e cada item continua com a própria cena, na hora em que é falado
                if fatiadas[i].get("enumeracao"):
                    falta = minimo_aqui - d
                    vizinhas = []
                    for j in (i - 1, i + 1):
                        if 0 <= j < len(fatiadas) and fatiadas[j].get("busca") != fatiadas[i].get("busca"):
                            dj = fatiadas[j]["fim"] - fatiadas[j]["ini"]
                            min_j = ESTILO_MINIMO_ENUMERACAO if fatiadas[j].get("enumeracao") else minimo
                            if dj - falta >= min_j - 0.001:
                                vizinhas.append((dj, j))
                    if vizinhas:
                        _, j = max(vizinhas)
                        if j < i:
                            corte = round(fatiadas[i]["ini"] - falta, 3)
                            fatiadas[j]["fim"] = fatiadas[i]["ini"] = corte
                        else:
                            corte = round(fatiadas[i]["fim"] + falta, 3)
                            fatiadas[i]["fim"] = fatiadas[j]["ini"] = corte
                        if palavras:
                            for k in (i, j):
                                fatiadas[k]["texto"] = _extrair_texto_palavras(
                                    palavras, fatiadas[k]["ini"], fatiadas[k]["fim"], fallback=fatiadas[k]["texto"])
                        mudou = True
                        i += 1
                        continue
                # Caso A: Fundir 2 cenas vizinhas se soma <= maximo
                if i > 0 and (fatiadas[i - 1]["fim"] - fatiadas[i - 1]["ini"] + d) <= maximo + 0.001:
                    t_ant = fatiadas[i - 1].get("texto", "").strip()
                    t_cur = fatiadas[i].get("texto", "").strip()
                    if _fica_o_visual_de(fatiadas[i], fatiadas[i - 1], t_cur, t_ant):
                        if fatiadas[i].get("busca") or fatiadas[i].get("prompt"):
                            fatiadas[i - 1]["busca"] = fatiadas[i].get("busca", "")
                            fatiadas[i - 1]["prompt"] = fatiadas[i].get("prompt", "")
                            fatiadas[i - 1]["tipo"] = fatiadas[i].get("tipo", fatiadas[i - 1].get("tipo", "ia"))
                            fatiadas[i - 1]["personagem"] = fatiadas[i].get("personagem", False)
                            # o assunto e o que deve aparecer acompanham a busca que ficou
                            for campo in ("sujeito", "mostrar", "animal", "exato", "epoca", "onde_existe", "aceitavel"):
                                fatiadas[i - 1][campo] = fatiadas[i].get(campo, "")
                            # e o material real também vai junto, senão a cena mostra uma coisa e busca outra
                            for campo in ("midia", "captura", "conferencia", "rejeitadas"):
                                if campo in fatiadas[i]:
                                    fatiadas[i - 1][campo] = fatiadas[i][campo]
                                else:
                                    fatiadas[i - 1].pop(campo, None)
                    fatiadas[i - 1]["fim"] = fatiadas[i]["fim"]
                    fatiadas[i - 1]["texto"] = (t_ant + " " + t_cur).strip()
                    fatiadas[i - 1]["texto_tela"] = None
                    fatiadas[i - 1]["efeito"] = None
                    fatiadas.pop(i)
                    mudou = True
                    continue
                elif i + 1 < len(fatiadas) and (fatiadas[i + 1]["fim"] - fatiadas[i + 1]["ini"] + d) <= maximo + 0.001:
                    t_cur = fatiadas[i].get("texto", "").strip()
                    t_seg = fatiadas[i + 1].get("texto", "").strip()
                    if _fica_o_visual_de(fatiadas[i], fatiadas[i + 1], t_cur, t_seg):
                        if fatiadas[i].get("busca") or fatiadas[i].get("prompt"):
                            fatiadas[i + 1]["busca"] = fatiadas[i].get("busca", "")
                            fatiadas[i + 1]["prompt"] = fatiadas[i].get("prompt", "")
                            fatiadas[i + 1]["tipo"] = fatiadas[i].get("tipo", fatiadas[i + 1].get("tipo", "ia"))
                            fatiadas[i + 1]["personagem"] = fatiadas[i].get("personagem", False)
                            # o assunto e o que deve aparecer acompanham a busca que ficou
                            for campo in ("sujeito", "mostrar", "animal", "exato", "epoca", "onde_existe", "aceitavel"):
                                fatiadas[i + 1][campo] = fatiadas[i].get(campo, "")
                            # e o material real também vai junto, senão a cena mostra uma coisa e busca outra
                            for campo in ("midia", "captura", "conferencia", "rejeitadas"):
                                if campo in fatiadas[i]:
                                    fatiadas[i + 1][campo] = fatiadas[i][campo]
                                else:
                                    fatiadas[i + 1].pop(campo, None)
                    fatiadas[i + 1]["ini"] = fatiadas[i]["ini"]
                    fatiadas[i + 1]["texto"] = (t_cur + " " + t_seg).strip()
                    fatiadas[i + 1]["texto_tela"] = None
                    fatiadas[i + 1]["efeito"] = None
                    fatiadas.pop(i)
                    mudou = True
                    continue
                # Caso B: Duas cenas com soma >= 2 * minimo: redistribui o corte ao meio
                elif i > 0 and (fatiadas[i - 1]["fim"] - fatiadas[i - 1]["ini"] + d) >= 2 * minimo:
                    soma = (fatiadas[i - 1]["fim"] - fatiadas[i - 1]["ini"]) + d
                    corte = round(fatiadas[i - 1]["ini"] + soma / 2.0, 3)
                    fatiadas[i - 1]["fim"] = corte
                    fatiadas[i]["ini"] = corte
                    fatiadas[i - 1]["texto_tela"] = None
                    fatiadas[i - 1]["efeito"] = None
                    fatiadas[i]["texto_tela"] = None
                    fatiadas[i]["efeito"] = None
                    if palavras:
                        fatiadas[i - 1]["texto"] = _extrair_texto_palavras(palavras, fatiadas[i - 1]["ini"], fatiadas[i - 1]["fim"], fallback=fatiadas[i - 1]["texto"])
                        fatiadas[i]["texto"] = _extrair_texto_palavras(palavras, fatiadas[i]["ini"], fatiadas[i]["fim"], fallback=fatiadas[i]["texto"])
                    mudou = True
                elif i + 1 < len(fatiadas) and (fatiadas[i + 1]["fim"] - fatiadas[i + 1]["ini"] + d) >= 2 * minimo:
                    soma = d + (fatiadas[i + 1]["fim"] - fatiadas[i + 1]["ini"])
                    corte = round(fatiadas[i]["ini"] + soma / 2.0, 3)
                    fatiadas[i]["fim"] = corte
                    fatiadas[i + 1]["ini"] = corte
                    fatiadas[i]["texto_tela"] = None
                    fatiadas[i]["efeito"] = None
                    fatiadas[i + 1]["texto_tela"] = None
                    fatiadas[i + 1]["efeito"] = None
                    if palavras:
                        fatiadas[i]["texto"] = _extrair_texto_palavras(palavras, fatiadas[i]["ini"], fatiadas[i]["fim"], fallback=fatiadas[i]["texto"])
                        fatiadas[i + 1]["texto"] = _extrair_texto_palavras(palavras, fatiadas[i + 1]["ini"], fatiadas[i + 1]["fim"], fallback=fatiadas[i + 1]["texto"])
                    mudou = True
                # Caso C: 3 cenas adjacentes (i-1, i, i+1) somam tempo para 2 cenas equilibradas
                elif i > 0 and i + 1 < len(fatiadas):
                    soma3 = (fatiadas[i - 1]["fim"] - fatiadas[i - 1]["ini"]) + d + (fatiadas[i + 1]["fim"] - fatiadas[i + 1]["ini"])
                    if soma3 <= 2 * maximo:
                        corte = round(fatiadas[i - 1]["ini"] + soma3 / 2.0, 3)
                        fatiadas[i - 1]["fim"] = corte
                        fatiadas[i + 1]["ini"] = corte
                        fatiadas[i - 1]["texto"] = (fatiadas[i - 1]["texto"] + " " + fatiadas[i]["texto"]).strip()
                        fatiadas[i - 1]["texto_tela"] = None
                        fatiadas[i - 1]["efeito"] = None
                        fatiadas[i + 1]["texto_tela"] = None
                        fatiadas[i + 1]["efeito"] = None
                        if palavras:
                            fatiadas[i - 1]["texto"] = _extrair_texto_palavras(palavras, fatiadas[i - 1]["ini"], fatiadas[i - 1]["fim"], fallback=fatiadas[i - 1]["texto"])
                            fatiadas[i + 1]["texto"] = _extrair_texto_palavras(palavras, fatiadas[i + 1]["ini"], fatiadas[i + 1]["fim"], fallback=fatiadas[i + 1]["texto"])
                        fatiadas.pop(i)
                        mudou = True
                        continue
            i += 1
        if not mudou:
            break

    # 4. Verificação final estrita: NENHUMA cena pode ter > maximo
    novas_finais = []
    for c in fatiadas:
        d = c["fim"] - c["ini"]
        if d > maximo + 0.001:
            metade = round(c["ini"] + d / 2.0, 3)
            c1 = dict(c)
            c1["fim"] = metade
            c1["texto"] = _extrair_texto_palavras(palavras, c1["ini"], c1["fim"], fallback=c.get("texto", ""))
            c2 = dict(c)
            c2["ini"] = metade
            c2["texto"] = _extrair_texto_palavras(palavras, c2["ini"], c2["fim"], fallback=c.get("texto", ""))
            c2["texto_tela"] = None
            c2["efeito"] = None
            c2["_grupo_dividido"] = c.get("n", 0)
            _sem_a_imagem_da_original(c2)
            if c2.get("busca"):
                c2["busca"] = _variar_termo_busca(c2["busca"], k_var=1, alternativa=c2.get("busca_alternativa", ""))
            if c2.get("prompt"):
                c2["prompt"] = f"Dynamic alternative angle, {c2['prompt']}"
            novas_finais.extend([c1, c2])
        else:
            novas_finais.append(c)

    # 5. Desduplicação de termos de busca vizinhos idênticos
    for idx in range(1, len(novas_finais)):
        curr_b = novas_finais[idx].get("busca", "")
        prev_b = novas_finais[idx - 1].get("busca", "")
        if curr_b and curr_b == prev_b:
            novas_finais[idx]["busca"] = _variar_termo_busca(curr_b, k_var=idx, alternativa=novas_finais[idx].get("busca_alternativa", ""))
            if novas_finais[idx].get("prompt") and novas_finais[idx].get("prompt") == novas_finais[idx - 1].get("prompt"):
                novas_finais[idx]["prompt"] = f"Alternative angle, {novas_finais[idx]['prompt']}"

    # 6. Renumerar e garantir sincronia total
    for idx, c in enumerate(novas_finais, start=1):
        c["n"] = idx
        c["ini"] = 0.0 if idx == 1 else novas_finais[idx - 2]["fim"]
        c["fim"] = novas_finais[idx]["ini"] if idx < len(novas_finais) else duracao_total
        c["ini"] = round(c["ini"], 3)
        c["fim"] = round(c["fim"], 3)

        dur = c["fim"] - c["ini"]
        ini_ref = c.pop("_ini_calculo", c["ini"])
        deriva = abs(c["ini"] - ini_ref)

        if c.get("texto_tela"):
            tt_ini = c["texto_tela"].get("inicio", 0.0)
            if tt_ini < 0.0 or tt_ini >= dur or deriva > 1.0:
                c["texto_tela"] = None

        if c.get("efeito"):
            ef_ini = c["efeito"].get("inicio", 0.0)
            if ef_ini < 0.0 or ef_ini >= dur or deriva > 1.0:
                c["efeito"] = None

    return novas_finais


def planejar(projeto, log=print) -> list[dict]:
    from . import avatar

    alinhamento = projeto.ler_json("alinhamento.json")
    if avatar.somente_avatar(projeto.perfil):
        # o personagem fala o vídeo inteiro, então não há o que ilustrar
        cenas = [{"n": 1, "ini": 0.0, "fim": alinhamento["duracao"], "frases": [0, len(alinhamento["unidades"]) - 1],
                  "texto": "", "tipo": "ia", "busca": "", "personagem": False, "prompt": "",
                  "texto_tela": None, "simbolos": [], "titulos": []}]
        projeto.salvar_json("cenas.json", {"cenas": cenas})
        log("  vídeo só com o personagem, sem cenas de imagem")
        return cenas
    unidades = alinhamento["unidades"]
    # o ritmo de corte é do estilo de vídeo, igual em qualquer perfil — não vem do perfil
    alvo = ESTILO_ALVO_SEGUNDOS
    minimo = ESTILO_MINIMO_SEGUNDOS
    maximo = ESTILO_MAXIMO_SEGUNDOS

    if projeto.offline:
        grupos = _agrupar_por_tempo(unidades, alvo, projeto.perfil)
    elif (projeto.config.get("cenas") or {}).get("provedor", "claude") in ("groq", "gemini") and roteirista.ativo(projeto):
        # o JSON de cenas do agente já está pronto (feito pelo texto, antes ou junto da narração): aqui ele só é
        # encaixado no tempo real das palavras. Sem ele, o agente decide sobre os cortes da narração
        grupos = (roteirista.grupos_para_a_narracao(projeto, unidades, log)
                  or roteirista.planejar_grupos(projeto, unidades, _pre_cortar(unidades, alvo, minimo, maximo), log))
    elif (projeto.config.get("cenas") or {}).get("provedor", "claude") in ("groq", "gemini"):
        grupos = _planejar_com_groq(projeto, unidades, alvo, minimo, maximo, log)
    else:
        grupos = _planejar_com_claude(projeto, unidades, alvo, minimo, maximo, log)
    grupos = _juntar_curtas(grupos, unidades, alinhamento["duracao"], minimo)
    grupos = _dividir_longas(grupos, unidades, alinhamento["duracao"], maximo)

    # Regra fixa da fábrica: 90% material real de acervo e 10% IA em qualquer nicho
    mistura = True
    com_textos = textos.ativo(projeto.perfil)
    com_efeitos = efeitos.ativo(projeto.perfil)
    cenas = []
    primeira_ia_do_grupo = {}
    for n, g in enumerate(grupos, start=1):
        frases = unidades[g["primeira_frase"]:g["ultima_frase"] + 1]
        busca = (g.get("busca") or "").strip()
        tipo = g.get("tipo", "ia")
        personagem = bool(g.get("personagem", False))
        if not mistura or personagem or not busca or tipo not in ("foto_real", "video_real"):
            tipo, busca = "ia", ""
        ini = 0.0 if n == 1 else frases[0]["ini"]
        # cenas quebradas pelo limite de segundos (_grupo_dividido) e que viraram ia têm o mesmo
        # prompt: geram uma imagem só, uma vez, e as demais reaproveitam o arquivo, pra não pagar
        # de novo pela mesma cena várias vezes
        # nunca repetir imagem: cada fatia de uma cena dividida ganha a própria imagem, mesmo sendo de IA
        copiar_imagem_de = None
        cenas.append({
            "n": n,
            "ini": ini,
            "_ini_calculo": ini,
            "fim": None,
            "frases": [g["primeira_frase"], g["ultima_frase"]],
            "texto": " ".join(f["texto"] for f in frases),
            "tipo": tipo,
            "busca": busca,
            "personagem": personagem,
            "prompt": (g.get("prompt") or "").strip(),
            "copiar_imagem_de": copiar_imagem_de,
            "enumeracao": bool(g.get("paralela")),
            "citacoes": [c for c in (g.get("citacoes") or []) if (c.get("palavra") or "").strip()],
            "sujeito": (g.get("sujeito") or "").strip(),
            # a espécie exata que o agente disse para a imagem (vazio: não é cena de animal); sem o campo,
            # num projeto antigo, midia.animal_da_cena adivinha pelo bloco
            **({"animal": (g.get("animal") or "").strip()} if "animal" in g else {}),
            **({"exato": (g.get("exato") or "").strip()} if "exato" in g else {}),
            # o ano, quando a imagem tem que ser daquela época (só arquivo: midia.e_de_epoca)
            **({"epoca": (g.get("epoca") or "").strip()} if (g.get("epoca") or "").strip() else {}),
            # onde a imagem existe (banco, arquivo, nao_existe) e o mínimo para a cena estar certa (o Jev julga contra ele)
            **({"onde_existe": g["onde_existe"]} if g.get("onde_existe") else {}),
            **({"aceitavel": g["aceitavel"]} if (g.get("aceitavel") or "").strip() else {}),
            "busca_alternativa": (g.get("busca_alternativa") or "").strip(),
            # do agente de roteiro: o que deve aparecer, a busca pronta caso a cena de IA vire acervo, o texto
            # sugerido e o tipo pensado (mapa, diagrama...), guardado para quando a fábrica desenhar animações
            "mostrar": (g.get("descricao") or "").strip(),
            "busca_reserva": (g.get("busca") or "").strip() if tipo == "ia" else "",
            "overlay": (g.get("overlay") or "").strip(),
            "visual": g.get("visual") or "",
            "fonte_sugerida": g.get("fonte") or "",  # stock ou wikimedia: onde o agente acha que o assunto está
            "bloco": g.get("bloco"),
            "texto_tela": _texto_tela(g.get("texto_tela"), frases, ini, _palavras_da_cena(alinhamento, frases)) if com_textos else None,
            "efeito": _efeito(g.get("efeito"), ini, _palavras_da_cena(alinhamento, frases)) if com_efeitos else None,
        })
    for i, c in enumerate(cenas):
        c["fim"] = cenas[i + 1]["ini"] if i + 1 < len(cenas) else alinhamento["duracao"]
    
    # trechos em que a narração enumera coisas viram uma cena por item, antes de qualquer outro ajuste
    cenas = _dividir_enumeracoes(cenas, alinhamento, log=log)
    # Aplica garantia de proporção do estilo (90% acervo real / 10% IA)
    from .midia import ia_ativa

    cenas = _balancear_proporcao_90_10(cenas, log, sem_ia=not ia_ativa(projeto))
    cenas = _balancear_foto_e_video(cenas, log)
    # os cortes por tempo apagam o texto das cenas que fundem ou se dividem, então guardo o momento
    # absoluto de cada um para devolvê-lo à cena final em que ele é falado
    textos_no_video = [(c["ini"] + c["texto_tela"]["inicio"], c["texto_tela"]) for c in cenas if c.get("texto_tela")]
    # Aplica garantia estrita de cortes de 3 a 5 segundos
    cenas = _garantir_limites_estritos(cenas, alinhamento["duracao"], minimo=minimo, maximo=maximo, alvo=alvo, log=log, alinhamento=alinhamento)
    
    for momento, texto_tela in textos_no_video:
        destino = next((c for c in cenas if c["ini"] <= momento < c["fim"]), None)
        if destino and not destino.get("texto_tela"):
            # se a palavra cai nos últimos instantes da cena, o texto entra um pouco antes dela para ter tempo de aparecer
            inicio = min(momento - destino["ini"], max(0.0, destino["fim"] - destino["ini"] - 1.2))
            destino["texto_tela"] = {**texto_tela, "inicio": round(max(0.0, inicio), 2)}

    if not projeto.offline and (projeto.config.get("cenas") or {}).get("provedor", "claude") in ("groq", "gemini"):
        # com o agente de roteiro, quem decide o que aparece é ele: aqui só as fatias de IA de uma enumeração
        # ganham o prompt da coisa que cada uma cita, e a busca que ele escolheu não é reescrita sem o roteiro
        _refinar_buscas_groq(projeto, cenas, unidades, log, so_ia=roteirista.ativo(projeto))
        # os textos na tela são decididos numa passada só para eles, vendo várias cenas seguidas: o texto sugerido
        # pelo agente entra como dica. Depois o código confere tudo (falado na cena, com fundamento, sem cenas seguidas)
        _textos_na_tela_groq(projeto, cenas, unidades, alinhamento, log)
        _conferir_textos_do_agente(cenas, alinhamento, log)

    _distribuir_simbolos(cenas, alinhamento.get("marcadores") or [], projeto.perfil)
    if not projeto.offline:
        _travar_assunto_por_topico(projeto, cenas, log)
        _destacar_titulos_groq(projeto, cenas, log)
    projeto.salvar_json("cenas.json", {"cenas": cenas})
    return cenas


def _distribuir_simbolos(cenas, marcadores, perfil):
    """Símbolos de pausa e títulos entram na cena em que caem, contados a partir do começo dela.

    Se a cena estiver acabando e não houver tempo de a marcação aparecer e sumir, ela passa
    para o começo da cena seguinte.
    """
    duracoes = {
        "simbolo": float((perfil.get("simbolo") or {}).get("duracao", 6)),
        "titulo": float((perfil.get("titulos") or {}).get("duracao", 7)),
    }
    for c in cenas:
        c["simbolos"], c["titulos"] = [], []
    numero = 0
    for m in marcadores:
        tipo = m.get("tipo", "simbolo")
        if tipo not in duracoes:  # avatar e insertos entram na montagem, não na cena
            continue
        t = m["ini"]
        i = next((k for k, c in enumerate(cenas) if c["ini"] <= t < c["fim"]), len(cenas) - 1)
        if cenas[i]["fim"] - t < min(duracoes[tipo], 3.0) and i + 1 < len(cenas):
            i += 1
            t = cenas[i]["ini"]
        inicio = round(t - cenas[i]["ini"], 2)
        if tipo == "titulo":
            numero += 1
            cenas[i]["titulos"].append({"inicio": inicio, "texto": m.get("texto", ""), "numero": numero})
        else:
            cenas[i]["simbolos"].append(inicio)


ESQUEMA_TOPICO_INGLES = {
    "type": "object",
    "properties": {"termo": {"type": "string"}},
    "required": ["termo"],
    "additionalProperties": False,
}

SISTEMA_TOPICO_INGLES = (
    "Você traduz o nome de um bicho ou assunto, escrito em português, para o termo em inglês que "
    "melhor descreve o que aparece numa foto ou vídeo dele — o mesmo termo que se usaria pra buscar "
    "num banco de imagens em inglês (Pexels, Pixabay, Wikimedia). Responda só com o termo em inglês, "
    "sem explicação, sem aspas."
)


def _termo_ingles_do_topico(projeto, topico_pt, log=print):
    """O [TITULO] é escrito em português pela pessoa, mas sujeito/busca são sempre em inglês (é o que
    os bancos de imagem entendem). Sem traduzir, o travamento por tópico nunca bateria com nada."""
    assinatura = hashlib.sha1(topico_pt.encode("utf-8")).hexdigest()[:10]
    arquivo = projeto.caminho("cenas_lotes", f"topico_ingles_{assinatura}.json")
    if arquivo.exists():
        return json.loads(arquivo.read_text(encoding="utf-8")).get("termo", "")
    try:
        dados = _modelo(projeto).perguntar(projeto, "termo em inglês do tópico", SISTEMA_TOPICO_INGLES, topico_pt,
                                            ESQUEMA_TOPICO_INGLES, log=log, temperatura=0.1)
        termo = (dados.get("termo") or "").strip()
    except (RuntimeError, SystemExit) as e:
        log(f"  não consegui traduzir o tópico '{topico_pt}' ({str(e)[:60]}), sem travar esse trecho")
        termo = ""
    arquivo.write_text(json.dumps({"termo": termo}, ensure_ascii=False), encoding="utf-8")
    return termo


_TERMOS_TAXONOMICOS_VAGOS = {
    "marsupial", "marsupiais", "reptil", "reptiles", "reptile", "reptiles", "felino", "felinos", "feline",
    "wildcat", "wildcats", "primata", "primatas", "primate", "primates", "roedor", "roedores", "rodent",
    "rodents", "ave", "aves", "serpente", "serpentes", "snake", "snakes", "peixe", "peixes", "mamifero",
    "mamiferos", "mammal", "mammals", "anfibio", "anfibios", "amphibian", "aracnideo", "aracnideos",
    "arachnid", "inseto", "insetos", "insect", "insects", "crustaceo", "crustaceos", "ele", "ela",
}


def _travar_assunto_por_topico(projeto, cenas, log=print):
    """Um trecho entre um [TITULO] numerado e o próximo tem um bicho específico como assunto, mas às
    vezes uma cena usa um termo genérico de família ("marsupial", "réptil") em vez do nome dele — e aí a
    busca e o filtro de assunto aceitam o parente errado (um vídeo de canguru numa cena que devia ser de
    petauro-do-açúcar, porque os dois são marsupiais).

    Só troca o sujeito da cena pelo nome do tópico (tirado do [TITULO], traduzido pro inglês) quando o
    sujeito atual é um desses termos genéricos — nunca quando a cena fala de outra coisa de propósito
    (cirurgia, mapa, uma pessoa, outro bicho citado à parte). O primeiro título do vídeo (o geral, sem
    número) não conta: ele não é o nome de um bicho específico.
    """
    from .midia import _radicais

    marcos = sorted(
        (c["n"], t["texto"]) for c in cenas for t in (c.get("titulos") or []) if t.get("numero", 0) > 1
    )
    if not marcos:
        return
    ordenadas = sorted(cenas, key=lambda c: c["n"])
    ultimo_n = ordenadas[-1]["n"]
    total_travadas = 0
    for indice, (inicio_n, texto_titulo) in enumerate(marcos):
        fim_n = marcos[indice + 1][0] - 1 if indice + 1 < len(marcos) else ultimo_n
        topico_pt = re.sub(r"^N[uú]mero\s+\d+\s*[—-]\s*", "", texto_titulo).strip()
        if not topico_pt:
            continue
        topico = _termo_ingles_do_topico(projeto, topico_pt, log)
        radicais_topico = _radicais(topico)
        if not radicais_topico:
            continue
        for c in ordenadas:
            if not (inicio_n <= c["n"] <= fim_n) or c.get("tipo") not in ("foto_real", "video_real"):
                continue
            atual = _radicais(c.get("sujeito") or c.get("busca") or "")
            if not atual or atual & radicais_topico or not (atual & _TERMOS_TAXONOMICOS_VAGOS):
                continue
            c["sujeito"] = topico
            total_travadas += 1
    if total_travadas:
        log(f"  {total_travadas} cena(s) travadas no assunto do trecho, porque a frase da vez não citava o bicho")


ESQUEMA_TITULO_DESTAQUE = {
    "type": "object",
    "properties": {"destaque": {"type": "string"}},
    "required": ["destaque"],
    "additionalProperties": False,
}

SISTEMA_TITULO_DESTAQUE = (
    "Você escolhe qual palavra ou expressão curta (no máximo 3 palavras) de um título de abertura de vídeo "
    "merece aparecer destacada numa cor diferente, pra chamar mais atenção. Escolha o trecho mais forte ou "
    "chamativo, que resuma o gancho do título — não escolha palavra de ligação (como \"que\", \"de\", \"em\"). "
    "Responda com o trecho copiado exatamente como está escrito no título, mesmas maiúsculas/minúsculas e acentos."
)


def _destacar_titulos_groq(projeto, cenas, log):
    """Pede ao modelo qual palavra ou expressão do [TITULO] merece ficar destacada em cor no cartão,
    pra não sair tudo com o mesmo peso visual. Cacheado por texto do título, então roda uma vez só."""
    for c in cenas:
        for t in c.get("titulos") or []:
            texto = (t.get("texto") or "").strip()
            if not texto or t.get("destaque"):
                continue
            assinatura = hashlib.sha1(texto.encode("utf-8")).hexdigest()[:10]
            arquivo = projeto.caminho("cenas_lotes", f"titulo_destaque_{assinatura}.json")
            if arquivo.exists():
                t["destaque"] = json.loads(arquivo.read_text(encoding="utf-8")).get("destaque", "")
                continue
            try:
                dados = _modelo(projeto).perguntar(projeto, "destaque do título", SISTEMA_TITULO_DESTAQUE, texto,
                                                    ESQUEMA_TITULO_DESTAQUE, log=log, temperatura=0.3)
                destaque = (dados.get("destaque") or "").strip()
            except (RuntimeError, SystemExit) as e:
                log(f"  não consegui destacar o título '{texto[:40]}' ({str(e)[:60]}), fica sem destaque")
                destaque = ""
            t["destaque"] = destaque
            arquivo.write_text(json.dumps({"destaque": destaque}, ensure_ascii=False), encoding="utf-8")


def _palavras_da_cena(alinhamento, frases):
    palavras = alinhamento.get("palavras") or []
    if not palavras or "c_ini" not in frases[0]:
        return []
    inicio, fim = frases[0]["c_ini"], frases[-1]["c_fim"]
    return [p for p in palavras if inicio <= p["c"] < fim]


def _simplificar(palavra):
    sem_pontuacao = re.sub(r"[^\w]", "", palavra)
    return unicodedata.normalize("NFKD", sem_pontuacao).encode("ascii", "ignore").decode().casefold()


def _momento_falado(texto, palavras_cena, ini_cena, reserva):
    """Segundo, desde o começo da cena, em que a narração fala esse texto. Se não achar, usa a reserva.

    O texto entra quando a PRIMEIRA palavra importante dele é dita: procura trechos de 3, 2 e 1 palavra de qualquer
    ponto do texto e fica com o que é falado mais cedo. Antes só procurava o começo do texto: "A RIQUEZA EM SÉCULOS DE
    TRADIÇÃO" não achava "a riqueza" na fala e entrava no começo da cena, embora "séculos de tradição" fosse dito no
    fim dela (9 de 23 textos do ouro-da-serra-gaucha entravam assim)."""
    alvo = [_simplificar(p) for p in texto.split() if _simplificar(p)][:8]
    faladas = [_simplificar(p["texto"]) for p in palavras_cena]
    achados = []
    for tamanho in range(min(3, len(alvo)), 0, -1):
        for inicio in range(len(alvo) - tamanho + 1):
            pedaco = alvo[inicio:inicio + tamanho]
            if tamanho == 1 and (len(pedaco[0]) <= 3 or pedaco[0] in _PALAVRAS_VAZIAS):
                continue  # uma palavra curta ou vazia sozinha, como "de" ou "para", casaria no lugar errado
            for k in range(len(faladas) - tamanho + 1):
                if faladas[k:k + tamanho] == pedaco and palavras_cena[k]["ini"] is not None:
                    achados.append(palavras_cena[k]["ini"])
                    break
    if achados:
        return round(max(0.0, min(achados) - ini_cena), 2)
    return reserva


_PALAVRAS_VAZIAS = {"para", "pela", "pelo", "pelos", "pelas", "mais", "menos", "esse", "essa", "isso", "este", "esta",
                    "isto", "aquele", "aquela", "como", "quando", "onde", "sobre", "entre", "cada", "todo", "toda",
                    "todos", "todas", "muito", "muita", "mesmo", "mesma", "ainda", "apenas", "depois", "antes", "porque",
                    "nossa", "nosso", "seus", "suas", "dele", "dela", "eles", "elas", "voce", "quem", "qual", "quais",
                    "sera", "seria", "foram", "eram", "sido", "estao", "esta", "tambem", "assim", "entao", "nunca"}


def _texto_tela(bruto, frases, ini_cena, palavras_cena=()):
    """Converte o momento do texto em segundos desde o começo da cena e descarta texto incompleto."""
    bruto = bruto or {}
    tipo = bruto.get("tipo", "nenhum")
    if tipo not in textos.TIPOS:
        return None
    momento = {f["id"]: round(max(0.0, f["ini"] - ini_cena), 2) for f in frases}
    reserva = momento.get(bruto.get("frase"), 0.0)
    itens = [
        {"texto": i["texto"].strip(), "frase": i.get("frase"),
         "inicio": _momento_falado(i["texto"], palavras_cena, ini_cena, momento.get(i.get("frase"), 0.0))}
        for i in bruto.get("itens") or []
        if (i.get("texto") or "").strip()
    ][:6]
    texto = (bruto.get("texto") or "").strip()
    titulo = (bruto.get("titulo") or "").strip()
    inicio = reserva
    if tipo == "destaque":
        inicio = _momento_falado(texto, palavras_cena, ini_cena, reserva)
    elif tipo == "rotulo":
        inicio = _momento_falado(titulo or texto, palavras_cena, ini_cena, reserva)
    elif tipo == "lista" and itens:
        inicio = min(reserva, itens[0]["inicio"])
    resultado = {
        "tipo": tipo,
        "frase": bruto.get("frase"),
        "texto": texto,
        "destaque": (bruto.get("destaque") or "").strip(),
        "titulo": titulo,
        "inicio": inicio,
        "itens": itens,
    }
    essencial = {
        "destaque": resultado["texto"],
        "lista": itens,
        "capitulo": resultado["texto"],
        "rotulo": resultado["titulo"] or resultado["texto"],
    }[tipo]
    return resultado if essencial else None


def _efeito(bruto, ini_cena, palavras_cena=()):
    """Efeito sonoro da cena, com o segundo em que ele bate contado a partir do começo dela."""
    bruto = bruto or {}
    descricao = (bruto.get("descricao") or "").strip()
    if not descricao:
        return None
    palavra = (bruto.get("palavra") or "").strip()
    return {
        "descricao": descricao,
        "palavra": palavra,
        "duracao": round(min(max(float(bruto.get("duracao") or 3), 1.0), 8.0), 1),
        "inicio": _momento_falado(palavra, palavras_cena, ini_cena, 0.0) if palavra else 0.0,
    }


def atualizar_tempos(projeto):
    """Recalcula o tempo das cenas e dos textos depois de a narração mudar de ritmo, sem chamar o Claude."""
    alinhamento = projeto.ler_json("alinhamento.json")
    unidades, duracao = alinhamento["unidades"], alinhamento["duracao"]
    dados = projeto.ler_json("cenas.json")
    # projetos antigos não guardavam o número das frases dos textos, mas a resposta do Claude guardou
    originais = {}
    for arquivo in sorted((projeto.pasta / "cenas_lotes").glob("lote_*.json")):
        for g in json.loads(arquivo.read_text(encoding="utf-8")):
            originais[(g["primeira_frase"], g["ultima_frase"])] = g.get("texto_tela")
    cenas = dados["cenas"]
    duracao_antes = {c["n"]: c["fim"] - c["ini"] for c in cenas}
    # cada cena começa onde as primeiras palavras DELA são faladas. Antes valia o começo da frase: cena cortada no meio
    # da frase ("podem ver." | "Frotas de colheitadeiras") ficava com duração zero, o corte juntava e dividia tudo, e
    # regerar o áudio sem mudar nada levava o zz_teste_animacoes de 252 para 260 cenas, com 249 mudadas
    # o jeito certo: o tempo de cada palavra da narração anterior leva cada corte de cena para o mesmo ponto da fala
    # (a mesma narração não muda nada; voz mais rápida encolhe tudo junto). Sem ele, ou com o roteiro mudado, cada
    # cena é achada pelas primeiras palavras dela
    mapear = None
    if projeto.existe("alinhamento_anterior.json"):
        try:
            mapear = _mapa_de_tempo(projeto.ler_json("alinhamento_anterior.json"), alinhamento)
        except (OSError, ValueError, KeyError):
            mapear = None
    falada = {} if mapear else _inicios_pela_fala(cenas, alinhamento.get("palavras") or [])
    anterior = 0.0
    for i, c in enumerate(cenas):
        frases = unidades[c["frases"][0]:c["frases"][1] + 1]
        inicio = mapear(c["ini"]) if mapear else falada.get(c["n"], frases[0]["ini"])
        c["ini"] = 0.0 if i == 0 else max(inicio, anterior)
        anterior = c["ini"]
        c["_ini_calculo"] = c["ini"]
        if c.get("efeito"):
            c["efeito"] = _efeito(c["efeito"], c["ini"], _palavras_da_cena(alinhamento, frases)) or c["efeito"]
        texto_tela = c.get("texto_tela")
        if not texto_tela:
            continue
        base = dict(originais.get(tuple(c["frases"])) or {})
        base.update({k: texto_tela[k] for k in ("tipo", "texto", "destaque", "titulo") if k in texto_tela})
        if texto_tela.get("frase") is not None:
            base["frase"] = texto_tela["frase"]
        if texto_tela.get("itens") and all(item.get("frase") is not None for item in texto_tela["itens"]):
            base["itens"] = texto_tela["itens"]
        if base.get("frase") is not None:
            c["texto_tela"] = _texto_tela(base, frases, c["ini"], _palavras_da_cena(alinhamento, frases)) or texto_tela
    for i, c in enumerate(cenas):
        c["fim"] = cenas[i + 1]["ini"] if i + 1 < len(cenas) else duracao
    # a fala de cada cena no tempo novo, antes do corte: a imagem numerada dela segue essa fala (ver abaixo)
    trechos = _trechos_pela_fala(cenas, alinhamento.get("palavras") or [], duracao)
    # a foto que a pessoa subiu do computador manda: sem IA ligada, toda imagem numerada só pode ter vindo dela
    from .midia import ia_ativa
    # (cena que já mostra material real tem a imagem numerada escondida, velha: essa não manda)
    da_pessoa = {c["n"] for c in cenas if (c.get("imagem_da_pessoa") or not ia_ativa(projeto))
                 and not (c.get("midia") or {}).get("arquivo")}
    escondidas = {c["n"] for c in cenas if (c.get("midia") or {}).get("arquivo")}
    # as cenas só mudam se a fala nova desequilibrar alguma: passou de 5 s, ou ficou abaixo do mínimo sem já ser
    # curta antes. Cena curta que já tinha sido aceita (o "selados." de 1 s) fica protegida no corte
    desequilibradas = [c["n"] for c in cenas if _desequilibrou(c, duracao_antes.get(c["n"]))]
    if desequilibradas:
        for c in cenas:
            antes = duracao_antes.get(c["n"])
            if (antes is not None and antes < ESTILO_MINIMO_SEGUNDOS - FOLGA_NA_TROCA_DE_VOZ - 0.001
                    and c["fim"] - c["ini"] >= antes - 0.3):
                c["_curta_aceita"] = True
        cenas = _garantir_limites_estritos(cenas, duracao, ESTILO_MINIMO_SEGUNDOS - FOLGA_NA_TROCA_DE_VOZ,
                                           ESTILO_MAXIMO_SEGUNDOS + FOLGA_NA_TROCA_DE_VOZ, ESTILO_ALVO_SEGUNDOS,
                                           alinhamento=alinhamento)
        for c in cenas:
            c.pop("_curta_aceita", None)
    else:
        for c in cenas:
            c.pop("_ini_calculo", None)
            c["ini"], c["fim"] = round(c["ini"], 3), round(c["fim"], 3)
    _levar_imagens_numeradas(projeto, cenas, trechos, da_pessoa, escondidas)
    # cena com material real e tipo "ia" sem imagem numerada (a junção trouxe o tipo de uma e o material da outra)
    # volta ao tipo do material
    for c in cenas:
        m = c.get("midia") or {}
        if m.get("arquivo") and c.get("tipo") == "ia" and not projeto.imagem(c["n"]).exists():
            c["tipo"] = "video_real" if m.get("tipo") == "video" else "foto_real"
    dados["cenas"] = cenas
    _distribuir_simbolos(cenas, alinhamento.get("marcadores") or [], projeto.perfil)
    projeto.salvar_json("cenas.json", dados)


def _mapa_de_tempo(anterior: dict, atual: dict):
    """Função que leva um segundo da narração anterior para o mesmo ponto da fala na atual, ou None.

    Só vale com as mesmas palavras nas duas (o roteiro não mudou): entre duas palavras, o ponto é interpolado."""
    import bisect

    pa, pn = anterior.get("palavras") or [], atual.get("palavras") or []
    if not pa or len(pa) != len(pn) or any(a.get("texto") != b.get("texto") for a, b in zip(pa, pn)):
        return None
    pares = [(0.0, 0.0)]
    for a, b in zip(pa, pn):
        if a.get("ini") is None or b.get("ini") is None:
            continue
        if a["ini"] > pares[-1][0] and b["ini"] >= pares[-1][1]:
            pares.append((float(a["ini"]), float(b["ini"])))
    fim_a, fim_n = float(anterior.get("duracao") or 0), float(atual.get("duracao") or 0)
    if fim_a > pares[-1][0] and fim_n >= pares[-1][1]:
        pares.append((fim_a, fim_n))
    velhos = [x for x, _ in pares]

    def mapear(t):
        k = max(0, min(bisect.bisect_right(velhos, t) - 1, len(pares) - 2))
        (a0, b0), (a1, b1) = pares[k], pares[k + 1]
        if t >= a1:
            return b1 + (t - a1)
        return b0 + (t - a0) * (b1 - b0) / (a1 - a0) if a1 > a0 else b0

    return mapear


# folga nos limites quando a narração é trocada: a pessoa quer as mesmas cenas, e uma voz 10% mais rápida ou mais
# lenta não pode recortar o vídeo inteiro (com o limite seco, a fala 8% mais lenta levava 252 cenas a 260)
FOLGA_NA_TROCA_DE_VOZ = 0.5


def _desequilibrou(cena, duracao_antes) -> bool:
    """A fala nova deixou a cena fora do limite (3 a 5 s, com a folga da troca de voz), e não porque já era assim."""
    agora = cena["fim"] - cena["ini"]
    if agora > ESTILO_MAXIMO_SEGUNDOS + FOLGA_NA_TROCA_DE_VOZ + 0.001:
        return True
    minimo = ESTILO_MINIMO_ENUMERACAO if cena.get("enumeracao") else ESTILO_MINIMO_SEGUNDOS
    if agora >= minimo - FOLGA_NA_TROCA_DE_VOZ - 0.001:
        return False
    return duracao_antes is None or agora < duracao_antes - 0.3


def _inicios_pela_fala(cenas, palavras) -> dict:
    """Segundo em que as primeiras palavras de cada cena são faladas, achadas em ordem no tempo de cada palavra."""
    normal = lambda t: re.sub(r"[^\w]", "", t.lower())
    sequencia = [normal(p.get("texto", "")) for p in palavras]
    inicios, cursor = {}, 0
    for c in cenas:
        alvo = [w for w in (normal(x) for x in (c.get("texto") or "").split()) if w][:3]
        if not alvo:
            continue
        for j in range(cursor, min(len(sequencia) - len(alvo) + 1, cursor + 400)):
            if sequencia[j:j + len(alvo)] == alvo and palavras[j].get("ini") is not None:
                inicios[c["n"]] = float(palavras[j]["ini"])
                cursor = j + 1
                break
    return inicios


def _trechos_pela_fala(cenas, palavras, duracao):
    """Começo e fim da fala de cada cena (pelo número antigo) no tempo da narração nova.

    O ini que atualizar_tempos calcula é o começo da FRASE: duas cenas cortadas no meio da mesma frase ("As facas
    forjadas nestas fazendas e" | "e pequenas oficinas") ficavam com duração zero. Aqui cada cena é achada pelas
    primeiras palavras dela, em ordem, no tempo de cada palavra; o trecho vai até o começo da cena seguinte."""
    inicios = _inicios_pela_fala(cenas, palavras)
    trechos = {}
    for i, c in enumerate(cenas):
        a = inicios.get(c["n"], c["ini"])
        seguinte = next((inicios[x["n"]] for x in cenas[i + 1:] if x["n"] in inicios), None)
        b = seguinte if seguinte is not None and seguinte > a else max(c["fim"], a)
        trechos[c["n"]] = (a, b if i + 1 < len(cenas) else duracao)
    return trechos


def _levar_imagens_numeradas(projeto, cenas, trechos, da_pessoa=(), escondidas=()):
    """Depois de recortar as cenas, cada imagem imagens/NNNN.png vai para a cena nova que mais cobre a fala dela.

    A imagem de IA e a foto que a pessoa subiu do computador ficam guardadas pelo número da cena. Narrar de novo com
    outra voz muda o ritmo, as cenas se dividem, se juntam e são renumeradas: antes as imagens ficavam com o número
    velho, a cena dona ficava sem arquivo e outra cena passava a mostrar a imagem errada (no zz_teste_animacoes, a foto
    da faca artesanal da cena 112 ficou na 112 nova e a 129, a dona, ficou vazia).

    trechos traz, para cada número antigo, o começo e o fim da fala dele no tempo NOVO. A imagem vai para a cena nova
    sem material real que mais se sobrepõe a esse trecho, uma imagem por cena (a imagem não se repete no vídeo: a
    outra metade de uma cena dividida fica sem arquivo até o "Continuar carregamento"). A foto que a pessoa subiu
    (da_pessoa) vai antes e vence o material de acervo: na junção de cenas, a do zz_teste_animacoes "Ela é sempre
    colocada deitada" perdia o lugar para a foto de banco da cena vizinha. A imagem que estava escondida atrás de
    material real (escondidas) só vai para outra cena com material real, para não reaparecer numa cena livre. Imagem
    sem cena vai para imagens/_sem_cena, sem ser apagada."""
    pasta = projeto.pasta / "imagens"
    if not pasta.is_dir():
        return
    arquivos = {int(a.stem): a for a in pasta.glob("[0-9][0-9][0-9][0-9].png")}
    if not arquivos:
        return
    pares = []
    for antigo in arquivos:
        if antigo not in trechos:
            continue
        a, b = trechos[antigo]
        for c in cenas:
            sobra = min(b, c["fim"]) - max(a, c["ini"])
            if sobra > 0.05:
                pares.append((sobra, antigo, c))
    for c in cenas:
        c.pop("imagem_da_pessoa", None)  # a marca volta só na cena que ficar com a foto
    donos, ocupadas = {}, set()

    def dar(antigo, c):
        if (c.get("midia") or {}).get("arquivo") and antigo not in escondidas:
            for campo in ("midia", "captura", "conferencia"):
                c.pop(campo, None)
        donos[antigo] = c["n"]
        ocupadas.add(c["n"])
        if antigo in da_pessoa:
            c["imagem_da_pessoa"] = True
        if c.get("tipo") in ("foto_real", "video_real") and not (c.get("midia") or {}).get("arquivo"):
            c["tipo"] = "ia"  # sem material real, a cena mostra a imagem numerada

    ordem = sorted(pares, key=lambda x: (x[1] not in da_pessoa, -x[0]))
    # 1ª passada: cena livre que cobre boa parte da fala. 2ª: o que sobrou, e a foto da pessoa pode tirar o acervo
    for passada in (1, 2):
        for sobra, antigo, c in ordem:
            if antigo in donos or c["n"] in ocupadas:
                continue
            tem_material = bool((c.get("midia") or {}).get("arquivo"))
            if antigo in escondidas:
                if tem_material:
                    dar(antigo, c)
                continue
            if passada == 1:
                a, b = trechos[antigo]
                if not tem_material and sobra >= 0.35 * (b - a):
                    dar(antigo, c)
            elif not tem_material or antigo in da_pessoa:
                dar(antigo, c)
    if all(donos.get(k) == k for k in arquivos):
        return
    # duas passadas, por uma pasta de passagem: a 0112 pode ir para a 0128 enquanto a 0128 vai para a 0146
    passagem = pasta / "_renumerando"
    passagem.mkdir(exist_ok=True)
    for arquivo in arquivos.values():
        arquivo.replace(passagem / arquivo.name)
    carimbo = time.strftime("%Y%m%d-%H%M%S")
    for antigo in arquivos:
        origem = passagem / f"{antigo:04d}.png"
        if antigo in donos:
            origem.replace(pasta / f"{donos[antigo]:04d}.png")
        else:
            (pasta / "_sem_cena").mkdir(exist_ok=True)
            origem.replace(pasta / "_sem_cena" / f"{antigo:04d}_{carimbo}.png")
    passagem.rmdir()


def _planejar_com_claude(projeto, unidades, alvo, minimo, maximo, log):
    cfg = projeto.config.get("claude") or {}
    tamanho = cfg.get("unidades_por_lote", 120)
    lotes = [unidades[i:i + tamanho] for i in range(0, len(unidades), tamanho)]
    sistema = _sistema(projeto.perfil, tx.normalizar(projeto.roteiro()), alvo, minimo, maximo)
    nome_provedor = "Claude"
    log(f"  {len(lotes)} lote(s) de frases com {nome_provedor}")
    # o primeiro lote grava o roteiro no cache e os demais aproveitam, em paralelo
    resultados = [_planejar_lote(projeto, sistema, lotes[0], 0, cfg, log)]
    if len(lotes) > 1:
        with ThreadPoolExecutor(cfg.get("processos", 2)) as executor:
            resultados += executor.map(
                lambda par: _planejar_lote(projeto, sistema, par[1], par[0], cfg, log),
                list(enumerate(lotes))[1:],
            )
    return [cena for lote in resultados for cena in lote]


# uma coisa visual diferente citada pela narração dentro da cena: o código corta a cena onde cada uma é falada
CITACAO = {
    "type": "object",
    "properties": {"palavra": {"type": "string"}, "busca": {"type": "string"}, "prompt": {"type": "string"}},
    "required": ["palavra", "busca", "prompt"],
    "additionalProperties": False,
}

CENA_GROQ = {
    "type": "object",
    "properties": {
        "n": {"type": "integer"},
        "sujeito": {"type": "string"},
        "tipo": {"type": "string", "enum": ["foto_real", "video_real", "ia"]},
        "busca": {"type": "string"},
        "busca_alternativa": {"type": "string"},
        "prompt": {"type": "string"},
        "personagem": {"type": "boolean"},
        "citacoes": {"type": "array", "items": CITACAO},
        "texto_tela": TEXTO_TELA,
        "efeito": EFEITO,
    },
    "required": ["n", "sujeito", "tipo", "busca", "busca_alternativa", "prompt", "personagem", "citacoes", "texto_tela", "efeito"],
    "additionalProperties": False,
}

# Para o Groq os cortes já chegam prontos (o código mede os segundos), e ele só decide o que
# aparece em cada cena. A ordem dos campos importa: sujeito vem antes de tipo e busca para o
# modelo dizer primeiro o que a narração cita e só depois escolher a imagem.
ESQUEMA_GROQ = {
    "type": "object",
    "properties": {"cenas": {"type": "array", "items": CENA_GROQ}},
    "required": ["cenas"],
    "additionalProperties": False,
}

SISTEMA_GROQ = """Você é o diretor de arte de um canal do YouTube. A narração de um vídeo já foi cortada em cenas numeradas de 3 a 5 segundos. Você NÃO corta nem junta cenas: se uma cena cita várias coisas, você só as lista em citacoes e o código faz o corte. Para cada cena recebida você decide o que aparece na tela enquanto ela é narrada.

Como responder
- Devolva UM item por cena recebida, com o mesmo n, na mesma ordem. Nunca pule uma cena e nunca invente cenas.
- As cenas marcadas como contexto servem só para você entender o assunto. Não devolva itens para elas.
- Preencha os campos nesta ordem de raciocínio. Primeiro sujeito, depois tipo, busca, prompt.

Regras
1. sujeito é a coisa concreta que a narração cita dentro DESTA cena, em inglês, em poucas palavras (por exemplo lionfish, jellyfish, pufferfish, beach, hospital). Se a cena cita um animal, lugar ou objeto pelo nome, o sujeito é esse. Se a frase é abstrata, escolha um detalhe visual que a traduza. Nunca use o sujeito de outra cena.
2. busca e prompt têm que mostrar o sujeito. Se o sujeito é lionfish, a busca fala de lionfish, nunca de outro animal nem de um termo genérico como sea danger ou marine life.
3. Nunca copie a busca de uma cena vizinha só porque o tema é parecido. Varie o enquadramento entre cenas vizinhas (close, plano aberto, detalhe, ação).
4. Escreva o prompt em inglês, como a descrição de uma fotografia. Diga o sujeito, a ação, o enquadramento, o ambiente e os detalhes importantes. Não descreva o estilo geral da imagem, ele é acrescentado depois. Escreva o prompt em todas as cenas, inclusive nas reais.
5. Nunca peça texto escrito, letras, placas legíveis ou logotipos dentro da imagem.
6. Prefira composições fortes, com luz dramática, close em detalhes e sensação de escala. Fuja da imagem genérica de banco de imagens.
7. Em texto_tela, frase é o número de uma frase que pertence a esta cena, entre colchetes na lista da cena. Nunca use o número de frase de outra cena.
10. busca_alternativa: outro jeito de procurar o MESMO assunto, para quando a busca principal render pouco. De 2 a 4 palavras em inglês, diferente da busca: o nome científico de um bicho ou planta, um sinônimo, um termo mais técnico ou mais geral. Nunca mude de assunto, e nunca repita a busca.
8. Texto na tela não é opcional quando a orientação do canal o pede. Se a cena tem o que a orientação manda destacar (um nome citado, um número, uma enumeração), preencha texto_tela com o tipo certo. Use nenhum só nas cenas em que nada disso aparece, o que normalmente é a maioria, mas nunca em todas.
9. citacoes: se a narração desta cena cita duas ou mais coisas visuais DIFERENTES (animais, objetos, lugares, pessoas, como "cobras, aranhas e escorpiões" ou "um Scania, um DAF e um Volvo"), devolva uma citação para cada uma, na ordem em que são faladas. palavra é a primeira palavra da citação, escrita exatamente como está no texto da cena. busca e prompt mostram só aquela coisa. Se a cena cita uma coisa só, ou nenhuma, devolva citacoes vazio. Não invente citações: só entram coisas que a narração fala.

{secao_midia}

{secao_bancos}

{secao_textos}

{secao_efeitos}

{secao_personagem}

Diretrizes do canal
{diretrizes}

Exemplo do formato de uma cena (os valores mudam conforme a narração)
{{"n": 7, "sujeito": "lionfish", "tipo": "video_real", "busca": "lionfish coral reef", "prompt": "A lionfish drifting over a coral reef, spines spread, side view, clear blue water", "personagem": false, "texto_tela": {{"tipo": "nenhum", "texto": "", "destaque": "", "titulo": "", "frase": 12, "itens": []}}, "efeito": {{"descricao": "", "palavra": "", "duracao": 0}}}}"""


class _ComReserva:
    """Tenta cada passo da cascata em ordem; se um falhar (erro ou cota), cai para o próximo."""

    def __init__(self, passos):
        self.passos = passos  # lista de (nome, modulo, modelo_fixo_ou_None)

    def perguntar(self, projeto, etapa, instrucoes, pedido, esquema, log=print, **resto):
        erro = None
        for indice, (nome, modulo, modelo_fixo) in enumerate(self.passos):
            chamada = dict(resto)
            if modelo_fixo:
                chamada["modelo"] = modelo_fixo
            elif indice > 0:
                chamada.pop("modelo", None)  # a reserva usa o próprio modelo padrão dela, não o do passo anterior
            try:
                return modulo.perguntar(projeto, etapa, instrucoes, pedido, esquema, log=log, **chamada)
            except (RuntimeError, SystemExit) as e:
                erro = e
                if indice + 1 < len(self.passos):
                    log(f"  {nome} falhou ({str(e)[:90]}), usando {self.passos[indice + 1][0]}")
        raise erro


def _modelo(projeto):
    """Quem responde pelas cenas, textos e buscas: o modelo principal (openrouter.modelo_principal, hoje o Space
    Bunny). MiMo, Groq e Gemini não são mais usados."""
    return _ComReserva([("modelo principal", openrouter_local, openrouter_local.principal(projeto))])


def _pre_cortar(unidades, alvo, minimo, maximo):
    """Corta as frases em cenas de minimo a maximo segundos, sem chamar nenhum modelo.

    Fecha a cena ao chegar no alvo, ao fim de uma frase completa depois do mínimo, ou quando a
    próxima frase estouraria o máximo. Uma frase sozinha maior que o máximo fica numa cena só e
    é dividida por tempo depois, em _garantir_limites_estritos.
    """
    grupos, inicio = [], 0
    paralelas = _frases_paralelas(unidades)
    for i, u in enumerate(unidades):
        duracao = u["fim"] - unidades[inicio]["ini"]
        ultima = i == len(unidades) - 1
        estoura = not ultima and unidades[i + 1]["fim"] - unidades[inicio]["ini"] > maximo
        fim_de_frase = u["texto"].rstrip().endswith((".", "?", "!", "…"))
        if i in paralelas:
            # "Cobras estão nessa lista. Aranhas estão nessa lista.": cada frase paralela é uma cena, com a imagem do que ela cita
            grupos.append({"primeira_frase": inicio, "ultima_frase": i, "paralela": True})
            inicio = i + 1
        elif ultima or estoura or duracao >= alvo or (fim_de_frase and duracao >= minimo):
            grupos.append({"primeira_frase": inicio, "ultima_frase": i})
            inicio = i + 1
    return grupos


def _frases_paralelas(unidades):
    """Índices das frases curtas que se repetem no final, uma citando cada coisa: "X está nessa lista. Y está nessa lista.".

    Precisam ser duas ou mais seguidas, terminadas em ponto, e com pelo menos um segundo cada, o mínimo das cenas de enumeração."""
    def final(u):
        palavras = [_simplificar(w) for w in u["texto"].split()]
        return tuple(w for w in palavras if w)[-3:]

    achadas, i = set(), 0
    while i < len(unidades):
        j = i
        chave = final(unidades[i])
        while (j + 1 < len(unidades) and len(chave) == 3 and final(unidades[j + 1]) == chave):
            j += 1
        seguidas = range(i, j + 1)
        if j > i and all(unidades[k]["texto"].rstrip().endswith(".") and
                         ESTILO_MINIMO_ENUMERACAO <= unidades[k]["fim"] - unidades[k]["ini"] <= ESTILO_MINIMO_SEGUNDOS
                         for k in seguidas):
            achadas.update(seguidas)
        i = j + 1
    return achadas


def _sistema_groq(perfil):
    return SISTEMA_GROQ.format(**_secoes(perfil))


def _planejar_com_groq(projeto, unidades, alvo, minimo, maximo, log):
    cfg = projeto.config.get("groq") or {}
    cortes = _pre_cortar(unidades, alvo, minimo, maximo)
    por_lote = cfg.get("cenas_por_lote", 20)
    antes, depois = cfg.get("contexto_antes", 3), cfg.get("contexto_depois", 2)
    sistema = _sistema_groq(projeto.perfil)
    lotes = [range(i, min(i + por_lote, len(cortes))) for i in range(0, len(cortes), por_lote)]
    log(f"  {len(cortes)} cortes prontos, {len(lotes)} lote(s) de cenas")

    resultado = []
    for indice, lote in enumerate(lotes):
        assinatura = hashlib.sha1(
            (sistema + json.dumps([cortes[k] for k in lote])).encode("utf-8")).hexdigest()[:10]
        arquivo = projeto.caminho("cenas_lotes", f"groq_{indice:03d}_{assinatura}.json")
        if arquivo.exists():
            resultado += json.loads(arquivo.read_text(encoding="utf-8"))
            continue
        contexto_antes = range(max(0, lote.start - antes), lote.start)
        contexto_depois = range(lote.stop, min(len(cortes), lote.stop + depois))
        decididas = _decidir_cenas_groq(projeto, sistema, unidades, cortes, lote, contexto_antes,
                                        contexto_depois, cfg, log)
        grupos = [{**cortes[k], **decididas[k]} for k in lote]
        arquivo.write_text(json.dumps(grupos, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"  lote {indice + 1} pronto com {len(grupos)} cenas")
        resultado += grupos
    return resultado


def _linhas_cena(unidades, cortes, k):
    g = cortes[k]
    frases = unidades[g["primeira_frase"]:g["ultima_frase"] + 1]
    duracao = frases[-1]["fim"] - frases[0]["ini"]
    corpo = "\n".join(f"  [{f['id']}] {f['texto']}" for f in frases)
    return f"CENA {k + 1} | {duracao:.1f}s\n{corpo}"


def _grande_demais(erro) -> bool:
    """O modelo recusou o pedido por tamanho (413), e não por limite de uso."""
    return "413" in str(erro) or "too large" in str(erro).lower()


def _pedindo_em_partes(pedir, itens, log, rotulo="cenas"):
    """Chama pedir(itens) e, se o pedido for grande demais, parte a lista no meio até caber.

    Cenas de narração longa fazem um lote passar do limite de tokens por minuto do Groq. Em vez de
    perder o lote inteiro, ele é dividido. Devolve as respostas de todas as partes, juntas."""
    try:
        return pedir(itens)
    except RuntimeError as e:
        if not _grande_demais(e) or len(itens) < 2:
            raise
        meio = len(itens) // 2
        log(f"  pedido grande demais para {len(itens)} {rotulo}, dividindo em dois")
        return (_pedindo_em_partes(pedir, itens[:meio], log, rotulo)
                + _pedindo_em_partes(pedir, itens[meio:], log, rotulo))


def _decidir_cenas_groq(projeto, sistema, unidades, cortes, lote, antes, depois, cfg, log, tentativa=0):
    """Pede ao Groq as decisões visuais das cenas do lote e devolve {indice: decisão}.

    O que faltar ou vier com número errado é pedido de novo uma vez. Depois disso, a cena ganha
    uma decisão reserva feita do próprio texto, só para o vídeo não parar.
    """
    lote = list(lote)
    blocos = []
    if len(antes):
        blocos.append("Contexto anterior, não devolva:\n" + "\n".join(_linhas_cena(unidades, cortes, k) for k in antes))
    blocos.append(
        f"Cenas para decidir. Devolva exatamente {len(lote)} itens, com n de {lote[0] + 1} a {lote[-1] + 1}. "
        + "\n".join(_linhas_cena(unidades, cortes, k) for k in lote))
    if len(depois):
        blocos.append("Contexto seguinte, não devolva:\n" + "\n".join(_linhas_cena(unidades, cortes, k) for k in depois))

    try:
        resposta = _modelo(projeto).perguntar(projeto, "cenas", sistema, "\n\n".join(blocos), ESQUEMA_GROQ, log=log)
    except RuntimeError as e:
        # cenas de narração longa fazem o pedido passar do limite de tokens por minuto: parte no meio
        if not _grande_demais(e) or len(lote) < 2:
            raise
        meio = len(lote) // 2
        log(f"  pedido grande demais para {len(lote)} cenas, dividindo em dois")
        metades = {}
        for parte in (lote[:meio], lote[meio:]):
            metades.update(_decidir_cenas_groq(projeto, sistema, unidades, cortes, parte, antes, depois, cfg, log, tentativa))
        return metades
    validas = {k + 1: k for k in lote}
    obtidas = {}
    for item in resposta.get("cenas", []):
        k = validas.get(item.get("n"))
        if k is not None and k not in obtidas and (item.get("prompt") or "").strip():
            obtidas[k] = {c: item.get(c) for c in ("tipo", "sujeito", "busca", "busca_alternativa", "personagem", "prompt", "citacoes", "texto_tela", "efeito")}
    faltam = [k for k in lote if k not in obtidas]
    if faltam and tentativa == 0:
        log(f"  Groq deixou {len(faltam)} cena(s) sem resposta, pedindo de novo")
        # pede só as que faltam, com as demais como contexto
        novas = _decidir_cenas_groq(projeto, sistema, unidades, cortes, faltam, antes, depois, cfg, log, tentativa=1)
        obtidas.update(novas)
        faltam = [k for k in lote if k not in obtidas]
    for k in faltam:
        frases = unidades[cortes[k]["primeira_frase"]:cortes[k]["ultima_frase"] + 1]
        texto = " ".join(f["texto"] for f in frases)
        log(f"  cena {k + 1} sem resposta do Groq, usando imagem de IA com o texto da cena")
        obtidas[k] = {"tipo": "ia", "busca": "", "personagem": False, "prompt": texto,
                      "citacoes": [], "texto_tela": None, "efeito": None}
    return obtidas


def _refinar_buscas_groq(projeto, cenas, unidades, log, so_ia=False):
    """Refaz a busca das cenas de material real cujo texto mudou depois dos cortes por tempo.

    Uma cena cortada no meio da frase, ou fundida com a vizinha, herdaria a busca decidida para
    outro trecho da narração (era o caso de mostrar Brazilian beach enquanto se fala do
    peixe-leão). Aqui o Groq vê o texto final de cada uma dessas cenas e escolhe de novo. Nas cenas
    de IA cortadas (uma imagem por item de uma enumeração) só o prompt é refeito, para que cada
    fatia gere a imagem do que ela cita e não a mesma imagem repetida. so_ia refaz apenas essas.
    """
    def original(c):
        return " ".join(u["texto"] for u in unidades[c["frases"][0]:c["frases"][1] + 1]).strip()

    tipos = ("ia",) if so_ia else ("foto_real", "video_real", "ia")
    alteradas = [i for i, c in enumerate(cenas)
                 if c["tipo"] in tipos and c["texto"].strip() != original(c)]
    if not alteradas:
        return
    cfg = projeto.config.get("groq") or {}
    por_lote = cfg.get("cenas_por_lote", 20)
    sistema = _sistema_groq(projeto.perfil)
    log(f"  {len(alteradas)} cena(s) cortadas ou fundidas, refazendo a busca delas")
    armadilhas = (projeto.ler_json("roteiro_mapa.json").get("armadilhas") or []
                  if roteirista.ativo(projeto) and projeto.existe("roteiro_mapa.json") else [])

    def linhas(i, com_busca=False):
        c = cenas[i]
        extra = f" | busca atual: {c['busca']}" if com_busca and c.get("busca") else ""
        marca = " | tipo ia" if c["tipo"] == "ia" else ""
        # o que o agente de roteiro pediu, lido com o roteiro inteiro, para a frase cortada não perder o assunto
        guia = f"\n  o que deve aparecer: {c['mostrar']}" if c.get("mostrar") else ""
        return f"CENA {c['n']} | {c['fim'] - c['ini']:.1f}s{marca}{extra}\n  [{c['frases'][0]}] {c['texto']}{guia}"

    def pedir(lote):
        vistos = set(lote)
        antes = [i for i in range(max(0, lote[0] - 2), lote[0]) if i not in vistos]
        depois = [i for i in range(lote[-1] + 1, min(len(cenas), lote[-1] + 2)) if i not in vistos]
        blocos = ["Estas cenas foram cortadas por tempo e o texto de cada uma mudou. Decida de novo o que "
                  "mostrar em cada uma, olhando para o texto dela e, quando houver, para o que deve aparecer, que foi "
                  "escrito lendo o roteiro inteiro e manda no assunto. As cenas marcadas como ia continuam sendo ia: "
                  "para elas devolva só um prompt que mostre a coisa que o texto dela cita, e não o conjunto."]
        if antes:
            blocos.append("Contexto anterior, não devolva:\n" + "\n".join(linhas(i, True) for i in antes))
        blocos.append(f"Cenas para decidir. Devolva exatamente {len(lote)} itens, um por cena, com o n dela.\n"
                      + "\n".join(linhas(i) for i in lote))
        if depois:
            blocos.append("Contexto seguinte, não devolva:\n" + "\n".join(linhas(i, True) for i in depois))
        resposta = _modelo(projeto).perguntar(projeto, "busca das cenas cortadas", sistema, "\n\n".join(blocos),
                                              ESQUEMA_GROQ, log=log)
        return resposta.get("cenas", [])

    for inicio in range(0, len(alteradas), por_lote):
        lote = alteradas[inicio:inicio + por_lote]
        try:
            respondidas = _pedindo_em_partes(pedir, lote, log)
        except RuntimeError as e:
            log(f"  não consegui refazer a busca das cenas {lote[0] + 1} a {lote[-1] + 1} ({e}), mantendo as anteriores")
            continue
        por_n = {cenas[i]["n"]: i for i in lote}
        for item in respondidas:
            i = por_n.get(item.get("n"))
            # as armadilhas do mapa valem aqui também: "Poverty Point" sozinho traz fotos de pobreza
            busca = roteirista.aplicar_armadilhas((item.get("busca") or "").strip(), armadilhas)
            if i is not None and cenas[i]["tipo"] == "ia":
                cenas[i]["prompt"] = (item.get("prompt") or cenas[i]["prompt"]).strip()
            elif i is not None and busca and item.get("tipo") in ("foto_real", "video_real"):
                cenas[i]["busca"] = busca
                cenas[i]["busca_alternativa"] = roteirista.aplicar_armadilhas(
                    (item.get("busca_alternativa") or "").strip(), armadilhas)
                cenas[i]["prompt"] = (item.get("prompt") or cenas[i]["prompt"]).strip()


ESQUEMA_TEXTOS = {
    "type": "object",
    "properties": {
        "cenas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"n": {"type": "integer"}, "texto_tela": TEXTO_TELA},
                "required": ["n", "texto_tela"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cenas"],
    "additionalProperties": False,
}

SISTEMA_TEXTOS = """Você decide os textos animados que aparecem sobre as imagens de um vídeo do canal. Cada cena traz o texto narrado nela. Para cada cena devolva um item com o mesmo n.

{secao_textos}

Regras
1. Use um texto sempre que a cena contiver o que a orientação do canal manda destacar, como um nome citado, um número ou uma enumeração. Use nenhum só quando a cena não tem nada disso.
2. O texto tem que sair de palavras que a narração DESTA cena diz. Nunca escreva o que a cena não fala nem o que só aparece em cenas vizinhas.
3. Em frase use o número da frase informado na cena.
4. Não coloque texto em duas cenas seguidas. Se as duas cenas citam algo, fique com a mais forte.
5. Quando a cena traz um texto sugerido, ele foi escrito por quem leu o roteiro inteiro: use-o só se ele seguir as regras de qualidade abaixo; se não seguir, reescreva ou deixe a cena sem texto.
6. Você vê várias cenas seguidas: guarde o texto para os fatos mais fortes do trecho, no máximo uma cena a cada quatro ou cinco.

""" + textos.REGRAS_QUALIDADE.replace("{", "{{").replace("}", "}}")


def _bate_com_a_fala(texto_tela, palavras):
    """O texto na tela só vale se as palavras dele foram faladas na própria cena.

    Compara as cinco primeiras letras de cada palavra de quatro letras ou mais, para aceitar o
    plural e a pontuação. Itens de lista que não batem são descartados.
    """
    faladas = {_simplificar(p["texto"])[:5] for p in palavras}

    def cita(texto):
        importantes = [w for w in (_simplificar(x) for x in (texto or "").split()) if len(w) >= 4]
        return not importantes or any(w[:5] in faladas for w in importantes)

    tipo = texto_tela["tipo"]
    if tipo == "lista":
        texto_tela["itens"] = [i for i in texto_tela["itens"] if cita(i["texto"])]
        return bool(texto_tela["itens"])
    if tipo == "rotulo":
        return cita(texto_tela["titulo"] or texto_tela["texto"])
    if tipo == "capitulo":
        return True
    return cita(texto_tela["texto"])


def _faladas_em_volta(cenas, i):
    """Palavras faladas na cena, nas vizinhas e no mesmo bloco de assunto: um texto na tela só pode usar palavras da
    narração. O bloco entra porque a cena às vezes diz "ela" e o texto nomeia a coisa (ARCA COBERTA DE BETUME)."""
    bloco = cenas[i].get("bloco")
    perto = cenas[max(0, i - 1):i + 2] + ([c for c in cenas if c.get("bloco") == bloco] if bloco is not None else [])
    return {p for c in perto for p in textos.palavras_normais(c.get("texto") or "")}


def _conferir_textos_do_agente(cenas, alinhamento, log=print):
    """As conferências dos textos na tela, sem chamar modelo: o texto tem que ser falado na cena, ter fundamento
    (nada de "PARTE 2", palavra solta ou palavra inventada) e duas cenas seguidas não têm texto."""
    anterior_com_texto = False
    recusados = []
    for i, c in enumerate(cenas):
        texto_tela = c.get("texto_tela")
        if texto_tela:
            palavras = [p for p in alinhamento.get("palavras") or []
                        if p.get("ini") is not None and c["ini"] - 0.15 <= p["ini"] < c["fim"] - 0.05]
            motivo = textos.motivo_para_recusar(texto_tela, _faladas_em_volta(cenas, i))
            if motivo:
                recusados.append(f"{c['n']} '{texto_tela.get('texto') or texto_tela.get('titulo')}' ({motivo})")
            if motivo or anterior_com_texto or not _bate_com_a_fala(texto_tela, palavras):
                c["texto_tela"] = None
        anterior_com_texto = bool(c.get("texto_tela"))
    if recusados:
        log(f"  {len(recusados)} texto(s) na tela sem fundamento tirados: " + "; ".join(recusados[:8]))


def refazer_textos(projeto, log=print) -> int:
    """Decide de novo só os textos na tela de um projeto pronto, com as regras de qualidade. Imagens não mudam.

    Custa quase nada (Groq gratuito, com o MiMo de reserva). Devolve quantas cenas ficaram com texto."""
    if not textos.ativo(projeto.perfil):
        log("  este perfil não usa textos na tela")
        return 0
    dados = projeto.ler_json("cenas.json")
    cenas = dados["cenas"]
    alinhamento = projeto.ler_json("alinhamento.json")
    for c in cenas:
        c["texto_tela"] = None  # o texto antigo não fica: só volta o que passar pelas regras novas
    _textos_na_tela_groq(projeto, cenas, alinhamento["unidades"], alinhamento, log)
    _conferir_textos_do_agente(cenas, alinhamento, log)
    projeto.salvar_json("cenas.json", dados)
    com_texto = [c for c in cenas if c.get("texto_tela")]
    log(f"  {len(com_texto)} cena(s) com texto na tela, de {len(cenas)}")
    return len(com_texto)


def _linha_texto(c, blocos=None):
    # o texto que o agente de roteiro sugeriu entra como dica; a regra de sair da fala da cena continua valendo.
    # O assunto do bloco deixa o texto nomear a coisa ("DRAGÃO-AZUL · ...") quando a cena diz só "ela" ou "vive"
    sugerido = f"\n  texto sugerido: {c['overlay']}" if c.get("overlay") else ""
    bloco = (blocos or {}).get(c.get("bloco"))
    assunto = f" | assunto: {bloco.get('nome', '')}" if bloco else ""
    return f"CENA {c['n']} | {c['fim'] - c['ini']:.1f}s | frase {c['frases'][0]}{assunto}\n  {c['texto']}{sugerido}"


def _textos_na_tela_groq(projeto, cenas, unidades, alinhamento, log):
    """Decide os textos animados de todas as cenas finais numa passada só para isso.

    O Groq errava a regularidade quando decidia o texto junto com a imagem, ora devolvendo texto
    em várias cenas, ora em nenhuma. Aqui ele vê o texto final de cada cena, com temperatura zero,
    e o código confere se o que ele escreveu foi mesmo falado na cena e evita texto em cenas seguidas.
    """
    if not textos.ativo(projeto.perfil):
        return
    cfg = projeto.config.get("groq") or {}
    sistema = SISTEMA_TEXTOS.format(secao_textos=_secoes(projeto.perfil)["secao_textos"])
    por_lote = cfg.get("cenas_por_lote", 20)
    blocos = {}
    if projeto.existe("roteiro_mapa.json"):
        blocos = {b["id"]: b for b in projeto.ler_json("roteiro_mapa.json").get("blocos", [])}
    # o texto na tela é redação: com o agente ligado, quem escreve é o mesmo modelo dele (MiMo, centavos),
    # que escreve bem melhor que o Groq gratuito; Groq e Gemini ficam de reserva
    modelo = roteirista._modelo_agente(projeto) if roteirista.ativo(projeto) else _modelo(projeto)
    decididos = {}
    for inicio in range(0, len(cenas), por_lote):
        lote = cenas[inicio:inicio + por_lote]
        corpo = "\n\n".join(_linha_texto(c, blocos) for c in lote)
        pedido = f"Devolva exatamente {len(lote)} itens, um por cena, com o n dela.\n\n{corpo}"
        assinatura = hashlib.sha1((sistema + pedido).encode("utf-8")).hexdigest()[:10]
        arquivo = projeto.caminho("cenas_lotes", f"textos_{inicio // por_lote:03d}_{assinatura}.json")
        if arquivo.exists():
            decididos.update({int(n): t for n, t in json.loads(arquivo.read_text(encoding="utf-8")).items()})
            continue
        reforco = [""]  # o aviso da segunda tentativa, acrescentado ao pedido

        def pedir(sublote, _lote=lote):
            corpo_parte = "\n\n".join(_linha_texto(c, blocos) for c in sublote)
            return modelo.perguntar(
                projeto, "textos na tela", sistema,
                f"Devolva exatamente {len(sublote)} itens, um por cena, com o n dela.\n\n{corpo_parte}{reforco[0]}",
                ESQUEMA_TEXTOS, log=log, temperatura=0).get("cenas", [])

        itens = None
        for tentativa in range(2):
            try:
                respondidas = _pedindo_em_partes(pedir, lote, log)
            except RuntimeError as e:
                log(f"  não consegui decidir os textos na tela deste lote ({e}), mantendo os anteriores")
                itens = None
                break
            itens = {i.get("n"): i.get("texto_tela") for i in respondidas}
            algum = any((t or {}).get("tipo", "nenhum") != "nenhum" for t in itens.values())
            if algum or len(lote) < 6:
                break
            reforco[0] = "\n\nAtenção: na resposta anterior todas as cenas ficaram em nenhum. Releia a orientação do canal e use texto onde ela pede."
        if itens:
            decididos.update(itens)
            arquivo.write_text(json.dumps(itens, ensure_ascii=False, indent=2), encoding="utf-8")

    anterior_com_texto = False
    for c in cenas:
        if c["n"] not in decididos:
            anterior_com_texto = bool(c.get("texto_tela"))
            continue
        palavras = [p for p in alinhamento.get("palavras") or []
                    if p.get("ini") is not None and c["ini"] - 0.15 <= p["ini"] < c["fim"] - 0.05]
        frases = unidades[c["frases"][0]:c["frases"][1] + 1]
        novo = _texto_tela(decididos[c["n"]], frases, c["ini"], palavras)
        if novo and (anterior_com_texto or not _bate_com_a_fala(novo, palavras)):
            novo = None
        if novo:
            # o momento em que a palavra é falada pode cair no fim da cena, então o texto entra um pouco antes
            novo["inicio"] = round(min(novo["inicio"], max(0.0, c["fim"] - c["ini"] - 1.2)), 2)
        c["texto_tela"] = novo
        anterior_com_texto = bool(novo)


def _secoes(perfil):
    """Seções do prompt que dependem do perfil, as mesmas para o Claude e para o Groq."""
    from . import bancos
    from .config import config_geral

    midia = perfil.get("midia_real")
    geral = config_geral().get("midia") or {}
    lista = list((midia or {}).get("fontes_foto") or geral.get("fontes_foto") or ["wikimedia", "pexels", "pixabay"])
    lista += [f for f in geral.get("fontes_foto_extras") or [] if f not in lista]
    secao_bancos = ""
    if midia and bancos.descrever(lista):
        secao_bancos = ("Bancos de imagens deste canal. A MESMA busca vale para todos, então escreva-a pelo nome do assunto, "
                        "que todo banco entende, e não por uma cena descrita (prefira 'fire ant' a 'ants attacking prey'):\n"
                        + bancos.descrever(lista))
    if midia and not (config_geral().get("ia") or {}).get("ativa", True):
        # só banco de imagens: o modelo nunca escolhe imagem de IA
        secao_midia = SECAO_SEM_IA
        if midia.get("orientacao"):
            secao_midia += "\n" + midia["orientacao"].strip()
    elif midia:
        # a proporção também é do estilo de vídeo, fixa em qualquer perfil — proporcao no YAML é ignorada
        secao_midia = SECAO_MIDIA
        if midia.get("orientacao"):
            secao_midia += "\n" + midia["orientacao"].strip()
    else:
        secao_midia = SEM_MIDIA

    if textos.ativo(perfil):
        secao_textos = SECAO_TEXTOS
        orientacao = (perfil.get("textos_na_tela") or {}).get("orientacao")
        if orientacao:
            secao_textos += "\n" + orientacao.strip()
    else:
        secao_textos = SEM_TEXTOS

    if efeitos.ativo(perfil):
        secao_efeitos = SECAO_EFEITOS
        orientacao = (perfil.get("efeitos") or {}).get("orientacao")
        if orientacao:
            secao_efeitos += "\n" + orientacao.strip()
    else:
        secao_efeitos = SEM_EFEITOS

    personagem = perfil.get("personagem") or {}
    if personagem.get("descricao"):
        nome = personagem.get("nome", "a personagem")
        secao_personagem = (
            f"Personagem\nMarque personagem como true só nas cenas em que {nome} aparece. Essas cenas são sempre do tipo ia. "
            "Nelas descreva o que a personagem faz e onde está, sem descrever a aparência, que vem de uma foto de referência.\n"
            f"{personagem['descricao'].strip()}\n"
            f"Frequência. {(personagem.get('frequencia') or 'Quando fizer sentido na narração.').strip()}"
        )
    else:
        secao_personagem = "Personagem\nEste canal não tem personagem fixa. Marque personagem como false em todas as cenas."

    return dict(secao_midia=secao_midia, secao_bancos=secao_bancos, secao_textos=secao_textos, secao_efeitos=secao_efeitos,
                secao_personagem=secao_personagem, diretrizes=(perfil.get("diretrizes") or "Nenhuma.").strip())


def _sistema(perfil, roteiro, alvo, minimo, maximo):
    return SISTEMA.format(alvo=alvo, minimo=minimo, maximo=maximo, roteiro=roteiro, **_secoes(perfil))


def _planejar_lote(projeto, sistema, lote, indice, cfg, log):
    # o nome do arquivo carrega um hash do prompt de sistema (perfil + roteiro + diretrizes)
    # pra o cache invalidar sozinho quando o perfil muda, sem depender de quem chama lembrar
    # de limpar cenas_lotes/ (rodar sem --forcar depois de editar o perfil já reaproveitava
    # o plano antigo às cegas, porque o nome do arquivo só olhava pro índice do lote)
    assinatura = hashlib.sha1(sistema.encode("utf-8")).hexdigest()[:10]
    arquivo = projeto.caminho("cenas_lotes", f"lote_{indice:03d}_{assinatura}.json")
    if arquivo.exists():
        salvo = json.loads(arquivo.read_text(encoding="utf-8"))
        return _consertar(salvo, lote[0]["id"], lote[-1]["id"])

    cenas = _planejar_lote_local(projeto, sistema, lote, indice, cfg, log)
    arquivo.write_text(json.dumps(cenas, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"  lote {indice + 1} pronto com {len(cenas)} cenas")
    return cenas


def _planejar_lote_local(projeto, sistema, lote, indice, cfg, log):
    """Planeja um lote pelo Claude Code ou pelo Gemini. Se o pedido for grande demais para o
    modelo, divide o lote ao meio e junta as respostas."""
    linhas = "\n".join(f"{u['id']} | {u['fim'] - u['ini']:.1f}s | {u['texto']}" for u in lote)
    pedido = (
        f"Frases {lote[0]['id']} a {lote[-1]['id']} no formato id | duração | texto. "
        "Devolva as cenas cobrindo todas elas, em ordem.\n\n" + linhas
    )
    try:
        resposta = claude_local.perguntar(projeto, f"cenas, lote {indice + 1}", sistema, pedido, ESQUEMA,
                                          esforco=cfg.get("esforco", "high"))
    except RuntimeError as e:
        if ("rate_limit" in str(e) or "too large" in str(e) or "quota" in str(e) or "429" in str(e)) and len(lote) > 4:
            meio = len(lote) // 2
            log(f"  lote {indice + 1} grande demais, dividindo em dois")
            return (_planejar_lote_local(projeto, sistema, lote[:meio], indice, cfg, log)
                    + _planejar_lote_local(projeto, sistema, lote[meio:], indice, cfg, log))
        raise
    cenas_lista = resposta.get("cenas") if isinstance(resposta, dict) else resposta
    return _consertar(cenas_lista, lote[0]["id"], lote[-1]["id"])


def _consertar(cenas, primeira, ultima):
    """Garante que as cenas cobrem todas as frases do lote, sem buraco e sem sobreposição."""
    resultado, esperada = [], primeira
    for c in sorted(cenas, key=lambda c: c.get("primeira_frase", 0)):
        a = max(c.get("primeira_frase", esperada), esperada)
        b = min(c.get("ultima_frase", ultima), ultima)
        if b < a:
            continue
        if a > esperada:
            if resultado:
                resultado[-1]["ultima_frase"] = a - 1
            else:
                a = esperada
        resultado.append({
            **c,
            "primeira_frase": a,
            "ultima_frase": b,
            "tipo": c.get("tipo", "ia"),
            "busca": (c.get("busca") or "").strip(),
            "personagem": bool(c.get("personagem", False)),
            "prompt": (c.get("prompt") or "").strip(),
        })
        esperada = b + 1
    if not resultado:
        raise SystemExit(f"O Claude não devolveu cenas para as frases {primeira} a {ultima}.")
    resultado[-1]["ultima_frase"] = ultima
    return resultado


def _juntar_curtas(grupos, unidades, duracao, minimo):
    """Cena rápida demais pisca na tela. Ela passa a fazer parte da cena anterior."""
    def inicio(g):
        return unidades[g["primeira_frase"]]["ini"]

    resultado = []
    for i, g in enumerate(grupos):
        fim = inicio(grupos[i + 1]) if i + 1 < len(grupos) else duracao
        minimo_aqui = ESTILO_MINIMO_ENUMERACAO if g.get("paralela") else minimo  # frases paralelas curtas não se fundem
        if resultado and fim - inicio(g) < minimo_aqui:
            resultado[-1]["ultima_frase"] = g["ultima_frase"]
        else:
            resultado.append(dict(g))
    # a primeira cena começa no zero, então se ela for curta a seguinte absorve
    if len(resultado) > 1 and inicio(resultado[1]) < minimo:
        resultado[1]["primeira_frase"] = resultado[0]["primeira_frase"]
        resultado.pop(0)
    return resultado


def _dividir_longas(grupos, unidades, duracao, maximo):
    """Quebra cenas que passem do limite de maximo segundos na fronteira das frases, sem exceções."""
    resultado = []
    for i, g in enumerate(grupos):
        fim_grupo = unidades[grupos[i + 1]["primeira_frase"]]["ini"] if i + 1 < len(grupos) else duracao
        if fim_grupo - unidades[g["primeira_frase"]]["ini"] <= maximo:
            resultado.append(g)
            continue
        pedacos, inicio = [], g["primeira_frase"]
        for frase in range(g["primeira_frase"], g["ultima_frase"] + 1):
            fim_frase = unidades[frase + 1]["ini"] if frase < g["ultima_frase"] else fim_grupo
            if frase > inicio and fim_frase - unidades[inicio]["ini"] > maximo:
                pedacos.append((inicio, frase - 1))
                inicio = frase
        pedacos.append((inicio, g["ultima_frase"]))
        # os pedaços de uma cena quebrada têm o mesmo prompt: se ela virar ia, uma imagem paga
        # de IA gerada de novo pra cada pedaço seria quase a mesma imagem se repetindo na tela,
        # e cara à toa. _grupo_dividido marca a família pra planejar() apontar todo mundo pra
        # uma imagem só, gerada uma vez.
        for n, (a, b) in enumerate(pedacos):
            resultado.append({**g, "primeira_frase": a, "ultima_frase": b,
                               "texto_tela": g.get("texto_tela") if n == 0 else None,
                               "efeito": g.get("efeito") if n == 0 else None,
                               "_grupo_dividido": i})
    return resultado


def _agrupar_por_tempo(unidades, alvo, perfil):
    """Modo offline. Agrupa por tempo e, se o perfil pedir, alterna cenas reais e textos de exemplo."""
    buscas = (perfil.get("midia_real") or {}).get("buscas_de_teste") or []
    com_textos = textos.ativo(perfil)
    sons = ["distant rolling thunder", "deep ceremonial horn blast", "crackling bonfire"]
    grupos, inicio = [], 0
    for i, u in enumerate(unidades):
        if u["fim"] - unidades[inicio]["ini"] >= alvo or i == len(unidades) - 1:
            frases = unidades[inicio:i + 1]
            real = bool(buscas) and len(grupos) % 2 == 1
            grupos.append({
                "primeira_frase": inicio,
                "ultima_frase": i,
                "tipo": "foto_real" if real else "ia",
                "busca": buscas[(len(grupos) // 2) % len(buscas)] if real else "",
                "personagem": not real and len(grupos) % 5 == 0,
                "prompt": " ".join(x["texto"] for x in frases),
                "texto_tela": _texto_de_teste(len(grupos), frases) if com_textos else None,
                "efeito": ({"descricao": sons[(len(grupos) // 3) % len(sons)], "duracao": 3,
                            "palavra": frases[0]["texto"].split()[0]} if len(grupos) % 3 == 2 else None),
            })
            inicio = i + 1
    return grupos


def _texto_de_teste(indice, frases):
    primeira, ultima = frases[0]["id"], frases[-1]["id"]
    palavras = " ".join(f["texto"] for f in frases).upper().replace(",", "").replace(".", "").split()
    exemplos = [
        {"tipo": "rotulo", "titulo": " ".join(palavras[:3]), "frase": primeira},
        {"tipo": "capitulo", "texto": "PARTE 1", "titulo": " ".join(palavras[:2]), "frase": ultima},
        {"tipo": "destaque", "texto": " ".join(palavras[:7]), "destaque": " ".join(palavras[5:7]), "frase": primeira},
        {"tipo": "lista", "titulo": "TEXTO DE TESTE", "frase": primeira,
         "itens": [{"texto": " ".join(f["texto"].split()[:4]).upper(), "frase": f["id"]} for f in frases[:4]]},
    ]
    return exemplos[indice] if indice < len(exemplos) else None
