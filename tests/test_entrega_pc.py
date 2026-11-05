"""Entrega no computador (entrega_pc) e texto fixo do canal na descrição (publicacao.texto_fixo)."""
import json
import os

from fabrica import entrega_pc, publicacao


class ProjetoFalso:
    def __init__(self, pasta, destino, perfil=None):
        self.nome = "teste-entrega"
        self.pasta = pasta
        self.perfil = perfil if perfil is not None else {"nome": "Canada Insight"}
        self.config = {"entrega_pc": {"ativo": True, "pasta": str(destino), "so_o_video": False}}
        self.dados = {}

    def existe(self, nome):
        return (self.pasta / nome).exists()

    def ler_json(self, nome):
        return json.loads((self.pasta / nome).read_text(encoding="utf-8"))

    def salvar_json(self, nome, dados):
        (self.pasta / nome).write_text(json.dumps(dados), encoding="utf-8")


def _projeto(tmp_path, titulo="Dollarama: 15 coisas?"):
    pasta, destino = tmp_path / "projeto", tmp_path / "Downloads"
    pasta.mkdir()
    (pasta / "final.mp4").write_bytes(b"video" * 100)
    (pasta / "thumbnail.jpg").write_bytes(b"jpg")
    (pasta / "publicacao.json").write_text(json.dumps({
        "titulo": titulo, "titulos_alt": ["Outro título"], "descricao": "Texto do canal\n\nResumo\n\nCapítulos\n0:00 Abertura",
        "tags": ["dollarama", "canada"], "hashtags": ["#canada"], "comentario_fixado": "Qual você compra?",
        "sintetico": False}), encoding="utf-8")
    return ProjetoFalso(pasta, destino), destino


def test_entrega_cria_a_pasta_com_video_descricao_e_publicacao(tmp_path):
    projeto, destino = _projeto(tmp_path)
    video = entrega_pc.entregar(projeto, log=lambda *_: None)
    pasta = video.parent
    assert pasta.parent == destino / "Canada Insight" and pasta.name.endswith("__teste-entrega_ENTREGA")
    assert video.name == "Dollarama꞉ 15 coisas？.mp4"  # o título inteiro, com parecidos no lugar do que o Windows recusa
    assert os.path.samefile(video, projeto.pasta / "final.mp4")  # link físico: não ocupa espaço de novo
    assert (pasta / "descricao.txt").read_text(encoding="utf-8").startswith("Texto do canal")
    publicacao_txt = (pasta / "publicacao.txt").read_text(encoding="utf-8")
    assert "dollarama, canada" in publicacao_txt and "Qual você compra?" in publicacao_txt
    assert (pasta / "Dollarama꞉ 15 coisas？.jpg").exists()  # a thumbnail com o título, nunca thumbnail.jpg
    assert not (pasta / "thumbnail.jpg").exists()


def test_titulo_novo_renomeia_a_mesma_pasta(tmp_path):
    projeto, destino = _projeto(tmp_path)
    entrega_pc.entregar(projeto, log=lambda *_: None)
    dados = projeto.ler_json("publicacao.json")
    dados["titulo"] = "Título novo"
    projeto.salvar_json("publicacao.json", dados)
    video = entrega_pc.entregar(projeto, log=lambda *_: None)
    pastas = list((destino / "Canada Insight").iterdir())
    assert len(pastas) == 1 and video.name == "Título novo.mp4"
    assert [x.name for x in pastas[0].glob("*.mp4")] == ["Título novo.mp4"]


def test_desligada_nao_entrega(tmp_path):
    projeto, destino = _projeto(tmp_path)
    projeto.config["entrega_pc"]["ativo"] = False
    assert entrega_pc.entregar(projeto, log=lambda *_: None) is None
    assert not destino.exists()


def test_texto_fixo_abre_a_descricao(tmp_path):
    projeto = ProjetoFalso(tmp_path, tmp_path, perfil={"publicacao": {"texto_fixo": "Inscreva-se: @canal\n"}})
    textos = {"resumo": "O resumo do vídeo.", "nomes_capitulos": [], "hashtags": []}
    texto = publicacao.descricao(textos, [], aviso_voz=False, topo=publicacao.texto_fixo(projeto))
    assert texto.startswith("Inscreva-se: @canal\n\nO resumo do vídeo.")
    sem = publicacao.descricao(textos, [], aviso_voz=False, topo=publicacao.texto_fixo(ProjetoFalso(tmp_path, tmp_path)))
    assert sem.startswith("O resumo do vídeo.")


def test_pasta_de_antes_da_separacao_vai_para_o_canal(tmp_path):
    projeto, destino = _projeto(tmp_path)
    projeto.config["entrega_pc"]["separar_por_canal"] = False
    entrega_pc.entregar(projeto, log=lambda *_: None)  # entrega antiga, direto em Downloads
    projeto.config["entrega_pc"]["separar_por_canal"] = True
    video = entrega_pc.entregar(projeto, log=lambda *_: None)
    assert video.parent.parent == destino / "Canada Insight"
    assert [x.name for x in destino.iterdir()] == ["Canada Insight"]  # nada sobrou solto em Downloads


def test_sem_nome_de_canal_vai_para_sem_canal(tmp_path):
    projeto, destino = _projeto(tmp_path)
    projeto.perfil = {}
    assert entrega_pc.entregar(projeto, log=lambda *_: None).parent.parent == destino / "Sem canal"


def test_so_o_video_leva_o_mp4_com_o_titulo_enviado_e_a_descricao(tmp_path):
    projeto, destino = _projeto(tmp_path)
    (projeto.pasta / "creditos.txt").write_text("c", encoding="utf-8")
    entrega_pc.entregar(projeto, log=lambda *_: None)  # entrega completa antiga
    projeto.config["entrega_pc"]["so_o_video"] = True
    projeto.dados = {"titulo_entrega": "10 MAIORES ANIMAIS: QUE JÁ ANDARAM NA TERRA?"}
    video = entrega_pc.entregar(projeto, log=lambda *_: None)
    assert video.name == "10 MAIORES ANIMAIS꞉ QUE JÁ ANDARAM NA TERRA？.mp4"
    assert sorted(x.name for x in video.parent.iterdir()) == sorted([video.name, "descricao.txt"])


def test_titulo_enviado_vai_para_o_kit_e_o_do_modelo_vira_alternativa(tmp_path, monkeypatch):
    projeto = ProjetoFalso(tmp_path, tmp_path)
    projeto.dados = {"titulo_entrega": "Meu título exato"}
    projeto.offline, projeto.config = True, {}
    for nome in ("capitulos", "assinatura", "_tem_imagem_de_ia", "markdown"):
        monkeypatch.setattr(publicacao, nome, lambda *a, _n=nome, **k: [] if _n == "capitulos" else "")
    dados = publicacao.gerar(projeto, log=lambda *_: None)
    assert dados["titulo"] == "Meu título exato"
    assert "Meu título exato" not in dados["titulos_alt"]


def test_rodape_fecha_a_descricao(tmp_path):
    """O rodapé do canal (apresentação e aviso legal) entra na descrição que a fábrica escreve: assim ela já sai
    pronta do projeto, sem ninguém montar nada depois (pedido do usuário em 2026-10-24)."""
    projeto = ProjetoFalso(tmp_path, tmp_path, perfil={"publicacao": {"rodape": "Sobre o canal\nDisclaimer: ...\n"}})
    textos = {"resumo": "O resumo do vídeo.", "nomes_capitulos": [], "hashtags": ["#a"]}
    texto = publicacao.descricao(textos, [], aviso_voz=False, fim=publicacao.rodape(projeto))
    assert texto == "O resumo do vídeo.\n\nSobre o canal\nDisclaimer: ...\n\n#a"
    # o rodapé fica DEPOIS do que é do vídeo e ANTES das hashtags
    assert texto.index("O resumo") < texto.index("Sobre o canal") < texto.index("#a")


def test_canal_sem_rodape_sai_como_antes(tmp_path):
    projeto = ProjetoFalso(tmp_path, tmp_path)
    textos = {"resumo": "O resumo do vídeo.", "nomes_capitulos": [], "hashtags": []}
    assert publicacao.rodape(projeto) == ""
    assert publicacao.descricao(textos, [], aviso_voz=False, fim=publicacao.rodape(projeto)) == "O resumo do vídeo."


def test_rodape_gigante_e_cortado(tmp_path):
    projeto = ProjetoFalso(tmp_path, tmp_path, perfil={"publicacao": {"rodape": "x" * 9000}})
    assert len(publicacao.rodape(projeto)) == publicacao.RODAPE_MAXIMO
