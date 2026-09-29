"""Bancos de imagens além do Pexels, do Pixabay e do Wikimedia.

Cada função recebe o Buscador (que traz o cliente HTTP, o tratamento de erros e as regras de licença), o tipo
("foto") e a busca, e devolve candidatos no mesmo formato das fontes de sempre:
fonte, id, tipo, miniatura, arquivo, duracao, pagina, autor, licenca e descricao.

A descricao é o que o próprio banco sabe sobre a imagem (espécie, título, legenda). Ela entra no filtro de
assunto e é lida pelo Jev na conferência, então quanto mais ela disser, melhor.

Só fotos: estes bancos não têm vídeo que sirva. Quem precisa de chave lê o nome dela do .env e se desliga
sozinho, com um aviso, quando ela não existe.
"""
import os
import re
from urllib.parse import quote


def _limpar(texto, tamanho=300):
    texto = re.sub(r"<[^>]+>", " ", str(texto or ""))
    return re.sub(r"\s+", " ", texto).strip()[:tamanho]


def _chave(*nomes):
    """A chave do banco, sem ligar para maiúsculas: UNSPLASH_ACCESS_KEY, Unsplash_api, UNSPLASH_API_KEY..."""
    procurados = {n.lower() for n in nomes}
    for nome, valor in os.environ.items():
        if nome.lower() in procurados and valor.strip():
            return valor.strip()
    return ""


def _licenca_livre(b, codigo):
    """Aceita CC0 e domínio público sempre. CC BY e CC BY-SA dependem do perfil. NC e ND nunca."""
    codigo = (codigo or "").lower().strip()
    if not codigo or "-nc" in codigo or "-nd" in codigo:
        return False
    if codigo in ("cc0", "pd", "pdm", "publicdomain") or codigo.startswith(("pd", "cc0")):
        return True
    if codigo.startswith("cc-by-sa"):
        return bool(b.cfg.get("aceitar_cc_by_sa", False))
    if codigo.startswith("cc-by"):
        return bool(b.cfg.get("aceitar_cc_by", True))
    return False


def _tamanho_si(url, maximo):
    return f"{url}&max={maximo}" if "deliveryService" in url and "max=" not in url else url


def inaturalist(b, tipo, busca):
    """Fotos de observações de campo, com o nome da espécie. O melhor banco para bicho e planta."""
    if tipo != "foto":
        return []
    r = b.http.get("https://api.inaturalist.org/v1/observations", params={
        "q": busca, "photos": "true", "quality_grade": "research", "license": "cc0,cc-by,cc-by-sa",
        "order_by": "votes", "per_page": 20, "locale": "en"})
    b._checar(r, "iNaturalist")
    achados = []
    for obs in r.json().get("results", []):
        foto = next((f for f in obs.get("photos") or [] if _licenca_livre(b, f.get("license_code"))), None)
        if not foto or not foto.get("url"):
            continue
        taxon = obs.get("taxon") or {}
        nome = taxon.get("preferred_common_name") or taxon.get("name") or ""
        cientifico = taxon.get("name") or ""
        legenda = nome + (f" ({cientifico})" if cientifico and cientifico != nome else "")
        lugar = obs.get("place_guess") or ""
        codigo = (foto.get("license_code") or "").lower()
        achados.append({
            "fonte": "inaturalist", "id": str(foto.get("id") or obs["id"]), "tipo": "foto",
            "miniatura": foto["url"].replace("/square.", "/medium."),
            "arquivo": foto["url"].replace("/square.", "/large."),
            "duracao": None, "pagina": obs.get("uri") or f"https://www.inaturalist.org/observations/{obs['id']}",
            "autor": _limpar((foto.get("attribution") or (obs.get("user") or {}).get("login") or ""), 120),
            "licenca": {"cc0": "CC0", "cc-by": "CC BY", "cc-by-sa": "CC BY-SA"}.get(codigo, codigo.upper()),
            "descricao": _limpar(f"{legenda}. {lugar}"),
        })
    return achados


def nasa(b, tipo, busca):
    """Espaço, Terra vista de cima, foguetes, astronautas. Domínio público."""
    if tipo != "foto":
        return []
    r = b.http.get("https://images-api.nasa.gov/search", params={"q": busca, "media_type": "image", "page_size": 20})
    b._checar(r, "NASA")
    achados = []
    for item in (r.json().get("collection") or {}).get("items", []):
        dados = (item.get("data") or [{}])[0]
        nasa_id = dados.get("nasa_id")
        miniatura = next((l.get("href") for l in item.get("links") or [] if l.get("render") == "image"), None)
        if not nasa_id or not miniatura:
            continue
        seguro = quote(nasa_id)
        achados.append({
            "fonte": "nasa", "id": nasa_id, "tipo": "foto", "miniatura": miniatura,
            "arquivo": f"https://images-assets.nasa.gov/image/{seguro}/{seguro}~large.jpg",
            "duracao": None, "pagina": f"https://images.nasa.gov/details/{seguro}",
            "autor": _limpar(dados.get("photographer") or dados.get("secondary_creator") or dados.get("center") or "NASA", 120),
            "licenca": "Domínio público (NASA)",
            "descricao": _limpar(f"{dados.get('title', '')}. {dados.get('description', '')}"),
        })
    return achados


def unsplash(b, tipo, busca):
    """Fotografia de qualidade. O plano de demonstração libera só 50 buscas por hora."""
    from .midia import FonteIndisponivel, LimiteAtingido

    if tipo != "foto":
        return []
    chave = _chave("UNSPLASH_ACCESS_KEY", "UNSPLASH_API", "UNSPLASH_API_KEY")
    if not chave:
        raise FonteIndisponivel("falta UNSPLASH_ACCESS_KEY no .env")
    r = b.http.get("https://api.unsplash.com/search/photos", headers={"Authorization": f"Client-ID {chave}"},
                   params={"query": busca, "orientation": "landscape", "per_page": 15})
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise LimiteAtingido("Unsplash", 3600)  # o Unsplash responde 403 quando as 50 buscas da hora acabam
    b._checar(r, "Unsplash")
    achados = []
    for f in r.json().get("results", []):
        urls = f.get("urls") or {}
        if not urls.get("raw"):
            continue
        tags = " ".join(t.get("title", "") for t in (f.get("tags") or [])[:8])
        achados.append({
            "fonte": "unsplash", "id": f["id"], "tipo": "foto", "miniatura": urls.get("small") or urls["raw"],
            "arquivo": urls["raw"] + ("&" if "?" in urls["raw"] else "?") + "w=2560&q=85&fm=jpg",
            "duracao": None, "pagina": (f.get("links") or {}).get("html", ""),
            "autor": (f.get("user") or {}).get("name", ""), "licenca": "Licença Unsplash",
            "descricao": _limpar(f"{f.get('alt_description') or ''}. {f.get('description') or ''}. {tags}"),
            # o Unsplash exige avisar que a foto foi usada, e o download avisa
            "registrar_download": (f.get("links") or {}).get("download_location"),
        })
    return achados


def smithsonian(b, tipo, busca):
    """Acervo dos museus do Smithsonian, só o que é CC0. Precisa de uma chave grátis do api.data.gov."""
    from .midia import FonteIndisponivel

    if tipo != "foto":
        return []
    chave = _chave("SMITHSONIAN_API_KEY", "SMITHSONIAN_API")
    if not chave:
        raise FonteIndisponivel("falta SMITHSONIAN_API_KEY no .env (chave grátis em api.data.gov)")
    r = b.http.get("https://api.si.edu/openaccess/api/v1.0/search", params={
        "api_key": chave, "q": f'{busca} AND online_media_type:"Images"', "rows": 20})
    b._checar(r, "Smithsonian")
    achados = []
    for linha in (r.json().get("response") or {}).get("rows", []):
        conteudo = linha.get("content") or {}
        basico = (conteudo.get("descriptiveNonRepeating") or {})
        midias = (basico.get("online_media") or {}).get("media") or []
        midia = next((m for m in midias if m.get("type") == "Images" and m.get("content")
                      and (m.get("usage") or {}).get("access") == "CC0"), None)
        if not midia:
            continue
        titulo = (basico.get("title") or {}).get("content") or linha.get("title") or ""
        unidade = basico.get("data_source") or (basico.get("unit_code") or "")
        livre = (conteudo.get("freetext") or {})
        notas = " ".join(n.get("content", "") for n in (livre.get("notes") or [])[:2])
        achados.append({
            "fonte": "smithsonian", "id": str(linha.get("id") or midia["idsId"]), "tipo": "foto",
            # a entrega do Smithsonian devolve o original de 4000 pixels (2,5 MB) se ninguém pedir um tamanho
            "miniatura": _tamanho_si(midia.get("thumbnail") or midia["content"], 500),
            "arquivo": _tamanho_si(midia["content"], 2560),
            "duracao": None, "pagina": basico.get("record_link") or basico.get("guid") or "",
            "autor": _limpar(unidade, 120), "licenca": "CC0 (Smithsonian)",
            "descricao": _limpar(f"{titulo}. {notas}"),
        })
    return achados


def europeana(b, tipo, busca):
    """Museus, arquivos e bibliotecas da Europa. Só o que tem licença aberta. Precisa de chave grátis."""
    from .midia import FonteIndisponivel

    if tipo != "foto":
        return []
    chave = _chave("EUROPEANA_API_KEY", "EUROPEANA_API")
    if not chave:
        raise FonteIndisponivel("falta EUROPEANA_API_KEY no .env (chave grátis em pro.europeana.eu)")
    r = b.http.get("https://api.europeana.eu/record/v2/search.json", params={
        "wskey": chave, "query": busca, "media": "true", "thumbnail": "true", "reusability": "open",
        "qf": "TYPE:IMAGE", "rows": 20, "profile": "standard"})
    b._checar(r, "Europeana")
    achados = []
    for item in r.json().get("items", []):
        direto = (item.get("edmIsShownBy") or [None])[0]
        miniatura = (item.get("edmPreview") or [None])[0]
        direitos = ((item.get("rights") or [""])[0]).lower()
        if not direto or not miniatura or "/by-nc" in direitos or "/nd" in direitos or "/by-sa" in direitos and not b.cfg.get("aceitar_cc_by_sa", False):
            continue
        licenca = "Domínio público" if ("publicdomain" in direitos or "/zero" in direitos) else "CC BY" if "/by/" in direitos else "Licença aberta"
        achados.append({
            "fonte": "europeana", "id": item["id"].strip("/").replace("/", "_"), "tipo": "foto",
            "miniatura": miniatura, "arquivo": direto, "duracao": None,
            "pagina": item.get("guid") or f"https://www.europeana.eu/item{item['id']}",
            "autor": _limpar(", ".join((item.get("dcCreator") or [])[:2]) or (item.get("dataProvider") or [""])[0], 120),
            "licenca": licenca, "descricao": _limpar(" ".join((item.get("title") or [])[:1])
                                                       + ". " + " ".join((item.get("dcDescription") or [])[:1])),
        })
    return achados


def harvard(b, tipo, busca):
    """Museus de arte de Harvard. Só as obras cujas imagens têm uso liberado. Precisa de chave grátis."""
    from .midia import FonteIndisponivel

    if tipo != "foto":
        return []
    chave = _chave("HARVARD_API_KEY", "HARVARD_API")
    if not chave:
        raise FonteIndisponivel("falta HARVARD_API_KEY no .env (chave grátis em harvardartmuseums.org/collections/api)")
    r = b.http.get("https://api.harvardartmuseums.org/object", params={
        "apikey": chave, "q": busca, "hasimage": 1, "size": 20, "sort": "rank", "sortorder": "desc",
        "fields": "id,title,people,primaryimageurl,url,imagepermissionlevel,dated,classification,description"})
    b._checar(r, "Harvard")
    achados = []
    for obra in r.json().get("records", []):
        imagem = obra.get("primaryimageurl")
        if not imagem or obra.get("imagepermissionlevel") not in (0, None):
            continue
        pessoas = ", ".join(p.get("name", "") for p in (obra.get("people") or [])[:2])
        achados.append({
            "fonte": "harvard", "id": str(obra["id"]), "tipo": "foto",
            "miniatura": imagem + "?height=400", "arquivo": imagem + "?height=1600",
            "duracao": None, "pagina": obra.get("url", ""), "autor": _limpar(pessoas or "Harvard Art Museums", 120),
            "licenca": "Harvard Art Museums (uso liberado)",
            "descricao": _limpar(f"{obra.get('title', '')}. {obra.get('classification', '')}. {obra.get('dated', '')}"
                                 f". {obra.get('description') or ''}"),
        })
    return achados


# o que cada banco tem de melhor, dito ao Passo 2 para ele escrever a busca certa para cada um
FORCAS = {
    "pexels": "fotos e vídeos modernos de banco de imagens, de gente, cidade, natureza e objetos do dia a dia",
    "pixabay": "fotos e vídeos de banco de imagens, muito material genérico e de objetos",
    "unsplash": "fotografia moderna de boa qualidade: lugares, gente, comida, objetos, natureza",
    "wikimedia": "fotos documentais e históricas, pessoas e lugares reais, mapas, obras de arte e ilustrações científicas",
    "inaturalist": "bichos e plantas fotografados no campo, indexados pelo nome comum e pelo científico (fire ant, Polistes dominula)",
    "nasa": "espaço, planetas, astronautas, foguetes, satélites e a Terra vista de cima",
    "smithsonian": "objetos de museu, ciência, história natural, tecnologia antiga (só o que é livre de direitos)",
    "europeana": "arquivo histórico europeu: fotos antigas, mapas, gravuras, manuscritos, arte",
    "harvard": "obras de arte de museu: pintura, gravura, escultura, sobretudo de séculos passados",
}


def descrever(fontes):
    """Texto para o prompt do Passo 2 com os bancos deste canal e o que cada um faz melhor."""
    linhas = [f"- {f}: {FORCAS[f]}" for f in fontes if f in FORCAS]
    return "\n".join(linhas)


# fonte -> função. NYPL, Biodiversity Heritage Library e Te Papa ainda não estão aqui.
FONTES = {"inaturalist": inaturalist, "nasa": nasa, "unsplash": unsplash, "smithsonian": smithsonian,
          "europeana": europeana, "harvard": harvard}
