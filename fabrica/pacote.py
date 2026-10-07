"""Pacote do projeto: o que fica com o cliente depois do render, e volta para a fábrica quando ele quer editar.

Pedido do usuário em 2026-10-06 (teste do MCP): no servidor fica só o MP4 pronto; o projeto vai para o computador do
cliente. O vídeo de 30 min do nunca-deve-ter-dentro-de-casa-parte-2 ocupava 5,8 GB, quase tudo refeito de graça:

- vai no pacote o que custa dinheiro ou trabalho para refazer: os textos do projeto (roteiro, mapa, cenas, tempos da
  fala, créditos, notas do Jev e os caches em JSON que evitam pagar o modelo de novo), a narração paga (o .mp3 e o
  .json de cada bloco), as imagens de IA e as que a pessoa subiu, e as fotos e vídeos de banco USADOS nas cenas (o
  endereço do arquivo não é guardado, e o do Pixabay nem é permanente);
- fica de fora o que a fábrica refaz sem pagar: os clipes do render, a narração aberta em .wav (sai do .mp3), a trilha
  tocada (sai da partitura), os MOV das animações (saem do motion.json), as prévias do editor, as versões antigas, as
  folhas de candidatos e as fotos recusadas.

importar() remonta a pasta de trabalho e a narração sem gastar (narracao.narrar(sem_gastar=True)); a trilha e as
animações o próprio render refaz. entregar() é o fim da produção: o pacote vai para o cliente, o MP4 fica em
entregas/ e a pasta de trabalho sai do servidor.
"""
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import yaml

from .config import RAIZ, carregar_perfil
from .projeto import PROJETOS, Projeto

VERSAO = 1
MANIFESTO = "pacote.json"
ENTREGAS = RAIZ / "entregas"

# pastas inteiras que a fábrica refaz de graça (o render, as prévias, as cópias de segurança das trocas)
_PASTAS_FORA = {"render", "render_vertical", "_previas", "antigas", "conferir", "revisao_video"}
# nestas pastas só os JSON vão (a receita); o resto (MOV, HTML, WAV, fontes) sai da receita
_SO_JSON = {"animacoes", "trilha", "motion_ia", "cenas_lotes"}
# na raiz, o que sai do resto: o vídeo pronto (entregue à parte), a narração aberta, as legendas e a página de revisão
_RAIZ_FORA = {"final.mp4", "final_vertical.mp4", "narracao.wav", "narracao_editor.mp3", "revisao.html"}
_COMPRIMIDOS = {".jpg", ".jpeg", ".png", ".webp", ".mp3", ".mp4", ".webm", ".mov", ".zip"}


def _cenas(projeto) -> list:
    return projeto.ler_json("cenas.json").get("cenas", []) if projeto.existe("cenas.json") else []


def _midia_usada(projeto) -> set:
    """As fotos, vídeos e capas que as cenas usam agora, e as imagens de IA ou da pessoa de cada cena."""
    usados = set()
    for c in _cenas(projeto):
        m = c.get("midia") or {}
        for campo in ("arquivo", "capa"):
            if m.get(campo):
                usados.add(Path(m[campo]).as_posix())
        n = c.get("n")
        if isinstance(n, int):
            usados.update({f"imagens/{n:04d}.png", f"imagens/{n:04d}.json"})
    return usados


def _vai_no_pacote(relativo: Path, usados: set, blocos_com_mp3: set) -> bool:
    partes = relativo.parts
    nome = relativo.name
    if partes[0] in _PASTAS_FORA or nome.endswith((".tmp", ".baixando")):
        return False
    if len(partes) == 1:
        return nome not in _RAIZ_FORA and not nome.startswith(("cenas_backup_", "legendas"))
    if partes[0] in _SO_JSON:
        return relativo.suffix == ".json"
    if partes[0] == "narracao":
        # o .mp3 é o que a voz paga entregou; o _bruto.wav sai dele. Sem .mp3 (voz do computador), vai o bruto
        if nome.endswith("_bruto.wav"):
            return nome.replace("_bruto.wav", "") not in blocos_com_mp3
        return relativo.suffix != ".wav"
    if partes[0] in ("midia", "imagens"):
        # os JSON da mídia são caches de busca, de escolha e de descrição: pequenos, e evitam pagar o modelo de novo
        return relativo.suffix == ".json" or relativo.as_posix() in usados
    return True


def arquivos(projeto) -> list:
    """(caminho, nome dentro do pacote) de tudo que vai no pacote."""
    usados = _midia_usada(projeto)
    blocos_com_mp3 = {f.stem for f in (projeto.pasta / "narracao").glob("bloco_*.mp3")}
    saida = []
    for f in sorted(projeto.pasta.rglob("*")):
        if f.is_file():
            relativo = f.relative_to(projeto.pasta)
            if _vai_no_pacote(relativo, usados, blocos_com_mp3):
                saida.append((f, relativo.as_posix()))
    return saida


def medir(projeto) -> dict:
    """Quanto o pacote pesa e quanto fica de fora, sem escrever nada."""
    dentro = arquivos(projeto)
    total = sum(f.stat().st_size for f in projeto.pasta.rglob("*") if f.is_file())
    tamanho = sum(f.stat().st_size for f, _ in dentro)
    return {"arquivos": len(dentro), "tamanho_mb": round(tamanho / 1e6, 1), "projeto_mb": round(total / 1e6, 1),
            "fica_de_fora_mb": round((total - tamanho) / 1e6, 1)}


def _perfil_relativo(caminho: str) -> str:
    try:
        return Path(caminho).resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        return Path(caminho).name


def exportar(projeto, destino: Path, log=print) -> dict:
    """Escreve o pacote (.zip) em destino. O perfil do canal vai junto, já com a base aplicada, para o projeto abrir
    igual num servidor que não tem esse perfil (e a narração não ser gravada de novo por uma voz diferente)."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    dentro = arquivos(projeto)
    manifesto = {
        "versao": VERSAO,
        "nome": projeto.nome,
        "criado": datetime.now().isoformat(timespec="seconds"),
        "perfil": _perfil_relativo(projeto.dados["perfil"]),
        "refazer_de_graca": ["narração aberta (.wav)", "trilha", "animações", "clipes do render", "prévias"],
    }
    temporario = destino.with_name(destino.name + ".tmp")
    with zipfile.ZipFile(temporario, "w") as z:
        z.writestr(MANIFESTO, json.dumps(manifesto, ensure_ascii=False, indent=2))
        z.writestr("perfil.yaml", yaml.safe_dump(projeto.perfil, allow_unicode=True, sort_keys=False))
        for f, nome in dentro:
            modo = zipfile.ZIP_STORED if f.suffix.lower() in _COMPRIMIDOS else zipfile.ZIP_DEFLATED
            z.write(f, f"projeto/{nome}", compress_type=modo)
    with zipfile.ZipFile(temporario) as z:
        ruim = z.testzip()
    if ruim:
        temporario.unlink(missing_ok=True)
        raise RuntimeError(f"o pacote saiu com o arquivo {ruim} corrompido")
    temporario.replace(destino)
    resumo = {**medir(projeto), "pacote": str(destino), "pacote_mb": round(destino.stat().st_size / 1e6, 1)}
    log(f"  pacote de {projeto.nome}: {resumo['arquivos']} arquivos, {resumo['pacote_mb']} MB "
        f"(o projeto tinha {resumo['projeto_mb']} MB; {resumo['fica_de_fora_mb']} MB a fábrica refaz de graça)")
    return resumo


def importar(arquivo: Path, nome: str | None = None, substituir: bool = False, log=print) -> Projeto:
    """Remonta a pasta de trabalho a partir do pacote e refaz a narração aberta sem gastar.

    Se o servidor não tem o perfil do canal (ou ele mudou de lugar), vale o que veio no pacote."""
    with zipfile.ZipFile(arquivo) as z:
        manifesto = json.loads(z.read(MANIFESTO))
        if manifesto.get("versao", 0) > VERSAO:
            raise SystemExit(f"O pacote é de uma fábrica mais nova (versão {manifesto['versao']}). Atualize a fábrica.")
        nome = nome or manifesto["nome"]
        pasta = PROJETOS / nome
        if pasta.exists():
            if not substituir:
                raise SystemExit(f"Já existe um projeto chamado '{nome}' no servidor. Use outro nome ou --substituir.")
            shutil.rmtree(pasta)
        pasta.mkdir(parents=True)
        try:
            for item in z.infolist():
                if item.filename.startswith("projeto/") and not item.is_dir():
                    relativo = Path(item.filename[len("projeto/"):])
                    if relativo.is_absolute() or ".." in relativo.parts:
                        raise SystemExit(f"O pacote tem um caminho inválido: {item.filename}")
                    destino = pasta / relativo
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(item) as origem, open(destino, "wb") as saida:
                        shutil.copyfileobj(origem, saida)
            perfil_do_pacote = z.read("perfil.yaml").decode("utf-8")
        except BaseException:
            shutil.rmtree(pasta, ignore_errors=True)  # pacote ruim não deixa projeto pela metade no servidor
            raise
    dados = json.loads((pasta / "projeto.json").read_text(encoding="utf-8"))
    no_servidor = RAIZ / manifesto.get("perfil", "")
    if manifesto.get("perfil") and no_servidor.is_file():
        dados["perfil"] = str(no_servidor.resolve())
    else:
        (pasta / "perfil_do_pacote.yaml").write_text(perfil_do_pacote, encoding="utf-8")
        dados["perfil"] = str((pasta / "perfil_do_pacote.yaml").resolve())
        log(f"  o perfil {manifesto.get('perfil')} não existe neste servidor: vale o que veio no pacote")
    dados["nome"] = nome
    (pasta / "projeto.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    projeto = Projeto(nome)
    if projeto.existe("alinhamento.json"):
        from . import narracao
        narracao.narrar(projeto, log=log, sem_gastar=True)
        log("  narração remontada a partir dos blocos do pacote, sem gastar")
    log(f"  projeto {nome} pronto para editar e renderizar de novo")
    return projeto


def entregar(projeto, pasta_do_cliente: Path, log=print) -> dict:
    """Fim da produção: o pacote vai para o cliente, o MP4 fica em entregas/NOME e a pasta de trabalho sai do servidor.

    Só apaga depois de o pacote estar escrito e conferido (exportar testa o zip)."""
    final = projeto.pasta / "final.mp4"
    if not final.exists():
        raise SystemExit(f"{projeto.nome} ainda não tem o vídeo pronto. Renderize antes de entregar.")
    resumo = exportar(projeto, Path(pasta_do_cliente) / f"{projeto.nome}.zip", log)
    guardado = ENTREGAS / projeto.nome
    guardado.mkdir(parents=True, exist_ok=True)
    for nome in ("final.mp4", "final_vertical.mp4", "creditos.txt"):
        if (projeto.pasta / nome).exists():
            shutil.copy2(projeto.pasta / nome, guardado / nome)
    (guardado / "entrega.json").write_text(json.dumps({
        "entregue": datetime.now().isoformat(timespec="seconds"), "pacote": resumo["pacote"],
        "pacote_mb": resumo["pacote_mb"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(projeto.pasta)
    log(f"  entregue: o vídeo fica em entregas/{projeto.nome} e a pasta de trabalho ({resumo['projeto_mb']} MB) "
        f"saiu do servidor")
    return {**resumo, "video": str(guardado / "final.mp4")}
