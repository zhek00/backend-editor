# Fábrica de vídeos

Roteiro pronto entra, vídeo narrado sai, misturando fotos e vídeos reais com imagens de IA.

## Como funciona

1. A GenAIPro gera a narração com as vozes da ElevenLabs, e a fábrica tira o tempo de cada palavra falada da legenda que ela devolve.
2. O Claude divide a narração em cenas. Para cada cena ele decide se vai foto real, vídeo real ou imagem de IA, escreve os termos de busca e a descrição da imagem.
3. Nas cenas reais o sistema busca candidatos no Wikimedia Commons, no Pexels e no Pixabay. O Claude olha as miniaturas e escolhe a que combina com a narração. Se nenhuma servir, a cena vira imagem de IA.
4. O Google gera as imagens de IA com o Nano Banana 2. Nas cenas com a personagem ele usa a foto de referência para manter o mesmo rosto.
5. O FFmpeg monta tudo. Fotos e imagens ganham movimento lento, fotos em pé ganham moldura com fundo desfocado, vídeos são cortados no tempo da cena. No fim entram narração, música e legenda.

Cada etapa salva o que fez. Se algo falhar no meio, o mesmo comando continua de onde parou sem pagar de novo.

## Preparação, uma vez só

1. Crie uma chave de API em cada serviço.
   - GenAIPro em https://genaipro.io, na parte de API. Vai no `.env` como `GENAIPRO_API`. Todos os modelos gastam 1 crédito por caractere.
   - ElevenLabs em https://elevenlabs.io, opcional, só para efeitos sonoros, música e voz por descrição.
   - Google em https://aistudio.google.com/apikey, com faturamento ativado no projeto, porque o modelo de imagem não tem plano grátis
   - Pexels em https://www.pexels.com/api, grátis
   - Pixabay em https://pixabay.com/api/docs, grátis
2. Copie `.env.exemplo` para `.env` e cole as chaves. O Wikimedia Commons não precisa de chave, mas exige um contato em `midia.contato` no `config.yaml`.
3. Conecte o Claude Code à sua assinatura. Abra o app Terminal, digite `claude`, aperte Enter e dentro dele digite `/login`. O Claude da fábrica roda por aí, sem créditos de API. O consumo aparece em `uv run fabrica custo NOME`.
4. Escolha a voz com `uv run fabrica vozes "nome da voz"` e cole o código em `voz.voice_id` no perfil.

## Teste sem custo

Usa a voz do Mac e imagens de teste no lugar das de IA. As fotos reais do Wikimedia são buscadas de verdade, porque são grátis.

```bash
uv run fabrica novo teste --roteiro exemplos/roteiro-enoque.txt --perfil perfis/livro-de-enoque.yaml --offline
uv run fabrica tudo teste
open projetos/teste/final.mp4
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

## Textos na tela

Com `textos_na_tela.ativo: true` no perfil, o Claude escolhe cenas para ganhar um texto animado. Existem quatro tipos.

| Tipo | Como aparece |
|---|---|
| `destaque` | frase grande de impacto, com uma ou duas palavras numa caixa colorida |
| `lista` | cartão com título e itens que surgem no momento em que são narrados |
| `capitulo` | referência grande no canto, como CAP 104 |
| `rotulo` | etiqueta pequena com o nome do livro ou fonte citada |

Cores, fontes e quando usar cada tipo ficam no bloco `textos_na_tela` do perfil.

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

Com `imagens.lote: true` no `config.yaml`, as imagens de IA vão de uma vez para o modo lote do Google, pela metade do preço. O Google promete o resultado em até 24 horas e costuma entregar em minutos. Se o programa parar no meio da espera, rodar o mesmo comando continua esperando o mesmo lote. Com menos de `minimo_lote` imagens, como no `refazer`, a geração é na hora. `--direto` força a geração na hora.

## Prática guiada, só áudio

Para uma meditação guiada, em que a voz fala pouco e o silêncio é longo, o roteiro é texto comum com a marcação `[SILENCIO 90]` numa linha própria. O tempo vai em segundos ou em minutos e segundos, como `[SILENCIO 1:30]`. A GenAIPro grava só as falas, uma por vez, e o silêncio vem do FFmpeg, sem custo. A música do perfil entra baixa por baixo de tudo.

```bash
uv run fabrica meditacao pratica --roteiro roteiros/pratica.txt --perfil perfis/meditacao.yaml
```

O resultado fica em `projetos/pratica/meditacao.mp3`. Com `--imagem capa.png` sai também um `meditacao.mp4` com a imagem parada, para plataforma que só aceita vídeo. Cada fala gravada fica guardada, então mudar uma frase e rodar de novo só regrava aquela fala. Para testar sem custo, acrescente `--offline` na primeira vez.

A trilha ambiente pode ser gerada na ElevenLabs Music (opcional, precisa de `ELEVENLABS_API_KEY`), que libera uso comercial nos planos pagos. Cada geração rende até 5 minutos, e a fábrica emenda a faixa com transição suave até cobrir o áudio inteiro.

```bash
uv run fabrica musica-gerar "Slow ambient meditation pad, soft warm drones, no melody, no percussion, very calm" --minutos 5 --nome ambiente-1
```

## Voz da biblioteca da GenAIPro

Procure pelo nome, ouça as amostras e copie o código da escolhida para `voz.voice_id` no perfil. Não precisa adicionar a voz a nenhuma conta. O editor mostra a mesma biblioteca, com botão para ouvir cada voz.

```bash
uv run fabrica vozes "narrador" --idioma pt
uv run fabrica creditos
```

O segundo comando mostra o saldo da GenAIPro e quando os créditos vencem, sem gastar nada.

## Criar uma voz original

Opcional, pela ElevenLabs direta (precisa de `ELEVENLABS_API_KEY`). A GenAIPro só narra com vozes da biblioteca pública, então a voz criada aqui só serve na fábrica depois de compartilhada na Voice Library da ElevenLabs.

O Voice Design da ElevenLabs cria uma voz nova a partir de uma descrição. Cada rodada gera 3 prévias lendo um texto de teste, e todas aparecem numa página para ouvir.

```bash
uv run fabrica voz-desenhar "Elderly Brazilian man with a deep, gravelly voice and theatrical diction" --rotulo "grave e rouca"
uv run fabrica voz-salvar 2 --nome "Narrador do canal"
```

O segundo comando guarda a prévia escolhida na sua conta e mostra o código que vai em `voz.voice_id`. As prévias expiram depois de algum tempo, então salve logo a que gostar.

## Comandos

| Comando | O que faz |
|---|---|
| `novo` | cria um projeto com roteiro e perfil |
| `tudo` | narração, cenas, material real, imagens e render em sequência |
| `narrar`, `cenas`, `midia`, `imagens`, `efeitos`, `render` | cada etapa separada, e `--forcar` refaz do zero |
| `refazer` | troca o que aparece em cenas específicas |
| `avatar-partes` | corta a narração nos áudios que vão para o HeyGen |
| `revisar` | abre a página com todas as cenas |
| `custo` | mostra a estimativa de gasto |
| `status` | mostra o que já está pronto |
| `personagem` | gera rostos candidatos para a personagem |

## Onde fica cada coisa

| Caminho | Conteúdo |
|---|---|
| `perfis/` | um arquivo por canal, com voz, estilo, proporção de material real, personagem e ritmo |
| `config.yaml` | preços para a estimativa, modelo do Claude e qualidade do render |
| `projetos/NOME/final.mp4` | vídeo pronto |
| `projetos/NOME/creditos.txt` | créditos das fotos e vídeos reais, para a descrição do vídeo |
| `projetos/NOME/legendas_final.srt` | legenda para subir junto no YouTube, já com a abertura e as falas dos clipes fixos |
| `efeitos/` | biblioteca de efeitos sonoros do canal, reaproveitados entre vídeos |
| `projetos/NOME/revisao.html` | página de revisão das cenas |
| `musicas/` | músicas livres de direitos, apontadas no campo `musica` do perfil |

## Novo canal

Copie um perfil com outro nome e mude voz, estilo, material real, personagem e diretrizes. Para um canal só com IA, apague o bloco `midia_real`. Para um canal sem personagem, apague o bloco `personagem`. Estilo, descrição da personagem e buscas ficam em inglês porque os acervos e os modelos de imagem entendem melhor.
