"""Conferência da narração (fabrica/conferir_voz.py): os casos que a comparação precisa pegar e os que não pode."""
from fabrica import conferir_voz as c


def tipos(r):
    return [p["tipo"] for p in r["problemas"]]


def test_frase_trocada_pela_voz_e_pega():
    # virou-filme-em-1996, bloco 2: a voz da Fish trocou a frase inteira por outra sem sentido, e o vídeo saiu assim
    roteiro = ("Os leões pulavam as cercas ou simplesmente passavam por baixo delas. E aqui vem um detalhe que deixa a "
               "história ainda mais assustadora: os leões pareciam aprender. Quando Patterson montava guarda num "
               "acampamento, eles atacavam outro.")
    ouvido = ("Os leões pulavam as cercas ou simplesmente passavam por baixo delas. Mis trabalhadores reagiram como da "
              "farira. Quando Peterson montava guarda num acampamento, eles atacavam outro.")
    assert "comeu" in tipos(c.problemas(roteiro, ouvido))


def test_trecho_repetido_e_pego():
    roteiro = "É a primeira imagem que o mundo tem do agro brasileiro. Mas existe outro Brasil."
    ouvido = "É a primeira imagem que o mundo tem do agro brasileiro que o mundo tem do agro. Mas existe outro Brasil."
    assert tipos(c.problemas(roteiro, ouvido)) == ["repetiu"]


def test_numero_por_extenso_nao_conta():
    roteiro = "A história começa em 1875, quando os primeiros imigrantes chegam."
    ouvido = "A história começa em mil oitocentos e setenta e cinco, quando os primeiros imigrantes chegam."
    assert tipos(c.problemas(roteiro, ouvido)) == []


def test_frase_inventada_pelo_whisper_nao_conta():
    roteiro = "A terra é íngreme demais. Não dá para plantar soja em grande escala."
    ouvido = "A terra é íngreme demais. Não dá para plantar soja em grande escala. Legendas pela comunidade Amara.org"
    assert tipos(c.problemas(roteiro, ouvido)) == []


def test_pronuncia_pelo_glossario():
    glossario = {"Hubble": ("hubble|rabou", ["Hubble", "Rábou"])}
    roteiro = "O telescópio Hubble viu a nebulosa."
    assert tipos(c.problemas(roteiro, "O telescópio Rubel viu a nebulosa.", ["Hubble"], glossario)) == ["pronuncia"]
    assert tipos(c.problemas(roteiro, "O telescópio Hubble viu a nebulosa.", ["Hubble"], glossario)) == []
    assert c.com_grafias(roteiro, {"Hubble": 1}, glossario) == "O telescópio Rábou viu a nebulosa."


def test_termo_com_hifen_e_achado():
    assert c.termos_do_texto("O cavalo-de-Przewalski vive na Mongólia.", {"Przewalski": 1}) == ["Przewalski"]
