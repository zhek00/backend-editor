"""Teto de imagem de IA (ia.teto, 35%), pedido do usuário em 2026-10-15: o everything-you-need-to-answer saiu com 54%
de imagens de IA (183 de 340 cenas). A IA fica com quem mais precisa; o resto busca foto do assunto no banco.
Sem rede e sem custo: a busca no banco é trocada por uma resposta pronta."""
from types import SimpleNamespace

from fabrica import imagens, midia


class Projeto(SimpleNamespace):
    def ler_json(self, nome):
        return self.arquivos[nome]

    def salvar_json(self, nome, dados):
        self.arquivos[nome] = dados

    def imagem(self, n):
        return self.pasta / f"{n:04d}.png"


def _projeto(tmp_path, cenas, teto=0.35, com_imagem=()):
    for n in com_imagem:
        (tmp_path / f"{n:04d}.png").write_bytes(b"ia")
    return Projeto(pasta=tmp_path, offline=False, arquivos={"cenas.json": {"cenas": cenas}},
                   config={"ia": {"ativa": True, "teto": teto}})


def _cena(n, **extra):
    return {"n": n, "tipo": "ia", "busca": "", "busca_reserva": f"busca {n}", "onde_existe": "banco", **extra}


def _banco(acha):
    """A busca no banco: as cenas em `acha` ganham foto; guarda quem foi buscado."""
    buscadas = []

    def buscar(projeto, apenas=None, log=print, permissivo=False):
        buscadas.extend(sorted(apenas))
        for c in projeto.arquivos["cenas.json"]["cenas"]:
            if c["n"] in apenas and c["n"] in acha:
                c["midia"] = {"fonte": "pexels", "arquivo": f"midia/{c['n']:04d}.jpg", "tipo": "foto"}
    return buscar, buscadas


def test_a_ia_fica_com_quem_mais_precisa_e_o_resto_vai_ao_banco(tmp_path, monkeypatch):
    # 10 cenas, teto de 35%: 3 vagas de IA
    cenas = [_cena(1), _cena(2, onde_existe="nao_existe"), _cena(3, ia_motivo="o Jev reprovou", ia_reserva={}),
             _cena(4), _cena(5, prompt_manual="a pessoa pediu"), _cena(6), _cena(7, epoca="1898")]
    cenas += [{"n": n, "tipo": "foto_real", "midia": {"fonte": "pexels"}} for n in (8, 9, 10)]
    p = _projeto(tmp_path, cenas)
    buscar, buscadas = _banco(acha={1, 4, 6, 7})
    monkeypatch.setattr(midia, "buscar", buscar)
    seguem = imagens._teto_da_ia(p, [c for c in cenas if c["n"] <= 7], log=lambda *_: None)
    # a escolha da pessoa sempre fica; depois o que ninguém fotografou e a foto reprovada
    assert sorted(c["n"] for c in seguem) == [2, 3, 5]
    # época e as comuns foram ao banco
    assert buscadas == [1, 4, 6, 7]


def test_vagas_contam_as_imagens_de_ia_que_ja_estao_no_video(tmp_path, monkeypatch):
    cenas = [_cena(n) for n in range(1, 11)]
    p = _projeto(tmp_path, cenas, com_imagem=(1, 2, 3))  # 3 já têm imagem de IA: as 3 vagas acabaram
    buscar, buscadas = _banco(acha=set(range(4, 11)))
    monkeypatch.setattr(midia, "buscar", buscar)
    seguem = imagens._teto_da_ia(p, [c for c in cenas if c["n"] >= 4], log=lambda *_: None)
    assert seguem == [] and buscadas == list(range(4, 11))


def test_a_cena_que_vai_ao_banco_perde_o_exato_e_ganha_a_busca(tmp_path, monkeypatch):
    # o exato era a busca inteira e não deixava passar nenhum candidato (cena 3 do everything-you-need-to-answer)
    cenas = [_cena(1, onde_existe="nao_existe"), _cena(2, exato="Lidl UK roast chicken hot counter")]
    cenas += [{"n": n, "tipo": "foto_real", "midia": {"fonte": "pexels"}} for n in range(3, 5)]
    p = _projeto(tmp_path, cenas, teto=0.25)  # 4 cenas: 1 vaga
    buscar, _ = _banco(acha={2})
    monkeypatch.setattr(midia, "buscar", buscar)
    imagens._teto_da_ia(p, cenas[:2], log=lambda *_: None)
    c = p.arquivos["cenas.json"]["cenas"][1]
    assert c["teto_ia"] and c["tipo"] == "foto_real" and c["busca"] == "busca 2"
    assert c["exato"] == "" and c["exato_original"] == "Lidl UK roast chicken hot counter"
    assert midia.exigido_da_cena({}, c) == set()  # vazio: qualquer foto do assunto serve, sem deduzir "Lidl"


def test_sem_foto_do_assunto_vai_para_a_ia_e_nao_volta_ao_banco(tmp_path, monkeypatch):
    cenas = [_cena(1, onde_existe="nao_existe"), _cena(2)]
    cenas += [{"n": n, "tipo": "foto_real", "midia": {"fonte": "pexels"}} for n in range(3, 5)]
    p = _projeto(tmp_path, cenas, teto=0.25)
    buscar, buscadas = _banco(acha=set())  # o banco não tem nem foto do assunto
    monkeypatch.setattr(midia, "buscar", buscar)
    seguem = imagens._teto_da_ia(p, cenas[:2], log=lambda *_: None)
    assert sorted(c["n"] for c in seguem) == [1, 2]  # cena vazia trava o render: vai para a IA
    assert p.arquivos["cenas.json"]["cenas"][1]["sem_midia_real"] is True
    # depois (a foto do assunto reprovada pelo Jev, por exemplo), a cena não vai ao banco de novo
    buscadas.clear()
    seguem = imagens._teto_da_ia(p, [p.arquivos["cenas.json"]["cenas"][1]], log=lambda *_: None)
    assert [c["n"] for c in seguem] == [2] and buscadas == []


def test_sem_teto_ou_offline_nada_muda(tmp_path, monkeypatch):
    cenas = [_cena(n) for n in range(1, 5)]
    monkeypatch.setattr(midia, "buscar", lambda *a, **k: (_ for _ in ()).throw(AssertionError("não buscar")))
    p = _projeto(tmp_path, cenas, teto=0)
    assert imagens._teto_da_ia(p, cenas, log=lambda *_: None) == cenas
    p = _projeto(tmp_path, cenas)
    p.offline = True
    assert imagens._teto_da_ia(p, cenas, log=lambda *_: None) == cenas
    p = _projeto(tmp_path, cenas)
    p.config["ia"]["ativa"] = False
    assert imagens._teto_da_ia(p, cenas, log=lambda *_: None) == cenas


def test_cena_reprovada_pelo_jev_vai_para_a_ia_mesmo_com_o_teto_cheio(tmp_path, monkeypatch):
    # "o vídeo jamais deve ter cenas vazias": com as vagas acabadas, a foto reprovada pelo Jev vira IA, sem voltar ao
    # banco (onde entraria uma foto do assunto sem julgamento)
    cenas = [_cena(n) for n in range(1, 11)]
    cenas[4].update(ia_motivo="o Jev deu 10% de chance de combinar com a narração", ia_reserva={"midia": {}})
    p = _projeto(tmp_path, cenas, com_imagem=(1, 2, 3))  # as 3 vagas (35% de 10) já estão ocupadas
    buscar, buscadas = _banco(acha=set(range(1, 11)))
    monkeypatch.setattr(midia, "buscar", buscar)
    seguem = imagens._teto_da_ia(p, cenas[3:], log=lambda *_: None)
    assert [c["n"] for c in seguem] == [5]
    assert 5 not in buscadas and buscadas == [4, 6, 7, 8, 9, 10]
