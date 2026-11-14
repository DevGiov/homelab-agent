from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    task: str
    images: Optional[List[str]]
    thread_id: Optional[str]
    force_mode: Optional[str]
    reasoning_budget: Optional[int]
    model: Optional[str]
    execute: Optional[bool]
    web_search: Optional[Any]
    web_prefetch_data: Optional[Dict[str, Any]]
    web_prefetch_metadata: Optional[Dict[str, Any]]
    routing_context: Optional[str]
    memory_context: Optional[str]
    previous_mode: Optional[str]
    last_tool_used: Optional[str]
    route_decision: Optional[Dict[str, Any]]
    mode: str
    plan: Dict[str, Any]
    plan_structure: Optional[Dict[str, Any]]
    tool_result: Optional[Any]
    execution_trace: Optional[List[Dict[str, Any]]]
    rollback_trace: Optional[List[Dict[str, Any]]]
    final_response: str
    reasoning_content: Optional[str]
    incognito: Optional[bool]
    approval_required: Optional[bool]
    request_id: Optional[str]
    approval_prompt: Optional[str]
    command_preview: Optional[str]
    command_prefix: Optional[str]
    risk_reason: Optional[str]
    security_mode: Optional[str]
    # Sensibilità (app.security.flows, Tag.to_dict): di tutto ciò che il turno ha in contesto, e della parte che vede
    # il router (richiesta e ultimi messaggi, senza la memoria)
    tag: Optional[Dict[str, Any]]
    routing_tag: Optional[Dict[str, Any]]
    # La sola richiesta (livello della conversazione, rilevatori, immagini): con `routing_tag` e `routing_context` è ciò
    # che può leggere la chiamata che riscrive un'uscita di dati senza la memoria (AgentLoop._clean_call)
    request_tag: Optional[Dict[str, Any]]
