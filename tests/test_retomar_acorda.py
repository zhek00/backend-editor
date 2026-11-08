"""O Retomar faz a criação que espera a próxima tentativa tentar na hora (pedido do usuário em 2026-11-08)."""
import threading
import time

from fabrica import api


def test_acordar_corta_a_espera():
    fim = {}

    def esperar():
        comeco = time.monotonic()
        api._esperar("projeto-x", 30)
        fim["levou"] = time.monotonic() - comeco

    t = threading.Thread(target=esperar)
    t.start()
    for _ in range(100):
        if "projeto-x" in api.ACORDAR:
            break
        time.sleep(0.01)
    assert api.acordar("projeto-x")
    t.join(5)
    assert fim["levou"] < 5 and "projeto-x" not in api.ACORDAR


def test_sem_espera_nao_acorda_nada():
    assert not api.acordar("ninguem-esperando")


def test_a_etapa_tenta_de_novo_depois_de_acordada(monkeypatch, tmp_path):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "projeto.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(api, "PROJETOS", tmp_path)
    monkeypatch.setattr(api, "_log_tarefa", lambda *a: None)
    monkeypatch.setattr(api, "_atualizar", lambda *a, **k: None)
    monkeypatch.setattr(api, "_ESPERAS", [60])
    monkeypatch.setattr(api, "TENTATIVAS_POR_ETAPA", 1)
    vezes = []

    def funcao():
        vezes.append(1)
        if len(vezes) == 1:
            threading.Timer(0.3, lambda: api.acordar("p")).start()
            raise RuntimeError("um serviço caiu")
        return "ok"
    comeco = time.monotonic()
    assert api._etapa_tentando("t", "p", "Narração", funcao) == "ok"
    assert len(vezes) == 2 and time.monotonic() - comeco < 10
