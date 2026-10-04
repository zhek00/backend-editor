# Plano de atualizações da fábrica

Escrito em 3 de outubro de 2026, a partir da análise do vídeo **virou-filme-em-1996** (os leões de Tsavo).

**Objetivo:** cada cena mostra o que a narração fala, naquele segundo. O pior erro é a cena **totalmente errada**
(uma ginasta no lugar do caçador, um elefante no lugar do acampamento). Imagem de IA é muito melhor do que isso.

## Andamento (3 de outubro, noite)

| Item | Situação |
|---|---|
| 0.1 Nota do vídeo | **Feito** (`qualidade.py`, `qualidade.json`, `fabrica status`, `GET /api/projetos/NOME/qualidade`) |
| 0.2 Três roteiros de teste | Falta escolher os dois que faltam (o de Tsavo já está em `zz_teste_plano`) |
| 0.3 Testes automáticos | **Feito** (`tests/`, 18 casos) |
| 1.1 Agente pelo Claude da assinatura | **Feito** (`roteirista.provedor: claude`, modelo principal de reserva) |
| 1.2 `onde_existe` e 1.3 aceitável | **Feito** |
| 1.4 Conferência do JSON do agente | **Feito** |
| 1.5 Armadilhas de duplo sentido | **Feito** |
| 2.1 Descrição sem o pedido | **Feito** (no Corrigir) |
| 2.2 Jev com três perguntas e o bloco | **Feito** |
| 2.3 Nova ordem (uma busca, depois IA) | **Feito** |
| 2.4 Vídeo de banco só onde faz sentido | **Feito** |
| 2.5 Categorias da Wikimedia em cena de época | **Feito** |
| 3.1 e 3.2 IA obrigatória, sem teto | **Feito** (`ia.ativa: true`) |
| 3.3 Prompt de época | **Feito** |
| 3.4 O Jev confere a imagem de IA | **Feito** (`conferir_ia`) |
| 4.1 Diretor | **Feito** no servidor e no terminal (`fabrica diretor`) |
| 4.2 Lista para confirmar no editor | Falta: precisa do frontend |
| 4.3 Nunca piorar | **Feito** |
| 4.4 Revisão do vídeo pronto alimenta o diretor | **Feito** |
| 5.x Editor | Falta: precisa do frontend |
| 6.1 Modelo principal | **Decisão sua** (ver abaixo) |
| 6.2 Modo offline no Windows | **Feito** |
| 6.3 Repositório dos amigos | **Decisão sua** |
| 6.4 Camada de animação em produção | Falta um vídeo real |

## O que o virou-filme mostrou

| Medida | Resultado |
|---|---|
| Cenas | 155 |
| Reprovadas pelo Jev (nota abaixo de 50) | 139: 66 com nota de 0 a 3%, 20 de 4 a 10%, 8 de 11 a 19%, 30 de 20 a 39%, 15 de 40 a 49% |
| Preenchidas pelo tapa-buraco na criação | 118 de 130 |
| Cenas em que o modelo recusou todos os candidatos | 86 de 146 |
| Cenas claramente erradas (nota até 10%) | 86 |
| Das quais, as gritantes, vistas uma a uma | cerca de 45 (outros "Patterson", outro bicho, coisas sem relação) |
| Imagens sem conferência nenhuma depois do Corrigir | 77 |

**As causas, em ordem de peso:**
1. O agente pedia o que não existe em banco ("leão arrastando um homem para a escuridão em 1898"), e a IA estava
   desligada. Essas cenas foram para o banco de imagens e o tapa-buraco pôs qualquer coisa.
2. O tapa-buraco aceitava qualquer foto que citasse uma palavra ("Tsavo", "Patterson").
3. O Corrigir rodou três rodadas de busca nova e terminou pior, com imagens que ninguém conferiu.
4. O modelo principal escreveu texto embaralhado nos pedidos ("exércitoBritish", "manless") e copiou a descrição de
   uma cena para as seguintes.

## A decisão: qual caminho para a IA

Foram avaliadas três hipóteses:

| | A favor | Contra |
|---|---|---|
| **1. Cena vazia, a IA preenche** | Simples, e a IA só entra onde faltou foto | A cena vai para a IA porque a busca falhou, não porque a coisa não existe em foto. Uma foto ruim que passou no filtro continua no vídeo. E o render trava até a IA terminar |
| **2. Tapa-buraco preenche, o Jev aponta o que é impossível** | O vídeo sai sempre completo | O Jev só lê a descrição da imagem e responde com um número. Não sabe se a coisa existe em banco nem diferencia "foto errada que existe certa" de "isso nunca foi fotografado" |
| **3. Corrigir Mídia com o roteiro completo troca por IA o que não faz sentido** | Visão do vídeo inteiro, gasto sob controle, a pessoa confirma | Precisa de um diretor que leia o roteiro, não só do Jev |

**Escolhida: a 3, com uma decisão antes, na criação.** O agente, que lê o roteiro inteiro, já diz o que não
existe em foto (`onde_existe`, item 1.2), e essas cenas vão para a IA já na criação. O Corrigir Mídia vira o
diretor que pega o que ainda ficou errado (Fase 4).

**Sem teto.** Cena ruim recebe imagem de IA **obrigatoriamente**, quantas forem. Não existe limite de cenas nem de
valor: o que decide é a qualidade de cada cena, com as medidas abaixo. A estimativa do custo continua aparecendo
na criação (total e por minuto), como toda etapa paga, mas ela informa, não corta cena.

**A prioridade:** a cena totalmente errada é o pior caso, e a IA é sempre melhor que ela. **Tudo o que é ruim para
o vídeo e não existe em foto certa, quem resolve é a IA.** Cena totalmente errada vai para a IA sem outra rodada de
busca grátis, porque buscar de novo quando o banco não tem a coisa só trouxe mais lixo.

**O volume:** num vídeo como o virou-filme, a IA resolveria de 90 a 120 cenas de 155, não 45.

**O cuidado:** nota baixa nem sempre é imagem ruim. O Jev comparou com o pedido ideal, e imagens boas tiraram nota
absurda (três leões sem juba com 8% e 4%, foto histórica real de operários da ferrovia com 9%). A troca por IA
acontece porque o sujeito está errado, não porque a nota ficou baixa contra um pedido impossível. Por isso o
ideal e o aceitável (1.3) e as três perguntas do Jev (2.2) vêm junto com a IA.

## O que já existe para a IA

- **Dois provedores:** Google Nano Banana (US$ 0,034 em lote, US$ 0,067 na hora) e Grok Imagine pela Kie
  (US$ 0,02). Configurados em `imagens.py` e `custos.preco_da_imagem`.
- **O agente já marca cenas como `ia`:** foram 43 no virou-filme. Com a IA desligada (`ia.ativa: false`), elas
  foram para o banco de imagens e viraram lixo.
- **O Corrigir já tem uma opção de gerar IA:** `ia=true` no `POST /corrigir-midia` gera as cenas em
  `precisam_ia` (`corrigir.regerar_com_ia`). O editor não usa essa opção.
- **Teto de 15% de IA** (`cenas.ESTILO_TETO_IA`), igual para todo canal.

O que falta não é ligar a IA: é decidir bem quais cenas vão para ela.

## Já feito (3 de outubro)

- Texto de outro alfabeto é traduzido em vez de apagado (`openrouter_local.py`).
- Tapa-buraco com filtro de verdade: o bicho pelo substantivo, nome e coisa juntos no `exato`, recusa o que o
  modelo disse que não confere, duas palavras do assunto, nunca bicho que a cena não cita, assunto do vídeo sem
  nome de pessoa (`midia.py`).
- Homônimos: o Jev sabe quem é a pessoa citada (`quem_e` no mapa).
- Cenas de época: só arquivo e Wikimedia, sempre foto, e o agente pede material de arquivo (`epoca`).
- Animação como camada por cima das cenas, presa à fala (`animacoes.py`).

---

## Fase 0: medir antes de mudar

Sem medida, toda mudança é no olho.

### 0.1 Nota do vídeo
- **O quê:** um resumo de qualidade gravado em `qualidade.json` no fim da criação, do Corrigir e do render:
  - porcentagem de cenas com nota acima de 40;
  - cenas totalmente erradas (sujeito errado);
  - imagens repetidas;
  - cenas vazias;
  - de onde veio cada imagem: escolhida, tapa-buraco ou IA;
  - tudo isso por bloco do roteiro.
- **Onde aparece:** no fim do log, no `fabrica status` e no botão Custos do editor (ou um botão Qualidade).
- **Custo:** zero. Usa as notas que o Jev já dá.

### 0.2 Três roteiros de teste fixos
- **O quê:** um roteiro de animais, um histórico (Tsavo) e um de ciência ou atualidade, sempre os mesmos. Toda
  mudança grande roda nos três e compara a nota do vídeo antes e depois.
- **Custo:** o do Jev, centavos por vídeo.

### 0.3 Testes automáticos dos filtros
- **O quê:** uma pasta `tests/` com os casos reais que já deram errado: elefante de Tsavo no acampamento, zebra
  no leão, "Patterson" trazendo ginasta, "tranca quebrada" trazendo cânion, Mustang nos restos mortais. Roda com
  `uv run pytest` em segundos e sem rede.
- **Por quê:** hoje não há teste nenhum. Uma regra corrigida pode voltar a quebrar sem ninguém perceber.

---

## Fase 1: o plano das cenas (agente de roteiro)

É o passo que mais pesa: um pedido ruim gera busca ruim, julgamento injusto e troca à toa.

### 1.1 Agente pelo Claude da assinatura
- **O quê:** o mapa e o plano das cenas passam a rodar pelo `claude -p` (assinatura do Claude Code, sem custo
  além da mensalidade). O modelo principal gratuito fica só como reserva.
- **Por quê:** o Space Bunny escreve palavras grudadas e copia descrições. E ele sai do OpenRouter em
  **5 de outubro de 2026** (veja 6.1).

### 1.2 Campo `onde_existe` em cada cena
- **O quê:** o agente diz onde a imagem existe:
  - `banco`: Pexels e Pixabay (leão, savana, laboratório);
  - `arquivo`: Wikimedia e acervos (a ponte de 1899, o retrato do Patterson);
  - `nao_existe`: momento que ninguém fotografou (o leão dentro da armadilha, Patterson na plataforma à noite).
- **Uso:** `nao_existe` vai direto para a IA (Fase 3) e nem passa pela busca.

### 1.3 O ideal e o aceitável
- **O quê:** cada cena ganha dois pedidos:
  - `mostrar`: o ideal, usado na busca e na IA (por exemplo, "dois leões sem juba entre tendas à noite");
  - `aceitavel`: o mínimo para a cena estar certa, usado pelo Jev (por exemplo, "leão sem juba").
- **Por quê:** hoje o Jev compara tudo com o ideal e dá nota 5 para uma foto boa de leão sem juba. Isso gera
  troca à toa.

### 1.4 Conferência do JSON do agente por código
Antes de aceitar a resposta do agente, o código confere e pede de novo quando acha:
- palavra grudada ou lixo ("exércitoBritish", "ferroviários_dpklsy", "presenteReality");
- o mesmo `mostrar` em cenas seguidas com falas diferentes (o "segundo leão caminhando" na cena em que a fala diz
  que o primeiro leão morreu);
- `animal` preenchido em cena que não mostra bicho (números, laboratório, diagrama);
- `exato` em português ou só com o nome do lugar quando a cena é sobre outra coisa;
- item de lista sem sentido ("Um", "o");
- armadilha de busca com um termo que não está no roteiro.

### 1.5 Armadilhas de duplo sentido
- **O quê:** o prompt do mapa passa a pedir também as palavras de duplo sentido, como "plataforma" (que virou
  estação de trem) e "tranca quebrada" (que virou o cânion Quebrada de las Conchas).

---

## Fase 2: a captura das imagens

### 2.1 Quem descreve não vê o pedido
- **O quê:** o modelo descreve a imagem sem saber o que a cena pede, e quem compara é o Jev.
- **Por quê:** vendo o pedido, ele escreveu "Lago Vitória" para uma cidade no litoral (nota 81) e "armadilha de
  madeira para leões" para uma gaiola de caranguejo.
- **Atenção:** na escolha entre candidatos, o modelo precisa do pedido para escolher. Ali a descrição continua
  junto, e a regra de não copiar nome do pedido (já feita) segura o erro.

### 2.2 O Jev com três perguntas e o contexto do bloco
- **O quê:** a pergunta única "combina?" vira três, na mesma chamada e pelo mesmo preço:
  1. a imagem mostra o sujeito certo?
  2. mostra o momento ou a ação da fala?
  3. é da época certa? (só em cena de época)
- **Também recebe:** o bloco do mapa (nome, âncora e contexto), o `exato`, o `animal` e o `aceitavel`. **Não**
  recebe o roteiro inteiro, que viraria ruído no julgamento de cada cena.
- **Decisão por código:**
  - sujeito errado: a cena está errada e troca;
  - sujeito certo mas genérico: a cena fica;
  - sujeito certo, mas a cena depende de um momento que não existe em foto: candidata a IA.

### 2.3 Nova ordem para preencher uma cena
1. Escolha normal no banco ou no arquivo, com o Jev conferindo.
2. Uma única busca nova, com os filtros rigorosos.
3. **IA, obrigatoriamente**, se o sujeito continua errado ou se a cena não existe em foto.
4. Se a IA falhar (provedor fora do ar, sem saldo), a fábrica tenta de novo e, se não der, a cena fica marcada para
   revisão. Nunca com imagem de outra coisa.

As últimas camadas do tapa-buraco ("assunto do vídeo" e "imagem nova pelo assunto"), que trouxeram o lixo, saem.
O tapa-buraco só fica para a primeira camada (um candidato da própria cena que passa nos filtros e no Jev).

### 2.4 Vídeo de banco só onde faz sentido
- **O quê:** a regra de 80% de vídeo nos 3 primeiros minutos (`_balancear_foto_e_video`) só transforma em vídeo
  as cenas de `banco` (bicho, paisagem, coisa de hoje).
- **Por quê:** ela transformou em vídeo cenas de 1898 e de pessoas específicas, e vídeo de banco é sempre atual e
  genérico. Cena de época já está protegida; falta proteger as de `nao_existe` e as de pessoa real.

### 2.5 Arquivo histórico mais fundo
- **O quê:** em cena de época, a busca também percorre as categorias da Wikimedia do assunto (por exemplo,
  "The Man-eaters of Tsavo", com as fotos do livro de 1907), não só a busca por palavra.
- **Por quê:** o livro de 1907 tem fotos em domínio público do acampamento, da ponte, da armadilha e dos leões
  mortos. A fábrica achou só uma.

---

## Fase 3: imagem de IA

### 3.1 IA obrigatória para cena ruim, sem teto
- **O quê:** toda cena que as medidas apontam como ruim recebe imagem de IA, na criação e no Corrigir. Não existe
  limite de cenas nem de valor.
- **As medidas que decidem se a cena é ruim** (para a IA não trocar uma foto real boa):
  - o Jev julga contra o **aceitável**, não contra o ideal (1.3);
  - o Jev responde **três perguntas**: sujeito certo, momento certo, época certa (2.2). Sujeito errado é ruim;
    sujeito certo num momento genérico fica;
  - o agente marcou a cena como `nao_existe` (1.2);
  - no Corrigir, o diretor com o roteiro inteiro confirma (4.1).
- **As medidas que a imagem de IA precisa passar** (3.3 e 3.4): pessoa real sem rosto, estilo da época, o Jev
  confere a imagem gerada e ela é refeita se vier errada.
- **O custo aparece, mas não corta:** a criação mostra a estimativa total e por minuto, como toda etapa paga.
- **Referência no virou-filme (8,5 min):**

  | Imagens de IA | Kie (US$ 0,02) | Google em lote (US$ 0,034) |
  |---|---|---|
  | 86 | US$ 1,72 (US$ 0,20/min) | US$ 2,92 (US$ 0,35/min) |
  | 120 | US$ 2,40 (US$ 0,28/min) | US$ 4,08 (US$ 0,48/min) |

### 3.2 Fim do teto de 15%
- **O quê:** o teto de IA (`cenas.ESTILO_TETO_IA`, 15%) sai do código, e com ele a regra do agente de "no máximo
  15% de IA" (`SECAO_MIDIA`).
- **Por quê:** 15% são 23 cenas de 155. No virou-filme, isso deixaria mais de 60 cenas erradas no vídeo.

### 3.3 O prompt de IA a partir do roteiro
- **O quê:** o prompt é montado com o `mostrar` (o ideal), o bloco, a época e o `estilo_ia` do mapa.
- **Regras fixas:**
  - pessoa real só de costas, de longe ou as mãos (o código já tira o nome do prompt);
  - nunca IA no lugar do que existe em foto (o Field Museum, a foto real do Patterson com o leão);
  - bicho na IA só quando a cena pede uma ação que não existe em foto (o leão dentro da armadilha, o leão
    rodeando a plataforma). Leão comum, búfalo e zebra vêm do banco. Bicho raro na IA pode sair com a espécie
    errada, e o Jev confere (3.4);
  - cena de época no estilo de foto antiga (sépia, granulada), para combinar com o material de arquivo.

### 3.4 O Jev confere a imagem de IA
- **O quê:** a imagem gerada passa pela mesma conferência. Se o sujeito vier errado (espécie trocada, pessoa de
  frente), gera de novo uma vez com o motivo no prompt.

### 3.5 Provedor e tempo
- **O quê:** dentro da criação, IA na hora (Kie ou Google direto). O modo lote do Google (metade do preço, pode
  levar horas) fica para quando a pessoa não tem pressa.

---

## Fase 4: Corrigir Mídia como diretor

### 4.1 Revisão com o roteiro inteiro
- **O quê:** a primeira ação do botão. Um modelo forte (o Claude da assinatura) recebe o roteiro completo, o mapa
  e, de cada cena: a fala, o pedido, o que a imagem mostra, as notas do Jev, de onde a imagem veio e o resultado
  da revisão do vídeo pronto.
- **Ele decide, por cena:** **fica**, **IA** (com o prompt), **arquivo de época** (com a busca) ou **busca
  nova**. Cena totalmente errada vai para a IA, sem outra rodada de busca grátis.

### 4.2 Lista para confirmar
- **O quê:** o editor mostra a lista com o motivo de cada troca e o custo total e por minuto. A pessoa desmarca o
  que quiser e confirma.
- **Atenção:** precisa mudar o frontend (`G:\editor-video-dark`). Enviar ao GitHub publica o site para todos.

### 4.3 Nunca piorar
- **O quê:** toda imagem trocada é julgada de novo. Se a nota piorar, a anterior volta.
- **Por quê:** hoje as trocas da última etapa (`_tirar_outra_coisa`) não são julgadas, e foi assim que sobraram
  77 imagens sem conferência no virou-filme.

### 4.4 A revisão do vídeo pronto alimenta o Corrigir
- **O quê:** o `revisar-video` (grátis) já olha o MP4 final e aponta tela preta, imagem que não combina e texto
  cortado. Hoje ele só aponta. Os apontamentos dele entram na lista do 4.1.

---

## Fase 5: o editor

### 5.1 Origem e motivo de cada cena
- **O quê:** um selo em cada cena (escolhida, tapa-buraco, IA ou arquivo) e a nota, com o motivo da reprovação.
- **Atenção:** precisa do frontend.

### 5.2 Botão "gerar com IA" na cena
- **O quê:** no inspetor, com o custo da imagem e o prompt editável.

### 5.3 Aprendizados do canal
- **O quê:** quando a pessoa troca uma imagem por IA, ou aceita a troca do diretor, isso vira exemplo para o
  agente dos próximos vídeos do mesmo canal (já funciona com a busca digitada e a imagem subida).

---

## Fase 6: robustez

### 6.1 Modelo principal (URGENTE)
- **O quê:** o Space Bunny sai do OpenRouter em **5 de outubro de 2026**. Sobra o Qwen gratuito, que tem 1.000
  chamadas por dia, e um vídeo usa de 1.200 a 2.300.
- **Fazer:** escolher e testar o próximo modelo da cadeia antes disso, ou levar o agente para o Claude da
  assinatura (1.1). O "pedido por imagem" também precisa caber no limite.

### 6.2 Modo offline no Windows
- **O quê:** o modo offline usa a voz do Mac (comando `say`) e não roda no Windows. Usar a voz do próprio Windows
  ou o Edge-TTS gratuito.
- **Por quê:** é o teste sem custo que o CLAUDE.md manda rodar antes de qualquer gasto, e hoje ele não roda aqui.

### 6.3 Repositório dos amigos
- **O quê:** o repositório `zhekbr/backend-editor` está muito atrás do `zhek00/backend-editor` (o último commit
  lá é a troca para a GenAIPro). Decidir qual é o oficial e manter os dois iguais, ou apagar o remoto que não é
  usado.

### 6.4 Camada de animação em produção
- **O quê:** rodar `fabrica animacoes` num projeto real pelo editor, conferir a prévia de cada cena e o tempo do
  render com 30 ou mais animações por cima.

---

## Ordem sugerida

| # | Item | Por quê agora | Custo para fazer |
|---|---|---|---|
| 1 | 6.1 Modelo principal | O Space Bunny sai do ar em 2 dias | Teste com modelo gratuito |
| 2 | 0.1 a 0.3 Medir | Sem isso não dá para saber se o resto melhora | Zero |
| 3 | 1.1 e 1.4 Agente forte e conferência do JSON | Corta o erro na origem | Zero (assinatura) |
| 4 | 2.3, 3.1, 3.2 e 3.3 IA obrigatória na cena ruim, sem teto | Acaba com as cenas totalmente erradas | De US$ 1 a 4 por vídeo de 8 min |
| 5 | 4.3 Nunca piorar | O Corrigir hoje pode piorar o vídeo | Zero |
| 4b | 1.3 e 2.2 aceitável e três perguntas, junto com o 4 | Sem isso a IA troca também imagens reais boas | Zero |
| 6 | 1.2 `onde_existe` | A IA entra já na criação, sem passar pela busca | Zero |
| 7 | 4.1 e 4.2 Corrigir como diretor | A sua hipótese 3 | Precisa do frontend |
| 8 | 2.1, 2.4 e 2.5 | Ajustes finos da captura | Zero |
| 9 | Fase 5 e o restante da Fase 6 | Conforto e manutenção | Frontend em parte |

Toda etapa que gasta dinheiro mostra a estimativa (total e por minuto) e pede confirmação antes.
