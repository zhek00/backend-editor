"""Roteiro em japonês: sem espaços entre as palavras e com 。！？ no lugar de ponto seguido de espaço."""
import textwrap
from types import SimpleNamespace

import pytest

from fabrica import cenas, conferir_voz, genaipro, motion_ia, narracao, roteirista
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


# ---------------------------------------------------------------- o resto do caminho do vídeo

def test_linha_de_legenda_japonesa_conta_letra_larga():
    linhas = tx.quebrar_linhas(LONGA, 42)
    assert len(linhas) >= 2
    assert all(len(linha) <= 21 for linha in linhas)
    assert "".join(linhas) == LONGA


def test_linha_de_legenda_em_portugues_nao_muda():
    frase = "Uma frase bem comprida que passa do limite da linha de legenda e continua até o fim dela."
    assert tx.quebrar_linhas(frase, 42) == textwrap.wrap(frase, 42)


def test_arquivo_de_legendas_em_japones(tmp_path):
    unidades = narracao._tempos_das_frases(LONGA, [float(i) for i in range(len(LONGA))],
                                           [float(i + 1) for i in range(len(LONGA))], float(len(LONGA)))
    destino = tmp_path / "legendas.srt"
    narracao._legendas(unidades, destino, [float(i) for i in range(len(LONGA))],
                       [float(i + 1) for i in range(len(LONGA))], largura=38, linhas=1)
    falas = [b.split("\n")[2] for b in destino.read_text(encoding="utf-8").strip().split("\n\n")]
    assert all(len(f) <= 19 for f in falas)
    assert "".join(falas) == LONGA


def test_conferencia_entende_japones():
    bloco = ROTEIRO.replace("\n\n", "")
    assert conferir_voz.problemas(bloco, bloco) == {"semelhanca": 1.0, "problemas": []}


def test_conferencia_acha_trecho_comido_em_japones():
    bloco = "".join(f"これは{n}番目の話です。" for n in "一二三四五六七八")
    ouvido = bloco[:30] + bloco[-10:]
    assert any(p["tipo"] == "comeu" for p in conferir_voz.problemas(bloco, ouvido)["problemas"])


def test_conferencia_tolera_poucas_letras_diferentes_em_japones():
    bloco = "日本の製造業は大きな転換点を迎えています。トヨタは新しい電池の開発に成功しました。"
    ouvido = bloco.replace("転換点", "てんかんてん")
    assert conferir_voz.problemas(bloco, ouvido)["problemas"] == []


def test_conferencia_acusa_fala_em_outra_lingua():
    relatorio = conferir_voz.problemas(ROTEIRO, "isso aqui saiu em outra língua completamente diferente")
    assert [p["tipo"] for p in relatorio["problemas"]] == ["diferente"]


@pytest.mark.parametrize("voz, esperado", [({"idioma_da_voz": "ja"}, "ja"), ({"idioma": "es"}, "es"), ({}, "pt")])
def test_idioma_da_voz_vem_do_perfil(voz, esperado):
    assert conferir_voz.idioma_da_voz(voz) == esperado


@pytest.mark.parametrize("texto, fecha", [("終わりです。", True), ("本当ですか？", True), ("「終わりです。」", True),
                                          ("続きますが、", False), ("Acabou.", True), ('Ele disse "acabou."', True),
                                          ("Dr. Silva e", False)])
def test_fecha_frase(texto, fecha):
    assert tx.fecha_frase(texto) is fecha


def test_clipe_para_no_fim_da_frase_japonesa():
    cena = {"n": 1, "texto": "新しい技術です。", "bloco": 1, "ini": 0.0, "fim": 2.0}
    seguinte = {"n": 2, "texto": "次の話です。", "bloco": 1, "ini": 2.0, "fim": 4.0}
    assert motion_ia.frase_da_cena(SimpleNamespace(config={}, perfil={}), cena, {1: cena, 2: seguinte}) == [cena]


def test_cena_fecha_no_fim_da_frase_japonesa():
    assert "終わりです。".endswith(tx.FINAIS) and "「終わり」".endswith(tx.FINAIS)
    assert not "続きますが、".endswith(tx.FINAIS)


def test_mapa_do_roteiro_acha_a_frase_japonesa():
    comparavel, posicoes = roteirista._comparavel(ROTEIRO)
    frase = "トヨタは新しい電池の開発に成功しました！"
    assert roteirista._localizar(comparavel, posicoes, frase, 0)[1] == ROTEIRO.index("トヨタ")


def test_comparavel_em_portugues_nao_muda():
    assert roteirista._comparavel("Coração, de ouro!")[0] == "coracao de ouro "


def test_texto_na_tela_acha_a_fala_mesmo_sem_a_particula():
    palavras = [{"texto": m.group(), "ini": float(i)}
                for i, m in enumerate(tx.achar_palavras("東京の企業は新しい技術を開発した。"))]
    assert cenas._momento_falado("新しい技術", palavras, 0.0, 99.0) == 2.0
    assert cenas._momento_falado("電気自動車", palavras, 0.0, 99.0) == 99.0


def test_legenda_da_voz_em_frases_inteiras_alinha_o_japones():
    srt = ("1\n00:00:00,000 --> 00:00:03,000\n" "日本の製造業は、いま大きな転換点を迎えています。\n\n"
           "2\n00:00:03,000 --> 00:00:05,000\n" "トヨタは新しい電池の開発に成功しました！\n")
    fala = "日本の製造業は、いま大きな転換点を迎えています。トヨタは新しい電池の開発に成功しました！"
    alinhado = narracao._alinhar_pelas_palavras(fala, genaipro.ler_srt(srt), 5.0)
    segunda = fala.index("トヨタ")
    assert alinhado["inicio"][segunda] == pytest.approx(3.0)
    assert alinhado["fim"][-1] == pytest.approx(5.0)
