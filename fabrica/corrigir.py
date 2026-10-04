"""Conferência e correção da mídia das cenas, comparando o que aparece com o que a narração diz.

Para cada cena o Gemini olha a imagem (ou dois quadros do vídeo) junto com a narração e devolve
uma legenda curta do que enxerga, um veredito e uma nota. A narração é a referência. O termo de
busca e o prompt só ajudam a entender a intenção, porque eles mesmos podem estar errados.

O que reprova e é material real ganha outra busca, de graça, sem repetir o que já foi rejeitado,
por algumas rodadas. O que continua reprovado, e o que é imagem de IA, só vira imagem nova de IA
quando quem chama pede, porque isso custa dinheiro.
"""
import copy
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PIL import Image

from . import animacoes, gemini_local, groq_local, imagens, midia, openrouter_local
from .util import duracao_audio, rodar

RODADAS = 3
NOTA_MINIMA = 40      # abaixo disso a cena entra no relatório como "não combina"
NOTA_PARA_TROCAR = 20  # só abaixo disso o sistema troca sozinho. Entre os dois, ele só aponta e você decide
# a imagem mostra OUTRA coisa no lugar do sujeito (pergunta "sujeito" do Jev): a cena está errada, qualquer que seja a
# nota de combinar. Com o sujeito certo e a nota baixa, a cena é só genérica e fica (três leões sem juba tiravam 4%
# contra o pedido ideal "dois leões entre tendas à noite" e seriam trocados à toa)
NOTA_SUJEITO_ERRADO = 35
NOTA_EPOCA_ERRADA = 30  # cena de época com foto de hoje
LADO_MAXIMO = 640  # imagem reduzida: uns 300 tokens em vez de 800. O plano gratuito do Groq limita tokens por minuto

VEREDITOS = ("combina", "em_parte", "nao_combina")

ESQUEMA_CONFERENCIA = {
    "type": "object",
    "properties": {
        "legenda": {"type": "string"},
        "veredito": {"type": "string", "enum": list(VEREDITOS)},
        "nota": {"type": "integer"},
        "motivo": {"type": "string"},
        "busca_nova": {"type": "string"},
        "prompt_novo": {"type": "string"},
    },
    "required": ["legenda", "veredito", "nota", "motivo", "busca_nova", "prompt_novo"],
    "additionalProperties": False,
}

ESQUEMA_CONFERENCIA_LOTE = {
    "type": "object",
    "properties": {
        "cenas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"n": {"type": "integer"}, **ESQUEMA_CONFERENCIA["properties"]},
                "required": ["n"] + ESQUEMA_CONFERENCIA["required"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cenas"],
    "additionalProperties": False,
}

# no lote as imagens chegam todas juntas, então a ordem delas é descrita no texto
INSTRUCOES_LOTE = """Você confere, em lote, se as imagens das cenas de um vídeo documentário combinam com o que a narração diz em cada trecho.

As imagens anexadas vêm na ordem indicada no pedido: a primeira cena recebe as primeiras imagens, a seguinte as próximas, e assim por diante. Quando uma cena tem duas imagens, são dois quadros do mesmo vídeo. Conte as imagens na ordem para não trocar uma cena pela outra.

Devolva um item por cena pedida, com o mesmo n, na mesma ordem. Nunca pule uma cena.

"""

INSTRUCOES = """Você confere se a imagem de uma cena de um vídeo documentário combina com o que a narração diz naquele trecho. Se houver duas imagens, são quadros do mesmo vídeo.

Regras
1. legenda: em português, em poucas palavras, o que você VÊ na imagem, por exemplo "peixe-leão nadando" ou "praia com pessoas". Descreva só o que aparece, sem interpretar.
2. A referência é a NARRAÇÃO da cena. O termo de busca e o prompt atuais só mostram a intenção e podem estar errados. Compare o que você vê com o que a narração cita neste trecho.
3. veredito
   - combina: mostra o que a narração cita, ou ilustra de forma fiel uma ideia abstrata. Uma imagem genérica do assunto certo conta como combina quando a narração é abstrata.
   - em_parte: é do mesmo assunto, mas outro detalhe, ou genérica demais para algo que a narração cita pelo nome.
   - nao_combina: outro animal, objeto ou lugar, ou contradiz a narração.
4. Contexto. A narração desta cena pode ser só um pedaço de uma frase que continua na cena vizinha. Os trechos anterior e seguinte servem para entender a frase inteira. Se o que falta para o sentido está na vizinha, considere a frase inteira ao julgar, mas a imagem ilustra principalmente o trecho desta cena.
   Frases gerais. Quando a narração é uma abertura, um encerramento ou apresenta o tema de forma geral, sem citar um animal, objeto ou lugar específico pelo nome, o que vale é o lugar e o contexto que ela cita. Uma paisagem do lugar citado combina. Um animal ou objeto de outro habitat ou contexto não combina, mesmo que a palavra "animais" apareça na frase. Só exija que apareça o sujeito quando a narração o citar pelo nome.
5. nota de 0 a 100. combina fica entre 90 e 100, em_parte entre 50 e 79, nao_combina entre 0 e 30.
6. Se o veredito não for combina, escreva busca_nova, de 2 a 4 palavras em inglês, com substantivos concretos, como alguém digitaria num banco de imagens para achar o que a narração cita neste trecho, e diferente da busca atual. Escreva também prompt_novo, a descrição em inglês de uma fotografia com sujeito, ação, enquadramento e ambiente, sem pedir texto escrito na imagem. Se combina, deixe busca_nova e prompt_novo vazios."""


def aprovada(conferencia, nota_minima=NOTA_MINIMA) -> bool:
    return (conferencia["veredito"] == "combina" or conferencia["nota"] >= nota_minima) and not errada(conferencia)


def _reduzir(origem, destino):
    with Image.open(origem) as imagem:
        imagem = imagem.convert("RGB")
        imagem.thumbnail((LADO_MAXIMO, LADO_MAXIMO))
        imagem.save(destino, quality=85)


def _quadros(projeto, cena):
    """Arquivos de imagem que mostram o que a cena exibe hoje. Vídeo vira dois quadros, aos 25% e 75%."""
    pasta = projeto.caminho("conferir")
    pasta.mkdir(parents=True, exist_ok=True)
    n = cena["n"]
    m = cena.get("midia")
    if m:
        origem = projeto.pasta / m["arquivo"]
    else:
        origem = projeto.imagem(n)  # a imagem de IA da cena (conferir_ia)
    if not origem.exists():
        return []
    if origem.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv"):
        # um quadro só, do meio do clipe: com dois, o modelo de visão tratava cada imagem como uma
        # cena diferente e as legendas saíam trocadas a partir do primeiro vídeo do lote
        destino = pasta / f"{n:04d}_0.jpg"
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{duracao_audio(origem) / 2:.2f}", "-i", origem,
               "-frames:v", "1", "-vf", f"scale={LADO_MAXIMO}:-2", destino])
        return [destino]
    destino = pasta / f"{n:04d}_0.jpg"
    _reduzir(origem, destino)
    return [destino]


def falas_do_material(projeto) -> dict:
    """Para cada foto ou vídeo de acervo em uso, a fala da cena que mostra ele. Tirada antes de trocar a narração."""
    if not projeto.existe("cenas.json"):
        return {}
    falas = {}
    for c in projeto.ler_json("cenas.json").get("cenas", []):
        arquivo = (c.get("midia") or {}).get("arquivo")
        if arquivo:
            falas[str(arquivo).replace("\\", "/")] = " ".join((c.get("texto") or "").split()).lower()
    return falas


def depois_da_narracao(projeto, antes: dict) -> dict:
    """O que a troca de narração deixou para refazer: cenas sem imagem (a mesma regra do render), cenas que
    continuam com a foto antiga mas com outra fala (o Jev julga de novo) e cenas com imagem repetida."""
    vazias, mudaram = set(), set()
    for c in projeto.ler_json("cenas.json").get("cenas", []):
        m = c.get("midia") or {}
        if m.get("arquivo"):
            if not (projeto.pasta / m["arquivo"]).exists():
                vazias.add(c["n"])
                continue
            fala = " ".join((c.get("texto") or "").split()).lower()
            if antes.get(str(m["arquivo"]).replace("\\", "/")) != fala:
                mudaram.add(c["n"])
        elif not projeto.imagem(c["n"]).exists():
            vazias.add(c["n"])
    repetidas = set(midia.cenas_repetidas(projeto))
    return {"vazias": vazias, "mudaram": mudaram, "repetidas": repetidas, "alvo": vazias | mudaram | repetidas}


def conferiveis(projeto, numeros=None) -> list[dict]:
    """Cenas que o conferidor olha: só material real de acervo já baixado, com narração.

    Cenas de IA, e cenas reais que ainda não têm arquivo, ficam de fora e nunca chegam ao modelo."""
    return [c for c in projeto.ler_json("cenas.json")["cenas"]
            if (numeros is None or c["n"] in numeros)
            and c.get("tipo") in midia.TIPOS_REAIS and c.get("midia")
            and (c.get("texto") or "").strip()]


def provedor(projeto) -> str:
    return (projeto.config.get("corrigir") or {}).get("provedor", "groq")


def modelo_de_visao(projeto):
    """Quem descreve as imagens para o Jev julgar: o modelo principal (enxerga imagens, texto e vídeo)."""
    return openrouter_local, openrouter_local.principal(projeto)


def _bloco_da_cena(cena, quadros, vizinhas):
    """Descrição em texto de uma cena, dizendo quantas imagens dela vêm anexadas."""
    antes, depois = (vizinhas or {}).get(cena["n"] - 1), (vizinhas or {}).get(cena["n"] + 1)
    contexto = ""
    if antes:
        contexto += f"Trecho anterior, só de contexto: \"{antes}\"\n"
    if depois:
        contexto += f"Trecho seguinte, só de contexto: \"{depois}\"\n"
    quantas = "1 imagem" if len(quadros) == 1 else f"{len(quadros)} imagens (quadros do mesmo vídeo)"
    return (
        f"Cena {cena['n']}, {cena['fim'] - cena['ini']:.1f} segundos, {quantas}\n"
        f"{contexto}"
        f"Narração desta cena: \"{cena['texto']}\"\n"
        f"Tipo: {cena['tipo']}\n"
        f"Termo de busca atual: {cena.get('busca') or '(nenhum)'}\n"
        f"Prompt atual: {cena.get('prompt') or '(nenhum)'}"
    )


ESQUEMA_LEGENDA = {
    "type": "object",
    "properties": {
        "cenas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"n": {"type": "integer"}, **midia.CAMPOS_SEM_PEDIDO},
                "required": ["n", *midia.CAMPOS_SEM_PEDIDO],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cenas"],
    "additionalProperties": False,
}

INSTRUCOES_LEGENDA = """Você olha as imagens das cenas de um vídeo e diz o que vê em cada uma, para um juiz que só lê texto.

As imagens anexadas vêm na ordem indicada no pedido: uma imagem por cena, na mesma ordem em que as cenas aparecem. Conte as imagens na ordem para não trocar uma cena pela outra.

Para cada cena devolva um item com o mesmo n. Você NÃO sabe o que a cena deveria mostrar, de propósito: descreva só o
que está na imagem. Quem compara com a narração é o juiz.

""" + midia.INSTRUCOES_SEM_PEDIDO + """

Devolva um item por cena pedida, na mesma ordem. Nunca pule uma cena."""

PERGUNTAS_JEV = {
    "combina": {
        "type": "noul",
        "instructions": ("Você é um diretor de arte rigoroso. A imagem descrita mostra, com precisão literal, o que a "
                         "narração desta cena fala naquele segundo? Confira o SUJEITO (o objeto, pessoa, veículo, "
                         "software, animal ou evento citado tem que ser exatamente aquele), o CENÁRIO (o ambiente "
                         "combina com a realidade do sujeito e o tom do texto), a AÇÃO ou CARACTERÍSTICA citada, e se "
                         "placas, textos e telas pertencem ao contexto. Metáfora visual e imagem genérica que foge do "
                         "sentido literal reprovam. Quando a narração não cita nada visual concreto (uma ideia, uma "
                         "pergunta), vale uma imagem direta do assunto do trecho, nunca uma metáfora. Quando o estado "
                         "traz item_da_lista_nesta_cena, a frase cita vários itens e esta cena é só um deles: a imagem "
                         "tem que mostrar ESSE item (o_que_a_cena_deve_mostrar), não os outros itens da frase. o_que_a_imagem_mostra "
                         "vem de quem VIU a imagem: o que é (com o grau de certeza), detalhes, cenário, ação, tipo de "
                         "imagem, texto visível e se ela confere com o pedido. Um 'confere: nao' de quem viu pesa muito "
                         "contra; um nome de espécie com certeza baixa não é prova; ilustração ou render no lugar de "
                         "foto real, ou logotipo e marca d'água, pesam contra. Nome de pessoa, lugar ou espécie dito "
                         "por quem viu só é prova quando também aparece no texto visível ou em "
                         "como_o_autor_descreveu_o_arquivo: quem descreve às vezes copia o nome do pedido. Quando o "
                         "estado traz pessoa_citada, a imagem tem que ser DESSA pessoa: se como_o_autor_descreveu_o_arquivo "
                         "aponta outra pessoa com o mesmo nome (outra época, outro país, outra profissão), reprova. "
                         "Quando o estado traz epoca_da_cena, a imagem tem que ser daquela época (fotografia antiga, "
                         "gravura, ilustração de livro ou jornal da época, mapa antigo, objeto de museu): foto atual, "
                         "com roupas, veículos, obras ou aparelhos de hoje, reprova."),
        "criteria": {
            "true": ("mostra o sujeito citado ou a representação visual direta do conceito, num cenário coerente: um "
                     "carro elétrico carregando para 'carro elétrico moderno', arquitetura romana para 'Roma Antiga', um "
                     "pangolim para o pangolim, servidores, código ou tela de criptografia para 'segurança de dados', um "
                     "gráfico para 'a pesquisa mostrou um aumento', o botão vermelho sendo apertado, o ferrão, as "
                     "brânquias. Coisa que só existe como tipo genérico (o gráfico de um estudo, um documento, uma "
                     "pessoa anônima) pode ser uma representação direta desse mesmo tipo. Não precisa mostrar cada "
                     "palavra da frase: basta o sujeito ou o conceito certo, sem trocar por outra coisa"),
            "false": ("mostra outra coisa no lugar do sujeito, mesmo parecida (carro a combustão para carro elétrico, "
                      "arquitetura medieval para Roma Antiga, um gato ou um tatu para o pangolim, um pato para o "
                      "ornitorrinco, outro lêmure para o aiê-aiê); cenário que contradiz o texto (café descontraído para "
                      "finanças corporativas, praia para esporte de inverno); B-roll desconexo ou metáfora (líquido "
                      "fervendo, gente correndo ou engrenagem para 'segurança de dados'); ação diferente da narrada "
                      "(alguém olhando uma tela quando a narração diz que ele apertou o botão); placa, texto ou tela de "
                      "outro contexto; logotipo em destaque; um animal sem dizer qual quando a narração nomeia a "
                      "espécie; ou, numa cena que é um item de lista, a imagem mostra outro item da frase (lobo na "
                      "cena dos alces) ou nenhum dos itens"),
        },
    },
}

PERGUNTA_SUJEITO = {
    "type": "noul",
    "instructions": ("A imagem descrita mostra o SUJEITO certo da cena (a coisa, pessoa, animal, lugar ou objeto que a "
                     "narração cita, ou o assunto direto do trecho quando ela não cita nada concreto), mesmo que o "
                     "momento, a ação ou o cenário sejam outros? Não é sobre a imagem ser perfeita: é sobre ela mostrar "
                     "AQUILO e não outra coisa. Quando o estado traz o_que_basta, esse é o mínimo para estar certa."),
    "criteria": {
        "true": ("mostra o sujeito certo, ainda que genérico: um leão sem juba para os leões de Tsavo, uma foto antiga "
                 "da ferrovia para a construção da ferrovia, um laboratório para a pesquisa, a pessoa citada (e não "
                 "um homônimo)"),
        "false": ("mostra outra coisa: outro animal (um elefante ou uma zebra no lugar do leão), outro lugar, outra "
                  "pessoa com o mesmo nome, uma cidade, um carro, um objeto sem relação, ou nada do assunto do trecho"),
    },
}

PERGUNTA_EPOCA = {
    "type": "noul",
    "instructions": ("A cena se passa na época em epoca_da_cena. A imagem descrita é dessa época (fotografia antiga, "
                     "gravura, ilustração de livro ou jornal da época, objeto de museu, ou cena sem nada que denuncie "
                     "o tempo, como um bicho ou uma paisagem)?"),
    "criteria": {
        "true": "foto antiga, gravura, ilustração da época, objeto de museu, ou natureza sem sinal de época",
        "false": "mostra roupas, carros, aparelhos, obras ou acabamentos de hoje, ou é foto digital moderna de gente",
    },
}


def _perguntas(estado) -> dict:
    """As perguntas da cena, numa chamada só e pelo mesmo preço: combina, sujeito e, em cena de época, época."""
    perguntas = {**PERGUNTAS_JEV, "sujeito": PERGUNTA_SUJEITO}
    if estado.get("epoca_da_cena"):
        perguntas["epoca"] = PERGUNTA_EPOCA
    return perguntas


def errada(avaliacao, nota_para_trocar=NOTA_PARA_TROCAR) -> bool:
    """A cena mostra outra coisa (sujeito errado), é de outra época, ou não combina de jeito nenhum. Só essa troca
    sozinha, e com a IA ligada vai para a IA. Sujeito certo com nota baixa é cena genérica e fica."""
    if avaliacao is None:
        return False
    sujeito, epoca = avaliacao.get("sujeito"), avaliacao.get("epoca")
    if sujeito is not None and sujeito < NOTA_SUJEITO_ERRADO:
        return True
    if epoca is not None and epoca < NOTA_EPOCA_ERRADA:
        return True
    return avaliacao["nota"] < nota_para_trocar and (sujeito is None or sujeito < 60)


ESQUEMA_BUSCAS = {
    "type": "object",
    "properties": {
        "cenas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"n": {"type": "integer"}, "busca_nova": {"type": "string"}, "prompt_novo": {"type": "string"}},
                "required": ["n", "busca_nova", "prompt_novo"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cenas"],
    "additionalProperties": False,
}

INSTRUCOES_BUSCAS = """Estas cenas de um vídeo estão com material que não combina com a narração. Para cada uma, escreva onde procurar um material melhor.

Em busca_nova, de 2 a 4 palavras em inglês, com substantivos concretos, como alguém digitaria num banco de imagens para achar o que a narração cita neste trecho. Precisa ser diferente da busca atual, que já falhou, e do que a imagem atual mostra.
Em prompt_novo, a descrição em inglês de uma fotografia: sujeito, ação, enquadramento e ambiente. Nunca peça texto escrito dentro da imagem.
Comparações e metáforas não são o assunto: mostre a coisa de que o trecho fala de verdade, nunca o objeto da figura de linguagem. Números e posições da contagem também não viram imagem.
Devolva um item por cena pedida, com o mesmo n."""


_reserva_ligada = set()  # projetos que já caíram para o modelo de reserva nesta execução


def _com_reserva(projeto, etapa, instrucoes, pedido, esquema, log=print, **extras):
    """Chama o modelo que descreve as imagens (o modelo principal). O nome ficou de quando havia reserva."""
    modulo, modelo = modelo_de_visao(projeto)
    return modulo.perguntar(projeto, etapa, instrucoes, pedido, esquema, log=log, modelo=modelo, **extras)


def _legenda_guardada(cena):
    """A descrição fica junto da mídia: a mesma foto nunca é descrita duas vezes. Só vale a do formato novo
    (com "O que é:" e a conferência com o pedido); a frase curta antiga é descrita de novo."""
    legenda = ((cena.get("midia") or {}).get("legenda") or "").strip()
    # a descrição feita vendo o pedido (a da escolha, com "confere com o pedido") é refeita sem ele
    return legenda if legenda.startswith("O que é:") and "confere com o pedido" not in legenda else ""


def _guardar_legendas(projeto, legendas):
    dados = projeto.ler_json("cenas.json")
    for c in dados["cenas"]:
        if c["n"] in legendas and c.get("midia"):
            c["midia"]["legenda"] = legendas[c["n"]]
    projeto.salvar_json("cenas.json", dados)


def _descrever_lote(projeto, lote, log):
    """O modelo de visão só diz o que aparece em cada imagem. Devolve {n: legenda}.

    lote é uma lista de (cena, quadros) já preparada, porque o tamanho da chamada é limitado pelo
    número de imagens, e não pelo de cenas."""
    if not lote:
        return {}
    quantas = len(lote)
    blocos, imagens = [], []
    for cena, quadros in lote:
        # sem o pedido: vendo o que a cena deveria mostrar, o modelo escrevia "Lago Vitória" para uma cidade no litoral
        # (nota 81) e "armadilha de madeira para leões" para uma gaiola de caranguejo. Quem compara é o Jev
        blocos.append(f"Cena {cena['n']}")
        imagens.extend(quadros)
    pedido = f"Diga o que você vê nas imagens destas {quantas} cenas, campo a campo.\n\n" + "\n".join(blocos)
    try:
        resposta = _com_reserva(projeto, "descrever imagens", INSTRUCOES_LEGENDA, pedido, ESQUEMA_LEGENDA,
                                log=log, imagens=imagens, temperatura=0)
    except RuntimeError as e:
        log(f"  não consegui descrever as imagens das cenas {lote[0][0]['n']} a {lote[-1][0]['n']} ({e})")
        return {}
    return {i["n"]: midia.compor_o_que_se_ve(i) for i in resposta.get("cenas", []) if midia.compor_o_que_se_ve(i)}


def _texto_da_fonte(cena):
    """O que o autor escreveu sobre o arquivo, tirado do endereço da página. Vem de graça na busca."""
    pagina = (cena.get("midia") or {}).get("pagina") or ""
    if not pagina:
        return ""
    bruto = re.sub(r"[-/_]+", " ", pagina.rstrip("/").rsplit("/", 1)[-1])
    bruto = re.sub(r"\s*\d{5,}\s*$", "", bruto)               # o número do arquivo no fim não diz nada
    bruto = re.sub(r"^file\s*:?\s*", "", bruto, flags=re.I).strip()
    if "%" in bruto or len(bruto) < 8:                         # nome codificado ou curto demais não ajuda
        return ""
    return bruto


def _julgar_com_jev(projeto, cena, legenda, vizinhas, log):
    """O Jev compara a descrição com a narração e devolve o veredito, a nota e o motivo."""
    from . import jev_local

    estado = {
        "narracao_desta_cena": cena["texto"],
        "trecho_anterior": (vizinhas or {}).get(cena["n"] - 1, ""),
        "trecho_seguinte": (vizinhas or {}).get(cena["n"] + 1, ""),
        "o_que_a_imagem_mostra": legenda,
    }
    # o assunto do bloco: "Mas ainda faltava um." sozinho não diz que é o segundo leão de Tsavo
    bloco = _bloco_da_cena_no_mapa(projeto, cena)
    if bloco:
        estado["assunto_do_trecho"] = bloco
    if (cena.get("aceitavel") or "").strip():
        # o mínimo para a cena estar certa: o ideal (o_que_a_cena_deve_mostrar) quase nunca existe em banco
        estado["o_que_basta"] = cena["aceitavel"].strip()
    if cena.get("exato"):
        estado["tem_que_ser"] = cena["exato"]
    if cena.get("tipo") == "ia" and not cena.get("midia"):
        estado["imagem_gerada_por_ia"] = "sim: não pese contra por ser imagem gerada; julgue se mostra o certo"
    # escrito pelo agente que leu o roteiro inteiro: "Coincidieron." sozinho não diz que é sobre Watson Brake
    if cena.get("visual") in animacoes.tipos(projeto) and animacoes.config(projeto).get("ativo", True):
        # a foto vai por baixo da animação: o que vale é ser do assunto, não ser "um diagrama mostra..."
        estado["o_que_a_cena_deve_mostrar"] = ("imagem de fundo, escurecida atrás de uma animação com o texto: uma "
                                               f"imagem direta do assunto ({cena.get('busca') or cena.get('sujeito')})")
    elif cena.get("mostrar"):
        estado["o_que_a_cena_deve_mostrar"] = cena["mostrar"]
    if midia.e_de_epoca(cena):
        estado["epoca_da_cena"] = str(cena["epoca"])
    pessoa = _pessoa_da_cena(projeto, cena)
    if pessoa:
        estado["pessoa_citada"] = pessoa
    if cena.get("item_citado"):
        # a cena é um pedaço de uma lista ("lobos, alces, cavalos-de-przewalski"): a imagem mostra ESTE item
        estado["item_da_lista_nesta_cena"] = cena["item_citado"]
    # o título que o autor deu ao arquivo é um segundo olhar, de graça, e corrige o modelo de visão
    # quando ele erra o nome de uma espécie ou objeto
    fonte = _texto_da_fonte(cena)
    if fonte:
        estado["como_o_autor_descreveu_o_arquivo"] = fonte
    try:
        respostas = jev_local.decidir(projeto, "julgar mídia", estado, _perguntas(estado), log=log)
    except RuntimeError as e:
        log(f"  o Jev não julgou a cena {cena['n']} ({e})")
        return None
    nota = round(float(respostas["combina"]["noul"]) * 100)

    def outra(chave):
        try:
            return round(float(respostas[chave]["noul"]) * 100)
        except (KeyError, TypeError, ValueError):
            return None
    sujeito, epoca = outra("sujeito"), outra("epoca") if "epoca_da_cena" in estado else None
    veredito = "combina" if nota >= 80 else "em_parte" if nota >= 50 else "nao_combina"
    motivo = f"o Jev deu {nota}% de chance de combinar com a narração"
    if sujeito is not None:
        motivo += f", {sujeito}% de mostrar o sujeito certo"
    if epoca is not None:
        motivo += f" e {epoca}% de ser da época"
    return {"legenda": legenda, "veredito": veredito, "nota": nota, "sujeito": sujeito, "epoca": epoca,
            "motivo": motivo, "busca_nova": "", "prompt_novo": ""}


_MAPAS = {}


def _mapa(projeto) -> dict:
    """O mapa do agente (roteiro_mapa.json), lido uma vez enquanto não muda."""
    arquivo = projeto.pasta / "roteiro_mapa.json"
    try:
        chave = (str(arquivo), arquivo.stat().st_mtime)
    except OSError:
        return {}
    if chave not in _MAPAS:
        try:
            _MAPAS[chave] = projeto.ler_json("roteiro_mapa.json")
        except (OSError, ValueError):
            _MAPAS[chave] = {}
    return _MAPAS[chave]


def _bloco_da_cena_no_mapa(projeto, cena) -> str:
    bloco = next((b for b in _mapa(projeto).get("blocos") or [] if b.get("id") == cena.get("bloco")), None)
    if not bloco:
        return ""
    return f"{bloco.get('nome', '')}: {bloco.get('ancora', '')}".strip(": ")


_QUEM_E = {}


def _pessoa_da_cena(projeto, cena) -> str:
    """Quem é a pessoa real que a cena cita (campo quem_e do mapa): nome, anos de vida e o que fez. Com isso o Jev
    separa o caçador John Henry Patterson (1867-1947) do homônimo de Dayton, Ohio, e do soldado de 1865, que
    entraram no virou-filme-em-1996 porque o nome batia."""
    arquivo = projeto.pasta / "roteiro_mapa.json"
    try:
        chave = (str(arquivo), arquivo.stat().st_mtime)
    except OSError:
        return ""
    if chave not in _QUEM_E:
        try:
            _QUEM_E[chave] = [p for p in projeto.ler_json("roteiro_mapa.json").get("quem_e") or []
                              if isinstance(p, dict) and (p.get("nome") or "").strip()]
        except (OSError, ValueError):
            _QUEM_E[chave] = []
    texto = " ".join(str(cena.get(c) or "") for c in ("texto", "exato", "sujeito", "mostrar", "busca"))
    for pessoa in _QUEM_E[chave]:
        sobrenome = pessoa["nome"].split()[-1]
        if re.search(rf"\b{re.escape(sobrenome)}\b", texto, re.I):
            return f"{pessoa['nome'].strip()}: {(pessoa.get('quem') or '').strip()}"
    return ""


def _buscas_das_reprovadas(projeto, cenas_reprovadas, resultados, log):
    """O Jev não escreve texto, então um modelo de texto sugere a busca nova só das cenas reprovadas."""
    if not cenas_reprovadas:
        return
    por_lote = max(1, (projeto.config.get("corrigir") or {}).get("cenas_por_chamada", 5))
    # quem descreve também escreve a busca nova: é o mesmo modelo, e ele já lida com texto
    modulo, modelo_texto = modelo_de_visao(projeto)
    for inicio in range(0, len(cenas_reprovadas), por_lote):
        lote = cenas_reprovadas[inicio:inicio + por_lote]
        corpo = "\n\n".join(
            f"Cena {c['n']}\nNarração: \"{c['texto']}\"\n"
            + (f"O que a cena deve mostrar: {c['mostrar']}\n" if c.get("mostrar") else "")
            + f"Busca atual, que falhou: {c.get('busca') or '(nenhuma)'}\n"
            f"O que a imagem atual mostra: {resultados[c['n']]['legenda']}" for c in lote)
        try:
            # com a reserva: se a cota do Groq acabou, o Gemini responde, e o Corrigir não para
            resposta = _com_reserva(projeto, "buscas das reprovadas", INSTRUCOES_BUSCAS,
                                    f"Devolva {len(lote)} itens.\n\n{corpo}", ESQUEMA_BUSCAS, log=log, temperatura=0)
        except RuntimeError as e:
            log(f"  não consegui sugerir busca nova para as cenas {lote[0]['n']} a {lote[-1]['n']} ({e})")
            continue
        for item in resposta.get("cenas", []):
            if item.get("n") in resultados:
                resultados[item["n"]]["busca_nova"] = (item.get("busca_nova") or "").strip()
                resultados[item["n"]]["prompt_novo"] = (item.get("prompt_novo") or "").strip()


def _avaliar_com_jev(projeto, cenas, vizinhas, log, nota_minima):
    """Caminho do Jev: o modelo de visão descreve as imagens e o Jev julga cada descrição."""
    cfg = projeto.config.get("corrigir") or {}
    # uma cena por chamada na descrição: com várias imagens juntas, o modelo de visão troca as
    # legendas entre as cenas (medido: em lote de 5, duas saíram trocadas; uma por vez, todas certas).
    # Sai barato mesmo assim, porque cada chamada é pequena
    por_chamada = teto_imagens = max(1, cfg.get("cenas_por_descricao", 1))
    legendas = {c["n"]: _legenda_guardada(c) for c in cenas if _legenda_guardada(c)}
    if legendas:
        log(f"  {len(legendas)} cena(s) já tinham a descrição guardada, não precisam ser olhadas de novo")
    lotes, atual, quantas = [], [], 0
    for cena in cenas:
        if cena["n"] in legendas:
            continue
        quadros = _quadros(projeto, cena)
        if not quadros:
            continue
        if atual and (quantas + len(quadros) > teto_imagens or len(atual) >= por_chamada):
            lotes.append(atual)
            atual, quantas = [], 0
        atual.append((cena, quadros))
        quantas += len(quadros)
    if atual:
        lotes.append(atual)
    if lotes:
        novas = {}
        with ThreadPoolExecutor(_paralelismo(projeto)) as executor:
            for parcial in executor.map(lambda lote: _descrever_lote(projeto, lote, log), lotes):
                novas.update(parcial)
        _guardar_legendas(projeto, novas)
        legendas.update(novas)
    por_n = {c["n"]: c for c in cenas}
    # o descritor às vezes devolve um número de cena que não foi pedido: essas respostas são descartadas
    inventadas = [n for n in legendas if n not in por_n]
    if inventadas:
        log(f"  descartando {len(inventadas)} legenda(s) com número de cena que não foi pedido")
        legendas = {n: l for n, l in legendas.items() if n in por_n}
    log(f"  {len(legendas)} imagem(ns) descritas, julgando com o Jev")

    resultados = {}
    with ThreadPoolExecutor((projeto.config.get("jev") or {}).get("processos", 6)) as executor:
        julgados = executor.map(lambda item: (item[0], _julgar_com_jev(projeto, por_n[item[0]], item[1], vizinhas, log)),
                                sorted(legendas.items()))
        for n, r in julgados:
            if r:
                resultados[n] = r
    reprovadas = [por_n[n] for n, r in sorted(resultados.items()) if not aprovada(r, nota_minima)]
    _buscas_das_reprovadas(projeto, reprovadas, resultados, log)
    return resultados


def _avaliar_cena(projeto, cena, log, vizinhas=None):
    quadros = _quadros(projeto, cena)
    if not quadros:
        return None
    modulo, modelo = modelo_de_visao(projeto)
    try:
        resposta = modulo.perguntar(projeto, "conferir mídia", INSTRUCOES, _bloco_da_cena(cena, quadros, vizinhas),
                                    ESQUEMA_CONFERENCIA, log=log, modelo=modelo, imagens=quadros, temperatura=0)
    except RuntimeError as e:
        log(f"  não consegui conferir a cena {cena['n']} ({e})")
        return None
    resposta["nota"] = max(0, min(100, int(resposta["nota"])))
    return resposta


def _avaliar_lote(projeto, lote, log, vizinhas=None):
    """Confere várias cenas numa chamada só, o que divide o texto fixo das instruções entre elas.

    Devolve {n: resultado}. Cena sem imagem, ou que o modelo deixar de fora, fica sem resultado e a
    rodada seguinte tenta de novo."""
    blocos, imagens = [], []
    for cena in lote:
        quadros = _quadros(projeto, cena)
        if not quadros:
            continue
        blocos.append(_bloco_da_cena(cena, quadros, vizinhas))
        imagens.extend(quadros)
    if not blocos:
        return {}
    numeros = [c["n"] for c in lote]
    pedido = (f"Devolva exatamente {len(blocos)} itens, um por cena, na ordem.\n\n" + "\n\n".join(blocos))
    modulo, modelo = modelo_de_visao(projeto)
    try:
        resposta = modulo.perguntar(projeto, "conferir mídia", INSTRUCOES_LOTE + INSTRUCOES, pedido,
                                    ESQUEMA_CONFERENCIA_LOTE, log=log, modelo=modelo, imagens=imagens, temperatura=0)
    except RuntimeError as e:
        log(f"  não consegui conferir as cenas {numeros[0]} a {numeros[-1]} ({e})")
        return {}
    resultados = {}
    for item in resposta.get("cenas", []):
        if item.get("n") in numeros:
            item["nota"] = max(0, min(100, int(item.get("nota", 0))))
            resultados[item["n"]] = item
    faltaram = [n for n in numeros if n not in resultados]
    if faltaram:
        log(f"  o modelo não respondeu pelas cenas {', '.join(map(str, faltaram))}")
    return resultados


def _paralelismo(projeto):
    """Quantas conferências ao mesmo tempo no modelo principal."""
    return int((projeto.config.get("corrigir") or {}).get("paralelo", 4))


def _avaliar(projeto, numeros, log, nota_minima=NOTA_MINIMA):
    todas = projeto.ler_json("cenas.json")["cenas"]
    vizinhas = {c["n"]: (c.get("texto") or "").strip() for c in todas}
    cenas = conferiveis(projeto, numeros)
    if numeros:
        # a imagem de IA também é conferida quando a cena é pedida pelo número (conferir_ia)
        cenas += [c for c in todas if c["n"] in numeros and c.get("tipo") == "ia" and not c.get("midia")
                  and projeto.imagem(c["n"]).exists() and (c.get("texto") or "").strip()]
    if provedor(projeto) == "jev":
        return _avaliar_com_jev(projeto, cenas, vizinhas, log, nota_minima)
    por_chamada = max(1, (projeto.config.get("corrigir") or {}).get("cenas_por_chamada", 1))
    with ThreadPoolExecutor(_paralelismo(projeto)) as executor:
        if por_chamada == 1:
            resultados = executor.map(lambda c: _avaliar_cena(projeto, c, log, vizinhas), cenas)
            return {c["n"]: r for c, r in zip(cenas, resultados) if r}
        lotes = [cenas[i:i + por_chamada] for i in range(0, len(cenas), por_chamada)]
        juntos = {}
        for parcial in executor.map(lambda lote: _avaliar_lote(projeto, lote, log, vizinhas), lotes):
            juntos.update(parcial)
        return juntos


def _guardar(projeto, avaliacoes, rodada):
    """A legenda e a nota ficam na cena, para o editor mostrar o que o sistema enxergou."""
    dados = projeto.ler_json("cenas.json")
    for c in dados["cenas"]:
        if c["n"] in avaliacoes:
            a = avaliacoes[c["n"]]
            c["conferencia"] = {"legenda": a["legenda"], "veredito": a["veredito"], "nota": a["nota"],
                                "motivo": a["motivo"], "rodada": rodada,
                                **{k: a[k] for k in ("sujeito", "epoca", "prompt_novo") if a.get(k) is not None}}
    projeto.salvar_json("cenas.json", dados)


def _trocar_por_outra_busca(projeto, avaliacoes, numeros, log):
    """Rejeita a mídia atual e busca outra com o termo novo. Só material real, que não custa nada."""
    dados = projeto.ler_json("cenas.json")
    for c in dados["cenas"]:
        if c["n"] not in numeros:
            continue
        m = c.get("midia")
        if m and m.get("fonte") and m.get("id") is not None:
            c.setdefault("rejeitadas", []).append(f"{m['fonte']}:{m['id']}")
        c["midia"] = None
        c.pop("sem_midia_real", None)
        novo = avaliacoes[c["n"]]
        if novo["busca_nova"].strip():
            c["busca"] = novo["busca_nova"].strip()
        if novo["prompt_novo"].strip():
            c["prompt"] = novo["prompt_novo"].strip()
    projeto.salvar_json("cenas.json", dados)
    midia.buscar(projeto, apenas=set(numeros), log=log)


def _snapshot(projeto, cena, avaliacao, rodada):
    """Guarda a mídia atual da cena, com cópia dos arquivos, para poder voltar se a troca não melhorar."""
    m = cena.get("midia")
    copias = []
    for chave in ("arquivo", "capa"):
        if m and m.get(chave):
            origem = projeto.pasta / m[chave]
            if origem.exists():
                destino = projeto.caminho("conferir", "backup", f"{cena['n']:04d}_r{rodada}_{origem.name}")
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origem, destino)
                copias.append((destino, origem))
    return {"nota": avaliacao["nota"], "avaliacao": avaliacao, "midia": copy.deepcopy(m), "copias": copias,
            "busca": cena.get("busca"), "prompt": cena.get("prompt")}


def _restaurar(projeto, snapshots):
    """Devolve às cenas a melhor mídia que elas tiveram, com legenda e nota dela."""
    dados = projeto.ler_json("cenas.json")
    for c in dados["cenas"]:
        snap = snapshots.get(c["n"])
        if not snap or not snap["midia"]:
            continue
        for copia, origem in snap["copias"]:
            shutil.copy2(copia, origem)
        c["midia"], c["busca"], c["prompt"] = snap["midia"], snap["busca"], snap["prompt"]
        c.pop("sem_midia_real", None)
        chave = f"{c['midia']['fonte']}:{c['midia']['id']}"
        if chave in c.get("rejeitadas", []):
            c["rejeitadas"].remove(chave)
        a = snap["avaliacao"]
        c["conferencia"] = {"legenda": a["legenda"], "veredito": a["veredito"], "nota": a["nota"],
                            "motivo": a["motivo"], "restaurada": True}
    projeto.salvar_json("cenas.json", dados)


def corrigir(projeto, numeros=None, rodadas=RODADAS, nota_minima=NOTA_MINIMA, nota_para_trocar=NOTA_PARA_TROCAR,
             so_avaliar=False, log=print, ia=None) -> dict:
    """Confere as cenas e troca, de graça, o material real que não combina com a narração.

    Devolve um resumo. Em precisam_ia ficam as cenas que só uma imagem nova de IA resolve, com o
    prompt sugerido, que regerar_com_ia usa se o usuário aprovar o custo.
    """
    if not projeto.existe("cenas.json"):
        raise SystemExit(f"Faltam as cenas. Rode uv run fabrica cenas {projeto.nome}")
    resumo = {"avaliadas": 0, "aprovadas_de_primeira": 0, "trocadas": 0, "sem_conferencia": [], "reprovadas": [],
              "para_revisar": []}
    precisam_ia = {}
    melhor, nota_atual = {}, {}
    alvo = set(numeros) if numeros else None
    # IA obrigatória para cena errada (ia.ativa): uma busca nova só, e o que continuar errado vai para a IA. Rodar
    # três rodadas de busca quando o banco não tem a coisa só trouxe mais lixo (o virou-filme-em-1996 terminou o
    # Corrigir com 77 imagens que ninguém conferiu)
    ia = midia.ia_ativa(projeto) if ia is None else ia
    if ia:
        rodadas = min(rodadas, 2)

    def devolver_as_melhores():
        """Volta cada cena para a melhor mídia que ela teve. Roda mesmo se o comando for interrompido,
        senão uma cena fica sem imagem nenhuma porque a troca não chegou a terminar."""
        voltar = {n: snap for n, snap in melhor.items() if snap["nota"] > nota_atual.get(n, -1)}
        if not voltar:
            return []
        _restaurar(projeto, voltar)
        for n, snap in voltar.items():
            if aprovada(snap["avaliacao"], nota_minima):
                precisam_ia.pop(n, None)
            else:
                a = snap["avaliacao"]
                precisam_ia[n] = {"cena": n, "prompt": a["prompt_novo"] or snap["prompt"] or "", "motivo": a["motivo"]}
        log(f"  voltei a melhor imagem que tinham {len(voltar)} cena(s), porque a troca não melhorou")
        return sorted(voltar)

    try:
        resumo["restauradas"] = _rodadas(projeto, rodadas, nota_minima, nota_para_trocar, so_avaliar, log, resumo,
                                         precisam_ia, melhor, nota_atual, alvo, devolver_as_melhores)
    except BaseException:
        devolver_as_melhores()
        raise
    if not so_avaliar:
        if ia:
            # a melhor imagem que a cena teve ainda mostra OUTRA coisa: com a IA ligada ela vai para a IA, sem nova
            # busca no banco que já não tinha a coisa
            for n, a in _ainda_erradas(projeto, alvo).items():
                precisam_ia.setdefault(n, {"cena": n, "prompt": a.get("prompt_novo") or "", "motivo": a.get("motivo", "")})
        else:
            # a melhor imagem que a cena teve pode ser de OUTRA coisa (elefantes para "pé de elefante"): essa sai
            for n in _tirar_outra_coisa(projeto, nota_minima, log):
                precisam_ia.pop(n, None)
        # regra fixa: jamais repetir imagem. A devolução da "melhor imagem que a cena teve" podia trazer de volta
        # uma foto que outra cena passou a usar (o lince2 ficou com a mesma foto nas cenas 75 e 77)
        midia.tirar_repetidas(projeto, log)
        # nunca piorar: toda imagem que mudou e ninguém julgou é julgada agora
        for n, a in _conferir_sem_nota(projeto, alvo, nota_minima, log).items():
            if ia and errada(a, nota_para_trocar):
                precisam_ia.setdefault(n, {"cena": n, "prompt": a.get("prompt_novo") or "", "motivo": a["motivo"]})
        if ia and precisam_ia:
            resumo["geradas_com_ia"] = resolver_com_ia(projeto, list(precisam_ia.values()), log)
            precisam_ia = {}
    resumo["precisam_ia"] = [precisam_ia[n] for n in sorted(precisam_ia)]
    return resumo


def _ainda_erradas(projeto, alvo) -> dict:
    """As cenas de material real cuja última conferência diz que mostram outra coisa."""
    saida = {}
    for c in projeto.ler_json("cenas.json")["cenas"]:
        conf = c.get("conferencia") or {}
        if (alvo is None or c["n"] in alvo) and c.get("tipo") in midia.TIPOS_REAIS and c.get("midia") \
                and conf.get("nota") is not None and (errada(conf) or conf["nota"] < midia.NOTA_OUTRA_COISA):
            saida[c["n"]] = conf
    return saida


def _conferir_sem_nota(projeto, alvo, nota_minima, log) -> dict:
    """Julga as cenas de material real que mudaram de imagem e ficaram sem conferência (troca por repetida, busca
    nova do fim). Devolve as avaliações novas."""
    dados = projeto.ler_json("cenas.json")
    faltam = {c["n"] for c in dados["cenas"]
              if (alvo is None or c["n"] in alvo) and c.get("tipo") in midia.TIPOS_REAIS and c.get("midia")
              and not (c.get("conferencia") or {}).get("legenda")}
    if not faltam:
        return {}
    log(f"  {len(faltam)} cena(s) com imagem nova sem conferência: conferindo antes de terminar")
    avaliacoes = _avaliar(projeto, faltam, log, nota_minima)
    _guardar(projeto, avaliacoes, rodada=0)
    return avaliacoes


# ---------------------------------------------------------------------------------------- IA obrigatória

def mandar_para_ia(projeto, itens, log=print) -> list[int]:
    """A cena errada passa a usar imagem de IA. A foto que ela tinha fica guardada (ia_reserva) e volta se a imagem
    de IA sair pior ou não puder ser feita: nunca piorar."""
    from . import imagens

    por_n = {int(i["cena"]): i for i in itens}
    dados = projeto.ler_json("cenas.json")
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    mandadas = []
    for c in dados["cenas"]:
        item = por_n.get(c["n"])
        if item is None or c.get("personagem"):
            continue
        conf = c.get("conferencia") or {}
        reserva = {"midia": copy.deepcopy(c.get("midia")), "tipo": c.get("tipo"), "busca": c.get("busca"),
                   "nota": conf.get("nota"), "sujeito": conf.get("sujeito"),
                   "movidos": imagens._guardar_versao_antiga(projeto, c, carimbo)}
        if c.get("midia") and c["midia"].get("fonte"):
            c.setdefault("rejeitadas", []).append(f"{c['midia']['fonte']}:{c['midia']['id']}")
        c["ia_reserva"] = reserva
        c["midia"] = None
        c["tipo"] = "ia"
        c.pop("sem_midia_real", None)
        c.pop("conferencia", None)
        if (item.get("prompt") or "").strip() and not (c.get("prompt") or "").strip():
            c["prompt"] = item["prompt"].strip()
        c["ia_motivo"] = item.get("motivo") or "a imagem do banco mostrava outra coisa"
        mandadas.append(c["n"])
    projeto.salvar_json("cenas.json", dados)
    if mandadas:
        log(f"  {len(mandadas)} cena(s) erradas vão para imagem de IA: {', '.join(map(str, mandadas[:40]))}")
    return mandadas


def _voltar_reserva(projeto, n, log) -> bool:
    """A cena volta para a foto que tinha antes da IA."""
    dados = projeto.ler_json("cenas.json")
    c = next((x for x in dados["cenas"] if x["n"] == n), None)
    reserva = (c or {}).get("ia_reserva")
    if not reserva or not reserva.get("midia"):
        return False
    for origem, destino in reserva.get("movidos") or []:
        if Path(origem).exists() and not Path(destino).exists():
            shutil.move(origem, destino)
    imagem = projeto.imagem(n)
    if imagem.exists():
        destino = projeto.caminho("antigas", f"{imagem.stem}-ia-{datetime.now():%Y%m%d-%H%M%S}{imagem.suffix}")
        shutil.move(imagem, destino)
    c["midia"], c["tipo"], c["busca"] = reserva["midia"], reserva.get("tipo") or "foto_real", reserva.get("busca")
    c["captura"] = {**(c.get("captura") or {}), "suspeita": True}
    c.pop("ia_reserva", None)
    projeto.salvar_json("cenas.json", dados)
    log(f"  cena {n}: a imagem de IA saiu pior, voltou a foto que estava")
    return True


def conferir_ia(projeto, numeros=None, log=print) -> dict:
    """O Jev confere a imagem de IA como confere uma foto. Sujeito errado (espécie trocada, pessoa de frente, outra
    coisa): a imagem é feita de novo uma vez, com o motivo no pedido. Se ainda sair pior que a foto que a cena tinha,
    a foto volta. Devolve {n: avaliação}."""
    from . import imagens

    dados = projeto.ler_json("cenas.json")
    alvo = {c["n"] for c in dados["cenas"]
            if c.get("tipo") == "ia" and not c.get("midia") and projeto.imagem(c["n"]).exists()
            and (numeros is None or c["n"] in numeros) and not (c.get("conferencia") or {}).get("legenda")}
    if not alvo:
        return {}
    log(f"  conferindo {len(alvo)} imagem(ns) de IA com o Jev")
    avaliacoes = _avaliar(projeto, alvo, log, NOTA_MINIMA)
    _guardar(projeto, avaliacoes, rodada=0)
    refazer = {n: a for n, a in avaliacoes.items() if errada(a)}
    if refazer:
        log(f"  {len(refazer)} imagem(ns) de IA mostram outra coisa: fazendo de novo, com o motivo no pedido")
        por_n = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}
        for n, a in refazer.items():
            cena = por_n[n]
            base = (cena.get("prompt_manual") or cena.get("prompt") or "").strip()
            correcao = (f"{base}\nIMPORTANT: the previous image was wrong ({a['legenda'][:200]}). The image must clearly "
                        f"show: {cena.get('mostrar') or cena.get('sujeito') or cena.get('busca')}.")
            # a imagem atual fica guardada: se a nova não sair (provedor fora do ar, sem saldo), ela volta. Sem isso, as
            # 9 cenas do virou-filme-em-1996 ficaram vazias quando o saldo da Kie acabou no meio
            guarda = projeto.imagem(n).with_name(f"{projeto.imagem(n).stem}_guarda{projeto.imagem(n).suffix}")
            if projeto.imagem(n).exists():
                shutil.copy2(projeto.imagem(n), guarda)
            try:
                imagens.refazer(projeto, [n], prompt=correcao, log=log)
            except (Exception, SystemExit) as erro:
                log(f"  cena {n}: não deu para refazer a imagem de IA ({str(erro)[:120]}); fica a que estava")
            if not projeto.imagem(n).exists() and guarda.exists():
                shutil.move(guarda, projeto.imagem(n))
            guarda.unlink(missing_ok=True)
        de_novo = _avaliar(projeto, set(refazer), log, NOTA_MINIMA)
        _guardar(projeto, de_novo, rodada=0)
        avaliacoes.update(de_novo)
        por_n = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}
        for n, a in de_novo.items():
            reserva = (por_n[n].get("ia_reserva") or {})
            if errada(a) and reserva.get("nota") is not None and reserva["nota"] > a["nota"] \
                    and (reserva.get("sujeito") or 0) > (a.get("sujeito") or 0):
                _voltar_reserva(projeto, n, log)
    return avaliacoes


def resolver_com_ia(projeto, itens, log=print) -> list[int]:
    """Cena errada vai para a IA: marca, gera as imagens e confere cada uma. Devolve as cenas que ficaram com IA."""
    from . import imagens

    mandadas = mandar_para_ia(projeto, itens, log)
    if not mandadas:
        return []
    try:
        imagens.gerar(projeto, apenas=set(mandadas), log=log, conferir=False)
    except (Exception, SystemExit) as erro:
        log(f"  as imagens de IA não saíram agora ({str(erro)[:160]}); as cenas seguem marcadas e saem na próxima rodada")
        return mandadas
    conferir_ia(projeto, set(mandadas), log)
    return [c["n"] for c in projeto.ler_json("cenas.json")["cenas"] if c["n"] in mandadas and c.get("tipo") == "ia"]


def _nota_final(cena):
    """A última nota que a cena recebeu: a da conferência, ou a da captura se ela não foi conferida."""
    for chave in ("conferencia", "captura"):
        nota = (cena.get(chave) or {}).get("nota")
        if nota is not None:
            return nota
    return None


def _tirar_outra_coisa(projeto, nota_minima, log=print) -> list[int]:
    """Regra fixa: cena que terminou a conferência mostrando OUTRA coisa (nota abaixo de midia.NOTA_OUTRA_COISA)
    busca uma imagem NOVA do assunto, nunca copia a de outra cena.

    Copiar a imagem de uma cena aprovada deixava o vídeo cheio de repetição (19 imagens repetidas em 39 cenas
    no lince2). A foto reprovada entra em rejeitadas para não voltar, e a busca usa os 9 bancos, o iNaturalist
    nas cenas de animal e, se preciso, o assunto do bloco e do vídeo. Nenhuma imagem já usada no vídeo entra.
    Se nem assim aparecer nada novo, a cena fica com a imagem que tinha, marcada para revisão."""
    dados = projeto.ler_json("cenas.json")
    ruins = {}
    for c in dados["cenas"]:
        nota = _nota_final(c)
        m = c.get("midia") or {}
        if nota is None or nota >= midia.NOTA_OUTRA_COISA or not m.get("arquivo"):
            continue
        ruins[c["n"]] = copy.deepcopy(m)
        if m.get("fonte") and m.get("id"):
            c.setdefault("rejeitadas", []).append(f"{m['fonte']}:{m['id']}")
        c.pop("midia", None)
        c.pop("conferencia", None)
        c.pop("sem_midia_real", None)
        c["captura"] = {}
    if not ruins:
        return []
    projeto.salvar_json("cenas.json", dados)
    log(f"  {len(ruins)} cena(s) mostravam outra coisa: buscando imagem nova do assunto, sem repetir nenhuma")
    try:
        midia.buscar(projeto, apenas=set(ruins), log=log)
    except (Exception, SystemExit) as erro:
        log(f"  a busca de imagem nova falhou ({str(erro)[:100]}); as cenas voltam para a imagem que tinham")
    dados = projeto.ler_json("cenas.json")
    trocadas, voltaram = [], []
    for c in dados["cenas"]:
        if c["n"] not in ruins:
            continue
        if c.get("midia"):
            trocadas.append(c["n"])
        else:
            c["midia"] = ruins[c["n"]]
            c["captura"] = {"suspeita": True, "preenchida": "sem imagem nova do assunto; ficou a que tinha"}
            voltaram.append(c["n"])
    projeto.salvar_json("cenas.json", dados)
    if voltaram:
        log(f"  {len(voltaram)} cena(s) sem imagem nova do assunto em nenhum banco, marcadas para revisão: "
            + ", ".join(map(str, voltaram)))
    return trocadas


def _rodadas(projeto, rodadas, nota_minima, nota_para_trocar, so_avaliar, log, resumo, precisam_ia, melhor,
             nota_atual, alvo, devolver_as_melhores):
    for rodada in range(1, rodadas + 1):
        avaliacoes = _avaliar(projeto, alvo, log, nota_minima)
        _guardar(projeto, avaliacoes, rodada)
        # trocar sozinho só o que está claramente errado: sujeito errado, época errada ou nota muito baixa. A faixa do
        # meio vira sugestão na tela: das 118 trocas de uma execução anterior, só 41 vingaram, e o resto girou à toa
        erradas = {n for n, a in avaliacoes.items() if errada(a, nota_para_trocar)}
        reprovadas = {n for n, a in avaliacoes.items() if not aprovada(a, nota_minima)} | erradas
        duvidosas = reprovadas - erradas
        cenas = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}
        nota_atual.update({n: a["nota"] for n, a in avaliacoes.items()})
        if rodada == 1:
            resumo["avaliadas"] = len(avaliacoes)
            resumo["aprovadas_de_primeira"] = len(avaliacoes) - len(reprovadas)
            esperadas = {c["n"] for c in conferiveis(projeto, alvo)}
            resumo["sem_conferencia"] = sorted(esperadas - set(avaliacoes))
            ignoradas = [n for n, c in cenas.items() if c["tipo"] not in midia.TIPOS_REAIS and (alvo is None or n in alvo)]
            if ignoradas:
                log(f"  {len(ignoradas)} cena(s) de IA ficam de fora, o conferidor só olha material real")
        log(f"  rodada {rodada}: {len(avaliacoes)} cena(s) conferidas, {len(reprovadas)} não combinam")
        for n in sorted(reprovadas):
            a = avaliacoes[n]
            log(f"    cena {n}, nota {a['nota']}: mostra {a['legenda']}. {a['motivo']}")

        if rodada == 1:
            resumo["para_revisar"] = [
                {"cena": n, "nota": avaliacoes[n]["nota"], "legenda": avaliacoes[n]["legenda"],
                 "motivo": avaliacoes[n]["motivo"]} for n in sorted(duvidosas)]
            if duvidosas:
                log(f"  {len(duvidosas)} cena(s) ficaram na dúvida (nota de {nota_para_trocar} a {nota_minima - 1}): "
                    "não troco sozinho, ficam na lista para você decidir")
        ultima = so_avaliar or rodada == rodadas
        if so_avaliar:
            resumo["reprovadas"] = sorted(reprovadas)
            break
        reprovadas = erradas  # daqui para baixo, só as claramente erradas são mexidas
        reais = []
        for n, a in avaliacoes.items():
            if n not in reprovadas:
                precisam_ia.pop(n, None)
            elif cenas[n]["tipo"] in midia.TIPOS_REAIS and not ultima:
                reais.append(n)
            else:
                precisam_ia[n] = {"cena": n, "prompt": a["prompt_novo"] or cenas[n].get("prompt", ""), "motivo": a["motivo"]}
        if not reais:
            break
        reais.sort()
        for n in reais:
            if n not in melhor or nota_atual[n] > melhor[n]["nota"]:
                melhor[n] = _snapshot(projeto, cenas[n], avaliacoes[n], rodada)
        log(f"  buscando outro material real para {len(reais)} cena(s), de graça")
        _trocar_por_outra_busca(projeto, avaliacoes, reais, log)
        resumo["trocadas"] += len(reais)
        depois = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}
        for n in reais:
            if not depois[n].get("midia"):
                nota_atual[n] = -1
                # nenhuma opção real sobrou: só a imagem de IA resolve
                precisam_ia[n] = {"cena": n, "prompt": avaliacoes[n]["prompt_novo"] or depois[n].get("prompt", ""),
                                  "motivo": "não achei outro material real que combine"}
        alvo = {n for n in reais if depois[n].get("midia")}
        if not alvo:
            break
    # se as trocas não melhoraram, a cena volta para a melhor mídia que teve, em vez de ficar pior ou sem imagem
    return devolver_as_melhores()


def preparar_gratis(projeto, log=print) -> dict:
    """Etapa sem custo antes da conferência: refaz a busca das cenas de material real com mídia suspeita
    (arquivo sumido, duplicado ou id inventado) e busca material para as cenas reais que ainda não têm.

    Não gera imagem de IA. Reaproveita as rotinas do limpeza.py."""
    from . import limpeza, verificar

    resultado = {"suspeitas": 0, "resolvidas": 0, "buscadas": 0}
    suspeitas = sorted({a["cena"] for a in verificar.verificar(projeto)})
    resultado["suspeitas"] = len(suspeitas)
    pendentes = set(suspeitas)
    for _ in range(limpeza.MAX_RODADAS_BUSCA):
        if not pendentes:
            break
        limpeza._rejeitar_e_limpar(projeto, pendentes)
        midia.buscar(projeto, apenas=pendentes, log=log)
        pendentes = {a["cena"] for a in verificar.verificar(projeto)}
    resultado["resolvidas"] = len(set(suspeitas) - pendentes)

    faltando = [c["n"] for c in projeto.ler_json("cenas.json")["cenas"] if midia.pendente(c)]
    if faltando:
        log(f"  {len(faltando)} cena(s) de material real ainda sem arquivo, buscando de graça")
        midia.buscar(projeto, apenas=set(faltando), log=log)
        depois = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}
        resultado["buscadas"] = sum(1 for n in faltando if depois[n].get("midia"))

    resultado.update(_preencher_sem_arquivo(projeto, log))
    return resultado


RODADAS_SEM_ARQUIVO = 3


def sem_arquivo(projeto) -> list[int]:
    """Cenas de material real que não têm nada para mostrar: nem arquivo de acervo nem imagem de IA já gerada."""
    lista = projeto.ler_json("cenas.json")["cenas"]
    return [c["n"] for c in lista if c.get("tipo") in midia.TIPOS_REAIS
            and not (c.get("midia") and (projeto.pasta / c["midia"]["arquivo"]).exists())
            and not projeto.imagem(c["n"]).exists()]


def _preencher_sem_arquivo(projeto, log=print) -> dict:
    """Prioridade do Corrigir Mídia: as cenas sem arquivo ganham material de banco de imagens, sem gerar IA.

    A busca que já falhou não é repetida. Um modelo de texto escreve termos novos a partir da narração, e a
    busca roda de novo, até RODADAS_SEM_ARQUIVO vezes. Na última rodada a escolha aceita o candidato mais
    próximo em vez de nenhum, porque a conferência que vem depois troca o que não combinar."""
    inicio = sem_arquivo(projeto)
    resultado = {"sem_arquivo_antes": len(inicio), "sem_arquivo_resolvidas": 0}
    if not inicio:
        return resultado
    log(f"  {len(inicio)} cena(s) de material real sem arquivo nenhum, buscando nos bancos de imagens (sem IA)")
    restantes = list(inicio)
    for rodada in range(1, RODADAS_SEM_ARQUIVO + 1):
        dados = projeto.ler_json("cenas.json")
        por_n = {c["n"]: c for c in dados["cenas"]}
        alvo = [por_n[n] for n in restantes]
        # os termos que já falharam ficam guardados, e o modelo é avisado de que precisa mudar de ideia
        resultados = {c["n"]: {"legenda": f"nenhuma imagem serviu para a busca '{c.get('busca') or ''}'"} for c in alvo}
        _buscas_das_reprovadas(projeto, alvo, resultados, log)
        trocou = []
        for c in alvo:
            nova = (resultados[c["n"]].get("busca_nova") or "").strip()
            if nova and nova != (c.get("busca") or ""):
                c.setdefault("buscas_tentadas", []).append(c.get("busca") or "")
                c["busca"] = nova
                if resultados[c["n"]].get("prompt_novo"):
                    c["prompt"] = resultados[c["n"]]["prompt_novo"]
                c.pop("sem_midia_real", None)
                trocou.append(c["n"])
        if not trocou:
            log("  não consegui termos de busca novos para as cenas que faltam")
            break
        projeto.salvar_json("cenas.json", dados)
        log(f"  rodada {rodada} de busca para as cenas sem arquivo: {len(trocou)} com termos novos")
        midia.buscar(projeto, apenas=set(trocou), log=log, permissivo=rodada == RODADAS_SEM_ARQUIVO)
        restantes = sem_arquivo(projeto)
        if not restantes:
            break
    depois = set(sem_arquivo(projeto))
    resultado["sem_arquivo_resolvidas"] = len(set(inicio) - depois)
    if depois:
        log(f"  {len(depois)} cena(s) continuam sem arquivo: {', '.join(map(str, sorted(depois)))}")
    return resultado


def regerar_com_ia(projeto, itens, log=print):
    """Troca as cenas por imagens novas de IA, com o prompt sugerido. Custa dinheiro, quem chama já confirmou."""
    for item in itens:
        imagens.refazer(projeto, [item["cena"]], prompt=item["prompt"], log=log)


def formatar(resumo) -> str:
    linhas = [f"{resumo['avaliadas']} cena(s) conferidas, {resumo['aprovadas_de_primeira']} combinavam de primeira."]
    if resumo["trocadas"]:
        linhas.append(f"{resumo['trocadas']} troca(s) de material real feitas, de graça.")
    if resumo.get("restauradas"):
        linhas.append("Ficou a imagem original, porque a troca não melhorou, nas cenas: " + ", ".join(map(str, resumo["restauradas"])))
    if resumo.get("para_revisar"):
        linhas.append(f"{len(resumo['para_revisar'])} cena(s) ficaram na dúvida e esperam a sua decisão: "
                      + ", ".join(str(i["cena"]) for i in resumo["para_revisar"]))
    if resumo["reprovadas"]:
        linhas.append("Não combinam com a narração, nada foi trocado: " + ", ".join(map(str, resumo["reprovadas"])))
    if resumo["precisam_ia"]:
        linhas.append("Só uma imagem nova de IA resolve as cenas: " + ", ".join(str(i["cena"]) for i in resumo["precisam_ia"]))
    if resumo["sem_conferencia"]:
        linhas.append("Não consegui conferir as cenas: " + ", ".join(map(str, resumo["sem_conferencia"])))
    return "\n".join(linhas)
