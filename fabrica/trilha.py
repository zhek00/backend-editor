"""Trilha e efeitos sonoros compostos pelo modelo e tocados pelo código, sem custo e sem depender de arquivo de música.

O modelo principal lê os blocos do roteiro e escreve uma partitura: para cada bloco, o clima, o tom, o andamento, a
sequência de acordes, a intensidade e o som que marca a entrada do bloco. O código toca essa partitura com
sintetizadores simples (colchão de acordes, baixo, arpejo e pulso) e grava trilha/trilha.wav, que o render usa quando
o perfil não aponta músicas (ou aponta uma pasta vazia). Assim todo vídeo sai com trilha.

Os efeitos (passagem de ar, impacto, subida e um toque curto quando o texto entra na tela) também são tocados pelo
código e vão para o render nos momentos que a partitura e as cenas pedem. Perfil com efeitos da ElevenLabs ligados
continua com os dele.

Sem o modelo (modo offline, ou o modelo fora do ar) a partitura sai pelas regras de cada clima, então a trilha nunca
falta. Tudo fica guardado com uma assinatura: renderizar de novo não pede nada ao modelo nem toca de novo.
"""
import hashlib
import json
import math
import random
import wave
from pathlib import Path

from . import openrouter_local
from .util import rodar

VERSAO = 2  # sobe quando o jeito de tocar muda, para as trilhas guardadas serem tocadas de novo
TAXA = 24000  # a trilha não tem nada acima de 6 kHz: tocar em 24 kHz custa metade, e o FFmpeg leva para 48 kHz
TAXA_EFEITOS = 48000

NOTAS = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8,
         "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}
MODOS = {
    "maior": [0, 2, 4, 5, 7, 9, 11],
    "menor": [0, 2, 3, 5, 7, 8, 10],
    "dorico": [0, 2, 3, 5, 7, 9, 10],
    "lidio": [0, 2, 4, 6, 7, 9, 11],
}
EFEITOS = ("passagem", "impacto", "subida", "nenhum")

# o que cada clima toca quando o modelo não diz (ou diz algo fora do lugar)
CLIMAS = {
    "misterio": {"modo": "menor", "andamento": 66, "progressao": [1, 6, 4, 5], "intensidade": 2, "pulso": False},
    "tensao": {"modo": "menor", "andamento": 84, "progressao": [1, 1, 6, 7], "intensidade": 3, "pulso": True},
    "calma": {"modo": "maior", "andamento": 64, "progressao": [1, 5, 6, 4], "intensidade": 1, "pulso": False},
    "epico": {"modo": "menor", "andamento": 76, "progressao": [1, 6, 3, 7], "intensidade": 4, "pulso": True},
    "curiosidade": {"modo": "dorico", "andamento": 82, "progressao": [1, 4, 1, 7], "intensidade": 2, "pulso": False},
    "alegre": {"modo": "maior", "andamento": 96, "progressao": [1, 5, 6, 4], "intensidade": 3, "pulso": False},
    "triste": {"modo": "menor", "andamento": 60, "progressao": [1, 4, 6, 5], "intensidade": 1, "pulso": False},
    "maravilha": {"modo": "lidio", "andamento": 70, "progressao": [1, 2, 1, 5], "intensidade": 2, "pulso": False},
}

INSTRUCOES = f"""Você é o compositor da trilha de um vídeo documental narrado. A música fica BAIXA, por baixo da voz:
ela sustenta o clima de cada parte, nunca disputa atenção com a narração.

Para cada bloco do roteiro, escolha:
- clima: um destes: {", ".join(CLIMAS)}. Leia o que o bloco conta: revelação ou segredo é misterio, perigo ou
  conflito é tensao, conquista ou escala grandiosa é epico, explicação de como algo funciona é curiosidade,
  natureza bonita é maravilha ou calma, perda é triste.
- tonalidade: a nota do tom (C, C#, D, Eb, E, F, F#, G, Ab, A, Bb, B). Mantenha o MESMO tom em blocos vizinhos e
  só mude quando o clima mudar de verdade; o vídeo inteiro deve soar como uma trilha só.
- modo: maior, menor, dorico ou lidio.
- andamento: batidas por minuto, de 56 a 110. Narração calma pede andamento baixo.
- progressao: de 2 a 6 graus da escala (números de 1 a 7), a sequência de acordes que se repete no bloco.
- intensidade: de 1 (só um colchão suave) a 5 (arpejo e pulso cheios). A intensidade sobe nos momentos fortes do
  roteiro e desce na conclusão.
- pulso: true para uma batida grave e discreta em tensão ou épico, false no resto.
- efeito_entrada: o som que marca a entrada do bloco: passagem (troca de assunto), impacto (revelação forte),
  subida (algo grande vai acontecer) ou nenhum. Use impacto com parcimônia.

Responda só com o JSON pedido, um item para cada bloco, na mesma ordem e com o mesmo id."""

ESQUEMA = {
    "type": "object",
    "properties": {
        "secoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "clima": {"type": "string"},
                    "tonalidade": {"type": "string"},
                    "modo": {"type": "string"},
                    "andamento": {"type": "integer"},
                    "progressao": {"type": "array", "items": {"type": "integer"}},
                    "intensidade": {"type": "integer"},
                    "pulso": {"type": "boolean"},
                    "efeito_entrada": {"type": "string"},
                },
                "required": ["id", "clima", "tonalidade", "modo", "andamento", "progressao", "intensidade"],
            },
        }
    },
    "required": ["secoes"],
}


def config(projeto) -> dict:
    return {**(projeto.config.get("trilha") or {}), **(projeto.perfil.get("trilha") or {})}


def ligada(projeto) -> bool:
    return bool(config(projeto).get("ativo", True))


def efeitos_ligados(projeto) -> bool:
    return ligada(projeto) and bool(config(projeto).get("efeitos", True))


# ---------------------------------------------------------------- partitura

def _blocos(projeto):
    """Os blocos de assunto com o segundo em que cada um começa na narração.

    Vêm do campo bloco das cenas (o agente de roteiro marca). Projeto sem blocos é dividido em trechos de uns
    90 segundos, cortados no começo de uma cena."""
    cenas = projeto.ler_json("cenas.json")["cenas"]
    duracao = float(projeto.ler_json("alinhamento.json")["duracao"])
    nomes = {}
    if projeto.existe("roteiro_mapa.json"):
        try:
            nomes = {b.get("id"): b.get("nome", "") for b in projeto.ler_json("roteiro_mapa.json").get("blocos") or []}
        except (ValueError, OSError):
            nomes = {}
    blocos = []
    if any(c.get("bloco") for c in cenas):
        for c in cenas:
            b = c.get("bloco")
            if b is None:
                continue
            if not blocos or blocos[-1]["bloco"] != b:
                blocos.append({"id": len(blocos) + 1, "bloco": b, "nome": nomes.get(b, ""), "ini": float(c["ini"]),
                               "textos": []})
            blocos[-1]["textos"].append(c.get("texto", ""))
    if not blocos:
        for c in cenas:
            if not blocos or float(c["ini"]) - blocos[-1]["ini"] >= 90:
                blocos.append({"id": len(blocos) + 1, "bloco": None, "nome": "", "ini": float(c["ini"]), "textos": []})
            blocos[-1]["textos"].append(c.get("texto", ""))
    blocos[0]["ini"] = 0.0
    for atual, seguinte in zip(blocos, blocos[1:] + [None]):
        atual["fim"] = seguinte["ini"] if seguinte else duracao
    return [b for b in blocos if b["fim"] - b["ini"] > 0.5]


def _assinatura_blocos(blocos) -> str:
    base = json.dumps([(b["id"], round(b["ini"], 1), round(b["fim"], 1), " ".join(b["textos"])[:400]) for b in blocos],
                      ensure_ascii=False)
    return hashlib.sha1(base.encode()).hexdigest()[:12]


def _pedido(blocos) -> str:
    linhas = []
    for b in blocos:
        texto = " ".join(b["textos"])
        if len(texto) > 700:
            texto = texto[:450] + " [...] " + texto[-200:]
        linhas.append(f"BLOCO id={b['id']} ({b['fim'] - b['ini']:.0f} s){' — ' + b['nome'] if b['nome'] else ''}\n{texto}")
    return "Blocos do roteiro, em ordem:\n\n" + "\n\n".join(linhas)


def _secao_valida(bruta, bloco, anterior):
    """Confere o que o modelo escreveu e completa pelo clima. Nunca recusa: o que não serve vira o padrão do clima."""
    bruta = bruta if isinstance(bruta, dict) else {}
    clima = str(bruta.get("clima") or "").strip().lower()
    clima = clima.replace("é", "e").replace("ã", "a").replace("ê", "e")
    if clima not in CLIMAS:
        clima = anterior["clima"] if anterior else "misterio"
    padrao = CLIMAS[clima]
    tom = str(bruta.get("tonalidade") or "").strip().upper().replace("♯", "#").replace("♭", "B")
    tom = tom[:2] if tom[:2] in NOTAS else tom[:1]
    if tom not in NOTAS:
        tom = anterior["tonalidade"] if anterior else "D"
    modo = str(bruta.get("modo") or "").strip().lower().replace("ó", "o").replace("í", "i")
    if modo not in MODOS:
        modo = padrao["modo"]
    try:
        andamento = int(bruta.get("andamento"))
    except (TypeError, ValueError):
        andamento = padrao["andamento"]
    andamento = min(max(andamento, 56), 110)
    progressao = [int(g) for g in (bruta.get("progressao") or []) if isinstance(g, (int, float)) and 1 <= int(g) <= 7]
    if not 2 <= len(progressao) <= 6:
        progressao = list(padrao["progressao"])
    try:
        intensidade = int(bruta.get("intensidade"))
    except (TypeError, ValueError):
        intensidade = padrao["intensidade"]
    intensidade = min(max(intensidade, 1), 5)
    pulso = bruta.get("pulso")
    pulso = padrao["pulso"] if not isinstance(pulso, bool) else pulso
    efeito = str(bruta.get("efeito_entrada") or "").strip().lower()
    if efeito not in EFEITOS:
        efeito = "passagem"
    return {"id": bloco["id"], "ini": round(bloco["ini"], 3), "fim": round(bloco["fim"], 3), "clima": clima,
            "tonalidade": tom, "modo": modo, "andamento": andamento, "progressao": progressao,
            "intensidade": intensidade, "pulso": pulso, "efeito_entrada": efeito}


def compor(projeto, log=print, forcar=False):
    """Escreve (ou reaproveita) trilha/partitura.json. O modelo compõe; sem ele, as regras de cada clima."""
    blocos = _blocos(projeto)
    assinatura = _assinatura_blocos(blocos)
    destino = projeto.pasta / "trilha" / "partitura.json"
    if not forcar and destino.exists():
        try:
            guardada = json.loads(destino.read_text(encoding="utf-8"))
            if guardada.get("assinatura") == assinatura:
                return guardada
        except ValueError:
            pass
    respostas, autor = {}, "regras"
    if not projeto.offline:
        try:
            resposta = openrouter_local.perguntar(projeto, "trilha", INSTRUCOES, _pedido(blocos), ESQUEMA, log=log,
                                                  modelo=openrouter_local.principal(projeto), temperatura=0.4)
            respostas = {s.get("id"): s for s in resposta.get("secoes") or [] if isinstance(s, dict)}
            autor = "modelo"
        except (Exception, SystemExit) as erro:
            log(f"  trilha: o modelo não respondeu ({str(erro)[:120]}); a partitura sai pelas regras de cada clima")
    secoes, anterior = [], None
    for b in blocos:
        anterior = _secao_valida(respostas.get(b["id"]), b, anterior)
        secoes.append(anterior)
    partitura = {"assinatura": assinatura, "autor": autor, "secoes": secoes}
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(partitura, ensure_ascii=False, indent=1), encoding="utf-8")
    climas = ", ".join(dict.fromkeys(s["clima"] for s in secoes))
    log(f"  trilha composta ({'pelo modelo' if autor == 'modelo' else 'pelas regras'}): {len(secoes)} partes, {climas}")
    return partitura


# ---------------------------------------------------------------- síntese

def _np():
    import numpy
    return numpy


def _freq(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def _acorde(secao, grau):
    """Notas MIDI da tríade do grau, dentro do modo e do tom da seção."""
    escala = MODOS[secao["modo"]]
    raiz = NOTAS[secao["tonalidade"]]
    notas = []
    for passo in (0, 2, 4):
        i = grau - 1 + passo
        notas.append(raiz + escala[i % 7] + 12 * (i // 7))
    return notas


def _vozes(notas, anterior):
    """Escolhe a inversão mais perto do acorde anterior (as vozes andam pouco, como num arranjo de verdade)."""
    candidatas = []
    for oitava in (48, 60):
        base = [n + oitava for n in notas]
        for k in range(3):
            inv = sorted(base[k:] + [x + 12 for x in base[:k]])
            if 52 <= inv[0] and inv[-1] <= 76:
                candidatas.append(inv)
    if not candidatas:
        candidatas = [[n + 60 for n in notas]]
    if not anterior:
        return min(candidatas, key=lambda v: abs(sum(v) / 3 - 62))
    return min(candidatas, key=lambda v: sum(abs(a - b) for a, b in zip(v, anterior)))


def _tom(np, t, freq, harmonicos, fase=0.0):
    onda = np.zeros_like(t)
    for h in range(1, harmonicos + 1):
        if freq * h > TAXA * 0.24:
            break
        onda += np.sin(2 * np.pi * freq * h * t + fase * h) / h ** 1.6
    return onda


def _tocar_secao(np, secao, inicio_global, sorteio):
    """Uma seção da trilha em estéreo, com 2 s de sobra no fim para a fusão com a seguinte."""
    dur = secao["fim"] - secao["ini"]
    total = int((dur + 2.0) * TAXA)
    esquerda, direita = np.zeros(total, np.float32), np.zeros(total, np.float32)
    batida = 60.0 / secao["andamento"]
    compasso = 4 * batida
    tamanho = 2 * compasso if secao["intensidade"] <= 3 else compasso
    intens = secao["intensidade"]
    harmonicos = 2 + min(intens, 4)
    anterior, k, t0 = None, 0, 0.0
    while t0 < dur + 0.01:
        grau = secao["progressao"][k % len(secao["progressao"])]
        notas = _acorde(secao, grau)
        vozes = _vozes(notas, anterior)
        anterior = vozes
        cauda = 2.5
        n = int((tamanho + cauda) * TAXA)
        a = int(t0 * TAXA)
        n = min(n, total - a)
        if n <= 0:
            break
        t = np.arange(n, dtype=np.float32) / TAXA
        # envelope do colchão: entra devagar, segura e solta por cima do acorde seguinte
        env = np.clip(t / 1.4, 0, 1)
        env = np.sin(env * np.pi / 2) ** 2
        fim_env = np.clip((t - tamanho) / cauda, 0, 1)
        env *= np.cos(fim_env * np.pi / 2) ** 2
        env *= 1 + 0.07 * np.sin(2 * np.pi * 0.18 * (t + inicio_global + t0))
        pad_e, pad_d = np.zeros(n, np.float32), np.zeros(n, np.float32)
        for v in vozes:
            f = _freq(v)
            pad_e += _tom(np, t, f * 0.9972, harmonicos, sorteio.random() * 6.28)
            pad_d += _tom(np, t, f * 1.0028, harmonicos, sorteio.random() * 6.28)
        esquerda[a:a + n] += 0.11 * env * pad_e
        direita[a:a + n] += 0.11 * env * pad_d
        # baixo: a raiz do acorde duas oitavas abaixo, redondo
        raiz = notas[0] + 36
        while raiz > 47:
            raiz -= 12
        env_b = np.clip(t / 0.4, 0, 1) * np.cos(np.clip((t - tamanho) / cauda, 0, 1) * np.pi / 2) ** 2
        baixo = (np.sin(2 * np.pi * _freq(raiz) * t) + 0.25 * np.sin(4 * np.pi * _freq(raiz) * t)) * env_b
        peso_baixo = 0.0 if intens == 1 else 0.075
        esquerda[a:a + n] += peso_baixo * baixo
        direita[a:a + n] += peso_baixo * baixo
        # arpejo de sino: mais notas quanto maior a intensidade
        if intens >= 2:
            passo = {2: 2 * batida, 3: batida, 4: batida / 2, 5: batida / 2}[intens]
            notas_arp = [x + 12 for x in vozes] + [vozes[0] + 24]
            j, ta = 0, 0.0
            while ta < tamanho - 0.05:
                nota = notas_arp[j % len(notas_arp)] if j % 6 < 4 else notas_arp[(len(notas_arp) - 1 - j) % len(notas_arp)]
                ini = a + int(ta * TAXA)
                m = min(int(1.6 * TAXA), total - ini)
                if m > 0:
                    tt = np.arange(m, dtype=np.float32) / TAXA
                    f = _freq(nota)
                    som = (np.sin(2 * np.pi * f * tt) + 0.35 * np.sin(2 * np.pi * f * 2 * tt)
                           + 0.12 * np.sin(2 * np.pi * f * 3.01 * tt))
                    som *= np.exp(-tt * 3.2) * np.clip(tt / 0.006, 0, 1)
                    forca = 0.045 * (0.75 + 0.5 * sorteio.random())
                    lado = 0.5 + 0.35 * math.sin(j * 1.7)
                    esquerda[ini:ini + m] += forca * (1 - lado) * 2 * som
                    direita[ini:ini + m] += forca * lado * 2 * som
                ta += passo
                j += 1
        # pulso grave, discreto, nos tempos fortes
        if secao["pulso"] and intens >= 3:
            passo = batida if intens >= 4 else 2 * batida
            tp = 0.0
            while tp < tamanho - 0.05:
                ini = a + int(tp * TAXA)
                m = min(int(0.45 * TAXA), total - ini)
                if m > 0:
                    tt = np.arange(m, dtype=np.float32) / TAXA
                    fase = 2 * np.pi * (45 * tt + (25 / 18.0) * (1 - np.exp(-tt * 18)))
                    som = np.sin(fase) * np.exp(-tt * 9) * np.clip(tt / 0.004, 0, 1)
                    esquerda[ini:ini + m] += 0.22 * som
                    direita[ini:ini + m] += 0.22 * som
                tp += passo
        t0 += tamanho
        k += 1
    return esquerda, direita


def _gravar_wav(np, destino, esquerda, direita, taxa):
    pico = float(max(np.abs(esquerda).max(initial=0), np.abs(direita).max(initial=0), 1e-6))
    ganho = 0.89 / pico
    pares = np.empty(len(esquerda) * 2, np.int16)
    pares[0::2] = np.clip(esquerda * ganho * 32767, -32767, 32767).astype(np.int16)
    pares[1::2] = np.clip(direita * ganho * 32767, -32767, 32767).astype(np.int16)
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(pares.tobytes())


def gerar(projeto, log=print, forcar=False) -> Path | None:
    """O arquivo da trilha do projeto, composto e tocado se ainda não existir. None se a trilha estiver desligada."""
    if not ligada(projeto) or not projeto.existe("cenas.json") or not projeto.existe("alinhamento.json"):
        return None
    partitura = compor(projeto, log, forcar=forcar)
    pasta = projeto.pasta / "trilha"
    destino = pasta / "trilha.wav"
    marca = pasta / "trilha.json"
    assinatura = hashlib.sha1(f"{VERSAO}|{json.dumps(partitura['secoes'], sort_keys=True)}".encode()).hexdigest()[:12]
    if not forcar and destino.exists() and marca.exists():
        try:
            if json.loads(marca.read_text(encoding="utf-8")).get("assinatura") == assinatura:
                return destino
        except ValueError:
            pass
    np = _np()
    secoes = partitura["secoes"]
    duracao = secoes[-1]["fim"]
    total = int((duracao + 2.5) * TAXA)
    esquerda, direita = np.zeros(total, np.float32), np.zeros(total, np.float32)
    sorteio = random.Random(projeto.nome)
    fusao = int(2.0 * TAXA)
    ultima = len(secoes) - 1
    for i, secao in enumerate(secoes):
        e, d = _tocar_secao(np, secao, secao["ini"], sorteio)
        # cada troca de parte é uma fusão de 2 s centrada no começo do bloco: a anterior sai enquanto a nova entra
        a = max(int(secao["ini"] * TAXA) - (fusao // 2 if i > 0 else 0), 0)
        b = int(secao["fim"] * TAXA) + (fusao // 2 if i < ultima else fusao)
        n = min(len(e), b - a, total - a)
        rampa = np.ones(n, np.float32)
        if i > 0:
            rampa[:fusao] = np.linspace(0, 1, fusao, dtype=np.float32)
        if i < ultima:
            rampa[-fusao:] = np.linspace(1, 0, fusao, dtype=np.float32)
        esquerda[a:a + n] += e[:n] * rampa
        direita[a:a + n] += d[:n] * rampa
    pasta.mkdir(parents=True, exist_ok=True)
    seco = pasta / "trilha_seca.wav"
    _gravar_wav(np, seco, esquerda, direita, TAXA)
    # ambiente: ecos curtos espalhados fazem o papel de uma sala, e a taxa sobe para a do vídeo
    temporario = pasta / "trilha.tmp.wav"
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", seco, "-af",
           "aecho=0.8:0.55:61|113|197|283|379:0.32|0.26|0.2|0.15|0.1,highpass=f=45,lowpass=f=7000,aresample=48000",
           "-c:a", "pcm_s16le", temporario])
    temporario.replace(destino)
    seco.unlink(missing_ok=True)
    marca.write_text(json.dumps({"assinatura": assinatura, "versao": VERSAO}), encoding="utf-8")
    log(f"  trilha tocada: {duracao / 60:.1f} min em {destino.relative_to(projeto.pasta).as_posix()}")
    return destino


# ---------------------------------------------------------------- efeitos

VOLUME_EFEITOS = {"passagem": -17, "impacto": -13, "subida": -19, "toque": -24}  # depois do pico levado a -1 dB
DURACAO_EFEITOS = {"passagem": 1.3, "impacto": 2.6, "subida": 2.2, "toque": 0.3}


def _efeito(nome) -> Path:
    """O arquivo do efeito, tocado uma vez e guardado na biblioteca efeitos/gerados para todo projeto usar."""
    from .config import caminho_relativo

    pasta = caminho_relativo("efeitos") / "gerados"
    destino = pasta / f"{nome}-v{VERSAO}.wav"
    if destino.exists():
        return destino
    np = _np()
    sorteio = np.random.default_rng(len(nome) * 7919 + VERSAO)
    dur = DURACAO_EFEITOS[nome]
    n = int(dur * TAXA_EFEITOS)
    t = np.arange(n, dtype=np.float32) / TAXA_EFEITOS
    x = t / dur
    if nome == "passagem":
        # ar passando: muitos senos em volta de um centro que sobe e desce, atravessando da esquerda para a direita
        centro = 350 + 2200 * np.sin(np.pi * x) ** 2
        fase_base = 2 * np.pi * np.cumsum(centro) / TAXA_EFEITOS
        som = np.zeros(n, np.float32)
        for fator in sorteio.uniform(0.55, 1.6, 90):
            som += np.sin(fase_base * fator + sorteio.uniform(0, 6.28))
        env = np.sin(np.pi * np.clip(x / 0.62, 0, 1) / 2) ** 3 * np.clip((1 - x) / 0.38, 0, 1) ** 1.5
        som *= env
        lado = np.clip(x, 0, 1)
        esquerda, direita = som * (1 - lado * 0.8), som * (0.2 + lado * 0.8)
    elif nome == "impacto":
        fase = 2 * np.pi * (38 * t + (24 / 6.0) * (1 - np.exp(-t * 6)))
        grave = np.sin(fase) * np.exp(-t * 2.4)
        baque = np.zeros(n, np.float32)
        for f in sorteio.uniform(80, 420, 40):
            baque += np.sin(2 * np.pi * f * t + sorteio.uniform(0, 6.28))
        baque *= np.exp(-t * 22) / 12
        som = (grave + baque) * np.clip(t / 0.003, 0, 1)
        esquerda = direita = som
    elif nome == "subida":
        som = np.zeros(n, np.float32)
        for k, base in enumerate((180, 270, 360, 540)):
            f = base * (1 + 4 * x ** 2)
            som += np.sin(2 * np.pi * np.cumsum(f) / TAXA_EFEITOS + k) / (k + 1)
        ar = np.zeros(n, np.float32)
        centro = 500 + 3500 * x ** 2
        fase_base = 2 * np.pi * np.cumsum(centro) / TAXA_EFEITOS
        for fator in sorteio.uniform(0.6, 1.5, 50):
            ar += np.sin(fase_base * fator + sorteio.uniform(0, 6.28)) / 12
        som = (som + ar) * x ** 2.2 * np.clip((1 - x) / 0.03, 0, 1)
        esquerda = direita = som
    else:  # toque: um estalo de madeira, curto e baixo
        f = 880 * (1 - 0.25 * np.clip(t / 0.05, 0, 1))
        fase = 2 * np.pi * np.cumsum(f) / TAXA_EFEITOS
        som = (np.sin(fase) + 0.3 * np.sin(2 * fase)) * np.exp(-t * 32) * np.clip(t / 0.002, 0, 1)
        esquerda = direita = som
    pasta.mkdir(parents=True, exist_ok=True)
    seco = destino.with_name(destino.stem + ".seco.wav")
    _gravar_wav(np, seco, np.asarray(esquerda, np.float32), np.asarray(direita, np.float32), TAXA_EFEITOS)
    eco = "aecho=0.8:0.5:47|89|151:0.3|0.22|0.15," if nome != "toque" else ""
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", seco, "-af", f"{eco}apad=pad_dur=0.4",
           "-c:a", "pcm_s16le", destino])
    seco.unlink(missing_ok=True)
    return destino


def efeitos_na_linha(projeto, cenas, log=print):
    """(segundo da narração, arquivo, volume em dB) de cada efeito gerado. Um efeito a cada 6 s no máximo.

    Ordem de prioridade: cartão de título (impacto), entrada de bloco (o efeito da partitura) e texto na tela
    (um toque curto). Cena animada não ganha o toque, porque a animação já tem o próprio ritmo."""
    if not efeitos_ligados(projeto):
        return []
    try:
        partitura = compor(projeto, log)
    except (Exception, SystemExit) as erro:
        log(f"  efeitos gerados ficaram de fora: {str(erro)[:120]}")
        return []
    pedidos = []
    for c in cenas:
        for t in c.get("titulos") or []:
            pedidos.append((0, float(c["ini"]) + float(t.get("inicio", 0.0)), "impacto"))
    for s in partitura["secoes"][1:]:
        efeito = s.get("efeito_entrada")
        if efeito == "subida":
            pedidos.append((1, max(s["ini"] - DURACAO_EFEITOS["subida"], 0.0), "subida"))
        elif efeito in ("passagem", "impacto"):
            # a passagem começa um pouco antes, para o ar passar bem no corte
            pedidos.append((1, max(s["ini"] - (0.55 if efeito == "passagem" else 0.0), 0.0), efeito))
    escolhidos = []
    for prioridade, momento, nome in sorted(pedidos):
        if all(abs(momento - m) >= 6.0 for m, _ in escolhidos):
            escolhidos.append((momento, nome))
    ajuste = float(config(projeto).get("volume_efeitos_db", 0))
    resultado = []
    for momento, nome in sorted(escolhidos):
        resultado.append((round(momento, 3), _efeito(nome), VOLUME_EFEITOS[nome] + ajuste))
    return resultado
