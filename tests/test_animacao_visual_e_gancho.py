"""Cena animada visual e o gancho dos primeiros 40 s (pedido do usuário em 2026-10-25).

No everything-you-need-to-answer 5 dos 25 trechos animados saíram sem nenhuma foto e 6 com frases inteiras ("Not a
case against Tesco as a business"), trechos de até 11,8 s, e 6 das 11 cenas do começo foram para a imagem de IA."""
import json
import pathlib

from fabrica import animacoes, animation_ai


class _Projeto:
    offline = False
    perfil: dict = {}

    def __init__(self, pasta, config=None):
        self.pasta = pathlib.Path(pasta)
        self.config = config or {}

    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.png"


def test_tem_imagem_olha_fundo_itens_e_lados():
    assert not animation_ai.tem_imagem({"itens": [{"texto": "Tesco"}]})
    assert animation_ai.tem_imagem({"fundo": "assets/fotos/fundo_0001.jpg"})
    assert animation_ai.tem_imagem({"itens": [{"texto": "Tesco", "foto": "a.jpg"}]})
    assert animation_ai.tem_imagem({"esq": {"titulo": "A", "foto": "a.jpg"}, "dir": {"titulo": "B"}})


def test_item_de_lista_e_o_nome_da_coisa_nao_uma_frase():
    fala = "Tesco is number one on the avoid list. Not a case against Tesco as a business."
    erros = animation_ai.conferir("lista", {"itens": [{"texto": "Not against Tesco as a business"},
                                                      {"texto": "Tesco"}]}, fala)
    assert any("mais de 5 palavras" in e for e in erros)
    assert not any("palavras (" in e for e in animation_ai.conferir(
        "lista", {"itens": [{"texto": "Tesco"}, {"texto": "avoid list"}]}, fala))


def test_imagem_de_ia_da_cena_serve_de_fundo(tmp_path):
    projeto = _Projeto(tmp_path)
    projeto.imagem(7).parent.mkdir(parents=True)
    projeto.imagem(7).write_bytes(b"png")
    foto = animation_ai._foto_da_cena(projeto, {"n": 7, "tipo": "ia"})
    assert foto and foto[0] == projeto.imagem(7) and foto[1]["fonte"] is None  # sem fonte: fora do creditos.txt
    assert animation_ai._foto_da_cena(projeto, {"n": 8, "tipo": "ia"}) is None  # sem imagem nenhuma


def test_camada_de_animacao_nao_entra_nos_primeiros_40_segundos(monkeypatch, tmp_path):
    projeto = _Projeto(tmp_path)
    monkeypatch.setattr(animacoes, "tipos", lambda projeto: ["diagrama"])
    cena = {"n": 3, "ini": 12.0, "visual": "diagrama", "texto": "a rede de distribuição"}
    assert not animacoes.elegivel(projeto, cena)
    assert animacoes.elegivel(projeto, cena, pedida=True)  # a pessoa pediu: entra
    assert animacoes.elegivel(projeto, {**cena, "ini": 41.0})


def test_gravar_recusa_cena_so_com_texto(monkeypatch, tmp_path):
    projeto = _Projeto(tmp_path)
    (tmp_path / "cenas.json").write_text(json.dumps({"cenas": []}), encoding="utf-8")
    projeto.ler_json = lambda nome: json.loads((tmp_path / nome).read_text(encoding="utf-8"))
    monkeypatch.setattr(animation_ai.animacoes, "node_pronto", lambda: "npx")
    monkeypatch.setattr(animation_ai, "palavras_do_trecho", lambda projeto, ini, fim: [])
    monkeypatch.setattr(animation_ai, "fotos_impacto", lambda *a, **k: {})
    trecho = [{"n": 50, "ini": 100.0, "fim": 105.0, "texto": "Tesco, Asda and Lidl."}]
    plano = {"tipo": "lista", "dados": {"itens": [{"texto": "Tesco"}, {"texto": "Asda"}, {"texto": "Lidl"}]}}
    try:
        animation_ai.gravar(projeto, trecho, plano, exigir_imagem=True)
    except animation_ai.SemImagem:
        pass
    else:
        raise AssertionError("a cena só com texto devia ser recusada")
