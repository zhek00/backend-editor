"""Robô PALHANO: liga este computador ao painel e produz os vídeos da fila com a fábrica (fabrica novo / tudo).

Na primeira vez pede o código de conexão (painel > Máquinas > Conectar máquina). Depois só roda:
    uv run fabrica robo                   (ou palhano/LIGAR-ROBO.bat)

As chaves do cliente chegam do painel só para esta máquina e ficam só na memória do processo da produção."""
import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

import httpx
import yaml

VERSAO = "0.3.0"
AQUI = Path(__file__).resolve().parent
FABRICA = AQUI.parent.parent  # o robô mora em fabrica-videos/palhano/robo
DADOS = AQUI / "dados"
CONFIG = DADOS / "maquina.json"
INTERVALO = 5

# título que a fábrica escreve ao começar uma etapa -> (o que o painel mostra, porcentagem nesse ponto)
ETAPAS = {
    "Mapa do roteiro": ("Lendo o roteiro", 4),
    "JSON de cenas": ("Planejando as cenas", 8),
    "Narração": ("Gravando a narração", 12),
    "Cenas": ("Dividindo as cenas", 25),
    "Material real": ("Buscando fotos e vídeos", 30),
    "Conferência": ("Conferindo as cenas", 55),
    "Imagens de IA": ("Gerando imagens de IA", 65),
    "Motion onde ajuda o roteiro": ("Cenas animadas", 72),
    "Efeitos sonoros": ("Efeitos sonoros", 75),
    "Animações": ("Animações", 78),
    "Trilha": ("Compondo a trilha", 82),
    "Render": ("Montando o vídeo", 85),
    "Revisão do vídeo pronto": ("Revisando o vídeo", 96),
}


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "video"


def pasta_downloads() -> Path:
    return Path.home() / "Downloads"


class Painel:
    def __init__(self, url: str, token: str = ""):
        self.url = url.rstrip("/")
        self.token = token
        self.http = httpx.Client(timeout=30)

    def pedir(self, metodo: str, caminho: str, **kw):
        cab = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        r = self.http.request(metodo, self.url + caminho, headers=cab, **kw)
        if r.status_code >= 400:
            try:
                detalhe = r.json().get("detail")
            except ValueError:
                detalhe = r.text[:200]
            raise RuntimeError(f"{r.status_code}: {detalhe}")
        return r.json()


class Producao(threading.Thread):
    """Uma produção: cria o projeto na fábrica, roda o tudo e entrega o MP4."""

    def __init__(self, painel: Painel, trabalho: dict):
        super().__init__(daemon=True)
        self.painel, self.t = painel, trabalho
        self.processo = None
        self.cancelada = False
        self.linhas: list = []
        self.etapa, self.progresso = "Começando", 1
        self.ultimo_envio = 0.0
        self.projeto = f"palhano-{trabalho['id']}-{slug(trabalho['nome'])}"

    # ------------------------------------------------------------ comunicação
    def _enviar(self, forcar=False):
        if not forcar and time.time() - self.ultimo_envio < 4:
            return
        linhas, self.linhas = self.linhas[-15:], []
        try:
            r = self.painel.pedir("POST", f"/api/robo/producoes/{self.t['id']}/andamento",
                                  json={"etapa": self.etapa, "progresso": self.progresso, "linhas": linhas})
            self.ultimo_envio = time.time()
            if r.get("cancelar"):
                self.cancelar()
        except (httpx.HTTPError, RuntimeError) as e:
            self.linhas = linhas + self.linhas
            log(f"  painel fora do ar ({e}); continuo e mando depois")

    def _fim(self, estado: str, **dados):
        corpo = {"estado": estado, "linhas": self.linhas[-15:], **dados}
        for espera in (0, 5, 15, 30, 60, 120):
            time.sleep(espera)
            try:
                self.painel.pedir("POST", f"/api/robo/producoes/{self.t['id']}/fim", json=corpo)
                return
            except (httpx.HTTPError, RuntimeError) as e:
                log(f"  não consegui avisar o fim ao painel ({e}); tento de novo")

    # ------------------------------------------------------------ fábrica
    def _ambiente(self) -> dict:
        env = dict(os.environ)
        env.update(self.t.get("ambiente") or {})
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _rodar(self, *args) -> int:
        comando = [sys.executable, "-m", "fabrica", *args]
        log("  fabrica " + " ".join(args))
        extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        self.processo = subprocess.Popen(comando, cwd=FABRICA, env=self._ambiente(), stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                         **extra)
        for linha in self.processo.stdout:
            linha = linha.rstrip()
            if not linha:
                continue
            print("    " + linha, flush=True)
            self.linhas.append(linha)
            titulo = linha.strip()
            if titulo in ETAPAS and ETAPAS[titulo][1] >= self.progresso:
                self.etapa, self.progresso = ETAPAS[titulo]
                self._enviar(forcar=True)
            m = re.search(r"(\d+)\s*/\s*(\d+)\s+clipes|clipes (\d+)/(\d+)", linha)
            if m and self.etapa == "Montando o vídeo":
                feitos, total = (int(x) for x in (m.group(1, 2) if m.group(1) else m.group(3, 4)))
                if total:
                    self.progresso = max(self.progresso, 85 + int(10 * feitos / total))
            self._enviar()
        return self.processo.wait()

    def _preparar_perfil(self, pasta: Path) -> Path:
        perfil = {"base": str(FABRICA / "perfis" / "documentario.yaml"), **(self.t["fabrica"].get("perfil") or {})}
        arquivo = pasta / "perfil.yaml"
        arquivo.write_text(yaml.safe_dump(perfil, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return arquivo

    def _custo(self) -> dict:
        script = ("import json,sys; from fabrica.projeto import Projeto; from fabrica import custos_reais; "
                  "r=custos_reais.resumo(Projeto(sys.argv[1])); r.pop('itens',None); r.pop('tarefas_dos_modelos',None); "
                  "print('CUSTO_JSON'+json.dumps(r))")
        try:
            saida = subprocess.run([sys.executable, "-c", script, self.projeto], cwd=FABRICA, env=self._ambiente(),
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180).stdout
            for linha in saida.splitlines():
                if linha.startswith("CUSTO_JSON"):
                    return json.loads(linha[len("CUSTO_JSON"):])
        except (subprocess.SubprocessError, ValueError, OSError) as e:
            log(f"  não consegui ler o custo ({e})")
        return {}

    def _entregar(self) -> str:
        """A fábrica já montou a pasta de entrega no fim do tudo (fabrica/entrega_pc.py, na pasta que o painel mandou):
        o robô só lê onde ela ficou."""
        pasta_projeto = FABRICA / "projetos" / self.projeto
        registro = pasta_projeto / "entrega_pc.json"
        if registro.exists():
            return json.loads(registro.read_text(encoding="utf-8"))["video"]
        return str(pasta_projeto / "final.mp4")

    def run(self):
        t, ajustes = self.t, self.t.get("ajustes") or {}
        log(f"Produzindo #{t['id']}: {t['nome']}")
        inicio = time.time()
        try:
            pasta = DADOS / "producoes" / str(t["id"])
            pasta.mkdir(parents=True, exist_ok=True)
            pasta_projeto = FABRICA / "projetos" / self.projeto
            if not (pasta_projeto / "projeto.json").exists():
                roteiro = pasta / "roteiro.txt"
                roteiro.write_text(t["roteiro"], encoding="utf-8")
                args = ["novo", self.projeto, "--roteiro", str(roteiro), "--perfil", str(self._preparar_perfil(pasta)),
                        "--sim"]
                if ajustes.get("teste"):
                    args.append("--offline")
                if self._rodar(*args) != 0:
                    raise RuntimeError("a fábrica não conseguiu criar o projeto")
                dados = json.loads((pasta_projeto / "projeto.json").read_text(encoding="utf-8"))
                dados["config_override"] = t["fabrica"].get("config_override") or {}
                dados["robo_palhano"] = {"producao": t["id"], "nome": t["nome"]}
                dados["titulo_entrega"] = t["nome"]  # a pasta e o MP4 entregues levam o nome que o cliente deu
                (pasta_projeto / "projeto.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                                                            encoding="utf-8")
            else:
                log("  o projeto já existe: continuo de onde parou, sem pagar de novo o que já foi feito")
            if self.cancelada:
                raise InterruptedError
            (pasta_projeto / "final.mp4").unlink(missing_ok=True)
            codigo = self._rodar("tudo", self.projeto, "--sim", *(["--vertical"] if ajustes.get("vertical") else []))
            if self.cancelada:
                raise InterruptedError
            if codigo != 0 or not (pasta_projeto / "final.mp4").exists():
                raise RuntimeError(f"a produção parou (código {codigo}). " + " | ".join(self.linhas[-3:]))
            self.etapa, self.progresso = "Entregando", 99
            self._enviar(forcar=True)
            arquivo = self._entregar()
            custo = self._custo()
            log(f"  pronto: {arquivo}")
            self._fim("entregue", arquivo=arquivo, custo=custo, duracao_s=custo.get("duracao_segundos", 0),
                      trabalho_s=int(time.time() - inicio))
        except InterruptedError:
            log("  produção cancelada pelo painel")
            self._fim("cancelado")
        except Exception as e:  # noqa: BLE001 - qualquer falha vai para o painel, e o robô segue vivo
            log(f"  falhou: {e}")
            self._fim("falhou", erro=str(e)[:900])

    def cancelar(self):
        self.cancelada = True
        if self.processo and self.processo.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.processo.pid)], capture_output=True)
            else:
                os.killpg(self.processo.pid, signal.SIGTERM)


def abrir(caminho: str, pasta=False) -> None:
    alvo = Path(caminho)
    if not alvo.exists():
        log(f"  o arquivo não está mais aqui: {alvo}")
        return
    if os.name == "nt":
        if pasta:
            subprocess.run(["explorer", "/select,", str(alvo)])
        else:
            os.startfile(str(alvo))  # noqa: S606 - abre o vídeo no tocador do computador
    elif sys.platform == "darwin":
        subprocess.run(["open", "-R", str(alvo)] if pasta else ["open", str(alvo)])
    else:
        subprocess.run(["xdg-open", str(alvo.parent if pasta else alvo)])


def conferir_ferramentas() -> None:
    faltam = [x for x in ("ffmpeg", "ffprobe") if not shutil.which(x)]
    if faltam:
        raise SystemExit("Falta instalar o FFmpeg neste computador. Sem ele a fábrica não monta o vídeo.")


def conectar(url: str, codigo: str) -> dict:
    painel = Painel(url)
    r = painel.pedir("POST", "/api/robo/parear", json={
        "codigo": codigo, "nome": platform.node() or "Computador",
        "sistema": f"{platform.system()} {platform.release()}", "versao": VERSAO,
        "pasta_padrao": str(pasta_downloads())})
    dados = {"url": url, "token": r["token"]}
    DADOS.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(dados), encoding="utf-8")
    log("Máquina conectada ao painel.")
    return dados


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fabrica robo", description="Robô PALHANO")
    ap.add_argument("--painel", default=os.environ.get("PALHANO_PAINEL", "http://127.0.0.1:8300"))
    ap.add_argument("--codigo", help="código de conexão do painel (Máquinas > Conectar máquina)")
    ap.add_argument("--uma-vez", action="store_true", help="produz no máximo um vídeo e sai (para teste)")
    ap.add_argument("--simultaneos", type=int, default=int(os.environ.get("PALHANO_SIMULTANEOS") or 3),
                    help="vídeos produzidos ao mesmo tempo neste computador (padrão 3)")
    a = ap.parse_args(argv)
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    conferir_ferramentas()

    dados = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else None
    if a.codigo or not dados:
        codigo = a.codigo or input("Código de conexão (painel > Máquinas > Conectar máquina): ").strip()
        dados = conectar(a.painel, codigo)
    painel = Painel(dados["url"], dados["token"])
    log(f"Robô PALHANO {VERSAO} ligado ao painel {dados['url']}, fábrica em {FABRICA}")
    simultaneos = 1 if a.uma_vez else max(1, a.simultaneos)
    log(f"Esperando vídeos na fila, até {simultaneos} ao mesmo tempo. Deixe esta janela aberta.")

    # vários vídeos ao mesmo tempo (pedido do usuário em 2026-10-12): boa parte da criação é espera pelos modelos e
    # pelos downloads, então enquanto um espera o outro anda. Cada vídeo é um projeto da fábrica separado
    rodando: list[Producao] = []
    feitas = 0
    while True:
        rodando = [x for x in rodando if x.is_alive()]
        livres = 0 if (a.uma_vez and feitas) else max(0, simultaneos - len(rodando))
        try:
            r = painel.pedir("POST", "/api/robo/ping", json={"ocupada": bool(rodando), "produzindo": len(rodando),
                                                              "livres": livres, "versao": VERSAO,
                                                              "pasta_padrao": str(pasta_downloads())})
        except RuntimeError as e:
            if str(e).startswith("401"):
                CONFIG.unlink(missing_ok=True)
                raise SystemExit("O painel desconectou esta máquina. Rode de novo com um código novo.")
            log(f"Painel respondeu com erro ({e}); tento de novo")
            time.sleep(INTERVALO * 3)
            continue
        except httpx.HTTPError as e:
            log(f"Sem conexão com o painel ({type(e).__name__}); tento de novo")
            time.sleep(INTERVALO * 3)
            continue
        for c in r.get("comandos", []):
            if c["tipo"] == "cancelar":
                for producao in rodando:
                    if producao.t["id"] == c["dados"].get("producao_id"):
                        producao.cancelar()
            elif c["tipo"] in ("abrir", "assistir"):
                abrir(c["dados"].get("arquivo", ""), pasta=c["tipo"] == "abrir")
        if r.get("trabalho") and livres:
            nova = Producao(painel, r["trabalho"])
            nova.start()
            rodando.append(nova)
            feitas += 1
        if a.uma_vez and feitas and not any(x.is_alive() for x in rodando):
            log("Teste concluído.")
            return
        time.sleep(INTERVALO)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Robô desligado.")
