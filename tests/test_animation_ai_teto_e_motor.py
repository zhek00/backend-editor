"""animation-ai: teto no lugar do motion, kicker legível e transições com chegada desacelerando e saída acelerando.

Antes: com o Motion IA pausado, as cenas reprovadas viravam cena animada sem teto nenhum (o brasil-selvagem chegou a
118 cenas, 31% do vídeo); com 25% e sem intervalo, o everything-you-need-to-answer saiu com 24 trechos; o kicker era caixa-alta espaçada de 26 px; e a transição
de cena era linear nos dois sentidos."""
import json
import pathlib
import re

from fabrica import animation_ai

RECURSOS = pathlib.Path(animation_ai.__file__).parent / "recursos" / "animation_ai"


class _Projeto:
    offline = False
    perfil: dict = {}

    def __init__(self, pasta, cenas, duracao, config=None):
        self.pasta = pathlib.Path(pasta)
        self.config = config or {}
        (self.pasta / "cenas.json").write_text(json.dumps({"cenas": cenas}), encoding="utf-8")
        (self.pasta / "alinhamento.json").write_text(json.dumps({"duracao": duracao}), encoding="utf-8")

    def existe(self, nome):
        return (self.pasta / nome).exists()

    def ler_json(self, nome):
        return json.loads((self.pasta / nome).read_text(encoding="utf-8"))


def _rodar(monkeypatch, tmp_path, cenas, notas, duracao=100.0, config=None, como_motion=True):
    """nas_uteis com o modelo e a gravação simulados: cada cena é uma frase, com a nota dada em notas[n]."""
    projeto = _Projeto(tmp_path, cenas, duracao, config)
    livres = [c for c in cenas if not (c.get("midia") or {}).get("fonte")]
    monkeypatch.setattr(animation_ai.animacoes, "node_pronto", lambda: "npx")
    monkeypatch.setattr(animation_ai, "frases_do_video", lambda todas, cfg: [[c] for c in livres])
    monkeypatch.setattr(animation_ai, "_itens_util", lambda projeto, grupos, todas: [
        {"id": str(g[0]["n"]), "ini": g[0]["ini"], "fim": g[0]["fim"], "dur": g[0]["fim"] - g[0]["ini"], "grupo": g}
        for g in grupos])
    monkeypatch.setattr(animation_ai, "decidir", lambda projeto, itens, log, tipos=None: {
        it["id"]: {"nota": notas[int(it["id"])], "tipo": "lista", "dados": {}} for it in itens})
    gravadas = []
    monkeypatch.setattr(animation_ai, "_gravar_grupos", lambda projeto, pares, log, frase_de_reserva=True: (
        gravadas.extend(g[0]["n"] for g, _ in pares) or [g[0]["n"] for g, _ in pares]))
    avisos = []
    feitas = animation_ai.nas_uteis(projeto, avisos.append, como_motion=como_motion)
    return feitas, avisos


def _cenas(n, dur=5.0, inicio=0.0):
    return [{"n": i + 1, "ini": inicio + i * dur, "fim": inicio + (i + 1) * dur, "texto": f"frase {i + 1}"} for i in range(n)]


# --- teto no lugar do motion ---------------------------------------------------------------------------------------
# 2026-10-25 (pedido do usuário: "muitos motion e muitas cenas longas"): o teto caiu de 25% para 10%, entrou um intervalo
# de 20 s também no lugar do motion e os primeiros 40 s ficam sem cena animada. As cenas dos testes começam aos 40 s

def test_no_lugar_do_motion_respeita_o_teto_de_10_por_cento(monkeypatch, tmp_path):
    # 20 cenas de 5 s num vídeo de 200 s, todas aprovadas: 10% = 20 s = 4 cenas, a 20 s uma da outra
    feitas, avisos = _rodar(monkeypatch, tmp_path, _cenas(20, inicio=40.0), {i: 80 for i in range(1, 21)},
                            duracao=200.0)
    assert len(feitas) == 4
    assert all((b - a) * 5 - 5 >= 20 for a, b in zip(sorted(feitas), sorted(feitas)[1:]))
    assert any("ficaram fora pelo teto de 10%" in a for a in avisos)


def test_no_teto_entram_as_de_nota_maior(monkeypatch, tmp_path):
    notas = {1: 71, 2: 95, 3: 72, 4: 90, 5: 73, 6: 85, 7: 74, 8: 70}
    feitas, _ = _rodar(monkeypatch, tmp_path, _cenas(8, inicio=40.0), notas, duracao=50.0)  # 10% de 50 s = 1 cena
    assert feitas == [2]


def test_o_teto_conta_as_cenas_que_ja_estao_animadas(monkeypatch, tmp_path):
    ja = [{"n": 99, "ini": 160.0, "fim": 175.0, "midia": {"fonte": "animation_ai"}}]  # 15 s já animados de 200 s
    feitas, _ = _rodar(monkeypatch, tmp_path, _cenas(6, inicio=40.0) + ja, {i: 80 for i in range(1, 7)},
                       duracao=200.0)
    assert len(feitas) == 1  # sobram 5 s dos 20 s


def test_os_primeiros_40_segundos_ficam_sem_cena_animada(monkeypatch, tmp_path):
    feitas, _ = _rodar(monkeypatch, tmp_path, _cenas(12), {i: 80 for i in range(1, 13)}, duracao=60.0,
                       config={"animation_ai": {"maximo_no_lugar_do_motion": 1, "intervalo_no_lugar_do_motion": 0}})
    assert sorted(feitas) == [9, 10, 11, 12]  # a cena 9 começa aos 40 s


def test_teto_e_intervalo_podem_mudar_no_config(monkeypatch, tmp_path):
    feitas, _ = _rodar(monkeypatch, tmp_path, _cenas(10), {i: 80 for i in range(1, 11)},
                       config={"animation_ai": {"maximo_no_lugar_do_motion": 0.5, "intervalo_no_lugar_do_motion": 0,
                                                "inicio_sem_animacao": 0}})
    assert len(feitas) == 10


def test_complemento_com_o_teto_e_o_intervalo_novos(monkeypatch, tmp_path):
    monkeypatch.setattr(animation_ai, "estrutura", lambda g: "lista")
    feitas, _ = _rodar(monkeypatch, tmp_path, _cenas(40, inicio=40.0), {i: 80 for i in range(1, 41)}, duracao=240.0,
                       como_motion=False)
    # 6% de 240 s = 14,4 s (2 cenas de 5 s), a 30 s uma da outra
    assert len(feitas) == 2
    assert abs(feitas[0] - feitas[1]) * 5 - 5 >= 30


# --- motor: kicker e transições ------------------------------------------------------------------------------------

def test_kicker_legivel_sem_caixa_alta_espacada():
    css = (RECURSOS / "motor.css").read_text(encoding="utf-8")
    kick = re.search(r"\.kick\s*\{([^}]*)\}", css).group(1)
    assert int(re.search(r"(\d+)px", kick).group(1)) >= 32
    assert "uppercase" not in kick and "letter-spacing" not in kick


def test_transicao_de_cena_chega_desacelerando_e_sai_acelerando():
    js = (RECURSOS / "motor.js").read_text(encoding="utf-8")
    linha = next(l for l in js.splitlines() if "const ent =" in l)
    assert "sai(t / 0.22)" in linha          # entrada: ease-out (cúbica de saída)
    assert "Math.pow(lim((t - (DUR - 0.3)) / 0.3), 2)" in linha  # saída: ease-in (quadrática)


def test_versao_do_desenho_subiu_para_regravar_os_trechos():
    assert animation_ai.VERSAO >= 4
