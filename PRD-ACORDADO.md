# Documento de Requisitos do Produto (PRD)
## Fábrica sempre acordada: o computador não dorme no meio de um vídeo

Data: 2026-10-13. Situação: implementado, falta reiniciar o servidor para valer.

---

### 1. Problema

Na madrugada de 12 para 13/10/2026, dois vídeos criados pelo editor ficaram parados por quase 10 horas, sem nenhum
erro na tela nem no log:

- `10-marcas-de-caf-en-colombia-que-debes-evitar-y-5-que-s-son-caf-de-verdad` (começou às 00:42)
- `16-canned-foods-you-won-t-be-able-to-find-in-the-uk-after-november-1st-2026` (começou às 00:46)

A última atividade dos dois foi por volta das 01:52. Os dois voltaram juntos às 11:43, sozinhos, de onde tinham
parado.

### 2. Causa (investigada e confirmada)

O registro de eventos do Windows mostra:

| Hora | Evento | O que significa |
|---|---|---|
| 13/10 01:56:46 | Kernel-Power 42, motivo "System Idle" | o Windows entrou em suspensão por falta de uso |
| 13/10 11:43:28 | Power-Troubleshooter 1 | o computador acordou |

Com o computador dormindo, o processador para e nenhum programa roda. A fábrica não falhou: ela foi congelada e,
quando o computador acordou, seguiu do mesmo ponto, sem pagar nada de novo. O que se perdeu foi tempo.

O que foi descartado na investigação:
- não havia erro (`erro` vazio no `criacao.json`);
- não esperava confirmação de pagamento (`precisa_voce: false`, sem `aguardando_ate`);
- o servidor (processo de 12/10 22:07) ficou no ar o tempo todo;
- a cota cheia do Groq e o limite do Gemini apareciam nos logs, mas a cadeia já seguia para o próximo modelo.

### 3. Alternativas consideradas

| Opção | Resultado |
|---|---|
| Trabalhar com o computador dormindo | impossível: na suspensão nenhum programa roda |
| Desligar a suspensão do Windows ("Nunca" quando conectado) | funciona, mas o computador nunca mais dorme, e é uma configuração que a própria pessoa precisa mudar |
| Rodar a fábrica num servidor alugado, sempre ligado | funciona com o computador desligado, mas tem custo mensal e dá trabalho para montar |
| **A fábrica impede o sono só enquanto trabalha** | **escolhida pelo usuário** |

### 4. Requisitos

1. Enquanto houver vídeo em produção, o computador não pode entrar em suspensão por falta de uso.
2. A tela pode apagar normalmente: só o sono do sistema fica segurado.
3. Sem trabalho, o computador volta a dormir como antes, sem a pessoa mexer em nada.
4. Vale para todo jeito de produzir:
   - pelo editor (site): criação, render, Corrigir Mídia, Continuar carregamento, limpeza, publicação;
   - pelo terminal: `fabrica tudo`;
   - pelo robô PALHANO e pelo MCP, que rodam o mesmo `tudo` por dentro.
5. Nunca para a fábrica: se o aviso ao sistema falhar, o vídeo segue normal.
6. Sem configuração nova e sem mexer nas configurações do Windows.

### 5. Como foi feito

**Arquivo novo: `fabrica/acordado.py`**
- Uma linha própria confere de 20 em 20 segundos se há trabalho e avisa o sistema só quando o estado muda.
- No Windows: `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)`, o mesmo aviso que um download ou um
  vídeo tocando dão. O aviso vale para a linha que chamou, por isso uma linha só faz todas as chamadas.
- No Mac: abre o `caffeinate -i` enquanto há trabalho e fecha quando acaba.
- Duas formas de dizer que há trabalho:
  - `acordado.segurar()`: um bloco `with` que segura o sono enquanto roda (pode ser aninhado);
  - `acordado.vigiar(funcao)`: registra uma função que responde se há trabalho. Erro dentro dela é ignorado.
- Qualquer falha é engolida: a fábrica nunca para por causa disso.

**`fabrica/api.py` (servidor do editor)**
- Ao subir (`criar_app`), registra `_ha_tarefa_andando`: há trabalho quando alguma tarefa em `TAREFAS` está
  `processando`, `renderizando` ou `enviando`.
- Tarefa esperando a pessoa (`aguardando_confirmacao`) não segura o sono.

**`fabrica/cli.py` (terminal, robô e MCP)**
- `cmd_tudo` virou um envoltório com `acordado.segurar()` em volta do corpo antigo, agora em `_tudo`.

**`tests/test_acordado.py`**
- O `segurar` conta e solta certo, inclusive um dentro do outro.
- Um verificador com erro não derruba os outros.

**`CLAUDE.md`**
- Nova linha na tabela de erros comuns: "Criação parada horas e voltando sozinha, sem erro nenhum", com a causa, a
  solução e onde conferir no registro do Windows.

### 6. Verificação

| Teste | Resultado |
|---|---|
| `pytest tests/test_acordado.py` | 2 passaram |
| Chamada ao Windows | aceita: a segunda chamada devolveu o estado anterior com o "sistema necessário" ligado |
| `import fabrica.api, fabrica.cli` | carrega sem erro |
| `powercfg /requests` (lista quem segura o sono) | não rodou: pede administrador |

### 7. Pendências

- **Reiniciar o servidor** (DESLIGAR-TIPLABS e LIGAR-TIPLABS) para a mudança valer. Fazer de preferência depois que
  os dois vídeos em produção terminarem. Interrompidos, eles voltam de onde pararam, mas perdem alguns minutos.
- Depois de reiniciar, conferir na prática: deixar um vídeo rodando de madrugada e ver no registro do Windows que não
  houve Kernel-Power 42 durante a produção. Também dá para conferir com `powercfg /requests` num terminal de
  administrador: a fábrica aparece em "SYSTEM".
- Nada foi enviado para o GitHub (sem commit).

### 8. Fora do escopo

- Trabalhar com o computador desligado ou dormindo (só com um servidor alugado).
- Tampa do notebook fechada: segue a configuração "ao fechar a tampa" do Windows, que o aviso não muda.
- Hibernação forçada por bateria fraca.
