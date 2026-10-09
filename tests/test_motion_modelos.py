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


# ---------------- a medida em caderno de campo (o clipe 1 da ariranha, escolhido pelo usuário em 2026-10-08)

ARIRANHA = "chegar a quase dois metros de comprimento, contando a a cauda achatada que funciona como leme."


def test_comprimento_com_foto_do_bicho_vira_a_medida_em_colagem():
    assert motion_modelos.indicado("dois metros", ARIRANHA, tem_foto=True) == "medida_colagem"
    assert motion_modelos.indicado("dois metros", ARIRANHA, tem_foto=False) == "regua"
    dados = {"valor": 2, "unidade": "metros", "prefixo": "quase", "parte": "cauda achatada",
             "funcao": "funciona como leme", "palavra_valor": "dois", "palavra_parte": "cauda", "palavra_funcao": "leme"}
    # sem foto da cena, vale a figura própria dos bancos (motion_figura); sem nenhuma das duas, não
    _, erros = motion_modelos.conferir("medida_colagem", dados, ARIRANHA, tem_foto=False, figura=True)
    assert erros == []
    _, erros = motion_modelos.conferir("medida_colagem", dados, ARIRANHA, tem_foto=False, figura=False)
    assert erros and "foto" in erros[0]
    _, erros = motion_modelos.conferir("foto_dado", {"valor": 2, "unidade": "metros"}, ARIRANHA, figura=True)
    assert erros  # o foto_dado precisa da foto da própria cena
    _, erros = motion_modelos.conferir("medida_colagem", {**dados, "funcao": "serve de remo"}, ARIRANHA, figura=True)
    assert any("remo" in e for e in erros)


def test_medida_desenha_a_fita_a_parte_e_o_leme_no_tempo_das_palavras():
    d, _ = motion_modelos.conferir("medida_colagem", {"valor": 2, "unidade": "metros", "prefixo": "quase",
                                                      "parte": "cauda achatada", "funcao": "funciona como leme"},
                                   ARIRANHA, figura=True)
    d.update(fig=(1026, 396), ext=(0.03, 0.97), parte_caixa=[0.0, 0.45, 0.26, 1.0],
             tempos={"valor": 0.67, "parte": 2.91, "funcao": 4.69})
    partes = motion_modelos.partes("medida_colagem", d, 5.88, "figura.png")
    html = partes["html"]
    assert 'url("assets/figura.png")' in partes["css"] and "2 m" in html and "quase" in html
    assert "cauda achatada" in html and "funciona como leme" in html and "m-icone" in html  # o leme tem ícone
    assert "2.91" in partes["js"] and "0.67" in partes["js"]
    sem_parte = motion_modelos.partes("medida_colagem", {**d, "parte": "", "parte_caixa": None}, 3.0, "figura.png")
    assert "m-rotulo" not in sem_parte["html"]


def test_marcas_da_fita_pela_unidade():
    assert motion_modelos._passo(2.12) == 0.5 and motion_modelos._passo(32) == 10
    assert motion_modelos._abreviacao("centímetros") == "cm" and motion_modelos._abreviacao("metros") == "m"


# ------------------------------------------- a contagem em caderno de campo (cena 21 do 11-animais-do-brasil)

MICOS = "Restavam apenas cerca de duzentos micos na natureza."


def test_contagem_de_bichos_com_foto_vira_a_grade_de_silhuetas():
    assert motion_modelos.indicado("duzentos micos", MICOS, tem_foto=True) == ""  # "micos" não é unidade conhecida
    assert motion_modelos.indicado("cerca de 35 animais", "cerca de 35 animais", tem_foto=True) == "contagem_colagem"
    assert motion_modelos.indicado("135 pessoas", "135 pessoas", tem_foto=True) == "contador"  # gente nunca
    d, erros = motion_modelos.conferir("contagem_colagem", {"valor": 200, "unidade": "micos", "prefixo": "cerca de",
                                                            "palavra_valor": "duzentos"}, MICOS, figura=True)
    assert erros == []
    d.update(fig=(900, 700), tempos={"valor": 1.2})
    partes = motion_modelos.partes("contagem_colagem", d, 4.3, "figura.png")
    assert partes["html"].count('class="m-ic"') == 40  # 200 micos: 40 miniaturas de 5
    assert "cada um = 5 micos" in partes["html"]
    moldura = motion_modelos.partes("contagem_colagem", {**d, "moldura": True}, 4.3, "figura_foto.jpg")
    assert "border-radius:50%" in moldura["css"] and "clip-path" in moldura["css"]


def test_quantificador_no_lugar_do_numero_vai_para_o_prefixo():
    # o modelo pôs "cerca de" no rótulo do número, e o clipe mostrou "cerca de micos" sem o 200
    d, _ = motion_modelos.conferir("contagem_colagem", {"valor": 200, "unidade": "micos", "rotulo_valor": "cerca de"},
                                   MICOS, figura=True)
    assert "rotulo_valor" not in d and d["prefixo"] == "cerca de"
    d, _ = motion_modelos.conferir("contagem_colagem", {"valor": 1000, "unidade": "indivíduos",
                                                        "rotulo_valor": "milhares"},
                                   "existam alguns milhares de indivíduos", figura=True)
    assert d["rotulo_valor"] == "milhares"


def test_kg_e_reconhecido_como_peso():
    # o padrão tinha um caractere de controle no lugar do limite de palavra: "kg" nunca casava
    assert motion_modelos.indicado("200 kg", "pesa 200 kg") == "balanca"


def test_medida_leva_o_segundo_dado_da_frase_sem_outra_balanca():
    fala = "Pode passar de dois metros e meio e pesar mais de cem quilos."
    base = {"valor": 2.5, "unidade": "metros", "prefixo": "mais de", "valor2": 100, "unidade2": "quilos",
            "prefixo2": "mais de", "palavra_valor2": "cem"}
    d, erros = motion_modelos.conferir("medida_colagem", base, fala, figura=True)
    assert erros == [] and d["valor2"] == 100
    d.update(fig=(1200, 340), ext=(0.02, 0.98), tempos={"valor": 0.5, "valor2": 2.6})
    partes = motion_modelos.partes("medida_colagem", d, 3.4, "figura.png")
    assert "mais de 100 quilos" in partes["html"] and "2.6" in partes["js"]
    d, _ = motion_modelos.conferir("medida_colagem", {**base, "unidade2": ""}, fala, figura=True)
    assert "valor2" not in d  # sem o que mede, o segundo dado sai


def test_dois_dados_do_mesmo_bicho_viram_a_ficha():
    # o pirarucu da cena 257: virava a terceira balança do vídeo, ou a régua sem o peso
    fala = "Pode passar de dois metros e meio e pesar mais de cem quilos."
    dado = motion_ia.dado_na_fala(fala)
    assert motion_modelos.indicado(dado, fala, tem_foto=True) == "ficha_colagem"
    itens = [{"valor": 2.5, "unidade": "metros", "prefixo": "mais de", "palavra": "dois"},
             {"valor": 100, "unidade": "quilos", "prefixo": "mais de", "palavra": "cem"}]
    d, erros = motion_modelos.conferir("ficha_colagem", {"itens": itens}, fala, figura=True)
    assert erros == [] and len(d["itens"]) == 2
    d.update(fig=(4, 3), moldura=True, tempos={"item0": 0.4, "item1": 2.6})
    partes = motion_modelos.partes("ficha_colagem", d, 3.4, "figura_foto.jpg")
    assert "metros" in partes["html"] and "quilos" in partes["html"] and "2.40" in partes["js"]  # adiantado: conta antes do corte
    _, erros = motion_modelos.conferir("ficha_colagem", {"itens": itens[:1]}, fala, figura=True)
    assert erros  # um dado só não é ficha


def test_desenhos_de_narracao_sem_numero_nem_foto():
    from fabrica import motion_modelos as mm
    fala = "Em 1875 os primeiros imigrantes italianos chegam. Produzir menos, mas muito melhor, e esperar mais."
    d, erros = mm.conferir("marco", {"marco": "1875", "texto": "os primeiros imigrantes italianos chegam"}, fala)
    assert not erros and "1875" in mm.partes("marco", d, 5.0)["html"]
    d, erros = mm.conferir("marco", {"marco": "1999", "texto": "os primeiros imigrantes"}, fala)
    assert any("número" in e for e in erros)
    d, erros = mm.conferir("topicos", {"etapas": ["produzir menos", "muito melhor"]}, fala)
    assert not erros and mm.partes("topicos", d, 5.0)["js"].count("m-ponto-") == 2
    d, erros = mm.conferir("topicos", {"etapas": ["produzir menos"]}, fala)
    assert erros
    d, erros = mm.conferir("contraste", {"itens": [{"rotulo": "menos", "texto": "produzir menos"},
                                                    {"rotulo": "mais", "texto": "esperar mais"}]}, fala)
    assert not erros and "m-lado-1" in mm.partes("contraste", d, 5.0)["html"]
    d, erros = mm.conferir("contraste", {"itens": [{"rotulo": "menos", "texto": "produzir menos"}]}, fala)
    assert erros
