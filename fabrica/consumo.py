"""Consumo do TipLabs no OpenRouter: cada chamada é anotada na hora, e a planilha se refaz sozinha.

Pedido do usuário em 2026-10-09: "a cada consumo no OpenRouter, deve ser registrado na planilha". Antes o consumo só
ficava nos uso_*.json de cada projeto: projeto apagado ou entregue levava o registro junto (dos US$ 19,31 que a conta
gastou até 2026-10-09, só US$ 8,02 estavam nos projetos que existiam).

- **Registro central** (`registrar`): uma linha por chamada em `relatorios/openrouter_consumo.csv`, fora dos
  projetos: data, projeto, tipo (texto, imagem, transcrição, voz), etapa, modelo, gratuito, tokens e custo. Chamado
  pelos registros de sempre: `openrouter_local._registrar` (texto e visão, sem as rotas da AIMLAPI),
  `jev_local._registrar` (o juiz), `custos_reais.registrar` (imagem e transcrição com provedor OpenRouter) e a voz
  grátis da Fish (`narracao`). Nunca para a fábrica: falhou, segue sem anotar.
- **Histórico** (`importar_historico`, `fabrica consumo --importar`): traz o que está nos projetos, sem repetir o que
  já está no registro (pela data, projeto, modelo, etapa e custo). Pode rodar de novo à vontade.
- **Planilha viva** (`gerar_planilha`): `relatorios/consumo_openrouter.xlsx`, refeita do registro até
  `ATRASO` segundos depois da última chamada (`agendar`) e no fim de cada comando (`atexit`), com o total oficial da
  conta (GET /api/v1/key e /credits, o último guardado em `openrouter_oficial.json` se a consulta falhar). Aberta no
  Excel, o Windows trava o arquivo: a fábrica tenta de novo depois, sem perder nada (o registro é o CSV).
  Abas: Resumo, Custo diário, Custo por API, Diário por API, Por etapa, Por projeto e Chamadas. As contas são
  fórmulas sobre a aba Chamadas, calculadas por quem abre (sem Excel nem LibreOffice aqui para gravar os valores).
"""
import atexit
import csv
import glob
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from .config import RAIZ

PASTA = RAIZ / "relatorios"
REGISTRO = PASTA / "openrouter_consumo.csv"
PLANILHA = PASTA / "consumo_openrouter.xlsx"
OFICIAL = PASTA / "openrouter_oficial.json"
CAMPOS = ["quando", "projeto", "tipo", "etapa", "modelo", "gratuito", "tokens_lidos", "tokens_escritos", "custo_usd"]
ATRASO = 120  # segundos de calma depois da última chamada antes de refazer a planilha
_trava = threading.Lock()
_relogio = None
_pendente = False


def gratuito(modelo) -> bool:
    m = str(modelo or "")
    return m.endswith(":free") or m.startswith("stealth/") or m == "openrouter/free"


def _nome_do_projeto(projeto) -> str:
    return getattr(projeto, "nome", None) or (str(projeto) if projeto else "(fora de projeto)")


def _escrever(linhas) -> None:
    PASTA.mkdir(parents=True, exist_ok=True)
    novo = not REGISTRO.exists()
    for tentativa in range(5):
        try:
            with _trava, open(REGISTRO, "a", encoding="utf-8", newline="") as f:
                escritor = csv.DictWriter(f, fieldnames=CAMPOS)
                if novo:
                    escritor.writeheader()
                escritor.writerows(linhas)
            return
        except PermissionError:
            time.sleep(0.2 * (tentativa + 1))  # outro processo da fábrica escrevendo ao mesmo tempo


def registrar(projeto, tipo, etapa, modelo, lidos=0, escritos=0, custo=0.0) -> None:
    """Anota uma chamada ao OpenRouter no registro central e agenda a planilha. Nunca levanta erro."""
    try:
        _escrever([{"quando": datetime.now().isoformat(timespec="seconds"), "projeto": _nome_do_projeto(projeto),
                    "tipo": tipo, "etapa": etapa or "", "modelo": modelo or "",
                    "gratuito": "Sim" if gratuito(modelo) else "Não", "tokens_lidos": int(lidos or 0),
                    "tokens_escritos": int(escritos or 0), "custo_usd": float(custo or 0)}])
        agendar()
    except Exception:  # noqa: BLE001 - anotar o consumo nunca para um vídeo
        pass


def ler() -> list:
    if not REGISTRO.exists():
        return []
    with _trava, open(REGISTRO, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _chave(r) -> tuple:
    return (str(r["quando"])[:19], r["projeto"], r["modelo"], r["etapa"], round(float(r["custo_usd"] or 0), 9))


def importar_historico(log=print) -> int:
    """Traz para o registro o que os projetos têm e ele ainda não. Devolve quantas linhas entraram."""
    vistas = {_chave(r) for r in ler()}
    novas = []
    pastas = RAIZ / "projetos"
    for arq in sorted(glob.glob(str(pastas / "*/uso_openrouter.json")) + glob.glob(str(pastas / "*/uso_jev.json"))):
        nome = Path(arq).parent.name
        for r in json.load(open(arq, encoding="utf-8")):
            modelo = r.get("modelo") or ""
            if modelo.startswith("aimlapi:"):
                continue  # outra conta
            novas.append({"quando": r["quando"], "projeto": nome, "tipo": "texto", "etapa": r.get("etapa") or "",
                          "modelo": modelo, "gratuito": "Sim" if gratuito(modelo) else "Não",
                          "tokens_lidos": int(r.get("tokens_lidos") or 0),
                          "tokens_escritos": int(r.get("tokens_escritos") or 0),
                          "custo_usd": float(r.get("custo_usd") or 0)})
    for arq in sorted(glob.glob(str(pastas / "*/custos_reais.json"))):
        nome = Path(arq).parent.name
        for r in json.load(open(arq, encoding="utf-8")):
            tipo, modelo, etapa = _da_conta(r.get("categoria"), r.get("detalhes") or {})
            if not tipo:
                continue
            novas.append({"quando": r["quando"], "projeto": nome, "tipo": tipo, "etapa": etapa, "modelo": modelo,
                          "gratuito": "Não", "tokens_lidos": 0, "tokens_escritos": 0,
                          "custo_usd": float(r.get("valor_usd") or 0)})
    novas = [r for r in novas if _chave(r) not in vistas]
    novas.sort(key=lambda r: r["quando"])
    if novas:
        _escrever(novas)
    log(f"  histórico: {len(novas)} chamada(s) dos projetos entraram no registro")
    return len(novas)


def _da_conta(categoria, detalhes) -> tuple:
    """(tipo, modelo, etapa) de um gasto do custos_reais.json que passou pelo OpenRouter; senão (None, ...)."""
    if categoria == "imagem" and detalhes.get("provedor") == "openrouter":
        return "imagem", detalhes.get("modelo") or "", "imagem de IA"
    if detalhes.get("provedor") == "fish" and detalhes.get("transcricao"):
        from . import fish
        return "transcrição", fish.config().get("transcricao") or fish.TRANSCRICAO_PADRAO, "tempo das palavras da voz da Fish"
    return None, "", ""


def registrar_custo(projeto, categoria, detalhes, valor) -> None:
    """Gancho do custos_reais.registrar: anota só o que passou pelo OpenRouter (não a Kie, não a GenAIPro)."""
    tipo, modelo, etapa = _da_conta(categoria, detalhes or {})
    if tipo:
        registrar(projeto, tipo, etapa, modelo, custo=valor)


# ------------------------------------------------------------------ planilha viva

def agendar() -> None:
    """Refaz a planilha ATRASO segundos depois da última chamada (milhares de chamadas por vídeo: uma vez por calma)."""
    global _relogio, _pendente
    _pendente = True
    if _relogio is not None and _relogio.is_alive():
        return
    _relogio = threading.Timer(ATRASO, _no_relogio)
    _relogio.daemon = True
    _relogio.start()


def _no_relogio():
    global _relogio
    _relogio = None
    if not gerar_planilha(log=lambda *_: None):
        agendar()  # o arquivo estava aberto no Excel: tenta de novo depois


@atexit.register
def _ao_sair():
    if _pendente:
        try:
            gerar_planilha(log=lambda *_: None)
        except Exception:  # noqa: BLE001
            pass


def _oficial():
    """O total da conta na OpenRouter; sem resposta, o último guardado."""
    import httpx
    from . import openrouter_local

    try:
        h = {"Authorization": f"Bearer {openrouter_local._chave()}"}
        chave = httpx.get("https://openrouter.ai/api/v1/key", headers=h, timeout=20).json()["data"]
        creditos = httpx.get("https://openrouter.ai/api/v1/credits", headers=h, timeout=20).json()["data"]
        dados = {"chave": {k: chave.get(k) for k in ("usage", "usage_monthly", "usage_weekly", "usage_daily", "limit",
                                                     "limit_remaining")},
                 "creditos": {"total_credits": creditos.get("total_credits")},
                 "consulta": datetime.now().strftime("%d/%m/%Y %H:%M")}
        PASTA.mkdir(parents=True, exist_ok=True)
        OFICIAL.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        return dados
    except Exception:  # noqa: BLE001
        if OFICIAL.exists():
            return json.loads(OFICIAL.read_text(encoding="utf-8"))
        return {"chave": {"usage": 0, "usage_monthly": 0, "usage_weekly": 0, "usage_daily": 0, "limit": 0,
                          "limit_remaining": 0}, "creditos": {"total_credits": 0}, "consulta": "sem consulta"}


def gerar_planilha(log=print) -> bool:
    """Refaz a planilha do registro. False se o arquivo estava aberto (o Windows trava) e não deu para gravar."""
    global _pendente
    _pendente = False
    if not REGISTRO.exists():
        return True
    linhas = []
    for r in ler():
        try:
            linhas.append({"quando": datetime.fromisoformat(r["quando"]), "projeto": r["projeto"], "tipo": r["tipo"],
                           "etapa": r["etapa"], "modelo": r["modelo"], "lidos": int(r["tokens_lidos"] or 0),
                           "escritos": int(r["tokens_escritos"] or 0), "custo": float(r["custo_usd"] or 0)})
        except (KeyError, ValueError):
            continue  # linha cortada por uma queda no meio da escrita
    if not linhas:
        return True
    linhas.sort(key=lambda x: x["quando"])
    oficial = _oficial()
    temporario = PLANILHA.with_name(PLANILHA.stem + f".{os.getpid()}.tmp.xlsx")
    _montar(linhas, oficial["chave"], oficial["creditos"], oficial["consulta"], temporario)
    try:
        os.replace(temporario, PLANILHA)
    except PermissionError:
        temporario.unlink(missing_ok=True)
        _pendente = True
        log(f"  a planilha está aberta em outro programa: ela se atualiza quando for fechada ({PLANILHA})")
        return False
    log(f"  planilha do consumo atualizada: {len(linhas)} chamada(s) em {PLANILHA}")
    return True



# ------------------------------------------------------------------ Google Planilhas (atualiza sozinho)
# Pedido do usuário em 2026-10-09: a planilha subida no Google Planilhas tem de se atualizar sozinha. A fábrica serve o
# registro em /consumo/openrouter.csv e o total oficial em /consumo/oficial.csv (pelo túnel, consumo.url_publica), com
# uma chave só de leitura e só para isso (CONSUMO_PLANILHA_TOKEN no .env, criada aqui, nunca o token do editor). O
# modelo para o Google (gerar_modelo_google) puxa os dois com IMPORTDATA, que o Google busca de novo sozinho (mais ou
# menos de hora em hora), e agrupa com QUERY: dia, modelo e etapa novos aparecem sem gerar arquivo de novo.

COLUNAS_CSV = ["data", "hora", "projeto", "tipo", "etapa", "modelo", "gratuito", "paga", "tokens_lidos",
               "tokens_escritos", "custo_usd"]


def token_da_planilha() -> str:
    """A chave só de leitura do consumo. Criada na primeira vez e guardada no .env."""
    import secrets

    atual = os.environ.get("CONSUMO_PLANILHA_TOKEN", "").strip()
    if atual:
        return atual
    novo = secrets.token_urlsafe(24)
    with open(RAIZ / ".env", "a", encoding="utf-8") as f:
        f.write(f"\n# chave só de leitura da planilha de consumo no Google Planilhas (fabrica/consumo.py)\n"
                f"CONSUMO_PLANILHA_TOKEN={novo}\n")
    os.environ["CONSUMO_PLANILHA_TOKEN"] = novo
    return novo


def chave_confere(recebida) -> bool:
    import secrets

    esperada = os.environ.get("CONSUMO_PLANILHA_TOKEN", "").strip()
    return bool(esperada) and bool(recebida) and secrets.compare_digest(str(recebida).strip(), esperada)


def csv_do_registro(desde=None) -> str:
    """O registro no formato que o IMPORTDATA lê bem: data e hora separadas, números com ponto (lidos em en_US)."""
    import io

    saida = io.StringIO()
    escritor = csv.writer(saida, lineterminator="\n")
    escritor.writerow(COLUNAS_CSV)
    for r in ler():
        quando = str(r.get("quando") or "")
        if len(quando) < 10 or (desde and quando[:10] < desde):
            continue
        try:
            custo = float(r.get("custo_usd") or 0)
        except ValueError:
            continue
        gratis = r.get("gratuito") == "Sim"
        escritor.writerow([quando[:10], quando[11:16], r.get("projeto", ""), r.get("tipo", ""), r.get("etapa", ""),
                           r.get("modelo", ""), "Sim" if gratis else "Não", 0 if gratis else 1,
                           r.get("tokens_lidos") or 0, r.get("tokens_escritos") or 0, f"{custo:.9f}".rstrip("0").rstrip(".") or "0"])
    return saida.getvalue()


def csv_oficial() -> str:
    """O total oficial da conta (o último consultado), em duas colunas: item e valor."""
    dados = _oficial()
    chave, creditos = dados.get("chave") or {}, dados.get("creditos") or {}
    linhas = [("item", "valor"), ("gasto_total", chave.get("usage")), ("gasto_mes", chave.get("usage_monthly")),
              ("gasto_semana", chave.get("usage_weekly")), ("gasto_hoje", chave.get("usage_daily")),
              ("creditos_comprados", creditos.get("total_credits")), ("limite_mensal", chave.get("limit")),
              ("sobra_do_limite", chave.get("limit_remaining")), ("consultado_em", dados.get("consulta", ""))]
    return "".join(f"{a},{'' if b is None else b}\n" for a, b in linhas)


def gerar_modelo_google(url_publica, destino=None) -> Path:
    """O arquivo para importar no Google Planilhas (Arquivo > Importar > Substituir planilha). Só funciona lá:
    IMPORTDATA e QUERY são do Google, o Excel não tem."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    destino = destino or PASTA / "consumo_openrouter_google.xlsx"
    chave = token_da_planilha()
    base = str(url_publica).rstrip("/")
    url_chamadas = f"{base}/consumo/openrouter.csv?chave={chave}"
    url_oficial = f"{base}/consumo/oficial.csv?chave={chave}"
    f_titulo = Font(name="Arial", size=14, bold=True)
    f_sub = Font(name="Arial", size=9, italic=True, color="595959")
    f_cab = Font(name="Arial", size=10, bold=True, color="FFFFFF")
    f_rot = Font(name="Arial", size=10)
    f_sec = Font(name="Arial", size=11, bold=True, color="1F3864")
    azul = PatternFill("solid", fgColor="1F3864")
    USD, USD6, INT = '"US$" #,##0.00', '"US$" 0.000000', "#,##0"

    wb = Workbook()
    rs = wb.active
    rs.title = "Resumo"
    ch = wb.create_sheet("Chamadas")
    ch["A1"] = f'=IMPORTDATA("{url_chamadas}", ",", "en_US")'
    for col, w in zip("ABCDEFGHIJK", (11, 7, 30, 11, 36, 42, 9, 6, 12, 12, 12)):
        ch.column_dimensions[col].width = w

    def aba(nome, titulo, sub, formula, larguras, formatos):
        ws = wb.create_sheet(nome)
        ws["A1"], ws["A2"], ws["A4"] = titulo, sub, formula
        ws["A1"].font, ws["A2"].font = f_titulo, f_sub
        for k, w in enumerate(larguras):
            ws.column_dimensions[chr(65 + k)].width = w
        for col, fmt in formatos.items():
            for i in range(5, 1500):
                ws[f"{col}{i}"].number_format = fmt
        for k in range(len(larguras)):
            c = ws.cell(4 if k else 4, k + 1)
            c.font, c.fill = f_cab, azul
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[4].height = 30
        ws.freeze_panes = "A5"
        return ws

    q = "Chamadas!A:K"
    aba("Custo diário", "Custo diário no OpenRouter", "Atualiza sozinho com a aba Chamadas.",
        f'=QUERY({q},"select A, count(A), sum(H), sum(K), sum(K)/count(A) where A is not null group by A order by A '
        f"label A 'Data', count(A) 'Chamadas', sum(H) 'Chamadas pagas', sum(K) 'Custo do dia (US$)', "
        f"sum(K)/count(A) 'Custo por chamada (US$)'\",1)",
        [13, 12, 14, 18, 22], {"A": "dd/mm/yyyy", "B": INT, "C": INT, "D": USD, "E": USD6})
    aba("Custo por API", "Custo por API (modelo)", "Da mais cara para a mais barata.",
        f'=QUERY({q},"select F, max(D), max(G), count(F), sum(I), sum(J), sum(K), sum(K)/count(F), min(A), max(A) '
        f"where F is not null group by F order by sum(K) desc label F 'API (modelo)', max(D) 'Tipo', "
        f"max(G) 'Gratuito?', count(F) 'Chamadas', sum(I) 'Tokens lidos', sum(J) 'Tokens escritos', "
        f"sum(K) 'Custo total (US$)', sum(K)/count(F) 'Custo por chamada (US$)', min(A) 'Primeiro uso', "
        f"max(A) 'Último uso'\",1)",
        [44, 12, 10, 11, 14, 14, 16, 20, 13, 13],
        {"D": INT, "E": INT, "F": INT, "G": USD, "H": USD6, "I": "dd/mm/yyyy", "J": "dd/mm/yyyy"})
    aba("Diário por API", "Custo por dia e por API (US$)", "Só as chamadas com custo.",
        f"=QUERY({q},\"select A, sum(K) where A is not null and K > 0 group by A pivot F label A 'Data'\",1)",
        [13] + [18] * 10, {**{"A": "dd/mm/yyyy"}, **{chr(66 + k): USD for k in range(12)}})
    aba("Por etapa", "Custo por etapa da fábrica", "O que cada etapa consumiu.",
        f'=QUERY({q},"select E, count(E), sum(H), sum(K), sum(K)/count(E) where E is not null group by E '
        f"order by sum(K) desc label E 'Etapa da fábrica', count(E) 'Chamadas', sum(H) 'Chamadas pagas', "
        f"sum(K) 'Custo total (US$)', sum(K)/count(E) 'Custo por chamada (US$)'\",1)",
        [44, 11, 14, 16, 20], {"B": INT, "C": INT, "D": USD, "E": USD6})
    aba("Por projeto", "Custo por projeto (vídeo)", "Projetos apagados continuam aqui: o registro é central.",
        f'=QUERY({q},"select C, count(C), sum(K), sum(K)/count(C) where C is not null group by C '
        f"order by sum(K) desc label C 'Projeto', count(C) 'Chamadas', sum(K) 'Custo total (US$)', "
        f"sum(K)/count(C) 'Custo por chamada (US$)'\",1)",
        [40, 11, 16, 20], {"B": INT, "C": USD, "D": USD6})

    rs["A1"], rs["A2"] = "Consumo do TipLabs no OpenRouter", ("Atualiza sozinho: o Google busca o registro da fábrica "
                                                              "de novo mais ou menos de hora em hora.")
    rs["A1"].font, rs["A2"].font = f_titulo, f_sub
    rs["E1"] = f'=IMPORTDATA("{url_oficial}", ",", "en_US")'
    rs["E1"].font = f_sub
    of = lambda item: f'=IFERROR(VLOOKUP("{item}",$E:$F,2,FALSE),0)'
    itens = [("Total oficial da conta (OpenRouter)", None, None),
             ("Gasto total desde o início", of("gasto_total"), USD), ("Gasto no mês", of("gasto_mes"), USD),
             ("Gasto na última semana", of("gasto_semana"), USD), ("Gasto hoje", of("gasto_hoje"), USD),
             ("Créditos comprados", of("creditos_comprados"), USD), ("Saldo de créditos", "=B9-B5", USD),
             ("Limite mensal da chave", of("limite_mensal"), USD), ("Sobra do limite deste mês", of("sobra_do_limite"), USD),
             ("Consultado em", '=IFERROR(VLOOKUP("consultado_em",$E:$F,2,FALSE),"")', None),
             ("Registrado pela fábrica", None, None),
             ("Chamadas registradas", "=COUNTA(Chamadas!A2:A)", INT), ("Chamadas pagas", "=SUM(Chamadas!H2:H)", INT),
             ("Chamadas gratuitas", "=B16-B17", INT), ("Custo registrado", "=SUM(Chamadas!K2:K)", USD),
             ("Custo médio por chamada", "=IF(B16=0,0,B19/B16)", USD6),
             ("Custo médio por chamada paga", "=IF(B17=0,0,B19/B17)", USD6),
             ("Dias com uso", "=COUNTUNIQUE(Chamadas!A2:A)", INT), ("Custo médio por dia com uso", "=IF(B22=0,0,B19/B22)", USD),
             ("Conciliação", None, None),
             ("Gasto oficial que não está no registro", "=B5-B19", USD),
             ("Parte do gasto oficial registrada", "=IF(B5=0,0,B19/B5)", "0.0%")]
    for k, (rotulo, formula, fmt) in enumerate(itens, 4):
        rs.cell(k, 1, rotulo).font = f_sec if formula is None else f_rot
        if formula:
            c = rs.cell(k, 2, formula)
            if fmt:
                c.number_format = fmt
    rs.column_dimensions["A"].width = 44
    rs.column_dimensions["B"].width = 20
    rs["A28"] = ("O gasto que não está no registro vem de projetos apagados ou entregues antes do registro central "
                 "(2026-10-09). A partir dele, toda chamada entra. As colunas E e F trazem o total oficial da conta.")
    rs["A28"].font = f_sub
    rs["A28"].alignment = Alignment(wrap_text=True, vertical="top")
    rs.merge_cells("A28:C30")
    PASTA.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    return destino

def _montar(linhas, chave, creditos, consulta, DESTINO):
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.workbook.properties import CalcProperties

    gratis = gratuito
    # ------------------------------------------------------------------ estilo
    FONTE = "Arial"
    f_normal = Font(name=FONTE, size=10)
    f_negrito = Font(name=FONTE, size=10, bold=True)
    f_cab = Font(name=FONTE, size=10, bold=True, color="FFFFFF")
    f_titulo = Font(name=FONTE, size=14, bold=True)
    f_sub = Font(name=FONTE, size=9, italic=True, color="595959")
    f_entrada = Font(name=FONTE, size=10, color="0000FF")
    f_link = Font(name=FONTE, size=10, color="008000")
    p_cab = PatternFill("solid", fgColor="1F3864")
    p_total = PatternFill("solid", fgColor="D9E1F2")
    fina = Side(style="thin", color="BFBFBF")
    borda = Border(top=fina, bottom=fina, left=fina, right=fina)
    USD = '"US$" #,##0.00;("US$" #,##0.00);-'
    USD_CHAMADA = '"US$" 0.000000;("US$" 0.000000);-'
    INT = '#,##0;(#,##0);-'
    PCT = '0.0%;(0.0%);-'
    DATA = "dd/mm/yyyy"

    wb = Workbook()


    def cabecalho(ws, linha, nomes, larguras):
        for k, (nome, largura) in enumerate(zip(nomes, larguras), 1):
            c = ws.cell(linha, k, nome)
            c.font, c.fill, c.border = f_cab, p_cab, borda
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(k)].width = largura
        ws.row_dimensions[linha].height = 30


    def celula(ws, linha, coluna, valor, formato=None, fonte=f_normal, preencher=None):
        c = ws.cell(linha, coluna, valor)
        c.font, c.border = fonte, borda
        if formato:
            c.number_format = formato
        if preencher:
            c.fill = preencher
        return c


    # ------------------------------------------------------------------ Chamadas (os dados)
    ch = wb.active
    ch.title = "Chamadas"
    cols = ["Data", "Hora", "Projeto", "Tipo", "Etapa da fábrica", "API (modelo)", "Gratuito?", "Tokens lidos",
            "Tokens escritos", "Custo (US$)"]
    cabecalho(ch, 1, cols, [12, 8, 34, 12, 38, 42, 10, 13, 13, 14])
    for i, r in enumerate(linhas, 2):
        celula(ch, i, 1, r["quando"].date(), DATA)
        celula(ch, i, 2, r["quando"].strftime("%H:%M"))
        celula(ch, i, 3, r["projeto"])
        celula(ch, i, 4, r["tipo"])
        celula(ch, i, 5, r["etapa"])
        celula(ch, i, 6, r["modelo"])
        celula(ch, i, 7, "Sim" if gratis(r["modelo"]) else "Não")
        celula(ch, i, 8, r["lidos"], INT)
        celula(ch, i, 9, r["escritos"], INT)
        celula(ch, i, 10, r["custo"], USD_CHAMADA)
    ultima = len(linhas) + 1
    ch.freeze_panes = "A2"
    ch.auto_filter.ref = f"A1:J{ultima}"
    R = lambda col: f"Chamadas!${col}$2:${col}${ultima}"

    # ------------------------------------------------------------------ Custo diário
    dia = wb.create_sheet("Custo diário")
    dia["A1"] = "Custo diário no OpenRouter"
    dia["A1"].font = f_titulo
    dia["A2"] = "Somado da aba Chamadas. Custo por chamada = custo do dia ÷ chamadas."
    dia["A2"].font = f_sub
    cabecalho(dia, 4, ["Data", "Chamadas", "Chamadas pagas", "Chamadas gratuitas", "Custo do dia (US$)",
                       "Custo por chamada (US$)", "Custo por chamada paga (US$)", "% do custo total"],
              [13, 12, 14, 14, 16, 18, 20, 13])
    datas = sorted({r["quando"].date() for r in linhas})
    for k, d in enumerate(datas):
        i = 5 + k
        celula(dia, i, 1, d, DATA)
        celula(dia, i, 2, f'=COUNTIFS({R("A")},A{i})', INT)
        celula(dia, i, 3, f'=COUNTIFS({R("A")},A{i},{R("G")},"Não")', INT)
        celula(dia, i, 4, f"=B{i}-C{i}", INT)
        celula(dia, i, 5, f'=SUMIFS({R("J")},{R("A")},A{i})', USD)
        celula(dia, i, 6, f"=IF(B{i}=0,0,E{i}/B{i})", USD_CHAMADA)
        celula(dia, i, 7, f"=IF(C{i}=0,0,E{i}/C{i})", USD_CHAMADA)
        celula(dia, i, 8, f"=IF($E${5 + len(datas)}=0,0,E{i}/$E${5 + len(datas)})", PCT)
    t = 5 + len(datas)
    celula(dia, t, 1, "Total", fonte=f_negrito, preencher=p_total)
    for col in "BCDE":
        celula(dia, t, " BCDE".index(col) + 1, f"=SUM({col}5:{col}{t - 1})", USD if col == "E" else INT, f_negrito, p_total)
    celula(dia, t, 6, f"=IF(B{t}=0,0,E{t}/B{t})", USD_CHAMADA, f_negrito, p_total)
    celula(dia, t, 7, f"=IF(C{t}=0,0,E{t}/C{t})", USD_CHAMADA, f_negrito, p_total)
    celula(dia, t, 8, f"=SUM(H5:H{t - 1})", PCT, f_negrito, p_total)
    dia.freeze_panes = "A5"

    # ------------------------------------------------------------------ Custo por API
    custo_api = {}
    for r in linhas:
        custo_api[r["modelo"]] = custo_api.get(r["modelo"], 0) + r["custo"]
    modelos = sorted(custo_api, key=lambda m: (-custo_api[m], m))
    tipo_do = {}
    for r in linhas:
        tipo_do.setdefault(r["modelo"], r["tipo"])
    api = wb.create_sheet("Custo por API")
    api["A1"] = "Custo por API (modelo) no OpenRouter"
    api["A1"].font = f_titulo
    api["A2"] = "Gratuito = modelo :free ou stealth do OpenRouter. Custo por chamada = custo total ÷ chamadas."
    api["A2"].font = f_sub
    cabecalho(api, 4, ["API (modelo)", "Tipo", "Gratuito?", "Chamadas", "Tokens lidos", "Tokens escritos",
                       "Custo total (US$)", "% do custo", "Custo por chamada (US$)", "Primeiro uso", "Último uso"],
              [44, 12, 10, 11, 14, 14, 15, 11, 18, 13, 13])
    for k, m in enumerate(modelos):
        i = 5 + k
        celula(api, i, 1, m)
        celula(api, i, 2, tipo_do[m])
        celula(api, i, 3, "Sim" if gratis(m) else "Não")
        celula(api, i, 4, f'=COUNTIFS({R("F")},A{i})', INT)
        celula(api, i, 5, f'=SUMIFS({R("H")},{R("F")},A{i})', INT)
        celula(api, i, 6, f'=SUMIFS({R("I")},{R("F")},A{i})', INT)
        celula(api, i, 7, f'=SUMIFS({R("J")},{R("F")},A{i})', USD)
        celula(api, i, 8, f"=IF($G${5 + len(modelos)}=0,0,G{i}/$G${5 + len(modelos)})", PCT)
        celula(api, i, 9, f"=IF(D{i}=0,0,G{i}/D{i})", USD_CHAMADA)
        celula(api, i, 10, f'=_xlfn.MINIFS({R("A")},{R("F")},A{i})', DATA)
        celula(api, i, 11, f'=_xlfn.MAXIFS({R("A")},{R("F")},A{i})', DATA)
    t = 5 + len(modelos)
    celula(api, t, 1, "Total", fonte=f_negrito, preencher=p_total)
    for col, fmt in (("D", INT), ("E", INT), ("F", INT), ("G", USD), ("H", PCT)):
        celula(api, t, "ABCDEFGH".index(col) + 1, f"=SUM({col}5:{col}{t - 1})", fmt, f_negrito, p_total)
    celula(api, t, 9, f"=IF(D{t}=0,0,G{t}/D{t})", USD_CHAMADA, f_negrito, p_total)
    api.freeze_panes = "B5"

    # ------------------------------------------------------------------ Diário por API (matriz)
    mat = wb.create_sheet("Diário por API")
    mat["A1"] = "Custo por dia e por API (US$)"
    mat["A1"].font = f_titulo
    pagos = [m for m in modelos if custo_api[m] > 0]
    mat["A2"] = f"Só as APIs com custo ({len(pagos)}); as gratuitas estão na aba Custo por API."
    mat["A2"].font = f_sub
    cabecalho(mat, 4, ["Data"] + pagos + ["Total do dia"], [13] + [18] * len(pagos) + [14])
    for k, d in enumerate(datas):
        i = 5 + k
        celula(mat, i, 1, d, DATA)
        for j, m in enumerate(pagos, 2):
            col = get_column_letter(j)
            celula(mat, i, j, f'=SUMIFS({R("J")},{R("A")},$A{i},{R("F")},{col}$4)', USD)
        celula(mat, i, len(pagos) + 2, f"=SUM(B{i}:{get_column_letter(len(pagos) + 1)}{i})", USD, f_negrito)
    t = 5 + len(datas)
    celula(mat, t, 1, "Total", fonte=f_negrito, preencher=p_total)
    for j in range(2, len(pagos) + 3):
        col = get_column_letter(j)
        celula(mat, t, j, f"=SUM({col}5:{col}{t - 1})", USD, f_negrito, p_total)
    for j in range(2, len(pagos) + 2):
        mat.cell(4, j).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    mat.row_dimensions[4].height = 45
    mat.freeze_panes = "B5"

    # ------------------------------------------------------------------ Por etapa
    custo_etapa = {}
    for r in linhas:
        custo_etapa[r["etapa"]] = custo_etapa.get(r["etapa"], 0) + r["custo"]
    etapas = sorted(custo_etapa, key=lambda e: (-custo_etapa[e], e))
    et = wb.create_sheet("Por etapa")
    et["A1"] = "Custo por etapa da fábrica"
    et["A1"].font = f_titulo
    et["A2"] = "O que cada etapa consumiu (escolha das fotos, Jev, imagens de IA...)."
    et["A2"].font = f_sub
    cabecalho(et, 4, ["Etapa da fábrica", "Chamadas", "Chamadas pagas", "Custo total (US$)", "% do custo",
                      "Custo por chamada (US$)"], [44, 11, 14, 16, 11, 18])
    for k, e in enumerate(etapas):
        i = 5 + k
        celula(et, i, 1, e)
        celula(et, i, 2, f'=COUNTIFS({R("E")},A{i})', INT)
        celula(et, i, 3, f'=COUNTIFS({R("E")},A{i},{R("G")},"Não")', INT)
        celula(et, i, 4, f'=SUMIFS({R("J")},{R("E")},A{i})', USD)
        celula(et, i, 5, f"=IF($D${5 + len(etapas)}=0,0,D{i}/$D${5 + len(etapas)})", PCT)
        celula(et, i, 6, f"=IF(B{i}=0,0,D{i}/B{i})", USD_CHAMADA)
    t = 5 + len(etapas)
    celula(et, t, 1, "Total", fonte=f_negrito, preencher=p_total)
    for col, fmt in (("B", INT), ("C", INT), ("D", USD), ("E", PCT)):
        celula(et, t, "ABCDE".index(col) + 1, f"=SUM({col}5:{col}{t - 1})", fmt, f_negrito, p_total)
    celula(et, t, 6, f"=IF(B{t}=0,0,D{t}/B{t})", USD_CHAMADA, f_negrito, p_total)
    et.freeze_panes = "A5"

    # ------------------------------------------------------------------ Por projeto
    projetos = sorted({r["projeto"] for r in linhas})
    pj = wb.create_sheet("Por projeto")
    pj["A1"] = "Custo por projeto (vídeo)"
    pj["A1"].font = f_titulo
    cabecalho(pj, 3, ["Projeto", "Chamadas", "Custo total (US$)", "% do custo", "Custo por chamada (US$)"],
              [40, 11, 16, 11, 18])
    for k, p in enumerate(projetos):
        i = 4 + k
        celula(pj, i, 1, p)
        celula(pj, i, 2, f'=COUNTIFS({R("C")},A{i})', INT)
        celula(pj, i, 3, f'=SUMIFS({R("J")},{R("C")},A{i})', USD)
        celula(pj, i, 4, f"=IF($C${4 + len(projetos)}=0,0,C{i}/$C${4 + len(projetos)})", PCT)
        celula(pj, i, 5, f"=IF(B{i}=0,0,C{i}/B{i})", USD_CHAMADA)
    t = 4 + len(projetos)
    celula(pj, t, 1, "Total", fonte=f_negrito, preencher=p_total)
    for col, fmt in (("B", INT), ("C", USD), ("D", PCT)):
        celula(pj, t, "ABCD".index(col) + 1, f"=SUM({col}4:{col}{t - 1})", fmt, f_negrito, p_total)
    celula(pj, t, 5, f"=IF(B{t}=0,0,C{t}/B{t})", USD_CHAMADA, f_negrito, p_total)

    # ------------------------------------------------------------------ Resumo (primeira aba)
    rs = wb.create_sheet("Resumo", 0)
    rs.column_dimensions["A"].width = 52
    rs.column_dimensions["B"].width = 18
    rs.column_dimensions["C"].width = 70
    rs["A1"] = "Consumo do TipLabs no OpenRouter"
    rs["A1"].font = f_titulo
    rs["A2"] = f"Chamadas de {datas[0]:%d/%m/%Y} a {datas[-1]:%d/%m/%Y}; total oficial consultado em {consulta}. A planilha se refaz sozinha a cada consumo."
    rs["A2"].font = f_sub
    fonte_api = f"Fonte: OpenRouter, GET /api/v1/key e /api/v1/credits, consultado em {consulta}."
    itens = [
        ("Total oficial da conta (OpenRouter)", None, None, None),
        ("Gasto total desde o início", chave["usage"], USD, fonte_api),
        ("Gasto no mês (outubro)", chave["usage_monthly"], USD, fonte_api),
        ("Gasto na última semana", chave["usage_weekly"], USD, fonte_api),
        ("Gasto hoje", chave["usage_daily"], USD, fonte_api),
        ("Créditos comprados", creditos["total_credits"], USD, fonte_api),
        ("Saldo de créditos", "=B9-B5", USD, "Créditos comprados menos o gasto total."),
        ("Limite mensal da chave", chave["limit"], USD, fonte_api),
        ("Sobra do limite deste mês", chave["limit_remaining"], USD, fonte_api),
        ("", None, None, None),
        ("Registrado pela fábrica (abas seguintes)", None, None, None),
        ("Chamadas registradas", f"=COUNT({R('A')})", INT, "Uma linha por chamada, no registro central relatorios/openrouter_consumo.csv."),
        ("Chamadas pagas", f'=COUNTIFS({R("G")},"Não")', INT, None),
        ("Chamadas gratuitas", "=B15-B16", INT, None),
        ("Custo registrado", f"=SUM({R('J')})", USD, None),
        ("Custo médio por chamada", "=IF(B15=0,0,B18/B15)", USD_CHAMADA, "Todas as chamadas, gratuitas incluídas."),
        ("Custo médio por chamada paga", "=IF(B16=0,0,B18/B16)", USD_CHAMADA, None),
        ("Dias com uso registrado", f"=COUNT('Custo diário'!A5:A{4 + len(datas)})", INT, None),
        ("Custo médio por dia com uso", "=IF(B21=0,0,B18/B21)", USD, None),
        ("", None, None, None),
        ("Conciliação", None, None, None),
        ("Gasto oficial que não está nos registros", "=B5-B18",
         USD, "Chamadas de projetos apagados ou entregues antes do registro central (2026-10-09), que não deixaram rastro."),
        ("Parte do gasto oficial que está registrada", "=IF(B5=0,0,B18/B5)", PCT, None),
    ]
    for k, (rotulo, valor, formato, nota) in enumerate(itens, 4):
        if valor is None and rotulo:
            rs.cell(k, 1, rotulo).font = Font(name=FONTE, size=11, bold=True, color="1F3864")
            continue
        if not rotulo:
            continue
        celula(rs, k, 1, rotulo)
        entrada = isinstance(valor, (int, float))
        c = celula(rs, k, 2, valor, formato, f_entrada if entrada else f_normal)
        if nota:
            n = rs.cell(k, 3, nota)
            n.font = f_sub
            if entrada:
                c.comment = Comment(nota, "TipLabs")
    rs["A29"] = ("Fora desta planilha: Kie (imagens), GenAIPro (narração) e Groq (gratuito) têm contas próprias. "
                 "O detalhe por dia e por modelo da própria OpenRouter (/api/v1/activity) pede uma chave de gerenciamento, "
                 "que a fábrica não tem; por isso o detalhe vem do registro da fábrica.")
    rs["A29"].font = f_sub
    rs["A29"].alignment = Alignment(wrap_text=True, vertical="top")
    rs.merge_cells("A29:C31")
    rs["A33"] = "Números em azul: valores consultados na OpenRouter. Em preto: fórmulas sobre a aba Chamadas."
    rs["A33"].font = f_sub

    for ws in wb.worksheets:
        ws.sheet_view.showGridLines = ws.title == "Chamadas"
    wb.calculation = CalcProperties(fullCalcOnLoad=True)  # sem os valores gravados: quem abre calcula
    wb.calculation = CalcProperties(fullCalcOnLoad=True)  # sem os valores gravados: quem abre calcula
    wb.save(DESTINO)
