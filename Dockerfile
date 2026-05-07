FROM python:3.12-slim

WORKDIR /app

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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN pip install --no-cache-dir -e .

ENV DJANGO_SETTINGS_MODULE=app.settings
ENV PYTHONPATH=/app:/app/app/src

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
