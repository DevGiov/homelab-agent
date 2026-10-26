FROM python:3.12-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
