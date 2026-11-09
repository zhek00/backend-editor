"""Conta do ChatGPT que para dá lugar a outra da gaveta do Radar; sem nenhuma, o erro sobe para a chave de API
(pedido do usuário em 2026-11-08)."""
import base64
import json

import pytest

from fabrica import chatgpt_assinatura as c


def _login(email):
    corpo = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return {"tokens": {"access_token": f"tok-{email}", "id_token": f"x.{corpo}.y"}}


@pytest.fixture
def pasta(monkeypatch, tmp_path):
    monkeypatch.setattr(c, "LOGIN", tmp_path / "auth.json")
    monkeypatch.setattr(c, "RECUSA", tmp_path / "recusado.json")
    monkeypatch.setattr(c, "GAVETA", tmp_path / "contas-radar")
    monkeypatch.setattr(c, "LIMITES", tmp_path / "limites.json")
    c._gravar_json(c.LOGIN, _login("a@x.com"))
    return tmp_path


def _guardar(email, **extra):
    c._gravar_json(c._na_gaveta(email), {"login": _login(email), "guardada": 1.0, **extra})


def test_conta_revogada_troca_pela_guardada_e_vai_para_a_gaveta(pasta, monkeypatch):
    _guardar("b@x.com")
    usadas = []

    def na_conta(*a):
        email = c._email(c._ler_json(c.LOGIN))
        usadas.append(email)
        if email == "a@x.com":
            raise c.SemLogin("revogado")
        return b"png", {"provedor": "assinatura"}
    monkeypatch.setattr(c, "_gerar_na_conta", na_conta)
    assert c.gerar("p")[0] == b"png"
    assert usadas == ["a@x.com", "b@x.com"]
    assert c._ler_json(c._na_gaveta("a@x.com"))["recusada"] == "revogado"
    assert not c._na_gaveta("b@x.com").exists()


def test_sem_outra_conta_o_erro_sobe(pasta, monkeypatch):
    monkeypatch.setattr(c, "_gerar_na_conta", lambda *a: (_ for _ in ()).throw(c.LimiteDaAssinatura("limite")))
    with pytest.raises(c.LimiteDaAssinatura):
        c.gerar("p")


def test_conta_no_limite_ou_recusada_nao_entra(pasta, monkeypatch):
    import time
    _guardar("b@x.com", recusada="revogado")
    _guardar("c@x.com", limite_ate=time.time() + 3600)
    monkeypatch.setattr(c, "_gerar_na_conta", lambda *a: (_ for _ in ()).throw(c.SemLogin("revogado")))
    with pytest.raises(c.SemLogin):
        c.gerar("p")
    assert c._email(c._ler_json(c.LOGIN)) == "a@x.com"     # nenhuma serviu: a ligada continua a mesma


def test_imagens_em_paralelo_trocam_uma_vez_so(pasta):
    _guardar("b@x.com")
    _guardar("c@x.com")
    versao = c._versao_do_login()
    assert c.trocar_de_conta(c.SemLogin("x"), versao)
    ligada = c._email(c._ler_json(c.LOGIN))
    assert c.trocar_de_conta(c.SemLogin("x"), versao)       # outra imagem com a versão velha: não troca de novo
    assert c._email(c._ler_json(c.LOGIN)) == ligada
