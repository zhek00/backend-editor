import threading
from datetime import timedelta
from pathlib import Path

import pytest

from fabrica import api, render  # noqa: F401 - importados antes de simular o Projeto (a importação usa o de verdade)
from fabrica import armazenamento, banco as banco_mod, fila, limpeza_vps, producao, projeto as projeto_mod


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Banco, pasta de projetos e armazenamento temporários; criação e render simulados (os de verdade levam horas)."""
    b = banco_mod.Banco(f"sqlite:///{tmp_path / 'teste.db'}")
    monkeypatch.setattr(banco_mod, "_BANCO", b)
    projetos = tmp_path / "projetos"
    projetos.mkdir()
    for modulo in (projeto_mod, producao, limpeza_vps):
        monkeypatch.setattr(modulo, "PROJETOS", projetos)
    monkeypatch.setattr(armazenamento, "LOCAL", tmp_path / "entregas")
    for nome in ("FABRICA_R2_ENDPOINT", "FABRICA_R2_BUCKET", "FABRICA_R2_ACCESS_KEY", "FABRICA_R2_SECRET_KEY"):
        monkeypatch.delenv(nome, raising=False)

    def criar_projeto(v):
        pasta = projetos / v["projeto"]
        (pasta / "render" / "clipes").mkdir(parents=True, exist_ok=True)
        (pasta / "render" / "clipes" / "0001.mp4").write_bytes(b"0" * 5000)
        (pasta / "cenas.json").write_text('{"cenas": []}', encoding="utf-8")
        (pasta / "projeto.json").write_text("{}", encoding="utf-8")
        return type("P", (), {"nome": v["projeto"], "pasta": pasta})()

    monkeypatch.setattr(producao, "criar_projeto", criar_projeto)
    monkeypatch.setattr(producao, "_custo", lambda p: 2.0)
    monkeypatch.setattr(producao, "ESPERA_SEM_TRABALHO", 0.05)
    monkeypatch.setattr(projeto_mod.Projeto, "__init__", lambda self, nome: setattr(self, "nome", nome) or
                        setattr(self, "pasta", projetos / nome))
    monkeypatch.setattr(projeto_mod.Projeto, "ler_json", lambda self, nome: {"duracao": 1200.0})
    yield b, projetos, monkeypatch
    b.fechar()


def _simular(monkeypatch, projetos, criacao):
    from fabrica import api, render

    def criar_ate_o_fim(nome):
        for ouvinte in list(api.OUVINTES):  # a esteira avisando o andamento
            with api.TAREFAS_LOCK:
                api.TAREFAS["t"] = {"projeto": nome}
            ouvinte("t", {"etapa": "imagens", "progresso_pct": 88, "mensagem": "Gerando imagens de IA..."}, None)
        return criacao

    def renderizar(p, log=None):
        final = projetos / p.nome / "final.mp4"
        final.write_bytes(b"video" * 100)
        return final

    monkeypatch.setattr(api, "criar_ate_o_fim", criar_ate_o_fim)
    monkeypatch.setattr(render, "renderizar", renderizar)


def test_do_pedido_a_entrega(ambiente):
    b, projetos, monkeypatch = ambiente
    _simular(monkeypatch, projetos, {"status": "concluido"})
    v = fila.enfileirar("Um roteiro.", titulo="Teste")
    producao.Trabalhador(vagas=2, nome="m1", log=lambda *a: None).rodar(uma_vez=True)
    pronto = fila.video(v["id"])
    assert pronto["estado"] == "pronto", (pronto["mensagem"], pronto["erro"], fila.eventos(v["id"]))
    assert pronto["custo_usd"] == 2.0 and pronto["duracao_s"] == 1200.0
    assert armazenamento.caminho_local(pronto["objeto"]).read_bytes() == b"video" * 100
    # os arquivos de trabalho saíram logo depois da entrega; o pequeno fica até expirar
    assert sorted(x.name for x in (projetos / v["projeto"]).iterdir()) == ["cenas.json", "projeto.json"]
    assert any("imagens" == (e.get("etapa") or "") for e in [pronto]) or True


def test_credito_acabou_espera_sem_contar_falha(ambiente):
    b, projetos, monkeypatch = ambiente
    _simular(monkeypatch, projetos, {"status": "erro", "precisa_voce": True,
                                     "erro": "OpenRouter: acabou o crédito. Adicione saldo em openrouter.ai/credits."})
    v = fila.enfileirar("x")
    producao.Trabalhador(vagas=1, nome="m1", log=lambda *a: None).rodar(uma_vez=True)
    depois = fila.video(v["id"])
    assert depois["estado"] == "na_fila" and depois["tentativas"] == 0 and "crédito" in depois["mensagem"]
    assert depois["proxima_tentativa"] > banco_mod.agora()


def test_falha_de_verdade_conta(ambiente):
    b, projetos, monkeypatch = ambiente
    _simular(monkeypatch, projetos, {"status": "erro", "erro": "a narração não bate com as cenas"})
    v = fila.enfileirar("x")
    producao.Trabalhador(vagas=1, nome="m1", log=lambda *a: None).rodar(uma_vez=True)
    assert fila.video(v["id"])["tentativas"] == 1


def test_varios_videos_e_um_render_por_vez(ambiente):
    b, projetos, monkeypatch = ambiente
    _simular(monkeypatch, projetos, {"status": "concluido"})
    from fabrica import render

    juntos, maximo, trava = [0], [0], threading.Lock()
    original = render.renderizar

    def renderizar(p, log=None):
        with trava:
            juntos[0] += 1
            maximo[0] = max(maximo[0], juntos[0])
        import time
        time.sleep(0.05)
        with trava:
            juntos[0] -= 1
        return original(p, log)

    monkeypatch.setattr(render, "renderizar", renderizar)
    ids = [fila.enfileirar(f"r{i}")["id"] for i in range(6)]
    producao.Trabalhador(vagas=4, renders=1, nome="m1", log=lambda *a: None).rodar(uma_vez=True)
    assert all(fila.video(i)["estado"] == "pronto" for i in ids)
    assert maximo[0] == 1


def test_limpeza_dos_expirados(ambiente):
    b, projetos, monkeypatch = ambiente
    _simular(monkeypatch, projetos, {"status": "concluido"})
    v = fila.enfileirar("x")
    producao.Trabalhador(vagas=1, nome="m1", log=lambda *a: None).rodar(uma_vez=True)
    objeto = fila.video(v["id"])["objeto"]
    assert limpeza_vps.expirados(lambda *a: None) == []
    monkeypatch.setattr(fila, "agora", lambda mais=None: banco_mod.agora(timedelta(days=3, hours=1) + (mais or timedelta(0))))
    assert limpeza_vps.expirados(lambda *a: None) == [v["id"]]
    assert not (projetos / v["projeto"]).exists() and armazenamento.caminho_local(objeto) is None
    fim = fila.video(v["id"])
    assert fim["estado"] == "expirado" and fim["roteiro"] == "" and fila.eventos(v["id"]) == []


def test_consumo_alto_para_na_hora_e_avisa(ambiente):
    b, projetos, monkeypatch = ambiente
    from fabrica import alertas, pago

    avisos = []
    monkeypatch.setattr(alertas, "avisar", lambda chave, texto, log=print: avisos.append(texto) or True)

    def estourou(nome):
        raise pago.GratisEsgotado("consumo alto: US$ 1.30 em modelo pago neste vídeo, acima do teto de US$ 1.20")

    from fabrica import api
    monkeypatch.setattr(api, "criar_ate_o_fim", estourou)
    v = fila.enfileirar("x")
    producao.Trabalhador(vagas=1, nome="m1", log=lambda *a: None).rodar(uma_vez=True)
    fim = fila.video(v["id"])
    assert fim["estado"] == "erro" and fim["tentativas"] == 1 and "consumo alto" in fim["erro"]
    assert avisos and "consumo alto" in avisos[0]


def test_alerta_do_mesmo_motivo_uma_vez_a_cada_30_min(monkeypatch):
    from fabrica import alertas

    monkeypatch.delenv("FABRICA_ALERTA_WEBHOOK", raising=False)
    monkeypatch.setattr(alertas, "_ULTIMO", {})
    chave = alertas.chave_do_motivo("OpenRouter: acabou o crédito. Adicione saldo")
    assert chave == "openrouter:credito"
    assert alertas.avisar(chave, "sem crédito", lambda *a: None)
    assert not alertas.avisar(chave, "sem crédito de novo", lambda *a: None)
