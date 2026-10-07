"""Modelo do cliente: as decisões da fábrica respondidas pelo Claude de quem usa o MCP (cliente.py, mcp_servidor.py)."""
import base64
import threading
import time
from types import SimpleNamespace

import pytest

from fabrica import cliente, jev_local, openrouter_local

ESQUEMA = {"type": "object", "properties": {"escolhas": {"type": "array"}}, "required": ["escolhas"]}


@pytest.fixture(autouse=True)
def fila_limpa(monkeypatch):
    monkeypatch.setattr(cliente, "_TAREFAS", {})
    yield


def _projeto(nome="video", modelo="cliente"):
    return SimpleNamespace(nome=nome, dados={"modelo": modelo}, config={}, pasta=None)


def _em_paralelo(funcao):
    resultado = {}
    t = threading.Thread(target=lambda: resultado.update(r=funcao()), daemon=True)
    t.start()
    for _ in range(200):
        if cliente.pendentes():
            break
        time.sleep(0.01)
    return t, resultado


def test_so_o_projeto_do_mcp_usa_a_fila():
    assert cliente.ativo(_projeto())
    assert not cliente.ativo(_projeto(modelo=None)) and not cliente.ativo(SimpleNamespace(nome="x"))


def test_pedido_vai_para_a_fila_e_a_resposta_volta(tmp_path):
    foto = tmp_path / "folha.jpg"
    foto.write_bytes(b"jpg")
    t, resultado = _em_paralelo(lambda: cliente.pedir(_projeto(), "escolha de material real", "escolha a foto",
                                                      "cena 3: um pangolim", ESQUEMA, [foto], log=lambda *_: None))
    [tarefa] = cliente.proximas()
    assert tarefa["etapa"] == "escolha de material real" and tarefa["pedido"] == "cena 3: um pangolim"
    assert base64.standard_b64decode(tarefa["imagens"][0]["dados"]) == b"jpg"
    assert cliente.responder(tarefa["id"], '{"escolhas": [2, 0]}') == {"ok": True}
    t.join(2)
    assert resultado["r"] == {"escolhas": [2, 0]} and cliente.pendentes() == 0


def test_pedido_com_texto_e_imagens_intercalados():
    pedido = [{"type": "text", "text": "candidato A"},
              {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(b"png").decode()}},
              {"type": "text", "text": "qual combina?"}]
    texto, imagens = cliente._imagens_do_pedido(pedido, ())
    assert texto == "candidato A\n[imagem 1]\nqual combina?" and imagens[0]["mime"] == "image/png"


def test_resposta_sem_a_chave_do_esquema_e_recusada_e_a_tarefa_continua():
    t, _ = _em_paralelo(lambda: cliente.pedir(_projeto(), "x", "i", "p", ESQUEMA, log=lambda *_: None))
    [tarefa] = cliente.proximas()
    assert not cliente.responder(tarefa["id"], '{"outra": 1}')["ok"]
    assert not cliente.responder(tarefa["id"], "isto não é JSON")["ok"]
    assert cliente.pendentes() == 1
    assert cliente.responder(tarefa["id"], {"escolhas": []})["ok"]
    t.join(2)


def test_tarefa_entregue_nao_volta_antes_do_prazo(monkeypatch):
    t, _ = _em_paralelo(lambda: cliente.pedir(_projeto(), "x", "i", "p", ESQUEMA, log=lambda *_: None))
    assert len(cliente.proximas()) == 1 and cliente.proximas() == []
    monkeypatch.setattr(cliente, "ENTREGA_VENCE", 0)
    assert len(cliente.proximas()) == 1  # o cliente fechou a sessão sem responder: a tarefa volta
    cliente.cancelar("video")
    t.join(2)


def test_cancelar_solta_a_producao():
    t, resultado = _em_paralelo(lambda: pytest.raises(cliente.Cancelada, cliente.pedir, _projeto(), "x", "i", "p",
                                                      ESQUEMA, log=lambda *_: None))
    assert cliente.cancelar("video") == 1
    t.join(2)
    assert resultado["r"]


def test_perguntar_do_projeto_do_mcp_nao_chama_nenhum_modelo(monkeypatch):
    monkeypatch.setattr(openrouter_local, "_perguntar_rota",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("chamou o OpenRouter")))
    t, resultado = _em_paralelo(lambda: openrouter_local.perguntar(_projeto(), "trilha", "i", "p", ESQUEMA,
                                                                   log=lambda *_: None))
    [tarefa] = cliente.proximas()
    cliente.responder(tarefa["id"], {"escolhas": [1]})
    t.join(2)
    assert resultado["r"] == {"escolhas": [1]}


def test_o_jev_do_projeto_do_mcp_e_o_claude_do_cliente(monkeypatch):
    monkeypatch.setattr(jev_local.httpx, "post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("chamou o Jev")))
    perguntas = {"combina": {"type": "noul", "instructions": "a imagem mostra o pangolim?"}}
    t, resultado = _em_paralelo(lambda: jev_local.decidir(_projeto(), "julgar mídia", {"fala": "o pangolim"},
                                                          perguntas, log=lambda *_: None))
    [tarefa] = cliente.proximas()
    assert "combina" in tarefa["esquema"]["required"]
    cliente.responder(tarefa["id"], {"combina": 0.9})
    t.join(2)
    assert resultado["r"]["combina"] == {"type": "noul", "noul": 0.9}


def test_mcp_manda_as_instrucoes_inteiras_uma_vez_por_chamada(monkeypatch):
    # cada subagente do comando nasce sem a conversa: as instruções vêm inteiras na primeira tarefa da chamada, e não
    # vêm de novo só quando quem pede diz que já tem a marca
    from fabrica import mcp_servidor

    instrucoes = "Regras longas da escolha das fotos. " * 20
    fios = [_em_paralelo(lambda: cliente.pedir(_projeto(), "escolha", instrucoes, f"cena {i}", ESQUEMA,
                                               log=lambda *_: None))[0] for i in range(3)]
    primeira, segunda = mcp_servidor.proximas_tarefas(limite=2)
    assert instrucoes in primeira and instrucoes not in segunda and "ver_instrucoes" in segunda
    marca = mcp_servidor._marca(instrucoes)
    assert mcp_servidor.ver_instrucoes(marca) == instrucoes
    cliente.cancelar("video")
    for f in fios:
        f.join(2)
    fios = [_em_paralelo(lambda: cliente.pedir(_projeto(), "escolha", instrucoes, "outra", ESQUEMA,
                                               log=lambda *_: None))[0] for _ in range(2)]
    [nova] = mcp_servidor.proximas_tarefas(limite=1)
    assert instrucoes in nova  # outra chamada, outro subagente: vem inteira de novo
    [com_marca] = mcp_servidor.proximas_tarefas(limite=1, instrucoes_que_ja_tenho=marca)
    assert instrucoes not in com_marca
    cliente.cancelar("video")
    for f in fios:
        f.join(2)


def test_tarefas_separadas_em_roteiro_e_visual():
    # o comando manda o roteiro ao Opus e o resto ao Sonnet
    assert cliente.grupo("roteirista: mapa") == cliente.grupo("roteirista: cenas") == cliente.grupo("diretor") == "roteiro"
    assert cliente.grupo("escolha das fotos (escolher e julgar)") == cliente.grupo("revisão do vídeo") == "visual"
    fios = [_em_paralelo(lambda e=e: cliente.pedir(_projeto(), e, "regras", "pedido", ESQUEMA,
                                                   log=lambda *_: None))[0] for e in ("roteirista: cenas", "trilha")]
    from fabrica import mcp_servidor
    with mcp_servidor._TRAVA:
        mcp_servidor._PRODUCOES["video"] = {"estado": "produzindo", "log": [], "inicio": "2026-10-07T10:00:00",
                                            "fim": None, "erro": None}
    try:
        assert mcp_servidor.esperar("video", 1) == "tarefas: roteiro 1, visual 1"
        [so_roteiro] = cliente.proximas("video", 5, tipo="roteiro")
        assert so_roteiro["etapa"] == "roteirista: cenas"
        assert mcp_servidor.esperar("video", 1) == "tarefas: roteiro 0, visual 1"
    finally:
        cliente.cancelar("video")
        mcp_servidor._PRODUCOES.pop("video", None)
        for f in fios:
            f.join(2)


def test_comando_tiplabs():
    # o arquivo do /tiplabs recebe os argumentos do Claude Code; o prompt do servidor já vem com eles
    from fabrica import mcp_servidor
    arquivo = mcp_servidor.instalar_tiplabs()
    assert "~/.claude/commands/tiplabs.md" in arquivo and "$ARGUMENTS" in arquivo and "argument-hint:" in arquivo
    assert "{" not in arquivo.split("=====")[1].replace("{nome}", "")  # nenhum campo sem preencher
    pronto = mcp_servidor.comando_tiplabs("roteiro.txt", "cafe-1")
    assert "Nome do vídeo: cafe-1" in pronto and '"sonnet"' in pronto and "$ARGUMENTS" not in pronto
