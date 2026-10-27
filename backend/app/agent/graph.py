"""Grafo LangGraph dell'agente: intake → memoria → routing → prefetch web → sottografo di modalità → risposta."""
import sqlite3
from functools import lru_cache

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from app.agent.nodes.act import act_graph_node
from app.agent.nodes.ask import ask_graph_node
from app.agent.nodes.chat import chat_graph_node
from app.agent.nodes.commit_memory import commit_memory_node
from app.agent.nodes.intake import intake_node
from app.agent.nodes.plan import plan_graph_node
from app.agent.nodes.respond import respond_node
from app.agent.nodes.retrieve_memory import retrieve_memory_node
from app.agent.nodes.routing import mode_router_node
from app.agent.nodes.web_prefetch import web_prefetch_node
from app.agent.state import AgentState
from app.core.config import settings


@lru_cache(maxsize=1)
def get_checkpointer() -> SqliteSaver:
    """Checkpointer condiviso; lo schema (checkpoints/writes) lo crea app.startup.init_storage."""
    return SqliteSaver(sqlite3.connect(settings.checkpoint_db_path, check_same_thread=False))


def route_to_subgraph(state: AgentState) -> str:
    """Conditional edge decision based on mode."""
    mode = state.get("mode", "plan")
    if mode in ["chat", "ask", "act", "plan"]:
        return f"{mode}_graph"
    return "plan_graph"

def build_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("intake", intake_node)
    workflow.add_node("retrieve_memory", retrieve_memory_node)
    workflow.add_node("web_prefetch", web_prefetch_node)
    workflow.add_node("mode_router_node", mode_router_node)

    # Subgraph nodes
    workflow.add_node("chat_graph", chat_graph_node)
    workflow.add_node("ask_graph", ask_graph_node)
    workflow.add_node("act_graph", act_graph_node)
    workflow.add_node("plan_graph", plan_graph_node)

    workflow.add_node("respond", respond_node)
    workflow.add_node("commit_memory", commit_memory_node)

    workflow.set_entry_point("intake")
    workflow.add_edge("intake", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "mode_router_node")
    workflow.add_edge("mode_router_node", "web_prefetch")

    workflow.add_conditional_edges(
        "web_prefetch",
        route_to_subgraph,
        {
            "chat_graph": "chat_graph",
            "ask_graph": "ask_graph",
            "act_graph": "act_graph",
            "plan_graph": "plan_graph"
        }
    )

    workflow.add_edge("chat_graph", "respond")
    workflow.add_edge("ask_graph", "respond")
    workflow.add_edge("act_graph", "respond")
    workflow.add_edge("plan_graph", "respond")

    workflow.add_edge("respond", "commit_memory")
    workflow.add_edge("commit_memory", END)

    return workflow.compile(checkpointer=get_checkpointer())
