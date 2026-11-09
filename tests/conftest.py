"""Nenhum teste toca no banco de imagens de verdade, nem no login e nas contas guardadas do ChatGPT."""
import pytest

from fabrica import banco_proprio, chatgpt_assinatura


@pytest.fixture(autouse=True)
def banco_de_imagens_de_teste(tmp_path, monkeypatch):
    monkeypatch.setattr(banco_proprio, "PASTA", tmp_path / "banco_imagens")
    monkeypatch.setattr(banco_proprio, "ARQUIVO_DO_BANCO", tmp_path / "banco_imagens" / "banco.db")


@pytest.fixture(autouse=True)
def chatgpt_de_teste(tmp_path, monkeypatch):
    # 2026-11-08: um teste sem isto trocou a conta de verdade e tirou uma conta da gaveta do Radar
    pasta = tmp_path / "codex-fabrica"
    monkeypatch.setattr(chatgpt_assinatura, "LOGIN", pasta / "auth.json")
    monkeypatch.setattr(chatgpt_assinatura, "RECUSA", pasta / "recusado.json")
    monkeypatch.setattr(chatgpt_assinatura, "GAVETA", pasta / "contas-radar")
    monkeypatch.setattr(chatgpt_assinatura, "LIMITES", pasta / "chatgpt_limites.json")
