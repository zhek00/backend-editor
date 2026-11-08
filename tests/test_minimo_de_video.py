"""Pelo menos 25% do material real é vídeo (pedido do usuário em 2026-11-07, pela retenção).

O 25-cavalos saiu com 505 fotos e nenhum vídeo de banco: o agente não tinha o tipo video_real e, sem a regra do
começo, nada trocava foto por vídeo."""
from fabrica import cenas, roteirista


def _fotos(n, **extra):
    return [{"n": i, "tipo": "foto_real", "ini": i * 4.0, "personagem": False, **extra} for i in range(n)]


def test_so_foto_ganha_o_minimo_de_video_espalhado():
    lista = _fotos(100)
    cenas._balancear_foto_e_video(lista, log=lambda *a: None)
    videos = [c["n"] for c in lista if c["tipo"] == "video_real"]
    assert len(videos) == 25
    assert min(videos) < 10 and max(videos) > 85          # do começo ao fim, não amontoado


def test_coisa_de_banco_vira_video_antes_da_que_tem_nome_exato():
    lista = _fotos(40)
    for c in lista[:20]:
        c["exato"] = "Mona Lisa"
    cenas._balancear_foto_e_video(lista, log=lambda *a: None)
    assert all(c["tipo"] == "foto_real" for c in lista[:20])
    assert sum(c["tipo"] == "video_real" for c in lista) == 10


def test_enumeracao_epoca_e_arquivo_ficam_foto():
    lista = _fotos(40, enumeracao=True) + [{"n": 100 + i, "tipo": "foto_real", "ini": 200 + i * 4.0, "epoca": "1898"}
                                           for i in range(10)]
    lista += [{"n": 200 + i, "tipo": "foto_real", "ini": 400 + i * 4.0, "onde_existe": "arquivo"} for i in range(10)]
    cenas._balancear_foto_e_video(lista, log=lambda *a: None)
    assert not any(c["tipo"] == "video_real" for c in lista)


def test_o_teto_de_30_continua():
    lista = [{"n": i, "tipo": "video_real", "ini": i * 4.0, "personagem": False} for i in range(100)]
    cenas._balancear_foto_e_video(lista, log=lambda *a: None)
    assert sum(c["tipo"] == "video_real" for c in lista) == 30


def test_o_agente_pode_pedir_video():
    assert "video_real" in roteirista.ESQUEMA_CENAS["properties"]["cenas"]["items"]["properties"]["tipo"]["enum"]
    bloco = {"id": 1, "ancora": "horse"}
    item = {"tipo": "video_real", "query": "horse galloping field", "onde_existe": "banco"}
    assert roteirista._converter(item, {}, bloco)["tipo"] == "video_real"
    # de época ou de arquivo, vídeo de banco não existe: fica foto
    assert roteirista._converter({**item, "epoca": "1898"}, {}, bloco)["tipo"] == "foto_real"
    assert roteirista._converter({**item, "onde_existe": "arquivo"}, {}, bloco)["tipo"] == "foto_real"
