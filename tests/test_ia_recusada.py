"""Imagem de IA recusada pelo filtro de segurança: o pedido é reescrito, e a cena nunca fica vazia.

Caso real: nunca-deve-ter-dentro-de-casa-parte-2, cenas 65 e 66 ("petauro arrancando o próprio pelo"). O OpenAI
recusou, a imagem antiga já estava em antigas/ e o render parou com "Faltam imagens de 2 cenas"."""
from types import SimpleNamespace

import pytest

from fabrica import corrigir, imagens

RECUSA = ('OpenRouter falhou ao gerar a imagem (400): {"error":{"message":"Your request was rejected by the safety '
          'system. If you believe this is an error, contact us at help.openai.com')


class Projeto(SimpleNamespace):
    def ler_json(self, nome):
        return self.arquivos[nome]

    def salvar_json(self, nome, dados):
        self.arquivos[nome] = dados

    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.png"


def _projeto(tmp_path, cenas):
    (tmp_path / "imagens").mkdir()
    (tmp_path / "antigas").mkdir()
    return Projeto(pasta=tmp_path, arquivos={"cenas.json": {"cenas": cenas}}, offline=False,
                   perfil={"imagens": {"provedor": "openrouter"}}, config={})


def test_recusa_de_seguranca_e_reconhecida():
    assert imagens._recusa_de_seguranca(RuntimeError(RECUSA))
    assert not imagens._recusa_de_seguranca(RuntimeError("OpenRouter falhou ao gerar a imagem (502): bad gateway"))


def test_prompt_recusado_e_reescrito_uma_vez(monkeypatch, tmp_path):
    projeto = _projeto(tmp_path, [])
    pedidos = []

    def gerador(prompt, img):
        pedidos.append(prompt)
        if "pulled out" in prompt:
            raise RuntimeError(RECUSA)
        return b"png", {"provedor": "openrouter", "modelo": "m", "custo_usd": 0.005}

    monkeypatch.setattr(imagens, "_imagem_openrouter", gerador)
    monkeypatch.setattr(imagens, "prompt_final", lambda c, p, r: c["prompt"])
    monkeypatch.setattr(imagens, "_prompt_sem_recusa",
                        lambda p, c, prompt: "a sugar glider with thin, patchy fur, tense posture, soft light")
    monkeypatch.setattr("fabrica.custos_reais.registrar", lambda *a, **k: None)
    cena = {"n": 65, "personagem": False, "texto": "relatam casos de petauros que arrancam o próprio pelo",
            "prompt": "sugar glider back with fur pulled out, exposed skin"}
    imagens._gerar_uma(projeto, cena, [], 3)
    assert len(pedidos) == 2 and "patchy fur" in pedidos[1]
    assert projeto.imagem(65).exists()


def test_recusado_de_novo_desiste_sem_repetir(monkeypatch, tmp_path):
    projeto = _projeto(tmp_path, [])
    pedidos = []
    monkeypatch.setattr(imagens, "_imagem_openrouter", lambda prompt, img: pedidos.append(prompt) or (_ for _ in ()).throw(RuntimeError(RECUSA)))
    monkeypatch.setattr(imagens, "prompt_final", lambda c, p, r: c["prompt"])
    monkeypatch.setattr(imagens, "_prompt_sem_recusa", lambda p, c, prompt: "a calm sugar glider on a branch, soft light")
    cena = {"n": 65, "personagem": False, "texto": "", "prompt": "fur pulled out"}
    with pytest.raises(imagens.SemImagem):
        imagens._gerar_uma(projeto, cena, [], 3)
    assert len(pedidos) == 2  # o recusado e o reescrito; nada de repetir o mesmo pedido três vezes


def test_imagem_que_nao_saiu_devolve_a_antiga(tmp_path):
    antiga = tmp_path / "antigas" / "0065-20261006-105123.png"
    cenas = [{"n": 65, "tipo": "ia", "midia": None, "ia_reserva": {
        "midia": None, "tipo": "ia", "movidos": [[str(antiga), str(tmp_path / "imagens" / "0065.png")]]}}]
    projeto = _projeto(tmp_path, cenas)
    antiga.write_bytes(b"png antiga")
    assert corrigir._devolver_sem_imagem(projeto, {65}, log=lambda *_: None) == [65]
    assert projeto.imagem(65).read_bytes() == b"png antiga"
    cena = projeto.ler_json("cenas.json")["cenas"][0]
    assert cena["tipo"] == "ia" and "ia_reserva" not in cena and cena["captura"]["suspeita"]


def test_foto_do_banco_volta_quando_a_ia_nao_sai(tmp_path):
    antiga = tmp_path / "antigas" / "0166-x.jpg"
    (tmp_path / "midia").mkdir()
    midia = {"fonte": "pexels", "id": "1", "arquivo": "midia/0166.jpg"}
    cenas = [{"n": 166, "tipo": "ia", "midia": None, "ia_reserva": {
        "midia": midia, "tipo": "foto_real", "busca": "sugar glider",
        "movidos": [[str(antiga), str(tmp_path / "midia" / "0166.jpg")]]}}]
    projeto = _projeto(tmp_path, cenas)
    antiga.write_bytes(b"jpg")
    corrigir._devolver_sem_imagem(projeto, {166}, log=lambda *_: None)
    cena = projeto.ler_json("cenas.json")["cenas"][0]
    assert cena["midia"] == midia and cena["tipo"] == "foto_real"
    assert (tmp_path / "midia" / "0166.jpg").exists()


def test_imagem_nova_que_saiu_fica(tmp_path):
    antiga = tmp_path / "antigas" / "0065-x.png"
    cenas = [{"n": 65, "tipo": "ia", "midia": None, "ia_reserva": {
        "midia": None, "movidos": [[str(antiga), str(tmp_path / "imagens" / "0065.png")]]}}]
    projeto = _projeto(tmp_path, cenas)
    antiga.write_bytes(b"antiga")
    projeto.imagem(65).write_bytes(b"nova")
    assert corrigir._devolver_sem_imagem(projeto, {65}, log=lambda *_: None) == []
    assert projeto.imagem(65).read_bytes() == b"nova"
