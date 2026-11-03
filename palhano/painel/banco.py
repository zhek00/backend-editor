"""Banco do painel (SQLite): contas, sessões, máquinas, canais, chaves, produções e comandos para as máquinas."""
import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

PASTA = Path(__file__).resolve().parent / "dados"
ARQUIVO = PASTA / "painel.db"
_TRAVA = threading.Lock()

# o dia do limite de vídeos segue o horário de Brasília (sem horário de verão desde 2019)
BRASILIA = timezone(timedelta(hours=-3))

PLANOS = {
    "basico": {"nome": "Básico", "limite_dia": 3},
    "mensal": {"nome": "Mensal", "limite_dia": 20},
    "anual": {"nome": "Anual", "limite_dia": 20},
    "cortesia": {"nome": "Cortesia", "limite_dia": 3},
    "ilimitado": {"nome": "Sem limite", "limite_dia": 0},
}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    nome TEXT NOT NULL DEFAULT '',
    senha_hash TEXT NOT NULL,
    aprovado INTEGER NOT NULL DEFAULT 0,
    admin INTEGER NOT NULL DEFAULT 0,
    plano TEXT NOT NULL DEFAULT '',
    vence TEXT NOT NULL DEFAULT '',
    criado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessoes (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    criado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pareamentos (
    codigo TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    criado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maquinas (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    nome TEXT NOT NULL,
    sistema TEXT NOT NULL DEFAULT '',
    versao TEXT NOT NULL DEFAULT '',
    token_hash TEXT UNIQUE NOT NULL,
    criada TEXT NOT NULL,
    visto_em TEXT NOT NULL DEFAULT '',
    ocupada INTEGER NOT NULL DEFAULT 0,
    pasta_padrao TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS canais (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    nome TEXT NOT NULL,
    descricao TEXT NOT NULL DEFAULT '',
    diretrizes TEXT NOT NULL DEFAULT '',
    descricao_fixa TEXT NOT NULL DEFAULT '',
    narrador TEXT NOT NULL DEFAULT '',
    voice_id TEXT NOT NULL DEFAULT '',
    velocidade REAL,
    estilo TEXT NOT NULL DEFAULT '',
    ajustes TEXT NOT NULL DEFAULT '{}',
    criado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chaves (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    provedor TEXT NOT NULL,
    cifrada TEXT NOT NULL,
    final TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'nao_testada',
    detalhe TEXT NOT NULL DEFAULT '',
    testada_em TEXT NOT NULL DEFAULT '',
    criada TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS producoes (
    id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    canal_id INTEGER,
    canal_nome TEXT NOT NULL DEFAULT '',
    nome TEXT NOT NULL,
    roteiro TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    estado TEXT NOT NULL DEFAULT 'fila',
    etapa TEXT NOT NULL DEFAULT '',
    progresso INTEGER NOT NULL DEFAULT 0,
    linhas TEXT NOT NULL DEFAULT '[]',
    maquina_id INTEGER,
    criada TEXT NOT NULL,
    dia TEXT NOT NULL,
    iniciada TEXT NOT NULL DEFAULT '',
    terminada TEXT NOT NULL DEFAULT '',
    duracao_s REAL NOT NULL DEFAULT 0,
    custo_usd REAL,
    custo TEXT NOT NULL DEFAULT '{}',
    arquivo TEXT NOT NULL DEFAULT '',
    erro TEXT NOT NULL DEFAULT '',
    escondida INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS comandos (
    id INTEGER PRIMARY KEY,
    maquina_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    dados TEXT NOT NULL DEFAULT '{}',
    criado TEXT NOT NULL,
    feito INTEGER NOT NULL DEFAULT 0
);
"""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hoje_brasilia() -> str:
    return datetime.now(BRASILIA).date().isoformat()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def novo_token() -> str:
    return secrets.token_urlsafe(32)


def hash_senha(senha: str) -> str:
    sal = secrets.token_hex(16)
    feito = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(sal), 310_000).hex()
    return f"pbkdf2${sal}${feito}"


def senha_confere(senha: str, guardada: str) -> bool:
    try:
        _, sal, feito = guardada.split("$")
    except ValueError:
        return False
    tentativa = hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(sal), 310_000).hex()
    return secrets.compare_digest(tentativa, feito)


def conectar() -> sqlite3.Connection:
    PASTA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ARQUIVO, check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


_CON = None


def con() -> sqlite3.Connection:
    global _CON
    if _CON is None:
        _CON = conectar()
        _CON.executescript(ESQUEMA)
        colunas = {x[1] for x in _CON.execute("PRAGMA table_info(canais)").fetchall()}
        if "descricao_fixa" not in colunas:  # banco criado antes do texto fixo da descrição
            _CON.execute("ALTER TABLE canais ADD COLUMN descricao_fixa TEXT NOT NULL DEFAULT ''")
            _CON.commit()
    return _CON


def um(sql: str, *args):
    with _TRAVA:
        linha = con().execute(sql, args).fetchone()
    return dict(linha) if linha else None


def todos(sql: str, *args) -> list:
    with _TRAVA:
        return [dict(x) for x in con().execute(sql, args).fetchall()]


def executar(sql: str, *args) -> int:
    with _TRAVA:
        c = con().execute(sql, args)
        con().commit()
        return c.lastrowid


def limite_do_dia(usuario: dict) -> int:
    """0 é sem limite (administração)."""
    if usuario.get("admin"):
        return 0
    return PLANOS.get(usuario.get("plano") or "", {}).get("limite_dia", 0) if usuario.get("plano") else -1


def usadas_hoje(usuario_id: int) -> int:
    # falhou e cancelado não contam; excluir da lista um vídeo entregue não devolve a vaga
    linha = um("SELECT COUNT(*) AS n FROM producoes WHERE usuario_id=? AND dia=? AND estado NOT IN ('falhou','cancelado')",
               usuario_id, hoje_brasilia())
    return linha["n"] if linha else 0


def json_de(texto, padrao=None):
    try:
        return json.loads(texto) if texto else padrao
    except (TypeError, ValueError):
        return padrao
