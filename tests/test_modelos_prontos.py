"""Os 30 layouts x 8 estilos do animation-ai (240 modelos prontos): o catálogo, a conferência dos 6 layouts novos, os tempos,
os sons e o determinismo do motor. Sem rede e sem custo; a gravação de verdade fica na verificação de
`verificar_modelos` (HyperFrames hyperframes check), que não roda aqui."""
import re

from fabrica import animation_ai as a

NOVOS = ("palavra_chave", "medidor", "grafico_linha", "deslizar", "revelacao", "pilha_cartoes")
ESTILOS_NOVOS = ("neon", "riso", "blueprint", "cinema")


def test_duzentos_e_quarenta_modelos():
    assert len(a.CATALOGO) == 30 and len(a.TEMAS) == 9  # 8 temas do motor de antes + o impacto
    assert len(a.CATALOGO) * len(a.TEMAS) >= 200
    assert set(a.CATALOGO) == set(a.EXEMPLOS)
    assert set(NOVOS) <= set(a.CATALOGO)


def test_todo_exemplo_passa_na_conferencia_e_nos_tempos():
    for tipo, exemplo in a.EXEMPLOS.items():
        fala = " ".join(a._textos(tipo, exemplo)) + " mil 85 ano"
        erros = [e for e in a.conferir(tipo, exemplo, fala) if "número que a fala não diz" not in e]
        assert erros == [], (tipo, erros)
        dados, sons = a.resolver_tempos(tipo, exemplo, [], 6.0)
        assert isinstance(sons, list) and len(sons) <= 8, tipo


def test_palavra_chave_e_uma_palavra_so():
    ok = {"termo": "TEMPO", "itens": [{"texto": "anos"}, {"texto": "paciência"}]}
    assert not [e for e in a.conferir("palavra_chave", ok, "tempo anos paciência") if "número" in e]
    erros = a.conferir("palavra_chave", {"termo": "uma frase comprida demais", "itens": ok["itens"]}, "tempo")
    assert any("UMA palavra" in e for e in erros)


def test_grafico_linha_pede_numeros_e_de_3_a_6_pontos():
    dois = {"itens": [{"rotulo": "a", "valor": 1}, {"rotulo": "b", "valor": 2}]}
    assert any("de 3 a 6" in e for e in a.conferir("grafico_linha", dois, "a b"))
    ruim = {"itens": [{"rotulo": "a", "valor": "muito"}, {"rotulo": "b", "valor": 2}, {"rotulo": "c", "valor": 3}]}
    assert any("é um número" in e for e in a.conferir("grafico_linha", ruim, "a b c muito"))


def test_medidor_a_fracao_vem_do_dito_e_nunca_inventa_escala():
    d, _ = a.resolver_tempos("medidor", {"valor": "85%", "legenda": "x"}, [], 6.0)
    assert d["fracao"] == 0.85 and d["contar"] is True
    d, _ = a.resolver_tempos("medidor", {"valor": "72 km/h", "legenda": "x", "maximo": 120}, [], 6.0)
    assert abs(d["fracao"] - 0.6) < 1e-9
    d, _ = a.resolver_tempos("medidor", {"valor": "72 km/h", "legenda": "x"}, [], 6.0)
    assert d["fracao"] == 0.72  # sem máximo dito, três quartos: "alto", sem escala inventada


def test_so_os_de_texto_sobre_fundo_ficam_para_as_cenas_pedidas():
    assert "palavra_chave" in a.SO_PEDIDAS and "revelacao" in a.SO_PEDIDAS
    for novo in ("medidor", "grafico_linha", "deslizar", "pilha_cartoes"):
        assert novo in a.DE_COMPLEMENTO
    assert "palavra_chave" in a.SIMPLES  # entra na conta de um terço dos trechos só de texto


def test_estilos_novos_trazem_fundo_entradas_camera_e_saida():
    for nome in ESTILOS_NOVOS:
        tema = a.TEMAS[nome]
        assert tema["_fundo"] in ("hud", "papel", "planta", "filme")
        assert tema["_entradas"] and tema["_cameras"] and tema["_saidas"]
        for chave in ("fundo", "acc", "acc2"):  # o canvas só entende #RRGGBB
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", tema[chave]), (nome, chave)
    for nome in ("apple", "noite", "editorial", "misterio"):
        assert not a.com_variante(a.TEMAS[nome]), nome  # os 4 de antes saem como saíam


def test_a_variante_so_muda_a_assinatura_dos_estilos_que_variam():
    d, _ = a.resolver_tempos("frase", {"texto": "x"}, [], 6.0)
    antigo = a.TEMAS["apple"]
    assert a.assinatura("frase", d, 6.0, antigo, "", 1) == a.assinatura("frase", d, 6.0, antigo, "", 2)
    novo = a.TEMAS["neon"]
    assert a.assinatura("frase", d, 6.0, novo, "", 1) != a.assinatura("frase", d, 6.0, novo, "", 2)


def test_a_pagina_leva_a_variante_para_o_motor():
    d, _ = a.resolver_tempos("medidor", a.EXEMPLOS["medidor"], [], 6.0)
    html = a.montar_html("medidor", d, 6.0, a.TEMAS["neon"], "Canal", 3)
    assert '"variante": 3' in html and '"fundo": "hud"' in html and '"entradas": ["scan", "glitch"]' in html


def test_o_motor_continua_funcao_pura_do_tempo():
    js = (a.RECURSOS / "motor.js").read_text(encoding="utf-8")
    sem_comentarios = re.sub(r"/\*.*?\*/|//[^\n]*", "", js, flags=re.S)
    for proibido in ("Math.random", "Date.now", "new Date", "performance.now", "requestAnimationFrame", "setTimeout",
                     "setInterval", ".animate("):
        assert proibido not in sem_comentarios, proibido
    css = (a.RECURSOS / "motor.css").read_text(encoding="utf-8")
    for proibido in ("@keyframes", "animation:", "transition:"):
        assert proibido not in css, proibido
