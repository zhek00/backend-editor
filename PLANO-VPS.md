# Fábrica em VPS: produção em massa

Pedido do usuário em 14 de outubro de 2026: o frontend sai de cena. A pessoa só manda o roteiro (pelo MCP ou por uma
API REST) e a fábrica constrói e renderiza o vídeo sozinha, para **200 a 500 vídeos por dia**, de centenas de pessoas.
Tudo numa VPS, com banco de dados, e o vídeo e os arquivos apagados **em no máximo 3 dias**.

Decisões (do usuário): VPS dimensionada aqui; PostgreSQL em Docker na própria VPS; vídeo pronto no armazenamento da
nuvem (Cloudflare R2); entrada pelo MCP e por uma API REST.

## Como era (até 14/10/2026)

- Um computador Windows, servidor e MCP ligados pelos scripts `LIGAR-TIPLABS`, túnel da Cloudflare.
- Estado na memória do servidor (`api.TAREFAS`, `CRIACOES_ATIVAS`, `mcp_servidor._PRODUCOES`) e em JSON solto
  (`criacao.json`, `mcp_producao.json`, `clientes_mcp.json`).
- Duas esteiras: a do site (`api._esteira`, com a medição de tempos) e a do MCP (`cli.cmd_tudo`).
- Sem fila: cada pedido do MCP abria uma produção na hora, sem limite.
- Paradas que esperam uma pessoa: crédito acabou, chave recusada, assunto sem foto em nenhum banco.

Medido no everything-you-need-to-answer (20 min, inglês): ~3 h de criação (1h35 esperando o agente de roteiro, já
atacado), ~25 min de render, ~2.200 chamadas de modelo, ~US$ 2,00 (narração 0,48, imagens 1,17, modelos 0,41),
4,3 GB de disco.

## Como fica

```
 MCP (Claude do cliente) ─┐                     ┌─ trabalhador 1 (N vídeos ao mesmo tempo)
 API REST /v1 (chave) ────┼─> PostgreSQL ──fila─┼─ trabalhador 2
                          │   (vídeos, clientes,└─ trabalhador ...
                          │    eventos, tempos)        │
                          └─────────────────────────── └─> Cloudflare R2 (vídeo pronto, 3 dias) -> link
```

1. **PostgreSQL é a fonte da verdade** (`fabrica/banco.py`): clientes, vídeos (estado, etapa, andamento, custo,
   tempos, erro, quando expira), eventos. SQLite no computador de desenvolvimento e nos testes, o mesmo código.
2. **Fila no banco** (`fabrica/fila.py`): o pedido entra como `na_fila`; o trabalhador pega com
   `FOR UPDATE SKIP LOCKED`, marca um sinal de vida a cada minuto e devolve à fila o vídeo de um trabalhador que
   morreu. Limite de vídeos ao mesmo tempo por trabalhador; mais máquinas = mais trabalhadores na mesma fila.
3. **Uma esteira só** (`fabrica/producao.py`): a criação do site (`api._esteira`, com os tempos) e o render, no fim,
   sem ninguém. O MCP e a API só põem na fila e leem o estado.
4. **Sem paradas que esperam gente**: crédito ou chave com problema deixam o vídeo em espera e tentam de novo sozinhos
   (com alerta); assunto sem foto vira imagem de IA.
5. **Entrega**: o vídeo pronto sobe para o R2 e o cliente recebe um link assinado. Os arquivos de trabalho do
   projeto (render, mídia baixada) são apagados logo depois da entrega.
6. **Limpeza em 3 dias** (`fabrica/limpeza_vps.py`): o que expirou (vídeo pronto, com erro ou cancelado) sai do
   disco e do R2, e o vídeo fica `expirado` no banco. Regra de ciclo de vida no R2 como segunda garantia.
7. **Docker**: `docker compose up` sobe PostgreSQL, API, MCP, trabalhador e o HTTPS; backup diário do banco.

## Fases

| Fase | O quê | Situação |
|---|---|---|
| 1 | Banco e fila (`banco.py`, `fila.py`), testes em SQLite e PostgreSQL | feito |
| 2 | Esteira única e trabalhador (`producao.py`, `fabrica trabalhador`), render automático | feito |
| 3 | Entrega no R2 (`armazenamento.py`) e limpeza em 3 dias (`limpeza_vps.py`) | feito |
| 4 | API REST `/v1` com chave por cliente (`api_v1.py`); MCP pela fila (`mcp_fila.py`) | feito |
| 5 | Sem paradas que esperam gente: espera e tenta de novo (crédito, chave, limite), cartão animado no lugar da foto que não existe, consumo alto para na hora, alertas (`alertas.py`) | feito |
| 6 | Linux e Docker (`deploy/`: Dockerfile, compose do principal e dos trabalhadores, HTTPS, backup) | feito, falta a 1ª subida |
| 7 | Piloto: 30 roteiros variados sem ninguém mexer (`fabrica enfileirar`, `fabrica relatorio`) | na VPS |

## Como subir

1. **Contratar** o servidor principal e um trabalhador (ver Dimensionamento), com rede privada entre eles, Ubuntu 24.04
   e Docker (`curl -fsSL https://get.docker.com | sh`). Apontar o DNS de `API_DOMINIO` e `MCP_DOMINIO` para o IP do
   principal.
2. **Cloudflare R2**: criar o bucket, uma chave de API só dele, e a regra de ciclo de vida "apagar objetos com mais de
   3 dias" (a segunda garantia da limpeza).
3. **No principal**, com o repositório clonado: `cd deploy && cp .env.vps.exemplo .env`, preencher o `.env` (copiando
   as chaves dos serviços do `.env` de hoje), e
   `mkdir -p dados/projetos dados/entregas_vps dados/backups && echo '{}' > dados/clientes_mcp.json &&
   sudo chown -R 1000:1000 dados/projetos dados/entregas_vps dados/clientes_mcp.json`; depois `docker compose up -d --build`.
4. **Clientes**: `docker compose exec api fabrica cliente-criar "Nome do cliente" --limite 50` mostra a chave da API
   (uma vez só). Os clientes do MCP continuam no `clientes_mcp.json` (`fabrica mcp-cliente`).
5. **Trabalhadores extras**: em cada máquina, o mesmo repositório e o mesmo `.env` com `POSTGRES_HOST` (o IP privado do
   principal), e `docker compose -f docker-compose.trabalhador.yml up -d --build`.
6. **Acompanhar**: `docker compose exec api fabrica fila`, `fabrica relatorio --dias 1`, os avisos no webhook e
   `GET /v1/saude`.

O banco só escuta na rede privada (`POSTGRES_IP_PRIVADO`): nunca abra a porta 5432 na internet.

## Dimensionamento (estimativa, a confirmar no piloto)

Um vídeo de ~20 min ocupa uns **2,5 a 3,5 núcleo-hora** (render ~25 min em 6 núcleos, animações no Chrome, FFmpeg); a
criação é quase toda espera de API. Para **300 vídeos/dia**: ~750 a 1.000 núcleo-hora por dia, ~35 a 45 núcleos
ocupados o dia todo; com folga para picos, **60 a 80 vCPU dedicadas**. Para 500/dia, uns 100 a 130.

- **1 servidor principal**: API, MCP, PostgreSQL, HTTPS. 4 a 8 vCPU, 16 GB, 160 GB NVMe.
- **3 a 5 trabalhadores**: 16 vCPU **dedicadas** (não compartilhadas), 32 GB, 300 GB NVMe cada. Cada um roda ~4 a 6
  vídeos ao mesmo tempo.
- **R2**: o vídeo pronto (~0,5 GB) por 3 dias: ~750 GB com 500/dia, uns US$ 11/mês, sem custo de saída.

Comece com o principal e **um** trabalhador, rode o piloto e some trabalhadores pelo que o piloto medir. O custo de
modelos e imagens (~US$ 2 por vídeo hoje, US$ 400 a 1.000 por dia nesse volume) pesa mais que as máquinas: o piloto
mede também quanto do que hoje é gratuito precisa virar pago.
