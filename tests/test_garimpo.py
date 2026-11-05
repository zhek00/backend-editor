"""Testes do garimpo no YouTube. Nada aqui vai à rede: o yt-dlp é trocado por um dublê."""
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fabrica import garimpo  # noqa: E402


def _entrada(vid="abc12345678", duracao=120, titulo="Grocery store walk", canal="Canal Teste", **extra):
    return {"id": vid, "duration": duracao, "title": titulo, "channel": canal, **extra}


class _YoutubeDLFalso:
    """Dublê do YoutubeDL: devolve as entradas combinadas e guarda as opções que recebeu."""

    entradas: list = []
    opcoes: list = []
    alvos: list = []
    erro: Exception | None = None

    def __init__(self, opcoes):
        _YoutubeDLFalso.opcoes.append(opcoes)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def extract_info(self, alvo, download=False):
        if _YoutubeDLFalso.erro:
            raise _YoutubeDLFalso.erro
        _YoutubeDLFalso.alvos.append(alvo)
        return {"entries": list(_YoutubeDLFalso.entradas)}


@pytest.fixture(autouse=True)
def _limpar(monkeypatch, tmp_path_factory):
    # nada de teste pode tocar no estado de verdade: um IP quente real pararia o garimpo por uma hora
    isolada = tmp_path_factory.mktemp("garimpo")
    monkeypatch.setattr(garimpo, "IP_QUENTE", isolada / "ip.json")
    monkeypatch.setattr(garimpo, "PASTA_DE_CONTAS", isolada / "contas")
    _YoutubeDLFalso.entradas = []
    _YoutubeDLFalso.opcoes = []
    _YoutubeDLFalso.erro = None
    garimpo._contas.clear()
    modulo = types.ModuleType("yt_dlp")
    modulo.YoutubeDL = _YoutubeDLFalso
    monkeypatch.setitem(sys.modules, "yt_dlp", modulo)
    yield


def test_busca_devolve_candidato_no_formato_dos_bancos():
    _YoutubeDLFalso.entradas = [_entrada()]
    (c,) = garimpo.buscar(None, "video", "grocery store")
    assert c["fonte"] == "youtube" and c["tipo"] == "video"
    # os campos que o resto da fábrica lê de qualquer banco
    for chave in ("id", "miniatura", "arquivo", "duracao", "pagina", "autor", "licenca", "descricao"):
        assert c[chave], chave
    assert c["duracao"] == garimpo.TRECHO  # a cena dispõe do trecho, não do vídeo inteiro
    assert c["arquivo"].endswith(c["id"])


def test_busca_de_foto_nao_traz_nada():
    """Miniatura de YouTube no lugar de uma foto entraria no vídeo como print de player."""
    _YoutubeDLFalso.entradas = [_entrada()]
    assert garimpo.buscar(None, "foto", "qualquer coisa") == []


@pytest.mark.parametrize("entrada", [
    _entrada(duracao=5),                      # Short: em pé e sem onde cortar
    _entrada(duracao=99999),                  # live ou aula inteira
    _entrada(live_status="is_live"),
    _entrada(live_status="is_upcoming"),
    {"id": None, "duration": 100},            # entrada sem id
    {"id": "x", "duration": None},            # entrada sem duração
])
def test_busca_descarta_o_que_nao_serve(entrada):
    _YoutubeDLFalso.entradas = [entrada]
    assert garimpo.buscar(None, "video", "grocery store") == []


def test_erro_de_conta_castiga_a_conta_e_a_busca_avisa(tmp_path, monkeypatch):
    cookies = tmp_path / "conta1.txt"
    cookies.write_text("# cookies", encoding="utf-8")
    _YoutubeDLFalso.erro = RuntimeError("Sign in to confirm you're not a bot")
    from fabrica.midia import LimiteAtingido

    # limite, e não FonteIndisponivel: FonteIndisponivel desligaria o YouTube pelo resto da execução
    with pytest.raises(LimiteAtingido) as erro:
        garimpo.buscar(None, "video", "grocery store", {"cookies": [str(cookies)]})
    assert erro.value.segundos == garimpo.CASTIGO  # sem outra conta, o banco espera
    assert garimpo._proxima_conta([cookies]) is None


def test_erro_do_video_nao_castiga_a_conta(tmp_path):
    cookies = tmp_path / "conta1.txt"
    cookies.write_text("# cookies", encoding="utf-8")
    _YoutubeDLFalso.erro = RuntimeError("Video unavailable")
    # ValueError: esta busca falha e as outras seguem (midia.Buscador._buscar)
    with pytest.raises(ValueError):
        garimpo.buscar(None, "video", "grocery store", {"cookies": [str(cookies)]})
    assert garimpo._proxima_conta([cookies]) == cookies


def test_conta_que_nao_existe_e_ignorada(tmp_path):
    existe = tmp_path / "boa.txt"
    existe.write_text("# cookies", encoding="utf-8")
    contas = garimpo.contas_de_cookies({"cookies": [str(tmp_path / "sumiu.txt"), str(existe)]})
    assert contas == [existe]


def test_cookies_pela_variavel_de_ambiente(tmp_path, monkeypatch):
    arquivo = tmp_path / "conta.txt"
    arquivo.write_text("# cookies", encoding="utf-8")
    monkeypatch.setenv("YOUTUBE_COOKIES", f"{tmp_path / 'nao-existe.txt'};{arquivo}")
    assert garimpo.contas_de_cookies({}) == [arquivo]


def test_busca_usa_os_cookies_da_conta_da_vez(tmp_path):
    cookies = tmp_path / "conta1.txt"
    cookies.write_text("# cookies", encoding="utf-8")
    _YoutubeDLFalso.entradas = [_entrada()]
    garimpo.buscar(None, "video", "grocery store", {"cookies": [str(cookies)]})
    # uma cópia, nunca o original: o yt-dlp grava no arquivo que recebe
    usado = _YoutubeDLFalso.opcoes[-1]["cookiefile"]
    assert usado != str(cookies) and not Path(usado).exists()


def test_inicio_do_trecho_pula_a_abertura_e_cabe_no_video():
    for duracao in (30, 120, 600, 2400):
        inicio = garimpo._inicio_do_trecho(duracao, garimpo.TRECHO)
        assert inicio >= 2.0
        assert inicio >= duracao * garimpo.PULO_DA_ABERTURA - 0.1  # longe da vinheta do canal
        assert inicio + garimpo.TRECHO <= duracao  # o trecho inteiro cabe


@pytest.mark.parametrize("frase", [
    "O que é: rua. Texto visível: legenda branca embaixo.",
    "O que é: loja. Texto visível: marca d'água do canal no canto.",
    "O que é: loja. Texto visível: INSCREVA-SE em amarelo.",
    "O que é: jornal. Texto visível: manchete sobreposta pelo editor.",
])
def test_veta_texto_que_outro_editor_queimou(frase):
    assert garimpo.texto_queimado(frase)


@pytest.mark.parametrize("frase", [
    "O que é: corredor de mercado. Texto visível: nenhum.",
    "O que é: fachada. Texto visível: placa Walmart na entrada.",   # a cena acontecendo, não edição alheia
    "O que é: prateleira. Texto visível: rótulos dos produtos.",
    "O que é: rua. Texto visível: nenhuma legenda.",                 # a negação cita a palavra
    "O que é: rua. Texto visível: sem marca d'água.",
    "O que é: rua.",                                                 # o juiz não falou de texto
    "",
])
def test_nao_veta_o_texto_que_e_a_propria_cena(frase):
    assert garimpo.texto_queimado(frase) == ""


def test_config_desliga_o_veto():
    frase = "O que é: rua. Texto visível: legenda branca embaixo."
    assert garimpo.texto_queimado(frase, {"vetar_texto": False}) == ""


def test_youtube_esta_registrado_como_banco():
    from fabrica import bancos

    assert bancos.FONTES["youtube"] is bancos.youtube
    assert "youtube" in bancos.FORCAS  # o Passo 2 precisa saber para o que serve esse banco


# ---------------------------------------------------------------------------------------------------
# A cota


class _ProjetoFalso:
    """O mínimo que a cota usa de um projeto: a pasta, o cenas.json e caminho()."""

    def __init__(self, pasta, cenas=0, de_youtube=0):
        self.pasta = Path(pasta)
        self.config = {}
        self._cenas = [{"n": i + 1} for i in range(cenas)]
        for c in self._cenas[:de_youtube]:
            c["midia"] = {"fonte": "youtube", "id": "x"}

    def ler_json(self, nome):
        assert nome == "cenas.json"
        return {"cenas": self._cenas}

    def caminho(self, *partes):
        return self.pasta.joinpath(*partes)


@pytest.fixture
def projeto(tmp_path):
    def fazer(cenas=100, de_youtube=0):
        garimpo._cotas.clear()
        return _ProjetoFalso(tmp_path, cenas, de_youtube)
    return fazer


def test_cota_deixa_garimpar_no_comeco(projeto):
    c = garimpo.cota(projeto(cenas=100))
    pode, motivo = c.pode_garimpar()
    assert pode and motivo == ""


def test_cota_fecha_no_teto(projeto):
    c = garimpo.cota(projeto(cenas=100))
    c.aceitos = 40  # teto padrão: 40% de 100
    pode, motivo = c.pode_garimpar()
    assert not pode and "teto" in motivo


def test_cota_fecha_quando_o_orcamento_acaba(projeto):
    c = garimpo.cota(projeto(cenas=100))
    c.downloads = 250  # orçamento padrão: 2,5 por cena
    pode, motivo = c.pode_garimpar()
    assert not pode and "orçamento" in motivo


def test_passado_o_alvo_so_segue_enquanto_rende(projeto):
    c = garimpo.cota(projeto(cenas=100))
    c.aceitos, c.downloads = 25, 40  # alvo alcançado, rendimento 25/40 = 62%
    assert c.pode_garimpar()[0]
    c.downloads = 200  # 25 de 200 = 12,5%, abaixo do piso de 15%
    assert c.rendimento() == pytest.approx(0.125)
    pode, motivo = c.pode_garimpar()
    assert not pode and "render" in motivo


def test_antes_do_alvo_o_rendimento_nao_freia(projeto):
    """Começo de vídeo tem rendimento ruim por acaso; frear ali mataria o garimpo antes de ele tentar."""
    c = garimpo.cota(projeto(cenas=100))
    c.aceitos, c.downloads = 3, 100
    assert c.pode_garimpar()[0]


def test_cota_desligada_pelo_config(projeto):
    c = garimpo.cota(projeto(cenas=100), {"cota": False})
    c.aceitos, c.downloads = 999, 999
    assert c.pode_garimpar()[0]


def test_sem_cenas_no_disco_a_cota_nao_freia(projeto):
    """No começo da produção o cenas.json ainda não existe: frear ali seria frear tudo."""
    c = garimpo.cota(projeto(cenas=0))
    assert c.pode_garimpar()[0]


def test_retomada_herda_as_cenas_que_ja_tem_trecho(projeto):
    c = garimpo.cota(projeto(cenas=100, de_youtube=30))
    assert c.aceitos == 30 and c.aceitos_herdados == 30
    assert c.pode_garimpar()[0]  # passou do alvo, mas esta execução ainda não baixou nada para medir


def test_retomada_que_passou_do_alvo_nao_fecha_na_primeira_cena(projeto):
    """A retomada herdava os downloads e descontava os aceitos: rendimento 0 de 60 e o garimpo fechava sozinho."""
    p = projeto(cenas=100, de_youtube=30)
    p.caminho(*garimpo.ARQUIVO_DA_COTA).parent.mkdir(parents=True, exist_ok=True)
    p.caminho(*garimpo.ARQUIVO_DA_COTA).write_text('{"downloads": 60, "aceitos": 30}', encoding="utf-8")
    c = garimpo.cota(p)
    assert c.downloads == 60
    assert c.pode_garimpar()[0]
    c.reservar()
    c.liberar()  # um download perdido não é amostra
    assert c.pode_garimpar()[0]
    for _ in range(garimpo.AMOSTRA_MINIMA - 1):
        c.reservar()
        c.liberar()
    assert not c.pode_garimpar()[0]  # agora sim: 0 aceitos em 10 downloads desta execução


def test_downloads_gastos_sobrevivem_a_retomada(projeto):
    p = projeto(cenas=100)
    c = garimpo.cota(p)
    for _ in range(7):
        c.reservar()
        c.liberar()
    garimpo.esquecer_cota(p)
    assert garimpo.cota(p).downloads == 7  # o orçamento é do vídeo, não da execução


def test_alvo_teto_e_orcamento_pelo_config(projeto):
    c = garimpo.cota(projeto(cenas=200), {"alvo": 0.5, "teto": 0.6, "downloads_por_cena": 1})
    assert (c._alvo(), c._teto(), c._orcamento()) == (100, 120, 200)


def test_aviso_de_fechado_sai_uma_vez_so(projeto):
    ditas = []
    c = garimpo.cota(projeto(cenas=100), None, ditas.append)
    c.avisar_se_fechou("teto alcançado")
    c.avisar_se_fechou("teto alcançado")
    assert len(ditas) == 1


def test_resumo_conta_cenas_e_orcamento(projeto):
    c = garimpo.cota(projeto(cenas=100, de_youtube=10))
    c.reservar()
    c.liberar()
    texto = c.resumo()
    assert "10/100" in texto and "alvo 25" in texto and "teto 40" in texto and "1 de 250" in texto


def test_a_cota_e_a_mesma_para_todas_as_cenas(projeto):
    """As cenas correm em paralelo: duas cotas diferentes gastariam o orçamento duas vezes."""
    p = projeto(cenas=100)
    assert garimpo.cota(p) is garimpo.cota(p)


def test_reservar_conta_quem_esta_baixando(projeto):
    """Downloads em paralelo: sem contar os que estão em voo, todos passariam pelo último lugar juntos."""
    c = garimpo.cota(projeto(cenas=10), {"teto": 0.2})
    c.reservar()
    c.reservar()
    with pytest.raises(garimpo.TrechoIndisponivel):
        c.reservar()
    c.liberar()  # um falhou: a vaga volta
    c.reservar()


def test_extra_conta_quem_foi_escolhido_e_ainda_nao_baixou(projeto):
    c = garimpo.cota(projeto(cenas=10), {"teto": 0.2})
    assert c.pode_garimpar(1)[0]
    assert not c.pode_garimpar(2)[0]


def test_aceito_devolvido_libera_a_vaga(projeto):
    c = garimpo.cota(projeto(cenas=10), {"teto": 0.1})
    c.reservar()
    c.anotar_aceito()
    assert not c.pode_garimpar()[0]
    c.devolver_aceito()
    assert c.pode_garimpar()[0]


def test_trecho_indisponivel_e_oserror():
    """midia.py captura (httpx.HTTPError, OSError, ValueError): outro tipo derrubaria a fase de mídia."""
    assert issubclass(garimpo.TrechoIndisponivel, OSError)


# ---------------------------------------------------------------------------------------------------
# O download do trecho


def _candidato(duracao=120.0):
    return {"id": "abc12345678", "arquivo": "https://www.youtube.com/watch?v=abc12345678", "yt_duracao": duracao}


def _roteiro(monkeypatch, respostas, destino=None):
    """Troca o processo do yt-dlp por respostas combinadas. Guarda os comandos e o que cada cookie continha."""
    feitos = []

    def falso(comando, prazo):
        cookie = comando[comando.index("--cookies") + 1] if "--cookies" in comando else None
        feitos.append({"comando": comando, "cookie": cookie,
                       "conteudo": Path(cookie).read_text(encoding="utf-8") if cookie else None})
        codigo, erro = respostas.pop(0)
        if codigo == 0 and destino:
            Path(destino).write_bytes(b"mp4")
        return codigo, erro, "Canal Real\n" if codigo == 0 else ""

    monkeypatch.setattr(garimpo, "_rodar_com_prazo", falso)
    return feitos


def _contas(tmp_path, n):
    arquivos = []
    for i in range(n):
        arquivo = tmp_path / f"conta{i}.txt"
        arquivo.write_text(f"# conta {i}", encoding="utf-8")
        arquivos.append(arquivo)
    return arquivos


BOT = "ERROR: Sign in to confirm you are not a bot"


def test_trecho_pede_o_corte_e_devolve_onde_ele_caiu(tmp_path, monkeypatch):
    destino = tmp_path / "0001.mp4"
    feitos = _roteiro(monkeypatch, [(0, "")], destino)
    trecho = garimpo.baixar_trecho(_candidato(), destino)
    comando = feitos[0]["comando"]
    assert comando[comando.index("--download-sections") + 1] == f"*{trecho['inicio']:.1f}-{trecho['fim']:.1f}"
    assert "--force-keyframes-at-cuts" in comando
    assert trecho["fim"] - trecho["inicio"] == pytest.approx(garimpo.TRECHO)
    assert trecho["canal"] == "Canal Real"  # a busca nem sempre traz o canal, e o crédito precisa dele


def test_conta_reclamada_passa_para_a_seguinte(tmp_path, monkeypatch):
    a, b = _contas(tmp_path, 2)
    destino = tmp_path / "0001.mp4"
    feitos = _roteiro(monkeypatch, [(1, BOT), (0, "")], destino)
    garimpo.baixar_trecho(_candidato(), destino, {"cookies": [str(a), str(b)]})
    assert [f["conteudo"] for f in feitos] == ["# conta 0", "# conta 1"]
    assert garimpo._contas_livres([a, b]) == [b]


def test_tres_contas_sao_todas_tentadas_antes_de_ir_sem_conta(tmp_path, monkeypatch):
    contas = _contas(tmp_path, 3)
    destino = tmp_path / "0001.mp4"
    feitos = _roteiro(monkeypatch, [(1, BOT), (1, BOT), (1, BOT), (0, "")], destino)
    garimpo.baixar_trecho(_candidato(), destino, {"cookies": [str(c) for c in contas]})
    assert [f["conteudo"] for f in feitos] == ["# conta 0", "# conta 1", "# conta 2", None]


def test_cookie_original_nunca_vai_para_o_ytdlp(tmp_path, monkeypatch):
    (a,) = _contas(tmp_path, 1)
    destino = tmp_path / "0001.mp4"
    feitos = _roteiro(monkeypatch, [(0, "")], destino)
    garimpo.baixar_trecho(_candidato(), destino, {"cookies": [str(a)]})
    assert feitos[0]["cookie"] != str(a) and str(a) not in feitos[0]["comando"]


def test_erro_do_video_para_na_hora_e_nao_castiga(tmp_path, monkeypatch):
    a, b = _contas(tmp_path, 2)
    feitos = _roteiro(monkeypatch, [(1, "ERROR: Video unavailable")])
    with pytest.raises(garimpo.TrechoIndisponivel, match="Video unavailable"):
        garimpo.baixar_trecho(_candidato(), tmp_path / "0001.mp4", {"cookies": [str(a), str(b)]})
    assert len(feitos) == 1
    assert garimpo._contas_livres([a, b]) == [a, b]


def test_todas_as_tentativas_falhando_sai_como_trecho_indisponivel(tmp_path, monkeypatch):
    (a,) = _contas(tmp_path, 1)
    _roteiro(monkeypatch, [(1, BOT), (1, BOT)])
    with pytest.raises(garimpo.TrechoIndisponivel):
        garimpo.baixar_trecho(_candidato(), tmp_path / "0001.mp4", {"cookies": [str(a)]})


def test_arquivo_que_nao_apareceu_e_falha(tmp_path, monkeypatch):
    _roteiro(monkeypatch, [(0, "")])
    with pytest.raises(garimpo.TrechoIndisponivel):
        garimpo.baixar_trecho(_candidato(), tmp_path / "0001.mp4")


def test_prazo_mata_o_processo():
    with pytest.raises(garimpo.TrechoIndisponivel, match="passou de"):
        garimpo._rodar_com_prazo([sys.executable, "-c", "import time; time.sleep(30)"], 1)


# ---------------------------------------------------------------------------------------------------
# O freio no fluxo de verdade: midia._buscar_cenas, com o download trocado


def _preparar_fluxo(monkeypatch, tmp_path, cenas, config, trazer=None):
    from contextlib import nullcontext

    from fabrica import midia

    p = _ProjetoFalso(tmp_path, cenas)
    p.config = {"garimpo": config}
    p.offline, p.perfil, p.nome = True, {}, "teste"
    p.salvar_json = lambda *a: None
    garimpo._cotas.clear()

    def candidatos(_b, cena):
        return [{"fonte": "youtube", "id": f"yt{cena['n']}", "tipo": "video"},
                {"fonte": "pexels", "id": f"px{cena['n']}", "tipo": "video"}]

    def trazer_falso(_projeto, _cena, candidato, _http, _base):
        return {"fonte": candidato["fonte"], "id": candidato["id"], "tipo": "video", "arquivo": "x.mp4"}

    monkeypatch.setattr(midia, "_candidatos_da_cena", candidatos)
    monkeypatch.setattr(midia, "exigido_da_cena", lambda *a: set())
    monkeypatch.setattr(midia, "_so_do_assunto", lambda _c, lista, _log: lista)
    monkeypatch.setattr(midia, "_trazer_midia", trazer or trazer_falso)
    monkeypatch.setattr(midia, "nome_livre", lambda _p, n, _s: f"{n:04d}")
    monkeypatch.setattr(midia, "_guardando_o_que_havia", lambda _a: nullcontext())
    monkeypatch.setattr(midia, "_igual_no_lote", lambda *a: None)
    monkeypatch.setattr(midia, "escrever_creditos", lambda _p: None)
    monkeypatch.setattr(midia.tempos, "parte", lambda *a: nullcontext())
    buscador = types.SimpleNamespace(quantidade=12, blocos={}, nomes=(), http=None)
    return midia, p, {"cenas": p._cenas}, buscador


def _fontes(dados):
    return [(c.get("midia") or {}).get("fonte") for c in dados["cenas"]]


def test_teto_freia_no_fluxo_de_verdade(monkeypatch, tmp_path):
    """Todas as cenas têm trecho na frente da ordem. O teto é de 2 em 20: as outras 18 ficam com o banco."""
    midia, p, dados, buscador = _preparar_fluxo(monkeypatch, tmp_path, 20, {"alvo": 0.05, "teto": 0.1})
    ditas = []
    midia._buscar_cenas(p, dados, dados["cenas"], {"processos": 4}, buscador, ditas.append, False)
    fontes = _fontes(dados)
    assert fontes.count("youtube") == 2 and fontes.count("pexels") == 18
    assert any("fechado" in d for d in ditas)
    assert garimpo.cota(p).aceitos == 2


def test_orcamento_freia_no_fluxo_de_verdade(monkeypatch, tmp_path):
    midia, p, dados, buscador = _preparar_fluxo(monkeypatch, tmp_path, 20,
                                                {"alvo": 1, "teto": 1, "downloads_por_cena": 0.15})
    midia._buscar_cenas(p, dados, dados["cenas"], {"processos": 4}, buscador, print, False)
    assert _fontes(dados).count("youtube") == 3  # 15% de 20 downloads


def test_cota_desligada_deixa_tudo_passar(monkeypatch, tmp_path):
    midia, p, dados, buscador = _preparar_fluxo(monkeypatch, tmp_path, 10, {"cota": False})
    midia._buscar_cenas(p, dados, dados["cenas"], {"processos": 4}, buscador, print, False)
    assert _fontes(dados).count("youtube") == 10


def test_trecho_que_falha_nao_derruba_a_fase_de_midia(monkeypatch, tmp_path):
    def falha(_projeto, _cena, candidato, _http, _base):
        raise garimpo.TrechoIndisponivel("Video unavailable")

    midia, p, dados, buscador = _preparar_fluxo(monkeypatch, tmp_path, 4, {"teto": 1, "alvo": 1}, falha)
    midia._buscar_cenas(p, dados, dados["cenas"], {"processos": 2}, buscador, print, False)
    assert _fontes(dados) == [None] * 4
    assert all("youtube:" in (c.get("rejeitadas") or [""])[0] for c in dados["cenas"])  # a próxima rodada tenta outro
    c = garimpo.cota(p)
    assert (c.aceitos, c.em_voo, c.downloads) == (0, 0, 4)  # gasto, mas a vaga voltou


def test_cena_de_foto_so_ve_o_youtube_nos_canais_que_garimpam():
    from fabrica import midia

    b = midia.Buscador.__new__(midia.Buscador)
    b.projeto = types.SimpleNamespace(config={})
    b._buscar = lambda fonte, tipo, busca: [{"id": i} for i in range(9)]
    b.cfg = {"fontes_video": ["pexels"]}
    assert b._do_garimpo("mercado") == []
    b.cfg = {"fontes_video": ["pexels", "youtube"]}
    assert len(b._do_garimpo("mercado")) == midia.VAGAS_DO_GARIMPO_EM_FOTO
    b.projeto.config = {"garimpo": {"em_cenas_de_foto": False}}
    assert b._do_garimpo("mercado") == []


# ---------------------------------------------------------------------------------------------------
# O quadro real do trecho


def _conferencia(monkeypatch, tmp_path, legendas, nota=80, cfg=None):
    """Prepara midia._conferir_o_trecho com a descrição e o juiz trocados. `legendas` sai uma por descrição pedida."""
    from fabrica import corrigir, midia

    p = _ProjetoFalso(tmp_path, 10)
    p.config, p.perfil, p.offline = {"garimpo": cfg or {}}, {}, False
    fila = list(legendas)
    monkeypatch.setattr(midia, "_descrever_o_trecho", lambda *a: fila.pop(0) if fila else "")
    monkeypatch.setattr(corrigir, "_julgar_com_jev", lambda *a: {"nota": nota} if nota is not None else None)
    cortes = []
    monkeypatch.setattr(garimpo, "cortar_embaixo", lambda arquivo, capa: cortes.append(arquivo))
    registro = {"id": "abc", "arquivo": "midia/0001.mp4", "capa": "midia/0001_capa.jpg", "pagina": "p"}
    return midia, p, {"n": 1, "texto": "x"}, registro, cortes


LIMPO = "O que é: mercado. Texto visível: nenhum."
COM_LEGENDA = "O que é: mercado. Texto visível: legenda branca embaixo."
COM_MARCA = "O que é: mercado. Texto visível: marca d'água do canal."


def test_trecho_bom_fica_com_a_nota_e_a_descricao(monkeypatch, tmp_path):
    midia, p, cena, registro, cortes = _conferencia(monkeypatch, tmp_path, [LIMPO])
    midia._conferir_o_trecho(p, cena, registro)
    assert registro["trecho_conferido"] is True and registro["nota_do_trecho"] == 80
    assert registro["legenda"] == LIMPO and cortes == []


def test_nota_abaixo_do_minimo_derruba_o_trecho(monkeypatch, tmp_path):
    midia, p, cena, registro, _ = _conferencia(monkeypatch, tmp_path, [LIMPO], nota=garimpo.NOTA_MINIMA - 1)
    with pytest.raises(midia.TrechoReprovado):
        midia._conferir_o_trecho(p, cena, registro)


def test_legenda_embaixo_ganha_o_corte_e_fica_se_limpar(monkeypatch, tmp_path):
    midia, p, cena, registro, cortes = _conferencia(monkeypatch, tmp_path, [COM_LEGENDA, LIMPO])
    midia._conferir_o_trecho(p, cena, registro)
    assert len(cortes) == 1 and registro["trecho_conferido"] is True


def test_legenda_que_sobrevive_ao_corte_derruba_o_trecho(monkeypatch, tmp_path):
    midia, p, cena, registro, cortes = _conferencia(monkeypatch, tmp_path, [COM_LEGENDA, COM_LEGENDA])
    with pytest.raises(midia.TrechoReprovado):
        midia._conferir_o_trecho(p, cena, registro)
    assert len(cortes) == 1


def test_marca_dagua_nao_se_resolve_com_corte(monkeypatch, tmp_path):
    midia, p, cena, registro, cortes = _conferencia(monkeypatch, tmp_path, [COM_MARCA])
    with pytest.raises(midia.TrechoReprovado):
        midia._conferir_o_trecho(p, cena, registro)
    assert cortes == []


def test_modelo_de_visao_fora_nao_derruba_o_trecho(monkeypatch, tmp_path):
    midia, p, cena, registro, _ = _conferencia(monkeypatch, tmp_path, [])
    midia._conferir_o_trecho(p, cena, registro)
    assert registro["trecho_conferido"] is False


def test_juiz_fora_nao_derruba_o_trecho(monkeypatch, tmp_path):
    midia, p, cena, registro, _ = _conferencia(monkeypatch, tmp_path, [LIMPO], nota=None)
    midia._conferir_o_trecho(p, cena, registro)
    assert registro["trecho_conferido"] is False


def test_config_desliga_a_conferencia(monkeypatch, tmp_path):
    midia, p, cena, registro, _ = _conferencia(monkeypatch, tmp_path, [COM_MARCA], cfg={"conferir_trecho": False})
    midia._conferir_o_trecho(p, cena, registro)
    assert "trecho_conferido" not in registro


def test_trecho_reprovado_libera_a_vaga_e_tenta_o_proximo_candidato(monkeypatch, tmp_path):
    def trazer(_projeto, _cena, candidato, _http, _base):
        return {"fonte": candidato["fonte"], "id": candidato["id"], "tipo": "video", "arquivo": "x.mp4", "capa": "x.jpg"}

    midia, p, dados, buscador = _preparar_fluxo(monkeypatch, tmp_path, 3, {"teto": 1, "alvo": 1}, trazer)

    def reprova(*_a):
        raise midia.TrechoReprovado("nota baixa")

    monkeypatch.setattr(midia, "_conferir_o_trecho", reprova)
    midia._buscar_cenas(p, dados, dados["cenas"], {"processos": 2}, buscador, lambda _m: None, False)
    assert _fontes(dados) == ["pexels"] * 3
    c = garimpo.cota(p)
    assert (c.aceitos, c.em_voo, c.downloads) == (0, 0, 3)


def test_perfil_do_canal_vale_por_cima_do_config():
    projeto = types.SimpleNamespace(config={"garimpo": {"alvo": 0.1, "teto": 0.3}}, perfil={"garimpo": {"alvo": 0.5}})
    assert garimpo.cfg_do_projeto(projeto) == {"alvo": 0.5, "teto": 0.3}


def test_aviso_de_conta_unica(tmp_path):
    (a,) = _contas(tmp_path, 1)
    ditas = []
    garimpo.avisar_contas({"cookies": [str(a)]}, ditas.append)
    assert "UMA" in ditas[0]


def test_aviso_sem_conta(monkeypatch):
    monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
    ditas = []
    garimpo.avisar_contas({}, ditas.append)
    assert "sem conta" in ditas[0]


# ---------------------------------------------------------------------------------------------------
# O pedido do Radar e os itens da lista


def test_pedido_do_video_vale_por_cima_do_perfil():
    projeto = types.SimpleNamespace(config={"garimpo": {"alvo": 0.1}}, perfil={"garimpo": {"alvo": 0.2}},
                                    dados={"config_override": {"garimpo": {"alvo": 0.4, "ligado": True}}})
    assert garimpo.cfg_do_projeto(projeto) == {"alvo": 0.4, "ligado": True}


def test_pedido_liga_o_youtube_nas_fontes_de_video():
    ligado = types.SimpleNamespace(config={}, perfil={}, dados={"config_override": {"garimpo": {"ligado": True}}})
    assert garimpo.com_youtube(ligado, {})["fontes_video"] == ["pexels", "pixabay", "youtube"]
    assert garimpo.com_youtube(ligado, {"fontes_video": ["coverr"]})["fontes_video"] == ["coverr", "youtube"]
    assert garimpo.com_youtube(ligado, {"fontes_video": ["youtube"]})["fontes_video"] == ["youtube"]


def test_sem_pedido_o_perfil_fica_como_esta():
    desligado = types.SimpleNamespace(config={}, perfil={}, dados={})
    cfg = {"fontes_video": ["pexels"]}
    assert garimpo.com_youtube(desligado, cfg) is cfg


def _buscador_com_blocos():
    from fabrica import midia

    b = midia.Buscador.__new__(midia.Buscador)
    b.blocos = {"b1": {"id": "b1", "ancora": "FreshCo Canada"}, "b2": {"id": "b2", "ancora": "Costco Canada"},
                "b3": {"id": "b3", "ancora": "Walmart Canada"}}
    return b


@pytest.mark.parametrize("titulo, sai", [
    ("Costco opening day in Toronto", True),            # de outro item
    ("FreshCo vs Costco prices", False),                 # cita o item da cena: o juiz decide
    ("Canada grocery prices explained", False),          # palavra de vários blocos não decide
    ("Grocery store walk", False),                       # não cita item nenhum
])
def test_trecho_de_outro_item_sai_antes_de_baixar(titulo, sai):
    b = _buscador_com_blocos()
    assert b._de_outro_item({"fonte": "youtube", "descricao": titulo}, {"bloco": "b1"}) is sai


def test_filtro_de_item_nao_toca_nos_outros_bancos():
    b = _buscador_com_blocos()
    assert b._de_outro_item({"fonte": "pexels", "descricao": "Costco"}, {"bloco": "b1"}) is False


def test_busca_e_so_em_creative_commons_por_padrao():
    """A regra escrita em palhano/README.md: cortes do YouTube só em Creative Commons."""
    _YoutubeDLFalso.entradas = [_entrada()]
    (c,) = garimpo.buscar(None, "video", "grocery store")
    assert garimpo.FILTRO_CC in _YoutubeDLFalso.alvos[-1] and "grocery+store" in _YoutubeDLFalso.alvos[-1]
    assert "Creative Commons" in c["licenca"] and c["yt_cc"] is True


def test_config_abre_para_qualquer_video():
    _YoutubeDLFalso.entradas = [_entrada()]
    (c,) = garimpo.buscar(None, "video", "grocery store", {"so_creative_commons": False})
    assert _YoutubeDLFalso.alvos[-1].startswith("ytsearch")
    assert "Creative Commons" not in c["licenca"] and c["yt_cc"] is False


# ---------------------------------------------------------------------------------------------------
# Tier, vídeo em pé, provas e IP quente


@pytest.mark.parametrize("titulo, esperado", [
    ("Walmart Shopping Tour, 4k Walking Tour", 0),
    ("Grocery store b-roll footage", 0),
    ("Walmart Canada store opening", 1),
    ("Grocery prices explained by an economist", 2),
    ("Self Checkout Machine Sound Effects", 3),
    ("Funny grocery #shorts", 3),
])
def test_tier_pelo_titulo(titulo, esperado):
    assert garimpo.tier({"descricao": titulo}) == esperado


def test_busca_poe_filmagem_na_frente_e_tira_o_que_nao_e_imagem():
    _YoutubeDLFalso.entradas = [_entrada("a" * 11, titulo="Store review"), _entrada("b" * 11, titulo="Checkout sound effects"),
                                _entrada("c" * 11, titulo="Store walking tour")]
    assert [c["id"][0] for c in garimpo.buscar(None, "video", "store")] == ["c", "a"]


def test_ip_quente_para_a_busca_e_o_download(tmp_path, monkeypatch):
    from fabrica.midia import LimiteAtingido

    monkeypatch.setattr(garimpo, "IP_QUENTE", tmp_path / "ip.json")
    assert not garimpo.ip_quente()
    garimpo.marcar_ip_quente()
    assert garimpo.ip_quente()
    with pytest.raises(LimiteAtingido):
        garimpo.buscar(None, "video", "store")
    with pytest.raises(garimpo.TrechoIndisponivel, match="endereço"):
        garimpo.baixar_trecho(_candidato(), tmp_path / "x.mp4")


def test_bloqueio_sem_conta_marca_o_ip(tmp_path, monkeypatch):
    from fabrica.midia import LimiteAtingido

    monkeypatch.setattr(garimpo, "IP_QUENTE", tmp_path / "ip.json")
    monkeypatch.setattr(garimpo, "PASTA_DE_CONTAS", tmp_path / "nada")
    monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
    _YoutubeDLFalso.erro = RuntimeError("Sign in to confirm you are not a bot")
    with pytest.raises(LimiteAtingido):
        garimpo.buscar(None, "video", "store")
    assert garimpo.ip_quente()


def test_conta_conectada_pela_tela_entra_na_lista(tmp_path, monkeypatch):
    monkeypatch.setattr(garimpo, "PASTA_DE_CONTAS", tmp_path)
    monkeypatch.delenv("YOUTUBE_COOKIES", raising=False)
    (tmp_path / "conta-1.txt").write_text("# cookies", encoding="utf-8")
    assert garimpo.contas_de_cookies({}) == [tmp_path / "conta-1.txt"]


def test_prova_guarda_o_quadro_e_a_decisao(tmp_path):
    p = _ProjetoFalso(tmp_path, 1)
    (tmp_path / "capa.jpg").write_bytes(b"quadro")
    garimpo.guardar_prova(p, {"n": 7}, {"id": "abc", "capa": "capa.jpg", "pagina": "u"}, "reprovado", "nota baixa", 30)
    assert (tmp_path / "garimpo_provas" / "c0007_abc.jpg").read_bytes() == b"quadro"
    linha = json.loads((tmp_path / "garimpo_provas" / "decisoes.jsonl").read_text(encoding="utf-8"))
    assert linha["decisao"] == "reprovado" and linha["nota"] == 30


def test_video_em_pe_e_reprovado(monkeypatch, tmp_path):
    midia, p, cena, registro, _ = _conferencia(monkeypatch, tmp_path, [LIMPO])
    monkeypatch.setattr(garimpo, "em_pe", lambda _a: True)
    with pytest.raises(midia.TrechoReprovado, match="em pé"):
        midia._conferir_o_trecho(p, cena, registro)


def test_alternativas_param_no_limite_e_sobem_o_erro(monkeypatch):
    from fabrica import midia

    tentados = []

    def baixar(_p, _c, candidato, _h):
        tentados.append(candidato["id"])
        raise garimpo.TrechoIndisponivel("x")

    monkeypatch.setattr(midia, "_baixar_midia", baixar)
    projeto = types.SimpleNamespace(config={"garimpo": {"tentativas": 2}}, perfil={})
    with pytest.raises(garimpo.TrechoIndisponivel):
        midia._baixar_com_alternativas(projeto, {}, {"id": 1, "fonte": "youtube"}, [{"id": 2}, {"id": 3}], None)
    assert tentados == [1, 2]


def test_banco_comum_nao_tenta_alternativa(monkeypatch):
    from fabrica import midia

    tentados = []

    def baixar(_p, _c, candidato, _h):
        tentados.append(candidato["id"])
        raise OSError("caiu")

    monkeypatch.setattr(midia, "_baixar_midia", baixar)
    with pytest.raises(OSError):
        midia._baixar_com_alternativas(None, {}, {"id": 1, "fonte": "pexels"}, [{"id": 2}], None)
    assert tentados == [1]


# ---------------------------------------------------------------------------------------------------
# Contas conectadas pela tela

COOKIES = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalor\n"


def test_conta_salva_aparece_sem_os_cookies():
    assert garimpo.salvar_conta("Conta Um!", COOKIES) == "conta-um"
    dados = garimpo.listar_contas()
    assert dados["contas"] == [{"nome": "conta-um", "de_castigo": False}] and dados["ip_quente"] is False
    assert "valor" not in json.dumps(dados)


@pytest.mark.parametrize("texto", ["", "qualquer texto", "# só comentário\n", "site.com\tTRUE\t/\tTRUE\t0\tX\ty\n"])
def test_o_que_nao_e_cookie_do_youtube_e_recusado(texto):
    with pytest.raises(ValueError):
        garimpo.salvar_conta("conta", texto)


def test_nome_vazio_e_recusado():
    with pytest.raises(ValueError):
        garimpo.salvar_conta("!!!", COOKIES)


def test_conta_castigada_aparece_na_lista():
    garimpo.salvar_conta("a", COOKIES)
    garimpo.castigar(garimpo.PASTA_DE_CONTAS / "a.txt")
    assert garimpo.listar_contas()["contas"][0]["de_castigo"] is True


def test_apagar_conta():
    garimpo.salvar_conta("a", COOKIES)
    assert garimpo.apagar_conta("a") is True and garimpo.listar_contas()["contas"] == []
    assert garimpo.apagar_conta("a") is False


def test_testar_conta_diz_se_esta_logada(monkeypatch):
    garimpo.salvar_conta("a", COOKIES)
    monkeypatch.setattr(garimpo, "_rodar_com_prazo", lambda c, p: (0, "", ""))
    assert garimpo.testar_conta("a") == {"logada": True, "motivo": ""}
    monkeypatch.setattr(garimpo, "_rodar_com_prazo", lambda c, p: (1, "ERROR: login required", ""))
    assert garimpo.testar_conta("a") == {"logada": False, "motivo": "ERROR: login required"}


def test_testar_conta_que_nao_existe():
    with pytest.raises(ValueError):
        garimpo.testar_conta("nada")
