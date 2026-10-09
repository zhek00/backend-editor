---
description: Produz um vídeo narrado com a fábrica TipLabs, do roteiro ao MP4
argument-hint: <roteiro.txt ou o texto do roteiro>
model: haiku
---
Produza um vídeo com a fábrica TipLabs (MCP fabrica). O usuário só mandou o roteiro e quer receber o vídeo:
não mostre a ele ferramentas nem detalhes técnicos, e não pergunte nada. A fábrica faz o vídeo inteiro sozinha.
Roteiro: $ARGUMENTS
(o caminho de um arquivo de texto ou o próprio texto do roteiro; se vier vazio, peça só o roteiro ao usuário)

1. Se o roteiro acima for o caminho de um arquivo, leia o arquivo; senão ele é o próprio texto. Chame
   criar_video(roteiro=<o texto>) e guarde o NOME que ele devolve. Se o mesmo roteiro já estava em produção, ele
   devolve o mesmo nome e o vídeo continua de onde parou.
2. Diga ao usuário só: "Seu vídeo está sendo produzido. Vou mostrando o andamento aqui."
3. Repita acompanhar(nome, ultima=<a última porcentagem que você mostrou, ou -1 na primeira vez>):
   - "SEM MUDANÇA": chame de novo, sem escrever nada.
   - Uma linha de andamento ("Escolhendo as imagens · 45% (etapa 4 de 7) · 6min12s"): mostre ao usuário exatamente
     essa linha, sozinha, sem comentário, e chame de novo com a porcentagem nova.
   - "PRONTO · 100% · <tempo>": guarde o tempo e siga para o passo 4.
   - "PAUSADO · ..." ou "PAROU · ...": mostre a frase ao usuário, diga que basta mandar o mesmo roteiro de novo com
     /tiplabs para continuar, e pare.
4. Chame entregar_video(nome), baixe o vídeo e o pacote do projeto para a pasta atual (curl -L -o ARQUIVO LINK) e diga
   ao usuário, em uma ou duas linhas, que o vídeo está pronto, em quanto tempo foi produzido e onde ficou o arquivo.
