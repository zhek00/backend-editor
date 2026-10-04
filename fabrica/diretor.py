"""O diretor: lê o roteiro inteiro e revisa o vídeo cena por cena, a primeira ação do botão Corrigir Mídia.

O Jev julga cada imagem sozinha, com a fala da cena e um pouco de contexto. Ele não sabe o que existe em banco de
imagens nem enxerga o vídeo inteiro. O diretor sabe: recebe o roteiro completo, o mapa e, de cada cena, a fala, o que
o agente pediu, o mínimo aceitável, o que a imagem mostra de fato (a descrição de quem viu), as notas do Jev, de onde
a imagem veio e o que a revisão do vídeo pronto apontou. E decide, para as cenas que precisam mudar:
- "ia": a cena mostra outra coisa, ou o que ela pede nunca foi fotografado. Vai para a imagem de IA, obrigatoriamente;
- "arquivo": é de época e existe em arquivo (foto antiga, gravura, ilustração do livro da época). Busca na Wikimedia;
- "busca": existe em banco, só veio errada. Uma busca nova com o termo dele.
Cena que mostra o assunto certo, mesmo genérico, fica. Quem responde é o Claude da assinatura (sem custo além da
mensalidade), com o modelo principal de reserva. A decisão fica em diretor.json.
"""
import json
from datetime import datetime

INSTRUCOES = """Você é o diretor de um canal de documentários no YouTube e revisa o vídeo antes de publicar. Conhece o
roteiro inteiro. Recebe, de cada cena: a fala, o que o agente de roteiro pediu, o mínimo aceitável, onde a imagem
existe (banco, arquivo, nao_existe), a época, o que a imagem atual mostra de fato (descrita por quem a viu), as notas
do juiz (combina com a fala; mostra o sujeito certo) e de onde a imagem veio.

O PIOR ERRO é a cena mostrar OUTRA coisa: outro animal, outra pessoa com o mesmo nome, uma cidade, um carro, um objeto
sem relação com a fala. Toda cena assim precisa mudar.

Liste SÓ as cenas que precisam mudar, com uma decisão:
- "ia": a imagem mostra outra coisa e o que a fala pede não existe em foto de banco (um momento específico do passado,
  uma ação que ninguém fotografou, um conceito), ou já se tentou o banco e veio errado. Escreva em prompt a imagem que a
  cena precisa, em inglês, com sujeito, ação, cenário e época. Pessoa real: só de costas, de longe ou as mãos, sem o
  nome. Cena de época: fotografia daquela época.
- "arquivo": a cena é de época e o certo existe em arquivo (fotografia antiga, gravura, ilustração de livro ou jornal
  da época, objeto de museu). Escreva em busca, em inglês, o que procurar na Wikimedia (nome do lugar, da obra, do
  livro, com o ano).
- "busca": o certo existe em banco de imagens de hoje (um animal, uma paisagem, um objeto) e só veio errado. Escreva
  em busca, em inglês, 2 a 5 palavras do que a cena precisa.

NÃO liste a cena que mostra o assunto certo, ainda que genérica (um leão sem juba para os leões de Tsavo está certo).
Nota baixa do juiz contra um pedido impossível não é motivo para mudar: o que importa é se o sujeito está certo.
Em motivo, até 20 palavras em português dizendo o que está errado."""

ESQUEMA = {
    "type": "object",
    "properties": {"mudar": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "n": {"type": "integer"},
            "decisao": {"type": "string", "enum": ["ia", "arquivo", "busca"]},
            "motivo": {"type": "string"},
            "prompt": {"type": "string"},
            "busca": {"type": "string"},
        },
        "required": ["n", "decisao", "motivo", "prompt", "busca"],
        "additionalProperties": False}}},
    "required": ["mudar"],
    "additionalProperties": False,
}

POR_PEDIDO = 40  # cenas por pedido: o roteiro inteiro vai em todos, e a resposta lista só as que mudam


def _origem(cena) -> str:
    from .qualidade import _origem as origem
    return origem(cena)


def _linha(cena, apontamentos) -> str:
    conf = cena.get("conferencia") or {}
    partes = [f"CENA {cena['n']}", f"fala: \"{cena.get('texto', '')}\""]
    if cena.get("mostrar"):
        partes.append(f"pedido: {cena['mostrar']}")
    if cena.get("aceitavel"):
        partes.append(f"mínimo aceitável: {cena['aceitavel']}")
    if cena.get("onde_existe"):
        partes.append(f"onde existe: {cena['onde_existe']}")
    if cena.get("epoca"):
        partes.append(f"época: {cena['epoca']}")
    partes.append(f"imagem atual ({_origem(cena)}): {(conf.get('legenda') or (cena.get('midia') or {}).get('legenda') or 'sem descrição')[:400]}")
    notas = []
    if conf.get("nota") is not None:
        notas.append(f"combina {conf['nota']}%")
    if conf.get("sujeito") is not None:
        notas.append(f"sujeito certo {conf['sujeito']}%")
    if conf.get("epoca") is not None:
        notas.append(f"da época {conf['epoca']}%")
    if notas:
        partes.append("juiz: " + ", ".join(notas))
    if apontamentos:
        partes.append("revisão do vídeo pronto: " + "; ".join(f"{a.get('tipo')}: {a.get('descricao')}" for a in apontamentos))
    return " | ".join(partes)


def revisar(projeto, log=print) -> dict:
    """Pede ao diretor as cenas que precisam mudar e grava diretor.json. Não troca nada."""
    from . import revisao_video, roteirista
    from . import texto as tx

    cenas = [c for c in projeto.ler_json("cenas.json")["cenas"] if not c.get("personagem")]
    roteiro = tx.normalizar(projeto.roteiro())
    mapa = projeto.ler_json("roteiro_mapa.json") if projeto.existe("roteiro_mapa.json") else {}
    contexto = (f"ROTEIRO COMPLETO:\n{roteiro}\n\nMAPA DO VÍDEO:\n"
                f"{json.dumps({k: mapa.get(k) for k in ('blocos', 'pessoas_reais', 'quem_e')}, ensure_ascii=False)}\n\n")
    modelo = roteirista._modelo_agente(projeto)
    mudar = []
    for inicio in range(0, len(cenas), POR_PEDIDO):
        lote = cenas[inicio:inicio + POR_PEDIDO]
        linhas = "\n".join(_linha(c, revisao_video.problemas_da_cena(projeto, c["n"])) for c in lote)
        pedido = (contexto + f"CENAS {lote[0]['n']} A {lote[-1]['n']}:\n{linhas}\n\n"
                  "Liste só as cenas destas que precisam mudar.")
        try:
            resposta = modelo.perguntar(projeto, "diretor", INSTRUCOES, pedido, ESQUEMA, log=log)
        except (RuntimeError, SystemExit) as erro:
            log(f"  o diretor não revisou as cenas {lote[0]['n']} a {lote[-1]['n']} ({str(erro)[:120]})")
            continue
        validos = {c["n"] for c in lote}
        mudar += [m for m in resposta.get("mudar", []) if m.get("n") in validos]
        log(f"  diretor: cenas {lote[0]['n']} a {lote[-1]['n']} revisadas")
    resultado = {"quando": datetime.now().isoformat(timespec="seconds"), "mudar": sorted(mudar, key=lambda m: m["n"])}
    projeto.salvar_json("diretor.json", resultado)
    contagem = {d: sum(1 for m in mudar if m["decisao"] == d) for d in ("ia", "arquivo", "busca")}
    log(f"  o diretor pediu para mudar {len(mudar)} cena(s): {contagem['ia']} para IA, {contagem['arquivo']} para "
        f"arquivo de época e {contagem['busca']} para busca nova")
    return resultado


def custo(projeto, resultado) -> float:
    """O que as decisões custam: só as imagens de IA (as buscas são grátis)."""
    from .custos import preco_da_imagem
    return sum(1 for m in resultado["mudar"] if m["decisao"] == "ia") * preco_da_imagem(projeto) * 1.1


def aplicar(projeto, resultado, numeros=None, log=print) -> dict:
    """Executa as decisões. Primeiro as buscas (grátis); a cena que a busca não resolve vai para a IA, como as que
    o diretor já mandou para a IA. Devolve o resumo."""
    from . import corrigir, imagens, midia

    escolhidas = [m for m in resultado["mudar"] if numeros is None or m["n"] in numeros]
    para_ia = [{"cena": m["n"], "prompt": m.get("prompt", ""), "motivo": f"diretor: {m.get('motivo', '')}"}
               for m in escolhidas if m["decisao"] == "ia"]
    buscas = [m for m in escolhidas if m["decisao"] in ("arquivo", "busca") and (m.get("busca") or "").strip()]
    resolvidas_na_busca = []
    for m in buscas:
        try:
            imagens.refazer(projeto, [m["n"]], busca=m["busca"].strip(), tipo="foto_real", log=log)
        except (RuntimeError, SystemExit) as erro:
            log(f"  cena {m['n']}: a busca do diretor não achou nada ({str(erro)[:100]})")
            para_ia.append({"cena": m["n"], "prompt": m.get("prompt", ""), "motivo": f"diretor: {m.get('motivo', '')}"})
            continue
        resolvidas_na_busca.append(m["n"])
    if resolvidas_na_busca:
        # a imagem nova da busca é julgada; a que ainda mostra outra coisa vai para a IA
        avaliacoes = corrigir._avaliar(projeto, set(resolvidas_na_busca), log)
        corrigir._guardar(projeto, avaliacoes, rodada=0)
        para_ia += [{"cena": n, "prompt": "", "motivo": a["motivo"]} for n, a in avaliacoes.items() if corrigir.errada(a)]
    geradas = []
    if para_ia and midia.ia_ativa(projeto):
        geradas = corrigir.resolver_com_ia(projeto, para_ia, log)
    elif para_ia:
        log(f"  {len(para_ia)} cena(s) precisam de IA, mas ela está desligada (ia.ativa no config.yaml)")
    return {"buscas": resolvidas_na_busca, "ia": geradas, "sem_solucao": [i["cena"] for i in para_ia if i["cena"] not in geradas]}
