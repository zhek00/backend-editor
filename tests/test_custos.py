"""Custos dos modelos de linguagem por tarefa.

Caso real: no nunca-deve-ter-dentro-de-casa-parte-2 o Custos mostrava "OpenRouter: 2.076 chamadas, US$ 3,00" e não
dava para ver que US$ 2,60 eram a escolha das fotos no Qwen pago e US$ 0,06 a descrição das imagens."""
import json
from types import SimpleNamespace

from fabrica import custos_reais


def test_etapas_viram_tarefas():
    assert custos_reais.tarefa_da_etapa("escolha de material real (tradução)") == ("visao", "Escolha das fotos do acervo")
    assert custos_reais.tarefa_da_etapa("descrever imagens") == ("visao", "Descrição das imagens")
    assert custos_reais.tarefa_da_etapa("julgar mídia (no lugar do Jev)")[0] == "juiz"
    assert custos_reais.tarefa_da_etapa("roteirista: cenas") == ("texto", "Roteiro e divisão em cenas")
    assert custos_reais.tarefa_da_etapa("algo novo") == ("texto", "Outros textos")


def test_custo_por_tarefa_e_por_modelo(tmp_path):
    (tmp_path / "uso_openrouter.json").write_text(json.dumps([
        {"etapa": "escolha de material real", "modelo": "qwen/qwen3.8-flash", "tokens_lidos": 2800,
         "tokens_escritos": 1500, "custo_usd": 0.002},
        {"etapa": "descrever imagens", "modelo": "dots-studio/dots-3-note-preview:free", "tokens_lidos": 1200,
         "tokens_escritos": 150, "custo_usd": 0},
    ]), encoding="utf-8")
    (tmp_path / "uso_groq.json").write_text(json.dumps([
        {"etapa": "descrever imagens", "modelo": "qwen/qwen3.8-27b", "tokens_lidos": 1200, "tokens_escritos": 150},
    ]), encoding="utf-8")
    projeto = SimpleNamespace(pasta=tmp_path, config={})
    tarefas = {t["tarefa"]: t for t in custos_reais.uso_por_tarefa(projeto)}
    escolha, descricao = tarefas["Escolha das fotos do acervo"], tarefas["Descrição das imagens"]
    assert escolha["custo_usd"] == 0.002 and escolha["gratis"] == 0
    assert descricao["chamadas"] == 2 and descricao["gratis"] == 2 and descricao["custo_usd"] == 0
    assert {m["modelo"] for m in descricao["modelos"]} == {"Groq qwen/qwen3.8-27b", "dots-studio/dots-3-note-preview:free"}
