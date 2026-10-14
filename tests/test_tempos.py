import json
from types import SimpleNamespace

import pytest

from fabrica import tempos


def test_medir_grava_o_que_deu_certo_e_o_que_falhou(tmp_path):
    p = SimpleNamespace(pasta=tmp_path)
    avisos = []
    with tempos.medir(p, "Busca de acervo", log=avisos.append, cenas=12):
        pass
    with pytest.raises(RuntimeError):
        with tempos.medir(p, "Imagens de IA"):
            raise RuntimeError("caiu")
    linhas = json.loads((tmp_path / "tempos.json").read_text(encoding="utf-8"))
    assert [(x["etapa"], x["ok"]) for x in linhas] == [("Busca de acervo", True), ("Imagens de IA", False)]
    assert linhas[0]["cenas"] == 12 and linhas[0]["segundos"] >= 0
    assert avisos == []  # menos de 1 s não vira aviso no registro


def test_resumo_soma_por_etapa_e_separa_a_criacao_atual(tmp_path):
    for etapa, inicio, s in [("Imagens de IA", "2026-10-12T10:00:00", 999), ("Imagens de IA", "2026-10-13T10:00:00", 60),
                             ("Busca de acervo", "2026-10-13T10:01:00", 1200), ("Imagens de IA", "2026-10-13T10:30:00", 30)]:
        linhas = json.loads((tmp_path / "tempos.json").read_text(encoding="utf-8")) if (tmp_path / "tempos.json").exists() else []
        linhas.append({"etapa": etapa, "inicio": inicio, "segundos": s, "ok": True})
        (tmp_path / "tempos.json").write_text(json.dumps(linhas), encoding="utf-8")
    assert tempos.resumo(tmp_path, desde="2026-10-13T00:00:00") == [("Busca de acervo", 1200.0, 1), ("Imagens de IA", 90.0, 2)]
    assert tempos.texto_do_resumo(tmp_path, desde="2026-10-13") == \
        "Tempo por etapa: Busca de acervo 20min00s; Imagens de IA 1min30s (2x)"


def test_duracao():
    assert [tempos.duracao(s) for s in (4.4, 75, 3725)] == ["4s", "1min15s", "1h02min"]


def test_etapa_da_criacao_mede_com_as_novas_tentativas(tmp_path, monkeypatch):
    from fabrica import api

    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "projeto.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(api, "PROJETOS", tmp_path)
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    api.TAREFAS["t_tempos"] = {"projeto": "video", "tipo": "teste", "logs": []}
    vezes = []

    def instavel():
        vezes.append(1)
        if len(vezes) < 3:
            raise RuntimeError("503 do servidor")
        return "pronto"

    try:
        assert api._etapa("t_tempos", "Busca de acervo", instavel) == "pronto"
    finally:
        api.TAREFAS.pop("t_tempos", None)
    linhas = json.loads((tmp_path / "video" / "tempos.json").read_text(encoding="utf-8"))
    assert [(x["etapa"], x["ok"]) for x in linhas] == [("Busca de acervo", True)]  # uma linha, com as 3 tentativas


def test_chamada_de_modelo_guarda_os_segundos(tmp_path, monkeypatch):
    from fabrica import groq_local

    p = SimpleNamespace(caminho=lambda nome: tmp_path / nome, pasta=tmp_path)
    groq_local._registrar(p, "julgar mídia", "qwen", {"prompt_tokens": 10, "completion_tokens": 2}, 12.345)
    groq_local._registrar(p, "julgar mídia", "qwen", {"prompt_tokens": 10, "completion_tokens": 2})
    linhas = json.loads((tmp_path / "uso_groq.json").read_text(encoding="utf-8"))
    assert linhas[0]["segundos"] == 12.3 and "segundos" not in linhas[1]


def test_imagem_de_ia_nunca_pede_texto():
    # cena 8 do everything-you-need-to-answer: "Tela com texto exibindo a metodologia..." virou texto em português
    # desenhado na imagem
    from fabrica import imagens

    assert imagens.o_que_mostrar({"mostrar": "Tela com texto exibindo a metodologia do teste", "visual": "foto_real"}) is None
    assert imagens.o_que_mostrar({"mostrar": "Mapa do Reino Unido", "visual": "mapa"}) is None
    assert imagens.o_que_mostrar({"mostrar": "Galinha caipira ciscando no quintal", "visual": "foto_real"}) == \
        "Galinha caipira ciscando no quintal"


def test_restaurar_poe_data_nova(tmp_path):
    # com o copy2, a imagem restaurada voltava à versão (data) que o navegador já tinha guardado
    import os
    from fabrica import api

    velho = tmp_path / "antiga.png"
    velho.write_bytes(b"x")
    os.utime(velho, (1_000_000, 1_000_000))
    destino = tmp_path / "0008.png"
    api._copiar_com_data_nova(str(velho), str(destino))
    assert destino.read_bytes() == b"x" and destino.stat().st_mtime > 1_000_000 + 10
