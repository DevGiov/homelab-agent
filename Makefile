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

.PHONY: help setup deploy deploy-backend deploy-frontend dev down logs rotate-key clean

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
