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
    "narracao": ("Narração", "créditos"),
    "efeito": ("Efeitos sonoros", "segundos"),
    "imagem": ("Imagens de IA", "imagens"),
    "cenas": ("Divisão de cenas", "tokens"),
    "escolha": ("Escolha do acervo", "tokens"),
    "conferencia": ("Conferência das cenas", "tokens"),
    "texto": ("Modelos de texto", "tokens"),
    "visao": ("Análise das imagens", "tokens"),
    "juiz": ("Jev (juiz)", "tokens"),
}

# tarefa dos modelos de linguagem -> (categoria, nome para a pessoa, começos do campo etapa do uso_*.json). O Custos
# mostrava uma linha por provedor ("OpenRouter: 2.076 chamadas, US$ 3,00") e a pessoa não via que US$ 2,59 eram a
# escolha das fotos (nunca-deve-ter-dentro-de-casa-parte-2, pedido do usuário em 2026-10-06)
TAREFAS = [
    ("visao", "Escolha das fotos do acervo", ("escolha de material real",)),
    ("visao", "Descrição das imagens", ("descrever imagens",)),
    ("visao", "Revisão do vídeo pronto", ("revisão do vídeo",)),
    ("juiz", "Jev: julgamento das imagens e do motion", ("julgar mídia", "motion IA: vale a pena")),
    ("texto", "Roteiro e divisão em cenas", ("roteirista:", "cenas", "busca das cenas cortadas",
                                            "prompts de IA em sequência", "textos na tela")),
    ("texto", "Diretor do Corrigir Mídia", ("diretor",)),
    ("texto", "Buscas e traduções", ("buscas das reprovadas", "traduzir busca", "prompt recusado")),
    ("texto", "Animações e Motion IA", ("animação da cena", "motion IA: modelo")),
    ("texto", "Trilha", ("trilha",)),
]
_USOS = (("uso_groq.json", "Groq"), ("uso_openrouter.json", "OpenRouter"), ("uso_jev.json", "Jev"),
         ("uso_gemini.json", "Gemini"))


# Créditos da GenAIPro gastos por caractere narrado. NÃO é 1 crédito por caractere: o saldo mostrou 676 créditos
# para os 10.543 caracteres do zz_teste_animacoes (eleven_turbo_v2_5), uns 0,064 por caractere. Antes a fábrica
# contava 1 por caractere e o Custos mostrava uns 15 vezes o gasto real. Cada narração mede o saldo antes e depois
# (narracao.narrar) e guarda a medida em genaipro_medido.json; a estimativa usa a média medida de cada modelo.
CREDITOS_POR_CARACTERE_PADRAO = 0.064
ARQUIVO_MEDIDAS = "genaipro_medido.json"


def _medidas() -> dict:
    from .config import RAIZ

    arquivo = RAIZ / ARQUIVO_MEDIDAS
    try:
        return json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else {}
    except (OSError, ValueError):
        return {}


def creditos_por_caractere(config, modelo: str = "") -> tuple:
    """Créditos gastos por caractere e de onde o número vem (medido no saldo ou o padrão do config)."""
    medida = (_medidas().get("modelos") or {}).get(modelo or "") or {}
    if medida.get("caracteres", 0) >= 2000 and medida.get("creditos", 0) > 0:
        return medida["creditos"] / medida["caracteres"], "medido no saldo da GenAIPro"
    padrao = (config.get("genaipro") or {}).get("creditos_por_caractere", CREDITOS_POR_CARACTERE_PADRAO)
    return float(padrao), "medida padrão"


def guardar_medida(modelo: str, caracteres: int, creditos: float) -> None:
    """Soma uma narração medida pelo saldo à média do modelo."""
    from .config import RAIZ

    with _trava:
        dados = _medidas()
        modelos = dados.setdefault("modelos", {})
        m = modelos.setdefault(modelo or "?", {"caracteres": 0, "creditos": 0, "narracoes": 0})
        m["caracteres"] += int(caracteres)
        m["creditos"] += float(creditos)
        m["narracoes"] += 1
        (RAIZ / ARQUIVO_MEDIDAS).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def preco_por_credito(config) -> tuple:
    """Quanto custa um crédito da GenAIPro e de onde esse preço vem (pacote: preço dividido pelos créditos)."""
    plano = plano_da_voz(config)
    mensal, incluido = plano.get("preco_mensal", 0) or 0, plano.get("incluido_no_mes", 0) or 0
    if mensal > 0 and incluido > 0:
        return mensal / incluido, f"pacote {plano.get('plano', 'GenAIPro')}"
    return preco_avulso_por_mil(config) / 1000, "tarifa avulsa da API"


def preco_por_caractere(config, modelo: str = "") -> tuple:
    """Quanto custa, de verdade, um caractere de narração: créditos por caractere vezes o preço do crédito."""
    por_credito, origem = preco_por_credito(config)
    creditos, _ = creditos_por_caractere(config, modelo)
    return por_credito * creditos, origem


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
    from . import consumo  # imagem e transcrição pelo OpenRouter entram no registro central (Kie e GenAIPro não)
    consumo.registrar_custo(projeto, categoria, detalhes, valor_usd)


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
    linhas = []
    for nome, chamadas in _chamadas(projeto):
        lidos = sum(c.get("tokens_lidos", 0) for c in chamadas)
        escritos = sum(c.get("tokens_escritos", 0) + c.get("tokens_pensamento", 0) for c in chamadas)
        custo = sum(_custo_da_chamada(projeto, nome, c) for c in chamadas)
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


def _chamadas(projeto):
    """(provedor, chamadas) de cada uso_*.json do projeto que tem alguma chamada."""
    for arquivo, nome in _USOS:
        caminho = projeto.pasta / arquivo
        if not caminho.exists():
            continue
        try:
            chamadas = json.loads(caminho.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if chamadas:
            yield nome, chamadas


def _custo_da_chamada(projeto, provedor, c) -> float:
    """O OpenRouter e o Jev informam o custo real; o Groq é gratuito; o Gemini sai dos preços do config."""
    if provedor == "Groq":
        return 0.0
    if provedor == "Gemini":
        precos = projeto.config.get("precos") or {}
        return (c.get("tokens_lidos", 0) * precos.get("gemini_entrada_por_milhao", 0.75)
                + (c.get("tokens_escritos", 0) + c.get("tokens_pensamento", 0))
                * precos.get("gemini_saida_por_milhao", 3.75)) / 1e6
    return float(c.get("custo_usd", 0) or 0)


def tarefa_da_etapa(etapa: str) -> tuple:
    """(categoria, tarefa) de uma etapa gravada no uso_*.json. "(tradução)" é da mesma tarefa."""
    base = (etapa or "").split(" (")[0].strip()
    for categoria, tarefa, comecos in TAREFAS:
        if any(base == c or base.startswith(c) for c in comecos):
            return categoria, tarefa
    return "texto", "Outros textos"


def uso_por_tarefa(projeto) -> list:
    """O que os modelos de linguagem fizeram neste vídeo, por tarefa: chamadas, quantas foram grátis, o custo e
    quais modelos responderam (com o custo de cada um)."""
    tarefas: dict = {}
    for provedor, chamadas in _chamadas(projeto):
        for c in chamadas:
            categoria, nome = tarefa_da_etapa(c.get("etapa", ""))
            t = tarefas.setdefault(nome, {"tarefa": nome, "categoria": categoria, "chamadas": 0, "gratis": 0,
                                          "custo_usd": 0.0, "tokens": 0, "modelos": {}})
            custo = _custo_da_chamada(projeto, provedor, c)
            t["chamadas"] += 1
            t["gratis"] += 1 if custo <= 0 else 0
            t["custo_usd"] += custo
            t["tokens"] += c.get("tokens_lidos", 0) + c.get("tokens_escritos", 0) + c.get("tokens_pensamento", 0)
            modelo = c.get("modelo") or provedor
            modelo = f"Groq {modelo}" if provedor == "Groq" else modelo
            m = t["modelos"].setdefault(modelo, {"modelo": modelo, "chamadas": 0, "custo_usd": 0.0})
            m["chamadas"] += 1
            m["custo_usd"] += custo
    saida = []
    for t in tarefas.values():
        modelos = sorted(t["modelos"].values(), key=lambda m: (-m["custo_usd"], -m["chamadas"]))
        saida.append({**t, "custo_usd": round(t["custo_usd"], 6),
                      "modelos": [{**m, "custo_usd": round(m["custo_usd"], 6)} for m in modelos]})
    return sorted(saida, key=lambda t: (-t["custo_usd"], -t["chamadas"]))


def _narracao_em_creditos(h: dict, config, por_credito: float) -> dict:
    """Registro de narração com o valor em créditos de verdade.

    Os registros antigos contavam 1 crédito por caractere (unidades = caracteres, sem "creditos" nos detalhes):
    são recalculados pelos créditos por caractere medidos, e ficam marcados como estimados."""
    detalhes = dict(h.get("detalhes") or {})
    if detalhes.get("provedor", "genaipro") != "genaipro" or "creditos" in detalhes:
        return h
    caracteres = detalhes.get("caracteres") or h.get("unidades") or 0
    taxa, _ = creditos_por_caractere(config, detalhes.get("modelo", ""))
    creditos = caracteres * taxa
    detalhes.update({"caracteres": caracteres, "creditos": round(creditos, 1), "estimado": True})
    return {**h, "valor_usd": round(creditos * por_credito, 6), "unidades": round(creditos, 1), "detalhes": detalhes,
            "motivo": h.get("motivo", "") + " (recalculado: a conta antiga usava 1 crédito por caractere)"}


def resumo(projeto) -> dict:
    """Tudo o que este vídeo custou: o que foi cobrado por chamada mais o que os modelos de texto gastaram."""
    itens = historico(projeto)
    modelos = _uso_dos_modelos(projeto)

    por_categoria: dict = {}
    medidas: dict = {}
    por_credito, _ = preco_por_credito(projeto.config)
    itens = [_narracao_em_creditos(h, projeto.config, por_credito) if h["categoria"] == "narracao" else h
             for h in itens]
    caracteres_narrados = sum((h.get("detalhes") or {}).get("caracteres", 0) for h in itens
                              if h["categoria"] == "narracao")
    for h in itens:
        por_categoria[h["categoria"]] = por_categoria.get(h["categoria"], 0.0) + h["valor_usd"]
        if h.get("unidades"):
            medidas[h["categoria"]] = medidas.get(h["categoria"], 0.0) + h["unidades"]
    # os modelos de linguagem em três cartões: texto (roteiro, buscas), análise das imagens e o Jev
    tarefas = uso_por_tarefa(projeto)
    for t in tarefas:
        por_categoria[t["categoria"]] = por_categoria.get(t["categoria"], 0.0) + t["custo_usd"]
        medidas[t["categoria"]] = medidas.get(t["categoria"], 0.0) + t["tokens"]

    total = sum(por_categoria.values())
    duracao = 0.0
    if projeto.existe("alinhamento.json"):
        duracao = projeto.ler_json("alinhamento.json").get("duracao", 0) or 0
    minutos = duracao / 60
    cenas = len(projeto.ler_json("cenas.json").get("cenas", [])) if projeto.existe("cenas.json") else 0

    por_unidade, origem_narracao = preco_por_caractere(projeto.config)
    plano = plano_da_voz(projeto.config)
    creditos = medidas.get("narracao", 0)
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
        "tarefas_dos_modelos": tarefas,
        "narracao": {
            "caracteres": round(caracteres_narrados),
            "creditos": round(creditos, 1),
            "origem_do_preco": origem_narracao,
            "preco_por_mil": round(por_unidade * 1000, 6),
            "preco_por_credito": por_credito,
            "plano": plano.get("plano", ""),
            "preco_mensal": plano.get("preco_mensal", 0),
            "incluido_no_mes": plano.get("incluido_no_mes", 0),
            "fatia_da_franquia": (round(creditos / plano["incluido_no_mes"] * 100, 3)
                                  if plano.get("incluido_no_mes") else 0),
            "videos_por_mes": (int(plano["incluido_no_mes"] // creditos)
                               if plano.get("incluido_no_mes") and creditos else 0),
        },
        "itens": sorted(itens, key=lambda h: h["quando"], reverse=True),
    }
