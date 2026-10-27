import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.core import config

logger = logging.getLogger("monitoring")

MONITORING_LOG_FILE = Path(config.MEMORY_DIR) / "monitoring_logs.jsonl"


@dataclass
class AgentSpan:
    """Span di monitoraggio per una sessione agente."""
    session_id: str
    thread_id: str
    task: str
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    end_time: Optional[datetime] = None
    llm_latency_ms: float = 0.0
    tool_calls: List[dict] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retrieval_hit_rate: float = 1.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "task": self.task,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "llm_latency_ms": self.llm_latency_ms,
            "tool_calls": self.tool_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "retrieval_hit_rate": self.retrieval_hit_rate,
            "error": self.error
        }

def log_span(span: AgentSpan):
    """Logga uno span di monitoraggio in formato JSONL."""
    try:
        log_path = MONITORING_LOG_FILE
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(span.to_dict()) + "\n")
        logger.info(f"Span loggato: {span.session_id} (latency={span.llm_latency_ms:.0f}ms, tokens={span.prompt_tokens + span.completion_tokens})")
        check_anomalies(span)
    except Exception as e:
        logger.warning(f"Impossibile scrivere span di monitoraggio: {e}")

def check_anomalies(span: AgentSpan, thresholds: dict = None):
    """Controlla se lo span supera le soglie di anomalia."""
    thresholds = thresholds or {
        "max_latency_ms": 10000.0,
        "max_tokens": 50000,
        "max_tool_failure_rate": 0.2
    }
    if span.llm_latency_ms > thresholds["max_latency_ms"]:
        logger.warning(f"⚠️ ALERT: Latency anomaly {span.llm_latency_ms:.0f}ms > {thresholds['max_latency_ms']}ms")
    total_tokens = span.prompt_tokens + span.completion_tokens
    if total_tokens > thresholds["max_tokens"]:
        logger.warning(f"⚠️ ALERT: Token anomaly {total_tokens} > {thresholds['max_tokens']}")


def analyze_monitoring_logs(log_file: str = None) -> Dict:
    """Analizza i log di monitoring in formato JSONL e calcola metriche aggregate P50/P90/P99."""
    target_path = Path(log_file) if log_file else MONITORING_LOG_FILE
    if not target_path.exists():
        return {
            "status": "no_logs",
            "message": f"Log file non trovato: {target_path}"
        }

    spans = []
    with open(target_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    spans.append(json.loads(line))
                except Exception:
                    pass

    if not spans:
        return {"status": "empty", "total_sessions": 0}

    latencies = sorted([s.get("llm_latency_ms", 0.0) for s in spans])
    p50 = latencies[int(len(latencies) * 0.50)] if latencies else 0.0
    p90 = latencies[int(len(latencies) * 0.90)] if latencies else 0.0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0.0

    total_prompt_tokens = sum(s.get("prompt_tokens", 0) for s in spans)
    total_completion_tokens = sum(s.get("completion_tokens", 0) for s in spans)

    total_tool_calls = sum(len(s.get("tool_calls", [])) for s in spans)
    failed_tool_calls = sum(1 for s in spans for tc in s.get("tool_calls", []) if not tc.get("success", True))
    tool_failure_rate = failed_tool_calls / total_tool_calls if total_tool_calls > 0 else 0.0

    avg_hit_rate = sum(s.get("retrieval_hit_rate", 1.0) for s in spans) / len(spans) if spans else 1.0

    return {
        "status": "ok",
        "total_sessions": len(spans),
        "latency_p50_ms": round(p50, 2),
        "latency_p90_ms": round(p90, 2),
        "latency_p99_ms": round(p99, 2),
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_prompt_tokens + total_completion_tokens,
        "total_tool_calls": total_tool_calls,
        "tool_call_failure_rate": round(tool_failure_rate, 4),
        "avg_retrieval_hit_rate": round(avg_hit_rate, 4)
    }

if __name__ == "__main__":
    metrics = analyze_monitoring_logs()
    print(json.dumps(metrics, indent=2))
