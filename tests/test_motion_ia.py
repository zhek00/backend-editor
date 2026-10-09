"""Motion IA: cena abstrata reprovada vira clipe de motion; cena concreta continua indo para a imagem de IA.

Rode com: uv run --no-sync --with pytest python -m pytest tests
Sem rede e sem custo: os modelos e o HyperFrames são trocados por respostas prontas.
"""
import importlib.util
from types import SimpleNamespace

import pytest

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


# ------------------------------------------------- revisão visual antes de gravar (vídeo estudado em 2026-10-06)

def _critica(menor, problema="o número ficou espremido no canto"):
    notas = {k: 9 for k in motion_ia.CRITERIOS}
    notas["composicao"] = menor
    return motion_ia._ler_critica({"notas": notas, "problemas": [
        {"criterio": "composicao", "problema": problema, "correcao": "centralize o card"}]})


def _revisar(monkeypatch, criticas, cfg=None):
    """Roda _revisado com o clipe e a crítica trocados por respostas prontas. Devolve (resultado, pedidos de clipe)."""
    pedidos, fila = [], list(criticas)

    def um_clipe(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, erros_visuais=(), direcao=None):
        pedidos.append(list(erros_visuais))
        return {"css": "", "html": "", "js": "", "modelo": "contador", "versao": len(pedidos),
                "dados": {"rodada": len(pedidos)}}
    monkeypatch.setattr(motion_ia, "_um_clipe", um_clipe)
    monkeypatch.setattr(motion_ia, "criticar", lambda *a, **k: fila.pop(0))
    projeto = SimpleNamespace(config={"motion_ia": {"critica": cfg or {}}})
    resultado = motion_ia._revisado(projeto, {"n": 7}, 4.0, ("", ""), None, None, (), lambda *a: None)
    return resultado, pedidos


def test_clipe_com_nota_baixa_volta_com_o_problema_ate_passar(monkeypatch):
    resultado, pedidos = _revisar(monkeypatch, [_critica(5), _critica(9)])
    assert resultado["versao"] == 2 and resultado["critica"]["menor"] == 9
    assert pedidos[0] == [] and "espremido no canto" in pedidos[1][0] and "composicao 5/10" in pedidos[1][0]
    assert [c["menor"] for c in resultado["criticas"]] == [5, 9]


def test_sem_passar_fica_o_de_melhor_nota_se_for_aceitavel(monkeypatch):
    resultado, pedidos = _revisar(monkeypatch, [_critica(6), _critica(5), _critica(4)])
    assert resultado["versao"] == 1 and len(pedidos) == 3


def test_reprovado_na_revisao_visual_segue_o_caminho_de_antes(monkeypatch):
    import pytest
    with pytest.raises(RuntimeError, match="revisão visual"):
        _revisar(monkeypatch, [_critica(2), _critica(3), _critica(2)])


def test_sem_quem_olhe_o_clipe_segue_sem_a_revisao(monkeypatch):
    # nunca para o vídeo: snapshot falhou ou nenhum modelo de visão gratuito atendeu
    resultado, pedidos = _revisar(monkeypatch, [None])
    assert resultado["versao"] == 1 and "critica" not in resultado


def test_revisao_desligada_nao_olha(monkeypatch):
    resultado, pedidos = _revisar(monkeypatch, [], cfg={"ativa": False})
    assert resultado["versao"] == 1 and len(pedidos) == 1


def test_notas_da_revisao_ficam_de_1_a_10_e_o_pior_problema_primeiro():
    critica = motion_ia._ler_critica({"notas": {"legibilidade": 14, "composicao": 3, "clareza": "7"},
                                      "problemas": [{"criterio": "clareza", "problema": "a", "correcao": ""},
                                                    {"criterio": "composicao", "problema": "b", "correcao": ""}]})
    assert critica["notas"] == {"legibilidade": 10, "composicao": 3, "clareza": 7} and critica["menor"] == 3
    assert [p["problema"] for p in critica["problemas"]] == ["b", "a"]
    assert motion_ia._ler_critica({"notas": {}}) is None


def test_revisao_visual_so_pelos_gratuitos(monkeypatch):
    from fabrica import openrouter_local
    usadas = []
    monkeypatch.setattr(openrouter_local, "perguntar", lambda *a, **k: usadas.append(k["cadeia_de"]) or {})
    projeto = SimpleNamespace(config={"midia": {"modelos_visao": ["groq:qwen/qwen3.8-27b", "dots/x:free", "qwen/qwen3.8-flash"]},
                                      "openrouter": {"so_texto": ["groq:openai/gpt-oss"]}})
    openrouter_local.VISAO.perguntar(projeto, "e", "i", "p", {}, imagens=["a.jpg"], so_gratuitos=True)
    assert usadas == [["groq:qwen/qwen3.8-27b", "dots/x:free"]]


# --------------------------------------------------------- o som do clipe, no tempo do movimento

def test_som_no_tempo_de_cada_movimento_do_clipe():
    from fabrica import motion_modelos
    balanca = motion_modelos.partes("balanca", {"valor": 1, "unidade": "tonelada", "abreviacao": "1 t"}, 4.0)
    assert "baque" in [s for _, s in motion_ia.eventos_de_som(balanca["js"], 4.0)]
    velocimetro = motion_modelos.partes("velocimetro", {"valor": 50, "unidade": "km/h"}, 4.0)
    sons = motion_ia.eventos_de_som(velocimetro["js"], 4.0)
    assert sons[0][1] == "pop" and "contagem" in [s for _, s in sons]
    # nunca dois sons a menos de 0,3 s, nem som perto do corte
    assert all(b[0] - a[0] >= 0.3 for a, b in zip(sons, sons[1:])) and all(t <= 3.75 for t, _ in sons)


def test_movimento_continuo_e_saida_nao_tem_som():
    js = ('tl.to("#m-b1", { x: 40, duration: 4, ease: "sine.inOut" }, 0);'
          'tl.fromTo(".m-x", {opacity: 1}, {opacity: 0, duration: 0.3}, 1.0);'
          'tl.fromTo("#m-pulso", {scale: 1}, {scale: 1.2, duration: 0.4, yoyo: true, repeat: 3}, 2.0);')
    assert motion_ia.eventos_de_som(js, 4.0) == []


def test_contagem_com_parenteses_dentro_da_chamada():
    js = ('(function () { const el = document.querySelector("#v"); const o = { v: 0 }; tl.to(o, { v: 35, duration: 0.9,'
          ' ease: "power3.out", onUpdate: function () { el.textContent = (Math.round(o.v * 1) / 1).toLocaleString("pt-BR"); } }, 1.2); })();'
          'tl.fromTo("#c", {opacity: 0, y: 40}, {opacity: 1, y: 0, duration: 0.6, ease: "back.out(1.7)"}, 0.1);')
    assert motion_ia.eventos_de_som(js, 4.0) == [(0.1, "pop"), (1.2, "contagem")]


def test_som_so_nos_clipes_de_motion(monkeypatch):
    monkeypatch.setattr(motion_ia, "sons_do_clipe", lambda projeto, c: f"sons-{c['n']}.wav")
    projeto = SimpleNamespace(config={"motion_ia": {"volume_sons_db": -18}})
    cenas = [{"n": 3, "ini": 9.5, "midia": {"fonte": "motion_ia"}}, {"n": 4, "ini": 12.0, "midia": {"fonte": "pexels"}}]
    assert motion_ia.sons_na_linha(projeto, cenas, log=lambda *a: None) == [(9.5, "sons-3.wav", -18.0)]
    projeto.config["motion_ia"]["sons"] = False
    assert motion_ia.sons_na_linha(projeto, cenas, log=lambda *a: None) == []


# ------------------------------------- direção de arte antes do desenho (PRD Motion AI 2.0, 2026-10-07)

MICO = "O mico-leão-dourado pesa pouco mais de meio quilo."


def test_diretor_que_escolhe_a_balanca_para_o_mico_e_corrigido(monkeypatch, tmp_path):
    # a regra do código vale por cima do diretor: coisa leve nunca vai para a balança
    from fabrica import corrigir
    monkeypatch.setattr(corrigir, "_bloco_da_cena_no_mapa", lambda projeto, cena: "o mico-leão-dourado")
    pedidos = []
    monkeypatch.setattr(motion_ia, "_perguntar", lambda projeto, etapa, instr, pedido, esquema, log, temperatura=0.4:
                        pedidos.append(pedido) or {"leitura": "é pesado", "tom": "pesado", "desenho": "balanca",
                                                   "nao_mostrar": ["haltere"]})
    projeto = _Projeto(tmp_path, [])
    cena = {"n": 3, "texto": MICO, "animal": "golden lion tamarin"}
    direcao = motion_ia.dirigir(projeto, cena, ("", ""), log=lambda *a: None)
    assert direcao["desenho"] == "tipografia" and "balanca" in direcao["desenhos_proibidos"]
    assert "meio quilo" in pedidos[0] and "o mico-leão-dourado" in pedidos[0]
    # guardada na pasta da cena: não pergunta de novo
    assert motion_ia.dirigir(projeto, cena, ("", ""), log=lambda *a: None) == direcao and len(pedidos) == 1
    # a fala mudou: pergunta de novo
    motion_ia.dirigir(projeto, {**cena, "texto": "Pesa uma tonelada."}, ("", ""), log=lambda *a: None)
    assert len(pedidos) == 2


def test_sem_diretor_vale_a_direcao_do_codigo(monkeypatch, tmp_path):
    from fabrica import corrigir
    monkeypatch.setattr(corrigir, "_bloco_da_cena_no_mapa", lambda projeto, cena: "")

    def fora(*a, **k):
        raise RuntimeError("nenhum modelo gratuito atendeu")
    monkeypatch.setattr(motion_ia, "_perguntar", fora)
    direcao = motion_ia.dirigir(_Projeto(tmp_path, []), {"n": 3, "texto": MICO}, ("", ""), log=lambda *a: None)
    assert direcao["desenho"] == "tipografia" and direcao["tom"] == "leve"
    assert direcao["desenhos_proibidos"] == ["balanca"]


def test_foto_dado_sem_foto_nao_vale_como_direcao():
    direcao = motion_ia._limpar_direcao({"desenho": "foto_dado", "tom": "neutro", "leitura": "x"},
                                        {"texto": "Pode passar dos 50 quilômetros por hora"}, foto=False)
    assert direcao["desenho"] == "velocimetro"


def test_a_direcao_vai_no_pedido_do_desenho_e_da_revisao():
    direcao = motion_ia.direcao_pelo_codigo({"texto": MICO})
    cena = {"n": 3, "texto": MICO}
    pedido = motion_ia._pedido_modelo(cena, 3.0, ("", ""), [], False, [], direcao)
    assert "desenhos proibidos: balanca" in pedido and "tom do movimento: leve" in pedido
    revisao = motion_ia._pedido_critica(cena, 3.0, {"modelo": "tipografia", "dados": {}}, ("", ""), direcao)
    assert "nunca mostrar: peso de ferro" in revisao


def test_com_a_foto_o_peso_do_bicho_vai_para_a_balanca_e_o_tom_segue_o_peso():
    mico = motion_ia.direcao_pelo_codigo({"texto": MICO}, foto=True)
    assert mico["desenho"] == "colagem_balanca" and mico["tom"] == "leve" and "balanca" in mico["desenhos_proibidos"]
    onca = motion_ia.direcao_pelo_codigo({"texto": "Um macho adulto pode passar de cem quilos de puro músculo."},
                                         foto=True)
    assert onca["desenho"] == "colagem_balanca" and onca["tom"] == "pesado"
    # sem foto, a colagem não vale
    assert motion_ia._limpar_direcao({"desenho": "colagem_balanca", "tom": "leve", "leitura": "x"},
                                     {"texto": MICO}, foto=False)["desenho"] == "tipografia"


def test_recorte_recusado_pela_visao_vai_para_a_moldura_e_fica_guardado(monkeypatch, tmp_path):
    from fabrica import openrouter_local, recorte
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "foto.jpg").write_bytes(b"foto")
    opcao = tmp_path / "r1.png"
    opcao.write_bytes(b"png")
    monkeypatch.setattr(recorte, "variantes", lambda foto, pasta: [opcao])
    monkeypatch.setattr(recorte, "folha", lambda opcoes, destino: destino)
    perguntas = []
    monkeypatch.setattr(openrouter_local.VISAO, "perguntar", lambda *a, **k: perguntas.append(k) or {"melhor": 0})
    cena = {"n": 15, "animal": "golden lion tamarin"}
    assert motion_ia._recorte_da_cena(None, tmp_path, "foto.jpg", cena, log=lambda *a: None) is None
    assert perguntas[0]["so_gratuitos"] is True
    assert motion_ia._recorte_da_cena(None, tmp_path, "foto.jpg", cena, log=lambda *a: None) is None
    assert len(perguntas) == 1  # guardado: não pergunta de novo
    (tmp_path / "recorte.json").unlink()
    monkeypatch.setattr(openrouter_local.VISAO, "perguntar", lambda *a, **k: {"melhor": 1})
    assert motion_ia._recorte_da_cena(None, tmp_path, "foto.jpg", cena, log=lambda *a: None) == "recorte.png"
    assert (tmp_path / "assets" / "recorte.png").read_bytes() == b"png"


# ------------------------------- motion onde ajuda o roteiro, mesmo com a foto aprovada (pedido de 2026-10-07)

def test_cena_com_dado_e_foto_aprovada_e_candidata(tmp_path):
    cenas = [
        {"n": 14, "texto": "que cabe na palma da mão e parece carregar uma pequena chama.", "midia": {"arquivo": "midia/0014.jpg"},
         "conferencia": {"nota": 90}},
        {"n": 15, "texto": "O mico-leão-dourado pesa pouco mais de meio", "midia": {"arquivo": "midia/0015.jpg"},
         "conferencia": {"nota": 95}},
        {"n": 16, "texto": "quilo, tem uma juba alaranjada que brilha ao sol", "midia": {"arquivo": "midia/0016.jpg"},
         "conferencia": {"nota": 97}},
        {"n": 17, "texto": "Restavam apenas cerca de duzentos micos na natureza.", "midia": {"arquivo": "midia/0017.jpg"}},
        {"n": 18, "texto": "Hoje 80 por cento deles vivem em reservas.", "midia": {"arquivo": "midia/0018.jpg"},
         "motion_reserva": {"midia": None}},  # já foi motion e a pessoa trocou pela foto
    ]
    projeto = _Projeto(tmp_path, cenas)
    # a frase cortada no meio: o clipe fica na cena em que o dado começa, e a seguinte não repete
    assert [c["n"] for c in motion_ia.uteis(projeto)] == [15, 17]
    assert motion_ia.pode_ajudar(cenas[1], cenas[2]) == "mais de meio quilo"
    assert motion_ia.pode_ajudar({"texto": "a caça ilegal levou a espécie à beira da extinção"}) != ""
    assert motion_ia.pode_ajudar({"texto": "tem uma juba alaranjada que brilha ao sol"}) == ""
    assert motion_ia.pode_ajudar({"texto": "Em 1898 foi construída a ponte"}) == ""  # ano não é dado


def test_motion_desfeito_nao_volta(tmp_path):
    cena = {"n": 15, "texto": "O mico-leão-dourado pesa pouco mais de meio quilo.",
            "midia": {"fonte": "motion_ia", "arquivo": "midia/0015_motion.mp4"},
            "motion_reserva": {"midia": {"arquivo": "midia/0015.jpg"}, "tipo": "foto_real"}}
    projeto = _Projeto(tmp_path, [cena])
    assert motion_ia.desfazer(projeto, 15)
    voltou = projeto.ler_json("cenas.json")["cenas"]
    assert voltou[0]["midia"]["arquivo"] == "midia/0015.jpg"
    assert motion_ia.candidatas(projeto, voltou) == []


# ------------------------------ o clipe cobre a frase inteira; a palavra dá o tempo (pedido de 2026-10-08)

def test_o_clipe_cobre_a_frase_ate_o_ponto():
    todas = {
        191: {"n": 191, "ini": 691.3, "fim": 694.26, "bloco": "b9", "texto": "chegar a quase dois metros de comprimento, contando a"},
        192: {"n": 192, "ini": 694.26, "fim": 697.18, "bloco": "b9", "texto": "a cauda achatada que funciona como leme."},
        193: {"n": 193, "ini": 697.18, "fim": 700.9, "bloco": "b9", "texto": "Tem o corpo alongado, pelos curtos e densos,"},
    }
    projeto = SimpleNamespace(config={})
    assert [c["n"] for c in motion_ia.frase_da_cena(projeto, todas[191], todas)] == [191, 192]
    assert [c["n"] for c in motion_ia.frase_da_cena(projeto, todas[192], todas)] == [192]
    # nunca passa do limite nem atravessa a foto que a pessoa subiu
    curto = SimpleNamespace(config={"motion_ia": {"duracao_maxima": 4}})
    assert [c["n"] for c in motion_ia.frase_da_cena(curto, todas[191], todas)] == [191]
    todas[192]["imagem_da_pessoa"] = True
    assert [c["n"] for c in motion_ia.frase_da_cena(projeto, todas[191], todas)] == [191]


def test_o_segundo_de_cada_palavra_vem_da_narracao(tmp_path):
    import json
    (tmp_path / "alinhamento.json").write_text(json.dumps({"palavras": [
        {"texto": "chegar", "ini": 691.181}, {"texto": "dois", "ini": 691.97}, {"texto": "metros", "ini": 692.237},
        {"texto": "cauda", "ini": 694.211}, {"texto": "leme.", "ini": 695.987}, {"texto": "Tem", "ini": 697.142}]}),
        encoding="utf-8")
    projeto = _Projeto(tmp_path, [])
    cena = {"ini": 691.3, "fim": 697.18}
    tempos = motion_ia.segundos_das_palavras(projeto, cena, {"valor": "dois", "parte": "cauda", "funcao": "leme",
                                                             "outra": "jacaré"})
    assert tempos == {"valor": 0.67, "parte": 2.91, "funcao": 4.69}


def test_correcao_que_sai_igual_para_a_revisao(monkeypatch):
    # cena 191 do 11-animais-do-brasil: o desenho pronto saiu igual três vezes, com a mesma nota
    pedidos = []

    def um_clipe(projeto, cena, dur, vizinhas, pasta, nome_foto, usados, log, erros_visuais=(), direcao=None):
        pedidos.append(1)
        return {"css": "", "html": "", "js": "", "modelo": "medida_colagem", "dados": {"valor": 2}}
    monkeypatch.setattr(motion_ia, "_um_clipe", um_clipe)
    monkeypatch.setattr(motion_ia, "criticar", lambda *a, **k: _critica(7))
    projeto = SimpleNamespace(config={"motion_ia": {"critica": {}}})
    resultado = motion_ia._revisado(projeto, {"n": 191}, 5.9, ("", ""), None, None, (), lambda *a: None)
    assert len(pedidos) == 2 and resultado["critica"]["menor"] == 7


def test_o_que_o_modelo_esqueceu_sai_da_fala():
    # cena 21 do 11-animais-do-brasil: sem o "cerca de" e com o número por extenso, sem contar
    from fabrica import motion_modelos
    fala = "Restavam apenas cerca de duzentos micos na natureza."
    d, _ = motion_modelos.conferir("contagem_colagem", {"valor": 200, "unidade": "micos", "rotulo_valor": "duzentos"},
                                   fala, figura=True)
    assert "rotulo_valor" not in d and d["palavra_valor"] == "duzentos"
    motion_ia._completar_pela_fala(d, fala)
    assert d["prefixo"] == "cerca de"
    sem_palavra = {"valor": 2}
    motion_ia._completar_pela_fala(sem_palavra, "pode chegar a quase dois metros de comprimento")
    assert sem_palavra == {"valor": 2, "prefixo": "quase", "palavra_valor": "dois"}


def test_o_mesmo_desenho_no_maximo_duas_vezes_no_video(monkeypatch, tmp_path):
    # "mudar a balança, que já apareceu umas 10x": 3 balanças e 4 tipografias em 16 clipes do 11-animais-do-brasil
    cenas = [{"n": n, "midia": {"fonte": "motion_ia"}} for n in (91, 257, 285, 350)]
    projeto = _Projeto(tmp_path, cenas)
    modelos = {91: "colagem_balanca", 257: "balanca", 285: "colagem_balanca", 350: "tipografia"}
    monkeypatch.setattr(motion_ia, "modelo_da_cena", lambda projeto, n: modelos[n])
    assert motion_ia.usados_no_video(projeto) == {"balanca": 3, "tipografia": 1}
    direcao = motion_ia.com_esgotados({"desenho": "colagem_balanca", "desenhos_proibidos": []}, projeto, exceto=[257])
    assert direcao["desenho"] == "" and {"balanca", "colagem_balanca"} <= set(direcao["desenhos_proibidos"])
    assert "tipografia" not in direcao["desenhos_proibidos"]


def test_dois_metros_e_meio_e_passar_de_saem_da_fala():
    # o pirarucu da cena 257: o modelo escreveu "2 metros" e esqueceu o "mais de"
    fala = "Pode passar de dois metros e meio e pesar mais de cem quilos."
    dados = {"itens": [{"valor": 2, "unidade": "metros", "palavra": "dois"},
                       {"valor": 100, "unidade": "quilos", "prefixo": "mais de", "palavra": "cem"}]}
    motion_ia._completar_pela_fala(dados, fala)
    assert dados["itens"][0] == {"valor": 2.5, "unidade": "metros", "palavra": "dois", "prefixo": "mais de"}
    assert dados["itens"][1]["valor"] == 100 and dados["itens"][1]["prefixo"] == "mais de"


def test_perfil_todo_em_motion_manda_toda_cena_sem_o_jev(tmp_path, monkeypatch):
    cenas = [{"n": 1, "texto": "Uma frase."}, {"n": 2, "texto": "Outra.", "personagem": True}]
    projeto = _Projeto(tmp_path, cenas)
    projeto.perfil = {"motion_ia": {"tudo": True}}
    monkeypatch.setattr(motion_ia, "ligado", lambda p: True)
    assert motion_ia.tudo_em_motion(projeto)
    assert motion_ia.classificar(projeto, cenas, log=lambda *a: None) == {1: True, 2: False}


def test_estilo_colagem_por_cima_do_esqueleto():
    html = motion_ia.montar_html(BOM, 3.0, estilo="colagem")
    assert 'id="m-colagem-fundo"' in html and "m-textura-papel" in html
    assert 'ease: "steps(6)"' in html and "back.out" not in html  # a mola vira degraus
    assert "scale: 1.05" in html and "scale: 1.03" not in html  # zoom lento de 1,0 a 1,05
    assert 'id="m-papel"' not in html  # o id da tipografia não pode colidir com o fundo
    assert motion_ia.montar_html(BOM, 3.0) == motion_ia.montar_html(BOM, 3.0, estilo=None)
    assert "m-colagem-fundo" not in motion_ia.montar_html(BOM, 3.0)


@pytest.mark.skipif(importlib.util.find_spec("fabrica.motion_colagem") is None,
                    reason="fabrica/motion_colagem.py (documento, barbante, foto_recortada) não está na pasta")
def test_desenhos_de_colagem_de_acervo():
    from fabrica import motion_modelos as mm
    fala = "O voo decola com 239 pessoas. Nvidia, OpenAI e Oracle se ligam. É a primeira Denominação de Origem."
    d, erros = mm.conferir("documento", {"carimbo": "239 pessoas", "linhas": ["O voo decola"]}, fala)
    assert not erros and "239 PESSOAS" in mm.partes("documento", d, 5.0)["html"]
    assert mm.conferir("documento", {"carimbo": "999 pessoas"}, fala)[1]  # número que a fala não diz
    assert mm.conferir("documento", {"linhas": ["O voo"]}, fala)[1]  # sem carimbo
    d, erros = mm.conferir("barbante", {"etapas": ["Nvidia", "OpenAI", "Oracle"]}, fala)
    assert not erros and mm.partes("barbante", d, 5.0)["js"].count("m-fio-") == 2
    assert mm.conferir("barbante", {"etapas": ["Nvidia"]}, fala)[1]
    # a foto recortada só vale quando a cena tem foto
    assert mm.conferir("foto_recortada", {"etiqueta": "Origem"}, fala)[1]
    d, erros = mm.conferir("foto_recortada", {"etiqueta": "Denominação de Origem"}, fala, tem_foto=True)
    assert not erros and "m-fq" in mm.partes("foto_recortada", d, 5.0, "foto.jpg")["html"]


def test_estilo_vox_entra_pelo_perfil_ao_lado_do_motion_ia_comum(tmp_path):
    projeto = _Projeto(tmp_path, [], config={"motion_ia": {"ativo": True, "estilo": ""}})
    projeto.perfil = {}
    assert motion_ia.estilo(projeto) == "" and motion_ia.linha_do_estilo(projeto) == ""
    projeto.perfil = {"motion_ia": {"estilo": "colagem"}}  # perfil documentario-vox: só troca o estilo, o resto do config fica
    assert motion_ia.estilo(projeto) == "colagem" and motion_ia.config(projeto)["ativo"] is True
    assert "foto_recortada" in motion_ia.linha_do_estilo(projeto)
    projeto.perfil = {"motion_ia": {"estilo": "vox"}}
    assert motion_ia.estilo(projeto) == "colagem"


def _projeto_livre(tmp_path, cenas, **extra):
    projeto = _Projeto(tmp_path, cenas, config={"motion_ia": {"demonstracao": "livre", **extra}})
    projeto.perfil = {}
    projeto.roteiro = lambda: " ".join(c["texto"] for c in cenas)
    projeto.existe = lambda nome: (tmp_path / nome).exists()
    (tmp_path / "alinhamento.json").write_text(
        '{"palavras": [{"c": 0, "texto": "Em", "ini": 0.1}, {"c": 3, "texto": "1875", "ini": 1.2}]}', encoding="utf-8")
    return projeto


def test_demonstracao_livre_aceita_desenho_figurativo_e_barra_o_que_estraga():
    bom = {"css": "#m-g { position: absolute; left: 300px; top: 200px; width: 400px; height: 500px; }"
                  " .m-r { font-size: 48px; }",
           "html": '<svg id="m-g" viewBox="0 0 400 500"><path d="M 100 0 L 300 0 L 340 500 L 60 500 Z" fill="#14213D"/></svg>',
           "js": 'tl.fromTo("#m-g", {opacity: 0, y: 60}, {opacity: 1, y: 0, duration: 0.8, ease: "elastic.out(1, 0.5)"}, 1.2);'}
    assert motion_ia.problemas_do_codigo_livre(bom) == []  # sem mola obrigatória nem peças prontas
    assert any("sorteio" in e for e in motion_ia.problemas_do_codigo_livre({**bom, "js": bom["js"] + "Math.random();"}))
    assert any("pequeno" in e for e in motion_ia.problemas_do_codigo_livre({**bom, "css": ".m-r { font-size: 20px; }"}))
    assert any("pequeno" in e for e in motion_ia.problemas_do_codigo_livre(
        {**bom, "html": '<svg><text font-size="24">x</text></svg>'}))
    assert motion_ia.problemas_do_codigo_livre({**bom, "js": ""})


def test_orquestradora_guarda_o_briefing_e_ele_vai_no_pedido(tmp_path, monkeypatch):
    from fabrica import roteirista
    cenas = [{"n": 1, "texto": "Em 1875 chegam os imigrantes.", "ini": 0.0, "fim": 3.5, "bloco": 1},
             {"n": 2, "texto": "Eles plantam uvas.", "ini": 3.5, "fim": 6.0, "bloco": 1}]
    projeto = _projeto_livre(tmp_path, cenas)
    perguntas = []

    class Agente:
        def perguntar(self, projeto, etapa, instrucoes, pedido, esquema, log=print, **resto):
            perguntas.append(pedido)
            return {"trechos": [{"n": 1, "funcao": "abre a história", "o_que_mostrar": "um navio que chega a uma encosta",
                                 "elementos": ["navio", "encosta"], "evitar": ["bandeira"],
                                 "momentos": [{"palavra": "1875", "acontece": "o ano carimba o casco"}],
                                 "texto_na_tela": "1875", "intensidade": "rica"},
                                {"n": 2, "funcao": "mostra o trabalho", "o_que_mostrar": "fileiras de parreiras crescendo"},
                                {"n": 99, "funcao": "x", "o_que_mostrar": "lixo"}]}

    monkeypatch.setattr(roteirista, "_modelo_agente", lambda p: Agente())
    feitos = motion_ia.orquestrar(projeto, log=lambda *a: None)
    assert sorted(feitos) == [1, 2] and feitos[1]["o_que_mostrar"].startswith("um navio")
    assert "[trecho 1]" in perguntas[0] and "TRECHOS PARA DECIDIR" in perguntas[0]
    # guardado pela fala: a segunda chamada não pergunta de novo, e a fala nova pede de novo
    motion_ia.orquestrar(projeto, log=lambda *a: None)
    assert len(perguntas) == 1
    trecho = motion_ia.trechos_do_projeto(projeto)[0]
    assert motion_ia.briefing_do_trecho(projeto, trecho)["texto_na_tela"] == "1875"
    direcao = motion_ia._direcao_do_briefing(projeto, trecho)
    assert direcao["leitura"].startswith("um navio") and direcao["nao_mostrar"] == ["bandeira"]
    pedido = motion_ia._pedido_livre(projeto, trecho[0], 3.5, ("", ""), [], briefing=direcao["briefing"])
    assert "BRIEFING DA ORQUESTRADORA" in pedido and "na palavra \"1875\"" in pedido and "1875 1.20" in pedido
