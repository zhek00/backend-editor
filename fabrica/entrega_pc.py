"""Entrega no computador: quando o vídeo fica pronto, uma pasta por vídeo (por padrão em Downloads) com tudo o que
vai para o YouTube. Pedido do usuário em 2026-10-12, no modelo do que o Robô do Dotti entrega.

Pasta `Downloads/NOME DO CANAL/Título__nome-do-projeto_ENTREGA` (o canal é o nome do perfil) com o vídeo (o nome é o título), a versão em pé, `descricao.txt` (a descrição
pronta para colar), `publicacao.txt` (título, alternativas, tags, hashtags e comentário fixado), a thumbnail, a
legenda, os créditos e os shorts. Os vídeos entram por link físico (o mesmo arquivo do projeto com dois nomes, sem
ocupar espaço dobrado); fora do mesmo disco, são copiados. Rodar de novo atualiza a mesma pasta, mesmo que o título
tenha mudado. Seção `entrega_pc` do config.yaml (ou do config_override do projeto): `ativo` e `pasta`.

Desde 2026-10-20 (pedido do usuário), com `so_o_video: true` a pasta leva só o vídeo e a `descricao.txt`: o resto
(versão em pé, publicacao.txt, thumbnail, legenda, créditos, shorts) sai, inclusive de uma entrega antiga. O nome do
MP4 é o título exato, porque o YouTube usa o nome do arquivo como título ao subir: os caracteres que o Windows recusa
viram os parecidos (`?` vira `？`, `:` vira `꞉`). Antes de montar a pasta, `metadados.gravar` põe dentro dos MP4 o
título, a descrição, as tags e o canal; na entrega completa a thumbnail, a legenda e os shorts também levam o título
como nome (metadados.py)."""
import os
import re
import shutil
from pathlib import Path

SUFIXO = "_ENTREGA"


def config(projeto) -> dict:
    return {"ativo": True, "pasta": "", "so_o_video": True, **(projeto.config.get("entrega_pc") or {})}


# o que a entrega completa põe na pasta além do vídeo e da descrição; com so_o_video, sai de uma entrega antiga
EXTRAS = ("publicacao.txt", "thumbnail.jpg", "legenda.srt", "creditos.txt")

# caracteres que o Windows recusa em nome de arquivo, trocados por parecidos, para o título chegar inteiro ao YouTube
PARECIDOS = str.maketrans({"?": "？", ":": "꞉", '"': "＂", "/": "⁄", "\\": "⧵", "|": "ǀ", "<": "‹", ">": "›",
                           "*": "∗"})


def nome_do_titulo(titulo: str, limite: int = 100) -> str:
    """O título como nome do MP4, igual ao que aparece no YouTube (que corta em 100 letras)."""
    texto = re.sub(r"[\x00-\x1f]+", "", (titulo or "").translate(PARECIDOS))
    texto = re.sub(r"\s+", " ", texto)[:limite].strip()
    texto = re.sub(r"\.+$", lambda m: "․" * len(m.group()), texto)  # o Windows apaga o ponto do fim
    return texto or "video"


def pasta_base(projeto) -> Path:
    escolhida = str(config(projeto).get("pasta") or "").strip()
    return Path(escolhida).expanduser() if escolhida else Path.home() / "Downloads"


def _nome_seguro(texto: str, limite: int = 90) -> str:
    texto = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", texto or "").strip().rstrip(".")
    return re.sub(r"\s+", " ", texto)[:limite].strip() or "video"


def canal(projeto) -> str:
    """O nome do canal (o nome do perfil), que separa as entregas em Downloads/NOME DO CANAL. Pedido do usuário em
    2026-10-15. Vazio quando a separação está desligada."""
    if not config(projeto).get("separar_por_canal", True):
        return ""
    return _nome_seguro(str((getattr(projeto, "perfil", None) or {}).get("nome") or "Sem canal"), 60)


def _pasta_do_projeto(raiz: Path, base: Path, projeto, titulo: str) -> Path:
    """A pasta deste projeto, achada pelo nome do projeto no fim: se o título mudou, a pasta antiga ganha o novo nome.
    Uma pasta de antes da separação por canal (direto em Downloads) ou de outro canal vem para a do canal certo."""
    marca = f"__{projeto.nome}{SUFIXO}"
    desejada = base / f"{_nome_seguro(titulo, 70).replace(' ', '_')}{marca}"
    candidatas = list(base.glob(f"*{marca}")) + list(raiz.glob(f"*{marca}")) + list(raiz.glob(f"*/*{marca}"))
    for existente in dict.fromkeys(candidatas):
        if existente.is_dir():
            if existente != desejada and not desejada.exists():
                existente.rename(desejada)
                return desejada
            return existente
    desejada.mkdir(parents=True, exist_ok=True)
    return desejada


def _por(origem: Path, destino: Path) -> None:
    """Põe o arquivo na entrega: link físico quando dá (vídeo grande não ocupa espaço de novo), senão cópia."""
    if destino.exists():
        try:
            if os.path.samefile(origem, destino):
                return
        except OSError:
            pass
        destino.unlink()
    try:
        os.link(origem, destino)
    except OSError:
        shutil.copy2(origem, destino)


def _cabe(pasta: Path, nome: str) -> str:
    """O nome encurtado se o caminho passar do que o Windows aceita (260 letras), mantendo a extensão."""
    if len(str(pasta / nome)) <= 250:
        return nome
    raiz, extensao = os.path.splitext(nome)
    return raiz[:max(20, 250 - len(str(pasta)) - len(extensao) - 1)].strip() + extensao


def _texto_da_publicacao(dados: dict, titulo: str) -> str:
    linhas = [f"TÍTULO\n{titulo}"]
    alternativos = [t for t in [dados.get("titulo"), *(dados.get("titulos_alt") or [])] if t and t != titulo]
    if alternativos:
        linhas.append("TÍTULOS ALTERNATIVOS (teste A/B)\n" + "\n".join(alternativos))
    if dados.get("tags"):
        linhas.append("TAGS\n" + ", ".join(dados["tags"]))
    if dados.get("hashtags"):
        linhas.append("HASHTAGS\n" + " ".join(dados["hashtags"]))
    if dados.get("comentario_fixado"):
        linhas.append("COMENTÁRIO FIXADO\n" + dados["comentario_fixado"])
    linhas.append("CONTEÚDO ALTERADO OU SINTÉTICO (YouTube Studio)\n" +
                  ("Sim: o vídeo tem imagens de IA" if dados.get("sintetico") else "Não"))
    return "\n\n".join(linhas) + "\n"


def entregar(projeto, log=print) -> Path | None:
    """Monta ou atualiza a pasta de entrega. Devolve o caminho do vídeo entregue, ou None se desligada ou sem vídeo."""
    if not projeto.existe("final.mp4"):
        return None
    from . import metadados

    # título, descrição e tags dentro dos MP4 antes do link: o vídeo da pasta (e o que sobe ao YouTube) já sai com
    # eles. Vale também com a entrega desligada
    metadados.gravar(projeto, log=log)
    if not config(projeto).get("ativo", True):
        return None
    dados = projeto.ler_json("publicacao.json") if projeto.existe("publicacao.json") else {}
    titulo = metadados.titulo(projeto)  # o que a pessoa deu ao vídeo (titulo_entrega) vence o do kit
    raiz = pasta_base(projeto)
    base = raiz / canal(projeto) if canal(projeto) else raiz
    base.mkdir(parents=True, exist_ok=True)
    pasta = _pasta_do_projeto(raiz, base, projeto, titulo)
    so_o_video = bool(config(projeto).get("so_o_video", True))
    nome = nome_do_titulo(titulo)
    if len(str(pasta / nome)) > 250:  # o Windows recusa caminho de mais de 260 letras
        nome = nome[:max(20, 250 - len(str(pasta)) - 1)].strip()
        log(f"  aviso: título encurtado no nome do arquivo (caminho longo demais): {nome}")
    for antigo in pasta.glob("*.mp4"):  # vídeo com o título antigo sai; o novo entra abaixo
        if not antigo.name.startswith(nome) or (so_o_video and antigo.name != f"{nome}.mp4"):
            antigo.unlink()
    video = pasta / f"{nome}.mp4"
    _por(projeto.pasta / "final.mp4", video)
    if dados:
        (pasta / "descricao.txt").write_text(dados.get("descricao", "") + "\n", encoding="utf-8")
    # a thumbnail, a legenda e os shorts com o título como nome (metadados.nomes), nunca thumbnail.jpg ou S01.mp4
    nomes = {} if so_o_video else metadados.nomes(projeto, nome)
    principais = {a: n for a, n in nomes.items() if not a.startswith("shorts/")}
    curtos = {a: _cabe(pasta / "shorts", n) for a, n in nomes.items() if a.startswith("shorts/")}
    for velho in [*pasta.glob("*.jpg"), *pasta.glob("*.srt"), *pasta.glob("shorts/*.mp4")]:
        # thumbnail.jpg e legenda.srt de antes, o título antigo, o que saiu do vídeo; com so_o_video, todos
        if velho.name not in (principais.values() if velho.parent == pasta else curtos.values()):
            velho.unlink()
    if so_o_video:
        for extra in EXTRAS:
            (pasta / extra).unlink(missing_ok=True)
        if (pasta / "shorts").is_dir():
            shutil.rmtree(pasta / "shorts")
        projeto.salvar_json("entrega_pc.json", {"pasta": str(pasta), "video": str(video)})
        log(f"  entregue no computador: {pasta}")
        return video
    for arquivo in ("final_vertical.mp4", "thumbnail.jpg", "legendas_final.srt"):
        if arquivo in principais:
            _por(projeto.pasta / arquivo, pasta / principais[arquivo])
    if dados:
        (pasta / "publicacao.txt").write_text(_texto_da_publicacao(dados, titulo), encoding="utf-8")
    if projeto.existe("creditos.txt"):
        _por(projeto.pasta / "creditos.txt", pasta / "creditos.txt")
    if curtos:
        (pasta / "shorts").mkdir(exist_ok=True)
        for arquivo, nome_do_short in curtos.items():
            _por(projeto.pasta / arquivo, pasta / "shorts" / nome_do_short)
    elif (pasta / "shorts").is_dir() and not any((pasta / "shorts").iterdir()):
        (pasta / "shorts").rmdir()
    projeto.salvar_json("entrega_pc.json", {"pasta": str(pasta), "video": str(video)})
    log(f"  entregue no computador: {pasta}")
    return video
