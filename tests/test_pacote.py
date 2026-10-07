"""Pacote do projeto: o que vai para o cliente e volta para a fábrica quando ele quer editar.

Medido no nunca-deve-ter-dentro-de-casa-parte-2 (30 min): 941 MB de pacote contra 6,2 GB de projeto. No teste offline
(teste-pacote), entregar, importar e renderizar de novo deu o mesmo vídeo, pixel a pixel e com o mesmo áudio."""
import json
import zipfile
from pathlib import Path

import pytest

from fabrica import pacote, projeto as modulo_projeto
from fabrica.config import RAIZ

PERFIL = RAIZ / "perfis" / "documentario.yaml"


def _vai(caminho, usados=(), com_mp3=()):
    return pacote._vai_no_pacote(Path(caminho), set(usados), set(com_mp3))


def test_fica_o_que_custa_refazer_e_sai_o_que_a_fabrica_refaz():
    assert _vai("cenas.json") and _vai("roteiro.txt") and _vai("custos_reais.json")
    assert _vai("narracao/bloco_000.mp3") and _vai("narracao/bloco_000.json")
    assert _vai("trilha/partitura.json") and _vai("animacoes/motion.json") and _vai("motion_ia/0006/partes.json")
    assert _vai("midia/0007.jpg", usados={"midia/0007.jpg"}) and _vai("imagens/0003.png", usados={"imagens/0003.png"})
    assert _vai("midia/escolha/cena_0007.json")  # cache da escolha: evita pagar o modelo de novo
    # refeito de graça
    assert not _vai("render/clipes/0001-abc.mp4") and not _vai("_previas/tela/0001.jpg")
    assert not _vai("final.mp4") and not _vai("narracao.wav") and not _vai("cenas_backup_20261006-103829.json")
    assert not _vai("animacoes/0004/clipe.mov") and not _vai("trilha/trilha.wav")
    assert not _vai("antigas/0065-20261006-105123.png") and not _vai("conferir/0001_0.jpg")
    # foto recusada ou de outra cena não vai
    assert not _vai("midia/0007_2.jpg", usados={"midia/0007.jpg"})


def test_narracao_vai_pelo_mp3_e_so_sem_ele_pelo_wav_bruto():
    assert not _vai("narracao/bloco_000_bruto.wav", com_mp3={"bloco_000"})
    assert not _vai("narracao/bloco_000.wav", com_mp3={"bloco_000"})
    assert _vai("narracao/bloco_001_bruto.wav", com_mp3={"bloco_000"})  # voz do computador: não há mp3


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    projetos = tmp_path / "projetos"
    monkeypatch.setattr(modulo_projeto, "PROJETOS", projetos)
    monkeypatch.setattr(pacote, "PROJETOS", projetos)
    monkeypatch.setattr(pacote, "ENTREGAS", tmp_path / "entregas")
    pasta = projetos / "video"
    (pasta / "midia").mkdir(parents=True)
    (pasta / "render" / "clipes").mkdir(parents=True)
    (pasta / "projeto.json").write_text(json.dumps({"nome": "video", "perfil": str(PERFIL), "offline": True}))
    (pasta / "roteiro.txt").write_text("Uma frase.", encoding="utf-8")
    (pasta / "cenas.json").write_text(json.dumps({"cenas": [
        {"n": 1, "midia": {"arquivo": "midia/0001.jpg", "fonte": "pexels", "id": "1"}}]}))
    (pasta / "midia" / "0001.jpg").write_bytes(b"foto usada")
    (pasta / "midia" / "0001_2.jpg").write_bytes(b"foto recusada")
    (pasta / "render" / "clipes" / "0001.mp4").write_bytes(b"clipe")
    (pasta / "final.mp4").write_bytes(b"video pronto")
    return tmp_path


def test_entregar_e_importar_de_volta(servidor):
    resumo = pacote.entregar(modulo_projeto.Projeto("video"), servidor / "cliente", log=lambda *_: None)
    assert not (servidor / "projetos" / "video").exists()
    assert (servidor / "entregas" / "video" / "final.mp4").read_bytes() == b"video pronto"
    with zipfile.ZipFile(resumo["pacote"]) as z:
        nomes = set(z.namelist())
    assert "projeto/midia/0001.jpg" in nomes and "projeto/midia/0001_2.jpg" not in nomes
    assert not any(n.startswith("projeto/render/") for n in nomes) and "projeto/final.mp4" not in nomes

    p = pacote.importar(Path(resumo["pacote"]), log=lambda *_: None)
    assert (p.pasta / "midia" / "0001.jpg").read_bytes() == b"foto usada"
    assert p.ler_json("cenas.json")["cenas"][0]["midia"]["arquivo"] == "midia/0001.jpg"


def test_importar_nao_passa_por_cima_de_projeto_existente(servidor):
    resumo = pacote.exportar(modulo_projeto.Projeto("video"), servidor / "cliente" / "video.zip", log=lambda *_: None)
    with pytest.raises(SystemExit):
        pacote.importar(Path(resumo["pacote"]), log=lambda *_: None)
    assert pacote.importar(Path(resumo["pacote"]), nome="video-2", log=lambda *_: None).nome == "video-2"


def test_pacote_com_caminho_para_fora_da_pasta_e_recusado(servidor):
    ruim = servidor / "ruim.zip"
    with zipfile.ZipFile(ruim, "w") as z:
        z.writestr(pacote.MANIFESTO, json.dumps({"versao": 1, "nome": "x", "perfil": "perfis/documentario.yaml"}))
        z.writestr("perfil.yaml", "nome: x\n")
        z.writestr("projeto/../../fora.txt", "invasão")
    with pytest.raises(SystemExit):
        pacote.importar(ruim, log=lambda *_: None)
    assert not (servidor / "fora.txt").exists()
    assert not (servidor / "projetos" / "x").exists()  # nada pela metade no servidor
