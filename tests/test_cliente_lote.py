"""MCP: escolha e julgamento numa tarefa só, várias cenas por tarefa (midia._escolher_pelo_cliente,
corrigir._avaliar_pelo_cliente). No teste mcp-pangolim, 3 cenas deram 12 tarefas de escolha e conferência; agora 1 a 2."""
import threading
import time
from types import SimpleNamespace

import pytest

from fabrica import cliente, corrigir, midia


@pytest.fixture(autouse=True)
def fila_limpa(monkeypatch):
    monkeypatch.setattr(cliente, "_TAREFAS", {})
    monkeypatch.setattr(midia, "_JUIZOS_DO_CLIENTE", {})


@pytest.fixture
def projeto(tmp_path):
    return SimpleNamespace(nome="video", dados={"modelo": "cliente"}, config={}, pasta=tmp_path, perfil={},
                           existe=lambda nome: False)


def _cena(n, texto):
    return {"n": n, "texto": texto, "ini": 0.0, "fim": 4.0, "mostrar": f"o que a cena {n} mostra", "busca": "pangolin",
            "prompt": "", "sujeito": "pangolin", "tipo": "foto_real", "aceitavel": "pangolim"}


def _responder_quando_chegar(resposta):
    for _ in range(300):
        tarefas = cliente.proximas(limite=8)
        if tarefas:
            return tarefas, cliente.responder(tarefas[0]["id"], resposta)
        time.sleep(0.01)
    raise AssertionError("nenhuma tarefa chegou")


def test_escolha_de_varias_cenas_numa_tarefa_ja_com_o_julgamento(projeto, tmp_path):
    from PIL import Image

    folhas, pendentes, candidatos = {}, [], {}
    for n in (1, 2):
        folha = tmp_path / f"cena_{n}.jpg"
        Image.new("RGB", (1920, 810), (40, 40, 40)).save(folha)
        folhas[n] = (folha, [0, 1])
        pendentes.append((_cena(n, f"fala {n}"), None, None))
        candidatos[n] = [{"tipo": "foto", "fonte": "pexels", "descricao": "pangolin, pangolin, scales, pangolin"},
                         {"tipo": "foto", "fonte": "pixabay", "descricao": "armadillo"}]
    vejos, juizos, saida = {}, {}, {}
    fio = threading.Thread(target=lambda: saida.update(r=midia._escolher_pelo_cliente(
        projeto, pendentes, candidatos, folhas, "escolha", True, vejos, juizos)), daemon=True)
    fio.start()

    def vejo(i, combina, sujeito):
        return {"indice": i, "o_que_e": "pangolim", "certeza": "alta", "detalhes": "escamas", "cenario": "floresta",
                "acao": "andando", "tipo_imagem": "foto real", "texto_visivel": "nenhum", "epoca_aparente": "indefinida",
                "confere": "sim", "motivo": "é o pangolim", "combina": combina, "sujeito": sujeito}
    tarefas, ok = _responder_quando_chegar({"cenas": [
        {"cena": 1, "escolhas": [0], "vejo": [vejo(0, 92, 98)]},
        {"cena": 2, "escolhas": [1, 0], "vejo": [vejo(1, 30, 10), vejo(0, 70, 95)]}]})
    fio.join(2)
    assert len(tarefas) == 1 and len(tarefas[0]["imagens"]) == 2  # as duas cenas na mesma tarefa
    assert "[imagem 2]" in tarefas[0]["pedido"] and str(folhas[2][0]) not in tarefas[0]["pedido"]
    # a folha vai menor (1280 px) e a descrição sem as tags repetidas
    import base64
    from io import BytesIO
    assert Image.open(BytesIO(base64.b64decode(tarefas[0]["imagens"][0]["dados"]))).width == 1280
    assert "pangolin, scales" in tarefas[0]["pedido"] and "pangolin, pangolin" not in tarefas[0]["pedido"]
    assert "combina" in tarefas[0]["esquema"]["properties"]["cenas"]["items"]["properties"]["vejo"]["items"]["required"]
    assert ok["ok"] and saida["r"] == {1: [0], 2: [1, 0]}
    assert juizos[2][1] == {"nota": 30, "sujeito": 10, "epoca": None}

    # o julgamento vale no lugar do Jev antes do download, sem outra tarefa
    candidatos = [{"fonte": "pexels", "id": "a"}, {"fonte": "pexels", "id": "b"}]
    midia._lembrar_juizos(projeto, 2, candidatos, {str(i): j for i, j in juizos[2].items()})
    julgamento = midia._nota_do_candidato(projeto, _cena(2, "fala 2"), candidatos[1], vejos[2][1], {}, print)
    assert julgamento["nota"] == 30 and julgamento["sujeito"] == 10 and cliente.pendentes() == 0
    assert corrigir.errada(julgamento)  # sujeito errado: o tatu no lugar do pangolim


def test_conferencia_depois_do_download_ve_e_julga_numa_tarefa(projeto, tmp_path, monkeypatch):
    quadro = tmp_path / "quadro.jpg"
    quadro.write_bytes(b"jpg")
    monkeypatch.setattr(corrigir, "_quadros", lambda p, c: [quadro])
    guardadas = {}
    monkeypatch.setattr(corrigir, "_guardar_legendas", lambda p, legendas: guardadas.update(legendas))
    cenas = [_cena(1, "o pangolim"), _cena(2, "ele se enrola")]
    saida = {}
    fio = threading.Thread(target=lambda: saida.update(r=corrigir._avaliar_pelo_cliente(
        projeto, cenas, {1: "o pangolim", 2: "ele se enrola"}, print, 40)[0]), daemon=True)
    fio.start()
    vista = {"o_que_e": "pangolim", "certeza": "alta", "detalhes": "escamas", "cenario": "museu", "acao": "parado",
             "tipo_imagem": "foto real", "texto_visivel": "nenhum", "epoca_aparente": "indefinida"}
    tarefas, ok = _responder_quando_chegar({"cenas": [
        {"n": 1, **vista, "combina": 95, "sujeito": 98, "busca_nova": "", "prompt_novo": ""},
        {"n": 2, **vista, "combina": 35, "sujeito": 90, "busca_nova": "curled up pangolin", "prompt_novo": "a pangolin"}]})
    fio.join(2)
    assert len(tarefas) == 1 and ok["ok"]
    r = saida["r"]
    assert r[1]["nota"] == 95 and r[2]["nota"] == 35 and r[2]["busca_nova"] == "curled up pangolin"
    assert not corrigir.errada(r[2])  # sujeito certo com nota baixa fica (regra da fábrica)
    assert guardadas[1].startswith("O que é: pangolim")


def test_tudo_so_confere_depois_do_download_o_que_ficou_na_duvida(monkeypatch):
    cenas = [{"n": 1, "captura": {"conferida": True, "nota": 92}},
             {"n": 2, "captura": {"conferida": True, "nota": 92, "suspeita": True}},
             {"n": 3, "captura": {"conferida": True, "nota": 35}},
             {"n": 4, "captura": {}}]
    monkeypatch.setattr(corrigir, "conferiveis", lambda p, numeros=None: cenas)
    monkeypatch.setattr(midia, "nota_minima_da_conferencia", lambda p: 40)
    assert corrigir.na_duvida(SimpleNamespace()) == {2, 3, 4}


def test_revisao_do_cliente_so_olha_o_que_ele_nao_viu_pronto(projeto, monkeypatch):
    # mcp-cafe-5min: 88 quadros revisados; o que a revisão achou de novo estava nas cenas com animação
    from fabrica import animacoes, revisao_video
    monkeypatch.setattr(animacoes, "cenas_cobertas", lambda p, cenas: {3})
    midia_ok = {"fonte": "pexels", "tipo": "foto"}
    cenas = [
        {"n": 1, "midia": midia_ok, "captura": {"conferida": True, "nota": 88}},           # já julgada: fica de fora
        {"n": 2, "midia": midia_ok, "captura": {"suspeita": True, "preenchida": "busca"}},  # tapada sem ele aprovar
        {"n": 3, "midia": midia_ok, "captura": {"conferida": True, "nota": 90}},           # animação por cima
        {"n": 4, "midia": {"fonte": "motion_ia", "tipo": "video"}, "captura": {}},          # clipe do Motion IA
        {"n": 5, "midia": midia_ok, "captura": {}, "conferencia": {"nota": 2}},             # ficou reprovada
        {"n": 6, "midia": midia_ok, "captura": {}, "conferencia": {"nota": 85}},            # aprovada na conferência
        {"n": 7, "tipo": "ia", "midia": None, "captura": {}},                                 # imagem de IA
    ]
    assert revisao_video.cenas_que_o_cliente_ainda_nao_viu(projeto, cenas) == {2, 3, 4, 5, 7}
