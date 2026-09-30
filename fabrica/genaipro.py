"""Narração pela GenAIPro, que revende as vozes e os modelos da ElevenLabs com créditos próprios.

A GenAIPro trabalha por tarefa: a fábrica pede o áudio, espera a tarefa ficar pronta e baixa o mp3.
Ela não devolve o tempo de cada letra como a ElevenLabs devolvia. O tempo de cada palavra vem da
legenda que ela mesma gera: pedindo um caractere por linha, cada bloco da legenda é uma palavra só,
com o tempo em milissegundos.

Cada tarefa criada fica anotada ao lado do áudio antes de esperar por ela. Se a fábrica cair no meio,
rodar de novo retoma a mesma tarefa, sem pagar outra vez.

Medido em 30/09/2026: todos os modelos gastam 1 crédito por caractere, e a velocidade só vai de 0,7 a 1,2.
As vozes padrão da ElevenLabs (George, Rachel...) são recusadas: só valem as vozes da biblioteca.
"""
import json
import os
import re
import time

import httpx

from .config import config_geral

URL_PADRAO = "https://genaipro.io/api"
NOMES_DA_CHAVE = ("GENAIPRO_API", "GENAIPRO_API_KEY")
MODELOS = ("eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_flash_v2_5", "eleven_v3")
MODELO_PADRAO = "eleven_multilingual_v2"
VELOCIDADE_MIN, VELOCIDADE_MAX = 0.7, 1.2
ESPERA_MAXIMA = 20 * 60  # uma tarefa grande pode ficar na fila da GenAIPro por alguns minutos


class ErroGenAIPro(SystemExit):
    """Erro com mensagem em português, que o editor e o terminal mostram como está."""


def chave() -> str:
    for nome in NOMES_DA_CHAVE:
        valor = os.environ.get(nome, "").strip().strip('"').strip("'")
        if valor:
            return valor
    raise ErroGenAIPro("Falta a chave da GenAIPro. Cole em GENAIPRO_API no arquivo .env.")


def tem_chave() -> bool:
    return any(os.environ.get(nome, "").strip() for nome in NOMES_DA_CHAVE)


def _url() -> str:
    return ((config_geral().get("genaipro") or {}).get("url") or URL_PADRAO).rstrip("/")


def _cabecalho() -> dict:
    # sem um User-Agent de navegador a GenAIPro às vezes recusa a conexão
    return {"Authorization": f"Bearer {chave()}", "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (fabrica-de-videos)"}


def _pedir(metodo, caminho, tentativas=4, **kw):
    """Chama a API e repete sozinho quando a falha é passageira (rede, 429 ou 5xx)."""
    erro, espera = "", kw.pop("timeout", 60)
    for tentativa in range(tentativas):
        try:
            r = httpx.request(metodo, _url() + caminho, headers=_cabecalho(), timeout=espera, **kw)
        except httpx.TransportError as e:
            erro = str(e)
        else:
            if r.status_code < 400:
                return r
            if r.status_code in (401, 403):
                raise ErroGenAIPro(f"A GenAIPro recusou a chave ({r.status_code}). Confira GENAIPRO_API no .env.")
            if r.status_code not in (429, 500, 502, 503, 504):
                raise ErroGenAIPro(f"A GenAIPro recusou o pedido ({r.status_code}). {_motivo(r)}")
            erro = r.text
        time.sleep(4 * (tentativa + 1))
    raise ErroGenAIPro(f"A GenAIPro falhou depois de {tentativas} tentativas. {erro[:300]}")


def _motivo(r) -> str:
    try:
        corpo = r.json()
    except ValueError:
        return r.text[:300]
    motivo = corpo.get("error") or corpo.get("message") or r.text[:300]
    traducoes = {
        "invalid_voice_id": "Essa voz não existe na GenAIPro. Escolha uma voz da biblioteca (fabrica vozes).",
        "insufficient_credits": "Os créditos da GenAIPro acabaram.",
    }
    return traducoes.get(motivo, motivo)


# ---------------------------------------------------------------- conta

def conta() -> dict:
    """Usuário e créditos ativos. Não gasta nada."""
    usuario = _pedir("GET", "/v2/me").json()
    pacotes = _pedir("GET", "/v1/labs/credits").json() or []
    pacotes = sorted(pacotes, key=lambda p: p.get("expire_at") or "")
    return {
        "usuario": usuario.get("username", ""),
        "creditos": sum(int(p.get("amount") or 0) for p in pacotes),
        "pacotes": [{"creditos": int(p.get("amount") or 0), "vence": p.get("expire_at")} for p in pacotes],
    }


def vozes(busca=None, idioma=None, genero=None, uso=None, quantidade=30, pagina=0) -> list:
    """Vozes da biblioteca, já no formato que a fábrica usa. Não gasta nada."""
    parametros = {"page": pagina, "page_size": quantidade, "sort": "trending"}
    for nome, valor in (("search", busca), ("language", idioma), ("gender", genero)):
        if valor:
            parametros[nome] = valor
    if uso:
        parametros["use_cases"] = uso
    dados = _pedir("GET", "/v1/labs/voices", params=parametros).json() or []
    return [_voz(v) for v in dados]


def _voz(v: dict) -> dict:
    genero = {"male": "masculina", "female": "feminina", "neutral": "neutra"}.get(v.get("gender"), "")
    idade = {"young": "jovem", "middle_aged": "meia-idade", "old": "madura"}.get(v.get("age"), "")
    return {
        "voice_id": v.get("voice_id"),
        "nome": (v.get("name") or "").strip(),
        "genero": genero,
        "idade": idade,
        "sotaque": v.get("accent") or "",
        "idioma": v.get("language") or "",
        "uso": v.get("use_case") or "",
        "descricao": (v.get("description") or "").strip(),
        "previa": v.get("preview_url") or "",
        "usos_no_ano": v.get("usage_character_count_1y") or 0,
    }


# ---------------------------------------------------------------- narração

def corpo_da_tarefa(texto: str, voz: dict) -> dict:
    voice_id = str(voz.get("voice_id") or "").strip()
    if not voice_id or "COLE" in voice_id:
        raise ErroGenAIPro("Defina voz.voice_id no perfil do canal. Rode uv run fabrica vozes TERMO para escolher uma.")
    modelo = voz.get("modelo") or MODELO_PADRAO
    if modelo not in MODELOS:
        modelo = MODELO_PADRAO
    velocidade = float(voz.get("velocidade") or 1.0)
    return {
        "input": texto,
        "voice_id": voice_id,
        "model_id": modelo,
        "speed": round(min(max(velocidade, VELOCIDADE_MIN), VELOCIDADE_MAX), 2),
        "stability": float(voz.get("estabilidade", 0.5)),
        "similarity": float(voz.get("similaridade", 0.75)),
        "style": float(voz.get("estilo", 0.0)),
        "use_speaker_boost": bool(voz.get("reforco_de_voz", True)),
    }


def narrar(texto: str, voz: dict, mp3, log=print) -> list:
    """Grava o texto em mp3 e devolve [(palavra, início, fim)] como a GenAIPro mediu.

    A tarefa fica anotada em <mp3>.tarefa.json antes da espera: rodar de novo com o mesmo texto e a
    mesma voz retoma a tarefa já paga em vez de criar outra."""
    corpo = corpo_da_tarefa(texto, voz)
    anotacao = mp3.with_name(mp3.name + ".tarefa.json")
    tarefa_id = None
    if anotacao.exists():
        try:
            anterior = json.loads(anotacao.read_text(encoding="utf-8"))
            if anterior.get("corpo") == corpo:
                tarefa_id = anterior.get("id")
        except (OSError, ValueError):
            pass
    if tarefa_id:
        log("    retomando a tarefa já paga na GenAIPro")
    else:
        tarefa_id = _pedir("POST", "/v1/labs/task", json=corpo).json()["task_id"]
        anotacao.write_text(json.dumps({"id": tarefa_id, "corpo": corpo}, ensure_ascii=False), encoding="utf-8")

    tarefa = _esperar(tarefa_id, lambda t: t.get("result"))
    r = httpx.get(tarefa["result"], timeout=300, follow_redirects=True)
    r.raise_for_status()
    mp3.write_bytes(r.content)
    palavras = legenda_por_palavra(tarefa_id, tarefa)
    anotacao.unlink(missing_ok=True)
    return palavras


def _esperar(tarefa_id, pronta, limite=ESPERA_MAXIMA) -> dict:
    inicio, pausa = time.time(), 1.5
    while True:
        tarefa = _pedir("GET", f"/v1/labs/task/{tarefa_id}").json()
        if pronta(tarefa):
            return tarefa
        if str(tarefa.get("status", "")).lower() in ("failed", "error", "cancelled"):
            raise ErroGenAIPro(f"A GenAIPro não conseguiu gravar o áudio (tarefa {tarefa_id}). "
                               f"{tarefa.get('error') or 'Tente de novo.'}")
        if time.time() - inicio > limite:
            raise ErroGenAIPro(f"A GenAIPro não terminou em {limite // 60} minutos. Rode de novo: a mesma tarefa "
                               "é retomada, sem pagar outra vez.")
        time.sleep(pausa)
        pausa = min(pausa * 1.3, 8.0)


def legenda_por_palavra(tarefa_id, tarefa=None) -> list:
    """Pede a legenda com uma palavra por bloco e devolve [(palavra, início, fim)]. Não gasta créditos."""
    if not (tarefa or {}).get("subtitle"):
        try:
            _pedir("POST", f"/v1/labs/task/subtitle/{tarefa_id}", timeout=120,
                   json={"max_characters_per_line": 1, "max_lines_per_cue": 1, "max_seconds_per_cue": 1})
        except ErroGenAIPro as e:
            if "already" not in str(e).lower():
                raise
        tarefa = _esperar(tarefa_id, lambda t: t.get("subtitle"), limite=180)
    r = httpx.get(tarefa["subtitle"], timeout=120, follow_redirects=True)
    r.raise_for_status()
    return ler_srt(r.content.decode("utf-8", errors="replace"))


_TEMPO = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def ler_srt(conteudo: str) -> list:
    """Palavras de uma legenda SRT ou VTT. Bloco com mais de uma palavra divide o tempo pelo tamanho delas."""
    palavras = []
    for bloco in re.split(r"\n\s*\n", conteudo.replace("\r", "")):
        linhas = bloco.strip().split("\n")
        for i, linha in enumerate(linhas):
            m = _TEMPO.search(linha)
            if not m:
                continue
            g = [int(x) for x in m.groups()]
            t0 = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
            t1 = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
            texto = " ".join(linhas[i + 1:]).split()
            total = sum(len(p) for p in texto) or 1
            cursor = t0
            for p in texto:
                fim = cursor + (t1 - t0) * len(p) / total
                palavras.append((p, cursor, fim))
                cursor = fim
            break
    return palavras
