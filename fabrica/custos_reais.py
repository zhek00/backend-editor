"""Registro do gasto real, em dinheiro de verdade, conforme cada chamada paga acontece.

Diferente de custos.py (que estima ANTES de gastar, por cima da duração do roteiro),
aqui só entra o que já foi cobrado de fato: caracteres realmente narrados, imagens
realmente geradas, segundos de efeito realmente sintetizados. Cada entrada guarda o
motivo em texto simples, pra dar pra conferir depois de onde veio cada centavo.

Um bloco de narração ou uma cena que já estava em cache e não chamou a API de novo
não é registrado aqui — só o que gerou cobrança nova.

O gasto dos modelos de texto (Groq, OpenRouter, Jev, Gemini) não passa por aqui: cada
um já grava o próprio uso_*.json com os tokens de cada chamada. O resumo junta os dois.
"""
import json
import threading
from datetime import datetime
from typing import Optional

_trava = threading.Lock()

# categoria -> (rótulo, nome da unidade medida)
CATEGORIAS = {
    "narracao": ("Narração", "caracteres"),
    "efeito": ("Efeitos sonoros", "segundos"),
    "imagem": ("Imagens de IA", "imagens"),
    "cenas": ("Divisão de cenas", "tokens"),
    "escolha": ("Escolha do acervo", "tokens"),
    "conferencia": ("Conferência das cenas", "tokens"),
    "texto": ("Modelos de texto", "tokens"),
}


def preco_por_caractere(config) -> tuple:
    """Quanto custa um caractere de narração e de onde esse preço vem.

    Com assinatura, o caractere vale o que a mensalidade cobra por ele (preço do plano dividido
    pela franquia do mês). Sem assinatura, vale a tarifa avulsa da API.
    """
    plano = plano_da_voz(config)
    mensal, incluido = plano.get("preco_mensal", 0) or 0, plano.get("incluido_no_mes", 0) or 0
    if mensal > 0 and incluido > 0:
        return mensal / incluido, f"pacote {plano.get('plano', 'GenAIPro')}"
    return preco_avulso_por_mil(config) / 1000, "tarifa avulsa da API"


def plano_da_voz(config) -> dict:
    """O pacote de créditos da GenAIPro. Config antiga só tinha a assinatura da ElevenLabs."""
    assinaturas = config.get("assinaturas") or {}
    return assinaturas.get("genaipro") or assinaturas.get("elevenlabs") or {}


def preco_avulso_por_mil(config) -> float:
    precos = config.get("precos") or {}
    return precos.get("genaipro_por_mil_caracteres", precos.get("elevenlabs_por_mil_caracteres", 0.022))


def registrar(projeto, categoria: str, motivo: str, valor_usd: float, detalhes: Optional[dict] = None,
              unidades: float = 0) -> None:
    """categoria: 'narracao', 'efeito' ou 'imagem'. unidades é o que foi medido (caracteres, segundos, imagens)."""
    if (not valor_usd or valor_usd <= 0) and not unidades:
        return
    linha = {
        "quando": datetime.now().isoformat(timespec="seconds"),
        "categoria": categoria,
        "motivo": motivo,
        "valor_usd": round(valor_usd or 0, 6),
        "unidades": round(unidades, 3),
        "detalhes": detalhes or {},
    }
    with _trava:
        arquivo = projeto.caminho("custos_reais.json")
        historico = json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
        historico.append(linha)
        arquivo.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")


def historico(projeto) -> list:
    arquivo = projeto.pasta / "custos_reais.json"
    if not arquivo.exists():
        return []
    return json.loads(arquivo.read_text(encoding="utf-8"))


def _uso_dos_modelos(projeto) -> list:
    """Uma linha por provedor de texto, lida do uso_*.json que cada um grava.

    O OpenRouter e o Jev informam o custo real de cada chamada. O Groq é do plano gratuito, então
    conta zero. O Gemini cobra por token, e o preço sai do config.
    """
    precos = projeto.config.get("precos") or {}
    linhas = []
    for arquivo, nome in (("uso_groq.json", "Groq"), ("uso_openrouter.json", "OpenRouter"),
                          ("uso_jev.json", "Jev"), ("uso_gemini.json", "Gemini")):
        caminho = projeto.pasta / arquivo
        if not caminho.exists():
            continue
        try:
            chamadas = json.loads(caminho.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not chamadas:
            continue
        lidos = sum(c.get("tokens_lidos", 0) for c in chamadas)
        escritos = sum(c.get("tokens_escritos", 0) + c.get("tokens_pensamento", 0) for c in chamadas)
        if nome == "Gemini":
            custo = (lidos * precos.get("gemini_entrada_por_milhao", 0.75)
                     + escritos * precos.get("gemini_saida_por_milhao", 3.75)) / 1e6
        else:
            custo = sum(c.get("custo_usd", 0) or 0 for c in chamadas)
        por_etapa: dict = {}
        for c in chamadas:
            etapa = c.get("etapa", "?")
            por_etapa[etapa] = por_etapa.get(etapa, 0) + 1
        linhas.append({
            "provedor": nome,
            "gratuito": nome == "Groq",
            "chamadas": len(chamadas),
            "tokens_lidos": lidos,
            "tokens_escritos": escritos,
            "custo_usd": round(custo, 6),
            "etapas": por_etapa,
            "quando": max((c.get("quando", "") for c in chamadas), default=""),
        })
    return linhas


def resumo(projeto) -> dict:
    """Tudo o que este vídeo custou: o que foi cobrado por chamada mais o que os modelos de texto gastaram."""
    itens = historico(projeto)
    modelos = _uso_dos_modelos(projeto)

    por_categoria: dict = {}
    medidas: dict = {}
    for h in itens:
        por_categoria[h["categoria"]] = por_categoria.get(h["categoria"], 0.0) + h["valor_usd"]
        if h.get("unidades"):
            medidas[h["categoria"]] = medidas.get(h["categoria"], 0.0) + h["unidades"]
    custo_texto = sum(m["custo_usd"] for m in modelos)
    if modelos:
        por_categoria["texto"] = por_categoria.get("texto", 0.0) + custo_texto
        medidas["texto"] = sum(m["tokens_lidos"] + m["tokens_escritos"] for m in modelos)

    total = sum(por_categoria.values())
    duracao = 0.0
    if projeto.existe("alinhamento.json"):
        duracao = projeto.ler_json("alinhamento.json").get("duracao", 0) or 0
    minutos = duracao / 60
    cenas = len(projeto.ler_json("cenas.json").get("cenas", [])) if projeto.existe("cenas.json") else 0

    por_unidade, origem_narracao = preco_por_caractere(projeto.config)
    plano = plano_da_voz(projeto.config)
    caracteres = medidas.get("narracao", 0)
    return {
        "total_usd": round(total, 4),
        "por_minuto_usd": round(total / minutos, 4) if minutos else 0,
        "por_cena_usd": round(total / cenas, 4) if cenas else 0,
        "duracao_segundos": round(duracao, 1),
        "cenas": cenas,
        "por_categoria": {k: round(v, 4) for k, v in por_categoria.items()},
        "medidas": {k: round(v, 2) for k, v in medidas.items()},
        "rotulos": {k: v[0] for k, v in CATEGORIAS.items()},
        "unidades": {k: v[1] for k, v in CATEGORIAS.items()},
        "modelos_de_texto": sorted(modelos, key=lambda m: -m["custo_usd"]),
        "narracao": {
            "caracteres": round(caracteres),
            "origem_do_preco": origem_narracao,
            "preco_por_mil": round(por_unidade * 1000, 4),
            "plano": plano.get("plano", ""),
            "preco_mensal": plano.get("preco_mensal", 0),
            "incluido_no_mes": plano.get("incluido_no_mes", 0),
            "fatia_da_franquia": (round(caracteres / plano["incluido_no_mes"] * 100, 1)
                                  if plano.get("incluido_no_mes") else 0),
            "videos_por_mes": (int(plano["incluido_no_mes"] // caracteres)
                               if plano.get("incluido_no_mes") and caracteres else 0),
        },
        "itens": sorted(itens, key=lambda h: h["quando"], reverse=True),
    }
