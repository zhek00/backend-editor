"""Motion IA: cena abstrata reprovada vira clipe de motion; cena concreta continua indo para a imagem de IA.

Rode com: uv run --no-sync --with pytest python -m pytest tests
Sem rede e sem custo: os modelos e o HyperFrames são trocados por respostas prontas.
"""
from types import SimpleNamespace

from fabrica import imagens, motion_ia

BOM = {"css": ".m-txt { position: absolute; left: 120px; top: 300px; }",
       "html": '<div class="m-txt"><span>primeiro</span> <span>lugar</span></div>',
       "js": 'tl.fromTo(".m-txt span", {opacity: 0, y: 30}, {opacity: 1, y: 0, duration: 0.6, ease: "expo.out", stagger: 0.08}, 0.2);'}


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


def test_palavra_que_a_fala_nao_diz_volta():
    partes = {**BOM, "html": '<span>primeiro</span> <span>campeão</span>'}
    assert motion_ia._palavras_inventadas(partes, "e o primeiro lugar vai te surpreender") == ["campeao"]
    assert motion_ia._palavras_inventadas(BOM, "e o primeiro lugar vai te surpreender") == []


def test_cena_com_animal_ou_nome_e_concreta_sem_perguntar(monkeypatch):
    perguntas = []
    monkeypatch.setattr(motion_ia, "_perguntar", lambda *a, **k: perguntas.append(a) or {"cenas": []})
    projeto = SimpleNamespace(config={}, offline=False)
    cenas = [{"n": 1, "texto": "Em oitavo lugar está o rinoceronte-negro", "animal": "black rhinoceros"},
             {"n": 2, "texto": "no Instituto Butantan", "exato": "Instituto Butantan"}]
    assert motion_ia.classificar(projeto, cenas, log=lambda *a: None) == {1: False, 2: False}
    assert perguntas == []


def test_classificacao_guardada_vale_enquanto_a_fala_for_a_mesma(monkeypatch):
    monkeypatch.setattr(motion_ia, "_perguntar", lambda *a, **k: {"cenas": [{"n": 6, "abstrata": False}]})
    projeto = SimpleNamespace(config={}, offline=False)
    cena = {"n": 6, "texto": "e o primeiro lugar vai te surpreender"}
    cena.update(abstrata=True, abstrata_fala=motion_ia._assinatura_fala(cena))
    assert motion_ia.classificar(projeto, [cena], log=lambda *a: None) == {6: True}
    cena["texto"] = "o leão ruge na savana"
    assert motion_ia.classificar(projeto, [cena], log=lambda *a: None) == {6: False}


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
    monkeypatch.setattr(openrouter_local, "principais", lambda projeto=None: [
        "stealth/space-bunny-alpha", "qwen/qwen3.8-27b:free", "qwen/qwen3.8-flash"])
    assert motion_ia.modelos(SimpleNamespace(config={})) == ["stealth/space-bunny-alpha", "qwen/qwen3.8-27b:free"]


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
    assert 'data-duration="3.23"' in html and "scale: 1.05" in html  # micro-movimento contínuo
