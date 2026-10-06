"""A nota do vídeo: quanto das cenas mostra o que a narração fala.

Sem medida, toda mudança na fábrica é no olho. No virou-filme-em-1996, 139 de 155 cenas foram reprovadas pelo Jev,
86 delas mostravam outra coisa, e ninguém viu isso antes de abrir o vídeo. Aqui sai, de graça (só lê as notas que o
Jev já deu), um resumo gravado em qualidade.json no fim da criação, do Corrigir e do `fabrica status`.
"""
from collections import Counter
from datetime import datetime


def _origem(cena, projeto=None) -> str:
    """De onde veio a imagem da cena."""
    if cena.get("imagem_da_pessoa"):
        return "da pessoa"
    if (cena.get("midia") or {}).get("fonte") == "motion_ia":
        return "Motion IA"
    if not cena.get("midia") and (cena.get("tipo") == "ia" or (projeto is not None and projeto.imagem(cena["n"]).exists())):
        # a cena que perdeu a foto (repetida, reprovada) e ganhou imagem de IA continua com o tipo de foto: no
        # nunca-deve-ter-dentro-de-casa-parte-2 eram 63 "sem imagem" com 0 vazias
        return "IA"
    captura = cena.get("captura") or {}
    if captura.get("preenchida"):
        return "tapa-buraco"
    if cena.get("midia"):
        return "escolhida"
    return "sem imagem"


def _avaliacao(cena):
    """A nota que vale para a cena: a da conferência depois do download, ou a do Jev na captura, antes de baixar
    (a cena aprovada na captura não passa de novo pela conferência, e contava como "sem conferência")."""
    conf = cena.get("conferencia") or {}
    if conf.get("nota") is not None:
        return conf
    cap = cena.get("captura") or {}
    if cap.get("conferida") and cap.get("nota") is not None and not cap.get("motion_ia"):
        return {"nota": cap["nota"], "sujeito": cap.get("sujeito"), "epoca": cap.get("epoca")}
    return None


def calcular(projeto) -> dict:
    from . import corrigir

    cenas = projeto.ler_json("cenas.json")["cenas"] if projeto.existe("cenas.json") else []
    total = len(cenas)
    avaliacao = {c["n"]: _avaliacao(c) for c in cenas}
    conferidas = [c for c in cenas if avaliacao[c["n"]] is not None]
    boas = [c for c in conferidas if avaliacao[c["n"]]["nota"] >= corrigir.NOTA_MINIMA and not corrigir.errada(avaliacao[c["n"]])]
    erradas = [c["n"] for c in conferidas if corrigir.errada(avaliacao[c["n"]])]
    vazias = [c["n"] for c in cenas if not c.get("midia") and not projeto.imagem(c["n"]).exists()]
    ids = Counter(f"{c['midia'].get('fonte')}:{c['midia'].get('id')}" for c in cenas
                  if c.get("midia") and c["midia"].get("fonte"))
    repetidas = sorted(c["n"] for c in cenas if c.get("midia") and ids[f"{c['midia'].get('fonte')}:{c['midia'].get('id')}"] > 1)
    sem_conferencia = [c["n"] for c in cenas if c["n"] not in {x["n"] for x in conferidas}
                       and _origem(c, projeto) not in ("da pessoa", "Motion IA")]
    por_bloco = {}
    for c in cenas:
        b = por_bloco.setdefault(str(c.get("bloco") or "-"), {"cenas": 0, "boas": 0, "erradas": 0})
        b["cenas"] += 1
        conf = avaliacao[c["n"]] or {}
        if conf.get("nota") is not None:
            b["boas"] += int(conf["nota"] >= corrigir.NOTA_MINIMA and not corrigir.errada(conf))
            b["erradas"] += int(corrigir.errada(conf))
    return {
        "quando": datetime.now().isoformat(timespec="seconds"),
        "cenas": total,
        "boas_pct": round(100 * len(boas) / total) if total else 0,
        "boas": len(boas),
        "erradas": erradas,
        "sem_conferencia": sem_conferencia,
        "vazias": vazias,
        "repetidas": repetidas,
        "origem": dict(Counter(_origem(c, projeto) for c in cenas)),
        "por_bloco": por_bloco,
    }


def registrar(projeto, momento, log=print) -> dict:
    """Calcula, grava em qualidade.json (o histórico fica, um item por momento) e escreve o resumo no log."""
    resumo = {**calcular(projeto), "momento": momento}
    historico = projeto.ler_json("qualidade.json").get("historico", []) if projeto.existe("qualidade.json") else []
    projeto.salvar_json("qualidade.json", {"atual": resumo, "historico": (historico + [resumo])[-30:]})
    log("  " + formatar(resumo))
    return resumo


def formatar(r) -> str:
    origem = ", ".join(f"{v} {k}" for k, v in sorted(r["origem"].items(), key=lambda x: -x[1]))
    partes = [f"Qualidade: {r['boas_pct']}% das {r['cenas']} cenas mostram o que a fala diz"]
    partes.append(f"{len(r['erradas'])} mostram outra coisa" + (f" ({', '.join(map(str, r['erradas'][:15]))})" if r["erradas"] else ""))
    if r["sem_conferencia"]:
        partes.append(f"{len(r['sem_conferencia'])} sem conferência")
    if r["vazias"]:
        partes.append(f"{len(r['vazias'])} sem imagem")
    if r["repetidas"]:
        partes.append(f"{len(r['repetidas'])} com imagem repetida")
    return "; ".join(partes) + f". Origem: {origem}."
