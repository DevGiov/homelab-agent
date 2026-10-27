"""Test delle ottimizzazioni di Fase 4: retrieval ibrido, metriche di monitoring, estrazione fatti salienti."""
import json
from unittest.mock import patch

from app.agent.graph import AgentSpan, extract_salient_facts
from app.agent.monitoring import analyze_monitoring_logs
from app.memory.letta_client import BM25Retriever, reciprocal_rank_fusion


def test_bm25_exact_match_and_rrf_fusion():
    docs = [
        "Container LXC 100 con Debian 12 ed 8GB di RAM",
        "Assegnato indirizzo IP statico 192.168.1.180 da IPAM",
        "Configurato record DNS test-service.home.lab su Pi-hole",
        "Host proxy configurato su Nginx Proxy Manager per porta 8080",
    ]
    bm25 = BM25Retriever()
    bm25.index(docs)

    results = bm25.search("192.168.1.180", k=2)
    assert results
    assert "192.168.1.180" in docs[results[0][0]]

    bm25_ranks = [(1, 4.5), (0, 2.1), (2, 1.0)]
    dense_ranks = [(0, 0.95), (1, 0.80), (3, 0.60)]
    fused = reciprocal_rank_fusion([bm25_ranks, dense_ranks], k=60, top_n=3)
    assert len(fused) == 3


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


def test_extract_salient_facts_parses_llm_bullets():
    llm_output = {"content": "- Preferisce Debian per i container LXC\n- ok\n* Usa un homelab Proxmox\n"}
    with patch("app.agent.graph._call_llm", return_value=llm_output) as mock_llm:
        facts = extract_salient_facts(
            "Preferisco sempre usare Debian per tutti i container LXC del mio Homelab.",
            "Ricevuto! Userò Debian come distribuzione predefinita.",
            "",
        )

    mock_llm.assert_called_once()
    # Le righe troppo corte ("ok") vengono scartate, i marker di elenco rimossi
    assert facts == ["Preferisce Debian per i container LXC", "Usa un homelab Proxmox"]


def test_extract_salient_facts_skips_llm_on_empty_input():
    with patch("app.agent.graph._call_llm") as mock_llm:
        assert extract_salient_facts("", "risposta", "") == []
    mock_llm.assert_not_called()
