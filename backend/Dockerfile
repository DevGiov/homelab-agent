FROM python:3.12-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modello di embedding incluso nell'immagine: nessun download a runtime né dipendenza da HuggingFace.
# Deve coincidere con vector_store.EMBEDDING_MODEL (verificato da tests/test_memory_rag.py)
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"

# Test: dipendenze di sviluppo sopra la stessa base; il codice arriva dal bind mount
FROM base AS test

ENV PYTHONDONTWRITEBYTECODE=1
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

ENTRYPOINT ["python", "-m", "pytest"]

# Produzione (stage di default)
FROM base AS prod

COPY . .

EXPOSE 8090

CMD ["python", "run_api.py"]
