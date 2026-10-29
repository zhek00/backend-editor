"""Relatório de tempo da produção (fabrica tempos NOME) e a anotação de cada chamada de IA (chamadas.jsonl).

Pedido do usuário em 2026-10-29: um vídeo de 30 min levou 4 h e não dava para saber qual IA era o gargalo. O
uso_*.json só guardava a rota que respondeu; o tempo perdido nas que falharam e a espera parada sumiam."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from fabrica import openrouter_local, relatorio_tempo, tempos

T0 = datetime(2026, 10, 29, 10, 0, 0)


def _iso(segundos):
    return (T0 + timedelta(seconds=segundos)).isoformat(timespec="seconds")


def test_uniao_conta_o_relogio_e_nao_a_soma():
    # duas chamadas de 10 s ao mesmo tempo ocupam 10 s de relógio, não 20
    a = [(T0, T0 + timedelta(seconds=10)), (T0 + timedelta(seconds=2), T0 + timedelta(seconds=10)),
         (T0 + timedelta(seconds=30), T0 + timedelta(seconds=35))]
    assert relatorio_tempo.uniao(a) == 15
    assert relatorio_tempo.uniao(a, de=T0 + timedelta(seconds=5), ate=T0 + timedelta(seconds=32)) == 7


def test_janela_e_a_ultima_producao_depois_de_uma_pausa_longa():
    antiga = {"_ini": T0, "_fim": T0 + timedelta(minutes=5)}
    nova = [{"_ini": T0 + timedelta(hours=5), "_fim": T0 + timedelta(hours=5, minutes=30)},
            {"_ini": T0 + timedelta(hours=5, minutes=40), "_fim": T0 + timedelta(hours=6)}]
    ini, fim = relatorio_tempo.janela_da_ultima_producao([antiga] + nova, [])
    assert ini == T0 + timedelta(hours=5) and fim == T0 + timedelta(hours=6)


def test_relatorio_aponta_a_ia_que_segurou_a_etapa(tmp_path):
    (tmp_path / "tempos.json").write_text(json.dumps([
        {"etapa": "Busca de acervo", "inicio": _iso(0), "segundos": 600, "ok": True,
         "partes": {"banco: pexels": [120.0, 30]}},
        {"etapa": "Trilha", "inicio": _iso(600), "segundos": 30, "ok": True}]), encoding="utf-8")
    # 20 escolhas de 25 s cada, uma depois da outra, no modelo lento; 20 do Jev de 1 s
    lento = [{"quando": _iso(25 * (i + 1)), "etapa": "escolha de material real", "modelo": "modelo/lento",
              "segundos": 25, "custo_usd": 0.001} for i in range(20)]
    jev = [{"quando": _iso(25 * (i + 1) + 1), "etapa": "julgar mídia", "modelo": "jev-1", "segundos": 1}
           for i in range(20)]
    (tmp_path / "uso_openrouter.json").write_text(json.dumps(lento), encoding="utf-8")
    (tmp_path / "uso_jev.json").write_text(json.dumps(jev), encoding="utf-8")
    linhas = [
        {"inicio": _iso(100) + ".000", "tipo": "texto", "etapa": "escolha de material real", "segundos": 40, "ok": True,
         "modelo": "modelo/lento", "esperas": {"pelo gratuito": 30},
         "rotas": [{"rota": "groq:qwen", "segundos": 5, "resultado": "não atende", "motivo": "cota do dia: x"},
                   {"rota": "modelo/lento", "segundos": 5, "resultado": "ok"}]},
        {"inicio": _iso(300) + ".000", "tipo": "imagem", "etapa": "imagem de IA", "segundos": 12, "ok": True,
         "modelo": "openai/gpt-5.4-image-2"}]
    (tmp_path / tempos.CHAMADAS).write_text("\n".join(json.dumps(x) for x in linhas) + "\n", encoding="utf-8")

    texto = relatorio_tempo.montar(tmp_path)
    gargalo = texto.split("## 7. Gargalo")[1]
    assert "Busca de acervo" in gargalo and "modelo/lento" in gargalo
    assert "| modelo/lento | 8min20s |" in texto  # 20 x 25 s seguidos
    assert "imagem: openai/gpt-5.4-image-2" in texto
    assert "espera parada pelo gratuito: 30s" in texto
    assert "| groq:qwen | não atende | 1 | 5s | cota do dia (1) |" in texto
    assert "banco: pexels 2min00s (30x)" in texto


def test_projeto_sem_medicao_nao_quebra(tmp_path):
    assert "Nenhuma medição" in relatorio_tempo.montar(tmp_path)


def test_cadeia_anota_a_rota_que_falhou_e_a_que_respondeu(tmp_path, monkeypatch):
    p = SimpleNamespace(nome="video", dados={}, pasta=tmp_path, config={"openrouter": {}})
    monkeypatch.setattr(openrouter_local, "_FORA_DO_AR", {})

    def rota(projeto, etapa, instrucoes, pedido, esquema, log, r, *a, **k):
        if r == "groq:a":
            raise openrouter_local.RotaIndisponivel("todas as chaves no limite do dia")
        return {"ok": 1}

    monkeypatch.setattr(openrouter_local, "uma_rota", rota)
    resposta = openrouter_local.perguntar(p, "trilha", "i", "p", {"type": "object"}, log=lambda *a: None,
                                          modelo="groq:a", cadeia_de=["groq:a", "groq:b"])
    assert resposta == {"ok": 1}
    linha = json.loads((tmp_path / tempos.CHAMADAS).read_text(encoding="utf-8").splitlines()[-1])
    assert linha["ok"] and linha["modelo"] == "groq:b" and linha["etapa"] == "trilha"
    assert [(r["rota"], r["resultado"]) for r in linha["rotas"]] == [("groq:a", "não atende"), ("groq:b", "ok")]
    assert "limite do dia" in linha["rotas"][0]["motivo"]


def test_anotar_sem_pasta_nunca_derruba():
    tempos.anotar_chamada(None, "texto", "x", 0)  # projeto dos testes, sem pasta
