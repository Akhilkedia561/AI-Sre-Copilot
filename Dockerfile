# Multi-stage build. Stage 1 downloads the embeddings model so the runtime
# image doesn't need internet access to boot.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.txt .
RUN pip install --user -r requirements.txt

# Pre-download the sentence-transformers model into the user cache
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('all-MiniLM-L6-v2')"

# ---------- Runtime image ---------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/appuser/.local/bin:$PATH

RUN useradd --create-home appuser
USER appuser
WORKDIR /app

# Copy installed packages + model cache from builder
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --from=builder --chown=appuser:appuser /root/.cache /home/appuser/.cache

# Copy application code
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser runbooks ./runbooks

EXPOSE 8000

# Runtime dir for Chroma persistence
VOLUME ["/data"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
