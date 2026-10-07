"""Pasta de um projeto de vídeo e seus arquivos intermediários."""
import json
import shutil
from datetime import datetime
from pathlib import Path

from .config import RAIZ, carregar_perfil, config_geral

PROJETOS = RAIZ / "projetos"


class Projeto:
    def __init__(self, nome: str):
        self.nome = nome
        self.pasta = PROJETOS / nome
        arquivo = self.pasta / "projeto.json"
        if not arquivo.exists():
            raise SystemExit(f"O projeto '{nome}' não existe. Crie com fabrica novo {nome} --roteiro ... --perfil ...")
        self.dados = json.loads(arquivo.read_text(encoding="utf-8"))
        self.perfil = carregar_perfil(self.dados["perfil"])
        # voz e provedor de imagem escolhidos no editor valem só neste projeto, sem tocar no perfil do canal.
        # Ficam aqui, e não na api, para o terminal e o servidor usarem (e cobrarem) exatamente o mesmo.
        for secao in ("voz", "imagens"):
            override = self.dados.get(f"{secao}_override")
            if override:
                self.perfil[secao] = {**(self.perfil.get(secao) or {}), **override}
        self.config = config_geral()
        # ajustes do config.yaml que valem só neste projeto (o MCP cria projeto sem imagem de IA, por exemplo):
        # cada seção do config_override se mistura por cima da do config.yaml
        for secao, valores in (self.dados.get("config_override") or {}).items():
            atual = self.config.get(secao)
            self.config[secao] = {**atual, **valores} if isinstance(atual, dict) and isinstance(valores, dict) else valores

    @classmethod
    def criar(cls, nome: str, roteiro: str, perfil: str, offline: bool) -> "Projeto":
        pasta = PROJETOS / nome
        if pasta.exists():
            raise SystemExit(f"Já existe um projeto chamado '{nome}'.")
        pasta.mkdir(parents=True)
        shutil.copy(roteiro, pasta / "roteiro.txt")
        dados = {
            "nome": nome,
            "perfil": str(Path(perfil).resolve()),
            "offline": offline,
            "criado": datetime.now().isoformat(timespec="seconds"),
        }
        (pasta / "projeto.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        return cls(nome)

    @property
    def offline(self) -> bool:
        return bool(self.dados.get("offline"))

    def caminho(self, *partes: str) -> Path:
        """Caminho dentro do projeto, com a pasta mãe já criada."""
        p = self.pasta.joinpath(*partes)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def imagem(self, n: int) -> Path:
        return self.caminho("imagens", f"{n:04d}.png")

    def existe(self, nome: str) -> bool:
        return (self.pasta / nome).exists()

    def ler_json(self, nome: str):
        return json.loads((self.pasta / nome).read_text(encoding="utf-8"))

    def salvar_json(self, nome: str, dados) -> None:
        destino = self.caminho(nome)
        temporario = destino.with_name(destino.name + ".tmp")
        temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        temporario.replace(destino)

    def roteiro(self) -> str:
        """Texto narrado, já sem as marcações [SIMBOLO]."""
        return self._roteiro_e_marcadores()[0]

    def marcadores(self) -> list[dict]:
        """Marcações [SIMBOLO] e [TITULO] do roteiro, com tipo, texto e posição no texto narrado."""
        return self._roteiro_e_marcadores()[1]

    def _roteiro_e_marcadores(self):
        from . import texto as tx

        return tx.extrair_marcadores((self.pasta / "roteiro.txt").read_text(encoding="utf-8"))
