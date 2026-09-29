"""Configuração geral, perfis de canal e chaves de API."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")


def carregar_yaml(caminho: Path) -> dict:
    with open(caminho, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def config_geral() -> dict:
    return carregar_yaml(RAIZ / "config.yaml")


def caminho_relativo(caminho: str | Path) -> Path:
    """Caminhos relativos nos perfis partem da pasta da fábrica."""
    p = Path(caminho).expanduser()
    return p if p.is_absolute() else RAIZ / p


# Nestes campos de texto o perfil filho acrescenta ao da base em vez de substituir, para as regras gerais
# da base continuarem valendo e o filho só escrever o que é do nicho. Um texto que comece com
# SUBSTITUIR: troca o da base por inteiro.
CAMPOS_QUE_SOMAM = ("diretrizes", "orientacao")
MARCA_SUBSTITUIR = "SUBSTITUIR:"


def _mesclar(base: dict, filho: dict) -> dict:
    """O filho sobrescreve a base. Blocos (dicionários) se mesclam por dentro, listas e valores simples são trocados."""
    resultado = dict(base)
    for chave_, valor in filho.items():
        atual = base.get(chave_)
        if isinstance(valor, dict) and isinstance(atual, dict):
            resultado[chave_] = _mesclar(atual, valor)
        elif chave_ in CAMPOS_QUE_SOMAM and isinstance(valor, str) and isinstance(atual, str):
            if valor.lstrip().startswith(MARCA_SUBSTITUIR):
                resultado[chave_] = valor.lstrip()[len(MARCA_SUBSTITUIR):].strip()
            else:
                resultado[chave_] = atual.rstrip() + "\n\n" + valor.strip()
        else:
            resultado[chave_] = valor
    return resultado


def carregar_perfil(caminho: str | Path, _visitados: tuple = ()) -> dict:
    """Lê o perfil. Se ele tiver `base: outro-perfil.yaml`, parte dos valores da base e aplica os dele por cima.

    A base é procurada primeiro ao lado do perfil e depois na pasta da fábrica. O campo `base` some do resultado."""
    destino = caminho_relativo(caminho).resolve()
    if destino in _visitados:
        raise SystemExit(f"O perfil {destino.name} herda de si mesmo, direta ou indiretamente.")
    perfil = carregar_yaml(destino)
    base = perfil.pop("base", None)
    if not base:
        return perfil
    ao_lado = destino.parent / base
    origem = ao_lado if ao_lado.exists() else caminho_relativo(base)
    if not origem.exists():
        raise SystemExit(f"O perfil {destino.name} herda de {base}, que não existe.")
    return _mesclar(carregar_perfil(origem, _visitados + (destino,)), perfil)


def chave(nome: str) -> str:
    valor = os.environ.get(nome, "").strip()
    if not valor:
        raise SystemExit(f"Falta a chave {nome}. Copie .env.exemplo para .env e preencha.")
    return valor
