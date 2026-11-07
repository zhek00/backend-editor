"""Garantia: no fim, a cena que ainda não combina com a fala vira imagem de IA, e a imagem de IA ruim é feita de novo."""
import copy
from pathlib import Path

from fabrica import corrigir, imagens, midia


class Projeto:
    offline, nome, perfil = False, "teste", {}

    def __init__(self, pasta, cenas, config=None):
        self.pasta, self.dados, self.config = pasta, {"cenas": cenas}, config or {}

    def ler_json(self, _nome):
        return copy.deepcopy(self.dados)

    def salvar_json(self, _nome, dados):
        self.dados = copy.deepcopy(dados)

    def existe(self, _nome):
        return True

    def imagem(self, n) -> Path:
        return self.pasta / f"{n:04d}.png"


def nota(n, sujeito=80):
    return {"nota": n, "sujeito": sujeito, "legenda": "mostra outra coisa", "prompt_novo": ""}


def preparar(monkeypatch, tmp_path, cenas, notas_novas):
    """notas_novas: a nota que o Jev dá à imagem de IA nova de cada cena."""
    p = Projeto(tmp_path, cenas)
    for c in cenas:
        if not c.get("midia"):
            p.imagem(c["n"]).write_bytes(b"x")
    chamadas = {"gerar": [], "refazer": []}
    monkeypatch.setattr(midia, "ia_ativa", lambda _p: True)

    def mandar(projeto, itens, log):
        dados = projeto.ler_json("cenas.json")
        nums = [i["cena"] for i in itens]
        for c in dados["cenas"]:
            if c["n"] in nums:
                c["ia_reserva"] = {"midia": c["midia"], "nota": c["conferencia"]["nota"], "sujeito": 80}
                c["midia"], c["tipo"] = None, "ia"
                c.pop("conferencia")
        projeto.salvar_json("cenas.json", dados)
        return nums

    def gerar(projeto, apenas, log, conferir):
        chamadas["gerar"].append(sorted(apenas))
        for n in apenas:
            projeto.imagem(n).write_bytes(b"x")

    def avaliar(projeto, numeros, log, minima):
        return {n: nota(notas_novas[n]) for n in numeros}

    def guardar(projeto, avaliacoes, rodada):
        dados = projeto.ler_json("cenas.json")
        for c in dados["cenas"]:
            if c["n"] in avaliacoes:
                c["conferencia"] = avaliacoes[c["n"]]
        projeto.salvar_json("cenas.json", dados)

    def refazer(projeto, numeros, prompt, log):
        chamadas["refazer"].append(sorted(numeros))

    monkeypatch.setattr(corrigir, "mandar_para_ia", mandar)
    monkeypatch.setattr(imagens, "gerar", gerar)
    monkeypatch.setattr(imagens, "refazer", refazer)
    monkeypatch.setattr(corrigir, "_avaliar", avaliar)
    monkeypatch.setattr(corrigir, "_guardar", guardar)
    monkeypatch.setattr(corrigir, "_devolver_sem_imagem", lambda *_a: [])
    monkeypatch.setattr(corrigir, "_voltar_reserva", lambda projeto, n, log: chamadas.setdefault("voltou", []).append(n))
    return p, chamadas


def foto(n, valor):
    return {"n": n, "tipo": "foto_real", "midia": {"fonte": "pexels", "id": str(n), "arquivo": f"m/{n}.jpg"},
            "conferencia": nota(valor)}


def ia(n, valor):
    return {"n": n, "tipo": "ia", "conferencia": nota(valor)}


def test_foto_fraca_vira_ia_e_a_boa_fica(tmp_path, monkeypatch):
    p, chamadas = preparar(monkeypatch, tmp_path, [foto(1, 30), foto(2, 90)], {1: 85})
    r = corrigir.garantir(p, log=lambda *_: None)
    assert chamadas["gerar"] == [[1]]
    assert r == {"para_ia": [1], "voltaram": []}
    assert p.dados["cenas"][0]["garantia"] is True


def test_imagem_de_ia_ruim_nao_e_feita_de_novo(tmp_path, monkeypatch):
    p, chamadas = preparar(monkeypatch, tmp_path, [ia(1, 10), ia(2, 70)], {1: 90})
    assert corrigir.garantir(p, log=lambda *_: None) == {"para_ia": [], "voltaram": []}
    assert chamadas["gerar"] == [] and chamadas["refazer"] == []


def test_ia_nova_pior_que_a_foto_devolve_a_foto(tmp_path, monkeypatch):
    p, chamadas = preparar(monkeypatch, tmp_path, [foto(1, 35)], {1: 20})
    corrigir.garantir(p, log=lambda *_: None)
    assert chamadas["voltou"] == [1]
    assert chamadas["refazer"] == []


def test_cena_da_pessoa_e_motion_ficam_de_fora(tmp_path, monkeypatch):
    cenas = [{**foto(1, 10), "imagem_da_pessoa": True}, {**foto(2, 10), "midia": {"fonte": "motion_ia", "id": "2"}}]
    p, chamadas = preparar(monkeypatch, tmp_path, cenas, {})
    assert corrigir.garantir(p, log=lambda *_: None) == {"para_ia": [], "voltaram": []}
    assert chamadas["gerar"] == [] and chamadas["refazer"] == []


def test_desligada_ou_sem_ia_nao_faz_nada(tmp_path, monkeypatch):
    p, _ = preparar(monkeypatch, tmp_path, [foto(1, 10)], {1: 90})
    p.config = {"corrigir": {"garantir": False}}
    assert corrigir.garantir(p, log=lambda *_: None) == {}


def test_a_garantia_nao_volta_para_o_banco_pelo_teto():
    assert imagens._prioridade_da_ia({"garantia": True, "ia_motivo": "x"}) == 0
