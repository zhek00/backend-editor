---
description: Produz um vídeo narrado com a fábrica TipLabs, do roteiro ao MP4
argument-hint: <roteiro.txt> <nome-do-video> [perfil]
model: sonnet
---
Produza um vídeo com a fábrica TipLabs (MCP fabrica).
Argumentos: $ARGUMENTS
O primeiro é o roteiro (o caminho de um arquivo ou o próprio texto), o segundo o nome do vídeo (letras minúsculas, números e hífen) e o terceiro, opcional, o perfil do canal (padrão: documentario). Se faltar o roteiro ou o nome, pergunte ao usuário.

1. Se o roteiro acima for o caminho de um arquivo, leia o arquivo; senão ele é o próprio texto. Chame criar_video(nome,
   roteiro=<o texto>, perfil) sem confirmar e mostre a estimativa ao usuário. Siga só se ele concordar, com
   criar_video(nome, roteiro="", confirmar=true). Se o nome já estiver em produção, pule para o passo 2.
2. Ciclo até o vídeo sair. Chame esperar(nome); ele devolve uma linha:
   - "trabalhando" ou "tarefas já entregues": chame esperar de novo.
   - "tarefas: roteiro N, visual M": para cada grupo com tarefas, lance um subagente com a ferramenta Agent
     (subagent_type "general-purpose", run_in_background false): o de roteiro com model "opus", o visual com model
     "sonnet". Se os dois grupos tiverem tarefas, lance os dois na mesma mensagem. O prompt de cada subagente é o texto
     AJUDANTE abaixo, com o tipo ("roteiro" ou "visual") no lugar indicado. Quando voltarem, chame esperar de novo.
   - "pronto": chame entregar_video(nome). Ele devolve o link do vídeo e o do pacote do projeto: baixe os dois para a
     pasta atual (curl -L -o ARQUIVO LINK) e diga ao usuário onde ficaram.
   - "erro ..." ou "cancelado": mostre ao usuário e pare.
   Nunca responda tarefa nesta conversa, só nos subagentes: assim as imagens não se acumulam aqui e o vídeo gasta o
   mínimo da assinatura. Não chame andamento nem proximas_tarefas aqui. Durante o ciclo, no máximo uma linha ao
   usuário por subagente que voltar.

AJUDANTE:
Você responde tarefas da fábrica de vídeos (ferramentas do MCP fabrica) do projeto <nome do vídeo>, só do tipo <roteiro ou visual>.
Repita até 5 vezes: proximas_tarefas(nome="<nome do vídeo>", tipo="<roteiro ou visual>", limite=2, instrucoes_que_ja_tenho="<as marcas das
instruções que você já recebeu, separadas por vírgula>"). Se vier "Nenhuma tarefa", pare. Para cada tarefa, siga as
instruções e o esquema dela à risca e chame responder(tarefa_id, resposta_json) com um JSON só com as chaves do esquema;
se for recusada, corrija e responda de novo. Olhe cada imagem com atenção: o sujeito que a narração cita tem que ser
exatamente aquele, nunca outra coisa parecida. Decida direto: as instruções de cada tarefa já dizem como julgar, então
não delibere longamente nem reveja a resposta antes de mandar. Não escreva arquivos nem explique nada ao usuário. No
fim, devolva uma linha só: quantas tarefas respondeu e de quais etapas.
