"""Aviso de voz lenta na GenAIPro (pedido do usuário em 2026-10-24): a medida de cada tarefa vira o aviso."""
from fabrica import genaipro


def _arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(genaipro, "_arquivo_velocidade", lambda: tmp_path / "genaipro_vozes.json")


def test_voz_sem_medida_nao_tem_aviso(tmp_path, monkeypatch):
    _arquivo(tmp_path, monkeypatch)
    assert genaipro.lentidao("qualquer") == {}


def test_voz_rapida_nao_tem_aviso(tmp_path, monkeypatch):
    _arquivo(tmp_path, monkeypatch)
    for s in (20, 35, 60):
        genaipro.anotar_espera("rapida", s)
    assert genaipro.lentidao("rapida") == {}


def test_voz_que_estoura_a_espera_fica_lenta(tmp_path, monkeypatch):
    _arquivo(tmp_path, monkeypatch)
    for s in (1200, 1200, 234):
        genaipro.anotar_espera("adam", s)
    lenta = genaipro.lentidao("adam")
    assert lenta["lenta"] is True and lenta["minutos"] == 20
    assert "GenAIPro" in lenta["aviso"]


def test_guarda_so_as_dez_ultimas(tmp_path, monkeypatch):
    _arquivo(tmp_path, monkeypatch)
    for s in [2000] * 10 + [10] * 10:
        genaipro.anotar_espera("voltou", s)
    assert genaipro.lentidao("voltou") == {}  # a voz que voltou a ser rápida perde o aviso


def test_arquivo_estragado_nao_derruba(tmp_path, monkeypatch):
    _arquivo(tmp_path, monkeypatch)
    (tmp_path / "genaipro_vozes.json").write_text("{quebrado", encoding="utf-8")
    assert genaipro.lentidao("x") == {}
    genaipro.anotar_espera("x", 30)
    assert genaipro.lentidao("x") == {}
