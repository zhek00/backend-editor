"""O cache do corte de cenas não guarda falha, não deixa meio arquivo e a renumeração de imagens se recupera.

Antes: uma falha de cota do modelo era gravada como resposta vazia e nunca mais refeita; uma queda no meio da gravação
deixava um JSON truncado que parava o corte; e uma queda no meio da renumeração deixava as imagens em
imagens/_renumerando para sempre, com as cenas pagando a imagem de IA de novo."""
import json

from fabrica import cenas


class _Projeto:
    def __init__(self, pasta):
        self.pasta = pasta

    def caminho(self, *partes):
        destino = self.pasta.joinpath(*partes)
        destino.parent.mkdir(parents=True, exist_ok=True)
        return destino


class _ModeloQueFalha:
    def perguntar(self, *args, **kwargs):
        raise RuntimeError("cota esgotada")


class _ModeloQueResponde:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = 0

    def perguntar(self, *args, **kwargs):
        self.chamadas += 1
        return self.resposta


def test_falha_do_modelo_na_traducao_do_topico_nao_vai_para_o_cache(tmp_path, monkeypatch):
    projeto = _Projeto(tmp_path)
    monkeypatch.setattr(cenas, "_modelo", lambda p: _ModeloQueFalha())
    assert cenas._termo_ingles_do_topico(projeto, "petauro-do-açúcar", log=lambda m: None) == ""
    assert not list((tmp_path / "cenas_lotes").glob("topico_ingles_*.json"))
    # na rodada seguinte o modelo responde, e o termo vale e fica guardado
    modelo = _ModeloQueResponde({"termo": "sugar glider"})
    monkeypatch.setattr(cenas, "_modelo", lambda p: modelo)
    assert cenas._termo_ingles_do_topico(projeto, "petauro-do-açúcar", log=lambda m: None) == "sugar glider"
    assert cenas._termo_ingles_do_topico(projeto, "petauro-do-açúcar", log=lambda m: None) == "sugar glider"
    assert modelo.chamadas == 1


def test_cache_vazio_de_uma_falha_antiga_e_refeito(tmp_path, monkeypatch):
    projeto = _Projeto(tmp_path)
    assinatura = __import__("hashlib").sha1("lince".encode("utf-8")).hexdigest()[:10]
    projeto.caminho("cenas_lotes", f"topico_ingles_{assinatura}.json").write_text('{"termo": ""}', encoding="utf-8")
    modelo = _ModeloQueResponde({"termo": "lynx"})
    monkeypatch.setattr(cenas, "_modelo", lambda p: modelo)
    assert cenas._termo_ingles_do_topico(projeto, "lince", log=lambda m: None) == "lynx"


def test_falha_do_modelo_no_destaque_do_titulo_nao_vai_para_o_cache(tmp_path, monkeypatch):
    projeto = _Projeto(tmp_path)
    lista = [{"titulos": [{"texto": "O Lince Que Ninguém Viu"}]}]
    monkeypatch.setattr(cenas, "_modelo", lambda p: _ModeloQueFalha())
    cenas._destacar_titulos_groq(projeto, lista, lambda m: None)
    assert lista[0]["titulos"][0]["destaque"] == ""
    assert not list((tmp_path / "cenas_lotes").glob("titulo_destaque_*.json"))
    modelo = _ModeloQueResponde({"destaque": "Ninguém Viu"})
    monkeypatch.setattr(cenas, "_modelo", lambda p: modelo)
    lista[0]["titulos"][0].pop("destaque")
    cenas._destacar_titulos_groq(projeto, lista, lambda m: None)
    assert lista[0]["titulos"][0]["destaque"] == "Ninguém Viu"


def test_cache_corrompido_e_ignorado_e_nao_para_o_corte(tmp_path):
    quebrado = tmp_path / "groq_000_abc.json"
    quebrado.write_text('[{"tipo": "foto_re', encoding="utf-8")  # gravação interrompida
    assert cenas._ler_cache(quebrado) is None
    assert cenas._ler_cache(tmp_path / "nao-existe.json") is None


def test_gravar_cache_troca_o_arquivo_inteiro_e_nao_deixa_temporario(tmp_path):
    arquivo = tmp_path / "groq_000_abc.json"
    cenas._gravar_cache(arquivo, [{"n": 1, "prompt": "ação"}])
    assert json.loads(arquivo.read_text(encoding="utf-8")) == [{"n": 1, "prompt": "ação"}]
    cenas._gravar_cache(arquivo, [{"n": 2}])
    assert cenas._ler_cache(arquivo) == [{"n": 2}]
    assert [p.name for p in tmp_path.iterdir()] == ["groq_000_abc.json"]


def test_renumeracao_interrompida_devolve_as_imagens(tmp_path):
    pasta = tmp_path / "imagens"
    passagem = pasta / "_renumerando"
    passagem.mkdir(parents=True)
    (passagem / "0007.png").write_bytes(b"a")
    (passagem / "0008.png").write_bytes(b"b")
    assert cenas._restaurar_renumeracao(pasta) == 2
    assert (pasta / "0007.png").read_bytes() == b"a"
    assert (pasta / "0008.png").read_bytes() == b"b"
    assert not passagem.exists()


def test_renumeracao_interrompida_nunca_sobrescreve_imagem_nova(tmp_path):
    pasta = tmp_path / "imagens"
    passagem = pasta / "_renumerando"
    passagem.mkdir(parents=True)
    (passagem / "0007.png").write_bytes(b"velha")
    (pasta / "0007.png").write_bytes(b"nova")  # a segunda fase já tinha posto uma imagem nesse número
    assert cenas._restaurar_renumeracao(pasta) == 1
    assert (pasta / "0007.png").read_bytes() == b"nova"
    guardadas = list((pasta / "_sem_cena").glob("0007_*.png"))
    assert len(guardadas) == 1 and guardadas[0].read_bytes() == b"velha"


def test_sem_pasta_de_passagem_nao_ha_o_que_restaurar(tmp_path):
    (tmp_path / "imagens").mkdir()
    assert cenas._restaurar_renumeracao(tmp_path / "imagens") == 0


def test_lote_do_claude_com_cache_truncado_e_refeito_em_vez_de_parar(tmp_path, monkeypatch):
    """O ramo padrão (provedor claude) lia o lote guardado sem proteção: meio arquivo derrubava o corte."""
    import hashlib

    projeto = _Projeto(tmp_path)
    sistema = "sistema do perfil"
    assinatura = hashlib.sha1(sistema.encode("utf-8")).hexdigest()[:10]
    guardado = projeto.caminho("cenas_lotes", f"lote_000_{assinatura}.json")
    guardado.write_text('[{"primeira_frase": 0, "ultima_fr', encoding="utf-8")
    nova = [{"primeira_frase": 0, "ultima_frase": 0, "tipo": "ia", "busca": "", "personagem": False, "prompt": "x"}]
    monkeypatch.setattr(cenas, "_planejar_lote_local", lambda *a, **k: nova)
    lote = [{"id": 0, "ini": 0.0, "fim": 4.0, "texto": "Olá."}]
    assert len(cenas._planejar_lote(projeto, sistema, lote, 0, {}, lambda m: None)) == 1
    assert cenas._ler_cache(guardado) == nova  # e o cache voltou a ser um arquivo inteiro


# --- correções menores do corte de cenas ---------------------------------------------------------------------------

def test_cenas_e_midia_usam_a_mesma_regra_de_epoca():
    """Uma regra só: cenas.py não tem mais a sua. Antes a de cenas (qualquer 1xxx) e a de midia podiam divergir."""
    from fabrica import midia

    for epoca in ("1898", "1949", "1950", "1990", "2009", "", None):
        cena = {"epoca": epoca}
        assert cenas._e_de_epoca(cena) == midia.e_de_epoca(cena)
    assert cenas._e_de_epoca({"epoca": "1898"})
    assert not cenas._e_de_epoca({"epoca": "2009"})
    assert not cenas._e_de_epoca({})


def test_cena_de_epoca_antiga_nunca_vira_video():
    lista = [{"n": i, "ini": float(i * 4), "fim": float(i * 4 + 4), "tipo": "video_real", "epoca": "1898"}
             for i in range(12)]
    cenas._balancear_foto_e_video(lista, log=lambda m: None)
    assert all(c["tipo"] == "foto_real" for c in lista)


def test_mapa_de_tempo_sem_palavra_com_tempo_nem_duracao_nao_quebra():
    sem_tempo = {"palavras": [{"texto": "oi", "ini": None}], "duracao": 0}
    assert cenas._mapa_de_tempo(sem_tempo, sem_tempo) is None
    com_duracao = {"palavras": [{"texto": "oi", "ini": None}], "duracao": 10.0}
    mapear = cenas._mapa_de_tempo(com_duracao, {"palavras": [{"texto": "oi", "ini": None}], "duracao": 12.0})
    assert mapear(5.0) == 6.0  # a duração sozinha ainda interpola


def test_busca_do_texto_em_portugues_mantem_as_palavras_acentuadas_e_tira_as_de_ligacao():
    busca = cenas._extrair_busca_do_prompt("", "A ação dos lobos que caçam com precisão")
    assert busca == "ação lobos caçam"
    # prompt em inglês continua como antes
    assert cenas._extrair_busca_do_prompt("wolf pack hunting elk in snow", "") == "wolf pack hunting"
    assert cenas._extrair_busca_do_prompt("", "") == "documentary cinematic"


def test_cena_sem_resposta_do_modelo_ganha_busca_de_reserva_e_prompt_explicado(tmp_path, monkeypatch):
    class _Modelo:
        def perguntar(self, *a, **k):
            return {"cenas": []}  # o modelo não devolveu nenhuma cena

    monkeypatch.setattr(cenas, "_modelo", lambda p: _Modelo())
    unidades = [{"id": 0, "ini": 0.0, "fim": 4.0, "texto": "A ação dos lobos que caçam"}]
    cortes = [{"primeira_frase": 0, "ultima_frase": 0}]
    obtidas = cenas._decidir_cenas_groq(_Projeto(tmp_path), "sistema", unidades, cortes, [0], [], [], {},
                                        lambda m: None, tentativa=1)
    assert obtidas[0]["tipo"] == "ia"
    assert obtidas[0]["busca"] == "ação lobos caçam"
    assert obtidas[0]["prompt"].endswith("A ação dos lobos que caçam")
    assert obtidas[0]["prompt"].startswith("Documentary photograph")


def test_enumeracao_com_palavras_no_mesmo_instante_e_item_repetido_corta_item_a_item():
    """O cursor da busca agora anda pelo índice da palavra achada. Na saída a diferença não aparece (o espaçamento mínimo
    entre cortes já compensava a posição errada), então este teste só protege o resultado correto."""
    palavras = [{"texto": "gatos", "ini": 1.0}, {"texto": "cães", "ini": 1.0}, {"texto": "cães", "ini": 2.0},
                {"texto": "aves", "ini": 3.5}]
    cena = {"ini": 0.0, "fim": 5.0, "texto": "gatos, cães, cães e aves", "tipo": "foto_real", "busca": "pets",
            "citacoes": [{"palavra": p, "busca": p + str(i), "prompt": p}
                         for i, p in enumerate(("gatos", "cães", "cães", "aves"))]}
    saida = cenas._dividir_enumeracoes([cena], {"palavras": palavras}, minimo=1.0, log=lambda m: None)
    assert [(c["busca"], c["ini"], c["fim"]) for c in saida] == [
        ("gatos0", 0.0, 1.0), ("cães1", 1.0, 2.0), ("cães2", 2.0, 3.5), ("aves3", 3.5, 5.0)]


def test_cena_curta_que_nao_da_para_fundir_e_avisada_no_log():
    avisos = []
    # uma cena de enumeração de 4 s e, depois dela, uma comum de 1 s: a comum não funde com fatia de item citado
    lista = [
        {"n": 1, "ini": 0.0, "fim": 4.0, "texto": "a", "tipo": "foto_real", "busca": "x", "enumeracao": True},
        {"n": 2, "ini": 4.0, "fim": 5.0, "texto": "b", "tipo": "foto_real", "busca": "y"},
    ]
    saida = cenas._garantir_limites_estritos(lista, 5.0, log=avisos.append)
    assert all(c["fim"] - c["ini"] <= 5.001 for c in saida)
    assert any("abaixo do mínimo" in a for a in avisos)
