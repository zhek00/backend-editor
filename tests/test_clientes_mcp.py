"""Contas do MCP na internet: token, limite por dia, links de download (clientes_mcp.py)."""
import time

import pytest

from fabrica import clientes_mcp


@pytest.fixture(autouse=True)
def arquivos(tmp_path, monkeypatch):
    monkeypatch.setattr(clientes_mcp, "ARQUIVO", tmp_path / "clientes.json")
    monkeypatch.setattr(clientes_mcp, "LINKS", tmp_path / "links.json")


def test_token_vale_ate_ser_revogado_e_o_arquivo_nao_guarda_o_token():
    token = clientes_mcp.criar("joao")
    assert clientes_mcp.quem(token) == "joao" and clientes_mcp.quem("tl_outro") is None
    assert token not in clientes_mcp.ARQUIVO.read_text(encoding="utf-8")  # só o hash
    with pytest.raises(ValueError):
        clientes_mcp.criar("joao")
    clientes_mcp.revogar("joao")
    assert clientes_mcp.quem(token) is None


def test_limite_de_videos_por_dia():
    clientes_mcp.criar("maria", por_dia=2)
    for video in ("um", "dois"):
        assert clientes_mcp.pode_comecar("maria") == ""
        clientes_mcp.registrar_producao("maria", video)
    assert "2 vídeo(s) por dia" in clientes_mcp.pode_comecar("maria")


def test_link_de_download_so_com_o_codigo_e_o_nome_certos(tmp_path, monkeypatch):
    video = tmp_path / "final.mp4"
    video.write_bytes(b"mp4")
    codigo, nome = clientes_mcp.link(video, "joao").split("/")
    assert clientes_mcp.arquivo_do_link(codigo, nome) == video.resolve()
    assert clientes_mcp.arquivo_do_link(codigo, "outro.mp4") is None
    assert clientes_mcp.arquivo_do_link("inventado", nome) is None
    depois = time.time() + clientes_mcp.VALIDADE_DO_LINK + 60
    monkeypatch.setattr(clientes_mcp.time, "time", lambda: depois)
    assert clientes_mcp.arquivo_do_link(codigo, nome) is None  # venceu
