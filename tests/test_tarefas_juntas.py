"""Render e Corrigir Mídia no mesmo projeto, ao mesmo tempo."""
import pytest
from fastapi import HTTPException

from fabrica import api


def test_render_recusado_com_corrigir_rodando():
    # nunca-deve-ter-dentro-de-casa-parte-2: o Corrigir trocou a imagem da cena 166 no meio do render
    api.TAREFAS["corrigir_x_1"] = {"projeto": "x", "status": "processando", "progresso_pct": 40, "mensagem": "conferindo"}
    try:
        with pytest.raises(HTTPException) as erro:
            api._recusar_se_ocupado("x", api._MEXEM_NA_MIDIA, "renderizar")
        assert erro.value.status_code == 409
        api._recusar_se_ocupado("outro", api._MEXEM_NA_MIDIA, "renderizar")  # outro projeto segue livre
        api.TAREFAS["corrigir_x_1"]["status"] = "concluido"
        api._recusar_se_ocupado("x", api._MEXEM_NA_MIDIA, "renderizar")
    finally:
        api.TAREFAS.pop("corrigir_x_1", None)


def test_corrigir_recusado_com_render_rodando():
    api.TAREFAS["render_x_1"] = {"projeto": "x", "status": "renderizando", "progresso_pct": 32}
    try:
        with pytest.raises(HTTPException):
            api._recusar_se_ocupado("x", ("render_",) + api._MEXEM_NA_MIDIA, "corrigir a mídia")
    finally:
        api.TAREFAS.pop("render_x_1", None)

