"""As imagens de IA saem enquanto a conferência roda, em vez de em ondas depois dela (pedido de 2026-11-09)."""
import time
from types import SimpleNamespace

from fabrica import banco_proprio, imagens, midia


class Projeto(SimpleNamespace):
    def ler_json(self, nome):
        return {"cenas": self.cenas}

    def imagem(self, n):
        return self.pasta / f"{n:04d}.png"


def _projeto(tmp_path, cenas):
    return Projeto(pasta=tmp_path, nome="p", offline=False, config={"imagens": {"processos": 4}},
                   perfil={"imagens": {"provedor": "openrouter"}}, cenas=cenas)


def _cena(n, bloco, ia=True, personagem=False):
    return {"n": n, "bloco": bloco, "tipo": "ia" if ia else "foto_real", "personagem": personagem}


def test_gera_durante_a_conferencia_e_deixa_trecho_e_personagem_para_depois(monkeypatch, tmp_path):
    feitas = []
    monkeypatch.setattr(midia, "ia_ativa", lambda p: True)
    monkeypatch.setattr(midia, "precisa_ia", lambda c: c["tipo"] == "ia")
    monkeypatch.setattr(banco_proprio, "atender", lambda p, pend, log=print: pend)

    def gerar_uma(projeto, cena, refs, tentativas):
        feitas.append(cena["n"])
        projeto.imagem(cena["n"]).write_bytes(b"png")
    monkeypatch.setattr(imagens, "_gerar_uma", gerar_uma)
    cenas = [_cena(1, "a", ia=False), _cena(2, "a"), _cena(3, "b", ia=False),
             _cena(5, "c"), _cena(6, "c"),                      # trecho de IA seguido: fica para o gerar
             _cena(8, "d", ia=False), _cena(9, "d", personagem=True), _cena(11, "e", ia=False)]
    p = _projeto(tmp_path, cenas)
    with imagens.ao_fundo(p, log=lambda *a: None, intervalo=0.05):
        time.sleep(0.2)
        p.cenas.append(_cena(13, "f"))                           # a conferência mandou mais uma para a IA no meio
        time.sleep(0.3)
    assert sorted(feitas) == [2, 13]


def test_nao_repete_a_que_as_adiantadas_ja_levaram(monkeypatch, tmp_path):
    feitas = []
    monkeypatch.setattr(midia, "ia_ativa", lambda p: True)
    monkeypatch.setattr(midia, "precisa_ia", lambda c: c["tipo"] == "ia")
    monkeypatch.setattr(banco_proprio, "atender", lambda p, pend, log=print: pend)
    monkeypatch.setattr(imagens, "_gerar_uma", lambda projeto, cena, refs, t: feitas.append(cena["n"]))
    monkeypatch.setitem(imagens._ADIANTADAS, "p", {2})
    p = _projeto(tmp_path, [_cena(2, "a"), _cena(4, "b")])
    with imagens.ao_fundo(p, log=lambda *a: None, intervalo=0.05):
        time.sleep(0.2)
    assert feitas == [4]


def test_sem_cota_para_o_fundo_sem_parar_o_video(monkeypatch, tmp_path):
    monkeypatch.setattr(midia, "ia_ativa", lambda p: True)
    monkeypatch.setattr(midia, "precisa_ia", lambda c: c["tipo"] == "ia")
    monkeypatch.setattr(banco_proprio, "atender", lambda p, pend, log=print: pend)
    monkeypatch.setattr(imagens, "_gerar_uma", lambda *a: (_ for _ in ()).throw(imagens.SemCota("acabou")))
    p = _projeto(tmp_path, [_cena(2, "a"), _cena(4, "b")])
    with imagens.ao_fundo(p, log=lambda *a: None, intervalo=0.05):
        time.sleep(0.2)                                          # sai sem erro: o imagens.gerar de depois resolve
