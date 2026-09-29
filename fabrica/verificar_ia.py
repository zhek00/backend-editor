"""Verificação de conteúdo por IA (Gemini com visão).

Diferente de verificar.py (que só olha os dados — arquivo duplicado, id inventado), essa
checagem manda a imagem/capa de cada cena pro Gemini junto com a narração e pergunta se elas
realmente combinam. Pega o tipo de erro que só dá pra ver olhando: uma imagem de IA que saiu
com o bicho errado, ou uma foto de banco que bateu com o termo de busca só por coincidência
mas não tem nada a ver com a cena.

Tem custo real (chama a API do Gemini com imagem, ao contrário do resto de verificar.py que
é de graça) — por isso fica de fora do "Corrigir Mídia" automático por padrão; quem chama
decide quando vale a pena rodar.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import chave

MODELO_VERIFICACAO = "gemini-3.6-flash"
# quando o modelo preferido está sobrecarregado (503), tenta os próximos em vez de insistir
# no mesmo - mesma lista de reserva que narracao.py usa pro planejamento de cenas
MODELOS_RESERVA = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-3.5-flash"]
CENAS_POR_LOTE = 6  # cenas analisadas por chamada, reduz o número de idas e vindas
PARALELISMO = 4
TENTATIVAS = 2  # por modelo, antes de cair pro próximo da lista de reserva

_INSTRUCAO = (
    "Você está revisando um vídeo documentário narrado. Para cada cena a seguir, olhe a imagem "
    "e diga se ela REALMENTE ilustra o que a narração descreve — mesmo animal, objeto ou cena, "
    "sem contradizer a anatomia, o contexto ou a lógica do que está sendo dito. Ignore diferenças "
    "de qualidade artística ou estilo; foque só em incompatibilidade de CONTEÚDO/ASSUNTO. Uma "
    "imagem genérica mas tematicamente correta conta como compatível.\n\n"
    "Responda estritamente em JSON, sem texto fora do JSON:\n"
    '{"cenas": [{"n": <numero da cena>, "compativel": <true ou false>, '
    '"motivo": "<explicação curta em português>", '
    '"prompt_sugerido": "<descrição em inglês pra gerar uma imagem de IA correta, só quando compativel=false>"}]}'
)

ESQUEMA_REFINO = {
    "type": "object",
    "properties": {
        "cenas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "busca": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["n"],
            },
        },
    },
    "required": ["cenas"],
}

INSTRUCOES_REFINO = """Você revisa, em lote, o termo de busca de acervo e o prompt de imagem de IA de cenas
de um vídeo, já divididas por outro modelo. Não mude o tipo da cena nem o que ela mostra, só melhore
a formulação.

Para cenas foto_real ou video_real: reescreva busca com 2 a 5 palavras em inglês, do jeito que alguém
digitaria num banco de imagens (Pexels, Pixabay, Wikimedia) para achar aquele exato registro real —
substantivos concretos, sem adjetivos de câmera ("cinematic", "close-up", "shot of") nem palavras vagas.
Se o termo atual já está bom, devolva ele igual.

Para cenas ia: reescreva prompt em inglês, como a legenda de uma fotografia: sujeito, ação, enquadramento,
ambiente e detalhes importantes, sem descrever o estilo geral (isso é acrescentado depois) e sem pedir
texto na imagem. Escreva prompts distintos e específicos para cada momento."""


def _cliente():
    from google import genai
    return genai.Client(api_key=chave("GEMINI_API_KEY"))


def _imagem_da_cena(projeto, cena):
    """Bytes da imagem que representa a cena hoje (capa do vídeo real, foto real, ou imagem
    de IA) — o que o espectador realmente vê na tela. None se ainda não tiver nada gerado."""
    midia = cena.get("midia")
    if midia:
        caminho = midia.get("capa") or midia.get("arquivo")
        if caminho:
            arq = projeto.pasta / caminho
            if arq.exists() and arq.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                return arq.read_bytes(), ("image/png" if arq.suffix.lower() == ".png" else "image/jpeg")
    arq_ia = projeto.imagem(cena["n"])
    if arq_ia.exists():
        return arq_ia.read_bytes(), "image/png"
    return None, None


def _pedir_avaliacao(cliente, lote):
    """lote: list de (n, texto, dados_imagem, mime). Devolve dict n -> resultado do Gemini."""
    from google.genai import types

    partes = [types.Part.from_text(text=_INSTRUCAO)]
    for n, texto, dados, mime in lote:
        partes.append(types.Part.from_text(text=f'Cena {n}. Narração: "{texto}"'))
        partes.append(types.Part.from_bytes(data=dados, mime_type=mime))

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.1,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    erro = None
    for modelo in [MODELO_VERIFICACAO, *MODELOS_RESERVA]:
        for tentativa in range(TENTATIVAS):
            try:
                resposta = cliente.models.generate_content(model=modelo, contents=partes, config=config)
                conteudo = (resposta.text or "").strip()
                return {int(item["n"]): item for item in json.loads(conteudo).get("cenas", [])}
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                erro = e
                time.sleep(2)
            except Exception as e:
                erro = e
                texto_erro = str(e).lower()
                if "503" in texto_erro or "unavailable" in texto_erro or "404" in texto_erro or "not_found" in texto_erro:
                    break  # esse modelo não está disponível agora, pula pro próximo
                time.sleep(4 * (tentativa + 1))
    raise RuntimeError(f"Gemini falhou em todos os modelos: {erro}")


def verificar_conteudo(projeto, log=print, apenas=None) -> list[dict]:
    """Devolve avisos {cena, tipo, detalhe, prompt_sugerido} pras cenas cuja imagem/vídeo não
    bate com a narração, segundo o Gemini. Não modifica nada."""
    if not projeto.existe("cenas.json"):
        return []
    cenas = projeto.ler_json("cenas.json").get("cenas", [])
    if apenas is not None:
        cenas = [c for c in cenas if c["n"] in apenas]

    candidatos = []
    for c in cenas:
        dados, mime = _imagem_da_cena(projeto, c)
        if dados and (c.get("texto") or "").strip():
            candidatos.append((c["n"], c["texto"], dados, mime))

    if not candidatos:
        return []

    log(f"  analisando o conteúdo de {len(candidatos)} cena(s) com o Gemini (isso tem custo, é uma chamada de IA com imagem)...")
    cliente = _cliente()
    lotes = [candidatos[i:i + CENAS_POR_LOTE] for i in range(0, len(candidatos), CENAS_POR_LOTE)]

    avisos = []
    with ThreadPoolExecutor(PARALELISMO) as executor:
        futuros = {executor.submit(_pedir_avaliacao, cliente, lote): lote for lote in lotes}
        concluidos = 0
        for futuro in as_completed(futuros):
            concluidos += 1
            try:
                resultado = futuro.result()
            except Exception as e:
                log(f"  um lote de verificação falhou: {e}")
                continue
            for n, item in resultado.items():
                if not item.get("compativel", True):
                    avisos.append({
                        "cena": n, "tipo": "conteudo_incompativel",
                        "detalhe": item.get("motivo") or "a imagem não bate com a narração, segundo o Gemini.",
                        "prompt_sugerido": item.get("prompt_sugerido"),
                    })
            if concluidos % 5 == 0 or concluidos == len(lotes):
                log(f"  verificação de conteúdo: {concluidos}/{len(lotes)} lote(s)")
    return avisos


def sugerir_prompts(projeto, cenas_alvo: list[dict], log=print) -> dict[int, str]:
    """Escreve um prompt de imagem novo pra cada cena, só a partir da narração dela — sem
    olhar nenhuma imagem, porque o problema já é sabido (prompt duplicado de outra cena).
    Usa o Gemini através da chave GEMINI_API_KEY."""
    if not cenas_alvo:
        return {}
    tamanho = 25
    lotes = [cenas_alvo[i:i + tamanho] for i in range(0, len(cenas_alvo), tamanho)]

    def processar(lote):
        pedido = "\n".join(f"Cena {c['n']} | tipo ia | prompt atual: {c.get('prompt', '')}" for c in lote)
        erro = None
        for tentativa in range(2):
            try:
                cliente = _cliente()
                from google.genai import types
                prompt_sistema = (
                    f"{INSTRUCOES_REFINO}\n\n"
                    f"IMPORTANTE: Você deve responder ESTRITAMENTE em formato JSON compatível com o seguinte esquema JSON:\n"
                    f"{json.dumps(ESQUEMA_REFINO, ensure_ascii=False)}"
                )
                config_gen = types.GenerateContentConfig(
                    system_instruction=prompt_sistema,
                    response_mime_type="application/json",
                    temperature=0.2,
                )
                resposta = cliente.models.generate_content(
                    model=MODELO_VERIFICACAO,
                    contents=[types.Part.from_text(text=pedido)],
                    config=config_gen,
                )
                dados = json.loads(resposta.text or "{}")
                itens = {item["n"]: item["prompt"].strip() for item in dados.get("cenas", []) if item.get("prompt")}
                if itens:
                    return itens
                erro = "a resposta veio sem nenhum prompt aproveitável"
            except Exception as e:
                erro = e
            time.sleep(3)
        numeros = ", ".join(str(c["n"]) for c in lote)
        log(f"  não consegui escrever prompt novo pras cenas {numeros}, mesmo tentando de novo: {erro}")
        return {}

    resultado = {}
    with ThreadPoolExecutor(PARALELISMO) as executor:
        for parcial in executor.map(processar, lotes):
            resultado.update(parcial)
    return resultado
