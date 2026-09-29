"""Varredura e correção automática de mídia suspeita.

Combina verificar.py (acha o problema pelos dados), midia.py (busca real, de graça),
imagens.py (gera de IA só quando não sobra opção real) e verificar_ia.py (o Gemini olha a
imagem de cada cena e julga se bate com a narração). É o mesmo passo a passo que fazíamos
na mão:
1. acha as cenas com mídia suspeita (id inventado, arquivo duplicado ou sumido);
2. rejeita a mídia suspeita de cada uma e busca material real de novo, de graça;
3. repete por algumas rodadas, porque às vezes a busca nova esbarra em outra cena
   (duas cenas podem escolher o mesmo clipe por coincidência) — então verifica de novo
   até não sobrar problema ou esgotar as rodadas;
4. o que não achou material real vira imagem de IA, com até TENTATIVAS_IMAGEM rodadas
   inteiras de tentativa (cada imagem já tenta de novo sozinha por dentro do imagens.py,
   isso aqui é uma segunda camada pra falhas passageiras da API, tipo "internal error");
5. com o que sobrou "certo" pelos dados, o Gemini olha a imagem/vídeo de cada cena e aponta
   quando o conteúdo não bate com a narração (o bicho errado, um objeto fora de contexto) —
   essa etapa tem custo real, é a única do processo que não é de graça.
"""
from . import imagens, midia, verificar, verificar_ia

MAX_RODADAS_BUSCA = 5
TENTATIVAS_IMAGEM = 2


def _rejeitar_e_limpar(projeto, numeros):
    """Marca a mídia atual dessas cenas como rejeitada e limpa pra uma busca nova."""
    dados = projeto.ler_json("cenas.json")
    por_n = {c["n"]: c for c in dados["cenas"]}
    for n in numeros:
        c = por_n.get(n)
        if not c:
            continue
        m = c.get("midia")
        if m and m.get("fonte") and m.get("id") is not None:
            c.setdefault("rejeitadas", []).append(f"{m['fonte']}:{m['id']}")
        c["midia"] = None
        c.pop("sem_midia_real", None)
        if c.get("tipo") not in midia.TIPOS_REAIS:
            # estado incomum (tinha mídia mas o tipo dizia ia): foto_real é o padrão mais
            # flexível pra buscar de novo, o mesmo usado em imagens.refazer nesse caso
            c["tipo"] = "foto_real"
    projeto.salvar_json("cenas.json", dados)


def _corrigir_prompts_duplicados(projeto, avisos_duplicados, log):
    """Escreve um prompt novo pra cada cena com prompt duplicado, a partir só da narração
    dela, e regenera a imagem — reaproveita o mesmo caminho da correção por conteúdo."""
    dados = projeto.ler_json("cenas.json")
    por_n = {c["n"]: c for c in dados["cenas"]}
    alvo = [por_n[a["cena"]] for a in avisos_duplicados if a["cena"] in por_n]
    if not alvo:
        return 0, []
    novos_prompts = verificar_ia.sugerir_prompts(projeto, alvo, log=log)
    avisos_como_conteudo = [
        {"cena": c["n"], "prompt_sugerido": novos_prompts[c["n"]]}
        for c in alvo if novos_prompts.get(c["n"])
    ]
    sem_prompt_novo = [c["n"] for c in alvo if c["n"] not in novos_prompts]
    if not avisos_como_conteudo:
        return 0, sem_prompt_novo
    corrigidas, com_falha = _corrigir_por_conteudo(projeto, avisos_como_conteudo, log)
    return corrigidas, com_falha + sem_prompt_novo


def _corrigir_por_conteudo(projeto, avisos_conteudo, log):
    """Aplica a sugestão do Gemini: vira cena de IA com o prompt corrigido e regenera."""
    dados = projeto.ler_json("cenas.json")
    por_n = {c["n"]: c for c in dados["cenas"]}
    numeros = []
    for aviso in avisos_conteudo:
        c = por_n.get(aviso["cena"])
        if not c:
            continue
        m = c.get("midia")
        if m and m.get("fonte") and m.get("id") is not None:
            c.setdefault("rejeitadas", []).append(f"{m['fonte']}:{m['id']}")
        c["tipo"] = "ia"
        c["midia"] = None
        c.pop("sem_midia_real", None)
        if aviso.get("prompt_sugerido"):
            c["prompt_manual"] = aviso["prompt_sugerido"]
        numeros.append(c["n"])
    projeto.salvar_json("cenas.json", dados)

    for tentativa in range(TENTATIVAS_IMAGEM):
        cenas_atuais = projeto.ler_json("cenas.json")["cenas"]
        faltando = [c["n"] for c in imagens.pendentes_ia(projeto, cenas_atuais) if c["n"] in numeros]
        if not faltando:
            break
        log(f"  gerando imagem corrigida (tentativa {tentativa + 1}/{TENTATIVAS_IMAGEM}), {len(faltando)} cena(s)")
        imagens.gerar(projeto, apenas=set(faltando), log=log)

    cenas_atuais = projeto.ler_json("cenas.json")["cenas"]
    ainda_faltando = [c["n"] for c in imagens.pendentes_ia(projeto, cenas_atuais) if c["n"] in numeros]
    return len(numeros) - len(ainda_faltando), ainda_faltando


def limpar(projeto, log=print, verificar_conteudo_com_gemini=True) -> dict:
    """Executa a varredura/correção completa. Devolve um resumo do que foi feito.

    verificar_conteudo_com_gemini liga a etapa final que manda a imagem de cada cena pro
    Gemini julgar se bate com a narração — é a única parte que tem custo real de API,
    então quem chama pode desligar (fica só com as checagens de dados, de graça)."""
    avisos_iniciais = verificar.verificar(projeto)
    cenas_suspeitas = sorted(set(a["cena"] for a in avisos_iniciais))
    resultado = {
        "cenas_com_problema_no_inicio": len(cenas_suspeitas),
        "rodadas_de_busca": 0,
        "cenas_resolvidas_com_material_real": 0,
        "imagens_ia_geradas": 0,
        "imagens_ia_com_falha": [],
        "avisos_restantes": [],
        "cenas_conteudo_incompativel": 0,
        "cenas_conteudo_corrigidas": 0,
        "cenas_conteudo_com_falha": [],
        "cenas_prompt_duplicado": 0,
        "cenas_prompt_duplicado_corrigidas": 0,
        "cenas_prompt_duplicado_com_falha": [],
    }

    if not cenas_suspeitas:
        log("  nenhuma mídia suspeita encontrada, projeto já está limpo")
    else:
        log(f"  {len(cenas_suspeitas)} cena(s) com mídia suspeita, buscando material real de novo (de graça)...")
        pendentes = set(cenas_suspeitas)
        for rodada in range(MAX_RODADAS_BUSCA):
            if not pendentes:
                break
            resultado["rodadas_de_busca"] += 1
            _rejeitar_e_limpar(projeto, pendentes)
            midia.buscar(projeto, apenas=pendentes, log=log)
            avisos = verificar.verificar(projeto)
            pendentes = set(a["cena"] for a in avisos)
            if pendentes:
                log(f"  rodada {rodada + 1}: ainda restam {len(pendentes)} cena(s) com mídia suspeita, tentando de novo")

        avisos_finais = verificar.verificar(projeto)
        resultado["avisos_restantes"] = avisos_finais
        cenas_com_problema_no_fim = set(a["cena"] for a in avisos_finais)
        resultado["cenas_resolvidas_com_material_real"] = len(set(cenas_suspeitas) - cenas_com_problema_no_fim)
        if cenas_com_problema_no_fim:
            log(f"  {len(cenas_com_problema_no_fim)} cena(s) continuam com aviso depois de {MAX_RODADAS_BUSCA} rodadas, "
                "seguindo mesmo assim")
        else:
            log("  nenhum aviso de mídia restante")

    cenas = projeto.ler_json("cenas.json")["cenas"]
    pendentes_ia = [c["n"] for c in imagens.pendentes_ia(projeto, cenas)]
    if pendentes_ia:
        log(f"  {len(pendentes_ia)} cena(s) sem material real disponível, precisam de imagem de IA")
        for tentativa in range(TENTATIVAS_IMAGEM):
            cenas_atuais = projeto.ler_json("cenas.json")["cenas"]
            faltando = [c["n"] for c in imagens.pendentes_ia(projeto, cenas_atuais) if c["n"] in pendentes_ia]
            if not faltando:
                break
            log(f"  gerando imagens de IA (tentativa {tentativa + 1}/{TENTATIVAS_IMAGEM}), {len(faltando)} pendente(s)")
            imagens.gerar(projeto, apenas=set(faltando), log=log)
        cenas_atuais = projeto.ler_json("cenas.json")["cenas"]
        ainda_faltando = [c["n"] for c in imagens.pendentes_ia(projeto, cenas_atuais) if c["n"] in pendentes_ia]
        resultado["imagens_ia_com_falha"] = ainda_faltando
        resultado["imagens_ia_geradas"] = len(pendentes_ia) - len(ainda_faltando)
        if ainda_faltando:
            log(f"  {len(ainda_faltando)} imagem(ns) continuam falhando depois de {TENTATIVAS_IMAGEM} tentativas: "
                f"{', '.join(map(str, ainda_faltando))}")

    avisos_duplicados = verificar.verificar_prompts_duplicados(projeto)
    resultado["cenas_prompt_duplicado"] = len(avisos_duplicados)
    if avisos_duplicados:
        log(f"  {len(avisos_duplicados)} cena(s) com prompt de imagem duplicado, escrevendo uma descrição "
            "própria pra cada uma, a partir da narração...")
        corrigidas, com_falha = _corrigir_prompts_duplicados(projeto, avisos_duplicados, log)
        resultado["cenas_prompt_duplicado_corrigidas"] = corrigidas
        resultado["cenas_prompt_duplicado_com_falha"] = com_falha
        if com_falha:
            log(f"  {len(com_falha)} cena(s) com prompt duplicado continuam sem correção: "
                f"{', '.join(map(str, com_falha))}")
    else:
        log("  nenhum prompt de imagem duplicado encontrado")

    if verificar_conteudo_com_gemini:
        try:
            avisos_conteudo = verificar_ia.verificar_conteudo(projeto, log=log)
        except Exception as e:
            log(f"  a verificação de conteúdo com o Gemini falhou, seguindo sem ela: {e}")
            avisos_conteudo = []
        resultado["cenas_conteudo_incompativel"] = len(avisos_conteudo)
        if avisos_conteudo:
            log(f"  {len(avisos_conteudo)} cena(s) com conteúdo incompatível segundo o Gemini, corrigindo...")
            for a in avisos_conteudo:
                log(f"    cena {a['cena']}: {a['detalhe']}")
            corrigidas, com_falha = _corrigir_por_conteudo(projeto, avisos_conteudo, log)
            resultado["cenas_conteudo_corrigidas"] = corrigidas
            resultado["cenas_conteudo_com_falha"] = com_falha
        else:
            log("  nenhuma incompatibilidade de conteúdo encontrada")

    return resultado


def formatar_resultado(r: dict) -> str:
    linhas = []
    if r["cenas_com_problema_no_inicio"] == 0:
        linhas.append("Nenhuma mídia suspeita encontrada.")
    else:
        linhas.append(
            f"{r['cenas_com_problema_no_inicio']} cena(s) tinham mídia suspeita — "
            f"{r['cenas_resolvidas_com_material_real']} resolvidas com material real gratuito."
        )
        if r["avisos_restantes"]:
            linhas.append(f"{len(set(a['cena'] for a in r['avisos_restantes']))} cena(s) continuam com aviso.")
    if r["imagens_ia_geradas"] or r["imagens_ia_com_falha"]:
        linhas.append(f"{r['imagens_ia_geradas']} imagem(ns) de IA geradas.")
        if r["imagens_ia_com_falha"]:
            linhas.append(f"{len(r['imagens_ia_com_falha'])} imagem(ns) falharam: {', '.join(map(str, r['imagens_ia_com_falha']))}")
    if r.get("cenas_prompt_duplicado"):
        linhas.append(
            f"{r['cenas_prompt_duplicado']} cena(s) tinham o mesmo prompt de imagem que outra cena, "
            f"{r.get('cenas_prompt_duplicado_corrigidas', 0)} ganharam uma descrição própria."
        )
        if r.get("cenas_prompt_duplicado_com_falha"):
            linhas.append(f"{len(r['cenas_prompt_duplicado_com_falha'])} continuam com prompt duplicado: "
                          f"{', '.join(map(str, r['cenas_prompt_duplicado_com_falha']))}")
    if r.get("cenas_conteudo_incompativel"):
        linhas.append(
            f"O Gemini achou {r['cenas_conteudo_incompativel']} cena(s) com conteúdo incompatível com a narração, "
            f"{r.get('cenas_conteudo_corrigidas', 0)} corrigidas."
        )
        if r.get("cenas_conteudo_com_falha"):
            linhas.append(f"{len(r['cenas_conteudo_com_falha'])} continuam com problema: {', '.join(map(str, r['cenas_conteudo_com_falha']))}")
    return "\n".join(linhas)
