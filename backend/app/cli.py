import argparse

from app.agent.graph import build_graph


def main():
    parser = argparse.ArgumentParser(description="LangGraph Agent CLI with Mode Router, MetaMCP, Letta Memory, and SQLite Checkpoint")
    parser.add_argument("task", type=str, help="Il task da eseguire")
    parser.add_argument("--thread", type=str, default=None, help="Thread/Session ID per la memoria persisente e checkpointing")
    parser.add_argument("--force-mode", type=str, default=None, choices=["chat", "ask", "act", "plan"], help="Forza la modalità di instradamento (chat, ask, act, plan)")

    args = parser.parse_args()

    thread_id = args.thread or "default"
    print(f"Task in esecuzione: {args.task}")
    if args.thread:
        print(f"Memoria e Checkpoint attivi per il thread: {args.thread}")
    if args.force_mode:
        print(f"Modalità forzata via CLI: {args.force_mode}")
    print()

    app = build_graph()
    initial_state = {
        "task": args.task,
        "thread_id": args.thread,
        "force_mode": args.force_mode,
        "agent_id": None,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": ""
    }

    config = {"configurable": {"thread_id": thread_id}}
    final_state = app.invoke(initial_state, config=config)
    print("\n--- RISPOSTA FINALE ---")
    print(final_state.get("final_response"))

if __name__ == "__main__":
    main()
