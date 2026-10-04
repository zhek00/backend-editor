"""Os filtros da captura, com os casos reais que já deram errado em vídeos de verdade.

Rode com: uv run --no-sync --with pytest python -m pytest tests
Sem rede e sem custo: nenhum banco de imagens nem modelo é chamado.
"""
from fabrica import cenas as cenas_mod
from fabrica import midia, roteirista

F = lambda descricao: {"descricao": descricao}

# cenas do virou-filme-em-1996 (os leões de Tsavo, 1898), como o agente as escreveu
ACAMPAMENTO = {"n": 3, "tipo": "foto_real", "busca": "Tsavo labor camp construction", "sujeito": "Tsavo railway workers",
               "exato": "Tsavo railway workers camp", "animal": "", "busca_alternativa": "",
               "prompt": "Wide view of a colonial railway workers camp with canvas tents near the Tsavo River"}
LEAO_FERIDO = {"n": 99, "tipo": "foto_real", "busca": "wounded lion advancing beneath tree", "sujeito": "leão de Tsavo",
               "exato": "Tsavo lion", "animal": "Tsavo lion", "busca_alternativa": "Panthera leo",
               "prompt": "A wounded maneless lion advancing beneath a tree"}
RESTOS = {"n": 29, "tipo": "video_real", "busca": "human bones dry savanna", "sujeito": "restos mortais", "exato": "",
          "animal": "", "busca_alternativa": "archaeological human remains", "prompt": "Human remains on dry savanna soil"}
TRANCA = {"n": 67, "tipo": "foto_real", "busca": "bullet shattered door latch", "sujeito": "tranca quebrada",
          "exato": "", "animal": "", "busca_alternativa": "damaged wooden cage latch",
          "prompt": "A bullet breaks the wooden latch of a trap door"}
LATAS = {"n": 40, "tipo": "foto_real", "busca": "worker striking metal tin", "sujeito": "worker striking metal",
         "exato": "", "animal": "", "busca_alternativa": "", "prompt": "Workers bang metal tins to make noise at night"}


def passa(cena, descricao, bloco=None):
    """A mesma regra do tapa-buraco (midia._preencher_vazias)."""
    bloco = bloco or {}
    exigido = midia.exigido_da_cena(bloco, cena, ())
    animal = midia.animal_da_cena(bloco, cena)
    x = F(descricao)
    if not animal and midia._mostra_outro_bicho(cena, x):
        return False
    if exigido:
        return midia._cita_o_assunto(exigido, x)
    return midia._cita_bastante(midia._radicais(midia.sujeito_da_busca(cena)), x)


def test_bicho_de_tsavo_nao_passa_no_acampamento():
    assert not passa(ACAMPAMENTO, "red elephant Tsavo Kenya savanna")
    assert not passa(ACAMPAMENTO, "group of vehicles on a dirt road Tsavo")


def test_outro_bicho_de_tsavo_nao_passa_por_leao():
    assert not passa(LEAO_FERIDO, "zebra Tsavo animal africa safari")
    assert not passa(LEAO_FERIDO, "chicken park tsavo")
    assert passa(LEAO_FERIDO, "lion male savanna Kenya")


def test_uma_palavra_so_nao_basta():
    assert not passa(RESTOS, "classic mustang fastback car dry")
    assert not passa(LATAS, "spray cans colour paint cans metal")


def test_sujeito_em_portugues_sem_acento_cede_a_busca():
    assert midia.sujeito_da_busca(TRANCA) == TRANCA["busca"]
    assert not passa(TRANCA, "quebrada de las conchas argentina")


def test_nome_inteiro_e_nao_quatro_letras():
    assert not midia._cita_o_nome("Patterson", F("abstract pattern texture"))
    assert not midia._cita_o_nome("Tsavo", F("tsavorite gemstone"))
    assert midia._cita_o_nome("Tsavo", F("Tsavo East National Park"))


def test_cabeca_do_animal_e_o_substantivo():
    assert midia._cabeca_do_animal("maneless Tsavo lion") == ["lion"]
    assert midia._cabeca_do_animal("spectacled cobra") == ["cobr"]
    assert midia._cabeca_do_animal("plains zebra") == ["zebr"]


def test_exato_com_nome_e_coisa_exige_os_dois():
    assert sorted(midia._identificador("Tsavo railway workers camp")) == ["camp", "tsav"]
    assert midia.exigido_da_cena({}, {"exato": "Palácio de Westminster"}, ()) == set()


def test_genero_cientifico():
    # o regex tinha um caractere invisível no lugar de \\b e nunca achava nada
    assert midia._generos_cientificos("Naja naja") == {"naja"}


def test_recusa_do_modelo():
    assert midia._disse_que_nao("Quem viu a imagem diz que confere com o pedido: nao (elefante).")
    assert not midia._disse_que_nao("Quem viu a imagem diz que confere com o pedido: parcial (x).")


def test_cena_de_epoca_vai_ao_arquivo_e_nunca_vira_video():
    assert midia._e_de_acervo({"epoca": "1898", "busca": "Uganda Railway 1899"}) == "epoca"
    assert roteirista._epoca("1898") == "1898" and roteirista._epoca("2009") == ""
    lista = [{"n": i, "tipo": "video_real" if i % 2 else "foto_real", "ini": i * 4.0, "personagem": False,
              **({"epoca": "1898"} if i < 6 else {})} for i in range(30)]
    cenas_mod._balancear_foto_e_video(lista, log=lambda *a: None)
    assert all(c["tipo"] == "foto_real" for c in lista if c.get("epoca"))
