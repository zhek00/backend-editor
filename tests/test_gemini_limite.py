"""O Gemini lento na descrição sai da frente (2026-10-27): no tescos-60-billion ele levou de 20 a 80 s por imagem,
com o Google sobrecarregado, e a descrição esperava cada uma. Com o limite, ele passa a vez para a cadeia de visão e
fica de lado uns minutos."""
import types as T

import httpx
import pytest

from fabrica import gemini_local, openrouter_local

ESQUEMA = {"type": "object", "properties": {"r": {"type": "string"}}, "required": ["r"]}


class _Lento:
    def __init__(self):
        self.chamadas = 0
        self.models = self

    def generate_content(self, **_):
        self.chamadas += 1
        raise httpx.ReadTimeout("passou do prazo")


@pytest.fixture
def lento(monkeypatch):
    cliente = _Lento()
    monkeypatch.setattr(gemini_local, "_cliente", lambda: cliente)
    gemini_local._de_lado.clear()
    yield cliente
    gemini_local._de_lado.clear()


def _pergunta(limite):
    projeto = T.SimpleNamespace(config={}, caminho=None, pasta=None, nome="teste")
    return gemini_local.perguntar(projeto, "descrever imagens", "x", "y", ESQUEMA, log=lambda *_: None,
                                  modelo="gemini-3.1-flash-lite", na_cadeia=True, limite=limite)


def test_lento_passa_a_vez_e_fica_de_lado(lento):
    with pytest.raises(openrouter_local.RotaIndisponivel):
        _pergunta(15)
    assert lento.chamadas == 1  # sem a segunda tentativa de 3 s
    with pytest.raises(openrouter_local.RotaIndisponivel, match="de lado"):
        _pergunta(15)
    assert lento.chamadas == 1  # de lado: nem chama


def test_sem_limite_nada_fica_de_lado(lento):
    with pytest.raises(openrouter_local.RotaIndisponivel):
        _pergunta(None)
    assert not gemini_local._de_lado
