"""Vídeo de IA: uma parte das cenas de imagem de IA ganha movimento de verdade.

Sem `video_ia.fracao` nada acontece, e é assim por padrão: cada clipe é pago à parte e custa bem mais que uma imagem. A
imagem da cena é a primeira imagem do clipe, então ele mostra o que já foi aprovado. O prompt da cena pede o movimento.
Quem faz é o Kie (KIE_API_KEY), a mesma chave das imagens: a imagem sobe por 24 h, e o clipe sai da fila de tarefas.

As cenas escolhidas ficam espalhadas pelo vídeo, em vez de amontoadas no começo. Clipe que falha só deixa a cena como
estava, com a imagem parada: nada aqui para a produção.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .config import chave

MODELO = "kling/v2-1-standard"
URL_UPLOAD = "https://kieai.redpandaai.co/api/file-stream-upload"
URL_TAREFA = "https://api.kie.ai/api/v1/jobs/createTask"
URL_ESTADO = "https://api.kie.ai/api/v1/jobs/recordInfo"
PRAZO = 600  # segundos para o clipe sair da fila
PRECO_POR_CLIPE = 0.15  # US$, 5 s, conta de chegada: o custo real é o que o Kie desconta dos créditos
PROCESSOS = 3
MOVIMENTO = "subtle natural motion, slow camera drift, keep the same subject and composition"
_trava = threading.Lock()


def config(projeto) -> dict:
    return projeto.config.get("video_ia") or {}


def candidatas(projeto, cenas: list) -> list:
    """As cenas de imagem de IA que viram vídeo, espalhadas pelo vídeo, até `fracao` delas."""
    fracao = float(config(projeto).get("fracao") or 0)
    if fracao <= 0:
        return []
    de_ia = [c for c in cenas if not c.get("midia") and projeto.imagem(c["n"]).exists()]
    quantas = round(len(de_ia) * min(fracao, 1))
    if not quantas:
        return []
    passo = len(de_ia) / quantas
    return [de_ia[int(i * passo)] for i in range(quantas)]


def _subir_imagem(http, cabecalho, imagem) -> str:
    with open(imagem, "rb") as f:
        r = http.post(URL_UPLOAD, headers=cabecalho, data={"uploadPath": "images/fabrica", "fileName": imagem.name},
                      files={"file": (imagem.name, f, "image/jpeg")}, timeout=120)
    dados = r.json()
    if not dados.get("success"):
        raise RuntimeError(f"o Kie recusou a imagem: {str(dados.get('msg'))[:160]}")
    return dados["data"]["downloadUrl"]


def _pedir_clipe(http, cabecalho, modelo, url_imagem, prompt) -> str:
    r = http.post(URL_TAREFA, headers=cabecalho, timeout=60, json={
        "model": modelo, "input": {"prompt": prompt[:4900], "image_url": url_imagem, "duration": "5"}})
    dados = r.json()
    if dados.get("code") != 200:
        raise RuntimeError(f"o Kie recusou o clipe ({dados.get('code')}): {str(dados.get('msg'))[:160]}")
    return dados["data"]["taskId"]


def _esperar_clipe(http, cabecalho, tarefa, dormir=time.sleep) -> str:
    limite = time.monotonic() + PRAZO
    while time.monotonic() < limite:
        dormir(8)
        r = http.get(URL_ESTADO, params={"taskId": tarefa}, headers=cabecalho, timeout=30)
        dados = (r.json() or {}).get("data") or {}
        estado = str(dados.get("state") or "").lower()
        if estado == "success":
            return json.loads(dados["resultJson"])["resultUrls"][0]
        if estado == "fail":
            raise RuntimeError(f"o Kie não fez o clipe: {str(dados.get('failMsg'))[:160]}")
    raise RuntimeError(f"o clipe passou de {PRAZO} s na fila do Kie")


def _clipe(projeto, cena, modelo) -> dict:
    from . import custos_reais

    imagem = projeto.imagem(cena["n"])
    cabecalho = {"Authorization": f"Bearer {chave('KIE_API_KEY')}"}
    prompt = f"{str(cena.get('prompt') or cena.get('mostrar') or '')[:400]}. {MOVIMENTO}"
    with httpx.Client(follow_redirects=True) as http:
        url_imagem = _subir_imagem(http, cabecalho, imagem)
        url_video = _esperar_clipe(http, cabecalho, _pedir_clipe(http, cabecalho, modelo, url_imagem, prompt))
    destino = projeto.caminho("midia", f"{cena['n']:04d}_ia.mp4")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url_video, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with open(destino, "wb") as saida:
            for parte in r.iter_bytes():
                saida.write(parte)
    custos_reais.registrar(projeto, "video_ia", f"vídeo de IA da cena {cena['n']}", PRECO_POR_CLIPE, unidades=1,
                           detalhes={"cena": cena["n"], "provedor": "kie", "modelo": modelo})
    return {"fonte": "video_ia", "id": f"ia{cena['n']}", "tipo": "video", "duracao": 5.0, "pagina": "", "autor": "", "licenca": "",
            "arquivo": str(destino.relative_to(projeto.pasta)), "capa": str(imagem.relative_to(projeto.pasta))}


def gerar(projeto, log=print) -> int:
    """Faz os clipes que faltam e grava nas cenas. Devolve quantos saíram."""
    if projeto.offline:
        return 0
    dados = projeto.ler_json("cenas.json")
    alvo = candidatas(projeto, dados["cenas"])
    if not alvo:
        return 0
    modelo = config(projeto).get("modelo") or MODELO
    log(f"  vídeo de IA: {len(alvo)} clipe(s), perto de US$ {len(alvo) * PRECO_POR_CLIPE:.2f}")

    def um(cena):
        try:
            return cena, _clipe(projeto, cena, modelo)
        except (RuntimeError, httpx.HTTPError, OSError, KeyError, ValueError, SystemExit) as erro:
            log(f"  vídeo de IA: a cena {cena['n']} fica com a imagem ({str(erro)[:120]})")
            return cena, None

    with ThreadPoolExecutor(int(config(projeto).get("processos") or PROCESSOS)) as executor:
        feitos = list(executor.map(um, alvo))
    prontos = 0
    for cena, registro in feitos:
        if registro:
            cena["midia"] = registro
            prontos += 1
    if prontos:
        with _trava:
            projeto.salvar_json("cenas.json", dados)
    log(f"  vídeo de IA: {prontos} de {len(alvo)} clipe(s) prontos")
    return prontos
