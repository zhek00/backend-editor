"""Cenas dirigidas (fabrica/direcao.py): a conferência da direção, os tempos pela fala, os ajustes em linguagem natural,
o determinismo do motor e a escolha do clipe em pé no render. Sem rede e sem custo; a gravação de verdade (Chrome
escondido) só roda com FABRICA_TESTES_LENTOS=1."""
import copy
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from fabrica import direcao, render

FALA = "Durante anos ninguém soube o que havia embaixo do gelo. Até que, em 1995, uma sonda desceu 400 metros."
PALAVRAS = [(w.strip(".,"), round(0.2 + i * 0.33, 3)) for i, w in enumerate(FALA.split())]


def spec_boa():
    return {
        "paleta": "misterio", "ritmo": "lento",
        "cenario": {"estilo": "particulas", "ciclos": 1, "seed": 7},
        "camera": [{"t": 0, "zoom": 1.0}, {"palavra": "sonda", "zoom": 1.1, "x": -2, "y": 1, "rot": -1.5},
                   {"t": 6.5, "zoom": 1.14, "x": 1, "rot": 0.5}],
        "camadas": [
            {"tipo": "forma", "forma": "circulo", "pos": "dir", "pos_v": "baixo", "morph": [{"para": "triangulo", "palavra": "sonda"}]},
            {"tipo": "texto", "texto": "Ninguém soube o *que havia* embaixo do gelo", "modo": "palavra",
             "entrada": "desfoca", "pos": "alto-esq", "pos_v": "alto", "tamanho": "g"},
            {"tipo": "numero", "valor": "400 metros", "legenda": "de profundidade", "palavra": "400", "pos": "baixo"},
        ],
    }


def test_direcao_boa_passa_na_conferencia():
    assert direcao.conferir(spec_boa(), FALA) == []


def test_camera_parada_e_recusada():
    um_ponto = spec_boa()
    um_ponto["camera"] = [{"t": 0, "zoom": 1.0}]
    assert any("a câmera nunca para" in e for e in direcao.conferir(um_ponto, FALA))
    igual = spec_boa()
    igual["camera"] = [{"t": 0, "zoom": 1.0}, {"t": 5, "zoom": 1.0}]
    assert any("parada" in e for e in direcao.conferir(igual, FALA))


def test_limites_do_diretor():
    s = spec_boa()
    s["camera"][1]["zoom"] = 3
    s["camadas"] = [{"tipo": "texto", "texto": "gelo"}] * 4 + [{"tipo": "card3d", "titulo": "a"},
                                                               {"tipo": "card3d", "titulo": "b"}]
    erros = " | ".join(direcao.conferir(s, FALA))
    assert "zoom" in erros and "no máximo 3 camadas de texto" in erros and "no máximo 1 card3d" in erros


def test_texto_inventado_numero_inventado_e_travessao():
    s = spec_boa()
    s["camadas"][1]["texto"] = "Os submarinos soviéticos já sabiam tudo sobre isso"
    assert any("palavras que a fala não diz" in e for e in direcao.conferir(s, FALA))
    s = spec_boa()
    s["camadas"][2]["valor"] = "900 metros"
    assert any("número que a fala não diz" in e for e in direcao.conferir(s, FALA))
    s = spec_boa()
    s["camadas"][1]["texto"] = "Ninguém soube — embaixo do gelo"
    assert any("travessão" in e for e in direcao.conferir(s, FALA))


def test_nao_repete_o_jeito_da_cena_anterior():
    s = spec_boa()
    assert any("mesmo jeito" in e for e in direcao.conferir(s, FALA, anterior=direcao.assinatura_visual(s)))


def test_paleta_personalizada_so_com_hex():
    s = spec_boa()
    s["paleta"] = {"acc": "vermelho"}
    assert any("paleta personalizada" in e for e in direcao.conferir(s, FALA))
    s["paleta"] = {"acc": "#112233"}
    assert direcao.conferir(s, FALA) == []
    assert direcao.cores_da_spec(s)["acc"] == "#112233"


def test_normalizar_prende_os_numeros_do_motor():
    s = direcao.normalizar({"camera": [{"t": 0, "zoom": 9, "x": 99, "rot": -50}, {"t": 2, "zoom": 0.1}], "camadas": [{"tipo": "nada"}]})
    assert s["camera"][0]["zoom"] == 1.7 and s["camera"][0]["x"] == 15 and s["camera"][0]["rot"] == -8
    assert s["camera"][1]["zoom"] == 0.85 and s["camadas"] == []


def test_tempos_pela_fala_em_sequencia():
    res, ev = direcao.resolver_tempos(direcao.normalizar(spec_boa()), PALAVRAS, 8.0)
    texto = next(c for c in res["camadas"] if c["tipo"] == "texto")
    assert texto["ts"] == sorted(texto["ts"]) and len(texto["ts"]) == 8
    # "ninguém" é a 3ª palavra da fala (0,2 + 2 x 0,33): a tipografia entra no ritmo da narração, um pouco antes dela
    assert abs(texto["ts"][0] - (PALAVRAS[2][1] - 0.1)) < 0.05
    forma = next(c for c in res["camadas"] if c["tipo"] == "forma")
    assert forma["morph"][0]["t"] > forma["t"]
    num = next(c for c in res["camadas"] if c["tipo"] == "numero")
    assert num["numero"] == 400 and num["contar"] is True and num["valor"] == "0"
    assert res["camera"][0]["t"] == 0 and res["camera"] == sorted(res["camera"], key=lambda k: k["t"])
    assert ev and all(nome in ("pop", "risco", "baque", "contagem") for _, nome in ev) and len(ev) <= 8


def test_a_tela_nunca_fica_so_com_o_fundo():
    s = direcao.normalizar(spec_boa())
    s["camadas"] = [c for c in s["camadas"] if c["tipo"] == "numero"]
    s["camadas"][0]["palavra"] = "metros"
    res, _ = direcao.resolver_tempos(s, PALAVRAS, 8.0)
    assert min(c["t"] for c in res["camadas"]) <= direcao.PRIMEIRO


def test_ajustes_simples_sem_modelo():
    s = direcao.normalizar(spec_boa())
    assert direcao.ajuste_rapido(s, "faz o final emendar no começo", None)[0]["loop"] is True
    devagar = direcao.ajuste_rapido(s, "desacelera um pouco", None)[0]
    assert devagar["ritmo"] == "lento" and devagar["camera"][-1]["zoom"] < s["camera"][-1]["zoom"]
    rapido = direcao.ajuste_rapido(s, "deixa mais rápido", None)[0]
    assert rapido["ritmo"] == "normal" and rapido["camera"][-1]["zoom"] > s["camera"][-1]["zoom"]
    suave = direcao.ajuste_rapido(s, "deixa a transição mais suave", None)[0]
    assert {k["ease"] for k in suave["camera"]} == {"suave"} and suave["transicao"]["saida"] == "fade"
    # pedido longo ou diferente vai ao modelo
    assert direcao.ajuste_rapido(s, "troca o texto principal por uma pergunta e põe o número em cima à direita", None) is None
    assert direcao.ajuste_rapido(s, "põe uma estrela no canto", None) is None
    # o ajuste conferido pelo mesmo diretor: nunca sai da regra
    assert direcao.conferir(suave, FALA) == []


def test_cores_do_tema():
    s = direcao.com_as_cores_do_tema(spec_boa(), {"fundo": "#F7F6F2", "acc": "#2563EB", "txt": "#1A1A1A", "mut": "x"})
    assert s["paleta"]["acc"] == "#2563EB" and s["paleta"]["fundo2"] == "#F7F6F2" and "mut" not in s["paleta"]


def test_reserva_sempre_passa_na_conferencia():
    for vez in range(4):
        assert direcao.conferir(direcao.direcao_de_reserva(FALA, vez), FALA) == []


def test_motor_e_funcao_pura_do_tempo():
    """Nada de relógio, sorteio sem semente ou animação em CSS no motor: o quadro X sai igual em toda gravação."""
    js = (direcao.RECURSOS / "direcao.js").read_text(encoding="utf-8")
    css = (direcao.RECURSOS / "direcao.css").read_text(encoding="utf-8")
    sem_comentarios = re.sub(r"/\*.*?\*/|//[^\n]*", "", js, flags=re.S)
    for proibido in ("Math.random", "Date.now", "new Date", "performance.now", "requestAnimationFrame", "setTimeout",
                     "setInterval", ".animate("):
        assert proibido not in sem_comentarios, proibido
    for proibido in ("@keyframes", "animation:", "transition:"):
        assert proibido not in css, proibido
    assert "mulberry" in js  # o sorteio que existe tem semente


def test_a_pagina_tem_o_tamanho_de_cada_formato():
    res, _ = direcao.resolver_tempos(direcao.normalizar(spec_boa()), PALAVRAS, 8.0)
    h = direcao.montar_html(res, 8.0, "horizontal", direcao.cores_da_spec(res))
    v = direcao.montar_html(res, 8.0, "vertical", direcao.cores_da_spec(res))
    assert 'data-width="1920" data-height="1080"' in h and "--W:1920px;--H:1080px" in h
    assert 'data-width="1080" data-height="1920"' in v and "--W:1080px;--H:1920px" in v


class _Projeto:
    def __init__(self, pasta):
        self.pasta = pasta

    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.png"


def test_render_em_pe_usa_o_clipe_em_pe_da_cena_dirigida(tmp_path):
    (tmp_path / "midia").mkdir()
    deitado = tmp_path / "midia" / "0003_anim.mp4"
    deitado.write_bytes(b"x")
    cena = {"n": 3, "midia": {"fonte": "animation_ai", "tipo": "video", "arquivo": "midia/0003_anim.mp4"}}
    projeto = _Projeto(tmp_path)
    assert render.origem_da_cena(projeto, cena, vertical=True) == ("video", deitado)  # sem o clipe em pé, o de sempre
    em_pe = tmp_path / "midia" / "0003_anim_vertical.mp4"
    em_pe.write_bytes(b"x")
    assert render.origem_da_cena(projeto, cena, vertical=True) == ("video", em_pe)
    assert render.origem_da_cena(projeto, cena, vertical=False) == ("video", deitado)
    outra = {"n": 4, "midia": {"fonte": "pexels", "tipo": "video", "arquivo": "midia/0003_anim.mp4"}}
    assert render.origem_da_cena(projeto, outra, vertical=True) == ("video", deitado)  # só a cena animada tem clipe em pé


@pytest.mark.skipif(os.environ.get("FABRICA_TESTES_LENTOS") != "1", reason="grava de verdade no Chrome escondido (uns 3 min)")
def test_gravar_duas_vezes_da_os_mesmos_quadros(tmp_path):
    from fabrica import animacoes

    class P:
        config = {}
        perfil = {}

    res, _ = direcao.resolver_tempos(direcao.normalizar(spec_boa()), PALAVRAS, 5.0)
    hashes = []
    for k in range(2):
        pasta = tmp_path / f"p{k}"
        pasta.mkdir()
        animacoes._preparar_pasta(pasta)
        (pasta / "index.html").write_text(direcao.montar_html(res, 5.0, "vertical", direcao.cores_da_spec(res)), encoding="utf-8")
        saida = pasta / "s.mp4"
        r = animacoes._hyperframes(P(), ["render", "--output", str(saida), "--format", "mp4", "--fps", "60", "--workers", "1",
                                         "--quiet"], pasta, 900)
        assert r.returncode == 0 and saida.exists()
        md5 = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(saida), "-f", "framemd5", "-"], capture_output=True, text=True).stdout
        hashes.append([l.split(",")[-1] for l in md5.splitlines() if not l.startswith("#")])
    assert hashes[0] == hashes[1] and len(hashes[0]) == 300


FALA_LEITE = ("Uma coisa sobre o leite neste país: os quatro litros mais baratos da prateleira e os quatro litros mais caros "
              "muitas vezes vieram das mesmas fazendas.")


def spec_do_primeiro_teste_real():
    """O que o diretor escreveu no leite: texto grande no centro e um quadrado embaixo. 'caros' saiu em cima do quadrado."""
    return {"camera": [{"t": 0, "zoom": 1.0}, {"palavra": "mesmas", "zoom": 1.08, "x": -2, "y": 1, "rot": -1.5}],
            "cenario": {"estilo": "particulas"}, "paleta": "misterio", "ritmo": "lento", "loop": True,
            "camadas": [{"tipo": "texto", "texto": "os *quatro* litros mais baratos e os *quatro* mais caros", "tamanho": "xl",
                         "pos": "centro", "entrada": "desfoca", "estilo": "serifa"},
                        {"tipo": "forma", "forma": "quadrado", "pos": "baixo", "tamanho_px": 180,
                         "morph": [{"para": "losango", "palavra": "mesmas"}]}]}


def test_texto_em_cima_da_forma_e_loop_sem_pedido_sao_recusados():
    erros = direcao.conferir(spec_do_primeiro_teste_real(), FALA_LEITE)
    assert any("loop" in e for e in erros)
    sem_loop = spec_do_primeiro_teste_real()
    sem_loop["loop"] = False
    erros = direcao.conferir(sem_loop, FALA_LEITE)
    assert any("bate na camada" in e for e in erros)
    # cada coisa no seu lugar: o texto em cima, a forma embaixo à direita
    sem_loop["camadas"][0].update({"pos": "alto", "tamanho": "g"})
    sem_loop["camadas"][1].update({"pos": "baixo-dir", "pos_v": "baixo"})
    assert direcao.conferir(sem_loop, FALA_LEITE) == []
    # o pedido de ajuste pode ligar o loop
    assert direcao.conferir(emendado := {**sem_loop, "loop": True}, FALA_LEITE, permite_loop=True) == []


def test_as_caixas_estimadas_cabem_na_tela_nos_dois_formatos():
    s = direcao.normalizar(spec_boa())
    for formato, (largura, altura) in direcao.FORMATOS.items():
        for c in s["camadas"]:
            x0, y0, x1, y1 = direcao.caixa_da_camada(c, formato)
            assert 0 <= y0 < y1 <= altura and x1 - x0 > 0
