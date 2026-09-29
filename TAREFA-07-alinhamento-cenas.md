# TAREFA 7 — Corrigir desalinhamento entre roteiro e cenas (texto na tela e busca)

Você é o agente executor (Antigravity, Gemini 3.8 Flash HIGH). Bug real reportado pelo dono do projeto num vídeo de verdade: `E:\fabrica-para-amigo\projetos\aas-8-piores-picadas-de-insetos-do-mundo-em-ordem-de-perigo`. Na Cena 4 (10.8s-14.5s), a narração fala de aranhas ("lista. Aranhas estão nessa lista...") mas a imagem mostrada é um escorpião (busca: "scorpion sand night") e o texto animado na tela mostra "Cobras estão nessa lista" — nada bate com o que está sendo narrado naquele momento.

## Regra desta tarefa

**Não invente mecanismo novo.** A correção deve reaproveitar as funções que já existem em `fabrica/cenas.py` (`_texto_tela`, `_efeito`, `_extrair_texto_palavras`) — o problema é a ORDEM em que elas rodam em relação ao ajuste de duração, não a lógica em si.

## Causa raiz confirmada

Em `fabrica/cenas.py`, dentro de `planejar()` (por volta da linha 383-450):

1. As cenas são montadas com `texto_tela` e `efeito` já calculados via `_texto_tela(...)` / `_efeito(...)`, usando o `ini` de cada cena **naquele momento do pipeline**. O campo `texto_tela["inicio"]` guarda o horário **relativo ao início da própria cena** (confira o docstring de `_texto_tela`, linha ~517: "Converte o momento do texto em segundos desde o começo da cena").
2. Só depois disso rodam `_balancear_proporcao_90_10(cenas, log)` e `_garantir_limites_estritos(cenas, ...)` (linhas ~448-451).
3. Dentro de `_garantir_limites_estritos`, o **Passo 1** ("Garantir ini e fim contínuos", linhas 251-253) reescreve o `ini`/`fim` de **todas** as cenas em cadeia. Os Passos 2-4 (dividir cenas longas, fundir cenas curtas) também mudam fronteiras.
4. Quando uma cena divide (Passo 2, `k > 0`) ou é subdividida no Passo 4, o código já zera `texto_tela` e `efeito` corretamente (linhas 274-275 e 352-353) — isso está certo.
5. **Mas quando cenas são fundidas** (Passo 3, Casos A/B/C, linhas 291-334), o `texto_tela`/`efeito` da cena sobrevivente **não é revisado nem zerado** — fica com o valor antigo, calculado pra uma janela de tempo que não existe mais.
6. E o Passo 1, que roda pra **toda** cena mesmo sem fusão nenhuma, já é suficiente pra deslocar o `ini` de cenas mais adiante na lista (efeito cascata de qualquer ajuste anterior), tornando o `texto_tela.inicio` (relativo) desalinhado mesmo em cenas que não foram fundidas nem divididas diretamente.

Isso explica o texto errado na tela. Para o **termo de busca errado** (escorpião numa cena de aranha), investigue se o mesmo padrão se aplica: quando uma cena funde com a vizinha (Passo 3), ela herda o `busca`/`prompt` da cena que sobrou (`fatiadas[i-1]` ou `fatiadas[i+1]`), decidido pelo Claude pra um texto mais curto — mas o `texto` da cena final é maior (concatenado). Confirme se isso é a causa do mesmo tipo de desalinhamento, ou se há um bug diferente (ex.: índice trocado) — reproduza com o projeto real citado acima antes de decidir.

## O que corrigir

1. **`texto_tela` e `efeito` depois de fusões (Passo 3):** quando duas cenas se fundem em qualquer um dos Casos A/B/C, zere `texto_tela` e `efeito` da cena resultante, do mesmo jeito que já é feito nas divisões (`fatia["texto_tela"] = None` / `fatia["efeito"] = None`). Não tente recalcular o conteúdo do zero (isso exigiria uma nova decisão do Claude, fora do escopo) — só evite mostrar algo que não bate mais.

2. **Deriva do Passo 1 em cenas não tocadas:** depois que `_garantir_limites_estritos` termina de fixar `ini`/`fim` finais de cada cena (final do Passo 6, "Renumerar e garantir sincronia total"), adicione uma validação: para cada cena com `texto_tela`, confira se `texto_tela["inicio"]` (que é relativo ao início da cena) ainda é menor que a duração final da cena (`fim - ini`). Se não for (ou se a diferença entre o `ini` da cena nesse ponto e o `ini` que ela tinha quando o `texto_tela` foi calculado for grande — decida o critério mais simples e seguro), zere o `texto_tela`. Mesma lógica pro `efeito["inicio"]`.

3. **Busca/prompt desalinhados por fusão:** se a investigação do item da causa raiz confirmar que fusões deixam `busca`/`prompt` descrevendo só uma fração do texto final da cena, decida com uma correção mínima e consistente — por exemplo, preferir sempre o `busca`/`prompt` da fatia com o texto mais longo/mais recente na fusão, já que é isso que domina o que está sendo narrado naquele trecho. Não invente um novo critério complexo — escolha o mais simples que resolva o caso real observado.

## Testar (sem gastar dinheiro além do necessário)

1. Rode `uv run fabrica cenas aas-8-piores-picadas-de-insetos-do-mundo-em-ordem-de-perigo --forcar` (esse projeto já tem `alinhamento.json` pronto, então recalcular cenas não deveria precisar narrar de novo nem buscar mídia de novo — confirme isso antes de rodar, pra não gastar à toa).
2. Depois de gerado o novo `cenas.json`, escreva um script simples (só leitura, sem chamar nada pago) que, pra cada cena com `texto_tela` preenchido, confira se o texto do `texto_tela` faz sentido perto do `texto` da própria cena (mesmo que seja uma checagem manual/visual sua lendo umas 15-20 cenas espalhadas pelo vídeo, não precisa ser automático).
3. Confirme especificamente a Cena 4 (ou a cena equivalente depois do recálculo): a imagem/busca e o texto na tela devem bater com a narração "aranhas", não mais "escorpião"/"cobras".

## O que preciso receber de volta

1. Diff de `fabrica/cenas.py` com as mudanças.
2. Confirmação da causa raiz do problema de busca/prompt (é a mesma deriva ou é outra coisa?).
3. Resultado da checagem manual de várias cenas depois do recálculo — quantas bateram, quantas não.
4. Confirmação de que o recálculo não disparou nenhuma chamada paga desnecessária (narração e mídia já existentes não deveriam ser refeitas).

Não mexa em mais nada de `cenas.py` além do que está descrito aqui.
