# TAREFA 4 — Limpar lixo morto + implementar Kie.ai e Edge TTS de verdade

Você é o agente executor (Antigravity, Gemini 3.8 Flash HIGH). Esta tarefa vem depois de revisar o relatório da Tarefa 1. Achamos 3 problemas em `E:\fabrica-para-amigo\fabrica\api.py`: um lixo morto (remover) e dois recursos reais do frontend sem suporte no núcleo (implementar de verdade, autorizado pelo dono do projeto). Trate as três partes como exceções à estrutura, já autorizadas — mas só o que está descrito aqui, nada além.

## Parte 0 — Remover lixo morto (sem decisão nenhuma envolvida)

Em `E:\fabrica-para-amigo\fabrica\api.py`, ache este trecho (perto da criação de projeto, dentro do `worker_criacao`):

```python
provedor_img = payload.imagens_provedor
if perfil_path.stem == "animais-exoticos":
    provedor_img = "kie"
if provedor_img in ("google", "kie"):
```

Apague as duas linhas do `if perfil_path.stem == "animais-exoticos": provedor_img = "kie"`. Esse perfil não existe em `E:\fabrica-para-amigo\perfis` — é resíduo do sistema multi-canal antigo, sem nenhuma função aqui. Fica só:

```python
provedor_img = payload.imagens_provedor
if provedor_img in ("google", "kie"):
```

## Parte A — Implementar o provedor de imagem Kie.ai em `fabrica/imagens.py`

O frontend (`js/app.js`) tem um botão "Kie" que já é o provedor padrão de imagem no editor, mas `fabrica/imagens.py` só sabe gerar via Google ou Fal. A implementação já existe pronta em `G:\fabrica-de videos\fabrica\imagens.py` — é portar, não inventar.

### A.1 — Constante do modelo

Perto do topo de `E:\fabrica-para-amigo\fabrica\imagens.py`, onde já existe `MODELO_GOOGLE` (confira o nome exato da constante existente), adicione ao lado:

```python
MODELO_KIE = "z-image"  # Qwen Z-Image (Kie.ai): geração ultrarrápida (1.0s) e fotorrealista
```

### A.2 — Função de geração

Adicione a função inteira abaixo (copiada de `G:\fabrica-de videos\fabrica\imagens.py`, função `_imagem_kie`, por volta da linha 432-540 — copie até o fim da função, que termina retornando `(dados, registro)` no mesmo formato que `_imagem_fal` já usa em `E:\fabrica-para-amigo\fabrica\imagens.py`; confira no arquivo de origem onde a função termina antes de copiar):

```python
def _imagem_kie(prompt, img):
    """Gera imagem pela API da Kie.ai (Qwen Z-Image)."""
    api_key = chave("KIE_API_KEY")
    modelo = img.get("modelo", MODELO_KIE)
    proporcao = img.get("proporcao", "16:9")

    payload = {
        "model": modelo,
        "input": {"aspect_ratio": proporcao, "prompt": prompt},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        resp = client.post("https://api.kie.ai/api/v1/jobs/createTask", json=payload, headers=headers)
        if resp.status_code in (401, 403):
            raise RuntimeError(f"Kie.ai: chave de API não autorizada ou inválida (HTTP {resp.status_code}).")
        if resp.status_code == 402:
            raise SemCota("Kie.ai: créditos insuficientes na conta. Recarregue seu saldo para gerar novas imagens com IA.")
        if resp.status_code != 200:
            raise RuntimeError(f"Erro ao criar tarefa na Kie.ai ({resp.status_code}): {resp.text[:300]}")
        # ... (copie o resto da função de G:\fabrica-de videos\fabrica\imagens.py sem alterar a lógica,
        # inclusive o polling do taskId e o retorno final no formato (dados, registro))
```

**Importante:** confira se `E:\fabrica-para-amigo\fabrica\imagens.py` já importa `httpx`, `json` e `time` no topo do arquivo (o resto do arquivo provavelmente já usa) — se algum faltar, adicione o import, é esperado.

A função `_imagem_kie` na origem levanta `SemCota` em alguns casos — confirme que a classe `SemCota` já existe em `E:\fabrica-para-amigo\fabrica\imagens.py` (ela é usada por `_imagem_google` para falta de cota do Google, então deve existir).

### A.3 — Ligar a chave de API

Em `E:\fabrica-para-amigo\fabrica\imagens.py`, na função `gerar(...)`, ache:

```python
    if not projeto.offline:
        chave("GEMINI_API_KEY" if provedor(projeto.perfil) == "google" else "FAL_KEY")
```

Troque por:

```python
    if not projeto.offline:
        prov = provedor(projeto.perfil)
        if prov == "google":
            chave("GEMINI_API_KEY")
        elif prov in ("kie", "kie.ai"):
            chave("KIE_API_KEY")
        else:
            chave("FAL_KEY")
```

### A.4 — Ligar a geração de verdade

Na função `_gerar_uma(...)`, ache:

```python
            if provedor(projeto.perfil) == "google":
                dados = _imagem_google(prompt, img, usar, img.get("proporcao", "16:9"), img.get("resolucao", "1K"))
                registro = {"provedor": "google", "modelo": img.get("modelo", MODELO_GOOGLE), "prompt": prompt}
            else:
                dados, registro = _imagem_fal(prompt, img, usar)
```

Troque por:

```python
            prov = provedor(projeto.perfil)
            if prov == "google":
                dados = _imagem_google(prompt, img, usar, img.get("proporcao", "16:9"), img.get("resolucao", "1K"))
                registro = {"provedor": "google", "modelo": img.get("modelo", MODELO_GOOGLE), "prompt": prompt}
            elif prov in ("kie", "kie.ai"):
                dados, registro = _imagem_kie(prompt, img)
            else:
                dados, registro = _imagem_fal(prompt, img, usar)
```

Não mude mais nada nessa função. Não mexa no valor padrão de `provedor()` (continua "google" quando o perfil não define nada — o frontend já manda "kie" explicitamente quando é essa a escolha).

### A.5 — Preço estimado

Em `E:\fabrica-para-amigo\config.yaml`, dentro do bloco `precos:`, adicione uma linha (mesmo formato das outras):
```yaml
  imagem_kie: 0.02                     # Qwen Z-Image via Kie.ai
```

Se `fabrica/custos.py` já faz alguma conta com os preços de imagem para estimativa (`fabrica estimar`), confira se ela busca a chave certa pelo provedor; se ela for genérica (só olha um preço fixo de imagem, sem diferenciar provedor), pode deixar como está e só reportar isso pra mim — não precisa mexer em `custos.py` além do necessário.

## Parte B — Implementar a voz Edge TTS em `fabrica/narracao.py`

O seletor de voz do editor (`js/voice-picker.js`) tem um botão real "Edge TTS" (voz gratuita), mas `fabrica/narracao.py` só narra com ElevenLabs. Implementação pronta em `G:\fabrica-de videos\fabrica\narracao.py`.

### B.1 — Dependência nova

Adicione ao `E:\fabrica-para-amigo\pyproject.toml`, na lista de `dependencies`:
```
"edge-tts>=7.2.8",
```
Depois rode `uv sync`.

### B.2 — Função de narração

Adicione a função inteira (copiada de `G:\fabrica-de videos\fabrica\narracao.py`, função `_edge_tts`, linhas 446-503):

```python
def _edge_tts(texto, voz, wav):
    import asyncio
    import edge_tts

    VOZES_VALIDAS = {
        "pt-BR-AntonioNeural",
        "pt-BR-FranciscaNeural",
        "pt-BR-ThalitaMultilingualNeural",
        "pt-PT-DuarteNeural",
        "pt-PT-RaquelNeural"
    }

    voz_nome = (voz.get("voz_edge") or "pt-BR-AntonioNeural").strip()
    if "Thalita" in voz_nome:
        voz_nome = "pt-BR-ThalitaMultilingualNeural"
    elif voz_nome not in VOZES_VALIDAS:
        voz_nome = "pt-BR-AntonioNeural"

    mp3 = wav.with_suffix(".mp3")
    velocidade = voz.get("velocidade_edge", "+0%")
    tom = voz.get("tom_edge", "+0Hz")

    # velocidade_edge e tom_edge aceitam o formato do Edge, como "-10%" e "-5Hz"
    async def _falar():
        c = edge_tts.Communicate(texto, voz_nome, rate=velocidade, pitch=tom)
        await c.save(str(mp3))

    ultimo_erro = None
    sucesso = False
    for tentativa in range(3):
        try:
            asyncio.run(_falar())
            if mp3.exists() and mp3.stat().st_size > 100:
                sucesso = True
                break
            ultimo_erro = RuntimeError(f"o Edge-TTS não gerou áudio (arquivo ausente ou vazio) pra voz {voz_nome}")
        except Exception as e:
            ultimo_erro = e
            if voz_nome != "pt-BR-AntonioNeural":
                voz_nome = "pt-BR-AntonioNeural"
        time.sleep(1.0)

    if not sucesso:
        raise ultimo_erro

    rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(TAXA), "-c:a", "pcm_s16le", str(wav)])
    mp3.unlink(missing_ok=True)
    duracao = duracao_audio(wav)
    n = max(len(texto), 1)
    return {
        "caracteres": list(texto),
        "inicio": [duracao * i / n for i in range(n)],
        "fim": [duracao * (i + 1) / n for i in range(n)],
    }
```

`E:\fabrica-para-amigo\fabrica\narracao.py` já importa `time` e `shutil`/`rodar` no topo — confirme, e adicione o que faltar.

### B.3 — Ligar no fluxo principal

Em `narrar(...)`, ache:
```python
            if projeto.offline:
                alinhamento = _voz_do_mac(bloco.texto, voz, bruto)
            else:
                anterior = blocos[i - 1].texto[-400:] if i > 0 else None
                seguinte = blocos[i + 1].texto[:400] if i + 1 < len(blocos) else None
                alinhamento = _elevenlabs(bloco.texto, anterior, seguinte, voz, bruto)
```

Troque por:
```python
            if projeto.offline:
                alinhamento = _voz_do_mac(bloco.texto, voz, bruto)
            elif voz.get("provedor") == "edge-tts":
                alinhamento = _edge_tts(bloco.texto, voz, bruto)
            else:
                anterior = blocos[i - 1].texto[-400:] if i > 0 else None
                seguinte = blocos[i + 1].texto[:400] if i + 1 < len(blocos) else None
                alinhamento = _elevenlabs(bloco.texto, anterior, seguinte, voz, bruto)
```

Não porte o mecanismo de `_assinatura_voz`/`_CAMPOS_ASSINATURA_VOZ` de `G:\fabrica-de videos` — isso é uma melhoria de cache separada, fora do escopo desta tarefa. Deixe o `_mesmo_texto` de `E:\fabrica-para-amigo` como está.

## O que NÃO fazer

- Não mude o padrão de `imgProvedor` nem o botão Kie no frontend — eles já estão certos, só faltava o backend.
- Não porte mais nada de `custos_reais.py`/`groq`/outras partes de G que não estejam listadas aqui.
- Não toque em `_voz_do_mac`, `_elevenlabs`, `_imagem_google` além do que foi pedido.

## Testar

1. `uv run python -c "import fabrica.imagens, fabrica.narracao; print('OK')"` — confirma que nada quebrou na importação.
2. Suba o servidor (`uv run fabrica servidor --porta 8080`) e, pelo editor, crie um projeto novo escolhendo Kie como provedor de imagem e Edge TTS como voz (ou use `--offline` primeiro pra não gastar, e só rode online se eu autorizar o gasto).
3. Confirme no log que a cena tenta mesmo chamar `_imagem_kie`/`_edge_tts` (não confirme só o HTTP 200 da criação do projeto — confirme que a geração de fato usa o caminho novo).

## O que preciso receber de volta

1. Diff de `api.py` (remoção do `animais-exoticos`), `imagens.py`, `narracao.py`, `pyproject.toml`, `config.yaml`.
2. Confirmação de que a Parte 0 (lixo morto) foi removida.
3. Resultado do teste com Kie e com Edge TTS — se der erro de chave (`KIE_API_KEY` ausente no `.env`), isso é esperado até você colar a chave; só me diga se o erro foi exatamente esse ou outro.
4. Se `custos.py` precisar de ajuste pra "imagem_kie" e você não tiver certeza, pare e me pergunte em vez de decidir sozinho.
