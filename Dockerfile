# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

# psycopg2-binary needs libpq's runtime, not the full -dev headers (that's only
# needed to build psycopg2 from source, which the binary wheel avoids).
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src/ ./src/
COPY backend/ ./backend/
COPY data/raw/ ./data/raw/

RUN pip install --no-cache-dir .

# Bake the embedding model into the image at build time instead of downloading
# it on first request -- closes the same cold-start gap identified during the
# project's own optimization review (every fresh process previously reloaded it
# from disk/network before serving a single request).
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/e5-base-v2')"

ENV PYTHONPATH=/app/src:/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
