"""A decisão da conferência, a conferência do JSON do agente e a nota do vídeo. Sem rede e sem custo."""
from fabrica import corrigir, roteirista


def test_sujeito_certo_com_nota_baixa_fica():
    # três leões sem juba julgados contra "dois leões entre tendas à noite": nota 4, mas o sujeito está certo
    assert not corrigir.errada({"nota": 4, "sujeito": 85})


def test_sujeito_errado_troca_mesmo_com_nota_media():
    # uma zebra de Tsavo no lugar do leão
    assert corrigir.errada({"nota": 45, "sujeito": 10})


def test_epoca_errada_troca():
    assert corrigir.errada({"nota": 60, "sujeito": 80, "epoca": 10})


def test_sem_a_pergunta_do_sujeito_vale_a_nota():
    assert corrigir.errada({"nota": 5})
    assert not corrigir.errada({"nota": 45})


def test_aprovada_nao_aceita_sujeito_errado():
    assert not corrigir.aprovada({"veredito": "em_parte", "nota": 55, "sujeito": 5})


def test_lixo_do_agente_e_recusado():
    respostas = [{"cena": 1, "descricao": "Um engenheiro do exércitoBritish chega", "exato": "Palácio de Westminster"},
                 {"cena": 2, "descricao": "Um engenheiro do exércitoBritish chega"}]
    problemas = roteirista.problemas_do_lote(respostas, {1: "o tenente-coronel chega", 2: "ele era experiente"})
    assert any("grudadas" in p for p in problemas)
    assert any("exato em português" in p for p in problemas)
    assert any("a mesma da cena 1" in p for p in problemas)


def test_descricao_igual_com_a_mesma_fala_passa():
    respostas = [{"cena": 1, "descricao": "Leão sem juba"}, {"cena": 2, "descricao": "Leão sem juba"}]
    assert not roteirista.problemas_do_lote(respostas, {1: "mesma fala", 2: "mesma fala"})


def test_limpeza_do_que_sobrou():
    limpo = roteirista._limpar_resposta({"descricao": "ferroviários_dpklsy no exércitoBritish"})
    assert limpo["descricao"] == "ferroviários no exército British"
