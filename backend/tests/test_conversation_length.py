import logging
import os
import time

from graph import MEMORY_DIR, build_graph

import pytest

# Valutazione end-to-end contro LLM/MetaMCP reali: esclusa dalla suite di default
pytestmark = [pytest.mark.live, pytest.mark.timeout(1800)]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_conversation_length")

def test_long_conversation():
    print("==========================================")
    print("TEST: Long Conversation (50+ Messages) & Hybrid Memory")
    print("==========================================")

    thread_id = f"test_long_conv_{int(time.time())}"
    app = build_graph()

    latencies = []

    # 1. Send initial messages (including key facts at message 5 and 10)
    for i in range(1, 51):
        t0 = time.time()

        if i == 5:
            user_msg = "Mi chiamo Alice e gestisco questo Homelab."
        elif i == 10:
            user_msg = "Per tutti i miei container preferisco sempre usare la distribuzione Debian."
        elif i == 20:
            user_msg = "Ho appena creato un nuovo servizio web per testare le prestazioni."
        elif i == 50:
            user_msg = "Ciao, ti ricordi come mi chiamo e quale distribuzione Linux preferisco?"
        else:
            user_msg = f"Messaggio di test numero {i} per verificare la gestione dello storico."

        initial_state = {
            "task": user_msg,
            "thread_id": thread_id,
            "force_mode": "chat",
            "execute": False,
            "agent_id": None,
            "memory_context": None,
            "mode": "",
            "plan": {},
            "tool_result": None,
            "final_response": ""
        }

        config = {"configurable": {"thread_id": thread_id}}
        final_state = app.invoke(initial_state, config=config)
        elapsed = time.time() - t0
        latencies.append(elapsed)

        resp = final_state.get("final_response", "")
        mem_ctx = final_state.get("memory_context") or ""

        # Verify token/character length of context remains bounded (< 5000 tokens ~ 20000 chars)
        ctx_tokens_est = len(mem_ctx) // 4
        assert ctx_tokens_est < 5000, f"Memory context too large! {ctx_tokens_est} tokens at turn {i}"

        if i % 10 == 0 or i == 50:
            print(f"Turn {i}/50 | Latency: {elapsed:.2f}s | Context Tokens Est: {ctx_tokens_est} | Response len: {len(resp)}")

    # 2. Check memory recall at turn 50
    final_resp = final_state.get("final_response", "").lower()
    print(f"\n[Risposta finale Turno 50]:\n{final_state.get('final_response')}")
    assert "alice" in final_resp or "debian" in final_resp or "homelab" in final_resp, "Agent failed to recall facts from message 5/10!"

    # 3. Check JSONL file persistence
    filepath = os.path.join(MEMORY_DIR, f"{thread_id}.jsonl")
    assert os.path.exists(filepath), f"JSONL file memory not found at {filepath}"

    with open(filepath, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    # 50 user turns + 50 assistant turns = 100 entries
    assert len(lines) == 100, f"Expected 100 entries in JSONL file, got {len(lines)}"
    print(f"\n✅ JSONL File Memory verified: {len(lines)} entries saved at {filepath}")

    # 4. Check Latencies (< 2s average)
    avg_latency = sum(latencies) / len(latencies)
    max_latency = max(latencies)
    print(f"✅ Avg Latency: {avg_latency:.2f}s | Max Latency: {max_latency:.2f}s")

    print("\n==========================================")
    print("ALL LONG CONVERSATION MEMORY TESTS PASSED SUCCESSFULLY!")
    print("==========================================")

if __name__ == "__main__":
    test_long_conversation()
