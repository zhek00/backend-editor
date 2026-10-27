"""Montagem do vídeo com FFmpeg.

Cada cena vira um clipe com a duração exata dela.
Imagens de IA e fotos reais ganham movimento lento de câmera. Foto com formato muito
diferente da tela fica numa moldura sobre um fundo desfocado dela mesma.
Vídeo real é cortado no tamanho da cena e desacelerado quando é curto.
Textos animados entram por cima de cada clipe no momento em que são narrados.
Depois os clipes são emendados e recebem narração, música e legenda.
"""
import hashlib
import json
import os
import random
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import abertura, animacoes, animation_ai, avatar, efeitos, motion_ia, rostos, textos, trilha
from .config import caminho_relativo
from .util import duracao_audio, rodar

MOVIMENTOS = ("aproximar", "afastar", "direita", "esquerda")
EXTENSOES_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
ESTILO_LEGENDA = (
    "FontName=Arial,FontSize=10,PrimaryColour=&H00FFFFFF,OutlineColour=&HA0000000,"
    "BorderStyle=1,Outline=1,Shadow=0,MarginV=18"
)
# na tela em pé a legenda sobe para o terço de baixo, acima dos botões e da descrição do Shorts e do Reels
ESTILO_LEGENDA_VERTICAL = (
    "FontName=Arial,FontSize=9,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&HC0000000,"
    "BorderStyle=1,Outline=1.4,Shadow=0,MarginL=24,MarginR=24,MarginV=72"
)


def origem_da_cena(projeto, cena, vertical=False):
    midia = cena.get("midia")
    if midia:
        arquivo = projeto.pasta / midia["arquivo"]
        if vertical and animation_ai.e_animada(cena):
            # a cena dirigida (direcao.py) tem um clipe próprio para a tela em pé, recomposto e não cortado
            em_pe = arquivo.with_name(arquivo.stem + "_vertical.mp4")
            if em_pe.exists():
                return "video", em_pe
        return ("video" if midia["tipo"] == "video" else "foto"), arquivo
    return "foto", projeto.imagem(cena["n"])


def com_avatar(projeto, sem_avatar=False) -> bool:
    return bool((projeto.perfil.get("avatar") or {}).get("ativo")) and not sem_avatar


def configuracao(projeto, vertical=False):
    """Ajustes do render. Na versão em pé (Reels e Shorts) a tela vira 1080x1920 e vale a seção vertical do config.

    A seção vertical fica fora da seção render de propósito: os ajustes do render entram no nome de cada clipe,
    e mexer neles faria a versão deitada de todo projeto renderizar de novo."""
    cfg = dict(projeto.config.get("render") or {})
    if vertical:
        v = projeto.config.get("vertical") or {}
        cfg.update({"largura": v.get("largura", 1080), "altura": v.get("altura", 1920), "vertical": True,
                    "superamostragem": v.get("superamostragem", 2), "recorte": v.get("recorte", 1.0)})
    return cfg


def arquivo_final(projeto, vertical=False):
    return projeto.pasta / ("final_vertical.mp4" if vertical else "final.mp4")


def renderizar(projeto, log=print, sem_avatar=False, vertical=False):
    from . import tempos

    # o render inteiro e as partes dele vão para o tempos.json (pedido do usuário em 2026-10-13: medir antes de
    # acelerar)
    esperar_clipes_adiantados(projeto, log)
    with tempos.medir(projeto, "Render em pé (total)" if vertical else "Render (total)", log=log):
        return _renderizar(projeto, log, sem_avatar, vertical)


def _renderizar(projeto, log, sem_avatar, vertical):
    from . import tempos

    cfg = configuracao(projeto, vertical)
    # a versão em pé tem pastas próprias: a limpeza dos clipes velhos de uma nunca apaga os da outra
    base = "render_vertical" if vertical else "render"
    if vertical and not sem_avatar and com_avatar(projeto, False):
        log("  a versão em pé sai sem o personagem, porque o quadro dele foi pensado para a tela deitada")
    sem_avatar = sem_avatar or vertical
    fps = cfg.get("fps", 30)
    duracao = projeto.ler_json("alinhamento.json")["duracao"]
    cenas = projeto.ler_json("cenas.json")["cenas"]
    origens = [origem_da_cena(projeto, c, vertical) for c in cenas]
    trechos = []
    if com_avatar(projeto, sem_avatar):
        if avatar.modo(projeto.perfil) == "trechos":
            pendentes = avatar.faltando(projeto)
            if pendentes:
                lista = ", ".join(p["video"] for p in pendentes)
                raise SystemExit(f"Faltam vídeos do personagem ({lista}). Gere no HeyGen com os áudios da pasta avatar "
                                 f"e da pasta de clipes fixos, ou rode o render com --sem-avatar.")
            trechos = avatar.janelas(projeto)
        else:
            partes = avatar.partes_faltando(projeto)
            if partes is None:
                raise SystemExit(f"O perfil pede avatar, mas a narração ainda não foi dividida. Rode fabrica avatar-partes {projeto.nome}")
            if partes:
                lista = ", ".join(p["video"] for p in partes)
                raise SystemExit(f"Faltam os vídeos do avatar ({lista}). Gere no HeyGen com os áudios da pasta avatar, "
                                 f"ou rode o render com --sem-avatar.")

    # as animações foram desenhadas para a tela deitada; na versão em pé a cena volta à foto
    com_animacoes = bool(animacoes.config(projeto).get("ativo", True)) and not vertical
    # a camada de animação vai por cima das cenas, no tempo da fala (animacoes.py): as cenas não mudam por causa dela
    if com_animacoes:
        animacoes.por_em_dia(projeto, log=log)
    motion = animacoes.validas(projeto) if com_animacoes else []
    pasta_clipes = projeto.caminho(base, "clipes", "_").parent
    pasta_fotos = projeto.caminho(base, "fotos", "_").parent
    pasta_textos = projeto.caminho(base, "textos", "_").parent
    tarefas = []
    linha = _linha_do_tempo(projeto, cenas, origens, trechos, duracao)
    faltando = sorted({p["cena"]["n"] for p in linha if p["tipo"] == "cena" and not p["arquivo"].exists()})
    if faltando:
        lista = ", ".join(map(str, faltando[:10]))
        raise SystemExit(f"Faltam imagens ou vídeos de {len(faltando)} cenas ({lista}). Rode fabrica imagens {projeto.nome}")
    linha = _agrupar_personagem(linha)
    transicao = float((projeto.perfil.get("avatar") or {}).get("transicao", 0.35))

    # a abertura sem fala vem antes de tudo e empurra narração, música e legenda para frente
    musica_abertura = faixa_abertura = None
    quadro = com_avatar(projeto, sem_avatar) and avatar.modo(projeto.perfil) != "trechos"
    if abertura.ativa(projeto.perfil) and not avatar.somente_avatar(projeto.perfil) and not quadro:
        tarefas, musica_abertura, faixa_abertura = _abertura(projeto, cenas, origens, cfg, pasta_clipes, log, base)
    atraso = sum(t["frames"] for t in tarefas) / fps
    # a revisão do vídeo pronto (revisao_video.py) precisa saber quanto a abertura empurra cada cena no final.mp4
    projeto.salvar_json(f"{base}/linha.json", {"atraso": round(atraso, 3), "fps": fps})

    tarefas += _tarefas_da_linha(projeto, linha, cfg, pasta_clipes, transicao)

    # o fechamento é o mesmo clipe em todo vídeo do canal e entra depois da última cena
    duracao_total, extras = duracao, [(j["ini"], Path(j["video"])) for j in trechos if j["tipo"] == "inserto"]
    fecho = (projeto.perfil.get("avatar") or {}).get("fechamento") if com_avatar(projeto, sem_avatar) else None
    if fecho:
        arquivo = avatar.caminho_fixo(projeto.perfil, fecho)
        frames = max(round(duracao_audio(arquivo) * fps), 1)
        assinatura = f"fechamento|{arquivo}|{arquivo.stat().st_mtime_ns}|{frames}|{sorted(cfg.items())}"
        codigo = hashlib.sha1(assinatura.encode()).hexdigest()[:10]
        tarefas.append({"tipo": "avatar", "segmentos": [{"arquivo": arquivo, "pulo": 0.0, "dur": frames / fps}],
                        "transicao": transicao, "frames": frames,
                        "destino": pasta_clipes / f"9999-fechamento-{codigo}.mp4"})
        extras.append((duracao, arquivo))
        duracao_total = duracao + frames / fps
    sons = efeitos.na_linha_do_tempo(projeto, cenas)
    if not efeitos.ativo(projeto.perfil):
        # sem os efeitos da ElevenLabs, entram os que o código toca: passagem e impacto na troca de bloco,
        # impacto no cartão de título e um toque curto quando o texto entra na tela
        try:
            sons = trilha.efeitos_na_linha(projeto, cenas, log)
        except (Exception, SystemExit) as erro:
            log(f"  efeitos gerados ficaram de fora: {str(erro)[:160]}")
            sons = []
    # os clipes do Motion IA ganham o som de cada movimento (pop, risco, contagem, baque), com qualquer perfil
    try:
        sons = list(sons) + motion_ia.sons_na_linha(projeto, cenas, log)
        sons = list(sons) + animation_ai.sons_na_linha(projeto, cenas, log)
    except (Exception, SystemExit) as erro:
        log(f"  sons dos clipes de motion ficaram de fora: {str(erro)[:160]}")
    legenda = _legendas_finais(projeto, trechos, fecho, duracao, atraso, base)

    validos = {t["destino"].name for t in tarefas}
    for velho in pasta_clipes.glob("*.mp4"):
        if velho.name not in validos:
            velho.unlink()
    pendentes = [t for t in tarefas if not t["destino"].exists()]
    processos = cfg.get("processos") or max(1, (os.cpu_count() or 4) // 2)
    log(f"  {len(pendentes)} clipes para renderizar, {len(tarefas) - len(pendentes)} já prontos")
    with tempos.medir(projeto, "Render: clipes", clipes=len(pendentes), processos=processos),             ThreadPoolExecutor(processos) as executor:
        futuros = {executor.submit(_clipe, t, pasta_fotos, pasta_textos, projeto.perfil, cfg): t for t in pendentes}
        for i, futuro in enumerate(as_completed(futuros), 1):
            try:
                futuro.result()
            except Exception as erro:
                # sem isto o executor montava todos os outros clipes calado antes de mostrar o erro: a tela ficou
                # 20 min nos 32% no nunca-deve-ter-dentro-de-casa-parte-2, com o vídeo já perdido
                for outro in futuros:
                    outro.cancel()
                cena = (futuros[futuro].get("cena") or {}).get("n")
                onde = f"a cena {cena}" if cena else futuros[futuro]["destino"].name
                raise RuntimeError(f"Não deu para montar {onde}: {str(erro)[:600]}. Os clipes prontos ficam guardados: "
                                   f"confira a cena e renderize de novo.") from erro
            if i % 10 == 0 or i == len(futuros):
                log(f"  clipes {i}/{len(futuros)}")

    medida = tempos.medir(projeto, "Render: juntar e mixar")
    with medida:
        return _juntar(projeto, base, tarefas, extras, sons, vertical, motion, duracao_total, atraso, log, sem_avatar,
                       musica_abertura, faixa_abertura, legenda, cfg)


def _tarefas_da_linha(projeto, linha, cfg, pasta_clipes, transicao, so_prontas=False) -> list:
    """O clipe de cada pedaço da linha do tempo, com o nome que diz o que ele mostra. so_prontas: só os pedaços cujo
    arquivo já existe (adiantar_clipes), sem mudar o movimento sorteado dos outros."""
    fps = cfg.get("fps", 30)
    sorteio, anterior, tarefas = random.Random(projeto.nome), None, []
    for pedaco in linha:
        f_ini, f_fim = round(pedaco["ini"] * fps), round(pedaco["fim"] * fps)
        frames = max(f_fim - f_ini, 1)
        arquivo = pedaco["arquivo"]
        if pedaco["tipo"] == "avatar":
            if so_prontas:
                continue
            origem = [(str(s["arquivo"]), s["arquivo"].stat().st_mtime_ns, round(s["pulo"], 3), round(s["dur"], 3))
                      for s in pedaco["segmentos"]]
            assinatura = f"avatar|{origem}|{frames}|{transicao}|{sorted(cfg.items())}"
            codigo = hashlib.sha1(assinatura.encode()).hexdigest()[:10]
            tarefas.append({**pedaco, "frames": frames, "transicao": transicao,
                            "destino": pasta_clipes / f"{pedaco['ordem']:04d}-avatar-{codigo}.mp4"})
            continue
        movimento = sorteio.choice([m for m in MOVIMENTOS if m != anterior])
        anterior = movimento
        if so_prontas and not arquivo.exists():
            continue
        simbolos, titulos = pedaco["simbolos"], pedaco["titulos"]
        # o nome do clipe muda quando a origem, a duração, o movimento, o símbolo ou o título mudam. O "||" é o lugar
        # do texto na tela, que saiu da fábrica (2026-10-05): fica vazio para os clipes já prontos não mudarem de nome
        enquadramento = _enquadramento(arquivo, cfg) if pedaco["origem"] == "foto" else ""
        assinatura = (
            f"{pedaco['origem']}|{arquivo}|{arquivo.stat().st_mtime_ns}|{frames}|{movimento}|{sorted(cfg.items())}{enquadramento}|"
            f"|{textos.assinatura_simbolos(simbolos, projeto.perfil)}|"
            f"{textos.assinatura_titulos(titulos, projeto.perfil)}"
        )
        codigo = hashlib.sha1(assinatura.encode()).hexdigest()[:10]
        tarefas.append({**pedaco, "frames": frames, "movimento": movimento,
                        "destino": pasta_clipes / f"{pedaco['ordem']:04d}-{codigo}.mp4"})
    return tarefas


# clipes adiantados em segundo plano, por pasta do projeto: o render espera eles antes de começar
_adiantando = {}
_de_novo = set()


def adiantar_clipes(projeto, log=print):
    """Começa, em segundo plano, os clipes das cenas que já têm a imagem, enquanto a criação segue (imagens de IA,
    animações, trilha). O nome do clipe diz a imagem, a duração e o movimento: a cena que mudar depois ganha outro
    nome e o render faz de novo; a que não mudar já está pronta. No everything-you-need-to-answer os 340 clipes
    levaram 10 min depois de toda a criação. Usa metade dos processos do render, para não sufocar o resto, e nunca
    para a criação."""
    import threading as _t

    chave = str(projeto.pasta)
    with _trava_placa:
        anterior = _adiantando.get(chave)
        if anterior and anterior.is_alive():
            # chamado de novo com outras cenas prontas: quando a rodada de agora acabar, faz mais uma
            _de_novo.add(chave)
            return anterior

    def trabalho():
        while True:
            uma_rodada()
            with _trava_placa:
                if chave not in _de_novo:
                    return
                _de_novo.discard(chave)

    def uma_rodada():
        from . import tempos

        try:
            with tempos.medir(projeto, "Render: clipes adiantados"):
                cfg = configuracao(projeto, False)
                duracao = projeto.ler_json("alinhamento.json")["duracao"]
                cenas = projeto.ler_json("cenas.json")["cenas"]
                origens = [origem_da_cena(projeto, c, False) for c in cenas]
                trechos = avatar.janelas(projeto) if (com_avatar(projeto, False)
                                                     and avatar.modo(projeto.perfil) == "trechos") else []
                linha = _agrupar_personagem(_linha_do_tempo(projeto, cenas, origens, trechos, duracao))
                pasta_clipes = projeto.caminho("render", "clipes", "_").parent
                pasta_fotos = projeto.caminho("render", "fotos", "_").parent
                pasta_textos = projeto.caminho("render", "textos", "_").parent
                pendentes = [t for t in _tarefas_da_linha(projeto, linha, cfg, pasta_clipes, 0.35, so_prontas=True)
                             if not t["destino"].exists()]
                processos = max(1, (cfg.get("processos") or max(1, (os.cpu_count() or 4) // 2)) // 2)
                log(f"  adiantando {len(pendentes)} clipes em segundo plano")
                with ThreadPoolExecutor(processos) as executor:
                    for futuro in [executor.submit(_clipe, t, pasta_fotos, pasta_textos, projeto.perfil, cfg)
                                   for t in pendentes]:
                        try:
                            futuro.result()
                        except Exception:  # o render final faz de novo o que falhar aqui
                            pass
        except (Exception, SystemExit) as erro:
            log(f"  clipes adiantados ficaram para o render: {str(erro)[:160]}")

    fio = _t.Thread(target=trabalho, name=f"adiantar-{projeto.nome}", daemon=True)
    with _trava_placa:
        _adiantando[chave] = fio
    fio.start()
    return fio


def esperar_clipes_adiantados(projeto, log=print):
    fio = _adiantando.get(str(projeto.pasta))
    if fio and fio.is_alive():
        log("  esperando os clipes adiantados terminarem")
        fio.join()


def _juntar(projeto, base, tarefas, extras, sons, vertical, motion, duracao_total, atraso, log, sem_avatar,
            musica_abertura, faixa_abertura, legenda, cfg):
    arquivo_lista = projeto.caminho(base, "clipes.txt")
    arquivo_lista.write_text("".join(f"file '{t['destino']}'\n" for t in tarefas), encoding="utf-8")
    video = projeto.caminho(base, "video.mp4")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", arquivo_lista, "-c", "copy", video])
    partes = ["narração", "música", "legenda"] + (["personagem"] if extras else []) + (["efeitos"] if sons else [])
    log("  juntando " + ", ".join(partes[:-1]) + " e " + partes[-1])
    final = arquivo_final(projeto, vertical)
    if motion:
        log(f"  {len(motion)} animação(ões) por cima das cenas")
    _mixar(projeto, video, duracao_total + atraso, final, log, sem_avatar, extras,
           sons=sons, atraso=atraso, musica_abertura=musica_abertura, faixa_abertura=faixa_abertura, legenda=legenda,
           cfg=cfg, base=base, motion=[(m["ini"] + atraso, m["fim"] + atraso, m["arquivo"]) for m in motion])
    return final


def _abertura(projeto, cenas, origens, cfg, pasta_clipes, log, base="render"):
    """Clipes da abertura sem fala e a música dela."""
    fps = cfg.get("fps", 30)
    ajustes = abertura.configuracao(projeto.perfil)
    por_numero = {c["n"]: (origem, arquivo) for c, (origem, arquivo) in zip(cenas, origens)}
    escolhidas = abertura.escolher(projeto, cenas, lambda c: por_numero[c["n"]][1].exists(), log)
    if not escolhidas:
        return [], None, None
    frames_corte = max(round(float(ajustes.get("corte", 0.4)) * fps), 2)
    flash = bool(ajustes.get("flash", True))
    tarefas = []
    for k, n in enumerate(escolhidas):
        origem, arquivo = por_numero[n]
        ultimo = k == len(escolhidas) - 1
        frames = frames_corte + (round(0.4 * fps) if ultimo else 0)  # a última cena segura um pouco e escurece
        assinatura = f"abertura2|{origem}|{arquivo}|{arquivo.stat().st_mtime_ns}|{frames}|{flash}|{ultimo}|{sorted(cfg.items())}"
        codigo = hashlib.sha1(assinatura.encode()).hexdigest()[:10]
        tarefas.append({"tipo": "abertura", "arquivo": arquivo, "origem": origem, "frames": frames, "flash": flash,
                        "ultimo": ultimo, "destino": pasta_clipes / f"a{k:03d}-{codigo}.mp4"})
    duracao = sum(t["frames"] for t in tarefas) / fps
    faixa = abertura.faixa(projeto)
    if not faixa:
        log("  abertura sem música, porque o perfil não aponta nenhuma faixa")
        return tarefas, None, None
    inicio = abertura.trecho_mais_forte(faixa, duracao)
    bruto = projeto.caminho(base, "musica_abertura_bruta.wav")
    destino = projeto.caminho(base, "musica_abertura.wav")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-t", f"{duracao + 1:.3f}", "-i", faixa,
           "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", bruto])
    volume = ajustes.get("volume_db", -2)
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", bruto, "-af",
           f"{_normalizar(bruto)},volume={volume}dB,atrim=0:{duracao:.3f},afade=t=in:d=0.06,"
           f"afade=t=out:st={max(duracao - 0.7, 0):.3f}:d=0.7", "-c:a", "pcm_s16le", destino])
    bruto.unlink(missing_ok=True)
    log(f"  abertura com {len(tarefas)} cenas e {duracao:.1f}s de música, a partir de {inicio:.0f}s da faixa {faixa.name}")
    return tarefas, destino, faixa


def _agrupar_personagem(linha):
    """Junta pedaços seguidos do personagem num clipe só, para a troca entre dois vídeos dele ser uma fusão."""
    resultado = []
    for p in linha:
        if p["tipo"] != "avatar":
            resultado.append(p)
            continue
        segmento = {"arquivo": p["arquivo"], "pulo": p["pulo"], "dur": p["fim"] - p["ini"]}
        anterior = resultado[-1] if resultado and resultado[-1]["tipo"] == "avatar" else None
        if anterior is None:
            resultado.append({**p, "segmentos": [segmento]})
            continue
        anterior["fim"] = p["fim"]
        ultimo = anterior["segmentos"][-1]
        continua = ultimo["arquivo"] == segmento["arquivo"] and abs(ultimo["pulo"] + ultimo["dur"] - segmento["pulo"]) < 0.05
        if continua:
            ultimo["dur"] += segmento["dur"]
        else:
            anterior["segmentos"].append(segmento)
    for n, p in enumerate(resultado, 1):
        p["ordem"] = n
    return resultado


def _clipe_avatar(tarefa, destino, temporario, cfg):
    """Personagem na tela, com um ou mais vídeos dele emendados por uma fusão curta.

    O vídeo seguinte começa parado no primeiro quadro durante a fusão, então a fala dele
    continua no tempo certo do áudio.
    """
    fps = cfg.get("fps", 30)
    largura, altura = cfg.get("largura", 1920), cfg.get("altura", 1080)
    segmentos, frames = tarefa["segmentos"], tarefa["frames"]
    fusao = min(float(tarefa.get("transicao", 0.35)), min(s["dur"] for s in segmentos) / 2) if len(segmentos) > 1 else 0.0
    base = f"scale={largura}:{altura}:force_original_aspect_ratio=increase,crop={largura}:{altura},setsar=1,fps={fps}"
    entradas, grafo = [], []
    for k, s in enumerate(segmentos):
        entradas += ["-ss", f"{max(s['pulo'], 0):.3f}", "-i", s["arquivo"]]
        extra = fusao if k else 0.0
        filtro = base + (f",tpad=start_duration={extra:.3f}:start_mode=clone" if extra else "")
        filtro += (f",tpad=stop_mode=clone:stop_duration={s['dur'] + 1:.3f},trim=duration={s['dur'] + extra:.3f},"
                   "setpts=PTS-STARTPTS,format=yuv420p")
        grafo.append(f"[{k}:v]{filtro}[s{k}]")
    atual, comprimento = "s0", segmentos[0]["dur"]
    for k in range(1, len(segmentos)):
        grafo.append(f"[{atual}][s{k}]xfade=transition=fade:duration={fusao:.3f}:offset={comprimento - fusao:.3f}[x{k}]")
        atual, comprimento = f"x{k}", comprimento + segmentos[k]["dur"]
    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(grafo), "-map", f"[{atual}]",
           "-frames:v", frames, "-r", fps, "-c:v", "libx264", "-preset", "veryfast", "-crf", cfg.get("crf", 18),
           "-threads", "2", "-an", temporario])
    temporario.replace(destino)


def _clipe_abertura(tarefa, destino, temporario, pasta_fotos, cfg):
    """Cena rápida da abertura, com um empurrão de zoom e um clarão no corte."""
    fps = cfg.get("fps", 30)
    largura, altura = cfg.get("largura", 1920), cfg.get("altura", 1080)
    frames, arquivo = tarefa["frames"], tarefa["arquivo"]
    duracao = frames / fps
    if tarefa["origem"] == "video":
        entradas, filtro = _entrada_video(arquivo, frames, cfg, centro=True)
    else:
        entradas = ["-i", _preparar_foto(arquivo, pasta_fotos, cfg)]
        filtro = (f"scale={largura * 2}:{altura * 2}:force_original_aspect_ratio=increase,crop={largura * 2}:{altura * 2},"
                  f"setsar=1,zoompan=z='1.24-0.18*on/{max(frames - 1, 1)}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':"
                  f"d={frames}:s={largura}x{altura}:fps={fps},format=yuv420p")
    if tarefa["flash"]:
        filtro += ",eq=brightness='0.3*max(0,1-t/0.12)':eval=frame"  # clarão curto, sem apagar a imagem
    if tarefa["ultimo"]:
        filtro += f",fade=t=out:st={max(duracao - 0.35, 0):.3f}:d=0.35"
    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-vf", filtro, "-frames:v", frames, "-r", fps,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", cfg.get("crf", 18), "-threads", "2", "-an", temporario])
    temporario.replace(destino)


def _linha_do_tempo(projeto, cenas, origens, janelas, duracao):
    """Corta a sequência de cenas nos trechos em que o personagem aparece e devolve os pedaços em ordem."""
    limites = sorted({0.0, duracao} | {c["ini"] for c in cenas} | {t for j in janelas for t in (j["ini"], j["fim"])})
    limites = [t for t in limites if 0.0 <= t <= duracao]
    pedacos = []
    for a, b in zip(limites, limites[1:]):
        if b - a < 0.05:
            continue
        janela = next((j for j in janelas if j["ini"] - 0.01 <= a and b <= j["fim"] + 0.01), None)
        if janela:
            arquivo = Path(janela["video"]) if janela["tipo"] == "inserto" else projeto.pasta / janela["video"]
            pedacos.append({"tipo": "avatar", "ini": a, "fim": b, "arquivo": arquivo, "pulo": a - janela["ini"]})
            continue
        i = max(k for k, c in enumerate(cenas) if c["ini"] <= a + 0.01)
        c, (origem, arquivo) = cenas[i], origens[i]
        deslocamento = a - c["ini"]
        desloca = lambda lista: [x for x in lista if x is not None]
        simbolos = [round(s - deslocamento, 2) for s in (c.get("simbolos") or []) if s >= deslocamento - 0.01]
        titulos = [{**t, "inicio": round(t["inicio"] - deslocamento, 2)}
                   for t in (c.get("titulos") or []) if t["inicio"] >= deslocamento - 0.01]
        pedacos.append({"tipo": "cena", "ini": a, "fim": b, "arquivo": arquivo, "origem": origem, "cena": c,
                        "simbolos": desloca(simbolos), "titulos": titulos})
    for n, p in enumerate(pedacos, 1):
        p["ordem"] = n
    return pedacos


def _clipe(tarefa, pasta_fotos, pasta_textos, perfil, cfg):
    destino, frames, arquivo = tarefa["destino"], tarefa["frames"], tarefa.get("arquivo")
    temporario = destino.with_name(destino.stem + ".tmp.mp4")
    fps = cfg.get("fps", 30)
    largura, altura = cfg.get("largura", 1920), cfg.get("altura", 1080)
    if tarefa["tipo"] == "avatar":
        return _clipe_avatar(tarefa, destino, temporario, cfg)
    if tarefa["tipo"] == "abertura":
        return _clipe_abertura(tarefa, destino, temporario, pasta_fotos, cfg)
    if tarefa["origem"] == "video":
        entradas, filtro = _entrada_video(arquivo, frames, cfg)
    else:
        entradas, filtro = ["-i", _preparar_foto(arquivo, pasta_fotos, cfg)], _filtro_foto(tarefa["movimento"], frames, cfg)

    duracao = frames / fps
    simbolos, titulos = tarefa["simbolos"], tarefa["titulos"]
    grafo = [f"[0:v]{filtro}[b0]"]
    pasta = pasta_textos / destino.stem
    if cfg.get("vertical"):
        camadas = textos.para_vertical(textos.camadas_titulo(titulos, perfil, pasta, duracao), largura, altura, pasta, "vtt")
    else:
        camadas = textos.camadas_titulo(titulos, perfil, pasta, duracao, largura, altura)
    camadas += textos.camadas_simbolo(simbolos, perfil, pasta, duracao, largura, altura)
    for i, camada in enumerate(camadas, 1):
        entradas += ["-loop", "1", "-framerate", fps, "-t", f"{duracao:.3f}", "-i", camada["arquivo"]]
        transicao = camada.get("transicao", textos.ENTRADA)
        # vai de 1 a 0 durante a entrada, e move a camada até a posição final
        progresso = f"max(0,min(1,({camada['inicio']}+{transicao}-t)/{transicao}))"
        x = f"{camada['x']}-60*{progresso}" if camada["animacao"] == "esquerda" else str(camada["x"])
        y = f"{camada['y']}+24*{progresso}" if camada["animacao"] == "subir" else str(camada["y"])
        efeitos = f"format=rgba,fade=t=in:st={camada['inicio']}:d={transicao}:alpha=1"
        if camada.get("fim") is not None:  # camadas com fim somem devagar, como o símbolo de pausa
            efeitos += f",fade=t=out:st={max(camada['fim'] - transicao, camada['inicio']):.3f}:d={transicao}:alpha=1"
        grafo.append(f"[{i}:v]{efeitos}[c{i}]")
        grafo.append(f"[b{i - 1}][c{i}]overlay=x='{x}':y='{y}':eval=frame[b{i}]")
    grafo.append(f"[b{len(camadas)}]format=yuv420p[v]")

    rodar([
        "ffmpeg", "-y", "-loglevel", "error", *entradas,
        "-filter_complex", ";".join(grafo), "-map", "[v]", "-frames:v", frames, "-r", fps,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", cfg.get("crf", 18), "-threads", "2",
        "-an", temporario,
    ])
    temporario.replace(destino)


def _filtro_foto(movimento, frames, cfg):
    largura, altura = cfg.get("largura", 1920), cfg.get("altura", 1080)
    fator = cfg.get("superamostragem", 3)
    zoom = cfg.get("zoom_maximo", 1.12)
    progresso = f"(on/{max(frames - 1, 1)})"
    centro_x, centro_y = "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    if movimento == "aproximar":
        z, x, y = f"1+{zoom - 1:.4f}*{progresso}", centro_x, centro_y
    elif movimento == "afastar":
        z, x, y = f"{zoom:.4f}-{zoom - 1:.4f}*{progresso}", centro_x, centro_y
    elif movimento == "direita":
        z, x, y = f"{zoom:.4f}", f"(iw-iw/zoom)*{progresso}", centro_y
    else:
        z, x, y = f"{zoom:.4f}", f"(iw-iw/zoom)*(1-{progresso})", centro_y
    # ampliar antes do zoompan evita o tremido do movimento lento
    return (
        f"scale={largura * fator}:{altura * fator}:force_original_aspect_ratio=increase,"
        f"crop={largura * fator}:{altura * fator},setsar=1,"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={largura}x{altura}:fps={cfg.get('fps', 30)},"
        "format=yuv420p"
    )


def _encaixe(cfg):
    """Filtro que leva um vídeo de qualquer formato para o tamanho da tela.

    Na tela deitada o vídeo preenche e corta as sobras. Na tela em pé, cortar um vídeo deitado jogaria fora dois
    terços da imagem: ele perde as laterais só até ficar quadrado e fica sobre uma cópia dele mesmo, desfocada."""
    largura, altura = cfg.get("largura", 1920), cfg.get("altura", 1080)
    preencher = f"scale={largura}:{altura}:force_original_aspect_ratio=increase,crop={largura}:{altura},setsar=1"
    if not cfg.get("vertical"):
        return preencher
    recorte = float(cfg.get("recorte", 1.0))
    l8, a8 = largura // 8, altura // 8
    return (f"split=2[enc_a][enc_b];"
            f"[enc_a]scale={l8}:{a8}:force_original_aspect_ratio=increase,crop={l8}:{a8},boxblur=6:1,"
            f"scale={largura}:{altura},colorchannelmixer=rr=0.45:gg=0.45:bb=0.45,setsar=1[enc_fundo];"
            f"[enc_b]crop='min(iw,ih*{recorte})':ih,scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
            f"setsar=1[enc_frente];"
            f"[enc_fundo][enc_frente]overlay=(W-w)/2:(H-h)/2")


def _entrada_video(arquivo, frames, cfg, centro=False):
    largura, altura, fps = cfg.get("largura", 1920), cfg.get("altura", 1080), cfg.get("fps", 30)
    necessario = frames / fps
    disponivel = duracao_audio(arquivo)
    inicio, velocidade = 0.0, 1.0
    if centro and disponivel > necessario:
        inicio = (disponivel - necessario) / 2  # na abertura vale o miolo do vídeo, onde costuma estar a ação
    elif disponivel >= necessario + 1:
        inicio = min(1.0, (disponivel - necessario) / 2)  # pula o comecinho, que costuma ter tremida
    elif disponivel < necessario:
        velocidade = max(disponivel / necessario, 0.5)  # desacelera até a metade, depois congela o fim
    # o clipe em pé de uma cena dirigida já tem o tamanho da tela: nada de cortar nem de pôr sobre fundo desfocado
    nativo = str(arquivo).endswith("_vertical.mp4") and cfg.get("vertical")
    filtro = (f"scale={largura}:{altura}:force_original_aspect_ratio=increase,crop={largura}:{altura},setsar=1"
              if nativo else _encaixe(cfg))
    if velocidade < 1:
        filtro += f",setpts=PTS/{velocidade:.4f}"
    filtro += f",fps={fps},tpad=stop_mode=clone:stop_duration={necessario:.3f},format=yuv420p"
    return ["-ss", f"{inicio:.3f}", "-i", arquivo], filtro


def _preparar_foto(origem, pasta_fotos, cfg):
    """Foto horizontal ocupa a tela inteira. Foto em pé, quadrada ou panorâmica ganha moldura com fundo desfocado.

    Foto que ocupa a tela é recortada pelo meio, a não ser que isso corte um rosto: aí o recorte segue os rostos
    (rostos.py). No retrato do jogador da cena 16 do virou-filme-em-1996, o editor mostrava só o tronco."""
    nome, gerar = _foto_na_tela(origem, cfg)
    if gerar is None:
        return origem
    destino = pasta_fotos / f"{origem.stem}-{nome}.jpg"
    if not destino.exists():
        gerar().save(destino, quality=92)
    return destino


def _enquadramento(arquivo, cfg) -> str:
    """O que muda no nome do clipe quando a foto precisa de um recorte pelos rostos ("" quando não precisa).

    Assim só os clipes dessas fotos renderizam de novo; os outros continuam com o mesmo nome."""
    try:
        nome, gerar = _foto_na_tela(arquivo, cfg)
    except Exception:
        return ""
    return f"|{nome}" if gerar is not None and "rosto" in nome else ""


def _foto_na_tela(origem, cfg):
    """(nome, gerar) da foto como ela entra na tela. gerar é None quando a foto entra como está.

    Serve ao render (_preparar_foto) e à prévia do editor (quadro_da_foto), para os dois mostrarem a mesma coisa."""
    from PIL import Image, ImageEnhance, ImageFilter

    largura, altura = cfg.get("largura", 1920), cfg.get("altura", 1080)
    tela = largura / altura
    with Image.open(origem) as imagem:
        tamanho = (imagem.width, imagem.height)
    proporcao = tamanho[0] / tamanho[1]
    marca = f"{origem}|{origem.stat().st_mtime_ns}|r{rostos.VERSAO}"
    if tela * 0.73125 <= proporcao <= tela * 1.125:  # na tela deitada, de 1,3 a 2,0
        achados = rostos.rostos(origem)
        if not rostos.corta_rosto_no_meio(tamanho[0], tamanho[1], tela, achados):
            return "", None
        caixa = rostos.recorte(tamanho[0], tamanho[1], tela, achados)
        codigo = hashlib.sha1(f"{marca}|{tela:.4f}|{caixa}".encode()).hexdigest()[:10]

        def gerar_recorte():
            with Image.open(origem) as foto:
                return foto.convert("RGB").crop(caixa)

        return f"rosto-{codigo}", gerar_recorte
    codigo = hashlib.sha1(f"{marca}|{largura}x{altura}|{bool(cfg.get('vertical'))}".encode()).hexdigest()[:10]

    def gerar_moldura():
        with Image.open(origem) as foto:
            return _moldura(foto.convert("RGB"), origem, cfg)

    return codigo, gerar_moldura


def quadro_da_foto(origem, largura_px, cfg=None):
    """A foto do jeito que ela aparece na tela do vídeo deitado, sem o movimento lento: para a prévia do editor.

    Antes a prévia era a foto reduzida, e o editor a esticava pelo meio: o retrato perdia a cabeça na prévia, embora
    o vídeo mostrasse a foto inteira com moldura."""
    from PIL import Image

    cfg = {"largura": 1920, "altura": 1080, **(cfg or {})}
    tela = cfg["largura"] / cfg["altura"]
    _, gerar = _foto_na_tela(origem, cfg)
    if gerar is not None:
        quadro = gerar()
    else:
        with Image.open(origem) as foto:
            quadro = foto.convert("RGB")
        # entra como está: a tela corta pelo meio, do mesmo jeito que o render
        if quadro.width / quadro.height > tela:
            sobra = (quadro.width - round(quadro.height * tela)) // 2
            quadro = quadro.crop((sobra, 0, sobra + round(quadro.height * tela), quadro.height))
        else:
            sobra = (quadro.height - round(quadro.width / tela)) // 2
            quadro = quadro.crop((0, sobra, quadro.width, sobra + round(quadro.width / tela)))
    return quadro.resize((largura_px, round(largura_px / tela)), Image.LANCZOS)


def _moldura(imagem, origem, cfg):
    """Foto em pé, quadrada ou panorâmica sobre uma cópia dela mesma, desfocada, no tamanho dobrado da tela."""
    from PIL import Image, ImageEnhance, ImageFilter

    largura, altura = cfg.get("largura", 1920), cfg.get("altura", 1080)
    tela_l, tela_a = largura * 2, altura * 2
    pequeno = (tela_l // 8, tela_a // 8)
    escala = max(pequeno[0] / imagem.width, pequeno[1] / imagem.height)
    fundo = imagem.resize((max(1, round(imagem.width * escala)), max(1, round(imagem.height * escala))))
    esquerda, topo = (fundo.width - pequeno[0]) // 2, (fundo.height - pequeno[1]) // 2
    fundo = fundo.crop((esquerda, topo, esquerda + pequeno[0], topo + pequeno[1]))
    fundo = fundo.filter(ImageFilter.GaussianBlur(6)).resize((tela_l, tela_a), Image.BICUBIC)
    fundo = ImageEnhance.Brightness(fundo).enhance(0.45)

    if cfg.get("vertical"):
        # na tela em pé a foto deitada perde as laterais até ficar no máximo quadrada e ocupa a largura toda; o
        # pedaço que fica é o dos rostos, quando há
        recorte = float(cfg.get("recorte", 1.0))
        if imagem.width / imagem.height > recorte:
            caixa = rostos.recorte(imagem.width, imagem.height, recorte, rostos.rostos(origem))
            if caixa is None:
                sobra = (imagem.width - round(imagem.height * recorte)) // 2
                caixa = (sobra, 0, imagem.width - sobra, imagem.height)
            imagem = imagem.crop(caixa)
        escala = min(tela_l / imagem.width, tela_a * 0.88 / imagem.height)
    else:
        escala = min(tela_l * 0.9 / imagem.width, tela_a * 0.88 / imagem.height)
    frente = imagem.resize((round(imagem.width * escala), round(imagem.height * escala)), Image.LANCZOS)
    fundo.paste(frente, ((tela_l - frente.width) // 2, (tela_a - frente.height) // 2))
    return fundo


def _mixar(projeto, video, duracao, final, log=print, sem_avatar=False, extras=(), sons=(), atraso=0.0,
           musica_abertura=None, faixa_abertura=None, legenda=None, cfg=None, base="render", motion=()):
    cfg = cfg if cfg is not None else (projeto.config.get("render") or {})
    # voz e música chegam prontas, com o tamanho e o volume certos, e aqui só se somam
    # a trilha completa sai antes, num passo só de áudio, porque o filtro de legenda
    # atrasa os fluxos com adelay quando tudo roda no mesmo grafo
    from . import tempos

    with tempos.parte(projeto, "render: áudio (narração, música, efeitos)"):
        audio = _trilha(projeto, duracao, extras, sons, atraso, musica_abertura, faixa_abertura, base)
    entradas, partes = ["-i", video, "-i", audio], []

    atual, reencodar, pip = "0:v", False, None
    # a camada de animação (MOV transparente) entra por cima das cenas, no segundo da fala, antes do avatar e da legenda
    for k, (ini, fim, arquivo) in enumerate(motion):
        n = len(entradas) // 2
        entradas += ["-i", str(arquivo)]
        partes.append(f"[{n}:v]setpts=PTS-STARTPTS+{ini:.3f}/TB,format=yuva420p[m{k}]")
        partes.append(f"[{atual}][m{k}]overlay=eof_action=pass:format=auto:enable='between(t,{ini:.3f},{fim:.3f})'[cm{k}]")
        atual, reencodar = f"cm{k}", True
    if com_avatar(projeto, sem_avatar) and avatar.modo(projeto.perfil) != "trechos":
        # o avatar entra num quadro no canto, recortado pela máscara e com a moldura por cima
        pip = avatar.preparar_pip(projeto, cfg, log)
        n = len(entradas) // 2
        entradas += ["-i", pip["video"], "-loop", "1", "-i", pip["mascara"], "-loop", "1", "-i", pip["moldura"]]
        partes += [
            f"[{n + 1}:v]format=gray[mascara]",
            f"[{n}:v][mascara]alphamerge[avatar]",
            f"[{atual}][avatar]overlay=x={pip['x']}:y={pip['y']}:eof_action=pass[com_avatar]",
            f"[com_avatar][{n + 2}:v]overlay=x={pip['x']}:y={pip['y']}:eof_action=pass[com_moldura]",
        ]
        atual, reencodar = "com_moldura", True

    legenda = legenda or projeto.pasta / "legendas_tela.srt"
    if projeto.perfil.get("legenda_na_tela") and legenda.exists():
        estilo = projeto.perfil.get("estilo_legenda") or ESTILO_LEGENDA
        if cfg.get("vertical"):
            estilo = ((projeto.perfil.get("vertical") or {}).get("estilo_legenda")
                      or (projeto.config.get("vertical") or {}).get("estilo_legenda") or ESTILO_LEGENDA_VERTICAL)
        if pip is not None and pip["y"] > cfg.get("altura", 1080) / 2 and not re.search(r"Margin[LR]=", estilo):
            # a legenda desvia do quadro do avatar. As margens do estilo contam numa tela de 384 pontos de largura
            largura_tela = cfg.get("largura", 1920)
            if pip["x"] < largura_tela / 2:
                estilo += f",MarginL={round((pip['x'] + pip['largura'] + 16) / largura_tela * 384)}"
            else:
                estilo += f",MarginR={round((largura_tela - pip['x'] + 16) / largura_tela * 384)}"
        # no filtro do FFmpeg a barra invertida e os dois-pontos do Windows (E:\pasta) precisam ser trocados e escapados
        arquivo_legenda = str(legenda).replace("\\", "/").replace(":", "\\:")
        pasta_fontes = next((f for f in ("/System/Library/Fonts/Supplemental", "C:/Windows/Fonts") if Path(f).is_dir()), None)
        fontes = f":fontsdir='{pasta_fontes.replace(':', chr(92) + ':')}'" if pasta_fontes else ""
        partes.append(
            f"[{atual}]subtitles=filename='{arquivo_legenda}'{fontes}:force_style='{estilo}'[com_legenda]"
        )
        atual, reencodar = "com_legenda", True

    if reencodar and pip is None and duracao >= 2 * PEDACO_MINIMO:
        # o vídeo inteiro numa codificação só levava 15 a 22 min num vídeo de 20 min (everything-you-need-to-answer),
        # até sem nenhum clipe novo. Em pedaços, ao mesmo tempo e na placa de vídeo quando houver, e emendados sem
        # codificar de novo. O personagem no canto segue o caminho de antes
        _mixar_em_pedacos(projeto, video, audio, duracao, final, cfg, base, motion, legenda_do_grafo(partes), log)
        return
    mapa_video = ["-map", f"[{atual}]"] if reencodar else ["-map", "0:v"]
    filtro = ["-filter_complex", ";".join(partes)] if partes else []

    def comando(codec_video):
        return ["ffmpeg", "-y", "-loglevel", "error", *entradas, *filtro,
                *mapa_video, "-map", "1:a", *codec_video, "-c:a", "aac", "-b:a", "192k",
                "-t", f"{duracao:.3f}", "-movflags", "+faststart", final]

    if reencodar:
        _rodar_codificando(comando, cfg, log)
    else:
        rodar(comando(["-c:v", "copy"]))


# pedaços da montagem final: cada um com pelo menos isto de segundos
PEDACO_MINIMO = 20.0
_placa = {}
_trava_placa = threading.Lock()


def _placa_funciona() -> bool:
    """A placa de vídeo NVIDIA codifica H.264? Testado uma vez por execução, com um quadro preto."""
    with _trava_placa:
        if "ok" not in _placa:
            try:
                rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=256x144:d=0.2",
                       "-c:v", "h264_nvenc", "-f", "null", "-"])
                _placa["ok"] = True
            except (RuntimeError, OSError):
                _placa["ok"] = False
        return _placa["ok"]


def _quer_placa(cfg) -> bool:
    return str(cfg.get("codificador", "auto")).lower() != "cpu" and _placa_funciona()


def codec_de_video(cfg, placa) -> list:
    """Argumentos do codificador da montagem final. render.codificador: auto (a placa quando houver) ou cpu.

    Medido em 2026-10-27, 30 s do everything-you-need-to-answer: a placa (RTX 2060) com cq 24 deu a mesma semelhança
    com o original que a CPU com crf 18 (SSIM 0,9607 e 0,9607), em uns 60% do tempo, com o arquivo 1,8 vez maior.
    Só a montagem final usa a placa: os clipes seguem na CPU, porque um clipe guardado da CPU emendado sem codificar
    a um novo da placa estragaria a emenda."""
    if placa:
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(cfg.get("cq_placa", 24)),
                "-b:v", "0", "-spatial-aq", "1", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg.get("crf", 18)), "-pix_fmt", "yuv420p"]


def _rodar_codificando(comando, cfg, log=print, placa=None) -> bool:
    """Roda comando(codec) na placa; se ela recusar (sessões esgotadas, driver), roda de novo na CPU. Devolve True
    se ficou na placa."""
    if _quer_placa(cfg) if placa is None else placa:
        try:
            rodar(comando(codec_de_video(cfg, True)))
            return True
        except RuntimeError as erro:
            log(f"  a placa de vídeo recusou a codificação, seguindo pela CPU. {str(erro)[-200:]}")
    rodar(comando(codec_de_video(cfg, False)))
    return False


def legenda_do_grafo(partes):
    """O filtro da legenda montado em _mixar (a parte que sai em [com_legenda]), sem as etiquetas."""
    for p in partes:
        if p.endswith("[com_legenda]"):
            return p[p.index("]") + 1:p.rindex("[")]
    return None


def pedacos_da_montagem(duracao, fps, quantos) -> list:
    """[(primeiro quadro, quadros)] que cobrem o vídeo inteiro em quadros inteiros: a soma dá exatamente o total, e a
    emenda nunca anda meio quadro (dez emendas arredondando cada uma deixariam a voz atrás da boca no fim)."""
    total = round(duracao * fps)
    quantos = max(1, min(int(quantos), int(duracao // PEDACO_MINIMO) or 1))
    cortes = [round(total * k / quantos) for k in range(quantos + 1)]
    return [(cortes[k], cortes[k + 1] - cortes[k]) for k in range(quantos) if cortes[k + 1] > cortes[k]]


def grafo_do_pedaco(inicio, fim, motion, legenda) -> tuple:
    """(entradas extras, filtro) do pedaço que vai de inicio a fim do vídeo final. A camada de animação que começou
    antes do pedaço entra já andada; a legenda vê o tempo do vídeo inteiro.

    Nada de setpts=PTS-STARTPTS depois de um -ss na entrada: no FFmpeg 8 os quadros de antes do corte ainda passam
    pelo filtro, e o STARTPTS contava a partir deles. O segundo pedaço do teste-animacao-1min saiu com 357 quadros
    em vez de 891. Depois do -ss o vídeo já começa em 0, e o deslocamento é fixo."""
    entradas, partes, atual = [], ["[0:v]null[base]"], "base"
    for k, (ini, fim_m, arquivo) in enumerate(motion):
        if fim_m <= inicio or ini >= fim:
            continue
        local = ini - inicio
        entradas += (["-ss", f"{-local:.6f}"] if local < 0 else []) + ["-i", str(arquivo)]
        n = entradas.count("-i")
        tempo = "setpts=PTS" if local < 0 else f"setpts=PTS-STARTPTS+{local:.6f}/TB"
        partes.append(f"[{n}:v]{tempo},format=yuva420p[m{k}]")
        partes.append(f"[{atual}][m{k}]overlay=eof_action=pass:format=auto:"
                      f"enable='between(t,{max(local, 0):.3f},{fim_m - inicio:.3f})'[cm{k}]")
        atual = f"cm{k}"
    if legenda:
        partes.append(f"[{atual}]setpts=PTS+{inicio:.6f}/TB,{legenda},setpts=PTS-{inicio:.6f}/TB[saida]")
    else:
        partes.append(f"[{atual}]null[saida]")
    return entradas, ";".join(partes)


def _mixar_em_pedacos(projeto, video, audio, duracao, final, cfg, base, motion, legenda, log=print):
    fps = cfg.get("fps", 30)
    na_placa = _quer_placa(cfg)
    # a placa aceita poucas codificações ao mesmo tempo; na CPU cada pedaço já usa vários núcleos
    juntos = int(cfg.get("pedacos_juntos") or (3 if na_placa else max(2, (os.cpu_count() or 4) // 4)))
    pedacos = pedacos_da_montagem(duracao, fps, cfg.get("pedacos") or juntos * 2)
    pasta = projeto.caminho(base, "pedacos")
    pasta.mkdir(parents=True, exist_ok=True)
    for velho in [*pasta.glob("*.mp4"), *pasta.glob("*.h264")]:
        velho.unlink()
    log(f"  montagem final em {len(pedacos)} pedaços, {juntos} de cada vez, "
        + ("na placa de vídeo" if na_placa else "na CPU"))

    def um(k, primeiro, quadros, placa):
        inicio, fim = primeiro / fps, (primeiro + quadros) / fps
        extras, filtro = grafo_do_pedaco(inicio, fim, motion, legenda)

        def comando(codec):
            # H.264 cru, sem quadros B: os pedaços se emendam byte a byte e os tempos são dados uma vez só no fim.
            # Em MP4, cada pedaço trazia os próprios tempos, e a emenda do everything-you-need-to-answer perdeu um
            # quadro (o último caiu em 1206,165 s em vez de 1206,2)
            return ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{inicio:.6f}", "-i", video, *extras,
                    "-filter_complex", filtro, "-map", "[saida]", "-frames:v", quadros, "-r", fps, *codec, "-bf", "0",
                    "-an", "-f", "h264", pasta / f"p{k:03d}.h264"]

        return _rodar_codificando(comando, cfg, log, placa=placa)

    def todos(placa):
        with ThreadPoolExecutor(juntos) as executor:
            return [f.result() for f in [executor.submit(um, k, p, q, placa) for k, (p, q) in enumerate(pedacos)]]

    from . import tempos

    with tempos.parte(projeto, "render: pedaços do vídeo"):
        refazer = na_placa and not all(todos(True))
    if refazer:
        # pedaços de codificadores diferentes não se emendam sem codificar de novo: todos vão pela CPU
        log("  um pedaço não saiu na placa: refazendo todos pela CPU, para a emenda ficar limpa")
        todos(False)
    elif not na_placa:
        todos(False)
    junto = pasta / "video.h264"
    with tempos.parte(projeto, "render: emenda e áudio"):
        with open(junto, "wb") as saida:
            for k in range(len(pedacos)):
                with open(pasta / f"p{k:03d}.h264", "rb") as pedaco:
                    shutil.copyfileobj(pedaco, saida, 1 << 22)
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-framerate", fps, "-f", "h264", "-i", junto, "-i", audio,
               "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{duracao:.3f}",
               "-movflags", "+faststart", final])
    for velho in pasta.glob("*.h264"):
        velho.unlink()


def _trilha(projeto, duracao, extras=(), sons=(), atraso=0.0, musica_abertura=None, faixa_abertura=None,
            base="render"):
    """Junta narração, música, clipes do personagem, efeitos e abertura numa faixa só, já no tempo certo.

    Tudo o que pertence ao vídeo principal anda atraso segundos para frente, o tempo da abertura.
    """
    # a voz e a música são normalizadas em duas passadas cada (uns 2 min num vídeo de 20 min): ao mesmo tempo
    with ThreadPoolExecutor(2) as executor:
        voz_futura = executor.submit(_preparar_voz, projeto, base)
        musica = _musica(projeto, duracao - atraso, [faixa_abertura] if faixa_abertura else [], base)
        voz = voz_futura.result()
    entradas, fontes, partes = [], [], []

    def entrada(arquivo):
        entradas.extend(["-i", str(arquivo)])
        return len(entradas) // 2 - 1

    def ms(segundos):
        valor = max(round(segundos * 1000), 0)
        return f"adelay={valor}|{valor}"

    partes.append(f"[{entrada(voz)}:a]{ms(atraso)}[voz]")
    fontes.append("[voz]")
    if musica:
        partes.append(f"[{entrada(musica)}:a]{ms(atraso)}[musica]")
        fontes.append("[musica]")
    # cada clipe do personagem entra com o próprio áudio, no segundo em que ele aparece
    for momento, arquivo in extras:
        n = entrada(arquivo)
        partes.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,{_normalizar(arquivo)},"
                      f"{ms(momento + atraso)}[e{n}]")
        fontes.append(f"[e{n}]")
    volume_sons = (projeto.perfil.get("efeitos") or {}).get("volume_db", -9)
    for som in sons:
        # os efeitos gerados (trilha.py) trazem o próprio volume; os da ElevenLabs usam o do perfil
        momento, arquivo = som[0], som[1]
        volume = som[2] if len(som) > 2 else volume_sons
        n = entrada(arquivo)
        partes.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,volume={_ganho_pico(arquivo) + volume:.1f}dB,"
                      f"{ms(momento + atraso)}[s{n}]")
        fontes.append(f"[s{n}]")
    if musica_abertura:
        fontes.append(f"[{entrada(musica_abertura)}:a]")
    destino = projeto.caminho(base, "trilha.wav")
    partes.append("".join(fontes) + f"amix=inputs={len(fontes)}:duration=longest:normalize=0[a]")
    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(partes),
           "-map", "[a]", "-t", f"{duracao:.3f}", "-c:a", "pcm_s16le", destino])
    return destino


def _ganho_pico(arquivo, alvo=-1.0):
    """Ganho em dB que leva o pico do arquivo até o alvo. Serve para sons curtos, em que o loudnorm não mede bem."""
    r = rodar(["ffmpeg", "-hide_banner", "-i", arquivo, "-af", "volumedetect", "-f", "null", "-"])
    achado = re.search(r"max_volume:\s*(-?[\d.]+) dB", r.stderr)
    return min(alvo - float(achado.group(1)), 12.0) if achado else 0.0  # som muito baixo não vira chiado alto


def _ler_srt(arquivo):
    pedacos = []
    for bloco in re.split(r"\n\s*\n", arquivo.read_text(encoding="utf-8").strip()):
        linhas = bloco.strip().splitlines()
        tempos = re.match(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)", linhas[1]) if len(linhas) > 2 else None
        if not tempos:
            continue
        v = [int(x) for x in tempos.groups()]
        pedacos.append([v[0] * 3600 + v[1] * 60 + v[2] + v[3] / 1000, v[4] * 3600 + v[5] * 60 + v[6] + v[7] / 1000,
                        "\n".join(linhas[2:]), False])
    return pedacos


def _escrever_srt(pedacos, destino):
    def carimbo(t):
        ms = int(round(max(t, 0) * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    blocos = [f"{n}\n{carimbo(a)} --> {carimbo(b)}\n{texto}\n" for n, (a, b, texto, *_) in enumerate(pedacos, 1)]
    destino.write_text("\n".join(blocos), encoding="utf-8")


def _legendas_finais(projeto, trechos, fecho, duracao, atraso, base="render"):
    """Legendas do vídeo pronto, com as falas dos clipes fixos e o tempo da abertura.

    A de uma linha vai gravada na imagem. A de duas linhas fica em legendas_final.srt,
    para subir no YouTube junto com o vídeo.
    """
    gravada = None
    for origem, destino, largura, linhas in (
        (projeto.pasta / "legendas_tela.srt", projeto.caminho(base, "legendas_tela_final.srt"), 38, 1),
        (projeto.pasta / "legendas.srt", projeto.caminho("legendas_final.srt"), 42, 2),
    ):
        if not origem.exists():
            continue
        pedacos = _ler_srt(origem)
        for j in trechos:
            if j["tipo"] == "inserto":
                pedacos += [[j["ini"] + a, j["ini"] + b, texto, True]
                            for a, b, texto in avatar.legendas_fixo(projeto.perfil, j["nome"], largura, linhas)]
        if fecho:
            pedacos += [[duracao + a, duracao + b, texto, True]
                        for a, b, texto in avatar.legendas_fixo(projeto.perfil, fecho, largura, linhas)]
        pedacos.sort(key=lambda p: p[0])
        for i, p in enumerate(pedacos):
            seguinte = pedacos[i + 1][0] if i + 1 < len(pedacos) else p[1] + 0.5
            if p[3]:  # fala de clipe fixo fica um pouco mais, como a da narração
                p[1] = p[1] + 0.5
            p[1] = max(p[0] + 0.3, min(p[1], seguinte))
        for p in pedacos:
            p[0], p[1] = p[0] + atraso, p[1] + atraso
        _escrever_srt(pedacos, destino)
        if gravada is None:
            gravada = destino
    return gravada


def _normalizar(arquivo):
    """Volume padrão em duas passadas. A primeira mede e a segunda aplica um ganho fixo, sem o volume oscilar."""
    r = rodar(["ffmpeg", "-hide_banner", "-i", arquivo, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    medida = json.loads(r.stderr[r.stderr.rfind("{"):r.stderr.rfind("}") + 1])
    return (
        f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={medida['input_i']}:measured_TP={medida['input_tp']}:"
        f"measured_LRA={medida['input_lra']}:measured_thresh={medida['input_thresh']}:"
        f"offset={medida['target_offset']}:linear=true"
    )


TRANSICAO_MUSICA = 4  # segundos de transição entre uma faixa e a próxima


def _musica(projeto, duracao, faixas_creditadas=(), base="render"):
    """Monta a trilha do vídeo com as faixas do perfil em sequência, repetindo e misturando as pontas até cobrir o vídeo.

    Sem faixas no perfil (ou com a pasta vazia, porque as músicas do canal não vêm no pacote), entra a trilha que o
    modelo compõe e o código toca (trilha.py). Com trilha.substituir no config, ela entra até no lugar das faixas."""
    origem = projeto.perfil.get("musica")
    faixas, gerada = [], None
    if origem and not trilha.config(projeto).get("substituir"):
        caminho = caminho_relativo(origem)
        if caminho.is_file():
            faixas = [caminho]
        elif caminho.is_dir():
            faixas = sorted(f for f in caminho.iterdir() if f.suffix.lower() in EXTENSOES_AUDIO)
        else:
            raise SystemExit(f"Música não encontrada em {caminho}")
    if not faixas:
        try:
            gerada = trilha.gerar(projeto)
        except (Exception, SystemExit) as erro:  # a trilha gerada nunca derruba o render
            print(f"  aviso: a trilha gerada falhou ({str(erro)[:160]})")
        if not gerada:
            print("  aviso: sem música no perfil e sem trilha gerada, o vídeo sai só com a narração")
            return None
        faixas = [gerada]

    sorteio = random.Random(projeto.nome)
    sequencia, total = [], 0.0
    while total < duracao + 5:
        rodada = faixas[:]
        sorteio.shuffle(rodada)
        if sequencia and len(rodada) > 1 and rodada[0] == sequencia[-1]:
            rodada.reverse()  # evita a mesma faixa duas vezes seguidas
        for faixa in rodada:
            sequencia.append(faixa)
            total += duracao_audio(faixa) - (TRANSICAO_MUSICA if len(sequencia) > 1 else 0)
            if total >= duracao + 5:
                break

    destino = projeto.caminho(base, "musica.wav")
    volume = projeto.perfil.get("volume_musica_db", trilha.config(projeto).get("volume_db", -16) if gerada else -14)
    assinatura = _assinatura_de("musica1", f"{duracao:.3f}", volume, TRANSICAO_MUSICA, *sequencia)
    if _ja_feito(destino, assinatura):
        _creditar_musica(projeto, list(faixas_creditadas) + sequencia)
        return destino
    emendada = projeto.caminho(base, "musica_emendada.wav")
    entradas = [item for f in sequencia for item in ("-i", f)]
    grafo = [f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[m{i}]" for i in range(len(sequencia))]
    anterior = "m0"
    for i in range(1, len(sequencia)):
        grafo.append(f"[{anterior}][m{i}]acrossfade=d={TRANSICAO_MUSICA}:c1=tri:c2=tri[x{i}]")
        anterior = f"x{i}"
    rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-filter_complex", ";".join(grafo),
           "-map", f"[{anterior}]", "-c:a", "pcm_s16le", emendada])

    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", emendada, "-af",
           f"atrim=0:{duracao:.3f},{_normalizar(emendada)},volume={volume}dB,aresample=48000,"
           f"aformat=channel_layouts=stereo,afade=t=in:d=2,afade=t=out:st={max(duracao - 4, 0):.3f}:d=4",
           "-c:a", "pcm_s16le", destino])
    emendada.unlink(missing_ok=True)
    _marcar_feito(destino, assinatura)
    _creditar_musica(projeto, list(faixas_creditadas) + sequencia)
    return destino


def _ja_feito(destino, assinatura) -> bool:
    """O áudio em destino foi feito com esta assinatura (as entradas e os ajustes). Renderizar de novo sem mudar a
    narração nem a música refazia as duas normalizações, uns 2 min num vídeo de 20 min."""
    marca = destino.with_name(destino.name + ".assinatura")
    return destino.exists() and marca.exists() and marca.read_text(encoding="utf-8") == assinatura


def _marcar_feito(destino, assinatura) -> None:
    destino.with_name(destino.name + ".assinatura").write_text(assinatura, encoding="utf-8")


def _assinatura_de(*partes) -> str:
    textos = []
    for p in partes:
        if isinstance(p, Path):
            p = f"{p}|{p.stat().st_mtime_ns}|{p.stat().st_size}" if p.exists() else f"{p}|-"
        textos.append(str(p))
    return hashlib.sha1("|".join(textos).encode()).hexdigest()


def _preparar_voz(projeto, base="render"):
    narracao = projeto.pasta / "narracao.wav"
    destino = projeto.caminho(base, "voz.wav")
    assinatura = _assinatura_de("voz1", narracao)
    if _ja_feito(destino, assinatura):
        return destino
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", narracao, "-af",
           f"{_normalizar(narracao)},aresample=48000,aformat=channel_layouts=stereo", "-c:a", "pcm_s16le", destino])
    _marcar_feito(destino, assinatura)
    return destino


def _creditar_musica(projeto, faixas):
    """Junta ao creditos.txt o crédito das músicas usadas, lido de um .txt com o mesmo nome da faixa."""
    linhas = []
    for faixa in dict.fromkeys(faixas):
        credito = faixa.with_suffix(".txt")
        if credito.exists():
            linhas.append(credito.read_text(encoding="utf-8").strip())
    arquivo = projeto.caminho("creditos.txt")
    atual = arquivo.read_text(encoding="utf-8") if arquivo.exists() else ""
    atual = atual.split("\nMúsica\n")[0].rstrip()
    if linhas:
        atual = (atual + "\n\n" if atual else "") + "Música\n" + "\n".join(linhas)
    arquivo.write_text(atual + "\n", encoding="utf-8")
