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


def test_comando_tiplabs_so_pede_o_roteiro():
    # o cliente não escolhe nada (pedido do usuário em 2026-10-09): nem nome, nem estilo, nem voz, nem estimativa
    from fabrica import mcp_servidor
    arquivo = mcp_servidor.instalar_tiplabs()
    assert "~/.claude/commands/tiplabs.md" in arquivo and "$ARGUMENTS" in arquivo and "argument-hint:" in arquivo
    assert "estimativa" not in arquivo.split("AJUDANTE:")[0] and "perfil" not in arquivo.split("AJUDANTE:")[0]
    pronto = mcp_servidor.comando_tiplabs("roteiro.txt")
    assert "Roteiro: roteiro.txt" in pronto and '"sonnet"' in pronto and "$ARGUMENTS" not in pronto


def test_nome_automatico_e_o_mesmo_roteiro_continua_o_video(tmp_path, monkeypatch):
    import json
    from fabrica import mcp_servidor
    monkeypatch.setattr(mcp_servidor, "PROJETOS", tmp_path)
    nome = mcp_servidor._nome_automatico("Ninguém imagina, mas o lobo-guará come frutas.")
    assert mcp_servidor._NOME_VALIDO.match(nome) and nome.startswith("ninguem-imagina-mas-o-lobo")
    roteiro = "O lobo-guará come frutas.\n\nE espalha sementes."
    (tmp_path / nome).mkdir()
    (tmp_path / nome / "projeto.json").write_text(json.dumps(
        {"modelo": "cliente", "roteiro_marca": mcp_servidor._marca_do_roteiro(roteiro)}), encoding="utf-8")
    assert mcp_servidor._video_em_andamento(mcp_servidor._marca_do_roteiro("O lobo-guará  come frutas. E espalha sementes.")) == nome
    assert mcp_servidor._video_em_andamento(mcp_servidor._marca_do_roteiro("Outro roteiro.")) == ""


# ---------------------------------------------------------------- reserva: o cliente parou no meio do vídeo

def _projeto_com_cenas(tmp_path, feitas, total=10):
    import json
    (tmp_path / "midia" / "escolha").mkdir(parents=True)
    for n in range(1, feitas + 1):
        (tmp_path / "midia" / "escolha" / f"cena_{n:04d}.json").write_text("{}", encoding="utf-8")
    cenas = {"cenas": [{"n": n} for n in range(1, total + 1)]}
    return SimpleNamespace(nome=f"video-{feitas}", dados={"modelo": "cliente"}, pasta=tmp_path,
                           config={"cliente": {"espera_reserva": 0.2}},
                           existe=lambda nome: nome == "cenas.json", ler_json=lambda nome: cenas)


def test_cliente_parou_antes_da_metade_a_producao_pausa(tmp_path):
    p = _projeto_com_cenas(tmp_path, feitas=5)  # 50% do vídeo: abaixo dos 60%
    fio, saida = _em_paralelo(lambda: cliente.pedir(p, "escolha das fotos", "regras", "pedido", ESQUEMA,
                                                    log=lambda *a: None))
    time.sleep(0.8)
    assert fio.is_alive() and cliente.medidas(p.nome)["pausado"]  # segue esperando o cliente
    [t] = cliente.proximas(p.nome)
    assert cliente.responder(t["id"], {"escolhas": [1]})["ok"]
    fio.join(2)
    assert saida["r"] == {"escolhas": [1]} and not cliente.medidas(p.nome)["pausado"]


def test_cliente_parou_depois_da_metade_a_fabrica_segue_e_ele_retoma_quando_volta(tmp_path):
    p = _projeto_com_cenas(tmp_path, feitas=6)  # 60% do vídeo: o mínimo
    erro = {}

    def pedir():
        try:
            cliente.pedir(p, "escolha das fotos", "regras", "pedido", ESQUEMA, log=lambda *a: None)
        except cliente.Reserva as e:
            erro["reserva"] = e

    fio = threading.Thread(target=pedir, daemon=True)
    fio.start()
    fio.join(3)
    assert "reserva" in erro and not cliente.atende(p, "escolha das fotos")  # visual vai para a cadeia
    assert cliente.atende(p, "roteirista: cenas")  # roteiro sempre espera o cliente
    fio, _ = _em_paralelo(lambda: cliente.pedir(p, "roteirista: cenas", "r", "p", ESQUEMA, log=lambda *a: None))
    [t] = cliente.proximas(p.nome)
    cliente.responder(t["id"], {"escolhas": []})  # o cliente voltou
    fio.join(2)
    assert cliente.atende(p, "escolha das fotos")


def test_tarefa_de_roteiro_nunca_vai_para_a_reserva(tmp_path):
    p = _projeto_com_cenas(tmp_path, feitas=10)
    fio, _ = _em_paralelo(lambda: cliente.pedir(p, "roteirista: mapa", "r", "p", ESQUEMA, log=lambda *a: None))
    time.sleep(0.8)
    assert fio.is_alive()
    cliente.cancelar(p.nome)
    fio.join(2)


def test_mcp_oferece_so_os_perfis_de_motion_de_apoio():
    # o vídeo do cliente é de banco de imagens e IA; o motion só apoia. Perfis todo em motion e canais pessoais ficam fora
    from fabrica import mcp_servidor
    assert mcp_servidor._perfis_do_mcp() == ["documentario", "documentario-vox"]
    assert "motion-vox" not in mcp_servidor.listar_perfis()
    with pytest.raises(ValueError):
        mcp_servidor._perfil("motion-ai")
    assert mcp_servidor._perfil("documentario-vox").name == "documentario-vox.yaml"


def test_com_visao_pela_fabrica_as_imagens_saem_do_claude_do_cliente(monkeypatch):
    # pedido do usuário em 2026-10-09: o Gemini descreve e escolhe as imagens e o Jev julga; o cliente fica com o texto
    from fabrica import openrouter_local
    p = _projeto()
    p.config = {"mcp": {"visao_pela_fabrica": True, "modelos_visao": ["gemini:gemini-3.1-flash-lite", "qwen/qwen3.7-flash"]}}
    assert not cliente.atende(p, "escolha das fotos")
    assert not cliente.atende(p, "conferir cenas") and not cliente.atende(p, "julgar mídia")
    assert not cliente.atende(p, "motion IA: revisão visual", imagens=True)
    assert cliente.atende(p, "roteirista: cenas") and cliente.atende(p, "trilha")
    assert cliente.atende(p, "motion IA: modelo")  # decisão de texto do motion segue com o cliente
    assert openrouter_local.visao(p) == ["gemini:gemini-3.1-flash-lite", "qwen/qwen3.7-flash"]
    sem = _projeto()
    assert cliente.atende(sem, "escolha das fotos")  # sem a chave de config, tudo segue com o cliente


def test_rota_gemini_na_cadeia(monkeypatch):
    from fabrica import gemini_local, openrouter_local
    chamadas = []

    def falso(projeto, etapa, instrucoes, pedido, esquema, log=print, modelo=None, imagens=(), temperatura=None,
              na_cadeia=False, raciocinio=None):
        chamadas.append((modelo, na_cadeia))
        return {"escolhas": [2]}

    monkeypatch.setattr(gemini_local, "perguntar", falso)
    p = _projeto(modelo="")
    p.config = {}
    r = openrouter_local.uma_rota(p, "escolha das fotos", "regras", "pedido", ESQUEMA, print, "gemini:gemini-3.8-flash",
                                  (), None)
    assert r == {"escolhas": [2]} and chamadas == [("gemini-3.8-flash", True)]


def test_andamento_em_linguagem_de_producao(monkeypatch):
    # o cliente vê "Escolhendo as imagens", nunca "Usou fabrica: esperar"
    from fabrica import mcp_servidor
    monkeypatch.setitem(mcp_servidor._PRODUCOES, "video-x", {"estado": "produzindo", "log": [
        "Mapa do roteiro", "Narração", "JSON de cenas", "Cenas", "Material real", "  imagens 3/10"]})
    e = mcp_servidor.progresso("video-x")
    assert e["estado"] == "produzindo" and e["titulo"] == "Escolhendo as imagens" and e["etapa"] == 4
    assert 42 < e["porcentagem"] < 60
    monkeypatch.setitem(mcp_servidor._PRODUCOES, "video-x", {"estado": "produzindo", "log": ["Render", "  clipes 8/16"]})
    assert mcp_servidor.progresso("video-x")["titulo"] == "Montando o vídeo"
    monkeypatch.setitem(mcp_servidor._PRODUCOES, "video-x", {"estado": "pronto", "log": []})
    assert mcp_servidor.progresso("video-x")["porcentagem"] == 100


def test_acompanhar_devolve_a_porcentagem_so_quando_muda(monkeypatch):
    from fabrica import mcp_servidor
    monkeypatch.setitem(mcp_servidor._PRODUCOES, "video-z", {"estado": "produzindo", "log": ["Cenas"],
                                                             "inicio": "2026-10-09T10:00:00", "fim": None})
    linha = mcp_servidor.acompanhar("video-z")
    assert linha.rsplit(" · ", 1)[1].count("min") == 1  # o tempo real de produção vai junto
    assert linha.startswith("Dividindo em cenas · ") and "etapa 3 de 7" in linha
    pct = int(linha.split("· ")[1].split("%")[0])
    assert mcp_servidor.acompanhar("video-z", ultima=pct, segundos=1) == "SEM MUDANÇA"
    monkeypatch.setitem(mcp_servidor._PRODUCOES, "video-z", {"estado": "pronto", "log": [],
                                                             "inicio": "2026-10-09T10:00:00", "fim": "2026-10-09T10:18:40"})
    assert mcp_servidor.acompanhar("video-z", ultima=pct, segundos=1) == "PRONTO · 100% · 18min40s"
