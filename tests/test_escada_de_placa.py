"""A escada de codificadores da montagem final. O ffmpeg é trocado por um dublê: nada aqui depende da placa da máquina."""
import pytest

from fabrica import render


AMF = {"codificador": "amf"}


@pytest.fixture(autouse=True)
def _limpar():
    render._placa.clear()
    yield
    render._placa.clear()


def _so_aceita(monkeypatch, aceito):
    """O ffmpeg de mentira: recusa todo codificador menos o `aceito`, como a máquina com uma placa só."""
    feitos = []

    def falso(comando):
        feitos.append([str(c) for c in comando])
        codec = feitos[-1][feitos[-1].index("-c:v") + 1]
        if codec != aceito:
            raise RuntimeError(f"Falhou ffmpeg ...\n[{codec} @ 0x1] Cannot load nvcuda.dll\n"
                               f"[vost#0:0/{codec} @ 0x2] Error while opening encoder\n"
                               "[out#0/null @ 0x3] Nothing was written into output file")

    monkeypatch.setattr(render, "rodar", falso)
    return feitos


def test_sobe_a_escada_ate_a_placa_que_existe(monkeypatch):
    feitos = _so_aceita(monkeypatch, "h264_amf")
    ditas = []
    assert render._placa_da_maquina(AMF, ditas.append) == "h264_amf"
    assert [f[f.index("-c:v") + 1] for f in feitos] == ["h264_nvenc", "h264_qsv", "h264_amf"]
    assert "Cannot load nvcuda.dll" in ditas[0]  # o motivo, não o "Nothing was written" do fim


def test_a_prova_usa_os_argumentos_do_trabalho(monkeypatch):
    feitos = _so_aceita(monkeypatch, "h264_amf")
    render._placa_da_maquina({**AMF, "cq_placa": 21})
    assert feitos[-1][feitos[-1].index("-c:v"):][:9] == render.codec_de_video({**AMF, "cq_placa": 21}, True)[:9]


def test_amf_usa_o_perfil_medido(monkeypatch):
    """O perfil quality foi 61% mais lento que a CPU na medida de 2026-11-05."""
    _so_aceita(monkeypatch, "h264_amf")
    argumentos = render.codec_de_video(AMF, True)
    assert argumentos[argumentos.index("-quality") + 1] == "speed"


def test_no_automatico_o_amf_nem_e_provado(monkeypatch):
    """Na montagem de verdade ele perdeu da CPU (41 s contra 34 s): na AMD o automático fica no libx264."""
    feitos = _so_aceita(monkeypatch, "h264_amf")
    assert render._placa_da_maquina({}) is None
    assert "h264_amf" not in [f[f.index("-c:v") + 1] for f in feitos]
    assert render.codec_de_video({}, True)[1] == "libx264"


def test_prova_acontece_uma_vez_por_execucao(monkeypatch):
    feitos = _so_aceita(monkeypatch, "h264_nvenc")
    render._placa_da_maquina({})
    render._placa_da_maquina({})
    assert len(feitos) == 1


def test_sem_placa_nenhuma_sai_em_libx264(monkeypatch):
    _so_aceita(monkeypatch, "nenhum")
    assert render._placa_da_maquina({}) is None
    assert not render._quer_placa({})
    assert render.codec_de_video({}, True)[1] == "libx264"


def test_config_cpu_nem_prova_a_placa(monkeypatch):
    feitos = _so_aceita(monkeypatch, "h264_amf")
    assert not render._quer_placa({"codificador": "cpu"})
    assert feitos == []


def test_placa_que_falha_no_trabalho_sai_do_resto_da_execucao(monkeypatch):
    _so_aceita(monkeypatch, "h264_amf")
    render._placa_da_maquina(AMF)
    chamadas = []

    def rodar_trabalho(comando):
        chamadas.append(comando)
        if comando[0] == "h264_amf":
            raise RuntimeError("No space left on device")

    monkeypatch.setattr(render, "rodar", rodar_trabalho)

    def comando(codec):
        return [codec[1]]

    assert render._rodar_codificando(comando, AMF, lambda _m: None) is False
    assert chamadas == [["h264_amf"], ["libx264"]]
    assert render._rodar_codificando(comando, AMF, lambda _m: None) is False
    assert chamadas[2:] == [["libx264"]]  # não tenta a placa de novo a cada pedaço
    assert not render._quer_placa(AMF)


# ---------------------------------------------------------------------------------------------------
# Repartir a máquina entre os renders


@pytest.fixture
def sem_renders():
    render._renders_rodando.clear()
    yield
    render._renders_rodando.clear()


def test_sozinho_o_render_fica_com_tudo(sem_renders):
    assert render._parte_da_maquina(6) == 6


def test_a_maquina_e_repartida_entre_os_renders(sem_renders):
    render._renders_rodando.update({"a", "b", "c"})
    assert render._parte_da_maquina(6) == 2


def test_o_piso_nao_deixa_nenhum_video_parado(sem_renders):
    render._renders_rodando.update({"a", "b", "c", "d", "e", "f", "g", "h"})
    assert render._parte_da_maquina(6) == 1
    assert render._parte_da_maquina(6, piso=2) == 2


class _Projeto:
    def __init__(self, pasta):
        self.pasta = pasta


def test_render_conta_enquanto_roda_e_sai_ao_terminar(monkeypatch, sem_renders):
    from contextlib import nullcontext

    from fabrica import tempos

    monkeypatch.setattr(tempos, "medir", lambda *a, **k: nullcontext())
    monkeypatch.setattr(render, "esperar_clipes_adiantados", lambda *a: None)
    vistos = []
    monkeypatch.setattr(render, "_renderizar", lambda *a: vistos.append(set(render._renders_rodando)) or "ok")
    assert render.renderizar(_Projeto("p1")) == "ok"
    assert vistos == [{"p1"}] and render._renders_rodando == set()


def test_render_que_falha_nao_fica_ocupando_a_maquina(monkeypatch, sem_renders):
    from contextlib import nullcontext

    from fabrica import tempos

    def quebra(*_a):
        raise SystemExit("Faltam imagens")

    monkeypatch.setattr(tempos, "medir", lambda *a, **k: nullcontext())
    monkeypatch.setattr(render, "esperar_clipes_adiantados", lambda *a: None)
    monkeypatch.setattr(render, "_renderizar", quebra)
    with pytest.raises(SystemExit):
        render.renderizar(_Projeto("p1"))
    assert render._renders_rodando == set()
