import logging
import time

import pytest

from graph import build_graph
from tool_catalog import get_tool_catalog
from tool_schemas import validate_tool_args

# Valutazione end-to-end contro LLM/MetaMCP reali: esclusa dalla suite di default
pytestmark = [pytest.mark.live, pytest.mark.timeout(600)]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_dynamic_tool_selection")

def test_dynamic_tool_selection():
    print("==========================================")
    print("TEST: Dynamic Tool Selection & Self-Correction")
    print("==========================================")

    app = build_graph()
    test_thread = f"test_dynamic_{int(time.time())}"

    # 1. Test phrasing variants for container listing
    variants = [
        "Lista i container attivi",
        "Mostrami tutti i container",
        "Quali container ci sono sul server?",
        "Elenco container in esecuzione"
    ]

    for idx, v in enumerate(variants):
        print(f"\nTesting variant {idx+1}: '{v}'")
        v_thread = f"test_dynamic_var_{idx}_{int(time.time())}"
        initial_state = {
            "task": v,
            "thread_id": v_thread,
            "force_mode": "act",
            "execute": False,
            "agent_id": None,
            "memory_context": None,
            "mode": "",
            "plan": {},
            "tool_result": None,
            "final_response": ""
        }
        config = {"configurable": {"thread_id": v_thread}}
        final_state = app.invoke(initial_state, config=config)

        mode = final_state.get("mode")
        plan = final_state.get("plan", {})
        tool_selected = plan.get("tool_name")

        print(f"Query: '{v}' -> Selected Tool: '{tool_selected}' (Mode: {mode})")
        assert tool_selected == "proxmox-mcp__list_containers", f"Failed for '{v}': expected 'proxmox-mcp__list_containers', got '{tool_selected}'"

    # 2. Test ambiguous request (No tool needed)
    ambiguous_query = "Scrivi una poesia sul tramonto nell'homelab"
    print(f"\nTesting ambiguous query: '{ambiguous_query}'")
    state_ambiguous = app.invoke({
        "task": ambiguous_query,
        "thread_id": test_thread,
        "force_mode": "act",
        "execute": False,
        "agent_id": None,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": ""
    }, config={"configurable": {"thread_id": test_thread}})

    plan_ambiguous = state_ambiguous.get("plan", {})
    assert plan_ambiguous.get("tool_needed") is False or not plan_ambiguous.get("tool_name"), "Expected tool_needed=False for non-tool request"
    print("✅ Ambiguous request correctly identified as tool_needed=False!")

    # 3. Test jsonschema argument validation helper
    tools = get_tool_catalog()
    assert len(tools) > 0, "Tool catalog is empty!"

    # Valid call to get_container_status
    val_ok = validate_tool_args("proxmox-mcp__get_container_status", {"vmid": 100}, tools)
    assert val_ok is None, f"Validation failed for valid args: {val_ok}"

    # Invalid call with wrong type or missing required args (if schema defines required)
    val_err = validate_tool_args("proxmox-mcp__get_container_status", {"vmid": "not_an_int"}, tools)
    print(f"Validation result for invalid vmid arg: {val_err}")

    print("\n==========================================")
    print("ALL DYNAMIC TOOL SELECTION TESTS PASSED SUCCESSFULLY!")
    print("==========================================")

if __name__ == "__main__":
    test_dynamic_tool_selection()
