"""animation-ai (fabrica/animation_ai.py): a conferência do plano do modelo, os trechos e os tempos pela fala."""
from fabrica import animation_ai as a


def test_tipo_inexistente_e_campos():
    assert a.conferir("grafico_pizza", {}, "fala")[0].startswith("o tipo")
    assert any("falta 'legenda'" in e for e in a.conferir("numero", {"valor": "150 milhões"}, "150 milhões de toneladas"))


def test_numero_que_a_fala_nao_diz_e_recusado():
    fala = "O Brasil produz mais de 150 milhões de toneladas de soja por ano."
    assert a.conferir("numero", {"valor": "150 milhões", "legenda": "de toneladas de soja"}, fala) == []
    erros = a.conferir("numero", {"valor": "200 milhões", "legenda": "de toneladas de soja"}, fala)
    assert any("número que a fala não diz" in e for e in erros)


def test_palavras_inventadas_sao_recusadas():
    fala = "Confira o selo, confira a validade e faça a conta do preço por litro."
    ok = {"titulo": "Antes de comprar", "itens": [{"texto": "Confira o selo"}, {"texto": "Confira a validade"}]}
    assert a.conferir("checklist", ok, fala, extras="comprar") == []
    inventado = {"itens": [{"texto": "Pesquise avaliações online"}, {"texto": "Compare supermercados vizinhos"}]}
    assert any("palavras que a fala não diz" in e for e in a.conferir("checklist", inventado, fala))


def test_frase_no_maximo_um_terco_do_video():
    # leite: o modelo pôs frase em 10 de 18 trechos, inclusive numa lista ("esquenta igual, engrossa igual...")
    fala = "Ele esquenta igual, engrossa igual e queima igual."
    plano = {"texto": "Esquenta igual, engrossa igual e *queima* igual"}
    assert a.conferir("frase", plano, fala, total=18, simples=2) == []
    assert any("um terço" in e for e in a.conferir("frase", plano, fala, total=18, simples=6))


def test_mesmo_tipo_tres_vezes_seguidas():
    fala = "Eles costumam ter o litro mais barato da loja."
    erros = a.conferir("frase", {"texto": "o litro mais *barato* da loja"}, fala, total=20, anteriores=("frase", "frase"))
    assert any("dois trechos anteriores" in e for e in erros)


def test_comparar_com_item_igual_ao_titulo():
    fala = "Aí é fama contra realidade."
    plano = {"esq": {"titulo": "Fama", "itens": [{"texto": "Fama"}]}, "dir": {"titulo": "Realidade", "itens": []}}
    assert any("repete o título" in e for e in a.conferir("comparar", plano, fala))


def test_abertura_so_no_comeco_e_encerramento_so_se_a_fala_pede():
    assert any("primeiro trecho" in e for e in a.conferir("abertura", {"titulo": "Leite"}, "leite", posicao=3, total=9))
    assert any("pede inscrição" in e for e in a.conferir("encerramento", {"texto": "leite barato"}, "leite barato"))
    assert a.conferir("encerramento", {"texto": "Se inscreva no canal"}, "Antes de começar, se inscreva no canal.") == []


def test_trechos_fecham_no_fim_da_frase_e_no_bloco():
    cenas = [{"n": 1, "ini": 0, "fim": 4, "bloco": 1, "texto": "Primeira parte"},
             {"n": 2, "ini": 4, "fim": 8.5, "bloco": 1, "texto": "termina aqui."},
             {"n": 3, "ini": 8.5, "fim": 12, "bloco": 1, "texto": "Outra frase."},
             {"n": 4, "ini": 12, "fim": 16, "bloco": 2, "texto": "Bloco novo."}]
    regras = {"duracao_alvo": 8, "duracao_maxima": 14, "duracao_minima": 3}
    assert [[c["n"] for c in g] for g in a.trechos(cenas, regras)] == [[1, 2], [3], [4]]
    # o resto curto do bloco (2 s) junta com o trecho anterior
    cenas[2]["fim"] = 10.5
    cenas[3]["ini"] = 10.5
    assert [[c["n"] for c in g] for g in a.trechos(cenas, regras)] == [[1, 2, 3], [4]]


def test_tempo_da_palavra_e_entrada_antes_dela():
    palavras = [("Confira", 0.4), ("o", 0.9), ("selo,", 1.0), ("confira", 1.6), ("a", 2.0), ("validade.", 2.2)]
    assert a.tempo_da_palavra("validade", palavras) == 2.2
    assert a.tempo_da_palavra("confira#2", palavras) == 1.6
    d, sons = a.resolver_tempos("checklist", {"titulo": "Antes", "itens": [{"texto": "selo", "palavra": "selo"},
                                                                         {"texto": "validade", "palavra": "validade"}]},
                                 palavras, 6.0)
    assert [it["t"] for it in d["itens"]] == [0.88, 2.08]
    assert sons and all(nome in a.NIVEL for _, nome in sons)


def test_tela_nunca_fica_vazia_esperando_a_palavra():
    # leite: o fato e o causa_efeito esperavam até 2,5 s e o começo do trecho saía só com o fundo
    palavras = [("mudam", 4.2)]
    d, _ = a.resolver_tempos("fato", {"texto": "Fórmulas *mudam*", "palavra": "mudam"}, palavras, 8.0)
    assert d["t"] <= a.PRIMEIRO
    d, _ = a.resolver_tempos("causa_efeito", {"itens": [{"texto": "x", "palavra": "mudam"}, {"texto": "y"}]}, palavras, 8.0)
    assert d["itens"][0]["t"] <= a.PRIMEIRO


def test_numero_conta_subindo_mas_ano_nao():
    assert a._partes_do_numero("R$ 2,5 bilhões") == ("R$ ", 2.5, 1, " bilhões", True)
    assert a._partes_do_numero("1875")[4] is False


# --------------------------------------------------------------------------------------------- complemento das fotos

def test_estrutura_so_manda_ao_modelo_o_que_tem_o_que_desenhar():
    est = lambda t, **k: a.estrutura([{"texto": t, **k}])
    assert est("Ele aparece nas marcas grandes, como Natrel, Lactantia, Neilson e Beatrice.") == "lista"
    assert est("Ele esquenta igual, engrossa igual e queima igual.") == "lista"  # repetição paralela, uma vírgula só
    assert est("Aí é fama contra realidade.") == "comparação"
    assert est("Chegaram em 1875 e a cooperativa veio em 1931.") == "datas"
    assert est("Eu sou Daniel e moro numa casa bonita.") == ""  # narração pura nem vai ao modelo
    assert est("Uma frase qualquer.", visual="linha_do_tempo").startswith("o agente pediu")


def test_complemento_nao_usa_os_tipos_de_texto_puro():
    assert "frase" not in a.DE_COMPLEMENTO and "abertura" not in a.DE_COMPLEMENTO
    assert len(a.DE_COMPLEMENTO) == 19


def test_frases_do_video_param_no_ponto_e_pulam_o_motion():
    cenas = [{"n": 1, "ini": 0, "fim": 2, "bloco": 1, "texto": "Confira o selo,"},
             {"n": 2, "ini": 2, "fim": 5, "bloco": 1, "texto": "a validade e o preço."},
             {"n": 3, "ini": 5, "fim": 9, "bloco": 1, "texto": "Um clipe de motion.", "midia": {"fonte": "motion_ia"}},
             {"n": 4, "ini": 9, "fim": 13, "bloco": 1, "texto": "Outra frase."}]
    grupos = a.frases_do_video(cenas, {"duracao_maxima": 12, "duracao_minima": 3})
    assert [[c["n"] for c in g] for g in grupos] == [[1, 2], [4]]


def test_cadencia_de_complemento():
    # leite: a lista de marcas começava colada num clipe do Motion IA, e o checklist do fim passava do orçamento
    itens = [{"id": 15, "ini": 43.0, "fim": 49.0, "dur": 6.0}, {"id": 39, "ini": 111.5, "fim": 118.2, "dur": 6.7},
             {"id": 48, "ini": 139.8, "fim": 150.0, "dur": 10.2}]
    decisoes = {15: {"nota": 80, "tipo": "lista"}, 39: {"nota": 85, "tipo": "checklist"},
                48: {"nota": 85, "tipo": "lista"}}
    cfg = {"limiar": 70, "intervalo_minimo": 20, "maximo_do_video": 0.12}
    motion = [(0.0, 5.0), (38.9, 43.0)]
    assert [it["id"] for it in a.escolher(itens, decisoes, cfg, 172.0, motion)] == [39]
    # vídeo longo: o orçamento cabe as três
    assert [it["id"] for it in a.escolher(itens, decisoes, cfg, 1200.0)] == [15, 39, 48]
    # nota abaixo do limiar nunca entra
    decisoes[48]["nota"] = 60
    assert 48 not in [it["id"] for it in a.escolher(itens, decisoes, cfg, 1200.0)]


def test_tema_apple_e_o_padrao_e_leva_o_jeito_de_mexer():
    from types import SimpleNamespace
    p = SimpleNamespace(config={}, perfil={})
    assert a.config(p)["tema"] == "apple"
    html = a.montar_html("frase", {"texto": "x", "t": 0.3}, 4.0, a.tema(p))
    assert "--fundo:#F7F6F2" in html and "--raio-card:20px" in html  # o creme e o card do Motion IA
    assert '"flutuar": true' in html and '"tremer": false' in html  # as opções vão para o motor, não para o CSS
    assert "--_flutuar" not in html
