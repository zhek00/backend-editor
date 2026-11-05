"""Teto de tamanho das fotos baixadas (fabrica/midia._garantir_jpeg)."""
from PIL import Image

from fabrica import midia


def test_foto_gigante_e_reduzida(tmp_path):
    arquivo = tmp_path / "0001.jpg"
    Image.new("RGB", (midia.LADO_MAXIMO_DA_FOTO * 2, 400), "red").save(arquivo, "JPEG")
    midia._garantir_jpeg(arquivo)
    with Image.open(arquivo) as imagem:
        assert imagem.format == "JPEG"
        assert max(imagem.size) == midia.LADO_MAXIMO_DA_FOTO
        assert imagem.size == (midia.LADO_MAXIMO_DA_FOTO, 200)


def test_foto_dentro_do_teto_nao_e_tocada(tmp_path):
    arquivo = tmp_path / "0002.jpg"
    Image.new("RGB", (1920, 1080), "blue").save(arquivo, "JPEG")
    antes = arquivo.read_bytes()
    midia._garantir_jpeg(arquivo)
    assert arquivo.read_bytes() == antes


def test_png_vira_jpeg_e_cabe_no_teto(tmp_path):
    arquivo = tmp_path / "0003.jpg"
    Image.new("RGBA", (midia.LADO_MAXIMO_DA_FOTO + 1000, 500), (0, 255, 0, 255)).save(arquivo, "PNG")
    midia._garantir_jpeg(arquivo)
    with Image.open(arquivo) as imagem:
        assert imagem.format == "JPEG"
        assert max(imagem.size) == midia.LADO_MAXIMO_DA_FOTO
