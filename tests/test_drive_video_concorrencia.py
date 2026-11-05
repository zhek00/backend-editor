"""Drive, vídeo de IA e a concorrência de imagem aprendida. O Google e a fal são dublês: nada vai à rede."""
import json
import sys
import time
import types

import pytest

from fabrica import drive, imagens, video_ia


class _Resp:
    def __init__(self, dados=None, codigo=200, headers=None, texto=""):
        self.dados, self.status_code, self.headers, self.text = dados or {}, codigo, headers or {}, texto

    def json(self):
        return self.dados

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _Google:
    def __init__(self, pastas=()):
        self.pastas, self.pedacos, self.criadas = list(pastas), [], []

    def get(self, url, params=None, headers=None, timeout=None):
        return _Resp({"files": [{"id": "achada"}] if self.pastas and self.pastas.pop(0) else []})

    def post(self, url, json=None, params=None, headers=None, timeout=None, data=None):
        if url == drive.URL_UPLOAD:
            return _Resp(headers={"location": "http://sessao"})
        if url == drive.URL_TOKEN:
            return _Resp({"access_token": "novo", "expires_in": 3600})
        self.criadas.append(json["name"])
        return _Resp({"id": f"id-{json['name']}"})

    def put(self, url, content=None, headers=None, timeout=None):
        self.pedacos.append(headers["Content-Range"])
        fim, total = headers["Content-Range"].split("-")[1].split("/")
        return _Resp({"id": "video-1"}, 200) if int(fim) + 1 == int(total) else _Resp(codigo=308)


@pytest.fixture
def conta(tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "ARQUIVO_CONTA", tmp_path / "conta.json")
    monkeypatch.setattr(drive, "_credenciais_app", lambda: ("id", "segredo"))
    drive._salvar({"refresh_token": "r", "access_token": "a", "expira_em": time.time() + 3000})


def _projeto(tmp_path, final=True):
    salvos = {}
    if final:
        (tmp_path / "final.mp4").write_bytes(b"x" * 10)
    return types.SimpleNamespace(pasta=tmp_path, perfil={"nome": "Canal A"}, nome="v", dados={"titulo_entrega": "Título"},
                                 salvar_json=lambda n, d: salvos.update({n: d}), salvos=salvos)


def test_sem_conta_o_video_fica_no_computador(tmp_path, monkeypatch):
    monkeypatch.setattr(drive, "ARQUIVO_CONTA", tmp_path / "nada.json")
    falas = []
    assert drive.enviar(_projeto(tmp_path), falas.append) is None
    assert "só no computador" in falas[0]


def test_envio_cria_as_pastas_e_sobe_o_video(tmp_path, conta):
    google = _Google()
    p = _projeto(tmp_path)
    assert drive.enviar(p, lambda _m: None, google) == "video-1"
    assert google.criadas == ["Fábrica", "Canal A"]
    assert p.salvos["drive.json"]["arquivo"] == "video-1"


def test_pasta_que_existe_nao_e_criada_de_novo(tmp_path, conta):
    google = _Google([True, True])
    drive.enviar(_projeto(tmp_path), lambda _m: None, google)
    assert google.criadas == []


def test_video_grande_sobe_em_pedacos(tmp_path, conta, monkeypatch):
    monkeypatch.setattr(drive, "PEDACO", 4)
    google = _Google()
    drive.enviar(_projeto(tmp_path), lambda _m: None, google)
    assert google.pedacos == ["bytes 0-3/10", "bytes 4-7/10", "bytes 8-9/10"]


def test_erro_do_drive_nao_para_a_entrega(tmp_path, conta):
    class Quebrado(_Google):
        def put(self, *a, **k):
            return _Resp(codigo=403, texto="sem permissão")

    falas = []
    assert drive.enviar(_projeto(tmp_path), falas.append, Quebrado()) is None
    assert "fica no computador" in falas[0]


def test_token_vencido_e_renovado(tmp_path, conta):
    drive._salvar({"refresh_token": "r", "access_token": "velho", "expira_em": 0})
    assert drive._token(_Google()) == "novo"
    assert drive.conta()["access_token"] == "novo" and drive.conta()["refresh_token"] == "r"


def test_autorizacao_pede_so_o_que_a_fabrica_cria(conta):
    url = drive.url_autorizacao("http://x/cb")
    assert "drive.file" in url and "state=drive" in url


# ---------------------------------------------------------------------------------------------------


class _Projeto:
    def __init__(self, pasta, cenas, cfg):
        self.pasta, self.config, self.offline = pasta, {"video_ia": cfg}, False
        self.cenas = cenas
        (pasta / "imagens").mkdir(exist_ok=True)
        for c in cenas:
            if not c.get("midia"):
                (pasta / "imagens" / f"{c['n']:04d}.jpg").write_bytes(b"i")

    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.jpg"

    def caminho(self, *partes):
        return self.pasta.joinpath(*partes)

    def ler_json(self, _n):
        return {"cenas": self.cenas}

    def salvar_json(self, _n, dados):
        self.salvo = dados


def test_sem_fracao_nao_gasta_nada(tmp_path):
    p = _Projeto(tmp_path, [{"n": 1}], {})
    assert video_ia.gerar(p, lambda _m: None) == 0


def test_cenas_ficam_espalhadas_e_cena_com_midia_fica_de_fora(tmp_path):
    cenas = [{"n": i} for i in range(1, 11)] + [{"n": 11, "midia": {"fonte": "pexels"}}]
    p = _Projeto(tmp_path, cenas, {"fracao": 0.2})
    assert [c["n"] for c in video_ia.candidatas(p, cenas)] == [1, 6]


def test_clipe_vira_midia_da_cena_e_falha_deixa_a_imagem(tmp_path, monkeypatch):
    cenas = [{"n": 1}, {"n": 2}]
    p = _Projeto(tmp_path, cenas, {"fracao": 1})

    def clipe(_p, cena, _m):
        if cena["n"] == 2:
            raise RuntimeError("sem crédito")
        return {"fonte": "video_ia", "tipo": "video", "arquivo": "midia/0001_ia.mp4"}

    monkeypatch.setattr(video_ia, "_clipe", clipe)
    falas = []
    assert video_ia.gerar(p, falas.append) == 1
    assert cenas[0]["midia"]["fonte"] == "video_ia" and "midia" not in cenas[1]
    assert any("fica com a imagem" in f for f in falas)


class _Kie:
    def __init__(self, estados=(), criar=None, subir=None):
        self.estados, self.criar, self.subir = list(estados), criar, subir
        self.corpo = None

    def post(self, url, json=None, headers=None, timeout=None, data=None, files=None):
        if url == video_ia.URL_UPLOAD:
            return _Resp(self.subir or {"success": True, "data": {"downloadUrl": "http://tmp/i.jpg"}})
        self.corpo = json
        return _Resp(self.criar or {"code": 200, "data": {"taskId": "t1"}})

    def get(self, url, params=None, headers=None, timeout=None):
        return _Resp({"data": self.estados.pop(0)})


def test_pedido_do_clipe_vai_no_formato_do_kie():
    kie = _Kie()
    assert video_ia._pedir_clipe(kie, {}, video_ia.MODELO, "http://i", "movimento") == "t1"
    assert kie.corpo == {"model": "kling/v2-1-standard", "input": {"prompt": "movimento", "image_url": "http://i", "duration": "5"}}


def test_falta_de_credito_vira_erro_com_o_motivo():
    kie = _Kie(criar={"code": 402, "msg": "Credits insufficient"})
    with pytest.raises(RuntimeError, match="Credits insufficient"):
        video_ia._pedir_clipe(kie, {}, "m", "u", "p")


def test_espera_a_fila_ate_sair_o_clipe():
    pronto = {"state": "success", "resultJson": json.dumps({"resultUrls": ["http://v.mp4"]})}
    kie = _Kie([{"state": "waiting"}, {"state": "generating"}, pronto])
    assert video_ia._esperar_clipe(kie, {}, "t1", dormir=lambda _s: None) == "http://v.mp4"


def test_clipe_que_falha_na_fila_diz_o_motivo():
    kie = _Kie([{"state": "fail", "failMsg": "imagem recusada"}])
    with pytest.raises(RuntimeError, match="imagem recusada"):
        video_ia._esperar_clipe(kie, {}, "t1", dormir=lambda _s: None)


def test_imagem_recusada_no_upload(tmp_path):
    (tmp_path / "i.jpg").write_bytes(b"x")
    with pytest.raises(RuntimeError, match="recusou a imagem"):
        video_ia._subir_imagem(_Kie(subir={"success": False, "msg": "grande demais"}), {}, tmp_path / "i.jpg")


# ---------------------------------------------------------------------------------------------------


@pytest.fixture
def aprendizado(tmp_path, monkeypatch):
    monkeypatch.setattr(imagens, "ARQUIVO_CONCORRENCIA", tmp_path / "c.json")


def test_comeca_no_teto_do_config(aprendizado):
    assert imagens.concorrencia("openrouter", 16) == 16


def test_limite_da_api_corta_pela_metade(aprendizado):
    imagens.aprender_concorrencia("openrouter", 16, 16, 3)
    assert imagens.concorrencia("openrouter", 16) == 8


def test_sem_limite_volta_a_subir_e_nunca_passa_do_teto(aprendizado):
    imagens.aprender_concorrencia("openrouter", 16, 16, 3)
    imagens.aprender_concorrencia("openrouter", 16, 8, 0)
    assert imagens.concorrencia("openrouter", 16) == 16
    imagens.aprender_concorrencia("openrouter", 16, 16, 0)
    assert imagens.concorrencia("openrouter", 16) == 16


def test_piso_de_duas(aprendizado):
    imagens.aprender_concorrencia("x", 16, 2, 5)
    assert imagens.concorrencia("x", 16) == 2


def test_cada_provedor_tem_a_sua_conta(aprendizado):
    imagens.aprender_concorrencia("a", 16, 16, 1)
    assert imagens.concorrencia("b", 16) == 16
    assert json.loads(imagens.ARQUIVO_CONCORRENCIA.read_text(encoding="utf-8")) == {"a": 8}


def test_config_mais_baixo_vale_por_cima_do_aprendido(aprendizado):
    imagens.aprender_concorrencia("a", 16, 16, 0)
    assert imagens.concorrencia("a", 4) == 4
