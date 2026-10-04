"""A duração e o encaixe da camada de animação, com os casos do virou-filme-em-1996.

Rode com: uv run --no-sync --with pytest python -m pytest tests
Sem rede, sem Node e sem custo.
"""
from types import SimpleNamespace

from fabrica import animacoes

PROJETO = SimpleNamespace(config={}, perfil={})


def test_frase_curta_dura_no_minimo_3_segundos():
    # "Em 2009 cientistas resolveram investigar.": a fala tem 3,1 s, e a animação sumia no corte da cena
    dados = {"palavras": [{"texto": "2009", "t": 0.3}, {"texto": "cientistas", "t": 0.8}]}
    assert animacoes.duracao_do_conteudo(PROJETO, dados) == 3.0


def test_muito_texto_para_em_8_segundos():
    dados = {"titulo": {"texto": "Por que os leões atacavam", "t": 0.2},
             "itens": [{"texto": "dentes quebrados e infecção na raiz de um canino", "t": 1.0 + i} for i in range(4)]}
    assert animacoes.duracao_do_conteudo(PROJETO, dados) == 8.0


def test_o_ultimo_elemento_sempre_aparece():
    # a fala do trecho passou de 8 s: o último elemento ainda ganha tempo de ser visto
    dados = {"esquerda": {"titulo": {"texto": "135", "t": 0.5}}, "direita": {"titulo": {"texto": "35", "t": 8.4}}}
    assert animacoes.duracao_do_conteudo(PROJETO, dados) >= 9.6


def test_nunca_cobre_a_animacao_seguinte():
    dados = {"titulo": {"texto": "Expresso Lunático", "t": 0.2},
             "itens": [{"texto": "mil quilômetros de trilhos pela savana", "t": 1.5}]}
    assert animacoes.duracao_do_conteudo(PROJETO, dados, limite=3.4) == 3.4


def test_validas_corta_a_sobreposicao(monkeypatch, tmp_path):
    itens = [{"id": "a", "ini": 10.0, "fim": 18.0}, {"id": "b", "ini": 15.0, "fim": 20.0}]
    projeto = SimpleNamespace(config={}, perfil={}, pasta=tmp_path)
    (tmp_path / "a.mov").write_bytes(b"x")
    (tmp_path / "b.mov").write_bytes(b"x")
    monkeypatch.setattr(animacoes, "ler", lambda p: [{**i, "arquivo": f"{i['id']}.mov", "render": "r"} for i in itens])
    monkeypatch.setattr(animacoes, "_ancorar", lambda p, i, pela_fala=False: {"ini": i["ini"], "fim": i["fim"]})
    monkeypatch.setattr(animacoes, "_assinatura_render", lambda p, i, a: "r")
    a, b = animacoes.validas(projeto)
    assert a["fim"] == 15.0 and b["fim"] == 20.0


def test_excluir_animacao_pela_faixa_motion(monkeypatch, tmp_path):
    itens = [{"id": "a", "c_ini": 1, "c_fim": 5}, {"id": "b", "c_ini": 9, "c_fim": 12},
             {"id": "c", "c_ini": 20, "c_fim": 25, "desligada": True}]
    projeto = SimpleNamespace(config={}, perfil={}, pasta=tmp_path, existe=lambda nome: False)
    monkeypatch.setattr(animacoes, "ler", lambda p: itens)
    salvos = []
    monkeypatch.setattr(animacoes, "_salvar", lambda p, lista: salvos.append([i["id"] for i in lista if i.get("desligada")]))
    assert animacoes.remover_item(projeto, "a") == ["a"]
    assert salvos[-1] == ["a", "c"]
    assert animacoes.remover_item(projeto, "todos") == ["b"]  # a que já estava desligada não conta de novo
    assert animacoes.remover_item(projeto, "nao-existe") == []
