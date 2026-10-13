import re
from types import SimpleNamespace

from fabrica import animation_ai as a


def _projeto(tema=None):
    return SimpleNamespace(config={"animation_ai": {"tema": tema}} if tema else {}, perfil={})


def test_impacto_e_o_padrao_e_usa_o_motor_dele():
    p = _projeto()
    assert a.config(p)["tema"] == "impacto"
    assert a.e_impacto(a.tema(p))
    html = a.montar_html("frase", {"texto": "x", "t": 0.3}, 4.0, a.tema(p))
    assert "R.baralho" in html and "--acc:#FFD23F" in html  # o motor e as cores do impacto
    assert "--_motor" not in html  # a chave do motor não vira variável de CSS
    # quem escolhe outro tema continua com o motor de antes
    assert "R.baralho" not in a.montar_html("frase", {"texto": "x", "t": 0.3}, 4.0, a.tema(_projeto("apple")))


def test_no_impacto_o_modelo_so_escolhe_tipo_que_tem_receita():
    tipos = a.tipos_do_tema(_projeto())
    assert tipos and set(tipos) <= set(a.TIPOS_IMPACTO)
    assert "barras" not in tipos
    assert a.tipos_do_tema(_projeto("apple")) == list(a.DE_COMPLEMENTO)
    # no lugar do motion, a mesma restrição em cima da lista dele
    assert set(a.tipos_do_tema(_projeto(), a.COMO_MOTION)) <= set(a.COMO_MOTION) & set(a.TIPOS_IMPACTO)


def test_todo_tipo_do_impacto_tem_receita_no_motor():
    js = (a.RECURSOS / "motor_impacto.js").read_text(encoding="utf-8")
    qual = js[js.index("const QUAL"):]
    qual = qual[:qual.index("};")]
    com_receita = set(re.findall(r"(\w+):\s*\"", qual))
    assert set(a.TIPOS_IMPACTO) <= com_receita
    assert set(a.TIPOS_IMPACTO) <= set(a.CATALOGO)
    assert set(a.COM_FOTO_IMPACTO) <= set(a.TIPOS_IMPACTO)


class _ProjetoDeFotos:
    def __init__(self, pasta, cenas):
        self.pasta, self._cenas, self.config, self.perfil = pasta, cenas, {}, {}

    def ler_json(self, nome):
        return {"cenas": self._cenas}

    def existe(self, nome):
        return False


def test_a_foto_da_cena_vai_para_o_fundo(tmp_path, monkeypatch):
    from PIL import Image

    (tmp_path / "midia").mkdir()
    Image.new("RGB", (64, 48), (40, 90, 40)).save(tmp_path / "midia" / "0012.jpg")
    cena = {"n": 12, "ini": 0.0, "fim": 4.0, "midia": {"fonte": "animation_ai"},
            "anim_reserva": {"midia": {"fonte": "pexels", "id": "77", "tipo": "foto", "arquivo": "midia/0012.jpg"}}}
    monkeypatch.setattr(a, "_foto_do_banco", lambda *args, **kw: None)
    pasta = tmp_path / "animation_ai" / "0012"
    dados = {"valor": "150", "t": 0.4}
    creditos = a.fotos_impacto(_ProjetoDeFotos(tmp_path, [cena]), [cena], "numero", dados, 0.0, pasta,
                               log=lambda *x: None)
    assert dados["fundo"] == "assets/fotos/fundo_0012.jpg" and (pasta / dados["fundo"]).exists()
    assert dados["fundo_id"] == "pexels:77"
    assert [c["id"] for c in creditos[12]] == ["77"]


def test_sons_do_impacto_caem_nos_momentos_das_receitas():
    # ligação: as causas aparecem (pop), o destino desliza (risco) e bate com o flash (baque)
    d = {"itens": [{"texto": "a", "t": 0.5}, {"texto": "b", "t": 1.2}, {"texto": "c", "t": 1.4}]}
    assert a.sons_impacto("causa_efeito", d, 6.0) == [(0.5, "pop"), (1.2, "pop"), (1.95, "baque")]  # o risco cai a 0,25 s do pop
    # comparar: o segundo lado nunca chega antes de 0,8 s depois do primeiro
    d = {"esq": {"titulo": "x", "t": 1.0}, "dir": {"titulo": "y", "t": 1.2}}
    assert a.sons_impacto("comparar", d, 6.0) == [(0.9, "risco"), (1.8, "baque")]
    # nada depois do fim, no máximo 8, sempre 0,25 s entre eles
    d = {"itens": [{"texto": str(i), "t": i * 0.5} for i in range(20)]}
    sons = a.sons_impacto("lista", d, 5.0)
    assert len(sons) <= 8 and all(t < 5.0 for t, _ in sons)
    assert all(b[0] - a_[0] >= 0.25 for a_, b in zip(sons, sons[1:]))
    # todo tipo do impacto tem som, com os exemplos
    for tipo in a.TIPOS_IMPACTO:
        dados, _ = a.resolver_tempos(tipo, a.EXEMPLOS[tipo], [], 6.0)
        assert a.sons_impacto(tipo, dados, 6.0), tipo


def test_nome_da_animacao_nao_pisa_no_arquivo_de_outra_cena(tmp_path):
    # a cena 33 (a 34 de antes de renumerar) mostra midia/0034_anim.mp4: a cena 34 nova grava com outro nome
    from fabrica.midia import nome_livre

    cenas = [{"n": 33, "midia": {"arquivo": "midia/0034_anim.mp4"}}, {"n": 34, "midia": None}]
    p = SimpleNamespace(ler_json=lambda nome: {"cenas": cenas})
    assert nome_livre(p, 34, ("_anim.mp4", "_anim_capa.jpg")) == "0034_2"
    assert nome_livre(p, 35, ("_anim.mp4", "_anim_capa.jpg")) == "0035"
