"""Openverse e NARA sem rede: o que entra, o que fica de fora e como cada um se desliga."""
import pytest

from fabrica import bancos
from fabrica.midia import FonteIndisponivel


class Resposta:
    def __init__(self, dados, tipo="application/json"):
        self.dados, self.headers, self.status_code = dados, {"content-type": tipo}, 200

    def json(self):
        return self.dados


class Http:
    def __init__(self, resposta):
        self.resposta, self.pedidos = resposta, []

    def get(self, url, **pedido):
        self.pedidos.append((url, pedido))
        return self.resposta


class Busca:
    def __init__(self, resposta, **cfg):
        self.http, self.cfg = Http(resposta), cfg

    def _checar(self, resposta, nome):
        pass


def _foto(licenca, **resto):
    return {"id": "a1", "url": "https://x/f.jpg", "license": licenca, "license_version": "4.0", "title": "Trem",
            "creator": "Ana", "foreign_landing_url": "https://x/p", "tags": [{"name": "train"}], **resto}


def test_openverse_traz_a_foto_com_licenca_e_credito():
    achado = bancos.openverse(Busca(Resposta({"results": [_foto("by")]})), "foto", "trem")[0]
    assert (achado["fonte"], achado["arquivo"], achado["autor"]) == ("openverse", "https://x/f.jpg", "Ana")
    assert achado["licenca"] == "CC-BY 4.0 (Openverse)" and "train" in achado["descricao"]


def test_openverse_respeita_a_licenca_do_perfil():
    b = Busca(Resposta({"results": [_foto("by-sa"), _foto("by-nc"), _foto("cc0")]}), aceitar_cc_by=False)
    assert [a["licenca"].split()[0] for a in bancos.openverse(b, "foto", "trem")] == ["CC0"]
    assert b.http.pedidos[0][1]["params"]["license"] == "cc0,pdm"


def test_openverse_nao_busca_video():
    b = Busca(Resposta({"results": []}))
    assert bancos.openverse(b, "video", "trem") == [] and b.http.pedidos == []


def _nara(status="Unrestricted", url="https://c/foto.JPG", tamanho=1000):
    return {"body": {"hits": {"hits": [{"_id": "9", "_source": {"record": {
        "naId": 123, "title": "Ponte", "useRestriction": {"status": status},
        "digitalObjects": [{"objectUrl": url, "objectFileSize": tamanho}]}}}]}}}


def test_nara_sem_chave_se_desliga(monkeypatch):
    monkeypatch.delenv("NARA_API_KEY", raising=False)
    with pytest.raises(FonteIndisponivel):
        bancos.nara(Busca(Resposta(_nara())), "foto", "ponte")


def test_nara_com_chave_traz_so_o_livre(monkeypatch):
    monkeypatch.setenv("NARA_API_KEY", "k")
    b = Busca(Resposta(_nara()))
    achado = bancos.nara(b, "foto", "ponte")[0]
    assert (achado["id"], achado["pagina"]) == ("123", "https://catalog.archives.gov/id/123")
    assert b.http.pedidos[0][1]["headers"] == {"x-api-key": "k"}
    assert bancos.nara(Busca(Resposta(_nara("Restricted - Possibly"))), "foto", "ponte") == []


def test_nara_ignora_o_que_nao_e_foto_e_o_arquivo_gigante(monkeypatch):
    monkeypatch.setenv("NARA_API_KEY", "k")
    assert bancos.nara(Busca(Resposta(_nara(url="https://c/a.mp3"))), "foto", "ponte") == []
    assert bancos.nara(Busca(Resposta(_nara(tamanho=90_000_000))), "foto", "ponte") == []


def test_nara_que_devolve_a_pagina_do_site_se_desliga(monkeypatch):
    monkeypatch.setenv("NARA_API_KEY", "k")
    with pytest.raises(FonteIndisponivel):
        bancos.nara(Busca(Resposta({}, "text/html")), "foto", "ponte")


def test_os_dois_so_entram_em_cena_de_acervo():
    assert {"openverse", "nara"} <= bancos.ACERVO and {"openverse", "nara"} <= set(bancos.FONTES) <= set(bancos.FORCAS) | {"youtube"}
