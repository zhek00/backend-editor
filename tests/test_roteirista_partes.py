import re
import threading
import time
from types import SimpleNamespace

from fabrica import aprendizados, roteirista


def test_bloco_grande_e_decidido_em_partes_ao_mesmo_tempo(tmp_path, monkeypatch):
    # everything-you-need-to-answer (2026-10-14): o bloco 10 tinha 65% do roteiro e andou sozinho, lote a lote, 1h20
    (tmp_path / "cenas_lotes").mkdir()
    m = {"blocos": [{"id": "1", "nome": "Co-op", "ancora": "Co-op counter", "inicio_c": 0},
                    {"id": "2", "nome": "Waitrose", "ancora": "Waitrose counter", "inicio_c": 100}]}
    unidades = [{"texto": f"frase {i}.", "c_ini": 0 if i < 2 else 100 + i, "ini": 3.0 * i, "fim": 3.0 * i + 3}
                for i in range(14)]
    cortes = [{"primeira_frase": i, "ultima_frase": i} for i in range(14)]
    projeto = SimpleNamespace(config={"roteirista": {"cenas_por_lote": 2, "paralelo": 8, "lotes_por_trecho": 2}},
                              perfil={}, nome="teste-partes", pasta=tmp_path,
                              caminho=lambda *partes: tmp_path.joinpath(*partes))
    monkeypatch.setattr(roteirista, "mapa", lambda p, log=print: m)
    monkeypatch.setattr(roteirista, "_mapa_para_o_modelo", lambda m: "mapa")
    monkeypatch.setattr(roteirista, "_perfil_do_nicho", lambda p: "perfil")
    monkeypatch.setattr(roteirista, "problemas_do_lote", lambda respostas, textos: [])
    monkeypatch.setattr(aprendizados, "texto_para_o_agente", lambda p: "")

    juntos, maximo, resumos, trava = [0], [0], {}, threading.Lock()

    class Modelo:
        def perguntar(self, projeto, etapa, instrucoes, pedido, esquema, log=print):
            de, ate = map(int, re.search(r"de (\d+) a (\d+)\):", pedido).groups())
            with trava:
                juntos[0] += 1
                maximo[0] = max(maximo[0], juntos[0])
                resumos[de] = pedido.split("ÚLTIMAS CENAS DO BLOCO ANTERIOR (para manter continuidade):\n")[1].split("\n\n")[0]
            time.sleep(0.2)
            with trava:
                juntos[0] -= 1
            return {"cenas": [{"cena": n, "descricao": f"cena {n}", "visual": "foto_real", "query": "chicken"}
                              for n in range(de, ate + 1)]}

    monkeypatch.setattr(roteirista, "_modelo_agente", lambda p: Modelo())
    grupos = roteirista.planejar_grupos(projeto, unidades, cortes, log=lambda *a: None)

    assert len(grupos) == 14 and all(g.get("busca") for g in grupos)
    # bloco 2: 12 cenas em 6 lotes de 2, em 3 partes de 2 lotes, mais a parte do bloco 1: 4 ao mesmo tempo
    assert maximo[0] == 4
    # as fronteiras dos lotes são as de sempre (os lotes guardados valem), e cada começo de parte tem o seu resumo
    assert sorted(resumos) == [1, 3, 5, 7, 9, 11, 13]
    assert resumos[1] == "(nenhuma, é o começo do vídeo)"
    assert resumos[3].startswith("(começo do bloco; o bloco anterior foi 1.")
    assert resumos[7].startswith("(meio do bloco 2;") and "frase 4. frase 5." in resumos[7]
    assert resumos[5].startswith("CENA 3: cena 3")  # dentro da parte, a continuidade de sempre


def test_esquema_do_groq_no_modo_estrito():
    # 2026-10-14: o gpt-oss recusava "invalid JSON schema" (additionalProperties:false em todo objeto) nas etapas
    # "prompts de IA em sequência" e "animation-ai: onde ajuda", e cada chamada perdia uma rota da cadeia
    from fabrica import animation_ai, groq_local, imagens

    formato = groq_local._formato_do_esquema(imagens.ESQUEMA_SEQUENCIA, True)
    assert formato["strict"] is True
    assert formato["schema"]["additionalProperties"] is False
    assert formato["schema"]["properties"]["cenas"]["items"]["additionalProperties"] is False
    assert "additionalProperties" not in imagens.ESQUEMA_SEQUENCIA  # o original fica como estava
    # o "dados" livre do animation-ai não cabe no modo estrito: vai sem ele
    assert groq_local._formato_do_esquema(animation_ai.ESQUEMA_UTIL, True)["strict"] is False
    # campo opcional também não cabe
    opcional = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a"]}
    assert groq_local._formato_do_esquema(opcional, True)["strict"] is False
    assert groq_local._formato_do_esquema(imagens.ESQUEMA_SEQUENCIA, False)["strict"] is False
