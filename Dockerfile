# syntax=docker/dockerfile:1
FROM python:3.11-slim
WORKDIR /app

# Prevent glibc memory fragmentation (OOM Fix)
ENV MALLOC_ARENA_MAX=2
ENV PYTHONUNBUFFERED=1

# Install build deps needed by some packages
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Plain pip install — no BuildKit cache mount, so this builds on any
# Docker engine including Railway's Metal builder (no BuildKit support).
RUN pip install --prefer-binary --no-cache-dir -r requirements.txt

COPY . .

# Create a non-root user and own the working directory
RUN adduser --system --no-create-home --group appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8182
CMD ["gunicorn", "--bind", "0.0.0.0:8182", "--workers", "1", "--threads", "2", "--timeout", "120", "--max-requests", "500", "--max-requests-jitter", "50", "core.app:create_app()"]
