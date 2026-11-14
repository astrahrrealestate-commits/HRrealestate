# syntax=docker/dockerfile:1.7
# One image, three roles (command decides): migrate | api | worker. See docker/compose.yml.

# Digest-pinned for reproducible builds; Dependabot (docker ecosystem) bumps tag + digest together.
FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_HTTP_TIMEOUT=120
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
# The local translation models (ADR 0011): pinned revisions, checksum-verified, ~160 MB each. Fetched before the app
# is copied, so code changes never download them again.
COPY app/translation/fetch.py /tmp/fetch_translation_model.py
RUN /app/.venv/bin/python /tmp/fetch_translation_model.py /app/models/opus-mt-nl-en nl-en && \
    /app/.venv/bin/python /tmp/fetch_translation_model.py /app/models/opus-mt-en-nl en-nl
COPY alembic.ini ./
COPY app ./app

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --no-create-home --home-dir /app estateos
WORKDIR /app
# Root-owned and read-only for the runtime user: nothing at runtime writes to /app except /app/.data.
COPY --from=builder /app /app
# The only writable path: dev data (local storage, fake mailboxes/media, dev keys) on a volume shared by api + worker.
# Unused in prod (prod refuses fake providers and local storage); prod hardening runs with a read-only root (M8).
RUN mkdir /app/.data && chown 10001 /app/.data
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    TRANSLATION_MODEL_DIR=/app/models/opus-mt-nl-en \
    TRANSLATION_MODEL_DIR_EN_NL=/app/models/opus-mt-en-nl
USER estateos
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
