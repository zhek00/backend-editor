"""O banco de imagens da casa: o que entra, o que sai e o limite de uso entre canais."""
import numpy as np
import pytest

from fabrica import banco_proprio as b


def vetor(*x):
    v = np.array(x, dtype=np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def banco(tmp_path):
    c = b.abrir(tmp_path / "banco.db")
    origem = tmp_path / "origem.png"

    def entra(conteudo, texto, canal, projeto, v=(1, 0), estilo=True):
        origem.write_bytes(conteudo)
        registro = {"prompt": f"Scene: {texto}\nStyle: {b.ESTILO_ATUAL if estilo else 'dark'}", "provedor": "x"}
        novo = b.guardar(c, origem, texto, registro, projeto, canal, pasta=tmp_path)
        if novo:
            c.execute("UPDATE imagens SET vetor=? WHERE id=?", (vetor(*v).tobytes(), novo))
        return novo

    return c, entra


def test_o_pedido_e_so_a_cena():
    assert b.cena_do_prompt("Scene: um mercado\nStyle: claro\nDo not include: nada") == "um mercado"


@pytest.mark.parametrize("cena, prompt, serve", [
    ({}, "Scene: supermarket shelf of tinned beans\nStyle: x", True),
    ({}, "Scene: McDonald's restaurant at night\nStyle: x", True),
    ({"personagem": True}, "Scene: supermarket shelf\nStyle: x", False),
    ({}, 'Scene: front of a shop named "TESCO"\nStyle: x', False),
    ({}, "Scene: register display showing '£1.19' in white\nStyle: x", False),
    ({}, "Scene: menu board with a 40% increase\nStyle: x", False),
])
def test_o_que_entra_no_banco(cena, prompt, serve):
    assert b.serve_para_o_banco(cena, prompt) is serve


def test_a_mesma_imagem_entra_uma_vez_so(banco):
    _c, entra = banco
    assert entra(b"a", "mercado", "canal-a", "p1")
    assert entra(b"a", "mercado", "canal-b", "p2") is None


def test_nunca_volta_ao_canal_que_gerou(banco):
    c, entra = banco
    entra(b"a", "mercado", "canal-a", "p1")
    assert not b.candidatas(c, "canal-a", "p9", 3)
    assert len(b.candidatas(c, "canal-b", "p9", 3)) == 1


def test_usos_max_conta_o_canal_que_gerou(banco):
    c, entra = banco
    i = entra(b"a", "mercado", "canal-a", "p1")
    c.execute("INSERT INTO usos VALUES (?,?,?,?,?)", (i, "canal-b", "p2", 1, ""))
    assert len(b.candidatas(c, "canal-c", "p3", 3)) == 1
    assert not b.candidatas(c, "canal-c", "p3", 2)


def test_estilo_antigo_nao_sai(banco):
    c, entra = banco
    entra(b"a", "mercado", "canal-a", "p1", estilo=False)
    assert not b.candidatas(c, "canal-b", "p9", 3)


def test_cada_imagem_serve_a_uma_cena_e_a_mais_forte_ganha(banco):
    c, entra = banco
    entra(b"a", "mercado", "canal-a", "p1", v=(1, 0))
    linhas = b.candidatas(c, "canal-b", "p9", 3)
    pedidos = np.array([vetor(1, 0.5), vetor(1, 0.01)])
    achadas = b.escolher(pedidos, linhas, 0.8)
    assert list(achadas) == [1]


def test_abaixo_do_corte_gera(banco):
    c, entra = banco
    entra(b"a", "mercado", "canal-a", "p1", v=(1, 0))
    assert not b.escolher(np.array([vetor(1, 1)]), b.candidatas(c, "canal-b", "p9", 3), 0.8)


class Projeto:
    config, perfil, nome = {}, {}, "video-novo"
    dados = {"perfil": "perfis/canal-b.yaml"}

    def __init__(self, pasta):
        self.pasta = pasta

    def imagem(self, n):
        return self.pasta / f"{n:04d}.png"


def test_atender_poe_a_imagem_e_devolve_o_resto(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "PASTA", tmp_path / "banco")
    monkeypatch.setattr(b, "ARQUIVO_DO_BANCO", tmp_path / "banco" / "banco.db")
    c = b.abrir()
    origem = tmp_path / "o.png"
    origem.write_bytes(b"imagem")
    i = b.guardar(c, origem, "mercado", {"prompt": f"Scene: mercado\nStyle: {b.ESTILO_ATUAL}"}, "p1", "canal-a")
    c.execute("UPDATE imagens SET vetor=? WHERE id=?", (vetor(1, 0).tobytes(), i))
    c.commit()
    c.close()
    from fabrica import custos_reais, imagens
    monkeypatch.setattr(imagens, "prompt_final", lambda cena, *_: f"Scene: {cena['prompt']}\nStyle: x")
    monkeypatch.setattr(custos_reais, "registrar", lambda *_a, **_k: None)
    monkeypatch.setattr(b, "significado", lambda t: np.array([vetor(1, 0) if "mercado" in x else vetor(0, 1) for x in t]))
    p = Projeto(tmp_path)
    cenas = [{"n": 1, "prompt": "mercado cheio"}, {"n": 2, "prompt": "floresta"}, {"n": 3, "prompt": "mercado", "prompt_manual": "x"}]
    faltam = b.atender(p, cenas, log=lambda *_: None)
    assert [x["n"] for x in faltam] == [2, 3]
    assert p.imagem(1).read_bytes() == b"imagem"


def test_sem_internet_gera_tudo(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "PASTA", tmp_path / "banco")
    monkeypatch.setattr(b, "ARQUIVO_DO_BANCO", tmp_path / "banco" / "banco.db")
    b.abrir().close()

    def fora(_t):
        raise b.httpx.ConnectError("fora")
    from fabrica import imagens
    monkeypatch.setattr(imagens, "prompt_final", lambda cena, *_: f"Scene: {cena['prompt']}\nStyle: x")
    monkeypatch.setattr(b, "significado", fora)
    c = b.abrir()
    o = tmp_path / "o.png"
    o.write_bytes(b"i")
    b.guardar(c, o, "mercado", {"prompt": b.ESTILO_ATUAL}, "p1", "canal-a")
    c.commit()
    c.close()
    assert len(b.atender(Projeto(tmp_path), [{"n": 1, "prompt": "mercado"}], log=lambda *_: None)) == 1
