"""Estilo de edição do vídeo (perfil `visual:`), vindo do Robô PALHANO: só muda o clipe quando o perfil pede."""
from fabrica import render


def test_sem_visual_nao_muda_o_filtro():
    assert render._com_visual("scale=1920:1080", {}) == "scale=1920:1080"
    assert render._com_visual("scale=1920:1080", {"visual": "inexistente"}) == "scale=1920:1080"


def test_cinema_deitado_tem_faixas_e_em_pe_nao():
    deitado = render._com_visual("x", {"visual": "cinema"})
    em_pe = render._com_visual("x", {"visual": "cinema", "vertical": True})
    assert "drawbox" in deitado and "colorbalance" in deitado
    assert "drawbox" not in em_pe and "colorbalance" in em_pe


def test_investigacao_tem_granulado_e_vinheta():
    filtro = render._com_visual("x", {"visual": "investigacao"})
    assert "noise=" in filtro and "vignette" in filtro
