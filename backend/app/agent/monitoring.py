import json
import logging
from pathlib import Path
from typing import Dict

from app.core import config

logger = logging.getLogger("analyze_monitoring")

MONITORING_LOG_FILE = Path(config.MEMORY_DIR) / "monitoring_logs.jsonl"

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
