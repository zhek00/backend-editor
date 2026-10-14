import threading
from datetime import timedelta

import pytest

from fabrica import banco as banco_mod
from fabrica import fila


@pytest.fixture
def banco_temporario(tmp_path, monkeypatch):
    b = banco_mod.Banco(f"sqlite:///{tmp_path / 'teste.db'}")
    monkeypatch.setattr(banco_mod, "_BANCO", b)
    yield b
    b.fechar()


def test_cliente_e_chave(banco_temporario):
    cid, chave = fila.criar_cliente("canal x", limite_por_dia=50)
    assert fila.cliente_da_chave(chave)["id"] == cid
    assert fila.cliente_da_chave("fab_errada") is None
    assert chave not in str(banco_temporario.todos("SELECT * FROM clientes"))  # só o hash fica guardado


def test_ciclo_de_um_video(banco_temporario):
    v = fila.enfileirar("Um roteiro.", titulo="Teste")
    assert v["estado"] == "na_fila" and fila.posicao_na_fila(v["id"]) == 1
    pego = fila.pegar("maquina-1")
    assert pego["id"] == v["id"] and pego["estado"] == "produzindo" and pego["trabalhador"] == "maquina-1"
    assert fila.pegar("maquina-2") is None  # nada mais na fila
    assert fila.sinal_de_vida(v["id"], "maquina-1") and not fila.sinal_de_vida(v["id"], "maquina-2")
    fila.atualizar(v["id"], etapa="render", progresso=90, nao_existe=1)
    fila.concluir(v["id"], objeto="videos/x.mp4", url_video="https://r2/x", custo_usd=2.0)
    pronto = fila.video(v["id"])
    assert pronto["estado"] == "pronto" and pronto["url_video"] == "https://r2/x" and pronto["expira_em"] > banco_mod.agora()
    assert [e["texto"] for e in fila.eventos(v["id"])][0] == "pedido recebido"


def test_dois_trabalhadores_nunca_pegam_o_mesmo(banco_temporario):
    for i in range(20):
        fila.enfileirar(f"roteiro {i}")
    pegos, trava = [], threading.Lock()

    def trabalhar(nome):
        while True:
            v = fila.pegar(nome)
            if v is None:
                return
            with trava:
                pegos.append(v["id"])

    linhas = [threading.Thread(target=trabalhar, args=(f"t{i}",)) for i in range(8)]
    [t.start() for t in linhas]
    [t.join() for t in linhas]
    assert len(pegos) == 20 and len(set(pegos)) == 20


def test_prioridade_e_ordem(banco_temporario):
    a = fila.enfileirar("a")
    b = fila.enfileirar("b", prioridade=5)
    assert fila.pegar("m")["id"] == b["id"] and fila.pegar("m")["id"] == a["id"]


def test_espera_nao_conta_como_falha_e_volta_depois(banco_temporario, monkeypatch):
    v = fila.enfileirar("x")
    fila.pegar("m")
    fila.esperar(v["id"], "OpenRouter sem crédito", minutos=30)
    depois = fila.video(v["id"])
    assert depois["estado"] == "na_fila" and depois["tentativas"] == 0 and "sem crédito" in depois["mensagem"]
    assert fila.pegar("m") is None  # ainda não chegou a hora
    monkeypatch.setattr(fila, "agora", lambda mais=None: banco_mod.agora(timedelta(minutes=31) + (mais or timedelta(0))))
    assert fila.pegar("m")["id"] == v["id"]


def test_falha_tenta_de_novo_e_depois_fica_com_erro(banco_temporario, monkeypatch):
    v = fila.enfileirar("x")
    estados = []
    for _ in range(fila.TENTATIVAS_MAXIMAS):
        monkeypatch.setattr(fila, "agora", lambda mais=None: banco_mod.agora(timedelta(days=1) + (mais or timedelta(0))))
        fila.pegar("m")
        estados.append(fila.falhar(v["id"], "o render quebrou"))
    assert estados[:-1] == ["na_fila"] * (fila.TENTATIVAS_MAXIMAS - 1) and estados[-1] == "erro"
    assert fila.video(v["id"])["expira_em"]  # erro também expira em 3 dias


def test_trabalhador_que_parou_devolve_o_video(banco_temporario):
    v = fila.enfileirar("x")
    fila.pegar("maquina-caiu")
    banco_temporario.executar("UPDATE videos SET sinal_de_vida = %s WHERE id = %s",
                              (banco_mod.agora(-timedelta(minutes=30)), v["id"]))
    assert fila.devolver_abandonados() == [v["id"]]
    assert fila.pegar("maquina-2")["id"] == v["id"]


def test_expirados_em_3_dias(banco_temporario, monkeypatch):
    v = fila.enfileirar("x")
    fila.pegar("m")
    fila.concluir(v["id"], objeto="videos/x.mp4", url_video="u")
    assert fila.expirados() == []
    monkeypatch.setattr(fila, "agora", lambda mais=None: banco_mod.agora(timedelta(days=3, minutes=1) + (mais or timedelta(0))))
    assert [x["id"] for x in fila.expirados()] == [v["id"]]
    fila.marcar_expirado(v["id"])
    fim = fila.video(v["id"])
    assert fim["estado"] == "expirado" and fim["url_video"] is None and fim["roteiro"] == ""


def test_cancelar(banco_temporario):
    v = fila.enfileirar("x")
    assert fila.cancelar(v["id"]) and fila.pegar("m") is None
    assert not fila.cancelar(v["id"])  # já terminado
