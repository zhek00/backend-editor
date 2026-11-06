"""O que evita esperar por quem empacou: a tarefa de voz presa e o modelo gratuito que não responde."""
import time

import pytest

from fabrica import genaipro, openrouter_local


class Resposta:
    def __init__(self, dados):
        self.dados = dados

    def json(self):
        return self.dados


def _falso(monkeypatch, estados, relogio):
    """estados: id -> quantas leituras até ficar pronta (None: nunca)."""
    pedidos = []

    def pedir(metodo, caminho, **kw):
        if metodo == "POST":
            pedidos.append(kw["json"])
            return Resposta({"task_id": "copia"})
        tarefa = caminho.rsplit("/", 1)[1]
        relogio[0] += 100
        falta = estados[tarefa]
        if falta is not None and falta <= 0:
            return Resposta({"result": f"http://x/{tarefa}.mp3"})
        if falta is not None:
            estados[tarefa] = falta - 1
        return Resposta({"status": "processing"})

    monkeypatch.setattr(genaipro, "_pedir", pedir)
    monkeypatch.setattr(genaipro.time, "time", lambda: relogio[0])
    monkeypatch.setattr(genaipro.time, "sleep", lambda _s: None)
    return pedidos


def test_tarefa_rapida_nao_paga_copia(monkeypatch):
    pedidos = _falso(monkeypatch, {"a": 1}, [0])
    assert genaipro._esperar_com_reserva("a", {"text": "x"}, log=lambda *_: None)[0] == "a"
    assert pedidos == []


def test_tarefa_presa_ganha_uma_copia_e_vale_a_primeira_pronta(monkeypatch):
    pedidos = _falso(monkeypatch, {"a": None, "copia": 2}, [0])
    assert genaipro._esperar_com_reserva("a", {"text": "x"}, log=lambda *_: None)[0] == "copia"
    assert pedidos == [{"text": "x"}]


def test_a_original_ainda_vale_se_terminar_primeiro(monkeypatch):
    pedidos = _falso(monkeypatch, {"a": 4, "copia": None}, [0])
    assert genaipro._esperar_com_reserva("a", {"text": "x"}, log=lambda *_: None)[0] == "a"
    assert len(pedidos) == 1


def test_prazo_devolve_o_resultado_e_o_erro():
    assert openrouter_local._com_prazo(1, lambda: 5) == 5
    with pytest.raises(ValueError):
        openrouter_local._com_prazo(1, lambda: int("x"))


def test_prazo_nao_espera_quem_empacou():
    comeco = time.time()
    with pytest.raises(TimeoutError):
        openrouter_local._com_prazo(0.05, lambda: time.sleep(5))
    assert time.time() - comeco < 1
