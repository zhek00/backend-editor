"""Motion IA: cena abstrata reprovada vira clipe de motion; cena concreta continua indo para a imagem de IA.

Rode com: uv run --no-sync --with pytest python -m pytest tests
Sem rede e sem custo: os modelos e o HyperFrames são trocados por respostas prontas.
"""
from types import SimpleNamespace

from fabrica import imagens, motion_ia

BOM = {"css": ".m-txt { position: absolute; left: 140px; top: 300px; font-size: 96px; }",
       "html": '<div class="m-card m-txt"><span>primeiro</span> <span class="m-destaque">lugar</span></div>',
       "js": 'tl.fromTo(".m-txt span", {opacity: 0, y: 30}, {opacity: 1, y: 0, duration: 0.6, ease: "back.out(1.7)", stagger: 0.12}, 0.2);'}


def test_codigo_bom_passa():
    assert motion_ia.problemas_do_codigo(BOM) == []


def test_codigo_com_animacao_css_relogio_ou_emoji_volta():
    for trecho, motivo in [("@keyframes sobe { from {opacity: 0} }", "CSS"),
                           ("setTimeout(() => {}, 100);", "relógio"),
                           ("Math.random()", "sorteio"),
                           ('tl.to(".m-a", {x: 10, ease: "linear"}, 0);', "curva"),
                           ("🦏", "emoji"),
                           ("background: url(https://x.com/a.png);", "endereço")]:
        erros = motion_ia.problemas_do_codigo({**BOM, "css": BOM["css"] + trecho})
        assert erros, motivo


def test_entrada_sem_mola_volta():
    # PRD de 2026-10-05: cards, textos e barras entram com física de mola (back.out)
    partes = {**BOM, "js": BOM["js"].replace("back.out(1.7)", "expo.out")}
    assert any("mola" in e for e in motion_ia.problemas_do_codigo(partes))


def test_texto_pequeno_demais_volta():
    # no "135 pessoas" do virou-filme, o rótulo "número de vítimas" saiu com 18px e não se lia
    partes = {**BOM, "css": BOM["css"] + " .m-rot { font-size: 18px; }"}
    assert any("pequeno" in e and "18px" in e for e in motion_ia.problemas_do_codigo(partes))


def test_palavra_que_a_fala_nao_diz_volta():
    partes = {**BOM, "html": '<span>primeiro</span> <span>campeão</span>'}
    assert motion_ia._palavras_inventadas(partes, "e o primeiro lugar vai te surpreender") == ["campeao"]
    assert motion_ia._palavras_inventadas(BOM, "e o primeiro lugar vai te surpreender") == []


class _Projeto:
    """Um projeto de mentira numa pasta temporária, com o cenas.json."""
    def __init__(self, pasta, cenas, config=None):
        import json
        self.pasta, self.config, self.offline, self.dados = pasta, config or {}, False, {}
        (pasta / "cenas.json").write_text(json.dumps({"cenas": cenas}), encoding="utf-8")

    def ler_json(self, nome):
        import json
        return json.loads((self.pasta / nome).read_text(encoding="utf-8"))

    def salvar_json(self, nome, dados):
        import json
        (self.pasta / nome).write_text(json.dumps(dados), encoding="utf-8")

    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.png"


def _jev_responde(monkeypatch, notas, chamadas):
    from fabrica import corrigir, jev_local
    monkeypatch.setattr(corrigir, "_bloco_da_cena_no_mapa", lambda projeto, cena: "")

    def decidir(projeto, etapa, estado, perguntas, log=print):
        chamadas.append(estado)
        nota = notas[estado["narracao_desta_cena"]]
        return {"dado": {"type": "noul", "noul": nota}, "util": {"type": "noul", "noul": nota}}
    monkeypatch.setattr(jev_local, "decidir", decidir)


def test_o_jev_decide_pelo_roteiro_onde_o_motion_vale(monkeypatch, tmp_path):
    # pedido do usuário em 2026-10-05: o motion caiu em "e o primeiro lugar vai te surpreender", sem impacto
    chamadas = []
    _jev_responde(monkeypatch, {"e o primeiro lugar vai te surpreender.": 0.2,
                                "os dois teriam comido cerca de 35 pessoas.": 0.9}, chamadas)
    cenas = [{"n": 6, "texto": "e o primeiro lugar vai te surpreender."},
             {"n": 7, "texto": "os dois teriam comido cerca de 35 pessoas."}]
    projeto = _Projeto(tmp_path, cenas)
    assert motion_ia.classificar(projeto, cenas, log=lambda *a: None) == {6: False, 7: True}
    assert ">>> os dois teriam comido cerca de 35 pessoas. <<<" in chamadas[1]["trecho_do_roteiro"]
    # a nota fica guardada: a mesma fala não é julgada de novo
    guardadas = projeto.ler_json("cenas.json")["cenas"]
    assert [c["motion_util"] for c in guardadas] == [20, 90]
    assert motion_ia.classificar(projeto, guardadas, log=lambda *a: None) == {6: False, 7: True}
    assert len(chamadas) == 2


def test_cena_de_animal_pode_virar_motion_com_ou_sem_foto(monkeypatch, tmp_path):
    # pedido do usuário em 2026-10-05: a foto é opcional (o velocímetro explica os 50 km/h sem o rinoceronte); só a
    # foto com o sujeito certo vai para o card do modelo foto_dado
    chamadas = []
    fala = "Pode passar dos 50 quilômetros por hora"
    _jev_responde(monkeypatch, {fala: 0.95}, chamadas)
    (tmp_path / "midia").mkdir()
    (tmp_path / "midia" / "0011.jpg").write_bytes(b"x")
    com_foto = {"n": 11, "texto": fala, "animal": "black rhinoceros",
                "midia": {"arquivo": "midia/0011.jpg", "tipo": "foto"}, "conferencia": {"nota": 13, "sujeito": 90}}
    foto_errada = {**com_foto, "n": 12, "conferencia": {"nota": 13, "sujeito": 20}}
    projeto = _Projeto(tmp_path, [com_foto, foto_errada])
    assert motion_ia.foto_da_cena(projeto, com_foto) == tmp_path / "midia" / "0011.jpg"
    assert motion_ia.foto_da_cena(projeto, foto_errada) is None
    assert motion_ia.classificar(projeto, [com_foto, foto_errada], log=lambda *a: None) == {11: True, 12: True}
    assert chamadas[0]["o_clipe_tem_a_foto"].startswith("sim") and "o_clipe_tem_a_foto" not in chamadas[1]


def test_foto_guardada_para_a_ia_vale_para_o_card(tmp_path):
    # no Corrigir, a foto vai para antigas/ (ia_reserva) antes do motion rodar
    antiga = tmp_path / "antigas" / "0008-20261005.jpg"
    antiga.parent.mkdir()
    antiga.write_bytes(b"x")
    cena = {"n": 8, "texto": "pesa mais de uma tonelada", "animal": "black rhinoceros", "midia": None, "tipo": "ia",
            "ia_reserva": {"sujeito": 93, "movidos": [[str(antiga), str(tmp_path / "midia" / "0008.jpg")]]}}
    assert motion_ia.foto_da_cena(_Projeto(tmp_path, [cena]), cena) == antiga


def test_clipe_com_foto_exige_o_card_dela():
    html = motion_ia.montar_html(BOM, 3.0, foto="foto.jpg")
    assert 'url("assets/foto.jpg")' in html
    assert motion_ia.montar_html(BOM, 3.0).count("assets/foto") == 0


def test_cena_da_pessoa_nunca_vira_motion():
    cenas = [{"n": 1, "texto": "a", "prompt_manual": "da pessoa"}, {"n": 2, "texto": "b", "imagem_da_pessoa": True},
             {"n": 3, "texto": "c", "personagem": True}, {"n": 4, "texto": "d"}]
    assert [c["n"] for c in motion_ia.candidatas(None, cenas)] == [4]


def test_limiar_do_env_vai_de_0_a_10(monkeypatch):
    monkeypatch.setenv("JEV_MIN_SCORE_THRESHOLD", "6.0")
    monkeypatch.setenv("JEV_MOTION_FALLBACK_ENABLED", "false")
    cfg = motion_ia.config(SimpleNamespace(config={"motion_ia": {"ativo": True}}))
    assert cfg["nota_minima"] == 60 and cfg["ativo"] is False


def test_so_os_modelos_gratuitos(monkeypatch):
    from fabrica import openrouter_local
    monkeypatch.delenv("OPENROUTER_FREE_MODELS", raising=False)
    monkeypatch.setattr(openrouter_local, "principais", lambda projeto=None: [
        "stealth/space-bunny-alpha", "qwen/qwen3.8-27b:free", "qwen/qwen3.8-flash"])
    assert motion_ia.modelos(SimpleNamespace(config={})) == ["stealth/space-bunny-alpha", "qwen/qwen3.8-27b:free"]


def test_modelos_do_env_tambem_so_gratuitos(monkeypatch):
    monkeypatch.setenv("OPENROUTER_FREE_MODELS", "qwen/qwen-2.5-coder-32b:free, openai/gpt-5, deepseek/deepseek-r1:free")
    assert motion_ia.modelos(SimpleNamespace(config={})) == ["qwen/qwen-2.5-coder-32b:free", "deepseek/deepseek-r1:free"]


def test_fps_do_env(monkeypatch):
    monkeypatch.setenv("MOTION_RENDER_FPS", "24")
    assert motion_ia.fps(SimpleNamespace(config={})) == 24
    monkeypatch.delenv("MOTION_RENDER_FPS")
    assert motion_ia.fps(SimpleNamespace(config={"motion_ia": {"fps": 30}})) == 30


def test_cena_so_de_nota_baixa_volta_para_a_foto_se_o_motion_falhar(monkeypatch):
    # rollback do PRD: ela não estava errada, então não vale pagar imagem de IA por ela
    from fabrica import corrigir
    voltaram = []
    monkeypatch.setattr(motion_ia, "resolver", lambda p, pend, log: [])
    monkeypatch.setattr(corrigir, "_voltar_reserva", lambda p, n, log: voltaram.append(n))
    cenas = {"cenas": [{"n": 5, "tipo": "ia", "motion_so": True}, {"n": 7, "tipo": "ia"}]}
    projeto = SimpleNamespace(offline=False, ler_json=lambda nome: cenas, imagem=lambda n: SimpleNamespace(exists=lambda: False))
    imagens._motion_antes_da_ia(projeto, None, cenas["cenas"], log=lambda *a: None)
    assert voltaram == [5]


def test_esqueleto_expoe_a_gravacao_quadro_a_quadro():
    html = motion_ia.montar_html(BOM, 3.23)
    assert "window.seekToFrame" in html and 'window.__timelines["main"] = tl' in html
    assert 'data-duration="3.23"' in html
    # estilo editorial do PRD: fundo creme com grade de pontos, cards que flutuam, linhas que se desenham
    assert "#F7F6F2" in html and "radial-gradient(#d1d0c9 1px" in html and "background-size: 24px 24px" in html
    assert '"--m-fy": "5px"' in html and "strokeDashoffset = L" in html and "scale: 1.03" in html


def test_css_vazio_volta():
    # cena 6 do natureza-teste-1min: o css veio vazio e tudo caiu no canto esquerdo, com letra de 16px
    erros = motion_ia.problemas_do_codigo({**BOM, "css": ""})
    assert any("css está vazio" in e for e in erros)
    sem_tamanho = {**BOM, "css": ".m-txt { position: absolute; left: 140px; top: 300px; }"}
    assert any("tamanho" in e for e in motion_ia.problemas_do_codigo(sem_tamanho))


def test_camada_para_no_comeco_do_clipe_de_motion(monkeypatch):
    # a frase da cena 5 (15,1 a 20,4 s) passava por cima do clipe da cena 6 (18,3 a 21,6 s)
    from fabrica import animacoes
    monkeypatch.setattr(animacoes, "_cenas_motion_ia", lambda projeto: [(18.33, 21.56)])
    itens = [{"id": "a", "ini": 15.1, "fim": 20.43}, {"id": "b", "ini": 19.0, "fim": 22.0},
             {"id": "c", "ini": 21.56, "fim": 24.9}]
    saida = animacoes._fora_do_motion_ia(None, itens)
    assert [(i["id"], i["fim"]) for i in saida] == [("a", 18.33), ("c", 24.9)]


def test_o_codigo_acha_o_dado_na_fala():
    # o sinal que faltou ao Jev na primeira rodada: ele deu 51% para os 50 km/h e 74% para "a ironia é que..."
    assert motion_ia.dado_na_fala("Pode passar dos 50 quilômetros por hora e investe com") == "50 quilômetros por hora"
    assert motion_ia.dado_na_fala("mais de uma tonelada e enxerga muito mal.") == "mais de uma tonelada"
    assert motion_ia.dado_na_fala("os dois teriam comido cerca de 35 pessoas.") == "cerca de 35 pessoas"
    assert motion_ia.dado_na_fala("A ironia é que ele mesmo vive em perigo,") == ""
    assert motion_ia.dado_na_fala("e o primeiro lugar vai te surpreender.") == ""


def test_a_nota_e_a_media_do_dado_e_da_utilidade(monkeypatch, tmp_path):
    from fabrica import corrigir, jev_local
    monkeypatch.setattr(corrigir, "_bloco_da_cena_no_mapa", lambda projeto, cena: "")
    estados = []
    monkeypatch.setattr(jev_local, "decidir", lambda projeto, etapa, estado, perguntas, log=print: estados.append(
        (estado, set(perguntas))) or {"dado": {"noul": 0.9}, "util": {"noul": 0.6}})
    cena = {"n": 11, "texto": "Pode passar dos 50 quilômetros por hora"}
    projeto = _Projeto(tmp_path, [cena])
    assert motion_ia.classificar(projeto, [cena], log=lambda *a: None) == {11: True}
    assert projeto.ler_json("cenas.json")["cenas"][0]["motion_util"] == 75
    estado, perguntas = estados[0]
    assert perguntas == {"dado", "util"} and estado["dado_na_fala"] == "50 quilômetros por hora"
    # nota da versão antiga da pergunta não vale: é pedida de novo
    velha = {**cena, "motion_util": 20, "motion_util_fala": motion_ia._assinatura_fala(cena)}
    assert motion_ia.a_julgar([velha]) == [velha]


def test_texto_fora_da_tela_reprova_o_clipe(monkeypatch, tmp_path):
    # cena 8 do natureza-teste-1min: o HyperFrames marcou "canvas_overflow" só como informação e o card saiu vazio
    import json
    from fabrica import animacoes
    saida = {"ok": True, "layout": {"findings": [
        {"severity": "info", "code": "canvas_overflow", "selector": "#m-numero", "time": t,
         "message": "Text extends outside the composition canvas."} for t in (2.1, 2.5)]}}
    monkeypatch.setattr(animacoes, "_hyperframes", lambda *a, **k: SimpleNamespace(stdout=json.dumps(saida), stderr=""))
    assert animacoes._conferir(None, tmp_path) == []  # a camada transparente segue como antes
    erros = animacoes._conferir(None, tmp_path, clipe=True)
    assert len(erros) == 1 and erros[0].startswith("canvas_overflow")
