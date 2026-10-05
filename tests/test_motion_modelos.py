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
