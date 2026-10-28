"""Test delle metriche di monitoring (Fase 4)."""
import json

from app.agent.monitoring import AgentSpan, analyze_monitoring_logs


def test_monitoring_log_aggregation(tmp_path):
    log_file = tmp_path / "monitoring_logs.jsonl"
    spans = [
        AgentSpan("sess_1", "thread_1", "Lista container", llm_latency_ms=150.0, prompt_tokens=100, completion_tokens=50),
        AgentSpan("sess_2", "thread_1", "Allocazione IP", llm_latency_ms=300.0, prompt_tokens=200, completion_tokens=80),
        AgentSpan("sess_3", "thread_2", "Creazione LXC", llm_latency_ms=500.0, prompt_tokens=250, completion_tokens=120),
    ]
    log_file.write_text("".join(json.dumps(s.to_dict()) + "\n" for s in spans), encoding="utf-8")

    metrics = analyze_monitoring_logs(str(log_file))

    assert metrics["status"] == "ok"
    assert metrics["total_sessions"] == 3
    assert metrics["latency_p50_ms"] >= 150.0
    assert metrics["total_tokens"] == (100 + 50) + (200 + 80) + (250 + 120)
