"""Correções do midia.py: palavras que não casam por prefixo, ciência que não vira chroma, imagem lisa que não é
"repetida" e cache da escolha de fotos que não derruba o lote.

Antes: "bee" aceitava "beer" e "ant" aceitava "antelope"; "chromatography" era tratado como material de edição; um
quadro preto e um fundo cinza tinham a mesma impressão digital (distância 0); e um cache da escolha gravado pela
metade parava o lote com JSONDecodeError."""
import pathlib
import threading

from PIL import Image, ImageDraw

from fabrica import cliente, midia, util


# --- 1. palavras: plural sim, prefixo qualquer não -------------------------------------------------------------------

def _cita(assunto, descricao):
    return midia._cita_o_assunto(midia._radicais(assunto), {"descricao": descricao})


def test_palavra_de_tres_letras_nao_casa_com_outra_que_so_comeca_igual():
    assert not _cita("bee", "cold beer glass on table")
    assert not _cita("ant", "antelope grazing on savanna")
    assert not _cita("cat", "cattle in a field")
    assert not _cita("rat", "rate chart on a screen")
    assert not _cita("bees", "beer festival")


def test_plural_continua_casando():
    assert _cita("bee", "bees on a honeycomb")
    assert _cita("bees", "a bee on a flower")
    assert _cita("ant", "ants carrying a leaf")
    assert _cita("fox", "two foxes in the snow")  # o radical de 4 letras de "foxes" é "foxe"
    assert _cita("lion", "lions resting")
    assert _cita("cat", "a cat and a dog")


def test_cita_bastante_usa_a_mesma_regra():
    assunto = midia._radicais("human bones dry savanna")
    assert midia._cita_bastante(assunto, {"descricao": "human bones on dry ground"})
    assert not midia._cita_bastante(midia._radicais("bee hive garden"), {"descricao": "beer garden at night"})


# --- 2. material de edição: palavra inteira --------------------------------------------------------------------------

def test_chroma_de_ciencia_nao_e_material_de_edicao():
    for descricao in ("chromatography column lab", "chromatin structure under microscope", "chromatic aberration lens",
                      "lower third of the moon", "lower thirds of the screen are dark"[:0] or "moon lower third of sky"):
        assert not midia.de_edicao({"descricao": descricao}), descricao


def test_chroma_key_continua_sendo_material_de_edicao():
    for descricao in ("Chroma Key green screen", "chroma_key_green_background", "chroma-key explosion", "chromakey",
                      "chroma", "lower third animation", "lower-third template", "lower thirds pack",
                      "Green Screen Chroma Key explosion", "like and subscribe button"):
        assert midia.de_edicao({"descricao": descricao}), descricao


# --- 3. impressão digital: imagem lisa não é a mesma que outra lisa ------------------------------------------------

def _cena(caminho, retangulos, fundo=(40, 60, 90)):
    im = Image.new("RGB", (320, 180), fundo)
    d = ImageDraw.Draw(im)
    for caixa, cor in retangulos:
        d.rectangle(caixa, fill=cor)
    im.save(caminho)
    return caminho


def test_quadro_preto_nao_e_igual_a_fundo_claro_nem_a_azul_liso(tmp_path):
    preto = Image.new("RGB", (320, 180), (10, 10, 10)); preto.save(tmp_path / "preto.png")
    claro = Image.new("RGB", (320, 180), (200, 200, 220)); claro.save(tmp_path / "claro.png")
    azul = Image.new("RGB", (320, 180), (30, 90, 200)); azul.save(tmp_path / "azul.png")
    hp, hc, ha = (midia._impressao(tmp_path / n) for n in ("preto.png", "claro.png", "azul.png"))
    assert not midia._impressoes_iguais(hp, hc)
    assert not midia._impressoes_iguais(hp, ha)
    assert not midia._impressoes_iguais(hc, ha)


def test_o_mesmo_quadro_liso_continua_igual_a_si_mesmo(tmp_path):
    Image.new("RGB", (320, 180), (10, 10, 10)).save(tmp_path / "a.png")
    Image.new("RGB", (640, 360), (12, 11, 10)).save(tmp_path / "b.png")  # outro tamanho, quase o mesmo preto
    assert midia._impressoes_iguais(midia._impressao(tmp_path / "a.png"), midia._impressao(tmp_path / "b.png"))


def test_foto_com_textura_recomprimida_e_redimensionada_continua_igual(tmp_path):
    original = _cena(tmp_path / "o.png", [((20, 20, 120, 90), (230, 200, 40)), ((180, 60, 300, 160), (200, 30, 30)),
                                           ((10, 120, 90, 170), (240, 240, 240))])
    Image.open(original).resize((640, 360)).save(tmp_path / "r.jpg", quality=55)
    outra = _cena(tmp_path / "x.png", [((200, 10, 310, 70), (230, 200, 40)), ((20, 90, 150, 170), (30, 200, 60)),
                                       ((130, 20, 170, 60), (10, 10, 10))])
    h = midia._impressao(original)
    assert midia._impressoes_iguais(h, midia._impressao(tmp_path / "r.jpg"))
    assert not midia._impressoes_iguais(h, midia._impressao(outra))


# --- 4. cache da escolha de fotos ----------------------------------------------------------------------------------

class _Projeto:
    nome = "teste"
    config = {}
    perfil = {"nome": "canal"}

    def __init__(self, pasta):
        self.pasta = pathlib.Path(pasta)

    def caminho(self, *partes):
        destino = self.pasta.joinpath(*partes)
        destino.parent.mkdir(parents=True, exist_ok=True)
        return destino


def _lote(tmp_path, monkeypatch, conteudo_do_cache):
    monkeypatch.setattr(cliente, "atende", lambda *a, **k: False)
    projeto = _Projeto(tmp_path)
    projeto.caminho("midia", "escolha", "cena_0001.json").write_text(conteudo_do_cache, encoding="utf-8")
    candidato = {"fonte": "pexels", "id": "1", "tipo": "foto", "miniatura": "x", "arquivo": "y", "duracao": None,
                 "descricao": "d"}
    cena = {"n": 1, "texto": "oi", "prompt": "p", "busca": "b", "ini": 0.0, "fim": 4.0}
    # sem miniatura válida a cena não vai ao modelo: o teste não precisa de rede nem de modelo
    return midia._escolher_lote(projeto, [cena], {1: [candidato]}, {1: (pathlib.Path("f.jpg"), [])})


def test_cache_da_escolha_truncado_nao_derruba_o_lote(tmp_path, monkeypatch):
    assert _lote(tmp_path, monkeypatch, '{"assinatura": "abc", "escolhas": [0') == {}


def test_cache_da_escolha_sem_os_campos_esperados_nao_derruba_o_lote(tmp_path, monkeypatch):
    assert _lote(tmp_path, monkeypatch, '{"assinatura": "abc"}') == {}
    assert _lote(tmp_path, monkeypatch, '[1, 2, 3]') == {}


def test_gravar_cache_nao_deixa_temporario_e_usa_a_thread_no_nome(tmp_path):
    arquivo = tmp_path / "cena_0001.json"
    util.gravar_cache(arquivo, {"escolhas": [0, 2], "vejo": {"0": "ação"}}, indent=None)
    assert util.ler_cache(arquivo) == {"escolhas": [0, 2], "vejo": {"0": "ação"}}
    assert [p.name for p in tmp_path.iterdir()] == ["cena_0001.json"]
    assert util.ler_cache(tmp_path / "nao-existe.json") is None
    (tmp_path / "quebrado.json").write_text('{"a": ', encoding="utf-8")
    assert util.ler_cache(tmp_path / "quebrado.json") is None


def test_duas_threads_gravando_o_mesmo_cache_nao_se_pisam(tmp_path):
    arquivo = tmp_path / "cena_0001.json"
    erros = []

    def gravar(i):
        try:
            for _ in range(30):
                util.gravar_cache(arquivo, {"escolhas": [i] * 50}, indent=None)
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    threads = [threading.Thread(target=gravar, args=(i,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not erros
    assert util.ler_cache(arquivo)["escolhas"] in ([i] * 50 for i in range(4))
