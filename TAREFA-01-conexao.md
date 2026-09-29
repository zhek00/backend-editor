# TAREFA 1 — Trocar o backend do editor-video-dark para a fábrica-para-amigo

Você é o agente executor (Antigravity, Gemini 3.8 Flash HIGH). Leia tudo antes de tocar em qualquer arquivo. Este documento é a única fonte de verdade — não invente passos fora dele.

## Contexto (já verificado, não precisa reconferir do zero)

Existem três pastas envolvidas:

1. `E:\fabrica-para-amigo` — a estrutura CANÔNICA. É só um pacote Python de linha de comando (`fabrica novo`, `fabrica tudo`, `fabrica narrar`, etc.). Hoje ela **não tem nenhum servidor HTTP**.
2. `G:\editor-video-dark` — o frontend (HTML/CSS/JS + um `server.py` leve que só serve arquivos estáticos). Ele fala com o backend via HTTP em `/api/...` (veja `js/api.js`).
3. `G:\fabrica-de videos` — uma pasta **legada e poluída**, fork antigo da fábrica. É para onde o `editor-video-dark/server.py` aponta hoje (`DEFAULT_FABRICA_DIR = Path("G:/fabrica-de videos")`). Ela tem lixo (logs, mp3 de teste, imagens de teste, `.env` com chaves reais, arquivos de scratch) e também tem código que a `fabrica-para-amigo` não tem: `fabrica/api.py`, `fabrica/custos_reais.py`, `fabrica/limpeza.py`, `fabrica/nichos.py`, `fabrica/verificar.py`, `fabrica/verificar_ia.py`, `fabrica/youtube_publicar.py`, e um subcomando `servidor` dentro de `cli.py`.

## Regra absoluta, sem exceção

- **`E:\fabrica-para-amigo` NUNCA pode ser modificada**, exceto para ADICIONAR a camada de conexão HTTP (a lista exata está no passo 2 abaixo). Nenhum arquivo já existente nela pode ser reescrito, renomeado, apagado ou ter seu comportamento alterado.
- **`G:\fabrica-de videos` NUNCA deve ser copiada inteira nem usada como destino de nada.** Ela só serve como referência para extrair a camada de conexão. Não copie logs, `.env`, mp3, png, `projetos/`, `roteiros/`, `.claude/`, scratch files — nada disso.
- **Nunca leia, copie, logue ou exponha o conteúdo do `.env` de `G:\fabrica-de videos`.** Ele tem chaves de API reais. Se precisar de exemplo de variáveis, use `.env.exemplo`, nunca `.env`.
- Se em algum ponto parecer necessário violar uma dessas regras para a tarefa funcionar, PARE e escreva o motivo em vez de decidir sozinho.

## Objetivo final

`G:\editor-video-dark` deve falar exclusivamente com `E:\fabrica-para-amigo` rodando localmente (`uv run fabrica servidor --porta 8080`), e `G:\fabrica-de videos` deixa de ser referenciada em qualquer lugar do editor. O sistema resultante deve ser enxuto: só entra em `fabrica-para-amigo` o código realmente usado pelo frontend, nada de features não usadas "por garantia".

## Passo a passo

### 1. Levantar o que o frontend realmente chama

Leia `G:\editor-video-dark\js\api.js` inteiro e liste todas as rotas `/api/...` que ele chama (já identifiquei estas, confirme se a lista está completa: `/api/projetos`, `/api/config/chaves`, `/api/projetos/{nome}/custos`, `/api/nichos/buscar`, `/api/nichos/canal/{id}/videos`, `/api/youtube/conectar`, `/api/youtube/status`, `/api/youtube/desconectar`, `/api/projetos/{nome}/youtube/publicar`, `/api/projetos/{nome}`, `/api/projetos/{nome}/cenas`, `/api/projetos/{nome}/cenas/{n}/refazer`, `/api/projetos/{nome}/cenas/{n}/upload`, `/api/projetos/{nome}/narracao`, `/api/projetos/{nome}/cenas/salvar`, `/api/projetos/{nome}/render`, `/api/projetos/{nome}/status`, `/api/project/scene/antigas`, `/api/project/scene/restore-antiga`, `/api/sfx-library`, `/api/music-library`, `/api/projetos/criar`, `/api/perfis`, `/api/vozes`, `/api/vozes/elevenlabs`, `/api/projetos/{nome}/verificar`, `/api/projetos/{nome}/limpar-midia`, `/api/projetos/{nome}/imagens/provedor`).

Também confira `js/dashboard.js`, `js/nichos.js`, `js/voice-picker.js` e `js/gate.js` — eles também podem chamar `/api/...` por conta própria.

### 2. Decidir o que entra em `fabrica-para-amigo` (a "camada de conexão")

Para cada rota do passo 1, ache em `G:\fabrica-de videos\fabrica\api.py` o handler correspondente e veja de quais módulos ele depende (`cenas`, `custos_reais`, `imagens`, `limpeza`, `midia`, `narracao`, `nichos`, `render`, `verificar`, `youtube_publicar`, `config`, `projeto`).

Regra de decisão:
- Se um módulo de apoio (`custos_reais.py`, `limpeza.py`, `nichos.py`, `verificar.py`, `verificar_ia.py`, `youtube_publicar.py`) é usado por pelo menos uma rota que o frontend chama de verdade → ele entra, copiado para `E:\fabrica-para-amigo\fabrica\`, adaptado ao estilo da `fabrica-para-amigo` (nomes e assinaturas dos módulos já existentes lá podem ter divergido do `G:\fabrica-de videos` — confira cada import um por um, não assuma que são iguais).
- Se nenhuma rota usada pelo frontend depende dele → **não copiar**. Isso é o que mantém o sistema leve.
- Módulos que já existem nos dois lados (`cenas.py`, `midia.py`, `narracao.py`, `render.py`, `imagens.py`, `config.py`, `projeto.py`, `util.py`, `texto.py`, `textos.py`, `avatar.py`, `abertura.py`, `claude_local.py`, `custos.py`, `efeitos.py`, `musica.py`, `meditacao.py`) **não são tocados**. Se `api.py` chama uma função que não existe na versão desses módulos dentro de `fabrica-para-amigo`, ajuste a chamada dentro do `api.py` novo — nunca o módulo original.

### 3. Portar o arquivo de conexão

- Copie `G:\fabrica-de videos\fabrica\api.py` para `E:\fabrica-para-amigo\fabrica\api.py`, ajustando os imports conforme o passo 2.
- Adicione em `E:\fabrica-para-amigo\fabrica\cli.py` **apenas** a função `cmd_servidor` e o subparser `servidor` (copie do `G:\fabrica-de videos\fabrica\cli.py`, linhas em torno de `def cmd_servidor` e `s = sub.add_parser("servidor", ...)`). Não mexa em nenhum outro comando existente no arquivo.
- Adicione em `E:\fabrica-para-amigo\pyproject.toml` só as dependências novas que `api.py` exige e que a `fabrica-para-amigo` ainda não tem (ex.: `fastapi`, `uvicorn`, e `python-multipart` se houver upload de arquivo). Não mude nenhuma outra dependência ou versão já travada.
- Rode `uv sync` em `E:\fabrica-para-amigo` para atualizar o lockfile.

### 4. Repontar o frontend

Em `G:\editor-video-dark\server.py`:
- Troque `DEFAULT_FABRICA_DIR = Path("G:/fabrica-de videos")` para `Path("E:/fabrica-para-amigo")`.
- Troque o `--fabrica` default do `argparse` (`"G:/fabrica-de videos"`) para `"E:/fabrica-para-amigo"`.
- Não toque em mais nada nesse arquivo.

**Não mexa em `config.js`** (a URL de produção `https://editor.bbnews.cc` é outro assunto, fora do escopo desta tarefa — isso é hospedagem remota, não a pasta local).

### 5. Testar

1. Em `E:\fabrica-para-amigo`: `uv run fabrica servidor --porta 8080` e confirmar que `GET http://localhost:8080/api/projetos` responde 200.
2. Em `G:\editor-video-dark`: `python server.py` e confirmar no log que ele NÃO tenta mais subir nada de `G:/fabrica-de videos`.
3. Abrir o editor no navegador e testar pelo menos: listar projetos, abrir um projeto, ver as cenas, disparar uma narração ou render em modo que não gaste (se existir flag de teste, use).
4. Reportar qualquer rota que retornou 404/500 por falta de algo que não foi portado.

## O que eu preciso receber de volta para analisar

1. Lista exata de arquivos criados/alterados dentro de `E:\fabrica-para-amigo` (deve ser só: `fabrica/api.py` novo, `fabrica/cli.py` com a adição do comando `servidor`, `pyproject.toml` com as deps novas, `uv.lock` atualizado, e os módulos de apoio que você decidiu portar no passo 2 — com a justificativa de qual rota usa cada um).
2. Diff de `G:\editor-video-dark\server.py`.
3. Confirmação de que nenhum arquivo pré-existente em `fabrica-para-amigo` teve seu conteúdo original alterado além das adições descritas.
4. Resultado do teste do passo 5 (o que funcionou, o que deu erro).
5. Confirmação de que você não leu nem copiou o `.env` de `G:\fabrica-de videos`.

Não apague `G:\fabrica-de videos` — isso fica para uma decisão minha depois de revisar o resultado desta tarefa.
