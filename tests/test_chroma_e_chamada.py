"""Material de edição (chroma) nunca entra e a chamada do canal mostra o assunto do vídeo.

Caso real: no leite (2026-10-09) a cena "se inscreve, e nos vemos no próximo vídeo" pediu "hand tapping YouTube like
subscribe buttons" e pegou do Pexels a "subscribe animation on green background": 4 s de tela verde no vídeo pronto."""
import random

from fabrica import cenas, midia


def test_nome_do_banco_entrega_o_material_de_edicao():
    assert midia.de_edicao({"pagina": "https://www.pexels.com/video/subscribe-animation-on-green-background-10306979/"})
    assert midia.de_edicao({"descricao": "Green Screen Chroma Key explosion"})
    assert midia.de_edicao({"descricao": "like and subscribe button"})
    assert not midia.de_edicao({"pagina": "https://www.pexels.com/photo/green-forest-trees-123/"})
    assert not midia.de_edicao({"descricao": "milk cartons on a supermarket shelf"})


def test_verde_liso_e_chroma_mas_folha_e_grama_nao(tmp_path):
    from PIL import Image
    liso = Image.new("RGB", (320, 180), (0, 177, 64))
    liso.paste(Image.new("RGB", (120, 40), (240, 240, 240)), (100, 120))  # o botão branco em cima do verde
    liso.save(tmp_path / "chroma.png")
    assert midia.fundo_de_chroma(tmp_path / "chroma.png")
    # verde com textura (folha, grama): muito verde, mas o brilho varia muito de um ponto a outro
    sorte = random.Random(1)
    mato = Image.new("RGB", (320, 180))
    mato.putdata([(sorte.randint(10, 60), sorte.randint(110, 230), sorte.randint(10, 60)) for _ in range(320 * 180)])
    mato.save(tmp_path / "mato.png")
    assert not midia.fundo_de_chroma(tmp_path / "mato.png")


class _Projeto:
    def __init__(self, mapa):
        self._mapa = mapa

    def existe(self, nome):
        return nome == "roteiro_mapa.json"

    def ler_json(self, nome):
        return self._mapa

    def imagem(self, n):
        from pathlib import Path
        return Path("nao-existe") / f"{n:04d}.png"


MAPA = {"titulo": "Leite", "blocos": [
    {"id": 1, "nome": "preços", "ancora": "milk cartons on grocery store shelf price tags", "contexto": "milk"},
    {"id": 5, "nome": "saquinhos", "ancora": "4 litre milk bags in Ontario grocery store fridge", "contexto": "grocery"}]}


def test_chamada_do_canal_pede_o_assunto_e_nao_o_youtube():
    lista = [
        {"n": 45, "bloco": 5, "tipo": "foto_real", "texto": "mora. Se isso te ajudou, deixa o like,",
         "busca": "hand tapping YouTube like subscribe buttons", "exato": "YouTube", "sem_midia_real": True},
        {"n": 46, "bloco": 5, "tipo": "video_real", "texto": "se inscreve, e nos vemos no próximo vídeo.",
         "busca": "milk bags in a fridge"},  # pediu o assunto: fica como está
        {"n": 47, "bloco": 5, "tipo": "foto_real", "texto": "Leia o rótulo, não a propaganda.",
         "busca": "YouTube logo"},  # não é chamada do canal: fica
    ]
    assert cenas._chamada_mostra_o_assunto(_Projeto(MAPA), lista) == 1
    c = lista[0]
    assert c["busca"] == "4 litre milk bags in Ontario grocery store fridge"
    assert c["busca_alternativa"] == "milk cartons on grocery store shelf price tags"  # o tema do vídeo
    assert c["exato"] == "" and "sem_midia_real" not in c  # vazio: qualquer imagem do assunto serve
    assert c["pedido_chamada"]["busca"] == "hand tapping YouTube like subscribe buttons"
    assert lista[1]["busca"] == "milk bags in a fridge" and lista[2]["busca"] == "YouTube logo"


def test_escolha_da_pessoa_fica():
    c = {"n": 1, "bloco": 5, "tipo": "foto_real", "texto": "se inscreve no canal", "busca": "YouTube subscribe",
         "busca_manual": True}
    assert cenas._chamada_mostra_o_assunto(_Projeto(MAPA), [c]) == 0
