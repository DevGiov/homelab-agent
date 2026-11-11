# ==============================================================================
# homelab-agent — Makefile
# Punto d'ingresso unificato per setup e deploy.
# ==============================================================================

COMPOSE        ?= docker compose
COMPOSE_PROD   := $(COMPOSE) -f docker-compose.prod.yml
COMPOSE_DEV    := $(COMPOSE) -f docker-compose.dev.yml
SETUP_SCRIPT   := scripts/setup-env.sh
BACKEND_ENV    := backend/.env
ROOT_ENV       := .env

BACKEND_VENV   := backend/.venv

# Modello di embedding per i test locali. I test bloccano la rete, quindi il modello deve essere già su disco:
# il default di fastembed è una cartella in /tmp, che si svuota al riavvio e fa andare la suite in timeout
export FASTEMBED_CACHE_PATH ?= $(HOME)/.cache/fastembed

.PHONY: help setup venv embed-model test lint test-container eval eval-compare deploy deploy-backend deploy-frontend dev down logs rotate-key clean

# ── Default ──────────────────────────────────────────────────────────────────

help: ## Mostra questo help
	@echo ""
	@echo "  homelab-agent — targets disponibili"
	@echo "  ───────────────────────────────────────"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ── Setup ────────────────────────────────────────────────────────────────────

setup: ## Setup interattivo: genera backend/.env e root .env con API key
	@bash $(SETUP_SCRIPT)

$(BACKEND_ENV):
	@echo "⚠  backend/.env mancante — avvio setup interattivo..."
	@bash $(SETUP_SCRIPT)

# ── Sviluppo locale & test ───────────────────────────────────────────────────

venv: ## Ricrea backend/.venv (Python 3.12, come Docker e CI) con le dipendenze dev
	rm -rf $(BACKEND_VENV)
	uv venv -p 3.12 $(BACKEND_VENV)
	uv pip install -p $(BACKEND_VENV) -r backend/requirements-dev.txt

embed-model: ## Scarica il modello di embedding in FASTEMBED_CACHE_PATH (rete solo la prima volta)
	@mkdir -p $(FASTEMBED_CACHE_PATH)
	@cd backend && .venv/bin/python -c "from app.memory.vector_store import EMBEDDING_MODEL; from fastembed import TextEmbedding; TextEmbedding(EMBEDDING_MODEL)"

test: embed-model ## pytest (backend) + Vitest (frontend); ARGS va a pytest: make test ARGS="tests/test_x.py -q"
	cd backend && .venv/bin/python -m pytest $(ARGS)
	cd frontend && npm test

lint: ## Ruff (backend) + oxlint (frontend)
	cd backend && .venv/bin/python -m ruff check .
	cd frontend && npm run lint

test-container: ## Esegue pytest nel container di test isolato (CT 125)
	$(COMPOSE_PROD) run --rm --build backend-test $(ARGS)

eval: ## Valuta i modelli nel backend avviato: make eval MODELS=A,B ARGS="--suites routing,tools --repeat 3"
	$(COMPOSE_PROD) exec backend python -m app.evals run --models $(MODELS) $(ARGS)

eval-compare: ## Tabella Markdown: per ogni modello, l'ultimo risultato di ogni suite
	$(COMPOSE_PROD) exec backend python -m app.evals compare

# ── Deploy produzione ────────────────────────────────────────────────────────

deploy: $(BACKEND_ENV) ## Build e avvia tutto lo stack (prod)
	$(COMPOSE_PROD) build
	$(COMPOSE_PROD) up -d
	@echo ""
	@echo "✅ Stack avviato. Frontend: http://localhost  Backend: http://localhost:8090"

deploy-backend: $(BACKEND_ENV) ## Build e avvia solo il backend (prod)
	$(COMPOSE_PROD) build backend
	$(COMPOSE_PROD) up -d backend

deploy-frontend: $(BACKEND_ENV) ## Build e avvia solo il frontend (prod)
	$(COMPOSE_PROD) build frontend
	$(COMPOSE_PROD) up -d frontend

# ── Sviluppo ─────────────────────────────────────────────────────────────────

dev: $(BACKEND_ENV) ## Avvia lo stack in modalità sviluppo (hot-reload)
	$(COMPOSE_DEV) up --build

dev-d: $(BACKEND_ENV) ## Avvia lo stack dev in background
	$(COMPOSE_DEV) up --build -d

# ── Gestione ─────────────────────────────────────────────────────────────────

down: ## Ferma tutti i container
	-$(COMPOSE_PROD) down 2>/dev/null
	-$(COMPOSE_DEV) down 2>/dev/null

logs: ## Tail dei log di tutti i servizi
	@if $(COMPOSE_PROD) ps -q 2>/dev/null | grep -q .; then \
		$(COMPOSE_PROD) logs -f --tail=100; \
	elif $(COMPOSE_DEV) ps -q 2>/dev/null | grep -q .; then \
		$(COMPOSE_DEV) logs -f --tail=100; \
	else \
		echo "Nessun container in esecuzione."; \
	fi

logs-backend: ## Tail dei log del solo backend
	@if $(COMPOSE_PROD) ps -q backend 2>/dev/null | grep -q .; then \
		$(COMPOSE_PROD) logs -f --tail=100 backend; \
	elif $(COMPOSE_DEV) ps -q backend 2>/dev/null | grep -q .; then \
		$(COMPOSE_DEV) logs -f --tail=100 backend; \
	else \
		echo "Backend non in esecuzione."; \
	fi

logs-frontend: ## Tail dei log del solo frontend
	@if $(COMPOSE_PROD) ps -q frontend 2>/dev/null | grep -q .; then \
		$(COMPOSE_PROD) logs -f --tail=100 frontend; \
	elif $(COMPOSE_DEV) ps -q frontend 2>/dev/null | grep -q .; then \
		$(COMPOSE_DEV) logs -f --tail=100 frontend; \
	else \
		echo "Frontend non in esecuzione."; \
	fi

# ── Rotazione chiave ────────────────────────────────────────────────────────

rotate-key: ## Genera una nuova API key e ricostruisce lo stack
	@NEW_KEY=$$(openssl rand -hex 32) && \
	sed -i "s/^API_SECRET_KEY=.*/API_SECRET_KEY=$$NEW_KEY/" $(BACKEND_ENV) && \
	echo "API_SECRET_KEY=$$NEW_KEY" > $(ROOT_ENV) && \
	echo "🔑 Nuova chiave generata: $${NEW_KEY:0:12}..." && \
	echo "♻️  Ricostruzione stack..."
	$(COMPOSE_PROD) build
	$(COMPOSE_PROD) up -d
	@echo "✅ Chiave ruotata e stack riavviato."

# ── Pulizia ──────────────────────────────────────────────────────────────────

clean: down ## Ferma i container e rimuove volumi
	-$(COMPOSE_PROD) down -v 2>/dev/null
	-$(COMPOSE_DEV) down -v 2>/dev/null
