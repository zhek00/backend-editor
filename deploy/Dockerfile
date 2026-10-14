# Fábrica de vídeos para a VPS (PLANO-VPS.md): uma imagem só para a API, o MCP e o trabalhador.
# Construir da raiz do repositório:  docker build -f deploy/Dockerfile -t fabrica .
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DO_NOT_TRACK=1 \
    HYPERFRAMES_NO_TELEMETRY=1

# FFmpeg (com libass, para a legenda queimada), as fontes (Liberation: as medidas da Arial e da Times, com acentos),
# as bibliotecas do Chrome sem tela que o HyperFrames usa para gravar as animações, e o Node 22
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl ca-certificates gnupg fontconfig fonts-liberation fonts-dejavu-core \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 libgtk-3-0 libx11-xcb1 libxshmfence1 \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"

# o HyperFrames na versão fixa da fábrica (animacoes.VERSAO_PADRAO) e o navegador dele, baixados na construção:
# sem isso, o primeiro vídeo de cada contêiner baixava tudo no meio da produção
RUN npx --yes hyperframes@0.8.113 --version || true

RUN useradd --create-home --uid 1000 fabrica && mkdir -p /app/projetos /app/entregas_vps \
    && chown -R fabrica:fabrica /app
USER fabrica

EXPOSE 8080 8092
CMD ["fabrica", "trabalhador"]
