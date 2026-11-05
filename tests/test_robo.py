"""O robô da fábrica: pega do Radar, produz na fábrica local, bate, prova. O Radar e a fábrica são dublês."""
import json
import os
import subprocess
import sys
import time

import httpx
import pytest

from fabrica import robo

TRABALHO = {"id": 7, "lease": "L", "projeto": "robo-7", "perfil": "canal-x", "titulo": "Vídeo", "titulo_entrega": "Vídeo (BR)",
            "roteiro": "Texto.", "config_override": {"garimpo": {"ligado": True, "alvo": 0.25}},
            "perfil_override": {"visual": "cinema"}}


class _Resposta:
    def __init__(self, dados=None, codigo=200):
        self.dados, self.status_code = dados if dados is not None else {}, codigo

    def json(self):
        return self.dados

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erro", request=None, response=None)


class _Http:
    """Radar e fábrica de mentira. `status` sai um por consulta; o último se repete."""

    def __init__(self, status=(), pasta=None, radar=None):
        self.status, self.pasta = list(status), pasta
        self.radar = radar or {}
        self.chamadas = []

    def post(self, url, json=None, headers=None):
        rota = url.rsplit("/", 1)[-1]
        self.chamadas.append((rota, json))
        resposta = self.radar.get(rota)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta.pop(0) if isinstance(resposta, list) and len(resposta) > 1 else (
            resposta[0] if isinstance(resposta, list) else _Resposta())

    def request(self, metodo, url, json=None, headers=None):
        self.chamadas.append((metodo, url.split("/api/")[-1]))
        if url.endswith("/status"):
            atual = self.status.pop(0) if len(self.status) > 1 else self.status[0]
            if atual == "escreve":
                (self.pasta / "robo-7" / "final.mp4").write_bytes(b"video")
                return _Resposta({"status": "concluido", "tarefa_id": "render_robo-7_1"})
            if atual == "escreve_com_o_disco_atrasado":
                final = self.pasta / "robo-7" / "final.mp4"
                final.write_bytes(b"video")
                atrasado = time.time() - 1
                os.utime(final, (atrasado, atrasado))
                return _Resposta({"status": "concluido", "tarefa_id": "render_robo-7_1"})
            return _Resposta(atual)
        return _Resposta({"status": "processando"})

    def rotas(self):
        return [c[0] for c in self.chamadas]


def _robo(tmp_path, http, **extras):
    def criar(nome, roteiro, perfil):
        assert roteiro.read_text(encoding="utf-8") == "Texto." and perfil == "canal-x"
        (tmp_path / nome).mkdir()
        (tmp_path / nome / "projeto.json").write_text('{"nome": "robo-7"}', encoding="utf-8")

    falas = []
    r = robo.Robo("http://radar/", "rdm_x", http=http, pasta=tmp_path, log=falas.append, criar=criar,
                  provar=lambda a: {"bytes": a.stat().st_size, "duracao": 60.0, "sha256": "abc"},
                  dormir=lambda _s: None, **extras)
    r.falas = falas
    return r


CRIANDO = {"status": "processando", "mensagem": "Gerando imagens", "tarefa_id": "criar_x"}
FIM_DA_CRIACAO = {"status": "concluido", "tarefa_id": "criar_x"}


def test_video_inteiro_ate_a_prova(tmp_path):
    http = _Http([CRIANDO, FIM_DA_CRIACAO, "escreve"], tmp_path)
    _robo(tmp_path, http).produzir(TRABALHO)
    assert "bater" in http.rotas()
    (conclusao,) = [c for c in http.chamadas if c[0] == "concluir"]
    assert conclusao[1] == {"id": 7, "lease": "L", "prova": {"bytes": 5, "duracao": 60.0, "sha256": "abc"}}
    dados = json.loads((tmp_path / "robo-7" / "projeto.json").read_text(encoding="utf-8"))
    assert dados["titulo_entrega"] == "Vídeo (BR)" and dados["config_override"]["garimpo"]["alvo"] == 0.25
    assert dados["perfil_override"] == {"visual": "cinema"}


def test_criacao_concluida_nao_e_o_fim(tmp_path):
    """A criação termina com status concluido, antes do render: entregar ali seria entregar sem vídeo."""
    http = _Http([FIM_DA_CRIACAO, "escreve"], tmp_path)
    _robo(tmp_path, http).produzir(TRABALHO)
    rotas = http.rotas()
    assert rotas.index("bater") < rotas.index("concluir")


def test_final_de_antes_nao_conta(tmp_path):
    """Pedido retomado: o final.mp4 velho no disco não é a entrega deste lease."""
    (tmp_path / "robo-7").mkdir()
    (tmp_path / "robo-7" / "projeto.json").write_text("{}", encoding="utf-8")
    velho = tmp_path / "robo-7" / "final.mp4"
    velho.write_bytes(b"velho")
    antes = time.time() - 3600
    os.utime(velho, (antes, antes))
    http = _Http([{"status": "concluido", "tarefa_id": "render_y"}, "escreve"], tmp_path)
    _robo(tmp_path, http).produzir(TRABALHO)
    assert http.rotas().count("bater") == 1 and "concluir" in http.rotas()


def test_video_novo_conta_com_o_relogio_do_disco_atras(tmp_path):
    """O Windows carimba o arquivo um instante antes do time.time() de quem pediu: comparar os dois relógios fazia o
    robô não ver o vídeo pronto (o teste de cima falhou 4 vezes em 45). O que vale é a data ter mudado."""
    (tmp_path / "robo-7").mkdir()
    (tmp_path / "robo-7" / "projeto.json").write_text("{}", encoding="utf-8")
    velho = tmp_path / "robo-7" / "final.mp4"
    velho.write_bytes(b"velho")
    antes = time.time() - 3600
    os.utime(velho, (antes, antes))
    http = _Http(["escreve_com_o_disco_atrasado", {"status": "erro", "erro": "o robô não viu o vídeo"}], tmp_path)
    _robo(tmp_path, http).produzir(TRABALHO)
    assert "concluir" in http.rotas() and "falhar" not in http.rotas()


def test_lease_velha_larga_o_video_sem_falhar(tmp_path):
    http = _Http([CRIANDO], tmp_path, {"bater": [_Resposta({"detail": "lease_velha"}, 409)]})
    r = _robo(tmp_path, http)
    r.produzir(TRABALHO)
    assert "falhar" not in http.rotas() and "concluir" not in http.rotas()
    assert any("não é mais desta máquina" in f for f in r.falas)


def test_erro_da_fabrica_avisa_o_radar(tmp_path):
    http = _Http([{"status": "erro", "erro": "sem crédito"}], tmp_path)
    _robo(tmp_path, http).produzir(TRABALHO)
    (falha,) = [c for c in http.chamadas if c[0] == "falhar"]
    assert falha[1]["erro"] == "sem crédito"


def test_radar_fora_do_ar_nao_para_o_video(tmp_path):
    erro = httpx.ConnectError("caiu")
    http = _Http([CRIANDO, "escreve"], tmp_path, {"bater": erro})
    _robo(tmp_path, http).produzir(TRABALHO)
    assert "concluir" in http.rotas() and "falhar" not in http.rotas()


def test_projeto_existente_nao_e_recriado(tmp_path):
    (tmp_path / "robo-7").mkdir()
    (tmp_path / "robo-7" / "projeto.json").write_text('{"ja": true}', encoding="utf-8")
    r = _robo(tmp_path, _Http([CRIANDO], tmp_path))
    r.criar = lambda *a: pytest.fail("não pode criar de novo")
    assert r.preparar(TRABALHO) == "robo-7"
    assert json.loads((tmp_path / "robo-7" / "projeto.json").read_text(encoding="utf-8")) == {"ja": True}


def test_sem_trabalho_nao_faz_nada(tmp_path):
    http = _Http(radar={"reivindicar": [_Resposta({"trabalho": None})]})
    assert _robo(tmp_path, http).uma_volta() is False


def test_chave_recusada_para_o_robo(tmp_path):
    http = _Http(radar={"reivindicar": [_Resposta({}, 401)]})
    with pytest.raises(SystemExit, match="recusou a chave"):
        _robo(tmp_path, http).uma_volta()


def test_radar_fora_do_ar_na_hora_de_pedir_nao_derruba(tmp_path):
    http = _Http(radar={"reivindicar": httpx.ConnectError("caiu")})
    assert _robo(tmp_path, http).uma_volta() is False


def test_capacidades_dizem_o_que_a_maquina_tem(tmp_path):
    c = robo.capacidades(tmp_path)
    assert c["nucleos"] > 0 and c["disco_livre_gb"] > 0


def test_prova_tem_tamanho_e_resumo_do_arquivo(tmp_path, monkeypatch):
    arquivo = tmp_path / "final.mp4"
    arquivo.write_bytes(b"video")
    monkeypatch.setattr(robo.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "61.5\n", ""))
    p = robo.prova_do_video(arquivo)
    assert p["bytes"] == 5 and p["duracao"] == 61.5 and len(p["sha256"]) == 64


# ---------------------------------------------------------------------------------------------------
# Atualização com volta, em um repositório de verdade


def _git(pasta, *args):
    return subprocess.run(["git", "-C", str(pasta), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def repositorios(tmp_path):
    origem, local = tmp_path / "origem", tmp_path / "local"
    origem.mkdir()
    _git(origem, "init", "-q", "-b", "main")
    (origem / "a.txt").write_text("1", encoding="utf-8")
    _git(origem, "add", ".")
    _git(origem, "commit", "-q", "-m", "um")
    subprocess.run(["git", "clone", "-q", str(origem), str(local)], check=True)
    return origem, local


def _nova_versao(origem):
    (origem / "a.txt").write_text("2", encoding="utf-8")
    _git(origem, "commit", "-q", "-am", "dois")


def test_versao_que_abre_fica(repositorios):
    origem, local = repositorios
    _nova_versao(origem)
    assert robo.atualizar(local, provar=lambda: True, log=lambda _m: None) is True
    assert (local / "a.txt").read_text(encoding="utf-8") == "2"


def test_versao_que_nao_abre_volta(repositorios):
    origem, local = repositorios
    _nova_versao(origem)
    falas = []
    assert robo.atualizar(local, provar=lambda: False, log=falas.append) is False
    assert (local / "a.txt").read_text(encoding="utf-8") == "1"
    assert "voltei" in falas[0]


def test_mudanca_local_nao_e_atropelada(repositorios):
    origem, local = repositorios
    _nova_versao(origem)
    (local / "a.txt").write_text("trabalho meu", encoding="utf-8")
    assert robo.atualizar(local, provar=lambda: True, log=lambda _m: None) is False
    assert (local / "a.txt").read_text(encoding="utf-8") == "trabalho meu"


def test_sem_versao_nova_nao_relanca(repositorios):
    _, local = repositorios
    assert robo.atualizar(local, provar=lambda: True, log=lambda _m: None) is False


def test_a_linha_de_comando_abre():
    """Um subcomando com nome repetido derruba o argparse de todos: o `fabrica novo` do Radar parava junto."""
    r = subprocess.run([sys.executable, "-c", "from fabrica.cli import main; main()", "maquina", "--help"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0 and "--radar" in r.stdout, r.stderr[-300:]


def test_o_subcomando_e_o_desta_maquina_e_nao_o_do_palhano():
    """Dois cmd_robo no mesmo arquivo: o de baixo ganhava, e `fabrica maquina` abriria o robô do PALHANO."""
    import os

    ambiente = {k: v for k, v in os.environ.items() if not k.startswith("ROBO_")}
    r = subprocess.run([sys.executable, "-c", "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"
                        "from fabrica.cli import main; main()", "maquina"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=ambiente)
    assert "ROBO_RADAR" in (r.stderr + r.stdout)
