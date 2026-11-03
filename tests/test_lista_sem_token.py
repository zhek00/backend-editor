"""A lista de projetos sem token só vale para o próprio computador (o LIGAR e o VIGIA conferindo a fábrica).

Caso real de 2026-10-20: com forwarded_allow_ips="*", um "X-Forwarded-For: 127.0.0.1" escrito por quem pede abria a
lista de projetos para quem viesse pelo túnel ou pela rede."""
from types import SimpleNamespace

from fabrica import api, cli


def _pedido(ip, **cabecalhos):
    return SimpleNamespace(client=SimpleNamespace(host=ip), headers={k.lower(): v for k, v in cabecalhos.items()})


def test_o_proprio_computador_ve_a_lista_sem_token():
    assert api.pedido_do_proprio_computador(_pedido("127.0.0.1"))
    assert api.pedido_do_proprio_computador(_pedido("::1"))


def test_pedido_de_fora_nunca_ve():
    assert not api.pedido_do_proprio_computador(_pedido("8.8.8.8"))
    assert not api.pedido_do_proprio_computador(_pedido("192.168.0.20"))


def test_pedido_pelo_tunel_nunca_ve_mesmo_chegando_por_127():
    # o túnel da Cloudflare entrega tudo por 127.0.0.1, sempre com os cabeçalhos dele
    assert not api.pedido_do_proprio_computador(_pedido("127.0.0.1", **{"X-Forwarded-For": "127.0.0.1, 8.8.8.8"}))
    assert not api.pedido_do_proprio_computador(_pedido("127.0.0.1", **{"Cf-Connecting-Ip": "8.8.8.8"}))


def test_so_o_tunel_local_diz_quem_pede():
    assert "*" not in cli.PROXIES_CONFIAVEIS
    assert set(cli.PROXIES_CONFIAVEIS.split(",")) == {"127.0.0.1", "::1"}


def test_vigia_confere_numa_rota_que_responde_na_hora(monkeypatch):
    # 2026-10-27: a /api/projetos lia o cenas.json e o perfil de todo projeto e passava dos 20 s com a criação
    # ocupada; o vigia achava que a fábrica travou e reiniciava no meio do vídeo (4 vezes no tescos-60-billion)
    from fastapi.testclient import TestClient

    monkeypatch.setenv("FABRICA_TOKEN", "segredo")
    cliente = TestClient(api.app)
    resposta = cliente.get("/api/saude", headers={"host": "localhost"})
    assert resposta.status_code == 200 and resposta.json() == {"ok": True}
    # pelo túnel, sem token, continua fechada
    assert cliente.get("/api/saude", headers={"host": "editor.bbnews.cc", "cf-connecting-ip": "8.8.8.8"}).status_code == 401
