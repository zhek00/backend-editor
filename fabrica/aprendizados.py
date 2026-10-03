"""O que a pessoa corrige no editor vira exemplo para o agente de roteiro dos próximos vídeos do mesmo canal.

Cada correção guarda o que o agente tinha pedido e o que a pessoa escolheu no lugar: a busca que ela digitou ("frosted
plant" no lugar de "campos de uva da Serra Gaúcha com geada"), a imagem que ela mesma subiu (o banco não tinha) e a
animação que ela trocou pela foto. Fica num arquivo por canal (o perfil), em aprendizados/, e as correções mais
recentes vão no pedido do agente como exemplos do que funciona naquele canal.

O texto usado num projeto fica congelado nele (aprendizados_usados.txt): retomar uma criação que caiu no meio não
muda o que o agente já decidiu, nem invalida o que ficou guardado.
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from .config import RAIZ

PASTA = RAIZ / "aprendizados"
LIMITE_GUARDADO = 300   # correções por canal; as mais antigas saem
EXEMPLOS_NO_PEDIDO = 15
_TRAVA = threading.Lock()


def canal(projeto) -> str:
    """O canal é o perfil do projeto: vídeos do mesmo perfil aprendem juntos."""
    perfil = str((getattr(projeto, "dados", {}) or {}).get("perfil") or "")
    return Path(perfil).stem or "geral"


def _arquivo(nome_canal) -> Path:
    return PASTA / f"{nome_canal}.json"


def _ler(nome_canal) -> list:
    arquivo = _arquivo(nome_canal)
    try:
        return json.loads(arquivo.read_text(encoding="utf-8")) if arquivo.exists() else []
    except (OSError, ValueError):
        return []


def registrar(projeto, cena, tipo, escolha="") -> None:
    """tipo: "busca" (a pessoa digitou outra busca), "upload" (subiu a própria imagem) ou "foto" (preferiu a foto
    à animação). Nunca atrapalha o editor: qualquer erro aqui é ignorado."""
    try:
        pedido = cena.get("pedido_original") or {}
        registro = {
            "quando": datetime.now().isoformat(timespec="seconds"),
            "projeto": projeto.nome,
            "cena": cena.get("n"),
            "tipo": tipo,
            "fala": (cena.get("texto") or "").strip()[:200],
            "visual": cena.get("visual") or "",
            "agente_buscou": (pedido.get("busca") if tipo == "busca" else cena.get("busca")) or "",
            "agente_pediu": ((pedido.get("mostrar") if tipo == "busca" else cena.get("mostrar")) or "")[:200],
            "escolha": (escolha or "")[:120],
        }
        from .openrouter_local import _sem_outro_alfabeto
        registro = _sem_outro_alfabeto(registro)  # pedidos antigos do agente vieram com pedaços de outro alfabeto
        nome = canal(projeto)
        with _TRAVA:
            dados = [r for r in _ler(nome) if not (r.get("projeto") == projeto.nome and r.get("cena") == cena.get("n")
                                                   and r.get("tipo") == tipo)]
            dados.append(registro)
            PASTA.mkdir(exist_ok=True)
            _arquivo(nome).write_text(json.dumps(dados[-LIMITE_GUARDADO:], ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001 - aprender é extra, nunca pode quebrar a troca da cena
        pass


def _linha(r) -> str:
    fala = f'Fala: "{r["fala"]}". '
    pedido = f'O agente pediu "{r["agente_pediu"]}" e buscou "{r["agente_buscou"]}". ' if r.get("agente_pediu") or \
        r.get("agente_buscou") else ""
    if r["tipo"] == "busca":
        return f'- {fala}{pedido}A pessoa trocou pela busca "{r["escolha"]}".'
    if r["tipo"] == "upload":
        return f"- {fala}{pedido}Os bancos não tinham uma imagem boa: a pessoa subiu a própria."
    if r["tipo"] == "foto":
        return f'- {fala}A cena era de {r.get("visual") or "animação"}, e a pessoa preferiu a foto à animação.'
    return ""


def _semear(projeto) -> None:
    """Na primeira vez de um canal, aproveita as buscas que a pessoa já tinha digitado nos projetos dele."""
    from .projeto import PROJETOS, Projeto

    nome = canal(projeto)
    if _arquivo(nome).exists() or not PROJETOS.exists():
        return
    for pasta in sorted(PROJETOS.iterdir()):
        try:
            dados = json.loads((pasta / "projeto.json").read_text(encoding="utf-8"))
            if Path(str(dados.get("perfil") or "")).stem != nome or pasta.name == projeto.nome:
                continue
            outro = Projeto(pasta.name)
            for c in outro.ler_json("cenas.json").get("cenas", []):
                if c.get("busca_manual"):
                    registrar(outro, c, "busca", c["busca_manual"])
        except (OSError, ValueError, KeyError, SystemExit):
            continue
    if not _arquivo(nome).exists():
        PASTA.mkdir(exist_ok=True)
        _arquivo(nome).write_text("[]", encoding="utf-8")


def texto_para_o_agente(projeto) -> str:
    """Os exemplos para o pedido do agente de roteiro, congelados no projeto na primeira vez."""
    usado = projeto.pasta / "aprendizados_usados.txt"
    if usado.exists():
        return usado.read_text(encoding="utf-8")
    try:
        _semear(projeto)
    except Exception:  # noqa: BLE001 - aprender é extra
        pass
    # busca digitada igual à do agente não ensina nada (a pessoa só pediu outra foto do mesmo assunto)
    uteis = [r for r in _ler(canal(projeto)) if r.get("projeto") != projeto.nome
             and not (r.get("tipo") == "busca" and (r.get("escolha") or "").strip().lower()
                      == (r.get("agente_buscou") or "").strip().lower())]
    recentes = uteis[-EXEMPLOS_NO_PEDIDO:]
    linhas = [l for l in (_linha(r) for r in recentes) if l]
    texto = ""
    if linhas:
        texto = ("Correções que a pessoa fez em vídeos anteriores deste canal. Use como exemplo do que funciona aqui: "
                 "buscas simples e concretas como as que ela escolheu, e nada de pedir o que ela teve de trocar.\n"
                 + "\n".join(linhas))
    try:
        usado.write_text(texto, encoding="utf-8")
    except OSError:
        pass
    return texto
