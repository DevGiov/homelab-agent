#!/usr/bin/env bash
# ==============================================================================
# homelab-agent — Setup interattivo
# Genera backend/.env (e root .env per docker-compose) con input dell'utente.
# Se un valore non viene inserito, usa il default (da .env esistente o .env.example).
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_ENV="$ROOT_DIR/backend/.env"
BACKEND_ENV_EXAMPLE="$ROOT_DIR/backend/.env.example"
ROOT_ENV="$ROOT_DIR/.env"

# --- Colori ---
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
RESET='\033[0m'

# --- Utility ---
banner() {
    echo ""
    echo -e "${CYAN}${BOLD}╔══════════════════════════════════════════════════╗${RESET}"
    echo -e "${CYAN}${BOLD}║     homelab-agent — Setup interattivo            ║${RESET}"
    echo -e "${CYAN}${BOLD}╚══════════════════════════════════════════════════╝${RESET}"
    echo ""
}

section() {
    echo ""
    echo -e "${BLUE}${BOLD}  $1${RESET}"
    echo -e "${DIM}  ──────────────────────────────────────${RESET}"
}

# Legge un valore dall'env esistente (se c'è), altrimenti ritorna il default.
read_existing() {
    local key="$1"
    local fallback="$2"
    if [[ -f "$BACKEND_ENV" ]]; then
        local val
        val=$(grep -E "^${key}=" "$BACKEND_ENV" 2>/dev/null | head -1 | cut -d'=' -f2-)
        if [[ -n "$val" ]]; then
            echo "$val"
            return
        fi
    fi
    echo "$fallback"
}

# Chiede un valore all'utente, mostrando il default tra parentesi quadre.
# Se l'utente preme Enter, usa il default.
ask() {
    local var_name="$1"
    local prompt_text="$2"
    local default_val="$3"
    local is_secret="${4:-false}"

    if [[ "$is_secret" == "true" && -n "$default_val" && "$default_val" != "change-me" && "$default_val" != "" ]]; then
        # Mostra solo gli ultimi 6 caratteri per i segreti
        local masked
        if [[ ${#default_val} -gt 6 ]]; then
            masked="***${default_val: -6}"
        else
            masked="$default_val"
        fi
        echo -ne "  ${prompt_text} ${DIM}[${masked}]${RESET}: "
    else
        echo -ne "  ${prompt_text} ${DIM}[${default_val}]${RESET}: "
    fi

    local input
    read -r input
    if [[ -z "$input" ]]; then
        eval "$var_name=\"$default_val\""
    else
        eval "$var_name=\"$input\""
    fi
}

# --- Main ---
banner

# Controlla se esiste già un .env
if [[ -f "$BACKEND_ENV" ]]; then
    echo -e "  ${YELLOW}⚠  backend/.env esistente trovato — i valori attuali saranno usati come default.${RESET}"
    echo -e "  ${DIM}  Premi Enter per mantenere un valore, oppure inserisci uno nuovo.${RESET}"
else
    echo -e "  ${DIM}  Nessun backend/.env trovato — verranno usati i default da .env.example.${RESET}"
    echo -e "  ${DIM}  Premi Enter per accettare un default, oppure inserisci un valore.${RESET}"
fi

# ── Sicurezza ──

section "🔐 Sicurezza"

# API_SECRET_KEY: genera automaticamente se non esiste o è un placeholder
EXISTING_KEY=$(read_existing "API_SECRET_KEY" "")
if [[ -z "$EXISTING_KEY" || "$EXISTING_KEY" == "change-me" || "$EXISTING_KEY" == "dev-local-key-change-me" ]]; then
    GENERATED_KEY=$(openssl rand -hex 32)
    echo -e "  ${GREEN}✔ API_SECRET_KEY generata automaticamente${RESET}"
    echo -e "  ${DIM}  $GENERATED_KEY${RESET}"
    API_SECRET_KEY="$GENERATED_KEY"
else
    ask API_SECRET_KEY "API_SECRET_KEY" "$EXISTING_KEY" true
fi

ask ALLOW_INSECURE "ALLOW_INSECURE (0=auth richiesta, 1=dev senza auth)" "$(read_existing ALLOW_INSECURE 0)"
ask CORS_ORIGINS "CORS_ORIGINS (origini separate da virgola)" "$(read_existing CORS_ORIGINS "http://localhost:5173,http://localhost:4173")"
ask RATE_LIMIT "RATE_LIMIT" "$(read_existing RATE_LIMIT "30/minute")"

# ── MetaMCP ──

section "🔧 MetaMCP"

ask METAMCP_URL "METAMCP_URL (endpoint streamable-http)" "$(read_existing METAMCP_URL "http://metamcp.example.local:12008/metamcp/MetaMCP/mcp")"
ask METAMCP_URL_HTTP "METAMCP_URL_HTTP (base URL HTTP)" "$(read_existing METAMCP_URL_HTTP "http://metamcp.example.local:12008")"
ask METAMCP_API_KEY "METAMCP_API_KEY" "$(read_existing METAMCP_API_KEY "")" true

# ── LLM ──

section "🧠 LLM"

ask DEFAULT_MODEL "DEFAULT_MODEL" "$(read_existing DEFAULT_MODEL "Qwen3.6-35B-HugeCtx")"
ask LLAMA_CPP_URL "LLAMA_CPP_URL (endpoint OpenAI-compatible)" "$(read_existing LLAMA_CPP_URL "http://llm.example.local:8080/v1")"

# ── Letta ──

section "💾 Letta (memoria conversazionale)"

ask LETTA_URL "LETTA_URL" "$(read_existing LETTA_URL "http://letta.example.local:8083")"
ask LETTA_API_KEY "LETTA_API_KEY" "$(read_existing LETTA_API_KEY "")" true

# ── Storage ──

section "📦 Storage"

ask CHECKPOINT_DB_PATH "CHECKPOINT_DB_PATH" "$(read_existing CHECKPOINT_DB_PATH "/data/checkpoints.db")"
ask TRUNCATION_LIMIT "TRUNCATION_LIMIT (max token contesto)" "$(read_existing TRUNCATION_LIMIT "40000")"

# ── SearXNG ──

section "🔍 SearXNG (ricerca web)"

ask SEARXNG_URL "SEARXNG_URL" "$(read_existing SEARXNG_URL "http://searxng.example.local:8080")"

# ── Firecracker ──

section "🔥 Firecracker (sandbox)"

ask FIRECRACKER_API_URL "FIRECRACKER_API_URL" "$(read_existing FIRECRACKER_API_URL "http://CHANGE_ME:8080")"
ask FIRECRACKER_KERNEL_PATH "FIRECRACKER_KERNEL_PATH" "$(read_existing FIRECRACKER_KERNEL_PATH "/opt/firecracker/vmlinux.bin")"
ask FIRECRACKER_ROOTFS_PATH "FIRECRACKER_ROOTFS_PATH" "$(read_existing FIRECRACKER_ROOTFS_PATH "/opt/firecracker/rootfs.ext4")"

# ── Scrittura file ──

echo ""
section "📝 Scrittura configurazione"

cat > "$BACKEND_ENV" <<EOF
# ===============================================
# homelab-agent backend — configurazione
# Generato da scripts/setup-env.sh
# $(date '+%Y-%m-%d %H:%M:%S')
# ===============================================

# --- Sicurezza ---
API_SECRET_KEY=${API_SECRET_KEY}
ALLOW_INSECURE=${ALLOW_INSECURE}
CORS_ORIGINS=${CORS_ORIGINS}
RATE_LIMIT=${RATE_LIMIT}

# --- MetaMCP ---
METAMCP_URL=${METAMCP_URL}
METAMCP_URL_HTTP=${METAMCP_URL_HTTP}
METAMCP_API_KEY=${METAMCP_API_KEY}

# --- LLM ---
DEFAULT_MODEL=${DEFAULT_MODEL}
LLAMA_CPP_URL=${LLAMA_CPP_URL}

# --- Letta ---
LETTA_URL=${LETTA_URL}
LETTA_API_KEY=${LETTA_API_KEY}

# --- Storage ---
CHECKPOINT_DB_PATH=${CHECKPOINT_DB_PATH}
TRUNCATION_LIMIT=${TRUNCATION_LIMIT}

# --- SearXNG ---
SEARXNG_URL=${SEARXNG_URL}

# --- Firecracker ---
FIRECRACKER_API_URL=${FIRECRACKER_API_URL}
FIRECRACKER_KERNEL_PATH=${FIRECRACKER_KERNEL_PATH}
FIRECRACKER_ROOTFS_PATH=${FIRECRACKER_ROOTFS_PATH}
EOF

echo -e "  ${GREEN}✔ backend/.env scritto${RESET}"

# Root .env per docker-compose (solo la chiave condivisa)
cat > "$ROOT_ENV" <<EOF
# Generato da scripts/setup-env.sh — usato da docker-compose per interpolazione.
# NON modificare manualmente: usa 'make setup' o 'make rotate-key'.
API_SECRET_KEY=${API_SECRET_KEY}
EOF

echo -e "  ${GREEN}✔ .env (root) scritto — chiave condivisa per docker-compose${RESET}"

echo ""
echo -e "${GREEN}${BOLD}  ✅ Setup completato!${RESET}"
echo -e "${DIM}  Usa 'make deploy' per avviare lo stack, oppure 'make dev' per lo sviluppo.${RESET}"
echo ""
