"""A esteira única da produção em massa e o trabalhador que a roda (PLANO-VPS.md, `fabrica trabalhador`).

Um vídeo pedido pelo MCP ou pela API /v1 entra na fila (fila.enfileirar) e um trabalhador:
1. cria o projeto nesta máquina, a partir do roteiro guardado no banco (perfil e voz da fábrica: mcp.perfil, mcp.voz);
2. roda a criação inteira do site (api.criar_ate_o_fim: mapa, narração, cenas, mídia, conferência, imagens, animações,
   trilha), com as novas tentativas e os tempos que ela já tem, espelhando o andamento no banco;
3. renderiza (um render por vez por máquina, `--renders`, porque o render usa todos os núcleos);
4. sobe o vídeo para o armazenamento (R2), conclui no banco e apaga os arquivos de trabalho.

O que passa sozinho (crédito acabou, chave recusada, serviço fora do ar) devolve o vídeo à fila para mais tarde, sem
contar falha e sem esperar uma pessoa; o resto conta como falha, com novas tentativas (fila.falhar). Pedido do usuário
em 2026-10-14: "o sistema ta pronto para trabalhar sem ajuste humano?".
"""
import os
import re
import socket
import tempfile
import threading
import time
import traceback
from pathlib import Path

from . import fila
from .projeto import PROJETOS, Projeto

MINUTOS_DE_ESPERA = 30         # crédito, chave, serviço fora: tenta de novo depois disso
INTERVALO_DO_SINAL = 60        # segundos entre um sinal de vida e outro
INTERVALO_DA_LIMPEZA = 3600    # segundos entre uma limpeza dos expirados e outra
ESPERA_SEM_TRABALHO = 5        # segundos entre uma olhada na fila e outra, com vaga livre e nada na fila

# o que passa sozinho e não é falha do vídeo: crédito, saldo, chave, limite, serviço fora do ar
_PASSA_SOZINHO = re.compile(r"crédito|credito|saldo|credits|recusou a chave|foi recusada|falta a chave|limite|"
                            r"rate limit|quota|cota|fora do ar|503|502|timed out|tempo esgotado", re.I)


def _perfil_e_voz():
    from .mcp_servidor import _escolhas_da_fabrica, _perfil

    perfil, voz = _escolhas_da_fabrica()
    return _perfil(perfil), voz


def criar_projeto(v) -> Projeto:
    """O projeto do vídeo nesta máquina (criado a partir do roteiro do banco, ou o que já existe, para continuar)."""
    nome = v["projeto"]
    if (PROJETOS / nome / "projeto.json").exists():
        return Projeto(nome)
    perfil, voz = _perfil_e_voz()
    opcoes = v.get("opcoes") or {}
    with tempfile.TemporaryDirectory() as pasta:
        arquivo = Path(pasta) / "roteiro.txt"
        arquivo.write_text(v["roteiro"], encoding="utf-8")
        # offline (testes do fluxo, sem custo): a voz do computador e imagens de teste
        p = Projeto.criar(nome, str(arquivo), str(perfil), offline=bool(opcoes.get("offline")))
    p.dados["video_id"] = v["id"]
    p.dados["dono"] = v.get("cliente_id")
    voz = (opcoes.get("voz") or voz or "").strip()
    if voz.startswith("fish"):
        from .mcp_servidor import VOZ_FISH_PADRAO

        p.dados["voz_override"] = {"provedor": "fish", "voice_id": voz.partition(":")[2] or VOZ_FISH_PADRAO,
                                   "idioma": opcoes.get("idioma") or "pt", "velocidade": 1.0}
    p.salvar_json("projeto.json", p.dados)
    return Projeto(nome)


class _Espelho:
    """Leva o andamento da criação (api._atualizar, api._log_tarefa) para o banco, sem escrever a cada linha."""

    def __init__(self, video_id, nome):
        self.video_id, self.nome, self.ultimo = video_id, nome, 0.0

    def __call__(self, task_id, campos, linha):
        from . import api

        with api.TAREFAS_LOCK:
            tarefa = api.TAREFAS.get(task_id) or {}
        if tarefa.get("projeto") != self.nome:
            return
        if campos:
            mudou = {k: campos[k] for k in ("etapa", "mensagem") if k in campos}
            if "progresso_pct" in campos:
                mudou["progresso"] = int(min(85, (campos["progresso_pct"] or 0) * 0.85))  # o render é o resto
            if mudou:
                fila.atualizar(self.video_id, **mudou)
        if linha and ("[tempo]" in linha or "[ERRO]" in linha) and time.time() - self.ultimo > 1:
            fila.evento(self.video_id, "criacao", linha.strip())
            self.ultimo = time.time()


def _custo(p) -> float:
    try:
        from . import custos_reais

        return round(float(custos_reais.resumo(p)["total_usd"]), 4)
    except Exception:  # noqa: BLE001
        return None


def produzir(v, trabalhador: str, trava_do_render: threading.Semaphore, log=print) -> str:
    """Produz um vídeo pego da fila até entregar. Devolve o estado final no banco."""
    from . import api, armazenamento, limpeza_vps, render

    vid = v["id"]
    try:
        p = criar_projeto(v)
    except Exception as erro:  # noqa: BLE001
        return fila.falhar(vid, f"não deu para criar o projeto: {erro}")
    from . import alertas, pago

    espelho = _Espelho(vid, p.nome)
    api.OUVINTES.append(espelho)
    try:
        fila.atualizar(vid, etapa="criação", mensagem="criando as cenas")
        estado = api.criar_ate_o_fim(p.nome)
    except pago.GratisEsgotado as erro:
        # o gasto em modelo pago passou do teto do vídeo (openrouter.teto_pago_por_minuto): erro na hora, sem tentar
        # de novo (cada tentativa gastaria de novo), e um aviso para quem cuida da fábrica
        alertas.avisar(f"consumo:{vid}", f"{p.nome}: parado por consumo alto ({str(erro).splitlines()[0][:200]})", log)
        return fila.falhar(vid, f"consumo alto: {erro}", definitivo=True)
    finally:
        api.OUVINTES.remove(espelho)
    if estado.get("status") != "concluido":
        erro = str(estado.get("erro") or estado.get("mensagem") or "a criação não terminou")
        if estado.get("precisa_voce") or _PASSA_SOZINHO.search(erro):
            # crédito, chave, serviço fora: o vídeo espera e tenta de novo sozinho; quem cuida da fábrica é avisado
            alertas.avisar(alertas.chave_do_motivo(erro), f"vídeos esperando: {erro[:300]}", log)
            fila.esperar(vid, erro[:300], MINUTOS_DE_ESPERA)
            return "na_fila"
        return fila.falhar(vid, erro)
    try:
        fila.atualizar(vid, etapa="render", progresso=86, mensagem="esperando a vez do render")
        with trava_do_render:
            fila.atualizar(vid, mensagem="renderizando o vídeo")
            final = render.renderizar(Projeto(p.nome), log=lambda m: None)
        fila.atualizar(vid, etapa="entrega", progresso=97, mensagem="enviando o vídeo")
        objeto = armazenamento.guardar(Path(final), f"videos/{vid}/{p.nome}.mp4")
        duracao = (Projeto(p.nome).ler_json("alinhamento.json") or {}).get("duracao")
        fila.concluir(vid, objeto=objeto, custo_usd=_custo(Projeto(p.nome)), duracao_s=duracao)
        liberados = limpeza_vps.depois_da_entrega(p.nome)
        log(f"  {p.nome}: entregue; {liberados / 1e9:.1f} GB de arquivos de trabalho apagados")
        return "pronto"
    except Exception as erro:  # noqa: BLE001
        texto = f"{erro}\n{traceback.format_exc()[-1200:]}"
        if _PASSA_SOZINHO.search(str(erro)):
            fila.esperar(vid, str(erro)[:300], MINUTOS_DE_ESPERA)
            return "na_fila"
        return fila.falhar(vid, texto)


class Trabalhador:
    """Pega vídeos da fila e produz até `vagas` ao mesmo tempo, com `renders` renders simultâneos."""

    def __init__(self, vagas=4, renders=1, nome=None, log=print):
        self.vagas, self.nome, self.log = max(1, vagas), nome or f"{socket.gethostname()}-{os.getpid()}", log
        self.trava_do_render = threading.Semaphore(max(1, renders))
        self.ocupados = {}  # video_id -> projeto
        self._trava = threading.Lock()
        self._parar = threading.Event()

    def _sinais(self):
        while not self._parar.wait(INTERVALO_DO_SINAL):
            with self._trava:
                ids = list(self.ocupados)
            for vid in ids:
                try:
                    fila.sinal_de_vida(vid, self.nome)
                except Exception:  # noqa: BLE001 - o banco piscou: tenta no próximo minuto
                    pass

    def _um(self, v):
        try:
            estado = produzir(v, self.nome, self.trava_do_render, self.log)
            self.log(f"  {v['projeto']}: {estado}")
        except BaseException as erro:  # noqa: BLE001 - nada derruba o trabalhador
            fila.falhar(v["id"], f"{erro}\n{traceback.format_exc()[-1200:]}")
        finally:
            with self._trava:
                self.ocupados.pop(v["id"], None)

    def rodar(self, uma_vez=False):
        from . import limpeza_vps

        self.log(f"Trabalhador {self.nome}: até {self.vagas} vídeo(s) ao mesmo tempo")
        threading.Thread(target=self._sinais, daemon=True, name="sinais-de-vida").start()
        ultima_limpeza = 0.0
        while not self._parar.is_set():
            if time.time() - ultima_limpeza > INTERVALO_DA_LIMPEZA:
                try:
                    fila.devolver_abandonados()
                    limpeza_vps.expirados(self.log)
                except Exception as erro:  # noqa: BLE001
                    self.log(f"  limpeza falhou: {str(erro)[:160]}")
                ultima_limpeza = time.time()
            with self._trava:
                livres = self.vagas - len(self.ocupados)
            v = fila.pegar(self.nome) if livres > 0 else None
            if v is None:
                if uma_vez:
                    with self._trava:
                        if not self.ocupados:
                            return
                self._parar.wait(ESPERA_SEM_TRABALHO)
                continue
            with self._trava:
                self.ocupados[v["id"]] = v["projeto"]
            self.log(f"  pegou {v['projeto']} ({v['id'][:8]})")
            threading.Thread(target=self._um, args=(v,), daemon=True, name=f"video-{v['projeto']}").start()

    def parar(self):
        self._parar.set()
