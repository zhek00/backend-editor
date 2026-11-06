"""A parte de IA escolhida para o vídeo."""
from types import SimpleNamespace

from fabrica import cenas, midia


def _cenas(n, ia=0, **resto):
    return [{"n": i, "tipo": "ia" if i < ia else "foto_real", "busca": f"b{i}", "prompt": f"p{i}", **resto} for i in range(n)]


def _ia(lista):
    return [c["n"] for c in lista if c["tipo"] == "ia"]


def test_leva_a_ia_ate_a_parte_escolhida_e_guarda_a_busca():
    lista = _cenas(100, ia=10)
    cenas._aplicar_fracao_da_ia(lista, 0.75, log=lambda *_: None)
    assert len(_ia(lista)) == 75
    virou = next(c for c in lista if c["tipo"] == "ia" and c["n"] >= 10)
    assert virou["busca"] == "" and virou["busca_reserva"] == f"b{virou['n']}" and virou["prompt"]


def test_espalha_pelo_video():
    lista = _cenas(100)
    cenas._aplicar_fracao_da_ia(lista, 0.25, log=lambda *_: None)
    assert max(b - a for a, b in zip(_ia(lista), _ia(lista)[1:])) <= 5


def test_nao_mexe_quando_ja_passou_da_parte():
    lista = _cenas(10, ia=8)
    cenas._aplicar_fracao_da_ia(lista, 0.5, log=lambda *_: None)
    assert len(_ia(lista)) == 8


def test_cena_de_nome_exato_e_a_ultima_a_virar_ia():
    lista = _cenas(4) + [{"n": 9, "tipo": "foto_real", "busca": "x", "prompt": "p", "exato": "Eiffel"}]
    cenas._aplicar_fracao_da_ia(lista, 0.8, log=lambda *_: None)
    assert lista[-1]["tipo"] == "foto_real"
    cenas._aplicar_fracao_da_ia(lista, 1, log=lambda *_: None)
    assert lista[-1]["tipo"] == "ia"


def test_cena_sem_prompt_nao_vira_ia():
    lista = [{"n": 0, "tipo": "foto_real", "busca": "b", "prompt": ""}]
    cenas._aplicar_fracao_da_ia(lista, 1, log=lambda *_: None)
    assert lista[0]["tipo"] == "foto_real"


def test_a_fracao_so_vale_com_a_ia_ligada():
    assert midia.fracao_da_ia(SimpleNamespace(config={"ia": {"fracao": 0.75}})) == 0.75
    assert midia.fracao_da_ia(SimpleNamespace(config={"ia": {"ativa": False, "fracao": 0.75}})) is None
    assert midia.fracao_da_ia(SimpleNamespace(config={})) is None
