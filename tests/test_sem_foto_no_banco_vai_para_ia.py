"""A cena de acervo que terminou a esteira sem nenhuma foto no banco vira cena de IA, em vez de parar o vídeo.

Caso real: 20-gigantes-da-era-do-gelo (2026-11-01), cena 376 ("museum collection"). Ela foi devolvida ao banco pelo
teto de imagem de IA, no banco não havia foto do assunto, e como `tipo` continuou foto_real ela não era imagem de IA
pendente (midia.precisa_ia): a criação parou em 94% depois de 3h28 com o recado "ou ligue a IA no config.yaml",
com a IA já ligada."""
import json
from pathlib import Path
from types import SimpleNamespace

from fabrica import api


class Projeto(SimpleNamespace):
    def ler_json(self, nome):
        return json.loads(json.dumps(self.arquivos[nome]))

    def salvar_json(self, nome, dados):
        self.arquivos[nome] = dados

    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.png"


def _projeto(tmp_path, cenas, com_imagem=()):
    (tmp_path / "imagens").mkdir()
    for n in com_imagem:
        (tmp_path / "imagens" / f"{n:04d}.png").write_bytes(b"png")
    return Projeto(pasta=Path(tmp_path), arquivos={"cenas.json": {"cenas": cenas}})


def test_cena_real_sem_foto_nenhuma_vira_imagem_de_ia(tmp_path):
    cenas = [{"n": 376, "tipo": "foto_real", "midia": None, "busca": "Copenhagen museum fossils",
              "sujeito": "museum collection"}]
    p = _projeto(tmp_path, cenas)
    assert api.cenas_sem_arquivo(p) == [376]
    assert api._marcar_sem_foto_no_banco(p, log=lambda *_: None) == [376]
    assert p.arquivos["cenas.json"]["cenas"][0]["sem_midia_real"] is True


def test_cena_que_ja_tem_imagem_ou_foto_nao_e_mexida(tmp_path):
    cenas = [{"n": 1, "tipo": "foto_real", "midia": {"fonte": "pexels", "arquivo": "midia/0001.jpg"}},
             {"n": 2, "tipo": "ia", "midia": None},                       # de IA: já é pendente da IA
             {"n": 3, "tipo": "foto_real", "midia": None}]                # esta sim, sem foto nenhuma
    p = _projeto(tmp_path, cenas, com_imagem=(2,))
    (tmp_path / "midia").mkdir()
    (tmp_path / "midia" / "0001.jpg").write_bytes(b"jpg")
    assert api._marcar_sem_foto_no_banco(p, log=lambda *_: None) == [3]
    salvas = {c["n"]: c for c in p.arquivos["cenas.json"]["cenas"]}
    assert salvas[3]["sem_midia_real"] is True
    assert not salvas[1].get("sem_midia_real") and not salvas[2].get("sem_midia_real")


def test_sem_nada_para_marcar_nao_grava_o_json(tmp_path):
    cenas = [{"n": 1, "tipo": "ia", "midia": None}]
    p = _projeto(tmp_path, cenas, com_imagem=(1,))
    antes = p.arquivos["cenas.json"]
    assert api._marcar_sem_foto_no_banco(p, log=lambda *_: None) == []
    assert p.arquivos["cenas.json"] is antes
