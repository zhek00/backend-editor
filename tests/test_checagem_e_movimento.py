"""Checagem técnica do vídeo pronto (imagem parada, tela preta, falta de som) e regras de movimento dos clipes de motion.

Ideias do video-use (autoavaliação do vídeo montado) e do motionmaxxing (quadro morto, cara de slide, movimento medido)."""
import json
import os
import pathlib
import shutil
import subprocess

import pytest

from fabrica import checagem_video, motion_ia, movimento

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


# --- checagem técnica ----------------------------------------------------------------------------------------------

def _video_com_defeitos(pasta):
    """3 s em movimento, 3 s de foto parada, 1,5 s de tela preta e 4 s de foto com zoom lento (como a fábrica faz).
    O som: 4 s de tom, 3 s de silêncio, 4,5 s de tom."""
    foto = pasta / "foto.png"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=1",
                    "-frames:v", "1", str(foto)], check=True)
    destino = pasta / "final.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=3",
        "-loop", "1", "-t", "3", "-i", str(foto),
        "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30:d=1.5",
        "-loop", "1", "-t", "4", "-i", str(foto),
        "-f", "lavfi", "-i", "sine=f=440:d=4", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=3",
        "-f", "lavfi", "-i", "sine=f=330:d=4.5",
        "-filter_complex",
        "[1:v]scale=1280:720,fps=30,setsar=1[parada];"
        "[3:v]scale=1280:720,zoompan=z='1+0.0008*on':d=1:s=1280x720:fps=30,setsar=1[zoom];"
        "[0:v]setsar=1[a];[2:v]setsar=1[preto];[a][parada][preto][zoom]concat=n=4:v=1:a=0[v];"
        "[4:a]aresample=44100[s1];[6:a]aresample=44100[s3];[s1][5:a][s3]concat=n=3:v=0:a=1[au]",
        "-map", "[v]", "-map", "[au]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(destino)], check=True)
    return destino


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    if not FFMPEG:
        pytest.skip("sem ffmpeg nesta máquina")
    return _video_com_defeitos(tmp_path_factory.mktemp("checagem"))


def _trecho(trechos, tipo):
    achados = [t for t in trechos if t["tipo"] == tipo]
    assert len(achados) == 1, trechos
    return achados[0]


def test_medir_acha_os_tres_defeitos_e_nao_acusa_o_zoom_lento(video):
    trechos = checagem_video.medir(video)
    parada, preta, muda = (_trecho(trechos, t) for t in ("congelado", "preto", "silencio"))
    assert parada["ini"] == pytest.approx(3, abs=0.2) and parada["fim"] == pytest.approx(6, abs=0.2)
    assert preta["ini"] == pytest.approx(6, abs=0.2) and preta["fim"] == pytest.approx(7.5, abs=0.2)
    assert muda["ini"] == pytest.approx(4, abs=0.2) and muda["fim"] == pytest.approx(7, abs=0.2)
    # a foto com zoom lento, de 7,5 s em diante, nunca entra como parada
    assert not [t for t in trechos if t["tipo"] == "congelado" and t["fim"] > 7.6]


class _Projeto:
    nome = "t"

    def __init__(self, pasta, cenas, atraso=0.0, config=None):
        self.pasta = pathlib.Path(pasta)
        self.config = config or {}
        (self.pasta / "cenas.json").write_text(json.dumps({"cenas": cenas}), encoding="utf-8")
        (self.pasta / "render").mkdir(exist_ok=True)
        (self.pasta / "render" / "linha.json").write_text(json.dumps({"atraso": atraso}), encoding="utf-8")

    def existe(self, nome):
        return (self.pasta / nome).exists()

    def ler_json(self, nome):
        return json.loads((self.pasta / nome).read_text(encoding="utf-8"))

    def salvar_json(self, nome, dados):
        (self.pasta / nome).write_text(json.dumps(dados), encoding="utf-8")

    def caminho(self, *partes):
        return self.pasta.joinpath(*partes)


def test_checar_liga_cada_defeito_as_cenas_contando_a_abertura(video, tmp_path):
    shutil.copy(video, tmp_path / "final.mp4")
    # a abertura empurra a narração em 1 s: a cena 2 (2 a 5 s da narração) passa no vídeo de 3 a 6 s, a da foto parada
    cenas = [{"n": 1, "ini": 0.0, "fim": 2.0}, {"n": 2, "ini": 2.0, "fim": 5.0}, {"n": 3, "ini": 5.0, "fim": 6.5},
             {"n": 4, "ini": 6.5, "fim": 9.8}]
    projeto = _Projeto(tmp_path, cenas, atraso=1.0)
    dados = checagem_video.checar(projeto, log=lambda m: None)
    parada = _trecho(dados["trechos"], "congelado")
    assert parada["cenas"] == [2, 3] or parada["cenas"] == [2]
    assert _trecho(dados["trechos"], "preto")["gravidade"] == "alta"
    assert 2 in dados["graves"]
    assert checagem_video.resultado(projeto) == dados
    assert "tela preta" in checagem_video.resumo(dados)


def test_resultado_deixa_de_valer_depois_de_um_render_novo(video, tmp_path):
    shutil.copy(video, tmp_path / "final.mp4")
    projeto = _Projeto(tmp_path, [{"n": 1, "ini": 0.0, "fim": 10.0}])
    checagem_video.checar(projeto, log=lambda m: None)
    os.utime(tmp_path / "final.mp4", (1, 1))  # outro final.mp4 no lugar
    assert checagem_video.resultado(projeto) is None


def test_fim_do_video_apagando_e_gravidade_baixa():
    assert checagem_video._gravidade({"tipo": "preto", "ini": 99.0, "fim": 100.0}, 100.0) == "baixa"
    assert checagem_video._gravidade({"tipo": "preto", "ini": 50.0, "fim": 51.0}, 100.0) == "alta"
    assert checagem_video._gravidade({"tipo": "congelado", "ini": 10.0, "fim": 12.5}, 100.0) == "media"
    assert checagem_video._gravidade({"tipo": "congelado", "ini": 10.0, "fim": 15.0}, 100.0) == "alta"


def test_desligada_pelo_config(tmp_path):
    assert not checagem_video.ligada(_Projeto(tmp_path, [], config={"checagem_video": {"ativo": False}}))
    assert checagem_video.ligada(_Projeto(tmp_path, []))


def test_resumo_sem_defeitos():
    assert "nenhuma" in checagem_video.resumo({"trechos": []})


# --- regras de movimento -------------------------------------------------------------------------------------------

# o exemplo que o próprio INSTRUCOES_HTML dá ao modelo: tem de passar em todas as regras
_EXEMPLO = {
    "css": "#m-f { position: absolute; left: 190px; top: 230px; width: 700px; height: 470px; }\n"
           "#m-d { position: absolute; left: 1030px; top: 270px; width: 700px; height: 390px; }\n"
           ".m-linha-1 { stroke: var(--laranja); stroke-width: 4; }",
    "html": '<div id="m-f" class="m-card m-foto"></div><div id="m-d" class="m-card"><div class="m-num">50</div>'
            '<div class="m-rot">quilômetros por <span class="m-destaque">hora</span></div></div>',
    "js": 'tl.fromTo("#m-f", {y: 40, scale: 0.92, opacity: 0}, {y: 0, scale: 1, opacity: 1, duration: 0.7, ease: "back.out(1.7)"}, 0.1);\n'
          'tl.to(".m-linha-1", {strokeDashoffset: 0, duration: 0.6, ease: "power3.out"}, 0.6);\n'
          'tl.fromTo("#m-d", {y: 40, scale: 0.92, opacity: 0}, {y: 0, scale: 1, opacity: 1, duration: 0.7, ease: "back.out(1.7)"}, 0.8);\n'
          'tl.fromTo("#m-d .m-num, #m-d .m-rot", {y: 30, opacity: 0}, {y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.7)", stagger: 0.15}, 1.0);\n'
          'tl.fromTo(".m-barra-1", {scaleY: 0}, {scaleY: 1, duration: 0.7, ease: "back.out(1.7)"}, 0.9);',
}


def _com(**mudanca):
    return {**_EXEMPLO, **mudanca}


def test_o_exemplo_do_proprio_pedido_passa():
    assert movimento.problemas(_EXEMPLO) == []
    assert motion_ia.problemas_do_codigo(_EXEMPLO) == []


def test_as_regras_estao_nos_dois_pedidos_ao_modelo():
    assert movimento.REGRAS in motion_ia.INSTRUCOES_HTML
    assert movimento.REGRAS in motion_ia.INSTRUCOES_LIVRE
    assert "Cara de slide" in motion_ia.CRITERIOS["acabamento"]


def test_contador_de_slide_reprova():
    assert any("contador" in e for e in movimento.problemas(_com(html=_EXEMPLO["html"] + '<div id="m-c">02 / 05</div>')))
    # fração de verdade, do dado da fala, não é contador
    assert not any("contador" in e for e in movimento.problemas(_com(html='<div class="m-num">1/3</div>')))


def test_barra_de_progresso_reprova():
    assert any("progresso" in e for e in movimento.problemas(_com(html=_EXEMPLO["html"] + '<div class="m-progresso"></div>')))


def test_rotulo_em_caixa_alta_espacada_reprova_mas_caixa_alta_simples_passa():
    ruim = _com(css=_EXEMPLO["css"] + "\n#m-k { text-transform: uppercase; letter-spacing: 0.22em; font-size: 36px; }")
    assert any("caixa-alta" in e for e in movimento.problemas(ruim))
    pouco = _com(css=_EXEMPLO["css"] + "\n#m-k { text-transform: uppercase; letter-spacing: 0.02em; }")
    assert not any("caixa-alta" in e for e in movimento.problemas(pouco))


def test_texto_digitado_letra_por_letra_reprova():
    js = _EXEMPLO["js"] + '\nconst letras = "Tsavo".split(""); letras.forEach((l, i) => tl.set("#m-t", {}, i * 0.05));'
    assert any("digitado" in e for e in movimento.problemas(_com(js=js)))


def test_entradas_so_de_opacidade_reprovam_mas_uma_passa():
    so_fade = ('tl.fromTo("#m-a", {opacity: 0}, {opacity: 1, duration: 0.5}, 0.1);\n'
               'tl.fromTo("#m-b", {opacity: 0}, {opacity: 1, duration: 0.5}, 0.4);\n'
               'tl.fromTo("#m-c", {y: 30, opacity: 0}, {y: 0, opacity: 1, duration: 0.5, ease: "back.out(1.7)"}, 0.7);')
    assert any("só de opacidade" in e for e in movimento.problemas(_com(js=so_fade)))
    um_brilho = _EXEMPLO["js"] + '\ntl.fromTo("#m-brilho", {opacity: 0}, {opacity: 0.6, duration: 0.4}, 1.5);'
    assert not any("só de opacidade" in e for e in movimento.problemas(_com(js=um_brilho)))


def test_crescer_de_um_ponto_reprova_mas_barra_e_icones_em_sequencia_passam():
    ponto = _EXEMPLO["js"] + '\ntl.fromTo("#m-caixa", {scale: 0, opacity: 0}, {scale: 1, opacity: 1, duration: 0.45, ease: "back.out(1.7)"}, 0.25);'
    assert any("de um ponto" in e for e in movimento.problemas(_com(js=ponto)))
    icones = _EXEMPLO["js"] + ('\ntl.fromTo(".m-ic", {scale: 0, opacity: 0}, {scale: 1, opacity: 1, duration: 0.35, '
                               'ease: "back.out(2)", stagger: {each: 0.035, from: "start"}}, 1.74);')
    assert movimento.problemas(_com(js=icones)) == []  # ícones de contagem surgindo em sequência são infográfico


def test_demonstracao_livre_tambem_confere_o_movimento():
    ponto = _com(js='tl.fromTo("#m-caixa", {scale: 0}, {scale: 1, duration: 0.45, ease: "power2.out"}, 0.25);')
    assert any("de um ponto" in e for e in motion_ia.problemas_do_codigo_livre(ponto))
