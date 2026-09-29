"""Divisão do roteiro em frases curtas (tempo das cenas) e em blocos (narração)."""
import math
import re
from dataclasses import dataclass


@dataclass
class Trecho:
    ini: int  # posição do primeiro caractere no roteiro
    fim: int  # posição logo depois do último caractere
    texto: str


FRASE = re.compile(r"\S.*?(?:[.!?…]+[\"')\]”»’]*(?=\s|$)|$)")
PALAVRA = re.compile(r"\S+")
PAUSA = re.compile(r"[,;:—–]$")
MARCADOR = re.compile(r"\[(SIMBOLO|TITULO|AVATAR|/AVATAR|INSERTO[ \t]+[A-Za-z0-9_-]+)\]", re.IGNORECASE)


def normalizar(texto: str) -> str:
    """Tira espaços sobrando e deixa uma linha em branco entre parágrafos."""
    paragrafos = re.split(r"\n\s*\n", texto.replace("\r\n", "\n").strip())
    limpos = (re.sub(r"\s+", " ", p).strip() for p in paragrafos)
    return "\n\n".join(p for p in limpos if p)


def extrair_marcadores(texto: str) -> tuple[str, list[dict]]:
    """Tira do roteiro as marcações que não são narradas e devolve o texto limpo e a lista delas.

    [SIMBOLO]           símbolo de pausa na tela
    [TITULO] Nome       título de uma parte, que aparece na tela sem ser narrado
    [AVATAR] ... [/AVATAR]  trecho em que o personagem aparece falando na tela
    [INSERTO nome]      clipe pronto do personagem, sempre o mesmo, encaixado ali

    Cada marcação guarda a posição dela no texto limpo.
    """
    paragrafos, marcadores = [], []
    for paragrafo in normalizar(texto).split("\n\n"):
        pedacos = MARCADOR.split(paragrafo)  # texto, marca, texto, marca, texto...
        montado = ""
        for i in range(0, len(pedacos), 2):
            pedaco = pedacos[i].strip()
            if i:
                marca = " ".join(pedacos[i - 1].split()).upper()
                posicao = sum(len(p) + 2 for p in paragrafos) + len(montado)
                if marca == "TITULO":
                    marcadores.append({"tipo": "titulo", "texto": pedaco, "c": posicao})
                    pedaco = ""  # o título fica na tela, não na narração
                elif marca == "AVATAR":
                    marcadores.append({"tipo": "avatar_inicio", "texto": "", "c": posicao})
                elif marca == "/AVATAR":
                    marcadores.append({"tipo": "avatar_fim", "texto": "", "c": posicao})
                elif marca.startswith("INSERTO"):
                    marcadores.append({"tipo": "inserto", "texto": marca.split(" ", 1)[1].lower(), "c": posicao})
                else:
                    marcadores.append({"tipo": "simbolo", "texto": "", "c": posicao})
            if pedaco:
                montado = f"{montado} {pedaco}" if montado else pedaco
        if montado:
            paragrafos.append(montado)
    limpo = "\n\n".join(paragrafos)
    for m in marcadores:
        m["c"] = min(m["c"], len(limpo))
    return limpo, marcadores


def frases(texto: str) -> list[Trecho]:
    trechos = []
    for linha in re.finditer(r"[^\n]+", texto):
        for m in FRASE.finditer(linha.group()):
            conteudo = m.group().rstrip()
            ini = linha.start() + m.start()
            trechos.append(Trecho(ini, ini + len(conteudo), conteudo))
    return trechos


def _dividir_longa(frase: Trecho, max_palavras: int) -> list[Trecho]:
    palavras = list(PALAVRA.finditer(frase.texto))
    total = len(palavras)
    if total <= max_palavras:
        return [frase]
    # partes de tamanho parecido, cortando na vírgula ou pausa mais próxima do ponto ideal
    quantidade = math.ceil(total / max_palavras)
    tamanho = total / quantidade
    folga = max(1, int(tamanho * 0.3))
    partes, inicio = [], 0
    for parte in range(1, quantidade):
        ideal = round(tamanho * parte) - 1
        janela = range(max(inicio, ideal - folga), min(total - 2, ideal + folga) + 1)
        pausas = [i for i in janela if PAUSA.search(palavras[i].group())]
        corte = min(pausas, key=lambda i: abs(i - ideal)) if pausas else max(ideal, inicio)
        partes.append((inicio, corte))
        inicio = corte + 1
    partes.append((inicio, total - 1))
    return [
        Trecho(
            frase.ini + palavras[a].start(),
            frase.ini + palavras[b].end(),
            frase.texto[palavras[a].start():palavras[b].end()],
        )
        for a, b in partes
    ]


def unidades(texto: str, max_palavras: int = 14) -> list[Trecho]:
    return [parte for f in frases(texto) for parte in _dividir_longa(f, max_palavras)]


def blocos(texto: str, max_caracteres: int = 2500) -> list[Trecho]:
    """Agrupa frases inteiras em blocos de narração, preferindo quebrar entre parágrafos."""
    limites = []
    ini = fim = None
    for f in frases(texto):
        if ini is None:
            ini, fim = f.ini, f.fim
            continue
        muda_paragrafo = "\n" in texto[fim:f.ini]
        if f.fim - ini > max_caracteres or (muda_paragrafo and fim - ini > max_caracteres * 0.6):
            limites.append((ini, fim))
            ini = f.ini
        fim = f.fim
    if ini is not None:
        limites.append((ini, fim))
    return [Trecho(a, b, texto[a:b]) for a, b in limites]
