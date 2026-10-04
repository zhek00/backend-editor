"""Cenas de IA seguidas: o pedido de cada cena vem da frase que ela fala, e os prompts não se repetem.

Caso real: cenas 23 a 26 do virou-filme-em-1996, quatro imagens do mesmo engenheiro de costas indo para a ponte.
Rode com: uv run --no-sync --with pytest python -m pytest tests
Sem rede e sem custo: o modelo é trocado por uma resposta pronta.
"""
from types import SimpleNamespace

from fabrica import cenas as cenas_mod
from fabrica import imagens, openrouter_local

CHEGA = "Um engenheiro do exército britânico chega a pé à obra da ponte, visto de costas."
CACADOR = "Um engenheiro colonial segura uma espingarda enquanto examina a ponte em construção."
ENGANADO = "John Henry Patterson observa a obra da ponte de costas, em silêncio."


class Projeto(SimpleNamespace):
    def existe(self, nome):
        return nome in self.arquivos

    def ler_json(self, nome):
        return self.arquivos[nome]

    def salvar_json(self, nome, dados):
        self.arquivos[nome] = dados


def _projeto(cenas):
    unidades = [{"ini": 0.0, "fim": 4.0}, {"ini": 4.0, "fim": 8.0}, {"ini": 8.0, "fim": 12.0}]
    palavras = [{"texto": f"p{i}", "ini": i * 0.5} for i in range(24)]
    agente = {"frases": 3, "cenas": [
        {"primeira_frase": 0, "ultima_frase": 0, "descricao": CHEGA, "prompt": "engineer arriving", "sujeito": "engineer"},
        {"primeira_frase": 1, "ultima_frase": 1, "descricao": CACADOR, "prompt": "engineer holding a rifle",
         "sujeito": "engineer"},
        {"primeira_frase": 2, "ultima_frase": 2, "descricao": ENGANADO, "prompt": "Patterson in silence",
         "sujeito": "John Henry Patterson"}]}
    alinhamento = {"unidades": unidades, "palavras": palavras, "duracao": 12.0}
    return Projeto(arquivos={"roteiro_cenas.json": agente, "cenas.json": {"cenas": cenas}}), alinhamento


def test_cena_recortada_leva_o_pedido_da_propria_frase():
    # o recorte deu às três cenas a descrição da primeira; cada uma fala uma frase diferente
    cenas = [{"n": i + 1, "ini": i * 4.0, "fim": i * 4.0 + 4.0, "mostrar": CHEGA, "prompt": "engineer arriving",
              "tipo": "ia"} for i in range(3)]
    projeto, alinhamento = _projeto(cenas)
    assert cenas_mod._pedido_pela_fala(projeto, cenas, alinhamento) == 2
    assert [c["mostrar"] for c in cenas] == [CHEGA, CACADOR, ENGANADO]
    assert cenas[2]["sujeito"] == "John Henry Patterson" and cenas[2]["pedido_mudou"]
    assert "pedido_mudou" not in cenas[0]


def test_a_escolha_da_pessoa_fica():
    cenas = [{"n": 1, "ini": 0.0, "fim": 4.0, "mostrar": CHEGA},
             {"n": 2, "ini": 4.0, "fim": 8.0, "mostrar": CHEGA, "busca_manual": "rifle", "prompt_manual": "x"}]
    projeto, alinhamento = _projeto(cenas)
    assert cenas_mod._pedido_pela_fala(projeto, cenas, alinhamento) == 0
    assert cenas[1]["mostrar"] == CHEGA


def test_so_trechos_de_duas_ou_mais_cenas_de_ia_com_pendente():
    c = lambda n, tipo="ia", bloco=4: {"n": n, "tipo": tipo, "bloco": bloco}
    cenas = [c(1, "foto_real"), c(2), c(3), c(4, "foto_real"), c(5), c(6), c(7, bloco=5)]
    trechos = imagens._trechos_de_ia(cenas, pendentes={3, 6})
    assert [[x["n"] for x in t] for t in trechos] == [[2, 3], [5, 6]]


def test_prompts_seguidos_sao_reescritos_em_planos_diferentes(monkeypatch):
    cenas = [{"n": n, "ini": n * 4.0, "fim": n * 4.0 + 4.0, "tipo": "ia", "bloco": 4, "texto": f"fala {n}",
              "prompt": "A British engineer walking toward the Tsavo railway bridge, seen from behind"} for n in (1, 2, 3)]
    projeto, _ = _projeto(cenas)
    respostas = [
        # primeira resposta: duas cenas seguidas no mesmo plano -> volta para o modelo
        {"cenas": [{"n": n, "plano": "medio", "prompt": f"Patterson doing thing number {n} near the bridge today"}
                   for n in (1, 2, 3)]},
        {"cenas": [{"n": 1, "plano": "geral", "prompt": "Small figure of an engineer arriving across the dry savanna"},
                   {"n": 2, "plano": "detalhe", "prompt": "Close detail of a hunting rifle and survey tools on the ground"},
                   {"n": 3, "plano": "medio", "prompt": "Patterson standing silent by the tents while workers keep building"}]},
    ]
    pedidos = []

    def perguntar(projeto, etapa, instrucoes, pedido, esquema, **k):
        pedidos.append(pedido)
        return respostas[len(pedidos) - 1]

    monkeypatch.setattr(openrouter_local, "perguntar", perguntar)
    monkeypatch.setattr(openrouter_local, "principal", lambda projeto: "modelo")
    assert imagens.prompts_em_sequencia(projeto, {1, 2, 3}, log=lambda *a: None) == 3
    assert len(pedidos) == 2 and "plano" in pedidos[1]
    final = projeto.arquivos["cenas.json"]["cenas"]
    assert [c["plano"] for c in final] == ["geral", "detalhe", "medio"]
    assert final[1]["prompt"].startswith("Close detail")


def test_parecidos():
    a = "A British engineer walking toward the Tsavo railway bridge, seen from behind"
    assert imagens.parecidos(a, "Alternative angle, " + a) >= 0.5
    assert imagens.parecidos(a, "Close detail of a hunting rifle and survey tools on the ground") < 0.2


def test_cena_recortada_leva_a_busca_da_propria_frase():
    # natureza-nos-ensina: "e algumas cabem na ponta do seu dedo" seguia buscando o elefante da frase anterior
    cenas = [{"n": i + 1, "ini": i * 4.0, "fim": i * 4.0 + 4.0, "mostrar": CHEGA, "tipo": tipo, "busca": "engineer"}
             for i, tipo in enumerate(("foto_real", "foto_real", "ia"))]
    projeto, alinhamento = _projeto(cenas)
    for g, busca in zip(projeto.arquivos["roteiro_cenas.json"]["cenas"], ("engineer", "rifle hunter", "camp dusk")):
        g["busca"] = busca
    cenas_mod._pedido_pela_fala(projeto, cenas, alinhamento)
    assert cenas[1]["busca"] == "rifle hunter"
    assert cenas[2]["busca"] == "engineer" and cenas[2]["busca_reserva"] == "camp dusk"
