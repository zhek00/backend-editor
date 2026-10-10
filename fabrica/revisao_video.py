"""Revisão do vídeo pronto: o modelo principal (gratuito) olha o final.mp4 cena por cena antes de você publicar.

A conferência das cenas (corrigir.py) julga cada imagem sozinha, antes do render. Ninguém olhava o vídeo montado,
com legenda queimada, texto na tela e animação por cima. Aqui sai um quadro de cada cena do final.mp4, e o modelo,
vendo o quadro e a fala daquela cena, aponta o que está errado: tela preta, imagem que não combina com a fala, texto
cortado ou por cima da legenda, imagem repetida, marca-d'água, imagem borrada.

Só aponta, não troca nada: o resultado fica em revisao_video.json, e o editor marca as cenas com problema. Vale
para o final.mp4 de quando a revisão rodou: depois de um render novo, a revisão antiga deixa de valer.
"""
import json
from datetime import datetime

from .util import rodar

POR_CHAMADA = 8  # quadros por pedido ao modelo: com muitos ele começa a trocar uma cena pela outra
TIPOS = {
    "tela_preta": "tela preta ou quase preta",
    "nao_combina": "a imagem não mostra o que a fala diz",
    "texto_cortado": "texto na tela cortado ou saindo da tela",
    "texto_sobreposto": "texto na tela por cima da legenda ou de outro texto",
    "texto_errado": "texto na tela com erro, palavra estranha ou outro idioma",
    "repetida": "a mesma imagem de outra cena deste trecho",
    "marca_dagua": "logotipo, marca-d'água ou texto de banco de imagens",
    "baixa_qualidade": "imagem borrada, pixelada ou distorcida",
}

INSTRUCOES = """Você é o editor-chefe de um canal de documentários no YouTube e faz a revisão final antes de publicar.
Recebe um quadro de cada cena do vídeo já montado (com a legenda queimada embaixo, o texto na tela e as animações) e a
fala de cada cena. As imagens vêm na mesma ordem das cenas do pedido: conte com cuidado para não trocar uma pela outra.

Para cada cena, diga se ela está boa ou quais problemas tem. Problemas possíveis (use o código):
""" + "\n".join(f"- {k}: {v}" for k, v in TIPOS.items()) + """

Seja exigente com problemas reais e não invente problema: imagem que representa bem o assunto da fala está boa, mesmo
que não seja literal. A legenda embaixo é normal e não é problema. gravidade: "alta" (ninguém publicaria assim),
"media" (incomoda) ou "baixa" (detalhe). Em descricao, até 15 palavras, em português, dizendo o que se vê de errado.
"""

ESQUEMA = {
    "type": "object",
    "properties": {"cenas": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "n": {"type": "integer"},
            "problemas": {"type": "array", "items": {
                "type": "object",
                "properties": {"tipo": {"type": "string"}, "gravidade": {"type": "string"},
                               "descricao": {"type": "string"}},
                "required": ["tipo", "gravidade", "descricao"], "additionalProperties": False}},
        },
        "required": ["n", "problemas"], "additionalProperties": False}}},
    "required": ["cenas"],
    "additionalProperties": False,
}


def _atraso(projeto) -> float:
    try:
        return float(projeto.ler_json("render/linha.json").get("atraso", 0.0)) if projeto.existe("render/linha.json") else 0.0
    except (OSError, ValueError):
        return 0.0


def _assinatura_final(projeto) -> str:
    final = projeto.caminho("final.mp4")
    return f"{final.stat().st_mtime_ns}" if final.exists() else ""


def resultado(projeto):
    """A revisão guardada, se ela é do final.mp4 que está no projeto agora; senão None."""
    if not projeto.existe("revisao_video.json"):
        return None
    dados = projeto.ler_json("revisao_video.json")
    return dados if dados.get("final") == _assinatura_final(projeto) else None


def problemas_da_cena(projeto, n, revisao=None) -> list:
    revisao = revisao if revisao is not None else resultado(projeto)
    if not revisao:
        return []
    return (revisao.get("cenas") or {}).get(str(n), [])


def cenas_que_o_cliente_ainda_nao_viu(projeto, cenas) -> set:
    """Projeto do MCP: as cenas cuja imagem final o Claude do cliente ainda não viu.

    Ele já viu e julgou cada foto na escolha e na conferência; o que só nasce no render é a animação por cima, o clipe
    do Motion IA e a cena tapada sem ele aprovar. No mcp-cafe-5min a revisão olhou as 88 cenas (88 imagens, uns 39 mil
    tokens) e o que ela achou de novo estava nas cenas com animação (84 e 85); o resto repetia a conferência."""
    from . import animacoes

    debaixo = animacoes.cenas_cobertas(projeto, cenas)
    alvo = set()
    for c in cenas:
        captura, conferencia = c.get("captura") or {}, c.get("conferencia") or {}
        # a imagem de IA (sem midia) só nasce depois da escolha: o cliente nunca a viu. No ouro-serra-1min a cena 15
        # ficou de fora, e a revisão olhou 0 cenas
        if (not c.get("midia") or c["n"] in debaixo or (c.get("midia") or {}).get("fonte") in ("motion_ia", "animation_ai")
                or captura.get("suspeita")
                or captura.get("preenchida") or (conferencia and (conferencia.get("nota") or 0) < 40)
                or (c.get("midia") and not captura.get("conferida") and not conferencia)):
            alvo.add(c["n"])
    return alvo


def revisar(projeto, log=print, numeros=None) -> dict:
    """Revisa o final.mp4 e grava revisao_video.json. Devolve o resumo."""
    from . import cliente, openrouter_local

    final = projeto.caminho("final.mp4")
    if not final.exists():
        raise SystemExit(f"Ainda não há vídeo pronto. Rode uv run fabrica render {projeto.nome}")
    assinatura = _assinatura_final(projeto)
    todas = projeto.ler_json("cenas.json")["cenas"]
    if numeros is None and cliente.ativo(projeto):
        numeros = cenas_que_o_cliente_ainda_nao_viu(projeto, todas)
        log(f"  revisão só das {len(numeros)} cena(s) que o Claude do cliente ainda não viu prontas (animação, "
            "Motion IA, tapadas ou reprovadas); as outras ele já julgou")
    cenas = [c for c in todas if numeros is None or c["n"] in numeros]
    atraso = _atraso(projeto)
    pasta = projeto.caminho("revisao_video", "_").parent
    pasta.mkdir(parents=True, exist_ok=True)
    for velho in pasta.glob("*.jpg"):
        velho.unlink()
    log(f"  tirando um quadro de cada uma das {len(cenas)} cenas do vídeo pronto")
    quadros = {}
    for c in cenas:
        # o quadro sai de 60% da cena: o texto na tela e a animação já entraram, e o corte para a próxima está longe
        t = atraso + c["ini"] + (c["fim"] - c["ini"]) * 0.6
        destino = pasta / f"{c['n']:04d}.jpg"
        try:
            rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", final, "-frames:v", "1",
                   "-vf", "scale=768:-2", "-q:v", "4", destino])
            quadros[c["n"]] = destino
        except Exception:  # noqa: BLE001 - uma cena sem quadro só fica fora da revisão
            continue
    achados, revisadas = {}, 0
    lista = [c for c in cenas if c["n"] in quadros]
    from . import animacoes
    debaixo = animacoes.cenas_cobertas(projeto, cenas)
    for inicio in range(0, len(lista), POR_CHAMADA):
        lote = lista[inicio:inicio + POR_CHAMADA]
        linhas = []
        for c in lote:
            origem = "foto com animação por cima" if c["n"] in debaixo else (
                "vídeo real" if (c.get("midia") or {}).get("tipo") == "video" else "foto real" if c.get("midia") else "imagem de IA")
            linhas.append(f"Cena {c['n']} ({origem}) | fala: \"{c.get('texto', '')}\"")
        pedido = (f"Revise estas {len(lote)} cenas, na ordem das imagens. Devolva um item por cena, com o mesmo n.\n\n"
                  + "\n".join(linhas))
        try:
            resposta = openrouter_local.VISAO.perguntar(projeto, "revisão do vídeo", INSTRUCOES, pedido, ESQUEMA, log=log,
                                                  imagens=[quadros[c["n"]] for c in lote], temperatura=0)
        except (RuntimeError, SystemExit) as e:
            log(f"  não consegui revisar as cenas {lote[0]['n']} a {lote[-1]['n']} ({str(e)[:80]})")
            continue
        validos = {c["n"] for c in lote}
        for item in resposta.get("cenas", []):
            if item.get("n") not in validos:
                continue
            revisadas += 1
            problemas = [{"tipo": p.get("tipo") if p.get("tipo") in TIPOS else "outro",
                          "gravidade": p.get("gravidade") if p.get("gravidade") in ("alta", "media", "baixa") else "media",
                          "descricao": str(p.get("descricao") or "")[:160]}
                         for p in item.get("problemas") or [] if isinstance(p, dict)]
            if problemas:
                achados[str(item["n"])] = problemas
        if (inicio // POR_CHAMADA) % 5 == 4:
            log(f"  revisadas {min(inicio + POR_CHAMADA, len(lista))} de {len(lista)} cenas")
    graves = sorted(int(n) for n, ps in achados.items() if any(p["gravidade"] == "alta" for p in ps))
    dados = {"quando": datetime.now().isoformat(timespec="seconds"), "final": assinatura, "revisadas": revisadas,
             "cenas": achados, "graves": graves}
    projeto.salvar_json("revisao_video.json", dados)
    log(f"  revisão do vídeo: {revisadas} cena(s) olhadas, {len(achados)} com algum problema, {len(graves)} grave(s)"
        + (f": {', '.join(map(str, graves[:20]))}" if graves else ""))
    return dados


def ligada(projeto) -> bool:
    return bool((projeto.config.get("revisao_video") or {}).get("ativo", True)) and not projeto.offline
