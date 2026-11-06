"""O banco de imagens da casa: toda imagem de IA gerada fica guardada, e a cena que pede algo parecido usa ela, sem gerar.

Pedido do usuário em 2026-11-06: os canais falam de assuntos parecidos, e imagem repetida entre vídeos não custa nem
espera. O ganho maior é o tempo (a etapa de imagens passa de uma hora num vídeo de 30 min) e não ficar parado quando a
assinatura ou a chave acabam.

Regras (config.yaml, banco_imagens):
- nunca a mesma imagem duas vezes no mesmo canal nem no mesmo vídeo, e no máximo `usos_max` usos no total: imagem igual
  em vários canais pesa na análise de conteúdo reutilizado do YouTube;
- só entra imagem sem personagem do canal e sem texto pedido (loja, preço): essas só servem à própria cena;
- só sai imagem do estilo atual: as antigas são escuras, e o usuário trocou o estilo em 2026-11-05;
- quem decide se serve é o Jev, depois (corrigir.conferir_ia): a imagem errada é refeita, como qualquer imagem de IA.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np

from .config import RAIZ

PASTA = RAIZ / "banco_imagens"
ARQUIVO_DO_BANCO = PASTA / "banco.db"
ESTILO_ATUAL = "Realistic documentary photo"
# 0,80 medido em 2026-11-06 com os pedidos de dois vídeos: acima disso a imagem é do mesmo assunto (o combo de mercado, o
# cardápio com preço); abaixo já vinha outra coisa (rã no museu para vitrine de outro objeto). Palavras em comum não servem:
# acharam auroque para floresta. O Jev ainda confere depois
PADRAO = {"ativo": True, "semelhanca_minima": 0.8, "usos_max": 3}
MODELO_DO_SIGNIFICADO = "openai/text-embedding-3-small"  # 9 mil pedidos custam uns US$ 0,02
DIMENSOES = 256
TEXTO_PEDIDO = re.compile(r"""["“”£€$]|\d+\s*%|(?:^|\s)'[^']+'""")
_trava = threading.Lock()


def opcoes(config) -> dict:
    return {**PADRAO, **((config or {}).get("banco_imagens") or {})}


def cena_do_prompt(prompt) -> str:
    """Só a parte que diz o que a imagem mostra: o resto do prompt final é estilo e o que evitar."""
    m = re.search(r"Scene:\s*(.*?)(?:\nStyle:|\Z)", prompt or "", re.S)
    return (m.group(1) if m else prompt or "").strip()


def serve_para_o_banco(cena: dict, prompt: str) -> bool:
    """Personagem do canal e texto pedido (preço, nome entre aspas) só servem à própria cena."""
    pedido = cena_do_prompt(prompt)
    return bool(pedido) and not cena.get("personagem") and not TEXTO_PEDIDO.search(pedido)


def significado(textos: list) -> np.ndarray:
    """O vetor de cada texto, de tamanho 1: a semelhança entre dois é a multiplicação deles."""
    from .openrouter_local import cabecalhos

    vetores = []
    for i in range(0, len(textos), 256):
        r = httpx.post("https://openrouter.ai/api/v1/embeddings", headers=cabecalhos(), timeout=60,
                       json={"model": MODELO_DO_SIGNIFICADO, "input": [t[:400] for t in textos[i:i + 256]], "dimensions": DIMENSOES})
        r.raise_for_status()
        vetores += [e["embedding"] for e in r.json()["data"]]
    m = np.array(vetores, dtype=np.float32)
    return m / np.linalg.norm(m, axis=1, keepdims=True)


def canal_do(projeto) -> str:
    return Path(str(projeto.dados.get("perfil") or "")).stem


def abrir(arquivo=None) -> sqlite3.Connection:
    arquivo = Path(arquivo or ARQUIVO_DO_BANCO)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(arquivo, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE IF NOT EXISTS imagens (id INTEGER PRIMARY KEY, hash TEXT UNIQUE, arquivo TEXT, texto TEXT, estilo INTEGER,
            provedor TEXT, modelo TEXT, projeto TEXT, canal TEXT, criado TEXT, vetor BLOB);
        CREATE TABLE IF NOT EXISTS usos (imagem INTEGER, canal TEXT, projeto TEXT, cena INTEGER, quando TEXT,
            PRIMARY KEY (projeto, cena));
    """)
    return c


def guardar(c, origem: Path, texto, registro, projeto, canal, pasta=None):
    """Entra uma imagem, sem vetor (completar_vetores). A repetida (mesmo conteúdo) fica como está."""
    conteudo = origem.read_bytes()
    nome = hashlib.sha1(conteudo).hexdigest()
    if c.execute("SELECT 1 FROM imagens WHERE hash=?", (nome,)).fetchone():
        return None
    pasta = Path(pasta or PASTA)
    destino = pasta / nome[:2] / f"{nome}{origem.suffix}"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(conteudo)  # cópia, não link: há rotinas que regravam a imagem do projeto no lugar
    novo = c.execute("INSERT INTO imagens (hash, arquivo, texto, estilo, provedor, modelo, projeto, canal, criado) "
                     "VALUES (?,?,?,?,?,?,?,?,?)",
                     (nome, str(destino.relative_to(pasta)), texto, int(ESTILO_ATUAL in (registro.get("prompt") or "")),
                      registro.get("provedor"), registro.get("modelo"), projeto, canal,
                      datetime.now().isoformat(timespec="seconds"))).lastrowid
    # quem gerou conta como o primeiro uso: a imagem nunca volta para o mesmo canal. Cena negativa: não é de uma cena viva
    c.execute("INSERT OR REPLACE INTO usos VALUES (?,?,?,?,?)", (novo, canal, projeto, -novo, ""))
    return novo


def completar_vetores(c) -> None:
    """A imagem entra no banco sem vetor, para não fazer uma chamada por imagem: aqui saem todos de uma vez."""
    faltam = c.execute("SELECT id, texto FROM imagens WHERE vetor IS NULL").fetchall()
    if faltam:
        for linha, vetor in zip(faltam, significado([f["texto"] for f in faltam])):
            c.execute("UPDATE imagens SET vetor=? WHERE id=?", (vetor.tobytes(), linha["id"]))
        c.commit()


def candidatas(c, canal, projeto, usos_max, so_estilo=True) -> list:
    """As imagens que este canal pode usar: nunca usadas nele nem neste vídeo, e com uso sobrando."""
    return c.execute(
        "SELECT i.id, i.arquivo, i.texto, i.vetor FROM imagens i WHERE i.vetor IS NOT NULL AND (? = 0 OR i.estilo = 1) "
        "AND i.id NOT IN (SELECT imagem FROM usos WHERE canal = ? OR projeto = ?) "
        "AND (SELECT COUNT(*) FROM usos u WHERE u.imagem = i.id) < ?", (int(so_estilo), canal, projeto, usos_max)).fetchall()


def escolher(pedidos: np.ndarray, linhas: list, minimo: float) -> dict:
    """{índice do pedido: imagem}. As combinações mais fortes ganham, e cada imagem serve a um pedido só."""
    if not linhas or not len(pedidos):
        return {}
    banco = np.frombuffer(b"".join(l["vetor"] for l in linhas), dtype=np.float32).reshape(len(linhas), -1)
    notas = pedidos @ banco.T
    achadas, usadas = {}, set()
    for i, j in zip(*np.unravel_index(np.argsort(-notas, axis=None), notas.shape)):
        nota = float(notas[i, j])
        if nota < minimo:
            break
        if int(i) not in achadas and int(j) not in usadas:
            achadas[int(i)] = {**{k: linhas[j][k] for k in ("id", "arquivo", "texto")}, "semelhanca": round(nota, 3)}
            usadas.add(int(j))
    return achadas


def atender(projeto, pendentes, log=print) -> list:
    """Põe as imagens do banco nas cenas que ele atende e devolve as que ainda precisam ser geradas. Nunca para o vídeo."""
    ajuste = opcoes(projeto.config)
    if not ajuste["ativo"] or not ARQUIVO_DO_BANCO.exists():
        return pendentes
    from . import custos_reais, imagens

    # prompt_manual: a pessoa pediu, ou o Jev já reprovou e escreveu a correção. Esses são sempre gerados
    pedidos = {c["n"]: imagens.prompt_final(c, projeto.perfil, False) for c in pendentes if not c.get("prompt_manual")}
    aptas = [c for c in pendentes if c["n"] in pedidos and serve_para_o_banco(c, pedidos[c["n"]])]
    if not aptas:
        return pendentes
    canal, atendidas = canal_do(projeto), set()
    try:
        with _trava:
            c = abrir()
            completar_vetores(c)
            linhas = candidatas(c, canal, projeto.nome, ajuste["usos_max"])
            vetores = significado([cena_do_prompt(pedidos[x["n"]]) for x in aptas]) if linhas else []
            for i, achada in escolher(vetores, linhas, ajuste["semelhanca_minima"]).items():
                cena, origem = aptas[i], PASTA / achada["arquivo"]
                if not origem.exists():
                    continue
                destino = projeto.imagem(cena["n"])
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origem, destino)
                destino.with_suffix(".json").write_text(json.dumps(
                    {"provedor": "banco_proprio", "imagem": achada["id"], "semelhanca": achada["semelhanca"],
                     "prompt": pedidos[cena["n"]], "texto_guardado": achada["texto"], "custo_usd": 0},
                    ensure_ascii=False, indent=2), encoding="utf-8")
                c.execute("INSERT OR REPLACE INTO usos VALUES (?,?,?,?,?)", (achada["id"], canal, projeto.nome, cena["n"],
                                                                            datetime.now().isoformat(timespec="seconds")))
                custos_reais.registrar(projeto, "imagem", f"imagem do banco próprio na cena {cena['n']}", 0, unidades=1,
                                       detalhes={"cena": cena["n"], "provedor": "banco_proprio", "modelo": ""})
                atendidas.add(cena["n"])
            c.commit()
            c.close()
    except (OSError, sqlite3.Error, httpx.HTTPError, ValueError, KeyError, SystemExit) as erro:
        log(f"  banco próprio fora agora, gerando tudo: {str(erro)[:120]}")
    if atendidas:
        log(f"  banco próprio: {len(atendidas)} de {len(pendentes)} imagens vieram de vídeos antigos, sem gerar")
    return [c for c in pendentes if c["n"] not in atendidas]


def depois_de_gerar(projeto, cena, destino: Path, registro: dict) -> None:
    """A imagem nova entra no banco, e a do banco que a cena usava (o Jev reprovou) volta a estar livre. Nunca para o vídeo."""
    from . import imagens

    try:
        if not opcoes(projeto.config)["ativo"]:
            return
        prompt = registro.get("prompt") or imagens.prompt_final(cena, projeto.perfil, False)
        with _trava:
            c = abrir()
            c.execute("DELETE FROM usos WHERE projeto=? AND cena=?", (projeto.nome, cena["n"]))
            if serve_para_o_banco(cena, prompt) and not cena.get("prompt_manual"):
                guardar(c, destino, cena_do_prompt(prompt), {**registro, "prompt": prompt}, projeto.nome, canal_do(projeto))
            c.commit()
            c.close()
    except Exception as erro:  # o banco é um extra: a imagem já está pronta, e o vídeo segue
        print(f"  a imagem da cena {cena['n']} não entrou no banco próprio: {str(erro)[:120]}")


def indexar_projetos(raiz: Path, log=print) -> int:
    """Põe no banco as imagens do estilo atual que os vídeos já têm. Pode rodar de novo: o que já está lá fica como está."""
    c, novas = abrir(), 0
    for pasta in sorted(p for p in raiz.iterdir() if (p / "imagens").is_dir() and (p / "projeto.json").exists()):
        try:
            canal = Path(str(json.loads((pasta / "projeto.json").read_text(encoding="utf-8")).get("perfil") or "")).stem
        except (OSError, ValueError):
            continue
        for sidecar in sorted((pasta / "imagens").glob("*.json")):
            try:
                registro = json.loads(sidecar.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            prompt = registro.get("prompt") or ""
            imagem = next((f for f in (sidecar.with_suffix(e) for e in (".png", ".jpg", ".webp")) if f.exists()), None)
            if (imagem is None or registro.get("provedor") == "banco_proprio" or ESTILO_ATUAL not in prompt
                    or not serve_para_o_banco({}, prompt)):
                continue
            if guardar(c, imagem, cena_do_prompt(prompt), registro, pasta.name, canal):
                novas += 1
        c.commit()
    completar_vetores(c)
    log(f"banco próprio: {novas} imagens novas, {c.execute('SELECT COUNT(*) FROM imagens').fetchone()[0]} no total")
    c.close()
    return novas
