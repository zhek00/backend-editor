"""Cena 9 do teste-animacao-1min (2026-10-26): a fala "Em segundo lugar, a água-viva" mostrou um peixe-leão.

1. O corte prévio juntou "uma dor intensa em quem encosta neles." com "Em segundo lugar, a água-viva.", e o agente
   pediu o peixe-leão para esse corte. A frase que anuncia o assunto da seguinte vai com a seguinte.
2. O Jev reprovou a imagem de IA (nota 3) e escreveu o pedido certo pela fala (prompt_novo, a água-viva), mas a
   imagem foi refeita pelo pedido antigo e saiu outro peixe-leão."""
import json
import pathlib

from fabrica import cenas, corrigir, imagens

FRASES = [
    ("Os espinhos das costas carregam veneno e causam", 0.0, 2.9),
    ("uma dor intensa em quem encosta neles.", 2.9, 5.3),
    ("Em segundo lugar, a água-viva.", 5.3, 7.4),
    ("Os tentáculos da água-viva soltam milhares de células que queimam a pele.", 7.4, 12.0),
]


def _unidades(frases):
    return [{"texto": t, "ini": i, "fim": f} for t, i, f in frases]


def _textos(grupos, unidades):
    return [" ".join(unidades[k]["texto"] for k in range(g["primeira_frase"], g["ultima_frase"] + 1)) for g in grupos]


def test_frase_que_anuncia_vai_com_a_seguinte():
    u = _unidades(FRASES)
    textos = _textos(cenas._pre_cortar(u, 4.0, 3.0, 5.0), u)
    assert "uma dor intensa em quem encosta neles." in textos
    assert not any("neles." in t and "água-viva" in t for t in textos)


def test_frase_do_mesmo_assunto_continua_junta():
    # "Ela se esconde na areia rasa" não repete nenhum nome da frase de antes: segue o corte de sempre
    u = _unidades([("Em quarto lugar, a arraia.", 0.0, 2.0), ("Ela se esconde na areia rasa, perto da beira,", 2.0, 4.8),
                   ("e quem pisa nela leva uma ferroada da cauda.", 4.8, 7.5)])
    assert _textos(cenas._pre_cortar(u, 4.0, 3.0, 5.0), u)[0] == (
        "Em quarto lugar, a arraia. Ela se esconde na areia rasa, perto da beira,")


class _Projeto:
    def __init__(self, pasta, cena):
        self.pasta = pathlib.Path(pasta)
        (self.pasta / "imagens").mkdir()
        (self.pasta / "imagens" / "0009.png").write_bytes(b"png")
        self._dados = {"cenas": [cena]}

    def ler_json(self, nome):
        return json.loads(json.dumps(self._dados))

    def salvar_json(self, nome, dados):
        self._dados = dados

    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.png"


def test_ia_reprovada_e_refeita_pelo_pedido_que_o_jev_escreveu(monkeypatch, tmp_path):
    cena = {"n": 9, "tipo": "ia", "texto": "Em segundo lugar, a água-viva. Os tentáculos da água-viva",
            "prompt": "diver's gloved hand approaching a lionfish", "mostrar": "Mão de mergulhador perto do peixe-leão",
            "sujeito": "diver hand lionfish"}
    projeto = _Projeto(tmp_path, cena)
    errada = {"nota": 3, "sujeito": 11, "veredito": "nao_combina", "legenda": "peixe-leão e mão de mergulhador",
              "prompt_novo": "Close-up of a translucent jellyfish with long tentacles"}
    monkeypatch.setattr(corrigir, "imagem_de_ia", lambda c: True)
    monkeypatch.setattr(corrigir, "_avaliar", lambda *a, **k: {9: dict(errada)})
    monkeypatch.setattr(corrigir, "_guardar", lambda *a, **k: None)
    pedidos = []
    monkeypatch.setattr(imagens, "refazer", lambda projeto, numeros, prompt=None, log=None: pedidos.append(prompt))
    corrigir.conferir_ia(projeto, log=lambda *a: None)
    assert pedidos and pedidos[0].startswith("Close-up of a translucent jellyfish")
    assert "lionfish" not in pedidos[0] and "peixe-leão" not in pedidos[0].split("IMPORTANT")[0]


def test_correcao_anterior_da_fabrica_nao_conta_como_escolha_da_pessoa(monkeypatch, tmp_path):
    # a primeira correção gravou o pedido no prompt_manual; a segunda repetia o peixe-leão com dois avisos de erro
    cena = {"n": 9, "tipo": "ia", "prompt": "diver's gloved hand approaching a lionfish",
            "prompt_manual": "diver's gloved hand approaching a lionfish\n" + corrigir.CORRECAO_IA + " (peixe-leão).",
            "mostrar": "Mão de mergulhador perto do peixe-leão"}
    projeto = _Projeto(tmp_path, cena)
    errada = {"nota": 2, "sujeito": 15, "veredito": "nao_combina", "legenda": "peixe-leão",
              "prompt_novo": "Close-up of a translucent jellyfish with long tentacles"}
    monkeypatch.setattr(corrigir, "imagem_de_ia", lambda c: True)
    monkeypatch.setattr(corrigir, "_avaliar", lambda *a, **k: {9: dict(errada)})
    monkeypatch.setattr(corrigir, "_guardar", lambda *a, **k: None)
    pedidos = []

    def refazer(projeto, numeros, prompt=None, log=None):
        pedidos.append(prompt)
        dados = projeto.ler_json("cenas.json")
        dados["cenas"][0]["prompt_manual"] = prompt
        projeto.salvar_json("cenas.json", dados)

    monkeypatch.setattr(imagens, "refazer", refazer)
    corrigir.conferir_ia(projeto, log=lambda *a: None)
    assert pedidos[0].startswith("Close-up of a translucent jellyfish")
    assert pedidos[0].count(corrigir.CORRECAO_IA) == 1
    final = projeto.ler_json("cenas.json")["cenas"][0]
    assert "prompt_manual" not in final and final["prompt"].startswith("Close-up of a translucent jellyfish")


def test_pedido_da_pessoa_continua_valendo(monkeypatch, tmp_path):
    cena = {"n": 9, "tipo": "ia", "prompt": "lionfish", "prompt_manual": "a blue jellyfish in a glass bowl"}
    projeto = _Projeto(tmp_path, cena)
    errada = {"nota": 2, "sujeito": 15, "veredito": "nao_combina", "legenda": "x", "prompt_novo": "something else"}
    monkeypatch.setattr(corrigir, "imagem_de_ia", lambda c: True)
    monkeypatch.setattr(corrigir, "_avaliar", lambda *a, **k: {9: dict(errada)})
    monkeypatch.setattr(corrigir, "_guardar", lambda *a, **k: None)
    pedidos = []
    monkeypatch.setattr(imagens, "refazer", lambda projeto, numeros, prompt=None, log=None: pedidos.append(prompt))
    corrigir.conferir_ia(projeto, log=lambda *a: None)
    assert pedidos[0].startswith("a blue jellyfish in a glass bowl")
