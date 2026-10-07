"""Narração do roteiro e tempo de cada frase.

A voz vem da GenAIPro (vozes e modelos da ElevenLabs), e o tempo de cada palavra sai da legenda que ela gera,
com o fim de cada palavra encostado no silêncio real do áudio. O Edge-TTS também informa o tempo das palavras.
No modo offline a voz vem do próprio Mac e o tempo é distribuído pelo tamanho do texto.

O áudio bruto de cada bloco fica guardado. O ajuste de ritmo, com pausas mais curtas e
fala mais rápida, é refeito a partir dele sem gastar créditos.
"""
import difflib
import json
import os
import re
import shutil
import sys
import textwrap
import time
import wave

import httpx

from . import custos_reais, fish, genaipro
from . import texto as tx
from .util import duracao_audio, rodar

TAXA = 44100
PAUSA_ENTRE_BLOCOS = 0.4
BLOCOS_AO_MESMO_TEMPO = 4  # tarefas na GenAIPro em paralelo
LETRA_LONGA = 0.35  # letra "falada" por mais tempo que isso está carregando a pausa anterior

TEXTO_TESTE_VOZ = (
    "Muito antes do dilúvio, um sinal apareceu no céu. Não era um sinal qualquer. Era o aviso final de que algo real, "
    "antigo e terrível estava descendo do alto sobre a Terra. O Livro de Enoque descreve esse momento com detalhes que "
    "nenhum outro texto teve coragem de registrar. E o que ele revela sobre o mal que caiu dos céus vai mudar a forma "
    "como você enxerga a história da humanidade."
)


def narrar(projeto, log=print, sem_gastar=False) -> float:
    """sem_gastar: só remonta a narração com os blocos já gravados (o pacote importado, pacote.importar); se algum
    bloco tivesse de ser gravado de novo (o texto ou a voz mudou), para antes de chamar a voz paga."""
    roteiro = tx.normalizar(projeto.roteiro())
    if not roteiro:
        raise SystemExit("O roteiro está vazio.")
    voz = projeto.perfil.get("voz") or {}
    blocos = tx.blocos(roteiro, voz.get("caracteres_por_bloco", 2500))
    tempos_ini = [None] * len(roteiro)
    tempos_fim = [None] * len(roteiro)
    wavs, deslocamento = [], 0.0

    def arquivos(i):
        bruto = projeto.caminho("narracao", f"bloco_{i:03d}_bruto.wav")
        return bruto, bruto.with_name(f"bloco_{i:03d}.json")

    # um bloco só é narrado de novo se o texto OU A VOZ mudou desde a última vez. Antes só o texto contava: trocar a
    # voz no editor (Nelton para Leo Antonio, no zz_teste_animacoes) reaproveitava os blocos e o vídeo saía com a
    # voz antiga
    assinatura = assinatura_da_voz(projeto, voz)
    pendentes, por_voz = [], 0
    for i, bloco in enumerate(blocos):
        bruto, arquivo_alinhamento = arquivos(i)
        _migrar_bloco_antigo(bruto, arquivo_alinhamento)
        if not (arquivo_alinhamento.exists() and bruto.exists() and _mesmo_texto(arquivo_alinhamento, bloco.texto)):
            pendentes.append(i)
        elif not _mesma_voz(projeto, arquivo_alinhamento, assinatura, i, len(blocos)):
            pendentes.append(i)
            por_voz += 1
    if pendentes and sem_gastar:
        raise SystemExit(f"{len(pendentes)} bloco(s) da narração teriam de ser gravados de novo (o texto ou a voz "
                         f"mudou desde o pacote). Nada foi gasto.")
    if por_voz:
        log(f"  a voz mudou: {por_voz} bloco(s) com o mesmo texto vão ser gravados de novo com a voz nova")

    def gravar(i):
        bloco = blocos[i]
        bruto, arquivo_alinhamento = arquivos(i)
        if projeto.offline or voz.get("provedor") == "computador":
            # "computador": a voz do sistema também fora do modo offline (teste do MCP sem gastar)
            alinhamento = _voz_do_mac(bloco.texto, voz, bruto)
        elif voz.get("provedor") == "edge-tts":
            alinhamento = _edge_tts(bloco.texto, voz, bruto)
        elif voz.get("provedor") == "fish":
            alinhamento = _fish(bloco.texto, voz, bruto, log)
            custo = alinhamento.pop("_custo_transcricao", 0)
            if custo:
                custos_reais.registrar(projeto, "narracao", f"bloco {i + 1}: tempo das palavras da voz da Fish Audio",
                                       custo, detalhes={"provedor": "fish", "transcricao": True})
        else:
            alinhamento = _genaipro(bloco.texto, voz, bruto, lambda *_: None)
        alinhamento["texto"] = bloco.texto
        alinhamento["voz"] = assinatura  # a voz que gravou este bloco: trocar a voz grava de novo
        arquivo_alinhamento.write_text(json.dumps(alinhamento, ensure_ascii=False), encoding="utf-8")

    narrados = []

    def cobrar(i):
        # só o que a API cobrou agora entra na conta: bloco reaproveitado do cache não paga de novo.
        # O valor sai do saldo da GenAIPro, medido no fim (_registrar_gasto_da_narracao)
        narrados.append(i)

    pago = not projeto.offline and voz.get("provedor") not in ("edge-tts", "fish", "computador")
    saldo_antes = _saldo_genaipro() if pago and pendentes else None
    com_fish = not projeto.offline and voz.get("provedor") == "fish"
    if (pago or com_fish) and len(pendentes) > 1:
        # a GenAIPro e a Fish trabalham por pedido, então vários blocos são gravados ao mesmo tempo
        from concurrent.futures import ThreadPoolExecutor, as_completed
        juntos = int(fish.config().get("blocos_ao_mesmo_tempo", 3)) if com_fish else BLOCOS_AO_MESMO_TEMPO
        log(f"  narrando {len(pendentes)} blocos {'na Fish Audio' if com_fish else 'na GenAIPro'}, {juntos} de cada vez")
        with ThreadPoolExecutor(max_workers=juntos) as grupo:
            tarefas = {grupo.submit(gravar, i): i for i in pendentes}
            prontos, erro = 0, None
            for tarefa in as_completed(tarefas):
                i = tarefas[tarefa]
                try:
                    tarefa.result()
                except (Exception, SystemExit) as e:
                    erro = erro or e
                    continue
                if pago:
                    cobrar(i)
                prontos += 1
                log(f"  bloco {i + 1} pronto ({prontos} de {len(pendentes)})")
        _registrar_gasto_da_narracao(projeto, blocos, narrados, voz, saldo_antes, log)
        if erro:
            raise erro
    else:
        try:
            for i in pendentes:
                log(f"  narrando bloco {i + 1} de {len(blocos)}")
                gravar(i)
                if pago:
                    cobrar(i)
        finally:
            if pago:
                _registrar_gasto_da_narracao(projeto, blocos, narrados, voz, saldo_antes, log)

    for i, bloco in enumerate(blocos):
        bruto, arquivo_alinhamento = arquivos(i)
        alinhamento = json.loads(arquivo_alinhamento.read_text(encoding="utf-8"))
        wav = bruto.with_name(f"bloco_{i:03d}.wav")
        alinhamento = _ajustar_ritmo(bruto, wav, alinhamento, voz)
        duracao = duracao_audio(wav)
        _mapear(bloco, alinhamento, duracao, deslocamento, tempos_ini, tempos_fim)
        wavs.append(wav)
        deslocamento += duracao + PAUSA_ENTRE_BLOCOS

    narracao = _juntar(projeto, wavs)
    total = duracao_audio(narracao)
    # cada [INSERTO] abre um silêncio do tamanho do clipe fixo, e tudo depois dele anda para frente
    total, inicio_insertos = _abrir_espaco_dos_insertos(projeto, narracao, total, tempos_ini, tempos_fim)
    unidades = _tempos_das_frases(roteiro, tempos_ini, tempos_fim, total)
    # o momento de cada palavra permite fazer textos e itens de lista surgirem quando são falados
    palavras = []
    for m in re.finditer(r"\S+", roteiro):
        ini = next((t for t in tempos_ini[m.start():m.end()] if t is not None), None)
        palavras.append({"c": m.start(), "texto": m.group(), "ini": round(ini, 3) if ini is not None else None})
    # título e entrada do avatar começam junto com a fala seguinte, o resto fecha com a fala anterior
    marcadores = []
    for m in projeto.marcadores():
        if m["tipo"] == "inserto" and m["c"] in inicio_insertos:
            t = inicio_insertos[m["c"]]
        elif m["tipo"] in ("titulo", "avatar_inicio"):
            t = next((x for x in tempos_ini[m["c"]:] if x is not None), total)
        else:
            t = next((x for x in reversed(tempos_fim[:m["c"]]) if x is not None), 0.0)
        marcadores.append({**m, "ini": round(min(t, total), 3)})
    # o tempo de cada palavra da narração anterior fica guardado: cenas.atualizar_tempos leva cada corte de cena para
    # o mesmo ponto da fala na narração nova, e as cenas não mudam à toa
    if projeto.existe("alinhamento.json"):
        shutil.copy2(projeto.pasta / "alinhamento.json", projeto.pasta / "alinhamento_anterior.json")
    projeto.salvar_json("alinhamento.json", {"duracao": total, "unidades": unidades, "palavras": palavras,
                                             "marcadores": marcadores})
    _legendas(unidades, projeto.caminho("legendas.srt"), tempos_ini, tempos_fim)
    _legendas(unidades, projeto.caminho("legendas_tela.srt"), tempos_ini, tempos_fim, largura=38, linhas=1)
    return total


def realinhar_edge(projeto, log=print) -> dict:
    """Projeto narrado pelo Edge antes do tempo por palavra: narra de novo (grátis) e move os cortes das cenas.

    As imagens escolhidas ficam. Cada corte antigo vira uma posição no texto (pelo tempo antigo das palavras) e
    essa posição vira o tempo novo. Guarda cópias de alinhamento.json e cenas.json antes de mexer."""
    voz = projeto.perfil.get("voz") or {}
    if voz.get("provedor") != "edge-tts" or not projeto.existe("alinhamento.json"):
        return {"realinhado": False, "motivo": "o projeto não foi narrado pelo Edge"}
    antigo = projeto.ler_json("alinhamento.json")
    carimbo = time.strftime("%Y%m%d-%H%M%S")
    projeto.salvar_json(f"alinhamento_antes_realinhar_{carimbo}.json", antigo)
    tem_cenas = projeto.existe("cenas.json")
    if tem_cenas:
        projeto.salvar_json(f"cenas_antes_realinhar_{carimbo}.json", projeto.ler_json("cenas.json"))
    for arq in (projeto.pasta / "narracao").glob("bloco_*.json"):
        arq.unlink()
    log("  narrando de novo pelo Edge, agora com o tempo de cada palavra")
    narrar(projeto, log=log)
    novo = projeto.ler_json("alinhamento.json")

    def pontos(alin):
        return [(p["c"], p["ini"]) for p in alin.get("palavras", []) if p.get("ini") is not None]

    velho_t_para_c = sorted(((t, c) for c, t in pontos(antigo)))
    novo_c_para_t = sorted(pontos(novo))

    def interpolar(xy, x):
        if not xy:
            return x
        if x <= xy[0][0]:
            return xy[0][1]
        for (x0, y0), (x1, y1) in zip(xy, xy[1:]):
            if x0 <= x <= x1:
                return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return xy[-1][1]

    def mover(t):
        return round(interpolar(novo_c_para_t, interpolar(velho_t_para_c, t)), 3)

    if tem_cenas:
        dados = projeto.ler_json("cenas.json")
        lista = dados["cenas"]

        def mover_dentro(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in ("ini", "fim") and isinstance(v, (int, float)):
                        obj[k] = mover(v)
                    else:
                        mover_dentro(v)
            elif isinstance(obj, list):
                for v in obj:
                    mover_dentro(v)

        mover_dentro(lista)
        # sem buracos nem sobreposição: cada cena começa onde a anterior acaba, e a última vai até o fim da voz
        for i, c in enumerate(lista):
            c["ini"] = 0.0 if i == 0 else lista[i - 1]["fim"]
            c["fim"] = max(c["fim"], c["ini"] + 0.5)
        if lista:
            lista[-1]["fim"] = round(novo["duracao"], 3)
        projeto.salvar_json("cenas.json", dados)
    log(f"  realinhado: duração {antigo.get('duracao', 0):.1f}s -> {novo['duracao']:.1f}s, cortes das cenas movidos")
    return {"realinhado": True, "duracao_antes": antigo.get("duracao"), "duracao_depois": novo["duracao"]}


def assinatura_da_voz(projeto, voz) -> dict:
    """O que muda o som gravado de um bloco: a voz e os ajustes que vão para quem grava.

    Ritmo e pausa ficam de fora de propósito: são aplicados depois, no áudio guardado, e mudar não custa nada."""
    if projeto.offline or voz.get("provedor") == "computador":
        return {"provedor": "mac", "voz": voz.get("voz_offline", "Luciana")}
    if voz.get("provedor") == "fish":
        return {"provedor": "fish", "voz": str(voz.get("voice_id") or "").strip(), "modelo": fish.modelo(voz),
                "velocidade": round(float(voz.get("velocidade") or 1.0), 2)}
    if voz.get("provedor") == "edge-tts":
        return {"provedor": "edge-tts", "voz": (voz.get("voz_edge") or "pt-BR-AntonioNeural").strip(),
                "velocidade": voz.get("velocidade_edge", "+0%"), "tom": voz.get("tom_edge", "+0Hz")}
    try:
        corpo = genaipro.corpo_da_tarefa("", voz)
    except Exception:
        return {"provedor": "genaipro", "voice_id": str(voz.get("voice_id") or "").strip()}
    corpo.pop("input", None)
    return {"provedor": "genaipro", **corpo}


def _mesma_voz(projeto, arquivo_alinhamento, assinatura, indice, total) -> bool:
    """O bloco guardado foi gravado com esta voz?

    Bloco novo guarda a assinatura. Bloco de antes disso não guarda: a voz dele sai do custos_reais.json, que
    registrou a voz de cada bloco cobrado ("bloco 2 de 6 narrado na GenAIPro"). Sem registro nenhum, vale o guardado,
    para não pagar de novo à toa."""
    try:
        guardada = json.loads(arquivo_alinhamento.read_text(encoding="utf-8")).get("voz")
    except (OSError, json.JSONDecodeError):
        return False
    if guardada is not None:
        return guardada == assinatura
    voz_antiga = _voz_do_bloco_pelo_custo(projeto, indice, total)
    if voz_antiga is None:
        return True
    return assinatura.get("provedor") == "genaipro" and voz_antiga == assinatura.get("voice_id")


def _voz_do_bloco_pelo_custo(projeto, indice, total):
    """voice_id com que o bloco foi cobrado pela última vez, lido do histórico de custos, ou None."""
    voz = None
    for h in custos_reais.historico(projeto):
        achado = re.match(r"bloco (\d+) de (\d+) narrado", h.get("motivo", ""))
        if achado and int(achado.group(1)) == indice + 1 and int(achado.group(2)) == total:
            voz = (h.get("detalhes") or {}).get("voz") or voz
    return voz


def _mesmo_texto(arquivo_alinhamento, texto):
    """Projetos antigos não guardavam o texto do bloco, e nesses o áudio guardado vale."""
    try:
        guardado = json.loads(arquivo_alinhamento.read_text(encoding="utf-8")).get("texto")
    except (OSError, json.JSONDecodeError):
        return False
    return guardado is None or guardado == texto


def _abrir_espaco_dos_insertos(projeto, narracao, total, tempos_ini, tempos_fim):
    """Abre no áudio um silêncio para cada clipe fixo do personagem e empurra os tempos seguintes.

    O clipe não entra colado na última palavra. Ele usa parte da pausa natural que vinha
    depois dela, para o personagem respirar antes de começar, e o resto da pausa fica
    depois do clipe. Devolve a nova duração e o segundo em que cada clipe começa.
    """
    from . import avatar

    insertos = [m for m in projeto.marcadores() if m["tipo"] == "inserto"]
    if not insertos:
        return total, {}
    antes = float((projeto.perfil.get("avatar") or {}).get("pausa_antes_inserto", 0.6))
    depois = min(antes, 0.4)
    pontos, inicios = [], {}
    for m in insertos:
        fim_fala = next((x for x in reversed(tempos_fim[:m["c"]]) if x is not None), 0.0)
        proxima = next((x for x in tempos_ini[m["c"]:] if x is not None), total)
        t = min(fim_fala + min(antes, max(proxima - fim_fala, 0.0) / 2), total)
        # quando a pausa natural é curta, o respiro que falta vira silêncio a mais em volta do clipe
        falta_antes = max(antes - (t - fim_fala), 0.0)
        falta_depois = max(depois - (proxima - t), 0.0)
        pontos.append((t, falta_antes + avatar.duracao_fixo(projeto.perfil, m["texto"]) + falta_depois))
        inicios[m["c"]] = (t, falta_antes)
    pontos.sort()

    partes, entradas, anterior, n = [], [], 0.0, 0
    for t, dur in pontos:
        silencio = projeto.caminho("narracao", f"silencio_inserto_{n}.wav")
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r={TAXA}:cl=mono",
               "-t", f"{dur:.3f}", "-c:a", "pcm_s16le", silencio])
        pedaco = projeto.caminho("narracao", f"pedaco_inserto_{n}.wav")
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", narracao, "-ss", f"{anterior:.3f}", "-to", f"{t:.3f}",
               "-c:a", "pcm_s16le", pedaco])
        partes += [pedaco, silencio]
        anterior, n = t, n + 1
    fim = projeto.caminho("narracao", f"pedaco_inserto_{n}.wav")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", narracao, "-ss", f"{anterior:.3f}", "-c:a", "pcm_s16le", fim])
    partes.append(fim)

    lista = projeto.caminho("narracao", "lista_insertos.txt")
    lista.write_text("".join(f"file '{p}'\n" for p in partes), encoding="utf-8")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lista,
           "-c:a", "pcm_s16le", narracao])
    for p in partes:
        p.unlink(missing_ok=True)

    def empurrar(t):
        return t + sum(dur for ponto, dur in pontos if t > ponto)

    for tempos in (tempos_ini, tempos_fim):
        for i, t in enumerate(tempos):
            if t is not None:
                tempos[i] = empurrar(t)
    # o clipe começa depois do respiro, e os clipes anteriores empurram os seguintes
    inicios = {c: t + falta + sum(dur for ponto, dur in pontos if ponto < t) for c, (t, falta) in inicios.items()}
    return duracao_audio(narracao), inicios


def _migrar_bloco_antigo(bruto, arquivo_alinhamento):
    """Projetos antigos guardavam só o mp3 da voz ou o wav já pronto."""
    if not arquivo_alinhamento.exists() or bruto.exists():
        return
    mp3 = bruto.with_name(bruto.name.replace("_bruto.wav", ".mp3"))
    antigo = bruto.with_name(bruto.name.replace("_bruto", ""))
    if mp3.exists():
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ac", "1", "-ar", TAXA, "-c:a", "pcm_s16le", bruto])
    elif antigo.exists():
        shutil.copyfile(antigo, bruto)


def _ajustar_ritmo(bruto, destino, alinhamento, voz):
    """Encurta pausas longas e acelera a fala, se o perfil pedir, e corrige o tempo de cada letra."""
    inicio, fim = list(alinhamento["inicio"]), list(alinhamento["fim"])
    atual = bruto
    pausa_maxima = voz.get("pausa_maxima")
    if pausa_maxima:
        cortes = _pausas_longas(bruto, float(pausa_maxima))
        if cortes:
            atual = destino.with_name(destino.stem + "_sem_pausas.wav")
            _remover_trechos(bruto, atual, cortes)
            inicio = [_descontar(t, cortes) for t in inicio]
            fim = [_descontar(t, cortes) for t in fim]
    ritmo = float(voz.get("ritmo") or 1.0)
    if abs(ritmo - 1.0) > 0.001:
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", atual, "-af", f"atempo={ritmo:.4f}",
               "-ac", "1", "-ar", TAXA, "-c:a", "pcm_s16le", destino])
        inicio = [t / ritmo for t in inicio]
        fim = [t / ritmo for t in fim]
    else:
        shutil.copyfile(atual, destino)
    return {**alinhamento, "inicio": inicio, "fim": fim}


def _pausas_longas(wav, pausa_maxima):
    """Trechos a remover para que nenhuma pausa passe de pausa_maxima segundos."""
    r = rodar(["ffmpeg", "-hide_banner", "-i", wav, "-af", f"silencedetect=noise=-40dB:d={pausa_maxima}", "-f", "null", "-"])
    inicios = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    cortes = []
    for a, b in zip(inicios, fins):
        excesso = (b - a) - pausa_maxima
        if excesso > 0.02:
            meio = (a + b) / 2
            cortes.append((meio - excesso / 2, meio + excesso / 2))
    return cortes


def _remover_trechos(origem, destino, cortes):
    with wave.open(str(origem), "rb") as entrada:
        parametros = entrada.getparams()
        quadros = entrada.readframes(entrada.getnframes())
    bytes_por_amostra = parametros.sampwidth * parametros.nchannels
    partes, anterior = [], 0
    for a, b in cortes:
        partes.append(quadros[anterior:int(a * parametros.framerate) * bytes_por_amostra])
        anterior = int(b * parametros.framerate) * bytes_por_amostra
    partes.append(quadros[anterior:])
    with wave.open(str(destino), "wb") as saida:
        saida.setparams(parametros)
        saida.writeframes(b"".join(partes))


def _descontar(t, cortes):
    removido = 0.0
    for a, b in cortes:
        if t >= b:
            removido += b - a
        elif t > a:
            removido += t - a
        else:
            break
    return t - removido


def buscar_vozes(termo, idioma=None, quantidade=15):
    """Procura vozes na biblioteca da GenAIPro. Qualquer uma delas serve direto no perfil, sem copiar para a conta."""
    return genaipro.vozes(busca=termo, idioma=idioma, quantidade=quantidade)


def _chave_elevenlabs():
    """Criar voz por descrição é da ElevenLabs direta, opcional: a GenAIPro só narra."""
    valor = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not valor:
        raise SystemExit("Criar voz por descrição só existe na ElevenLabs direta, que é opcional. A GenAIPro não cria "
                         "vozes. Se quiser usar, coloque ELEVENLABS_API_KEY no .env.")
    return valor


def desenhar_voz(descricao, texto=TEXTO_TESTE_VOZ, modelo="eleven_ttv_v3"):
    """Cria prévias de uma voz nova a partir de uma descrição, pelo Voice Design da ElevenLabs direta (opcional)."""
    if not 20 <= len(descricao) <= 1000:
        raise SystemExit("A descrição da voz precisa ter entre 20 e 1000 caracteres.")
    if not 100 <= len(texto) <= 1000:
        raise SystemExit("O texto de teste precisa ter entre 100 e 1000 caracteres.")
    r = httpx.post(
        "https://api.elevenlabs.io/v1/text-to-voice/design",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": _chave_elevenlabs()},
        json={"voice_description": descricao, "text": texto, "model_id": modelo},
        timeout=300,
    )
    if r.status_code in (401, 403):
        raise SystemExit(f"A ElevenLabs recusou ({r.status_code}). Libere o acesso a Geração de Voz na chave da API. {r.text[:200]}")
    if r.status_code != 200:
        raise SystemExit(f"A ElevenLabs recusou criar a voz ({r.status_code}). {r.text[:300]}")
    return r.json()["previews"]


def salvar_voz_criada(generated_voice_id, nome, descricao):
    """Transforma a prévia escolhida numa voz da conta da ElevenLabs e devolve o voice_id.

    A GenAIPro só narra com vozes da biblioteca pública: para usar esta voz na fábrica, compartilhe-a na
    biblioteca da ElevenLabs (Voice Library) e depois ache pelo nome com fabrica vozes."""
    r = httpx.post(
        "https://api.elevenlabs.io/v1/text-to-voice",
        headers={"xi-api-key": _chave_elevenlabs()},
        json={"voice_name": nome, "voice_description": descricao, "generated_voice_id": generated_voice_id},
        timeout=60,
    )
    if r.status_code != 200:
        raise SystemExit(f"A ElevenLabs recusou salvar a voz ({r.status_code}). {r.text[:300]}")
    return r.json()["voice_id"]


def _saldo_genaipro():
    """Créditos da conta GenAIPro agora (consulta grátis), ou None se não deu para ler."""
    try:
        return genaipro.conta()["creditos"]
    except Exception:
        return None


def _registrar_gasto_da_narracao(projeto, blocos, narrados, voz, saldo_antes, log=print):
    """Grava em custos_reais.json o que a GenAIPro cobrou nesta narração, medido pela diferença do saldo.

    A GenAIPro não diz quanto cada tarefa gastou, e não é 1 crédito por caractere (ver
    custos_reais.CREDITOS_POR_CARACTERE_PADRAO). Se outra narração rodar ao mesmo tempo na mesma conta, a diferença
    pega as duas; por isso uma medida fora do razoável (mais de 1 crédito por caractere) vira estimativa."""
    if not narrados:
        return
    caracteres = sum(len(blocos[i].texto) for i in narrados)
    modelo = voz.get("modelo", "") or genaipro.MODELO_PADRAO
    saldo_depois = _saldo_genaipro() if saldo_antes is not None else None
    medido = saldo_antes is not None and saldo_depois is not None and 0 < saldo_antes - saldo_depois <= caracteres
    if medido:
        creditos = float(saldo_antes - saldo_depois)
        custos_reais.guardar_medida(modelo, caracteres, creditos)
        como = "medido no saldo da GenAIPro"
    else:
        taxa, _ = custos_reais.creditos_por_caractere(projeto.config, modelo)
        creditos = caracteres * taxa
        como = "estimado (não deu para ler o saldo)"
    por_credito, origem = custos_reais.preco_por_credito(projeto.config)
    custos_reais.registrar(
        projeto, "narracao", f"{len(narrados)} de {len(blocos)} blocos narrados na GenAIPro: "
                             f"{creditos:.0f} créditos, {como}",
        creditos * por_credito, unidades=creditos,
        detalhes={"caracteres": caracteres, "creditos": round(creditos, 1), "voz": voz.get("voice_id", ""),
                  "modelo": modelo, "provedor": "genaipro", "preco": origem, "medido": medido,
                  "creditos_por_caractere": round(creditos / caracteres, 4) if caracteres else 0})
    narrados.clear()
    log(f"  narração custou {creditos:.0f} créditos (US$ {creditos * por_credito:.4f}), {como}")


def _genaipro(texto, voz, wav, log=print):
    """Grava o texto na GenAIPro e devolve o tempo de cada letra, montado a partir do tempo de cada palavra."""
    mp3 = wav.with_name(wav.name.replace("_bruto.wav", ".mp3")) if wav.name.endswith("_bruto.wav") else wav.with_suffix(".mp3")
    palavras = genaipro.narrar(texto, voz, mp3, log)
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ac", "1", "-ar", TAXA, "-c:a", "pcm_s16le", wav])
    palavras = _encostar_nas_pausas(palavras, _silencios(wav))
    return _alinhar_pelas_palavras(texto, palavras, duracao_audio(wav))


def _fish(texto, voz, wav, log=print):
    """Grava na Fish Audio (OpenRouter, grátis) e mede o tempo de cada palavra pela transcrição.

    Sem a transcrição (falta saldo no OpenRouter, ela caiu), o tempo é estimado pelas pausas do áudio: a legenda e
    os cortes ficam um pouco menos precisos, mas o vídeo nunca para por causa disso."""
    mp3 = wav.with_name(wav.name.replace("_bruto.wav", ".mp3")) if wav.name.endswith("_bruto.wav") else wav.with_suffix(".mp3")
    fish.narrar(texto, voz, mp3, log)
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ac", "1", "-ar", TAXA, "-c:a", "pcm_s16le", wav])
    duracao = duracao_audio(wav)
    silencios = _pausas_da_voz(wav)
    custo = 0.0
    try:
        palavras, custo = fish.palavras_com_tempo(mp3, texto, voz.get("idioma") or "pt")
        como = "medido pela transcrição"
    except Exception as erro:
        log(f"    tempo das palavras estimado pelas pausas do áudio ({str(erro)[:120]})")
        palavras, como = _palavras_estimadas(texto, duracao, wav), "estimado pelas pausas"
    palavras = _encostar_nas_pausas(palavras, silencios)
    alinhamento = _alinhar_pelas_palavras(texto, palavras, duracao)
    alinhamento["tempo_das_palavras"] = como
    alinhamento["_custo_transcricao"] = custo
    return alinhamento


def _pausas_da_voz(wav, minima=0.12):
    """Pausas do áudio com o limite de silêncio ajustado ao volume da voz.

    A voz da Fish tem um chiado de fundo perto de -35 dB: com o limite fixo de -40 dB, o silêncio depois de um ponto
    não aparecia (4 pausas em 49 s). Com o limite 7 dB abaixo do volume médio, aparecem as pausas de verdade."""
    r = rodar(["ffmpeg", "-hide_banner", "-i", wav, "-af", "volumedetect", "-f", "null", "-"])
    achado = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
    limite = min(-25.0, float(achado.group(1)) - 7.0) if achado else -35.0
    r = rodar(["ffmpeg", "-hide_banner", "-i", wav, "-af", f"silencedetect=noise={limite:.1f}dB:d={minima}", "-f", "null", "-"])
    inicios = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(inicios, fins))


def _palavras_estimadas(texto, duracao, wav):
    """Tempo de cada palavra sem transcrição, casando a pontuação do roteiro com as pausas reais do áudio.

    Cada ponto ou vírgula, em ordem, procura a pausa mais provável perto de onde a proporção de letras diz que ele
    cai; o ponto prefere pausa longa. Achada a pausa, o trecho fica preso a ela, e as palavras de cada trecho dividem
    o tempo dele pelo tamanho. Usado só quando a transcrição não está disponível."""
    pausas = [(a, b) for a, b in _pausas_da_voz(wav) if b - a >= 0.12]
    inicio_fala = next((b for a, b in pausas if a <= 0.02), 0.0)
    fim_fala = next((a for a, b in pausas if b >= duracao - 0.02 and a > inicio_fala), duracao)
    internas = [(a, b) for a, b in pausas if inicio_fala + 0.1 < a and b < fim_fala - 0.1]

    tokens = [m.group() for m in re.finditer(r"\S+", texto)]
    pesos = [len(re.sub(r"[^\w]", "", t)) + 1 for t in tokens]
    acumulado = [0]
    for peso in pesos:
        acumulado.append(acumulado[-1] + peso)
    forca = [2 if re.search(r"[.!?…]$", t) else 1 if re.search(r"[,;:—–-]$", t) else 0 for t in tokens]

    # âncoras: (índice do token depois do qual o trecho fecha, fim da fala do trecho, começo do trecho seguinte)
    ancoras, t_cur, k_cur, usadas = [], inicio_fala, 0, set()
    for k in range(len(tokens) - 1):
        if not forca[k]:
            continue
        resto = acumulado[-1] - acumulado[k_cur]
        previsto = t_cur + (acumulado[k + 1] - acumulado[k_cur]) / max(resto, 1) * (fim_fala - t_cur)
        janela = max(0.8, 0.3 * (previsto - t_cur))
        melhor, nota_melhor = None, None
        for j, (a, b) in enumerate(internas):
            if j in usadas or a <= t_cur + 0.15:
                continue
            distancia = abs((a + b) / 2 - previsto)
            if distancia > janela:
                continue
            nota = distancia - forca[k] * 0.4 * min(b - a, 0.8)
            if nota_melhor is None or nota < nota_melhor:
                melhor, nota_melhor = j, nota
        if melhor is None:
            continue
        a, b = internas[melhor]
        usadas.update(range(melhor + 1))  # as pausas antes desta ficam para trás
        ancoras.append((k, a, b))
        t_cur, k_cur = b, k + 1
    palavras, k_ini, t_ini = [], 0, inicio_fala
    for k_fim, t_fim, t_seguinte in ancoras + [(len(tokens) - 1, fim_fala, fim_fala)]:
        soma = acumulado[k_fim + 1] - acumulado[k_ini] or 1
        for k in range(k_ini, k_fim + 1):
            t0 = t_ini + (t_fim - t_ini) * (acumulado[k] - acumulado[k_ini]) / soma
            t1 = t_ini + (t_fim - t_ini) * (acumulado[k + 1] - acumulado[k_ini]) / soma
            palavras.append((tokens[k], t0, t1))
        k_ini, t_ini = k_fim + 1, t_seguinte
    return palavras


def _silencios(wav, minimo=0.15):
    r = rodar(["ffmpeg", "-hide_banner", "-i", wav, "-af", f"silencedetect=noise=-40dB:d={minimo}", "-f", "null", "-"])
    inicios = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(inicios, fins))


def _encostar_nas_pausas(palavras, silencios):
    """Na legenda da GenAIPro uma palavra vai até a seguinte começar, então a pausa depois de um ponto fica
    dentro da palavra anterior ("explodiu." ia até 4,67 s, e a fala parava em 4,17 s). A palavra passa a
    terminar onde o silêncio começa e a começar onde ele acaba. Silêncio no meio da palavra não mexe nela."""
    ajustadas = []
    for palavra, t0, t1 in palavras:
        for a, b in silencios:
            if t0 + 0.05 < a < t1 <= b + 0.05:
                t1 = a
            elif a <= t0 < b < t1 - 0.05:
                t0 = b
        ajustadas.append((palavra, t0, max(t1, t0 + 0.02)))
    return ajustadas


def _edge_tts(texto, voz, wav):
    import asyncio
    import edge_tts

    VOZES_VALIDAS = {
        "pt-BR-AntonioNeural",
        "pt-BR-FranciscaNeural",
        "pt-BR-ThalitaMultilingualNeural",
        "pt-PT-DuarteNeural",
        "pt-PT-RaquelNeural"
    }

    voz_nome = (voz.get("voz_edge") or "pt-BR-AntonioNeural").strip()
    if "Thalita" in voz_nome:
        voz_nome = "pt-BR-ThalitaMultilingualNeural"
    elif voz_nome not in VOZES_VALIDAS:
        voz_nome = "pt-BR-AntonioNeural"

    mp3 = wav.with_suffix(".mp3")
    velocidade = voz.get("velocidade_edge", "+0%")
    tom = voz.get("tom_edge", "+0Hz")

    palavras = []  # (texto, início em s, fim em s) de cada palavra, como o Edge falou

    # velocidade_edge e tom_edge aceitam o formato do Edge, como "-10%" e "-5Hz". O WordBoundary faz o Edge
    # dizer quando cada palavra é falada: sem ele o tempo era dividido por igual entre as letras, e as pausas
    # dos pontos e parágrafos iam acumulando atraso na legenda e nos cortes das cenas
    async def _falar():
        palavras.clear()
        c = edge_tts.Communicate(texto, voz_nome, rate=velocidade, pitch=tom, boundary="WordBoundary")
        with open(mp3, "wb") as saida:
            async for pedaco in c.stream():
                if pedaco["type"] == "audio":
                    saida.write(pedaco["data"])
                elif pedaco["type"] == "WordBoundary":
                    ini = pedaco["offset"] / 1e7  # o Edge mede em unidades de 100 nanossegundos
                    palavras.append((pedaco["text"], ini, ini + pedaco["duration"] / 1e7))

    ultimo_erro = None
    sucesso = False
    for tentativa in range(3):
        try:
            asyncio.run(_falar())
            if mp3.exists() and mp3.stat().st_size > 100:
                sucesso = True
                break
            ultimo_erro = RuntimeError(f"o Edge-TTS não gerou áudio (arquivo ausente ou vazio) pra voz {voz_nome}")
        except Exception as e:
            ultimo_erro = e
            if voz_nome != "pt-BR-AntonioNeural":
                voz_nome = "pt-BR-AntonioNeural"
        time.sleep(1.0)

    if not sucesso:
        raise ultimo_erro

    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(TAXA), "-c:a", "pcm_s16le", str(wav)])
    mp3.unlink(missing_ok=True)
    return _alinhar_pelas_palavras(texto, palavras, duracao_audio(wav))


def _alinhar_pelas_palavras(texto, palavras, duracao):
    """Tempo de cada letra a partir do tempo de cada palavra que a voz informou.

    Cada palavra é achada no texto em ordem; as letras dela dividem o tempo da palavra, e espaços e pontuação
    entre duas palavras ficam no fim da anterior. Palavra que não se acha (a voz leu "2017" por extenso, por
    exemplo) só deixa aquele trecho interpolado entre as vizinhas, sem desalinhar o resto."""
    n = len(texto)
    ini, fim = [None] * n, [None] * n
    cursor = 0
    for palavra, t0, t1 in palavras:
        palavra = (palavra or "").strip()
        if not palavra:
            continue
        pos = texto.find(palavra, cursor, cursor + 300)
        if pos < 0:
            continue
        tam = len(palavra)
        for k in range(tam):
            ini[pos + k] = t0 + (t1 - t0) * k / tam
            fim[pos + k] = t0 + (t1 - t0) * (k + 1) / tam
        cursor = pos + tam
    if not any(t is not None for t in ini):
        # a voz não mandou o tempo das palavras: volta a dividir por igual, como antes
        return {"caracteres": list(texto), "inicio": [duracao * i / max(n, 1) for i in range(n)],
                "fim": [duracao * (i + 1) / max(n, 1) for i in range(n)]}
    # o que ficou sem tempo (espaços, pontuação, palavra não achada) é preenchido entre as letras conhecidas
    conhecidos = [i for i in range(n) if ini[i] is not None]
    for i in range(n):
        if ini[i] is not None:
            continue
        antes = next((j for j in reversed(conhecidos) if j < i), None) if conhecidos[0] < i else None
        depois = next((j for j in conhecidos if j > i), None)
        a = fim[antes] if antes is not None else 0.0
        b = ini[depois] if depois is not None else duracao
        if antes is not None and depois is not None and depois - antes > 1:
            # dentro de um trecho sem tempo, as letras andam por igual de uma palavra conhecida até a outra
            frac = (i - antes) / (depois - antes)
            ini[i] = fim[i] = a + (b - a) * frac
        else:
            ini[i] = fim[i] = a if antes is not None else b
    return {"caracteres": list(texto), "inicio": ini, "fim": fim}


def _voz_do_windows(txt, wav):
    """A voz do próprio Windows (System.Speech), sem custo: a portuguesa (Maria) se estiver instalada, senão a padrão.
    O comando say só existe no Mac, e o modo offline não rodava no Windows."""
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$pt = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'pt*' } | Select-Object -First 1; "
        "if ($pt) { $s.SelectVoice($pt.VoiceInfo.Name) }; "
        f"$s.SetOutputToWaveFile('{wav}'); "
        f"$s.Speak([IO.File]::ReadAllText('{txt}', [Text.Encoding]::UTF8)); $s.Dispose()")
    rodar(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


def _voz_do_mac(texto, voz, wav):
    txt = wav.with_suffix(".txt")
    aiff = wav.with_suffix(".aiff")
    txt.write_text(texto, encoding="utf-8")
    if sys.platform == "win32" or not shutil.which("say"):
        bruto = wav.with_name(wav.stem + "_windows.wav")
        try:
            _voz_do_windows(txt, bruto)
            rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", bruto, "-ac", "1", "-ar", TAXA, "-c:a", "pcm_s16le", wav])
        except (RuntimeError, OSError):
            # sem voz no sistema (Windows sem o motor de voz, Linux): um tom baixo com a duração prevista do texto. É um
            # teste do fluxo da fábrica, sem custo; o tempo de cada letra sai proporcional. Silêncio puro não serve:
            # a normalização de volume do render recusa áudio sem som nenhum
            segundos = max(len(texto) / 15.0, 0.5)
            rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate={TAXA}",
                   "-t", f"{segundos:.2f}", "-af", "volume=0.05", "-ac", "1", "-c:a", "pcm_s16le", wav])
        bruto.unlink(missing_ok=True)
        txt.unlink(missing_ok=True)
        duracao = duracao_audio(wav)
        n = max(len(texto), 1)
        return {"caracteres": list(texto), "inicio": [duracao * i / n for i in range(n)],
                "fim": [duracao * (i + 1) / n for i in range(n)]}
    try:
        rodar(["say", "-v", voz.get("voz_offline", "Luciana"), "-o", aiff, "-f", txt])
    except RuntimeError:
        rodar(["say", "-v", "Luciana", "-o", aiff, "-f", txt])
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", aiff, "-ac", "1", "-ar", TAXA, "-c:a", "pcm_s16le", wav])
    aiff.unlink(missing_ok=True)
    txt.unlink(missing_ok=True)
    duracao = duracao_audio(wav)
    n = max(len(texto), 1)
    return {
        "caracteres": list(texto),
        "inicio": [duracao * i / n for i in range(n)],
        "fim": [duracao * (i + 1) / n for i in range(n)],
    }


def _mapear(bloco, alinhamento, duracao, deslocamento, tempos_ini, tempos_fim):
    """Copia o tempo de cada caractere falado para a posição dele no roteiro inteiro."""
    letras, ini, fim = [], [], []
    for c, s, e in zip(alinhamento["caracteres"], alinhamento["inicio"], alinhamento["fim"]):
        if e - s > LETRA_LONGA:
            s = e - 0.12  # a pausa antes da frase fica fora da primeira letra
        for letra in c:
            letras.append(letra)
            ini.append(s)
            fim.append(e)
    recebido = "".join(letras)
    if recebido == bloco.texto:
        pares = ((i, i) for i in range(len(recebido)))
    else:
        # a API às vezes normaliza espaços e símbolos; casamos os trechos iguais
        comparador = difflib.SequenceMatcher(None, bloco.texto, recebido, autojunk=False)
        pares = ((a + k, b + k) for a, b, tamanho in comparador.get_matching_blocks() for k in range(tamanho))
    for i_bloco, i_recebido in pares:
        posicao = bloco.ini + i_bloco
        tempos_ini[posicao] = deslocamento + min(ini[i_recebido], duracao)
        tempos_fim[posicao] = deslocamento + min(fim[i_recebido], duracao)


def _tempos_das_frases(roteiro, tempos_ini, tempos_fim, total):
    unidades = []
    for n, u in enumerate(tx.unidades(roteiro)):
        inis = [t for t in tempos_ini[u.ini:u.fim] if t is not None]
        fins = [t for t in tempos_fim[u.ini:u.fim] if t is not None]
        unidades.append({"id": n, "texto": u.texto, "c_ini": u.ini, "c_fim": u.fim,
                         "ini": inis[0] if inis else None, "fim": fins[-1] if fins else None})
    # frase sem tempo (raro) herda os limites das vizinhas
    for i, u in enumerate(unidades):
        if u["ini"] is None:
            u["ini"] = unidades[i - 1]["fim"] if i > 0 and unidades[i - 1]["fim"] is not None else 0.0
    for i in range(len(unidades) - 1, -1, -1):
        if unidades[i]["fim"] is None:
            unidades[i]["fim"] = unidades[i + 1]["ini"] if i + 1 < len(unidades) else total
    ultimo = 0.0
    for u in unidades:
        u["ini"] = round(max(u["ini"], ultimo), 3)
        u["fim"] = round(max(u["fim"], u["ini"]), 3)
        ultimo = u["ini"]
    return unidades


def _juntar(projeto, wavs):
    silencio = projeto.caminho("narracao", "silencio.wav")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"anullsrc=r={TAXA}:cl=mono",
           "-t", PAUSA_ENTRE_BLOCOS, "-c:a", "pcm_s16le", silencio])
    linhas = []
    for i, wav in enumerate(wavs):
        if i:
            linhas.append(f"file '{silencio}'")
        linhas.append(f"file '{wav}'")
    lista = projeto.caminho("narracao", "lista.txt")
    lista.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    destino = projeto.caminho("narracao.wav")
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lista, "-c:a", "pcm_s16le", destino])
    return destino


def _legendas(unidades, destino, tempos_ini, tempos_fim, largura=42, linhas=2):
    """Legenda para subir no YouTube (duas linhas) ou para gravar na tela (uma linha curta).

    Cada pedaço começa quando a primeira letra dele é falada e termina na última.
    """
    def carimbo(t):
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    pedacos = []
    for u in unidades:
        quebradas = textwrap.wrap(u["texto"], largura) or [u["texto"]]
        cursor = 0
        for k in range(0, len(quebradas), linhas):
            grupo = quebradas[k:k + linhas]
            a = u["texto"].find(grupo[0], cursor)
            b = u["texto"].find(grupo[-1], max(a, cursor)) + len(grupo[-1]) if a >= 0 else -1
            inicio_pedaco, fim_pedaco = u["ini"], u["fim"]
            if a >= 0 and b > a:
                cursor = b
                inis = [t for t in tempos_ini[u["c_ini"] + a:u["c_ini"] + b] if t is not None]
                fins = [t for t in tempos_fim[u["c_ini"] + a:u["c_ini"] + b] if t is not None]
                if inis and fins:
                    inicio_pedaco, fim_pedaco = inis[0], fins[-1]
            pedacos.append([inicio_pedaco, fim_pedaco, "\n".join(grupo)])

    # a legenda fica na tela até a próxima começar, com no máximo 0,6s depois da última palavra
    for i, pedaco in enumerate(pedacos):
        seguinte = pedacos[i + 1][0] if i + 1 < len(pedacos) else pedaco[1] + 0.6
        pedaco[1] = max(pedaco[0] + 0.3, min(seguinte, pedaco[1] + 0.6))

    saida = [f"{n}\n{carimbo(a)} --> {carimbo(b)}\n{texto}\n" for n, (a, b, texto) in enumerate(pedacos, 1)]
    destino.write_text("\n".join(saida), encoding="utf-8")
