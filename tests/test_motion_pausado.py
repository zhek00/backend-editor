"""Motion IA fora da produção (motion_ia.pausado): nenhuma entrada automática faz clipe, nem com o perfil ligando,
e o animation-ai entra no lugar dele antes da imagem de IA. Sem projeto, sem rede."""
from types import SimpleNamespace

from fabrica import animation_ai, imagens, motion_ia


def projeto(pausado, perfil=None):
    return SimpleNamespace(config={"motion_ia": {"ativo": True, "pausado": pausado}}, perfil=perfil or {},
                           offline=False)


def test_pausa_vale_por_cima_do_perfil():
    perfil_motion = {"motion_ia": {"ativo": True, "tudo": True}}  # como os perfis motion-ai e motion-vox
    assert not motion_ia.ligado(projeto(True, perfil_motion))
    assert not motion_ia.tudo_em_motion(projeto(True, perfil_motion))
    assert motion_ia.ligado(projeto(False, perfil_motion))


def test_antes_da_imagem_de_ia_entra_o_animation_ai(monkeypatch):
    chamadas = {}
    monkeypatch.setattr(animation_ai, "nas_uteis",
                        lambda p, log, numeros=None, como_motion=False: chamadas.setdefault("anim", (numeros, como_motion)) and [])
    monkeypatch.setattr(motion_ia, "resolver", lambda p, pend, log: chamadas.setdefault("motion", True) and [])
    pendentes = [{"n": 4}, {"n": 9}]
    assert imagens._motion_antes_da_ia(projeto(True), None, pendentes, lambda *a: None) == pendentes
    # só as cenas que iam para a IA, do jeito do motion (sem filtro nem teto), e o motion nem é chamado
    assert chamadas == {"anim": ({4, 9}, True)}
    chamadas.clear()
    imagens._motion_antes_da_ia(projeto(False), None, pendentes, lambda *a: None)
    assert chamadas == {"motion": True}


def test_nota_baixa_vai_para_o_animation_ai(monkeypatch):
    from fabrica import corrigir
    p = projeto(True)
    monkeypatch.setattr(animation_ai, "ligado", lambda proj: True)
    monkeypatch.setattr(motion_ia, "candidatas", lambda proj, cenas: cenas)
    monkeypatch.setattr(motion_ia, "classificar", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Jev do motion")))
    agora = {7: {"n": 7, "conferencia": {"nota": 20}}, 8: {"n": 8, "conferencia": {"nota": 90}}}
    # só a de nota baixa, sem perguntar ao Jev do motion: quem decide é o animation-ai, antes da imagem de IA
    assert corrigir._motion_com_nota_baixa(p, [7, 8], {}, agora, lambda *a: None) == [7]


def test_perfil_de_video_todo_pede_mesmo_pausado():
    perfil_motion = {"motion_ia": {"ativo": True, "tudo": True}}
    assert motion_ia.tudo_pedido(projeto(True, perfil_motion))
    assert not motion_ia.tudo_pedido(projeto(True))
