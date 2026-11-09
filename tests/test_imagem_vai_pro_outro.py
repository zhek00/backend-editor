"""Quando uma fonte de imagem acaba, a outra entra (pedido do usuário em 2026-11-08: "sempre que acabar o crédito de
um vai pro outro"), e o login do ChatGPT revogado aparece como desconectado em vez de "conectada"."""
import json
from types import SimpleNamespace

import pytest

from fabrica import chatgpt_assinatura, imagens


class Projeto(SimpleNamespace):
    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.png"


def _projeto(tmp_path, provedor):
    (tmp_path / "imagens").mkdir()
    return Projeto(pasta=tmp_path, nome="p", offline=False, config={},
                   perfil={"imagens": {"provedor": provedor, "provedor_reserva": "openrouter"}})


@pytest.fixture
def sem_custos(monkeypatch):
    monkeypatch.setattr(imagens, "prompt_final", lambda c, p, r: "um prompt")
    monkeypatch.setattr("fabrica.custos_reais.registrar", lambda *a, **k: None)
    monkeypatch.setattr("fabrica.banco_proprio.depois_de_gerar", lambda *a, **k: None)


CENA = {"n": 3, "personagem": False, "texto": "", "prompt": "um prompt"}


def test_openrouter_no_limite_vai_para_o_chatgpt(monkeypatch, tmp_path, sem_custos):
    projeto = _projeto(tmp_path, "openrouter")
    monkeypatch.setattr(imagens, "_imagem_por_api", lambda *a, **k: (_ for _ in ()).throw(imagens.SemCota("limite semanal")))
    monkeypatch.setattr(chatgpt_assinatura, "disponivel", lambda: True)
    monkeypatch.setattr(chatgpt_assinatura, "gerar", lambda *a, **k: (b"png", {"provedor": "assinatura", "custo_usd": 0.0}))
    imagens._gerar_uma(projeto, dict(CENA), [], 2)
    registro = json.loads(projeto.imagem(3).with_suffix(".json").read_text(encoding="utf-8"))
    assert registro["provedor"] == "assinatura" and "limite semanal" in registro["reserva_da_api"]


def test_chatgpt_fora_vai_para_o_openrouter(monkeypatch, tmp_path, sem_custos):
    projeto = _projeto(tmp_path, "assinatura")
    monkeypatch.setattr(chatgpt_assinatura, "gerar", lambda *a, **k: (_ for _ in ()).throw(chatgpt_assinatura.SemLogin("revogado")))
    monkeypatch.setattr(imagens, "_imagem_por_api", lambda *a, **k: (b"png", {"provedor": "openrouter", "custo_usd": 0.004}))
    imagens._gerar_uma(projeto, dict(CENA), [], 2)
    assert projeto.imagem(3).exists()


def test_as_duas_acabaram_a_mensagem_diz_as_duas(monkeypatch, tmp_path, sem_custos):
    projeto = _projeto(tmp_path, "assinatura")
    monkeypatch.setattr(chatgpt_assinatura, "gerar", lambda *a, **k: (_ for _ in ()).throw(chatgpt_assinatura.SemLogin("revogado")))
    monkeypatch.setattr(imagens, "_imagem_por_api", lambda *a, **k: (_ for _ in ()).throw(imagens.SemCota("limite semanal")))
    with pytest.raises(imagens.SemCota) as erro:
        imagens._gerar_uma(projeto, dict(CENA), [], 2)
    assert "revogado" in str(erro.value) and "limite semanal" in str(erro.value)


def test_login_recusado_fica_desconectado_ate_um_login_novo(monkeypatch, tmp_path):
    login = tmp_path / "auth.json"
    login.write_text(json.dumps({"tokens": {"access_token": "x"}}), encoding="utf-8")
    monkeypatch.setattr(chatgpt_assinatura, "LOGIN", login)
    monkeypatch.setattr(chatgpt_assinatura, "RECUSA", tmp_path / "recusado.json")
    monkeypatch.setattr(chatgpt_assinatura, "_venceu", lambda t: False)
    assert chatgpt_assinatura.disponivel()
    chatgpt_assinatura.marcar_recusa("A OpenAI revogou o login")
    assert not chatgpt_assinatura.disponivel()
    assert chatgpt_assinatura.estado()["conectada"] is False
    login.write_text(json.dumps({"tokens": {"access_token": "novo-login"}}), encoding="utf-8")   # conectou de novo
    assert chatgpt_assinatura.disponivel()
