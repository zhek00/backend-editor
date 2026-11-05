"""O computador não dorme enquanto a fábrica trabalha (fabrica/acordado.py)."""
from fabrica import acordado


def test_segurar_conta_e_solta():
    assert not acordado._ocupado()
    with acordado.segurar():
        assert acordado._ocupado()
        with acordado.segurar():
            assert acordado._ocupado()
        assert acordado._ocupado()
    assert not acordado._ocupado()


def test_verificador_com_erro_nao_derruba():
    def quebrado():
        raise RuntimeError("x")

    estado = {"ocupado": False}
    acordado.vigiar(quebrado)
    acordado.vigiar(lambda: estado["ocupado"])
    assert not acordado._ocupado()
    estado["ocupado"] = True
    assert acordado._ocupado()
    acordado._verificadores.clear()
