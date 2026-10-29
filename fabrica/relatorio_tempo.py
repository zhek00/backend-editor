"""Onde foi o tempo da produção de um vídeo: etapas, IAs, esperas e trocas de modelo (fabrica tempos NOME).

Pedido do usuário em 2026-10-29: um vídeo de 30 min levou 4 h para sair e não dava para dizer qual IA segurou a
produção. Os dados já existiam, espalhados: tempos.json (cada etapa), uso_*.json (cada chamada de modelo que
respondeu, com os segundos) e, desde este pedido, chamadas.jsonl (cada chamada pela cadeia com as rotas que falharam e
as esperas paradas; cada imagem de IA; cada bloco de voz). Aqui eles viram um relatório só, em tempo_relatorio.md.

Chamadas correm ao mesmo tempo, então a soma dos segundos de um modelo passa do tempo de relógio. O que importa para o
gargalo é o tempo de relógio em que ele estava ocupado (a união dos intervalos de cada chamada): é o que a produção
esperou por ele, no máximo. Grátis e sem rede: só lê os arquivos do projeto.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from .tempos import CHAMADAS, duracao

ARQUIVO = "tempo_relatorio.md"
PAUSA_ENTRE_PRODUCOES = timedelta(hours=2)  # mais que isso sem etapa nenhuma: outra produção (ou a fábrica parada)
# arquivos de uso e como o nome do modelo aparece no relatório
USOS = {"uso_openrouter.json": "", "uso_groq.json": "groq:", "uso_gemini.json": "gemini:", "uso_jev.json": "jev:"}


def _data(texto):
    try:
        return datetime.fromisoformat(str(texto))
    except (TypeError, ValueError):
        return None


def _ler_json(arquivo):
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return dados if isinstance(dados, list) else []


def _ler_linhas(arquivo):
    linhas = []
    try:
        with open(arquivo, encoding="utf-8") as f:
            for texto in f:
                try:
                    linhas.append(json.loads(texto))
                except ValueError:
                    continue
    except OSError:
        pass
    return linhas


def etapas(pasta) -> list:
    """As linhas do tempos.json com começo e fim em datetime."""
    saida = []
    for linha in _ler_json(Path(pasta) / "tempos.json"):
        ini = _data(linha.get("inicio"))
        if ini:
            saida.append({**linha, "_ini": ini, "_fim": ini + timedelta(seconds=float(linha.get("segundos") or 0))})
    return sorted(saida, key=lambda x: x["_ini"])


def chamadas_de_modelo(pasta) -> list:
    """Cada chamada de modelo que respondeu (uso_*.json) e cada imagem e voz (chamadas.jsonl), com começo e fim.
    No uso_*.json o "quando" é o fim da chamada."""
    pasta = Path(pasta)
    saida = []
    for nome, prefixo in USOS.items():
        for r in _ler_json(pasta / nome):
            fim, s = _data(r.get("quando")), float(r.get("segundos") or 0)
            if fim and s > 0:
                saida.append({"modelo": prefixo + str(r.get("modelo") or "?"), "etapa": r.get("etapa") or "?",
                              "segundos": s, "_ini": fim - timedelta(seconds=s), "_fim": fim,
                              "custo": float(r.get("custo_usd") or 0)})
    for r in _ler_linhas(pasta / CHAMADAS):
        if r.get("tipo") in ("imagem", "voz"):
            ini, s = _data(r.get("inicio")), float(r.get("segundos") or 0)
            if ini and s > 0:
                saida.append({"modelo": f"{r['tipo']}: {r.get('modelo') or '?'}", "etapa": r.get("etapa") or "?",
                              "segundos": s, "_ini": ini, "_fim": ini + timedelta(seconds=s), "custo": 0.0,
                              "ok": r.get("ok", True)})
    return sorted(saida, key=lambda x: x["_ini"])


def chamadas_da_cadeia(pasta) -> list:
    saida = []
    for r in _ler_linhas(Path(pasta) / CHAMADAS):
        ini = _data(r.get("inicio"))
        if ini and r.get("tipo") in ("texto", "visão"):
            saida.append({**r, "_ini": ini, "_fim": ini + timedelta(seconds=float(r.get("segundos") or 0))})
    return saida


def janela_da_ultima_producao(lista_etapas, chamadas):
    """Começo e fim da última produção: a última sequência de etapas sem pausa de 2 h entre elas."""
    marcas = sorted([(e["_ini"], e["_fim"]) for e in lista_etapas] + [(c["_ini"], c["_fim"]) for c in chamadas])
    if not marcas:
        return None, None
    ate_aqui, maior = [], None  # o fim mais tarde até cada marca
    for _, f in marcas:
        maior = f if maior is None or f > maior else maior
        ate_aqui.append(maior)
    ini = marcas[0][0]
    for i in range(len(marcas) - 1, 0, -1):
        if marcas[i][0] - ate_aqui[i - 1] > PAUSA_ENTRE_PRODUCOES:
            ini = marcas[i][0]
            break
    return ini, ate_aqui[-1]


def uniao(intervalos, de=None, ate=None) -> float:
    """Segundos de relógio cobertos por pelo menos um intervalo (recortados em [de, ate])."""
    pedacos = []
    for a, b in intervalos:
        a, b = max(a, de) if de else a, min(b, ate) if ate else b
        if b > a:
            pedacos.append((a, b))
    total, fim = 0.0, None
    for a, b in sorted(pedacos):
        if fim is None or a > fim:
            total += (b - a).total_seconds()
            fim = b
        elif b > fim:
            total += (b - fim).total_seconds()
            fim = b
    return total


def _dentro(itens, de, ate):
    return [x for x in itens if x["_fim"] > de and x["_ini"] < ate]


def _por_modelo(chamadas, de=None, ate=None) -> list:
    """[(modelo, relógio ocupado, soma dos segundos, chamadas, maior chamada, custo)], do mais ocupado ao menos."""
    grupos = {}
    for c in chamadas:
        grupos.setdefault(c["modelo"], []).append(c)
    linhas = [(m, uniao([(c["_ini"], c["_fim"]) for c in cs], de, ate), sum(c["segundos"] for c in cs), len(cs),
               max(c["segundos"] for c in cs), sum(c["custo"] for c in cs)) for m, cs in grupos.items()]
    return sorted(linhas, key=lambda x: -x[1])


def _por_etapa_de_ia(chamadas, de=None, ate=None) -> list:
    grupos = {}
    for c in chamadas:
        grupos.setdefault(c["etapa"], []).append(c)
    linhas = []
    for etapa, cs in grupos.items():
        modelos = {}
        for c in cs:
            modelos[c["modelo"]] = modelos.get(c["modelo"], 0) + 1
        linhas.append((etapa, uniao([(c["_ini"], c["_fim"]) for c in cs], de, ate), sum(c["segundos"] for c in cs),
                       len(cs), sorted(modelos.items(), key=lambda x: -x[1])))
    return sorted(linhas, key=lambda x: -x[1])


def _cadeia(chamadas) -> dict:
    """Espera parada, tempo perdido em rotas que falharam e quantas chamadas caíram para o seguinte da cadeia."""
    esperas, perdidas, trocas, sem_resposta = {}, {}, 0, 0
    for c in chamadas:
        for nome, s in (c.get("esperas") or {}).items():
            t, n = esperas.get(nome, (0.0, 0))
            esperas[nome] = (t + float(s), n + 1)
        rotas = c.get("rotas") or []
        if len(rotas) > 1:
            trocas += 1
        if not c.get("ok"):
            sem_resposta += 1
        for r in rotas:
            if r.get("resultado") != "ok":
                motivo = (r.get("motivo") or "").split(":")[0][:60]
                chave = (r.get("rota") or "?", r.get("resultado") or "?")
                t, n, motivos = perdidas.get(chave, (0.0, 0, {}))
                motivos[motivo] = motivos.get(motivo, 0) + 1
                perdidas[chave] = (t + float(r.get("segundos") or 0), n + 1, motivos)
    return {"esperas": esperas, "perdidas": perdidas, "trocas": trocas, "sem_resposta": sem_resposta,
            "total": len(chamadas)}


def _pct(parte, todo):
    return f"{100 * parte / todo:.0f}%" if todo else "-"


def montar(pasta, desde=None, ate=None) -> str:
    """O relatório em texto (markdown simples). desde e ate: texto ISO; sem eles, a última produção."""
    pasta = Path(pasta)
    todas_etapas, modelos, cadeia = etapas(pasta), chamadas_de_modelo(pasta), chamadas_da_cadeia(pasta)
    if desde or ate:
        de = _data(desde) or datetime.min
        fim = _data(ate) or datetime.max
    else:
        de, fim = janela_da_ultima_producao(todas_etapas, modelos + cadeia)
    if de is None:
        return f"# Tempo da produção: {pasta.name}\n\nNenhuma medição neste projeto (tempos.json, uso_*.json ou {CHAMADAS})."
    lista_etapas = _dentro(todas_etapas, de, fim)
    modelos, cadeia = _dentro(modelos, de, fim), _dentro(cadeia, de, fim)
    ini_real = min([x["_ini"] for x in lista_etapas + modelos + cadeia] or [de])
    fim_real = max([x["_fim"] for x in lista_etapas + modelos + cadeia] or [fim])
    relogio = (fim_real - ini_real).total_seconds()
    ocupado_ia = uniao([(c["_ini"], c["_fim"]) for c in modelos], ini_real, fim_real)

    t = [f"# Tempo da produção: {pasta.name}", "",
         f"Janela: {ini_real:%d/%m %H:%M} a {fim_real:%d/%m %H:%M}, **{duracao(relogio)}** de relógio. "
         f"Alguma IA trabalhando em {duracao(ocupado_ia)} ({_pct(ocupado_ia, relogio)}); "
         f"o resto foi banco de imagens, download, FFmpeg, espera ou a fábrica parada.", ""]

    # 1. etapas
    t += ["## 1. Etapas (tempos.json)", ""]
    if not lista_etapas:
        t += ["Sem etapas medidas nesta janela (produção anterior à medição, ou feita fora da esteira).", ""]
    for e in sorted(lista_etapas, key=lambda x: -float(x.get("segundos") or 0)):
        if e["etapa"].startswith("Render:"):
            continue  # o "Render (total)" já conta os pedaços
        s = float(e.get("segundos") or 0)
        ia = uniao([(c["_ini"], c["_fim"]) for c in modelos], e["_ini"], e["_fim"])
        t.append(f"- **{e['etapa']}**: {duracao(s)} ({_pct(s, relogio)} da janela){'' if e.get('ok', True) else ' FALHOU'}"
                 f", começou {e['_ini']:%H:%M}; IA ocupada {duracao(ia)} ({_pct(ia, s)} da etapa)")
        dentro = _por_modelo(_dentro(modelos, e["_ini"], e["_fim"]), e["_ini"], e["_fim"])[:4]
        for m, oc, soma, n, maior, _ in dentro:
            if oc >= 1:
                t.append(f"  - {m}: ocupado {duracao(oc)} ({_pct(oc, s)}), {n} chamadas, média {soma / n:.1f}s, "
                         f"a maior {maior:.0f}s")
        partes = [(k, v) for k, v in (e.get("partes") or {}).items() if not k.startswith("modelo:")]
        if partes:
            t.append("  - partes (somadas, podem correr juntas): " + "; ".join(
                f"{k} {duracao(v[0])} ({v[1]}x)" for k, v in sorted(partes, key=lambda x: -x[1][0])[:5]))
    t.append("")

    # 2. modelos
    t += ["## 2. Quem ocupou o relógio (por IA)", "",
          "Relógio ocupado = tempo em que pelo menos uma chamada daquela IA estava aberta. "
          "Soma = segundos somados de todas as chamadas (passa do relógio quando correm juntas).", "",
          "| IA | relógio ocupado | % da janela | soma | chamadas | média | maior | custo |",
          "|---|---|---|---|---|---|---|---|"]
    for m, oc, soma, n, maior, custo in _por_modelo(modelos, ini_real, fim_real):
        t.append(f"| {m} | {duracao(oc)} | {_pct(oc, relogio)} | {duracao(soma)} | {n} | {soma / n:.1f}s | "
                 f"{maior:.0f}s | US$ {custo:.3f} |")
    t.append("")

    # 3. etapas de IA
    t += ["## 3. Por tarefa de IA", "",
          "| tarefa | relógio ocupado | soma | chamadas | média | IAs (chamadas) |", "|---|---|---|---|---|---|"]
    for etapa, oc, soma, n, mods in _por_etapa_de_ia(modelos, ini_real, fim_real)[:25]:
        t.append(f"| {etapa} | {duracao(oc)} | {duracao(soma)} | {n} | {soma / n:.1f}s | "
                 + ", ".join(f"{m} ({k})" for m, k in mods[:3]) + " |")
    t.append("")

    # 4. cadeia
    c = _cadeia(cadeia)
    t += ["## 4. Cadeia de modelos: esperas e trocas", ""]
    if not c["total"]:
        t += [f"Sem {CHAMADAS} nesta janela: a anotação das trocas e esperas começou em 2026-10-29.", ""]
    else:
        t.append(f"{c['total']} chamadas pela cadeia; {c['trocas']} ({_pct(c['trocas'], c['total'])}) passaram por "
                 f"mais de um modelo; {c['sem_resposta']} terminaram sem resposta.")
        for nome, (s, n) in sorted(c["esperas"].items(), key=lambda x: -x[1][0]):
            t.append(f"- espera parada {nome}: {duracao(s)} em {n} chamadas")
        if c["perdidas"]:
            t += ["", "Tempo perdido em rotas que não responderam:", "",
                  "| rota | resultado | vezes | tempo perdido | motivos |", "|---|---|---|---|---|"]
            for (rota, res), (s, n, motivos) in sorted(c["perdidas"].items(), key=lambda x: -x[1][0])[:15]:
                t.append(f"| {rota} | {res} | {n} | {duracao(s)} | "
                         + "; ".join(f"{m} ({k})" for m, k in sorted(motivos.items(), key=lambda x: -x[1])[:2]) + " |")
        t.append("")

    # 5. as mais lentas
    t += ["## 5. As 15 chamadas mais lentas", ""]
    for x in sorted(modelos + cadeia, key=lambda x: -float(x.get("segundos") or 0))[:15]:
        quem = x.get("modelo") or ", ".join(r.get("rota", "?") for r in x.get("rotas") or []) or "?"
        t.append(f"- {x['_ini']:%H:%M:%S} {x['etapa']}: {float(x['segundos']):.0f}s ({quem})")
    t.append("")

    # 6. buracos: trechos sem nenhuma IA trabalhando, com a etapa que estava aberta (ou nenhuma: a fábrica parada)
    t += ["## 6. Trechos de 2 min ou mais sem nenhuma IA trabalhando", ""]
    buracos, fim_ate_aqui = [], ini_real
    for a, b in sorted((c["_ini"], c["_fim"]) for c in modelos + cadeia):
        if (a - fim_ate_aqui).total_seconds() >= 120:
            buracos.append((fim_ate_aqui, a))
        fim_ate_aqui = max(fim_ate_aqui, b)
    if (fim_real - fim_ate_aqui).total_seconds() >= 120:
        buracos.append((fim_ate_aqui, fim_real))
    for a, b in sorted(buracos, key=lambda x: x[0] - x[1])[:12]:
        abertas = sorted({e["etapa"] for e in lista_etapas if e["_ini"] < b and e["_fim"] > a})
        t.append(f"- {a:%H:%M} a {b:%H:%M}, {duracao((b - a).total_seconds())}: "
                 + (", ".join(abertas) if abertas else "nenhuma etapa medida (fábrica parada ou etapa sem medição)"))
    if not buracos:
        t.append("Nenhum.")
    t.append("")

    # 7. conclusão
    t += ["## 7. Gargalo", ""]
    principais = [e for e in lista_etapas if not e["etapa"].startswith("Render:") and e["etapa"] != "Render (total)"]
    if principais:
        maior = max(principais, key=lambda e: float(e.get("segundos") or 0))
        s = float(maior.get("segundos") or 0)
        t.append(f"- Etapa mais longa: **{maior['etapa']}**, {duracao(s)} ({_pct(s, relogio)} da janela).")
        dentro = _por_modelo(_dentro(modelos, maior["_ini"], maior["_fim"]), maior["_ini"], maior["_fim"])
        if dentro and dentro[0][1] >= 1:
            m, oc, soma, n, _, _ = dentro[0]
            t.append(f"- Dentro dela, quem mais segurou: **{m}**, ocupado {duracao(oc)} ({_pct(oc, s)} da etapa), "
                     f"{n} chamadas de {soma / n:.1f}s em média.")
        livre = s - uniao([(c["_ini"], c["_fim"]) for c in modelos], maior["_ini"], maior["_fim"])
        if livre > 0.3 * s:
            t.append(f"- {duracao(livre)} dessa etapa ({_pct(livre, s)}) sem nenhuma IA trabalhando: banco de "
                     "imagens, download, FFmpeg ou espera (veja as partes na seção 1).")
    geral = _por_modelo(modelos, ini_real, fim_real)
    if geral:
        m, oc, *_ = geral[0]
        t.append(f"- Na produção toda, a IA mais ocupada foi **{m}**: {duracao(oc)} de relógio ({_pct(oc, relogio)}).")
    if c["total"]:
        espera = sum(s for s, _ in c["esperas"].values())
        perdido = sum(s for s, _, _ in c["perdidas"].values())
        if espera + perdido >= 60:
            t.append(f"- A cadeia perdeu {duracao(perdido)} em rotas que falharam e {duracao(espera)} parada "
                     "esperando (somados; podem correr juntos).")
    return "\n".join(t) + "\n"


def salvar(projeto, desde=None, ate=None) -> Path:
    pasta = Path(getattr(projeto, "pasta", projeto))
    destino = pasta / ARQUIVO
    destino.write_text(montar(pasta, desde, ate), encoding="utf-8")
    return destino
