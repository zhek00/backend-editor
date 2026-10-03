"""Animações das cenas que não existem em banco de imagens, feitas com o HyperFrames.

O agente de roteiro marca cada cena com um tipo visual. Diagrama, texto na tela, linha do tempo e mapa não se
fotografam: antes viravam a foto de banco mais próxima ("diagrama de rede clandestina" virou uma iguana, "diagrama
da fazenda em torno do fogo de chão" virou a ilha vulcânica do Fogo). Agora o modelo principal (gratuito) escreve
a animação dessas cenas em HTML, por cima do material real da cena escurecido, com cada elemento entrando no tempo
exato da palavra falada, e o HyperFrames (github.com/heygen-com/hyperframes, roda no PC com Node 22+) transforma
em MP4.

Nada aqui pode quebrar o vídeo: sem Node, com a etapa desligada ou com a animação reprovada na conferência do
próprio HyperFrames, a cena continua com a foto de sempre. O render só usa a animação que está em dia com a cena
(mesma fala, mesmo tempo, mesmo fundo); se algo mudou, volta a foto até a animação ser refeita.

A fábrica monta a parte fixa da página (tela, fundo, fontes, linha do tempo) e o modelo escreve só o conteúdo e as
entradas no tempo das palavras: escrevendo a página inteira ele errava muito mais. O HyperFrames confere cada
animação (texto sobreposto, saindo da tela, regras de animação); reprovada, os erros voltam para o modelo corrigir.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .animacoes_modelos import CATALOGO, MODELOS, conferir_dados
from .animacoes_modelos import VERSAO as VERSAO_DESIGN
from .animacoes_modelos import partes as partes_do_modelo
from .util import duracao_audio, rodar

TIPOS_PADRAO = ("diagrama", "texto_tela", "linha_do_tempo", "mapa")
VERSAO_PADRAO = "0.8.113"  # versão fixa: uma atualização do HyperFrames não muda o vídeo de ninguém sem aviso
RECURSOS = Path(__file__).parent / "recursos"
GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"

ESTILO_PADRAO = {
    "destaque": "#E8A33D",   # números, palavras-chave, linhas
    "texto": "#F3EBDD",      # texto principal
    "secundaria": "#B9BEC6",  # rótulos e texto de apoio
    "painel": "rgba(14, 11, 9, 0.78)",  # fundo de cartões
    "alerta": "#C2313F",     # o que a narração nega, risca ou contrapõe
    "escurecer": 0.62,       # quanto o fundo real escurece por trás da animação (0 a 1)
}

_TRAVA_NODE = threading.Lock()
_NODE = {}


def config(projeto) -> dict:
    return {**(projeto.config.get("animacoes") or {}), **((projeto.perfil.get("animacoes") or {}))}


def tipos(projeto) -> tuple:
    return tuple(config(projeto).get("tipos") or TIPOS_PADRAO)


def ligada(projeto) -> bool:
    """A etapa está ligada no config.yaml (ou no perfil) e o projeto não está em modo offline."""
    return bool(config(projeto).get("ativo", True)) and not projeto.offline


def node_pronto() -> str:
    """O caminho do npx se o Node 22+ existir nesta máquina; senão uma string vazia. Conferido uma vez só."""
    with _TRAVA_NODE:
        if "npx" in _NODE:
            return _NODE["npx"]
        npx, node = shutil.which("npx"), shutil.which("node")
        pronto = ""
        if npx and node:
            try:
                versao = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout
                if int(re.sub(r"[^\d.]", "", versao).split(".")[0]) >= 22:
                    pronto = npx
            except (OSError, ValueError, subprocess.SubprocessError):
                pronto = ""
        _NODE["npx"] = pronto
        return pronto


def elegivel(projeto, cena, pedida=False) -> bool:
    """A cena é de um tipo que se anima e já tem o material real ou a imagem que vai ao fundo.

    Cena em que a pessoa escolheu ficar com a foto (animacao.desligada) só volta a ser animada se ela pedir."""
    if (cena.get("animacao") or {}).get("desligada") and not pedida:
        return False
    return cena.get("visual") in tipos(projeto) and _fundo(projeto, cena) is not None


def _fundo(projeto, cena):
    m = cena.get("midia") or {}
    if m.get("arquivo"):
        arquivo = projeto.pasta / m["arquivo"]
        return arquivo if arquivo.exists() else None
    imagem = projeto.imagem(cena["n"])
    return imagem if imagem.exists() else None


_PALAVRAS = {}  # (arquivo, data) -> palavras da narração: o editor confere a animação de centenas de cenas por vez


def _palavras_do_projeto(projeto) -> list:
    arquivo = projeto.pasta / "alinhamento.json"
    if not arquivo.exists():
        return []
    chave = (str(arquivo), arquivo.stat().st_mtime_ns)
    if chave not in _PALAVRAS:
        _PALAVRAS.clear()  # guarda só o projeto da vez
        _PALAVRAS[chave] = json.loads(arquivo.read_text(encoding="utf-8")).get("palavras", [])
    return _PALAVRAS[chave]


def palavras_da_cena(projeto, cena) -> list:
    """[(palavra, segundo dentro da cena)] com o tempo que a narração mediu."""
    saida = []
    for p in _palavras_do_projeto(projeto):
        ini = p.get("ini")
        if ini is not None and cena["ini"] - 0.05 <= ini < cena["fim"]:
            saida.append((p["texto"], round(max(ini - cena["ini"], 0.0), 2)))
    return saida


def _pedido_da_cena(cena) -> dict:
    """O que o agente de roteiro pediu, antes de qualquer busca manual mudar a cena."""
    original = cena.get("pedido_original") or {}
    texto_tela = cena.get("texto_tela") or cena.get("overlay") or ""
    if isinstance(texto_tela, dict):
        texto_tela = " ".join(str(texto_tela.get(k) or "") for k in ("titulo", "texto")).strip()
    return {"mostrar": original.get("mostrar") or cena.get("mostrar") or "", "texto_tela": texto_tela}


def _assinatura_pedido(projeto, cena) -> str:
    """Muda quando muda o que a animação diz: fala, tempo das palavras, tipo ou pedido do agente."""
    pedido = _pedido_da_cena(cena)
    base = json.dumps([cena.get("texto"), round(cena["fim"] - cena["ini"], 2), cena.get("visual"), pedido,
                       palavras_da_cena(projeto, cena)], ensure_ascii=False)
    return hashlib.sha1(base.encode()).hexdigest()[:12]


def _assinatura_render(projeto, cena, assinatura_pedido) -> str:
    """Muda também quando muda o fundo (a mídia da cena), o tamanho do vídeo ou a versão do HyperFrames."""
    fundo = _fundo(projeto, cena)
    cfg = projeto.config.get("render") or {}
    base = (f"{assinatura_pedido}|{fundo.name if fundo else ''}|{fundo.stat().st_mtime_ns if fundo else 0}|"
            f"{cfg.get('largura', 1920)}x{cfg.get('altura', 1080)}|{config(projeto).get('versao', VERSAO_PADRAO)}|"
            f"{json.dumps(_estilo(projeto), sort_keys=True)}|design {VERSAO_DESIGN}")
    return hashlib.sha1(base.encode()).hexdigest()[:12]


def valida(projeto, cena):
    """O MP4 da animação, se ela existe e está em dia com a cena; senão None (a cena usa a foto)."""
    info = cena.get("animacao") or {}
    if not info.get("arquivo") or cena.get("visual") not in tipos(projeto):
        return None
    arquivo = projeto.pasta / info["arquivo"]
    if not arquivo.exists():
        return None
    assinatura_pedido = _assinatura_pedido(projeto, cena)
    if info.get("pedido") != assinatura_pedido or info.get("render") != _assinatura_render(projeto, cena, assinatura_pedido):
        return None
    return arquivo


def situacao(projeto, cena) -> str:
    """Para o editor: "pronta", "desatualizada" (algo da cena mudou), "possivel" (dá para animar) ou ""."""
    if valida(projeto, cena) is not None:
        return "pronta"
    if (cena.get("animacao") or {}).get("desligada"):
        return "desligada" if cena.get("visual") in tipos(projeto) else ""
    if (cena.get("animacao") or {}).get("arquivo") and cena.get("visual") in tipos(projeto):
        return "desatualizada"
    return "possivel" if elegivel(projeto, cena) else ""


def _estilo(projeto) -> dict:
    return {**ESTILO_PADRAO, **(config(projeto).get("estilo") or {})}


# ---------------------------------------------------------------------------------------------- o pedido

INSTRUCOES = """Você é diretor de motion design de documentários para o YouTube. Escolhe a animação de UMA cena de um
vídeo narrado e preenche os textos dela. O design já está pronto na fábrica, no estilo editorial e limpo da Apple e da
Netflix: você só escolhe o modelo que melhor conta o que a narração diz e preenche os dados dele.

Modelos e o formato exato de "dados" de cada um:
""" + CATALOGO + """
Como escolher: número com o que ele mede -> numero; dois lados opostos -> contraste; um assunto que une várias coisas
-> radial; enumeração -> lista; processo em etapas -> fluxo; datas ou épocas -> linha_do_tempo; lugar, distância ou
rota -> mapa; afirmação de impacto sem nada disso -> frase. Use o pedido do diretor de arte como pista, mas quem manda
é o que a narração desta cena diz.

O TEMPO MANDA: todo "t" é o segundo em que aquela palavra é falada, tirado da lista de tempos do pedido. Cada elemento
entra quando é falado, nunca antes. Elemento que não é falado na cena (um rótulo, um título) entra junto com a palavra
mais próxima do sentido dele.

Textos: português do Brasil, com acentos. Curtos (veja os limites de cada campo). Só o que a narração diz ou o fato
direto dela; nunca invente número, data ou nome. Títulos e rótulos em poucas palavras.
"""

ESQUEMA = {
    "type": "object",
    "properties": {"modelo": {"type": "string", "enum": list(MODELOS)}, "dados": {"type": "object"}},
    "required": ["modelo", "dados"],
    "additionalProperties": False,
}


def _pedido(projeto, cena, vizinhas, erros):
    pedido = _pedido_da_cena(cena)
    palavras = palavras_da_cena(projeto, cena)
    linhas = [
        f"Tipo pedido pelo agente de roteiro: {cena.get('visual')}",
        f"Duração da cena: {cena['fim'] - cena['ini']:.2f} s",
        f"Narração desta cena: \"{cena.get('texto', '')}\"",
        "Tempo de cada palavra (segundos dentro da cena): " + ", ".join(f"{p} {t:.2f}" for p, t in palavras),
        f"Frases anteriores: \"{vizinhas[0]}\"" if vizinhas[0] else "",
        f"Frase seguinte: \"{vizinhas[1]}\"" if vizinhas[1] else "",
        f"O que o diretor de arte pediu: {pedido['mostrar']}" if pedido["mostrar"] else "",
        f"Texto sugerido para a tela: {pedido['texto_tela']}" if pedido["texto_tela"] else "",
    ]
    if erros:
        linhas.append("\nA resposta anterior foi REPROVADA, por estes motivos. Corrija todos:\n- " + "\n- ".join(erros))
    return "\n".join(l for l in linhas if l)


def _erros_para_o_modelo(erros_conferencia) -> list:
    """Traduz o que a conferência do HyperFrames achou para o que o modelo de linguagem consegue corrigir: texto."""
    saida = []
    for e in erros_conferencia:
        if "overlap" in e or "overflow" in e or "clipped" in e or "outside" in e:
            saida.append("um texto ficou grande demais e saiu do lugar ou encostou em outro: encurte os textos "
                         f"(detalhe: {e[:160]})")
        else:
            saida.append(e[:200])
    return saida


def _montar_html(partes, cena, fundo_tipo, largura, altura, estilo) -> str:
    dur = round(cena["fim"] - cena["ini"], 3)
    if fundo_tipo == "video":
        fundo = (f'<video id="fundo" src="assets/fundo.mp4" data-start="0" data-duration="{dur}" '
                 'data-track-index="0" muted playsinline></video>')
    else:
        fundo = '<img id="fundo" src="assets/fundo.jpg" alt="" />'
    cores = "".join(f"--{k}: {v};" for k, v in estilo.items() if k != "escurecer")
    return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={largura}, height={altura}" />
    <script src="{GSAP}"></script>
    <style>
      @font-face {{ font-family: "Titulo"; src: url("assets/fontes/PlayfairDisplay.ttf"); font-weight: 400 900; }}
      @font-face {{ font-family: "Texto"; src: url("assets/fontes/Inter.ttf"); font-weight: 100 900; }}
      :root {{ {cores} }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {largura}px; height: {altura}px; overflow: hidden; background: #0b0907; }}
      #root {{ position: relative; width: 100%; height: 100%; overflow: hidden; }}
      #camada-fundo {{ position: absolute; inset: -40px; }}
      #fundo {{ display: block; width: 100%; height: 100%; object-fit: cover; }}
      #veu {{ position: absolute; inset: 0; background: rgba(8, 6, 4, {float(estilo.get("escurecer", 0.62)):.2f}); }}
      #conteudo {{ position: absolute; inset: 0; padding: 110px 110px 210px 110px; font-family: "Texto", sans-serif;
                   color: var(--texto); }}
      /* da cena */
{partes["css"]}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="{largura}" data-height="{altura}">
      <div id="camada-fundo">{fundo}</div>
      <div id="veu"></div>
      <section id="conteudo" class="clip" data-start="0" data-duration="{dur}" data-track-index="1">
{partes["html"]}
      </section>
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      tl.fromTo("#camada-fundo", {{ scale: 1.03 }}, {{ scale: 1.1, duration: {dur}, ease: "none" }}, 0);
      tl.fromTo("#veu", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.4, ease: "power2.out" }}, 0);
      (function () {{
{partes["js"]}
      }})();
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


# ---------------------------------------------------------------------------------------------- a pasta

def _pasta(projeto, cena) -> Path:
    return projeto.pasta / "animacoes" / f"{cena['n']:04d}"


def _preparar_pasta(projeto, cena, pasta, largura, altura) -> str:
    """Fundo da cena (o mesmo trecho que o render usaria) e as fontes. Devolve "video" ou "foto"."""
    assets = pasta / "assets"
    (assets / "fontes").mkdir(parents=True, exist_ok=True)
    for nome in ("Inter.ttf", "PlayfairDisplay.ttf"):
        destino = assets / "fontes" / nome
        if not destino.exists():
            shutil.copy2(RECURSOS / "fontes" / nome, destino)
    (pasta / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
        "media": {"autoProxy": True}}, indent=2), encoding="utf-8")
    (pasta / "meta.json").write_text(json.dumps({"id": pasta.name, "name": pasta.name}), encoding="utf-8")
    origem = _fundo(projeto, cena)
    dur = cena["fim"] - cena["ini"]
    escala = f"scale={largura}:{altura}:force_original_aspect_ratio=increase,crop={largura}:{altura}"
    for velho in assets.glob("fundo.*"):
        velho.unlink()
    if origem.suffix.lower() in (".mp4", ".mov", ".webm", ".m4v"):
        disponivel = duracao_audio(origem)
        # o mesmo começo do render (render._entrada_video): pula até 1 s, que costuma ter tremida
        inicio = min(1.0, (disponivel - dur) / 2) if disponivel >= dur + 1 else 0.0
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-i", origem, "-t", f"{dur + 0.5:.3f}",
               "-an", "-vf", f"{escala},fps=30,tpad=stop_mode=clone:stop_duration={dur + 0.5:.3f}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", assets / "fundo.mp4"])
        return "video"
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", origem, "-vf", escala, "-q:v", "3", assets / "fundo.jpg"])
    return "foto"


def _hyperframes(projeto, args, pasta, limite):
    npx = node_pronto()
    versao = config(projeto).get("versao", VERSAO_PADRAO)
    ambiente = {**os.environ, "DO_NOT_TRACK": "1", "HYPERFRAMES_NO_TELEMETRY": "1", "HYPERFRAMES_SKIP_SKILLS": "1"}
    return subprocess.run([npx, "--yes", f"hyperframes@{versao}", *args], cwd=pasta, env=ambiente,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=limite)


def _conferir(projeto, pasta) -> list:
    """Os erros que a conferência do HyperFrames achou (texto sobreposto, saindo da tela, regras quebradas)."""
    r = _hyperframes(projeto, ["check", "--json"], pasta, 300)
    try:
        dados = json.loads(r.stdout[r.stdout.find("{"):])
    except ValueError:
        return [f"a conferência não rodou: {(r.stderr or r.stdout)[-300:]}"]
    if dados.get("ok"):
        return []
    erros = []
    for parte in ("lint", "runtime", "layout", "motion", "contrast"):
        for f in (dados.get(parte) or {}).get("findings", []):
            if f.get("severity") == "error":
                quando = f" em {f['time']:.2f}s" if isinstance(f.get("time"), (int, float)) else ""
                texto = f" (\"{f['text'][:40]}\")" if f.get("text") else ""
                erros.append(f"{f.get('code')}{quando} no {f.get('selector', '?')}{texto}: {f.get('message', '')} "
                             f"Como corrigir: {f.get('fixHint', '')}".strip())
    return erros or ["a conferência reprovou sem dizer o motivo"]


def _renderizar(projeto, pasta, destino) -> bool:
    temporario = destino.with_name(destino.stem + ".tmp.mp4")
    r = _hyperframes(projeto, ["render", "--output", str(temporario), "--fps", "30", "--quality", "delivery",
                               "--workers", "1", "--quiet"], pasta, 900)
    if r.returncode != 0 or not temporario.exists() or temporario.stat().st_size < 1000:
        temporario.unlink(missing_ok=True)
        return False
    temporario.replace(destino)
    return True


# ---------------------------------------------------------------------------------------------- a etapa

def _gravar(projeto, n, info, trava):
    """Grava só o campo animacao da cena, lendo o arquivo na hora: o editor pode ter mexido em outra cena."""
    def gravar():
        dados = projeto.ler_json("cenas.json")
        for c in dados["cenas"]:
            if c["n"] == n:
                if info is None:
                    c.pop("animacao", None)
                else:
                    c["animacao"] = info
        projeto.salvar_json("cenas.json", dados)
    if trava is not None:
        with trava:
            gravar()
    else:
        gravar()


def _animar(projeto, cena, vizinhas, forcar, log):
    """Faz (ou reaproveita) a animação de uma cena. Devolve (info, situação) ou (None, motivo)."""
    from . import openrouter_local

    cfg_render = projeto.config.get("render") or {}
    largura, altura = cfg_render.get("largura", 1920), cfg_render.get("altura", 1080)
    estilo = _estilo(projeto)
    assinatura_pedido = _assinatura_pedido(projeto, cena)
    assinatura_render = _assinatura_render(projeto, cena, assinatura_pedido)
    pasta = _pasta(projeto, cena)
    destino = projeto.pasta / "animacoes" / f"{cena['n']:04d}.mp4"
    info = {k: v for k, v in (cena.get("animacao") or {}).items() if k != "desligada"}
    if not forcar and info.get("pedido") == assinatura_pedido and info.get("render") == assinatura_render \
            and destino.exists():
        return info, "já estava pronta"
    pasta.mkdir(parents=True, exist_ok=True)
    fundo_tipo = _preparar_pasta(projeto, cena, pasta, largura, altura)
    arquivo_partes = pasta / "partes.json"
    dur = cena["fim"] - cena["ini"]
    tempos = [t for _, t in palavras_da_cena(projeto, cena)]
    fala = " ".join([vizinhas[0], cena.get("texto", ""), vizinhas[1]])
    escolha = None
    # a mesma fala e o mesmo tempo: só o fundo (ou o design) mudou, então reaproveita o que o modelo escolheu
    if not forcar and info.get("pedido") == assinatura_pedido and arquivo_partes.exists():
        guardada = json.loads(arquivo_partes.read_text(encoding="utf-8"))
        if guardada.get("modelo") in MODELOS:
            dados, erros = conferir_dados(guardada["modelo"], guardada.get("dados"), dur, tempos, fala)
            if not erros:
                html_ = _montar_html(partes_do_modelo(guardada["modelo"], dados, dur), cena, fundo_tipo, largura, altura, estilo)
                (pasta / "index.html").write_text(html_, encoding="utf-8")
                if not _conferir(projeto, pasta):
                    escolha = {"modelo": guardada["modelo"], "dados": dados}
    if escolha is None:
        erros = []
        for tentativa in range(int(config(projeto).get("tentativas", 3))):
            resposta = openrouter_local.perguntar(
                projeto, "animação da cena", INSTRUCOES, _pedido(projeto, cena, vizinhas, erros), ESQUEMA, log=log,
                modelo=openrouter_local.principal(projeto), temperatura=0.4 if tentativa else 0.2)
            modelo = str(resposta.get("modelo") or "").strip()
            dados, erros = conferir_dados(modelo, resposta.get("dados"), dur, tempos, fala)
            if not erros:
                html_ = _montar_html(partes_do_modelo(modelo, dados, dur), cena, fundo_tipo, largura, altura, estilo)
                (pasta / "index.html").write_text(html_, encoding="utf-8")
                erros = _erros_para_o_modelo(_conferir(projeto, pasta))
            if not erros:
                escolha = {"modelo": modelo, "dados": dados}
                break
            erros = erros[:6]
        if escolha is None:
            return None, "reprovada na conferência: " + "; ".join(erros)[:300]
        arquivo_partes.write_text(json.dumps(escolha, ensure_ascii=False, indent=1), encoding="utf-8")
    if not _renderizar(projeto, pasta, destino):
        return None, "o HyperFrames não conseguiu renderizar"
    return {"arquivo": destino.relative_to(projeto.pasta).as_posix(), "pedido": assinatura_pedido,
            "render": assinatura_render, "visual": cena.get("visual"), "modelo": escolha["modelo"]}, "feita"


def gerar(projeto, numeros=None, forcar=False, log=print, trava=None) -> dict:
    """Anima as cenas de diagrama, texto na tela, linha do tempo e mapa que ainda não têm animação em dia.

    Nunca para o vídeo: a cena que não deu para animar continua com a foto. trava protege o cenas.json quando o
    editor também pode estar mexendo nele (o servidor passa a trava do projeto)."""
    resumo = {"feitas": [], "prontas": [], "falharam": {}, "motivo": ""}
    if not ligada(projeto):
        resumo["motivo"] = "animações desligadas (animacoes.ativo no config.yaml) ou projeto offline"
        return resumo
    if not node_pronto():
        resumo["motivo"] = "falta o Node.js 22 ou mais nesta máquina (nodejs.org): as cenas seguem com foto"
        log(f"  animações: {resumo['motivo']}")
        return resumo
    if not projeto.existe("cenas.json"):
        return resumo
    cenas = projeto.ler_json("cenas.json")["cenas"]
    alvo = [c for c in cenas if (numeros is None and elegivel(projeto, c))
            or (numeros is not None and c["n"] in numeros and elegivel(projeto, c, pedida=True))]
    if not alvo:
        return resumo
    textos = {c["n"]: (c.get("texto") or "").strip() for c in cenas}
    log(f"  animando {len(alvo)} cena(s) de diagrama, texto na tela, linha do tempo e mapa (HyperFrames)")

    def uma(cena):
        # três frases antes: o assunto de um diagrama costuma ter sido apresentado logo antes ("o elemento que une
        # o vinho, a cachaça, a carne e a terra: o fogo" vem nas cenas antes de "é o altar ao redor do qual...")
        partes_antes, k = [], 1
        while cena["n"] - k in textos and k <= 8 and sum(len(x) for x in partes_antes) < 300:
            partes_antes.insert(0, textos[cena["n"] - k])
            k += 1
        antes = " ".join(partes_antes).strip()
        vizinhas = (antes, textos.get(cena["n"] + 1, ""))
        try:
            info, situacao_ = _animar(projeto, cena, vizinhas, forcar, log)
        except (Exception, SystemExit) as erro:
            info, situacao_ = None, f"falhou: {str(erro)[:200]}"
        return cena, info, situacao_

    with ThreadPoolExecutor(max(1, int(config(projeto).get("paralelo", 2)))) as executor:
        for cena, info, situacao_ in executor.map(uma, alvo):
            if info is None:
                resumo["falharam"][cena["n"]] = situacao_
                log(f"  cena {cena['n']}: sem animação, fica a foto ({situacao_})")
                continue
            if situacao_ == "já estava pronta":
                resumo["prontas"].append(cena["n"])
                continue
            _gravar(projeto, cena["n"], info, trava)
            resumo["feitas"].append(cena["n"])
            log(f"  cena {cena['n']}: animação pronta ({cena.get('visual')})")
    log(f"  animações: {len(resumo['feitas'])} feita(s), {len(resumo['prontas'])} já pronta(s), "
        f"{len(resumo['falharam'])} ficaram com foto")
    return resumo


def remover(projeto, n, trava=None) -> None:
    """A cena volta a usar a foto e fica assim: a criação não anima de novo sozinha. Os arquivos ficam guardados."""
    _gravar(projeto, n, {"desligada": True}, trava)
    from . import aprendizados
    cena = next((c for c in projeto.ler_json("cenas.json")["cenas"] if c["n"] == n), None)
    if cena:
        aprendizados.registrar(projeto, cena, "foto")
