"""O × do editor manda o projeto para projetos/_lixeira, e ele volta inteiro (roast chicken, 2026-10-13)."""
import json
from datetime import datetime, timedelta

from fabrica import lixeira


def _projetos(tmp_path, monkeypatch):
    monkeypatch.setattr(lixeira, "PROJETOS", tmp_path)
    monkeypatch.setattr(lixeira, "PASTA", tmp_path / "_lixeira")


def _criar(tmp_path, nome):
    pasta = tmp_path / nome
    (pasta / "render").mkdir(parents=True)
    (pasta / "projeto.json").write_text(json.dumps({"nome": nome}), encoding="utf-8")
    (pasta / "render" / "final.mp4").write_bytes(b"video")
    return pasta


def test_apagar_e_restaurar(tmp_path, monkeypatch):
    _projetos(tmp_path, monkeypatch)
    pasta = _criar(tmp_path, "roast-chicken")
    lixeira.mover(pasta)
    assert not pasta.exists()
    assert [i["nome"] for i in lixeira.listar()] == ["roast-chicken"]
    # uma tarefa atrasada recriou a pasta só com o registro de consumo: não impede restaurar
    (tmp_path / "roast-chicken").mkdir()
    (tmp_path / "roast-chicken" / "uso_openrouter.json").write_text("[]", encoding="utf-8")
    lixeira.restaurar("roast-chicken")
    assert (pasta / "render" / "final.mp4").read_bytes() == b"video"
    assert lixeira.listar() == []


def test_nao_restaura_por_cima_de_projeto(tmp_path, monkeypatch):
    _projetos(tmp_path, monkeypatch)
    lixeira.mover(_criar(tmp_path, "x"))
    _criar(tmp_path, "x")
    try:
        lixeira.restaurar("x")
        assert False
    except FileExistsError:
        pass


def test_limpa_so_os_antigos(tmp_path, monkeypatch):
    _projetos(tmp_path, monkeypatch)
    lixeira.mover(_criar(tmp_path, "novo"))
    antigo = datetime.now() - timedelta(days=lixeira.DIAS + 1)
    (tmp_path / "_lixeira" / f"velho__apagado-{antigo:%Y%m%d-%H%M%S}").mkdir()
    assert lixeira.limpar_antigos() == 1
    assert [i["nome"] for i in lixeira.listar()] == ["novo"]
