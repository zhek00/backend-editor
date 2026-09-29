"""Verificação de integridade das cenas antes de renderizar.

Pega sinais de mídia que não veio de uma busca de verdade — ids inventados, o mesmo
arquivo reaproveitado em cenas de conteúdo diferente, arquivos que sumiram do disco —
antes que isso vá parar no vídeo final. Não modifica nada, só aponta os problemas.
"""
import re

FONTES_REAIS = ("pexels", "pixabay", "wikimedia")

# Palavras de estilo/câmera que aparecem em quase todo prompt e não dizem nada sobre o
# assunto da cena — ignoradas na hora de comparar o "tema" visual de cenas vizinhas.
PALAVRAS_ESTILO = {
    "a", "an", "the", "of", "in", "on", "at", "with", "and", "or", "for", "to", "is", "are",
    "shot", "scene", "closeup", "close", "up", "macro", "wide", "view", "angle", "frame",
    "photo", "photograph", "video", "footage", "documentary", "style", "lighting", "light",
    "background", "high", "quality", "detail", "detailed", "realistic", "real", "natural",
    "cinematic", "camera", "depth", "field", "shallow", "soft", "warm", "cute", "adorable",
    "playful", "cozy", "beautiful", "scene", "showing", "displaying", "featuring",
}

MINIMO_CENAS_NO_GRUPO = 3  # grupos menores que isso não têm base pra comparar com confiança


def _palavras_visuais(cena):
    texto = f"{cena.get('busca') or ''} {cena.get('prompt') or ''}".lower()
    return {p for p in re.findall(r"[a-z]+", texto) if len(p) > 3 and p not in PALAVRAS_ESTILO}


def _grupos_por_rotulo(cenas):
    """Agrupa cenas usando os marcadores de rótulo (nome do animal/tópico) do texto na tela,
    quando o perfil usa esse recurso — cada grupo vai de um rótulo até o próximo. O trecho
    antes do primeiro rótulo (abertura/gancho) também vira um grupo, se tiver cenas suficientes."""
    marcos = sorted(c["n"] for c in cenas if (c.get("texto_tela") or {}).get("tipo") == "rotulo")
    if len(marcos) < 2:
        return []
    grupos = []
    primeiro = cenas[0]["n"] if cenas else marcos[0]
    if marcos[0] - primeiro >= MINIMO_CENAS_NO_GRUPO:
        grupos.append((primeiro, marcos[0] - 1))
    for i, inicio in enumerate(marcos):
        fim = marcos[i + 1] - 1 if i + 1 < len(marcos) else cenas[-1]["n"]
        grupos.append((inicio, fim))
    return grupos


def verificar_contexto_visual(projeto) -> list[dict]:
    """Acha cenas cujo termo de busca/prompt não tem nenhuma palavra em comum com as cenas
    ao redor — sinal de que o texto de busca ficou associado à cena errada (o mesmo tipo de
    corrupção que gerava mídia duplicada, só que no texto em vez do arquivo). É uma checagem
    por aproximação: às vezes uma cena legitimamente diferente das vizinhas será apontada à
    toa, vale conferir antes de mudar algo."""
    if not projeto.existe("cenas.json"):
        return []
    cenas = projeto.ler_json("cenas.json").get("cenas", [])
    if len(cenas) < MINIMO_CENAS_NO_GRUPO * 2:
        return []

    por_n = {c["n"]: c for c in cenas}
    grupos = _grupos_por_rotulo(cenas)

    if grupos:
        janelas = [[por_n[n] for n in range(ini, fim + 1) if n in por_n] for ini, fim in grupos]
    else:
        # sem rótulos no perfil: usa uma janela deslizante de vizinhos mais próximos
        ordenadas = sorted(cenas, key=lambda c: c["n"])
        raio = 4
        janelas = [
            ordenadas[max(0, i - raio):min(len(ordenadas), i + raio + 1)]
            for i in range(len(ordenadas))
        ]

    avisos = []
    vistas = set()
    for janela in janelas:
        if len(janela) < MINIMO_CENAS_NO_GRUPO:
            continue
        palavras_por_cena = {c["n"]: _palavras_visuais(c) for c in janela}
        for c in janela:
            if c["n"] in vistas:
                continue
            palavras = palavras_por_cena[c["n"]]
            if not palavras:
                continue
            bate_com_alguma = any(
                palavras & palavras_por_cena[outro["n"]]
                for outro in janela if outro["n"] != c["n"]
            )
            if not bate_com_alguma:
                vistas.add(c["n"])
                termo = c.get("busca") or c.get("prompt") or ""
                avisos.append({
                    "cena": c["n"], "tipo": "busca_fora_de_contexto",
                    "detalhe": (f"o termo de busca/prompt ('{termo[:80]}') não tem nenhuma palavra em comum "
                                "com nenhuma cena por perto — pode ter ficado associado à cena errada."),
                })
    return avisos


def verificar_prompts_duplicados(projeto) -> list[dict]:
    """Acha cenas de IA cujo prompt é idêntico ao de outra cena que não é da mesma família de
    divisão por tempo (cenas.copiar_imagem_de) — sinal de que o planejamento reaproveitou a
    mesma descrição por preguiça em vez de escrever uma própria pra cada momento da narração.
    A primeira cena do grupo fica como está (é a referência); as outras entram na correção."""
    if not projeto.existe("cenas.json"):
        return []
    cenas = projeto.ler_json("cenas.json").get("cenas", [])
    grupos: dict[str, list[dict]] = {}
    for c in cenas:
        if c.get("tipo") != "ia" or c.get("copiar_imagem_de"):
            continue
        # prompt_manual é o que realmente gera a imagem quando presente (ver imagens.prompt_final)
        prompt = (c.get("prompt_manual") or c.get("prompt") or "").strip()
        if prompt:
            grupos.setdefault(prompt, []).append(c)

    avisos = []
    for prompt, membros in grupos.items():
        if len(membros) < 2:
            continue
        membros = sorted(membros, key=lambda c: c["n"])
        for c in membros[1:]:
            avisos.append({
                "cena": c["n"], "tipo": "prompt_duplicado",
                "detalhe": (f"o prompt desta cena é idêntico ao da cena {membros[0]['n']} — ficou genérico "
                            "demais no planejamento e precisa de uma descrição própria, baseada só na "
                            "narração desta cena."),
            })
    return avisos


def verificar(projeto) -> list[dict]:
    """Devolve uma lista de avisos: cada um tem 'cena', 'tipo' e 'detalhe'."""
    if not projeto.existe("cenas.json"):
        return []
    cenas = projeto.ler_json("cenas.json").get("cenas", [])
    avisos = []

    por_arquivo: dict[str, list[int]] = {}
    for c in cenas:
        m = c.get("midia")
        if not m:
            continue

        arquivo = m.get("arquivo")
        if arquivo:
            # normaliza a barra pra "\" e "/" apontando pro mesmo arquivo não escaparem da checagem
            por_arquivo.setdefault(arquivo.replace("\\", "/"), []).append(c["n"])

        fonte, id_bruto = m.get("fonte"), m.get("id")
        if fonte in FONTES_REAIS and id_bruto is not None and not str(id_bruto).isdigit():
            avisos.append({
                "cena": c["n"], "tipo": "id_suspeito",
                "detalhe": (f"a mídia diz vir de {fonte}, mas o id '{id_bruto}' não é um id real dessa fonte "
                            "(era pra ser só números) — parece ter sido inventado por algum script avulso."),
            })

        for campo in ("arquivo", "capa"):
            caminho = m.get(campo)
            if caminho and not (projeto.pasta / caminho).exists():
                avisos.append({
                    "cena": c["n"], "tipo": "arquivo_ausente",
                    "detalhe": f"aponta pro arquivo '{caminho}', que não existe mais em disco.",
                })

    for arquivo, numeros in por_arquivo.items():
        if len(numeros) <= 1:
            continue
        for n in numeros:
            outras = ", ".join(str(x) for x in numeros if x != n)
            avisos.append({
                "cena": n, "tipo": "duplicata",
                "detalhe": (f"o arquivo '{arquivo}' desta cena também está em uso nas cenas {outras} — "
                            "provavelmente foi reaproveitado por engano entre conteúdos diferentes."),
            })

    return avisos


def formatar(avisos: list[dict]) -> str:
    if not avisos:
        return "Nenhum problema de mídia encontrado."
    por_cena: dict[int, list[dict]] = {}
    for a in avisos:
        por_cena.setdefault(a["cena"], []).append(a)
    linhas = [f"{len(por_cena)} cena(s) com mídia suspeita, {len(avisos)} aviso(s) no total:"]
    for n in sorted(por_cena):
        for a in por_cena[n]:
            linhas.append(f"  cena {n}: {a['detalhe']}")
    return "\n".join(linhas)
