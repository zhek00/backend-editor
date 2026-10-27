"""Montagem final em pedaços (render._mixar_em_pedacos): as emendas não podem perder nem ganhar quadro."""
from fabrica import render


def test_pedacos_cobrem_o_video_em_quadros_inteiros():
    for duracao in (40.0, 59.402449, 1206.7, 61.3):
        pedacos = render.pedacos_da_montagem(duracao, 30, 6)
        assert pedacos[0][0] == 0
        assert sum(q for _, q in pedacos) == round(duracao * 30)
        for (p, q), (seguinte, _) in zip(pedacos, pedacos[1:]):
            assert p + q == seguinte  # nenhum quadro repetido ou perdido na emenda


def test_pedaco_nunca_fica_curto_demais():
    assert len(render.pedacos_da_montagem(59.4, 30, 6)) == 2
    assert all(q / 30 >= render.PEDACO_MINIMO for _, q in render.pedacos_da_montagem(1206.7, 30, 6))


def test_grafo_do_pedaco_sem_startpts_depois_do_corte():
    # no FFmpeg 8 o STARTPTS depois de um -ss na entrada contava a partir dos quadros de antes do corte: o segundo
    # pedaço do teste-animacao-1min saiu com 357 quadros em vez de 891
    _, filtro = render.grafo_do_pedaco(29.7, 59.4, [], "subtitles=x.srt")
    assert filtro.startswith("[0:v]null[base]")
    assert "setpts=PTS+29.700000/TB,subtitles=x.srt,setpts=PTS-29.700000/TB[saida]" in filtro


def test_animacao_que_comecou_antes_entra_andada():
    entradas, filtro = render.grafo_do_pedaco(20, 40, [(10, 25, "a.mov"), (30, 50, "b.mov"), (45, 50, "c.mov")], None)
    assert entradas == ["-ss", "10.000000", "-i", "a.mov", "-i", "b.mov"]  # c.mov fica fora do pedaço
    assert "[1:v]setpts=PTS,format=yuva420p[m0]" in filtro
    assert "enable='between(t,0.000,5.000)'" in filtro
    assert "[2:v]setpts=PTS-STARTPTS+10.000000/TB" in filtro


def test_legenda_tirada_do_grafo():
    partes = ["[0:v]overlay[cm0]", "[cm0]subtitles=filename='a.srt':force_style='X'[com_legenda]"]
    assert render.legenda_do_grafo(partes) == "subtitles=filename='a.srt':force_style='X'"
    assert render.legenda_do_grafo(["[0:v]overlay[cm0]"]) is None


def test_mesma_foto_baixada_ao_mesmo_tempo_por_duas_cenas(tmp_path):
    # a conferência pelo cenas.json só via as cenas já gravadas: duas cenas baixando a mesma foto juntas passavam
    from types import SimpleNamespace

    from fabrica import midia

    projeto = SimpleNamespace(pasta=tmp_path)
    midia._reservar(projeto, 4, None, "pexels:123")
    assert midia._reservada_por_outra(projeto, 7, None, "pexels:123") == 4
    assert midia._reservada_por_outra(projeto, 4, None, "pexels:123") is None  # a própria cena
    assert midia._reservada_por_outra(projeto, 7, None, "pexels:999") is None
    midia._reservar(projeto, 4, None, "pexels:999")  # a cena 4 trocou de foto: a antiga fica livre
    assert midia._reservada_por_outra(projeto, 7, None, "pexels:123") is None
    outro = SimpleNamespace(pasta=tmp_path / "outro")
    assert midia._reservada_por_outra(outro, 7, None, "pexels:999") is None  # outro projeto não conta
