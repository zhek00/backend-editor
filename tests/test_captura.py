"""Os filtros da captura, com os casos reais que já deram errado em vídeos de verdade.

Rode com: uv run --no-sync --with pytest python -m pytest tests
Sem rede e sem custo: nenhum banco de imagens nem modelo é chamado.
"""
from fabrica import cenas as cenas_mod
from fabrica import midia, roteirista

F = lambda descricao: {"descricao": descricao}

# cenas do virou-filme-em-1996 (os leões de Tsavo, 1898), como o agente as escreveu
ACAMPAMENTO = {"n": 3, "tipo": "foto_real", "busca": "Tsavo labor camp construction", "sujeito": "Tsavo railway workers",
               "exato": "Tsavo railway workers camp", "animal": "", "busca_alternativa": "",
               "prompt": "Wide view of a colonial railway workers camp with canvas tents near the Tsavo River"}
LEAO_FERIDO = {"n": 99, "tipo": "foto_real", "busca": "wounded lion advancing beneath tree", "sujeito": "leão de Tsavo",
               "exato": "Tsavo lion", "animal": "Tsavo lion", "busca_alternativa": "Panthera leo",
               "prompt": "A wounded maneless lion advancing beneath a tree"}
RESTOS = {"n": 29, "tipo": "video_real", "busca": "human bones dry savanna", "sujeito": "restos mortais", "exato": "",
          "animal": "", "busca_alternativa": "archaeological human remains", "prompt": "Human remains on dry savanna soil"}
TRANCA = {"n": 67, "tipo": "foto_real", "busca": "bullet shattered door latch", "sujeito": "tranca quebrada",
          "exato": "", "animal": "", "busca_alternativa": "damaged wooden cage latch",
          "prompt": "A bullet breaks the wooden latch of a trap door"}
LATAS = {"n": 40, "tipo": "foto_real", "busca": "worker striking metal tin", "sujeito": "worker striking metal",
         "exato": "", "animal": "", "busca_alternativa": "", "prompt": "Workers bang metal tins to make noise at night"}


def passa(cena, descricao, bloco=None):
    """A mesma regra do tapa-buraco (midia._preencher_vazias)."""
    bloco = bloco or {}
    exigido = midia.exigido_da_cena(bloco, cena, ())
    animal = midia.animal_da_cena(bloco, cena)
    x = F(descricao)
    if not animal and midia._mostra_outro_bicho(cena, x):
        return False
    if exigido:
        return midia._cita_o_assunto(exigido, x)
    return midia._cita_bastante(midia._radicais(midia.sujeito_da_busca(cena)), x)


def test_bicho_de_tsavo_nao_passa_no_acampamento():
    assert not passa(ACAMPAMENTO, "red elephant Tsavo Kenya savanna")
    assert not passa(ACAMPAMENTO, "group of vehicles on a dirt road Tsavo")


def test_outro_bicho_de_tsavo_nao_passa_por_leao():
    assert not passa(LEAO_FERIDO, "zebra Tsavo animal africa safari")
    assert not passa(LEAO_FERIDO, "chicken park tsavo")
    assert passa(LEAO_FERIDO, "lion male savanna Kenya")


def test_uma_palavra_so_nao_basta():
    assert not passa(RESTOS, "classic mustang fastback car dry")
    assert not passa(LATAS, "spray cans colour paint cans metal")


def test_sujeito_em_portugues_sem_acento_cede_a_busca():
    assert midia.sujeito_da_busca(TRANCA) == TRANCA["busca"]
    assert not passa(TRANCA, "quebrada de las conchas argentina")


def test_nome_inteiro_e_nao_quatro_letras():
    assert not midia._cita_o_nome("Patterson", F("abstract pattern texture"))
    assert not midia._cita_o_nome("Tsavo", F("tsavorite gemstone"))
    assert midia._cita_o_nome("Tsavo", F("Tsavo East National Park"))


def test_cabeca_do_animal_e_o_substantivo():
    assert midia._cabeca_do_animal("maneless Tsavo lion") == ["lion"]
    assert midia._cabeca_do_animal("spectacled cobra") == ["cobr"]
    assert midia._cabeca_do_animal("plains zebra") == ["zebr"]


def test_exato_com_nome_e_coisa_exige_os_dois():
    assert sorted(midia._identificador("Tsavo railway workers camp")) == ["camp", "tsav"]
    assert midia.exigido_da_cena({}, {"exato": "Palácio de Westminster"}, ()) == set()


def test_genero_cientifico():
    # o regex tinha um caractere invisível no lugar de \\b e nunca achava nada
    assert midia._generos_cientificos("Naja naja") == {"naja"}


def test_recusa_do_modelo():
    assert midia._disse_que_nao("Quem viu a imagem diz que confere com o pedido: nao (elefante).")
    assert not midia._disse_que_nao("Quem viu a imagem diz que confere com o pedido: parcial (x).")


def test_cena_de_epoca_vai_ao_arquivo_e_nunca_vira_video():
    assert midia._e_de_acervo({"epoca": "1898", "busca": "Uganda Railway 1899"}) == "epoca"
    assert roteirista._epoca("1898") == "1898" and roteirista._epoca("2009") == ""
    lista = [{"n": i, "tipo": "video_real" if i % 2 else "foto_real", "ini": i * 4.0, "personagem": False,
              **({"epoca": "1898"} if i < 6 else {})} for i in range(30)]
    cenas_mod._balancear_foto_e_video(lista, log=lambda *a: None)
    assert all(c["tipo"] == "foto_real" for c in lista if c.get("epoca"))


# ---------------------------------------------------------------- o modelo que escolhe recusou todos (natureza-nos-ensina)

CROCODILO = {"n": 54, "tipo": "foto_real", "busca": "Crocodylus niloticus", "sujeito": "Nile crocodile",
             "exato": "Nile crocodile", "animal": "Nile crocodile", "busca_alternativa": "Crocodylus niloticus",
             "texto": "que espera em silêncio: o crocodilo-do-nilo.",
             "mostrar": "Crocodilo-do-nilo imóvel na água, apenas olhos e narinas acima da superfície."}


def test_recusou_tudo_entram_os_do_assunto(monkeypatch):
    # o modelo recusou 11 fotos boas de crocodilo porque nenhuma era "só olhos e narinas na água"
    monkeypatch.setattr(midia, "nomes_do_roteiro", lambda projeto: set())
    candidatos = [{"descricao": "nile crocodile resting on riverbank sand"},
                  {"descricao": "zebra crossing a river"},
                  {"descricao": "crocodile Crocodylus niloticus Nile open mouth"}]
    assert midia._do_assunto_quando_recusou(None, CROCODILO, candidatos) == [0, 2]


def test_captura_aceita_sujeito_certo_com_nota_baixa(monkeypatch):
    # leoas andando para "caçam em grupo, cercando a presa": nota 12, sujeito 90. É cena genérica e fica
    leoas = {"n": 19, "tipo": "video_real", "busca": "lionesses hunting group savanna", "sujeito": "lionesses",
             "exato": "", "animal": "lion", "texto": "caçam em grupo, com estratégia e paciência, cercando a presa"}
    julgamentos = {0: {"nota": 12, "sujeito": 90}, 1: {"nota": 10, "sujeito": 20}}
    monkeypatch.setattr(midia, "_nota_do_candidato", lambda p, c, cand, f, v, l: julgamentos[cand["i"]])
    monkeypatch.setattr(midia, "nomes_do_roteiro", lambda projeto: set())
    projeto = type("P", (), {"config": {}})()
    candidatos = [{"i": 0, "fonte": "pexels", "id": 1, "descricao": "lionesses walking savanna"},
                  {"i": 1, "fonte": "pexels", "id": 2, "descricao": "house cat"}]
    escolhido, info = midia._escolher_conferindo(projeto, leoas, [0, 1], candidatos, {0: "leoas", 1: "gato"},
                                                  set(), {}, print)
    assert escolhido["i"] == 0 and info["suspeita"]


def test_captura_recusa_sujeito_errado(monkeypatch):
    julgamentos = {0: {"nota": 12, "sujeito": 10}}
    monkeypatch.setattr(midia, "_nota_do_candidato", lambda p, c, cand, f, v, l: julgamentos[cand["i"]])
    monkeypatch.setattr(midia, "nomes_do_roteiro", lambda projeto: set())
    projeto = type("P", (), {"config": {}})()
    escolhido, _ = midia._escolher_conferindo(projeto, CROCODILO, [0], [{"i": 0, "fonte": "x", "id": 1,
                                                                         "descricao": "iguana by the lake"}],
                                               {0: "iguana"}, set(), {}, print)
    assert escolhido is None


# ---------------------------------------------------------------- "não existe" passa pelo acervo antes da IA

class _ProjetoFalso:
    def __init__(self, pasta, cenas):
        self.pasta, self.offline, self.config = pasta, False, {}
        self.dados = {"cenas.json": {"cenas": cenas}}

    def ler_json(self, nome):
        return self.dados[nome]

    def salvar_json(self, nome, dados):
        self.dados[nome] = dados

    def imagem(self, n):
        return self.pasta / f"imagens/{n:04d}.png"


def test_nao_existe_so_fica_com_foto_aprovada(tmp_path):
    # elefante derrubando árvore: o agente achou que não existe; a busca achou e o Jev aprovou com 72
    (tmp_path / "midia").mkdir()
    (tmp_path / "midia" / "0033.jpg").write_bytes(b"x")
    cenas = [
        {"n": 32, "tipo": "foto_real", "midia": {"arquivo": "midia/0032.jpg", "fonte": "pexels", "id": "1"},
         "captura": {"conferida": True, "nota": 72}},
        {"n": 33, "tipo": "foto_real", "midia": {"arquivo": "midia/0033.jpg", "fonte": "pixabay", "id": "2"},
         "captura": {"conferida": True, "nota": 55, "suspeita": True}},
        {"n": 34, "tipo": "foto_real", "sem_midia_real": True},
    ]
    projeto = _ProjetoFalso(tmp_path, cenas)
    assert midia._so_as_aprovadas(projeto, {32, 33, 34}, log=lambda *a: None) == [32]
    final = {c["n"]: c for c in projeto.dados["cenas.json"]["cenas"]}
    assert final[32]["tipo"] == "foto_real"
    assert final[33]["tipo"] == "ia" and "midia" not in final[33] and "pixabay:2" in final[33]["rejeitadas"]
    assert not (tmp_path / "midia" / "0033.jpg").exists()
    assert final[34]["tipo"] == "ia" and "sem_midia_real" not in final[34]


def test_nao_existe_e_tentado_uma_vez(tmp_path, monkeypatch):
    cenas = [{"n": 1, "tipo": "ia", "onde_existe": "nao_existe", "busca_reserva": "elephant pushing tree"},
             {"n": 2, "tipo": "ia", "onde_existe": "nao_existe", "busca_reserva": "x", "banco_tentado": True},
             {"n": 3, "tipo": "ia", "onde_existe": "nao_existe", "busca_reserva": "y", "prompt_manual": "da pessoa"}]
    projeto = _ProjetoFalso(tmp_path, cenas)
    monkeypatch.setattr(midia, "ia_ativa", lambda p: True)
    buscadas = []
    monkeypatch.setattr(midia, "_buscar", lambda p, apenas, log, permissivo: buscadas.append(set(apenas)))
    midia.tentar_banco_nas_nao_existe(projeto, log=lambda *a: None)
    assert buscadas == [{1}]
    assert projeto.dados["cenas.json"]["cenas"][0]["banco_tentado"]


def test_exato_dentro_da_busca_tambem_e_buscado_sozinho():
    # mcp-cafe-5min, cena 35: "New York stock exchange screen" não achava nada na Wikimedia, e o exato sozinho nunca
    # era buscado. Os candidatos caíam todos no filtro do exato e entrou um túnel de trem
    buscadas = []

    def das_fontes(tipo, busca, preferida=None, acervo=False):
        buscadas.append(busca)
        if busca == "New York Stock Exchange":
            return [{"fonte": "wikimedia", "id": str(i), "descricao": f"New York Stock Exchange trading floor {i}"}
                    for i in range(3)]
        return [{"fonte": "pexels", "id": busca, "descricao": "stock market screen chart"}]

    b = object.__new__(midia.Buscador)
    b.blocos, b.nomes, b.quantidade, b.log = {}, set(), 24, lambda *a: None
    b._das_fontes = das_fontes
    cena = {"n": 35, "tipo": "foto_real", "busca": "New York stock exchange screen", "exato": "New York Stock Exchange",
            "busca_alternativa": "stock market screen", "sujeito": "stock exchange screen"}
    achados = b.candidatos(cena)
    assert "New York Stock Exchange" in buscadas
    assert achados[0]["fonte"] == "wikimedia"


def test_assunto_do_video_nao_tapa_cena_que_exige_outra_coisa():
    # mcp-cafe-5min, cena 35: o túnel da Mantiqueira cita o assunto do vídeo, mas a cena exige a bolsa de Nova York
    cena = {"n": 35, "exato": "New York Stock Exchange", "busca": "stock exchange trading screen"}
    tunel = {"descricao": "Túnel da Mantiqueira boca mineira railway tunnel"}
    exigido = midia.exigido_da_cena({}, cena, set())
    assert not midia._serve_pelo_assunto_do_video(cena, tunel, "Mantiqueira", set(), exigido)
    assert midia._serve_pelo_assunto_do_video({"n": 1}, tunel, "Mantiqueira", set())


# ---------------------------------------------------------------- banco que cai: tenta de novo, e cai seguido sai um tempo

def _buscador(tmp_path, funcao):
    import threading
    b = object.__new__(midia.Buscador)
    b.desligadas, b.bloqueada_ate, b.quedas, b.trava = set(), {}, {}, threading.Lock()
    b.log = lambda *a: None
    b.projeto = type("P", (), {"caminho": lambda self, *partes: tmp_path.joinpath(*partes)})()
    (tmp_path / "midia" / "buscas").mkdir(parents=True, exist_ok=True)
    b._pexels = funcao
    return b


def test_cache_de_busca_pela_metade_nao_derruba_a_producao(tmp_path, monkeypatch):
    # 11-animais-do-brasil pelo MCP: duas cenas com a mesma busca, e uma leu o cache vazio no meio da gravação da outra
    import hashlib
    b = _buscador(tmp_path, lambda tipo, busca: [{"fonte": "pexels", "id": "9"}])
    b._aguardar = lambda fonte: True
    codigo = hashlib.sha1("pexels|foto|maned wolf".encode()).hexdigest()[:16]
    (tmp_path / "midia" / "buscas" / f"{codigo}.json").write_text("", encoding="utf-8")
    assert b._buscar("pexels", "foto", "maned wolf") == [{"fonte": "pexels", "id": "9"}]
    assert b._buscar("pexels", "foto", "maned wolf") == [{"fonte": "pexels", "id": "9"}]  # agora vem do cache
    assert not list((tmp_path / "midia" / "buscas").glob("*.tmp"))


def test_queda_passageira_tenta_de_novo(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(midia.time, "sleep", lambda s: None)
    chamadas = []

    def pexels(tipo, busca):
        chamadas.append(busca)
        if len(chamadas) < 3:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        return [{"fonte": "pexels", "id": "1"}]

    b = _buscador(tmp_path, pexels)
    assert b._buscar("pexels", "foto", "black mamba") == [{"fonte": "pexels", "id": "1"}]
    assert len(chamadas) == 3


def test_banco_caido_seguido_fica_de_fora_um_tempo(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(midia.time, "sleep", lambda s: None)

    def pexels(tipo, busca):
        raise httpx.ConnectTimeout("timeout")

    b = _buscador(tmp_path, pexels)
    for i in range(midia.QUEDAS_PARA_PAUSAR):
        assert b._buscar("pexels", "foto", f"busca {i}") == []
    assert b.bloqueada_ate.get("pexels", 0) > midia.time.time() + 60


def test_figura_do_motion_caixa_e_parte():
    from fabrica import motion_figura
    assert motion_figura._caixa([10, 20, 90, 80]) == [0.1, 0.2, 0.9, 0.8]  # veio em porcentagem
    assert motion_figura._caixa([0.5, 0.5, 0.52, 0.9]) is None            # fina demais
    assert motion_figura._caixa(["x"]) is None
    assert motion_figura.parte_padrao("cauda achatada") == [0.0, 0.45, 0.26, 1.0]
    assert motion_figura.parte_padrao("mancha clara") is None


def test_recorte_com_fundo_grudado_e_medido(tmp_path):
    # o céu azul grudado no mico (11-animais-do-brasil): a visão gratuita aprovou; a conta separa
    import cv2
    import numpy as np
    from fabrica import recorte
    limpo = np.zeros((100, 100, 4), np.uint8)
    limpo[20:80, 20:80] = (40, 120, 200, 255)          # um bicho alaranjado (BGR)
    cv2.imwrite(str(tmp_path / "limpo.png"), limpo)
    sujo = limpo.copy()
    sujo[60:80, 20:45] = (200, 180, 20, 255)            # um pedaço azul-esverdeado grudado
    cv2.imwrite(str(tmp_path / "sujo.png"), sujo)
    assert recorte.fundo_grudado(tmp_path / "limpo.png") < 0.04 < recorte.fundo_grudado(tmp_path / "sujo.png")


def test_recorte_com_pontas_espetadas_e_barrado(tmp_path):
    # o pirarucu da cena 257 do 11-animais-do-brasil com folhas e gravetos espetados: "fica basicamente estranho"
    import cv2
    import numpy as np
    from fabrica import recorte
    liso = np.zeros((300, 600, 4), np.uint8)
    cv2.ellipse(liso, (300, 150), (250, 80), 0, 0, 360, (60, 90, 120, 255), -1)
    cv2.imwrite(str(tmp_path / "liso.png"), liso)
    espetado = liso.copy()
    for x in range(80, 520, 40):
        cv2.line(espetado, (x, 80), (x + 10, 15), (60, 90, 120, 255), 4)
    cv2.imwrite(str(tmp_path / "espetado.png"), espetado)
    assert recorte.pontas(tmp_path / "liso.png") < recorte.PONTAS_MAXIMO < recorte.pontas(tmp_path / "espetado.png")
    assert recorte.limpo(tmp_path / "liso.png") and not recorte.limpo(tmp_path / "espetado.png")
