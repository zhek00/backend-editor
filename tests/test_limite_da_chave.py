"""O 403 de limite da chave do OpenRouter: espera se é reserva, avisa certo se acabou (2026-11-06)."""
import pytest

from fabrica import imagens, openrouter_local as o


class Resposta:
    def __init__(self, status, texto):
        self.status_code, self.text = status, texto

    def json(self):
        return {"data": []}


LIMITE = Resposta(403, '{"error":{"message":"Key limit exceeded (weekly limit). $22.76 of $22.00 used"}}')
BOA = Resposta(200, "{}")


@pytest.fixture
def resta(monkeypatch):
    def definir(valor):
        monkeypatch.setattr(o, "_limite_lido", (o.time.time(), valor))
    return definir


def test_403_de_limite_com_folga_e_reserva(resta):
    resta(1.64)
    assert o.credito_reservado(LIMITE)


def test_limite_acabado_nao_e_reserva(resta):
    resta(0.1)
    assert o.limite_da_chave(LIMITE) and not o.credito_reservado(LIMITE)


def test_sem_leitura_do_limite_conta_como_reserva(resta):
    resta(None)
    assert o.credito_reservado(LIMITE)


def test_outro_403_nao_e_limite():
    assert not o.limite_da_chave(Resposta(403, "forbidden"))
    assert not o.credito_reservado(Resposta(403, "forbidden"))


def test_a_imagem_espera_a_reserva_e_sai(resta, monkeypatch):
    resta(1.64)
    monkeypatch.setattr(o.time, "sleep", lambda _s: None)
    respostas = iter([LIMITE, LIMITE, BOA])
    assert o.postar_com_sessao(lambda *_a, **_k: next(respostas), "url", {}, None).status_code == 200


def test_limite_acabado_para_as_imagens_com_o_aviso_certo(resta, monkeypatch):
    resta(0.1)
    monkeypatch.setenv("OPENROUTER_API_KEY", "teste")
    monkeypatch.setattr(imagens.httpx.Client, "post", lambda *_a, **_k: LIMITE)
    with pytest.raises(imagens.SemCota, match="limite semanal"):
        imagens._imagem_openrouter_images("p", {}, "openai/gpt-5.4-image-2")
