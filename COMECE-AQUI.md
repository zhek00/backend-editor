# Comece aqui

Esta é uma fábrica de vídeos. Você entrega um roteiro em texto e ela devolve um MP4 narrado, com fotos e vídeos reais misturados com imagens de IA, textos animados na tela e legenda queimada.

**O jeito mais fácil é abrir esta pasta no Claude Code e dizer "me ajuda a começar".** Ele já vem com instruções próprias neste projeto, no arquivo `CLAUDE.md`, e conduz a instalação e o primeiro vídeo passo a passo.

## 1. O que instalar

```bash
brew install uv ffmpeg
```

No Windows ou Linux, instale o [uv](https://docs.astral.sh/uv/) e o [FFmpeg](https://ffmpeg.org/download.html) pelo site de cada um.

Depois, dentro desta pasta:

```bash
uv sync
```

## 2. As chaves

Copie o arquivo de exemplo e preencha com as suas chaves.

```bash
cp .env.exemplo .env
```

| Chave | Onde criar | Custo |
|---|---|---|
| `ELEVENLABS_API_KEY` | elevenlabs.io, num plano pago, que libera uso comercial | uns US$ 0,10 por mil caracteres |
| `GEMINI_API_KEY` | aistudio.google.com/apikey, com faturamento ativo | US$ 0,034 por imagem no modo lote |
| `PEXELS_API_KEY` | pexels.com/api | grátis |
| `PIXABAY_API_KEY` | pixabay.com/api/docs | grátis |

Na chave da ElevenLabs, marque acesso de leitura em Text to Speech e de escrita em Vozes.

O `DREAMAPI_KEY` e o `FAL_KEY` são opcionais e só servem para caminhos alternativos.

## 3. O Claude

A divisão em cenas e a escolha das fotos são feitas pelo Claude. Por padrão isso roda pela **sua assinatura do Claude Code**, sem gastar créditos de API. Basta estar logado.

```bash
claude
# dentro dele, digite /login
```

Se preferir usar a API e pagar por token, troque `claude.via` para `api` no `config.yaml` e preencha `ANTHROPIC_API_KEY` no `.env`.

## 4. Mais duas coisas antes do primeiro vídeo

**O contato do Wikimedia.** Abra o `config.yaml` e troque `SEU_EMAIL_AQUI` pelo seu e-mail. O Wikimedia recusa buscas sem um contato no pedido.

**A música.** As pastas em `musicas/` vêm só com o arquivo de crédito. Baixe as faixas que você quiser, de preferência do Pixabay, coloque na pasta e escreva um `.txt` com o mesmo nome contendo a linha de crédito que o autor pede. Esse crédito entra sozinho no `creditos.txt` do vídeo.

## 5. Teste sem gastar nada

```bash
uv run fabrica novo teste --roteiro exemplos/roteiro-enoque.txt --perfil perfis/livro-de-enoque.yaml --offline
uv run fabrica tudo teste
open projetos/teste/final.mp4
```

O modo offline usa a voz do próprio Mac e imagens de teste. As fotos reais do Wikimedia são buscadas de verdade, porque são grátis.

## 6. O primeiro vídeo de verdade

Antes, crie a sua voz e o seu perfil de canal.

```bash
# procurar uma voz pronta na biblioteca da ElevenLabs
uv run fabrica vozes "narrador grave"

# ou criar uma voz original a partir de uma descrição
uv run fabrica voz-desenhar "Elderly man with a deep, gravelly voice" --rotulo "grave"
uv run fabrica voz-salvar 2 --nome "Narrador do canal"
```

Copie o código que aparece para `voz.voice_id` no perfil. Depois copie um dos arquivos de `perfis/` com outro nome e ajuste voz, estilo das imagens, proporção de material real e diretrizes.

```bash
uv run fabrica novo meu-video --roteiro roteiros/meu-roteiro.txt --perfil perfis/meu-canal.yaml
uv run fabrica tudo meu-video
```

A fábrica mostra a estimativa de custo antes de gastar e pede confirmação. Cada etapa salva o que fez, então se algo falhar no meio, o mesmo comando continua de onde parou sem pagar de novo.

## 7. O que não veio junto

- **Chaves, projetos e vozes** do dono original, por motivos óbvios.
- **Os clipes do personagem** que aparece no vídeo. Essa parte usa o HeyGen, num plano pago, e cada canal tem o seu. Os perfis `apresentacao.yaml` e `workshop.yaml` dependem dela. Para começar sem isso, use um perfil sem o bloco `avatar`, como o `livro-de-enoque.yaml`.
- **As músicas**, por causa da licença. Veja o item 4.

## 8. Custo real, para calibrar

Um vídeo de 36 minutos com 250 cenas, 60% de material real e 94 imagens de IA saiu por uns **US$ 5,60, algo como US$ 0,16 por minuto**. A maior parte é imagem. A narração foi US$ 1,91 e o Claude não custou nada além da assinatura.

O resto está no `README.md`, que explica cada comando, os textos animados na tela, as marcações do roteiro e como criar um canal novo.
