"""Openverse sem rede: o que entra e o que fica de fora."""
from fabrica import bancos


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


def test_openverse_so_entra_em_cena_de_acervo():
    assert "openverse" in bancos.ACERVO and "openverse" in bancos.FONTES and "openverse" in bancos.FORCAS
