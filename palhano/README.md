# Robô PALHANO

O cliente cola o roteiro num site, e um robô no computador dele entrega o vídeo pronto. **Quem faz o vídeo é a
fábrica**, com todas as regras dela: o Jev, as animações, as thumbnails, os shorts e o kit de publicação. O PALHANO é
a parte de venda, com conta, planos, fila e máquinas.

Ele foi feito do zero, no modelo do Robô do Dotti Studio, sem copiar código, texto, marca ou visual de lá.

## As duas partes

| Parte | O que faz | Onde roda |
|---|---|---|
| **Painel** (`palhano/painel/`, `uv run fabrica painel`) | Conta, aprovação, plano e limite por dia, canais, chaves, fila, acompanhamento, produções, custos, administração | No seu servidor |
| **Robô** (`palhano/robo/robo.py`, `uv run fabrica robo`) | Conecta o computador ao painel, pega até 3 vídeos da fila ao mesmo tempo (`--simultaneos N` muda), roda `fabrica novo` e `fabrica tudo` com as chaves do cliente e entrega o MP4 | No computador do cliente, com a fábrica instalada |

## Como o pedido do painel vira um projeto da fábrica

O robô escreve um perfil por cima de `perfis/documentario.yaml`:
- **voz:** narrador, `voice_id` e velocidade;
- **imagens:** o jeito das imagens de IA do estilo;
- **legenda;**
- **diretrizes do canal;**
- **`visual`:** o estilo de edição.

E põe o `config_override` no `projeto.json`:
- `ia.ativa`: as imagens de IA;
- `trilha.ativo`: a trilha;
- `animation_ai.tema`: o tema das cenas animadas do estilo.

O modo teste usa `fabrica novo --offline`, e a versão em pé usa `tudo --vertical`.

### Estilos

| Estilo | Visual (`visual` no perfil) | Tema das cenas animadas |
|---|---|---|
| Documentário | Natural | apple |
| Investigação | Cor lavada, granulado, vinheta | misterio |
| Noticiário | Neutro | editorial |
| Energia | Cor forte | noite |
| Cinema | Tom de filme e faixas pretas (só na versão deitada) | noite |

O robô entrega na pasta escolhida o MP4, a versão em pé (se pedida), os créditos, o kit de publicação e a
thumbnail.

## Ligar para testar

1. Na pasta da fábrica, rode `uv sync`.
2. Dê dois cliques em **palhano/LIGAR-PAINEL.bat** (ou rode `uv run fabrica painel`). O navegador abre em
   http://127.0.0.1:8300.
3. Crie a conta. **A primeira conta é a da administração.**
4. Em **Máquinas**, gere o código de conexão.
5. Dê dois cliques em **palhano/LIGAR-ROBO.bat** (ou rode `uv run fabrica robo`) e digite o código.
6. Em **Produzir**, cole o roteiro e, no passo 3, marque **Teste sem custo** para conferir.

## O que veio do motor próprio que existiu por um dia

Ele foi apagado em 2026-10-12. O que ele tinha de bom foi levado para a fábrica:

1. **Estilos de edição** (`render.VISUAIS`, `visual:` no perfil).
2. **Recusar gráfico, tabela e calendário de banco de imagens.** Eles mostram dados de outro lugar ou de outro ano. A
   regra vale para o agente, para a escolha das fotos e para o Jev.
3. **Recusar sinais de outro país e de outra época:** texto em outro idioma, ano errado e preço em outra moeda.

O primeiro teste dele (Dollarama, 2:44, US$ 0,022) mostrou esses erros: um botão SUBSCRIBE em fundo verde, gráficos
de CO₂ e calendários em português. O fundo verde a fábrica já barrava.

## Arquivos que não vão para o Git

- `palhano/painel/dados/`: o banco e o `segredo.key`, que cifra as chaves dos clientes. Faça backup. Em produção,
  prefira a variável `PALHANO_SEGREDO`.
- `palhano/robo/dados/`: o token da máquina e os roteiros recebidos.

## O que falta

1. **Painel na internet** com HTTPS (`PALHANO_HTTPS=1`).
2. **Instalador do Windows** com a fábrica, o uv e o FFmpeg.
3. **Kiwify** testado com uma compra de verdade.
4. **Escolher a voz no painel**, com prévia.
5. **"Esqueci minha senha"**, login com Google e e-mails.
6. **Termos de uso e privacidade.**
7. **Cortes do YouTube em Creative Commons:**
   - desligados por padrão, com aviso de responsabilidade;
   - trechos curtos, sem o som original;
   - crédito automático.
8. **Envio ao Google Drive** e **publicar no YouTube** pelo painel. A fábrica já publica pelo editor.
