"""Shorts cortados do vídeo pronto: até 3 trechos de 20 a 58 s em 1080x1920, com título-gancho e legenda palavra por
palavra.

Pedido do usuário em 2026-10-09, da análise do concorrente (Pipeline Canal Dark), que corta os melhores trechos do
vídeo longo em shorts. Aqui, de graça e sem renderizar as cenas de novo:

- **Trechos** (`escolher`): as frases do roteiro com o tempo de cada uma (as `unidades` do `alinhamento.json`, juntas
  até o ponto final). O modelo principal (cadeia gratuita primeiro) escolhe até `shorts.quantidade` trechos que se
  sustentam sozinhos, começam com gancho (pergunta, número, afirmação forte) e não misturam dois blocos do mapa, e
  escreve o título-gancho da tela e o título do post. O código confere (`conferir`): duração entre `duracao_minima` e
  `duracao_maxima` (58 s, o Shorts aceita até 60), sem sobreposição, um bloco só. Sem modelo, as janelas com pergunta
  ou número na primeira frase (`_por_regra`).
- **Imagem** (`gravar`): o render deixa `render/video.mp4` (as cenas montadas, sem a legenda queimada) e
  `render/trilha.wav` (o áudio final), na mesma linha do tempo do `final.mp4`. O short corta os dois no trecho, põe a
  camada de animação que passa por ali (`animacoes.validas`), e monta em pé: o vídeo deitado no meio, sobre uma cópia
  dele desfocada e escura; o título-gancho em cima (Pillow, Inter Black, *destaque* em amarelo); a legenda grande
  embaixo, 3 palavras por vez com a palavra falada em amarelo (ASS, tempo do `alinhamento.json`). Longe das bordas que
  o app do Shorts cobre (embaixo e à direita).
- **Saída**: `shorts/S01.mp4`... e `shorts/shorts.json` (trecho, títulos, descrição com o link do vídeo completo).
  As escolhas ficam guardadas pela assinatura do roteiro; o MP4 é refeito quando o render muda.
"""
import hashlib
import json
import re
from pathlib import Path

from .util import rodar

LARGURA, ALTURA = 1080, 1920
FONTES = Path(__file__).parent / "recursos" / "fontes"
AMARELO = (255, 212, 0)


def config(projeto) -> dict:
    padrao = {"ativo": True, "quantidade": 3, "duracao_minima": 20, "duracao_maxima": 58, "palavras_por_legenda": 3}
    return {**padrao, **(projeto.config.get("shorts") or {}), **((projeto.perfil or {}).get("shorts") or {})}


# ------------------------------------------------------------------------------------------------ frases

def frases(projeto) -> list:
    """[{"i", "ini", "fim", "texto", "c", "bloco"}] das frases faladas (unidades juntas até o ponto)."""
    alin = projeto.ler_json("alinhamento.json")
    mapa = projeto.ler_json("roteiro_mapa.json") if projeto.existe("roteiro_mapa.json") else {}
    inicios = sorted((int(b.get("inicio_c") or 0), b.get("id")) for b in mapa.get("blocos") or [])
    bloco_de = lambda c: next((b for ini, b in reversed(inicios) if ini <= c), None)
    saida, atual = [], None
    for u in alin.get("unidades") or []:
        if atual is None:
            atual = {"ini": float(u["ini"]), "fim": float(u["fim"]), "texto": u["texto"].strip(), "c": u["c_ini"]}
        else:
            atual["fim"], atual["texto"] = float(u["fim"]), f"{atual['texto']} {u['texto'].strip()}"
        if re.search(r"[.!?…]['\"”)]*$", u["texto"].strip()):
            saida.append(atual)
            atual = None
    if atual:
        saida.append(atual)
    for i, f in enumerate(saida):
        f["i"], f["bloco"] = i, bloco_de(f["c"])
    return saida


def conferir(trecho, todas, cfg, outros=()) -> list:
    erros = []
    de, ate = trecho.get("de"), trecho.get("ate")
    if not (isinstance(de, int) and isinstance(ate, int) and 0 <= de <= ate < len(todas)):
        return ["'de' e 'ate' são números de frase da lista, com de <= ate"]
    dur = todas[ate]["fim"] - todas[de]["ini"] + 0.6
    if dur > float(cfg["duracao_maxima"]):
        erros.append(f"o trecho {de} a {ate} tem {dur:.0f} s, passa de {cfg['duracao_maxima']} s")
    if dur < float(cfg["duracao_minima"]):
        erros.append(f"o trecho {de} a {ate} tem {dur:.0f} s, menos que {cfg['duracao_minima']} s")
    if len({todas[k]["bloco"] for k in range(de, ate + 1)}) > 1:
        erros.append(f"o trecho {de} a {ate} mistura dois assuntos (blocos)")
    if any(not (ate < o["de"] or de > o["ate"]) for o in outros):
        erros.append(f"o trecho {de} a {ate} se sobrepõe a outro short")
    titulo = str(trecho.get("titulo") or "")
    if not titulo.strip() or len(titulo.replace("*", "")) > 60:
        erros.append("'titulo' (o gancho da tela) tem de 1 a 60 letras")
    if "—" in titulo or "—" in str(trecho.get("titulo_post") or ""):
        erros.append("nunca use travessão")
    from .animation_ai import _inventadas
    fala = " ".join(todas[k]["texto"] for k in range(de, ate + 1))
    fora = _inventadas([titulo], fala)
    if len(fora) > 1:
        erros.append(f"o título do trecho {de} a {ate} usa palavras que a fala não diz: {', '.join(fora[:4])}")
    return erros


_GANCHO = re.compile(r"\?|\d|\b(?:nunca|ningu[ée]m|segredo|verdade|mentira|perig|proib|maior|pior|melhor|primeir)", re.I)


def _por_regra(todas, cfg) -> list:
    """Sem modelo: janelas de frases seguidas do mesmo bloco, a de gancho mais forte na primeira frase primeiro."""
    cands = []
    for i in range(len(todas)):
        for j in range(i, len(todas)):
            t = {"de": i, "ate": j, "titulo": todas[i]["texto"][:57].rsplit(" ", 1)[0]}
            dur = todas[j]["fim"] - todas[i]["ini"] + 0.6
            if dur > float(cfg["duracao_maxima"]) or todas[j]["bloco"] != todas[i]["bloco"]:
                break
            if dur >= float(cfg["duracao_minima"]):
                nota = 3 * bool(re.search(r"\?", todas[i]["texto"])) + 2 * bool(_GANCHO.search(todas[i]["texto"]))
                cands.append((nota + (1 if 30 <= dur <= 50 else 0) - 0.001 * i, t))
                break
    escolhidos = []
    for _, t in sorted(cands, key=lambda x: -x[0]):
        if not conferir(t, todas, cfg, escolhidos):
            escolhidos.append(t)
        if len(escolhidos) >= int(cfg["quantidade"]):
            break
    for t in escolhidos:
        t["titulo_post"] = t["titulo"]
    return sorted(escolhidos, key=lambda t: t["de"])


ESQUEMA = {"type": "object", "properties": {"shorts": {"type": "array", "items": {
    "type": "object", "properties": {"de": {"type": "integer"}, "ate": {"type": "integer"},
                                     "titulo": {"type": "string"}, "titulo_post": {"type": "string"}},
    "required": ["de", "ate", "titulo", "titulo_post"]}}}, "required": ["shorts"]}


def _instrucoes(cfg) -> str:
    return f"""Você é editor de Shorts do YouTube. Recebe as frases numeradas de um vídeo, com o tempo de cada uma, e
escolhe até {cfg['quantidade']} trechos que viram Shorts. Responda só em JSON:
{{"shorts": [{{"de": N, "ate": N, "titulo": "...", "titulo_post": "..."}}]}}

- Cada trecho é uma sequência de frases (de "de" até "ate") com {cfg['duracao_minima']} a {cfg['duracao_maxima']}
  segundos no total, que se entende SOZINHO, sem o resto do vídeo: começa com gancho (pergunta, número, afirmação
  forte) e termina numa conclusão, nunca no meio de uma ideia. Nunca começa com "e", "mas", "então" ou "isso".
- Não misture dois blocos (o número do bloco vem em cada frase) e não sobreponha trechos.
- titulo: o gancho que fica no alto da tela, até 50 letras, uma ou duas palavras entre *asteriscos* (o destaque).
  Ele instiga, não resume. Nada que o trecho não entrega.
- titulo_post: o título do Short no YouTube, até 90 letras, com a palavra-chave no começo.
- Português do Brasil correto e natural, com as palavras da própria fala. Nunca use travessão (—)."""


def escolher(projeto, log=print, forcar=False) -> list:
    """Os trechos dos shorts, guardados em shorts/escolha.json pela assinatura do roteiro."""
    from . import openrouter_local

    cfg = config(projeto)
    todas = frases(projeto)
    marca = hashlib.sha1(json.dumps([1, [f["texto"] for f in todas], cfg["quantidade"], cfg["duracao_maxima"]],
                                    ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    arquivo = projeto.caminho("shorts", "escolha.json")
    if arquivo.exists() and not forcar:
        guardado = json.loads(arquivo.read_text(encoding="utf-8"))
        if guardado.get("assinatura") == marca:
            return guardado["trechos"]
    linhas = "\n".join(f"{f['i']}. [{f['ini']:.1f}-{f['fim']:.1f} s, bloco {f['bloco']}] {f['texto']}" for f in todas)
    escolhidos, erros = [], []
    for _ in range(2):
        pedido = f"FRASES:\n{linhas}"
        if erros:
            pedido += "\n\nA RESPOSTA ANTERIOR TEVE ESTES PROBLEMAS: " + "; ".join(erros[:6])
        try:
            resposta = openrouter_local.perguntar(projeto, "shorts: escolha dos trechos", _instrucoes(cfg), pedido,
                                                  ESQUEMA, log=log, modelo=openrouter_local.principal(projeto))
        except (Exception, SystemExit) as erro:
            log(f"  shorts: o modelo não respondeu ({str(erro)[:100]}); trechos pela regra")
            break
        escolhidos, erros = [], []
        for t in resposta.get("shorts") or []:
            if not isinstance(t, dict):
                continue
            problemas = conferir(t, todas, cfg, escolhidos)
            if problemas:
                erros += problemas
            else:
                escolhidos.append({k: t[k] for k in ("de", "ate", "titulo", "titulo_post")})
        if escolhidos and (len(escolhidos) >= int(cfg["quantidade"]) or not erros):
            break
    if not escolhidos:
        escolhidos = _por_regra(todas, cfg)
    escolhidos = sorted(escolhidos, key=lambda t: t["de"])[:int(cfg["quantidade"])]
    arquivo.write_text(json.dumps({"assinatura": marca, "trechos": escolhidos}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    return escolhidos


# ------------------------------------------------------------------------------------------------ imagem

def _fonte(px, peso=900):
    from PIL import ImageFont
    f = ImageFont.truetype(str(FONTES / "Inter.ttf"), px)
    try:
        f.set_variation_by_axes([32, peso])
    except Exception:  # noqa: BLE001
        pass
    return f


def _titulo_png(titulo, destino) -> Path:
    """O título-gancho centrado, até 3 linhas, com o *destaque* em amarelo."""
    from PIL import Image, ImageDraw, ImageFilter

    palavras = [(p.strip("*"), p.startswith("*") or p.endswith("*")) for p in re.findall(r"\*[^*]+\*|\S+", titulo)]
    # *duas palavras* viram duas palavras em destaque
    soltas = []
    for texto, forte in palavras:
        soltas += [(w, forte) for w in texto.split()]
    px = 96
    while px > 54:
        fonte = _fonte(px)
        linhas, atual = [], []
        for w in soltas:
            teste = atual + [w]
            if atual and fonte.getlength(" ".join(x for x, _ in teste).upper()) > 960:
                linhas.append(atual)
                atual = [w]
            else:
                atual = teste
        if atual:
            linhas.append(atual)
        if len(linhas) <= 3:
            break
        px -= 6
    img = Image.new("RGBA", (LARGURA, 420), (0, 0, 0, 0))
    altura = len(linhas) * px * 1.12
    y = (420 - altura) / 2
    sombra = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ds, desenho = ImageDraw.Draw(sombra), ImageDraw.Draw(img)
    posicoes = []
    for linha in linhas:
        largura = fonte.getlength(" ".join(w for w, _ in linha).upper())
        x = (LARGURA - largura) / 2
        for w, forte in linha:
            posicoes.append((x, y, w.upper(), forte))
            x += fonte.getlength(w.upper() + " ")
        y += px * 1.12
    for x, y, w, _ in posicoes:
        ds.text((x + 5, y + 8), w, font=fonte, fill=(0, 0, 0, 200), stroke_width=9, stroke_fill=(0, 0, 0, 200))
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(7)))
    for x, y, w, forte in posicoes:
        desenho.text((x, y), w, font=fonte, fill=AMARELO if forte else (255, 255, 255), stroke_width=6,
                     stroke_fill=(10, 10, 12))
    img.save(destino)
    return destino


def _ass(projeto, t0, t1, atraso, destino, por_legenda=3) -> Path:
    """Legenda palavra por palavra: blocos de 3 palavras, a falada em amarelo."""
    alin = projeto.ler_json("alinhamento.json")
    palavras = [p for p in alin.get("palavras") or [] if p.get("ini") is not None]
    dentro = []
    for k, p in enumerate(palavras):
        ini = float(p["ini"]) + atraso - t0
        fim = (float(palavras[k + 1]["ini"]) if k + 1 < len(palavras) else float(alin["duracao"])) + atraso - t0
        if fim <= 0 or ini >= t1 - t0:
            continue
        dentro.append((max(0.0, ini), min(fim, ini + 1.2, t1 - t0), re.sub(r"[{}\\]", "", p["texto"])))

    def carimbo(t):
        cs = int(round(t * 100))
        return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"

    eventos = []
    for g in range(0, len(dentro), por_legenda):
        grupo = dentro[g:g + por_legenda]
        for k, (ini, fim, _) in enumerate(grupo):
            fim = grupo[k + 1][0] if k + 1 < len(grupo) else fim
            texto = " ".join(("{\\c&H00D4FF&}" + w.upper() + "{\\c&HFFFFFF&}") if j == k else w.upper()
                             for j, (_, _, w) in enumerate(grupo))
            eventos.append(f"Dialogue: 0,{carimbo(ini)},{carimbo(max(fim, ini + 0.05))},Leg,,0,0,0,,{texto}")
    cabeca = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Leg,Inter,82,&H00FFFFFF,&H00FFFFFF,&H00101010,&H96000000,1,0,0,0,100,100,0,0,1,6,3,2,90,90,560,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    destino.write_text(cabeca + "\n".join(eventos) + "\n", encoding="utf-8")
    return destino


def _caminho_filtro(p) -> str:
    return str(p).replace("\\", "/").replace(":", "\\:")


def gravar(projeto, trecho, numero, log=print) -> dict:
    """Monta o short S0N a partir do render deitado. Devolve os dados dele."""
    from . import animacoes

    todas = frases(projeto)
    linha = projeto.ler_json("render/linha.json") if projeto.existe("render/linha.json") else {}
    atraso = float(linha.get("atraso") or 0)
    video, audio = projeto.pasta / "render" / "video.mp4", projeto.pasta / "render" / "trilha.wav"
    if not video.exists() or not audio.exists():
        raise RuntimeError(f"faltam as partes do render: rode uv run fabrica render {projeto.nome}")
    t0 = max(0.0, todas[trecho["de"]]["ini"] + atraso - 0.15)
    t1 = todas[trecho["ate"]]["fim"] + atraso + 0.45
    dur = min(t1 - t0, float(config(projeto)["duracao_maxima"]) + 1.0)
    pasta = projeto.caminho("shorts", "x").parent
    nome = f"S{numero:02d}"
    titulo_png = _titulo_png(trecho["titulo"], pasta / f"{nome}_titulo.png")
    legenda = _ass(projeto, t0, t0 + dur, atraso, pasta / f"{nome}.ass", int(config(projeto)["palavras_por_legenda"]))
    entradas = ["-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
                "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", str(audio), "-loop", "1", "-i", str(titulo_png)]
    partes, atual = [], "0:v"
    # a camada de animação que passa por este trecho entra por cima, como no vídeo deitado
    for k, m in enumerate(animacoes.validas(projeto) if animacoes.config(projeto).get("ativo", True) else []):
        ini, fim = float(m["ini"]) + atraso - t0, float(m["fim"]) + atraso - t0
        if fim <= 0 or ini >= dur:
            continue
        n = sum(1 for x in entradas if x == "-i")  # o número da entrada nova
        entradas += ["-i", str(m["arquivo"])]
        partes.append(f"[{n}:v]setpts=PTS-STARTPTS+{max(ini, 0):.3f}/TB,format=yuva420p[m{k}]")
        partes.append(f"[{atual}][m{k}]overlay=eof_action=pass:format=auto:enable='between(t,{ini:.3f},{fim:.3f})'[c{k}]")
        atual = f"c{k}"
    partes += [
        f"[{atual}]fps=30,split[a][b]",
        f"[a]scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=increase,crop={LARGURA}:{ALTURA},boxblur=28:2,"
        f"eq=brightness=-0.18:saturation=1.1[fundo]",
        f"[b]scale={LARGURA}:-2[meio]",
        "[fundo][meio]overlay=0:620[com_meio]",
        "[com_meio][2:v]overlay=0:150:shortest=1[com_titulo]",
        f"[com_titulo]subtitles=filename='{_caminho_filtro(legenda)}':fontsdir='{_caminho_filtro(FONTES)}'[saida]",
        f"[1:a]afade=t=in:d=0.15,afade=t=out:st={max(0.0, dur - 0.45):.3f}:d=0.45[som]",
    ]
    destino = pasta / f"{nome}.mp4"
    temporario = destino.with_name(destino.stem + ".tmp.mp4")
    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(partes), "-map", "[saida]",
           "-map", "[som]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-t", f"{dur:.3f}", "-movflags", "+faststart", str(temporario)])
    temporario.replace(destino)
    kit = projeto.ler_json("publicacao.json") if projeto.existe("publicacao.json") else {}
    hashtags = " ".join((kit.get("hashtags") or [])[:2] + ["#shorts"])
    titulo_post = re.sub(r"\*", "", trecho.get("titulo_post") or trecho["titulo"])[:90]
    return {"id": nome, "arquivo": f"shorts/{nome}.mp4", "de": trecho["de"], "ate": trecho["ate"],
            "inicio": round(t0, 2), "duracao": round(dur, 2), "titulo": trecho["titulo"],
            "titulo_post": titulo_post if "#shorts" in titulo_post.lower() else f"{titulo_post} #shorts"[:100],
            "descricao": f"Vídeo completo no canal: {kit.get('titulo') or projeto.nome}\n\n{hashtags}",
            "fala": " ".join(todas[k]["texto"] for k in range(trecho["de"], trecho["ate"] + 1))}


def gerar(projeto, log=print, forcar=False) -> list:
    """Escolhe os trechos e monta os shorts. Grátis. Devolve a lista em shorts/shorts.json."""
    if not projeto.existe("alinhamento.json"):
        raise RuntimeError("falta a narração")
    trechos = escolher(projeto, log, forcar)
    feitos = []
    for k, t in enumerate(trechos, 1):
        try:
            feitos.append(gravar(projeto, t, k, log))
            log(f"  short S{k:02d} pronto ({feitos[-1]['duracao']:.0f} s): {feitos[-1]['titulo_post']}")
        except (Exception, SystemExit) as erro:
            log(f"  short S{k:02d} não saiu: {str(erro)[:200]}")
    for velho in projeto.pasta.glob("shorts/S*.mp4"):
        if velho.name not in {Path(f["arquivo"]).name for f in feitos} and ".tmp." not in velho.name:
            velho.unlink()
    projeto.salvar_json("shorts/shorts.json", {"shorts": feitos})
    return feitos
