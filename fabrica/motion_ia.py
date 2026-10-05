"""Motion IA: cena abstrata reprovada pelo Jev vira um clipe de motion graphics, no lugar da imagem (PRD-MOTION.txt).

Quando a imagem de banco de uma cena é reprovada e a cena iria para a imagem de IA, mas a fala não cita nada que se
fotografe (um número, uma ideia, uma conclusão, uma chamada para o canal), a fábrica pede a um modelo gratuito o HTML
de uma animação no padrão "Apple Event" (fundo escuro, muito espaço vazio, tipografia cinética, curva de frenagem
suave, movimento contínuo) e o HyperFrames grava um MP4 com a duração exata da cena, quadro a quadro, num Chrome
escondido. O MP4 entra como a mídia da cena (midia.fonte "motion_ia"), igual a um vídeo de banco, e o editor mostra o
selo "Motion IA". A pessoa continua podendo trocar a mídia como em qualquer cena.

Cena que cita um animal, uma pessoa, um lugar ou um objeto continua indo para a imagem de IA: a regra de precisão
literal não muda (o rinoceronte continua sendo um rinoceronte). Decisão do usuário em 2026-10-04.

Custo zero: só os modelos gratuitos da cadeia de principais (ou motion_ia.modelos no config.yaml), com no máximo
motion_ia.max_por_minuto pedidos por minuto. Nunca para o vídeo: falhou, a cena segue o caminho de antes (a imagem de
IA, se estava errada, ou a foto que tinha, se só tinha nota baixa).

O modelo escreve o HTML livre (decisão do usuário), dentro de um esqueleto fixo da fábrica que dá a ele a linha do
tempo do GSAP (tl), as fontes e o tamanho da tela, e expõe window.seekToFrame para a gravação. O código confere o que
volta (nada de animação CSS, relógio, sorteio, endereço externo ou emoji) e o HyperFrames confere texto saindo da tela
ou sobreposto; o que reprovar volta para o modelo, até motion_ia.tentativas.
"""
import hashlib
import json
import os
import re
import shutil
import threading
import time
import unicodedata
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import animacoes
from .util import rodar

FONTE = "motion_ia"
TIPOS_SEM_MOTION = ("personagem",)
_TRAVA_PEDIDOS = threading.Lock()
_PEDIDOS = deque()  # horários dos últimos pedidos aos modelos, para o limite por minuto
_TRAVA_CENAS = threading.Lock()


def config(projeto) -> dict:
    """motion_ia do config.yaml, com JEV_MOTION_FALLBACK_ENABLED e JEV_MIN_SCORE_THRESHOLD (0 a 10) do .env por cima."""
    cfg = dict(projeto.config.get("motion_ia") or {})
    ligado = os.environ.get("JEV_MOTION_FALLBACK_ENABLED")
    if ligado is not None:
        cfg["ativo"] = ligado.strip().lower() in ("1", "true", "sim", "yes")
    limiar = os.environ.get("JEV_MIN_SCORE_THRESHOLD")
    if limiar:
        try:
            cfg["nota_minima"] = float(limiar) * 10  # o PRD fala de 0 a 10; o Jev da fábrica dá de 0 a 100
        except ValueError:
            pass
    return cfg


def ligado(projeto) -> bool:
    return bool(config(projeto).get("ativo", True)) and not projeto.offline


def nota_minima(projeto) -> float:
    from .midia import nota_minima_da_conferencia
    return float(config(projeto).get("nota_minima", nota_minima_da_conferencia(projeto)))


def e_motion(cena) -> bool:
    return (cena.get("midia") or {}).get("fonte") == FONTE


def modelos(projeto) -> list:
    """Só modelos gratuitos: os da lista motion_ia.modelos, ou os gratuitos da cadeia de principais."""
    from .openrouter_local import principais
    lista = config(projeto).get("modelos") or [m for m in principais(projeto) if m.endswith(":free") or m.startswith("stealth/")]
    return [m for m in lista if m]


def _esperar_vez(projeto) -> None:
    """No máximo motion_ia.max_por_minuto pedidos por minuto aos modelos gratuitos (o PRD pede 15)."""
    limite = int(config(projeto).get("max_por_minuto", 15))
    while True:
        with _TRAVA_PEDIDOS:
            agora = time.time()
            while _PEDIDOS and agora - _PEDIDOS[0] > 60:
                _PEDIDOS.popleft()
            if len(_PEDIDOS) < limite:
                _PEDIDOS.append(agora)
                return
            espera = 60 - (agora - _PEDIDOS[0]) + 0.1
        time.sleep(max(espera, 0.5))


def _perguntar(projeto, etapa, instrucoes, pedido, esquema, log, temperatura=0.4):
    """Pergunta em cascata, só pelos modelos gratuitos: o que não atender passa a vez para o seguinte."""
    from . import openrouter_local
    erro = None
    lista = modelos(projeto)
    for k, modelo in enumerate(lista):
        _esperar_vez(projeto)
        try:
            return openrouter_local._perguntar_rota(projeto, etapa, instrucoes, pedido, esquema, log, modelo, (),
                                                    temperatura, cadeia=k < len(lista) - 1)
        except (openrouter_local.RotaIndisponivel, RuntimeError, SystemExit) as e:
            erro = e
            log(f"  motion IA: {modelo} não atendeu ({str(e)[:100]})")
    raise RuntimeError(f"nenhum modelo gratuito atendeu: {erro}")


# ------------------------------------------------------------------------------------- cena abstrata ou concreta

INSTRUCOES_ABSTRATA = """Você classifica cenas de um documentário narrado. Para cada cena, diga se a fala dela cita
algo CONCRETO que se fotografa (um animal, uma pessoa, um lugar, um objeto, uma ação física de alguém ou de algo) ou se
é ABSTRATA (um número ou estatística, uma ideia, uma opinião, uma conclusão, uma comparação sem objeto, uma transição
como "e o primeiro lugar vai te surpreender", um pedido de like ou de inscrição no canal).
Na dúvida, é concreta: só é abstrata a fala em que uma foto de banco não teria o que mostrar."""

ESQUEMA_ABSTRATA = {
    "type": "object",
    "properties": {"cenas": {"type": "array", "items": {
        "type": "object", "properties": {"n": {"type": "integer"}, "abstrata": {"type": "boolean"}},
        "required": ["n", "abstrata"]}}},
    "required": ["cenas"],
}


def _assinatura_fala(cena) -> str:
    return hashlib.sha1(" ".join((cena.get("texto") or "").split()).encode()).hexdigest()[:10]


def classificar(projeto, cenas, log=print) -> dict:
    """{n: True se a cena é abstrata}. Cena com animal ou nome exato é concreta sem perguntar. A resposta fica na
    cena (abstrata, abstrata_fala) e só é perguntada de novo se a fala mudar."""
    saida, perguntar = {}, []
    for c in cenas:
        if (c.get("animal") or "").strip() or (c.get("exato") or "").strip() or c.get("personagem"):
            saida[c["n"]] = False
        elif c.get("abstrata_fala") == _assinatura_fala(c) and isinstance(c.get("abstrata"), bool):
            saida[c["n"]] = c["abstrata"]
        else:
            perguntar.append(c)
    for k in range(0, len(perguntar), 12):
        lote = perguntar[k:k + 12]
        pedido = "\n".join(f"Cena {c['n']}: fala \"{(c.get('texto') or '').strip()}\" | pedido do agente: "
                           f"{(c.get('mostrar') or '').strip()}" for c in lote)
        try:
            resposta = _perguntar(projeto, "motion IA: cena abstrata", INSTRUCOES_ABSTRATA, pedido, ESQUEMA_ABSTRATA,
                                  log, temperatura=0.0)
            for item in resposta.get("cenas") or []:
                if isinstance(item, dict) and str(item.get("n", "")).isdigit():
                    saida[int(item["n"])] = bool(item.get("abstrata"))
        except (RuntimeError, SystemExit) as e:
            log(f"  motion IA: não deu para classificar {len(lote)} cena(s), seguem como concretas ({str(e)[:100]})")
        for c in lote:
            saida.setdefault(c["n"], False)
    return saida


def _gravar_classificacao(projeto, resultado) -> None:
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        for c in dados["cenas"]:
            if c["n"] in resultado:
                c["abstrata"], c["abstrata_fala"] = bool(resultado[c["n"]]), _assinatura_fala(c)
        projeto.salvar_json("cenas.json", dados)


# ----------------------------------------------------------------------------------------- o HTML do modelo

INSTRUCOES_HTML = """Você é diretor de motion design no padrão "Apple Event". Escreve o código de UM clipe de motion
graphics para uma cena de um documentário narrado, que vai entrar no vídeo NO LUGAR de uma foto. A fala da cena é
abstrata (um número, uma ideia, uma conclusão, uma chamada): o clipe traduz essa ideia em geometria, luz e tipografia.

Você devolve três campos: css, html e js. Eles entram num esqueleto pronto da fábrica:
- a tela tem 1920x1080 e o fundo já é um gradiente radial escuro (preto absoluto para cinza-chumbo profundo);
- o seu html vai dentro de <section id="cena">, que já ocupa a tela inteira (position: relative);
- já existe a linha do tempo do GSAP 3 numa variável tl (gsap.timeline paused) e a constante DUR (duração em segundos);
- as fontes são "Texto" (Inter, sans-serif geométrica, pesos de 100 a 900) e "Titulo" (Playfair Display);
- a fábrica já aplica um zoom lento contínuo na cena inteira: você não precisa fazer isso.

REGRAS INEGOCIÁVEIS (o código confere e devolve o que quebrar):
1. TODA animação é feita no tl, com a posição em segundos: tl.fromTo(seletor, {de}, {para, duration, ease}, segundo).
   Nada de @keyframes, animation ou transition no CSS; nada de setTimeout, setInterval, requestAnimationFrame,
   Date, Math.random, fetch, imagens ou endereços externos. Tudo tem que terminar antes de DUR - 0.3.
2. Curva de movimento: use ease "expo.out" (equivale a cubic-bezier(0.16, 1, 0.3, 1)) ou "power4.out". Proibido
   "linear", "none" e "power1.inOut".
3. Textos NUNCA surgem de uma vez: palavra por palavra (cada palavra num <span>, entrando em sequência, 0.06 a 0.12 s
   uma da outra) ou revelados de baixo para cima com clip-path.
4. Tipografia: só "Texto" (Inter). Contraste extremo de pesos (100 ou 200 contra 800 ou 900). No máximo 12 palavras
   visíveis no clipe, TODAS tiradas da fala da cena (a palavra-chave, o número). Nada de frase inventada.
5. Minimalismo: no mínimo 70% da tela vazia. Margem de 120 px dos lados e de cima, e os 240 px de baixo livres (é onde
   fica a legenda). Nada pode sair da tela nem encostar em outro elemento.
6. Sem emojis, ícones figurativos, desenhos de objetos ou cliparts: só geometria abstrata (linhas, círculos, anéis,
   barras, grades, pontos, arcos em SVG ou div), luz (brilhos com radial-gradient e box-shadow suaves) e tipografia.
   Crescimento: geometria fluida que sobe. Foco ou isolamento: círculos concêntricos. Comparação: dois blocos.
7. Vidro: elemento por cima de outro pode usar backdrop-filter: blur(15px) e borda de 1px rgba(255,255,255,0.12).
8. Cores: branco quente (#F3EBDD) no texto, um único destaque (#E8A33D) e cinzas. Nada de cores saturadas.
9. Todo id e classe começa com "m-". Nada de position fixed."""

ESQUEMA_HTML = {
    "type": "object",
    "properties": {"css": {"type": "string"}, "html": {"type": "string"}, "js": {"type": "string"}},
    "required": ["css", "html", "js"],
}

_PROIBIDOS = [
    (r"@keyframes|(?<![-\w])animation\s*:|(?<![-\w])transition\s*:", "animação ou transição em CSS (tudo vai no tl)"),
    (r"setTimeout|setInterval|requestAnimationFrame", "relógio do navegador (tudo vai no tl)"),
    (r"Math\.random|Date\.now|new Date", "sorteio ou hora (o vídeo tem que sair igual sempre)"),
    (r"https?://|url\(\s*['\"]?(?!#)", "endereço externo ou imagem"),
    (r"fetch\(|XMLHttpRequest|import\s*\(", "chamada de rede"),
    (r"ease\s*:\s*['\"](?:linear|none|power1\.inOut)['\"]", "curva proibida (use expo.out ou power4.out)"),
    (r"position\s*:\s*fixed", "position fixed"),
    (r"<script|</section|<body|<html|<head", "tag de documento dentro do html (só o conteúdo da cena)"),
]
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")


def problemas_do_codigo(partes) -> list:
    """O que o código acha de errado no que o modelo devolveu, antes de gastar um render."""
    erros = []
    tudo = "\n".join(str(partes.get(k) or "") for k in ("css", "html", "js"))
    for padrao, motivo in _PROIBIDOS:
        if re.search(padrao, tudo, re.I):
            erros.append(f"tem {motivo}")
    if _EMOJI.search(tudo):
        erros.append("tem emoji")
    if "tl." not in str(partes.get("js") or ""):
        erros.append("o js não anima nada no tl")
    if not str(partes.get("html") or "").strip():
        erros.append("o html está vazio")
    if len(tudo) > 20000:
        erros.append("o código passou de 20.000 caracteres: simplifique")
    return erros


def _palavras_inventadas(partes, fala) -> list:
    """Palavras do html que a fala não diz (tirando números, que podem vir escritos de outro jeito)."""
    texto = re.sub(r"<[^>]+>", " ", str(partes.get("html") or ""))
    normal = lambda t: unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()
    ditas = set(re.findall(r"[a-z]+", normal(fala)))
    return [p for p in re.findall(r"[a-z]{4,}", normal(texto)) if p not in ditas][:6]


def montar_html(partes, dur, largura=1920, altura=1080) -> str:
    """O esqueleto da fábrica com o que o modelo escreveu dentro."""
    dur = round(dur, 3)
    return f"""<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={largura}, height={altura}" />
    <script src="{animacoes.GSAP}"></script>
    <style>
      @font-face {{ font-family: "Titulo"; src: url("assets/fontes/PlayfairDisplay.ttf"); font-weight: 400 900; }}
      @font-face {{ font-family: "Texto"; src: url("assets/fontes/Inter.ttf"); font-weight: 100 900; }}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {largura}px; height: {altura}px; overflow: hidden; background: #050505; }}
      #root {{ position: relative; width: 100%; height: 100%; overflow: hidden;
               background: radial-gradient(ellipse at 50% 42%, #1f1f22 0%, #0c0c0e 55%, #030303 100%);
               font-family: "Texto", system-ui, sans-serif; color: #F3EBDD; }}
      #cena {{ position: relative; width: 100%; height: 100%; transform-origin: 50% 45%; }}
      /* do modelo */
{partes.get("css") or ""}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="{largura}" data-height="{altura}">
      <section id="cena" class="clip" data-start="0" data-duration="{dur}" data-track-index="1">
{partes.get("html") or ""}
      </section>
    </div>
    <script>
      const DUR = {dur};
      const tl = gsap.timeline({{ paused: true }});
      (function () {{
{partes.get("js") or ""}
      }})();
      // micro-movimento contínuo: a cena nunca fica parada (PRD, item 5.C)
      tl.fromTo("#cena", {{ scale: 1.0 }}, {{ scale: 1.05, duration: DUR, ease: "power1.out" }}, 0);
      window.__timelines["main"] = tl;
      // gravação quadro a quadro (PRD, item 5.C): o HyperFrames usa a linha do tempo; isto é para quem gravar por fora
      window.seekToFrame = function (frame, total, fps) {{ tl.seek(frame / (fps || 30)); }};
    </script>
  </body>
</html>
"""


def _pedido(cena, dur, vizinhas, erros):
    linhas = [f"Fala desta cena: \"{(cena.get('texto') or '').strip()}\"",
              f"Duração: {dur:.2f} s (DUR)",
              f"Proporção: 16:9, 1920x1080"]
    if vizinhas[0]:
        linhas.append(f"Fala anterior (só contexto): \"{vizinhas[0]}\"")
    if vizinhas[1]:
        linhas.append(f"Fala seguinte (só contexto): \"{vizinhas[1]}\"")
    if (cena.get("mostrar") or "").strip():
        linhas.append(f"Ideia visual sugerida pelo diretor de arte (traduza em geometria abstrata): {cena['mostrar'].strip()}")
    if erros:
        linhas.append("\nA resposta anterior foi REPROVADA por estes motivos. Corrija todos:\n- " + "\n- ".join(erros[:8]))
    return "\n".join(linhas)


# ------------------------------------------------------------------------------------------------- uma cena

def _pasta(projeto, n) -> Path:
    return projeto.pasta / "motion_ia" / f"{n:04d}"


def gerar_cena(projeto, cena, vizinhas, log=print):
    """Faz o clipe de uma cena. Devolve o caminho relativo do MP4, ou levanta RuntimeError com o motivo."""
    if not animacoes.node_pronto():
        raise RuntimeError("falta o Node.js 22 ou mais (o HyperFrames grava o clipe)")
    dur = max(float(cena["fim"]) - float(cena["ini"]), 1.0)
    pasta = _pasta(projeto, cena["n"])
    pasta.mkdir(parents=True, exist_ok=True)
    animacoes._preparar_pasta(pasta)
    erros, aprovado = [], None
    for tentativa in range(int(config(projeto).get("tentativas", 3))):
        resposta = _perguntar(projeto, "motion IA: html", INSTRUCOES_HTML, _pedido(cena, dur, vizinhas, erros),
                              ESQUEMA_HTML, log, temperatura=0.5 if tentativa else 0.3)
        partes = {k: str(resposta.get(k) or "") for k in ("css", "html", "js")}
        erros = problemas_do_codigo(partes)
        inventadas = _palavras_inventadas(partes, " ".join([vizinhas[0], cena.get("texto") or "", vizinhas[1]]))
        if inventadas:
            erros.append("usa palavras que a fala não diz (" + ", ".join(inventadas) + "): só palavras da fala")
        if erros:
            continue
        (pasta / "index.html").write_text(montar_html(partes, dur), encoding="utf-8")
        erros = animacoes._erros_para_o_modelo(animacoes._conferir(projeto, pasta))
        if not erros:
            aprovado = partes
            break
    if aprovado is None:
        raise RuntimeError("reprovado na conferência: " + "; ".join(erros)[:300])
    (pasta / "partes.json").write_text(json.dumps(aprovado, ensure_ascii=False, indent=1), encoding="utf-8")
    destino = projeto.pasta / "midia" / f"{cena['n']:04d}_motion.mp4"
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.stem + ".tmp.mp4")
    r = animacoes._hyperframes(projeto, ["render", "--output", str(temporario), "--format", "mp4", "--fps",
                                         str(int(config(projeto).get("fps", 30))), "--workers", "1", "--quiet"],
                               pasta, 900)
    if r.returncode != 0 or not temporario.exists() or temporario.stat().st_size < 1000:
        temporario.unlink(missing_ok=True)
        raise RuntimeError(f"o HyperFrames não gravou o clipe: {(r.stderr or r.stdout or '')[-200:]}")
    temporario.replace(destino)
    capa = destino.with_name(f"{cena['n']:04d}_motion_capa.jpg")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{min(dur * 0.6, dur - 0.1):.2f}", "-i", str(destino),
           "-frames:v", "1", "-q:v", "3", str(capa)])
    # o HTML é só um passo: fica o partes.json, para refazer ou conferir depois
    (pasta / "index.html").unlink(missing_ok=True)
    return destino, capa, dur


def _aplicar(projeto, n, destino, capa, dur) -> None:
    """O clipe entra como a mídia da cena, igual a um vídeo de banco. O que a cena tinha fica em motion_reserva."""
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        c = next(x for x in dados["cenas"] if x["n"] == n)
        c["motion_reserva"] = {k: c.get(k) for k in ("midia", "tipo", "busca", "captura", "conferencia", "ia_reserva")}
        c["midia"] = {"fonte": FONTE, "id": f"{n:04d}-{int(time.time())}", "tipo": "video",
                      "arquivo": destino.relative_to(projeto.pasta).as_posix(),
                      "capa": capa.relative_to(projeto.pasta).as_posix() if capa.exists() else None,
                      "autor": "", "licenca": "feito pela fábrica", "pagina": "", "duracao": round(dur, 2)}
        c["tipo"] = "video_real"
        c["captura"] = {"conferida": True, "motion_ia": True}
        for campo in ("sem_midia_real", "conferencia", "motion_ia_falhou", "motion_so"):
            c.pop(campo, None)
        projeto.salvar_json("cenas.json", dados)


def _marcar_falha(projeto, n, motivo) -> None:
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        c = next((x for x in dados["cenas"] if x["n"] == n), None)
        if c is not None:
            c["motion_ia_falhou"] = {"motivo": motivo[:300], "fala": _assinatura_fala(c)}
            projeto.salvar_json("cenas.json", dados)


# ---------------------------------------------------------------------------------------------- a etapa

def candidatas(projeto, cenas) -> list:
    """Cenas que iriam para a imagem de IA e podem virar motion: sem prompt ou imagem da pessoa, sem personagem e sem
    uma falha de motion na mesma fala."""
    saida = []
    for c in cenas:
        falha = c.get("motion_ia_falhou") or {}
        if (c.get("prompt_manual") or c.get("imagem_da_pessoa") or c.get("personagem") or e_motion(c)
                or falha.get("fala") == _assinatura_fala(c) or not (c.get("texto") or "").strip()):
            continue
        saida.append(c)
    return saida


def resolver(projeto, pendentes, log=print) -> list:
    """As cenas pendentes de imagem de IA que são abstratas viram clipe de motion. Devolve as cenas resolvidas.

    Chamado por imagens._gerar antes de gerar qualquer imagem: vale para a criação, a conferência e o diretor."""
    if not ligado(projeto) or not pendentes:
        return []
    cands = candidatas(projeto, pendentes)
    if not cands:
        return []
    if not modelos(projeto):
        log("  motion IA: nenhum modelo gratuito configurado, as cenas seguem para a imagem de IA")
        return []
    if not animacoes.node_pronto():
        log("  motion IA: falta o Node.js 22 ou mais, as cenas seguem para a imagem de IA")
        return []
    tipos = classificar(projeto, cands, log)
    _gravar_classificacao(projeto, tipos)
    abstratas = [c for c in cands if tipos.get(c["n"])]
    if not abstratas:
        return []
    log(f"  motion IA: {len(abstratas)} cena(s) abstrata(s) viram clipe de motion, de graça: "
        + ", ".join(str(c["n"]) for c in abstratas))
    todas = {c["n"]: c for c in projeto.ler_json("cenas.json")["cenas"]}

    def uma(c):
        antes, depois = todas.get(c["n"] - 1) or {}, todas.get(c["n"] + 1) or {}
        vizinhas = ((antes.get("texto") or "").strip()[-200:], (depois.get("texto") or "").strip()[:200])
        try:
            destino, capa, dur = gerar_cena(projeto, c, vizinhas, log)
            _aplicar(projeto, c["n"], destino, capa, dur)
            return c["n"], None
        except (Exception, SystemExit) as erro:
            return c["n"], str(erro) or erro.__class__.__name__

    feitas = []
    with ThreadPoolExecutor(max(1, int(config(projeto).get("paralelo", 2)))) as executor:
        for n, erro in executor.map(uma, abstratas):
            if erro is None:
                feitas.append(n)
                log(f"  motion IA: cena {n} pronta")
            else:
                _marcar_falha(projeto, n, erro)
                log(f"  motion IA: cena {n} não saiu ({erro[:160]}); segue o caminho de antes")
    return feitas


def desfazer(projeto, n) -> bool:
    """A cena volta para o que tinha antes do motion (o editor, ou um teste). O clipe fica em midia/."""
    with _TRAVA_CENAS:
        dados = projeto.ler_json("cenas.json")
        c = next((x for x in dados["cenas"] if x["n"] == n), None)
        if c is None or not e_motion(c) or not c.get("motion_reserva"):
            return False
        reserva = c.pop("motion_reserva")
        for campo, valor in reserva.items():
            if valor is None:
                c.pop(campo, None)
            else:
                c[campo] = valor
        projeto.salvar_json("cenas.json", dados)
    return True
