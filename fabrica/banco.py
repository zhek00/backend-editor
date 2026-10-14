"""O banco de dados da fábrica: clientes, vídeos (a fila de produção) e eventos.

PostgreSQL na VPS (FABRICA_BANCO=postgresql://usuario:senha@host:5432/fabrica) e SQLite no computador de
desenvolvimento e nos testes (sem FABRICA_BANCO, o arquivo fabrica.db na raiz). O mesmo código serve aos dois: o SQL
é escrito com %s e as datas são texto ISO em UTC (comparam certo como texto nos dois bancos).

Pedido do usuário em 2026-10-14 (PLANO-VPS.md): produção em massa, 200 a 500 vídeos por dia, com o estado num banco
robusto no lugar da memória do servidor e dos JSON soltos (api.TAREFAS, mcp_producao.json, clientes_mcp.json).
"""
import contextlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from .config import RAIZ

VERSAO_DO_ESQUEMA = 1


def agora(mais=None) -> str:
    """A hora em UTC como texto ISO (segundos), opcionalmente somada a um timedelta."""
    momento = datetime.now(timezone.utc) + (mais or timedelta(0))
    return momento.strftime("%Y-%m-%dT%H:%M:%SZ")


def _esquema(postgres: bool) -> list:
    serial = "BIGSERIAL PRIMARY KEY" if postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return [
        """CREATE TABLE IF NOT EXISTS esquema (versao INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            chave_hash TEXT UNIQUE NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            limite_por_dia INTEGER,
            criado_em TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            projeto TEXT UNIQUE NOT NULL,
            titulo TEXT,
            roteiro TEXT NOT NULL,
            opcoes TEXT NOT NULL DEFAULT '{}',
            estado TEXT NOT NULL,
            etapa TEXT,
            progresso INTEGER NOT NULL DEFAULT 0,
            mensagem TEXT,
            erro TEXT,
            tentativas INTEGER NOT NULL DEFAULT 0,
            prioridade INTEGER NOT NULL DEFAULT 0,
            proxima_tentativa TEXT,
            trabalhador TEXT,
            sinal_de_vida TEXT,
            criado_em TEXT NOT NULL,
            iniciado_em TEXT,
            concluido_em TEXT,
            expira_em TEXT,
            apagado_em TEXT,
            objeto TEXT,
            url_video TEXT,
            custo_usd REAL,
            duracao_s REAL
        )""",
        """CREATE INDEX IF NOT EXISTS videos_fila ON videos (estado, prioridade, criado_em)""",
        """CREATE INDEX IF NOT EXISTS videos_cliente ON videos (cliente_id, criado_em)""",
        """CREATE INDEX IF NOT EXISTS videos_expira ON videos (expira_em)""",
        f"""CREATE TABLE IF NOT EXISTS eventos (
            id {serial},
            video_id TEXT NOT NULL,
            quando TEXT NOT NULL,
            tipo TEXT NOT NULL,
            texto TEXT NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS eventos_video ON eventos (video_id, id)""",
    ]


class Banco:
    """Uma conexão por linha de execução (o trabalhador roda vários vídeos ao mesmo tempo, cada um na sua)."""

    def __init__(self, url=None):
        self.url = url or os.environ.get("FABRICA_BANCO") or f"sqlite:///{RAIZ / 'fabrica.db'}"
        self.postgres = self.url.startswith(("postgres://", "postgresql://"))
        self._local = threading.local()
        self._trava_sqlite = threading.Lock()  # o SQLite aceita um escritor por vez: a fila se organiza por ela
        self.preparar()

    # ------------------------------------------------------------------------------------------------ conexão
    def _conexao(self):
        con = getattr(self._local, "con", None)
        if con is not None:
            return con
        if self.postgres:
            import psycopg

            con = psycopg.connect(self.url, autocommit=False)
        else:
            caminho = self.url.split("sqlite:///", 1)[1]
            con = sqlite3.connect(caminho, timeout=30, check_same_thread=False)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA busy_timeout=30000")
        self._local.con = con
        return con

    def fechar(self):
        con = getattr(self._local, "con", None)
        if con is not None:
            con.close()
            self._local.con = None

    def _sql(self, sql: str) -> str:
        return sql if self.postgres else sql.replace("%s", "?")

    @contextlib.contextmanager
    def transacao(self):
        """Tudo dentro do bloco entra junto ou nada entra. No SQLite, um escritor por vez."""
        con = self._conexao()
        trava = contextlib.nullcontext() if self.postgres else self._trava_sqlite
        with trava:
            try:
                if not self.postgres:
                    con.execute("BEGIN IMMEDIATE")
                yield _Cursor(self, con)
                con.commit()
            except BaseException:
                con.rollback()
                raise

    def executar(self, sql, params=()):
        with self.transacao() as c:
            return c.executar(sql, params)

    def um(self, sql, params=()):
        with self.transacao() as c:
            return c.um(sql, params)

    def todos(self, sql, params=()):
        with self.transacao() as c:
            return c.todos(sql, params)

    def preparar(self):
        with self.transacao() as c:
            for comando in _esquema(self.postgres):
                c.executar(comando)
            if c.um("SELECT versao FROM esquema") is None:
                c.executar("INSERT INTO esquema (versao) VALUES (%s)", (VERSAO_DO_ESQUEMA,))


class _Cursor:
    def __init__(self, banco, con):
        self.banco, self.con = banco, con

    def executar(self, sql, params=()):
        cur = self.con.cursor()
        cur.execute(self.banco._sql(sql), tuple(params))
        return cur.rowcount

    def todos(self, sql, params=()):
        cur = self.con.cursor()
        cur.execute(self.banco._sql(sql), tuple(params))
        if cur.description is None:
            return []
        nomes = [d[0] for d in cur.description]
        return [dict(zip(nomes, linha)) for linha in cur.fetchall()]

    def um(self, sql, params=()):
        linhas = self.todos(sql, params)
        return linhas[0] if linhas else None


def json_de(texto, padrao=None):
    try:
        return json.loads(texto) if texto else (padrao if padrao is not None else {})
    except (TypeError, ValueError):
        return padrao if padrao is not None else {}


_BANCO = None
_TRAVA = threading.Lock()


def banco() -> Banco:
    """O banco do processo (um só, criado na primeira vez)."""
    global _BANCO
    with _TRAVA:
        if _BANCO is None:
            _BANCO = Banco()
        return _BANCO
