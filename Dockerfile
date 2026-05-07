# ---- builder ----
FROM python:3.12-slim AS builder

RUN set -eux; \
    arch="$(uname -m)"; \
    case "$arch" in \
        aarch64|arm64|x86_64|amd64) echo "Building for $arch" ;; \
        *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
    esac

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- final ----
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --no-create-home --shell /bin/false appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY . .
RUN pip install --no-cache-dir -e . --no-deps

RUN chown -R appuser:appuser /app
USER appuser

ENV DJANGO_SETTINGS_MODULE=app.settings
ENV PYTHONPATH=/app:/app/app/src

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=5)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
