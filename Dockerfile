# syntax=docker/dockerfile:1
FROM python:3.11-slim
WORKDIR /app

# Install build deps needed by some packages
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# BuildKit cache mount keeps pip downloads between rebuilds (much faster)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefer-binary -r requirements.txt

COPY . .
EXPOSE 8182
CMD ["python", "server_v5.py"]
