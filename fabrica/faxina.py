"""Faxina de disco: tira das produções antigas o que o render refaz de graça.

Um vídeo de 30 minutos deixa uns 2,5 GB em render/ (clipes, a emenda sem legenda, voz, música e trilha já mixadas) que
só servem para refazer o render mais depressa. Com o disco em 95% (2026-11-05) e uma queda de render por "No space left
on device" no Robô do Dotti, esse é o primeiro lugar de onde tirar.

Roda depois de cada entrega, e só quando o disco está abaixo de faxina.livre_gb. Vai do projeto mais antigo para o mais
novo e para assim que alcança a folga. Só toca em projeto com final.mp4, entregue há mais de faxina.dias, e parado.

Nunca toca no que custou dinheiro ou tempo de modelo: final.mp4, imagens/, midia/, narracao/, animacoes/, trilha/,
thumbs e os .json. Um render depois da faxina funciona, só leva o tempo de refazer os clipes.
"""
import json
import shutil
import sys
import time
from pathlib import Path

DIAS = 7          # produção mais nova que isso continua pronta para corrigir uma cena depressa
LIVRE_GB = 60     # abaixo disso de folga a faxina entra; acima, ela nem olha os projetos
PASTAS = ("clipes", "fotos", "textos", "pedacos")
ARQUIVOS = ("video.mp4", "voz.wav", "musica.wav", "musica.wav.assinatura", "trilha.wav", "clipes.txt")
PARADO_HA = 3600  # segundos sem gravar nada no projeto para ele contar como parado


def _config() -> dict:
    from .config import config_geral

    return config_geral().get("faxina") or {}


def _tamanho(caminho: Path) -> int:
    if caminho.is_file():
        return caminho.stat().st_size
    return sum(f.stat().st_size for f in caminho.rglob("*") if f.is_file())


def _sobras(projeto: Path) -> list:
    render = projeto / "render"
    return [c for c in [*(render / p for p in PASTAS), *(render / a for a in ARQUIVOS)] if c.exists()]


def _pode_limpar(projeto: Path, agora: float, dias: float) -> bool:
    final = projeto / "final.mp4"
    if not final.is_file() or agora - final.stat().st_mtime < dias * 86400:
        return False
    for nome in ("cenas.json", "criacao.json", "chamadas.jsonl"):
        arquivo = projeto / nome
        if arquivo.exists() and agora - arquivo.stat().st_mtime < PARADO_HA:
            return False
    try:
        return json.loads((projeto / "criacao.json").read_text(encoding="utf-8")).get("status") != "processando"
    except (OSError, ValueError):
        return True  # projeto de antes do criacao.json, ou arquivo quebrado: o final.mp4 antigo já diz que acabou


def candidatos(raiz: Path, dias: float = DIAS, agora: float | None = None) -> list:
    """Os projetos que podem ser limpos, do mais antigo para o mais novo."""
    agora = time.time() if agora is None else agora
    pastas = [p for p in raiz.iterdir() if p.is_dir() and not p.name.startswith("_") and _sobras(p)
              and _pode_limpar(p, agora, dias)]
    return sorted(pastas, key=lambda p: (p / "final.mp4").stat().st_mtime)


def limpar_projeto(projeto: Path) -> int:
    """Apaga as sobras do render deste projeto. Devolve os bytes liberados."""
    liberado = 0
    for sobra in _sobras(projeto):
        tamanho = _tamanho(sobra)
        try:
            shutil.rmtree(sobra) if sobra.is_dir() else sobra.unlink()
            liberado += tamanho
        except OSError:
            continue  # arquivo aberto em outro programa: fica para a próxima
    return liberado


def faxinar(log=print, raiz: Path | None = None, cfg: dict | None = None, simular: bool = False) -> int:
    """Libera espaço até a folga de faxina.livre_gb. Devolve os bytes liberados (ou os que liberaria, em simular)."""
    from .projeto import PROJETOS

    cfg = _config() if cfg is None else cfg
    if cfg.get("ativo", True) is False:
        return 0
    raiz = Path(raiz or PROJETOS)
    alvo = float(cfg.get("livre_gb", LIVRE_GB)) * 2**30
    livre = shutil.disk_usage(raiz).free
    if livre >= alvo:
        return 0
    liberado, limpos = 0, 0
    for projeto in candidatos(raiz, float(cfg.get("dias", DIAS))):
        if livre + liberado >= alvo:
            break
        liberado += sum(_tamanho(s) for s in _sobras(projeto)) if simular else limpar_projeto(projeto)
        limpos += 1
    if limpos:
        verbo = "liberaria" if simular else "liberou"
        log(f"  faxina: {verbo} {liberado / 2**30:.1f} GB em {limpos} produção(ões) antiga(s); "
            f"o render refaz isso de graça se preciso")
    return liberado


if __name__ == "__main__":
    faxinar(simular="--apagar" not in sys.argv)
