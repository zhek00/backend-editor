"""Correções do corrigir.py (e do download em midia.py que ele usa).

Antes: uma imagem nova recusada depois do download apagava a foto antiga da cena, e o Corrigir devolvia à cena um
arquivo que não existia; a restauração gravava a conferência sem o sujeito e a época; uma resposta do Jev sem a nota
de combinar derrubava a escolha com KeyError; e os caches do mapa guardavam uma cópia a cada edição."""
import io
import json
import os
import pathlib
import time

import httpx
import pytest
from PIL import Image, ImageDraw

from fabrica import corrigir, jev_local, midia


class _Projeto:
    nome = "t"
    offline = True
    config: dict = {}
    perfil: dict = {}

    def __init__(self, pasta, cenas=None):
        self.pasta = pathlib.Path(pasta)
        self._cenas = {"cenas": cenas or []}

    def caminho(self, *partes):
        destino = self.pasta.joinpath(*partes)
        destino.parent.mkdir(parents=True, exist_ok=True)
        return destino

    def existe(self, nome):
        return nome == "cenas.json" or (self.pasta / nome).exists()

    def ler_json(self, nome):
        if nome == "cenas.json":
            return json.loads(json.dumps(self._cenas))
        return json.loads((self.pasta / nome).read_text(encoding="utf-8"))

    def salvar_json(self, nome, dados):
        if nome == "cenas.json":
            self._cenas = json.loads(json.dumps(dados))
        else:
            (self.pasta / nome).write_text(json.dumps(dados), encoding="utf-8")

    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.png"


def _jpeg(formas, fundo=(40, 60, 90)):
    im = Image.new("RGB", (320, 180), fundo)
    desenho = ImageDraw.Draw(im)
    for caixa, cor in formas:
        desenho.rectangle(caixa, fill=cor)
    saida = io.BytesIO()
    im.save(saida, "JPEG")
    return saida.getvalue()


_A = [((20, 20, 120, 90), (230, 200, 40)), ((180, 60, 300, 160), (200, 30, 30)), ((10, 120, 90, 170), (240, 240, 240))]
_B = [((200, 10, 310, 70), (230, 200, 40)), ((20, 90, 150, 170), (30, 200, 60)), ((130, 20, 170, 60), (10, 10, 10))]
_C = [((60, 30, 260, 150), (90, 20, 160)), ((5, 5, 40, 40), (250, 250, 0))]


class _Resposta:
    def __init__(self, dados):
        self.dados = dados

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self):
        yield self.dados


class _Http:
    """O banco devolve sempre estes bytes; com falha=True a conexão cai no meio."""

    def __init__(self, dados, falha=False):
        self.dados, self.falha = dados, falha

    def stream(self, metodo, url):
        if self.falha:
            raise httpx.ConnectError("caiu")
        return _Resposta(self.dados)


def _cenario(tmp_path):
    """Cena 1 sem mídia, mas com a foto antiga (B) ainda em midia/0001.jpg; cena 2 mostra a foto A."""
    (tmp_path / "midia").mkdir()
    (tmp_path / "midia" / "0001.jpg").write_bytes(_jpeg(_B))
    (tmp_path / "midia" / "0002.jpg").write_bytes(_jpeg(_A))
    cenas = [{"n": 1, "midia": None},
             {"n": 2, "midia": {"fonte": "pexels", "id": "2", "arquivo": "midia/0002.jpg", "capa": "midia/0002.jpg"}}]
    return _Projeto(tmp_path, cenas), cenas


_CANDIDATO = {"fonte": "pixabay", "id": "9", "tipo": "foto", "miniatura": "m", "arquivo": "a"}


# --- 1. a foto antiga da cena sobrevive à imagem nova recusada -----------------------------------------------------

def test_imagem_nova_repetida_nao_apaga_a_foto_antiga_da_cena(tmp_path):
    projeto, cenas = _cenario(tmp_path)
    antiga = (tmp_path / "midia" / "0001.jpg").read_bytes()
    with pytest.raises(midia.ImagemRepetida):
        midia._baixar_midia(projeto, cenas[0], _CANDIDATO, _Http(_jpeg(_A)))  # a mesma foto da cena 2
    assert (tmp_path / "midia" / "0001.jpg").read_bytes() == antiga
    assert not list((tmp_path / "midia").glob("*.anterior"))


def test_download_que_cai_no_meio_nao_apaga_a_foto_antiga(tmp_path):
    projeto, cenas = _cenario(tmp_path)
    antiga = (tmp_path / "midia" / "0001.jpg").read_bytes()
    with pytest.raises(httpx.HTTPError):
        midia._baixar_midia(projeto, cenas[0], _CANDIDATO, _Http(b"", falha=True))
    assert (tmp_path / "midia" / "0001.jpg").read_bytes() == antiga
    assert not list((tmp_path / "midia").glob("*.anterior"))


def test_imagem_nova_aceita_ocupa_o_lugar_e_nao_deixa_copia(tmp_path):
    projeto, cenas = _cenario(tmp_path)
    nova = _jpeg(_C)
    registro = midia._baixar_midia(projeto, cenas[0], _CANDIDATO, _Http(nova))
    assert registro["arquivo"].replace("\\", "/") == "midia/0001.jpg"
    assert (tmp_path / "midia" / "0001.jpg").read_bytes() == nova
    assert not list((tmp_path / "midia").glob("*.anterior"))


def test_tirar_outra_coisa_devolve_uma_foto_que_existe_quando_a_nova_e_recusada(tmp_path, monkeypatch):
    """O caminho real: o Corrigir tira a foto que mostra outra coisa, a busca baixa uma repetida, o download é
    recusado (como no aplicar do midia.buscar) e a cena volta para a foto que tinha. Antes ela voltava sem arquivo."""
    (tmp_path / "midia").mkdir()
    (tmp_path / "midia" / "0001.jpg").write_bytes(_jpeg(_B))
    (tmp_path / "midia" / "0002.jpg").write_bytes(_jpeg(_A))
    cenas = [{"n": 1, "tipo": "foto_real", "conferencia": {"nota": 5},
              "midia": {"fonte": "pexels", "id": "1", "arquivo": "midia/0001.jpg", "capa": "midia/0001.jpg"}},
             {"n": 2, "tipo": "foto_real", "conferencia": {"nota": 90},
              "midia": {"fonte": "pexels", "id": "2", "arquivo": "midia/0002.jpg", "capa": "midia/0002.jpg"}}]
    projeto = _Projeto(tmp_path, cenas)

    def busca_que_acha_uma_repetida(proj, apenas=None, log=print, permissivo=False):
        dados = proj.ler_json("cenas.json")
        for c in dados["cenas"]:
            if c["n"] in apenas:
                try:
                    c["midia"] = midia._baixar_midia(proj, c, _CANDIDATO, _Http(_jpeg(_A)))
                except midia.ImagemRepetida:
                    pass  # o aplicar real também só registra e segue
        proj.salvar_json("cenas.json", dados)

    monkeypatch.setattr(midia, "buscar", busca_que_acha_uma_repetida)
    trocadas = corrigir._tirar_outra_coisa(projeto, 40, log=lambda m: None)
    assert trocadas == []
    cena = projeto.ler_json("cenas.json")["cenas"][0]
    assert cena["midia"]["arquivo"] == "midia/0001.jpg"
    assert (tmp_path / cena["midia"]["arquivo"]).exists()  # a referência aponta para um arquivo de verdade
    assert cena["captura"]["suspeita"]


# --- 2. a restauração guarda a conferência inteira -----------------------------------------------------------------

def test_restaurar_mantem_sujeito_epoca_e_prompt_novo(tmp_path):
    avaliacao = {"legenda": "x", "veredito": "nao_combina", "nota": 30, "motivo": "m", "sujeito": 20, "epoca": 80,
                 "prompt_novo": "a lynx in snow"}
    m = {"fonte": "f", "id": "1", "arquivo": "midia/0001.jpg"}
    projeto = _Projeto(tmp_path, [{"n": 1, "midia": m, "busca": "b", "prompt": "p"}])
    corrigir._restaurar(projeto, {1: {"nota": 30, "avaliacao": avaliacao, "midia": m, "copias": [],
                                      "busca": "b", "prompt": "p"}})
    conferencia = projeto.ler_json("cenas.json")["cenas"][0]["conferencia"]
    assert conferencia["sujeito"] == 20 and conferencia["epoca"] == 80 and conferencia["prompt_novo"] == "a lynx in snow"
    assert conferencia["restaurada"] is True
    assert corrigir.errada(conferencia) == corrigir.errada(avaliacao) is True


def test_guardar_continua_igual(tmp_path):
    projeto = _Projeto(tmp_path, [{"n": 1}, {"n": 2}])
    corrigir._guardar(projeto, {1: {"legenda": "x", "veredito": "combina", "nota": 90, "motivo": "m", "sujeito": 95,
                                    "epoca": None, "prompt_novo": ""}}, rodada=2)
    cenas = projeto.ler_json("cenas.json")["cenas"]
    assert cenas[0]["conferencia"] == {"legenda": "x", "veredito": "combina", "nota": 90, "motivo": "m", "rodada": 2,
                                       "sujeito": 95, "prompt_novo": ""}
    assert "conferencia" not in cenas[1]


# --- 3. resposta incompleta do Jev ---------------------------------------------------------------------------------

@pytest.mark.parametrize("resposta", [{"sujeito": {"noul": 0.9}}, {"combina": {}}, {"combina": {"noul": None}},
                                      {"combina": {"noul": "talvez"}}])
def test_resposta_incompleta_do_jev_vale_como_nao_julgou(tmp_path, monkeypatch, resposta):
    monkeypatch.setattr(jev_local, "decidir", lambda *a, **k: resposta)
    projeto = _Projeto(tmp_path)
    cena = {"n": 1, "texto": "oi", "midia": {"pagina": ""}}
    assert corrigir._julgar_com_jev(projeto, cena, "legenda", {}, lambda m: None) is None
    # e a escolha das fotos segue: o candidato passa sem julgamento, em vez de um KeyError derrubar o lote
    assert midia._nota_do_candidato(projeto, cena, {"fonte": "x", "id": "1"}, "frase", {}, lambda m: None) is None


def test_resposta_completa_do_jev_continua_valendo(tmp_path, monkeypatch):
    monkeypatch.setattr(jev_local, "decidir", lambda *a, **k: {"combina": {"noul": 0.85}, "sujeito": {"noul": 0.9}})
    avaliacao = corrigir._julgar_com_jev(_Projeto(tmp_path), {"n": 1, "texto": "oi", "midia": {}}, "l", {}, lambda m: None)
    assert avaliacao["nota"] == 85 and avaliacao["sujeito"] == 90 and avaliacao["veredito"] == "combina"


# --- 4. caches do mapa ---------------------------------------------------------------------------------------------

def test_cache_do_mapa_tem_uma_entrada_por_arquivo_e_acompanha_a_edicao(tmp_path):
    projeto = _Projeto(tmp_path)
    arquivo = tmp_path / "roteiro_mapa.json"
    antes_mapas, antes_quem = len(corrigir._MAPAS), len(corrigir._QUEM_E)
    for i in range(5):
        arquivo.write_text(json.dumps({"blocos": [{"id": 1, "nome": f"bloco {i}", "ancora": "a"}],
                                       "quem_e": [{"nome": "John Patterson", "quem": f"versão {i}"}]}), encoding="utf-8")
        momento = time.time() + i + 1
        os.utime(arquivo, (momento, momento))
        assert corrigir._bloco_da_cena_no_mapa(projeto, {"bloco": 1}) == f"bloco {i}: a"
        assert corrigir._pessoa_da_cena(projeto, {"texto": "Patterson chegou"}) == f"John Patterson: versão {i}"
    assert len(corrigir._MAPAS) - antes_mapas == 1
    assert len(corrigir._QUEM_E) - antes_quem == 1


def test_sem_mapa_nao_ha_bloco_nem_pessoa(tmp_path):
    projeto = _Projeto(tmp_path)
    assert corrigir._bloco_da_cena_no_mapa(projeto, {"bloco": 1}) == ""
    assert corrigir._pessoa_da_cena(projeto, {"texto": "Patterson"}) == ""
