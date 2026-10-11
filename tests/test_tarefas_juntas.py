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



def _etapa_com_falhas(monkeypatch, tmp_path, falhas, apagar_na=None):
    """Roda api._etapa com uma função que falha `falhas` vezes; sem dormir de verdade."""
    monkeypatch.setattr(api, "PROJETOS", tmp_path)
    monkeypatch.setattr(api, "_salvar_criacao", lambda *a: None)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "projeto.json").write_text("{}", encoding="utf-8")
    esperas = []
    monkeypatch.setattr(api.time, "sleep", lambda s: esperas.append(s))
    api.TAREFAS["criar_x_1"] = {"projeto": "x", "tipo": "criacao", "logs": []}
    chamadas = []

    def funcao():
        chamadas.append(1)
        if apagar_na and len(chamadas) == apagar_na:
            (tmp_path / "x" / "projeto.json").unlink()
        if len(chamadas) <= falhas:
            raise RuntimeError("o Groq caiu")
        return "pronto"
    try:
        return api._etapa("criar_x_1", "Busca de acervo", funcao), esperas
    finally:
        api.TAREFAS.pop("criar_x_1", None)


def test_etapa_nunca_desiste_de_queda_passageira(monkeypatch, tmp_path):
    # pedido do usuário em 2026-10-10: "a edição jamais deve parar". Antes, 6 tentativas em uns 2 min e o vídeo parava
    resultado, esperas = _etapa_com_falhas(monkeypatch, tmp_path, falhas=10)
    assert resultado == "pronto"
    assert esperas[:6] == api._ESPERAS and set(esperas[6:]) == {api.ESPERA_LONGA}


def test_etapa_para_se_o_projeto_foi_apagado(monkeypatch, tmp_path):
    # o × do editor apaga a pasta: a esteira não fica tentando para sempre um projeto que não existe
    with pytest.raises(RuntimeError):
        _etapa_com_falhas(monkeypatch, tmp_path, falhas=100, apagar_na=3)


def test_etapa_para_com_erro_que_esperar_nao_resolve(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "PROJETOS", tmp_path)
    api.TAREFAS["criar_y_1"] = {"projeto": "y", "tipo": "criacao", "logs": []}
    try:
        with pytest.raises(api.ParadaPrecisaDeVoce):
            api._etapa("criar_y_1", "Narração", lambda: (_ for _ in ()).throw(RuntimeError("Acabou o crédito no OpenRouter")))
    finally:
        api.TAREFAS.pop("criar_y_1", None)
