# Instruções para o Claude

Este projeto é uma fábrica de vídeos. O usuário entrega um roteiro em texto e a fábrica devolve um MP4 narrado, com fotos e vídeos reais misturados com imagens de IA, textos animados e legenda queimada.

Quem chegou aqui provavelmente recebeu esta pasta de um amigo e nunca usou o sistema. Trate a pessoa como alguém que não programa. Fale em português simples, sem jargão.

## Primeira conversa, nesta ordem

Faça um passo de cada vez e confirme antes de seguir.

1. **Instalação.** Confira se `uv` e `ffmpeg` existem com `uv --version` e `ffmpeg -version`. Se faltar, instale com `brew install uv ffmpeg`. Depois rode `uv sync` na pasta do projeto.
2. **Chaves.** Confira se existe um `.env`. Se não existir, crie a partir do `.env.exemplo` e peça para a pessoa colar as chaves **no arquivo, nunca no chat**. As obrigatórias são `GENAIPRO_API`, `GEMINI_API_KEY`, `PEXELS_API_KEY` e `PIXABAY_API_KEY`. Teste cada uma com uma chamada barata antes de seguir (a da GenAIPro se testa de graça com `uv run fabrica creditos`). A `ELEVENLABS_API_KEY` é opcional: só serve para efeitos sonoros, música e voz por descrição.
3. **Contato do Wikimedia.** Troque `SEU_EMAIL_AQUI` no `config.yaml` pelo e-mail da pessoa. Sem isso o Wikimedia recusa as buscas.
4. **Claude da fábrica.** A divisão em cenas roda pela assinatura do Claude Code, com `claude -p`. Confirme que o terminal está logado. Se não estiver, peça para rodar `claude` e digitar `/login`.
5. **Teste sem custo.** Rode o exemplo em modo offline, que usa a voz do Mac e imagens de teste. Só depois disso fale em gastar dinheiro.
6. **Voz.** Ajude a escolher uma voz da biblioteca da GenAIPro com `fabrica vozes TERMO --idioma pt` (ou no editor, que toca a prévia). Qualquer voz da lista serve direto: cole o código em `voz.voice_id` no perfil. As vozes padrão da ElevenLabs (George, Rachel...) são recusadas pela GenAIPro.
7. **Perfil do canal.** Copie um perfil de `perfis/` com outro nome e ajuste voz, estilo das imagens, proporção de material real e diretrizes. Explique que o perfil é a identidade do canal.

## Regras que valem sempre

- **Nunca peça nem escreva chaves de API no chat.** Elas ficam só no `.env`.
- **Nunca gaste sem avisar.** Toda etapa paga mostra a estimativa e pede confirmação. Não use `--sim` sem a pessoa ter concordado com o valor.
- Use os comandos que já existem. Não escreva scripts paralelos para fazer o que o `fabrica` já faz.
- Cada etapa salva o resultado. Se algo falhar no meio, rodar o mesmo comando continua de onde parou, sem pagar de novo.
- O modo `--offline` existe para testar qualquer mudança sem custo. Use antes de propor gasto.

## Comandos

```bash
uv run fabrica novo NOME --roteiro caminho.txt --perfil perfis/canal.yaml   # cria o projeto
uv run fabrica tudo NOME          # narração, cenas, material real, imagens e render
uv run fabrica mapa NOME          # o agente de roteiro lê o roteiro inteiro (roteiro_mapa.json)
uv run fabrica narrar NOME        # só a narração
uv run fabrica cenas NOME         # o Claude divide em cenas
uv run fabrica midia NOME         # busca fotos e vídeos reais
uv run fabrica imagens NOME       # gera as imagens de IA que faltam
uv run fabrica render NOME        # monta o vídeo
uv run fabrica revisar NOME       # abre a página com todas as cenas
uv run fabrica refazer NOME 12 31 # troca o que aparece nessas cenas
uv run fabrica custo NOME         # estimativa e consumo do Claude
uv run fabrica status NOME        # o que já está pronto
uv run fabrica estimar roteiro.txt --perfil perfis/canal.yaml   # duração, sem gastar
```

Há também `personagem`, `vozes`, `creditos` (saldo da GenAIPro, grátis), `voz-desenhar` e `voz-salvar` (ElevenLabs direta, opcionais), `avatar-partes`, `avatar` e `meditacao`. Rode `uv run fabrica --help` para a lista completa.

## Regras fixas do corte de cenas (valem para qualquer perfil e roteiro)

O roteiro manda: o que a narração cita tem que aparecer, na hora em que é falado. Estas regras estão no código (`fabrica/cenas.py`), não nos perfis, e não devem ser desligadas.

- Cenas de 3 a 5 segundos, alvo de 4. O corte respeita o tempo de cada palavra falada.
- Frases curtas que se repetem no final ("X está nessa lista. Y está nessa lista.") viram uma cena por frase (`_frases_paralelas`).
- Listas com vírgulas ou "e" viram uma cena por item (`_itens_enumerados`).
- Cena que cita duas ou mais coisas visuais diferentes: o Groq (ou o MiMo de reserva) devolve `citacoes`, e o código corta a cena onde cada uma é falada, com a busca e o prompt da própria coisa.
- Cenas de citação e de enumeração têm mínimo de 1 segundo em vez de 3. **Item curto nunca engole o seguinte** ("alces" dura 0,6 s antes de "cavalos-de-przewalski"): o corte do próximo item é empurrado só o necessário (`_dividir_enumeracoes`), e na fase de cenas curtas o item empresta tempo da vizinha em vez de se fundir a ela. Cada citação do agente traz a própria `descricao`, `exato` e `animal`, e a fatia leva `item_citado`: o Jev julga se a imagem mostra AQUELE item, não os outros da frase.
- Do material real, pelo menos 70% é foto, mas o começo é de vídeo: 80% dos 3 primeiros minutos e 40% até os 7 (`_balancear_foto_e_video`). Os 30% de vídeo permitidos no total são gastos primeiro no começo, com prioridade para os 3 primeiros minutos.
- **Precisão literal (direção de arte).** O agente (`roteirista.PROMPT_CENAS`, "Diretor de Arte Sênior") e o Jev (`corrigir.PERGUNTAS_JEV`) seguem as mesmas 6 regras: sujeito exato sem substituições, cenário fiel, nada de B-roll desconexo ou metáfora, ação e característica exatas, placas e telas do contexto certo, nada de reaproveitar entre blocos sem relação. Só o que existe apenas como tipo genérico (o gráfico de um estudo, uma pessoa anônima) aceita uma representação direta do mesmo tipo. **Animal tem ainda a regra de código abaixo**: se a fala cita o pangolim, aparece um pangolim — nunca um gato, um tatu, outro lêmure ou "um animal parecido". Vale para o agente (busca pelo nome da espécie, nome científico na alternativa), para o Jev (`corrigir.PERGUNTAS_JEV`) e para o código: em cena de animal (`midia.animal_da_cena`) só entra candidato cujas tags citam a espécie ou o tipo do bicho ("snake" para uma cobra, porque os bancos descrevem assim; a espécie exata quem confere é o julgamento), a Wikimedia vem primeiro e o tapa-buraco nunca põe outro bicho. **Nunca encher cenas repetindo a mesma foto do animal**: isso já foi feito e ficou pior (cenas 4 a 7 com a mesma cobra).
- **Onze bancos de imagem** (`midia.Buscador._das_fontes`, `fontes_foto` do perfil base), consultados ao mesmo tempo e com os resultados intercalados (antes a lista era cortada na ordem dos bancos). Wikimedia, Pexels, Pixabay e Unsplash entram em toda busca de foto. O iNaturalist entra primeiro em cena de animal e a NASA só em cena de espaço. **Os bancos de acervo (Harvard, Europeana, Smithsonian, NYPL e Te Papa, `bancos.ACERVO`) só entram em cena de acervo** (`midia._e_de_acervo`): o agente mandou buscar na Wikimedia, ou a cena fala de história, arte, artefato ou ano antes de 1950; em cena de animal, só com fóssil, esqueleto, espécime ou espécie extinta. Antes eles entravam em tudo e só tomavam vaga: no lince2 o Harvard trouxe 4.303 candidatos, quase todos quadros, e 1 entrou no vídeo. O Biodiversity Heritage Library ficou de fora porque devolve livros, não imagens. O Unsplash da chave atual é do plano de demonstração (50 buscas por hora) e acaba cedo; a fábrica segue com os outros. Vídeo continua só no Pexels e no Pixabay. 12 candidatos por cena (`midia.candidatos`).
- **A busca digitada pela pessoa manda** (botão "Pesquisar novo material de acervo" e `fabrica refazer --busca`, em `imagens._a_busca_da_pessoa_manda`): o termo vira o assunto da cena (`busca`, `sujeito` e `mostrar`), o `exato` sai, e o pedido do agente fica guardado em `pedido_original`. Termo em português é traduzido pelo modelo principal (`midia.busca_em_ingles`) e as duas versões são buscadas. Antes só a busca mudava: na cena 15 do ouro-da-serra-gaucha a pessoa pediu "frosted plant", o sujeito antigo "campos com geada" pôs Campo Mourão e Campos dos Goytacazes na frente das fotos de geada, e o pedido "campos de uva da Serra Gaúcha" fez a planta ser recusada.
- **O assunto que ordena, filtra e busca é sempre em inglês** (`midia.sujeito_da_busca`): os bancos descrevem as fotos em inglês, e o agente escreve o `sujeito` em português em boa parte das cenas (62 de 217 no ouro-da-serra-gaucha). Sujeito com cara de português cede lugar à `busca`. Antes, na cena 106, "fogo de chão" marcou as 6 fotos de fogueira como fora do assunto e, buscado na Wikimedia, "fogo" trouxe a ilha vulcânica do Fogo (Cabo Verde), que ficou no vídeo.
- Captura de material real: a busca vai do mais exato para o mais amplo (a busca da cena, a `busca_alternativa` do agente e o sujeito em duas palavras). O filtro `_so_do_assunto` tira candidatos cujas tags não citam o assunto, mas se tirar todos, devolve todos para o modelo de visão decidir.
- **O que o Jev lê sobre cada imagem** (`midia.CAMPOS_DO_QUE_SE_VE`, na captura e na conferência): o modelo que vê a imagem responde campo a campo (o que é e com que certeza, detalhes que identificam, cenário, ação, tipo de imagem, texto visível) e **confere com o que a cena pede** (sim, parcial ou não, e por quê). O Jev só lê texto: uma frase solta não dizia se era a espécie certa nem se era foto ou desenho. Descrição antiga, em frase curta, é refeita.
- Conferência na captura (`midia.conferir_na_captura`, ligada por padrão): o modelo que escolhe (MiMo, Groq ou Gemini) escreve uma frase do que vê em cada candidato e o Jev julga antes do download. Abaixo de `nota_minima_captura` (30) o candidato cai e o próximo é testado, até `candidatos_conferidos`. Se nenhum passar, fica o de maior nota e a cena ganha `captura.suspeita`. No passo `conferir`, abaixo de `corrigir.nota_para_trocar` (20) a fábrica troca sozinha, e entre isso e `nota_minima` (40) só aponta.
- **JAMAIS repetir imagem, conferido na imagem em si.** Toda foto baixada ganha uma impressão digital visual (`midia._impressao`, dHash de 64 pontos) e é recusada (`ImagemRepetida`) se for igual ou quase igual a outra do vídeo, mesmo vinda de outro banco ou com outro número; a mesma foto do mesmo banco também é recusada. No fim da conferência e no fim da criação, `midia.tirar_repetidas` varre o vídeo e troca qualquer repetida por imagem nova. A checagem antiga, por nome de arquivo, deixou passar a mesma foto nas cenas 75 e 77 do lince2.
- **Nenhuma cena fica vazia, buraco se completa COM O ASSUNTO, e NUNCA se repete imagem.** Com `ia.ativa: false`, a cena que o acervo não resolveu recebe, nesta ordem (`_preencher_vazias` em `fabrica/midia.py`): um candidato da própria cena cujas tags citam o assunto; uma busca maior por todos os nomes do mesmo assunto (busca, alternativa, animal, sujeito, contexto e âncora do bloco); por último, uma imagem NOVA pelo assunto do bloco e do vídeo. Cena que terminou a conferência mostrando outra coisa (`corrigir._tirar_outra_coisa`) busca imagem nova, com a reprovada em `rejeitadas`. **Nunca copiar a imagem de outra cena**: isso já foi feito e encheu o lince2 de repetição (19 imagens repetidas). O agente não reaproveita cena (`reusar_cena` sempre 0) e fatia de IA não copia a imagem da vizinha. Toda cena preenchida ganha `captura.suspeita` e `captura.preenchida`.
- **Nota mínima única** (`midia.NOTA_MINIMA_FIXA`, 40): a captura nunca aceita menos do que a conferência. Na criação (site e `tudo`) a conferência olha toda cena abaixo de 40 ou suspeita e troca sozinha, no acervo, sem deixar para o botão Corrigir Mídia. O `config.yaml` pode subir a nota, nunca baixar.
- **O agente diz o que a foto obrigatoriamente mostra** (campo `exato` de cada cena: "Pripyat", "Geiger counter", "New Safe Confinement", "Eurasian lynx", ou vazio quando qualquer representação direta serve). Com `exato`, a Wikimedia vem primeiro e só entra foto cujas tags citem o nome (nome composto: todas as palavras, senão "Chernobyl Elephant's Foot" aceitaria um elefante). **O `exato` também é o primeiro termo de busca**, na busca da cena e no tapa-buraco: antes ele era só filtro, e a cena 11 do aparte2-2min-v2 exigia "Instituto Butantan", buscava "antivenom vials corridor" e descartava todos os candidatos (0 de 12 citavam o nome; com o `exato` na busca, 7 de 12). É a correção de raiz: antes cada etapa adivinhava o essencial pela busca, e toda adivinhação tinha furo. Sem o campo (projeto antigo), `midia.exigido_da_cena` deduz o animal ou o nome próprio do roteiro.
- **Busca com o contexto do bloco**: quando a busca fala do assunto do bloco, o `contexto` do mapa vai junto ("sugar glider" vira "sugar glider marsupial animal"). No tapa-buraco, candidato cujas tags não citam o assunto nunca entra às cegas.
- **Texto na tela com fundamento** (`textos.REGRAS_QUALIDADE` e `textos.motivo_para_recusar`): número com o que ele mede, nome com a identificação ou a conclusão do trecho. Nunca metadados ("PARTE 2", "NÚMERO 8" sem o nome), palavra solta ou palavra que não foi falada. Na dúvida, sem texto. `fabrica textos NOME` refaz só os textos.
- **Voz do Edge com o tempo de cada palavra** (`boundary="WordBoundary"`): legenda e cortes seguem a fala. Projeto antigo se corrige com `narracao.realinhar_edge`.
- Cena de IA cortada por citação refaz o prompt de cada fatia, para não gerar a mesma imagem repetida.
- Material real primeiro: IA só quando o acervo não tem o assunto, com teto de 15% das cenas (`ESTILO_TETO_IA`).
- Ao refazer cenas, o `--forcar` apaga o cache dos lotes e guarda `imagens` e `midia` em pastas `_antigas_`.

## Agente de roteiro (principal do passo de cenas)

`fabrica/roteirista.py`, ligado por `roteirista.ativo` no `config.yaml`. Ele não entra em modo offline nem em perfil com personagem ou efeitos, que seguem pelo caminho antigo.

1. **Mapa** (`fabrica mapa NOME`, e sozinho no início de `cenas`). Lê o roteiro inteiro e grava `roteiro_mapa.json` com os blocos de assunto (cada um com a âncora visual e a posição no roteiro), as armadilhas de busca, as pessoas reais, o que é proibido e as imagens recorrentes. Só depende do texto, então roda antes da narração. Quem responde é o MiMo, com Groq e Gemini de reserva. Na criação pelo editor, o mapa aparece na janela de progresso e fica em `GET /api/projetos/NOME/mapa`.
2. **JSON de cenas** (`roteiro_cenas.json`, também no `fabrica mapa`). Feito só com o texto, antes ou junto da narração: o corte (`_pre_cortar`) usa o tempo previsto de cada frase pelo `ritmo.caracteres_por_minuto` do perfil, e para cada bloco, em lotes de `roteirista.cenas_por_lote` e com `roteirista.paralelo` blocos ao mesmo tempo, o agente decide tipo, descrição, busca, prompt, texto na tela e reaproveitamento. O que ele deixar sem resposta cai no Groq antigo. No `tudo` e no editor ele roda em paralelo com a narração.
3. **Passo de cenas = encaixe.** Os números das frases saem só do texto, então o JSON se encaixa nas frases da narração sem nenhum modelo: o passo de cenas aplica as regras fixas de tempo e só confere os textos na tela por código. Se a narração tiver outro número de frases (roteiro mudou), o agente decide sobre os cortes reais.

O que o agente decide segue adiante: `mostrar` (a descrição) vai para a escolha do acervo, para o Jev e para a busca nova das reprovadas; `overlay` vira sugestão no passo dos textos na tela; as armadilhas corrigem por código a busca que for só o nome ambíguo. Tipos de animação (`texto_tela`, `linha_do_tempo`, `mapa`, `diagrama`) ficam guardados em `visual` e, por enquanto, viram a imagem de baixo, porque a fábrica ainda não desenha animações. As regras fixas acima continuam valendo depois dele.

## Como o sistema funciona por dentro

Cada projeto vive em `projetos/NOME`. As etapas são estas.

1. **Narração.** A GenAIPro (`fabrica/genaipro.py`) grava cada bloco como uma tarefa, 4 blocos ao mesmo tempo. O tempo de cada palavra vem da legenda que ela gera com um caractere por linha (uma palavra por bloco da legenda), e o fim de cada palavra é encostado no silêncio real do áudio (`narracao._encostar_nas_pausas`), porque na legenda a pausa depois do ponto fica dentro da palavra anterior. Isso sustenta a legenda e os textos animados. A tarefa criada fica anotada em `bloco_NNN.mp3.tarefa.json` antes da espera: se a fábrica cair, rodar de novo retoma a mesma tarefa sem pagar outra vez. O áudio bruto de cada bloco fica guardado, então mudar ritmo ou pausa não custa nada.
2. **Cenas.** O Claude recebe as frases com a duração e devolve grupos, dizendo se cada cena é foto real, vídeo real ou imagem de IA, com os termos de busca e o prompt.
3. **Material real.** Busca no Wikimedia, no Pexels e no Pixabay, o Claude escolhe pelas miniaturas e o sistema grava `creditos.txt`, que vai na descrição do vídeo.
4. **Imagens.** O Google gera as que faltam, por padrão no modo lote, que custa metade e pode demorar horas.
5. **Render.** O FFmpeg monta tudo com movimento lento nas fotos, textos animados, música e legenda.

Arquivos importantes de um projeto: `alinhamento.json` com o tempo de cada frase, `cenas.json` com o plano de cena, `revisao.html` para revisar e `final.mp4`.

## Marcações que o roteiro aceita

- `[SIMBOLO]` mostra na tela o símbolo definido no perfil, sem narrar nada.
- `[TITULO] Nome da parte` mostra um cartão com o título, sem narrar.
- `[AVATAR] ... [/AVATAR]` marca o trecho em que o personagem aparece falando.
- `[INSERTO nome]` encaixa um clipe fixo do personagem.

As duas últimas dependem de vídeos gerados no HeyGen, que não vieram no pacote.

## Erros comuns

| Sintoma | Causa e solução |
|---|---|
| Wikimedia devolve 403 | falta o e-mail em `midia.contato` no `config.yaml` |
| Google recusa com 429 e fala em cota | falta ativar o faturamento no Google AI Studio, ou o crédito acabou |
| GenAIPro recusa a chave (401 ou 403) | chave errada em `GENAIPRO_API` no `.env`. Confira com `uv run fabrica creditos` |
| GenAIPro diz `invalid_voice_id` | a voz não está na biblioteca pública. Escolha outra com `uv run fabrica vozes TERMO` |
| GenAIPro diz que a velocidade é inválida | `voz.velocidade` só vai de 0,7 a 1,2 (a fábrica já limita) |
| Claude Code diz que não está logado | rodar `claude` no terminal e digitar `/login` |
| Lote do Google demora demais | é normal, pode levar horas. O mesmo comando retoma o lote sem pagar de novo |
| Pexels ou Pixabay atingem o limite | a fábrica espera sozinha e continua |

## Quem responde cada etapa

**Um modelo só para tudo que não é o juiz:** `openrouter.modelo_principal` no `config.yaml`, hoje o
`stealth/space-bunny-alpha` (OpenRouter; lê até 1 milhão de tokens, enxerga texto, imagem e vídeo, e hoje é
gratuito). **MiMo, Groq e Gemini não são mais usados** em nenhuma etapa. O Jev continua sendo o juiz.

| Etapa | Quem responde |
|---|---|
| Agente de roteiro (mapa, cenas, contexto dos blocos) | modelo principal |
| Textos na tela, buscas das reprovadas | modelo principal |
| Escolha das fotos e vídeos do acervo (olha as miniaturas) | modelo principal |
| Descrição das imagens para a conferência | modelo principal |
| Julgamento (a imagem combina com a fala?) | Jev, pelo OpenRouter; se ele cair, o modelo principal julga |

Cuidados com esse modelo, que já custaram erro:
- Ele **ignora o `response_format`** e inventa os nomes das chaves. Por isso `openrouter_local.perguntar` põe o
  esquema também no texto e **confere se as chaves obrigatórias vieram**, pedindo de novo quando não vêm.
- Ele **pensa antes de responder**: sem `raciocinio_por_modelo: stealth/: low`, gastava todo o limite pensando e
  não entregava a resposta.
- É um modelo "stealth": gratuito e em teste, pode ter limite de uso, ficar fora do ar ou sumir do OpenRouter.
  Para trocar, basta mudar `openrouter.modelo_principal` no `config.yaml`.

## Custo real, medido

Cada etapa paga grava o que foi cobrado em `projetos/NOME/custos_reais.json` na hora em que
cobra (`fabrica/custos_reais.py`). Bloco de narração ou imagem reaproveitados do cache não
entram, porque não geraram cobrança nova. Os modelos de texto gravam os próprios
`uso_groq.json`, `uso_openrouter.json`, `uso_jev.json` e `uso_gemini.json`, e o resumo junta tudo.

- `uv run fabrica custo NOME` mostra a estimativa e, embaixo, o gasto real por categoria, por
  minuto de vídeo e por cena.
- O botão **Custos** do editor mostra o mesmo.
- O preço do caractere de narração sai da seção `assinaturas` do `config.yaml`: preço do plano
  dividido pela franquia do mês. Sem assinatura, vale a tarifa avulsa de `precos`.
- O Groq é do plano gratuito e conta zero. OpenRouter e Jev informam o custo real de cada
  chamada. O Gemini é calculado pelos preços por milhão de tokens do `config.yaml`.

## Custo real, para calibrar

Um vídeo de 36 minutos com 250 cenas, 60% de material real e 94 imagens saiu por uns US$ 5,60, algo como US$ 0,16 por minuto. A narração foi US$ 1,91 na ElevenLabs; na GenAIPro (US$ 22 por 1 milhão de caracteres, `assinaturas.genaipro` no `config.yaml`) a mesma narração sai por volta de US$ 0,70, uns US$ 0,02 por minuto. O resto foi imagem. O Claude pela assinatura não custa nada além da mensalidade.

Sempre informe o custo total **e o custo por minuto** quando falar de dinheiro.
