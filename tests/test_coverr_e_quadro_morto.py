"""Coverr (vídeos de banco) e o quadro morto das cenas animadas. Sem rede."""
import subprocess

import pytest

from fabrica import animation_ai as a
from fabrica import bancos


class Resposta:
    status_code = 200

    def __init__(self, dados):
        self._dados = dados

    def json(self):
        return self._dados


class Buscador:
    def __init__(self, dados):
        self.dados = dados
        self.pedidos = []
        self.http = self

    def get(self, url, **kw):
        self.pedidos.append((url, kw))
        return Resposta(self.dados)

    def _checar(self, r, nome):
        pass


def video(**campos):
    base = {"id": "abc", "title": "Lion walking", "description": "A lion on the savanna", "tags": ["lion", "savanna"],
            "thumbnail": "https://t/x.jpg", "is_vertical": False, "duration": 12.5, "max_width": 3840,
            "max_height": 2160, "urls": {"mp4": "https://v/x.mp4"}}
    base.update(campos)
    return base


def test_coverr_sem_chave_se_desliga(monkeypatch):
    from fabrica.midia import FonteIndisponivel

    monkeypatch.delenv("COVERR_API_KEY", raising=False)
    monkeypatch.delenv("COVERR_API", raising=False)
    with pytest.raises(FonteIndisponivel):
        bancos.coverr(Buscador({}), "video", "lion")


def test_coverr_so_traz_video_horizontal_com_arquivo(monkeypatch):
    monkeypatch.delenv("COVERR_API", raising=False)
    monkeypatch.setenv("COVERR_API_KEY", "segredo")
    b = Buscador({"hits": [video(), video(id="v", is_vertical=True), video(id="s", urls={}),
                           video(id="q", max_width=1080, max_height=1920)]})
    achados = bancos.coverr(b, "video", "lion")
    assert [c["id"] for c in achados] == ["abc"]
    c = achados[0]
    assert c["fonte"] == "coverr" and c["tipo"] == "video" and c["duracao"] == 12.5
    assert "savanna" in c["descricao"] and c["avisar_download"].endswith("/videos/abc/stats/downloads")
    assert b.pedidos[0][1]["headers"]["Authorization"] == "Bearer segredo"
    assert bancos.coverr(b, "foto", "lion") == []


def test_coverr_mp4_em_dicionario(monkeypatch):
    monkeypatch.delenv("COVERR_API", raising=False)
    monkeypatch.setenv("COVERR_API_KEY", "k")
    b = Buscador({"hits": [video(urls={"mp4": {"low": "https://v/l.mp4", "high": "https://v/h.mp4"}})]})
    assert bancos.coverr(b, "video", "x")[0]["arquivo"] == "https://v/h.mp4"


def test_aviso_de_download_so_para_a_coverr(monkeypatch):
    monkeypatch.delenv("COVERR_API", raising=False)
    monkeypatch.setenv("COVERR_API_KEY", "k")
    chamadas = []

    class Http:
        def request(self, metodo, url, headers=None):
            chamadas.append((metodo, url))

    bancos.avisar_download({"fonte": "coverr", "avisar_download": "https://api.coverr.co/videos/1/stats/downloads"}, Http())
    bancos.avisar_download({"fonte": "pexels", "avisar_download": "https://x"}, Http())
    assert chamadas == [("PATCH", "https://api.coverr.co/videos/1/stats/downloads")]


def _clipe(tmp_path, filtro, nome):
    destino = tmp_path / nome
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", filtro, "-t", "6", "-r", "30",
                    "-pix_fmt", "yuv420p", str(destino)], check=True)
    return destino


def test_quadro_morto_tela_parada_reprova(tmp_path):
    parado = _clipe(tmp_path, "color=c=0xF7F6F2:s=320x180", "parado.mp4")
    no_meio, no_fim = a.quadros_mortos(parado)
    assert no_fim > 5 or no_meio > 5
    assert a._reprovado_por_quadro_morto(parado)


def test_quadro_morto_movimento_passa(tmp_path):
    vivo = _clipe(tmp_path, "testsrc=s=320x180:r=30", "vivo.mp4")
    assert a._reprovado_por_quadro_morto(vivo) == ""
