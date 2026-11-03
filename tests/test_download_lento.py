"""Download com prazo total (midia._baixar): banco mandando a foto aos pouquinhos não segura a fila.

Caso real (2026-10-12): a criação ficou 17 min parada entre as cenas 334 e 336, sem nenhuma chamada a modelo, porque
um download recebia pedaços pequenos sem nunca passar 60 s calado (o timeout do httpx só pega o servidor calado)."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from fabrica import midia


class _Banco(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        if self.path == "/lento":
            for _ in range(40):  # 4 s mandando 10 bytes a cada 0,1 s: nunca fica calado
                try:
                    self.wfile.write(b"x" * 10)
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(0.1)
        else:
            self.wfile.write(b"y" * 1000)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def banco():
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Banco)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_port}"
    servidor.shutdown()


def test_banco_lento_desiste_no_prazo_e_nao_deixa_arquivo(banco, tmp_path):
    destino = tmp_path / "0001.jpg"
    inicio = time.monotonic()
    with httpx.Client(timeout=60) as http, pytest.raises(httpx.HTTPError):
        midia._baixar(http, f"{banco}/lento", destino, prazo=1)
    assert time.monotonic() - inicio < 3
    assert not destino.exists() and not list(tmp_path.glob("*.baixando"))


def test_download_normal_continua_funcionando(banco, tmp_path):
    destino = tmp_path / "0002.jpg"
    with httpx.Client(timeout=60) as http:
        midia._baixar(http, f"{banco}/rapido", destino)
    assert destino.read_bytes() == b"y" * 1000


def test_miniatura_lenta_fica_fora_da_folha(banco, monkeypatch):
    monkeypatch.setattr(midia, "PRAZO_MINIATURA", 1)
    with httpx.Client(timeout=60) as http:
        assert midia._miniatura(http, f"{banco}/lento") is None
