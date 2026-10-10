"""Animações (motion) por cima do vídeo, feitas com o HyperFrames.

O agente de roteiro marca cada cena com um tipo visual. Diagrama, texto na tela, linha do tempo e mapa não se
fotografam: antes viravam a foto de banco mais próxima ("diagrama de rede clandestina" virou uma iguana). O modelo
principal (gratuito) escolhe um dos modelos prontos (animacoes_modelos.py) e preenche os textos e o segundo de cada
um, e o HyperFrames (github.com/heygen-com/hyperframes, roda no PC com Node 22+) desenha.

A animação é uma CAMADA POR CIMA DAS CENAS, não uma cena. Cada animação fica em animacoes/motion.json, presa às
palavras do roteiro (a posição de cada palavra no texto, o campo c do alinhamento.json), e é desenhada num MOV
transparente com o véu escuro dentro. O render monta as cenas como sempre e põe a camada por cima, no tempo da fala.
Por isso:
- trocar a imagem de uma cena, dividir, juntar ou renumerar cenas não mexe na animação. Antes cada animação era um
  clipe da cena com a foto dela no fundo, e qualquer troca deixava a animação "desatualizada" e voltava a foto;
- trocar a voz só reposiciona a animação na fala nova e desenha de novo, sem perguntar de novo ao modelo;
- cenas de animação seguidas, do mesmo bloco, viram UMA animação que segue por cima enquanto as imagens trocam
  embaixo (até animacoes.duracao_maxima segundos);
- a duração vem do que está escrito na animação (duracao_do_conteudo): de 3 a 8 segundos, o bastante para ler tudo.
  Antes ela durava só a fala das cenas dela, e uma cena de 3 s sumia com a animação no meio da leitura. Ela começa na
  palavra e pode seguir por cima das cenas seguintes, até a próxima animação.

Nada aqui pode quebrar o vídeo: sem Node, com a etapa desligada ou com a animação reprovada na conferência do
próprio HyperFrames, as cenas seguem com a foto e o texto na tela de sempre.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .animacoes_modelos import CATALOGO, MODELOS, conferir_dados
from .animacoes_modelos import VERSAO as VERSAO_DESIGN
from .animacoes_modelos import partes as partes_do_modelo
from .util import rodar

TIPOS_PADRAO = ("diagrama", "texto_tela", "linha_do_tempo", "mapa")
VERSAO_PADRAO = "0.8.113"  # versão fixa: uma atualização do HyperFrames não muda o vídeo de ninguém sem aviso
VERSAO_CAMADA = 2  # suba quando mudar o jeito de montar a camada (véu, entrada, saída): tudo é desenhado de novo
RECURSOS = Path(__file__).parent / "recursos"
GSAP = "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"
ARQUIVO = "animacoes/motion.json"
DURACAO_MAXIMA = 8.0  # cenas de animação seguidas viram uma animação só até este tamanho; e nenhuma dura mais
DURACAO_MINIMA = 3.0  # nenhuma animação dura menos, mesmo com a fala curta
SEGUNDOS_POR_PALAVRA = 0.3  # leitura do que está escrito na tela (umas 200 palavras por minuto)

ESTILO_PADRAO = {
    "destaque": "#E8A33D",   # números, palavras-chave, linhas
    "texto": "#F3EBDD",      # texto principal
    "secundaria": "#B9BEC6",  # rótulos e texto de apoio
    "painel": "rgba(14, 11, 9, 0.78)",  # fundo de cartões
    "alerta": "#C2313F",     # o que a narração nega, risca ou contrapõe
    "escurecer": 0.62,       # quanto a camada escurece as cenas por baixo (0 a 1)
}

_TRAVA_NODE = threading.Lock()
_NODE = {}
_TRAVA_ARQUIVO = threading.Lock()


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


def _estilo(projeto) -> dict:
    return {**ESTILO_PADRAO, **(config(projeto).get("estilo") or {})}


def _tamanho(projeto):
    cfg = projeto.config.get("render") or {}
    return cfg.get("largura", 1920), cfg.get("altura", 1080)


# ------------------------------------------------------------------------------------- as palavras da fala

_PALAVRAS = {}  # (arquivo, data) -> palavras da narração: o editor consulta centenas de cenas por vez


def _palavras_do_projeto(projeto) -> list:
    arquivo = projeto.pasta / "alinhamento.json"
    if not arquivo.exists():
        return []
    chave = (str(arquivo), arquivo.stat().st_mtime_ns)
    if chave not in _PALAVRAS:
        _PALAVRAS.clear()  # guarda só o projeto da vez
        _PALAVRAS[chave] = [p for p in json.loads(arquivo.read_text(encoding="utf-8")).get("palavras", [])
                            if p.get("ini") is not None]
    return _PALAVRAS[chave]


def _normal(texto) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or "").lower()).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", texto))


def _palavras_entre(projeto, ini, fim) -> list:
    return [p for p in _palavras_do_projeto(projeto) if ini - 0.05 <= p["ini"] < fim]


def _ancorar(projeto, item, pela_fala=False) -> dict | None:
    """Onde a animação está AGORA na fala: {ini, fim, palavras}. None se a fala dela não existe mais.

    A âncora é a posição das palavras no roteiro (campo c), que não muda quando a voz muda; o tempo vem da
    narração atual. Roteiro editado (posições mudaram) procura as mesmas palavras perto de onde estavam.
    O fim é o da duração da animação (pelo conteúdo); pela_fala=True dá o fim da fala do trecho."""
    palavras = _palavras_do_projeto(projeto)
    if not palavras:
        return None
    alvo = item.get("fala_normal") or _normal(item.get("texto"))
    sel = [p for p in palavras if p.get("c") is not None and item["c_ini"] <= p["c"] <= item["c_fim"]]
    if not sel or _normal(" ".join(p["texto"] for p in sel)) != alvo:
        # o roteiro mudou de lugar: as mesmas palavras, na sequência, mais perto da posição antiga
        quantas = len(alvo.split())
        normais = [_normal(p["texto"]) for p in palavras]
        achados = [i for i in range(len(palavras) - quantas + 1)
                   if " ".join(normais[i:i + quantas]) == alvo]
        if not achados:
            return None
        i = min(achados, key=lambda k: abs((palavras[k].get("c") or 0) - item["c_ini"]))
        sel = palavras[i:i + quantas]
    depois = next((p for p in palavras if p["ini"] > sel[-1]["ini"] and p is not sel[-1]
                   and (p.get("c") or 0) > (sel[-1].get("c") or 0)), None)
    ini = max(0.0, sel[0]["ini"] - item.get("folga_ini", 0.0))
    if depois is not None:
        fim = depois["ini"] - item.get("folga_fim", 0.0)
    else:
        fim = sel[-1]["ini"] + item.get("cauda", 1.0)
    fim = max(fim, ini + 0.5)
    if item.get("duracao") and not pela_fala:
        fim = ini + float(item["duracao"])
    return {"ini": round(ini, 3), "fim": round(fim, 3), "palavras": sel,
            "c_ini": sel[0].get("c"), "c_fim": sel[-1].get("c")}


def _tempos(ancora) -> list:
    return [round(max(p["ini"] - ancora["ini"], 0.0), 2) for p in ancora["palavras"]]


# ------------------------------------------------------------------------------------------- o arquivo

def ler(projeto) -> list:
    """As animações do projeto (animacoes/motion.json)."""
    arquivo = projeto.pasta / ARQUIVO
    if not arquivo.exists():
        return []
    try:
        return json.loads(arquivo.read_text(encoding="utf-8")).get("itens", [])
    except (OSError, ValueError):
        return []


def _salvar(projeto, itens) -> None:
    arquivo = projeto.pasta / ARQUIVO
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(json.dumps({"itens": sorted(itens, key=lambda i: i["c_ini"])}, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    temporario.replace(arquivo)


def _atualizar_item(projeto, novo, trava=None) -> None:
    """Grava um item lendo o arquivo na hora: outra animação pode ter terminado ao mesmo tempo."""
    with _TRAVA_ARQUIVO:
        itens = [i for i in ler(projeto) if i["id"] != novo["id"]] + [novo]
        _salvar(projeto, itens)


def _assinatura_render(projeto, item, ancora) -> str:
    """Muda quando muda o que vai na tela: o modelo e os dados, o tempo das palavras, o tamanho, o estilo ou o design.
    As cenas por baixo não entram: trocar a imagem de uma cena não mexe na animação."""
    base = json.dumps([item.get("modelo"), item.get("dados"), round(ancora["fim"] - ancora["ini"], 2), _tempos(ancora),
                       _tamanho(projeto), config(projeto).get("versao", VERSAO_PADRAO), _estilo(projeto),
                       VERSAO_DESIGN, VERSAO_CAMADA], ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(base.encode()).hexdigest()[:12]


def validas(projeto) -> list:
    """As animações em dia, com o tempo de agora: [{**item, ini, fim, arquivo: Path}]. É o que o render põe por cima."""
    if not config(projeto).get("ativo", True):
        return []
    saida = []
    for item in ler(projeto):
        if item.get("desligada") or not item.get("arquivo"):
            continue
        arquivo = projeto.pasta / item["arquivo"]
        if not arquivo.exists():
            continue
        ancora = _ancorar(projeto, item)
        if ancora is None or item.get("render") != _assinatura_render(projeto, item, ancora):
            continue
        saida.append({**item, "ini": ancora["ini"], "fim": ancora["fim"], "arquivo": arquivo})
    saida.sort(key=lambda i: i["ini"])
    # a fala mudou de ritmo depois de feita: uma animação nunca passa por cima do começo da seguinte
    for atual, seguinte in zip(saida, saida[1:]):
        if atual["fim"] > seguinte["ini"]:
            atual["fim"] = max(seguinte["ini"], atual["ini"] + 0.5)
    return _fora_do_motion_ia(projeto, saida)


def _cenas_motion_ia(projeto) -> list:
    """(ini, fim) das cenas que são um clipe do Motion IA (motion_ia.py)."""
    arquivo = projeto.pasta / "cenas.json"
    if not arquivo.exists():
        return []
    return [(c["ini"], c["fim"]) for c in json.loads(arquivo.read_text(encoding="utf-8"))["cenas"]
            if (c.get("midia") or {}).get("fonte") in ("motion_ia", "animation_ai")]  # a cena animada do animation-ai também


def _fora_do_motion_ia(projeto, itens) -> list:
    """A camada nunca passa por cima de um clipe do Motion IA: ele já é uma animação, com fundo próprio, e o véu
    escuro da camada embolava os dois (cena 6 do natureza-teste-1min, coberta pela frase da cena 5 até 20,4 s).
    A camada para no começo do clipe; a que começa dentro de um clipe sai."""
    clipes = _cenas_motion_ia(projeto)
    if not clipes:
        return itens
    saida = []
    for item in itens:
        if any(ini - 0.05 <= item["ini"] < fim - 0.05 for ini, fim in clipes):
            continue
        corte = min((ini for ini, _ in clipes if item["ini"] < ini < item["fim"]), default=None)
        if corte is not None:
            if corte - item["ini"] < 0.5:
                continue
            item = {**item, "fim": corte}
        saida.append(item)
    return saida


def _cobre(item, cena) -> bool:
    """A animação está por cima da maior parte da cena (o meio da cena cai dentro dela)."""
    meio = (cena["ini"] + cena["fim"]) / 2
    return item["ini"] <= meio < item["fim"]


def sobreposta(item, cena, folga=0.3) -> bool:
    """A animação passa por cima de parte da cena (mais que folga segundos)."""
    return min(item["fim"], cena["fim"]) - max(item["ini"], cena["ini"]) > folga


def da_cena(projeto, cena, itens=None):
    """A animação em dia que está por cima desta cena, ou None."""
    for item in itens if itens is not None else validas(projeto):
        if _cobre(item, cena):
            return item
    return None


def valida(projeto, cena):
    """O MOV da animação que está por cima da cena, se ela está em dia; senão None. (Nome antigo, mantido.)"""
    item = da_cena(projeto, cena)
    return item["arquivo"] if item else None


def cenas_cobertas(projeto, cenas, itens=None) -> set:
    """Os números das cenas que ficam embaixo de uma animação em dia (o texto na tela delas sai)."""
    itens = validas(projeto) if itens is None else itens
    return {c["n"] for c in cenas if any(sobreposta(i, c) for i in itens)}


def _item_por_tempo(projeto, cena, itens=None):
    """Qualquer animação (em dia ou não, ligada ou desligada) por cima da cena."""
    for item in itens if itens is not None else ler(projeto):
        ancora = _ancorar(projeto, item)
        if ancora and _cobre({"ini": ancora["ini"], "fim": ancora["fim"]}, cena):
            return item
    return None


def situacao(projeto, cena, itens=None) -> str:
    """Para o editor: "pronta", "desligada", "desatualizada", "possivel" (dá para animar) ou "".
    itens: as animações em dia (validas), quando quem chama já tem a lista."""
    if da_cena(projeto, cena, itens) is not None:
        return "pronta"
    item = _item_por_tempo(projeto, cena)
    if item is not None:
        return "desligada" if item.get("desligada") else "desatualizada"
    if (cena.get("animacao") or {}).get("desligada"):
        return "desligada" if cena.get("visual") in tipos(projeto) else ""
    return "possivel" if elegivel(projeto, cena) else ""


def elegivel(projeto, cena, pedida=False) -> bool:
    """A cena é de um tipo que se anima e tem fala. Cena em que a pessoa escolheu ficar com a foto só volta a ser
    animada se ela pedir. A imagem da cena não importa: a animação vai por cima de qualquer uma."""
    if (cena.get("animacao") or {}).get("desligada") and not pedida:
        return False
    if (cena.get("midia") or {}).get("fonte") in ("motion_ia", "animation_ai"):
        return False  # a cena já é um clipe de motion (motion_ia.py): uma camada por cima embolaria os dois
    return cena.get("visual") in tipos(projeto) and bool((cena.get("texto") or "").strip())


# ---------------------------------------------------------------------------------------------- o pedido

INSTRUCOES = """Você é diretor de motion design de documentários para o YouTube. Escolhe a animação de UM trecho de
um vídeo narrado e preenche os textos dela. A animação vai por cima das imagens do vídeo, que seguem passando por
baixo, escurecidas. O design já está pronto na fábrica, no estilo editorial e limpo da Apple e da Netflix: você só
escolhe o modelo que melhor conta o que a narração diz e preenche os dados dele.

Modelos e o formato exato de "dados" de cada um:
""" + CATALOGO + """
Como escolher: número com o que ele mede -> numero; dois lados opostos -> contraste; um assunto que une várias coisas
-> radial; enumeração -> lista; processo em etapas -> fluxo; datas ou épocas -> linha_do_tempo; lugar, distância ou
rota -> mapa; afirmação de impacto sem nada disso -> frase. Use o pedido do diretor de arte como pista, mas quem manda
é o que a narração deste trecho diz.

O TEMPO MANDA: todo "t" é o segundo em que aquela palavra é falada, tirado da lista de tempos do pedido. Cada elemento
entra quando é falado, nunca antes. Elemento que não é falado no trecho (um rótulo, um título) entra junto com a
palavra mais próxima do sentido dele.

Textos: português do Brasil, com acentos. Curtos (veja os limites de cada campo). Só o que a narração diz ou o fato
direto dela; nunca invente número, data ou nome. Títulos e rótulos em poucas palavras.
"""

ESQUEMA = {
    "type": "object",
    "properties": {"modelo": {"type": "string", "enum": list(MODELOS)}, "dados": {"type": "object"}},
    "required": ["modelo", "dados"],
    "additionalProperties": False,
}


def _pedido(item, ancora, vizinhas, erros):
    palavras = [(p["texto"], t) for p, t in zip(ancora["palavras"], _tempos(ancora))]
    pedido = item.get("pedido") or {}
    linhas = [
        f"Tipo pedido pelo agente de roteiro: {item.get('visual')}",
        f"Duração do trecho: {ancora['fim'] - ancora['ini']:.2f} s",
        f"Narração deste trecho: \"{item.get('texto', '')}\"",
        "Tempo de cada palavra (segundos dentro do trecho): " + ", ".join(f"{p} {t:.2f}" for p, t in palavras),
        f"Frases anteriores: \"{vizinhas[0]}\"" if vizinhas[0] else "",
        f"Frase seguinte: \"{vizinhas[1]}\"" if vizinhas[1] else "",
        f"O que o diretor de arte pediu: {pedido.get('mostrar')}" if pedido.get("mostrar") else "",
        f"Texto sugerido para a tela: {pedido.get('texto_tela')}" if pedido.get("texto_tela") else "",
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


def _montar_html(partes, dur, largura, altura, estilo) -> str:
    """A página da camada: fundo transparente, o véu escuro que entra e sai, e o conteúdo do modelo."""
    dur = round(dur, 3)
    cores = "".join(f"--{k}: {v};" for k, v in estilo.items() if k != "escurecer")
    saida = max(dur - 0.35, 0.0)
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
      html, body {{ width: {largura}px; height: {altura}px; overflow: hidden; background: transparent; }}
      #root {{ position: relative; width: 100%; height: 100%; overflow: hidden; }}
      #veu {{ position: absolute; inset: 0; background: rgba(8, 6, 4, {float(estilo.get("escurecer", 0.62)):.2f}); }}
      #conteudo {{ position: absolute; inset: 0; padding: 110px 110px 210px 110px; font-family: "Texto", sans-serif;
                   color: var(--texto); }}
      /* do trecho */
{partes["css"]}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="{largura}" data-height="{altura}">
      <div id="veu"></div>
      <section id="conteudo" class="clip" data-start="0" data-duration="{dur}" data-track-index="1">
{partes["html"]}
      </section>
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      tl.fromTo("#veu", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.4, ease: "power2.out" }}, 0);
      (function () {{
{partes["js"]}
      }})();
      tl.to("#root", {{ opacity: 0, duration: 0.3, ease: "power2.in" }}, {saida:.2f});
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


# ---------------------------------------------------------------------------------------------- a pasta

def _pasta(projeto, item) -> Path:
    return projeto.pasta / "animacoes" / "motion" / item["id"]


def _preparar_pasta(pasta) -> None:
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


def _hyperframes(projeto, args, pasta, limite):
    npx = node_pronto()
    versao = config(projeto).get("versao", VERSAO_PADRAO)
    ambiente = {**os.environ, "DO_NOT_TRACK": "1", "HYPERFRAMES_NO_TELEMETRY": "1", "HYPERFRAMES_SKIP_SKILLS": "1"}
    return subprocess.run([npx, "--yes", f"hyperframes@{versao}", *args], cwd=pasta, env=ambiente,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=limite)


# texto fora da tela ou fora do card: o HyperFrames marca só como informação, mas num clipe de tela inteira é defeito
# (cena 8 do natureza-teste-1min: o número dentro do card com left: 1192px, contado da borda do card, saiu da tela)
_ESTOURO_NO_CLIPE = ("canvas_overflow", "text_box_overflow")


def _conferir(projeto, pasta, clipe=False) -> list:
    """Os erros que a conferência do HyperFrames achou (texto sobreposto, saindo da tela, regras quebradas).
    clipe=True para a página de tela inteira e fundo opaco do motion_ia.py: vale o contraste, e texto fora da tela ou
    fora do card reprova mesmo marcado só como informação."""
    r = _hyperframes(projeto, ["check", "--json"], pasta, 300)
    try:
        dados = json.loads(r.stdout[r.stdout.find("{"):])
    except ValueError:
        return [f"a conferência não rodou: {(r.stderr or r.stdout)[-300:]}"]
    erros, vistos = [], set()
    # contraste fica de fora: com o fundo transparente, a conferência mede o texto contra o nada; o véu escuro
    # da camada garante a leitura sobre qualquer imagem
    for parte in ("lint", "runtime", "layout", "motion") + (("contrast",) if clipe else ()):
        for f in (dados.get(parte) or {}).get("findings", []):
            estouro = clipe and f.get("code") in _ESTOURO_NO_CLIPE
            if f.get("severity") == "error" or estouro:
                if estouro:
                    if (f.get("code"), f.get("selector")) in vistos:
                        continue  # o mesmo texto aparece em cada momento conferido: basta uma vez
                    vistos.add((f.get("code"), f.get("selector")))
                quando = f" em {f['time']:.2f}s" if isinstance(f.get("time"), (int, float)) else ""
                texto = f" (\"{f['text'][:40]}\")" if f.get("text") else ""
                erros.append(f"{f.get('code')}{quando} no {f.get('selector', '?')}{texto}: {f.get('message', '')} "
                             f"Como corrigir: {f.get('fixHint', '')}".strip())
    return erros


def _renderizar(projeto, pasta, destino) -> bool:
    """MOV ProRes 4444, com transparência: o render põe por cima das cenas."""
    temporario = destino.with_name(destino.stem + ".tmp.mov")
    r = _hyperframes(projeto, ["render", "--output", str(temporario), "--format", "mov", "--fps", "30",
                               "--workers", "1", "--quiet"], pasta, 900)
    if r.returncode != 0 or not temporario.exists() or temporario.stat().st_size < 1000:
        temporario.unlink(missing_ok=True)
        return False
    temporario.replace(destino)
    return True


# ------------------------------------------------------------------------------------------- a duração

def _textos_na_tela(dados) -> list:
    """(texto, segundo em que entra) de cada elemento escrito da animação."""
    saida = []

    def andar(x):
        if isinstance(x, dict):
            if "t" in x:
                texto = " ".join(str(x[k]) for k in ("rotulo", "texto", "nome", "detalhe") if isinstance(x.get(k), str))
                try:
                    saida.append((texto.strip(), float(x["t"])))
                except (TypeError, ValueError):
                    pass
            for v in x.values():
                if isinstance(v, (dict, list)):
                    andar(v)
        elif isinstance(x, list):
            for v in x:
                andar(v)
    andar(dados)
    return saida


def duracao_do_conteudo(projeto, dados, limite=None) -> float:
    """Quanto a animação fica na tela: o bastante para ler tudo o que está escrito, de 3 a 8 segundos.

    O último elemento fica ao menos 1,5 s depois de entrar, e o conjunto o tempo de ler todas as palavras desde o
    primeiro. limite: segundos até a próxima animação, que ela nunca cobre."""
    cfg = config(projeto)
    minima = float(cfg.get("duracao_minima", DURACAO_MINIMA))
    maxima = float(cfg.get("duracao_maxima", DURACAO_MAXIMA))
    elementos = _textos_na_tela(dados)
    if elementos:
        palavras = sum(len(texto.split()) or 1 for texto, _ in elementos)
        primeiro = min(t for _, t in elementos)
        ultimo = max(t for _, t in elementos)
        precisa = max(ultimo + 1.5, primeiro + 1.2 + SEGUNDOS_POR_PALAVRA * palavras) + 0.35  # 0,35 s da saída
        # o último elemento sempre ganha tempo de ser visto, mesmo que a fala do trecho passe do máximo
        dur = min(max(precisa, minima), max(maxima, ultimo + 1.2))
    else:
        dur = minima
    if limite is not None:
        dur = min(dur, max(limite, 0.5))
    return round(dur, 2)


# --------------------------------------------------------------------------------- de cenas para animações

def _novo_item(cenas_do_trecho, palavras) -> dict | None:
    """Uma animação nova para cenas seguidas, presa às palavras que elas falam."""
    primeira, ultima = cenas_do_trecho[0], cenas_do_trecho[-1]
    sel = [p for p in palavras if p.get("c") is not None and primeira["ini"] - 0.05 <= p["ini"] < ultima["fim"]]
    if not sel:
        return None
    depois = next((p for p in palavras if p["ini"] >= ultima["fim"] - 0.05 and p["ini"] > sel[-1]["ini"]), None)
    texto = " ".join(p["texto"] for p in sel)
    mostrar = " / ".join(dict.fromkeys(c.get("mostrar") or "" for c in cenas_do_trecho if c.get("mostrar")))
    telas = []
    for c in cenas_do_trecho:
        t = c.get("texto_tela") or c.get("overlay") or ""
        if isinstance(t, dict):
            t = " ".join(str(t.get(k) or "") for k in ("titulo", "texto")).strip()
        if t:
            telas.append(t)
    return {
        "id": f"m{sel[0]['c']:06d}",
        "c_ini": sel[0]["c"], "c_fim": sel[-1]["c"],
        "texto": texto, "fala_normal": _normal(texto),
        "folga_ini": round(max(sel[0]["ini"] - primeira["ini"], 0.0), 3),
        "folga_fim": round(max(depois["ini"] - ultima["fim"], 0.0), 3) if depois else 0.0,
        "cauda": round(max(ultima["fim"] - sel[-1]["ini"], 0.5), 3),
        "visual": primeira.get("visual"),
        "pedido": {"mostrar": mostrar, "texto_tela": " / ".join(dict.fromkeys(telas))},
        "cenas_origem": [c["n"] for c in cenas_do_trecho],
    }


def _trechos(projeto, cenas, candidatas) -> list:
    """Agrupa cenas de animação seguidas, do mesmo bloco, em trechos de até duracao_maxima segundos."""
    maximo = float(config(projeto).get("duracao_maxima", DURACAO_MAXIMA))
    trechos, atual = [], []
    for c in sorted(candidatas, key=lambda c: c["ini"]):
        if atual and (abs(c["ini"] - atual[-1]["fim"]) <= 0.1 and c.get("bloco") == atual[-1].get("bloco")
                      and c["fim"] - atual[0]["ini"] <= maximo):
            atual.append(c)
            continue
        if atual:
            trechos.append(atual)
        atual = [c]
    if atual:
        trechos.append(atual)
    return trechos


def _reaproveitar_antiga(projeto, cena):
    """Projeto de antes da camada: a animação da cena tinha modelo e dados em animacoes/NNNN/partes.json. Os tempos
    eram contados do começo da cena, o mesmo começo da animação nova de uma cena só."""
    antiga = cena.get("animacao") or {}
    arquivo = projeto.pasta / "animacoes" / f"{cena['n']:04d}" / "partes.json"
    if not antiga.get("modelo") or not arquivo.exists():
        return None
    try:
        guardada = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return guardada if guardada.get("modelo") == antiga["modelo"] else None


def _remapear(dados, antigos, novos):
    """Leva cada "t" para a mesma palavra no tempo novo (a voz mudou de ritmo)."""
    if not antigos or not novos:
        return dados

    def um(t):
        try:
            t = float(t)
        except (TypeError, ValueError):
            return t
        k = min(range(len(antigos)), key=lambda i: abs(antigos[i] - t))
        if len(antigos) == len(novos):
            return novos[k] + (t - antigos[k])
        return t * (novos[-1] / antigos[-1]) if antigos[-1] else t

    def andar(x):
        if isinstance(x, dict):
            return {k: (um(v) if k == "t" else andar(v)) for k, v in x.items()}
        if isinstance(x, list):
            return [andar(v) for v in x]
        return x
    return andar(dados)


# ---------------------------------------------------------------------------------------------- a etapa

def _animar(projeto, item, vizinhas, forcar, log, limite=None):
    """Faz (ou reaproveita) uma animação. Devolve (item atualizado, situação) ou (None, motivo).

    limite: segundos do começo desta animação até o começo da seguinte."""
    from . import openrouter_local

    ancora = _ancorar(projeto, item)
    if ancora is None:
        return None, "a fala desta animação não existe mais"
    largura, altura = _tamanho(projeto)
    estilo = _estilo(projeto)
    da_fala = _ancorar(projeto, item, pela_fala=True)
    dur = da_fala["fim"] - da_fala["ini"]  # os tempos dos elementos ficam dentro da fala do trecho
    tempos = _tempos(ancora)
    fala = " ".join([vizinhas[0], item.get("texto", ""), vizinhas[1]])
    item = {**item, "c_ini": ancora["c_ini"], "c_fim": ancora["c_fim"]}

    def desenhar(modelo, dados):
        """Escreve a página da camada com a duração pelo conteúdo e devolve essa duração."""
        duracao = duracao_do_conteudo(projeto, dados, limite)
        (pasta / "index.html").write_text(
            _montar_html(partes_do_modelo(modelo, dados, duracao), duracao, largura, altura, estilo), encoding="utf-8")
        return duracao

    destino_atual = projeto.pasta / item["arquivo"] if item.get("arquivo") else None
    if (not forcar and item.get("modelo") and destino_atual and destino_atual.exists()
            and item.get("render") == _assinatura_render(projeto, item, ancora)):
        return item, "já estava pronta"
    pasta = _pasta(projeto, item)
    pasta.mkdir(parents=True, exist_ok=True)
    _preparar_pasta(pasta)
    escolha = None
    if not forcar and item.get("modelo") in MODELOS:
        # a mesma fala: só o tempo (outra voz) ou o design mudou, então reaproveita o que o modelo escolheu
        dados = _remapear(item.get("dados"), item.get("tempos") or [], tempos)
        dados, erros = conferir_dados(item["modelo"], dados, dur, tempos, fala)
        if not erros:
            duracao = desenhar(item["modelo"], dados)
            if not _conferir(projeto, pasta):
                escolha = {"modelo": item["modelo"], "dados": dados, "duracao": duracao}
    if escolha is None:
        erros = []
        for tentativa in range(int(config(projeto).get("tentativas", 3))):
            resposta = openrouter_local.perguntar(
                projeto, "animação da cena", INSTRUCOES, _pedido(item, ancora, vizinhas, erros), ESQUEMA, log=log,
                modelo=openrouter_local.principal(projeto), temperatura=0.4 if tentativa else 0.2)
            modelo = str(resposta.get("modelo") or "").strip()
            dados, erros = conferir_dados(modelo, resposta.get("dados"), dur, tempos, fala)
            if not erros:
                duracao = desenhar(modelo, dados)
                erros = _erros_para_o_modelo(_conferir(projeto, pasta))
            if not erros:
                escolha = {"modelo": modelo, "dados": dados, "duracao": duracao}
                break
            erros = erros[:6]
        if escolha is None:
            return None, "reprovada na conferência: " + "; ".join(erros)[:300]
    item = {**item, **escolha, "tempos": tempos}
    ancora = _ancorar(projeto, item)  # com a duração nova
    assinatura = _assinatura_render(projeto, item, ancora)
    destino = projeto.pasta / "animacoes" / "motion" / f"{item['id']}_{assinatura}.mov"
    if not _renderizar(projeto, pasta, destino):
        return None, "o HyperFrames não conseguiu renderizar"
    for velho in destino.parent.glob(f"{item['id']}_*.mov"):
        if velho != destino:
            velho.unlink(missing_ok=True)
    item.update(arquivo=destino.relative_to(projeto.pasta).as_posix(), render=assinatura, desligada=False)
    return item, "feita"


def gerar(projeto, numeros=None, forcar=False, log=print, trava=None, so_existentes=False) -> dict:
    """Faz as animações que faltam e põe em dia as que a fala mudou. numeros: só as das cenas indicadas.
    so_existentes: só põe em dia as que já existem, sem animar cena nova.

    Nunca para o vídeo: o trecho que não deu para animar segue com a foto e o texto na tela. trava fica na assinatura
    para o servidor: as animações não gravam mais no cenas.json, só em animacoes/motion.json."""
    resumo = {"feitas": [], "prontas": [], "falharam": {}, "motivo": ""}
    if not ligada(projeto):
        resumo["motivo"] = "animações desligadas (animacoes.ativo no config.yaml) ou projeto offline"
        return resumo
    if not node_pronto():
        resumo["motivo"] = "falta o Node.js 22 ou mais nesta máquina (nodejs.org): as cenas seguem com foto"
        log(f"  animações: {resumo['motivo']}")
        return resumo
    if not projeto.existe("cenas.json") or not _palavras_do_projeto(projeto):
        return resumo
    cenas = projeto.ler_json("cenas.json")["cenas"]
    palavras = _palavras_do_projeto(projeto)
    itens = ler(projeto)

    # animações cuja fala sumiu (o roteiro mudou) saem; as cenas daquele trecho voltam a ser candidatas
    vivos = []
    for item in itens:
        if _ancorar(projeto, item) is None:
            log(f"  animação '{item.get('texto', '')[:40]}' saiu: a fala dela não existe mais")
        else:
            vivos.append(item)
    if len(vivos) != len(itens):
        with _TRAVA_ARQUIVO:
            _salvar(projeto, vivos)
    itens = vivos
    cobertas = {}
    for item in itens:
        # pela fala: a cena de animação logo depois, que a camada anterior cobre só pela duração, ganha a dela
        ancora = _ancorar(projeto, item, pela_fala=True)
        for c in cenas:
            if _cobre(ancora, c):
                cobertas[c["n"]] = item

    alvo = []
    if numeros is None:
        alvo = [i for i in itens if not i.get("desligada")]
        livres = [] if so_existentes else [c for c in cenas if c["n"] not in cobertas and elegivel(projeto, c)]
    else:
        alvo = list({id(cobertas[n]): cobertas[n] for n in numeros if n in cobertas}.values())
        livres = [c for c in cenas if c["n"] in numeros and c["n"] not in cobertas and elegivel(projeto, c, pedida=True)]
    for trecho in _trechos(projeto, cenas, livres):
        novo = _novo_item(trecho, palavras)
        if novo is None:
            continue
        if len(trecho) == 1:
            antiga = _reaproveitar_antiga(projeto, trecho[0])
            if antiga:
                novo.update(modelo=antiga["modelo"], dados=antiga.get("dados"))
        alvo.append(novo)
    if not alvo:
        return resumo
    textos = {c["n"]: (c.get("texto") or "").strip() for c in cenas}
    # cada animação vai até, no máximo, o começo da seguinte (as que já existem e as que vão ser feitas agora)
    comecos = sorted({a["ini"] for a in (_ancorar(projeto, i, pela_fala=True)
                                          for i in [*itens, *alvo] if not i.get("desligada")) if a}
                     | {ini for ini, _ in _cenas_motion_ia(projeto)})  # nem o começo de um clipe do Motion IA
    log(f"  animando {len(alvo)} trecho(s) de diagrama, texto na tela, linha do tempo e mapa (HyperFrames)")

    def uma(item):
        ancora = _ancorar(projeto, item, pela_fala=True) or {"ini": 0, "fim": 0}
        seguinte = next((t for t in comecos if t > ancora["ini"] + 0.05), None)
        limite = seguinte - ancora["ini"] - 0.15 if seguinte is not None else None
        antes_cenas = [c for c in cenas if c["fim"] <= ancora["ini"] + 0.05][-3:]
        depois_cena = next((c for c in cenas if c["ini"] >= ancora["fim"] - 0.05), None)
        vizinhas = (" ".join(textos[c["n"]] for c in antes_cenas).strip()[-300:],
                    textos.get(depois_cena["n"], "") if depois_cena else "")
        try:
            novo, situacao_ = _animar(projeto, item, vizinhas, forcar, log, limite)
        except (Exception, SystemExit) as erro:
            novo, situacao_ = None, f"falhou: {str(erro)[:200]}"
        return item, novo, situacao_

    with ThreadPoolExecutor(max(1, int(config(projeto).get("paralelo", 2)))) as executor:
        for item, novo, situacao_ in executor.map(uma, alvo):
            ancora = _ancorar(projeto, item)
            nums = [c["n"] for c in cenas if ancora and sobreposta(ancora, c)] or item.get("cenas_origem") or []
            if novo is None:
                for n in nums:
                    resumo["falharam"][n] = situacao_
                log(f"  animação '{item.get('texto', '')[:40]}': ficou sem, seguem as fotos ({situacao_})")
                continue
            if situacao_ == "já estava pronta":
                resumo["prontas"].extend(nums)
                continue
            _atualizar_item(projeto, novo)
            resumo["feitas"].extend(nums)
            log(f"  animação pronta por cima das cenas {', '.join(map(str, nums))} ({novo.get('visual')})")
    log(f"  animações: {len(resumo['feitas'])} cena(s) com animação nova, {len(resumo['prontas'])} já em dia, "
        f"{len(resumo['falharam'])} seguem com foto")
    return resumo


def por_em_dia(projeto, log=print) -> None:
    """Redesenha as animações que já existem e ficaram desatualizadas (outra voz, design ou duração novos), sem
    animar cena nova e, quando dá, sem perguntar de novo ao modelo. O render chama antes de montar: sem isso, a
    animação desatualizada sumia do vídeo sem aviso. Nunca para o render."""
    try:
        if not ligada(projeto) or not node_pronto():
            return
        em_dia = {i["id"] for i in validas(projeto)}
        if any(not i.get("desligada") and i["id"] not in em_dia and _ancorar(projeto, i) for i in ler(projeto)):
            gerar(projeto, log=log, so_existentes=True)
    except (Exception, SystemExit) as erro:
        log(f"  animações: não deu para pôr em dia ({str(erro)[:160]}); seguem as que estão prontas")


def remover_item(projeto, ident) -> list:
    """Exclui do vídeo a animação ident (ou todas, com ident "todos"), pela faixa Motion do editor. Ela fica marcada
    desligada em motion.json, e a criação não anima de novo aquele trecho; as cenas por baixo voltam a mostrar o
    texto na tela delas. Devolve os ids excluídos. O vídeo pronto só muda no próximo render."""
    with _TRAVA_ARQUIVO:
        itens = ler(projeto)
        alvo = [i for i in itens if not i.get("desligada") and (ident == "todos" or i["id"] == ident)]
        for item in alvo:
            item["desligada"] = True
        if alvo:
            _salvar(projeto, itens)
    if len(alvo) == 1 and projeto.existe("cenas.json"):
        # a pessoa preferiu a foto nesse trecho: vira exemplo para o agente de roteiro do canal (como "Voltar para a
        # foto"). Excluir todas de uma vez não ensina nada sobre trecho nenhum
        from . import aprendizados
        ancora = _ancorar(projeto, alvo[0], pela_fala=True)
        cena = next((c for c in projeto.ler_json("cenas.json")["cenas"] if ancora and _cobre(ancora, c)), None)
        if cena is not None:
            try:
                aprendizados.registrar(projeto, cena, "foto")
            except (OSError, ValueError, KeyError):
                pass
    return [i["id"] for i in alvo]


def remover(projeto, n, trava=None) -> None:
    """A animação por cima da cena sai e fica assim: a criação não anima de novo sozinha. Os arquivos ficam."""
    cena = next((c for c in projeto.ler_json("cenas.json")["cenas"] if c["n"] == n), None)
    if cena is None:
        return
    with _TRAVA_ARQUIVO:
        itens = ler(projeto)
        item = _item_por_tempo(projeto, cena, itens)
        if item is None:
            # ninguém por cima: um marcador desligado no tempo da cena, para a criação não animar de novo
            item = _novo_item([cena], _palavras_do_projeto(projeto))
            if item is None:
                return
            itens.append(item)
        item["desligada"] = True
        _salvar(projeto, itens)
    from . import aprendizados
    aprendizados.registrar(projeto, cena, "foto")


# ------------------------------------------------------------------------------------ a prévia do editor

def previa_da_camada(projeto, item, criar=False):
    """Para o editor: a animação inteira em WebM com transparência (VP9 com canal alfa), leve, que o player toca
    numa faixa própria por cima das cenas, no tempo da fala.

    Antes o editor recebia uma montagem por cena (a imagem da cena com o pedaço da animação por cima): na troca de
    cena a animação reiniciava ou sumia, embora no vídeo final ela seguisse inteira. O nome leva a assinatura do
    render: animação refeita ganha prévia nova. Sem criar, só devolve se já existir."""
    mov = Path(item["arquivo"])
    if not mov.is_absolute():
        mov = projeto.pasta / mov
    if not mov.exists():
        return None
    destino = projeto.pasta / "_previas" / "motion" / f"{item['id']}_{item.get('render') or 'x'}.webm"
    if destino.exists() or not criar:
        return destino if destino.exists() else None
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(f"{destino.stem}.{threading.get_ident()}.tmp.webm")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mov), "-an",
           "-vf", "scale=1280:720,fps=30,format=yuva420p", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
           "-auto-alt-ref", "0", "-b:v", "0", "-crf", "34", "-deadline", "realtime", "-cpu-used", "8",
           str(temporario)])
    for velho in destino.parent.glob(f"{item['id']}_*.webm"):
        if velho != destino and ".tmp." not in velho.name:
            velho.unlink(missing_ok=True)
    temporario.replace(destino)
    return destino
