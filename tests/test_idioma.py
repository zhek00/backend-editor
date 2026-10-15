from types import SimpleNamespace

from fabrica import idioma


def _projeto(tmp_path, roteiro):
    (tmp_path / "roteiro.txt").write_text(roteiro, encoding="utf-8")
    return SimpleNamespace(pasta=tmp_path)


def test_lingua_do_roteiro(tmp_path):
    en = _projeto(tmp_path, "Supermarkets across Britain have been selling you the same hot roast chicken for years, "
                            "and most of us have never once stopped to question it. I did. Here's what I found.")
    assert idioma.lingua(en) == "en" and idioma.locale(en) == "en-US" and "inglês" in idioma.regra_da_tela(en)
    assert idioma.lingua_do_texto("A capivara é o maior roedor do mundo e vive perto de rios com os filhotes") == "pt"
    assert idioma.lingua_do_texto("El tucán tiene un pico muy grande y vive en los bosques de la selva") == "es"
    assert idioma.lingua_do_texto("Ten supermarkets.") is None  # curto demais: por isso a língua vem do roteiro inteiro


def test_texto_de_tela_em_outra_lingua(tmp_path):
    # cena 8 do everything-you-need-to-answer, num vídeo para americanos
    fala = "Ten supermarkets. Three weeks. Dozens of chickens."
    assert idioma.outra_lingua(["10 SUPERMERCADOS", "3 SEMANAS", "DEZENAS DE FRANGOS"], "en", fala)
    assert not idioma.outra_lingua(["10 SUPERMARKETS", "3 WEEKS", "DOZENS OF CHICKENS"], "en", fala)
    assert idioma.outra_lingua(["O Teste"], "en") and idioma.outra_lingua(["Avaliação"], "en")
    # vídeo em português: texto em inglês na tela também é recusado; o português passa
    assert idioma.outra_lingua(["The best of the list"], "pt")
    assert not idioma.outra_lingua(["O melhor da lista"], "pt", "o melhor da lista é o frango")
