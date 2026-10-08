"""Os modelos de demonstração do Motion IA: cada dado com o seu desenho, e nada que a fala não diga.

Rode com: uv run --no-sync --with pytest python -m pytest tests
Sem rede e sem custo.
"""
import pytest

from fabrica import motion_ia, motion_modelos

FALA_50 = "Pode passar dos 50 quilômetros por hora e investe com"

EXEMPLOS = {
    "velocimetro": (FALA_50, {"topo": "pode passar dos", "valor": 50, "unidade": "km/h"}),
    "balanca": ("mais de uma tonelada e enxerga muito mal.", {"valor": 1, "unidade": "tonelada", "prefixo": "mais de"}),
    "regua": ("um chifre que chega a mais de um metro de comprimento.",
              {"topo": "um chifre", "destaque": "chifre", "valor": 1, "unidade": "metro", "forma": "cone"}),
    "contador": ("os dois teriam comido cerca de 35 pessoas.", {"valor": 35, "unidade": "pessoas", "forma": "pessoa"}),
    "porcentagem": ("80 por cento dos ataques acontecem à noite", {"valor": 80, "unidade": "dos ataques"}),
    "comparacao": ("um comeu 11 pessoas e o outro 24", {"itens": [{"rotulo": "um", "valor": 11},
                                                                 {"rotulo": "outro", "valor": 24}], "unidade": "pessoas"}),
    "tendencia": ("a caça ilegal levou a espécie à beira da extinção.", {"direcao": "desce", "fim": "extinção"}),
    "fluxo": ("a caça ilegal levou a espécie à beira da extinção.", {"etapas": ["caça ilegal", "beira da extinção"]}),
    "ranking": ("Em oitavo lugar está o rinoceronte-negro.", {"posicao": 8, "total": 8, "nome": "rinoceronte-negro"}),
    "frase": ("A ironia é que ele mesmo vive em perigo,", {"frase": "ele mesmo vive em perigo", "destaque": "perigo"}),
    "tipografia": ("O mico-leão-dourado pesa pouco mais de meio quilo.",
                   {"texto": "meio quilo", "prefixo": "pouco mais de", "tom": "leve"}),
}


@pytest.mark.parametrize("modelo", list(EXEMPLOS))
def test_cada_modelo_desenha_com_os_dados_da_fala(modelo):
    fala, dados = EXEMPLOS[modelo]
    d, erros = motion_modelos.conferir(modelo, dados, fala)
    assert erros == []
    partes = motion_modelos.partes(modelo, d, 3.4)
    assert partes["html"].strip() and "tl." in partes["js"]
    html = motion_ia.montar_html(partes, 3.4)
    assert "window.seekToFrame" in html


def test_os_clipes_nao_saem_mais_todos_iguais():
    # pedido do usuário em 2026-10-05: todos saíam com a foto num card e o número noutro
    desenhos = {motion_modelos.partes(m, motion_modelos.conferir(m, d, f)[0], 3.4)["html"][:400]
                for m, (f, d) in EXEMPLOS.items()}
    assert len(desenhos) == len(EXEMPLOS)


def test_numero_que_a_fala_nao_diz_volta():
    _, erros = motion_modelos.conferir("velocimetro", {"valor": 80, "unidade": "km/h"}, FALA_50)
    assert any("não é um número que a fala diz" in e for e in erros)


def test_palavra_inventada_volta():
    _, erros = motion_modelos.conferir("fluxo", {"etapas": ["caça ilegal", "desmatamento"]},
                                       "a caça ilegal levou a espécie à beira da extinção.")
    assert any("desmatamento" in e for e in erros)


def test_foto_dado_so_com_foto():
    _, erros = motion_modelos.conferir("foto_dado", {"valor": 50, "unidade": "km/h"}, FALA_50, tem_foto=False)
    assert erros and "foto" in erros[0]
    _, erros = motion_modelos.conferir("foto_dado", {"valor": 50, "unidade": "km/h"}, FALA_50, tem_foto=True)
    assert erros == []


def test_escala_redonda_acima_do_valor():
    assert motion_modelos.teto(50) == 80 and motion_modelos.teto(1) == 1.5 and motion_modelos.teto(35) == 50


def test_o_numero_da_vizinha_nao_vale_para_esta_cena():
    # cena 12 do natureza-teste-1min: o "50" da fala anterior fazia o "1 metro" do chifre ser recusado
    contexto = FALA_50 + " um chifre que chega a mais de um metro de comprimento."
    _, erros = motion_modelos.conferir("regua", {"valor": 1, "unidade": "metro"}, contexto,
                                       fala_da_cena="um chifre que chega a mais de um metro de comprimento.")
    assert erros == []


def test_prefixo_so_quantificador():
    d, _ = motion_modelos.conferir("velocimetro", {"valor": 50, "unidade": "km/h", "prefixo": "passar dos"}, FALA_50)
    assert "prefixo" not in d
    d, _ = motion_modelos.conferir("balanca", {"valor": 1, "unidade": "tonelada", "prefixo": "mais de"},
                                   "mais de uma tonelada")
    assert d["prefixo"] == "mais de"


def test_o_dado_indica_o_desenho():
    # cena 11 do natureza-teste-1min: o modelo escolheu a foto com o número no lugar do velocímetro
    assert motion_modelos.indicado("50 quilômetros por hora") == "velocimetro"
    assert motion_modelos.indicado("mais de uma tonelada") == "balanca"
    assert motion_modelos.indicado("mais de um metro") == "regua"
    assert motion_modelos.indicado("cerca de 35 pessoas") == "contador"
    _, erros = motion_modelos.conferir("foto_dado", {"valor": 50, "unidade": "km/h"}, FALA_50, tem_foto=True,
                                       sugerido="velocimetro")
    assert erros and "velocimetro" in erros[0]


# ------------------------------------------- PRD Motion AI 2.0 (2026-10-07): o sentido manda, não a unidade

MICO = "O mico-leão-dourado pesa pouco mais de meio quilo."


def test_peso_de_coisa_leve_nunca_vai_para_a_balanca():
    # "pesa pouco mais de meio quilo" achava "quilo" e o código obrigava a balança com o peso de ferro
    assert motion_ia.dado_na_fala(MICO) == "mais de meio quilo"
    assert motion_modelos.indicado("meio quilo", MICO) == "tipografia"
    assert motion_modelos.indicado("300 gramas", "o beija-flor pesa 300 gramas") == "tipografia"
    assert motion_modelos.indicado("3 quilos", "pesa 3 quilos") == "tipografia"
    assert motion_modelos.indicado("200 quilos", "um leão pode pesar 200 quilos") == "balanca"
    assert motion_modelos.indicado("mais de uma tonelada", "mais de uma tonelada e enxerga muito mal.") == "balanca"


def test_desenho_proibido_pela_direcao_volta():
    _, erros = motion_modelos.conferir("balanca", {"valor": 1, "unidade": "quilo"}, MICO,
                                       sugerido="tipografia", proibidos=("balanca",))
    assert erros and "proibiu" in erros[0] and "tipografia" in erros[0]


def test_frase_vale_quando_a_direcao_indica_frase():
    fala, dados = EXEMPLOS["frase"]
    _, erros = motion_modelos.conferir("frase", dados, fala, sugerido="frase")
    assert erros == []


def test_tipografia_so_com_palavras_e_numeros_da_fala():
    _, erros = motion_modelos.conferir("tipografia", {"texto": "levíssimo"}, MICO)
    assert any("levissimo" in e for e in erros)
    _, erros = motion_modelos.conferir("tipografia", {"texto": "600 gramas"}, MICO)
    assert erros
    d, erros = motion_modelos.conferir("tipografia", {"texto": "meio quilo", "tom": "flutuante"}, MICO)
    assert erros == [] and d["tom"] == "neutro"


def test_o_tom_muda_o_movimento_da_tipografia():
    d = motion_modelos.conferir("tipografia", {"texto": "meio quilo"}, MICO)[0]
    leve = motion_modelos.tipografia({**d, "tom": "leve"}, 3.4)["js"]
    pesado = motion_modelos.tipografia({**d, "tom": "pesado"}, 3.4)["js"]
    assert "power4.in" in pesado and "power4.in" not in leve
    assert "sine.inOut" in leve  # flutua depois de pousar
    assert "back.out" not in leve  # nada de mola para coisa leve


def test_peso_com_a_foto_do_bicho_vira_a_colagem_na_balanca():
    # pedido do usuário em 2026-10-07: "ele em cima de uma balança mostrando 0,5 kg, estilo colagem Vox"
    assert motion_modelos.indicado("mais de meio quilo", MICO, tem_foto=True) == "colagem_balanca"
    assert motion_modelos.indicado("mais de meio quilo", MICO, tem_foto=False) == "tipografia"
    _, erros = motion_modelos.conferir("colagem_balanca", {"valor": 0.5, "unidade": "kg"}, MICO, tem_foto=False)
    assert erros and "foto" in erros[0]
    d, erros = motion_modelos.conferir("colagem_balanca", {"valor": 0.5, "unidade": "kg", "prefixo": "pouco mais de",
                                                           "tom": "leve"}, MICO, tem_foto=True)
    assert erros == [] and d["prefixo"] == "pouco mais de"
    partes = motion_modelos.partes("colagem_balanca", d, 3.6, "recorte.png")
    assert 'url("assets/recorte.png")' in partes["html"] + partes["css"] and "bounce" not in partes["js"]
    pesado = motion_modelos.partes("colagem_balanca", {**d, "valor": 100, "tom": "pesado"}, 3.6, "recorte.png")
    assert "bounce.out" in pesado["js"]
    moldura = motion_modelos.partes("colagem_balanca", {**d, "moldura": True}, 3.6, "foto.jpg")
    assert "clip-path" in moldura["css"] and "cover" in moldura["css"]
