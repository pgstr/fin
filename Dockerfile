# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.21 AS uv

FROM python:3.13-slim-bookworm AS builder
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.13-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENVIRONMENT=production \
    DATABASE_PATH=/data/finanzplaner.db \
    BACKUP_DIR=/backups \
    TZ=Europe/Berlin
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates curl gosu tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 finanzplaner \
    && useradd --system --uid 10001 --gid finanzplaner --home-dir /nonexistent --shell /usr/sbin/nologin finanzplaner
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
COPY docker/entrypoint.sh /usr/local/bin/finanzplaner-entrypoint
RUN chmod 0755 /usr/local/bin/finanzplaner-entrypoint \
    && mkdir -p /data /backups \
    && chown finanzplaner:finanzplaner /data /backups
VOLUME ["/data", "/backups"]
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/finanzplaner-entrypoint"]
CMD ["serve"]
