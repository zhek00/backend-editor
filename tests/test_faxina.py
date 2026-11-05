"""A faxina tira só o que o render refaz de graça, das produções antigas e paradas, e só com o disco apertado."""
import json
import os
import shutil
import time
from collections import namedtuple

import pytest

from fabrica import faxina

Disco = namedtuple("Disco", "total used free")
DIA = 86400


def _projeto(raiz, nome, dias_atras=30, final=True, status="concluido"):
    p = raiz / nome
    (p / "render" / "clipes").mkdir(parents=True)
    (p / "render" / "clipes" / "0001.mp4").write_bytes(b"x" * 1000)
    (p / "render" / "video.mp4").write_bytes(b"x" * 1000)
    (p / "render" / "voz.wav").write_bytes(b"x" * 1000)
    (p / "imagens").mkdir()
    (p / "imagens" / "0001.jpg").write_bytes(b"caro")
    (p / "midia").mkdir()
    (p / "midia" / "0002.mp4").write_bytes(b"caro")
    (p / "cenas.json").write_text("{}", encoding="utf-8")
    (p / "criacao.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    if final:
        (p / "final.mp4").write_bytes(b"o video")
    antes = time.time() - dias_atras * DIA
    for f in p.rglob("*"):
        if f.is_file():
            os.utime(f, (antes, antes))
    return p


@pytest.fixture
def disco_cheio(monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: Disco(100, 99, 0))


CFG = {"livre_gb": 1, "dias": 7}


def test_limpa_o_cache_e_guarda_o_que_custou_dinheiro(tmp_path, disco_cheio):
    p = _projeto(tmp_path, "velho")
    assert faxina.faxinar(lambda _m: None, tmp_path, CFG) == 3000
    assert not (p / "render" / "clipes").exists() and not (p / "render" / "video.mp4").exists()
    for fica in ("final.mp4", "imagens/0001.jpg", "midia/0002.mp4", "cenas.json"):
        assert (p / fica).exists(), fica


def test_disco_com_folga_nao_mexe_em_nada(tmp_path, monkeypatch):
    p = _projeto(tmp_path, "velho")
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: Disco(100, 0, 2 * 2**30))
    assert faxina.faxinar(lambda _m: None, tmp_path, CFG) == 0
    assert (p / "render" / "video.mp4").exists()


@pytest.mark.parametrize("como", [{"dias_atras": 2}, {"final": False}, {"status": "processando"}])
def test_nao_toca_em_producao_nova_sem_final_ou_rodando(tmp_path, disco_cheio, como):
    p = _projeto(tmp_path, "intocado", **como)
    assert faxina.faxinar(lambda _m: None, tmp_path, CFG) == 0
    assert (p / "render" / "video.mp4").exists()


def test_projeto_gravado_ha_pouco_conta_como_ocupado(tmp_path, disco_cheio):
    p = _projeto(tmp_path, "mexido")
    os.utime(p / "cenas.json")  # alguém corrigiu uma cena agora
    assert faxina.faxinar(lambda _m: None, tmp_path, CFG) == 0


def test_lixeira_fica_de_fora(tmp_path, disco_cheio):
    p = _projeto(tmp_path, "_lixeira")
    assert faxina.faxinar(lambda _m: None, tmp_path, CFG) == 0
    assert (p / "render" / "video.mp4").exists()


def test_comeca_pelo_mais_antigo_e_para_na_folga(tmp_path, monkeypatch):
    velho, medio = _projeto(tmp_path, "a-velho", 60), _projeto(tmp_path, "b-medio", 30)
    monkeypatch.setattr(shutil, "disk_usage", lambda _p: Disco(100, 0, 2**30 - 2000))
    assert faxina.faxinar(lambda _m: None, tmp_path, CFG) == 3000
    assert not (velho / "render" / "video.mp4").exists()
    assert (medio / "render" / "video.mp4").exists()


def test_simular_nao_apaga(tmp_path, disco_cheio):
    p = _projeto(tmp_path, "velho")
    ditas = []
    assert faxina.faxinar(ditas.append, tmp_path, CFG, simular=True) == 3000
    assert (p / "render" / "video.mp4").exists() and "liberaria" in ditas[0]


def test_config_desliga(tmp_path, disco_cheio):
    p = _projeto(tmp_path, "velho")
    assert faxina.faxinar(lambda _m: None, tmp_path, {**CFG, "ativo": False}) == 0
    assert (p / "render" / "video.mp4").exists()
