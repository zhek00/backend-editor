# Instruções para o Claude

Este projeto é uma fábrica de vídeos. O usuário entrega um roteiro em texto e a fábrica devolve um MP4 narrado, com fotos e vídeos reais misturados com imagens de IA, animações (HyperFrames) e legenda queimada.

Quem chegou aqui provavelmente recebeu esta pasta de um amigo e nunca usou o sistema. Trate a pessoa como alguém que não programa. Fale em português simples, sem jargão.

## Primeira conversa, nesta ordem

Faça um passo de cada vez e confirme antes de seguir.

1. **Instalação.** Confira se `uv` e `ffmpeg` existem com `uv --version` e `ffmpeg -version`. Se faltar, instale com `brew install uv ffmpeg`. Depois rode `uv sync` na pasta do projeto. Para as animações (diagramas, textos na tela, linhas do tempo e mapas), confira também o Node.js 22 ou mais com `node --version` (`brew install node`). Ele é opcional: sem ele essas cenas ficam com foto.
2. **Chaves.** Confira se existe um `.env`. Se não existir, crie a partir do `.env.exemplo` e peça para a pessoa colar as chaves **no arquivo, nunca no chat**. As obrigatórias são `GENAIPRO_API`, `GEMINI_API_KEY`, `PEXELS_API_KEY` e `PIXABAY_API_KEY`. Teste cada uma com uma chamada barata antes de seguir (a da GenAIPro se testa de graça com `uv run fabrica creditos`). A `ELEVENLABS_API_KEY` é opcional: só serve para efeitos sonoros, música e voz por descrição.
3. **Contato do Wikimedia.** Troque `SEU_EMAIL_AQUI` no `config.yaml` pelo e-mail da pessoa. Sem isso o Wikimedia recusa as buscas.
4. **Claude da fábrica.** A divisão em cenas roda pela assinatura do Claude Code, com `claude -p`. Confirme que o terminal está logado. Se não estiver, peça para rodar `claude` e digitar `/login`.
5. **Teste sem custo.** Rode o exemplo em modo offline, que usa a voz do computador (a do Mac; no Windows, a do sistema ou, sem ela, um tom baixo no lugar da fala) e imagens de teste. Só depois disso fale em gastar dinheiro.
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
uv run fabrica animacoes NOME     # anima diagramas, frases de destaque, linhas do tempo e mapas (grátis)
uv run fabrica motion NOME        # o Jev diz onde um clipe de motion explica a fala melhor (--aplicar faz os clipes)
uv run fabrica trilha NOME        # o modelo compõe a trilha e o código toca (grátis)
uv run fabrica render NOME        # monta o vídeo
uv run fabrica render NOME --vertical   # versão em pé (9:16) para Reels e Shorts, em final_vertical.mp4
uv run fabrica revisar-video NOME # o modelo olha o vídeo pronto e aponta problemas (grátis)
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
- Cenas de citação e de enumeração têm mínimo de 1 segundo em vez de 3. **Item curto nunca engole o seguinte** ("alces" dura 0,6 s antes de "cavalos-de-przewalski"): o corte do próximo item é empurrado só o necessário (`_dividir_enumeracoes`), e na fase de cenas curtas o item empresta tempo da vizinha em vez de se fundir a ela. Cada citação do agente traz a própria `descricao`, `exato` e `animal`, e a fatia leva `item_citado`: o Jev julga se a imagem mostra AQUELE item, não os outros da frase. **Item citado no fim da cena adianta o corte** (tirando tempo do item anterior, os dois com o mínimo), em vez de ser jogado fora: "outras pela velocidade" é dita a 0,92 s do fim da frase, e o guepardo que o agente pediu sumia. **Cena comum curta nunca funde nem divide tempo com a fatia de um item citado** (`livre` em `_garantir_limites_estritos`): a frase do mosquito (2,6 s) era fundida com a fatia do guepardo, e ele sumia de novo; ela busca o tempo do outro lado.
- Do material real, pelo menos 70% é foto, mas o começo é de vídeo: 80% dos 3 primeiros minutos e 40% até os 7 (`_balancear_foto_e_video`). Os 30% de vídeo permitidos no total são gastos primeiro no começo, com prioridade para os 3 primeiros minutos.
- **Precisão literal (direção de arte).** O agente (`roteirista.PROMPT_CENAS`, "Diretor de Arte Sênior") e o Jev (`corrigir.PERGUNTAS_JEV`) seguem as mesmas 6 regras: sujeito exato sem substituições, cenário fiel, nada de B-roll desconexo ou metáfora, ação e característica exatas, placas e telas do contexto certo, nada de reaproveitar entre blocos sem relação. Só o que existe apenas como tipo genérico (o gráfico de um estudo, uma pessoa anônima) aceita uma representação direta do mesmo tipo. **Animal tem ainda a regra de código abaixo**: se a fala cita o pangolim, aparece um pangolim — nunca um gato, um tatu, outro lêmure ou "um animal parecido". Vale para o agente (busca pelo nome da espécie, nome científico na alternativa), para o Jev (`corrigir.PERGUNTAS_JEV`) e para o código: em cena de animal (`midia.animal_da_cena`) só entra candidato cujas tags citam a espécie ou o tipo do bicho ("snake" para uma cobra, porque os bancos descrevem assim; a espécie exata quem confere é o julgamento), a Wikimedia vem primeiro e o tapa-buraco nunca põe outro bicho. **Nunca encher cenas repetindo a mesma foto do animal**: isso já foi feito e ficou pior (cenas 4 a 7 com a mesma cobra).
- **Onze bancos de imagem** (`midia.Buscador._das_fontes`, `fontes_foto` do perfil base), consultados ao mesmo tempo e com os resultados intercalados (antes a lista era cortada na ordem dos bancos). Wikimedia, Pexels, Pixabay e Unsplash entram em toda busca de foto. O iNaturalist entra primeiro em cena de animal e a NASA só em cena de espaço. **Os bancos de acervo (Harvard, Europeana, Smithsonian, NYPL e Te Papa, `bancos.ACERVO`) só entram em cena de acervo** (`midia._e_de_acervo`): o agente mandou buscar na Wikimedia, ou a cena fala de história, arte, artefato ou ano antes de 1950; em cena de animal, só com fóssil, esqueleto, espécime ou espécie extinta. Antes eles entravam em tudo e só tomavam vaga: no lince2 o Harvard trouxe 4.303 candidatos, quase todos quadros, e 1 entrou no vídeo. O Biodiversity Heritage Library ficou de fora porque devolve livros, não imagens. O Unsplash da chave atual é do plano de demonstração (50 buscas por hora) e acaba cedo; a fábrica segue com os outros. Vídeo continua só no Pexels e no Pixabay. 12 candidatos por cena (`midia.candidatos`).
- **A busca digitada pela pessoa manda** (botão "Pesquisar novo material de acervo" e `fabrica refazer --busca`, em `imagens._a_busca_da_pessoa_manda`): o termo vira o assunto da cena (`busca`, `sujeito` e `mostrar`), o `exato` e o `animal` saem, e o pedido do agente fica guardado em `pedido_original`. Sem tirar o `animal`, o filtro de espécie continuava com o bicho do agente: a cena marcada "impala" voltava três impalas seguidas para a busca "leão". Termo em português é traduzido pelo modelo principal (`midia.busca_em_ingles`) e as duas versões são buscadas. Antes só a busca mudava: na cena 15 do ouro-da-serra-gaucha a pessoa pediu "frosted plant", o sujeito antigo "campos com geada" pôs Campo Mourão e Campos dos Goytacazes na frente das fotos de geada, e o pedido "campos de uva da Serra Gaúcha" fez a planta ser recusada.
- **O assunto que ordena, filtra e busca é sempre em inglês** (`midia.sujeito_da_busca`): os bancos descrevem as fotos em inglês, e o agente escreve o `sujeito` em português em boa parte das cenas (62 de 217 no ouro-da-serra-gaucha). Sujeito com cara de português cede lugar à `busca`. Antes, na cena 106, "fogo de chão" marcou as 6 fotos de fogueira como fora do assunto e, buscado na Wikimedia, "fogo" trouxe a ilha vulcânica do Fogo (Cabo Verde), que ficou no vídeo.
- **Na escolha do acervo, o sujeito é obrigatório e a ação e o cenário só ordenam** (`midia.INSTRUCOES_ESCOLHA`, `VERSAO_ESCOLHA` na assinatura do cache da escolha). No natureza-nos-ensina o modelo que escolhe recusou 11 fotos boas de crocodilo-do-nilo porque nenhuma era "só olhos e narinas na água", e 22 cenas foram para a IA sem ninguém julgar: 48 imagens de IA em 92 cenas de um vídeo de animais da África. Quando ele recusa todos, os candidatos que citam o assunto nas tags entram mesmo assim (`midia._do_assunto_quando_recusou`), como suspeitos, e a conferência do Jev julga. Na captura, o Jev segue a regra da conferência: sujeito certo (60 ou mais) com nota baixa é cena genérica e fica (`_escolher_conferindo`); antes as leoas andando, para "caçam em grupo, cercando a presa", iam para a IA.
- **Cena de vídeo de animal procura foto quando nenhum vídeo é da espécie** (`midia.Buscador.candidatos`): vale a própria espécie (`_cabeca_do_animal`, "mamba"), não o tipo do bicho. "snake" nas tags de vídeos de píton e de cobra-do-milho passava por mamba-negra, a foto nunca era procurada e as 6 cenas da mamba do natureza-nos-ensina foram para a IA. A foto vem do iNaturalist em cena de animal (antes só da Wikimedia), e quem cita a espécie vai na frente de quem cita só o tipo do bicho no corte dos 12 candidatos.
- **Segunda leva de candidatos** (`midia._segunda_leva`): a mesma busca traz 24 candidatos por cena (o dobro de `midia.candidatos`, sem pedido a mais aos bancos); o modelo vê os 12 primeiros e, se ele ou o Jev recusarem todos, vê os 12 seguintes. Só depois valem as tags (`_do_assunto_quando_recusou`, sobre os 24) e, por último, a IA. A imagem de candidatos e a escolha da segunda leva ficam em `midia/escolha/cena_NNNN_2.*`. Antes os outros 28 a 37 resultados de cada banco eram jogados fora sem ninguém olhar.
- Captura de material real: a busca vai do mais exato para o mais amplo (a busca da cena, a `busca_alternativa` do agente e o sujeito em duas palavras). O filtro `_so_do_assunto` tira candidatos cujas tags não citam o assunto, mas se tirar todos, devolve todos para o modelo de visão decidir.
- **O que o Jev lê sobre cada imagem** (`midia.CAMPOS_DO_QUE_SE_VE`, na captura e na conferência): o modelo que vê a imagem responde campo a campo (o que é e com que certeza, detalhes que identificam, cenário, ação, tipo de imagem, texto visível) e **confere com o que a cena pede** (sim, parcial ou não, e por quê). O Jev só lê texto: uma frase solta não dizia se era a espécie certa nem se era foto ou desenho. Descrição antiga, em frase curta, é refeita.
- Conferência na captura (`midia.conferir_na_captura`, ligada por padrão): o modelo que escolhe (o modelo principal) escreve uma frase do que vê em cada candidato e o Jev julga antes do download. Abaixo de `nota_minima_captura` (30) o candidato cai e o próximo é testado, até `candidatos_conferidos`. Se nenhum passar, fica o de maior nota e a cena ganha `captura.suspeita`. No passo `conferir`, abaixo de `corrigir.nota_para_trocar` (20) a fábrica troca sozinha, e entre isso e `nota_minima` (40) só aponta.
- **Foto com pessoa nunca perde o rosto** (`fabrica/rostos.py`). O OpenCV acha os rostos com o YuNet (modelo de 230 KB, licença MIT, em `recursos/rostos`; no próprio computador, grátis), guardados em `.rostos.json` na pasta da foto. Foto que preenche a tela era recortada pelo meio: quando isso cortaria um rosto, `render._foto_na_tela` recorta pelos rostos (centro deles a 40% da altura); na versão em pé, o recorte lateral também segue o rosto. A prévia do editor (`render.quadro_da_foto`) é montada igual ao vídeo, com a moldura do retrato e o recorte pelo rosto: antes ela era a foto esticada pelo meio, e o retrato do jogador da cena 16 do virou-filme-em-1996 aparecia só com o tronco. Só os clipes dessas fotos mudam de nome (`_enquadramento`); os outros não renderizam de novo. O detector clássico (Haar) foi testado e descartado: errou 10 de 12 fotos (folha, abutre, mapa, manuscrito). OpenCV fica na versão 4 (a 5 tirou o detector clássico e o projeto fixa `<5`).
- **JAMAIS repetir imagem, conferido na imagem em si.** Toda foto baixada ganha uma impressão digital visual (`midia._impressao`, dHash de 64 pontos) e é recusada (`ImagemRepetida`) se for igual ou quase igual a outra do vídeo, mesmo vinda de outro banco ou com outro número; a mesma foto do mesmo banco também é recusada. No fim da conferência e no fim da criação, `midia.tirar_repetidas` varre o vídeo e troca qualquer repetida por imagem nova. A checagem antiga, por nome de arquivo, deixou passar a mesma foto nas cenas 75 e 77 do lince2.
- **Nenhuma cena fica vazia, buraco se completa COM O ASSUNTO, e NUNCA se repete imagem.** Com `ia.ativa: false`, a cena que o acervo não resolveu recebe, nesta ordem (`_preencher_vazias` em `fabrica/midia.py`): um candidato da própria cena cujas tags citam o assunto; uma busca maior por todos os nomes do mesmo assunto (busca, alternativa, animal, sujeito, contexto e âncora do bloco); por último, uma imagem NOVA pelo assunto do bloco e do vídeo. Cena que terminou a conferência mostrando outra coisa (`corrigir._tirar_outra_coisa`) busca imagem nova, com a reprovada em `rejeitadas`. **Nunca copiar a imagem de outra cena**: isso já foi feito e encheu o lince2 de repetição (19 imagens repetidas). O agente não reaproveita cena (`reusar_cena` sempre 0) e fatia de IA não copia a imagem da vizinha. Toda cena preenchida ganha `captura.suspeita` e `captura.preenchida`.
- **Tapa-buraco com filtro de verdade** (`midia._preencher_vazias`, regras de 2026-10-03, do virou-filme-em-1996, onde 118 de 130 cenas vieram do tapa-buraco e quase todas mostravam outra coisa):
  - **O bicho é o substantivo, não o lugar** (`_cabeca_do_animal`): em "maneless Tsavo lion" vale "lion". Antes valia a primeira palavra e qualquer uma bastava: zebra, elefante, girafa e galinha "de Tsavo" passaram por leão. Em cena de animal o bicho é obrigatório (`exigido_da_cena`), e o nome do lugar no `exato` não conta.
  - **`exato` com um nome e uma coisa exige os dois** (`_identificador`: "Tsavo railway workers camp" pede Tsavo E camp). `exato` em português é ignorado (as tags são em inglês).
  - **Candidato que o modelo descreveu como "confere: nao" nunca entra** (`_disse_que_nao`): o elefante da cena 3 foi recusado por ele e posto pelo tapa-buraco.
  - **Assunto de três palavras ou mais precisa de duas nas tags** (`_cita_bastante`): uma só aceitou Mustang, latas de spray e a vista de uma cidade.
  - **Cena que não é de animal nunca recebe foto de bicho que ela não cita** (`_mostra_outro_bicho`, lista `_BICHOS`).
  - **O assunto do vídeo nunca é nome de pessoa** (`assunto_do_video` tira as `pessoas_reais` do mapa) **e é conferido pela palavra inteira** (`_cita_o_nome`): "Patterson" pelas 4 primeiras letras trouxe a cidade de Patterson, uma ginasta e uma estação de trem para 20 cenas. O último recurso não usa mais o primeiro resultado às cegas.
  - Sujeito em português sem acento ("tranca quebrada") cede lugar à busca quando não divide nenhuma palavra com os campos em inglês (`sujeito_da_busca`); "quebrada" trouxe o cânion Quebrada de las Conchas.
  - Preferível uma cena vazia para revisão a uma imagem de outra coisa: o render avisa quais faltam.
  - **Com a IA ligada, a repetida que não acha foto nova vai para a imagem de IA** (no fim da criação, `api` depois de `tirar_repetidas`, e em `cli.completar_depois_da_narracao`): antes a criação parava pedindo uma foto (cena 79 do nunca-deve-ter-dentro-de-casa-parte-2, o petauro-do-açúcar, com `ia.ativa: true`).
- **Cena de motion é julgada como fundo** (`corrigir._julgar_com_jev`): a imagem vai escurecida embaixo da camada de animação, então o Jev julga "imagem de fundo do assunto", não "um diagrama mostra...".
- **Quem descreve não tira nome do pedido** (`midia.INSTRUCOES_DO_QUE_SE_VE`): uma cidade no litoral virou "Lago Vitória" com nota 81. O Jev só aceita nome que aparece no texto visível ou no título do arquivo, e recebe `pessoa_citada` (campo `quem_e` do mapa: anos de vida e o que fez) para separar homônimos (o John Henry Patterson de Dayton, Ohio, entrou no lugar do caçador de 1898). O descritor também diz a `epoca_aparente` da imagem.
- **Cenas de época** (vídeos históricos; campo `epoca` de cada cena, um ano antes de 1950, e `epoca` de cada bloco no mapa): o agente pede material de arquivo (foto da época, gravura, ilustração de livro ou jornal, objeto de museu), nunca reconstituição com ação e hora que ninguém fotografou. A cena nunca vira vídeo (`cenas._balancear_foto_e_video`), busca só na Wikimedia e nos bancos de acervo (`midia._e_de_acervo` devolve "epoca", `Buscador._das_fontes`), e o Jev reprova foto atual. Cena sem `epoca` (bicho, paisagem, hoje) segue igual. No Tsavo de 1898, Pexels e Pixabay puseram obras modernas e uma estação de trem atual.
- **O Jev responde três perguntas numa chamada só** (`corrigir._perguntas`): combina (a nota), **sujeito** (a imagem mostra AQUILO e não outra coisa, mesmo que genérica) e, em cena de época, **época**. Recebe também o assunto do bloco do mapa, o `exato` e o **`aceitavel`** (o mínimo para a cena estar certa, escrito pelo agente; o ideal fica no `mostrar`). Sujeito certo com nota baixa é cena genérica e **fica**: três leões sem juba tiravam 4% contra "dois leões entre tendas à noite" e seriam trocados à toa.
- **Quem descreve no Corrigir não vê o pedido** (`corrigir._descrever_lote`, `midia.INSTRUCOES_SEM_PEDIDO`): vendo, ele escrevia o nome que estava nele. Descrição antiga feita com o pedido ("confere com o pedido") é refeita. Com uma cena por chamada, a resposta única é daquela cena, seja qual for o número que o modelo escreveu: o Qwen do Groq devolveu outro número e as imagens de IA ficaram sem descrição, sem a conferência do Jev.
- **O Corrigir nunca termina com imagem sem conferência** (`corrigir._conferir_sem_nota`): a troca por repetida e as buscas do fim são julgadas antes de acabar. No virou-filme sobraram 77 sem ninguém olhar.
- **A imagem de IA é conferida pelo Jev** (`corrigir.conferir_ia`, chamada por `imagens.gerar`): mostrando outra coisa, é feita de novo uma vez com o motivo no pedido. Refazer com o prompt da pessoa (`refazer`) não confere. Em cena de época a imagem sai no estilo de foto antiga (`imagens.prompt_final`).
- **Nota mínima única** (`midia.NOTA_MINIMA_FIXA`, 40): a captura nunca aceita menos do que a conferência. Na criação (site e `tudo`) a conferência olha toda cena abaixo de 40 ou suspeita e troca sozinha, no acervo, sem deixar para o botão Corrigir Mídia. O `config.yaml` pode subir a nota, nunca baixar.
- **O agente diz o que a foto obrigatoriamente mostra** (campo `exato` de cada cena: "Pripyat", "Geiger counter", "New Safe Confinement", "Eurasian lynx", ou vazio quando qualquer representação direta serve). Com `exato`, a Wikimedia vem primeiro e só entra foto cujas tags citem o nome (nome composto: todas as palavras, senão "Chernobyl Elephant's Foot" aceitaria um elefante). **O `exato` também é o primeiro termo de busca**, na busca da cena e no tapa-buraco: antes ele era só filtro, e a cena 11 do aparte2-2min-v2 exigia "Instituto Butantan", buscava "antivenom vials corridor" e descartava todos os candidatos (0 de 12 citavam o nome; com o `exato` na busca, 7 de 12). É a correção de raiz: antes cada etapa adivinhava o essencial pela busca, e toda adivinhação tinha furo. Sem o campo (projeto antigo), `midia.exigido_da_cena` deduz o animal ou o nome próprio do roteiro.
- **Busca com o contexto do bloco**: quando a busca fala do assunto do bloco, o `contexto` do mapa vai junto ("sugar glider" vira "sugar glider marsupial animal"). No tapa-buraco, candidato cujas tags não citam o assunto nunca entra às cegas.
- **Texto curto com fundamento** (`textos.REGRAS_QUALIDADE`, no pedido do agente para o `overlay`, que vira o texto da animação em camada): número com o que ele mede, nome com a identificação ou a conclusão do trecho. Nunca metadados ("PARTE 2", "NÚMERO 8" sem o nome), palavra solta ou palavra que não foi falada. Na dúvida, sem texto.
- **Voz do Edge com o tempo de cada palavra** (`boundary="WordBoundary"`): legenda e cortes seguem a fala. Projeto antigo se corrige com `narracao.realinhar_edge`.
- Cena de IA cortada por citação refaz o prompt de cada fatia, para não gerar a mesma imagem repetida.
- **Cena recortada leva o pedido da frase que ela fala** (`cenas._pedido_pela_fala`, no fim de `atualizar_tempos` **e de `planejar`**, depois de `_garantir_limites_estritos`). Na primeira montagem também: juntar as curtas e dividir as longas copiava o pedido de uma cena para a outra, e no natureza-nos-ensina "e algumas cabem na ponta do seu dedo" (o agente pediu o mosquito) mostrou um elefante; eram 27 pares de cenas seguidas com o mesmo pedido. A busca vai junto (`busca`, ou `busca_reserva` em cena de IA). No recorte de outra narração, o pedaço novo herdava a descrição da cena de onde saiu: as cenas 23 a 26 do virou-filme-em-1996 falavam de quatro frases e ficaram com "um engenheiro chega a pé à obra, visto de costas". Agora a frase de cada cena é a que tem mais palavras dela, e o pedido (`mostrar`, `sujeito`, `exato`, `animal`, `epoca`, `onde_existe`, `aceitavel`, `busca_alternativa`, `prompt`) vem do `roteiro_cenas.json` para essa frase. A escolha da pessoa (busca, imagem ou prompt dela) e a fatia de citação ficam. A cena ganha `pedido_mudou`, e `corrigir.depois_da_narracao` julga a foto dela de novo.
- **Cenas de IA seguidas têm prompts escritos juntos** (`imagens.prompts_em_sequencia`, no começo de `_gerar`, grátis, modelo principal): todo trecho de 2 ou mais cenas de IA seguidas do mesmo bloco, com imagem por fazer, é reescrito numa chamada (até 8 cenas), cada prompt no momento da própria fala, e o plano (`geral`, `medio`, `detalhe`) é obrigatoriamente diferente do da cena anterior. O código confere e devolve uma vez quando duas seguidas repetem o plano ou quase o mesmo pedido (`imagens.parecidos` >= 0,5), ou quando a de duas antes divide 0,4 ou mais (as cenas 24 e 26 do virou-filme saíram com a mesma pose: 0,41). Cena com imagem pronta ou com `prompt_manual` só entra como contexto. O prompt antigo fica em `prompt_antes_da_sequencia`. A medida de palavras sozinha não serve de gatilho: os quatro prompts repetidos do virou-filme davam 0,25 a 0,32.
- **Cena errada recebe imagem de IA, obrigatoriamente e sem teto** (desde 2026-10-03, pedido do usuário; `ia.ativa: true`). O pior erro é a cena mostrar outra coisa, e a IA é sempre melhor que isso. Material real continua primeiro, mas:
  - o agente marca `onde_existe` em cada cena (`banco`, `arquivo` ou `nao_existe`); `nao_existe` (um momento que ninguém fotografou) nasce como IA, mas **passa por uma busca antes** (`midia.tentar_banco_nas_nao_existe`, no fim de `midia.buscar` do projeto inteiro, uma vez por cena: `banco_tentado`). A regra é estrita: só fica a foto que o Jev aprovou antes de baixar, com a nota mínima e sem suspeita; o resto volta para a IA. No natureza-nos-ensina 4 de 13 acharam foto aprovada (o elefante derrubando árvores, o búfalo escondido no capim);
  - na conferência, cena **errada** (`corrigir.errada`: sujeito errado, época errada ou nota muito baixa sem sujeito certo) tem **uma** busca nova e, se continuar errada, vai para a IA (`corrigir.resolver_com_ia`). Três rodadas de busca quando o banco não tem a coisa só trouxeram mais lixo;
  - **só a cena errada vai para a IA, também no fim do `corrigir`**: a devolução da melhor imagem punha na lista da IA toda cena abaixo da nota mínima, e no natureza-nos-ensina hipopótamo (94% de sujeito certo), crocodilo (91%) e búfalo (88%) foram para a IA. Antes de `resolver_com_ia`, quem não é `errada` sai da lista e vai para revisão;
  - a foto que a cena tinha fica em `ia_reserva` e volta se a imagem de IA sair pior (`conferir_ia`) **ou não sair**
    (`corrigir._devolver_sem_imagem`): no nunca-deve-ter-dentro-de-casa-parte-2 o filtro recusou as cenas 65 e 66, a
    imagem antiga ficou em `antigas/` e o render parou com "Faltam imagens de 2 cenas";
  - **pedido recusado pelo filtro de segurança do provedor** ("rejected by the safety system") é reescrito uma vez pelo
    modelo principal, sem o detalhe gráfico (`imagens._prompt_sem_recusa`), em vez de repetir o mesmo pedido três vezes;
  - **o teto de 15% saiu** (`ESTILO_TETO_IA` não existe mais): ele transformava em foto de banco as cenas que o agente marcou como IA, e o virou-filme-em-1996 saiu com 86 cenas de outra coisa;
  - a estimativa da criação mostra o custo das imagens (total e por minuto); ela informa, não corta cena. Com `ia.ativa: false`, nenhuma IA e o tapa-buraco preenche.
- Ao refazer cenas, o `--forcar` apaga o cache dos lotes e guarda `imagens` e `midia` em pastas `_antigas_`.
- **Trocar a voz troca a voz, e as cenas ficam.** Cada bloco de narração guarda a assinatura da voz que o gravou (`narracao.assinatura_da_voz`: voz, modelo, estabilidade, similaridade, estilo, velocidade; ritmo e pausa ficam fora porque são ajustes grátis depois). Bloco com o mesmo texto mas outra voz é gravado de novo; bloco antigo sem assinatura tem a voz lida do custos_reais.json. Antes só o texto contava, e trocar Nelton por Leo Antonio no editor reaproveitava os blocos com a voz antiga. Ao narrar, o tempo de cada palavra da narração anterior fica em `alinhamento_anterior.json`, e `cenas.atualizar_tempos` leva cada corte de cena para o mesmo ponto da fala (`_mapa_de_tempo`); antes ele recalculava pelo começo da frase e regerar sem mudar nada levava 252 cenas a 260. As cenas só mudam se a fala desequilibrar (`_desequilibrou`, com folga de 0,5 s: abaixo de 2,5 s ou acima de 5,5 s): voz até 10% mais rápida ou mais lenta não mexe em nenhuma cena. O endereço da narração leve do editor leva a data, para o navegador não tocar a gravação antiga.
- **Trocar a narração nunca entrega vídeo com cena faltando.** Depois de narrar de novo (`POST /narracao` e `fabrica narrar`), a fábrica continua sozinha: `corrigir.depois_da_narracao` aponta as cenas sem imagem, as que ficaram com a foto antiga mas outra fala e as repetidas; no site, `api._completar_depois_da_narracao` solta as cópias repetidas e põe a esteira da criação para andar a partir da busca (feitas = mapa, narração e cenas), com a conferência do Jev só nessas cenas (`conferir_cenas`; as de outra fala são julgadas mesmo aprovadas na captura, `conferir_forcadas`), imagens de IA se ligada, completar, nenhuma repetida, animações e trilha. O editor mostra "Em produção" e o render fica travado até terminar; trocar a narração durante a esteira é recusado. No terminal, `cli.completar_depois_da_narracao` faz a mesma sequência (no `tudo` as etapas seguintes já fazem).
- **A imagem acompanha a fala quando a narração muda** (`cenas._levar_imagens_numeradas`, chamada em `atualizar_tempos`). A imagem de IA e a foto que a pessoa sobe do computador ficam em `imagens/NNNN.png`, pelo número da cena. Narrar de novo (outra voz, outro ritmo) divide, junta e renumera as cenas. Antes, as imagens ficavam com o número velho: a cena dona ficava sem arquivo e outra mostrava a imagem errada (no zz_teste_animacoes, 9 cenas sem arquivo e a foto da faca artesanal na cena errada). Agora cada cena antiga é achada pelas primeiras palavras dela no tempo novo (`_trechos_pela_fala`), e a imagem vai para a cena nova sem material real que cobre ao menos 35% dessa fala. A foto da pessoa (marca `imagem_da_pessoa`, que o upload grava; sem IA ligada, toda imagem numerada conta como dela) vence o acervo se não houver cena livre. Uma imagem por cena, nunca repetida: o pedaço novo de uma cena dividida (imagem numerada OU foto e vídeo de acervo, `cenas._sem_a_imagem_da_original`) fica sem arquivo, com a foto da original em `rejeitadas`, até o "Continuar carregamento" (antes ele levava uma cópia do material, e o zz_teste_animacoes narrado três vezes chegou a 68 cenas repetindo a vizinha). O material baixado leva o número da cena no nome; depois de renumerar, `midia.nome_livre` escolhe `NNNN_2.jpg` quando outra cena já usa `NNNN.jpg`, senão a foto nova apagaria a de outra cena. A estimativa do "Continuar carregamento" com a IA desligada é só o Jev (uns US$ 0,00005 por chamada, até 4 por cena). Na junção de duas cenas, o material real acompanha a busca que ficou (antes o tipo "ia" de uma vinha com o material da outra, e o editor marcava "sem arquivo" uma cena com foto de banco; o editor agora segue a regra do render: sem imagem de IA, mostra o material real). O que não tiver cena vai para `imagens/_sem_cena`, sem ser apagado.

## Animações (HyperFrames)

`fabrica/animacoes.py` e `fabrica/animacoes_modelos.py`, ligadas por `animacoes.ativo` no `config.yaml`. As cenas que o agente marca como `diagrama`, `texto_tela`, `linha_do_tempo` ou `mapa` (39 de 217 no ouro-da-serra-gaucha) não existem em banco de imagens e antes viravam a foto mais próxima (a iguana no "diagrama de rede clandestina"). Agora ganham uma animação, com cada elemento entrando no tempo exato da palavra falada.

- **A animação é uma CAMADA POR CIMA DAS CENAS, não uma cena** (desde 2026-10-03, pedido do usuário). Antes cada animação era um clipe da cena com a foto dela escurecida no fundo: trocar a imagem, dividir, juntar ou renumerar a cena deixava a animação "desatualizada" e a foto voltava. Agora cada animação fica em `animacoes/motion.json`, **presa às palavras do roteiro** (a posição `c` de cada palavra no `alinhamento.json`, que não muda quando a voz muda), e é desenhada num **MOV transparente (ProRes 4444)** com o véu escuro dentro. **Não amarrar a animação ao número, ao corte ou à imagem da cena de novo.**
  - Cenas de animação seguidas, do mesmo bloco, viram **uma** animação de até `animacoes.duracao_maxima` segundos (8), que segue por cima enquanto as imagens trocam embaixo (`_trechos`).
  - **A duração vem do que está escrito, não da cena** (`duracao_do_conteudo`, desde 2026-10-04, pedido do usuário): de 3 a 8 s, o tempo de ler todas as palavras (0,3 s cada) e de o último elemento ficar 1,5 s na tela. Ela começa na palavra e pode seguir por cima das cenas seguintes, mas nunca cobre o começo da próxima animação (`limite` em `gerar`, e `validas` corta se a voz mudou). Fica em `duracao` no `motion.json`; `_ancorar(..., pela_fala=True)` dá o fim da fala, usado nos tempos dos elementos e para achar as cenas livres. Antes a animação durava só a fala das cenas dela.
  - O render põe em dia as animações desatualizadas antes de montar (`por_em_dia`, sem animar cena nova e sem perguntar ao modelo quando dá): antes uma animação desatualizada sumia do vídeo sem aviso.
  - **Trocar a imagem ou mexer nas cenas não mexe na animação.** Trocar a voz reposiciona a animação na fala nova (`_ancorar`) e leva cada elemento para a mesma palavra (`_remapear`), desenhando de novo **sem perguntar ao modelo**. Roteiro editado antes do trecho: acha as mesmas palavras pela sequência. A fala do trecho mudou: a animação sai e a criação faz outra pelas cenas.
  - Em dia (`animacoes.validas`): o MOV existe e a assinatura (modelo, dados, tempos das palavras, tamanho, estilo, `animacoes_modelos.VERSAO`, `VERSAO_CAMADA`) bate. As cenas por baixo não entram na assinatura.
- **Quem faz:** o modelo principal (gratuito) escolhe um dos 8 modelos prontos (`frase`, `numero`, `contraste`, `radial`, `lista`, `fluxo`, `linha_do_tempo`, `mapa`) e preenche os textos curtos e o segundo de cada um. O design é da fábrica (`animacoes_modelos.py`). **Não deixar o modelo escrever o HTML livre:** isso foi testado e saiu ruim (elemento aparecendo antes de ser falado, elemento esquecido, layout embolado). (A exceção é o Motion IA, abaixo, por decisão do usuário, com esqueleto fixo e conferência.) O código (`conferir_dados`) encosta cada tempo na palavra falada mais próxima e corta texto comprido.
- **Conferência:** o `hyperframes check --json` reprova texto sobreposto, saindo da tela e regras de animação quebradas (o contraste fica de fora: com fundo transparente ele mede contra o nada); os erros voltam para o modelo, até `animacoes.tentativas`. Reprovada, as cenas ficam com a foto e o texto na tela.
- **Render:** as cenas são montadas como sempre e a camada entra por cima no `_mixar`, no segundo da fala (mais a abertura), antes do avatar e da legenda. Versão em pé: sem a camada.
- **Editor:** a animação tem **faixa própria (Motion), acima das Cenas**, e toca inteira por cima delas: `GET /cenas` devolve a lista `motion` (começo, fim, modelo, texto e a prévia) e o player toca a prévia `_previas/motion/ID_ASSINATURA.webm` (VP9 com transparência, `animacoes.previa_da_camada`, rota `/arquivos_previas/NOME/motion/ID.webm`) num vídeo próprio por cima das cenas. A cena mostra a imagem dela; `animada` diz que alguma animação passa por cima. **Não voltar à montagem por cena** (`composicao_da_cena`, removida): na troca de cena a animação reiniciava ou sumia, embora no vídeo final seguisse inteira. O WebM transparente toca no Chrome, Edge, Brave e Firefox; o Safari não mostra a transparência.
- **Onde roda:** último passo da criação pelo site, etapa `animacoes` no `tudo` (antes do render), comando `fabrica animacoes NOME [--cenas N...] [--forcar] [--remover]` e o cartão Animação no inspetor do editor (`POST /api/projetos/NOME/cenas/N/animacao`). "Voltar para a foto" marca a animação por cima da cena como `desligada` (ou grava um marcador desligado no tempo dela) e a criação não anima de novo sozinha.
- **Excluir animação pelo editor:** cada bloco da faixa Motion tem um ×, e o cabeçalho da faixa tem "× todas" (`DELETE /api/projetos/NOME/motion/ID`, ou `todos`; `animacoes.remover_item`). A animação fica `desligada` no `motion.json` (a criação não anima de novo aquele trecho) e o vídeo pronto muda no próximo render. Excluir uma só vira aprendizado do canal, como "Voltar para a foto".
- **Projetos de antes da camada:** a animação nova de uma cena só reaproveita o modelo e os dados de `animacoes/NNNN/partes.json`, sem perguntar ao modelo.
- **O Corrigir julga e troca a imagem embaixo da animação normalmente** (o Jev julga como "imagem de fundo do assunto"), porque a troca não estraga mais a animação.
- **Nunca para o vídeo:** sem Node, com a etapa desligada, offline ou com erro, a cena segue com a foto de sempre.
- **Fontes:** Inter e Playfair Display (licença OFL) em `fabrica/recursos/fontes`. Não usar fontes do Windows, que não podem ir para os amigos.

## Motion IA (cena abstrata reprovada vira clipe de motion)

`fabrica/motion_ia.py`, do `PRD-MOTION.txt`, ligado por `motion_ia.ativo` no `config.yaml` (no `.env`,
`JEV_MOTION_FALLBACK_ENABLED` e `JEV_MIN_SCORE_THRESHOLD`, de 0 a 10, valem por cima). Decisões do usuário em
2026-10-04: **HTML livre escrito pelo modelo** e o clipe **substitui a imagem da cena**; em 2026-10-05, **o Jev decide pelo
roteiro onde o motion vale a pena** (antes, só em cena abstrata).

- **Quando entra:** a cena ia para a imagem de IA (errada no Jev ou `nao_existe`) ou tirou nota abaixo de
  `motion_ia.nota_minima` (40) mesmo com o sujeito certo, **e o Jev, lendo o roteiro, diz que o motion vale a pena**
  (nota de 0 a 100, a partir de `motion_ia.nota_utilidade`, 70). São duas perguntas na mesma chamada, pelo mesmo preço,
  e a nota é a média: `PERGUNTA_DADO` (a fala traz um dado de infográfico?) e `PERGUNTA_UTIL` (o clipe, com a foto no
  card, explica melhor que só a foto?). O código acha o número com o que ele mede (`dado_na_fala`: "50 quilômetros por
  hora", "mais de uma tonelada", "cerca de 35 pessoas") e passa ao Jev. Com uma pergunta só, a primeira rodada deu 51%
  aos 50 km/h, 43% ao chifre de mais de um metro e 74% a "a ironia é que ele mesmo vive em perigo": a pergunta punha a
  aparência do animal como motivo para dizer não. Mudou a pergunta, suba `VERSAO_UTIL` (a nota guardada é refeita). Ele recebe a fala, duas cenas antes e
  duas depois (`_trecho_do_roteiro`), o assunto do bloco no mapa, o pedido do diretor de arte e o que a imagem de hoje
  mostra, e julga se um infográfico (número com o que ele mede, comparação, causa e consequência, etapas) explica a fala
  melhor que a imagem. A nota fica na cena (`motion_util`, `motion_util_fala`) e só é pedida de novo se a fala mudar.
  Pedido do usuário em 2026-10-05: antes um modelo só separava "abstrata" de "concreta", e o motion caiu em "e o primeiro
  lugar vai te surpreender", sem impacto, enquanto "pode passar dos 50 quilômetros por hora" ficava de fora por citar o
  rinoceronte. **A foto da cena é opcional** (pedido do usuário em 2026-10-05: "pode existir motion sem animal"; o
  velocímetro explica os 50 km/h sem o rinoceronte): cena com `animal` ou `exato` também vira motion. Quando a cena tem
  foto com o sujeito certo (Jev 60 ou mais; `foto_da_cena` procura na mídia, na `ia_reserva` em `antigas/` e na imagem
  de IA, e tira um quadro de vídeo), o modelo pode escolher o `foto_dado`, com ela num card ao lado do dado. O gancho é `imagens._motion_antes_da_ia`, no começo de `_gerar`, então vale para a
  criação, a conferência, o diretor e o refazer; a nota baixa entra pelo fim do `corrigir` (`_motion_com_nota_baixa`,
  marca `motion_so`). No terminal, `fabrica motion NOME [--cenas N...] [--aplicar] [--sim]` mostra a nota do Jev de
  cada candidata (com o custo antes, uns US$ 0,00007 por cena) e, com `--aplicar`, faz os clipes.
- **Quem faz:** só os modelos gratuitos (`OPENROUTER_FREE_MODELS` do `.env`, `motion_ia.modelos`, ou os `:free` e
  `stealth/` da cadeia de principais; modelo pago numa dessas listas é ignorado), em cascata, com no máximo 15 pedidos
  por minuto. Sem Groq (saiu da fábrica).
- **Modelos de demonstração** (`fabrica/motion_modelos.py`, pedido do usuário em 2026-10-05: os clipes saíam todos
  iguais, a foto num card e o número noutro, porque o modelo copiava o único exemplo do pedido). A fábrica desenha a
  demonstração de cada tipo de dado e o modelo de linguagem só escolhe e preenche os dados da fala (`_pelo_modelo_pronto`,
  `INSTRUCOES_MODELO`, `CATALOGO`): `velocimetro` (velocidade, o ponteiro sobe), `balanca` (peso, um peso de ferro cai
  na balança), `regua` (tamanho, a coisa cresce na régua; `forma: cone` desenha chifre, presa ou dente), `contador`
  (quantidade, um boneco ou ponto por unidade), `porcentagem` (anel), `comparacao` (barras), `tendencia` (queda ou
  subida até o marcador: "à beira da extinção"), `fluxo` (causa e consequência), `ranking` (posição acesa na lista),
  `frase` (ideia, palavra-chave em serifa sublinhada) e `foto_dado` (só com foto). O pedido diz os modelos das cenas de
  motion vizinhas, para variar. `motion_modelos.conferir` recusa número que a fala DESTA cena não diz (o "50" da vizinha
  fazia o "1 metro" do chifre ser recusado), palavra que nenhuma das falas diz, prefixo que não é quantificador ("passar
  dos" repetia o topo) e `foto_dado` sem foto. O dado achado na fala indica o desenho (`motion_modelos.indicado`: km/h
  pede o velocímetro, tonelada a balança, metro a régua, pessoas o contador, por cento o anel): com ele, `foto_dado` e
  `frase` são recusados (na cena 11 do natureza-teste-1min o modelo escolheu a foto no lugar do velocímetro). O que reprovar volta ao modelo (`motion_ia.tentativas_modelo`, 3); se
  nenhum modelo servir, vai o **HTML livre de reserva**: o modelo escreve css, html e js dentro do esqueleto
  (`montar_html`). O `partes.json` guarda `modelo` e `dados`. Mudou o desenho, suba `motion_modelos.VERSAO`.
- **Estilo editorial Vox / SaaS** (PRD de 2026-10-05, no lugar do "Apple Event" escuro): o esqueleto dá o fundo creme
  `#F7F6F2` com grade de pontos, as cores (`--verde`, `--azul`, `--laranja`, `--grafite`), as fontes Inter e Playfair,
  a linha do tempo `tl` do GSAP pausada, `window.seekToFrame` e as peças prontas: `.m-card` (branco, raio 20px, sombra
  suave, **flutua 5px sozinho** pelo `translate` do CSS, que não briga com a entrada do modelo), `.m-destaque` (serifa
  itálica colorida), `.m-linha` (path SVG que o esqueleto deixa escondido no tamanho exato; o modelo só leva
  `strokeDashoffset` a 0), `.m-barra` (cresce de baixo), `.m-foto` (a foto da cena) e as peças do dado: o `.m-card` já
  centraliza o conteúdo em coluna, com `.m-num` (168 px), `.m-rot`, `.m-sub` e `.m-frase` já no tamanho. Dentro do card
  nada de `position: absolute`: na cena 8 do natureza-teste-1min o número com `left: 1192px` contou da borda do card e
  saiu da tela, e o card ficou vazio. O pedido traz um exemplo de foto + dado (`INSTRUCOES_HTML`); com ele as cenas 8
  e 11, reprovadas nas 3 tentativas antes, saíram de primeira. As regras vão no pedido (`INSTRUCOES_HTML`): uma composição
  pela fala (número sozinho vira número enorme num card, **nunca gráfico inventado**; barras só com vários valores
  ditos; fluxo vira cards ligados por curvas; comparação, dois cards), centralizada, 60 px entre cards, entrada com
  mola `back.out(1.7)` (palavra sem scale, senão encosta na vizinha), tamanhos mínimos para o celular e os 260 px de
  baixo livres. A legenda é branca: uma faixa grafite suave embaixo (`#m-faixa-legenda`) deixa ela legível no fundo
  claro. Testado em 4 cenas reais (natureza-nos-ensina 97, virou-filme-em-1996 1, 30 e 121): 30 a 95 s por clipe.
- **Conferência:** o código recusa animação ou transição em CSS, relógio, sorteio, endereço externo, emoji, curva
  linear, entrada sem a mola, css vazio ou sem posição e tamanho de texto (na cena 6 do natureza-teste-1min o css veio
  vazio e tudo caiu no canto com letra de 16 px), texto abaixo de 32 px e palavra que a fala não diz (`problemas_do_codigo`,
  `_palavras_inventadas`); o `hyperframes check` recusa texto sobreposto e, como o fundo é opaco, contraste ruim
  (`animacoes._conferir(..., clipe=True)`). Texto fora da tela ou fora do card (`canvas_overflow`,
  `text_box_overflow`) o HyperFrames marca só como informação, e o clipe passava com o card vazio: no clipe isso
  reprova (`_ESTOURO_NO_CLIPE`), com uma dica para o modelo. O que reprovar volta para o modelo, até `motion_ia.tentativas`.
- **Gravação:** o HyperFrames grava o MP4 quadro a quadro num Chrome escondido (é o pipeline do PRD, sem Playwright),
  1920x1080, 30 quadros (`MOTION_RENDER_FPS` no `.env`), com a duração exata da cena (cena 6 do natureza-teste-1min: 3,231 s, clipe de 3,233 s).
  Fica em `midia/NNNN_motion.mp4`, com capa, e entra como a mídia da cena (`midia.fonte: motion_ia`, tipo
  `video_real`); o que a cena tinha fica em `motion_reserva` (`motion_ia.desfazer` volta). O pedido do modelo fica em
  `motion_ia/NNNN/partes.json`.
- **Nunca para o vídeo:** falhou (sem Node, modelo fora do ar, reprovado), a cena ganha `motion_ia_falhou` (não tenta
  de novo na mesma fala) e segue o caminho de antes: a imagem de IA se estava errada, a foto que tinha se era só nota
  baixa (`motion_so`, sem pagar imagem).
- **Onde ele não entra:** a conferência do Jev não julga o clipe (`corrigir.conferiveis`), a animação em camada não
  vai por cima dele (`animacoes.elegivel`, e `animacoes._fora_do_motion_ia` para a camada de uma cena anterior no
  começo do clipe: a frase da cena 5 do natureza-teste-1min, com o véu escuro, cobria o clipe da cena 6), e ele não vai para os créditos. No editor a cena mostra o selo
  **"Motion IA"** na lista e no cartão Origem Visual, e pode ser trocada como qualquer outra.

## Texto na tela: saiu da fábrica

Desde 2026-10-05, a pedido do usuário, a fábrica **não tem mais o texto na tela desenhado pelo FFmpeg** (destaque,
lista, capítulo e rótulo, em caixas por cima da imagem). Ele ficava amador ao lado das animações do HyperFrames e caía
por cima dos clipes de motion (na cena 11 do natureza-teste-1min, "MAIS DE 50 QUILÔMETROS POR HORA" numa caixa sobre o
clipe dos 50 km/h). Saíram a decisão dos textos (`cenas._textos_na_tela_groq`, `refazer_textos` e o comando `fabrica
textos`), o desenho (`textos.camadas` e os temas), o toque da trilha quando o texto entrava e a conversão do `overlay`
do agente em texto na tela. As cenas guardam `texto_tela: None`; o de projetos antigos fica no `cenas.json`, mas o
render não desenha e a API manda `None` ao editor. **Não trazer de volta.** O que fica: a legenda queimada, os cartões
de título (`[TITULO]`, `textos.camadas_titulo`, com o tema e as cores de `textos_na_tela` no perfil), o símbolo do canal
(`[SIMBOLO]`), as animações em camada e os clipes do Motion IA. `cenas._momento_falado` continua: ele põe o efeito
sonoro no tempo da palavra.

## Aprendizados do canal

`fabrica/aprendizados.py`. O que a pessoa corrige no editor vira exemplo para o agente de roteiro dos próximos vídeos
do mesmo canal (o perfil): a busca que ela digitou no lugar da do agente, a imagem que ela mesma subiu e a animação que
ela trocou pela foto. Fica em `aprendizados/CANAL.json` (fora do Git, até 300 por canal), e as 15 mais recentes vão no
pedido do agente como "APRENDIZADOS DO CANAL". Correção que não muda nada não entra. O texto usado num projeto fica
congelado em `aprendizados_usados.txt`: retomar uma criação não muda o que o agente já decidiu.

## Diretor (primeira ação do Corrigir Mídia)

`fabrica/diretor.py`. Quando a IA está ligada, o botão Corrigir Mídia (e `fabrica diretor NOME [--aplicar]`) começa
pelo diretor: o modelo do agente (`roteirista.modelo`, DeepSeek V4 Flash; a cadeia de principais de reserva) recebe o roteiro inteiro, o mapa e, de cada cena, a
fala, o pedido, o aceitável, onde existe, a época, o que a imagem mostra, as notas do Jev, de onde ela veio e o que a
revisão do vídeo pronto apontou. Ele lista só as cenas que precisam mudar: **ia** (com o prompt), **arquivo** (busca
de época na Wikimedia) ou **busca** (nova, no banco). As buscas rodam primeiro (grátis) e são julgadas; o que continuar
errado vai para a IA. A decisão fica em `diretor.json`. Sem frontend novo, o botão aplica sozinho e devolve no
resultado as decisões e o que foi gerado; no terminal, sem `--aplicar` só mostra a lista e o custo.

## Nota do vídeo

`fabrica/qualidade.py`. Grátis (só lê as notas do Jev): porcentagem de cenas certas, cenas que mostram outra coisa,
sem conferência, vazias, repetidas, de onde veio cada imagem (escolhida, tapa-buraco, IA, da pessoa) e por bloco. Fica
em `qualidade.json` (com o histórico) no fim da criação, do Corrigir, do diretor e do `tudo`; aparece no `fabrica
status` e em `GET /api/projetos/NOME/qualidade`. Serve para saber se uma mudança na fábrica melhora ou piora o vídeo.

## Testes

`uv run --no-sync --with pytest python -m pytest tests`: os filtros da captura e a decisão da conferência, com os casos
reais que já deram errado (elefante de Tsavo no acampamento, zebra no leão, "Patterson" trazendo ginasta, "tranca
quebrada" trazendo cânion). Sem rede e sem custo. Toda regra nova da captura ganha um caso aqui.

## Revisão do vídeo pronto

`fabrica/revisao_video.py`, ligada por `revisao_video.ativo`. Depois do render (no `tudo` e no site, em segundo plano),
o modelo principal recebe um quadro de cada cena do `final.mp4` (a 60% da cena, com o atraso da abertura de
`render/linha.json`), 8 por pedido, e aponta tela preta, imagem que não combina, texto cortado, sobreposto ou errado,
imagem repetida, marca-d'água e baixa qualidade. **Só aponta, não troca nada.** O resultado (`revisao_video.json`) só
vale para o `final.mp4` de agora; no editor vira o selo "⚠ revisar" na cena e o cartão Revisão no inspetor. Nunca
derruba o render.

## Versão em pé (Reels e Shorts)

`fabrica render NOME --vertical`, `fabrica tudo NOME --vertical` (monta as duas) ou o campo "Formato" na janela de
renderizar do editor (`vertical: true` no `POST /render`). Sai em `final_vertical.mp4`, com tudo em `render_vertical/`:
a limpeza dos clipes velhos de uma versão nunca apaga os da outra, e **o vídeo deitado não muda**.

- Tela 1080x1920 pela seção `vertical` do `config.yaml`, que fica **fora** da seção `render` de propósito: os ajustes
  do render entram no nome de cada clipe, e mexer neles faria a versão deitada de todo projeto renderizar de novo.
- Foto ou vídeo deitado perde as laterais só até ficar quadrado (`vertical.recorte`) e fica sobre uma cópia dele
  mesmo, desfocada (`render._encaixe` e `_preparar_foto`). Cortar para 9:16 jogaria fora dois terços da imagem.
- Cartões de título são desenhados para a tela deitada e levados para a faixa do meio da tela em pé
  (`textos.para_vertical`), longe da legenda e dos botões do app. A legenda sobe (`ESTILO_LEGENDA_VERTICAL`).
- Sem animações (foram desenhadas para a tela deitada: a cena volta à foto) e sem o quadro do
  personagem. A revisão do vídeo pronto olha só o deitado.

## Trilha e efeitos gerados

`fabrica/trilha.py`, ligada por `trilha.ativo`. **Todo vídeo sai com trilha**, sem custo e sem arquivo de música.

- **Partitura:** o modelo principal lê os blocos do roteiro (o campo `bloco` das cenas; projeto sem blocos é cortado
  em trechos de uns 90 s) e escolhe, por bloco, clima, tom, modo, andamento, sequência de acordes, intensidade, pulso
  grave e o efeito de entrada. O código confere e completa pelo clima (`CLIMAS`); sem modelo (offline ou fora do ar)
  a partitura sai só pelas regras. Fica em `trilha/partitura.json`, com assinatura dos blocos.
- **Som:** o código toca a partitura com numpy (colchão de acordes com as vozes andando pouco, baixo, arpejo de sino e
  pulso grave), com fusão de 2 s na troca de bloco e ambiente pelo FFmpeg, em `trilha/trilha.wav`. Mudou o jeito de
  tocar, sobe `trilha.VERSAO`. Um vídeo de 11 min toca em uns 45 s.
- **Quando entra:** no render, quando o perfil não aponta músicas ou a pasta está vazia (as músicas do canal não vêm
  no pacote); com `trilha.substituir: true`, sempre. Volume em `trilha.volume_db` (-16), abaixo do
  `volume_musica_db` do perfil. Medido: voz em -16 LUFS e trilha em -32 LUFS.
- **Efeitos:** passagem de ar, impacto e subida na troca de bloco (o que a partitura pediu), impacto no cartão de
  título. No máximo um a cada 6 s. São tocados
  pelo código uma vez e guardados em `efeitos/gerados/`. Perfil com os efeitos da ElevenLabs ligados segue com os dele.
- **Onde roda:** etapa `trilha` no `tudo` (antes do render), último passo da criação pelo site, `fabrica trilha NOME
  [--forcar] [--efeitos]` e, se nada disso rodou, o próprio render. **Nunca para o vídeo:** se falhar, sai só com a voz.

## Agente de roteiro (principal do passo de cenas)

`fabrica/roteirista.py`, ligado por `roteirista.ativo` no `config.yaml`. Ele não entra em modo offline nem em perfil com personagem ou efeitos, que seguem pelo caminho antigo.

1. **Mapa** (`fabrica mapa NOME`, e sozinho no início de `cenas`). Lê o roteiro inteiro e grava `roteiro_mapa.json` com os blocos de assunto (cada um com a âncora visual e a posição no roteiro), as armadilhas de busca, as pessoas reais, o que é proibido e as imagens recorrentes. Só depende do texto, então roda antes da narração. Quem responde é o `roteirista.modelo` (`roteirista.provedor: openrouter`; hoje o `deepseek/deepseek-v4-flash`, com raciocínio `low`), com a cadeia de principais de reserva se ele falhar. **O Claude da assinatura não serve para a fábrica** (decisão do usuário, 2026-10-03; o código `_PeloClaude` ficou, desligado). Medido no roteiro de Tsavo (8,5 min): uns US$ 0,22 por vídeo, cerca de US$ 0,01 por lote, bem acima do preço de tabela por causa do raciocínio; com o raciocínio alto ele levava 30 min e estourava o limite pensando. Comparado ao Claude, o DeepSeek escreve o JSON limpo e o aceitável em todas as cenas, mas acha menos armadilhas de busca (3 contra 16) e manda mais cenas para a IA (68 contra 48). O mapa traz também `quem_e` (anos de vida e o que cada pessoa real fez, contra homônimos) e a `epoca` de cada bloco. Na criação pelo editor, o mapa aparece na janela de progresso e fica em `GET /api/projetos/NOME/mapa`.
2. **JSON de cenas** (`roteiro_cenas.json`, também no `fabrica mapa`). Feito só com o texto, antes ou junto da narração: o corte (`_pre_cortar`) usa o tempo previsto de cada frase pelo `ritmo.caracteres_por_minuto` do perfil, e para cada bloco, em lotes de `roteirista.cenas_por_lote` e com `roteirista.paralelo` blocos ao mesmo tempo, o agente decide tipo, descrição, busca, prompt, texto curto da animação (`overlay`), `onde_existe`, `aceitavel` e `epoca`. **Antes de aceitar, o código confere cada lote** (`roteirista.problemas_do_lote`): palavra grudada ou lixo ("exércitoBritish"), a mesma descrição em cenas seguidas com falas diferentes e `exato` em português pedem a resposta de novo, uma vez; o que sobrar é limpo (`_limpar_resposta`). O que ele deixar sem resposta cai no caminho antigo. No `tudo` e no editor ele roda em paralelo com a narração.
3. **Passo de cenas = encaixe.** Os números das frases saem só do texto, então o JSON se encaixa nas frases da narração sem nenhum modelo: o passo de cenas aplica as regras fixas de tempo. Se a narração tiver outro número de frases (roteiro mudou), o agente decide sobre os cortes reais.

O que o agente decide segue adiante: `mostrar` (a descrição) vai para a escolha do acervo, para o Jev e para a busca nova das reprovadas; `overlay` vira o texto da animação em camada; as armadilhas corrigem por código a busca que for só o nome ambíguo. Tipos de animação (`texto_tela`, `linha_do_tempo`, `mapa`, `diagrama`) ficam guardados em `visual` e viram animação (seção Animações, acima). As regras fixas acima continuam valendo depois dele.

## Como o sistema funciona por dentro

Cada projeto vive em `projetos/NOME`. As etapas são estas.

1. **Narração.** A GenAIPro (`fabrica/genaipro.py`) grava cada bloco como uma tarefa, 4 blocos ao mesmo tempo. O tempo de cada palavra vem da legenda que ela gera com um caractere por linha (uma palavra por bloco da legenda), e o fim de cada palavra é encostado no silêncio real do áudio (`narracao._encostar_nas_pausas`), porque na legenda a pausa depois do ponto fica dentro da palavra anterior. Isso sustenta a legenda e os textos animados. A tarefa criada fica anotada em `bloco_NNN.mp3.tarefa.json` antes da espera: se a fábrica cair, rodar de novo retoma a mesma tarefa sem pagar outra vez. O áudio bruto de cada bloco fica guardado, então mudar ritmo ou pausa não custa nada.
2. **Cenas.** O Claude recebe as frases com a duração e devolve grupos, dizendo se cada cena é foto real, vídeo real ou imagem de IA, com os termos de busca e o prompt.
3. **Material real.** Busca no Wikimedia, no Pexels e no Pixabay, o Claude escolhe pelas miniaturas e o sistema grava `creditos.txt`, que vai na descrição do vídeo.
4. **Imagens.** O **GPT-5.4 Image 2 em qualidade baixa** pelo OpenRouter gera as que faltam (`imagens.provedor: openrouter`, `modelo: openai/gpt-5.4-image-2`, `qualidade: low`; padrão desde 2026-10-04, pedido do usuário depois do teste no natureza-teste-1min: uns US$ 0,005 por imagem medidos, em 16:9, na chave do OpenRouter que a fábrica já usa). O Grok Imagine 2 pelo OpenRouter (`x-ai/grok-imagine-image-2.0`, US$ 0,04) continua valendo para quem o tem no perfil ou no projeto. A Kie (o mesmo modelo, US$ 0,02, saldo à parte) e o Google (Nano Banana 2, com modo lote) continuam como opção no perfil e no editor. **GPT Image da OpenAI pelo OpenRouter** (`imagens.modelo: openai/gpt-image-1` com `provedor: openrouter`): ele não responde pelo chat e sim pela interface de imagens (`POST /api/v1/images`, `imagens._imagem_openrouter_images`, `PREFIXO_IMAGES_API`); não aparece na lista principal de modelos do OpenRouter, mas existe. Aceita só 1:1, 3:2 e 2:3 (a fábrica pede 3:2, 1536x1024, e o render corta para 16:9) e `imagens.qualidade` low, medium ou high (padrão low). Medido no natureza-teste-1min em qualidade baixa: US$ 0,0165 a 0,0174 por imagem (o OpenRouter informa o custo, que é o registrado; sem ele vale `PRECO_GPT_IMAGE`). **O GPT-5.4 Image 2** (`imagens.modelo: openai/gpt-5.4-image-2`) vai pela mesma interface de imagens (é o pedido do playground do OpenRouter, com `quality` e `aspect_ratio`), e aceita **16:9** (1536x864, sem corte). Medido no natureza-teste-1min em qualidade baixa: **US$ 0,0044 a 0,0059 por imagem**, quase 10 vezes mais barato que o Grok (US$ 0,04), e o usuário achou a qualidade boa; a do gpt-image-1 em qualidade baixa ele achou péssima.
5. **Render.** O FFmpeg monta tudo com movimento lento nas fotos, as animações por cima, música e legenda.

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
| Um banco cai ("Server disconnected", tempo esgotado, erro 5xx) | a busca tenta de novo em 2 e 5 s (`midia.ESPERAS_QUEDA`); caindo 3 buscas seguidas, o banco fica 3 min de fora e volta sozinho (`Buscador._caiu`). Antes desistia na hora |
| `'charmap' codec can't encode characters` derruba a esteira | o backend no Windows gravava o fabrica.log na codificação antiga e caía com um pedaço em chinês do modelo. `cli.main` força UTF-8 na saída desde 2026-10-03; se voltar, confira se alguém tirou isso |
| Criação pelo site parada nos 15% ("Esperando o agente terminar o JSON das cenas") | o agente de roteiro ainda decide as cenas, lote a lote (383 cenas no nunca-deve-ter-dentro-de-casa-parte-2 levaram quase uma hora). Desde 2026-10-05 a barra anda de 15% a 35% com os lotes decididos (`roteirista.PROGRESSO`), e o modelo que estoura o limite pensando tenta uma vez só, já no teto (`openrouter.max_tokens_teto`), e passa para o seguinte da cadeia (antes subia em dois degraus, minutos cada). Cada lote guardado é achado pelo trecho do roteiro, sem o resumo das cenas anteriores (`roteirista.arquivo_do_lote`): com o resumo na marca, um reinício refazia e pagava de novo lotes prontos. Para ver se anda: os arquivos novos em `cenas_lotes/` e o fim de `criacao.json` |
| Render parado na mesma porcentagem, mas o FFmpeg segue montando clipes | um clipe falhou e o executor montava todos os outros calado antes de mostrar o erro. Desde 2026-10-06 o render para na hora e diz a cena (`render.renderizar`). A causa, no nunca-deve-ter-dentro-de-casa-parte-2, foi o Corrigir Mídia rodando junto: a cena 166 virou foto do Pexels e o FFmpeg não achou `imagens/0166.png`. Agora render, Corrigir, Continuar e Limpeza se recusam no mesmo projeto enquanto outro roda (`api._recusar_se_ocupado`) |
| Completar cenas depois de trocar a narração demora | a escolha das fotos roda `midia.escolhas_ao_mesmo_tempo` lotes de 6 cenas juntos (4; antes 2, uma cena por minuto). O ritmo depende também do limite de buscas do Pixabay e do Unsplash |

## Quem responde cada etapa

**Modelo de texto pago só com a confirmação da pessoa, e só depois de TODOS os gratuitos** (`fabrica/pago.py`,
`openrouter.confirmar_pago`, pedido do usuário em 2026-10-06: o saldo do OpenRouter caiu de US$ 6,10 para US$ 1,97 em
dois dias, US$ 2,59 deles no Qwen Flash pago escolhendo as fotos do nunca-deve-ter-dentro-de-casa-parte-2, sem ninguém
saber). `openrouter_local.perguntar` põe todos os gratuitos da cadeia na frente dos pagos (na do agente, o DeepSeek
vinha antes do Groq) e, antes do primeiro pago, chama `pago.autorizar`: no servidor a tarefa **espera sem gastar** e o
editor mostra "APIs gratuitas esgotadas" (`js/pago.js` do frontend, pelo `pago_pendente` de `GET /status` e por
`GET /api/projetos/NOME/pago`), com "Usar a API paga" (`POST /pago`, vale para o projeto até o fim do dia, em
`pago_liberado.json`) ou "Esperar os gratuitos" (a tarefa tenta os gratuitos de novo quando o primeiro volta, ou de
minuto em minuto, e o aviso some quando um atende). No terminal pergunta [s/N]; sem terminal para com `GratisEsgotado`
(BaseException, para os `except Exception` não mandarem a cena para o tapa-buraco ou para a IA paga) e
`uv run fabrica pago NOME` libera. Cadeia sem nenhum gratuito (o Jev, escolhido de propósito) segue sem perguntar; as
imagens de IA seguem com a estimativa de sempre.

**O máximo de API gratuita** (pedido do usuário em 2026-10-05, que trouxe o Groq de volta): toda cadeia começa pelos
gratuitos e só termina no pago. **Groq** entra como rota `groq:MODELO` (`openrouter_local.uma_rota`, `groq_local.perguntar`
com `na_cadeia=True`), revezando as `GROQ_API_KEY` do `.env` (11 hoje); cada chave tem 1.000 pedidos por dia e 8.000
tokens por minuto por modelo. Ele tem hoje três modelos úteis: `qwen/qwen3.8-27b` (**enxerga imagem**: a folha de
candidatos em 1,1 s), `openai/gpt-oss-120b` e `openai/gpt-oss-20b` (só texto). Rota do Groq que não atende (todas as
chaves no limite do minuto ou do dia, fora do ar) levanta `RotaIndisponivel` e fica de lado em `_FORA_DO_AR`; resposta
sem as chaves do esquema ou com outro alfabeto é pedida de novo uma vez. Pedido com imagem pula quem está em
`openrouter.so_texto`. **Reserva da resposta no Groq: 3.000 tokens** (`groq.max_tokens`): o Groq conta a reserva no limite por minuto, e com 8.000 cada escolha de fotos ocupava o minuto inteiro da chave; na criação, com 4 escolhas ao mesmo tempo, as 11 chaves saturavam e a escolha caía no Qwen pago. 404 por causa de imagem (o `openrouter/free` mandou para um modelo que só lê texto) deixa a rota de lado 5 min, não 24 h. A cadeia de visão tem ainda o Gemma 4 26B e o Nemotron Nano Omni antes do pago. **Antes de pagar, espera uns segundos pelo gratuito** (`openrouter.espera_pelo_gratis`, 60 s, `openrouter_local._espera_pelo_gratis`): se as rotas gratuitas estão fora só pelo limite do minuto (o Groq diz em quantos segundos a chave volta; os gratuitos do OpenRouter têm um limite por minuto da conta inteira), a cadeia espera a primeira voltar em vez de ir para o pago; o pago só entra com o gratuito fora por mais tempo (cota do dia, fora do ar). Num pico da conferência do nunca-deve-ter-dentro-de-casa-parte-2, com tudo no limite do minuto, 27 descrições foram para o Qwen pago em 1 minuto. Esperar segundos não é esperar cota: a regra de nunca ficar parado vale para minutos e horas. Testado no natureza-teste-1min, de graça: escolha das fotos em 8 s (a foto 3 em primeiro, como o
Qwen pago e o Dots), descrição para o Jev em 4 s, trilha e buscas em 1 s. **Descrição é uma cena por chamada**
(`corrigir.cenas_por_descricao: 1`): com três imagens numa chamada, o Qwen do Groq descreveu o rinoceronte da cena 7
com o guepardo da cena 3. O agente de roteiro não cabe no Groq (cada lote lê uns 6.800 tokens e escreve uns 7.800) e
ficou com o `nvidia/nemotron-3-ultra-550b-a55b:free` na frente do DeepSeek (`roteirista.modelos`, `roteirista._PelaCadeia`). Comparados com o mesmo pedido em 3 lotes do nunca-deve-ter-dentro-de-casa-parte-2, ele foi igual ou melhor (acertou a Naja kaouthia do caso do DF, pediu a colagem dos 10 animais do vídeo anterior e os frascos de vacina antirrábica onde o DeepSeek repetia o quati na cozinha; uma vez inventou uma raposa-do-deserto que a fala não cita), de 1,5 a 4 min por lote, sem estourar o limite pensando. O DeepSeek custava US$ 0,28 num vídeo de 30 min. Cadeia de principais (`openrouter.principais`), em ordem:
`groq:qwen/qwen3.8-27b`, `groq:openai/gpt-oss-120b`, os gratuitos do OpenRouter (Gemma 4 31B, Dots 3 Note, Nemotron
Super, `openrouter/free`) e, por último, o `qwen/qwen3.8-flash`, **pago** (US$ 0,15 e 0,47 por milhão de tokens, uns US$ 0,80 por vídeo se fizer tudo; aprovado pelo usuário em 2026-10-03), que só entra quando os gratuitos acabam: o limite de 1.000 chamadas por dia vale para a conta inteira, e um vídeo usa de 1.200 a 2.300. A cadeia também aceita rota pela
AIMLAPI (`aimlapi:` na frente do modelo, chave `aimlapi_api` no `.env`), tirada em 2026-10-03 a pedido do usuário. Quando um não atende (sem saldo, limite do dia dos
gratuitos, retirado do ar, servidor cheio), `openrouter_local.perguntar` passa na hora para o seguinte e deixa o que
caiu de lado um tempo (`_FORA_DO_AR`): nunca esperar. O Space Bunny (`stealth/space-bunny-alpha`), que abria a cadeia,
saiu do OpenRouter em 2026-10-05 (404) e saiu da lista e dos padrões do código. No mesmo dia o `qwen/qwen3.8-27b`
deixou de ser gratuito (só pago, e mais caro que o Flash), e o Gemma 4 31B gratuito entrou no lugar, a pedido do
usuário. **Teste de 2026-10-05, nas tarefas do modelo principal** (escolher fotos pela folha de candidatos, descrever
imagens para o Jev, compor a trilha, escrever buscas em JSON): o Gemma 4 31B e o 26B gratuitos deram 429 em todas as
chamadas ("temporarily rate-limited upstream": o Google limita o gratuito para todos, não é a conta). Na cadeia isso
custa meio segundo por minuto: o 429 deixa o Gemma de lado por 1 minuto e a chamada passa na hora para o Qwen Flash,
que hoje faz quase tudo (uns US$ 0,80 por vídeo). O `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (enxerga
imagem) descreveu as fotos no formato certo, compôs a trilha e escreveu as buscas, mas levou 575 s para escolher as
fotos de UMA cena e escolheu um só candidato: não serve para a escolha. O `nvidia/nemotron-3-super-120b-a12b:free`
(só texto) responde rápido e faz o Motion IA (`motion_ia.modelos`). Comparação de 2026-10-03 nos testes da fábrica (descrever foto,
escolher entre imagens, compor a trilha, dividir o roteiro): o Qwen gratuito passou em tudo, com português mais limpo
que o Space Bunny; Gemma gratuita vivia lotada (429), Inkling só serve em ferramenta de agente, Dots falha com imagem.
O limite dos gratuitos na conta é de 1.000 chamadas por dia, e um vídeo usa de 1.200 a 2.300: por isso a cadeia. O
Space Bunny da AIMLAPI vinha do mesmo espaço stealth do OpenRouter, e a AIMLAPI exige saldo até para ele.
**Cadeia de visão** (`midia.modelos_visao` e `midia.raciocinio_visao` no `config.yaml`, `openrouter_local.VISAO`,
pedido do usuário em 2026-10-05: "as análises e buscas de mídia eram para ser gratuitas"): quem olha as imagens (escolha
das fotos, descrição para o Jev, revisão do vídeo pronto) vai primeiro pelos gratuitos que enxergam imagem
(`groq:qwen/qwen3.8-27b`, `dots-studio/dots-3-note-preview:free`, `google/gemma-4-31b-it:free`, `openrouter/free`)
e só por último pelo Qwen Flash pago, **sem raciocínio**. No nunca-deve-ter-dentro-de-casa-parte-2 (30 min, 457 cenas) a escolha caiu toda no Qwen pago, com o
raciocínio dele: 1.351 chamadas para 594 folhas de candidatos, 2.500 tokens escritos por chamada, US$ 2,44 (o vídeo
inteiro, US$ 2,91, uns US$ 0,10 por minuto). Medido na cena 7 do natureza-teste-1min: Dots sem raciocínio escolhe em
25 s, de graça, na mesma ordem do Qwen (com raciocínio ele levava 99 s); Qwen sem raciocínio, uns US$ 0,001 por folha;
Nemotron Nano Omni sem raciocínio responde em 12 s mas não escolhe nenhuma foto. A descrição que o modelo não
escreveu na escolha **não é pedida de novo** (o `_completar_vejo` saiu em 2026-10-06, pedido do usuário: era 551 das
1.570 chamadas da escolha no nunca-deve-ter-dentro-de-casa-parte-2, US$ 0,97 no Qwen pago); o escolhido passa sem o
Jev antes do download e a conferência depois do download julga a cena, que não foi aprovada na captura. Os gratuitos têm 1.000 chamadas por dia na conta: um vídeo de 30 min
usa umas 600 na escolha, então o segundo vídeo grande do dia cai no Qwen sem raciocínio.
**MiMo e Gemini não são mais usados** em nenhuma etapa; o Groq voltou como rota gratuita. O Jev continua sendo o juiz.

**Voz grátis: Fish Audio** (`fabrica/fish.py`, `voz.provedor: fish`), no lugar do Edge-TTS, pelo OpenRouter
(`fish-audio/s2.1-pro-free:free`); as vozes são as da biblioteca pública da Fish (`GET /api/vozes/fish`, com amostra),
e no editor o botão Fish Audio usa a mesma grade de vozes da GenAIPro. A Fish devolve só o áudio: o tempo de cada
palavra vem da transcrição (`fish.palavras_com_tempo`, Whisper turbo, casando as palavras ouvidas com as do roteiro)
e, sem saldo para ela, de `narracao._palavras_estimadas`, que casa cada ponto e vírgula do roteiro com a pausa real do
áudio (limite de silêncio ajustado ao volume, `_pausas_da_voz`, porque a Fish tem chiado perto de -35 dB). Medido no
áudio do Edge, que informa o tempo real: erro médio de 0,08 s por palavra. Projeto antigo com Edge continua
funcionando; no editor ele aparece como Fish e regerar troca a voz.

| Etapa | Quem responde |
|---|---|
| Agente de roteiro (mapa e cenas) e diretor | `roteirista.modelos` em cadeia: Nemotron Ultra 550B gratuito, DeepSeek V4 Flash pago de reserva, e depois a cadeia de principais |
| Contexto dos blocos | cadeia de principais (Groq primeiro) |
| Buscas das reprovadas | cadeia de principais (Groq primeiro) |
| Escolha das fotos e vídeos do acervo (olha as miniaturas) | cadeia de visão: Qwen 27B do Groq, Dots, Gemma e `openrouter/free` gratuitos; Qwen Flash pago sem raciocínio de reserva |
| Descrição das imagens para a conferência e revisão do vídeo pronto | cadeia de visão (a mesma) |
| Julgamento (a imagem combina com a fala?) | Jev, pelo OpenRouter; se ele cair, o modelo principal julga |
| Imagens de IA | GPT-5.4 Image 2 em qualidade baixa pelo OpenRouter (`openai/gpt-5.4-image-2`), padrão do perfil base |

Cuidados com esse modelo, que já custaram erro:
- Ele **mistura pedaços de outros alfabetos** no meio do texto ("uma composição清楚的", "esteiras스타일"). `openrouter_local.perguntar` avisa em todo pedido que a resposta é só em alfabeto latino (`REGRA_DO_ALFABETO`), pede de novo uma vez quando a resposta traz chinês, japonês, coreano, cirílico, árabe e afins, e se ainda sobrar, **traduz** cada trecho no idioma do texto em volta (`_traduzir_trechos`, uma chamada a mais) em vez de só apagar: apagado, "分布于岩石和灌木之间" (entre rochas e arbustos) sumia da descrição que o Jev lê. Comentário do modelo sobre o próprio raciocínio volta vazio. Se a tradução falhar, o que sobrar é tirado (`_sem_outro_alfabeto`). Acentos do português ficam.
- Ele **ignora o `response_format`** e inventa os nomes das chaves. Por isso `openrouter_local.perguntar` põe o
  esquema também no texto e **confere se as chaves obrigatórias vieram**, pedindo de novo quando não vêm.
- Ele **pensa antes de responder**: sem `raciocinio_por_modelo: stealth/: low`, gastava todo o limite pensando e
  não entregava a resposta.
- É um modelo "stealth": gratuito e em teste, pode ter limite de uso, ficar fora do ar ou sumir do OpenRouter.
  Para trocar ou reordenar, mude a lista `openrouter.principais` no `config.yaml`.

## Custo real, medido

Cada etapa paga grava o que foi cobrado em `projetos/NOME/custos_reais.json` na hora em que
cobra (`fabrica/custos_reais.py`). Bloco de narração ou imagem reaproveitados do cache não
entram, porque não geraram cobrança nova. Os modelos de texto gravam os próprios
`uso_groq.json`, `uso_openrouter.json`, `uso_jev.json` e `uso_gemini.json`, e o resumo junta tudo.

- `uv run fabrica custo NOME` mostra a estimativa e, embaixo, o gasto real por categoria, por
  minuto de vídeo e por cena.
- O botão **Custos** do editor mostra o mesmo.
- **Narração em créditos, medida no saldo.** A GenAIPro cobra em créditos (US$ 22 por 1 milhão, `assinaturas.genaipro`)
  e **não é 1 crédito por caractere**: 10.543 caracteres gastaram 676 créditos (uns 0,064 por caractere, turbo v2.5),
  e o Custos mostrava uns 15 vezes o gasto real. A GenAIPro não informa o gasto de cada tarefa, então
  `narracao.narrar` lê o saldo antes e depois (`_registrar_gasto_da_narracao`) e grava os créditos de verdade. A média
  medida de cada modelo fica em `genaipro_medido.json` (fora do Git) e vale para a estimativa; sem medida, vale
  `genaipro.creditos_por_caractere` do `config.yaml`. Registro antigo (1 crédito por caractere) é recalculado na hora
  de mostrar. Diferença de saldo zero ou maior que os caracteres (outra narração ao mesmo tempo) vira estimativa.
- O Groq é do plano gratuito e conta zero. OpenRouter e Jev informam o custo real de cada
  chamada. O Gemini é calculado pelos preços por milhão de tokens do `config.yaml`.

## Custo real, para calibrar

Um vídeo de 36 minutos com 250 cenas, 60% de material real e 94 imagens saiu por uns US$ 5,60, algo como US$ 0,16 por minuto. A narração foi US$ 1,91 na ElevenLabs; na GenAIPro (US$ 22 por 1 milhão de créditos, uns 0,064 crédito por caractere) a mesma narração sai por volta de US$ 0,05, uns US$ 0,0013 por minuto. O resto foi imagem. O Claude pela assinatura não custa nada além da mensalidade.

Sempre informe o custo total **e o custo por minuto** quando falar de dinheiro.
