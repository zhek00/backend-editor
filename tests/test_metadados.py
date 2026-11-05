"""Metadados do YouTube dentro dos MP4 e nomes pelo título (metadados.py), com vídeo de verdade feito pelo FFmpeg."""
import json
import os
import shutil
import subprocess

import pytest

from fabrica import entrega_pc, metadados

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not FFMPEG, reason="sem ffmpeg nesta máquina")


class ProjetoFalso:
    def __init__(self, pasta, destino):
        self.nome = "teste-metadados"
        self.pasta = pasta
        self.perfil = {"nome": "Canada Insight"}
        self.config = {"entrega_pc": {"ativo": True, "pasta": str(destino), "so_o_video": True}}
        self.dados = {}

    def existe(self, nome):
        return (self.pasta / nome).exists()

    def ler_json(self, nome):
        return json.loads((self.pasta / nome).read_text(encoding="utf-8"))

    def salvar_json(self, nome, dados):
        (self.pasta / nome).parent.mkdir(parents=True, exist_ok=True)
        (self.pasta / nome).write_text(json.dumps(dados), encoding="utf-8")


def _video(caminho):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=1",
                    "-f", "lavfi", "-i", "sine=d=1", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(caminho)],
                   check=True)


def _etiquetas(caminho):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags:stream=codec_type:stream_tags=language",
                        "-of", "json", str(caminho)], capture_output=True, check=True)
    dados = json.loads(r.stdout.decode("utf-8"))
    audio = [s.get("tags", {}).get("language") for s in dados.get("streams", []) if s.get("codec_type") == "audio"]
    return dados["format"].get("tags", {}), audio


def _projeto(tmp_path, titulo="Dollarama: 15 coisas que você precisa comprar?"):
    pasta, destino = tmp_path / "projeto", tmp_path / "Downloads"
    pasta.mkdir()
    _video(pasta / "final.mp4")
    (pasta / "roteiro.txt").write_text("Hoje você vai conhecer as lojas mais baratas do Canadá e o que vale a pena "
                                       "comprar nelas, com os preços de cada uma.", encoding="utf-8")
    (pasta / "publicacao.json").write_text(json.dumps({
        "titulo": titulo, "descricao": "Resumo do vídeo.\n\nCapítulos\n0:00 Abertura\n0:20 Preços",
        "tags": ["dollarama", "canada", "lojas baratas"], "hashtags": ["#canada"]}), encoding="utf-8")
    return ProjetoFalso(pasta, destino), destino


def test_grava_titulo_descricao_tags_e_canal_dentro_do_mp4(tmp_path):
    projeto, _ = _projeto(tmp_path)
    data = (projeto.pasta / "final.mp4").stat().st_mtime_ns
    assert metadados.gravar(projeto, log=lambda *_: None) == 1
    tags, audio = _etiquetas(projeto.pasta / "final.mp4")
    assert tags["title"] == "Dollarama: 15 coisas que você precisa comprar?"  # o título exato, com : e ?
    assert tags["artist"] == "Canada Insight"
    assert "0:20 Preços" in tags["description"] and "0:20 Preços" in tags["comment"]
    assert tags["keywords"] == "dollarama, canada, lojas baratas"
    assert audio == ["por"]
    # a revisão do vídeo pronto e a checagem do FFmpeg reconhecem o final.mp4 pela data: ela não pode mudar
    assert (projeto.pasta / "final.mp4").stat().st_mtime_ns == data
    assert not list(projeto.pasta.glob("*.tmp*"))  # o temporário da troca não fica para trás


def test_rodar_de_novo_sem_mudanca_nao_mexe_no_arquivo_e_titulo_novo_grava(tmp_path):
    projeto, _ = _projeto(tmp_path)
    metadados.gravar(projeto, log=lambda *_: None)
    assert metadados.gravar(projeto, log=lambda *_: None) == 0
    projeto.dados = {"titulo_entrega": "Meu título exato"}  # o que a pessoa escreveu vence o do kit
    assert metadados.gravar(projeto, log=lambda *_: None) == 1
    assert _etiquetas(projeto.pasta / "final.mp4")[0]["title"] == "Meu título exato"


def test_render_novo_ganha_os_metadados_de_novo(tmp_path):
    projeto, _ = _projeto(tmp_path)
    metadados.gravar(projeto, log=lambda *_: None)
    _video(projeto.pasta / "final.mp4")  # um render novo escreve o final.mp4 sem os metadados
    os.utime(projeto.pasta / "final.mp4", ns=(1, 2_000_000_000_000_000_000))
    assert metadados.gravar(projeto, log=lambda *_: None) == 1
    assert _etiquetas(projeto.pasta / "final.mp4")[0]["title"].startswith("Dollarama")


def test_entrega_so_o_video_sai_com_titulo_exato_e_metadados(tmp_path):
    projeto, destino = _projeto(tmp_path)
    video = entrega_pc.entregar(projeto, log=lambda *_: None)
    assert video.name == "Dollarama꞉ 15 coisas que você precisa comprar？.mp4"
    assert sorted(x.name for x in video.parent.iterdir()) == sorted([video.name, "descricao.txt"])
    assert os.path.samefile(video, projeto.pasta / "final.mp4")  # continua link físico, sem ocupar espaço de novo
    assert _etiquetas(video)[0]["title"] == "Dollarama: 15 coisas que você precisa comprar?"


def test_shorts_e_versao_em_pe_levam_o_proprio_titulo(tmp_path):
    projeto, _ = _projeto(tmp_path)
    _video(projeto.pasta / "final_vertical.mp4")
    (projeto.pasta / "shorts").mkdir()
    _video(projeto.pasta / "shorts" / "S01.mp4")
    projeto.salvar_json("shorts/shorts.json", {"shorts": [{
        "id": "S01", "arquivo": "shorts/S01.mp4", "titulo": "O *segredo* do preço",
        "titulo_post": "O segredo do preço baixo #shorts", "descricao": "Vídeo completo no canal"}]})
    metadados.gravar(projeto, log=lambda *_: None)
    assert _etiquetas(projeto.pasta / "shorts" / "S01.mp4")[0]["title"] == "O segredo do preço baixo"
    assert _etiquetas(projeto.pasta / "final_vertical.mp4")[0]["keywords"] == "dollarama, canada, lojas baratas"
    nomes = metadados.nomes(projeto)
    assert nomes["final.mp4"] == "Dollarama꞉ 15 coisas que você precisa comprar？.mp4"
    assert nomes["final_vertical.mp4"] == "Dollarama꞉ 15 coisas que você precisa comprar？ (em pé).mp4"
    assert nomes["shorts/S01.mp4"] == "O segredo do preço baixo.mp4"
    assert metadados.nome_para_baixar(projeto, "shorts/S01.mp4") == "O segredo do preço baixo.mp4"
    assert metadados.nome_para_baixar(projeto, "midia/0001.jpg") is None  # o resto baixa com o nome de sempre


def test_entrega_completa_poe_shorts_e_thumbnail_com_titulo(tmp_path):
    projeto, _ = _projeto(tmp_path)
    projeto.config["entrega_pc"]["so_o_video"] = False
    (projeto.pasta / "thumbnail.jpg").write_bytes(b"jpg")
    (projeto.pasta / "shorts").mkdir()
    _video(projeto.pasta / "shorts" / "S01.mp4")
    projeto.salvar_json("shorts/shorts.json", {"shorts": [{
        "id": "S01", "arquivo": "shorts/S01.mp4", "titulo_post": "O segredo do preço baixo #shorts"}]})
    pasta = entrega_pc.entregar(projeto, log=lambda *_: None).parent
    assert [x.name for x in (pasta / "shorts").iterdir()] == ["O segredo do preço baixo.mp4"]
    assert (pasta / "Dollarama꞉ 15 coisas que você precisa comprar？.jpg").exists()
    # de volta para só o vídeo: a thumbnail e os shorts saem da pasta
    projeto.config["entrega_pc"]["so_o_video"] = True
    video = entrega_pc.entregar(projeto, log=lambda *_: None)
    assert sorted(x.name for x in pasta.iterdir()) == sorted([video.name, "descricao.txt"])


def test_arquivo_que_nao_e_video_nao_derruba_a_entrega(tmp_path):
    projeto, _ = _projeto(tmp_path)
    (projeto.pasta / "final.mp4").write_bytes(b"isto nao e um video")
    avisos = []
    assert metadados.gravar(projeto, log=avisos.append) == 0
    assert "não gravados" in avisos[0]
    assert (projeto.pasta / "final.mp4").read_bytes() == b"isto nao e um video"
    assert not list(projeto.pasta.glob("*.tmp*"))
