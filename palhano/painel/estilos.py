"""Estilos de edição, narradores e a tradução de um pedido do painel para o perfil e os ajustes da fábrica.

O estilo muda o visual da montagem (`visual` no perfil, fabrica/render.py: cor, granulado, faixas de cinema), o
tema das cenas animadas (animation_ai.tema) e o jeito das imagens de IA. As regras fixas da fábrica (cenas de 3 a
5 s, proporção de material real, conferência do Jev) valem para todos."""

ESTILOS = {
    "documentario": {"nome": "Documentário", "resumo": "Limpo e direto, a história em primeiro plano.", "tema": "apple",
                     "imagem": "Cinematic still, photorealistic, natural light, one clear focal subject, documentary look."},
    "investigacao": {"nome": "Investigação", "resumo": "Cor lavada, granulado e clima de mistério.", "tema": "misterio",
                     "imagem": "Moody investigative still, low key lighting, archival textures, muted colors, film grain."},
    "noticiario": {"nome": "Noticiário", "resumo": "Neutro, com cara de jornal e dados na tela.", "tema": "editorial",
                   "imagem": "Editorial news photograph, crisp, neutral color, realistic, magazine quality."},
    "energia": {"nome": "Energia", "resumo": "Cor forte e ritmo acelerado.", "tema": "noite",
                "imagem": "Bold high-contrast photograph, vivid colors, dynamic angle, punchy lighting."},
    "cinema": {"nome": "Cinema", "resumo": "Faixas pretas de filme e luz dramática.", "tema": "noite",
               "imagem": "Anamorphic film still, dramatic lighting, strong contrast, shallow depth of field."},
}

NARRADORES = {
    "genaipro": "GenAI Pro (realista, pago por caractere)",
    "fish": "Fish Audio (grátis pelo OpenRouter)",
    "computador": "Voz do computador (teste)",
}

PADRAO = {
    "estilo": "documentario",
    "narrador": "fish",
    "voice_id": "",
    "velocidade": 1.0,
    "ia": True,
    "trilha": True,
    "legenda": True,
    "vertical": False,
    "teste": False,
    "destino": "",
}

CAMPOS = tuple(PADRAO)


def misturar(canal: dict | None, pedido: dict) -> dict:
    """Vídeo por cima do canal, canal por cima do padrão. Campo vazio no canal não apaga o padrão."""
    final = dict(PADRAO)
    if canal:
        guardado = canal.get("ajustes") or {}
        for k in CAMPOS:
            if guardado.get(k) not in (None, ""):
                final[k] = guardado[k]
        for k in ("narrador", "voice_id", "estilo"):
            if canal.get(k):
                final[k] = canal[k]
        if canal.get("velocidade"):
            final["velocidade"] = canal["velocidade"]
    for k in CAMPOS:
        if k in pedido and pedido[k] not in (None, ""):
            final[k] = pedido[k]
    if final["estilo"] not in ESTILOS:
        final["estilo"] = PADRAO["estilo"]
    if final["narrador"] not in NARRADORES:
        final["narrador"] = PADRAO["narrador"]
    try:
        final["velocidade"] = min(1.2, max(0.7, float(final["velocidade"])))
    except (TypeError, ValueError):
        final["velocidade"] = 1.0
    for k in ("ia", "trilha", "legenda", "vertical", "teste"):
        final[k] = bool(final[k])
    final["diretrizes"] = (canal or {}).get("diretrizes", "")
    final["descricao_fixa"] = (canal or {}).get("descricao_fixa", "")
    return final


def para_fabrica(ajustes: dict, canal: dict | None) -> dict:
    """O perfil (sem a base, que a máquina completa com o caminho dela) e o config_override do projeto."""
    estilo = ESTILOS[ajustes["estilo"]]
    voz = {"provedor": ajustes["narrador"], "velocidade": ajustes["velocidade"]}
    if ajustes.get("voice_id"):
        voz["voice_id"] = ajustes["voice_id"]
    perfil = {
        "nome": (canal or {}).get("nome") or "Robô PALHANO",
        "voz": voz,
        "imagens": {"estilo": estilo["imagem"]},
        "legenda_na_tela": ajustes["legenda"],
        "visual": ajustes["estilo"],
    }
    if ajustes.get("diretrizes"):
        perfil["diretrizes"] = ajustes["diretrizes"]
    if ajustes.get("descricao_fixa"):
        perfil["publicacao"] = {"texto_fixo": ajustes["descricao_fixa"]}
    config_override = {
        "ia": {"ativa": ajustes["ia"]},
        "trilha": {"ativo": ajustes["trilha"]},
        "animation_ai": {"tema": estilo["tema"]},
        # a entrega no computador vai para a pasta escolhida no painel (vazio: Downloads)
        "entrega_pc": {"ativo": True, "pasta": ajustes.get("destino") or ""},
    }
    return {"perfil": perfil, "config_override": config_override}


def minutos_estimados(roteiro: str) -> float:
    # cerca de 900 caracteres por minuto de narração em ritmo normal
    return round(len(" ".join(roteiro.split())) / 900, 1)
