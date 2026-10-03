"""Linha de comando da fábrica de vídeos."""
import argparse
import sys
import base64
import html
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from . import animacoes, avatar, cenas, trilha, claude_local, revisao_video, corrigir, custos, gemini_local, genaipro, groq_local, jev_local, openrouter_local, efeitos, imagens, meditacao, midia, musica, narracao, render
from . import custos_reais
from . import texto as tx
from .config import RAIZ, carregar_perfil, config_geral
from .projeto import PROJETOS, Projeto
from .util import confirmar, mmss


def log(mensagem):
    print(mensagem, flush=True)


def via_api(p):
    return (p.config.get("claude") or {}).get("via", "assinatura") == "api"


def mostrar_uso(p):
    uso = claude_local.resumo_uso(p)
    if not uso:
        return
    numero = lambda n: f"{n:,}".replace(",", ".")
    log(f"  consumo do Claude neste projeto, {uso['chamadas']} chamadas, {numero(uso['lidos'])} tokens lidos "
        f"e {numero(uso['escritos'])} escritos (equivaleria a {custos.dinheiro(uso['equivalente'])} em créditos de API)")


def cmd_novo(a):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", a.nome):
        raise SystemExit("Use só letras minúsculas, números, hífen e sublinhado no nome do projeto.")
    for arquivo in (a.roteiro, a.perfil):
        if not Path(arquivo).is_file():
            raise SystemExit(f"Arquivo não encontrado: {arquivo}")
    if not a.offline:
        perfil = carregar_perfil(Path(a.perfil).resolve())
        roteiro = tx.normalizar(Path(a.roteiro).read_text(encoding="utf-8"))
        minutos = custos.duracao_estimada(roteiro, perfil) / 60
        if minutos < cenas.ESTILO_DURACAO_MINIMA_MINUTOS:
            if not confirmar(
                f"Esse roteiro dá cerca de {minutos:.0f} min de vídeo, abaixo do alvo de "
                f"{cenas.ESTILO_DURACAO_MINIMA_MINUTOS:.0f} min do estilo da fábrica. Criar assim mesmo?", a.sim):
                raise SystemExit("Cancelado. Aumente o roteiro ou rode de novo com --sim para forçar.")
    p = Projeto.criar(a.nome, a.roteiro, a.perfil, a.offline)
    log(f"Projeto criado em {p.pasta}")
    log("Modo offline, sem custo." if p.offline else custos.formatar(custos.estimar(p)))
    log(f"Próximo passo: uv run fabrica tudo {p.nome}")


def etapa_narrar(p, a, aprovado=False):
    nova_voz = getattr(a, "nova_voz", False)
    if p.existe("alinhamento.json") and not (a.forcar or nova_voz):
        log("Narração já existe, pulando. Use --forcar para aplicar mudanças no roteiro ou no ritmo, "
            "que só pagam os blocos com texto novo, ou --nova-voz para gerar tudo de novo.")
        return
    if nova_voz:
        shutil.rmtree(p.pasta / "narracao", ignore_errors=True)
    vai_gastar = nova_voz or not (p.pasta / "narracao").exists()
    if vai_gastar and not (p.offline or aprovado):
        valor = custos.dinheiro(custos.estimar(p)["voz"])
        if not confirmar(f"A narração custa cerca de {valor}. Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    antes = corrigir.falas_do_material(p)
    log("Narração")
    total = narracao.narrar(p, log)
    caracteres = len(tx.normalizar(p.roteiro()))
    log(f"  pronta, {mmss(total)}, ritmo de {caracteres / total * 60:.0f} caracteres por minuto")
    marcadores = p.marcadores()
    if marcadores:
        simbolos = sum(m["tipo"] == "simbolo" for m in marcadores)
        log(f"  {simbolos} símbolos de pausa e {len(marcadores) - simbolos} títulos com o tempo marcado")
    if p.existe("cenas.json"):
        cenas.atualizar_tempos(p)
        log("  tempos das cenas e dos textos atualizados")
        if not getattr(a, "_dentro_do_tudo", False):
            completar_depois_da_narracao(p, a, antes)
    if render.com_avatar(p):
        partes_avatar(p, getattr(a, "minutos", None))


def completar_depois_da_narracao(p, a, antes):
    """Trocar a narração nunca pode deixar o vídeo com cena faltando nem com imagem que não combina com a fala.

    A mesma sequência da criação, só nas cenas que mudaram: busca de acervo (com a conferência na captura), o Jev
    julga as cenas novas e as que ficaram com a foto antiga mas outra fala, imagens de IA (se ligada, com o custo
    perguntado), cenas completadas sem repetir imagem, animações e trilha."""
    mudou = corrigir.depois_da_narracao(p, antes)
    if not mudou["alvo"] or avatar.somente_avatar(p.perfil):
        return
    log(f"A narração mudou o corte: {len(mudou['vazias'])} cena(s) sem imagem, {len(mudou['mudaram'])} com outra fala "
        f"e {len(mudou['repetidas'])} com imagem repetida")
    midia.tirar_repetidas(p, log=log)
    midia.buscar(p, log=log)
    cfg = p.config.get("corrigir") or {}
    if not p.offline and cfg.get("automatico", True):
        minima = midia.nota_minima_da_conferencia(p)
        forcadas = mudou["mudaram"] - mudou["vazias"]

        def aprovada(c):
            cap = c.get("captura") or {}
            return cap.get("conferida") and not cap.get("suspeita") and (cap.get("nota") or 0) >= minima

        julgar = {c["n"] for c in corrigir.conferiveis(p, numeros=mudou["alvo"]) if c["n"] in forcadas or not aprovada(c)}
        if julgar:
            log(f"  o Jev confere {len(julgar)} cena(s)")
            resumo = corrigir.corrigir(p, numeros=julgar, rodadas=cfg.get("rodadas", corrigir.RODADAS),
                                       nota_minima=minima, nota_para_trocar=minima, log=log)
            log(corrigir.formatar(resumo))
    etapa_imagens(p, a)
    for _ in range(2):
        if not corrigir.depois_da_narracao(p, {})["vazias"]:
            break
        corrigir.preparar_gratis(p, log=log)
    faltam = corrigir.depois_da_narracao(p, {})["vazias"]
    if faltam:
        midia.buscar(p, apenas=set(faltam), log=log, permissivo=True)
    midia.tirar_repetidas(p, log=log)
    faltam = sorted(corrigir.depois_da_narracao(p, {})["vazias"])
    if faltam:
        log(f"  ainda sem imagem: cenas {', '.join(map(str, faltam))}. Suba uma foto delas no editor ou ligue a IA")
    etapa_animacoes(p, a, aprovado=True)
    etapa_trilha(p, a, aprovado=True)


def partes_avatar(p, minutos=None):
    """Corta a narração nos áudios que vão para o HeyGen e diz o que fazer com eles."""
    if avatar.modo(p.perfil) == "trechos":
        trechos = avatar.fatias(p, log)
        if not trechos:
            log("  o roteiro não tem nenhum trecho marcado com [AVATAR]")
        else:
            log(f"  suba cada áudio no HeyGen e salve os vídeos na pasta {p.pasta / 'avatar'} com o mesmo nome")
        pendentes = [x for x in avatar.faltando(p) if x["tipo"] in ("inserto", "fechamento")]
        for x in pendentes:
            log(f"  falta o clipe fixo {x.get('nome', '')} em {x['video']}")
        return trechos
    partes = avatar.dividir_narracao(p, minutos or (p.perfil.get("avatar") or {}).get("limite_minutos", avatar.LIMITE_MINUTOS))
    log(f"  narração dividida em {len(partes)} parte(s) para o avatar")
    for parte in partes:
        log(f"    {parte['audio']}  {mmss(parte['fim'] - parte['ini'])}")
    log(f"  suba cada áudio no HeyGen, gere o avatar em retrato e salve os vídeos em {p.pasta / 'avatar'} "
        "com os nomes parte_1.mp4, parte_2.mp4 e assim por diante")
    return partes


def etapa_mapa(p, a, aprovado=False, forcar=None):
    """O agente de roteiro lê o roteiro inteiro, monta o mapa e o JSON de todas as cenas. Só precisa do texto."""
    from . import roteirista

    if not roteirista.ativo(p):
        log("O agente de roteiro está desligado para este projeto (modo offline, perfil com personagem ou efeitos, "
            "ou roteirista.ativo: false no config.yaml).")
        return None
    forcar = a.forcar if forcar is None else forcar
    salvo = p.ler_json("roteiro_mapa.json") if p.existe("roteiro_mapa.json") else {}
    mapa_novo = forcar or salvo.get("assinatura") != roteirista.assinatura_do_mapa(p)
    cenas_salvas = p.ler_json("roteiro_cenas.json") if p.existe("roteiro_cenas.json") else {}
    cenas_novas = mapa_novo or cenas_salvas.get("assinatura") != roteirista._assinatura_das_cenas(p, salvo)
    segundos = custos.duracao_estimada(tx.normalizar(p.roteiro()), p.perfil)
    previsto = roteirista.estimar(p, max(1, round(segundos / cenas.ESTILO_ALVO_SEGUNDOS)))
    valor = (previsto["mapa"] if mapa_novo else 0.0) + (previsto["cenas"] if cenas_novas else 0.0)
    if valor and not aprovado:
        minutos = max(1.0, segundos / 60)
        if not confirmar(f"O agente de roteiro vai ler o roteiro e decidir as cenas pelo MiMo: cerca de "
                         f"{custos.dinheiro(valor)} no total ({custos.dinheiro(valor / minutos)} por minuto de vídeo). "
                         "Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    log("Mapa do roteiro")
    m = roteirista.mapa(p, log, forcar=forcar)
    for b in m["blocos"]:
        log(f"  {b['id']:>2}. {b['nome']}  ->  {b['ancora']}")
    for t in m.get("armadilhas") or []:
        log(f"  armadilha: {t['termo']}  ->  buscar {t['usar']}")
    log("JSON de cenas")
    dados = roteirista.roteiro_de_cenas(p, log, forcar=forcar)
    log(f"  {len(dados['cenas'])} cenas decididas, salvas em {p.pasta / 'roteiro_cenas.json'}")
    return m


def etapa_cenas(p, a, aprovado=False):
    if not p.existe("alinhamento.json"):
        raise SystemExit(f"Falta a narração. Rode uv run fabrica narrar {p.nome}")
    if p.existe("cenas.json") and not a.forcar:
        log("Cenas já existem, pulando. Use --forcar para refazer.")
        return
    if a.forcar:
        shutil.rmtree(p.pasta / "cenas_lotes", ignore_errors=True)
        (p.pasta / "roteiro_cenas.json").unlink(missing_ok=True)  # o JSON de cenas do agente é refeito também
        carimbo = f"{datetime.now():%Y%m%d-%H%M%S}"
        for pasta in ("imagens", "midia"):
            if (p.pasta / pasta).exists():
                (p.pasta / pasta).rename(p.pasta / f"{pasta}_antigas_{carimbo}")
                log(f"  {pasta} anterior guardada em {pasta}_antigas_{carimbo}")
    if via_api(p) and not (p.offline or aprovado):
        valor = custos.dinheiro(custos.estimar(p)["claude"])
        if not confirmar(f"Planejar as cenas com o Claude custa cerca de {valor}. Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    # o JSON de cenas sai do agente (feito antes, ou agora se faltar); o passo de cenas só o encaixa no tempo
    etapa_mapa(p, a, aprovado, forcar=False)
    log("Cenas")
    lista = cenas.planejar(p, log)
    reais = sum(c["tipo"] != "ia" for c in lista)
    com_texto = sum(bool(c.get("texto_tela")) for c in lista)
    log(f"  {len(lista)} cenas, {reais} pedindo material real, {com_texto} com texto na tela, "
        f"{sum(c['personagem'] for c in lista)} com a personagem")
    mostrar_uso(p)


def etapa_midia(p, a, aprovado=False):
    if avatar.somente_avatar(p.perfil):
        return
    if not p.existe("cenas.json"):
        raise SystemExit(f"Faltam as cenas. Rode uv run fabrica cenas {p.nome}")
    pendentes = [c for c in p.ler_json("cenas.json")["cenas"] if midia.pendente(c)]
    if not pendentes:
        return
    if via_api(p) and not (p.offline or aprovado):
        valor = custos.dinheiro(len(pendentes) * p.config["precos"].get("claude_escolha_por_cena", 0.02))
        if not confirmar(f"O Claude vai escolher fotos e vídeos reais para {len(pendentes)} cenas, cerca de {valor}. Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    log("Material real")
    midia.buscar(p, log=log)
    log(f"  créditos para a descrição do vídeo em {p.pasta / 'creditos.txt'}")
    mostrar_uso(p)


def etapa_imagens(p, a, aprovado=False):
    if avatar.somente_avatar(p.perfil):
        return
    if not p.existe("cenas.json"):
        raise SystemExit(f"Faltam as cenas. Rode uv run fabrica cenas {p.nome}")
    pendentes = imagens.pendentes_ia(p, p.ler_json("cenas.json")["cenas"])
    if pendentes and not (p.offline or aprovado):
        valor = custos.dinheiro(len(pendentes) * p.config["precos"]["imagem"])
        if not confirmar(f"Gerar {len(pendentes)} imagens de IA custa cerca de {valor}. Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    log("Imagens de IA")
    log(f"  revisão em {imagens.gerar(p, log=log, direto=getattr(a, 'direto', False))}")


def etapa_animacoes(p, a, aprovado=False):
    """Diagramas, textos na tela, linhas do tempo e mapas viram animação (HyperFrames). Gratuito e sem bloquear:
    a cena que não der para animar fica com a foto."""
    if avatar.somente_avatar(p.perfil) or not p.existe("cenas.json"):
        return
    log("Animações")
    resumo = animacoes.gerar(p, log=log)
    if resumo.get("motivo"):
        log(f"  {resumo['motivo']}")


def etapa_trilha(p, a, aprovado=False):
    """O modelo compõe a trilha pelos blocos do roteiro e o código toca. Gratuito; só entra no vídeo quando o perfil
    não tem músicas próprias (ou trilha.substituir no config)."""
    if not trilha.ligada(p) or not p.existe("cenas.json") or not p.existe("alinhamento.json"):
        return
    log("Trilha")
    try:
        trilha.gerar(p, log=log)
    except (Exception, SystemExit) as erro:
        log(f"  a trilha não saiu ({str(erro)[:120]}); o render tenta de novo")


def cmd_trilha(a):
    p = Projeto(a.nome)
    if not p.existe("cenas.json") or not p.existe("alinhamento.json"):
        raise SystemExit(f"Faltam a narração e as cenas. Rode uv run fabrica tudo {p.nome}")
    if not trilha.ligada(p):
        raise SystemExit("A trilha gerada está desligada (trilha.ativo no config.yaml ou no perfil).")
    log("Trilha")
    destino = trilha.gerar(p, log=log, forcar=a.forcar)
    if a.efeitos:
        cenas_ = p.ler_json("cenas.json")["cenas"]
        sons = trilha.efeitos_na_linha(p, cenas_, log=log)
        nomes = {}
        for _, arquivo, _ in sons:
            nome = arquivo.stem.rsplit("-v", 1)[0]
            nomes[nome] = nomes.get(nome, 0) + 1
        log("  efeitos: " + (", ".join(f"{n} {k}" for k, n in nomes.items()) or "nenhum"))
    log(f"  pronta em {destino}. Entra no próximo render.")


def etapa_revisao_video(p, a):
    """Depois do render, o modelo principal olha o vídeo pronto e aponta problemas. Gratuito e sem bloquear."""
    if not revisao_video.ligada(p) or not p.existe("final.mp4"):
        return
    log("Revisão do vídeo pronto")
    try:
        revisao_video.revisar(p, log=log)
    except (Exception, SystemExit) as erro:
        log(f"  a revisão não rodou ({str(erro)[:120]}); o vídeo está pronto do mesmo jeito")


def cmd_revisar_video(a):
    p = Projeto(a.nome)
    log("Revisão do vídeo pronto")
    r = revisao_video.revisar(p, log=log, numeros=set(a.cenas) if a.cenas else None)
    for n, problemas in sorted(r["cenas"].items(), key=lambda x: int(x[0])):
        for pr in problemas:
            log(f"  cena {n} [{pr['gravidade']}] {revisao_video.TIPOS.get(pr['tipo'], pr['tipo'])}: {pr['descricao']}")


def cmd_animacoes(a):
    p = Projeto(a.nome)
    if a.remover:
        for n in a.cenas or []:
            animacoes.remover(p, n)
        log(f"Cenas {', '.join(map(str, a.cenas or []))} voltaram a usar a foto. Rode o render para valer no vídeo.")
        return
    log("Animações")
    resumo = animacoes.gerar(p, numeros=set(a.cenas) if a.cenas else None, forcar=a.forcar, log=log)
    if resumo.get("motivo"):
        log(f"  {resumo['motivo']}")
    elif resumo["feitas"]:
        log(f"Pronto. Rode uv run fabrica render {p.nome} para as animações entrarem no vídeo.")


def etapa_efeitos(p, a, aprovado=False):
    if not efeitos.ativo(p.perfil):
        return
    if not p.existe("cenas.json"):
        raise SystemExit(f"Faltam as cenas. Rode uv run fabrica cenas {p.nome}")
    segundos = efeitos.segundos_pendentes(p)
    sem_chave = not os.environ.get("ELEVENLABS_API_KEY", "").strip()  # sem ela os efeitos ficam de fora, sem custo
    if segundos and not (p.offline or aprovado or sem_chave):
        valor = custos.dinheiro(segundos / 60 * p.config["precos"].get("efeito_por_minuto", 0.12))
        if not confirmar(f"Gerar {segundos:.0f} segundos de efeitos sonoros custa cerca de {valor}. Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    log("Efeitos sonoros")
    efeitos.gerar(p, log)


def etapa_render(p, a, aprovado=False):
    log("Render")
    inicio = time.time()
    vertical = getattr(a, "vertical", False)
    if vertical and not aprovado:
        # só a versão em pé: a deitada fica como está
        log("  versão em pé (9:16), para Reels e Shorts")
        final = render.renderizar(p, log, sem_avatar=getattr(a, "sem_avatar", False), vertical=True)
        log(f"  vídeo em pé pronto em {final} ({mmss(time.time() - inicio)} de render)")
        return
    final = render.renderizar(p, log, sem_avatar=getattr(a, "sem_avatar", False))
    log(f"  vídeo pronto em {final} ({mmss(time.time() - inicio)} de render)")
    if vertical:
        inicio = time.time()
        log("Render da versão em pé (9:16), para Reels e Shorts")
        final = render.renderizar(p, log, sem_avatar=getattr(a, "sem_avatar", False), vertical=True)
        log(f"  vídeo em pé pronto em {final} ({mmss(time.time() - inicio)} de render)")


def etapa_corrigir(p, a, aprovado=False):
    """Confere se cada foto e vídeo de acervo combina com a narração e troca o que não combina.

    Roda entre o acervo e as imagens de IA: o que a conferência conserta de graça no acervo deixa de
    virar imagem paga depois. Cenas de IA não são olhadas."""
    cfg = p.config.get("corrigir") or {}
    if p.offline or getattr(a, "sem_corrigir", False) or not cfg.get("automatico", True):
        return
    total = len(corrigir.conferiveis(p))
    if not total:
        return
    if not aprovado:
        valor = custos.dinheiro(total * p.config["precos"].get("correcao_por_cena", 0.0005))
        if not confirmar(f"Conferir {total} cena(s) custa cerca de {valor}. Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    log("Conferindo se as cenas combinam com a narração")
    # regra fixa, igual à da criação pelo site: abaixo da nota mínima a cena é trocada sozinha, de graça no acervo
    minima = midia.nota_minima_da_conferencia(p)
    resumo = corrigir.corrigir(
        p, rodadas=cfg.get("rodadas", corrigir.RODADAS), nota_minima=minima, nota_para_trocar=minima, log=log)
    log(corrigir.formatar(resumo))


def cmd_tudo(a):
    p = Projeto(a.nome)
    if not p.offline:
        log(custos.formatar(custos.estimar(p)))
        if not confirmar("Gerar o vídeo completo?", a.sim):
            raise SystemExit("Cancelado.")
    # o agente monta o JSON de cenas pelo texto enquanto a narração é gravada: os dois não dependem um do outro
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as agente:
        pronto = agente.submit(etapa_mapa, p, a, True)
        a._dentro_do_tudo = True  # no tudo, as etapas seguintes já completam as cenas
        etapa_narrar(p, a, aprovado=True)
        pronto.result()
    for etapa in (etapa_cenas, etapa_midia, etapa_corrigir, etapa_imagens, etapa_efeitos, etapa_animacoes, etapa_trilha):
        etapa(p, a, aprovado=True)
    if render.com_avatar(p, a.sem_avatar):
        faltando = avatar.faltando(p) if avatar.modo(p.perfil) == "trechos" else avatar.partes_faltando(p)
        if faltando:
            lista = ", ".join(x["video"] for x in faltando)
            log(f"Tudo pronto menos o personagem. Faltam {lista}.")
            log(f"Gere no HeyGen com os áudios da pasta avatar e depois rode uv run fabrica render {p.nome}")
            return
    etapa_render(p, a, aprovado=True)
    etapa_revisao_video(p, a)
    log(f"Revise as cenas com uv run fabrica revisar {p.nome}")


def cmd_avatar_partes(a):
    p = Projeto(a.nome)
    if not p.existe("alinhamento.json"):
        raise SystemExit(f"Falta a narração. Rode uv run fabrica narrar {p.nome}")
    partes_avatar(p, a.minutos)
    subprocess.run(["open", p.pasta / "avatar"])


def cmd_refazer(a):
    p = Projeto(a.nome)
    so_acervo = bool(a.busca and not a.prompt and not a.ia)
    if so_acervo:
        log("Só busca em acervo, sem gerar imagem de IA.")
    if not p.offline and not so_acervo:
        precos = p.config["precos"]
        por_cena = precos["imagem"] + (precos.get("claude_escolha_por_cena", 0.02) if via_api(p) else 0)
        valor = custos.dinheiro(len(a.cenas) * por_cena)
        if not confirmar(f"Refazer {len(a.cenas)} cenas custa no máximo {valor}. Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    pagina = imagens.refazer(p, a.cenas, prompt=a.prompt, busca=a.busca, forcar_ia=a.ia, log=log)
    log(f"Pronto. Revise em {pagina} e depois rode uv run fabrica render {p.nome}" if pagina
        else f"Pronto. Revise no editor e depois rode uv run fabrica render {p.nome}")


CUSTO_CONFERENCIA_JEV_POR_CENA = 0.003  # medido: US$ 0,003 a 0,004 por cena, com o roteador escolhendo um modelo que raciocina (deepseek-v4.1-flash)
CUSTO_CONFERENCIA_POR_CENA = 0.003  # medido no gemini-3.8-flash: cerca de 2,6 mil tokens lidos e 200 escritos por cena


def cmd_corrigir(a):
    p = Projeto(a.nome)
    cfg = p.config.get("corrigir") or {}
    numeros = a.cenas or None
    total = len(corrigir.conferiveis(p, set(numeros) if numeros else None))
    if not total:
        raise SystemExit("Nenhuma cena de material real com arquivo baixado para conferir. Cenas de IA não entram.")
    com_gemini = corrigir.provedor(p) == "gemini"
    com_jev = corrigir.provedor(p) in ("jev", "openrouter")
    if com_jev and not p.offline:
        valor = custos.dinheiro(total * CUSTO_CONFERENCIA_JEV_POR_CENA)
        if not confirmar(f"Conferir {total} cena(s) com o Jev pelo OpenRouter custa cerca de {valor} por rodada (o preço varia com o modelo que o roteador escolhe). Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    if com_gemini and not p.offline:
        valor = custos.dinheiro(total * CUSTO_CONFERENCIA_POR_CENA)
        if not confirmar(f"Conferir {total} cena(s) com o Gemini custa cerca de {valor} por rodada, só sobre as reprovadas nas seguintes. Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    rotulo = (" (o modelo de visão descreve e o Jev julga)" if corrigir.provedor(p) == "jev"
              else " (OpenRouter)" if com_jev else "" if com_gemini else " (Groq, plano gratuito, sem custo)")
    log("Conferindo a mídia com a narração" + rotulo)
    zero = {"custo": 0, "chamadas": 0}
    inicio_or = openrouter_local.resumo_uso(p) or zero
    inicio_jev = jev_local.resumo_uso(p) or zero
    inicio = gemini_local.resumo_uso(p) or {"lidos": 0, "escritos": 0, "pensamento": 0}
    inicio_groq = groq_local.resumo_uso(p) or {"lidos": 0, "escritos": 0}
    resumo = corrigir.corrigir(
        p, numeros=numeros, rodadas=a.rodadas or cfg.get("rodadas", corrigir.RODADAS),
        nota_minima=a.nota_minima or cfg.get("nota_minima", corrigir.NOTA_MINIMA),
        nota_para_trocar=a.nota_para_trocar or cfg.get("nota_para_trocar", corrigir.NOTA_PARA_TROCAR),
        so_avaliar=a.avaliar, log=log)
    fim = gemini_local.resumo_uso(p) or inicio
    lidos, escritos = fim["lidos"] - inicio["lidos"], fim["escritos"] + fim["pensamento"] - inicio["escritos"] - inicio["pensamento"]
    gasto = lidos * 0.75 / 1e6 + escritos * 3.75 / 1e6
    log(corrigir.formatar(resumo))
    if com_jev:
        fim_or = openrouter_local.resumo_uso(p) or inicio_or
        fim_jev = jev_local.resumo_uso(p) or inicio_jev
        chamadas = (fim_or["chamadas"] - inicio_or["chamadas"]) + (fim_jev["chamadas"] - inicio_jev["chamadas"])
        gasto = (fim_or["custo"] - inicio_or["custo"]) + (fim_jev["custo"] - inicio_jev["custo"])
        log(f"OpenRouter: {chamadas} chamada(s), custo real de US$ {gasto:.4f}")
    if not com_gemini and not com_jev:
        fim_groq = groq_local.resumo_uso(p) or inicio_groq
        usados = fim_groq["lidos"] + fim_groq["escritos"] - inicio_groq["lidos"] - inicio_groq["escritos"]
        log(f"Groq: {usados} tokens gastos nesta conferência, do limite diário de cada conta")
    if com_gemini:
        log(f"Gemini: {lidos} tokens lidos e {escritos} escritos, cerca de {custos.dinheiro(gasto)} pelo preço do gemini-3.8-flash")

    faltam = resumo["precisam_ia"]
    if a.avaliar:
        log("Para trocar as que não combinam, rode sem --avaliar.")
        return
    if not faltam:
        return
    if not a.ia:
        log(f"Para trocar essas {len(faltam)} cena(s) por imagem nova de IA, rode de novo com --ia. Isso custa dinheiro.")
        return
    precos = p.config["precos"]
    provedor = ((p.perfil.get("imagens") or {}).get("provedor") or "google").lower()
    por_imagem = precos["imagem_kie"] if provedor in ("kie", "kie.ai") else precos["imagem"]
    valor = custos.dinheiro(len(faltam) * por_imagem)
    if not confirmar(f"Gerar {len(faltam)} imagem(ns) de IA custa cerca de {valor}. Continuar?", a.sim):
        raise SystemExit("Cancelado. As cenas seguem como estão.")
    corrigir.regerar_com_ia(p, faltam, log=log)
    log(f"Pronto. Revise as cenas e rode uv run fabrica render {p.nome}")


def cmd_custo(a):
    p = Projeto(a.nome)
    log("Modo offline, sem custo." if p.offline else custos.formatar(custos.estimar(p)))
    mostrar_uso(p)
    log("")
    log(formatar_gasto_real(custos_reais.resumo(p)))


def formatar_gasto_real(r):
    """O que este vídeo já custou de verdade, medido chamada por chamada."""
    if not r["total_usd"] and not r["medidas"]:
        return "Gasto real: nada foi cobrado ainda neste projeto."
    numero = lambda n: f"{n:,.0f}".replace(",", ".")
    linhas = ["Gasto real já cobrado neste vídeo"]
    for categoria, valor in sorted(r["por_categoria"].items(), key=lambda x: -x[1]):
        rotulo = r["rotulos"].get(categoria, categoria)
        medida = r["medidas"].get(categoria)
        detalhe = f"  ({numero(medida)} {r['unidades'].get(categoria, '')})" if medida else ""
        linhas.append(f"  {rotulo:<22}{custos.dinheiro(valor):>12}{detalhe}")
    linhas.append(f"  {'TOTAL':<22}{custos.dinheiro(r['total_usd']):>12}")
    if r["duracao_segundos"]:
        linhas.append(f"  por minuto de vídeo   {custos.dinheiro(r['por_minuto_usd']):>12}"
                      f"  ({mmss(r['duracao_segundos'])} de vídeo)")
    if r["cenas"]:
        linhas.append(f"  por cena              {custos.dinheiro(r['por_cena_usd']):>12}  ({r['cenas']} cenas)")

    n = r["narracao"]
    if n["caracteres"]:
        linhas.append("")
        linhas.append(f"Narração: {numero(n['caracteres'])} caracteres, cobrados pela {n['origem_do_preco']} "
                      f"({custos.dinheiro(n['preco_por_mil'])} por mil)")
        if n["incluido_no_mes"]:
            linhas.append(f"  o plano {n['plano']} custa {custos.dinheiro(n['preco_mensal'])} por mês e inclui "
                          f"{numero(n['incluido_no_mes'])} caracteres")
            linhas.append(f"  este vídeo usou {n['fatia_da_franquia']}% da franquia do mês, "
                          f"que dá para uns {n['videos_por_mes']} vídeos deste tamanho")
    if r["modelos_de_texto"]:
        linhas.append("")
        linhas.append("Modelos de texto")
        for m in r["modelos_de_texto"]:
            valor = "grátis" if m["gratuito"] else custos.dinheiro(m["custo_usd"])
            linhas.append(f"  {m['provedor']:<12}{valor:>10}  {m['chamadas']} chamadas, "
                          f"{numero(m['tokens_lidos'])} tokens lidos e {numero(m['tokens_escritos'])} escritos")
    return "\n".join(linhas)


def cmd_status(a):
    p = Projeto(a.nome)
    log(f"Projeto {p.nome}{' (offline)' if p.offline else ''} com o perfil {p.perfil.get('nome', '?')}")
    if p.existe("alinhamento.json"):
        log(f"  narração pronta, {mmss(p.ler_json('alinhamento.json')['duracao'])}")
    else:
        log("  narração pendente")
    if p.existe("cenas.json"):
        lista = p.ler_json("cenas.json")["cenas"]
        reais = sum(bool(c.get("midia")) for c in lista)
        esperando = sum(midia.pendente(c) for c in lista)
        com_ia = [c for c in lista if midia.precisa_ia(c)]
        prontas = sum(p.imagem(c["n"]).exists() for c in com_ia)
        resumo = f"  {len(lista)} cenas, {reais} com material real, {prontas} de {len(com_ia)} imagens de IA prontas"
        log(resumo + (f", {esperando} esperando busca de material real" if esperando else ""))
    else:
        log("  cenas pendentes")
    if render.com_avatar(p) and p.existe("alinhamento.json"):
        faltando = avatar.faltando(p) if avatar.modo(p.perfil) == "trechos" else avatar.partes_faltando(p)
        if faltando is None:
            log("  avatar pendente, a narração ainda não foi dividida")
        elif faltando:
            log(f"  personagem esperando {len(faltando)} vídeo(s), " +
                ", ".join(x.get("nome") or Path(x["video"]).name for x in faltando))
        else:
            log("  vídeos do personagem prontos")
    log(f"  vídeo final em {p.pasta / 'final.mp4'}" if p.existe("final.mp4") else "  vídeo final pendente")
    mostrar_uso(p)


def cmd_revisar(a):
    p = Projeto(a.nome)
    if not p.existe("cenas.json"):
        raise SystemExit("Ainda não há cenas para revisar.")
    subprocess.run(["open", imagens.gerar_revisao(p)])


def cmd_personagem(a):
    perfil = carregar_perfil(Path(a.perfil).resolve())
    quantidade = max(1, min(a.quantidade, 4))
    valor = custos.dinheiro(quantidade * config_geral()["precos"]["imagem"] * 1.5)
    if not confirmar(f"Gerar {quantidade} rostos em 2K custa cerca de {valor}. Continuar?", a.sim):
        raise SystemExit("Cancelado.")
    pasta, arquivos = imagens.candidatos_personagem(perfil, quantidade, log)
    log(f"  {len(arquivos)} rostos salvos em {pasta}")
    log("  copie o escolhido para a pasta personagens e coloque o caminho em personagem.referencias no perfil")
    subprocess.run(["open", pasta])


def cmd_avatar(a):
    creditos, dolares = avatar.custo(a.audio, a.resolucao)
    if not confirmar(f"O avatar em {a.resolucao} usa cerca de {creditos:.0f} créditos da DreamAPI "
                     f"({custos.dinheiro(dolares)}). Continuar?", a.sim):
        raise SystemExit("Cancelado.")
    destino = Path(a.saida) if a.saida else Path(a.audio).with_name(Path(a.audio).stem + f"_avatar_{a.resolucao}.mp4")
    log("Avatar")
    avatar.criar_video(a.imagem, a.audio, destino, a.prompt, a.resolucao, log)
    log(f"  pronto em {destino}")
    subprocess.run(["open", destino])


def cmd_meditacao(a):
    if not (PROJETOS / a.nome / "projeto.json").exists():
        if not (a.roteiro and a.perfil):
            raise SystemExit(f"O projeto '{a.nome}' ainda não existe. Na primeira vez, passe --roteiro e --perfil.")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", a.nome):
            raise SystemExit("Use só letras minúsculas, números, hífen e sublinhado no nome do projeto.")
        for arquivo in (a.roteiro, a.perfil):
            if not Path(arquivo).is_file():
                raise SystemExit(f"Arquivo não encontrado: {arquivo}")
        p = Projeto.criar(a.nome, a.roteiro, a.perfil, a.offline)
        log(f"Projeto criado em {p.pasta}")
    p = Projeto(a.nome)
    if a.nova_voz:
        shutil.rmtree(p.pasta / "meditacao", ignore_errors=True)
    e = meditacao.estimar(p)
    log(f"{e['falas']} falas com {e['caracteres']} caracteres e {mmss(e['silencio'])} de silêncio, "
        f"cerca de {mmss(e['duracao'])} no total")
    if e["faltam"] and not p.offline:
        valor = custos.dinheiro(e["voz"] * e["faltam"] / max(e["falas"], 1))
        if not confirmar(f"Gravar {e['faltam']} fala(s) na GenAIPro custa cerca de {valor}. Continuar?", a.sim):
            raise SystemExit("Cancelado.")
    log("Prática guiada")
    saida, duracao = meditacao.gerar(p, a.imagem, log)
    log(f"  pronta em {saida}, {mmss(duracao)}")


def cmd_musica_gerar(a):
    if not confirmar(f"Gerar {a.minutos:g} minuto(s) de música consome créditos da ElevenLabs direta (opcional, fora da GenAIPro). Continuar?", a.sim):
        raise SystemExit("Cancelado.")
    log("Música")
    mp3 = musica.gerar(a.descricao, a.minutos, a.pasta, a.nome, a.modelo)
    log(f"  salva em {mp3}, com o crédito no .txt ao lado")
    subprocess.run(["open", mp3])


def cmd_estimar(a):
    perfil = carregar_perfil(Path(a.perfil).resolve())
    roteiro = tx.normalizar(Path(a.roteiro).read_text(encoding="utf-8"))
    palavras = len(roteiro.split())
    numero = lambda n: f"{n:,}".replace(",", ".")
    log(f"{numero(len(roteiro))} caracteres e {numero(palavras)} palavras, cerca de "
        f"{mmss(custos.duracao_estimada(roteiro, perfil))} de vídeo com a voz do perfil")
    if not (perfil.get("ritmo") or {}).get("caracteres_por_minuto"):
        log("  estimativa genérica, porque o perfil ainda não tem ritmo.caracteres_por_minuto")


def cmd_vozes(a):
    vozes = narracao.buscar_vozes(a.termo, a.idioma)
    if not vozes:
        raise SystemExit("Nenhuma voz encontrada com esse termo.")
    for i, v in enumerate(vozes, 1):
        detalhes = " · ".join(x for x in (v["genero"], v["idade"], v["sotaque"], v["idioma"], v["uso"]) if x)
        log(f"{i:>2}. {v['nome']}  ({detalhes})")
        if v["descricao"]:
            log(f"    {v['descricao'][:140]}")
        log(f"    ouvir em {v['previa']}")
        log(f"    código para voz.voice_id no perfil: {v['voice_id']}")
    log("Qualquer uma serve direto: cole o código em voz.voice_id no perfil do canal.")


def cmd_creditos(a):
    c = genaipro.conta()
    numero = lambda n: f"{n:,}".replace(",", ".")
    por_caractere, origem = custos_reais.preco_por_caractere(config_geral())
    taxa, de_onde = custos_reais.creditos_por_caractere(config_geral())
    log(f"GenAIPro, conta {c['usuario']}: {numero(c['creditos'])} créditos "
        f"({taxa:.3f} crédito por caractere narrado, {de_onde})")
    for pacote in c["pacotes"]:
        log(f"  {numero(pacote['creditos'])} vencem em {(pacote['vence'] or '')[:10]}")
    ritmo = 900  # caracteres por minuto de uma narração típica
    log(f"  dá para cerca de {int(c['creditos'] / (taxa * ritmo) / 60)} horas de narração, "
        f"a {custos.dinheiro(por_caractere * ritmo)} por minuto ({origem})")


VOZES_CRIADAS = RAIZ / "vozes_criadas"


def cmd_voz_desenhar(a):
    texto = Path(a.texto).read_text(encoding="utf-8").strip() if a.texto else narracao.TEXTO_TESTE_VOZ
    log("Criando prévias da voz na ElevenLabs direta (opcional)")
    previas = narracao.desenhar_voz(a.descricao, texto, a.modelo)
    VOZES_CRIADAS.mkdir(exist_ok=True)
    arquivo_registro = VOZES_CRIADAS / "previas.json"
    registro = json.loads(arquivo_registro.read_text(encoding="utf-8")) if arquivo_registro.exists() else []
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    for i, previa in enumerate(previas, 1):
        audio = VOZES_CRIADAS / f"{carimbo}-{i}.mp3"
        audio.write_bytes(base64.b64decode(previa["audio_base_64"]))
        registro.append({"arquivo": audio.name, "id": previa["generated_voice_id"], "descricao": a.descricao,
                         "rotulo": a.rotulo or "", "modelo": a.modelo, "quando": carimbo})
        log(f"  prévia {len(registro)} salva")
    arquivo_registro.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    pagina = _pagina_vozes_criadas(registro)
    log(f"Ouça em {pagina}")
    log('Para guardar a escolhida na sua conta, rode uv run fabrica voz-salvar NÚMERO --nome "Nome da voz"')
    if not a.nao_abrir:
        subprocess.run(["open", pagina])


def _pagina_vozes_criadas(registro):
    cartoes = []
    for i, previa in enumerate(registro, 1):
        cartoes.append(
            f'<article><div class="topo"><b>{i}</b><h2>{html.escape(previa["rotulo"] or "voz criada")}</h2></div>'
            f'<p class="meta">{previa["quando"]}</p><p>{html.escape(previa["descricao"])}</p>'
            f'<audio controls preload="none" src="{previa["arquivo"]}"></audio></article>'
        )
    pagina = VOZES_CRIADAS / "vozes_criadas.html"
    pagina.write_text(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>Vozes criadas</title><style>"
        "body{margin:0;padding:24px 16px;background:#141414;color:#eaeaea;font:15px/1.45 -apple-system,sans-serif}"
        "header,main{max-width:1100px;margin:0 auto}h1{font-size:22px;margin:0 0 6px}header p{color:#b5b5b5;margin:0 0 20px}"
        "main{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px}"
        "article{background:#1f1f1f;border-radius:8px;padding:14px}.topo{display:flex;gap:10px;align-items:baseline}"
        ".topo b{color:#e0b04a;font-size:18px}h2{font-size:16px;margin:0}.meta{color:#9a9a9a;font-size:13px;margin:4px 0}"
        "article p{margin:6px 0;font-size:14px}audio{width:100%;margin-top:6px}</style>"
        "<header><h1>Vozes criadas no Voice Design</h1><p>Ouça, compare e me diga o número da escolhida.</p></header>"
        "<main>" + "\n".join(cartoes) + "</main>",
        encoding="utf-8",
    )
    return pagina


def cmd_voz_salvar(a):
    arquivo_registro = VOZES_CRIADAS / "previas.json"
    if not arquivo_registro.exists():
        raise SystemExit("Ainda não há prévias. Rode uv run fabrica voz-desenhar primeiro.")
    registro = json.loads(arquivo_registro.read_text(encoding="utf-8"))
    if not 1 <= a.numero <= len(registro):
        raise SystemExit(f"Escolha um número entre 1 e {len(registro)}.")
    previa = registro[a.numero - 1]
    voice_id = narracao.salvar_voz_criada(previa["id"], a.nome, previa["descricao"])
    log(f"Voz salva na conta da ElevenLabs com o código {voice_id}.")
    log("A GenAIPro só narra com vozes da biblioteca pública: compartilhe esta voz na Voice Library da ElevenLabs "
        "e depois ache pelo nome com uv run fabrica vozes NOME.")


def cmd_servidor(a):
    import uvicorn
    from .api import criar_app
    app = criar_app(frontend_dir=getattr(a, "frontend", None))
    log(f"Iniciando API HTTP da Fábrica de Vídeos em http://{a.host}:{a.porta}")
    uvicorn.run(app, host=a.host, port=a.porta, proxy_headers=True, forwarded_allow_ips="*")


def main():
    # no Windows, com a saída indo para um arquivo (o backend escondido grava em fabrica.log), o Python usa a
    # codificação antiga do sistema: um aviso com um pedaço em chinês que o modelo devolveu derrubava a esteira
    # inteira ("'charmap' codec can't encode", na troca de narração do zz_teste_animacoes)
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(prog="fabrica", description="Roteiro pronto entra, vídeo narrado sai.")
    sub = parser.add_subparsers(dest="comando", required=True, metavar="comando")

    s = sub.add_parser("novo", help="cria um projeto com um roteiro e um perfil de canal")
    s.add_argument("nome")
    s.add_argument("--roteiro", required=True)
    s.add_argument("--perfil", required=True)
    s.add_argument("--offline", action="store_true", help="teste sem custo, com a voz do Mac e imagens de teste")
    s.add_argument("--sim", action="store_true", help="aceita criar mesmo com roteiro abaixo do alvo de duração")
    s.set_defaults(funcao=cmd_novo)

    comandos = {
        "tudo": ("faz narração, cenas, material real, imagens e render em sequência", cmd_tudo),
        "mapa": ("o agente de roteiro lê o roteiro inteiro e monta o mapa do vídeo, antes da narração",
                 lambda a: etapa_mapa(Projeto(a.nome), a)),
        "narrar": ("gera a narração e o tempo de cada frase", lambda a: etapa_narrar(Projeto(a.nome), a)),
        "cenas": ("divide em cenas e decide o que aparece em cada uma", lambda a: etapa_cenas(Projeto(a.nome), a)),
        "midia": ("busca fotos e vídeos reais para as cenas marcadas", lambda a: etapa_midia(Projeto(a.nome), a)),
        "conferir": ("confere se as cenas de acervo combinam com a narração e troca o que não combina",
                     lambda a: etapa_corrigir(Projeto(a.nome), a)),
        "imagens": ("gera as imagens de IA que faltam e a página de revisão", lambda a: etapa_imagens(Projeto(a.nome), a)),
        "textos": ("decide de novo só os textos na tela, com as regras de qualidade, sem mexer nas imagens",
                   lambda a: cenas.refazer_textos(Projeto(a.nome), log=log)),
        "efeitos": ("gera os efeitos sonoros que ainda não estão na biblioteca", lambda a: etapa_efeitos(Projeto(a.nome), a)),
        "render": ("monta o vídeo final", lambda a: etapa_render(Projeto(a.nome), a)),
        "custo": ("mostra a estimativa de gasto e o consumo do Claude", cmd_custo),
        "status": ("mostra o que já está pronto", cmd_status),
        "revisar": ("abre a página de revisão das cenas", cmd_revisar),
    }
    for nome, (ajuda, funcao) in comandos.items():
        s = sub.add_parser(nome, help=ajuda)
        s.add_argument("nome")
        s.add_argument("--sim", action="store_true", help="aprova o gasto sem perguntar")
        s.add_argument("--forcar", action="store_true", help="refaz a etapa. Na narração, só refaz o ritmo, sem custo")
        s.add_argument("--nova-voz", action="store_true", help="gera a narração de novo na GenAIPro, com custo")
        s.add_argument("--direto", action="store_true", help="gera as imagens na hora, sem o modo lote do Google")
        s.add_argument("--sem-avatar", action="store_true", help="monta o vídeo sem o quadro do avatar")
        s.add_argument("--sem-corrigir", action="store_true", help="pula a conferência das cenas antes de renderizar")
        s.add_argument("--vertical", action="store_true",
                       help="no render, monta só a versão em pé (9:16) em final_vertical.mp4; no tudo, monta as duas")
        s.set_defaults(funcao=funcao)

    s = sub.add_parser("trilha", help="o modelo compõe a trilha pelos blocos do roteiro e o código toca (grátis)")
    s.add_argument("nome")
    s.add_argument("--forcar", action="store_true", help="pede uma partitura nova ao modelo e toca de novo")
    s.add_argument("--efeitos", action="store_true", help="mostra também os efeitos que entram no vídeo")
    s.set_defaults(funcao=cmd_trilha)

    s = sub.add_parser("revisar-video", help="o modelo principal olha o vídeo pronto e aponta problemas (grátis)")
    s.add_argument("nome")
    s.add_argument("--cenas", type=int, nargs="*", help="só essas cenas")
    s.set_defaults(funcao=cmd_revisar_video)

    s = sub.add_parser("animacoes", help="anima as cenas de diagrama, texto na tela, linha do tempo e mapa (HyperFrames, grátis)")
    s.add_argument("nome")
    s.add_argument("--cenas", type=int, nargs="*", help="só essas cenas (também anima cena que tinha voltado para a foto)")
    s.add_argument("--forcar", action="store_true", help="pede uma animação nova ao modelo mesmo se a atual estiver em dia")
    s.add_argument("--remover", action="store_true", help="as cenas de --cenas voltam a usar a foto e ficam assim")
    s.set_defaults(funcao=cmd_animacoes)

    s = sub.add_parser("corrigir", help="confere se a mídia de cada cena combina com a narração e troca a que não combina")
    s.add_argument("nome")
    s.add_argument("--cenas", type=int, nargs="*", help="só confere essas cenas")
    s.add_argument("--rodadas", type=int, help="quantas vezes tenta outro material real, por padrão 3")
    s.add_argument("--nota-minima", type=int, help="nota abaixo da qual a cena entra no relatório, por padrão 55")
    s.add_argument("--nota-para-trocar", type=int, help="nota abaixo da qual o sistema troca sozinho, por padrão 35")
    s.add_argument("--avaliar", action="store_true", help="só confere e mostra o resultado, sem trocar nada")
    s.add_argument("--ia", action="store_true", help="depois das trocas de graça, gera imagem nova de IA nas que sobrarem, com custo")
    s.add_argument("--sim", action="store_true", help="aprova o gasto sem perguntar")
    s.set_defaults(funcao=cmd_corrigir)

    s = sub.add_parser("avatar-partes", help="corta a narração nos áudios que vão para o HeyGen")
    s.add_argument("nome")
    s.add_argument("--minutos", type=float, help="tamanho máximo de cada parte, por padrão 29,5")
    s.set_defaults(funcao=cmd_avatar_partes)

    s = sub.add_parser("refazer", help="troca o que aparece nas cenas indicadas")
    s.add_argument("nome")
    s.add_argument("cenas", nargs="+", type=int)
    s.add_argument("--busca", help="novos termos em inglês para buscar foto ou vídeo real")
    s.add_argument("--ia", action="store_true", help="troca a cena por imagem de IA")
    s.add_argument("--prompt", help="nova descrição da imagem de IA, em inglês")
    s.add_argument("--sim", action="store_true")
    s.set_defaults(funcao=cmd_refazer)

    s = sub.add_parser("personagem", help="gera rostos candidatos para a personagem do perfil")
    s.add_argument("--perfil", required=True)
    s.add_argument("--quantidade", type=int, default=4)
    s.add_argument("--sim", action="store_true")
    s.set_defaults(funcao=cmd_personagem)

    s = sub.add_parser("avatar", help="gera um vídeo do personagem falando um áudio, pela DreamAPI")
    s.add_argument("imagem")
    s.add_argument("audio")
    s.add_argument("--resolucao", default="720p", choices=["480p", "720p"])
    s.add_argument("--prompt", default=avatar.PROMPT_PADRAO)
    s.add_argument("--saida")
    s.add_argument("--sim", action="store_true")
    s.set_defaults(funcao=cmd_avatar)

    s = sub.add_parser("meditacao", help="gera o áudio de uma prática guiada, com falas curtas e silêncio longo")
    s.add_argument("nome")
    s.add_argument("--roteiro", help="na primeira vez, o roteiro com as marcações [SILENCIO 90]")
    s.add_argument("--perfil", help="na primeira vez, o perfil com a voz e a música")
    s.add_argument("--offline", action="store_true", help="teste sem custo, com a voz do Mac")
    s.add_argument("--imagem", help="gera também um mp4 com essa imagem parada, para plataforma que só aceita vídeo")
    s.add_argument("--nova-voz", action="store_true", help="grava todas as falas de novo na GenAIPro, com custo")
    s.add_argument("--sim", action="store_true", help="aprova o gasto sem perguntar")
    s.set_defaults(funcao=cmd_meditacao)

    s = sub.add_parser("musica-gerar", help="cria uma trilha instrumental na ElevenLabs Music (opcional, precisa de ELEVENLABS_API_KEY)")
    s.add_argument("descricao", help="descrição da música, de preferência em inglês")
    s.add_argument("--minutos", type=float, default=5.0, help="duração da faixa, no máximo 5")
    s.add_argument("--pasta", default="musicas/meditacao", help="pasta onde a faixa é salva")
    s.add_argument("--nome", help="nome do arquivo, sem a extensão")
    s.add_argument("--modelo", default="music_v2_5", choices=list(musica.MODELOS))
    s.add_argument("--sim", action="store_true", help="aprova o gasto sem perguntar")
    s.set_defaults(funcao=cmd_musica_gerar)

    s = sub.add_parser("estimar", help="mostra quanto tempo de vídeo um roteiro vai dar, sem gastar nada")
    s.add_argument("roteiro")
    s.add_argument("--perfil", required=True)
    s.set_defaults(funcao=cmd_estimar)

    s = sub.add_parser("vozes", help="procura vozes na biblioteca da GenAIPro, sem gastar")
    s.add_argument("termo")
    s.add_argument("--idioma", help="código do idioma, por exemplo pt")
    s.set_defaults(funcao=cmd_vozes)

    s = sub.add_parser("creditos", help="mostra os créditos da GenAIPro e quando vencem, sem gastar")
    s.set_defaults(funcao=cmd_creditos)

    s = sub.add_parser("voz-desenhar", help="cria prévias de uma voz nova a partir de uma descrição (ElevenLabs direta, opcional)")
    s.add_argument("descricao", help="descrição da voz, de preferência em inglês")
    s.add_argument("--rotulo", help="nome curto para reconhecer a variação na página")
    s.add_argument("--texto", help="arquivo com o texto de teste, entre 100 e 1000 caracteres")
    s.add_argument("--modelo", default="eleven_ttv_v3", choices=["eleven_ttv_v3", "eleven_multilingual_ttv_v2"])
    s.add_argument("--nao-abrir", action="store_true", help="não abre a página no navegador")
    s.set_defaults(funcao=cmd_voz_desenhar)

    s = sub.add_parser("voz-salvar", help="guarda na conta da ElevenLabs uma voz criada no voz-desenhar (opcional)")
    s.add_argument("numero", type=int)
    s.add_argument("--nome", required=True)
    s.set_defaults(funcao=cmd_voz_salvar)

    s = sub.add_parser("servidor", help="inicia o servidor de API HTTP (FastAPI) para o frontend")
    s.add_argument("--porta", type=int, default=8000, help="porta do servidor (padrão: 8000)")
    s.add_argument("--host", default="0.0.0.0", help="host do servidor (padrão: 0.0.0.0)")
    s.add_argument("--frontend", default=None, help="pasta do frontend para servir junto")
    s.set_defaults(funcao=cmd_servidor)

    argumentos = parser.parse_args()
    try:
        argumentos.funcao(argumentos)
    except KeyboardInterrupt:
        raise SystemExit("\nInterrompido. Rode o mesmo comando para continuar de onde parou.")
    except RuntimeError as erro:
        raise SystemExit(f"Erro: {erro}")
