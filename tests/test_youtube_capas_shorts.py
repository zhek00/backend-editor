"""Thumbnails, shorts e publicação no YouTube: o que dá para conferir sem rede e sem publicar nada."""
from datetime import datetime, timezone

import pytest

from fabrica import shorts, thumbnail, youtube_publicar as yt


def test_hora_do_canal_vira_utc():
    assert yt.quando_utc("2026-10-12 18:00") == datetime(2026, 10, 12, 21, 0, tzinfo=timezone.utc)
    assert yt.quando_utc("2026-10-12T18:00:00+00:00") == datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)


def test_agendado_sobe_privado_com_publishat_e_declara_sintetico(monkeypatch, tmp_path):
    enviado = {}

    class Resposta:
        status_code = 200
        headers = {"Location": "https://upload"}
        text = ""

    def post(url, params=None, headers=None, json=None, timeout=None):
        enviado.update(json or {})
        return Resposta()

    class Cliente:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def put(self, url, content=None, headers=None):
            r = Resposta()
            r.status_code = 201
            r.json = lambda: {"id": "abc"}
            return r

    arquivo = tmp_path / "v.mp4"
    arquivo.write_bytes(b"0" * 1000)
    monkeypatch.setattr(yt, "_token_valido", lambda: "token")
    monkeypatch.setattr(yt.httpx, "post", post)
    monkeypatch.setattr(yt.httpx, "Client", lambda timeout=None: Cliente())
    r = yt.publicar(arquivo, "Título", "Desc", ["a"], "public", publicar_em=datetime(2026, 10, 12, 21, tzinfo=timezone.utc),
                    sintetico=True)
    assert r["id"] == "abc"
    assert enviado["status"]["privacyStatus"] == "private"
    assert enviado["status"]["publishAt"] == "2026-10-12T21:00:00.000Z"
    assert enviado["status"]["containsSyntheticMedia"] is True


def test_checador_nao_mexe_no_que_o_youtube_agendou(monkeypatch, tmp_path):
    import json
    from fabrica import projeto as projeto_mod
    pasta = tmp_path / "p"
    pasta.mkdir()
    (pasta / "youtube.json").write_text(json.dumps({"status": "agendado", "pelo_youtube": True, "video_id": "x",
                                                    "agendado_para": "2020-01-01T00:00:00+00:00"}), encoding="utf-8")
    monkeypatch.setattr(projeto_mod, "PROJETOS", tmp_path)
    assert list(yt._agendamentos_pendentes()) == []


def test_thumbnail_1280x720_menor_que_2mb(tmp_path):
    from PIL import Image
    foto = tmp_path / "f.jpg"
    Image.new("RGB", (1600, 900), (90, 120, 160)).save(foto)
    for layout in thumbnail.LAYOUTS:
        destino = thumbnail.desenhar(foto, "Mesma fazenda", "*Preço* diferente", layout, tmp_path / f"{layout}.jpg")
        with Image.open(destino) as im:
            assert im.size == (1280, 720)
        assert destino.stat().st_size < 2_000_000


def _frases(*duracoes, bloco=1):
    saida, t = [], 0.0
    for i, d in enumerate(duracoes):
        saida.append({"i": i, "ini": t, "fim": t + d, "texto": f"Frase {i} sobre o leite?", "c": i, "bloco": bloco})
        t += d
    return saida


CFG = {"quantidade": 3, "duracao_minima": 20, "duracao_maxima": 58, "palavras_por_legenda": 3}


def test_short_respeita_duracao_bloco_e_sobreposicao():
    todas = _frases(10, 10, 10, 10, 10, 10, 10)
    todas[5]["bloco"] = todas[6]["bloco"] = 2
    ok = {"de": 0, "ate": 2, "titulo": "Frase sobre o *leite*", "titulo_post": "x"}
    assert shorts.conferir(ok, todas, CFG) == []
    assert any("passa de" in e for e in shorts.conferir({**ok, "ate": 6}, todas, CFG))
    assert any("menos que" in e for e in shorts.conferir({**ok, "ate": 0}, todas, CFG))
    assert any("mistura" in e for e in shorts.conferir({**ok, "de": 3, "ate": 5}, todas, CFG))
    assert any("sobrepõe" in e for e in shorts.conferir({**ok, "de": 1, "ate": 3}, todas, CFG, [ok]))


def test_titulo_do_short_com_palavras_da_fala():
    todas = _frases(12, 12)
    ruim = {"de": 0, "ate": 1, "titulo": "O *secreto* escondido revelado", "titulo_post": "x"}
    assert any("palavras que a fala não diz" in e for e in shorts.conferir(ruim, todas, CFG))


def test_shorts_pela_regra_sem_modelo():
    escolhidos = shorts._por_regra(_frases(*([9] * 12)), CFG)
    assert 1 <= len(escolhidos) <= 3
    assert all(shorts.conferir(t, _frases(*([9] * 12)), CFG) == [] for t in escolhidos)
