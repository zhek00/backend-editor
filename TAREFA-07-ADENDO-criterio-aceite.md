# ADENDO à TAREFA 7 — critério de aceite mais rígido

Isto complementa `TAREFA-07-alinhamento-cenas.md`. Não é uma tarefa nova — é o mesmo bug, com um critério de teste mais exigente antes de considerar resolvido.

## O padrão exigido, em uma frase

Cada cena mostra o que a narração está dizendo NAQUELE momento. Se a narração fala "rato", a cena daquele trecho é obrigatoriamente sobre rato — não sobre outro bicho, não uma cena genérica. Se fala "pirâmide", é pirâmide. Isso já é o objetivo do prompt que o Claude recebe em `SISTEMA` (`fabrica/cenas.py`) — o pipeline de ajuste de 3-5s é que está descumprindo essa decisão depois dela já ter sido tomada certa.

## Exemplo real que falhou, além da Cena 4

No mesmo projeto (`aas-8-piores-picadas-de-insetos-do-mundo-em-ordem-de-perigo`), o roteiro passa por pelo menos três bichos em sequência — cobra, aranha e escorpião — mas no vídeo final só o escorpião apareceu representado corretamente. Os trechos sobre cobra e aranha não tiveram nenhuma cena congruente.

## Critério de aceite (além do que já está na Tarefa 7)

Depois de aplicar a correção e recalcular as cenas desse projeto:

1. Localize no `roteiro.txt` todos os pontos em que um bicho específico é citado pelo nome (cobra, aranha, escorpião, e qualquer outro que apareça na lista do vídeo).
2. Para cada citação, confira a cena correspondente em `cenas.json` (pelo intervalo de tempo/frase) e confirme que o `busca` (se for foto/vídeo real) ou o `prompt` (se for IA) menciona esse mesmo bicho — não um bicho diferente, não algo genérico tipo "insect danger".
3. Reporte uma lista simples: bicho citado → cena correspondente → busca/prompt daquela cena → bateu ou não bateu.

Se depois da correção da Tarefa 7 ainda sobrar alguma citação sem cena congruente, não invente uma segunda camada de correção sozinho — pare e me reporte qual caso específico ainda falha, com o trecho do roteiro e o que a cena mostrou, pra eu decidir o próximo passo.
