"""Costo delle chiamate al modello: prezzi per modello, tetti di spesa mensili e spesa del mese.

È la nostra contabilità (token per prezzo), non il saldo vero dell'account del provider. Prezzi e tetti sono
impostazioni modificate dalla UI: stanno in `mcp.db` accanto alle altre, non in `metrics.db`, le cui righe la
retention elimina. Il costo di una chiamata si calcola quando viene registrata, col prezzo di quel momento, e si
salva in `llm_calls.cost_usd`: cambiare un prezzo non riscrive il passato.
"""
import logging
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.core.config import settings
from app.observability import store

logger = logging.getLogger("llm_costs")

# Scope del tetto che somma la spesa di tutti i provider
TOTAL_SCOPE = "total"

_TOKENS_PER_PRICE_UNIT = 1_000_000


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = Path(settings.mcp_db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_costs_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS model_prices ("
            " provider TEXT NOT NULL, model TEXT NOT NULL,"
            " input_per_mtok REAL NOT NULL CHECK (input_per_mtok >= 0),"   # dollari per milione di token di prompt
            " cached_per_mtok REAL NOT NULL CHECK (cached_per_mtok >= 0),"  # ... di prompt letto dalla cache
            " output_per_mtok REAL NOT NULL CHECK (output_per_mtok >= 0),"  # ... di risposta
            " updated_at TEXT NOT NULL, PRIMARY KEY (provider, model))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS spend_ceilings ("
            " scope TEXT PRIMARY KEY,"  # nome di un provider, oppure `total`
            " monthly_usd REAL NOT NULL CHECK (monthly_usd > 0),"
            " updated_at TEXT NOT NULL)"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _amount(value: Any, name: str, positive: bool = False) -> float:
    """Un importo finito e non negativo (o positivo): altrimenti ValueError."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name}: serve un numero.")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name}: deve essere {'maggiore di' if positive else 'almeno'} zero.")
    return float(value)


def _name(value: Any, what: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{what} mancante.")
    return value


# --- Prezzi --------------------------------------------------------------------------------------

def list_prices() -> List[Dict[str, Any]]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM model_prices ORDER BY provider, model")]


def get_price(provider: str, model: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM model_prices WHERE provider = ? AND model = ?", (provider, model)).fetchone()
    return dict(row) if row else None


def set_price(provider: str, model: str, input_per_mtok: Any, cached_per_mtok: Any, output_per_mtok: Any) -> Dict[str, Any]:
    """Imposta il prezzo di un modello, in dollari per milione di token; sostituisce quello che c'era."""
    provider, model = _name(provider, "Provider"), _name(model, "Modello")
    prices = (_amount(input_per_mtok, "input_per_mtok"), _amount(cached_per_mtok, "cached_per_mtok"),
              _amount(output_per_mtok, "output_per_mtok"))
    with _connect() as conn:
        conn.execute(
            "INSERT INTO model_prices (provider, model, input_per_mtok, cached_per_mtok, output_per_mtok, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(provider, model) DO UPDATE SET input_per_mtok = excluded.input_per_mtok,"
            " cached_per_mtok = excluded.cached_per_mtok, output_per_mtok = excluded.output_per_mtok,"
            " updated_at = excluded.updated_at",
            (provider, model, *prices, _now_iso()),
        )
    logger.info(f"Prezzo di '{provider}/{model}': {prices[0]} / {prices[1]} / {prices[2]} dollari per milione di token")
    return get_price(provider, model)


def delete_price(provider: str, model: str) -> bool:
    with _connect() as conn:
        return bool(conn.execute("DELETE FROM model_prices WHERE provider = ? AND model = ?", (provider, model)).rowcount)


def call_cost(provider: str, model: Optional[str], prompt_tokens: int, cached_tokens: int, completion_tokens: int) -> float:
    """Costo in dollari di una chiamata, col prezzo di adesso; 0 se il modello non ha un prezzo.

    Convenzione dei token: `prompt_tokens` INCLUDE quelli in cache (llama.cpp: `prompt_n + cache_n`; API OpenAI:
    `prompt_tokens` comprende `cached_tokens`). I token di prompt non in cache costano `input_per_mtok`, quelli in
    cache `cached_per_mtok`, quelli di risposta (ragionamento compreso) `output_per_mtok`. Una chiamata fallita che
    ha riportato token costa quello che ha usato."""
    price = get_price(provider, model) if model else None
    if price is None:
        return 0.0
    cached = min(max(cached_tokens or 0, 0), max(prompt_tokens or 0, 0))
    uncached = max(prompt_tokens or 0, 0) - cached
    return (uncached * price["input_per_mtok"] + cached * price["cached_per_mtok"]
            + max(completion_tokens or 0, 0) * price["output_per_mtok"]) / _TOKENS_PER_PRICE_UNIT


# --- Tetti ----------------------------------------------------------------------------------------

def list_ceilings() -> Dict[str, float]:
    with _connect() as conn:
        return {r["scope"]: r["monthly_usd"] for r in conn.execute("SELECT scope, monthly_usd FROM spend_ceilings")}


def set_ceiling(scope: str, monthly_usd: Any) -> float:
    """Imposta il tetto mensile in dollari di un provider o del totale (`total`); sostituisce quello che c'era."""
    scope = _name(scope, "Scope")
    amount = _amount(monthly_usd, "monthly_usd", positive=True)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO spend_ceilings (scope, monthly_usd, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(scope) DO UPDATE SET monthly_usd = excluded.monthly_usd, updated_at = excluded.updated_at",
            (scope, amount, _now_iso()),
        )
    logger.info(f"Tetto di spesa '{scope}': {amount} dollari al mese")
    return amount


def delete_ceiling(scope: str) -> bool:
    with _connect() as conn:
        return bool(conn.execute("DELETE FROM spend_ceilings WHERE scope = ?", (scope,)).rowcount)


def month_bounds(now: Optional[datetime] = None) -> tuple:
    """Inizio del mese di `now` (UTC) e inizio del successivo, come ISO: il mese è [inizio, fine)."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end


def month_spend(now: Optional[datetime] = None) -> Dict[str, float]:
    """Spesa del mese di calendario UTC di `now`, già registrata nelle chiamate: {provider: dollari, "total": dollari}."""
    start, end = month_bounds(now)
    rows = store.select(
        "SELECT provider, SUM(cost_usd) AS usd FROM llm_calls WHERE ts >= ? AND ts < ? AND cost_usd IS NOT NULL GROUP BY provider",
        (start.isoformat(), end.isoformat()),
    )
    spend = {r["provider"] or "?": r["usd"] or 0.0 for r in rows}
    spend[TOTAL_SCOPE] = sum(spend.values())
    return spend


def reached_scopes(ceilings: Dict[str, float], spend: Dict[str, float]) -> Dict[str, bool]:
    """Per ogni scope che ha un tetto: la spesa del mese lo ha raggiunto?"""
    return {scope: spend.get(scope, 0.0) >= limit for scope, limit in ceilings.items()}


def ceiling_reached(provider: str, now: Optional[datetime] = None) -> Optional[str]:
    """Quale tetto ha raggiunto la spesa del mese: `"provider"` (quello del provider), `"total"` (quello totale) o None.

    Guarda la spesa già registrata: una chiamata lunga può superare il tetto di quanto costa lei stessa."""
    ceilings = list_ceilings()
    if not ceilings:
        return None
    reached = reached_scopes(ceilings, month_spend(now))
    if reached.get(provider):
        return "provider"
    if reached.get(TOTAL_SCOPE):
        return "total"
    return None


def delete_provider(provider: str) -> None:
    """Toglie prezzi e tetto di un provider eliminato. Le chiamate già registrate e il loro costo restano."""
    with _connect() as conn:
        conn.execute("DELETE FROM model_prices WHERE provider = ?", (provider,))
        conn.execute("DELETE FROM spend_ceilings WHERE scope = ?", (provider,))
