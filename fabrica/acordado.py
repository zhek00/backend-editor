"""Não deixa o computador dormir enquanto a fábrica trabalha.

Pedido do usuário em 2026-10-13: na madrugada de 12 para 13/10 o Windows entrou em suspensão por falta de uso às
01:56 ("System Idle") e os dois vídeos que estavam sendo criados pelo site ficaram parados até as 11:43, quando alguém
acordou o computador. Com o computador dormindo nenhum programa roda: o jeito é avisar o sistema que há trabalho,
como faz um download ou um vídeo tocando. A tela pode apagar normalmente; só o sono fica segurado.

Uma linha própria confere de 20 em 20 s se há trabalho (`segurar` em volta do `tudo`, que também serve o robô e o
MCP, e os verificadores que o servidor registra para as tarefas do site) e avisa o sistema. Sem trabalho, o aviso sai
e o computador volta a dormir como antes. No Windows é o SetThreadExecutionState, que vale para a linha que chamou,
por isso uma linha só faz as chamadas; no Mac é o `caffeinate -i`. Nunca para a fábrica: qualquer falha é ignorada.
"""
from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
import time
from typing import Callable, List

INTERVALO = 20  # segundos entre as conferências

_TRAVA = threading.Lock()
_segurando = 0
_verificadores: List[Callable[[], bool]] = []
_linha: threading.Thread | None = None

# Windows: SetThreadExecutionState
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def _ocupado() -> bool:
    with _TRAVA:
        if _segurando > 0:
            return True
        verificadores = list(_verificadores)
    for ver in verificadores:
        try:
            if ver():
                return True
        except Exception:
            pass
    return False


def _laco() -> None:
    cafe = None  # processo do caffeinate no Mac
    acordado = False
    while True:
        try:
            ocupado = _ocupado()
            if ocupado != acordado:
                if sys.platform == "win32":
                    import ctypes
                    estado = _ES_CONTINUOUS | (_ES_SYSTEM_REQUIRED if ocupado else 0)
                    ctypes.windll.kernel32.SetThreadExecutionState(estado)
                elif sys.platform == "darwin":
                    if ocupado and cafe is None:
                        cafe = subprocess.Popen(["caffeinate", "-i"], stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL)
                    elif not ocupado and cafe is not None:
                        cafe.terminate()
                        cafe = None
                acordado = ocupado
        except Exception:
            pass
        time.sleep(INTERVALO)


def _ligar() -> None:
    global _linha
    with _TRAVA:
        if _linha is None:
            _linha = threading.Thread(target=_laco, daemon=True, name="acordado")
            _linha.start()


def vigiar(verificador: Callable[[], bool]) -> None:
    """Registra uma função que diz se há trabalho (o servidor passa as tarefas do site)."""
    with _TRAVA:
        _verificadores.append(verificador)
    _ligar()


@contextlib.contextmanager
def segurar():
    """Enquanto o bloco roda, o computador não dorme."""
    global _segurando
    with _TRAVA:
        _segurando += 1
    _ligar()
    try:
        yield
    finally:
        with _TRAVA:
            _segurando -= 1
