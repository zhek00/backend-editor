# Comece aqui

Esta é uma fábrica de vídeos. Você entrega um roteiro em texto e ela devolve um MP4 narrado, com fotos e vídeos reais misturados com imagens de IA, cenas animadas e legenda queimada.

**O jeito mais fácil é abrir esta pasta no Claude Code e dizer "me ajuda a começar".** Ele já vem com instruções próprias neste projeto, no arquivo `CLAUDE.md`, e conduz a instalação e o primeiro vídeo passo a passo.

## 1. O que instalar

```bash
brew install uv ffmpeg node
```

No Windows ou Linux, instale o [uv](https://docs.astral.sh/uv/), o [FFmpeg](https://ffmpeg.org/download.html) e o [Node.js 22 ou mais](https://nodejs.org) pelo site de cada um. O Node é opcional: sem ele as cenas animadas ficam com foto.

Depois, dentro desta pasta:

```bash
uv sync
uv sync --project motores_voz/omnivoice
uv sync --project motores_voz/qwen
```

Os dois últimos preparam as vozes open source que narram os vídeos (uns 9 GB, nesta mesma pasta). Os modelos de voz baixam sozinhos na primeira fala.

## 2. As chaves

Copie o arquivo de exemplo e preencha com as suas chaves. O próprio arquivo diz onde criar cada uma.

```bash
cp .env.exemplo .env
```

| Chave | Para quê | Custo |
|---|---|---|
| `OPENROUTER_API_KEY` | imagens de IA, o juiz das cenas e os modelos de reserva | pago por uso, uns US$ 0,005 por imagem |
| `GROQ_API_KEY` | o primeiro modelo de toda etapa | grátis |
| `GEMINI_API_KEY` | descreve as imagens para o juiz | grátis até 500 pedidos por dia |
| `PEXELS_API_KEY` | fotos e vídeos reais | grátis |
| `PIXABAY_API_KEY` | fotos e vídeos reais | grátis |

A narração não precisa de chave nenhuma. As outras chaves do arquivo são opcionais.

## 3. Mais duas coisas antes do primeiro vídeo

**O contato do Wikimedia.** Abra o `config.yaml` e troque `SEU_EMAIL_AQUI` pelo seu e-mail. O Wikimedia recusa buscas sem um contato no pedido.

**A música, se quiser.** Sem música, a fábrica compõe e toca uma trilha sozinha, de graça. Para usar músicas suas, coloque as faixas numa pasta de `musicas/` com um `.txt` de mesmo nome contendo a linha de crédito que o autor pede. Esse crédito entra sozinho no `creditos.txt` do vídeo.

## 4. Teste sem gastar nada

```bash
uv run fabrica novo teste --roteiro exemplos/roteiro-enoque.txt --perfil perfis/livro-de-enoque.yaml --offline
uv run fabrica tudo teste
```

O vídeo fica em `projetos/teste/final.mp4`. O modo offline usa a voz do próprio computador e imagens de teste. As fotos reais do Wikimedia são buscadas de verdade, porque são grátis.

## 5. O primeiro vídeo de verdade

Antes, escolha a voz e crie o seu perfil de canal. Copie um dos arquivos de `perfis/` com outro nome (o `base-documentario.yaml` é um bom começo) e ajuste a voz, o estilo das imagens, a proporção de material real e as diretrizes. A voz vai em `voz.voz_local`, com o código de uma das vozes da lista do editor, como `omnivoice:community_pt_br_lucas`.

```bash
uv run fabrica novo meu-video --roteiro roteiros/meu-roteiro.txt --perfil perfis/meu-canal.yaml
uv run fabrica tudo meu-video
```

A fábrica mostra a estimativa de custo antes de gastar e pede confirmação. Cada etapa salva o que fez, então se algo falhar no meio, o mesmo comando continua de onde parou sem pagar de novo.

## 6. O que não veio junto

- **Chaves e projetos** do dono original, por motivos óbvios.
- **Os clipes do personagem** que aparece no vídeo. Essa parte usa o HeyGen, num plano pago, e cada canal tem o seu. Os perfis `apresentacao.yaml` e `workshop.yaml` dependem dela. Para começar sem isso, use um perfil sem o bloco `avatar`.
- **As músicas**, por causa da licença. Veja o item 3.

## 7. Custo real, para calibrar

Com a narração open source, o gasto é quase todo em imagens de IA (uns US$ 0,005 cada) e nos modelos pagos de reserva, quando os gratuitos acabam no dia. Um vídeo normal fica em centavos por minuto. `uv run fabrica custo NOME` mostra a estimativa e o gasto real, no total e por minuto.

O resto está no `README.md`, que explica cada comando, as marcações do roteiro e como criar um canal novo.
