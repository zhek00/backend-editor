"""Gravação do cenas.json à prova de Windows (util.gravar_atomico).

Caso real (2026-10-12, 12-animais-estranhos): a cena animada 434 a 436 se perdeu com "[WinError 5] Acesso negado:
cenas.json.tmp": a troca do temporário pelo arquivo falha enquanto outra parte está lendo, e todas as gravações usavam
o mesmo temporário."""
import json
import threading
import time

from fabrica.util import gravar_atomico


def test_espera_quem_esta_lendo_e_grava(tmp_path):
    destino = tmp_path / "cenas.json"
    destino.write_text('{"v": 0}', encoding="utf-8")
    leitor = open(destino, encoding="utf-8")  # no Windows, segura o arquivo e a troca falha enquanto estiver aberto
    erros = []

    def gravar():
        try:
            gravar_atomico(destino, '{"v": 1}')
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    t = threading.Thread(target=gravar)
    t.start()
    time.sleep(0.6)
    leitor.close()
    t.join(timeout=15)
    assert not erros
    assert json.loads(destino.read_text(encoding="utf-8")) == {"v": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_muitas_gravacoes_ao_mesmo_tempo_nao_se_atropelam(tmp_path):
    destino = tmp_path / "cenas.json"
    erros = []

    def gravar(i):
        try:
            gravar_atomico(destino, json.dumps({"v": i, "texto": "x" * 50_000}))
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    threads = [threading.Thread(target=gravar, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not erros
    assert json.loads(destino.read_text(encoding="utf-8"))["v"] in range(12)  # um arquivo inteiro, nunca pela metade
    assert not list(tmp_path.glob("*.tmp"))
