"""A língua do vídeo e a regra de que todo texto que aparece na tela vai nela.

Pedido do usuário em 2026-10-14, depois do everything-you-need-to-answer (roteiro em inglês, para americanos): a cena
8 saiu com "10 SUPERMERCADOS • 3 SEMANAS • DEZENAS DE FRANGOS" na tela. "Tudo que for escrito na tela deve ser na
língua do roteiro: se o roteiro é em pt-br, motion, animação, textos, tudo em pt-br; a mesma coisa para o inglês."

A causa: a regra global do openrouter_local mandava toda resposta em português do Brasil (ela existe para os textos
internos da fábrica: descrições, motivos, notas do Jev), e os pedidos de texto de tela (o overlay do roteirista, as
animações, o motion, o kit de publicação, os shorts) não diziam a língua. Agora:
- lingua(projeto): a língua do roteiro inteiro (pt, en ou es), pelas palavras que só cada uma tem;
- regra_da_tela(projeto): a frase que vai em todo pedido de texto de tela;
- outra_lingua(textos, lingua): as palavras de tela que são de outra língua (a última barreira, antes de desenhar).
"""
import re
import unicodedata

NOMES = {"pt": "português do Brasil", "en": "inglês (English)", "es": "espanhol (español)"}
LOCALES = {"pt": "pt-BR", "en": "en-US", "es": "es-ES"}

# palavras curtas e comuns que só uma das línguas tem (sem acento, depois de normalizar)
SO_DE = {
    "pt": {"o", "que", "os", "da", "das", "dos", "em", "na", "nas", "nos", "um", "uma", "para", "com", "nao", "mais",
           "seu", "sua", "ao", "pelo", "pela", "foi", "sao", "esta", "como", "quando", "muito", "tambem", "mas", "ja",
           "ate", "sem", "quem", "onde", "cada", "voce", "isso", "ele", "ela", "eles", "porque", "entao"},
    "en": {"the", "and", "of", "to", "is", "are", "was", "were", "that", "with", "for", "you", "your", "it", "this",
           "they", "we", "have", "has", "what", "which", "from", "but", "not", "will", "their", "there", "be", "been",
           "would", "about", "when", "who", "how", "than", "every"},
    "es": {"el", "los", "las", "del", "que", "una", "por", "para", "con", "pero", "muy", "esta", "este", "como",
           "cuando", "donde", "usted", "ellos", "tambien", "porque", "hay", "fue", "son", "sus", "al", "lo", "le"},
}
# palavras de cada língua que se reconhecem pelo jeito (acento, cedilha, terminação), mesmo sozinhas num título
JEITO_DE = {
    "pt": re.compile(r"[ãõç]|(?:ção|ções|cao|coes|mente|dade|dades|agem|eiro|eira|ado|ados|ada|adas|ido|idos)$"),
    "es": re.compile(r"[ñ¿¡]|(?:ción|ciones|mente|dad|dades)$"),
    "en": re.compile(r"(?:tion|tions|ness|ing|ly|ed)$"),
}


def normal(texto) -> str:
    texto = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")


def lingua_do_texto(texto):
    """"pt", "en", "es" ou None, pelas palavras que só cada uma tem (precisa de pelo menos duas)."""
    palavras = re.findall(r"[a-z]+", normal(texto))
    contagem = {l: sum(p in s for p in palavras) for l, s in SO_DE.items()}
    melhor = max(contagem, key=contagem.get)
    segundo = sorted(contagem.values())[-2]
    return melhor if contagem[melhor] >= 2 and contagem[melhor] > segundo else None


_CACHE = {}


def lingua(projeto, padrao="pt") -> str:
    """A língua do roteiro do projeto (o roteiro inteiro, não a fala de uma cena: "Ten supermarkets." é curto demais)."""
    try:
        arquivo = projeto.pasta / "roteiro.txt"
        chave = (str(arquivo), arquivo.stat().st_mtime_ns)
    except (OSError, AttributeError):
        return padrao
    if chave not in _CACHE:
        try:
            texto = arquivo.read_text(encoding="utf-8")[:30000]
        except OSError:
            texto = ""
        _CACHE[chave] = lingua_do_texto(texto) or padrao
    return _CACHE[chave]


def nome(projeto_ou_lingua) -> str:
    codigo = projeto_ou_lingua if isinstance(projeto_ou_lingua, str) else lingua(projeto_ou_lingua)
    return NOMES.get(codigo, codigo)


def locale(projeto) -> str:
    return LOCALES.get(lingua(projeto), "pt-BR")


def regra_da_tela(projeto) -> str:
    """A frase para todo pedido que escreve texto que aparece no vídeo ou para o público."""
    return (f"LÍNGUA DO QUE APARECE NA TELA: todo texto que vai aparecer no vídeo ou para o público (texto na tela, "
            f"overlay, títulos, rótulos, legendas de gráfico, números por extenso, títulos de capítulo, título e "
            f"descrição do YouTube, títulos de shorts, texto de thumbnail) vai em {nome(projeto)}, a língua do roteiro "
            f"e da narração. Nunca em outra língua, nem uma palavra só. Use as palavras da própria narração.")


def outra_lingua(textos, lingua_do_video, fala="") -> list:
    """As palavras de tela que são de outra língua e a fala não diz: a tela traduzida em vez da fala resumida."""
    if not lingua_do_video:
        return []
    ditas = set(re.findall(r"[a-z]+", normal(fala)))
    fora = []
    for texto in textos if isinstance(textos, (list, tuple)) else [textos]:
        for bruta in re.findall(r"[^\W\d_]+", re.sub(r"\*", "", str(texto or "")).lower()):
            w = normal(bruta)
            if w in ditas or len(w) < 1:
                continue
            for outra, palavras in SO_DE.items():
                if outra == lingua_do_video:
                    continue
                if w in palavras and w not in SO_DE.get(lingua_do_video, set()):
                    fora.append(w)
                    break
                if outra != "en" and JEITO_DE[outra].search(bruta) and lingua_do_video == "en":
                    fora.append(w)
                    break
    return list(dict.fromkeys(fora))
