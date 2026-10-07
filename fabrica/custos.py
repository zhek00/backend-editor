"""Estimativa de gasto antes de chamar as APIs pagas."""
from . import custos_reais, efeitos
from . import texto as tx
from .util import mmss

TIPOS_REAIS = ("foto_real", "video_real")
# o agente marca como IA o que não existe em foto (sem teto desde 2026-10-03)
PROPORCAO_IA_TIPICA = 0.15
# das cenas reais planejadas, a fatia que vem errada do banco e vai obrigatoriamente para a IA. Medido no
# virou-filme-em-1996 (Tsavo, 1898): 86 de 155 cenas mostravam outra coisa; num vídeo de animais é bem menos
FALHA_BUSCA_TIPICA = 0.3


def estimar(projeto) -> dict:
    precos = projeto.config.get("precos") or {}
    roteiro = tx.normalizar(projeto.roteiro())
    caracteres = len(roteiro)
    if projeto.existe("alinhamento.json"):
        duracao = projeto.ler_json("alinhamento.json")["duracao"]
    else:
        duracao = duracao_estimada(roteiro, projeto.perfil)
    from . import cenas as plano

    # o ritmo de corte e a proporção de acervo são do estilo da fábrica, iguais em qualquer perfil
    alvo = plano.ESTILO_ALVO_SEGUNDOS
    proporcao = 1.0 - PROPORCAO_IA_TIPICA if projeto.perfil.get("midia_real") else 0.0
    if projeto.existe("cenas.json"):
        lista = projeto.ler_json("cenas.json")["cenas"]
        cenas = len(lista)
        reais = sum(1 for c in lista if c.get("tipo") in TIPOS_REAIS and not c.get("sem_midia_real"))
    else:
        cenas = max(1, round(duracao / alvo))
        reais = round(cenas * proporcao)

    # o edge-tts é a voz gratuita da Microsoft: só a GenAIPro cobra por caractere, pelo preço do pacote
    # a Fish Audio pelo OpenRouter também é grátis (a transcrição do tempo das palavras custa uns centavos por vídeo)
    gratuita = (projeto.perfil.get("voz") or {}).get("provedor", "genaipro") in ("edge-tts", "fish", "computador")
    voz = 0.0 if gratuita else caracteres * custos_reais.preco_por_caractere(projeto.config)[0]
    # sem as cenas prontas, conta um efeito de 3 segundos por minuto de vídeo, antes do reaproveitamento
    if not efeitos.ativo(projeto.perfil):
        segundos_efeito = 0.0
    elif projeto.existe("cenas.json"):
        segundos_efeito = efeitos.segundos_pendentes(projeto)
    else:
        segundos_efeito = duracao / 60 * 3
    som = segundos_efeito / 60 * precos.get("efeito_por_minuto", 0.12)
    # parte das cenas reais não acha material e cai para IA, e 10% das imagens vão para refações
    em_lote = em_lote_no_google(projeto)
    preco_imagem = preco_da_imagem(projeto)
    from .midia import ia_ativa

    # com a IA desligada nenhuma imagem é gerada; ligada, 10% das imagens são feitas de novo pela conferência
    imagens = (cenas - reais * (1 - FALHA_BUSCA_TIPICA)) * 1.1 * preco_imagem if ia_ativa(projeto) else 0.0
    if (projeto.perfil.get("avatar") or {}).get("somente_avatar"):
        cenas, reais, imagens = 0, 0, 0.0  # o personagem fala o vídeo inteiro

    # a conferência olha cada cena de material real uma vez, com um modelo de visão barato mais o Jev
    cfg_corr = projeto.config.get("corrigir") or {}
    correcao = reais * precos.get("correcao_por_cena", 0.0005) if cfg_corr.get("automatico", True) else 0.0

    via_api = (projeto.config.get("claude") or {}).get("via", "assinatura") == "api"
    claude = escolha = 0.0
    if via_api:
        por_lote = (projeto.config.get("claude") or {}).get("unidades_por_lote", 120)
        lotes = max(1, -(-len(tx.unidades(roteiro)) // por_lote))
        claude = (
            lotes * (caracteres / 3.5 + 2000) / 1e6 * precos.get("claude_entrada_por_milhao", 5.0)
            + cenas * 350 / 1e6 * precos.get("claude_saida_por_milhao", 25.0)
        )
        escolha = reais * precos.get("claude_escolha_por_cena", 0.02)
    # o agente de roteiro lê o roteiro inteiro e decide as cenas pelo MiMo, que cobra centavos de dólar
    from . import roteirista

    agente = roteirista.estimar(projeto, cenas)
    agente = 0.0 if projeto.existe("cenas.json") else agente["cenas"] + (0.0 if projeto.existe("roteiro_mapa.json") else agente["mapa"])
    from . import cliente

    pelo_cliente = cliente.ativo(projeto)
    if pelo_cliente:
        # projeto do MCP: o roteiro, a escolha das fotos e o julgamento saem da assinatura do Claude do cliente
        agente = correcao = claude = escolha = 0.0
    return {
        "pelo_cliente": pelo_cliente,
        "duracao": duracao,
        "cenas": cenas,
        "roteirista": agente,
        "reais": reais,
        "voz": voz,
        "claude": claude,
        "escolha": escolha,
        "imagens": imagens,
        "correcao": correcao,
        "efeitos": som,
        "em_lote": em_lote,
        "via_api": via_api,
        "total": voz + claude + escolha + imagens + som + correcao + agente,
    }


def preco_da_imagem(projeto) -> float:
    """Preço de uma imagem de IA, pelo provedor e pelo modo do projeto."""
    precos = projeto.config.get("precos") or {}
    if em_lote_no_google(projeto):
        return precos.get("imagem_lote", 0.034)
    provedor = ((projeto.perfil.get("imagens") or {}).get("provedor") or "google").lower()
    if provedor in ("kie", "kie.ai"):
        return precos.get("imagem_kie", 0.02)
    if provedor == "openrouter":
        img = projeto.perfil.get("imagens") or {}
        from .imagens import MODELO_OPENROUTER, PREFIXO_IMAGES_API, preco_images_api
        modelo = str(img.get("modelo") or "") if "/" in str(img.get("modelo") or "") else MODELO_OPENROUTER
        if modelo.startswith(PREFIXO_IMAGES_API):
            return preco_images_api(modelo, img.get("qualidade"))
        return precos.get("imagem_openrouter", 0.02)
    return precos.get("imagem", 0.08)


def em_lote_no_google(projeto) -> bool:
    """Imagens pelo modo lote do Google, metade do preço, quando o perfil ou o config pedem."""
    img = projeto.perfil.get("imagens") or {}
    if (img.get("provedor") or "google").lower() != "google":
        return False
    geral = projeto.config.get("imagens") or {}
    return bool(img.get("lote", geral.get("lote", False)))


def duracao_estimada(roteiro, perfil) -> float:
    """Segundos de narração previstos para o roteiro, pelo ritmo medido da voz do perfil."""
    por_minuto = (perfil.get("ritmo") or {}).get("caracteres_por_minuto")
    if por_minuto:
        return len(roteiro) / por_minuto * 60
    return len(roteiro.split()) / 150 * 60


def dinheiro(valor: float) -> str:
    # valores de fração de centavo (o agente de roteiro, o custo por minuto) não podem aparecer como zero
    casas = 4 if 0 < abs(valor) < 0.01 else 2
    return "US$ " + f"{valor:,.{casas}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def formatar(e: dict) -> str:
    linhas = [
        f"Estimativa para {mmss(e['duracao'])} de vídeo com cerca de {e['cenas']} cenas",
        f"  narração        {dinheiro(e['voz'])}",
    ]
    if e.get("pelo_cliente"):
        linhas.append("  decisões        pela assinatura do seu Claude (roteiro, fotos, julgamento), sem custo na fábrica")
    elif e["via_api"]:
        linhas.append(f"  cenas           {dinheiro(e['claude'])}")
        if e["reais"]:
            linhas.append(f"  material real   {dinheiro(e['escolha'])}  ({e['reais']} cenas, fotos e vídeos grátis)")
    else:
        linhas.append("  Claude          pela assinatura, sem custo extra")
    minutos = max(e["duracao"] / 60, 0.01)
    linhas += [
        f"  imagens de IA   {dinheiro(e['imagens'])}" + ("  (modo lote do Google)" if e.get("em_lote") else ""),
    ]
    if e.get("roteirista"):
        linhas.append(f"  agente roteiro  {dinheiro(e['roteirista'])}  (lê o roteiro e decide as cenas, pelo MiMo)")
    if e.get("correcao"):
        linhas.append(f"  conferir cenas  {dinheiro(e['correcao'])}  (o Jev checa se cada imagem bate com a narração)")
    if e.get("efeitos"):
        linhas.append(f"  efeitos         {dinheiro(e['efeitos'])}")
    linhas += [
        f"  total          {dinheiro(e['total'])}  ({dinheiro(e['total'] / minutos)} por minuto)",
    ]
    return "\n".join(linhas)
