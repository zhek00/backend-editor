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


def test_japones_e_coreano_saem_pelo_alfabeto():
    from fabrica import idioma as _idioma
    assert _idioma.lingua_do_texto("皆さんは、銅がいつか別の素材に置き換わると思いますか。") == "ja"
    assert _idioma.lingua_do_texto("한국의 기술이 세계를 또 한 번 놀라게 했습니다.") == "ko"
    assert _idioma.lingua_do_texto("O que é isso para quem mora no Brasil") == "pt"
    assert "japonês" in _idioma.nome("ja")


def _projeto_em(tmp_path, texto):
    (tmp_path / "roteiro.txt").write_text(texto, encoding="utf-8")
    return type("P", (), {"pasta": tmp_path})()


def test_o_filtro_de_alfabeto_nao_apaga_o_japones_do_video_japones(tmp_path):
    from fabrica import openrouter_local as o
    projeto = _projeto_em(tmp_path, "皆さんは、銅がいつか別の素材に置き換わると思いますか。" * 5)
    resposta = {"titulo": "銅の未来を変える日本の技術", "tags": ["銅", "カーボンナノチューブ"]}
    assert o._sem_outro_alfabeto(resposta, projeto) == resposta
    assert o._trechos_de_outro_alfabeto(resposta, projeto) == []
    assert "nunca em português" in o.regra_do_idioma(projeto)
    assert "Nunca escreva em chinês" not in o.regra_do_idioma(projeto)


def test_o_filtro_continua_limpando_o_video_em_portugues(tmp_path):
    from fabrica import openrouter_local as o
    projeto = _projeto_em(tmp_path, "O que é isso para quem mora no Brasil e como isso muda tudo.")
    assert o._sem_outro_alfabeto("uma composição清楚的 boa", projeto) == "uma composição boa"
    assert o._sem_outro_alfabeto("uma composição清楚的 boa") == "uma composição boa"


def test_a_fonte_do_japones_tem_as_letras():
    from PIL import ImageFont
    from fabrica import idioma as _idioma
    caminho = _idioma.fonte_do_texto("銅の未来")
    assert caminho and ImageFont.truetype(caminho, 40).getlength("銅の未来") > 100
    assert _idioma.fonte_do_texto("Copper") == ""


def test_a_descricao_japonesa_nao_leva_texto_fixo_em_portugues():
    from fabrica import publicacao
    texto = publicacao.descricao({"resumo": "皆さんは、銅がいつか別の素材に置き換わると思いますか。", "nomes_capitulos": ["銅の真実"]},
                                 [{"inicio": 0}], creditos="")
    assert "チャプター" in texto and "合成音声" in texto
    assert "Capítulos" not in texto and "voz sintética" not in texto


def test_o_destaque_do_short_japones_nao_mostra_o_asterisco(tmp_path):
    from PIL import Image
    from fabrica import shorts
    com, sem = tmp_path / "com.png", tmp_path / "sem.png"
    shorts._titulo_png("銅は*消えない*", com)
    shorts._titulo_png("銅は消えない", sem)
    assert Image.open(com).size == Image.open(sem).size
    assert Image.open(com).tobytes() != Image.open(sem).tobytes()
