"""A figura do motion: a foto própria do sujeito, buscada nos bancos para o desenho, recortada como figurinha.

Pedido do usuário em 2026-10-08, depois dos 5 motions da ariranha (cena 191 do 11-animais-do-brasil): "você já se
limita indo buscar fotos da lontra que já tem no projeto... você tem banco de imagens, de forma livre e grátis". A
foto da cena foi escolhida para a cena, não para o desenho: para medir o comprimento, a ariranha tem de estar de corpo
inteiro e de perfil, com a cauda à vista; nas 9 fotos do projeto, nenhuma estava. Nos bancos, a do Pixabay (deitada de
perfil, do focinho à ponta da cauda) virou o clipe que o usuário escolheu.

O caminho, tudo de graça (bancos gratuitos, cadeia de visão só com os gratuitos e o recorte no próprio computador):
1. busca o animal nos bancos (iNaturalist, Wikimedia, Pexels, Pixabay, Unsplash), pelo nome e pelo nome científico;
2. a visão olha a folha de candidatos e escolhe a que serve ao desenho (corpo inteiro, de perfil, a espécie certa),
   dizendo onde o bicho está na foto e para que lado a cabeça aponta;
3. o recorte sai em várias versões (pela caixa que a visão deu, pelas margens, e sem a vegetação grudada), sempre com
   a cabeça para a direita;
4. a visão aprova uma versão e aponta onde fica a parte citada na fala ("a cauda"), para o destaque.
Sem nada que sirva, devolve None e o clipe segue com a foto da cena (foto_da_cena) ou outro desenho.
"""
import hashlib
import json
import shutil
from pathlib import Path

VERSAO = 7  # suba quando mudar a busca, a escolha ou o recorte: a figura guardada é refeita

INSTRUCOES_ESCOLHA = """Você escolhe a foto de um animal para um clipe de motion graphics que mostra uma medida
(o comprimento, a altura) com o próprio bicho recortado. Cada número da folha é uma foto. A foto serve quando:
- é o animal citado, a espécie certa (nunca outro bicho parecido);
- o animal está de corpo inteiro, da cabeça à ponta da cauda, nada cortado pela borda;
- está de perfil (de lado), esticado, de preferência parado num fundo que contrasta com ele;
- um animal só, ou um bem destacado dos outros.
Responda o número da melhor foto (-1 se nenhuma serve), a caixa do animal nela (x0, y0, x1, y1, frações de 0 a 1 da
largura e da altura da foto, com o corpo e a cauda inteiros dentro) e para que lado a cabeça aponta."""

ESQUEMA_ESCOLHA = {
    "type": "object",
    "properties": {"numero": {"type": "integer"}, "caixa": {"type": "array", "items": {"type": "number"}},
                   "cabeca": {"type": "string", "enum": ["esquerda", "direita"]}, "motivo": {"type": "string"}},
    "required": ["numero"],
}

INSTRUCOES_RECORTE = """Você aprova o recorte de um animal para uma colagem de motion graphics. Cada número da folha é
um recorte diferente da MESMA foto, com borda branca de figurinha, sobre um fundo cinza-azulado liso. Um recorte serve
quando mostra o animal inteiro (cabeça, corpo, patas e cauda) e NADA do fundo da foto: qualquer pedaço de outra cor
grudado na borda (céu, capim, folhas, água, pedra, galho, outro bicho) reprova. Entre os que servem, prefira o mais
justo ao contorno do animal. Responda o número do melhor que serve (0 se nenhum serve). Se o pedido citar uma parte do
corpo, diga onde ela fica NO RECORTE ESCOLHIDO: a caixa x0, y0, x1, y1 em frações de 0 a 1 da largura e da altura dele."""

ESQUEMA_RECORTE = {
    "type": "object",
    "properties": {"melhor": {"type": "integer"}, "parte": {"type": "array", "items": {"type": "number"}},
                   "motivo": {"type": "string"}},
    "required": ["melhor"],
}

# onde a parte costuma ficar num bicho de perfil olhando para a direita, quando a visão não apontou
PARTES = {"cauda": (0.0, 0.45, 0.26, 1.0), "rabo": (0.0, 0.45, 0.26, 1.0), "cabeça": (0.74, 0.0, 1.0, 0.55),
          "cabeca": (0.74, 0.0, 1.0, 0.55), "focinho": (0.82, 0.05, 1.0, 0.5), "pata": (0.55, 0.65, 1.0, 1.0),
          "patas": (0.45, 0.65, 1.0, 1.0), "pescoço": (0.66, 0.15, 0.9, 0.6), "pescoco": (0.66, 0.15, 0.9, 0.6)}


def _caixa(valores):
    """A caixa conferida (x0 < x1, y0 < y1, entre 0 e 1), ou None."""
    try:
        x0, y0, x1, y1 = (float(v) for v in valores)
    except (TypeError, ValueError):
        return None
    if max(x0, y0, x1, y1) > 1.5:  # veio em porcentagem
        x0, y0, x1, y1 = x0 / 100, y0 / 100, x1 / 100, y1 / 100
    x0, y0, x1, y1 = (max(0.0, min(1.0, v)) for v in (x0, y0, x1, y1))
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:
        return None
    return [round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)]


def parte_padrao(parte):
    """A caixa provável da parte citada ("cauda achatada" -> a cauda), num bicho olhando para a direita."""
    for palavra in (parte or "").lower().split():
        if palavra in PARTES:
            return list(PARTES[palavra])
    return None


def _candidatos(projeto, cena, log):
    from . import midia
    nomes = [n for n in dict.fromkeys([(cena.get("animal") or "").strip(), (cena.get("exato") or "").strip()]) if n]
    alternativa = (cena.get("busca_alternativa") or "").strip()
    if alternativa and len(alternativa.split()) <= 3:
        nomes.append(alternativa)  # o nome científico, que o agente costuma pôr aqui
    if not nomes:
        return [], None
    buscador = midia.Buscador(projeto, log)
    listas = []
    for nome in nomes[:3]:
        for fonte in ("inaturalist", "wikimedia", "pixabay", "pexels", "unsplash"):
            try:
                listas.append([c for c in buscador._buscar(fonte, "foto", nome) if c.get("miniatura")])
            except (Exception, SystemExit):
                continue
    vistos, achados, rodada = set(), [], 0
    while len(achados) < 16 and any(rodada < len(lista) for lista in listas):
        for lista in listas:
            if rodada < len(lista):
                c = lista[rodada]
                chave = (c.get("fonte"), c.get("id"))
                if chave not in vistos:
                    vistos.add(chave)
                    achados.append(c)
        rodada += 1
    return achados[:16], buscador


def _folha(projeto, pasta, candidatos, http):
    from PIL import Image, ImageDraw
    from . import midia
    celula_l, celula_a, colunas = 400, 280, 4
    linhas = -(-len(candidatos) // colunas)
    folha = Image.new("RGB", (colunas * celula_l, linhas * celula_a), (18, 18, 18))
    desenho = ImageDraw.Draw(folha)
    fonte = midia._fonte(34)
    validos = []
    for i, candidato in enumerate(candidatos):
        miniatura = midia._miniatura(http, candidato["miniatura"])
        if miniatura is None:
            continue
        x, y = (i % colunas) * celula_l, (i // colunas) * celula_a
        miniatura.thumbnail((celula_l - 8, celula_a - 8))
        folha.paste(miniatura, (x + (celula_l - miniatura.width) // 2, y + (celula_a - miniatura.height) // 2))
        desenho.rectangle([x + 6, y + 6, x + 22 + fonte.getlength(str(i)), y + 48], fill=(0, 0, 0))
        desenho.text((x + 14, y + 8), str(i), font=fonte, fill=(255, 214, 0))
        validos.append(i)
    destino = pasta / "figura_candidatos.jpg"
    folha.save(destino, quality=85)
    return destino, validos


def figura(projeto, pasta, cena, parte="", log=print):
    """A figurinha do sujeito para o clipe, em pasta/assets/figura.png, olhando para a direita. Devolve
    {"arquivo", "parte" (a caixa da parte citada no recorte, ou None), "credito"} ou None. Guardada em figura.json
    pelo animal e pela parte: não busca nem pergunta de novo."""
    from . import midia, openrouter_local, recorte
    nome = (cena.get("animal") or cena.get("exato") or "").strip()
    if not nome:
        return None
    marca = hashlib.sha1(f"{nome}|{parte}|v{VERSAO}".encode()).hexdigest()[:12]
    arquivo = pasta / "figura.json"
    try:
        guardada = json.loads(arquivo.read_text(encoding="utf-8"))
        if guardada.get("marca") == marca and (guardada.get("arquivo") is None
                                               or (pasta / "assets" / guardada["arquivo"]).exists()):
            return guardada if guardada.get("arquivo") else None
    except (OSError, ValueError):
        pass

    def guardar(resultado, motivo):
        dados = {"marca": marca, "motivo": motivo, **(resultado or {"arquivo": None})}
        arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"  motion IA: cena {cena['n']}, " + (f"figura própria dos bancos ({dados['credito'].get('fonte')}, "
                                                  f"{'foto inteira' if dados.get('moldura') else 'recortada'})"
                                                  if resultado else f"sem figura própria ({motivo})"))
        return resultado

    candidatos, buscador = _candidatos(projeto, cena, log)
    if not candidatos:
        return guardar(None, "nenhum candidato nos bancos")
    folha, validos = _folha(projeto, pasta, candidatos, buscador.http)
    if not validos:
        return guardar(None, "nenhuma miniatura baixou")
    try:
        escolha = openrouter_local.VISAO.perguntar(
            projeto, "motion IA: foto para a figura", INSTRUCOES_ESCOLHA,
            f"O animal: {nome}. Números válidos: {', '.join(map(str, validos))}.", ESQUEMA_ESCOLHA, log=log,
            imagens=[folha], temperatura=0, so_gratuitos=True) or {}
        numero = int(escolha.get("numero", -1))
    except (RuntimeError, SystemExit, ValueError, TypeError) as e:
        return guardar(None, f"a visão não escolheu ({str(e)[:80]})")
    if numero not in validos:
        return guardar(None, "nenhuma foto de corpo inteiro e de perfil")
    candidato = candidatos[numero]
    original = pasta / "figura_original.jpg"
    try:
        midia._baixar(buscador.http, candidato["arquivo"], original)
        midia._garantir_jpeg(original)
    except Exception as e:  # noqa: BLE001 (o banco caiu: segue sem a figura própria)
        return guardar(None, f"o download falhou ({str(e)[:80]})")
    espelhar = str(escolha.get("cabeca") or "direita") == "esquerda"
    caixa = _caixa(escolha.get("caixa") or [])
    pasta_r = pasta / "figuras"
    shutil.rmtree(pasta_r, ignore_errors=True)
    opcoes = []
    # a caixa bem mais larga primeiro: a da visão costuma começar depois da ponta da cauda
    jeitos = ([dict(caixa=caixa, sem_verde=True, folga=2.5), dict(caixa=caixa), dict(caixa=caixa, sem_verde=True)]
              if caixa else []) + \
             [dict(margem=0.04, sem_verde=True), dict(margem=0.02, sem_verde=True), dict(margem=0.06)]
    # sem a caixa, as margens pequenas: a de 12% cortava a cauda da ariranha, que começa a 10% da borda da foto
    for k, jeito in enumerate(jeitos, 1):
        feito = recorte.recortar(original, pasta_r / f"figura_{k}.png", espelhar=espelhar, lado=1600, **jeito)
        # o fundo grudado e as pontas que a visão gratuita deixa passar (o céu atrás do mico, as folhas espetadas no
    # pirarucu): fora antes de ela olhar
        if feito and recorte.limpo(feito):
            opcoes.append(feito)
    credito = {k: candidato.get(k) for k in ("fonte", "id", "autor", "licenca", "pagina")}
    credito["tipo"] = "foto"

    def so_a_foto(motivo):
        # sem recorte limpo, a foto escolhida inteira (numa moldura de papel rasgado no clipe): o mico do
        # 11-animais-do-brasil sempre vem num galho, e nenhum recorte saiu sem o fundo
        (pasta / "assets").mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, pasta / "assets" / "figura_foto.jpg")
        return guardar({"arquivo": "figura_foto.jpg", "moldura": True, "parte": None, "credito": credito},
                       f"só a foto ({motivo})")

    if not opcoes:
        return so_a_foto("nenhum recorte passou nas contas")
    pedido = f"O animal: {nome}. Há {len(opcoes)} recorte(s)."
    if parte:
        pedido += f" A parte citada na fala: {parte}."
    try:
        resposta = openrouter_local.VISAO.perguntar(
            projeto, "motion IA: recorte da figura", INSTRUCOES_RECORTE, pedido, ESQUEMA_RECORTE, log=log,
            imagens=[recorte.folha(opcoes, pasta_r / "folha.jpg")], temperatura=0, so_gratuitos=True) or {}
        melhor = int(resposta.get("melhor") or 0)
    except (RuntimeError, SystemExit, ValueError, TypeError) as e:
        return so_a_foto(f"a visão não aprovou o recorte: {str(e)[:80]}")
    if not 1 <= melhor <= len(opcoes):
        return so_a_foto("nenhum recorte limpo")
    (pasta / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copy2(opcoes[melhor - 1], pasta / "assets" / "figura.png")
    caixa_parte = _caixa(resposta.get("parte") or []) or parte_padrao(parte) if parte else None
    return guardar({"arquivo": "figura.png", "parte": caixa_parte, "credito": credito}, "ok")
