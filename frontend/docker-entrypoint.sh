#!/bin/sh
# ==============================================================================
# Frontend entrypoint — genera /config.json con la API key iniettata a runtime.
# Questo permette di ruotare la chiave senza ricostruire l'immagine frontend.
# ==============================================================================

CONFIG_PATH="/usr/share/nginx/html/config.json"

# Scrivi config.json con la API key (vuota se non impostata)
cat > "$CONFIG_PATH" <<EOF
{"apiKey":"${API_SECRET_KEY:-}"}
EOF

echo "[entrypoint] config.json generato con API key ${API_SECRET_KEY:+(set)}${API_SECRET_KEY:-(vuota)}"

# Avvia nginx
exec nginx -g 'daemon off;'
