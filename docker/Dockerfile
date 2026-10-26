# syntax=docker/dockerfile:1.7
# One image, three roles (command decides): migrate | api | worker. See docker/compose.yml.

# Digest-pinned for reproducible builds; Dependabot (docker ecosystem) bumps tag + digest together.
FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv

FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY app ./app

FROM python:3.12-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
RUN useradd --system --uid 10001 --no-create-home --home-dir /app estateos
WORKDIR /app
# Root-owned and read-only for the runtime user: nothing at runtime writes to /app except /app/.data.
COPY --from=builder /app /app
# The only writable path: dev data (local storage, fake mailboxes/media, dev keys) on a volume shared by api + worker.
# Unused in prod (prod refuses fake providers and local storage); prod hardening runs with a read-only root (M8).
RUN mkdir /app/.data && chown 10001 /app/.data
ENV PATH="/app/.venv/bin:${PATH}" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER estateos
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
