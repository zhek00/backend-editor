"""Conferência da narração: cada bloco gravado é ouvido de novo e conferido com o roteiro.

Pedido do usuário em 2026-10-09, depois da análise do concorrente (Pipeline Canal Dark): antes ninguém conferia se a
voz comeu uma palavra, repetiu um trecho ou errou um nome. A transcrição é o Whisper do Groq (whisper-large-v3-turbo,
grátis, 2.000 pedidos por dia por chave, um bloco de 2.500 letras em uns 2 s), revezando as GROQ_API_KEY do .env.

O que conta como problema (`problemas`), sempre pelo trecho e não pela nota do bloco inteiro, porque um bloco nosso
tem uns 400 palavras e uma palavra comida mal mexe na semelhança:
- **comeu**: 3 ou mais palavras do roteiro que não foram ouvidas, num trecho só (inclui o fim cortado);
- **repetiu**: 4 ou mais palavras ouvidas a mais, que são palavras do roteiro ali perto (a voz falou duas vezes).
  Palavra a mais que não é do roteiro é invenção da transcrição ("legendas pela comunidade Amara.org") e não conta;
- **pronúncia**: termo do glossário (`pronuncia.json` na raiz e `voz.pronuncia` do perfil) que a transcrição não
  reconheceu. A próxima gravação usa a grafia seguinte do glossário; a legenda e as cenas continuam com o termo
  original, porque o tempo das palavras é casado com o roteiro (`narracao._alinhar_pelas_palavras` interpola a
  palavra que não se acha);
- **diferente**: a fala inteira bate menos de 60% com o roteiro (outra língua, áudio quebrado).
Número escrito de um jeito e falado de outro ("1875" e "mil oitocentos e setenta e cinco") nunca conta.

Com problema, o bloco é gravado de novo (`conferencia_voz.regravar`, 2 vezes; na voz paga,
`conferencia_voz.regravar_paga`, 1 vez: uns US$ 0,004 por bloco na GenAIPro) e fica a gravação com menos problemas.
O resultado fica em `conferencia` no json de cada bloco e em `narracao/conferencia.json`. Sem transcrição (Groq fora,
offline, voz do computador), a narração segue sem a conferência: nunca para o vídeo.
"""
import difflib
import json
import re
import time
import unicodedata
from pathlib import Path

import httpx

from .config import RAIZ
from .util import rodar

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODELO = "whisper-large-v3-turbo"
GLOSSARIO = RAIZ / "pronuncia.json"
SEMELHANCA_MINIMA = 0.6
COMEU_MINIMO = 3
REPETIU_MINIMO = 4


def config(projeto) -> dict:
    padrao = {"ativo": True, "regravar": 2, "regravar_paga": 1, "modelo": MODELO}
    return {**padrao, **((projeto.config.get("conferencia_voz") or {}) if projeto else {})}


def ativa(projeto) -> bool:
    voz = projeto.perfil.get("voz") or {}
    return bool(config(projeto).get("ativo")) and not projeto.offline and voz.get("provedor") != "computador"


# ---------------------------------------------------------------- glossário

def glossario(projeto=None) -> dict:
    """{termo: (expressão que reconhece o termo na transcrição, [grafias para a voz])}. O do perfil vence o geral."""
    dados = {}
    if GLOSSARIO.exists():
        dados.update(json.loads(GLOSSARIO.read_text(encoding="utf-8")))
    if projeto is not None:
        dados.update(((projeto.perfil.get("voz") or {}).get("pronuncia")) or {})
    saida = {}
    for termo, v in dados.items():
        if termo.startswith("_") or not isinstance(v, dict):
            continue
        grafias = [g for g in (v.get("grafias") or []) if str(g).strip()] or [termo]
        reconhecer = v.get("reconhecer") or re.escape(_normal(termo))
        saida[termo] = (reconhecer, grafias)
    return saida


def _achar_termo(termo):
    # hífen em volta vale: "cavalo-de-Przewalski" tem o termo Przewalski
    return re.compile(rf"(?i)(?<!\w){re.escape(termo)}(?!\w)")


def termos_do_texto(texto, termos) -> list:
    """Termos do glossário que aparecem no texto, os mais compridos primeiro ("Serra Gaúcha" antes de "Serra")."""
    return [t for t in sorted(termos, key=len, reverse=True) if _achar_termo(t).search(texto)]


def com_grafias(texto, escolha, termos) -> str:
    """O texto que vai para a voz, com a grafia escolhida de cada termo."""
    for termo, i in escolha.items():
        texto = _achar_termo(termo).sub(termos[termo][1][i], texto)
    return texto


# ---------------------------------------------------------------- transcrição

def transcrever(audio: Path, idioma="pt", modelo=MODELO, log=print):
    """Texto ouvido no áudio, pelo Whisper do Groq, ou None se não deu (sem chave, todas no limite, fora do ar)."""
    from . import groq_local

    leve = audio.with_name(audio.stem + ".conferir.mp3")
    try:
        # 16 kHz mono a 32 kbps: um bloco de 2,5 min fica com uns 600 KB, longe do limite de 25 MB do Groq
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", audio, "-ac", "1", "-ar", "16000", "-b:a", "32k", leve])
        try:
            chaves = groq_local._chaves()
        except SystemExit as erro:
            log(f"    conferência da voz sem transcrição: {str(erro)[:120]}")
            return None
        ultimo = ""
        for tentativa in range(min(len(chaves) + 2, 8)):
            chave = chaves[groq_local._escolher_chave(chaves)]
            try:
                with open(leve, "rb") as f:
                    r = httpx.post(URL, headers={"Authorization": f"Bearer {chave}"},
                                   files={"file": (leve.name, f, "audio/mpeg")},
                                   data={"model": modelo, "language": idioma or "pt", "response_format": "json",
                                         "temperature": "0"}, timeout=180)
            except httpx.HTTPError as erro:
                ultimo = str(erro)[:120]
                time.sleep(2)
                continue
            if r.status_code == 200:
                return (r.json().get("text") or "").strip()
            ultimo = f"{r.status_code} {r.text[:160]}"
            if r.status_code == 429:
                # o limite é por chave: a seguinte costuma estar livre; com todas cheias, espera o que o Groq pedir
                if tentativa >= len(chaves) - 1:
                    time.sleep(min(30, groq_local._espera(r, tentativa)))
                continue
            if r.status_code in (400, 413):
                break
            time.sleep(2)
        log(f"    conferência da voz sem transcrição ({ultimo})")
        return None
    finally:
        leve.unlink(missing_ok=True)


# ---------------------------------------------------------------- comparação

def _normal(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", texto))


def _palavras(texto):
    return _normal(texto).split()


def _tem_numero(palavras):
    return any(any(ch.isdigit() for ch in p) for p in palavras)


def problemas(texto: str, ouvido: str, termos_texto=(), termos=None) -> dict:
    """Confere o que foi ouvido com o roteiro do bloco. Devolve {"semelhanca", "problemas": [...]}."""
    alvo, escuta = _palavras(texto), _palavras(ouvido)
    casador = difflib.SequenceMatcher(None, alvo, escuta, autojunk=False)
    semelhanca = casador.ratio() if alvo else 1.0
    achados = []
    for op, i1, i2, j1, j2 in casador.get_opcodes():
        if op == "equal":
            continue
        roteiro, ouvidas = alvo[i1:i2], escuta[j1:j2]
        if _tem_numero(roteiro) or _tem_numero(ouvidas):
            continue  # "1875" escrito e "mil oitocentos e setenta e cinco" falado
        faltaram = len(roteiro) - len(ouvidas)
        if faltaram >= COMEU_MINIMO and len(ouvidas) <= len(roteiro) / 2:
            achados.append({"tipo": "comeu", "trecho": " ".join(roteiro[:14]),
                            "onde": "no fim" if i2 >= len(alvo) else "no meio", "palavras": faltaram})
        sobraram = len(ouvidas) - len(roteiro)
        if sobraram >= REPETIU_MINIMO:
            perto = set(alvo[max(0, i1 - 40):i2 + 40])
            do_roteiro = [p for p in ouvidas if p in perto]
            if len(do_roteiro) >= 0.75 * len(ouvidas):
                achados.append({"tipo": "repetiu", "trecho": " ".join(ouvidas[:14]), "palavras": sobraram})
    ouvido_normal = _normal(ouvido)
    for termo in termos_texto:
        if not termos or termo not in termos:
            continue
        vezes = len(_achar_termo(termo).findall(texto))
        reconhecido = len(re.findall(termos[termo][0], ouvido_normal))
        if reconhecido < vezes:
            achados.append({"tipo": "pronuncia", "termo": termo, "trecho": termo})
    if semelhanca < SEMELHANCA_MINIMA:
        achados.append({"tipo": "diferente", "trecho": ouvido[:120], "semelhanca": round(semelhanca, 3)})
    return {"semelhanca": round(semelhanca, 3), "problemas": achados}


def gravidade(relatorio) -> int:
    """Para escolher a melhor entre as gravações: palavra comida e fala diferente pesam mais."""
    if not relatorio:
        return 0
    peso = {"diferente": 100, "comeu": 10, "repetiu": 6, "pronuncia": 3}
    return sum(peso.get(p["tipo"], 1) * max(1, p.get("palavras", 1)) for p in relatorio.get("problemas", []))


def descrever(p) -> str:
    if p["tipo"] == "comeu":
        return f"comeu {p['palavras']} palavra(s) {p['onde']}: \"{p['trecho']}\""
    if p["tipo"] == "repetiu":
        return f"repetiu um trecho: \"{p['trecho']}\""
    if p["tipo"] == "pronuncia":
        return f"não reconheci \"{p['termo']}\" na fala (pronúncia)"
    return f"a fala está muito diferente do roteiro ({p.get('semelhanca', 0):.0%})"


# ---------------------------------------------------------------- relatório do projeto

def resumo(projeto) -> dict:
    """Junta a conferência de todos os blocos em narracao/conferencia.json."""
    blocos = []
    for arq in sorted((projeto.pasta / "narracao").glob("bloco_*.json")):
        if arq.name.endswith(".tarefa.json"):
            continue
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        conf = dados.get("conferencia")
        blocos.append({"bloco": int(re.search(r"\d+", arq.stem).group()) + 1,
                       "conferido": bool(conf and conf.get("conferido")),
                       "semelhanca": (conf or {}).get("semelhanca"),
                       "gravacoes": (conf or {}).get("gravacoes", 1),
                       "problemas": (conf or {}).get("problemas", [])})
    saida = {"blocos": blocos, "conferidos": sum(b["conferido"] for b in blocos),
             "com_problema": [b["bloco"] for b in blocos if b["problemas"]]}
    projeto.salvar_json("narracao/conferencia.json", saida)
    return saida


def conferir_projeto(projeto, log=print) -> dict:
    """Confere a narração que já existe, sem gravar nada (grátis): `fabrica conferir-voz NOME`."""
    termos = glossario(projeto)
    idioma = (projeto.perfil.get("voz") or {}).get("idioma") or "pt"
    for arq in sorted((projeto.pasta / "narracao").glob("bloco_*.json")):
        if arq.name.endswith(".tarefa.json"):
            continue
        bruto = arq.with_name(arq.stem + "_bruto.wav")
        dados = json.loads(arq.read_text(encoding="utf-8"))
        if not bruto.exists() or not dados.get("texto"):
            continue
        ouvido = transcrever(bruto, idioma, config(projeto).get("modelo", MODELO), log)
        if ouvido is None:
            continue
        nos_termos = termos_do_texto(dados["texto"], termos)
        rel = problemas(dados["texto"], ouvido, nos_termos, termos)
        anterior = dados.get("conferencia") or {}
        dados["conferencia"] = {**rel, "conferido": True, "gravacoes": anterior.get("gravacoes", 1)}
        arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        n = int(re.search(r"\d+", arq.stem).group()) + 1
        if rel["problemas"]:
            for p in rel["problemas"]:
                log(f"  bloco {n}: {descrever(p)}")
        else:
            log(f"  bloco {n}: ok (semelhança {rel['semelhanca']:.0%})")
    return resumo(projeto)
