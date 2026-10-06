"""A chamada ao OpenRouter quando o modelo gasta o limite só pensando.

Rode com: uv run --no-sync --with pytest python -m pytest tests
Sem rede e sem custo: o OpenRouter é trocado por uma resposta pronta.
"""
from types import SimpleNamespace

import pytest

from fabrica import openrouter_local


def test_estourou_pensando_tenta_uma_vez_no_teto_e_desiste(monkeypatch):
    # nunca-deve-ter-dentro-de-casa-parte-2: o DeepSeek estourava em 10 mil, 20 mil e 24 mil tokens, cada volta levava
    # minutos e a criação ficou quase uma hora nos 15%. Agora: o pedido normal, uma volta já no teto, e passa adiante
    pedidos = []

    def post(url, json=None, headers=None, timeout=None):
        pedidos.append(json["max_tokens"])
        return SimpleNamespace(status_code=200, text="", json=lambda: {
            "choices": [{"finish_reason": "length", "message": {"content": ""}}], "usage": {}})

    monkeypatch.setattr(openrouter_local.httpx, "post", post)
    monkeypatch.setattr(openrouter_local, "_rota", lambda modelo: ("url", "chave", modelo, "openrouter"))
    monkeypatch.setattr(openrouter_local, "_registrar", lambda *a, **k: None)
    projeto = SimpleNamespace(config={"openrouter": {"max_tokens": 10000, "max_tokens_teto": 24000}})
    with pytest.raises(RuntimeError, match="raciocinando"):
        openrouter_local._perguntar_rota(projeto, "teste", "instruções", "pedido", {"type": "object"},
                                         lambda *a: None, "deepseek/deepseek-v4-flash", (), 0.2)
    assert pedidos == [10000, 24000]


def test_lote_pronto_vale_mesmo_com_outro_resumo(tmp_path):
    # nunca-deve-ter-dentro-de-casa-parte-2: depois de reiniciar, lotes prontos foram decididos de novo porque o
    # resumo das cenas anteriores (que entrava na marca do arquivo) tinha mudado
    from fabrica import roteirista
    projeto = SimpleNamespace(caminho=lambda *partes: tmp_path.joinpath(*partes))
    (tmp_path / "cenas_lotes").mkdir()
    pedido_1 = "MAPA...\nÚLTIMAS CENAS:\nCENA 9: um teiú\n\nTRECHOS: cenas 10 a 18"
    pedido_2 = "MAPA...\nÚLTIMAS CENAS:\nCENA 9: outro teiú\n\nTRECHOS: cenas 10 a 18"
    primeiro = roteirista.arquivo_do_lote(projeto, 9, pedido_1, "CENA 9: um teiú")
    primeiro.write_text("[]", encoding="utf-8")
    assert roteirista.arquivo_do_lote(projeto, 9, pedido_2, "CENA 9: outro teiú") == primeiro


def test_lote_com_a_marca_antiga_continua_valendo(tmp_path):
    from fabrica import roteirista
    projeto = SimpleNamespace(caminho=lambda *partes: tmp_path.joinpath(*partes))
    (tmp_path / "cenas_lotes").mkdir()
    pedido = "MAPA...\nÚLTIMAS CENAS:\nCENA 9: um teiú\n\nTRECHOS: cenas 10 a 18"
    antigo = tmp_path / "cenas_lotes" / f"roteirista_0009_{roteirista._marca(roteirista.PROMPT_CENAS + pedido)}.json"
    antigo.write_text('[{"cena": 10}]', encoding="utf-8")
    novo = roteirista.arquivo_do_lote(projeto, 9, pedido, "CENA 9: um teiú")
    assert novo.exists() and novo.read_text(encoding="utf-8") == '[{"cena": 10}]'


def test_imagens_vao_pela_cadeia_de_visao_com_o_pago_sem_raciocinio(monkeypatch):
    # nunca-deve-ter-dentro-de-casa-parte-2: a escolha das fotos caiu toda no Qwen pago (US$ 2,44, 2.500 tokens de
    # raciocínio por chamada). Agora vai pelos gratuitos que enxergam imagem, e o Qwen é só reserva, sem pensar
    chamadas = []
    monkeypatch.setattr(openrouter_local, "perguntar", lambda *a, **k: chamadas.append(k) or {"ok": True})
    projeto = SimpleNamespace(config={
        "openrouter": {"principais": ["google/gemma-4-31b-it:free", "qwen/qwen3.8-flash"],
                       "raciocinio_por_modelo": {"qwen/": "low", "deepseek/": "low"}},
        "midia": {"modelos_visao": ["dots-studio/dots-3-note-preview:free", "qwen/qwen3.8-flash"],
                  "raciocinio_visao": {"dots-studio/": "nenhum", "qwen/": "nenhum"}}})
    openrouter_local.VISAO.perguntar(projeto, "escolha", "i", "p", {}, imagens=["folha.jpg"])
    k = chamadas[0]
    assert k["cadeia_de"] == ["dots-studio/dots-3-note-preview:free", "qwen/qwen3.8-flash"]
    assert k["modelo"] == "dots-studio/dots-3-note-preview:free" and k["imagens"] == ["folha.jpg"]
    assert k["raciocinio"]["qwen/"] == "nenhum" and k["raciocinio"]["deepseek/"] == "low"


def _projeto_da_cadeia():
    return SimpleNamespace(config={"openrouter": {
        "principais": ["groq:qwen/qwen3.8-27b", "groq:openai/gpt-oss-120b", "dots-studio/dots-3-note-preview:free",
                       "qwen/qwen3.8-flash"],
        "so_texto": ["groq:openai/gpt-oss", "nvidia/nemotron-3-super"]}})


def test_groq_no_limite_passa_a_vez_para_o_seguinte(monkeypatch):
    # pedido do usuário em 2026-10-05: o máximo de API gratuita, com as chaves do Groq na frente da cadeia
    from fabrica import groq_local
    openrouter_local._FORA_DO_AR.clear()
    rotas = []

    def groq(projeto, etapa, instrucoes, pedido, esquema, log=print, modelo=None, imagens=(), temperatura=None,
             na_cadeia=False, raciocinio=None):
        rotas.append("groq:" + modelo)
        raise openrouter_local.RotaIndisponivel("Groq: o Groq pediu para esperar em todas as chaves")

    def openrouter(projeto, etapa, instrucoes, pedido, esquema, log, modelo, imagens, temperatura, cadeia=False,
                   traduzir=True, raciocinio=None):
        rotas.append(modelo)
        return {"cenas": []}

    monkeypatch.setattr(groq_local, "perguntar", groq)
    monkeypatch.setattr(openrouter_local, "_perguntar_rota", openrouter)
    projeto = _projeto_da_cadeia()
    assert openrouter_local.perguntar(projeto, "teste", "i", "p", {"required": ["cenas"]}, log=lambda *a: None,
                                      modelo="groq:qwen/qwen3.8-27b") == {"cenas": []}
    assert rotas == ["groq:qwen/qwen3.8-27b", "groq:openai/gpt-oss-120b", "dots-studio/dots-3-note-preview:free"]
    openrouter_local._FORA_DO_AR.clear()


def test_pedido_com_imagem_pula_quem_so_le_texto(monkeypatch):
    rotas = []
    monkeypatch.setattr(openrouter_local, "uma_rota",
                        lambda projeto, etapa, i, p, e, log, rota, imagens, t, cadeia=False, raciocinio=None:
                        rotas.append(rota) or (_ for _ in ()).throw(openrouter_local.RotaIndisponivel("fora")))
    openrouter_local._FORA_DO_AR.clear()
    with pytest.raises(Exception):
        openrouter_local.perguntar(_projeto_da_cadeia(), "teste", "i", "p", {}, log=lambda *a: None,
                                   modelo="groq:qwen/qwen3.8-27b", imagens=["folha.jpg"])
    assert "groq:openai/gpt-oss-120b" not in rotas and rotas[0] == "groq:qwen/qwen3.8-27b"
    openrouter_local._FORA_DO_AR.clear()


def test_raciocinio_do_groq_pela_mesma_tabela():
    from fabrica import groq_local
    assert groq_local._esforco("qwen/qwen3.8-27b", {"qwen/": "nenhum"}) == "none"
    assert groq_local._esforco("qwen/qwen3.8-27b", {"qwen/": "low"}) == "none"
    assert groq_local._esforco("openai/gpt-oss-120b", {"groq:openai/": "nenhum"}) == "low"


def test_agente_comeca_pelo_gratuito_e_tem_o_deepseek_de_reserva(monkeypatch):
    from fabrica import roteirista
    chamadas = []
    monkeypatch.setattr(openrouter_local, "perguntar", lambda *a, **k: chamadas.append(k) or {"cenas": []})
    projeto = SimpleNamespace(config={
        "roteirista": {"provedor": "openrouter", "modelos": ["nvidia/nemotron-3-ultra-550b-a55b:free",
                                                            "deepseek/deepseek-v4-flash"]},
        "openrouter": {"principais": ["groq:qwen/qwen3.8-27b", "qwen/qwen3.8-flash"]}})
    roteirista._modelo_agente(projeto).perguntar(projeto, "roteirista: cenas", "i", "p", {})
    assert chamadas[0]["cadeia_de"] == ["nvidia/nemotron-3-ultra-550b-a55b:free", "deepseek/deepseek-v4-flash",
                                        "groq:qwen/qwen3.8-27b", "qwen/qwen3.8-flash"]
    assert chamadas[0]["modelo"] == "nvidia/nemotron-3-ultra-550b-a55b:free"


def test_antes_de_pagar_espera_uns_segundos_pelo_gratis(monkeypatch):
    # pico da conferência no nunca-deve-ter-dentro-de-casa-parte-2: Groq e gratuitos no limite do minuto ao mesmo
    # tempo mandaram 27 descrições para o Qwen pago. Fora só por segundos, o gratuito vale a espera
    import time as _time
    openrouter_local._FORA_DO_AR.clear()
    rotas, esperas = [], []
    monkeypatch.setattr(openrouter_local.time, "sleep", lambda s: esperas.append(s) or openrouter_local._FORA_DO_AR.clear())

    def rota(projeto, etapa, i, p, e, log, r, imagens, t, cadeia=False, raciocinio=None):
        rotas.append(r)
        if r.startswith("groq:") and not esperas:
            openrouter_local._FORA_DO_AR[r] = _time.time() + 20  # o limite do minuto: volta em 20 s
            raise openrouter_local.RotaIndisponivel("todas as chaves no limite do minuto")
        return {"ok": True}

    monkeypatch.setattr(openrouter_local, "uma_rota", rota)
    projeto = SimpleNamespace(config={"openrouter": {"principais": ["groq:qwen/qwen3.8-27b", "qwen/qwen3.8-flash"]}})
    assert openrouter_local.perguntar(projeto, "teste", "i", "p", {}, log=lambda *a: None,
                                      modelo="groq:qwen/qwen3.8-27b") == {"ok": True}
    assert rotas == ["groq:qwen/qwen3.8-27b", "groq:qwen/qwen3.8-27b"] and 0 < esperas[0] <= 21
    openrouter_local._FORA_DO_AR.clear()


def test_gratis_fora_por_muito_tempo_vai_para_o_pago(monkeypatch):
    import time as _time
    openrouter_local._FORA_DO_AR.clear()
    rotas = []
    monkeypatch.setattr(openrouter_local.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("não espera")))

    def rota(projeto, etapa, i, p, e, log, r, imagens, t, cadeia=False, raciocinio=None):
        rotas.append(r)
        if r.startswith("groq:"):
            openrouter_local._FORA_DO_AR[r] = _time.time() + 3600  # a cota do dia
            raise openrouter_local.RotaIndisponivel("cota do dia")
        return {"ok": True}

    monkeypatch.setattr(openrouter_local, "uma_rota", rota)
    projeto = SimpleNamespace(config={"openrouter": {"principais": ["groq:qwen/qwen3.8-27b", "qwen/qwen3.8-flash"]}})
    openrouter_local.perguntar(projeto, "teste", "i", "p", {}, log=lambda *a: None, modelo="groq:qwen/qwen3.8-27b")
    assert rotas == ["groq:qwen/qwen3.8-27b", "qwen/qwen3.8-flash"]
    openrouter_local._FORA_DO_AR.clear()


def test_descricao_de_uma_cena_so_vale_mesmo_com_outro_numero(monkeypatch):
    # o Qwen do Groq respondeu "cena 1" para a cena 79, e a descrição era jogada fora
    from fabrica import corrigir
    monkeypatch.setattr(corrigir, "_com_reserva", lambda *a, **k: {"cenas": [{
        "n": 1, "o_que_e": "petauro-do-açúcar", "certeza": "alta", "detalhes": "olhos grandes", "cenario": "galho",
        "acao": "parado", "tipo_imagem": "ilustração", "texto_visivel": "nenhum", "epoca_aparente": "atual"}]})
    r = corrigir._descrever_lote(SimpleNamespace(config={}), [({"n": 79}, ["a.png"])], lambda *a: None)
    assert list(r) == [79] and "petauro" in r[79]


def test_qualidade_conta_a_nota_da_captura_e_a_ia_de_cena_de_foto(tmp_path):
    # nunca-deve-ter-dentro-de-casa-parte-2: 464 "sem conferência" (as aprovadas antes de baixar) e 63 "sem imagem"
    # (cenas que perderam a foto e ganharam imagem de IA, com o tipo de foto)
    import json
    from fabrica import qualidade
    (tmp_path / "imagens").mkdir()
    (tmp_path / "imagens" / "0002.png").write_bytes(b"x")
    cenas = [{"n": 1, "tipo": "foto_real", "midia": {"fonte": "pexels", "id": "1"}, "captura": {"conferida": True, "nota": 85}},
             {"n": 2, "tipo": "foto_real", "midia": None}]
    (tmp_path / "cenas.json").write_text(json.dumps({"cenas": cenas}), encoding="utf-8")
    projeto = SimpleNamespace(pasta=tmp_path, existe=lambda nome: (tmp_path / nome).exists(),
                              ler_json=lambda nome: json.loads((tmp_path / nome).read_text(encoding="utf-8")),
                              imagem=lambda n: tmp_path / "imagens" / f"{n:04d}.png")
    r = qualidade.calcular(projeto)
    assert r["boas"] == 1 and r["sem_conferencia"] == [2] and r["origem"] == {"escolhida": 1, "IA": 1}
