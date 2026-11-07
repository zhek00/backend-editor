"""Cada chamada ao HyperFrames entra nas partes da etapa: era o tempo que não aparecia em lugar nenhum."""
from types import SimpleNamespace

from fabrica import animacoes, tempos


def test_hyperframes_vira_parte(tmp_path, monkeypatch):
    monkeypatch.setattr(animacoes, "node_pronto", lambda: "npx")
    monkeypatch.setattr(animacoes, "config", lambda p: {})
    monkeypatch.setattr(animacoes.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    projeto = SimpleNamespace(pasta=tmp_path)
    animacoes._hyperframes(projeto, ["render", "--output", "x.mp4"], tmp_path, 10)
    assert tempos._foto_das_partes(projeto)["hyperframes: render"][1] == 1
