"""As imagens de IA começam junto com a busca, sem escrever no cenas.json e sem passar do teto."""
from pathlib import Path

from fabrica import banco_proprio, imagens, midia


class Projeto:
    offline, nome, perfil = False, "teste", {}

    def __init__(self, pasta, cenas, config=None):
        self.pasta, self.cenas, self.config, self.gravou = pasta, cenas, config or {}, False

    def ler_json(self, _nome):
        return {"cenas": self.cenas}

    def salvar_json(self, *_a):
        self.gravou = True

    def imagem(self, n) -> Path:
        return self.pasta / f"{n:04d}.png"


def preparar(monkeypatch, teto=0.5):
    feitas = []
    monkeypatch.setattr(midia, "ia_ativa", lambda _p: True)
    monkeypatch.setattr(midia, "teto_da_ia", lambda _p: teto)
    monkeypatch.setattr(imagens, "prompts_em_sequencia", lambda *_a: 0)
    monkeypatch.setattr(banco_proprio, "atender", lambda _p, pend, _l: pend)
    monkeypatch.setattr(imagens, "_gerar_uma", lambda _p, c, *_a: feitas.append(c["n"]))
    return feitas


def cenas(n=10, **extra):
    return [{"n": i, "tipo": "ia", "personagem": False, **extra} for i in range(1, n + 1)]


def test_gera_so_a_folga_do_teto(tmp_path, monkeypatch):
    feitas = preparar(monkeypatch, teto=0.5)
    imagens.adiantar(Projeto(tmp_path, cenas()), log=lambda *_: None).join()
    assert len(feitas) == 3  # 50% de 10 cenas, 70% dessas vagas


def test_personagem_e_cena_real_ficam_para_depois(tmp_path, monkeypatch):
    feitas = preparar(monkeypatch, teto=0)
    lista = cenas(3) + [{"n": 4, "tipo": "foto_real", "personagem": False}, {"n": 5, "tipo": "ia", "personagem": True}]
    imagens.adiantar(Projeto(tmp_path, lista), log=lambda *_: None).join()
    assert sorted(feitas) == [1, 2, 3]


def test_a_cena_que_ja_tem_imagem_nao_gera_de_novo(tmp_path, monkeypatch):
    feitas = preparar(monkeypatch, teto=0)
    (tmp_path / "0001.png").write_bytes(b"x")
    imagens.adiantar(Projeto(tmp_path, cenas(2)), log=lambda *_: None).join()
    assert feitas == [2]


def test_a_linha_nao_escreve_no_cenas_json(tmp_path, monkeypatch):
    preparar(monkeypatch, teto=0)
    p = Projeto(tmp_path, cenas(3))
    imagens.adiantar(p, log=lambda *_: None).join()
    assert not p.gravou


def test_falha_de_uma_cena_nao_para_as_outras(tmp_path, monkeypatch):
    feitas = preparar(monkeypatch, teto=0)

    def gerar(_p, c, *_a):
        if c["n"] == 1:
            raise RuntimeError("provedor fora")
        feitas.append(c["n"])
    monkeypatch.setattr(imagens, "_gerar_uma", gerar)
    imagens.adiantar(Projeto(tmp_path, cenas(3)), log=lambda *_: None).join()
    assert sorted(feitas) == [2, 3]


def test_desligado_ou_offline_nao_comeca(tmp_path, monkeypatch):
    preparar(monkeypatch)
    assert imagens.adiantar(Projeto(tmp_path, cenas(), {"imagens": {"adiantar": False}}), log=lambda *_: None) is None
    p = Projeto(tmp_path, cenas())
    p.offline = True
    assert imagens.adiantar(p, log=lambda *_: None) is None
