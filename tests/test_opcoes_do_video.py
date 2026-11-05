"""As escolhas da Nova produção que valem só para um vídeo: perfil, ritmo, acervo, transição, camada e som."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from fabrica import animacoes, camadas, midia, projeto as modulo_projeto, render


def _projeto_em(tmp_path, monkeypatch, dados):
    monkeypatch.setattr(modulo_projeto, "PROJETOS", tmp_path)
    monkeypatch.setattr(modulo_projeto, "carregar_perfil", lambda _c: {"visual": "documentario", "avatar": {"ativo": True, "modo": "x"},
                                                                     "musica": "faixas/"})
    (tmp_path / "v").mkdir()
    (tmp_path / "v" / "projeto.json").write_text(json.dumps({"nome": "v", "perfil": "p.yaml", "offline": True, **dados}), encoding="utf-8")
    return modulo_projeto.Projeto("v")


def test_perfil_do_video_vale_por_cima_do_canal(tmp_path, monkeypatch):
    p = _projeto_em(tmp_path, monkeypatch, {"perfil_override": {"visual": "cinema", "avatar": {"ativo": False}, "musica": None}})
    assert p.perfil["visual"] == "cinema" and p.perfil["musica"] is None
    assert p.perfil["avatar"] == {"ativo": False, "modo": "x"}  # só o que o pedido escolheu muda


def test_sem_pedido_o_perfil_fica_igual(tmp_path, monkeypatch):
    p = _projeto_em(tmp_path, monkeypatch, {})
    assert p.perfil["visual"] == "documentario" and p.perfil["musica"] == "faixas/"


def test_configuracao_so_ganha_chave_quando_pedida():
    """O cfg entra no nome de cada clipe: chave nova em projeto antigo mandaria refazer tudo."""
    base = SimpleNamespace(config={"render": {}}, perfil={})
    assert "transicao" not in render.configuracao(base) and "camada" not in render.configuracao(base)
    pedido = SimpleNamespace(config={"render": {}}, perfil={"transicao": "brasa", "camada": "poeira"})
    assert render.configuracao(pedido)["transicao"] == "brasa" and render.configuracao(pedido)["camada"] == "poeira"
    errado = SimpleNamespace(config={"render": {}}, perfil={"transicao": "inventada", "camada": "fogo"})
    assert "transicao" not in render.configuracao(errado) and "camada" not in render.configuracao(errado)


def test_transicao_entra_e_sai_na_cor_do_nome():
    filtro = render._com_transicao("x", {"transicao": "branco"}, 120, 30)
    assert "fade=t=in:st=0:d=0.1:color=white" in filtro and "fade=t=out:st=3.900:d=0.1:color=white" in filtro


def test_corte_seco_nao_mexe_no_filtro():
    assert render._com_transicao("x", {}, 120, 30) == "x"


class _Buscador(midia.Buscador):
    def __init__(self, acervo):
        self.projeto = SimpleNamespace(config={"midia": {"acervo": acervo}})
        self.cfg = {"fontes_foto": ["wikimedia", "pexels", "harvard", "nypl"]}
        self.quantidade = 12
        self.pedidas = []

    def _buscar(self, fonte, tipo, busca):
        self.pedidas.append(fonte)
        return []


@pytest.mark.parametrize("modo, cena_de_acervo, ve_museu", [("sem", True, False), ("sem", "epoca", False), ("sempre", False, True),
                                                           (None, False, False), (None, True, True)])
def test_modo_de_acervo(modo, cena_de_acervo, ve_museu):
    b = _Buscador(modo)
    b._das_fontes("foto", "leão", acervo=cena_de_acervo)
    assert ("harvard" in b.pedidas) is ve_museu


def test_som_nos_textos_vem_desligado():
    projeto = SimpleNamespace(config={"animacoes": {}}, perfil={})
    assert animacoes.sons_na_linha(projeto) == []


def test_som_segue_o_tipo_da_animacao(monkeypatch):
    projeto = SimpleNamespace(config={"animacoes": {"som": True}}, perfil={})
    monkeypatch.setattr(animacoes, "validas", lambda _p: [{"ini": 1.0, "modelo": "numero"}, {"ini": 9.0, "modelo": "frase"},
                                                         {"ini": 15.0, "modelo": "lista"}])
    monkeypatch.setattr(camadas, "som", lambda nome: nome)
    assert animacoes.sons_na_linha(projeto, lambda _m: None) == [(1.0, "contador"), (9.0, "pop"), (15.0, "passagem")]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem FFmpeg")
@pytest.mark.parametrize("nome", ["pop", "passagem", "contador"])
def test_sons_saem_do_ffmpeg(tmp_path, monkeypatch, nome):
    monkeypatch.setattr(camadas, "PASTA", tmp_path)
    arquivo = camadas.som(nome)
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(arquivo)],
                       capture_output=True, text=True)
    assert 0.1 < float(r.stdout) < 1


def test_laco_fecha_sem_emenda():
    """t=0 e t=1 têm de ser o mesmo quadro, senão as partículas pulam a cada volta do laço."""
    import numpy as np

    cfg = camadas.PARTICULAS["poeira"]
    sementes = (np.array([100.0, 500.0]), np.array([100.0, 300.0]), np.array([1, 2]), np.array([0.1, 0.7]), np.array([2.0, 2.0]))
    assert (camadas._quadro(cfg, sementes, 0.0) == camadas._quadro(cfg, sementes, 1.0)).all()


def test_varias_cenas_pedindo_o_laco_juntas_gravam_uma_vez(tmp_path, monkeypatch):
    """No primeiro render de verdade: WinError 32, todas as cenas gravando o mesmo arquivo ao mesmo tempo."""
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(camadas, "PASTA", tmp_path)
    gravadas = []

    def gravar(nome, destino):
        gravadas.append(nome)
        destino.write_bytes(b"x")

    monkeypatch.setattr(camadas, "_gravar_laco", gravar)
    with ThreadPoolExecutor(6) as executor:
        arquivos = list(executor.map(lambda _i: camadas.laco("brasas"), range(6)))
    assert gravadas == ["brasas"] and len(set(arquivos)) == 1
