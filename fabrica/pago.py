"""Modelo de texto pago só com a confirmação da pessoa, depois que TODOS os gratuitos esgotaram.

Pedido do usuário em 2026-10-06: o saldo do OpenRouter caiu de US$ 6,10 para US$ 1,97 em dois dias, quase tudo no
Qwen Flash pago escolhendo fotos (US$ 2,59, 1.412 chamadas no nunca-deve-ter-dentro-de-casa-parte-2), porque a
cadeia passava para o pago sozinha quando os gratuitos estavam no limite. Agora a cadeia tenta todos os gratuitos
primeiro e, antes do primeiro pago, para e pergunta:

- pelo editor (servidor): a tarefa espera, sem gastar, e o editor mostra "As APIs gratuitas esgotaram" com o botão
  para liberar o pago (GET e POST /api/projetos/NOME/pago). Se um gratuito volta enquanto espera, a cadeia segue com
  ele e o aviso some;
- pelo terminal: pergunta [s/N]; sem terminal, para com GratisEsgotado (uv run fabrica pago NOME libera).

A liberação vale para o projeto até o fim do dia (pago_liberado.json): o limite dos gratuitos volta no dia seguinte.
Quem só existe pago e foi escolhido de propósito (o Jev, as imagens de IA) não passa por aqui: a cadeia sem nenhum
gratuito segue como antes.
"""
import json
import sys
import threading
import time
from datetime import date, datetime

ARQUIVO = "pago_liberado.json"
PASSO = 10  # de quanto em quanto tempo (s) a tarefa que espera confere a resposta
ESPERA_MINIMA = 60  # segundos esperando a pessoa antes de tentar os gratuitos de novo, quando nenhum diz quando volta

_TRAVA = threading.Lock()
_PEDIDOS: dict = {}  # nome do projeto -> pedido em aberto
responde_o_editor = False  # o servidor (api.py) liga: a pergunta vai para o editor em vez do terminal


class GratisEsgotado(BaseException):
    """Os gratuitos acabaram e ninguém liberou o pago. BaseException de propósito: os `except Exception` da fábrica
    (que seguem sem a etapa) não podem engolir isto e mandar a cena para o tapa-buraco ou para a imagem de IA."""


def confirmar(projeto) -> bool:
    return bool((projeto.config.get("openrouter") or {}).get("confirmar_pago", True))


def liberado(projeto) -> bool:
    arquivo = projeto.pasta / ARQUIVO
    try:
        return json.loads(arquivo.read_text(encoding="utf-8")).get("dia") == date.today().isoformat()
    except (OSError, ValueError):
        return False


def liberar(projeto) -> None:
    (projeto.pasta / ARQUIVO).write_text(json.dumps(
        {"dia": date.today().isoformat(), "quando": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    with _TRAVA:
        pedido = _PEDIDOS.pop(projeto.nome, None)
    if pedido:
        pedido["evento"].set()


def gratis_atendeu(projeto) -> None:
    """Um gratuito voltou a responder: o aviso do editor some."""
    if _PEDIDOS:
        with _TRAVA:
            _PEDIDOS.pop(getattr(projeto, "nome", None), None)


def pendente(nome) -> dict | None:
    """O que o editor mostra: etapa, modelo pago e quanto ele custou por chamada neste projeto."""
    with _TRAVA:
        pedido = _PEDIDOS.get(nome)
    if not pedido:
        return None
    return {k: pedido[k] for k in ("etapa", "modelo", "desde", "custo_por_chamada_usd", "gasto_pago_hoje_usd")}


def _medido(projeto, rota):
    """(média por chamada desse modelo neste projeto, gasto em modelo pago hoje), pelo uso_openrouter.json."""
    try:
        historico = json.loads((projeto.pasta / "uso_openrouter.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, 0.0
    custos = [h.get("custo_usd") or 0 for h in historico if h.get("modelo") == rota and (h.get("custo_usd") or 0) > 0]
    hoje = date.today().isoformat()
    gasto = sum(h.get("custo_usd") or 0 for h in historico if str(h.get("quando", "")).startswith(hoje))
    return (round(sum(custos) / len(custos), 5) if custos else None), round(gasto, 4)


def autorizar(projeto, rota, etapa, fora, log=print) -> bool:
    """Antes do primeiro modelo pago da cadeia. True: pode pagar. False: um gratuito voltou, tente a cadeia de novo.

    fora: {rota gratuita: segundo em que ela volta} das que estão de lado agora."""
    from . import cliente

    # projeto do MCP: a cadeia só chega aqui quando o Claude do cliente parou depois da metade do vídeo, e a reserva
    # paga é a regra combinada (cliente.Reserva); ninguém está no editor para confirmar
    if not confirmar(projeto) or liberado(projeto) or cliente.ativo(projeto):
        return True
    if not responde_o_editor:
        return _no_terminal(projeto, rota, etapa)
    nome = projeto.nome
    with _TRAVA:
        pedido = _PEDIDOS.get(nome)
        if pedido is None:
            por_chamada, gasto = _medido(projeto, rota)
            pedido = _PEDIDOS[nome] = {"etapa": etapa, "modelo": rota, "desde": datetime.now().isoformat(timespec="seconds"),
                                       "custo_por_chamada_usd": por_chamada, "gasto_pago_hoje_usd": gasto,
                                       "evento": threading.Event()}
            log(f"  as APIs gratuitas esgotaram ({etapa}): esperando a confirmação no editor para usar o {rota}, "
                f"sem gastar enquanto isso")
    inicio = time.time()
    volta = min(fora.values()) if fora else None
    while True:
        if pedido["evento"].wait(PASSO) or liberado(projeto):
            return True
        agora = time.time()
        # tenta os gratuitos de novo quando o primeiro que estava de lado volta, ou de minuto em minuto
        if (volta is not None and agora >= volta) or (volta is None and agora - inicio >= ESPERA_MINIMA):
            return False


def _no_terminal(projeto, rota, etapa) -> bool:
    por_chamada, gasto = _medido(projeto, rota)
    preco = f", uns US$ {por_chamada:.4f} por chamada" if por_chamada else ""
    texto = (f"As APIs gratuitas esgotaram na etapa {etapa}. Usar o {rota} (pago{preco}) neste projeto até o fim do "
             f"dia? Hoje já foram US$ {gasto:.2f} em modelo pago.")
    if not sys.stdin.isatty():
        raise GratisEsgotado(f"{texto}\nNada foi gasto. Para liberar: uv run fabrica pago {projeto.nome}, "
                             f"e rode o mesmo comando de novo (ele continua de onde parou).")
    with _TRAVA:
        if liberado(projeto):
            return True
        if input(f"{texto} [s/N] ").strip().lower() in ("s", "sim"):
            liberar(projeto)
            return True
    raise GratisEsgotado("Parado sem gastar. Rode o mesmo comando mais tarde: ele continua de onde parou.")
