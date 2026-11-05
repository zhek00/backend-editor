"""O robô: esta fábrica pega vídeos da fila de um Radar que está em outra máquina (radar/maquinas.py).

`fabrica maquina` fica ligado do lado da fábrica desta máquina (porta 8080). A cada volta ele pede trabalho ao Radar. Com
um pedido na mão, cria o projeto, manda a fábrica produzir, bate no Radar enquanto ela trabalha e, no fim, manda a prova
da entrega: tamanho, duração e SHA-256 do vídeo, que fica nesta máquina.

O lease é o que manda. Se o Radar responder 409 (lease_velha), o vídeo não é mais desta máquina: o robô larga o pedido
sem avisar mais nada e volta a pedir trabalho. Queda de rede não larga nada: ele tenta de novo na batida seguinte, e o
que já está no disco não se perde, porque o projeto de um pedido tem sempre o mesmo nome (robo-ID) e a fábrica retoma.

As chaves de API são as desta máquina, e o gasto também. ROBO.ps1 relança depois de queda, com teto por hora.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from .projeto import PROJETOS

RAIZ = Path(__file__).resolve().parents[1]
PEDIR_A_CADA = 30      # segundos entre os pedidos de trabalho, com a máquina livre
BATER_A_CADA = 30      # segundos entre as batidas, bem dentro do lease
ATUALIZAR_A_CADA = 6 * 3600
PRAZO_DO_VIDEO = 12 * 3600
SAIDA_ATUALIZADO = 75  # o ROBO.ps1 relança na hora, já com o código novo


class LeaseVelha(RuntimeError):
    """O Radar disse que este vídeo não é mais desta máquina."""


def capacidades(pasta=PROJETOS) -> dict:
    """O que o Radar mostra desta máquina."""
    versao = subprocess.run(["git", "-C", str(RAIZ), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return {"nucleos": os.cpu_count() or 0, "disco_livre_gb": round(shutil.disk_usage(pasta).free / 2**30, 1),
            "versao": versao.stdout.strip()}


def prova_do_video(arquivo: Path) -> dict:
    """O que prova que o vídeo existe de verdade, sem mandar o vídeo."""
    resumo = hashlib.sha256()
    with open(arquivo, "rb") as f:
        for bloco in iter(lambda: f.read(2**20), b""):
            resumo.update(bloco)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(arquivo)],
                       capture_output=True, text=True)
    return {"bytes": arquivo.stat().st_size, "duracao": float(r.stdout.strip() or 0), "sha256": resumo.hexdigest()}


def _criar_na_fabrica(nome: str, roteiro: Path, perfil: str) -> None:
    """O mesmo `fabrica novo` que o Radar usa nesta máquina."""
    codigo = "from fabrica.cli import main; main()"
    r = subprocess.run([sys.executable, "-c", codigo, "novo", nome, "--roteiro", str(roteiro), "--perfil",
                        f"perfis/{perfil}.yaml", "--sim"], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300)
    if r.returncode:
        raise RuntimeError(f"a fábrica não criou o projeto: {(r.stderr or r.stdout or '')[-300:]}")


def atualizar(raiz=RAIZ, provar=None, log=print) -> bool:
    """Puxa a versão nova e volta para a de antes se ela não abrir. Devolve True quando há código novo no disco.

    Com mudança local não mexe em nada: atualizar por cima dela já mandou trabalho para o stash nesta fábrica."""
    def git(*args):
        return subprocess.run(["git", "-C", str(raiz), *args], capture_output=True, text=True)

    if git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        log("  robô: há mudanças locais, não atualizo")
        return False
    antes = git("rev-parse", "HEAD").stdout.strip()
    if git("pull", "--ff-only", "--quiet").returncode:
        return False
    depois = git("rev-parse", "HEAD").stdout.strip()
    if depois == antes:
        return False
    provar = provar or (lambda: subprocess.run([sys.executable, "-c", "import fabrica.cli, fabrica.api"], cwd=raiz,
                                               capture_output=True).returncode == 0)
    if provar():
        log(f"  robô: atualizado de {antes[:8]} para {depois[:8]}")
        return True
    git("reset", "--hard", antes)
    log(f"  robô: a versão {depois[:8]} não abriu; voltei para {antes[:8]}")
    return False


class Robo:
    def __init__(self, radar, chave, fabrica="http://127.0.0.1:8080", token="", http=None, pasta=PROJETOS, log=print,
                 criar=_criar_na_fabrica, provar=prova_do_video, dormir=time.sleep):
        self.radar, self.fabrica = radar.rstrip("/"), fabrica.rstrip("/")
        self.chave, self.token = chave, token
        self.http = http or httpx.Client(timeout=30)
        self.pasta, self.log = Path(pasta), log
        self.criar, self.provar, self.dormir = criar, provar, dormir

    # ---- as duas conversas ------------------------------------------------------------------------
    def _ao_radar(self, rota: str, corpo: dict) -> dict:
        r = self.http.post(f"{self.radar}/api/robo/{rota}", json=corpo, headers={"x-robo-chave": self.chave})
        if r.status_code == 409:
            raise LeaseVelha(corpo.get("id"))
        if r.status_code == 401:
            raise SystemExit("O Radar recusou a chave desta máquina. Crie outra em Acompanhar > Máquinas.")
        r.raise_for_status()
        return r.json()

    def _fabrica(self, metodo: str, rota: str, corpo=None) -> dict:
        r = self.http.request(metodo, f"{self.fabrica}{rota}", json=corpo, headers={"x-fabrica-token": self.token})
        r.raise_for_status()
        return r.json()

    # ---- um vídeo ---------------------------------------------------------------------------------
    def preparar(self, trabalho: dict) -> str:
        """Cria o projeto do pedido, se ainda não existir. Mesmo nome sempre: um lease retomado continua de onde parou."""
        nome = trabalho["projeto"]
        destino = self.pasta / nome
        if not (destino / "projeto.json").exists():
            with tempfile.TemporaryDirectory() as temporaria:
                roteiro = Path(temporaria) / "roteiro.txt"
                roteiro.write_text(trabalho["roteiro"], encoding="utf-8")
                self.criar(nome, roteiro, trabalho["perfil"])
            dados = json.loads((destino / "projeto.json").read_text(encoding="utf-8"))
            dados["titulo_entrega"] = trabalho.get("titulo_entrega") or trabalho.get("titulo") or nome
            for chave in ("config_override", "perfil_override"):
                if trabalho.get(chave):
                    dados[chave] = {**(dados.get(chave) or {}), **trabalho[chave]}
            (destino / "projeto.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        return nome

    def _data_do_final(self, nome: str) -> float:
        final = self.pasta / nome / "final.mp4"
        return final.stat().st_mtime if final.is_file() else 0.0

    def _pronto(self, nome: str, status: dict, data_antes: float) -> bool:
        """A criação termina com o render começando sozinho: só o render concluído, com o vídeo no disco, é o fim.

        O vídeo tem de ser outro que o de antes deste lease. Compara a data do arquivo com ela mesma, e não com o
        time.time(): o Windows carimba o arquivo um instante antes do relógio de quem pediu."""
        return (status.get("status") == "concluido" and str(status.get("tarefa_id") or "").startswith("render_")
                and self._data_do_final(nome) > data_antes)

    def produzir(self, trabalho: dict) -> None:
        fid, lease = trabalho["id"], trabalho["lease"]
        comeco = time.time()
        try:
            nome = self.preparar(trabalho)
            data_antes = self._data_do_final(nome)
            self._fabrica("POST", f"/api/projetos/{nome}/retomar", {"confirmar": True})
            ultimo = ""
            while time.time() - comeco < PRAZO_DO_VIDEO:
                try:
                    status = self._fabrica("GET", f"/api/projetos/{nome}/status")
                except httpx.HTTPError as erro:
                    self.log(f"  robô: a fábrica não respondeu ({str(erro)[:80]})")
                    status = {}
                if status.get("status") == "erro":
                    raise RuntimeError(status.get("erro") or status.get("mensagem") or "a fábrica parou com erro")
                if self._pronto(nome, status, data_antes):
                    self._ao_radar("concluir", {"id": fid, "lease": lease, "prova": self.provar(self.pasta / nome / "final.mp4")})
                    self.log(f"  robô: pedido {fid} entregue")
                    return
                passo = str(status.get("mensagem") or status.get("etapa") or "")
                eventos = [passo] if passo and passo != ultimo else []
                ultimo = passo or ultimo
                try:
                    self._ao_radar("bater", {"id": fid, "lease": lease, "passo": passo, "eventos": eventos})
                except httpx.HTTPError as erro:
                    self.log(f"  robô: o Radar não respondeu ({str(erro)[:80]}); sigo produzindo")
                self.dormir(BATER_A_CADA)
            raise RuntimeError(f"o vídeo passou de {PRAZO_DO_VIDEO // 3600} horas")
        except LeaseVelha:
            self.log(f"  robô: o pedido {fid} não é mais desta máquina")
        except (RuntimeError, OSError, ValueError, httpx.HTTPError) as erro:
            self.log(f"  robô: o pedido {fid} parou: {str(erro)[:200]}")
            try:
                self._ao_radar("falhar", {"id": fid, "lease": lease, "erro": str(erro)[:400]})
            except (LeaseVelha, httpx.HTTPError):
                pass  # o lease vence sozinho e o vídeo volta para a fila

    def uma_volta(self) -> bool:
        """Pede trabalho e faz. Devolve se havia trabalho."""
        try:
            trabalho = self._ao_radar("reivindicar", {"capacidades": capacidades(self.pasta)}).get("trabalho")
        except httpx.HTTPError as erro:
            self.log(f"  robô: o Radar não respondeu ({str(erro)[:80]}); tento de novo")
            return False
        if trabalho:
            self.log(f"  robô: peguei o pedido {trabalho['id']}: {str(trabalho.get('titulo'))[:60]}")
            self.produzir(trabalho)
        return bool(trabalho)

    def rodar(self) -> None:
        self.log(f"  robô ligado, pedindo trabalho em {self.radar}")
        atualizado_em = time.time()
        while True:
            if not self.uma_volta():
                if time.time() - atualizado_em > ATUALIZAR_A_CADA:
                    atualizado_em = time.time()
                    if atualizar(log=self.log):
                        raise SystemExit(SAIDA_ATUALIZADO)
                self.dormir(PEDIR_A_CADA)
