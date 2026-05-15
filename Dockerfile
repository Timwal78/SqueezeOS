# syntax=docker/dockerfile:1
FROM python:3.11-slim
WORKDIR /app

# Install build deps needed by some packages
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Plain pip install — no BuildKit cache mount, so this builds on any
# Docker engine including Railway's Metal builder (no BuildKit support).
RUN pip install --prefer-binary --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8182
CMD ["python", "core/app.py"]
