# TAREFA 2 — Fixar o estilo de cena em 90% acervo real / 10% IA, cortes de 3 a 5s

Você é o agente executor (Antigravity, Gemini 3.8 Flash HIGH). Esta tarefa é independente da Tarefa 1 (conexão HTTP) e pode ser feita antes, depois ou em paralelo.

## Contexto

O dono do projeto já tinha resolvido esse problema antes, numa pasta legada: `G:\fabrica-de videos\fabrica\cenas.py`. Lá existe um bloco de constantes que fixa o estilo de vídeo, independente do perfil do canal:

```python
ESTILO_ALVO_SEGUNDOS = 4.0
ESTILO_MINIMO_SEGUNDOS = 3.0
ESTILO_MAXIMO_SEGUNDOS = 5.0
ESTILO_PROPORCAO_REAL = 0.9
```

Mais uma função `_garantir_limites_estritos` que divide cenas longas e funde/rebalanceia cenas curtas para garantir que TODA cena fique entre 3 e 5 segundos, e um prompt de sistema mais rígido para o Claude ("REGRA ABSOLUTA DE DURAÇÃO"). O arquivo `E:\fabrica-para-amigo\fabrica\cenas.py` (versão atual, mais simples) ainda deixa isso configurável por perfil — e a maioria dos perfis nem configura `midia_real`, então cai tudo em IA, sem material real. É provavelmente a causa das cenas ruins/fora de contexto.

## Regra absoluta desta tarefa

- Esta é a ÚNICA outra exceção autorizada à estrutura de `E:\fabrica-para-amigo`, além da Tarefa 1. Não aproveite para portar mais nada de `G:\fabrica-de videos` além do que está descrito aqui.
- Nunca copie `.env`, logs, projetos, roteiros ou qualquer outro arquivo de `G:\fabrica-de videos`.

## Passo a passo

### 1. Substituir o arquivo

Troque `E:\fabrica-para-amigo\fabrica\cenas.py` (539 linhas) pelo conteúdo de `G:\fabrica-de videos\fabrica\cenas.py` (901 linhas) — é uma substituição completa do arquivo, não um merge manual de trechos.

### 2. Validar as dependências antes de finalizar

O `cenas.py` novo importa `claude_local`, `efeitos`, `textos` e `texto` (como `tx`) — esses quatro arquivos são DIFERENTES entre as duas pastas (já conferido, não são idênticos). Antes de dar a tarefa por concluída:

- Liste toda função/atributo que `cenas.py` novo chama desses quatro módulos (ex.: `claude_local.resumo_uso`, `efeitos.algumacoisa`, `textos.algumacoisa`, `tx.normalizar`, etc.).
- Confira se cada uma existe com a mesma assinatura na versão desses módulos que já está em `E:\fabrica-para-amigo\fabrica\`.
- Se existir uma função faltando ou com assinatura diferente, **não edite esses quatro módulos**. Em vez disso, pare e me reporte exatamente qual função falta e o que `cenas.py` esperava dela — eu decido se essa função também entra como exceção ou se ajustamos só a chamada dentro do `cenas.py`.

### 3. Perfis

Não precisa editar nenhum arquivo em `perfis/`. Já confirmei que `midia.py` em `E:\fabrica-para-amigo` já lida bem com perfil sem bloco `midia_real:` (usa fontes padrão). Só não esqueça de registrar, para eu revisar depois: os perfis atuais (`apresentacao.yaml`, `meditacao.yaml`, `vo-cida.yaml`) não têm `midia_real:` configurado, e com essa mudança eles passam a buscar 90% de material real mesmo assim, usando as fontes padrão do `midia.py`. Se isso não for o esperado para algum desses perfis, me avise em vez de decidir sozinho.

### 4. Testar sem gastar

Use um roteiro de exemplo em `E:\fabrica-para-amigo\exemplos\` com `--offline`:

```
uv run fabrica novo teste-estilo --roteiro exemplos/roteiro-teste.txt --perfil perfis/livro-de-enoque.yaml --offline
uv run fabrica cenas teste-estilo
```

Depois abra `projetos/teste-estilo/cenas.json` e confirme:
- Nenhuma cena com duração fora de 3.0–5.0s.
- A proporção de cenas `foto_real`/`video_real` está próxima de 90% (modo offline pode não respeitar isso perfeitamente já que não chama o Claude de verdade — se for o caso, rode `uv run fabrica cenas teste-estilo --forcar` sem `--offline` só se eu autorizar o gasto; senão, apenas confirme que o código dos limites de duração (`_garantir_limites_estritos`) funciona lendo o `cenas.json` gerado).

## O que preciso receber de volta

1. Confirmação de que `cenas.py` foi substituído por completo (diff mostrando que o arquivo novo bate com o de `G:\fabrica-de videos`).
2. Resultado da checagem do passo 2 — qual função de `claude_local`, `efeitos`, `textos` ou `texto` (se alguma) não bateu, ou confirmação de que todas bateram.
3. Resultado do teste do passo 4 — duração mínima/máxima observada nas cenas geradas.
4. Se algum perfil precisa de ajuste em `midia_real` por causa da mudança, a lista de quais e por quê — sem aplicar a mudança, só reportando.

Não apague nem modifique nada em `G:\fabrica-de videos`.
