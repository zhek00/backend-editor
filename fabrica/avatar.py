"""Avatar falante.

Dois caminhos. A DreamAPI, com o DreamAvatar 3.0 Fast do DreamFace, gera o vídeo pela
API a partir de uma foto e um áudio. O HeyGen, pelo plano do canal, recebe a narração
cortada em partes de até 30 minutos e devolve um vídeo por parte. As partes entram no
render como um quadro no canto da tela, do jeito de aula online.
"""
import hashlib
import json
import re
import time
from pathlib import Path

import httpx

from .config import chave
from .util import duracao_audio, rodar

BASE = "https://api.newportai.com/api"
LIMITE_MINUTOS = 29.5  # o HeyGen aceita vídeos de até 30 minutos
POSICOES = {"inferior-direito", "inferior-esquerdo", "superior-direito", "superior-esquerdo"}


def modo(perfil) -> str:
    """quadro mostra o personagem o vídeo inteiro num canto. trechos só onde o roteiro marca [AVATAR]."""
    return ((perfil.get("avatar") or {}).get("modo") or "quadro").lower()


def caminho_fixo(perfil, nome, extensao=".mp4"):
    from .config import caminho_relativo

    pasta = (perfil.get("avatar") or {}).get("pasta_fixos", "avatar_fixos")
    return caminho_relativo(pasta) / f"{nome}{extensao}"


def duracao_fixo(perfil, nome):
    """Duração do clipe fixo. Antes de o vídeo existir, vale a do áudio que vai gerar ele."""
    for extensao in (".mp4", ".mp3"):
        arquivo = caminho_fixo(perfil, nome, extensao)
        if arquivo.exists():
            return duracao_audio(arquivo)
    raise SystemExit(f"Não achei o clipe fixo '{nome}' em {caminho_fixo(perfil, nome).parent}")


def legendas_fixo(perfil, nome, largura=38, linhas=1):
    """Pedaços de legenda de um clipe fixo, contados do começo do clipe.

    O texto vem do .txt salvo ao lado do clipe. Como não existe o tempo de cada letra,
    o texto é espalhado pelos trechos em que há fala, na proporção do tamanho de cada pedaço.
    """
    import textwrap

    from . import texto as tx

    video, arquivo_texto = caminho_fixo(perfil, nome), caminho_fixo(perfil, nome, ".txt")
    if not (video.exists() and arquivo_texto.exists()):
        return []
    pedacos = []
    for unidade in tx.unidades(tx.normalizar(arquivo_texto.read_text(encoding="utf-8"))):
        quebradas = textwrap.wrap(unidade.texto, largura) or [unidade.texto]
        pedacos += ["\n".join(quebradas[k:k + linhas]) for k in range(0, len(quebradas), linhas)]
    falas = _trechos_de_fala(video)
    total = sum(b - a for a, b in falas)
    if not pedacos or total <= 0:
        return []

    def no_tempo(fracao, comeco):
        """Segundo do clipe que corresponde a essa fração da fala, pulando os silêncios."""
        alvo = fracao * total
        for a, b in falas:
            if alvo < b - a or (not comeco and alvo <= b - a):
                return a + alvo
            alvo -= b - a
        return falas[-1][1]

    pesos = [len(p.replace("\n", " ")) for p in pedacos]
    soma, acumulado, resultado = sum(pesos), 0, []
    for pedaco, peso in zip(pedacos, pesos):
        inicio = no_tempo(acumulado / soma, True)
        acumulado += peso
        resultado.append((round(inicio, 3), round(no_tempo(acumulado / soma, False), 3), pedaco))
    return resultado


def _trechos_de_fala(arquivo):
    duracao = duracao_audio(arquivo)
    r = rodar(["ffmpeg", "-hide_banner", "-i", arquivo, "-vn", "-af", "silencedetect=noise=-38dB:d=0.25", "-f", "null", "-"])
    inicios = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)] + [duracao]
    falas, cursor = [], 0.0
    for a, b in zip(inicios, fins):
        if a - cursor > 0.05:
            falas.append((cursor, a))
        cursor = max(cursor, b)
    if duracao - cursor > 0.05:
        falas.append((cursor, duracao))
    return falas


def somente_avatar(perfil) -> bool:
    """Vídeo em que o personagem fala o tempo todo, sem cenas de imagem."""
    return bool((perfil.get("avatar") or {}).get("somente_avatar"))


def janelas(projeto):
    """Trechos do vídeo em que o personagem aparece na tela, em ordem.

    Cada janela é um trecho falado marcado com [AVATAR] no roteiro, gerado no HeyGen a partir
    da narração, ou um clipe fixo encaixado com [INSERTO nome]. Num vídeo só de avatar a
    narração inteira é uma janela só.
    """
    if somente_avatar(projeto.perfil):
        duracao = projeto.ler_json("alinhamento.json")["duracao"]
        return [{"tipo": "trecho", "n": 1, "ini": 0.0, "fim": duracao,
                 "audio": "avatar/trecho_1.mp3", "video": "avatar/trecho_1.mp4"}]
    marcadores = projeto.ler_json("alinhamento.json").get("marcadores") or []
    resultado, aberto, n = [], None, 0
    for m in marcadores:
        if m["tipo"] == "avatar_inicio":
            aberto = m["ini"]
        elif m["tipo"] == "avatar_fim" and aberto is not None:
            n += 1
            resultado.append({"tipo": "trecho", "n": n, "ini": aberto, "fim": m["ini"],
                              "audio": f"avatar/trecho_{n}.mp3", "video": f"avatar/trecho_{n}.mp4"})
            aberto = None
        elif m["tipo"] == "inserto":
            arquivo = caminho_fixo(projeto.perfil, m["texto"])
            resultado.append({"tipo": "inserto", "nome": m["texto"], "ini": m["ini"],
                              "fim": m["ini"] + duracao_fixo(projeto.perfil, m["texto"]),
                              "video": str(arquivo), "audio": str(arquivo.with_suffix(".mp3"))})
    resultado.sort(key=lambda j: j["ini"])
    # quando um clipe fixo vem logo depois de um trecho falado, o personagem continua na tela
    # durante o respiro entre os dois, em vez de a imagem voltar por meio segundo
    for atual, seguinte in zip(resultado, resultado[1:]):
        if atual["tipo"] == "trecho" and seguinte["tipo"] == "inserto" and 0 < seguinte["ini"] - atual["fim"] <= 1.5:
            atual["fim"] = seguinte["ini"]
    return resultado


def fatias(projeto, log=print):
    """Corta da narração o áudio de cada trecho falado pelo personagem, para subir no HeyGen."""
    narracao = projeto.pasta / "narracao.wav"
    trechos = [j for j in janelas(projeto) if j["tipo"] == "trecho"]
    for j in trechos:
        destino = projeto.caminho(j["audio"])
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", narracao, "-ss", f"{j['ini']:.3f}",
               "-to", f"{j['fim']:.3f}", "-c:a", "libmp3lame", "-b:a", "128k", destino])
        log(f"  {j['audio']}  {j['fim'] - j['ini']:.1f}s")
    return trechos


def faltando(projeto):
    """Vídeos do personagem que ainda não estão na pasta, seja trecho do HeyGen ou clipe fixo."""
    pendentes = []
    for j in janelas(projeto):
        arquivo = Path(j["video"]) if j["tipo"] == "inserto" else projeto.pasta / j["video"]
        if not arquivo.exists():
            pendentes.append(j)
    fecho = (projeto.perfil.get("avatar") or {}).get("fechamento")
    if fecho and not caminho_fixo(projeto.perfil, fecho).exists():
        pendentes.append({"tipo": "fechamento", "nome": fecho, "video": str(caminho_fixo(projeto.perfil, fecho))})
    return pendentes


def dividir_narracao(projeto, limite_minutos=LIMITE_MINUTOS):
    """Corta a narração em partes de até limite_minutos, sempre numa pausa entre frases.

    Cada parte vira um mp3 para subir no HeyGen. O arquivo partes.json guarda onde cada
    uma começa e termina, e é por ele que o render encaixa os vídeos de volta no tempo.
    """
    alinhamento = projeto.ler_json("alinhamento.json")
    unidades, duracao = alinhamento["unidades"], alinhamento["duracao"]
    limite = float(limite_minutos) * 60
    trechos, inicio = [], 0.0
    for i, u in enumerate(unidades):
        if i and u["fim"] - inicio > limite:
            corte = round((unidades[i - 1]["fim"] + u["ini"]) / 2, 3)
            if corte > inicio:
                trechos.append((inicio, corte))
                inicio = corte
    trechos.append((inicio, duracao))

    narracao = projeto.pasta / "narracao.wav"
    partes = []
    for n, (a, b) in enumerate(trechos, 1):
        audio = projeto.caminho("avatar", f"parte_{n}.mp3")
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", narracao, "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
               "-c:a", "libmp3lame", "-b:a", "128k", audio])
        partes.append({"n": n, "ini": a, "fim": round(b, 3), "audio": f"avatar/parte_{n}.mp3", "video": f"avatar/parte_{n}.mp4"})
    projeto.salvar_json("avatar/partes.json", {"partes": partes, "limite_minutos": limite_minutos})
    return partes


def partes_faltando(projeto):
    """Vídeos do HeyGen que ainda não estão na pasta do projeto."""
    if not projeto.existe("avatar/partes.json"):
        return None
    return [p for p in projeto.ler_json("avatar/partes.json")["partes"] if not (projeto.pasta / p["video"]).exists()]


def preparar_pip(projeto, cfg_render, log=print):
    """Monta o quadro do avatar para o render.

    Junta os vídeos do HeyGen num só, no tamanho do quadro e alinhado ao tempo da narração,
    e desenha a máscara da forma e a moldura. Devolve os arquivos e a posição na tela.
    """
    from PIL import Image, ImageDraw

    cfg = projeto.perfil.get("avatar") or {}
    partes = projeto.ler_json("avatar/partes.json")["partes"]
    largura_tela, altura_tela, fps = cfg_render.get("largura", 1920), cfg_render.get("altura", 1080), cfg_render.get("fps", 30)
    escala = largura_tela / 1920
    forma = cfg.get("forma", "retangulo")
    largura = round(largura_tela * float(cfg.get("largura", 0.17)))
    primeiro = projeto.pasta / partes[0]["video"]
    lv, av = _dimensoes(primeiro)
    # o HeyGen entrega em paisagem com o rosto no meio, então o quadro recorta a proporção pedida
    if forma == "circulo":
        alvo = 1.0
    elif cfg.get("proporcao"):
        l, _, a = str(cfg["proporcao"]).partition(":")
        alvo = float(l) / float(a or 1)
    else:
        alvo = lv / av
    largura = round(largura / 2) * 2
    altura = round(largura / alvo / 2) * 2

    # o vídeo do HeyGen pode começar com um silêncio diferente do áudio enviado
    entradas, grafo = [], []
    for k, p in enumerate(partes):
        video = projeto.pasta / p["video"]
        deslocamento = _inicio_da_fala(video) - _inicio_da_fala(projeto.pasta / p["audio"])
        tamanho = p["fim"] - p["ini"]
        entradas += ["-ss", f"{max(deslocamento, 0):.3f}", "-i", video]
        filtro = ""
        if abs(alvo - lv / av) > 0.01:
            centro = float(cfg.get("centro_rosto", 0.42))
            filtro += (f"crop=w='min(iw,ih*{alvo:.6f})':h='min(ih,iw/{alvo:.6f})':x='(iw-ow)/2':"
                       f"y='max(0,min(ih-oh,ih*{centro}-oh/2))',")
        filtro += f"scale={largura}:{altura},setsar=1,fps={fps},"
        if deslocamento < -0.02:
            filtro += f"tpad=start_duration={-deslocamento:.3f}:start_mode=clone,"
        filtro += f"trim=duration={tamanho:.3f},tpad=stop_mode=clone:stop_duration={tamanho:.3f},trim=duration={tamanho:.3f},setpts=PTS-STARTPTS"
        grafo.append(f"[{k}:v]{filtro}[v{k}]")
        if abs(deslocamento) > 0.05:
            log(f"  parte {p['n']} do avatar ajustada em {deslocamento:+.2f}s")
    grafo.append("".join(f"[v{k}]" for k in range(len(partes))) + f"concat=n={len(partes)}:v=1:a=0[v]")

    assinatura = hashlib.sha1(json.dumps([
        [(p["video"], (projeto.pasta / p["video"]).stat().st_mtime_ns, p["ini"], p["fim"]) for p in partes],
        largura, altura, forma, cfg.get("centro_rosto"), cfg.get("proporcao"), fps,
    ]).encode()).hexdigest()[:10]
    continuo = projeto.caminho("render", f"avatar_continuo-{assinatura}.mp4")
    if not continuo.exists():
        log("  juntando os vídeos do avatar")
        temporario = continuo.with_name(continuo.stem + ".tmp.mp4")
        rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(grafo), "-map", "[v]",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-an", temporario])
        temporario.replace(continuo)
    for velho in continuo.parent.glob("avatar_continuo-*.mp4"):
        if velho != continuo:
            velho.unlink()

    # máscara da forma, em cinza, e moldura por cima
    raio = round(float(cfg.get("raio", 28)) * escala)
    borda = round(float(cfg.get("borda", 3)) * escala)
    cor_borda = cfg.get("cor_borda", "#C9A45C")
    mascara = Image.new("L", (largura, altura), 0)
    moldura = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    caixa = [0, 0, largura - 1, altura - 1]
    if forma == "circulo":
        ImageDraw.Draw(mascara).ellipse(caixa, fill=255)
        if borda:
            ImageDraw.Draw(moldura).ellipse(caixa, outline=cor_borda, width=borda)
    else:
        ImageDraw.Draw(mascara).rounded_rectangle(caixa, radius=raio, fill=255)
        if borda:
            ImageDraw.Draw(moldura).rounded_rectangle(caixa, radius=raio, outline=cor_borda, width=borda)
    arquivo_mascara = projeto.caminho("render", "avatar_mascara.png")
    arquivo_moldura = projeto.caminho("render", "avatar_moldura.png")
    mascara.save(arquivo_mascara)
    moldura.save(arquivo_moldura)

    posicao = cfg.get("posicao", "inferior-direito")
    if posicao not in POSICOES:
        raise SystemExit(f"avatar.posicao inválida no perfil. Use uma destas: {', '.join(sorted(POSICOES))}")
    margem = round(float(cfg.get("margem", 48)) * escala)
    x = margem if posicao.endswith("esquerdo") else largura_tela - largura - margem
    y = margem if posicao.startswith("superior") else altura_tela - altura - margem
    return {"video": continuo, "mascara": arquivo_mascara, "moldura": arquivo_moldura, "x": x, "y": y,
            "largura": largura, "altura": altura}


def _dimensoes(video):
    r = rodar(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", video])
    fluxo = json.loads(r.stdout)["streams"][0]
    return int(fluxo["width"]), int(fluxo["height"])


def _inicio_da_fala(arquivo):
    """Segundo em que a fala começa, para conferir se o HeyGen acrescentou ou tirou silêncio do começo."""
    r = rodar(["ffmpeg", "-hide_banner", "-t", "20", "-i", arquivo, "-af", "silencedetect=noise=-35dB:d=0.25", "-f", "null", "-"])
    inicios = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    if inicios and fins and inicios[0] <= 0.05:
        return fins[0]
    return 0.0
CREDITOS_POR_SEGUNDO = {"480p": 2, "720p": 4}
DOLAR_POR_CREDITO = 60 / 8000  # pacote mínimo de US$ 60 com 8.000 créditos
PROMPT_PADRAO = (
    "An elderly man speaking calmly and seriously to the camera, subtle natural head movements "
    "and blinking, like a documentary narrator."
)
TIPOS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
         ".mp3": "audio/mpeg", ".wav": "audio/wav", ".mp4": "video/mp4"}


def custo(audio, resolucao):
    creditos = duracao_audio(audio) * CREDITOS_POR_SEGUNDO[resolucao]
    return creditos, creditos * DOLAR_POR_CREDITO


def criar_video(imagem, audio, destino, prompt=PROMPT_PADRAO, resolucao="720p", log=print):
    imagem, audio, destino = Path(imagem), Path(audio), Path(destino)
    log("  enviando foto e áudio para a DreamAPI")
    imagem_url = enviar_arquivo(imagem)
    audio_url = enviar_arquivo(audio)
    log("  gerando o avatar")
    dados = _pedir(f"{BASE}/async/dreamavatar/image_to_video/3.0fast",
                   {"image": imagem_url, "audio": audio_url, "prompt": prompt, "resolution": resolucao}, "criar o avatar")
    url = _aguardar(dados["taskId"], log)
    r = httpx.get(url, timeout=300, follow_redirects=True)
    r.raise_for_status()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(r.content)
    return destino


def enviar_arquivo(caminho):
    """Sobe um arquivo local para o armazenamento da DreamAPI e devolve o link público dele."""
    politica = _pedir(f"{BASE}/file/v1/get_policy", {"scene": "Dream-CN"}, "pedir permissão de envio")
    objeto = politica["key"]
    if objeto.endswith("/"):
        objeto += caminho.name
    campos = {  # a ordem importa, e o arquivo precisa ser o último campo
        "success_action_status": "200",
        "policy": politica["policy"],
        "OSSAccessKeyId": politica["OSSAccessKeyId"],
        "signature": politica["signature"],
        "key": objeto,
        "callback": politica["callback"],
    }
    arquivo = {"file": (caminho.name, caminho.read_bytes(), TIPOS.get(caminho.suffix.lower(), "application/octet-stream"))}
    r = httpx.post(politica["host"], data=campos, files=arquivo, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"A DreamAPI recusou o envio de {caminho.name} ({r.status_code}). {r.text[:300]}")
    return f"{politica['host'].rstrip('/')}/{objeto}"


def _aguardar(task_id, log, limite=900):
    inicio = time.time()
    while time.time() - inicio < limite:
        dados = _pedir(f"{BASE}/getAsyncResult", {"taskId": task_id}, "consultar o avatar")
        tarefa = dados.get("task") or {}
        if tarefa.get("status") == 3:
            videos = dados.get("videos") or []
            if not videos:
                raise RuntimeError("A DreamAPI terminou a tarefa sem entregar vídeo.")
            return videos[0]["videoUrl"]
        if tarefa.get("status") == 4:
            raise RuntimeError(f"A DreamAPI não conseguiu gerar o avatar. {tarefa.get('reason') or ''}")
        time.sleep(5)
    raise RuntimeError("O avatar passou de 15 minutos sem ficar pronto.")


def _cabecalho():
    return {"Authorization": f"Bearer {chave('DREAMAPI_KEY')}", "Content-Type": "application/json"}


class Ocupada(RuntimeError):
    """A DreamAPI está com fila cheia, o que acontece com contas grátis em horário de pico."""


def _pedir(url, corpo, etapa, tentativas=8):
    """Faz o pedido e, se a DreamAPI estiver ocupada, espera cada vez mais e tenta de novo."""
    for tentativa in range(tentativas):
        try:
            return _checar(httpx.post(url, headers=_cabecalho(), json=corpo, timeout=60), etapa)
        except Ocupada:
            if tentativa == tentativas - 1:
                raise RuntimeError(f"A DreamAPI ficou ocupada demais para {etapa}. Tente mais tarde ou coloque créditos na conta.")
            time.sleep(min(30 * (tentativa + 1), 180))


def _checar(resposta, etapa):
    if resposta.status_code in (401, 403):
        raise SystemExit("A DreamAPI recusou a chave. Confira DREAMAPI_KEY no .env.")
    resposta.raise_for_status()
    dados = resposta.json()
    if dados.get("code") not in (0, None):
        mensagem = str(dados.get("message") or dados)
        if "busy" in mensagem.lower() or "queued" in mensagem.lower():
            raise Ocupada(mensagem)
        raise RuntimeError(f"A DreamAPI falhou ao {etapa}. {mensagem}")
    return dados.get("data") or {}
