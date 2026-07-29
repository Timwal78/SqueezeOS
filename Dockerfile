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
# Starter plan = 1 instance. Never use --max-requests on a single worker:
# worker recycle = full 502 window → Render healthCheckPath /api/status times
# out at 5s → server_failed → restart thrash (looks like "cold start").
# More threads absorb beastmode/oracle/IAM scan concurrency on catalyst days
# (Fed / BOJ / Korea / JPY risk).
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8182", \
     "--workers", "1", \
     "--threads", "8", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--worker-tmp-dir", "/dev/shm", \
     "core.app:create_app()"]
