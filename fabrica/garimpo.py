"""Garimpo no YouTube: trechos de vídeos de verdade para as cenas que os bancos de imagem não cobrem.

O garimpo entra como um banco a mais (``bancos.FONTES["youtube"]``), então ele só é usado nos canais cujo
perfil tem ``youtube`` em ``midia_real.fontes_video``. Nenhum vídeo existente muda sem essa linha no perfil.

A busca devolve candidatos no formato dos outros bancos, e o arquivo só é baixado quando o candidato é
escolhido: um trecho de poucos segundos, nunca o vídeo inteiro.

Dois olhares: antes do download só existe a MINIATURA, e é ela que quem escolhe vê. O trecho baixado é um pedaço
sorteado do vídeo, então depois do download um quadro dele é descrito e julgado de novo
(``midia._conferir_o_trecho``): nota abaixo de ``NOTA_MINIMA`` ou texto de outro editor derrubam o trecho, e a cena
segue para a IA. Legenda ou tarja embaixo ganham uma chance: a faixa de baixo é cortada e o quadro é julgado de novo.

Direito de uso: a busca é só em vídeos com licença Creative Commons (a regra escrita em palhano/README.md: desligado
por padrão, trechos curtos, sem o som original, crédito automático). ``garimpo.so_creative_commons: false`` abre para
qualquer vídeo, como o Robô do Dotti faz, e aí o trecho é obra de terceiro: pode render reivindicação de direitos.
O registro guarda o canal e o segundo de cada trecho, para o CREDITS.txt do vídeo.
"""
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote_plus

from .util import duracao_audio, gravar_atomico, rodar

RAIZ = Path(__file__).resolve().parents[1]

# Vídeo curto demais é Short (em pé, e o corte não tem onde cair); longo demais é live ou aula inteira, em
# que o yt-dlp gasta tempo só para achar o trecho.
MIN_DURACAO = 25
MAX_DURACAO = 2400
TRECHO = 10.0  # segundos de cada trecho baixado; garimpo.segundos troca
PULO_DA_ABERTURA = 0.15  # o corte começa depois destes 15% do vídeo, para não cair na vinheta do canal
BUSCAS_POR_TERMO = 12  # candidatos pedidos ao YouTube por busca
FILTRO_CC = "EgIwAQ%3D%3D"  # o filtro "Creative Commons" da busca do YouTube
PRAZO_TRECHO = 180  # segundos para o trecho chegar; garimpo.prazo troca
NOTA_MINIMA = 64  # nota do quadro real para o trecho ficar; material de terceiro precisa ganhar o lugar
CORTE_EMBAIXO = 0.12  # fração da altura tirada de baixo quando o texto queimado é legenda ou tarja
# só a imagem: o som do vídeo de outro canal não tem o que fazer aqui. H.264 até 1080p é o que se emenda melhor
FORMATO = "bv*[height<=1080][vcodec^=avc1]/bv*[height<=1080]/b[height<=1080]"

# As contas de cookies ficam de fora por um tempo quando o YouTube reclama delas (uma conta no limite
# derruba todo download que usá-la). Castigo em segundos.
CASTIGO = 3600
_contas: dict = {}
_trava = threading.Lock()


class TrechoIndisponivel(OSError):
    """O trecho não veio. É OSError de propósito: quem baixa mídia trata OSError como download que falhou e
    segue para a próxima cena, e uma exceção de outro tipo derrubaria a fase de mídia inteira."""


# A fonte diz pelo título o que o vídeo costuma ter. 0: a cena acontecendo, sem ninguém falando para a câmera. 2: gente
# falando, que quase nunca serve de imagem. 3: nem é imagem do assunto, e não gasta download.
TIER_FILMAGEM = ("walking tour", "walk through", "walkthrough", "walk ", "b-roll", "broll", "footage", "drone", "aerial",
                 "timelapse", "time lapse", "pov", "no commentary", "4k tour", "tour", "stock video")
TIER_FALA = ("review", "explained", "interview", "podcast", "how to", "tutorial", "reaction", "vlog", "opinion", "debate",
             "unboxing", "explaining", "lecture")
TIER_FORA = ("sound effect", "sound effects", "sfx", "lyrics", "lyric video", "#shorts", "shorts", "trailer", "meme",
             "gameplay", "audiobook", "playlist", "music video", "full album", "karaoke", "asmr")


def tier(candidato: dict) -> int:
    titulo = f" {str(candidato.get('descricao') or '').lower()} "
    if any(marca in titulo for marca in TIER_FORA):
        return 3
    if any(marca in titulo for marca in TIER_FALA):
        return 2
    return 0 if any(marca in titulo for marca in TIER_FILMAGEM) else 1


# Quando o YouTube bloqueia o endereço, e não uma conta, trocar de conta não adianta: tudo espera um tempo.
IP_QUENTE = RAIZ / "garimpo_ip_quente.json"
ESPERA_DO_IP = 3600


def ip_quente() -> bool:
    try:
        return time.time() - float(json.loads(IP_QUENTE.read_text(encoding="utf-8")).get("quando") or 0) < ESPERA_DO_IP
    except (OSError, ValueError, AttributeError):
        return False


def marcar_ip_quente() -> None:
    try:
        gravar_atomico(IP_QUENTE, json.dumps({"quando": time.time()}))
    except OSError:
        pass


def _imprimivel(texto: str) -> str:
    return "".join(c for c in texto if c.isprintable())


def cfg_do_projeto(projeto) -> dict:
    """O garimpo deste projeto: o do config.yaml, o do perfil do canal por cima, e o do próprio vídeo por último (o
    Radar grava a escolha da Nova produção em ``config_override`` no projeto.json)."""
    do_video = ((getattr(projeto, "dados", None) or {}).get("config_override") or {}).get("garimpo") or {}
    return {**((getattr(projeto, "config", None) or {}).get("garimpo") or {}),
            **((getattr(projeto, "perfil", None) or {}).get("garimpo") or {}), **do_video}


def com_youtube(projeto, midia_real: dict) -> dict:
    """A seção midia_real do perfil com o YouTube nas fontes de vídeo, quando este vídeo pediu footage real
    (``garimpo.ligado``). Sem pedido volta igual: o perfil continua mandando."""
    if not cfg_do_projeto(projeto).get("ligado"):
        return midia_real
    fontes = list(midia_real.get("fontes_video") or ["pexels", "pixabay"])
    return {**midia_real, "fontes_video": fontes if "youtube" in fontes else [*fontes, "youtube"]}


def avisar_contas(cfg, log=print) -> None:
    """Diz no começo da busca como estão as contas. Sem conta o YouTube pode pedir login no meio do vídeo, e com uma
    só não há quem assuma quando ela bater no limite."""
    contas = contas_de_cookies(cfg)
    livres = _contas_livres(contas)
    if not contas:
        log("  garimpo: sem conta do YouTube (garimpo.cookies): se ele pedir login, o trecho falha e a cena segue sem")
    elif len(livres) == 1:
        log(f"  garimpo: só UMA conta pronta de {len(contas)}: se ela bater no limite, não há outra para assumir")
    elif not livres:
        log(f"  garimpo: as {len(contas)} conta(s) estão de castigo; os trechos vão sem conta")


PASTA_DE_CONTAS = RAIZ / "contas_youtube"


def contas_de_cookies(cfg=None) -> list:
    """Os arquivos de cookies disponíveis, em ordem de uso. Vazio quer dizer garimpar sem conta.

    Vem de ``garimpo.cookies`` no config (um caminho ou uma lista) ou da variável ``YOUTUBE_COOKIES``
    (caminhos separados por ponto e vírgula). Arquivo que não existe é ignorado em silêncio: uma conta
    desconectada não pode derrubar a produção."""
    bruto = (cfg or {}).get("cookies") or os.environ.get("YOUTUBE_COOKIES") or []
    if isinstance(bruto, str):
        bruto = [p for p in bruto.split(";") if p.strip()]
    contas = [Path(p).expanduser() for p in bruto if Path(p).expanduser().is_file()]
    return contas + sorted(PASTA_DE_CONTAS.glob("*.txt"))  # as conectadas pela tela do Radar


def _nome_da_conta(nome: str) -> str:
    limpo = re.sub(r"[^a-z0-9-]+", "-", str(nome or "").lower()).strip("-")[:40]
    if not limpo:
        raise ValueError("Dê um nome para a conta.")
    return limpo


def salvar_conta(nome: str, cookies: str) -> str:
    """Guarda o cookies.txt de uma conta em contas_youtube/, fora do Git. Recusa o que não é da conta do YouTube."""
    linhas = [l for l in str(cookies or "").splitlines() if l.strip() and not l.startswith("# ")]
    if not any("\t" in l and ("youtube.com" in l or "google.com" in l) for l in linhas):
        raise ValueError("Isso não parece um cookies.txt do YouTube (formato Netscape).")
    limpo = _nome_da_conta(nome)
    PASTA_DE_CONTAS.mkdir(exist_ok=True)
    gravar_atomico(PASTA_DE_CONTAS / f"{limpo}.txt", str(cookies))
    return limpo


def apagar_conta(nome: str) -> bool:
    arquivo = PASTA_DE_CONTAS / f"{_nome_da_conta(nome)}.txt"
    existia = arquivo.exists()
    arquivo.unlink(missing_ok=True)
    return existia


def listar_contas() -> dict:
    """O que a tela mostra: as contas, quais estão de castigo e se o endereço está barrado. Nunca os cookies."""
    livres = set(map(str, _contas_livres(sorted(PASTA_DE_CONTAS.glob("*.txt")))))
    contas = [{"nome": f.stem, "de_castigo": str(f) not in livres} for f in sorted(PASTA_DE_CONTAS.glob("*.txt"))]
    return {"contas": contas, "ip_quente": ip_quente()}


def testar_conta(nome: str) -> dict:
    """A conta está logada de verdade? O histórico só abre com login: é o que diferencia conta de cookie vencido."""
    arquivo = PASTA_DE_CONTAS / f"{_nome_da_conta(nome)}.txt"
    if not arquivo.exists():
        raise ValueError("Conta não encontrada.")
    with _copia_da_conta(arquivo) as copia:
        codigo, erro, _ = _rodar_com_prazo([sys.executable, "-m", "yt_dlp", "--quiet", "--no-warnings", "--simulate",
                                            "--flat-playlist", "--playlist-items", "1", "--cookies", str(copia),
                                            ":ythistory"], 60)
    return {"logada": codigo == 0, "motivo": "" if codigo == 0 else _motivo_do_erro(erro)}


def _contas_livres(contas) -> list:
    """As contas fora de castigo, na ordem em que foram dadas."""
    agora = time.monotonic()
    with _trava:
        return [arquivo for arquivo in contas if _contas.get(str(arquivo), 0) <= agora]


def _proxima_conta(contas):
    """A primeira conta fora de castigo, ou None quando todas estão castigadas (ou não há nenhuma)."""
    livres = _contas_livres(contas)
    return livres[0] if livres else None


def castigar(arquivo, segundos=CASTIGO):
    """Tira esta conta do garimpo por um tempo. O YouTube reclama por conta, não por máquina."""
    if arquivo:
        with _trava:
            _contas[str(arquivo)] = time.monotonic() + segundos


def _e_reclamacao_de_conta(erro: str) -> bool:
    """O erro é da conta (limite, bot, login), e não do vídeo?"""
    texto = erro.lower()
    return any(marca in texto for marca in (
        "sign in to confirm", "not a bot", "too many requests", "http error 429",
        "cookies are no longer valid", "account has been terminated", "please sign in"))


@contextmanager
def _copia_da_conta(conta):
    """Uma cópia descartável do arquivo de cookies. O yt-dlp GRAVA no arquivo que recebe ao terminar: com vários
    downloads ao mesmo tempo no original, um pisaria no outro e a conta perderia o login."""
    if not conta:
        yield None
        return
    pasta = tempfile.mkdtemp(prefix="garimpo-")
    try:
        copia = Path(pasta) / "cookies.txt"
        shutil.copyfile(conta, copia)
        yield copia
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def _miniatura(entrada, vid) -> str:
    """A miniatura grande do vídeo. A entrada da busca às vezes não traz nenhuma, e aí vale o endereço fixo
    do YouTube, que existe para todo vídeo público."""
    for m in reversed(entrada.get("thumbnails") or []):
        if m.get("url"):
            return m["url"]
    return f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"


def _licenca(canal: str, cc: bool) -> str:
    base = "Trecho do YouTube em Creative Commons" if cc else "Trecho do YouTube"
    return f"{base}, canal {canal}" if canal else base


def _inicio_do_trecho(duracao, segundos) -> float:
    """Onde o corte começa: depois da abertura, e longe do fim para o trecho inteiro caber."""
    cedo = max(2.0, duracao * PULO_DA_ABERTURA)
    tarde = max(cedo, duracao - segundos - 2.0)
    return round(random.uniform(cedo, tarde), 1) if tarde > cedo else cedo


def buscar(b, tipo, busca, cfg=None):
    """Candidatos do YouTube para esta busca, no formato dos outros bancos (``bancos.FONTES``).

    Só vídeo: uma miniatura de YouTube no lugar de uma foto de banco seria um print de player. O trecho que será
    baixado já vai anunciado em ``duracao``, porque é dele que a cena dispõe.

    Erro aqui nunca vira FonteIndisponivel, que desliga o banco pelo resto da execução: reclamação de conta é
    limite (o Buscador segue com a próxima conta ou espera) e o resto é ValueError (esta busca falha, as outras
    continuam)."""
    from .midia import FonteIndisponivel, LimiteAtingido

    if tipo != "video":
        return []
    if ip_quente():
        raise LimiteAtingido("YouTube", ESPERA_DO_IP)
    try:
        from yt_dlp import YoutubeDL
    except ImportError as erro:  # pragma: no cover - o pacote está no pyproject
        raise FonteIndisponivel(f"falta o yt-dlp ({erro})") from erro

    segundos = float((cfg or {}).get("segundos") or TRECHO)
    contas = contas_de_cookies(cfg)
    conta = _proxima_conta(contas)
    so_cc = (cfg or {}).get("so_creative_commons", True) is not False
    alvo = (f"https://www.youtube.com/results?search_query={quote_plus(busca[:120])}&sp={FILTRO_CC}" if so_cc
            else f"ytsearch{BUSCAS_POR_TERMO}:{busca[:120]}")
    try:
        with _copia_da_conta(conta) as copia:
            opcoes = {"quiet": True, "no_warnings": True, "noprogress": True, "ignoreerrors": False, "retries": 2,
                      "socket_timeout": 30, "extract_flat": "in_playlist", "skip_download": True,
                      "playlistend": BUSCAS_POR_TERMO}
            if copia:
                opcoes["cookiefile"] = str(copia)
            with YoutubeDL(opcoes) as yt:
                dados = yt.extract_info(alvo, download=False) or {}
    except Exception as erro:  # o yt-dlp levanta DownloadError e descendentes de Exception
        if _e_reclamacao_de_conta(str(erro)):
            castigar(conta)
            if not conta:
                marcar_ip_quente()  # sem conta nenhuma em jogo, quem o YouTube barrou foi o endereço
            raise LimiteAtingido("YouTube", 1 if _proxima_conta(contas) else CASTIGO) from erro
        raise ValueError(f"o YouTube não respondeu ({str(erro)[:120]})") from erro

    achados = []
    for entrada in dados.get("entries") or []:
        vid = entrada.get("id")
        duracao = entrada.get("duration")
        if not vid or not duracao or entrada.get("live_status") in ("is_live", "is_upcoming"):
            continue
        if not MIN_DURACAO <= float(duracao) <= MAX_DURACAO:
            continue
        canal = _imprimivel(entrada.get("channel") or entrada.get("uploader") or "")
        titulo = _imprimivel(entrada.get("title") or "")
        achados.append({
            "fonte": "youtube", "id": vid, "tipo": "video",
            "miniatura": _miniatura(entrada, vid),
            "arquivo": f"https://www.youtube.com/watch?v={vid}",
            "duracao": min(segundos, float(duracao)),  # a cena dispõe do trecho, não do vídeo inteiro
            "pagina": f"https://www.youtube.com/watch?v={vid}",
            "autor": canal,
            "licenca": _licenca(canal, so_cc),
            "descricao": titulo,
            "yt_duracao": float(duracao),  # só do garimpo, usado no download
            "yt_cc": so_cc,
        })
    # a ordem da busca fica entre os do mesmo tier: sort é estável
    return sorted((c for c in achados if tier(c) < 3), key=tier)


# ---------------------------------------------------------------------------------------------------
# A cota
#
# Sem freio, o garimpo tomaria toda cena em que achasse um trecho razoável, e o vídeo viraria uma colagem de
# material de terceiros. A cota persegue o ALVO de cenas com footage real, segue até o TETO só enquanto está
# rendendo, e para de vez quando gasta o ORÇAMENTO de downloads do vídeo.
#
# A busca de candidatos de TODAS as cenas acontece antes do primeiro download (midia._buscar_cenas), então o freio
# que vale é o da hora da escolha e o do download (midia._sem_youtube_se_a_cota_fechou e Cota.reservar). O da
# busca só poupa buscas numa retomada ou no tapa-buraco.
#
# O orçamento é do vídeo inteiro, sem fatia por terço. As cenas do tipo "ia" nascem assim no planejamento e não
# passam por aqui; as outras que não ganharem material continuam indo para a IA no fim, como já iam.
ALVO = 0.25               # fração das cenas que deveria ter trecho do YouTube
TETO = 0.40               # nunca passa disso, mesmo rendendo bem
DOWNLOADS_POR_CENA = 2.5  # orçamento de downloads do vídeo inteiro, por cena do roteiro
PISO_DE_RENDIMENTO = 0.15  # passado o alvo, só segue enquanto 15% dos downloads viram cena aceita
AMOSTRA_MINIMA = 10       # com menos downloads que isso nesta execução o rendimento não prova nada
ARQUIVO_DA_COTA = ("midia", "garimpo-cota.json")

_cotas: dict = {}
_trava_cota = threading.Lock()


class Cota:
    """O freio do garimpo num projeto. Compartilhada pelas cenas, que correm em paralelo.

    Na retomada ela herda do disco: as cenas que já têm trecho do YouTube contam para o alvo e os downloads já
    gastos contam para o orçamento. O rendimento olha só esta execução."""

    def __init__(self, projeto, cfg=None, log=print):
        cfg = cfg or {}
        self.projeto = projeto
        self.log = log
        self.alvo_fracao = float(cfg.get("alvo", ALVO))
        self.teto_fracao = float(cfg.get("teto", TETO))
        self.por_cena = float(cfg.get("downloads_por_cena", DOWNLOADS_POR_CENA))
        self.piso = float(cfg.get("piso_de_rendimento", PISO_DE_RENDIMENTO))
        self.desligada = cfg.get("cota") is False
        self._trava = threading.Lock()
        self._trava_disco = threading.Lock()
        self._cenas = 0
        self.em_voo = 0  # downloads reservados que ainda não viraram cena nem falharam
        self.aceitos = self._aceitos_no_disco()
        self.downloads = self._downloads_no_disco()
        self.aceitos_herdados = self.aceitos
        self.downloads_herdados = self.downloads
        self._avisou_fechada = False

    # ---- o que já está no disco -------------------------------------------------------------------
    def _lista_de_cenas(self) -> list:
        try:
            return (self.projeto.ler_json("cenas.json") or {}).get("cenas") or []
        except (OSError, ValueError):
            return []

    def _aceitos_no_disco(self) -> int:
        return sum(1 for c in self._lista_de_cenas() if ((c.get("midia") or {}).get("fonte")) == "youtube")

    def _caminho(self):
        return self.projeto.caminho(*ARQUIVO_DA_COTA)

    def _downloads_no_disco(self) -> int:
        try:
            return int(json.loads(self._caminho().read_text(encoding="utf-8")).get("downloads") or 0)
        except (OSError, ValueError, AttributeError):
            return 0

    def _gravar(self):
        with self._trava_disco:
            try:
                caminho = self._caminho()
                caminho.parent.mkdir(parents=True, exist_ok=True)
                gravar_atomico(caminho, json.dumps({"downloads": self.downloads, "aceitos": self.aceitos}))
            except OSError:
                pass  # o freio da execução continua valendo na memória; só a retomada perde a conta

    # ---- os números do vídeo ----------------------------------------------------------------------
    @property
    def cenas(self) -> int:
        """Quantas cenas o roteiro tem. Lido uma vez: o total não muda durante a busca."""
        if not self._cenas:
            self._cenas = len(self._lista_de_cenas())
        return self._cenas

    def _alvo(self) -> int:
        return max(1, round(self.cenas * self.alvo_fracao)) if self.cenas else 0

    def _teto(self) -> int:
        return max(1, round(self.cenas * self.teto_fracao)) if self.cenas else 0

    def _orcamento(self) -> int:
        return max(1, round(self.cenas * self.por_cena)) if self.cenas else 0

    def rendimento(self) -> float:
        """Quanto dos downloads DESTA execução virou cena. Herdar downloads sem herdar os aceitos, ou o contrário,
        faria a retomada parecer que não rende nada e fechar na primeira cena."""
        novos = self.downloads - self.downloads_herdados
        if novos < AMOSTRA_MINIMA:
            return 1.0
        return (self.aceitos - self.aceitos_herdados) / novos

    # ---- a decisão --------------------------------------------------------------------------------
    def _motivo_para_fechar(self, extra=0) -> str:
        if self.desligada or not self.cenas:
            return ""
        ocupadas = self.aceitos + self.em_voo + extra
        if ocupadas >= self._teto():
            return f"teto de {self._teto()} cena(s) com trecho do YouTube alcançado"
        if self.downloads + extra >= self._orcamento():
            return f"orçamento de {self._orcamento()} download(s) deste vídeo gasto"
        if ocupadas >= self._alvo() and self.rendimento() < self.piso:
            return (f"alvo de {self._alvo()} cena(s) alcançado e o garimpo parou de render"
                    f" ({self.aceitos - self.aceitos_herdados} de"
                    f" {self.downloads - self.downloads_herdados} downloads)")
        return ""

    def pode_garimpar(self, extra=0) -> tuple:
        """(pode, motivo). ``extra`` conta os trechos já escolhidos que ainda não começaram a baixar."""
        with self._trava:
            motivo = self._motivo_para_fechar(extra)
        return not motivo, motivo

    def reservar(self):
        """Ocupa uma vaga antes do download, de uma vez só, para downloads em paralelo não passarem juntos pelo
        último lugar. Levanta TrechoIndisponivel quando a cota fechou."""
        with self._trava:
            motivo = self._motivo_para_fechar()
            if motivo:
                raise TrechoIndisponivel(f"cota do garimpo: {motivo}")
            self.downloads += 1
            self.em_voo += 1
        self._gravar()

    def liberar(self):
        """O download reservado não virou cena. A vaga volta; o download continua gasto."""
        with self._trava:
            self.em_voo = max(0, self.em_voo - 1)

    def anotar_aceito(self):
        with self._trava:
            self.em_voo = max(0, self.em_voo - 1)
            self.aceitos += 1
        self._gravar()

    def devolver_aceito(self):
        """O trecho foi descartado depois de aceito (igual a outro do mesmo lote)."""
        with self._trava:
            self.aceitos = max(0, self.aceitos - 1)
        self._gravar()

    def avisar_se_fechou(self, motivo):
        """Diz no log, uma vez só, que o garimpo fechou. Uma linha por cena viraria centenas de linhas."""
        with self._trava:
            if self._avisou_fechada:
                return
            self._avisou_fechada = True
        self.log(f"  garimpo: fechado para as cenas seguintes -- {motivo}")

    def resumo(self) -> str:
        if not self.cenas:
            return "garimpo: sem cenas no disco ainda"
        herdado = f"; {self.aceitos_herdados} herdada(s) do disco" if self.aceitos_herdados else ""
        return (f"garimpo: {self.aceitos}/{self.cenas} cena(s) com trecho do YouTube"
                f" (alvo {self._alvo()}, teto {self._teto()}); {self.downloads} de {self._orcamento()}"
                f" download(s) do orçamento{herdado}")


def cota(projeto, cfg=None, log=print) -> Cota:
    """A cota deste projeto, uma só para todas as cenas (elas correm em paralelo)."""
    chave = str(getattr(projeto, "pasta", projeto))
    with _trava_cota:
        atual = _cotas.get(chave)
        if atual is None:
            atual = _cotas[chave] = Cota(projeto, cfg, log)
        return atual


def esquecer_cota(projeto):
    """Tira a cota da memória. Chamado no começo de cada busca: o servidor vive dias, e a conta de ontem não
    pode valer para as cenas de hoje. A conta no disco fica."""
    with _trava_cota:
        _cotas.pop(str(getattr(projeto, "pasta", projeto)), None)


# O que faz um candidato do YouTube ser vetado pelo texto que tem na imagem. Não é qualquer texto: a placa da
# loja e o rótulo do produto são a cena acontecendo. O que não pode entrar é o texto que OUTRO editor queimou no
# vídeo dele. O veto lê a descrição da MINIATURA, a única imagem vista antes do download: ele não vê o trecho, e
# miniatura costuma ter texto que o vídeo não tem.
MARCAS_DE_TEXTO_QUEIMADO = (
    "marca d'água", "marca d água", "marca de água", "watermark",
    "legenda", "subtítulo", "subtitulo", "subtitle", "closed caption",
    "logotipo do canal", "logo do canal", "nome do canal", "logotipo de canal",
    "inscreva-se", "se inscreva", "subscribe",
    "título do vídeo", "titulo do video", "texto editado", "sobreposto", "sobreposta",
    "lower third", "tarja",
)
SEM_TEXTO = ("nenhum", "nenhuma", "sem ", "não há", "nao ha", "none", "no text", "n/a")
MARCAS_DE_BAIXO = ("legenda", "subtítulo", "subtitulo", "subtitle", "closed caption", "tarja", "lower third")


def vem_de_baixo(motivo: str) -> bool:
    """O texto vetado costuma ficar na faixa de baixo, e cortá-la pode salvar o trecho?"""
    return any(marca in str(motivo).lower() for marca in MARCAS_DE_BAIXO)


def texto_queimado(frase, cfg=None) -> str:
    """O motivo do veto quando a descrição fala de texto queimado na imagem, ou "" quando não há nada a vetar.

    Lê o campo "Texto visível" que já vem na descrição de cada candidato (``compor_o_que_se_ve``), sem chamada a
    mais. Só existe descrição com ``midia.conferir_na_captura`` ligado: sem ele o veto não roda.
    ``garimpo.vetar_texto: false`` no config desliga."""
    if (cfg or {}).get("vetar_texto") is False:
        return ""
    for parte in re.split(r"\.\s+", str(frase or "")):
        rotulo, _, valor = parte.partition(":")
        if "texto" not in rotulo.lower():
            continue
        valor = valor.strip().lower()
        if valor.startswith(SEM_TEXTO):
            continue
        for marca in MARCAS_DE_TEXTO_QUEIMADO:
            if marca in valor:
                return valor[:80]
    return ""


def _comando_do_trecho(candidato, destino, inicio, fim, conta) -> list:
    saida = str(Path(destino).with_suffix("")) + ".%(ext)s"
    # --print: a busca nem sempre traz o canal, e o crédito precisa dele
    comando = [sys.executable, "-m", "yt_dlp", "--quiet", "--no-warnings", "--no-progress", "--no-playlist",
               "--no-simulate", "--print", "%(channel)s",
               "--force-overwrites", "--socket-timeout", "30", "--retries", "2", "-f", FORMATO,
               "--remux-video", "mp4", "--force-keyframes-at-cuts",
               "--download-sections", f"*{inicio:.1f}-{fim:.1f}", "-o", saida]
    if conta:
        comando += ["--cookies", str(conta)]
    return comando + [candidato["arquivo"]]


def _rodar_com_prazo(comando, prazo) -> tuple:
    """(código de saída, erro, saída). O yt-dlp roda em outro processo porque só assim dá para matá-lo: um vídeo que chega
    aos pouquinhos seguraria a fila inteira, e dentro deste processo não há como parar o ffmpeg que ele abriu."""
    processo = subprocess.Popen(comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace")
    try:
        saida, erro = processo.communicate(timeout=prazo)
    except subprocess.TimeoutExpired as estouro:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(processo.pid)], capture_output=True)
        else:
            processo.kill()
        processo.communicate()
        raise TrechoIndisponivel(f"o trecho passou de {prazo:.0f} s para chegar") from estouro
    return processo.returncode, erro or "", saida or ""


def _motivo_do_erro(texto: str) -> str:
    linhas = [l.strip() for l in str(texto).splitlines() if l.strip()]
    erros = [l for l in linhas if l.startswith("ERROR")]
    return ((erros or linhas or ["sem mensagem"])[-1])[:160]


def baixar_trecho(candidato, destino, cfg=None, log=print) -> dict:
    """Baixa um trecho do vídeo do candidato em ``destino`` (mp4). Devolve onde o trecho começa e termina.

    Tenta cada conta fora de castigo e por último sem conta. Reclamação de conta castiga a conta e passa para a
    seguinte; erro do vídeo (apagado, bloqueado) não é culpa da conta e encerra na hora. Tudo que falha aqui sai
    como TrechoIndisponivel. O trecho é cortado em quadro-chave, senão a emenda com os outros clipes pisca."""
    cfg = cfg or {}
    segundos = float(cfg.get("segundos") or TRECHO)
    prazo = float(cfg.get("prazo") or PRAZO_TRECHO)
    duracao = float(candidato.get("yt_duracao") or 0) or segundos + 4.0
    segundos = min(segundos, max(2.0, duracao - 2.0))
    inicio = _inicio_do_trecho(duracao, segundos)
    fim = min(duracao, inicio + segundos)
    destino = Path(destino)

    if ip_quente():
        raise TrechoIndisponivel("o YouTube barrou este endereço; o garimpo volta em até uma hora")
    motivo, saida = "", ""
    for conta in [*_contas_livres(contas_de_cookies(cfg)), None]:
        with _copia_da_conta(conta) as copia:
            codigo, erro, saida = _rodar_com_prazo(_comando_do_trecho(candidato, destino, inicio, fim, copia), prazo)
        if codigo == 0:
            break
        motivo = _motivo_do_erro(erro)
        if conta is None and _e_reclamacao_de_conta(erro):
            marcar_ip_quente()
        if not (conta and _e_reclamacao_de_conta(erro)):
            raise TrechoIndisponivel(f"o garimpo não baixou {candidato.get('id')}: {motivo}")
        castigar(conta)
        log(f"  garimpo: a conta {Path(conta).name} ficou de fora por uma hora ({motivo[:80]})")
    else:
        raise TrechoIndisponivel(f"o garimpo não baixou {candidato.get('id')}: {motivo}")

    if not destino.exists():
        raise TrechoIndisponivel("o garimpo baixou, mas o arquivo do trecho não apareceu")
    canal = next((_imprimivel(l).strip() for l in saida.splitlines() if l.strip() and l.strip() != "NA"), "")
    return {"inicio": inicio, "fim": fim, "canal": canal}


def em_pe(arquivo) -> bool:
    """O vídeo é mais alto que largo? Cortado para a tela deitada, sobra um pedaço pequeno e sem foco."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(arquivo)], capture_output=True, text=True)
    try:
        largura, altura = (int(x) for x in r.stdout.strip().split(",")[:2])
    except ValueError:
        return False
    return altura > largura


def guardar_prova(projeto, cena, registro, decisao: str, motivo: str = "", nota=None) -> None:
    """O quadro julgado e o que se decidiu sobre ele, em garimpo_provas/, para dar para conferir depois.
    Guarda também o que foi reprovado: é ali que se vê se o veto está certo. Nunca para a produção."""
    try:
        pasta = projeto.caminho("garimpo_provas")
        pasta.mkdir(parents=True, exist_ok=True)
        capa = projeto.pasta / str(registro.get("capa") or "")
        quadro = pasta / f"c{cena['n']:04d}_{registro.get('id')}.jpg"
        if capa.is_file():
            shutil.copy2(capa, quadro)
        with open(pasta / "decisoes.jsonl", "a", encoding="utf-8") as saida:
            saida.write(json.dumps({"cena": cena["n"], "id": registro.get("id"), "pagina": registro.get("pagina"),
                                    "decisao": decisao, "motivo": motivo, "nota": nota, "quando": time.time()},
                                   ensure_ascii=False) + "\n")
    except OSError:
        pass


def capa_do_trecho(arquivo, capa) -> None:
    """Grava em ``capa`` um quadro do meio do trecho. A miniatura do YouTube não serve de capa: ela é uma arte feita
    para o clique, e a comparação de repetidas e o Corrigir julgariam a arte em vez do que entrou na cena."""
    try:
        meio = duracao_audio(arquivo) / 2
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{meio:.2f}", "-i", arquivo, "-frames:v", "1",
               "-q:v", "3", capa])
    except (RuntimeError, ValueError, KeyError) as erro:
        raise TrechoIndisponivel(f"o trecho veio sem imagem legível ({str(erro)[-120:]})") from erro


def cortar_embaixo(arquivo, capa, fracao=CORTE_EMBAIXO) -> None:
    """Tira a faixa de baixo do trecho, onde costuma ficar a legenda ou a tarja de outro editor, e refaz a capa. A
    imagem volta ao tamanho de antes: quem emenda os clipes não precisa saber que ela foi cortada."""
    arquivo = Path(arquivo)
    temporario = arquivo.with_name(arquivo.stem + ".cortado.mp4")
    try:
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", arquivo, "-vf",
               f"crop=iw:trunc(ih*{1 - fracao:.2f}/2)*2:0:0,scale=1920:1080:force_original_aspect_ratio=increase,"
               "crop=1920:1080", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-an",
               temporario])
        os.replace(temporario, arquivo)
    except (RuntimeError, OSError) as erro:
        temporario.unlink(missing_ok=True)
        raise TrechoIndisponivel(f"não deu para cortar o trecho ({str(erro)[-120:]})") from erro
    capa_do_trecho(arquivo, capa)
