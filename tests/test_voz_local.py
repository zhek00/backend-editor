"""Voz open source no computador (fabrica/voz_local.py), no lugar das narrações pagas canceladas em 2026-10-28."""
import json

import pytest

from fabrica import narracao, voz_local


class _Projeto:
    offline = False

    def __init__(self, voz, config=None):
        self.perfil = {"voz": voz}
        self.config = config or {}


def test_genaipro_vira_voz_local():
    from fabrica.projeto import Projeto
    p = Projeto.__new__(Projeto)
    p.perfil, p.config = {"voz": {"provedor": "genaipro", "voice_id": "abc"}}, {}
    p.sem_narracao_paga()
    assert p.perfil["voz"]["provedor"] == "local"
    assert p.perfil["voz"]["pagas_trocadas"] and p.perfil["voz"]["provedor_pago"] == "genaipro"


def test_sem_provedor_era_genaipro_e_vira_local():
    from fabrica.projeto import Projeto
    p = Projeto.__new__(Projeto)
    p.perfil, p.config = {"voz": {"voice_id": "abc"}}, {}
    p.sem_narracao_paga()
    assert p.perfil["voz"]["provedor"] == "local"


def test_fish_e_computador_ficam():
    from fabrica.projeto import Projeto
    for provedor in ("fish", "computador"):
        p = Projeto.__new__(Projeto)
        p.perfil, p.config = {"voz": {"provedor": provedor}}, {}
        p.sem_narracao_paga()
        assert p.perfil["voz"]["provedor"] == provedor


def test_pagas_podem_continuar_se_o_config_pedir():
    from fabrica.projeto import Projeto
    p = Projeto.__new__(Projeto)
    p.perfil, p.config = {"voz": {"provedor": "genaipro"}}, {"voz_local": {"no_lugar_das_pagas": False}}
    p.sem_narracao_paga()
    assert p.perfil["voz"]["provedor"] == "genaipro"


def _bloco(tmp_path, voz):
    arq = tmp_path / "bloco_000.json"
    arq.write_text(json.dumps({"texto": "x", "voz": voz}), encoding="utf-8")
    return arq


def test_bloco_ja_pago_na_genaipro_continua_valendo(tmp_path):
    # projeto narrado na GenAIPro antes do cancelamento: não grava de novo com outra voz no meio do vídeo
    projeto = _Projeto({"provedor": "local", "pagas_trocadas": True})
    assinatura = narracao.assinatura_da_voz(projeto, projeto.perfil["voz"])
    arq = _bloco(tmp_path, {"provedor": "genaipro", "voice_id": "abc"})
    assert narracao._mesma_voz(projeto, arq, assinatura, 0, 1)


def test_mesma_voz_local_vale(tmp_path):
    projeto = _Projeto({"provedor": "local", "voz_local": "kokoro:pm_alex"})
    assinatura = narracao.assinatura_da_voz(projeto, projeto.perfil["voz"])
    arq = _bloco(tmp_path, assinatura)
    assert narracao._mesma_voz(projeto, arq, assinatura, 0, 1)


def test_outra_voz_local_grava_de_novo(tmp_path):
    projeto = _Projeto({"provedor": "local", "voz_local": "kokoro:pm_santa"})
    assinatura = narracao.assinatura_da_voz(projeto, projeto.perfil["voz"])
    arq = _bloco(tmp_path, {**assinatura, "voz": "kokoro:pm_alex"})
    assert not narracao._mesma_voz(projeto, arq, assinatura, 0, 1)


def test_casar_palavras_ouvidas_com_o_roteiro():
    ouvidas = [{"word": "A", "start": 0.0, "end": 0.1}, {"word": "história", "start": 0.1, "end": 0.6},
               {"word": "começa", "start": 0.6, "end": 1.0}, {"word": "em", "start": 1.0, "end": 1.1},
               {"word": "mil", "start": 1.1, "end": 1.4}]
    casadas = voz_local._casar("A história começa em 1875.", ouvidas)
    assert [p for p, _, _ in casadas] == ["A", "história", "começa", "em"]


def test_catalogo_tem_as_vozes_dos_dois_projetos(monkeypatch):
    monkeypatch.setattr(voz_local, "_galeria", lambda: [])
    ids = {v["id"] for v in voz_local.catalogo()}
    assert {"kokoro:pm_alex", "kokoro:pf_dora", "kokoro:af_heart", "qwen:Ryan", "qwen:Sohee"} <= ids
    assert "omnivoice:male, middle-aged, low pitch, british accent" in ids
    assert "omnivoice:child, low pitch" not in ids  # combinação implausível fica de fora, como no VoiceStudio


def test_resolver_cada_motor(monkeypatch):
    monkeypatch.setattr(voz_local, "_galeria", lambda: [
        {"id": "feat_01_the_documentarian", "type": "preset", "instruct": "male, middle-aged, low pitch"}])
    assert voz_local.resolver("kokoro:pm_alex") == ("kokoro", {"codigo": "pm_alex"})
    assert voz_local.resolver("qwen:Ryan") == ("qwen", {"codigo": "Ryan"})
    assert voz_local.resolver("qwen_design:voz grave e calma") == ("qwen_design", {"descricao": "voz grave e calma"})
    assert voz_local.resolver("omnivoice:feat_01_the_documentarian") == (
        "omnivoice", {"atributos": "male, middle-aged, low pitch"})
    assert voz_local.resolver("omnivoice:Female, Elderly") == ("omnivoice", {"atributos": "female, elderly"})


def test_voz_inexistente_e_erro_claro(monkeypatch):
    monkeypatch.setattr(voz_local, "_galeria", lambda: [])
    for codigo in ("kokoro:pm_ninguem", "qwen:Fulano", "qwen_design:", "omnivoice:voz linda", "elevenlabs:x"):
        with pytest.raises(voz_local.ErroVozLocal):
            voz_local.resolver(codigo)
