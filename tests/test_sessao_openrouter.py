"""O Jev e as imagens de IA mandam o nome do projeto (session_id) para a aba Sessions do OpenRouter."""

from types import SimpleNamespace

from fabrica.openrouter_local import postar_com_sessao


class _Resposta:
    def __init__(self, status, texto=""):
        self.status_code, self.text = status, texto


def test_manda_o_nome_do_projeto():
    enviados = []

    def post(url, json, **kw):
        enviados.append(json)
        return _Resposta(200)

    postar_com_sessao(post, "u", {"model": "m"}, SimpleNamespace(nome="ouro da serra"))
    assert enviados == [{"model": "m", "session_id": "ouro-da-serra"}]


def test_interface_que_recusa_o_campo_vai_sem_ele():
    enviados = []

    def post(url, json, **kw):
        enviados.append(json)
        return _Resposta(400, "unknown field session_id") if "session_id" in json else _Resposta(200)

    r = postar_com_sessao(post, "u", {"model": "m"}, SimpleNamespace(nome="x"))
    assert r.status_code == 200 and enviados[-1] == {"model": "m"}


def test_outro_erro_400_nao_repete():
    enviados = []

    def post(url, json, **kw):
        enviados.append(json)
        return _Resposta(400, "prompt too long")

    postar_com_sessao(post, "u", {"model": "m"}, SimpleNamespace(nome="x"))
    assert len(enviados) == 1
