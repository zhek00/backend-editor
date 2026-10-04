"""Agente de roteiro: lê o roteiro inteiro antes de decidir o que aparece em cada cena.

Sem ele, o modelo das cenas decide olhando só uns 100 segundos de narração, e uma frase como
"Coincidieron." ou "El mayor, conocido como Montículo A" chega sem o assunto do vídeo. O trabalho
acontece em duas etapas.

1. Mapa. Uma chamada lê o roteiro completo e devolve os blocos de assunto (com a âncora visual
   de cada um), as armadilhas de busca, as pessoas reais, o que é proibido mostrar e as imagens
   que voltam. Fica em roteiro_mapa.json e só depende do texto, então roda antes da narração.
2. Cenas. Os cortes continuam sendo feitos pelo código (_pre_cortar, 3 a 5 segundos). Para cada
   bloco, o agente recebe o mapa, o perfil do canal, as últimas cenas decididas e os trechos já
   cortados, e decide a imagem de cada um. As regras fixas de cenas.py continuam valendo depois.
"""
import hashlib
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from . import texto as tx
from .textos import REGRAS_QUALIDADE

PROMPT_MAPA = """Você é o diretor visual de um canal de YouTube no estilo "dark" (narração sem apresentador, só imagens).

Você vai receber o ROTEIRO COMPLETO de um vídeo e o NICHO do canal.
Sua tarefa NÃO é criar as cenas. Sua tarefa é entender a história e produzir um MAPA curto que vai orientar a criação das cenas depois.

Devolva SOMENTE um JSON válido, neste formato:

{
  "titulo": "título curto do vídeo",
  "estilo_ia": "estilo visual único para todas as imagens geradas por IA neste vídeo (em inglês)",
  "blocos": [
    {
      "id": 1,
      "nome": "nome do bloco",
      "primeira_frase": "primeiras palavras exatas do trecho onde o bloco começa",
      "ancora": "assunto visual principal do bloco, em inglês, concreto (ex.: 'monitor lizard in the Amazon rainforest')",
      "contexto": "1 ou 2 palavras em inglês que dizem o que o assunto do bloco É (ex.: 'marsupial animal', 'lizard', 'venomous fish')",
      "epoca": "o ano em que se passa o que o bloco conta, quando é passado (ex.: '1898'); vazio quando é hoje ou não tem época"
    }
  ],
  "armadilhas": [
    {"termo": "nome ambíguo", "problema": "o que a busca traria de errado", "usar": "como escrever a busca corretamente"}
  ],
  "pessoas_reais": ["nomes de pessoas reais citadas, que nunca terão rosto gerado por IA"],
  "quem_e": [{"nome": "nome completo da pessoa real", "quem": "anos de vida, país e o que fez, em até 15 palavras"}],
  "proibidos": ["marcas, séries, filmes, logos ou obras protegidas citadas que não podem aparecer em imagem"],
  "imagens_recorrentes": [
    {"descricao": "imagem que deve voltar em vários momentos para dar coesão", "momentos": "onde ela aparece"}
  ]
}

REGRAS:
- Um novo bloco começa quando o ASSUNTO PRINCIPAL da narração muda (outro animal, outro lugar, outra época, outra ideia central).
- O primeiro bloco começa na primeira frase do roteiro.
- Em primeira_frase copie as primeiras 6 a 10 palavras do trecho exatamente como estão no roteiro, com a mesma grafia e acentos.
- A âncora deve ser algo que se possa ver, nunca um conceito abstrato, e sempre escrita em inglês.
- O contexto vai junto das buscas do bloco nos bancos de imagens, para um nome ambíguo não trazer outra coisa ("sugar glider" sozinho traz açúcar; "sugar glider marsupial" traz o animal). Use a categoria do assunto, nunca clima ou enquadramento.
- Só liste em "armadilhas" termos que estão no roteiro.
- Em "armadilhas", liste todo nome que, buscado num banco de fotos, traria outra coisa: nome próprio ambíguo (um lugar chamado "Poverty Point" traz fotos de pobreza), palavra de duplo sentido ("plataforma" de caça vira estação de trem; "tranca quebrada" vira o cânion Quebrada de las Conchas; sobrenome de pessoa vira a cidade com o mesmo nome), apelido, metáfora ou comparação ("pé de elefante" para a massa derretida do reator de Chernobyl, "olho do furacão", "cavalo de Troia" para um vírus). Em "usar", 2 a 5 palavras em inglês que descrevem o que a coisa É, com o lugar ou o assunto do vídeo, e NUNCA a palavra que causa a armadilha: "pé de elefante" vira "Chernobyl reactor corium lava" (sem "elephant", que traria elefantes); "cavalo de Troia" vira "computer virus malware" (sem "horse"). Sem palavras de clima ou enquadramento como dark, moody, close-up.
- Em "pessoas_reais", só nomes próprios de pessoas citadas pelo nome no roteiro. Se nenhuma é citada pelo nome, devolva a lista vazia.
- Em "quem_e", um item para cada pessoa de "pessoas_reais", com o nome completo e quem ela é (ex.: "John Henry Patterson" → "1867-1947, oficial do exército britânico, caçou os leões de Tsavo em 1898"). Serve para não confundir com outra pessoa do mesmo nome nos bancos de imagens.
- Em "epoca", o ano do que o bloco conta quando é passado ("1898" para a construção da ferrovia). Vazio para o que se passa hoje (uma pesquisa de 2009, um museu hoje) ou não tem época.
- Seja conciso. Este mapa é um guia, não o trabalho final."""

ESQUEMA_MAPA = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "estilo_ia": {"type": "string"},
        "blocos": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "nome": {"type": "string"},
                           "primeira_frase": {"type": "string"}, "ancora": {"type": "string"},
                           "contexto": {"type": "string"}, "epoca": {"type": "string"}},
            "required": ["id", "nome", "primeira_frase", "ancora", "contexto", "epoca"],
            "additionalProperties": False,
        }},
        "armadilhas": {"type": "array", "items": {
            "type": "object",
            "properties": {"termo": {"type": "string"}, "problema": {"type": "string"}, "usar": {"type": "string"}},
            "required": ["termo", "problema", "usar"],
            "additionalProperties": False,
        }},
        "pessoas_reais": {"type": "array", "items": {"type": "string"}},
        "quem_e": {"type": "array", "items": {
            "type": "object",
            "properties": {"nome": {"type": "string"}, "quem": {"type": "string"}},
            "required": ["nome", "quem"],
            "additionalProperties": False,
        }},
        "proibidos": {"type": "array", "items": {"type": "string"}},
        "imagens_recorrentes": {"type": "array", "items": {
            "type": "object",
            "properties": {"descricao": {"type": "string"}, "momentos": {"type": "string"}},
            "required": ["descricao", "momentos"],
            "additionalProperties": False,
        }},
    },
    "required": ["titulo", "estilo_ia", "blocos", "armadilhas", "pessoas_reais", "quem_e", "proibidos",
                 "imagens_recorrentes"],
    "additionalProperties": False,
}

PROMPT_CENAS = """Você é o Diretor de Arte Sênior e Pesquisador Visual Rigoroso de um canal de YouTube de narração sem apresentador (estilo "dark").
Sua função é decidir, trecho a trecho, a imagem de cada cena com 100% de precisão, fidelidade e coerência com a narração, em qualquer nicho ou tema.
É proibido usar metáforas visuais preguiçosas, imagens genéricas que fujam do sentido literal ou inventar elementos que a narração não menciona.

Você vai receber o MAPA do vídeo, o PERFIL DO NICHO e os TRECHOS de UM bloco, já cortados e numerados.

REGRAS ABSOLUTAS (tolerância zero para erro de contexto):
1. Precisão absoluta do sujeito, sem substituições. Se a narração cita um objeto, pessoa, veículo, software, animal ou evento específico, a imagem mostra EXATAMENTE aquilo. "Carro elétrico moderno" nunca vira carro a combustão clássico; "Roma Antiga" nunca vira arquitetura medieval; "pangolim" nunca vira tatu.
2. Cenário e contexto fiéis. O ambiente corresponde à realidade do sujeito e ao tom do texto: finanças corporativas não acontecem num café descontraído (a menos que o texto peça); roteiro de esporte de inverno não tem praia.
3. Nada de B-roll desconexo. Cada cena ilustra literalmente o conceito ou a ação narrada naquele segundo. "Segurança de dados" é servidor, código ou tela de criptografia, nunca líquido fervendo, gente correndo ou engrenagem genérica.
4. Ação e característica exatas. Se a narração diz "ele apertou o botão vermelho de emergência", a imagem mostra o botão sendo apertado, não alguém olhando para uma tela. Se cita uma parte do corpo ou da estrutura (o ferrão, as brânquias, o casco), é ela que aparece.
5. Placas, textos e telas do contexto certo. Nada de placa em inglês sobre avalanche num vídeo sobre trânsito urbano brasileiro. Na imagem de IA, nunca peça texto escrito, letras legíveis ou logotipos.
6. Continuidade sem reaproveitar fora do lugar. Uma imagem de impacto (explosão, cirurgia, gráfico disparando) não se repete em blocos sem relação: cada tópico tem a própria identidade visual. Reaproveitar só vale dentro do mesmo assunto, quando o trecho retoma algo já mostrado.

Devolva SOMENTE um JSON válido, com um item por trecho recebido, com o mesmo número em "cena", na mesma ordem. Nunca pule um trecho e nunca invente trechos.

Campos de cada cena (para cada trecho, analise o texto falado e responda):
- tipo: foto_real | ia | texto_tela | linha_do_tempo | mapa | diagrama
- fonte: stock | wikimedia | ia | motion
- sujeito: o SUJEITO/FOCO PRINCIPAL que tem que estar na cena, sem ambiguidade, em inglês, em 1 a 3 palavras, só o substantivo (ex.: "cobra", "soil core", "hospital"), nunca uma cena descrita
- descricao: o que aparece na tela, em português, 1 frase com o sujeito concreto E o CENÁRIO/AMBIENTE onde ele está, físico ou digital (nunca "ele", "o lugar", "o animal")
- exato: o que a foto OBRIGATORIAMENTE precisa mostrar, escrito como estaria na legenda da foto num banco de imagens, em inglês: o nome próprio de um lugar, pessoa, obra, evento ou objeto único ("Pripyat", "Chernobyl", "New Safe Confinement", "Mona Lisa"), o nome de um aparelho ou objeto específico ("Geiger counter", "trail camera") ou a espécie de um animal ("Eurasian lynx"). Vazio quando qualquer representação direta do mesmo tipo serve (um hospital, uma floresta, um gráfico, uma pessoa de costas). A fábrica só aceita foto cujas tags citem esse nome, então não ponha adjetivo nem ação aqui
- onde_existe: onde a imagem certa desta cena existe de verdade:
  - "banco": em banco de imagens de stock (Pexels, Pixabay): animal, paisagem, objeto, lugar ou situação de hoje;
  - "arquivo": em acervo e na Wikimedia: foto ou gravura de época, retrato de pessoa real, documento, lugar, obra ou espécie específica;
  - "nao_existe": ninguém fotografou: um momento específico do passado ou da história (o leão dentro da armadilha, o caçador na plataforma à noite), uma cena reconstruída, uma ação que só a narração descreve. Essas cenas viram imagem de IA.
  Na dúvida entre "banco" e "nao_existe", pense se uma busca acharia AQUELE momento, e não uma coisa parecida
- aceitavel: em português, o MÍNIMO que a imagem precisa mostrar para a cena estar certa, quando o ideal da descricao não existir: o sujeito, sem o momento exato (descricao "dois leões sem juba entre tendas à noite" → aceitavel "leão sem juba"; descricao "engenheiro britânico chegando à obra da ponte" → aceitavel "obra de ponte ferroviária antiga"). É contra isso que a imagem é julgada
- epoca: o ano (ex.: "1898") quando a imagem tem que ser DAQUELA época: pessoas, roupas, construções, veículos, documentos, objetos e acontecimentos do passado, antes de 1950. Vazio para o que não muda com o tempo (um animal, uma paisagem, um rio, o céu) e para o que é de hoje (um laboratório em 2009, um museu hoje). Use o "epoca" do bloco no mapa como referência
- animal: se a imagem deve mostrar um animal, o nome comum em inglês DAQUELA espécie (ex.: "pangolin", "aye-aye", "glass frog", "spectacled cobra"); vazio quando a imagem não é de um animal (um cientista, um laboratório, uma sala, um gráfico), mesmo num bloco sobre animais
- query: busca em inglês, 2 a 6 palavras
- busca_alternativa: uma segunda busca do MESMO sujeito, 1 a 3 palavras em inglês, para quando a query não achar nada (ex.: query "exotic pet risk chart" → alternativa "risk chart"). Diferente da query e nunca de outra coisa. Para ANIMAL use o nome científico dele (ex.: query "spectacled cobra hood" → alternativa "Naja naja")
- prompt_ia: o PROMPT VISUAL em inglês, ultradetalhado e focado na precisão do sujeito (ver regras abaixo)
- overlay: o texto na tela deste trecho, em MAIÚSCULAS, seguindo as regras de QUALIDADE DO TEXTO NA TELA abaixo, ou vazio (o normal)
- reusar_cena: número da cena reaproveitada, ou 0 quando não reaproveita
- citacoes: OBRIGATÓRIO sempre que o trecho cita duas ou mais coisas visuais DIFERENTES, de qualquer assunto (bichos: "lobos, alces, cavalos-de-przewalski"; objetos: "cobre, esteatita e pedernal"; lugares, pessoas, aparelhos). Uma citação por coisa, na ordem em que são faladas, e a fábrica corta a cena para cada uma aparecer na hora em que é falada. Em cada citação: palavra é a primeira palavra dela exatamente como está no trecho; descricao é o que a fatia mostra, em português, só daquela coisa; exato e animal seguem as mesmas regras da cena, só daquela coisa; query e prompt_ia mostram só aquela coisa. Se cita uma coisa só, ou nenhuma, devolva vazio.

CENAS DE ÉPOCA (campo epoca preenchido):
- O que existe de uma época passada é material de ARQUIVO: fotografias tiradas na época, gravuras, ilustrações de livros e jornais da época, mapas antigos, documentos, objetos e espécimes de museu. Não existe foto de banco de imagens de 1898: Pexels e Pixabay só têm gente e obra de hoje.
- descricao e query pedem esse material, nunca uma reconstituição com ação, hora e luz que ninguém fotografou ("leão entrando na tenda à noite", "engenheiro chegando de costas"). Peça o que o arquivo tem: o lugar, a obra, a pessoa ou o objeto daquela época ("Uganda Railway construction 1899 photograph", "Tsavo bridge 1899", "Victorian hunting rifle").
- Se o fato virou livro, reportagem ou foi fotografado na época, a query usa isso (ex.: as fotos do livro "The Man-eaters of Tsavo", de 1907: "Man-eaters of Tsavo 1907 photograph"). Marque fonte wikimedia.
- Pessoa real de época: a query é o nome completo com o ano ou a função ("John Henry Patterson 1907", "Lieutenant Colonel Patterson Tsavo"), nunca só o sobrenome, que traz homônimos.

COMO DECIDIR O TIPO (siga nesta ordem, pare na primeira que servir):
1. O impacto do trecho está num NÚMERO ou DATA? → texto_tela (fonte: motion)
2. Compara ÉPOCAS ou datas diferentes? → linha_do_tempo (fonte: motion)
3. Fala de LUGARES, DISTÂNCIAS ou ROTAS? → mapa (fonte: motion)
4. Explica um CONCEITO ou PROCESSO que não se fotografa? → diagrama (fonte: motion)
5. O que aparece EXISTE HOJE e já foi fotografado?
   - Se é algo comum (animal conhecido, paisagem, objeto do dia a dia, monumento famoso) → foto_real, fonte: stock
   - Se é um lugar, objeto, artefato ou espécie específico e pouco conhecido → foto_real, fonte: wikimedia
6. Nada disso (passado distante, cena reconstruída, momento que ninguém fotografou) → ia

A fábrica ainda não desenha animações. Por isso TODA cena, de qualquer tipo, traz query e prompt_ia: nas de motion eles descrevem a imagem que fica por baixo do texto, do mapa ou do diagrama, sempre com o sujeito do bloco.

REGRAS DAS BUSCAS (query):
- A busca procura EXATAMENTE o sujeito e a ação do trecho, escrita do jeito que alguém procuraria essa foto num banco de imagens: o nome mais comum da coisa + o que a narração diz dela (ex.: "cobra snake hood", "hospital intensive care", "hand pressing emergency button", "server room racks").
- Se o que a frase cita é específico demais para existir em banco de imagens (o gráfico de um estudo, um documento, uma pessoa anônima), busque uma representação DIRETA do mesmo tipo de coisa (um gráfico, um documento, uma pessoa de costas), nunca uma metáfora.
- Sempre em inglês, com substantivos concretos, de 2 a 5 palavras. Nunca mais de 6.
- Só o assunto: nunca palavras de clima, luz ou enquadramento (dark, moody, cinematic, silhouette, glowing, night, close-up, macro). O clima vai no prompt_ia, não na busca.
- Quando o trecho fala do sujeito do bloco sem nomeá-lo ("ele", "o animal", "o lugar"), a busca usa o sujeito da âncora do bloco. Mas quando o trecho fala de OUTRA coisa (um hospital, uma pessoa, um soro, uma cidade, um tribunal), a imagem mostra essa outra coisa, e não o sujeito do bloco: "deu entrada às pressas em um hospital" é hospital, não a cobra do bloco.
- ANIMAL tem que ser exato: quando o trecho fala de um animal, a query é o nome comum em inglês DAQUELA espécie (ex.: "pangolin", "platypus", "tasmanian devil"), nunca um parente ou um genérico ("animal", "mammal", "lizard" para um teiú), e a busca_alternativa é o nome científico (ex.: "Manis", "Ornithorhynchus anatinus"). Marque fonte wikimedia, que tem foto de espécies raras.
- Nunca use uma frase abstrata como busca. Transforme-a numa cena concreta com o sujeito do bloco.
- Aplique as correções da lista de armadilhas do mapa.
- ANTES de escrever cada query e cada busca_alternativa, pergunte: "esta busca, sozinha num banco de fotos, sem saber do que o vídeo trata, pode trazer outra coisa?". Você conhece o roteiro inteiro; o banco de fotos não. Se a busca tem apelido, metáfora, comparação, palavra de duplo sentido ou nome que também é outra coisa, TIRE essa palavra e escreva o que a coisa é de fato, com o lugar ou o assunto do vídeo: num vídeo sobre Chernobyl, o "pé de elefante" é "Chernobyl reactor corium lava", nunca "elephant foot"; a "tampa do reator" é "Chernobyl reactor 4 destroyed roof", nunca "lid". O campo exato segue a mesma regra.

REGRAS DOS PROMPTS DE IA (prompt_ia):
- Fórmula: SUJEITO exato + fazendo a AÇÃO literal do trecho + ONDE (o cenário da descricao) + QUE ÉPOCA + LUZ e PALETA + CÂMERA (ex.: "cinematic shot, 35mm lens, hyper-realistic, strictly focused on [sujeito] [ação] in [ambiente], [luz], [paleta]").
- Não repita o estilo geral do vídeo; ele será adicionado automaticamente.
- Pessoas da lista "pessoas_reais": nunca mostrar o rosto. Mostrar de costas, de longe ou só as mãos, e nunca escrever o nome delas no prompt.
- Nunca gerar nada da lista "proibidos".
- Nunca gerar pessoas de povos ou grupos reais de forma estereotipada; prefira paisagem.
- Nunca pedir texto escrito, letras, placas legíveis ou logotipos dentro da imagem.

RITMO E COESÃO:
- Frases curtas e de impacto merecem destaque (texto_tela ou imagem forte).
- Momentos de mistério: neblina, entardecer, noite. Revelações: imagem forte ou número grande.
- NUNCA repita imagem: use reusar_cena 0 sempre. Quando o trecho retoma algo já mostrado (inclusive das "imagens_recorrentes" do mapa), mostre o MESMO assunto por outro ângulo, outro momento ou outro detalhe, com uma query diferente da cena anterior.
- Evite duas cenas seguidas com a mesma imagem, a não ser que seja reaproveitamento intencional.

""" + REGRAS_QUALIDADE

CITACAO = {
    "type": "object",
    "properties": {"palavra": {"type": "string"}, "descricao": {"type": "string"}, "exato": {"type": "string"},
                   "animal": {"type": "string"}, "query": {"type": "string"}, "prompt_ia": {"type": "string"}},
    "required": ["palavra", "descricao", "exato", "animal", "query", "prompt_ia"],
    "additionalProperties": False,
}

ESQUEMA_CENAS = {
    "type": "object",
    "properties": {"cenas": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "cena": {"type": "integer"},
            "tipo": {"type": "string", "enum": ["foto_real", "ia", "texto_tela", "linha_do_tempo", "mapa", "diagrama"]},
            "fonte": {"type": "string", "enum": ["stock", "wikimedia", "ia", "motion"]},
            "descricao": {"type": "string"},
            "sujeito": {"type": "string"},
            "animal": {"type": "string"},
            "exato": {"type": "string"},
            "onde_existe": {"type": "string", "enum": ["banco", "arquivo", "nao_existe"]},
            "aceitavel": {"type": "string"},
            "epoca": {"type": "string"},
            "query": {"type": "string"},
            "busca_alternativa": {"type": "string"},
            "prompt_ia": {"type": "string"},
            "overlay": {"type": "string"},
            "reusar_cena": {"type": "integer"},
            "citacoes": {"type": "array", "items": CITACAO},
        },
        "required": ["cena", "tipo", "fonte", "descricao", "sujeito", "animal", "exato", "onde_existe", "aceitavel",
                     "epoca", "query", "busca_alternativa", "prompt_ia",
                     "overlay", "reusar_cena", "citacoes"],
        "additionalProperties": False,
    }}},
    "required": ["cenas"],
    "additionalProperties": False,
}

TIPOS_MOTION = ("texto_tela", "linha_do_tempo", "mapa", "diagrama")
# palavras que só dizem enquadramento ou estilo: uma busca feita só delas e do termo ambíguo é o termo sozinho
_SO_ESTILO = {"close", "closeup", "up", "macro", "detail", "view", "shot", "angle", "wide", "aerial", "dramatic",
              "cinematic", "photo", "image", "picture", "the", "of", "a", "an", "in", "at", "on"}


def ativo(projeto) -> bool:
    """O agente só entra nos canais sem personagem e sem efeitos, que ele não sabe decidir."""
    perfil = projeto.perfil
    cfg = projeto.config.get("roteirista") or {}
    return (bool(cfg.get("ativo", True)) and not projeto.offline
            and not (perfil.get("personagem") or {}).get("descricao")
            and not (perfil.get("efeitos") or {}).get("ativo"))


MIMO = "stealth/space-bunny-alpha"  # nome antigo; quem manda é openrouter.modelo_principal


def _modelo_agente(projeto):
    """Quem responde pelo agente: roteirista.provedor primeiro, depois o Groq e o Gemini.

    O padrão é o MiMo pela OpenRouter, pelo nome fixo e com o raciocínio desligado no config.yaml: ele lê o
    roteiro inteiro de uma vez (o Groq gratuito não cabe) e, medido nos projetos, sai a uns US$ 0,11 por milhão
    de tokens lidos e US$ 0,25 por milhão escritos, bem abaixo do Gemini."""
    from . import gemini_local, groq_local, openrouter_local
    from .cenas import _ComReserva, _modelo

    cfg = projeto.config.get("roteirista") or {}
    provedor = cfg.get("provedor", "mimo")
    principal = ("modelo principal", openrouter_local, openrouter_local.principal(projeto))
    if provedor == "openrouter" and cfg.get("modelo"):
        # um modelo do OpenRouter só para o agente e o diretor (roteirista.modelo, hoje o DeepSeek V4 Flash: bom em
        # seguir instruções longas e JSON, uns US$ 0,01 por vídeo). Se ele falhar, a cadeia de principais responde
        return _ComReserva([(cfg["modelo"], openrouter_local, cfg["modelo"]), principal])
    if provedor == "claude":
        # o Claude da assinatura do Claude Code: não cobra além da mensalidade e escreve o JSON limpo. O modelo
        # principal gratuito escreveu "exércitoBritish" e copiou descrições de uma cena para as seguintes. Se o
        # Claude falhar (sem login, limite da assinatura), o modelo principal responde, sem esperar
        return _ComReserva([("Claude da assinatura", _PeloClaude(), None), principal])
    if provedor != "mimo":
        return _modelo(projeto)
    return _ComReserva([principal])


class _PeloClaude:
    """O claude_local com a mesma assinatura dos outros modelos (log, temperatura e modelo são ignorados)."""

    def perguntar(self, projeto, etapa, instrucoes, pedido, esquema, log=print, **_):
        from . import claude_local

        esforco = (projeto.config.get("roteirista") or {}).get("esforco_claude", "medium")
        return claude_local.perguntar(projeto, etapa, instrucoes, pedido, esquema, esforco=esforco)


def estimar(projeto, quantas_cenas) -> dict:
    """Custo do agente em dólares: o mapa (roteiro inteiro) e as cenas (um pedido por lote). Zero se não usar o MiMo.

    Tamanhos medidos: cada lote de cenas lê uns 6,5 mil tokens e escreve uns 6 mil (com o raciocínio do DeepSeek); o
    mapa escreve uns 3 mil."""
    provedor = (projeto.config.get("roteirista") or {}).get("provedor", "mimo")
    if not ativo(projeto) or provedor not in ("mimo", "openrouter"):
        return {"mapa": 0.0, "cenas": 0.0}
    precos = projeto.config.get("precos") or {}
    if provedor == "openrouter":
        entrada = precos.get("agente_entrada_por_milhao", 0.03) / 1e6
        saida = precos.get("agente_saida_por_milhao", 0.06) / 1e6
    else:
        entrada = precos.get("mimo_entrada_por_milhao", 0.11) / 1e6
        saida = precos.get("mimo_saida_por_milhao", 0.25) / 1e6
    roteiro = tx.normalizar(projeto.roteiro())
    lidos_mapa = (len(PROMPT_MAPA) + len(roteiro) + len(json.dumps(ESQUEMA_MAPA))) / 3.3
    lotes = -(-max(1, quantas_cenas) // (projeto.config.get("roteirista") or {}).get("cenas_por_lote", 10))
    return {"mapa": lidos_mapa * entrada + 3000 * saida, "cenas": lotes * (6500 * entrada + 6000 * saida)}


def _nicho(perfil):
    return (perfil.get("nicho") or perfil.get("nome") or "").strip()


def _perfil_do_nicho(projeto):
    from .midia import ia_ativa

    perfil = projeto.perfil
    partes = [f"Canal: {_nicho(perfil)}"]
    if (perfil.get("diretrizes") or "").strip():
        partes.append("Diretrizes: " + perfil["diretrizes"].strip())
    orientacao = ((perfil.get("midia_real") or {}).get("orientacao") or "").strip()
    if orientacao:
        partes.append("Orientação de mídia: " + orientacao)
    if not ia_ativa(projeto):
        partes.append("Este canal está sem imagem de IA: prefira foto_real, e a query de toda cena tem que achar foto em banco de imagens.")
    return "\n".join(partes)


def _comparavel(texto):
    """Texto sem acento, minúsculo e só com letras e números, com a posição de cada letra no original."""
    letras, posicoes, espaco = [], [], True
    for i, ch in enumerate(texto):
        base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode().lower()
        if base and base.isalnum():
            letras.append(base[0])
            posicoes.append(i)
            espaco = False
        elif not espaco:
            letras.append(" ")
            posicoes.append(i)
            espaco = True
    return "".join(letras), posicoes


def _localizar(roteiro_comparavel, posicoes, frase, desde):
    """Posição no roteiro onde a frase começa, procurando do ponto desde em diante. Tenta com menos palavras se não achar."""
    palavras = _comparavel(frase)[0].split()
    for quantas in sorted({q for q in (len(palavras), 8, 6, 4) if 0 < q <= len(palavras)}, reverse=True):
        agulha = " ".join(palavras[:quantas])
        achado = roteiro_comparavel.find(agulha, desde)
        if achado >= 0:
            return achado, posicoes[achado]
    return None, None


def assinatura_do_mapa(projeto):
    """Muda quando o roteiro, o nicho ou o prompt do mapa mudam, e só aí o mapa é refeito."""
    roteiro = tx.normalizar(projeto.roteiro())
    return hashlib.sha1((PROMPT_MAPA + _nicho(projeto.perfil) + roteiro).encode("utf-8")).hexdigest()[:12]


def mapa(projeto, log=print, forcar=False) -> dict:
    """Lê o roteiro inteiro e devolve o mapa do vídeo, guardado em roteiro_mapa.json.

    Só é refeito quando o roteiro, o nicho ou o prompt mudam. Cada bloco ganha inicio_c, a posição no
    roteiro narrado onde ele começa, que liga o bloco às frases da narração."""
    roteiro = tx.normalizar(projeto.roteiro())
    nicho = _nicho(projeto.perfil)
    assinatura = assinatura_do_mapa(projeto)
    if projeto.existe("roteiro_mapa.json") and not forcar:
        salvo = projeto.ler_json("roteiro_mapa.json")
        if salvo.get("assinatura") == assinatura:
            return salvo

    log("  lendo o roteiro inteiro para montar o mapa do vídeo")
    pedido = f"NICHO: {nicho}\n\nROTEIRO:\n{roteiro}"
    dados = _modelo_agente(projeto).perguntar(projeto, "roteirista: mapa", PROMPT_MAPA, pedido, ESQUEMA_MAPA, log=log,
                                       temperatura=0.2)
    comparavel, posicoes = _comparavel(roteiro)
    blocos, desde = [], 0
    for bloco in dados.get("blocos") or []:
        if not blocos:
            inicio_c, achado = 0, 0  # o primeiro bloco começa no começo do roteiro, diga o modelo o que disser
        else:
            achado, inicio_c = _localizar(comparavel, posicoes, bloco.get("primeira_frase", ""), desde)
            if achado is None:
                log(f"  bloco '{bloco.get('nome')}' sem posição no roteiro, fica junto do anterior")
                continue
        blocos.append({**bloco, "inicio_c": inicio_c})
        desde = achado + 1
    if not blocos:
        blocos = [{"id": 1, "nome": dados.get("titulo", ""), "primeira_frase": "", "ancora": dados.get("titulo", ""),
                   "inicio_c": 0}]
    for n, bloco in enumerate(blocos, start=1):
        bloco["id"] = n
    resultado = {**dados, "blocos": blocos, "assinatura": assinatura}
    projeto.salvar_json("roteiro_mapa.json", resultado)
    log(f"  mapa pronto: {len(blocos)} bloco(s), {len(dados.get('armadilhas') or [])} armadilha(s) de busca")
    return resultado


def _mapa_para_o_modelo(m):
    """O mapa sem os campos internos da fábrica, compacto para caber no limite por pedido."""
    return json.dumps({k: ([{c: b[c] for c in ("id", "nome", "ancora")} for b in v] if k == "blocos" else v)
                       for k, v in m.items() if k not in ("assinatura",)}, ensure_ascii=False, separators=(",", ":"))


def _bloco_da_frase(m, unidade):
    atual = m["blocos"][0]
    for bloco in m["blocos"]:
        if bloco["inicio_c"] <= unidade["c_ini"]:
            atual = bloco
    return atual


def _palavras(texto):
    return [p for p in re.findall(r"[a-z0-9]+", _comparavel(texto)[0])]


def _limpa(busca):
    from .cenas import limpar_busca

    return limpar_busca(busca)


def completar_contexto(projeto, log=print) -> None:
    """Mapa feito antes do campo contexto: pede ao MiMo só essa palavra de cada bloco e grava no mapa.

    Uma chamada pequena por projeto (frações de centavo). A assinatura do mapa não muda, então nada é refeito."""
    if not projeto.existe("roteiro_mapa.json"):
        return
    mapa_salvo = projeto.ler_json("roteiro_mapa.json")
    faltam = [b for b in mapa_salvo.get("blocos", []) if not (b.get("contexto") or "").strip()]
    if not faltam:
        return
    log(f"  completando o contexto de {len(faltam)} bloco(s) do mapa, para as buscas não trazerem outra coisa")
    pedido = "\n".join(f"{b['id']}. {b.get('nome', '')} | âncora: {b.get('ancora', '')}" for b in faltam)
    esquema = {"type": "object", "properties": {"blocos": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "integer"}, "contexto": {"type": "string"}},
        "required": ["id", "contexto"], "additionalProperties": False}}},
        "required": ["blocos"], "additionalProperties": False}
    instrucoes = ("Para cada bloco, escreva em 'contexto' 1 ou 2 palavras em inglês que dizem o que o assunto do bloco É, "
                  "a categoria que vai junto da busca nos bancos de imagens para um nome ambíguo não trazer outra coisa "
                  "(ex.: sugar glider -> 'marsupial animal'; teiú -> 'lizard'; lionfish -> 'venomous fish'; um bloco de "
                  "introdução com vários animais -> 'exotic animals'). Nunca clima, cor ou enquadramento.")
    from . import openrouter_local

    resposta = openrouter_local.perguntar(projeto, "contexto do mapa", instrucoes, pedido, esquema, log=log,
                                          modelo=openrouter_local.principal(projeto))
    novos = {int(b["id"]): (b.get("contexto") or "").strip() for b in resposta.get("blocos", []) if b.get("contexto")}
    for b in mapa_salvo["blocos"]:
        if novos.get(b["id"]) and not (b.get("contexto") or "").strip():
            b["contexto"] = novos[b["id"]]
    projeto.salvar_json("roteiro_mapa.json", mapa_salvo)
    log("  contexto dos blocos: " + "; ".join(f"{b['id']} {b.get('contexto', '')}" for b in mapa_salvo["blocos"]))


def aplicar_armadilhas(busca, armadilhas):
    """Uma busca que é só o nome ambíguo (mais palavras de enquadramento) vira a busca certa do mapa."""
    if not busca:
        return busca
    palavras = set(_palavras(busca))
    for a in armadilhas or []:
        termo = _palavras(a.get("termo", ""))
        if termo and set(termo) <= palavras and not (palavras - set(termo) - _SO_ESTILO) and a.get("usar"):
            return _limpa(a["usar"].strip())
    return busca


def _sem_pessoas_reais(prompt, pessoas):
    """Tira do prompt de IA o nome das pessoas reais, que faria o gerador tentar o rosto delas."""
    tirou = False
    for nome in pessoas or []:
        if nome and re.search(re.escape(nome), prompt, re.I):
            prompt = re.sub(re.escape(nome), "a person", prompt, flags=re.I)
            tirou = True
    return prompt + ", seen from behind, face not visible" if tirou else prompt


def _linhas(unidades, cortes, k):
    g = cortes[k]
    frases = unidades[g["primeira_frase"]:g["ultima_frase"] + 1]
    duracao = frases[-1]["fim"] - frases[0]["ini"]
    return f"CENA {k + 1} | {duracao:.1f}s\n  " + " ".join(f["texto"] for f in frases)


# palavra grudada em outra ("exércitoBritish", "presenteReality") ou com lixo depois de sublinhado ("ferroviários_dpklsy"):
# o modelo principal gratuito escrevia assim no meio das descrições, e a busca e o Jev liam o lixo
_GRUDADA = re.compile(r"[a-zà-ÿ]{3,}[A-Z][a-z]{2,}|[a-zà-ÿ]_[A-Za-z]{3,}")
_CAMPOS_DE_TEXTO = ("descricao", "query", "busca_alternativa", "exato", "sujeito", "aceitavel", "prompt_ia")


def problemas_do_lote(respostas, textos) -> list:
    """O que está errado nas cenas que o agente devolveu, para pedir de novo. textos: {cena: fala da cena}."""
    problemas = []
    por_cena = {r.get("cena"): r for r in respostas}
    for r in respostas:
        n = r.get("cena")
        for campo in _CAMPOS_DE_TEXTO:
            achado = _GRUDADA.search(str(r.get(campo) or ""))
            if achado:
                problemas.append(f"cena {n}, campo {campo}: palavras grudadas ou lixo (\"{achado.group()}\"); "
                                 "escreva palavras separadas, só em português na descricao e no aceitavel e só em inglês na query")
                break
        exato = (r.get("exato") or "").strip()
        if exato and re.search(r"[ãõçáéíóúâêô]|\b(de|do|da|dos|das)\b", exato.lower()):
            problemas.append(f"cena {n}: exato em português (\"{exato}\"); escreva em inglês, como na legenda da foto")
        anterior = por_cena.get(n - 1) if isinstance(n, int) else None
        if anterior and (r.get("descricao") or "").strip() and \
                (r.get("descricao") or "").strip() == (anterior.get("descricao") or "").strip() and \
                textos.get(n, "").strip() != textos.get(n - 1, "").strip():
            problemas.append(f"cena {n}: a descricao é a mesma da cena {n - 1}, mas a fala é outra; descreva o que "
                             f"ESTA fala cita (\"{textos.get(n, '')[:80]}\")")
    return problemas


def _limpar_resposta(r) -> dict:
    """O que sobrou de palavra grudada depois de pedir de novo ganha um espaço; o lixo depois de sublinhado sai."""
    limpo = dict(r)
    for campo in _CAMPOS_DE_TEXTO:
        valor = str(limpo.get(campo) or "")
        valor = re.sub(r"_[A-Za-z]{3,}", "", valor)
        valor = re.sub(r"([a-zà-ÿ]{3,})([A-Z][a-z]{2,})", r"\1 \2", valor)
        limpo[campo] = valor
    return limpo


def _epoca(valor) -> str:
    """O ano da época que a imagem tem que mostrar, só antes de 1950; depois disso os bancos de stock servem."""
    anos = [int(a) for a in re.findall(r"\b(1\d{3})\b", str(valor or ""))]
    return str(anos[0]) if anos and anos[0] < 1950 else ""


def _converter(item, m, bloco):
    """A decisão do agente no formato das cenas da fábrica. Motion vira a imagem de baixo até existir animação."""
    armadilhas = m.get("armadilhas") or []
    pessoas = m.get("pessoas_reais") or []
    visual = item.get("tipo", "ia")
    # a busca fica só com o assunto e no máximo 6 palavras, mesmo que o modelo tenha escrito mais
    busca = _limpa(aplicar_armadilhas((item.get("query") or "").strip(), armadilhas))
    onde = (item.get("onde_existe") or "").strip()
    if onde == "nao_existe":
        # ninguém fotografou: a cena nasce como IA (com a IA desligada, cenas.py devolve ela ao acervo)
        tipo = "ia"
    elif visual == "foto_real" or (visual in TIPOS_MOTION and busca) or onde in ("banco", "arquivo"):
        tipo = "foto_real"
    else:
        tipo = "ia"
    prompt = _sem_pessoas_reais((item.get("prompt_ia") or item.get("descricao") or "").strip(), pessoas)
    citacoes = [{"palavra": (c.get("palavra") or "").strip(),
                 "busca": _limpa(aplicar_armadilhas((c.get("query") or "").strip(), armadilhas)),
                 "prompt": _sem_pessoas_reais((c.get("prompt_ia") or "").strip(), pessoas),
                 # cada item citado tem o próprio "o que mostrar", exato e animal: é contra ele que o Jev julga a fatia
                 "descricao": (c.get("descricao") or "").strip(),
                 "exato": (c.get("exato") or "").strip(),
                 "animal": (c.get("animal") or "").strip()}
                for c in item.get("citacoes") or [] if (c.get("palavra") or "").strip()]
    return {
        "tipo": tipo,
        "busca": busca or _limpa(aplicar_armadilhas(bloco.get("ancora", ""), armadilhas)),
        "busca_alternativa": _limpa(aplicar_armadilhas((item.get("busca_alternativa") or "").strip(), armadilhas)),
        "sujeito": (item.get("sujeito") or "").strip(),
        # a espécie exata que a imagem tem que mostrar, dita pelo agente; vazio quando a cena não é de animal
        "animal": (item.get("animal") or "").strip(),
        # o nome que a foto precisa ter (lugar, objeto único, aparelho, espécie); vazio: qualquer representação direta
        "exato": (item.get("exato") or "").strip(),
        # o ano, quando a imagem tem que ser daquela época: só material de arquivo (midia.e_de_epoca)
        "epoca": _epoca(item.get("epoca")),
        # onde a imagem existe (banco, arquivo, nao_existe) e o mínimo para a cena estar certa, contra o qual o Jev julga
        "onde_existe": onde,
        "aceitavel": (item.get("aceitavel") or "").strip(),
        "prompt": prompt,
        "personagem": False,
        "citacoes": citacoes,
        "texto_tela": None,
        "efeito": None,
        "descricao": (item.get("descricao") or "").strip(),
        "overlay": (item.get("overlay") or "").strip(),
        "visual": visual,
        "fonte": "wikimedia" if onde == "arquivo" else item.get("fonte", ""),
        "bloco": bloco["id"],
    }


def planejar_grupos(projeto, unidades, cortes, log=print):
    """Decide a imagem de cada corte, bloco a bloco, com o mapa do vídeo. Devolve os grupos no formato de cenas.py.

    Cada pedaço decidido fica guardado em cenas_lotes, então rodar de novo continua de onde parou. O que o
    agente deixar sem resposta vai para a decisão antiga do Groq, para o vídeo não parar."""
    from .cenas import _decidir_cenas_groq, _sistema_groq

    m = mapa(projeto, log)
    cfg = projeto.config.get("roteirista") or {}
    por_lote = cfg.get("cenas_por_lote", 10)
    mapa_texto = _mapa_para_o_modelo(m)
    perfil_texto = _perfil_do_nicho(projeto)
    from . import aprendizados
    # o que a pessoa corrigiu em vídeos anteriores do canal, congelado neste projeto na primeira vez
    aprendido = aprendizados.texto_para_o_agente(projeto)

    por_bloco = {}
    for k, corte in enumerate(cortes):
        por_bloco.setdefault(_bloco_da_frase(m, unidades[corte["primeira_frase"]])["id"], []).append(k)
    blocos = {b["id"]: b for b in m["blocos"]}
    log(f"  {len(cortes)} cortes prontos em {len(por_bloco)} bloco(s) do roteiro")

    ordem = sorted(por_bloco)

    def decidir_bloco(id_bloco):
        """Os lotes de um bloco, em ordem. Cada lote vê as últimas cenas decididas no próprio bloco; o primeiro
        vê só o nome e a âncora do bloco anterior, para os blocos poderem rodar em paralelo e o pedido (e o
        cache) ser sempre o mesmo, rode na ordem que rodar."""
        bloco, ks = blocos[id_bloco], por_bloco[id_bloco]
        posicao = ordem.index(id_bloco)
        anterior = blocos[ordem[posicao - 1]] if posicao else None
        # lotes do mesmo tamanho, em vez de 10 + 10 + uma sobra de 1 ou 2 cenas que custava um pedido inteiro
        quantos = -(-len(ks) // por_lote)
        tamanho = -(-len(ks) // quantos)
        brutas, locais = {}, {}
        for inicio in range(0, len(ks), tamanho):
            lote = ks[inicio:inicio + tamanho]
            anteriores = [k for k in sorted(locais) if k < lote[0]][-3:]
            if anteriores:
                resumo = "\n".join(f"CENA {k + 1}: {locais[k].get('descricao', '')} "
                                   f"({locais[k].get('visual', '')}, {locais[k].get('busca', '')})" for k in anteriores)
            elif anterior:
                resumo = f"(começo do bloco; o bloco anterior foi {anterior['id']}. {anterior['nome']}, âncora: {anterior['ancora']})"
            else:
                resumo = "(nenhuma, é o começo do vídeo)"
            trechos = "\n".join(_linhas(unidades, cortes, k) for k in lote)
            pedido = (f"MAPA DO VÍDEO:\n{mapa_texto}\n\nPERFIL DO NICHO:\n{perfil_texto}\n\n"
                      + (f"APRENDIZADOS DO CANAL:\n{aprendido}\n\n" if aprendido else "") +
                      f"ÚLTIMAS CENAS DO BLOCO ANTERIOR (para manter continuidade):\n{resumo}\n\n"
                      f"BLOCO ATUAL: {bloco['id']}. {bloco['nome']} (âncora: {bloco['ancora']})\n\n"
                      f"TRECHOS DESTE BLOCO (devolva exatamente {len(lote)} cenas, de {lote[0] + 1} a {lote[-1] + 1}):\n{trechos}")
            assinatura = hashlib.sha1((PROMPT_CENAS + pedido).encode("utf-8")).hexdigest()[:10]
            arquivo = projeto.caminho("cenas_lotes", f"roteirista_{lote[0]:04d}_{assinatura}.json")
            if arquivo.exists():
                respostas = json.loads(arquivo.read_text(encoding="utf-8"))
            else:
                validas = {k + 1 for k in lote}
                textos_do_lote = {k + 1: " ".join(f["texto"] for f in unidades[cortes[k]["primeira_frase"]:
                                                                               cortes[k]["ultima_frase"] + 1])
                                  for k in lote}
                respostas, problemas = [], []
                for tentativa in range(2):
                    extra = ("\n\nA RESPOSTA ANTERIOR FOI RECUSADA. Corrija:\n- " + "\n- ".join(problemas)) if problemas else ""
                    try:
                        respostas = _modelo_agente(projeto).perguntar(projeto, "roteirista: cenas", PROMPT_CENAS,
                                                                      pedido + extra, ESQUEMA_CENAS, log=log).get("cenas", [])
                    except (RuntimeError, SystemExit) as e:
                        log(f"  o agente não decidiu as cenas {lote[0] + 1} a {lote[-1] + 1} ({str(e)[:90]})")
                        respostas = []
                    respostas = [r for r in respostas if r.get("cena") in validas]
                    problemas = problemas_do_lote(respostas, textos_do_lote)
                    if not problemas or not respostas:
                        break
                    log(f"  o agente errou nas cenas {lote[0] + 1} a {lote[-1] + 1}, pedindo de novo: {problemas[0][:120]}")
                respostas = [_limpar_resposta(r) for r in respostas]
                if len(respostas) == len(lote):
                    arquivo.write_text(json.dumps(respostas, ensure_ascii=False, indent=2), encoding="utf-8")
            for item in respostas:
                k = item["cena"] - 1
                if k not in brutas:
                    brutas[k] = item
                    locais[k] = _converter(item, m, bloco)
            log(f"  bloco {bloco['id']} ({bloco['nome']}): cenas {lote[0] + 1} a {lote[-1] + 1} decididas")
        return brutas

    # os blocos não dependem um do outro, então vários rodam ao mesmo tempo (roteirista.paralelo)
    brutas = {}
    with ThreadPoolExecutor(max_workers=max(1, int(cfg.get("paralelo", 4)))) as grupo:
        for resultado in grupo.map(decidir_bloco, ordem):
            brutas.update(resultado)

    # o reaproveitamento pode apontar para uma cena de outro bloco, então só é resolvido com tudo decidido
    decididas = {}
    for k in sorted(brutas):
        item = brutas[k]
        bloco = _bloco_da_frase(m, unidades[cortes[k]["primeira_frase"]])
        decisao = _converter(item, m, bloco)
        origem = decididas.get((item.get("reusar_cena") or 0) - 1)
        if origem and item.get("reusar_cena", 0) - 1 < k:
            # reaproveitamento: mesma busca e mesmo prompt da cena original
            decisao.update({c: origem[c] for c in ("tipo", "busca", "busca_alternativa", "sujeito", "prompt")})
            decisao["reusa"] = item["reusar_cena"]
        decididas[k] = decisao

    faltam = [k for k in range(len(cortes)) if k not in decididas]
    if faltam:
        log(f"  {len(faltam)} cena(s) sem resposta do agente, decididas pelo caminho antigo")
        sistema = _sistema_groq(projeto.perfil)
        cfg_groq = projeto.config.get("groq") or {}
        passo = cfg_groq.get("cenas_por_lote", 20)
        for inicio in range(0, len(faltam), passo):
            decididas.update(_decidir_cenas_groq(projeto, sistema, unidades, cortes, faltam[inicio:inicio + passo],
                                                 range(0), range(0), cfg_groq, log))
    return [{**cortes[k], **decididas[k]} for k in range(len(cortes))]


def _unidades_estimadas(projeto):
    """As frases do roteiro, com o tempo previsto pelo ritmo da voz do perfil, antes de existir narração.

    Os números das frases saem só do texto (texto.unidades), então são os mesmos que a narração vai
    gerar depois, e o JSON de cenas feito aqui se encaixa nelas sem nenhuma conta nova."""
    roteiro = tx.normalizar(projeto.roteiro())
    por_segundo = ((projeto.perfil.get("ritmo") or {}).get("caracteres_por_minuto") or 900) / 60
    unidades, relogio = [], 0.0
    for n, u in enumerate(tx.unidades(roteiro)):
        duracao = (len(u.texto) + 1) / por_segundo
        unidades.append({"id": n, "texto": u.texto, "c_ini": u.ini, "c_fim": u.fim,
                         "ini": round(relogio, 3), "fim": round(relogio + duracao, 3)})
        relogio += duracao
    return unidades


def _assinatura_das_cenas(projeto, m):
    cfg = projeto.config.get("roteirista") or {}
    ritmo = (projeto.perfil.get("ritmo") or {}).get("caracteres_por_minuto")
    base = json.dumps([m.get("assinatura"), PROMPT_CENAS, _perfil_do_nicho(projeto), cfg.get("cenas_por_lote", 10), ritmo])
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def roteiro_de_cenas(projeto, log=print, forcar=False) -> dict:
    """O JSON completo das cenas, feito só com o texto: o agente decide cada trecho antes da narração.

    Fica em roteiro_cenas.json. O corte usa o tempo previsto de cada frase (3 a 5 segundos pelo ritmo da voz),
    e o passo de cenas só encaixa esse JSON no tempo real das palavras, sem chamar nenhum modelo."""
    from .cenas import ESTILO_ALVO_SEGUNDOS, ESTILO_MAXIMO_SEGUNDOS, ESTILO_MINIMO_SEGUNDOS, _pre_cortar

    m = mapa(projeto, log)
    assinatura = _assinatura_das_cenas(projeto, m)
    if projeto.existe("roteiro_cenas.json") and not forcar:
        salvo = projeto.ler_json("roteiro_cenas.json")
        if salvo.get("assinatura") == assinatura:
            return salvo
    unidades = _unidades_estimadas(projeto)
    cortes = _pre_cortar(unidades, ESTILO_ALVO_SEGUNDOS, ESTILO_MINIMO_SEGUNDOS, ESTILO_MAXIMO_SEGUNDOS)
    log(f"  o agente vai decidir {len(cortes)} cenas pelo texto do roteiro")
    grupos = planejar_grupos(projeto, unidades, cortes, log)
    for g in grupos:
        g["texto"] = " ".join(u["texto"] for u in unidades[g["primeira_frase"]:g["ultima_frase"] + 1])
        if g.get("overlay") and not g.get("texto_tela"):
            # o texto sugerido pelo agente vira o texto na tela, no momento da primeira frase da cena
            g["texto_tela"] = {"tipo": "destaque", "texto": g["overlay"], "destaque": "", "titulo": "",
                               "frase": g["primeira_frase"], "itens": []}
    resultado = {"assinatura": assinatura, "frases": len(unidades), "cenas": grupos}
    projeto.salvar_json("roteiro_cenas.json", resultado)
    log(f"  JSON de cenas pronto: {len(grupos)} cenas em roteiro_cenas.json")
    return resultado


def grupos_para_a_narracao(projeto, unidades, log=print):
    """Os grupos do JSON de cenas, prontos para o passo de cenas. Refaz o JSON só se ele não servir mais."""
    dados = roteiro_de_cenas(projeto, log)
    if dados.get("frases") != len(unidades):
        # a narração foi feita de outro texto: o JSON não se encaixa, e o agente decide sobre os cortes reais
        log("  o JSON de cenas não bate com as frases da narração, decidindo pelos cortes da narração")
        return None
    grupos = [dict(g) for g in dados["cenas"]]
    for g in grupos:
        # JSONs feitos antes da regra de 6 palavras: a busca é limpa aqui também, sem chamar o agente de novo
        for campo in ("busca", "busca_alternativa"):
            g[campo] = _limpa(g.get(campo, ""))
    return grupos
