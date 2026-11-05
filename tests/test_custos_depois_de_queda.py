"""Queda de energia no meio de uma gravação não pode parar a produção nem fazer pagar duas vezes pela mesma imagem.

Caso real: 2026-11-04, 23:24. O custos_reais.json do 17-ultimas-fotos virou 12 mil zeros, e cada imagem nova era salva,
estourava ao anotar o custo, contava como falha e era gerada de novo."""
import json

import pytest

from fabrica import consumo, custos_reais, util


class _Projeto:
    def __init__(self, pasta):
        self.pasta = pasta

    def caminho(self, *partes):
        return self.pasta.joinpath(*partes)


@pytest.fixture
def projeto(tmp_path, monkeypatch):
    monkeypatch.setattr(consumo, "registrar_custo", lambda *a, **k: None)
    return _Projeto(tmp_path)


def test_anotar_custo_com_arquivo_de_zeros_nao_estoura(projeto):
    arquivo = projeto.caminho("custos_reais.json")
    arquivo.write_bytes(b"\x00" * 12099)
    custos_reais.registrar(projeto, "imagem", "cena 1", 0.04, unidades=1)
    assert [l["motivo"] for l in json.loads(arquivo.read_text(encoding="utf-8"))] == ["cena 1"]


def test_arquivo_quebrado_fica_guardado_ao_lado(projeto):
    projeto.caminho("custos_reais.json").write_bytes(b"\x00" * 50)
    custos_reais.registrar(projeto, "imagem", "cena 1", 0.04, unidades=1)
    (guardado,) = projeto.pasta.glob("custos_reais.quebrado-*.json")
    assert guardado.read_bytes() == b"\x00" * 50


def test_arquivo_que_nao_e_lista_tambem_conta_como_quebrado(projeto):
    projeto.caminho("custos_reais.json").write_text('{"a": 1}', encoding="utf-8")
    custos_reais.registrar(projeto, "imagem", "cena 1", 0.04, unidades=1)
    assert len(custos_reais.historico(projeto)) == 1


def test_historico_quebrado_vale_como_vazio_e_nao_mexe_no_arquivo(projeto):
    """A página de custos só lê: quem guarda o quebrado é a próxima anotação."""
    arquivo = projeto.caminho("custos_reais.json")
    arquivo.write_bytes(b"\x00" * 50)
    assert custos_reais.historico(projeto) == []
    assert arquivo.read_bytes() == b"\x00" * 50


def test_custos_em_ordem_continuam_somando(projeto):
    custos_reais.registrar(projeto, "imagem", "cena 1", 0.04, unidades=1)
    custos_reais.registrar(projeto, "imagem", "cena 2", 0.04, unidades=1)
    assert [l["motivo"] for l in custos_reais.historico(projeto)] == ["cena 1", "cena 2"]


def test_gravar_atomico_nao_deixa_temporario(tmp_path):
    util.gravar_atomico(tmp_path / "a.json", '{"ok": true}')
    assert [f.name for f in tmp_path.iterdir()] == ["a.json"]
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == {"ok": True}
