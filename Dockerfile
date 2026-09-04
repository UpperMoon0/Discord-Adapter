# Lily-Discord-Adapter production image
FROM python:3.11-slim

ARG APP_UID=10001
ARG APP_GID=10001

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean && \
    apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      libsodium-dev \
      nodejs \
    && groupadd --gid "$APP_GID" lily \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --no-create-home --shell /usr/sbin/nologin lily \
    && mkdir -p /app/data /app/Lily-Discord-Adapter \
    && chown -R lily:lily /app \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=lily:lily . /app/Lily-Discord-Adapter
WORKDIR /app/Lily-Discord-Adapter
RUN chmod 0555 /app/Lily-Discord-Adapter/yt-dlp \
    && chown -R lily:lily /app/Lily-Discord-Adapter /app/data

ENV PYTHONPATH=/app/Lily-Discord-Adapter \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache

EXPOSE 8004

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8004/health', timeout=5).raise_for_status()" || exit 1

# Production runs this image as UID/GID 10001 via docker-compose.prod.yml. The
# image intentionally leaves USER unset because NsTut-CICD appends root-only
# addon installation layers when building the composite release.
CMD ["python", "main.py"]
