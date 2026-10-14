import pytest
from fastapi.testclient import TestClient

from fabrica import api, armazenamento, banco as banco_mod, fila

ROTEIRO = "Este é um roteiro de teste com mais de vinte caracteres."


@pytest.fixture
def cliente_http(tmp_path, monkeypatch):
    b = banco_mod.Banco(f"sqlite:///{tmp_path / 'teste.db'}")
    monkeypatch.setattr(banco_mod, "_BANCO", b)
    monkeypatch.setattr(armazenamento, "LOCAL", tmp_path / "entregas")
    for nome in ("FABRICA_R2_ENDPOINT", "FABRICA_R2_BUCKET", "FABRICA_R2_ACCESS_KEY", "FABRICA_R2_SECRET_KEY"):
        monkeypatch.delenv(nome, raising=False)
    yield TestClient(api.app)
    b.fechar()


def _cab(chave):
    return {"Authorization": f"Bearer {chave}"}


def test_sem_chave_ou_chave_errada(cliente_http):
    assert cliente_http.post("/v1/videos", json={"roteiro": ROTEIRO}).status_code == 401
    assert cliente_http.get("/v1/videos", headers=_cab("fab_errada")).status_code == 401


def test_pedir_acompanhar_e_baixar(cliente_http, tmp_path):
    _, chave = fila.criar_cliente("canal")
    r = cliente_http.post("/v1/videos", json={"roteiro": ROTEIRO, "titulo": "Meu vídeo"}, headers=_cab(chave))
    assert r.status_code == 202 and r.json()["estado"] == "na_fila" and r.json()["posicao_na_fila"] == 1
    vid = r.json()["id"]
    # o trabalhador produz e entrega (aqui, direto na fila)
    fila.pegar("m1")
    arquivo = tmp_path / "final.mp4"
    arquivo.write_bytes(b"video")
    objeto = armazenamento.guardar(arquivo, f"videos/{vid}/x.mp4")
    fila.concluir(vid, objeto=objeto, duracao_s=60.0)
    v = cliente_http.get(f"/v1/videos/{vid}", headers=_cab(chave)).json()
    assert v["estado"] == "pronto" and v["url_video"] == f"/v1/videos/{vid}/arquivo" and v["eventos"]
    baixado = cliente_http.get(v["url_video"], headers=_cab(chave))
    assert baixado.status_code == 200 and baixado.content == b"video"
    assert [x["id"] for x in cliente_http.get("/v1/videos", headers=_cab(chave)).json()["videos"]] == [vid]


def test_um_cliente_nao_ve_o_do_outro(cliente_http):
    _, chave_a = fila.criar_cliente("a")
    _, chave_b = fila.criar_cliente("b")
    vid = cliente_http.post("/v1/videos", json={"roteiro": ROTEIRO}, headers=_cab(chave_a)).json()["id"]
    assert cliente_http.get(f"/v1/videos/{vid}", headers=_cab(chave_b)).status_code == 404
    assert cliente_http.delete(f"/v1/videos/{vid}", headers=_cab(chave_b)).status_code == 404
    assert cliente_http.get("/v1/videos", headers=_cab(chave_b)).json()["videos"] == []


def test_limite_por_dia_e_cancelar(cliente_http):
    _, chave = fila.criar_cliente("pequeno", limite_por_dia=2)
    ids = [cliente_http.post("/v1/videos", json={"roteiro": ROTEIRO}, headers=_cab(chave)).json()["id"] for _ in range(2)]
    assert cliente_http.post("/v1/videos", json={"roteiro": ROTEIRO}, headers=_cab(chave)).status_code == 429
    assert cliente_http.delete(f"/v1/videos/{ids[0]}", headers=_cab(chave)).json()["estado"] == "cancelado"
    assert cliente_http.delete(f"/v1/videos/{ids[0]}", headers=_cab(chave)).status_code == 409


def test_roteiro_curto_e_saude(cliente_http):
    _, chave = fila.criar_cliente("c")
    assert cliente_http.post("/v1/videos", json={"roteiro": "curto"}, headers=_cab(chave)).status_code == 422
    cliente_http.post("/v1/videos", json={"roteiro": ROTEIRO}, headers=_cab(chave))
    assert cliente_http.get("/v1/saude").json() == {"fila": {"na_fila": 1}}
