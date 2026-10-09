---
description: Produz um vídeo narrado com a fábrica TipLabs, do roteiro ao MP4
argument-hint: <roteiro.txt ou o texto do roteiro>
model: sonnet
---
Produza um vídeo com a fábrica TipLabs (MCP fabrica). O usuário só mandou o roteiro e quer receber o vídeo:
não mostre a ele ferramentas, tarefas nem detalhes técnicos, e não pergunte nada.
Roteiro: $ARGUMENTS
(o caminho de um arquivo de texto ou o próprio texto do roteiro; se vier vazio, peça só o roteiro ao usuário)

1. Se o roteiro acima for o caminho de um arquivo, leia o arquivo; senão ele é o próprio texto. Chame
   criar_video(roteiro=<o texto>) e guarde o NOME que ele devolve. Se o mesmo roteiro já estava em produção, ele
   devolve o mesmo nome e o vídeo continua de onde parou.
2. Diga ao usuário só: "Seu vídeo está sendo produzido. Vou mostrando o andamento aqui."
3. Lance UM subagente com a ferramenta Agent (subagent_type "general-purpose", model "sonnet",
   run_in_background true, description "Produzindo o vídeo") com o texto OPERADOR abaixo, trocando o nome. Não
   responda tarefa nesta conversa e não chame esperar, andamento nem proximas_tarefas aqui: o operador faz tudo.
4. Enquanto o operador trabalha, repita acompanhar(nome, ultima=<a última porcentagem que você mostrou, ou -1 na
   primeira vez>):
   - "SEM MUDANÇA": chame de novo, sem escrever nada.
   - Uma linha de andamento ("Escolhendo as imagens · 45% (etapa 4 de 7) · 6min12s"): mostre ao usuário exatamente essa linha,
     sozinha, sem comentário, e chame de novo com a porcentagem nova.
   - "PRONTO · 100% · <tempo>": guarde o tempo e siga para o passo 5.
   - "PAUSADO · ..." ou "PAROU · ...": mostre a frase ao usuário e pare.
5. Quando estiver pronto (o acompanhar disse PRONTO ou o operador terminou com "pronto"): chame entregar_video(nome),
   baixe o vídeo e o pacote do projeto para a pasta atual (curl -L -o ARQUIVO LINK) e diga ao usuário, em uma ou duas
   linhas, que o vídeo está pronto, em quanto tempo foi produzido e onde ficou o arquivo. Se o operador terminar com "erro" ou "cancelado": diga,
   numa linha, que a produção parou e que basta mandar o mesmo roteiro de novo com /tiplabs para continuar.

OPERADOR:
Você é o operador da fábrica de vídeos TipLabs (ferramentas do MCP fabrica) no vídeo <o nome que o criar_video devolveu>. Trabalhe em
silêncio até o vídeo ficar pronto: não escreva nada para o usuário no caminho.

Repita:
1. esperar(nome="<o nome que o criar_video devolveu>"). Ele devolve uma linha:
   - "trabalhando" ou "tarefas já entregues": chame esperar de novo.
   - "tarefas: ...": chame proximas_tarefas(nome="<o nome que o criar_video devolveu>", limite=3, instrucoes_que_ja_tenho="<as marcas das
     instruções que você já recebeu, separadas por vírgula>") e responda cada tarefa com responder(tarefa_id,
     resposta_json): um JSON só com as chaves do esquema dela, seguindo as instruções à risca. Se for recusada,
     corrija e responda de novo. Decida direto: as instruções já dizem como julgar, não delibere longamente nem reveja
     a resposta. Depois volte ao passo 1.
   - "pronto", "erro ..." ou "cancelado": pare.
2. No fim, devolva uma linha só: a última linha do esperar ("pronto", "erro ..." ou "cancelado").
