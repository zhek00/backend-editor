"""Clientes do MCP na internet: a senha (token) de cada um, o limite de vídeos por dia e os links de download.

Pedido do usuário em 2026-10-07: o MCP ganha uma URL real. Sem senha, quem achasse a URL criaria vídeos com as chaves
da fábrica (narração e imagens pagas) e, pelo entregar_video e pelo importar_pacote, gravaria e leria arquivos no disco
do servidor. Agora cada cliente tem um token (`fabrica mcp-cliente criar NOME`), mandado pelo Claude Code dele no
cabeçalho Authorization; o arquivo guarda só o hash do token, então ele vazado não dá acesso. Cada projeto tem dono, e
um cliente nunca vê nem responde as tarefas do outro.

No fim, o vídeo e o pacote do projeto saem por link de download (/baixar/ID/ARQUIVO), com validade, em vez de um
caminho no disco do servidor.
"""
import hashlib
import json
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import RAIZ

ARQUIVO = RAIZ / "clientes_mcp.json"  # fora do Git
LINKS = RAIZ / "entregas" / "links.json"
POR_DIA = 2  # vídeos que cada conta começa por dia (o produto de R$ 1.000)
VALIDADE_DO_LINK = 7 * 24 * 3600

_TRAVA = threading.Lock()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ler(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def _gravar(caminho: Path, dados):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(caminho)


def _dados():
    return _ler(ARQUIVO, {"clientes": {}})


def criar(nome: str, por_dia: int = POR_DIA) -> str:
    """Cria o cliente e devolve o token. O token só aparece aqui: o arquivo guarda o hash."""
    nome = nome.strip().lower()
    with _TRAVA:
        dados = _dados()
        if any(c["nome"] == nome for c in dados["clientes"].values()):
            raise ValueError(f"o cliente {nome} já existe (revogue antes para gerar outro token)")
        token = "tl_" + secrets.token_urlsafe(32)
        dados["clientes"][_hash(token)] = {"nome": nome, "criado": datetime.now().isoformat(timespec="seconds"),
                                           "ativo": True, "por_dia": int(por_dia), "producoes": []}
        _gravar(ARQUIVO, dados)
    return token


def revogar(nome: str) -> bool:
    with _TRAVA:
        dados = _dados()
        achado = False
        for c in dados["clientes"].values():
            if c["nome"] == nome:
                c["ativo"], achado = False, True
        _gravar(ARQUIVO, dados)
    return achado


def listar() -> list:
    hoje = datetime.now().date().isoformat()
    return [{"nome": c["nome"], "ativo": c["ativo"], "criado": c["criado"], "por_dia": c.get("por_dia", POR_DIA),
             "hoje": sum(1 for p in c.get("producoes", []) if p["quando"].startswith(hoje)),
             "total": len(c.get("producoes", []))}
            for c in _dados()["clientes"].values()]


def quem(token: str):
    """O nome do cliente dono do token, ou None (token errado ou revogado)."""
    c = _dados()["clientes"].get(_hash((token or "").strip()))
    return c["nome"] if c and c.get("ativo") else None


def pode_comecar(nome: str) -> str:
    """Vazio se o cliente pode começar mais um vídeo hoje; senão, o motivo."""
    hoje = datetime.now().date().isoformat()
    for c in _dados()["clientes"].values():
        if c["nome"] == nome:
            feitos = [p for p in c.get("producoes", []) if p["quando"].startswith(hoje)]
            limite = c.get("por_dia", POR_DIA)
            if len(feitos) >= limite:
                return (f"o limite da sua conta é de {limite} vídeo(s) por dia, e hoje já foram {len(feitos)} "
                        f"({', '.join(p['video'] for p in feitos)}). Amanhã libera de novo.")
            return ""
    return "conta não encontrada"


def registrar_producao(nome: str, video: str):
    with _TRAVA:
        dados = _dados()
        for c in dados["clientes"].values():
            if c["nome"] == nome:
                c.setdefault("producoes", []).append({"video": video,
                                                     "quando": datetime.now().isoformat(timespec="seconds")})
        _gravar(ARQUIVO, dados)


def link(arquivo: Path, cliente: str) -> str:
    """Um código de download de uso do cliente, válido por VALIDADE_DO_LINK. A URL é /baixar/CODIGO/NOME_DO_ARQUIVO."""
    codigo = secrets.token_urlsafe(24)
    with _TRAVA:
        links = {k: v for k, v in _ler(LINKS, {}).items() if v["vence"] > time.time()}
        links[codigo] = {"arquivo": str(Path(arquivo).resolve()), "cliente": cliente,
                         "vence": time.time() + VALIDADE_DO_LINK}
        _gravar(LINKS, links)
    return f"{codigo}/{Path(arquivo).name}"


def arquivo_do_link(codigo: str, nome: str):
    """O arquivo do link, se o código existe, não venceu e o nome bate; senão None."""
    item = _ler(LINKS, {}).get(codigo)
    if not item or item["vence"] < time.time():
        return None
    caminho = Path(item["arquivo"])
    return caminho if caminho.name == nome and caminho.is_file() else None
