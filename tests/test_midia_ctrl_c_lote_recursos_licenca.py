"""midia.py: Ctrl+C que para de verdade, duplicata dentro do mesmo lote de downloads, recursos que se fecham e o cache de
buscas que sabe a licença configurada.

Antes: Ctrl+C era guardado como qualquer erro e a escolha seguia esperando todos os lotes; duas cenas do mesmo lote
podiam ficar com a mesma foto vinda de bancos diferentes; cada Buscador deixava um cliente HTTP aberto; os nomes do
roteiro ficavam guardados para sempre; e ligar uma licença da Wikimedia não trazia as fotos de volta."""
import gc
import pathlib
from concurrent.futures import Future

import pytest
from PIL import Image, ImageDraw

from fabrica import midia


# --- 5. Ctrl+C -----------------------------------------------------------------------------------------------------

def _pronto(valor=None, erro=None):
    futuro = Future()
    futuro.set_exception(erro) if erro else futuro.set_result(valor)
    return futuro


def test_erro_de_um_lote_nao_derruba_os_outros_e_volta_no_fim():
    aplicados = []
    erro = RuntimeError("cota esgotada")
    futuros = [_pronto("a"), _pronto(erro=erro), _pronto("c")]
    resultado = midia._aplicar_ao_terminar(futuros, aplicados.append)
    assert aplicados == ["a", "c"]  # o lote que falhou não impediu o seguinte
    assert resultado is erro


def test_ctrl_c_na_aplicacao_para_na_hora_e_cancela_os_lotes_que_faltam():
    pendente_1, pendente_2 = Future(), Future()
    chamadas = []

    def aplicar(valor):
        chamadas.append(valor)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        midia._aplicar_ao_terminar([_pronto("a"), pendente_1, pendente_2], aplicar)
    assert chamadas == ["a"]  # os lotes seguintes não foram aplicados
    assert pendente_1.cancelled() and pendente_2.cancelled()


def test_ctrl_c_enquanto_espera_um_lote_tambem_sobe_na_hora():
    aplicados = []
    futuros = [_pronto("a"), _pronto(erro=KeyboardInterrupt()), _pronto("c")]
    with pytest.raises(KeyboardInterrupt):
        midia._aplicar_ao_terminar(futuros, aplicados.append)
    assert aplicados == ["a"]
    assert futuros[2].cancelled() is False  # já tinha terminado: nada a cancelar


# --- 6. duplicata dentro do mesmo lote ------------------------------------------------------------------------------

class _Projeto:
    def __init__(self, pasta):
        self.pasta = pathlib.Path(pasta)

    def caminho(self, *partes):
        destino = self.pasta.joinpath(*partes)
        destino.parent.mkdir(parents=True, exist_ok=True)
        return destino


def _foto(pasta, nome, retangulos):
    destino = pasta / "midia" / nome
    destino.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (320, 180), (40, 60, 90))
    desenho = ImageDraw.Draw(im)
    for caixa, cor in retangulos:
        desenho.rectangle(caixa, fill=cor)
    im.save(destino)
    return f"midia/{nome}"


_FORMAS = [((20, 20, 120, 90), (230, 200, 40)), ((180, 60, 300, 160), (200, 30, 30)), ((10, 120, 90, 170), (240, 240, 240))]
_OUTRAS = [((200, 10, 310, 70), (230, 200, 40)), ((20, 90, 150, 170), (30, 200, 60)), ((130, 20, 170, 60), (10, 10, 10))]


def test_a_mesma_foto_de_dois_bancos_no_mesmo_lote_e_pega(tmp_path):
    projeto = _Projeto(tmp_path)
    pexels = {"fonte": "pexels", "id": "1", "arquivo": _foto(tmp_path, "0001.jpg", _FORMAS)}
    pexels["capa"] = pexels["arquivo"]
    pixabay = {"fonte": "pixabay", "id": "99", "arquivo": _foto(tmp_path, "0002.jpg", _FORMAS)}  # a mesma foto
    pixabay["capa"] = pixabay["arquivo"]
    outra = {"fonte": "wikimedia", "id": "7", "arquivo": _foto(tmp_path, "0003.jpg", _OUTRAS)}
    outra["capa"] = outra["arquivo"]
    vistas = {}
    assert midia._igual_no_lote(projeto, 1, pexels, vistas) is None
    assert midia._igual_no_lote(projeto, 2, pixabay, vistas) == 1  # mesma foto, outro banco, outro número
    assert midia._igual_no_lote(projeto, 3, outra, vistas) is None  # foto diferente passa
    assert set(vistas) == {1, 3}  # a repetida não entra no registro


def test_descartar_baixado_apaga_os_arquivos_e_rejeita_a_imagem(tmp_path):
    projeto = _Projeto(tmp_path)
    registro = {"fonte": "pixabay", "id": "99", "arquivo": _foto(tmp_path, "0002.jpg", _FORMAS)}
    registro["capa"] = registro["arquivo"]
    cena = {"n": 2}
    midia._descartar_baixado(projeto, cena, registro)
    assert not (tmp_path / "midia" / "0002.jpg").exists()
    assert cena["rejeitadas"] == ["pixabay:99"]


def test_imagem_sem_arquivo_para_comparar_nao_e_tratada_como_repetida(tmp_path):
    projeto = _Projeto(tmp_path)
    assert midia._igual_no_lote(projeto, 1, {"fonte": "x", "id": "1", "arquivo": "midia/nao-existe.jpg"}, {}) is None


# --- 7. recursos e nomes do roteiro ---------------------------------------------------------------------------------

class _ProjetoComRoteiro(_Projeto):
    perfil: dict = {}
    config: dict = {}
    offline = True

    def roteiro(self):
        return (self.pasta / "roteiro.txt").read_text(encoding="utf-8")

    def existe(self, nome):
        return (self.pasta / nome).exists()


def test_nomes_do_roteiro_acompanham_o_roteiro_editado(tmp_path):
    projeto = _ProjetoComRoteiro(tmp_path)
    (tmp_path / "roteiro.txt").write_text("A cidade de Pripyat foi evacuada.", encoding="utf-8")
    antes = midia.nomes_do_roteiro(projeto)
    assert "Pripyat" in antes
    assert midia.nomes_do_roteiro(projeto) is antes  # sem edição, vem do cache
    (tmp_path / "roteiro.txt").write_text("A cidade de Chernobyl foi abandonada depois.", encoding="utf-8")
    depois = midia.nomes_do_roteiro(projeto)
    assert "Chernobyl" in depois and "Pripyat" not in depois


def test_buscador_fecha_o_cliente_http(tmp_path):
    buscador = midia.Buscador(_ProjetoComRoteiro(tmp_path), lambda m: None)
    assert not buscador.http.is_closed
    buscador.fechar()
    assert buscador.http.is_closed
    buscador.fechar()  # segunda vez: nada acontece


def test_buscador_descartado_sem_fechar_tambem_fecha_o_cliente(tmp_path):
    buscador = midia.Buscador(_ProjetoComRoteiro(tmp_path), lambda m: None)
    cliente = buscador.http
    del buscador
    gc.collect()
    assert cliente.is_closed


# --- 8. licença no cache de buscas ----------------------------------------------------------------------------------

class _ProjetoComPerfil(_ProjetoComRoteiro):
    def __init__(self, pasta, midia_real):
        super().__init__(pasta)
        self.perfil = {"midia_real": midia_real}


def _buscador(tmp_path, midia_real):
    buscador = midia.Buscador(_ProjetoComPerfil(tmp_path, midia_real), lambda m: None)
    chamadas = []

    def wikimedia(tipo, busca):
        chamadas.append(busca)
        return [{"fonte": "wikimedia", "id": "1", "tipo": "foto", "miniatura": "m", "arquivo": "a"}]

    buscador._wikimedia = wikimedia
    return buscador, chamadas


def test_assinatura_da_licenca_so_aparece_fora_do_padrao(tmp_path):
    padrao, _ = _buscador(tmp_path, {})
    com_sa, _ = _buscador(tmp_path, {"aceitar_cc_by_sa": True})
    sem_by, _ = _buscador(tmp_path, {"aceitar_cc_by": False})
    assert padrao._assinatura_da_licenca("wikimedia") == ""  # caches que já existem continuam valendo
    assert com_sa._assinatura_da_licenca("wikimedia") != ""
    assert sem_by._assinatura_da_licenca("wikimedia_categoria") != ""
    assert com_sa._assinatura_da_licenca("wikimedia") != sem_by._assinatura_da_licenca("wikimedia")
    assert com_sa._assinatura_da_licenca("pexels") == ""  # banco que não filtra por licença não muda


def test_ligar_uma_licenca_busca_de_novo_em_vez_de_usar_o_cache_antigo(tmp_path):
    antes, chamadas_antes = _buscador(tmp_path, {})
    antes._buscar("wikimedia", "foto", "lince")
    antes._buscar("wikimedia", "foto", "lince")
    assert chamadas_antes == ["lince"]  # a segunda veio do cache

    depois, chamadas_depois = _buscador(tmp_path, {"aceitar_cc_by_sa": True})
    depois._buscar("wikimedia", "foto", "lince")
    assert chamadas_depois == ["lince"]  # outra licença, outra busca: não reaproveitou o cache sem as fotos cc-by-sa

    de_novo, chamadas_de_novo = _buscador(tmp_path, {})
    de_novo._buscar("wikimedia", "foto", "lince")
    assert chamadas_de_novo == []  # voltar ao padrão volta ao cache de antes


# --- ponta a ponta: o fluxo real do _buscar (modo offline, sem rede nem modelo) -----------------------------------

class _ProjetoCompleto(_ProjetoComRoteiro):
    nome = "e2e"

    def __init__(self, pasta, cenas):
        super().__init__(pasta)
        self._cenas = {"cenas": cenas}

    def ler_json(self, nome):
        import json
        return json.loads(json.dumps(self._cenas))  # cópia, como ler do disco

    def salvar_json(self, nome, dados):
        self._cenas = dados

    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.png"


def _cenas_e2e(n_cenas):
    return [{"n": n, "tipo": "foto_real", "busca": "lynx", "texto": f"cena {n}", "prompt": "p", "ini": 4.0 * n,
             "fim": 4.0 * n + 4, "sujeito": "lynx"} for n in range(1, n_cenas + 1)]


def _rodar_buscar(monkeypatch, tmp_path, fotos_por_cena):
    """fotos_por_cena: {n: formas} — a foto que o download de cada cena grava."""
    projeto = _ProjetoCompleto(tmp_path, _cenas_e2e(len(fotos_por_cena)))
    candidatos = {n: [{"fonte": f"banco{n}", "id": str(n), "tipo": "foto", "miniatura": "m", "arquivo": "a",
                       "descricao": "lynx"}] for n in fotos_por_cena}
    monkeypatch.setattr(midia.Buscador, "candidatos", lambda self, cena: list(candidatos[cena["n"]]))

    def baixar(proj, cena, candidato, http):
        arquivo = _foto(tmp_path, f"{cena['n']:04d}.jpg", fotos_por_cena[cena["n"]])
        return {"fonte": candidato["fonte"], "id": candidato["id"], "tipo": "foto", "arquivo": arquivo, "capa": arquivo}

    monkeypatch.setattr(midia, "_baixar_midia", baixar)
    avisos = []
    midia.buscar(projeto, log=avisos.append)
    return projeto._cenas["cenas"], avisos


def test_buscar_de_ponta_a_ponta_pega_a_mesma_foto_de_dois_bancos_no_mesmo_lote(monkeypatch, tmp_path):
    cenas, avisos = _rodar_buscar(monkeypatch, tmp_path, {1: _FORMAS, 2: _FORMAS, 3: _OUTRAS})
    com_midia = [c["n"] for c in cenas if c.get("midia")]
    assert len(com_midia) == 2 and 3 in com_midia  # a foto diferente fica; das duas iguais, só uma
    repetida = next(c for c in cenas if c["n"] in (1, 2) and not c.get("midia"))
    assert repetida["rejeitadas"] and repetida.get("sem_midia_real")  # sem mídia: a IA ou o tapa-buraco resolvem
    assert any("a mesma da cena" in a for a in avisos)
    assert not (tmp_path / "midia" / f"{repetida['n']:04d}.jpg").exists()  # o arquivo duplicado foi apagado


def test_buscar_de_ponta_a_ponta_com_fotos_diferentes_nao_recusa_nenhuma(monkeypatch, tmp_path):
    cenas, avisos = _rodar_buscar(monkeypatch, tmp_path, {1: _FORMAS, 2: _OUTRAS})
    assert all(c.get("midia") for c in cenas)
    assert not any("a mesma da cena" in a for a in avisos)
    assert (tmp_path / "creditos.txt").exists()  # o fim do fluxo (créditos) também rodou
