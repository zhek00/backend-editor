"""Kit de publicação do vídeo pronto: título, alternativas, descrição com capítulos nos tempos reais, tags, hashtags,
comentário fixado, os créditos e a legenda para subir junto.

Pedido do usuário em 2026-10-09, depois da análise do concorrente (Pipeline Canal Dark), que entrega isso em cada
vídeo. Antes a fábrica entregava só o `creditos.txt`, e o título e a descrição eram escritos à mão no editor.

- **Capítulos** (`capitulos`, grátis): pelos `[TITULO]` do roteiro quando há pelo menos 2; senão, pelos blocos do
  `roteiro_mapa.json` (o `inicio_c` de cada bloco vira tempo pelo `alinhamento.json`). Os tempos são do `final.mp4`:
  somam a abertura (`render/linha.json`). As regras do YouTube valem: o primeiro em 0:00, cada um com 10 s ou mais e
  pelo menos 3, senão a descrição sai sem capítulos.
- **Textos** (`_textos_do_modelo`, grátis pela cadeia de principais, Groq primeiro): o modelo lê o roteiro e escreve
  o título (até 60 letras), 2 alternativas, o resumo do topo da descrição, as tags, até 3 hashtags, o comentário
  fixado e um nome curto para cada capítulo, sem travessão. Só é pedido de novo se o roteiro ou os capítulos mudarem
  (`assinatura`) ou com `--forcar`. Sem modelo (offline, fora do ar), sai com o título do mapa e os nomes dos blocos.
- **Conteúdo sintético**: vídeo com imagem de IA sai marcado (`sintetico`), para declarar no YouTube Studio.

Fica em `publicacao.json` (o editor e a publicação no YouTube leem) e `PUBLICACAO.md` (para ler e copiar), na pasta
do projeto. A legenda de duas linhas é a `legendas_final.srt`, que o render já escreve com o tempo da abertura.
"""
import hashlib
import json
import re

TITULO_MAXIMO = 60
TAGS_MAXIMO = 480  # o YouTube aceita 500 letras somando as tags
DESCRICAO_MAXIMA = 4900
CAPITULO_MINIMO = 10.0


def _sem_travessao(texto):
    return re.sub(r"\s*[—–]\s*", ", ", texto).strip() if isinstance(texto, str) else texto


def mmss(segundos) -> str:
    s = int(segundos)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _atraso(projeto) -> float:
    if projeto.existe("render/linha.json"):
        return float(projeto.ler_json("render/linha.json").get("atraso") or 0)
    return 0.0


def _tempo_do_caractere(palavras, c):
    """Tempo da primeira palavra falada a partir da posição c do roteiro."""
    return next((p["ini"] for p in palavras if p["c"] >= c and p.get("ini") is not None), None)


def capitulos(projeto) -> list:
    """[{"inicio": segundos no final.mp4, "nome": nome provisório, "trecho": começo da fala}], já nas regras do
    YouTube, ou [] se não der 3 capítulos."""
    if not projeto.existe("alinhamento.json"):
        return []
    alin = projeto.ler_json("alinhamento.json")
    palavras = alin.get("palavras") or []
    roteiro = projeto.roteiro()
    brutos = [(m["ini"], m.get("texto") or "", m.get("c", 0)) for m in alin.get("marcadores") or []
              if m.get("tipo") == "titulo" and m.get("texto")]
    if len(brutos) < 2 and projeto.existe("roteiro_mapa.json"):
        brutos = []
        for b in projeto.ler_json("roteiro_mapa.json").get("blocos") or []:
            t = _tempo_do_caractere(palavras, int(b.get("inicio_c") or 0))
            if t is not None:
                brutos.append((t, b.get("nome") or "", int(b.get("inicio_c") or 0)))
    brutos.sort()
    atraso = _atraso(projeto)
    if brutos and brutos[0][0] + atraso >= CAPITULO_MINIMO:
        # fala antes do primeiro título: ela vira o capítulo de abertura, porque o primeiro precisa estar em 0:00
        brutos.insert(0, (0.0, "Abertura", 0))
    lista = []
    for t, nome, c in brutos:
        inicio = 0.0 if not lista else t + atraso
        if lista and inicio - lista[-1]["inicio"] < CAPITULO_MINIMO:
            continue  # o YouTube recusa capítulo com menos de 10 s: este fica junto com o anterior
        lista.append({"inicio": round(inicio, 2), "nome": nome.strip(), "trecho": roteiro[c:c + 220].strip()})
    duracao = float(alin.get("duracao") or 0) + atraso
    if lista and duracao - lista[-1]["inicio"] < CAPITULO_MINIMO:
        lista.pop()  # o último também precisa durar 10 s
    return lista if len(lista) >= 3 else []


def _tem_imagem_de_ia(projeto) -> bool:
    from . import midia

    if not projeto.existe("cenas.json"):
        return False
    return any(midia.precisa_ia(c) and projeto.imagem(c["n"]).exists()
               for c in projeto.ler_json("cenas.json").get("cenas") or [])


def _creditos(projeto) -> str:
    if not projeto.existe("creditos.txt"):
        return ""
    return (projeto.pasta / "creditos.txt").read_text(encoding="utf-8").strip()


ESQUEMA = {
    "type": "object",
    "properties": {
        "titulo": {"type": "string"},
        "titulos_alt": {"type": "array", "items": {"type": "string"}},
        "resumo": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "comentario_fixado": {"type": "string"},
        "capitulos": {"type": "array", "items": {"type": "string"}},
        "thumbs": {"type": "array", "items": {"type": "object", "properties": {
            "l1": {"type": "string"}, "l2": {"type": "string"}}, "required": ["l1", "l2"]}},
    },
    "required": ["titulo", "titulos_alt", "resumo", "tags", "hashtags", "comentario_fixado", "capitulos", "thumbs"],
    "additionalProperties": False,
}

INSTRUCOES = """Você prepara a publicação de um vídeo do YouTube a partir do roteiro narrado. Responda só em JSON.

- titulo: até 60 caracteres, a palavra-chave nos primeiros 40, no máximo uma palavra em CAIXA ALTA, sem prometer o
  que o vídeo não entrega, sem aspas.
- titulos_alt: 2 títulos diferentes, nas mesmas regras, para teste A/B.
- resumo: 2 ou 3 frases que abrem a descrição, com a palavra-chave, contando o que o vídeo mostra.
- tags: de 8 a 15 buscas que alguém digitaria para achar este vídeo, em minúsculas, do mais específico ao mais geral.
- hashtags: até 3, com #, sem espaço.
- comentario_fixado: uma pergunta curta ao espectador sobre o assunto do vídeo, para puxar conversa.
- capitulos: um nome curto (2 a 6 palavras) para cada capítulo, NA MESMA ORDEM e na MESMA QUANTIDADE da lista
  recebida, dizendo o assunto daquele trecho para quem vai assistir (nada de "Introdução" genérica no lugar do
  assunto). Se a lista vier vazia, devolva [].
- thumbs: 3 opções DIFERENTES de texto para a thumbnail, cada uma com l1 e l2 (de 1 a 4 palavras cada linha, as
  duas juntas até 6 palavras). Elas COMPLETAM o título, nunca o repetem: a curiosidade, o número forte ou o contraste
  do vídeo. Uma palavra de l2 entre *asteriscos* vira o destaque colorido. Nada que o vídeo não entrega.
Regras: português do Brasil, nunca use travessão (—), nunca use dados que o roteiro não diz."""


def assinatura(projeto, caps) -> str:
    base = json.dumps([projeto.roteiro(), [c["nome"] for c in caps]], ensure_ascii=False)
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def _textos_do_modelo(projeto, caps, log=print):
    from . import openrouter_local

    roteiro = projeto.roteiro()
    titulo_mapa = ""
    if projeto.existe("roteiro_mapa.json"):
        titulo_mapa = projeto.ler_json("roteiro_mapa.json").get("titulo") or ""
    lista = "\n".join(f"{i + 1}. ({mmss(c['inicio'])}) {c['nome']}: {c['trecho'][:160]}" for i, c in enumerate(caps))
    pedido = (f"TÍTULO DE TRABALHO: {titulo_mapa or '(nenhum)'}\n\nCAPÍTULOS ({len(caps)}):\n{lista or '(nenhum)'}\n\n"
              f"ROTEIRO NARRADO:\n{roteiro[:24000]}")
    # pela cadeia de principais, os gratuitos primeiro: sem o modelo, a chamada ia para o openrouter.modelo (o Jev),
    # que mandou para o DeepSeek pago sem perguntar
    return openrouter_local.perguntar(projeto, "publicacao", INSTRUCOES, pedido, ESQUEMA, log=log,
                                      modelo=openrouter_local.principal(projeto))


def _limpar(dados, caps, titulo_reserva):
    titulo = _sem_travessao(str(dados.get("titulo") or titulo_reserva or "")).strip().strip('"')
    if len(titulo) > 100:
        titulo = titulo[:97].rsplit(" ", 1)[0] + "..."
    alt = [_sem_travessao(str(t)).strip().strip('"') for t in (dados.get("titulos_alt") or []) if str(t).strip()][:2]
    tags, total = [], 0
    for t in dados.get("tags") or []:
        t = re.sub(r"[<>,#]", "", str(t)).strip().lower()
        if t and t not in tags and total + len(t) + 1 < TAGS_MAXIMO:
            tags.append(t)
            total += len(t) + 1
    hashtags = []
    for h in dados.get("hashtags") or []:
        h = "#" + re.sub(r"[^\w]", "", str(h))
        if len(h) > 1 and h.lower() not in (x.lower() for x in hashtags):
            hashtags.append(h)
    thumbs = []
    for t in dados.get("thumbs") or []:
        if not isinstance(t, dict):
            continue
        l1, l2 = (_sem_travessao(str(t.get(k) or "")).strip().strip('"') for k in ("l1", "l2"))
        if (l1 or l2) and len((l1 + " " + l2).split()) <= 8:
            thumbs.append({"l1": l1, "l2": l2})
    nomes = [_sem_travessao(str(n)).strip() for n in (dados.get("capitulos") or [])]
    if len(nomes) != len(caps):
        nomes = [c["nome"] for c in caps]  # o modelo errou a quantidade: ficam os nomes dos blocos
    return {"titulo": titulo, "titulos_alt": alt, "resumo": _sem_travessao(str(dados.get("resumo") or "")),
            "tags": tags, "hashtags": hashtags[:3],
            "comentario_fixado": _sem_travessao(str(dados.get("comentario_fixado") or "")),
            "nomes_capitulos": nomes, "thumbs": thumbs[:3]}


def descricao(textos, caps, creditos, aviso_voz=True) -> str:
    partes = [textos.get("resumo") or ""]
    if caps:
        partes.append("Capítulos\n" + "\n".join(f"{mmss(c['inicio'])} {n}"
                                                for c, n in zip(caps, textos["nomes_capitulos"])))
    if creditos:
        partes.append(creditos)
    if aviso_voz:
        partes.append("A narração deste vídeo é feita com voz sintética.")
    if textos.get("hashtags"):
        partes.append(" ".join(textos["hashtags"]))
    texto = "\n\n".join(p.strip() for p in partes if p and p.strip())
    if len(texto) > DESCRICAO_MAXIMA:
        # os créditos são o que mais cresce: cortados no fim, com aviso, e o resto fica inteiro
        texto = texto[:DESCRICAO_MAXIMA - 60].rsplit("\n", 1)[0] + "\n(créditos completos no arquivo creditos.txt)"
    return texto


def gerar(projeto, log=print, forcar=False) -> dict:
    """Escreve publicacao.json e PUBLICACAO.md. O modelo só é chamado quando o roteiro ou os capítulos mudam."""
    caps = capitulos(projeto)
    anterior = projeto.ler_json("publicacao.json") if projeto.existe("publicacao.json") else {}
    marca = assinatura(projeto, caps)
    titulo_mapa = (projeto.ler_json("roteiro_mapa.json").get("titulo") if projeto.existe("roteiro_mapa.json")
                   else "") or projeto.nome
    textos = anterior.get("textos") if not forcar and anterior.get("assinatura") == marca else None
    if textos is not None and "thumbs" not in textos:
        textos = None  # kit de antes das thumbnails: os textos delas saem na mesma chamada
    origem = "guardado"
    if textos is None:
        try:
            if projeto.offline:
                raise RuntimeError("modo offline")
            textos = _limpar(_textos_do_modelo(projeto, caps, log), caps, titulo_mapa)
            origem = "modelo"
        except (Exception, SystemExit) as erro:
            log(f"  publicação sem o modelo ({str(erro)[:120]}): título do mapa e nomes dos blocos")
            textos = _limpar({}, caps, titulo_mapa)
            origem = "sem modelo"
    cfg = projeto.config.get("publicacao") or {}
    sintetico = _tem_imagem_de_ia(projeto)
    dados = {
        "assinatura": marca if origem != "sem modelo" else None,
        "textos": textos,
        "titulo": textos["titulo"],
        "titulos_alt": textos["titulos_alt"],
        "descricao": descricao(textos, caps, _creditos(projeto), cfg.get("aviso_voz_sintetica", True)),
        "tags": textos["tags"],
        "hashtags": textos["hashtags"],
        "comentario_fixado": textos["comentario_fixado"],
        "thumbs": textos.get("thumbs") or [],
        "capitulos": [{"inicio": c["inicio"], "tempo": mmss(c["inicio"]), "nome": n}
                      for c, n in zip(caps, textos["nomes_capitulos"])],
        "sintetico": sintetico,
        "video": "final.mp4",
        "legenda": "legendas_final.srt" if projeto.existe("legendas_final.srt") else None,
    }
    projeto.salvar_json("publicacao.json", dados)
    (projeto.pasta / "PUBLICACAO.md").write_text(markdown(dados), encoding="utf-8")
    log(f"  kit de publicação pronto ({len(dados['capitulos'])} capítulos, {len(dados['tags'])} tags): "
        f"{projeto.pasta / 'PUBLICACAO.md'}")
    return dados


def markdown(dados) -> str:
    linhas = ["# Publicação", "", f"**Título:** {dados['titulo']}"]
    if dados["titulos_alt"]:
        linhas.append(f"**Alternativas (teste A/B):** {' · '.join(dados['titulos_alt'])}")
    linhas += [f"**Vídeo:** {dados['video']}",
               f"**Legenda para subir junto:** {dados['legenda'] or '(renderize o vídeo para ela sair)'}",
               f"**Conteúdo alterado ou sintético (realista):** {'Sim, o vídeo tem imagens de IA' if dados['sintetico'] else 'Não'}",
               "", "## Descrição", "```", dados["descricao"], "```", "",
               "## Comentário fixado", "```", dados["comentario_fixado"] or "(sem comentário)", "```", "",
               "## Tags", ", ".join(dados["tags"]) or "(sem tags)", ""]
    if not dados["capitulos"]:
        linhas.append("> Sem capítulos: o YouTube pede pelo menos 3, com 10 s ou mais cada. Marque partes com "
                      "[TITULO] no roteiro.")
    return "\n".join(linhas) + "\n"
