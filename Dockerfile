FROM python:3.11-slim AS base

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg postgresql-client && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY . .

EXPOSE 8888
CMD ["drama", "serve"]
