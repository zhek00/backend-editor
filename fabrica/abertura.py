"""Abertura sem fala, com cenas do próprio vídeo passando rápido sobre uma música forte.

O Claude escolhe as cenas de maior impacto visual pelas descrições, sem revelar o fim do
vídeo. A música é o trecho mais intenso da faixa do perfil, achado pelo volume. Nada disso
custa dinheiro, porque as cenas já existem e o Claude roda pela assinatura.
"""
import json
import random
import re

from . import claude_local
from .config import caminho_relativo
from .util import rodar

EXTENSOES_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

ESQUEMA = {
    "type": "object",
    "properties": {"cenas": {"type": "array", "items": {"type": "integer"}}},
    "required": ["cenas"],
    "additionalProperties": False,
}

INSTRUCOES = """Você monta a abertura de um vídeo do YouTube do canal {canal}. A abertura não tem fala. São {quantidade} cenas do próprio vídeo passando rápido, cerca de meio segundo cada, sobre uma música forte, para prender quem acabou de chegar.
Escolha pelas descrições as cenas de maior impacto visual, como seres imponentes, fogo, céu dramático, manuscritos antigos e rostos intensos. Varie o tipo de imagem, evite duas cenas parecidas seguidas e não use cenas que revelem a conclusão do vídeo.
Devolva os números das cenas na ordem em que devem aparecer, crescendo em intensidade até a última."""


def configuracao(perfil):
    return perfil.get("abertura") or {}


def ativa(perfil) -> bool:
    return bool(configuracao(perfil).get("ativo"))


def quantidade(perfil) -> int:
    cfg = configuracao(perfil)
    return max(3, round(float(cfg.get("duracao", 6)) / float(cfg.get("corte", 0.4))))


def escolher(projeto, cenas, disponivel, log=print):
    """Números das cenas da abertura, guardados em abertura.json para o render não perguntar de novo."""
    total = quantidade(projeto.perfil)
    candidatas = [c for c in cenas if disponivel(c) and c["fim"] - c["ini"] >= 1]
    arquivo = projeto.pasta / "abertura.json"
    validos = {c["n"] for c in candidatas}
    if arquivo.exists():
        salvas = [n for n in json.loads(arquivo.read_text(encoding="utf-8")).get("cenas", []) if n in validos]
        if len(salvas) >= min(total, len(candidatas)):
            return salvas[:total]
    if len(candidatas) <= total:
        escolhidas = [c["n"] for c in candidatas]
    elif projeto.offline:
        escolhidas = _por_espacamento(candidatas, total, projeto.nome)
    else:
        linhas = "\n".join(f"{c['n']} | {c['tipo']} | {(c.get('prompt') or c['texto'])[:160]}" for c in candidatas)
        instrucoes = INSTRUCOES.format(canal=projeto.perfil.get("nome", ""), quantidade=total)
        try:
            resposta = claude_local.perguntar(projeto, "abertura", instrucoes,
                                              f"Cenas no formato número | tipo | descrição\n\n{linhas}", ESQUEMA, esforco="low")
            escolhidas = [n for n in dict.fromkeys(resposta.get("cenas", [])) if n in validos][:total]
        except (RuntimeError, SystemExit) as erro:
            log(f"  o Claude não escolheu a abertura, usando cenas espalhadas pelo vídeo. {str(erro)[:120]}")
            escolhidas = []
        if len(escolhidas) < total:
            extras = [n for n in _por_espacamento(candidatas, total, projeto.nome) if n not in escolhidas]
            escolhidas += extras[:total - len(escolhidas)]
    arquivo.write_text(json.dumps({"cenas": escolhidas}, ensure_ascii=False, indent=2), encoding="utf-8")
    return escolhidas


def _por_espacamento(candidatas, total, semente):
    """Cenas espalhadas pelo vídeo, com preferência para imagens de IA e vídeos, que costumam ter mais impacto."""
    fortes = [c for c in candidatas if c["tipo"] in ("ia", "video_real")] or candidatas
    passo = len(fortes) / total
    escolhidas = [fortes[min(int(i * passo), len(fortes) - 1)]["n"] for i in range(total)]
    random.Random(semente).shuffle(escolhidas)
    return list(dict.fromkeys(escolhidas))


def faixa(projeto):
    """Arquivo de música da abertura. Numa pasta, a escolha é sempre a mesma para o mesmo projeto."""
    origem = configuracao(projeto.perfil).get("musica") or projeto.perfil.get("musica")
    if not origem:
        return None
    caminho = caminho_relativo(origem)
    if caminho.is_dir():
        faixas = sorted(f for f in caminho.iterdir() if f.suffix.lower() in EXTENSOES_AUDIO)
        return random.Random(projeto.nome).choice(faixas) if faixas else None
    return caminho if caminho.is_file() else None


def trecho_mais_forte(arquivo, duracao):
    """Segundo em que começa a janela mais alta da faixa, pelo volume percebido a cada décimo de segundo."""
    r = rodar(["ffmpeg", "-hide_banner", "-nostats", "-i", arquivo, "-af", "ebur128", "-f", "null", "-"])
    medidas = [(float(t), float(m)) for t, m in re.findall(r"t:\s*([\d.]+)\s+TARGET:.*?M:\s*(-?[\d.]+)", r.stderr)]
    if not medidas:
        return 0.0
    passo = max(medidas[1][0] - medidas[0][0], 0.05) if len(medidas) > 1 else 0.1
    janela = max(1, round(duracao / passo))
    fim_util = len(medidas) - max(1, round(3 / passo))  # os últimos segundos costumam ser o fecho da faixa
    melhor, inicio = None, 0.0
    soma = sum(max(m, -70) for _, m in medidas[:janela])
    for k in range(0, max(fim_util - janela, 1)):
        if melhor is None or soma > melhor:
            melhor, inicio = soma, medidas[k][0]
        if k + janela < len(medidas):
            soma += max(medidas[k + janela][1], -70) - max(medidas[k][1], -70)
    # a medida do ebur128 olha 400 ms para trás, então o trecho começa um pouco antes
    return max(inicio - 0.4, 0.0)
