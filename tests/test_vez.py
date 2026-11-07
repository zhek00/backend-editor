"""Uma de cada vez: a segunda entrada espera a primeira sair, e 0 no config desliga o limite."""
import threading
import time

from fabrica import tempos, vez


class Projeto:
    def __init__(self, config):
        self.config = config


def test_segunda_espera_a_primeira(monkeypatch):
    monkeypatch.setattr(vez, "_SEMAFOROS", {})
    esperas = []
    monkeypatch.setattr(tempos, "medir", lambda p, nome, log=None: _Medida(esperas, nome))
    ordem = []
    p = Projeto({"vez": {"teste": 1}})

    def trabalho(nome):
        with vez.na_vez("teste", p, log=lambda *_: None):
            ordem.append(f"entra {nome}")
            time.sleep(0.15)
            ordem.append(f"sai {nome}")

    a = threading.Thread(target=trabalho, args=("a",))
    a.start()
    time.sleep(0.03)
    b = threading.Thread(target=trabalho, args=("b",))
    b.start()
    a.join(); b.join()
    assert ordem == ["entra a", "sai a", "entra b", "sai b"]
    assert esperas == ["Esperando a vez: teste"]


def test_zero_desliga(monkeypatch):
    monkeypatch.setattr(vez, "_SEMAFOROS", {})
    p = Projeto({"vez": {"teste": 0}})
    with vez.na_vez("teste", p):
        with vez.na_vez("teste", p):   # sem limite, entra de novo sem travar
            pass
    assert "teste" not in vez._SEMAFOROS


class _Medida:
    def __init__(self, lista, nome):
        self.lista, self.nome = lista, nome

    def __enter__(self):
        self.lista.append(self.nome)

    def __exit__(self, *_):
        return False
