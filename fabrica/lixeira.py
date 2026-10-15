"""Projeto excluído vai para a lixeira, não some.

Pedido do usuário em 2026-10-15 ("precisamos ser precisos na criação de vídeos, sem gasto à toa"): o × do editor apagava
a pasta inteira, e no everything-you-need-to-answer o projeto excluído e recriado pagou a produção inteira de novo
(214 imagens de IA, a escolha das fotos, a descrição e o Jev de 340 cenas). Agora a pasta vai para projetos/_lixeira e
volta com `fabrica restaurar NOME`, com tudo o que já foi pago. Fica DIAS dias e depois é apagada de verdade.

A lixeira não aparece em nenhuma lista: ela não tem projeto.json, e toda listagem de projetos exige um.
"""
import shutil
import time
from datetime import datetime
from pathlib import Path

from .projeto import PROJETOS

PASTA = PROJETOS / "_lixeira"
DIAS = 7
_SEPARADOR = "__"


def mandar(nome: str) -> Path:
    """Move projetos/NOME para a lixeira e devolve o destino. PermissionError: um arquivo ainda está em uso."""
    origem = PROJETOS / nome
    PASTA.mkdir(parents=True, exist_ok=True)
    destino = PASTA / f"{nome}{_SEPARADOR}{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    ultimo = None
    for _ in range(5):
        try:
            shutil.move(str(origem), str(destino))
            break
        except PermissionError as e:
            ultimo = e
            time.sleep(0.4)
    else:
        raise ultimo
    limpar()
    return destino


def listar() -> list:
    """(nome do projeto, quando foi para a lixeira, pasta), o mais recente primeiro."""
    if not PASTA.exists():
        return []
    itens = []
    for pasta in PASTA.iterdir():
        if pasta.is_dir() and _SEPARADOR in pasta.name:
            nome, carimbo = pasta.name.rsplit(_SEPARADOR, 1)
            try:
                quando = datetime.strptime(carimbo, "%Y%m%d-%H%M%S")
            except ValueError:
                continue
            itens.append((nome, quando, pasta))
    return sorted(itens, key=lambda i: i[1], reverse=True)


def restaurar(nome: str, como: str = None) -> Path:
    """Volta a versão mais recente de NOME da lixeira para projetos/ (como outro nome, se o nome já estiver em uso)."""
    candidatos = [i for i in listar() if i[0] == nome]
    if not candidatos:
        raise FileNotFoundError(f"'{nome}' não está na lixeira.")
    destino = PROJETOS / (como or nome)
    if destino.exists():
        raise FileExistsError(f"Já existe um projeto '{destino.name}'. Restaure com outro nome.")
    shutil.move(str(candidatos[0][2]), str(destino))
    return destino


def limpar(dias: int = DIAS) -> int:
    """Apaga de verdade o que está na lixeira há mais de DIAS dias. Devolve quantos."""
    agora = datetime.now()
    apagados = 0
    for _, quando, pasta in listar():
        if (agora - quando).days >= dias:
            shutil.rmtree(pasta, ignore_errors=True)
            apagados += 1
    return apagados
