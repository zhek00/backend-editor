"""corrigir: conjunto vazio não confere o vídeo inteiro e as cópias de backup são apagadas; jev_local: o uso_jev.json
é gravado inteiro ou nada, não é relido à toa e, corrompido, não derruba mais o julgamento."""
import json
import pathlib

from fabrica import corrigir, jev_local


class _Projeto:
    nome = "t"
    offline = True
    config: dict = {}
    perfil: dict = {}

    def __init__(self, pasta, cenas=None):
        self.pasta = pathlib.Path(pasta)
        self._cenas = {"cenas": cenas or []}

    def caminho(self, *partes):
        destino = self.pasta.joinpath(*partes)
        destino.parent.mkdir(parents=True, exist_ok=True)
        return destino

    def existe(self, nome):
        return nome == "cenas.json" or (self.pasta / nome).exists()

    def ler_json(self, nome):
        return json.loads(json.dumps(self._cenas))

    def salvar_json(self, nome, dados):
        self._cenas = json.loads(json.dumps(dados))

    def imagem(self, n):
        return self.pasta / "imagens" / f"{n:04d}.png"


# --- 5. conjunto vazio ---------------------------------------------------------------------------------------------

def test_conjunto_vazio_nao_confere_nenhuma_cena(tmp_path, monkeypatch):
    chamadas = []
    monkeypatch.setattr(corrigir, "_avaliar", lambda *a, **k: chamadas.append(a) or {})
    resumo = corrigir.corrigir(_Projeto(tmp_path, [{"n": 1, "tipo": "foto_real"}]), numeros=set(), log=lambda m: None)
    assert chamadas == []  # nada foi avaliado (antes: o vídeo inteiro)
    assert resumo["avaliadas"] == 0 and resumo["precisam_ia"] == []
    assert corrigir.formatar(resumo)  # o resumo vazio continua no formato que o terminal e o site mostram


def test_none_continua_sendo_todas_as_cenas(tmp_path, monkeypatch):
    alvos = []
    monkeypatch.setattr(corrigir, "_avaliar", lambda projeto, alvo, *a, **k: alvos.append(alvo) or {})
    corrigir.corrigir(_Projeto(tmp_path, []), numeros=None, so_avaliar=True, log=lambda m: None)
    assert alvos == [None]


# --- 7. cópias de backup -------------------------------------------------------------------------------------------

def _cena_com_foto(tmp_path, n):
    (tmp_path / "midia").mkdir(exist_ok=True)
    (tmp_path / "midia" / f"{n:04d}.jpg").write_bytes(b"foto")
    return {"n": n, "tipo": "foto_real", "texto": "t", "busca": "b", "prompt": "p",
            "midia": {"fonte": "f", "id": str(n), "arquivo": f"midia/{n:04d}.jpg"}}


def test_backup_some_quando_a_troca_termina(tmp_path, monkeypatch):
    projeto = _Projeto(tmp_path, [_cena_com_foto(tmp_path, 1)])
    ruim = {"legenda": "x", "veredito": "nao_combina", "nota": 5, "motivo": "m", "sujeito": 10, "busca_nova": "",
            "prompt_novo": ""}
    monkeypatch.setattr(corrigir, "_avaliar", lambda *a, **k: {1: dict(ruim)})
    monkeypatch.setattr(corrigir.midia, "buscar", lambda *a, **k: None)  # a busca nova não acha nada
    monkeypatch.setattr(corrigir.midia, "tirar_repetidas", lambda *a, **k: [])
    corrigir.corrigir(projeto, numeros={1}, rodadas=2, ia=False, log=lambda m: None)
    backup = tmp_path / "conferir" / "backup"
    assert backup.is_dir() and not list(backup.iterdir())  # a cópia foi feita e apagada depois de usada
    assert (tmp_path / "midia" / "0001.jpg").read_bytes() == b"foto"  # e a foto voltou para a cena


def test_backup_some_tambem_quando_o_corrigir_e_interrompido(tmp_path, monkeypatch):
    projeto = _Projeto(tmp_path, [_cena_com_foto(tmp_path, 1)])
    ruim = {"legenda": "x", "veredito": "nao_combina", "nota": 5, "motivo": "m", "sujeito": 10, "busca_nova": "",
            "prompt_novo": ""}
    monkeypatch.setattr(corrigir, "_avaliar", lambda *a, **k: {1: dict(ruim)})

    def busca_interrompida(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(corrigir.midia, "buscar", busca_interrompida)
    try:
        corrigir.corrigir(projeto, numeros={1}, rodadas=2, ia=False, log=lambda m: None)
    except KeyboardInterrupt:
        pass
    assert not list((tmp_path / "conferir" / "backup").iterdir())
    assert projeto.ler_json("cenas.json")["cenas"][0]["midia"]["arquivo"] == "midia/0001.jpg"  # devolvida antes


def test_apagar_backups_tolera_copia_que_ja_sumiu(tmp_path):
    copia = tmp_path / "x.jpg"
    copia.write_bytes(b"1")
    corrigir._apagar_backups({1: {"copias": [(copia, tmp_path / "o.jpg"), (tmp_path / "sumiu.jpg", tmp_path / "o2.jpg")]}})
    assert not copia.exists()


# --- 6. uso_jev.json -----------------------------------------------------------------------------------------------

def _registrar(projeto, monkeypatch, vezes=1):
    monkeypatch.setattr("fabrica.consumo.registrar", lambda *a, **k: None)
    for _ in range(vezes):
        jev_local._registrar(projeto, "julgar mídia", {"input_tokens": 10, "output_tokens": 0, "cost": 0.001}, "jev")


def test_registro_continua_sendo_uma_lista_json(tmp_path, monkeypatch):
    projeto = _Projeto(tmp_path)
    _registrar(projeto, monkeypatch, vezes=3)
    historico = json.loads((tmp_path / "uso_jev.json").read_text(encoding="utf-8"))
    assert isinstance(historico, list) and len(historico) == 3  # o formato que api, consumo e motion_ia leem
    assert jev_local.resumo_uso(projeto)["chamadas"] == 3
    assert not list(tmp_path.glob("*.tmp"))


def test_registro_corrompido_vai_para_o_lado_e_nao_derruba_o_julgamento(tmp_path, monkeypatch):
    projeto = _Projeto(tmp_path)
    (tmp_path / "uso_jev.json").write_text('[{"quando": "2026', encoding="utf-8")  # gravado pela metade
    assert jev_local.resumo_uso(projeto) is None  # o resumo não quebra
    _registrar(projeto, monkeypatch)  # antes: JSONDecodeError aqui, dentro de decidir
    assert len(json.loads((tmp_path / "uso_jev.json").read_text(encoding="utf-8"))) == 1
    guardados = list(tmp_path.glob("uso_jev.json.corrompido-*"))
    assert len(guardados) == 1 and guardados[0].read_text(encoding="utf-8") == '[{"quando": "2026'


def test_registro_relê_o_arquivo_quando_outro_processo_escreve(tmp_path, monkeypatch):
    projeto = _Projeto(tmp_path)
    _registrar(projeto, monkeypatch)
    # outro processo (o servidor e o terminal ao mesmo tempo) acrescentou duas linhas
    arquivo = tmp_path / "uso_jev.json"
    historico = json.loads(arquivo.read_text(encoding="utf-8"))
    arquivo.write_text(json.dumps(historico + [historico[0], historico[0]]), encoding="utf-8")
    _registrar(projeto, monkeypatch)
    assert len(json.loads(arquivo.read_text(encoding="utf-8"))) == 4  # as linhas do outro processo não se perderam
