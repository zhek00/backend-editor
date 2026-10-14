import pytest

from fabrica import armazenamento, banco as banco_mod, fila, mcp_fila

ROTEIRO = "Um roteiro com bem mais de vinte caracteres para o teste."


@pytest.fixture
def modo_fila(tmp_path, monkeypatch):
    b = banco_mod.Banco(f"sqlite:///{tmp_path / 'teste.db'}")
    monkeypatch.setattr(banco_mod, "_BANCO", b)
    monkeypatch.setattr(armazenamento, "LOCAL", tmp_path / "entregas")
    monkeypatch.setenv("FABRICA_MODO", "fila")
    for nome in ("FABRICA_R2_ENDPOINT", "FABRICA_R2_BUCKET", "FABRICA_R2_ACCESS_KEY", "FABRICA_R2_SECRET_KEY"):
        monkeypatch.delenv(nome, raising=False)
    yield
    b.fechar()


def _nome(roteiro):
    return "video-" + str(abs(hash(roteiro)) % 10000)


def test_criar_repete_o_mesmo_e_isola_clientes(modo_fila):
    assert mcp_fila.ativo()
    r1 = mcp_fila.criar(ROTEIRO, "ana", _nome)
    nome = r1.split("NOME: ")[1].split(" ")[0]
    assert r1.startswith("Vídeo começou") and "já está em produção" in mcp_fila.criar(ROTEIRO, "ana", _nome)
    assert mcp_fila.e_meu(nome, "ana") and not mcp_fila.e_meu(nome, "bia")
    assert mcp_fila.criar("curto", "ana", _nome).startswith("O roteiro está vazio")


def test_andamento_e_entrega(modo_fila, tmp_path):
    nome = mcp_fila.criar(ROTEIRO, "ana", _nome).split("NOME: ")[1].split(" ")[0]
    assert mcp_fila.progresso(nome, 7)["titulo"] == "Na fila (posição 1)"
    v = fila.pegar("m1")
    fila.atualizar(v["id"], progresso=50, mensagem="Gerando imagens de IA...")
    e = mcp_fila.progresso(nome, 7)
    assert e["estado"] == "produzindo" and e["porcentagem"] == 50 and e["etapa"] == 4
    assert mcp_fila.estado_curto(nome) == "trabalhando" and "ainda não tem" in mcp_fila.entregar(nome, "")
    arquivo = tmp_path / "f.mp4"
    arquivo.write_bytes(b"v")
    fila.concluir(v["id"], objeto=armazenamento.guardar(arquivo, f"videos/{v['id']}/f.mp4"))
    assert mcp_fila.estado_curto(nome) == "pronto" and mcp_fila.progresso(nome, 7)["porcentagem"] == 100
    assert f"/v1/videos/{v['id']}/arquivo" in mcp_fila.entregar(nome, "https://fabrica.exemplo")
    assert mcp_fila.tempo(nome)


def test_cancelar(modo_fila):
    nome = mcp_fila.criar(ROTEIRO, "ana", _nome).split("NOME: ")[1].split(" ")[0]
    assert mcp_fila.cancelar(nome) == "Cancelado." and mcp_fila.estado_curto(nome) == "cancelado"
