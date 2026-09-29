# TAREFA 3 — Corrigir as 3 chamadas quebradas que a Tarefa 2 deixou pendentes

Análise da minha parte sobre o relatório da Tarefa 2: o arquivo `cenas.py` foi portado certinho e o teste offline provou que o estilo fixo (90% real / 10% IA, cortes de 3–5s) funciona. Mas o agente achou 3 chamadas em `cenas.py` que dependem de `claude_local.usa_gemini`, `claude_local.groq_disponivel` e `claude_local._perguntar_groq` — funções que só existem na pasta legada `G:\fabrica-de videos`, não em `E:\fabrica-para-amigo`.

**Decisão: NÃO portar essas 3 funções para `claude_local.py`.** Motivo: `E:\fabrica-para-amigo\CLAUDE.md` já deixa explícito que a fábrica usa só Claude Code pela assinatura (`claude -p`) para dividir cenas — nada de Gemini ou Groq nessa etapa, e Groq nem está na lista de chaves obrigatórias do projeto. Portar essas funções abriria um provedor pago novo que este sistema nunca teve. Isso contraria "sistema limpo e leve" e o "tudo que não for para esse sistema jamais deve existir".

Em vez disso, os 3 pontos em `cenas.py` viram parte simplificada do próprio arquivo — que já é a exceção autorizada — sem tocar em `claude_local.py`.

## O que fazer, exatamente

Abra `E:\fabrica-para-amigo\fabrica\cenas.py` e faça estas três mudanças, nada além delas:

### 1. Remover a segunda passada opcional pela Groq

Por volta da linha 489-490:
```python
    if not projeto.offline and claude_local.groq_disponivel():
        _refinar_com_groq(projeto, cenas, log)
```
Apague essas duas linhas (a chamada inteira). A fábrica já garante a proporção 90/10 e os cortes de 3-5s nas duas linhas logo acima (`_balancear_proporcao_90_10` e `_garantir_limites_estritos`); essa segunda passada era só um refino extra usando Groq, que este sistema não vai ter.

### 2. Remover a função e os dados que ficaram sem uso

Como a única chamada a `_refinar_com_groq` foi removida no passo 1, apague também:
- a função inteira `_refinar_com_groq` (linha ~496 em diante, até o `return`/fim da função — confira onde ela termina antes de apagar);
- a constante `ESQUEMA_REFINO` (linha ~128) e a constante `INSTRUCOES_REFINO` (linha ~147), **se e somente se** nada mais no arquivo as usar (confirme com uma busca por `ESQUEMA_REFINO` e `INSTRUCOES_REFINO` depois de remover a função — se não sobrar nenhuma outra referência, pode apagar as duas constantes).

### 3. Trocar o nome do provedor no log

Por volta da linha 688:
```python
    nome_provedor = "Gemini" if claude_local.usa_gemini(projeto) else "Claude"
```
Troque por:
```python
    nome_provedor = "Claude"
```
(a fábrica só usa Claude Code nessa etapa, não tem mais decisão de provedor aqui).

## Depois de editar, confirme que não sobrou nenhuma chamada quebrada

Rode:
```
grep -n "usa_gemini\|groq_disponivel\|_perguntar_groq" fabrica/cenas.py
```
Isso não pode devolver nenhuma linha. Se devolver, ainda falta algum ponto.

## Testar de novo

Repita o teste da Tarefa 2 (mesmo projeto `teste-estilo` ou um novo) com `uv run fabrica cenas <nome>` e confirme que roda sem erro e sem depender de mais nada da pasta legada.

## O que preciso receber de volta

1. Diff de `cenas.py` mostrando só essas remoções/trocas (nada de `claude_local.py` tocado).
2. Saída do grep do passo acima (deve vir vazia).
3. Confirmação de que o teste rodou sem erro.

Sobre os perfis sem `midia_real` (`apresentacao.yaml`, `meditacao.yaml`, `vo-cida.yaml`) que o relatório da Tarefa 2 levantou: já conferi o `midia.py` e o padrão dele quando o perfil não configura fontes é `["pexels", "pixabay"]` para vídeo e `["wikimedia", "pexels", "pixabay"]` para foto — exatamente igual ao que todo perfil configurado já usa. Não precisa mexer em nenhum perfil, o padrão já está certo. O impacto visual em `meditacao.yaml` e `vo-cida.yaml` (passarem a ter 90% de material real) é o comportamento pretendido: o estilo fixo vale para todo canal, por decisão explícita do dono do projeto.
