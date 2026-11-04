"""Roteiro em japonês: sem espaços entre as palavras e com 。！？ no lugar de ponto seguido de espaço."""
import pytest

from fabrica import cenas, narracao
from fabrica import texto as tx

ROTEIRO = (
    "日本の製造業は、いま大きな転換点を迎えています。トヨタは新しい電池の開発に成功しました！"
    "では、なぜ世界はこの技術に注目するのでしょうか？\n\n"
    "専門家は「これは革命です。」と語りました。生産性は3.5倍になりました。"
)
LONGA = (
    "東京大学の研究チームは、従来の半導体よりも消費電力が少なく、製造費用も大幅に抑えられる新しい素材を開発し、"
    "国内の複数の企業と協力しながら、数年以内に工場での本格的な生産を始める計画を発表しました。"
)


def textos(trechos):
    return [t.texto for t in trechos]


def test_frases_terminam_em_pontuacao_japonesa_sem_espaco():
    assert textos(tx.frases(ROTEIRO)) == [
        "日本の製造業は、いま大きな転換点を迎えています。",
        "トヨタは新しい電池の開発に成功しました！",
        "では、なぜ世界はこの技術に注目するのでしょうか？",
        "専門家は「これは革命です。」と語りました。",
        "生産性は3.5倍になりました。",
    ]


def test_citacao_seguida_de_to_continua_a_mesma_frase():
    assert textos(tx.frases("「すごい！」と彼は言った。")) == ["「すごい！」と彼は言った。"]
    assert textos(tx.frases("本当に？と聞いた。")) == ["本当に？と聞いた。"]


def test_citacao_que_fecha_a_frase_fica_com_ela():
    assert textos(tx.frases("彼は「終わりです。」次の話です。")) == ["彼は「終わりです。」", "次の話です。"]


def test_pontuacao_repetida_nao_vira_frase_sozinha():
    assert textos(tx.frases("本当ですか！？はい。")) == ["本当ですか！？", "はい。"]


def test_posicoes_das_frases_batem_com_o_roteiro():
    for t in tx.frases(ROTEIRO):
        assert ROTEIRO[t.ini:t.fim] == t.texto


def test_frase_longa_vira_trechos_curtos_sem_perder_nada():
    partes = tx.unidades(LONGA)
    assert len(partes) >= 2
    assert all(len(p.texto) <= 60 for p in partes)
    assert "".join(textos(partes)) == LONGA
    for p in partes:
        assert LONGA[p.ini:p.fim] == p.texto


def test_corte_prefere_a_virgula_japonesa():
    assert sum(p.texto.endswith("、") for p in tx.unidades(LONGA)) >= 1


def test_corte_nao_parte_palavra_de_kanji():
    emendas = [a.texto[-2:] + b.texto[:2] for a, b in zip(tx.unidades(LONGA), tx.unidades(LONGA)[1:])]
    for palavra in ("東京大学", "半導体", "消費電力", "製造費用", "本格的", "工場"):
        assert not any(palavra in e and not e.startswith(palavra) and not e.endswith(palavra) for e in emendas)


def test_frase_curta_fica_inteira():
    assert textos(tx.unidades("新しい技術です。")) == ["新しい技術です。"]


def test_palavras_japonesas_seguem_a_fronteira_da_escrita():
    assert [m.group() for m in tx.achar_palavras("東京の企業は、新しい技術を開発した。")] == [
        "東京の", "企業は、", "新しい", "技術を", "開発した。"]


def test_palavras_cobrem_o_texto_japones_inteiro():
    assert "".join(m.group() for m in tx.achar_palavras(LONGA)) == LONGA


@pytest.mark.parametrize("texto", ["Isto é um teste, com vírgula.  E outra frase!", "It's 3.5 times bigger, really."])
def test_palavras_em_portugues_e_ingles_continuam_por_espaco(texto):
    assert [m.group() for m in tx.achar_palavras(texto)] == texto.split()


def test_portugues_com_um_nome_japones_nao_encurta_o_limite():
    frase = "O nome 東京 aparece no meio de uma frase com só catorze palavras aqui."
    assert len(frase.split()) == 14
    assert textos(tx.unidades(frase)) == [frase]


def test_portugues_e_ingles_nao_mudam():
    pt = ("A inteligência artificial mudou tudo. Em 2024, o mercado cresceu 3.5 vezes! Mas por quê? "
          "Ele disse: \"Acabou.\" E saiu…\n\nUma frase bem comprida que passa do limite de palavras permitido, "
          "porque tem uma vírgula perto do meio e continua falando sem parar até o final dela.")
    assert textos(tx.frases(pt)) == [
        "A inteligência artificial mudou tudo.", "Em 2024, o mercado cresceu 3.5 vezes!", "Mas por quê?",
        "Ele disse: \"Acabou.\"", "E saiu…",
        "Uma frase bem comprida que passa do limite de palavras permitido, porque tem uma vírgula perto do meio "
        "e continua falando sem parar até o final dela.",
    ]
    assert textos(tx.unidades(pt))[-2:] == [
        "Uma frase bem comprida que passa do limite de palavras permitido,",
        "porque tem uma vírgula perto do meio e continua falando sem parar até o final dela.",
    ]
    en = "Dr. Smith paid $3.50 today. Why? Because it works, and that is all."
    assert textos(tx.frases(en)) == ["Dr.", "Smith paid $3.50 today.", "Why?", "Because it works, and that is all."]


def test_blocos_de_narracao_quebram_entre_frases_japonesas():
    roteiro = "".join(f"これは{n}番目の文章です。" for n in range(40))
    blocos = tx.blocos(roteiro, 100)
    assert len(blocos) > 3
    assert all(len(b.texto) <= 100 and b.texto.endswith("。") for b in blocos)


def test_tempos_das_frases_em_japones():
    n = len(ROTEIRO)
    ini = [float(i) for i in range(n)]
    fim = [float(i + 1) for i in range(n)]
    unidades = narracao._tempos_das_frases(ROTEIRO, ini, fim, float(n))
    assert len(unidades) == 5
    assert unidades[1]["texto"] == "トヨタは新しい電池の開発に成功しました！"
    assert unidades[1]["ini"] == ROTEIRO.index("トヨタ")
    assert unidades[1]["fim"] == ROTEIRO.index("トヨタ") + len(unidades[1]["texto"])


def test_tempos_sem_transcricao_param_nas_pausas_do_japones(monkeypatch):
    monkeypatch.setattr(narracao, "_pausas_da_voz", lambda wav: [(0.0, 0.1), (5.0, 5.4), (8.0, 8.1)])
    achadas = narracao._palavras_estimadas("東京の企業は新しい技術を開発しました。次の話題に移ります。", 8.0, "x.wav")
    tempos = dict((p, (a, b)) for p, a, b in achadas)
    assert tempos["開発しました。"][1] == pytest.approx(5.0)
    assert tempos["次の"][0] == pytest.approx(5.4)


def test_simplificar_guarda_o_japones_e_nao_muda_o_portugues():
    assert cenas._simplificar("技術を、") == "技術を"
    assert cenas._simplificar("Coração,") == "coracao"


def test_texto_na_tela_acha_o_momento_falado_em_japones():
    palavras = [{"texto": m.group(), "ini": float(i)}
                for i, m in enumerate(tx.achar_palavras("東京の企業は新しい技術を開発した。"))]
    assert cenas._momento_falado("新しい技術を", palavras, 0.0, 99.0) == 2.0


def test_inicio_da_cena_e_achado_na_fala_em_japones():
    fala = "東京の企業は新しい技術を開発した。次の話題に移ります。"
    palavras = [{"texto": m.group(), "ini": float(i)} for i, m in enumerate(tx.achar_palavras(fala))]
    assert cenas._inicios_pela_fala([{"n": 2, "texto": "次の話題に移ります。"}], palavras) == {2: 5.0}


def test_texto_da_fatia_junta_o_japones_sem_espaco():
    palavras = [{"texto": "新しい", "ini": 0.0}, {"texto": "技術を", "ini": 1.0}]
    assert cenas._extrair_texto_palavras(palavras, 0.0, 5.0) == "新しい技術を"
    palavras = [{"texto": "nova", "ini": 0.0}, {"texto": "técnica", "ini": 1.0}]
    assert cenas._extrair_texto_palavras(palavras, 0.0, 5.0) == "nova técnica"
