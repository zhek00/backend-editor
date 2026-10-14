"""A limpeza da produção em massa (PLANO-VPS.md): nada fica mais de 3 dias.

- Logo depois da entrega: os arquivos de trabalho do projeto (render, mídia baixada, imagens, animações, prévias,
  narração) saem do disco; ficam só os JSON pequenos de diagnóstico (cenas, tempos, custos, uso dos modelos).
- 3 dias depois de terminar (pronto, erro ou cancelado): a pasta do projeto inteira, o vídeo no R2 e os eventos saem;
  a linha do vídeo fica no banco como `expirado`, sem o roteiro e sem o link (para a contagem e a cobrança).
O trabalhador roda a limpeza dos expirados a cada hora; `fabrica limpar-expirados` roda na mão.
"""
import shutil

from . import armazenamento, fila
from .projeto import PROJETOS

# o que fica na pasta depois da entrega, até expirar: só o pequeno, para entender um problema depois
FICAM_DEPOIS_DA_ENTREGA = {"projeto.json", "cenas.json", "tempos.json", "custos_reais.json", "criacao.json",
                           "qualidade.json", "roteiro.txt", "uso_openrouter.json", "uso_groq.json", "uso_gemini.json",
                           "uso_jev.json", "uso_claude.json"}


def depois_da_entrega(projeto: str) -> int:
    """Apaga os arquivos de trabalho do projeto entregue. Devolve quantos bytes saíram."""
    pasta = PROJETOS / projeto
    if not pasta.is_dir():
        return 0
    liberados = 0
    for item in pasta.iterdir():
        if item.name in FICAM_DEPOIS_DA_ENTREGA:
            continue
        if item.is_dir():
            liberados += sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            shutil.rmtree(item, ignore_errors=True)
        else:
            liberados += item.stat().st_size
            item.unlink(missing_ok=True)
    return liberados


def expirados(log=print) -> list:
    """Apaga o que passou dos 3 dias: a pasta, o vídeo no armazenamento e os eventos. Devolve os ids."""
    feitos = []
    for v in fila.expirados():
        try:
            armazenamento.apagar(v.get("objeto"))
            shutil.rmtree(PROJETOS / v["projeto"], ignore_errors=True)
            fila.marcar_expirado(v["id"])
            fila.apagar_eventos_de(v["id"])  # por último: o marcar_expirado também registra um evento
            feitos.append(v["id"])
        except Exception as erro:  # noqa: BLE001 - tenta de novo na próxima hora
            log(f"  limpeza: não deu para apagar {v['projeto']} ({str(erro)[:160]})")
    if feitos:
        log(f"  limpeza: {len(feitos)} vídeo(s) passaram dos {fila.DIAS_ATE_EXPIRAR} dias e foram apagados")
    return feitos
