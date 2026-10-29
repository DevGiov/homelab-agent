import argparse

from app import startup
from app.agent.graph import build_graph
from app.memory import thread_store


def main():
    parser = argparse.ArgumentParser(description="LangGraph Agent CLI with Mode Router, MetaMCP, SQLite memory and checkpoints")
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

    startup.configure_logging()
    startup.init_storage()
    app = build_graph()
    initial_state = {
        "task": args.task,
        "thread_id": args.thread,
        "force_mode": args.force_mode,
        "memory_context": None,
        "mode": "",
        "plan": {},
        "tool_result": None,
        "final_response": ""
    }

    # Come l'API: il messaggio dell'utente è nella cronologia prima dell'esecuzione, la risposta dopo
    if args.thread:
        thread_store.save_user_message(args.thread, args.task)
    config = {"configurable": {"thread_id": thread_id}}
    final_state = app.invoke(initial_state, config=config)
    if args.thread:
        thread_store.save_assistant_message(args.thread, {"response": final_state.get("final_response", ""), "mode": final_state.get("mode")})
    print("\n--- RISPOSTA FINALE ---")
    print(final_state.get("final_response"))

if __name__ == "__main__":
    main()
