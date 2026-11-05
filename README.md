# Fábrica de vídeos

Roteiro pronto entra, vídeo narrado sai, misturando fotos e vídeos reais com imagens de IA.

## Como funciona

1. **Narração.** As vozes open source (OmniVoice, Kokoro e Qwen3-TTS) rodam dentro da própria fábrica, na placa de vídeo, sem chave e sem custo. O tempo de cada palavra vem do Whisper do Groq.
2. **Cenas.** O agente de roteiro lê o roteiro inteiro, divide a narração em cenas de 3 a 5 segundos e decide, para cada uma, se vai foto real, vídeo real ou imagem de IA, com os termos de busca e a descrição.
3. **Material real.** O sistema busca em até onze bancos ao mesmo tempo (Wikimedia, Pexels, Pixabay, Unsplash, iNaturalist e acervos de museu). Um modelo de visão olha as miniaturas e escolhe, e o Jev confere se a imagem mostra o que a narração fala.
4. **Imagens de IA.** O GPT-5.4 Image 2, pelo OpenRouter, gera só as cenas que nenhum banco resolveu, até 35% do vídeo.
5. **Animações.** Listas, datas, comparações e números viram cenas animadas (HyperFrames), misturadas com as fotos.
6. **Render.** O FFmpeg monta tudo: movimento lento nas fotos, animações, trilha composta pela fábrica e legenda.

Os modelos de texto e de visão vão primeiro pelos gratuitos (Groq e os gratuitos do OpenRouter) e só depois pelos pagos. Cada etapa salva o que fez. Se algo falhar no meio, o mesmo comando continua de onde parou sem pagar de novo.

## Preparação, uma vez só

1. Copie `.env.exemplo` para `.env` e cole as chaves. As obrigatórias são OpenRouter, Groq, Google (Gemini), Pexels e Pixabay; o arquivo diz onde criar cada uma. O Wikimedia Commons não precisa de chave, mas exige um contato em `midia.contato` no `config.yaml`.
2. Prepare os motores de voz, uma vez (uns 9 GB):

   ```bash
   uv sync --project motores_voz/omnivoice
   uv sync --project motores_voz/qwen
   ```

3. Escolha a voz pela lista do editor, com prévia, e ponha o código dela em `voz.voz_local` no perfil (`kokoro:pm_alex`, `qwen:Ryan`, `omnivoice:community_pt_br_lucas`).
4. Para as animações, instale o Node.js 22 ou mais. Sem ele essas cenas ficam com foto.
5. Só para perfis com personagem, efeitos sonoros ou abertura: essas partes ainda usam o Claude da sua assinatura. Abra o terminal, digite `claude` e, dentro dele, `/login`. Os outros perfis não precisam.

## Teste sem custo

Usa a voz do computador e imagens de teste no lugar das de IA. As fotos reais do Wikimedia são buscadas de verdade, porque são grátis.

```bash
uv run fabrica novo teste --roteiro exemplos/roteiro-enoque.txt --perfil perfis/livro-de-enoque.yaml --offline
uv run fabrica tudo teste
open projetos/teste/final.mp4   # no Windows: start projetos/teste/final.mp4
```

## Vídeo de verdade

Crie o projeto e gere o vídeo. Antes de gastar, a fábrica mostra a estimativa e pede confirmação.

```bash
uv run fabrica novo vigilantes --roteiro roteiros/vigilantes.txt --perfil perfis/livro-de-enoque.yaml
uv run fabrica tudo vigilantes
```

Revise as cenas, troque as ruins e renderize de novo. O render só refaz os trechos que mudaram.

```bash
uv run fabrica revisar vigilantes
uv run fabrica refazer vigilantes 12 31
uv run fabrica refazer vigilantes 18 --busca "qumran caves interior"
uv run fabrica refazer vigilantes 22 --ia
uv run fabrica refazer vigilantes 25 --prompt "Two hundred luminous giant figures descending on a mountain at night"
uv run fabrica render vigilantes
```

Sem opções, a cena real ganha outro candidato e a cena de IA ganha outra imagem. `--busca` procura material real com novos termos. `--ia` e `--prompt` trocam a cena por imagem de IA.

Se o canal tiver personagem fixa, gere rostos, escolha um, copie para a pasta `personagens` e coloque o caminho em `personagem.referencias` no perfil.

```bash
uv run fabrica personagem --perfil perfis/vo-cida.yaml
```

## Aula com avatar no canto

Com o bloco `avatar` no perfil, como em `perfis/workshop.yaml`, o vídeo ganha um quadro no canto com o personagem falando, do jeito de aula online. O rosto vem do HeyGen e a voz continua sendo a da fábrica.

1. `uv run fabrica narrar NOME` gera a narração e já corta os áudios em partes de até 29,5 minutos, em `projetos/NOME/avatar/parte_1.mp3` e seguintes.
2. Suba cada áudio no HeyGen, gere o avatar em retrato e salve os vídeos na mesma pasta como `parte_1.mp4`, `parte_2.mp4` e assim por diante.
3. `uv run fabrica render NOME` encaixa os vídeos no tempo certo, confere se o HeyGen mexeu no silêncio do começo e desvia a legenda do quadro.

`uv run fabrica avatar-partes NOME --minutos 10` refaz o corte com outro tamanho. `--sem-avatar` no render monta o vídeo sem o quadro. Forma, tamanho, posição e moldura ficam no bloco `avatar` do perfil.

## Símbolo de pausa e títulos

Escreva `[SIMBOLO]` numa linha do roteiro e o símbolo do perfil aparece na tela quando a frase anterior termina, some sozinho e o vídeo não para. Escreva `[TITULO] Nome da parte` numa linha e o título aparece num cartão centralizado quando a primeira frase da parte começa, numerado como PARTE I, PARTE II e assim por diante. Nenhuma das duas marcações é narrada. Imagem, tempo na tela e posição ficam nos blocos `simbolo` e `titulos` do perfil.

## Personagem no meio do vídeo

Com `avatar.modo: trechos`, o personagem só aparece onde o roteiro marca `[AVATAR]` e `[/AVATAR]`, e `[INSERTO nome]` encaixa um clipe fixo da pasta `avatar_fixos`. O clipe fixo não entra colado na última palavra. Ele usa parte da pausa natural da narração para o personagem respirar antes de falar, o tempo em `pausa_antes_inserto`. Quando dois vídeos do personagem vêm seguidos, a troca é uma fusão curta, o tempo em `transicao`, e o personagem não some da tela no meio. A fala dos clipes fixos entra na legenda, a partir do texto salvo no `.txt` ao lado do clipe.

## Efeitos sonoros

Com `efeitos.ativo: true` no perfil, o Claude marca as cenas em que a narração mostra algo com som de verdade, como trovão, trombeta ou fogo, e diz em que palavra o som bate. `uv run fabrica efeitos NOME` gera na ElevenLabs direta (opcional, precisa de `ELEVENLABS_API_KEY`) só os sons que ainda não existem na biblioteca `efeitos/`, e o render encaixa cada um na palavra certa, por baixo da narração. O mesmo som é reaproveitado em qualquer vídeo que peça ele. O volume fica em `efeitos.volume_db`.

## Abertura sem fala

Com o bloco `abertura` no perfil, o vídeo começa com uma prévia de alguns segundos, sem narração, com cenas do próprio vídeo passando rápido sobre o trecho mais intenso da música do bloco. O Claude escolhe as cenas pelas descrições e a escolha fica em `abertura.json` no projeto. Para trocar as cenas, edite ou apague esse arquivo e rode o render de novo. Duração, tempo de cada cena, clarão no corte e volume ficam no bloco. Como a abertura empurra todo o resto, a legenda para subir no YouTube passa a ser `legendas_final.srt`.

## Imagens em lote

Só com o provedor `google` nas imagens. Com `imagens.lote: true` no `config.yaml`, as imagens de IA vão de uma vez para o modo lote do Google, pela metade do preço. O Google promete o resultado em até 24 horas e costuma entregar em minutos. Se o programa parar no meio da espera, rodar o mesmo comando continua esperando o mesmo lote. `--direto` força a geração na hora.

## Prática guiada, só áudio

Para uma meditação guiada, em que a voz fala pouco e o silêncio é longo, o roteiro é texto comum com a marcação `[SILENCIO 90]` numa linha própria. O tempo vai em segundos ou em minutos e segundos, como `[SILENCIO 1:30]`. A voz do perfil grava só as falas, uma por vez, e o silêncio vem do FFmpeg, sem custo. A música do perfil entra baixa por baixo de tudo.

```bash
uv run fabrica meditacao pratica --roteiro roteiros/pratica.txt --perfil perfis/meditacao.yaml
```

O resultado fica em `projetos/pratica/meditacao.mp3`. Com `--imagem capa.png` sai também um `meditacao.mp4` com a imagem parada, para plataforma que só aceita vídeo. Cada fala gravada fica guardada, então mudar uma frase e rodar de novo só regrava aquela fala. Para testar sem custo, acrescente `--offline` na primeira vez.

A trilha ambiente pode ser gerada na ElevenLabs Music (opcional, precisa de `ELEVENLABS_API_KEY`), que libera uso comercial nos planos pagos. Cada geração rende até 5 minutos, e a fábrica emenda a faixa com transição suave até cobrir o áudio inteiro.

```bash
uv run fabrica musica-gerar "Slow ambient meditation pad, soft warm drones, no melody, no percussion, very calm" --minutos 5 --nome ambiente-1
```

## Vozes

A narração usa as vozes open source do VoiceStudio e do voicebox (588 hoje), rodando dentro da fábrica. O editor mostra a lista com filtros de idioma e gênero e um botão para ouvir cada uma. O código da escolhida vai em `voz.voz_local` no perfil. A Fish Audio (grátis, pelo OpenRouter) também serve, com `voz.provedor: fish`.

Os comandos `vozes` e `creditos` (biblioteca e saldo da GenAIPro) e `voz-desenhar` e `voz-salvar` (ElevenLabs direta) continuam na fábrica, mas a narração não usa mais esses serviços.

## Comandos

| Comando | O que faz |
|---|---|
| `novo` | cria um projeto com roteiro e perfil |
| `tudo` | narração, cenas, material real, imagens, animações, trilha e render em sequência |
| `mapa`, `narrar`, `cenas`, `midia`, `imagens`, `animation-ai`, `trilha`, `render` | cada etapa separada, e `--forcar` refaz do zero |
| `refazer` | troca o que aparece em cenas específicas |
| `revisar` | abre a página com todas as cenas |
| `servidor` | sobe o servidor do editor (no Windows, o `LIGAR-TIPLABS.ps1` sobe tudo) |
| `publicacao`, `thumbs`, `shorts`, `publicar` | kit do YouTube, capas, shorts e envio |
| `custo`, `consumo`, `tempos` | estimativa e gasto, planilha do OpenRouter e onde foi o tempo |
| `status` | mostra o que já está pronto |
| `restaurar` | volta um projeto excluído no editor (lixeira de 7 dias) |

A lista completa, com o que cada um faz, está em `uv run fabrica --help` e no `CLAUDE.md`.

## Onde fica cada coisa

| Caminho | Conteúdo |
|---|---|
| `perfis/` | um arquivo por canal, com voz, estilo, proporção de material real, personagem e ritmo |
| `config.yaml` | preços para a estimativa, modelos de cada etapa e qualidade do render |
| `projetos/NOME/final.mp4` | vídeo pronto |
| `projetos/NOME/creditos.txt` | créditos das fotos e vídeos reais, para a descrição do vídeo |
| `projetos/NOME/legendas_final.srt` | legenda para subir junto no YouTube, já com a abertura e as falas dos clipes fixos |
| `efeitos/` | biblioteca de efeitos sonoros do canal, reaproveitados entre vídeos |
| `projetos/NOME/revisao.html` | página de revisão das cenas |
| `musicas/` | músicas livres de direitos, apontadas no campo `musica` do perfil (sem elas, a fábrica compõe a trilha) |
| `motores_voz/` | os motores das vozes open source, os modelos baixados e as prévias |

## Novo canal

Copie um perfil com outro nome e mude voz, estilo, material real, personagem e diretrizes. Para um canal só com IA, apague o bloco `midia_real`. Para um canal sem personagem, apague o bloco `personagem`. Estilo, descrição da personagem e buscas ficam em inglês porque os acervos e os modelos de imagem entendem melhor.
