"""Nenhum teste toca no banco de imagens de verdade."""
import pytest

from fabrica import banco_proprio


@pytest.fixture(autouse=True)
def banco_de_imagens_de_teste(tmp_path, monkeypatch):
    monkeypatch.setattr(banco_proprio, "PASTA", tmp_path / "banco_imagens")
    monkeypatch.setattr(banco_proprio, "ARQUIVO_DO_BANCO", tmp_path / "banco_imagens" / "banco.db")
