"""Gasto à toa no OpenRouter (2026-10-15): projeto excluído vai para a lixeira, e o vigia aponta o que a chave gastou
sem registro da fábrica. Caso real: no everything-you-need-to-answer o projeto excluído e recriado pagou a produção
inteira de novo, e numa semana o OpenRouter cobrou US$ 15,46 contra US$ 3,14 registrados. Sem rede e sem custo."""
import json
from datetime import datetime, timedelta

import pytest

from fabrica import consumo, lixeira


@pytest.fixture
def projetos(tmp_path, monkeypatch):
    monkeypatch.setattr(lixeira, "PROJETOS", tmp_path)
    monkeypatch.setattr(lixeira, "PASTA", tmp_path / "_lixeira")
    return tmp_path


def _projeto(raiz, nome):
    pasta = raiz / nome
    (pasta / "imagens").mkdir(parents=True)
    (pasta / "projeto.json").write_text(json.dumps({"nome": nome}), encoding="utf-8")
    (pasta / "imagens" / "0001.png").write_bytes(b"imagem paga")
    return pasta


def test_excluir_guarda_tudo_e_restaurar_devolve(projetos):
    _projeto(projetos, "video")
    lixeira.mandar("video")
    assert not (projetos / "video").exists()
    assert [i[0] for i in lixeira.listar()] == ["video"]
    lixeira.restaurar("video")
    assert (projetos / "video" / "imagens" / "0001.png").read_bytes() == b"imagem paga"
    assert lixeira.listar() == []


def test_restaurar_nao_passa_por_cima_de_projeto_com_o_mesmo_nome(projetos):
    _projeto(projetos, "video")
    lixeira.mandar("video")
    _projeto(projetos, "video")  # recriado do zero depois de excluir
    with pytest.raises(FileExistsError):
        lixeira.restaurar("video")
    assert lixeira.restaurar("video", como="video-antigo") == projetos / "video-antigo"


def test_a_lixeira_nao_aparece_como_projeto(projetos):
    _projeto(projetos, "video")
    lixeira.mandar("video")
    assert not (projetos / "_lixeira" / "projeto.json").exists()  # toda listagem de projetos exige projeto.json


def test_limpa_o_que_passou_dos_dias(projetos):
    velho = projetos / "_lixeira" / f"velho__{(datetime.now() - timedelta(days=8)):%Y%m%d-%H%M%S}"
    velho.mkdir(parents=True)
    _projeto(projetos, "novo")
    lixeira.mandar("novo")
    assert [i[0] for i in lixeira.listar()] == ["novo"]


@pytest.fixture
def vigia(tmp_path, monkeypatch):
    monkeypatch.setattr(consumo, "PASTA", tmp_path)
    monkeypatch.setattr(consumo, "VAZAMENTO", tmp_path / "vazamento.csv")
    monkeypatch.setattr(consumo, "ESTADO_VIGIA", tmp_path / "vigia.json")
    estado = {"cobrado": 10.0, "registrado": 2.0}
    monkeypatch.setattr(consumo, "_uso_da_chave", lambda: estado["cobrado"])
    monkeypatch.setattr(consumo, "_registrado_total", lambda: estado["registrado"])
    return estado


def test_vigia_aponta_o_que_a_chave_gastou_sem_registro(vigia):
    avisos = []
    assert consumo.conferir_vazamento(log=avisos.append) is None  # primeira vez: só guarda o ponto de partida
    vigia["cobrado"] += 1.30   # a chave gastou US$ 1,30
    vigia["registrado"] += 0.40  # a fábrica registrou US$ 0,40
    assert consumo.conferir_vazamento(log=avisos.append) == pytest.approx(0.90)
    assert avisos and "VAZAMENTO" in avisos[0]
    janela = consumo.ler_vazamento()[0]
    assert float(janela["sem_registro_usd"]) == pytest.approx(0.90)


def test_vigia_quieto_quando_tudo_e_da_fabrica(vigia):
    avisos = []
    consumo.conferir_vazamento(log=avisos.append)
    vigia["cobrado"] += 0.50
    vigia["registrado"] += 0.49  # o Jev cobrado alguns minutos depois cabe na tolerância
    assert consumo.conferir_vazamento(log=avisos.append) == pytest.approx(0.01)
    assert avisos == []


def test_vigia_sem_resposta_da_openrouter_pula_a_janela(vigia, monkeypatch):
    consumo.conferir_vazamento(log=print)
    monkeypatch.setattr(consumo, "_uso_da_chave", lambda: None)
    assert consumo.conferir_vazamento(log=print) is None
    assert consumo.ler_vazamento() == []
