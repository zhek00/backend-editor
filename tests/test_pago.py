"""Modelo pago só depois de todos os gratuitos e com a confirmação da pessoa.

Caso real: em 05/10 o Qwen Flash pago escolheu as fotos do nunca-deve-ter-dentro-de-casa-parte-2 (1.412 chamadas,
US$ 2,59) sozinho, porque a cadeia passava para ele quando os gratuitos estavam no limite."""
import threading
import time
from types import SimpleNamespace

import pytest

from fabrica import openrouter_local, pago

GROQ, DOTS, PAGO = "groq:qwen/qwen3.8-27b", "dots-studio/dots-3-note-preview:free", "qwen/qwen3.8-flash"


@pytest.fixture
def projeto(tmp_path, monkeypatch):
    monkeypatch.setattr(openrouter_local, "_FORA_DO_AR", {})
    monkeypatch.setattr(pago, "_PEDIDOS", {})
    monkeypatch.setattr(pago, "responde_o_editor", False)
    monkeypatch.setattr(pago, "PASSO", 0.05)
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))
    return SimpleNamespace(nome="x", pasta=tmp_path, config={"openrouter": {"espera_pelo_gratis": 0}})


def _rotas(monkeypatch, falham):
    chamadas = []

    def uma_rota(projeto, etapa, instrucoes, pedido, esquema, log, rota, *a, **k):
        chamadas.append(rota)
        if rota in falham:
            raise openrouter_local.RotaIndisponivel("limite do dia")
        return {"ok": rota}

    monkeypatch.setattr(openrouter_local, "uma_rota", uma_rota)
    return chamadas


def _perguntar(projeto, cadeia):
    return openrouter_local.perguntar(projeto, "escolha", "i", "p", {}, log=lambda *_: None, modelo=cadeia[0],
                                      cadeia_de=cadeia)


def test_gratuitos_vao_antes_do_pago_mesmo_fora_de_ordem(projeto, monkeypatch):
    # na cadeia do agente o DeepSeek pago vinha antes do Groq
    chamadas = _rotas(monkeypatch, falham={DOTS})
    assert _perguntar(projeto, [DOTS, PAGO, GROQ]) == {"ok": GROQ}
    assert chamadas == [DOTS, GROQ]


def test_gratuitos_esgotados_param_sem_gastar(projeto, monkeypatch):
    chamadas = _rotas(monkeypatch, falham={GROQ, DOTS})
    with pytest.raises(pago.GratisEsgotado):
        _perguntar(projeto, [GROQ, DOTS, PAGO])
    assert PAGO not in chamadas


def test_gratis_esgotado_nao_e_engolido_por_except_exception():
    # os except Exception da fábrica mandariam a cena para o tapa-buraco ou para a imagem de IA (paga)
    assert not issubclass(pago.GratisEsgotado, Exception)


def test_pago_liberado_hoje_segue(projeto, monkeypatch):
    chamadas = _rotas(monkeypatch, falham={GROQ, DOTS})
    pago.liberar(projeto)
    assert _perguntar(projeto, [GROQ, DOTS, PAGO]) == {"ok": PAGO}
    assert chamadas[-1] == PAGO


def test_liberacao_de_ontem_nao_vale(projeto):
    (projeto.pasta / pago.ARQUIVO).write_text('{"dia": "2026-10-05"}', encoding="utf-8")
    assert not pago.liberado(projeto)


def test_jev_sem_gratuito_na_cadeia_nao_pergunta(projeto, monkeypatch):
    # o juiz e quem só existe pago de propósito seguem como antes
    _rotas(monkeypatch, falham=set())
    assert _perguntar(projeto, ["typesafe/jev-router"]) == {"ok": "typesafe/jev-router"}


def test_editor_espera_a_pessoa_liberar(projeto, monkeypatch):
    monkeypatch.setattr(pago, "responde_o_editor", True)
    monkeypatch.setattr(pago, "ESPERA_MINIMA", 30)
    chamadas = _rotas(monkeypatch, falham={GROQ, DOTS})
    resultado = {}
    tarefa = threading.Thread(target=lambda: resultado.update(r=_perguntar(projeto, [GROQ, DOTS, PAGO])))
    tarefa.start()
    for _ in range(100):
        if pago.pendente("x"):
            break
        time.sleep(0.02)
    aviso = pago.pendente("x")
    assert aviso["modelo"] == PAGO and aviso["etapa"] == "escolha"
    assert PAGO not in chamadas  # esperando, nada foi gasto
    pago.liberar(projeto)
    tarefa.join(5)
    assert resultado["r"] == {"ok": PAGO} and pago.pendente("x") is None


def test_editor_volta_ao_gratuito_quando_ele_volta(projeto, monkeypatch):
    monkeypatch.setattr(pago, "responde_o_editor", True)
    chamadas, no_limite = [], {GROQ, DOTS}

    def uma_rota(projeto, etapa, instrucoes, pedido, esquema, log, rota, *a, **k):
        chamadas.append(rota)
        if rota in no_limite:
            # limite do minuto: fica de lado um instante e depois volta a atender
            no_limite.discard(rota)
            openrouter_local._FORA_DO_AR[rota] = time.time() + 0.2
            raise openrouter_local.RotaIndisponivel("limite do minuto")
        return {"ok": rota}

    monkeypatch.setattr(openrouter_local, "uma_rota", uma_rota)
    assert _perguntar(projeto, [GROQ, DOTS, PAGO]) == {"ok": GROQ}
    assert PAGO not in chamadas and pago.pendente("x") is None

def _uso(projeto, *custos):
    import json
    (projeto.pasta / "uso_openrouter.json").write_text(
        json.dumps([{"quando": "2026-10-10T10:00:00", "modelo": PAGO, "custo_usd": c} for c in custos]), encoding="utf-8")


def _automatico(projeto, minutos=None):
    projeto.config["openrouter"].update(confirmar_pago=False, teto_pago_por_minuto=0.06, teto_pago_minimo=0.5)
    if minutos:
        (projeto.pasta / "alinhamento.json").write_text(f'{{"unidades": [{{"fim": {minutos * 60}}}]}}', encoding="utf-8")


def test_pago_automatico_segue_sem_perguntar(projeto, monkeypatch):
    # pedido do usuário em 2026-10-10: "a edição jamais deve parar, exceto se tiver alto consumo de tokens". O
    # brasil-selvagem (20 min) ficou quase 2 h esperando o clique com a cota do Groq cheia
    _automatico(projeto, minutos=20)
    _uso(projeto, 0.30, 0.20)  # US$ 0,50, abaixo do teto de 20 x 0,06 = US$ 1,20
    chamadas = _rotas(monkeypatch, falham={GROQ, DOTS})
    assert _perguntar(projeto, [GROQ, DOTS, PAGO]) == {"ok": PAGO}
    assert chamadas[-1] == PAGO


def test_consumo_alto_para_sem_gastar(projeto, monkeypatch):
    # o Qwen pago pensando escolheu as fotos do nunca-deve-ter-dentro-de-casa-parte-2: US$ 2,59 num vídeo de 30 min
    _automatico(projeto, minutos=30)
    _uso(projeto, 2.59)  # acima do teto de 30 x 0,06 = US$ 1,80
    chamadas = _rotas(monkeypatch, falham={GROQ, DOTS})
    with pytest.raises(pago.GratisEsgotado, match="onsumo alto"):
        _perguntar(projeto, [GROQ, DOTS, PAGO])
    assert PAGO not in chamadas


def test_consumo_alto_liberado_segue(projeto, monkeypatch):
    _automatico(projeto, minutos=30)
    _uso(projeto, 2.59)
    pago.liberar(projeto)
    _rotas(monkeypatch, falham={GROQ, DOTS})
    assert _perguntar(projeto, [GROQ, DOTS, PAGO]) == {"ok": PAGO}


def test_teto_minimo_para_video_curto(projeto):
    _automatico(projeto, minutos=2)
    assert pago.teto(projeto) == 0.5  # 2 x 0,06 = 0,12 seria pouco para um vídeo curto
