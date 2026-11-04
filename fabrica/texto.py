"""Divisão do roteiro em frases curtas (tempo das cenas) e em blocos (narração)."""
import math
import re
import textwrap
from dataclasses import dataclass


@dataclass
class Trecho:
    ini: int  # posição do primeiro caractere no roteiro
    fim: int  # posição logo depois do último caractere
    texto: str


# japonês não separa frases nem palavras com espaço: 。！？ fecham a frase mesmo com texto colado, menos na citação que
# segue com と ou って ("「すごい！」と彼は言った。" é uma frase só)
_FIM_CJK = "。！？｡"
_FECHA_CJK = "」』）】〉》〕”’\"'"
FRASE = re.compile(
    r"\S.*?(?:[.!?…]+[\"')\]”»’]*(?=\s|$)"
    rf"|[{_FIM_CJK}]+[{_FECHA_CJK}]*(?![{_FIM_CJK}{_FECHA_CJK}]|と|って)"
    r"|$)"
)
PALAVRA = re.compile(r"\S+")
PAUSA = re.compile(r"[,;:—–、，；：]$")
_HIRAGANA = r"\u3041-\u309f"
_LETRA_CJK = r"\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f"  # kana e kanji
CJK = re.compile(f"[{_LETRA_CJK}]")
_DEPOIS_CJK = f"{_FIM_CJK}{_FECHA_CJK}、，；：…‥"
# sem espaço, a palavra japonesa vira kanji/katakana mais o hiragana que vem colado: 東京の / 企業は、 / 新しい
_PALAVRA_CJK = re.compile(
    rf"(?:[^\s{_HIRAGANA}{_DEPOIS_CJK}]{{1,12}}[{_HIRAGANA}]{{0,12}}|[{_HIRAGANA}]{{1,12}})[{_DEPOIS_CJK}]*"
    rf"|[{_DEPOIS_CJK}]+"
)
_ESPACO_ENTRE_CJK = re.compile(rf"(?<=[{_LETRA_CJK}{_DEPOIS_CJK}]) (?=[{_LETRA_CJK}])")
# 14 palavras japonesas dariam ~65 letras, trecho longo demais na fala; 10 delas dão ~45 (estimativa, sem medir a voz)
_LIMITE_CJK = 10 / 14
# como uma frase pode terminar; 」 e 』 fecham a citação que fechou a frase
FINAIS = (".", "?", "!", "…", "。", "！", "？", "｡", "」", "』")
_FECHA_FRASE = re.compile(rf"[.!?…{_FIM_CJK}]['\"”)」』）】〉》]*\s*$")
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


def achar_palavras(texto: str) -> list[re.Match]:
    """As palavras do texto: o que está entre espaços e, no meio de japonês, os pedaços de _PALAVRA_CJK."""
    achadas = []
    for m in PALAVRA.finditer(texto):
        achadas += _PALAVRA_CJK.finditer(texto, m.start(), m.end()) if CJK.search(m.group()) else [m]
    return achadas


def juntar_palavras(palavras: list[str]) -> str:
    """Junta palavras com espaço, menos entre as japonesas."""
    return _ESPACO_ENTRE_CJK.sub("", " ".join(palavras))


def predomina_cjk(texto: str) -> bool:
    return len(CJK.findall(texto)) * 2 > len(texto)


def fecha_frase(texto: str) -> bool:
    return bool(_FECHA_FRASE.search((texto or "").strip()))


def quebrar_linhas(texto: str, largura: int) -> list[str]:
    """Linhas de legenda de até `largura` letras. A letra japonesa ocupa o lugar de duas, e a linha corta entre palavras."""
    if not predomina_cjk(texto):
        return textwrap.wrap(texto, largura)
    limite = max(1, largura // 2)
    linhas, ini, fim = [], None, None
    for m in achar_palavras(texto):
        if ini is not None and m.end() - ini > limite:
            linhas.append(texto[ini:fim])
            ini = None
        ini = m.start() if ini is None else ini
        fim = m.end()
    if ini is not None:
        linhas.append(texto[ini:fim])
    return [linha[i:i + limite] for linha in linhas for i in range(0, len(linha), limite)]


def _dividir_longa(frase: Trecho, max_palavras: int) -> list[Trecho]:
    palavras = achar_palavras(frase.texto)
    total = len(palavras)
    if predomina_cjk(frase.texto):
        max_palavras = max(1, round(max_palavras * _LIMITE_CJK))
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
