"""Lixeira dos projetos: o × do editor move a pasta para projetos/_lixeira em vez de apagar.

Pedido do usuário em 2026-10-13: o vídeo "DON'T Buy Roast Chicken From These 6 UK Supermarkets" ficou pronto e foi
apagado sem querer pelo ×, logo depois de dois projetos de teste. O shutil.rmtree apagava de vez, sem passar pela
lixeira do Windows. A lixeira do Windows não serve: projeto grande (6 GB) passa do tamanho dela e o Windows apaga de vez
sem avisar. Mover dentro do mesmo disco é instantâneo.

Em 2026-10-15 a mesma ideia veio do GitHub ("precisamos ser precisos na criação de vídeos, sem gasto à toa"): no
everything-you-need-to-answer o projeto excluído e recriado pagou a produção inteira de novo (214 imagens de IA, a
escolha das fotos, a descrição e o Jev de 340 cenas). As duas versões foram juntadas aqui: `mover(pasta)` e
`mandar(nome)`, `limpar_antigos()` e `limpar()`, `fabrica lixeira --restaurar NOME` e `fabrica restaurar NOME [--como]`.
Os itens de `listar()` valem como tupla (nome, quando, pasta) e como dicionário (item["nome"], ["apagado"], ["pasta"]).

A lixeira não aparece em nenhuma lista: ela não tem projeto.json, e toda listagem de projetos exige um.
Fica `DIAS` dias e é apagada de vez depois disso.
"""
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from .projeto import PROJETOS

PASTA = PROJETOS / "_lixeira"
DIAS = 30
_SEPARADOR = "__apagado-"
# a versão do GitHub nomeava NOME__AAAAMMDD-HHMMSS; as duas são lidas
_SEPARADORES = (_SEPARADOR, "__")


class Item(tuple):
    """(nome, quando, pasta), que também responde por item["nome"], item["apagado"] e item["pasta"]."""
    _CHAVES = {"nome": 0, "apagado": 1, "quando": 1, "pasta": 2}

    def __getitem__(self, chave):
        if isinstance(chave, str):
            return tuple.__getitem__(self, self._CHAVES[chave])
        return tuple.__getitem__(self, chave)


def mover(pasta: Path, tentativas: int = 5) -> Path:
    """Move o projeto para a lixeira. Arquivo em uso (Windows) é tentado de novo algumas vezes."""
    pasta = Path(pasta)
    PASTA.mkdir(parents=True, exist_ok=True)
    destino = PASTA / f"{pasta.name}{_SEPARADOR}{datetime.now():%Y%m%d-%H%M%S}"
    for tentativa in range(tentativas):
        try:
            shutil.move(str(pasta), str(destino))
            return destino
        except PermissionError:
            if tentativa == tentativas - 1:
                raise
            time.sleep(0.4)
    return destino


def mandar(nome: str) -> Path:
    """Move projetos/NOME para a lixeira e devolve o destino. PermissionError: um arquivo ainda está em uso."""
    destino = mover(PROJETOS / nome)
    limpar()
    return destino


def _ler(pasta: Path):
    for separador in _SEPARADORES:
        if separador not in pasta.name:
            continue
        nome, carimbo = pasta.name.rsplit(separador, 1)
        try:
            return nome, datetime.strptime(carimbo, "%Y%m%d-%H%M%S")
        except ValueError:
            continue
    return None


def listar() -> list:
    """Itens (nome, quando, pasta) do mais recente para o mais antigo."""
    if not PASTA.exists():
        return []
    itens = []
    for pasta in PASTA.iterdir():
        lido = pasta.is_dir() and _ler(pasta)
        if lido:
            itens.append(Item((lido[0], lido[1], pasta)))
    return sorted(itens, key=lambda i: i[1], reverse=True)


def restaurar(nome: str, como: str = None) -> Path:
    """Devolve a cópia mais recente do projeto para projetos/ (como outro nome, se pedido). Recusa se já existir um
    projeto com o nome."""
    item = next((i for i in listar() if i[0] == nome), None)
    if not item:
        raise FileNotFoundError(f"'{nome}' não está na lixeira.")
    destino = PROJETOS / (como or nome)
    if (destino / "projeto.json").exists():
        raise FileExistsError(f"Já existe um projeto '{destino.name}'. Restaure com outro nome.")
    if destino.exists():
        # sobra de uma tarefa que escreveu depois de o projeto sair (só o uso_*.json; o consumo já está no
        # registro central, relatorios/openrouter_consumo.csv)
        shutil.rmtree(destino)
    shutil.move(str(item[2]), str(destino))
    return destino


def limpar_antigos(dias: int = None) -> int:
    """Apaga de vez o que está na lixeira há mais de `dias` dias (DIAS se não disser). Devolve quantos."""
    limite = datetime.now() - timedelta(days=DIAS if dias is None else dias)
    apagados = 0
    for item in listar():
        if item[1] < limite:
            shutil.rmtree(item[2], ignore_errors=True)
            apagados += 1
    return apagados


limpar = limpar_antigos
