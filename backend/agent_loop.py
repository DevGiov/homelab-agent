import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import config
from mode_policy import get_mode_policy
from registry.manager import get_registry_manager
from text_utils import clean_synthesis_content
from tool_catalog import format_catalog_for_prompt, format_dynamic_catalog_response
from tool_schemas import ToolSelection, validate_tool_args

logger = logging.getLogger("agent_loop")


def is_tools_discovery_query(query: str) -> bool:
    """Verifica se l'utente sta chiedendo informazioni sui tool o server MCP disponibili.

    ATTENZIONE: deve essere una DOMANDA SUL CATALOGO (es. "quali tool hai?"),
    NON un task che menziona i tool come mezzo (es. "cerca X usando il web search").
    """
    q = query.lower().strip()

    # Marker di TASK: se presenti, la query è un'azione da eseguire, non una
    # domanda sul catalogo — anche se menziona "tool"/"web search".
    task_markers = [
        "dammi", "cerca", "trova", "usando", "utilizzando", "utilizza", "usa ",
        "informazioni su", "notizie", "analizza", "esegui", "crea ", "lancia",
        "aggiornate", "aggiornati", "latest",
    ]
    if any(m in q for m in task_markers):
        return False

    has_target = any(k in q for k in ["mcp", "tool", "tools", "strumenti", "capacità", "funzioni", "comandi"])
    has_intent = any(k in q for k in [
        "quali", "quale", "elenco", "elenca", "lista dei", "lista dei tool",
        "mostra i", "mostrami i", "cosa puoi fare", "hai a disposizione", "di che tool",
    ])
    return has_target and has_intent


def _call_llm_with_phase(fn: Any, prompt: str, system_prompt: Optional[str] = None, reasoning_budget: int = -1, reasoning_phase: Optional[str] = None) -> Any:
    if not fn:
        return None
    try:
        return fn(prompt, system_prompt=system_prompt, reasoning_budget=reasoning_budget, reasoning_phase=reasoning_phase)
    except TypeError:
        return fn(prompt, system_prompt=system_prompt, reasoning_budget=reasoning_budget)


def _normalize_call_signature(tool_name: str, arguments: Dict[str, Any]) -> str:
    if tool_name == "web_search":
        q = str(arguments.get("query", "")).lower().strip().strip('"\'')
        q = " ".join(q.split())
        return f"web_search:{q}"
    return f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"


def _query_jaccard_similarity(q1: str, q2: str) -> float:
    tokens1 = set(re.findall(r"\w+", q1.lower()))
    tokens2 = set(re.findall(r"\w+", q2.lower()))
    if not tokens1 or not tokens2:
        return 0.0
    return len(tokens1 & tokens2) / len(tokens1 | tokens2)



def run_agent_loop(
    task: str,
    mode: str,
    memory_context: Optional[str] = None,
    call_llm_fn: Any = None,
    call_llm_structured_fn: Any = None,
    thread_id: Optional[str] = None,
    web_prefetch_data: Optional[Dict[str, Any]] = None,
    images: Optional[List[str]] = None,
    security_mode: str = "normal",
) -> Dict[str, Any]:
    """
    Esegue il loop ReAct autonomo in base alla ModePolicy della modalità corrente.
    - Se max_tool_calls == 0 (es. chat), risponde direttamente senza tool.
    - Altrimenti cicla: Reason -> Act -> Observe -> Loop fino al raggiungimento di max_tool_calls o final answer.
    """
    policy = get_mode_policy(mode)
    logger.info(f"Avvio agent loop per mode='{mode}' (max_tool_calls={policy.max_tool_calls}, registries={policy.allowed_registries})")

    from graph import stream_queue

    manager = get_registry_manager()
    available_tools = manager.get_tools_for_mode(policy.allowed_registries)
    execution_trace = []

    # Risposta immediata e dinamica per query di verifica tool/MCP disponibili
    if is_tools_discovery_query(task):
        logger.info("Query di discovery tool rilevata: formattazione dinamica del catalogo attivo")
        catalog_reply = format_dynamic_catalog_response(available_tools)
        return {
            "final_response": catalog_reply,
            "execution_trace": [],
            "reasoning_content": f"Elenco dinamico generato con successo per i {len(available_tools)} tool attivi."
        }

    # Blocco prefetch formattato (se disponibile)
    prefetch_block = ""
    if web_prefetch_data and web_prefetch_data.get("summary_text"):
        from registry.search_security import wrap_untrusted_web_evidence
        prefetch_block = wrap_untrusted_web_evidence(
            query=web_prefetch_data.get("query", task),
            formatted_content=web_prefetch_data.get("summary_text", ""),
            sources=web_prefetch_data.get("sources", [])
        )

    # Se la modalità non ammette tool o il catalogo ammessi è vuoto
    if policy.max_tool_calls <= 0 or not available_tools:
        if call_llm_fn:
            now_str = datetime.now().strftime('%A %d %B %Y, %H:%M:%S')
            from registry.search_security import UNTRUSTED_CONTEXT_POLICY
            sys_prompt = (
                f"Data e Ora Corrente del Sistema: {now_str}\n"
                f"Sei l'Agente AI per la gestione dell'Homelab (modalità: {mode.upper()}). Rispondi in modo naturale e completo in italiano.\n"
                f"{UNTRUSTED_CONTEXT_POLICY}\n"
                f"Contesto memoria:\n{memory_context or ''}"
            )
            prompt_parts = []
            if prefetch_block:
                prompt_parts.append(prefetch_block)
            prompt_parts.append(f"Richiesta utente: '{task}'")
            combined_task = "\n\n".join(prompt_parts)

            ans_res = call_llm_fn(combined_task, system_prompt=sys_prompt, reasoning_budget=policy.reasoning_budget)
            if ans_res:
                raw_ans = ans_res.get("content", "")
                reasoning = ans_res.get("reasoning_content", "")
                ans = clean_synthesis_content(raw_ans) or raw_ans
                return {"final_response": ans, "execution_trace": [], "reasoning_content": reasoning}
        return {"final_response": f"Ho ricevuto la tua richiesta: '{task}'.", "execution_trace": [], "reasoning_content": None}

    catalog_str = format_catalog_for_prompt(available_tools)
    history_observations = []
    accumulated_reasonings: List[Tuple[str, str]] = []

    # Cache/deduplicazione e tracciamento storico chiamate nello stesso run
    call_cache: Dict[str, Any] = {}
    call_history_counts: Dict[str, int] = {}
    executed_search_queries: List[str] = []

    for step_id in range(1, policy.max_tool_calls + 1):
        from stream_session import current_session_var
        sess = current_session_var.get()
        if sess:
            if sess.is_stopped():
                logger.info("Agent loop interrotto da session stop")
                break
            sess.pause_event.wait(timeout=300)
            if sess.is_stopped():
                break

        obs_context = "\n".join(history_observations) if history_observations else "Nessuna azione eseguita finora."

        now_str = datetime.now().strftime('%A %d %B %Y, %H:%M:%S')
        from registry.search_security import UNTRUSTED_CONTEXT_POLICY
        base_system_prompt = (
            f"Current System Date and Time: {now_str}\n"
            f"You are the Homelab AI Management Agent (mode: {mode.upper()}).\n"
            "You have access to the connected MCP ecosystem, infrastructure tools, visual analysis, web search, and code execution.\n"
            "Language Directive: English is your internal instruction language. ALWAYS detect and respond in the language used by the user in their prompt (e.g. if the user writes in Italian, respond in natural and fluent Italian; if in English, respond in English), unless explicitly instructed otherwise.\n"
            f"{UNTRUSTED_CONTEXT_POLICY}\n"
        )

        prefetch_guidance = ""
        if prefetch_block:
            prefetch_guidance = (
                f"\n\nAVAILABLE WEB PREFETCH DATA:\n{prefetch_block}\n\n"
                "NOTE: A web prefetch has already been performed for this turn. "
                "If the above information is sufficient to answer the user's request, "
                "set `tool_needed=false` and provide the final answer immediately in `final_answer`. "
                "Only use `web_search` if you require further details or different data not present in the prefetch.\n"
            )

        vision_guidance = ""
        if images and len(images) > 0:
            vision_guidance = (
                f"\n\nAVAILABLE VISUAL CONTEXT:\n"
                f"The user attached {len(images)} image(s) directly to this request.\n"
                "If the user's request asks to analyze, describe, interpret, or answer questions about the attached image, "
                "you can perceive it directly: set `tool_needed=false` and provide your thorough, detailed, and accurate answer in `final_answer`.\n"
                "Only invoke tools if external actions on Homelab/MCP resources, additional web searches, or code execution are needed.\n"
            )

        tool_system_prompt = base_system_prompt + (
            f"Catalog of available tools for this mode:\n{catalog_str}\n\n"
            f"Conversational memory context:\n{memory_context or ''}\n\n"
            f"{prefetch_guidance}"
            f"{vision_guidance}"
            f"History of actions executed in this turn:\n{obs_context}\n\n"
            "CORE TOOL SELECTION RULES:\n"
            "1. DISTINCTION BETWEEN VIEW vs EXECUTE TOOLS:\n"
            "   - `[VIEW]`: Purely informational, read-only diagnostic tools (e.g. `get_container_status`, `list_containers`, `list_templates`, `web_search`). These run automatically without interrupting the flow.\n"
            "   - `[EXECUTE]`: Shell commands on host/containers and operations that mutate infrastructure, DNS, or configs (e.g. `exec_lxc_command`, `create_service`, `stop_container`, `allocate_ip`). These trigger Human-In-The-Loop (HITL) approval in the UI. In the `reasoning` field, always clearly explain what action you intend to take before calling them.\n"
            "2. If the user request asks about recent events, latest news, updates, dates, live prices, or information not present in your certain knowledge (and not covered by prefetch), set `tool_needed=true` and select `tool_name='web_search'`.\n"
            "3. If the request requires operating on homelab resources, files, network configs, DNS, or any service managed via the MCP ecosystem, set `tool_needed=true` and specify the corresponding MCP tool.\n"
            "4. If the request can be answered with absolute certainty from internal knowledge, the attached image, or the web prefetch without further actions (and does not ask for live market prices), set `tool_needed=false` and provide the complete response in `final_answer`.\n"
            "5. For `web_search`: use natural, concise queries without superfluous quotes or arbitrary years (e.g. 'SpaceX Starship latest launch updates').\n"
            "6. PARALLEL CALLS: if you need information from MULTIPLE independent read-only tools, use `parallel_calls`.\n"
            "7. IF AN ACTION OR TOOL HAS ALREADY BEEN EXECUTED (e.g. `inspect_image`, `web_search`, infrastructure command) and the result is in 'History of actions executed in this turn', that action is ALREADY COMPLETED: DO NOT repeat the same call or analogous tools. Set `tool_needed=false` and summarize the results in `final_answer` for the user.\n"
            "8. ANTI-HALLUCINATION ON EMPTY SEARCH: If web searches return no matches for the requested terms, DO NOT search in an endless loop and DO NOT invent that entities are fictitious. Transparently report what was found or the absence of official records in consulted sources.\n"
            "9. REASONING: Reason freely in the `reasoning` field. When `tool_needed=false`, ALWAYS provide the final response for the user in `final_answer` in the user's language.\n"
            "10. ALWAYS PREFER DEDICATED MCP TOOLS: To create or clone containers, check status, manage DNS or proxy, ALWAYS use the dedicated MCP tools (e.g. `create_lxc_from_template`, `create_service`, `get_container_status`, `list_containers`, `stop_container`, `start_container`, `allocate_ip`, `add_pihole_dns_record`, etc.). DO NOT attempt raw shell commands like `pct clone` when a dedicated tool exists."
        )

        if not call_llm_structured_fn:
            if call_llm_fn:
                direct_system_prompt = base_system_prompt + "Respond naturally, completely, clearly, and thoroughly in the language used by the user in their prompt. If the request concerns recent events or unverified data, state it transparently instead of inventing facts."
                direct_prompt = f"Request: '{task}'\nMemory context:\n{memory_context or ''}"
                syn_res = _call_llm_with_phase(call_llm_fn, direct_prompt, system_prompt=direct_system_prompt, reasoning_budget=policy.reasoning_budget, reasoning_phase="Elaborazione Risposta Finale")
                syn_ans = syn_res.get("content", "") if isinstance(syn_res, dict) else (syn_res or "")
                reasoning_content = syn_res.get("reasoning_content", "") if isinstance(syn_res, dict) else ""
                return {"final_response": syn_ans or "Richiesta completata.", "execution_trace": execution_trace, "reasoning_content": reasoning_content}
            break

        effective_reasoning_cap = min(policy.reasoning_budget, 1024) if policy.reasoning_budget > 0 else 1024
        try:
            selection = call_llm_structured_fn(
                prompt=task,
                system_prompt=tool_system_prompt,
                schema_cls=ToolSelection,
                max_tokens=4096,
                temperature=0.10,
                max_retries=2,
                reasoning_budget=effective_reasoning_cap,
                images=images,
            )
        except TypeError:
            selection = call_llm_structured_fn(
                prompt=task,
                system_prompt=tool_system_prompt,
                schema_cls=ToolSelection,
                max_tokens=4096,
                temperature=0.10,
                max_retries=2,
                reasoning_budget=effective_reasoning_cap,
            )

        step_thinking = getattr(selection, "raw_thinking", "") or ""
        step_cot = (selection.reasoning if selection else "") or ""
        step_reasoning = step_thinking or step_cot
        if step_reasoning:
            phase_label = f"Step {step_id}: Analisi e Selezione Tool" if step_id > 1 else "Analisi e Selezione Tool"
            accumulated_reasonings.append((phase_label, step_reasoning))

        if not selection or (not selection.tool_needed and not selection.parallel_calls) or not selection.tool_name:
            # 1. Se l'LLM ha fornito un final_answer esplicito
            if selection and selection.final_answer and len(selection.final_answer.strip()) > 10:
                final_ans = selection.final_answer.strip()
                # Emette la risposta finale in streaming pulito verso il frontend se la coda è attiva
                q = stream_queue.get()
                if q:
                    words = re.findall(r'\S+|\s+', final_ans)
                    for w in words:
                        q.put({"type": "content", "delta": w})
                reasoning_content = "\n\n---\n\n".join(
                    f"#### {'🔍' if 'Analisi' in title else '💡'} {title}\n\n{body}"
                    for title, body in accumulated_reasonings
                ) if accumulated_reasonings else None
            # 2. Se abbiamo eseguito dei tool ed abbiamo delle osservazioni, sintetizziamo la risposta per l'utente
            elif history_observations and call_llm_fn:
                summary_system_prompt = base_system_prompt + (
                    "You are in the final synthesis stage after executing tool actions.\n"
                    "Your task is to synthesize the information obtained from the tools into a fluent, thorough, and structured response in the language used by the user in their prompt.\n"
                    "Present the data clearly and in natural prose (no raw JSON dump): this is the final response for the user."
                )
                obs_text = "\n".join(history_observations)
                if len(obs_text) > config.TRUNCATION_LIMIT:
                    obs_text = obs_text[:config.TRUNCATION_LIMIT] + "\n... [observations truncated for brevity]"
                summary_prompt = (
                    f"User task: '{task}'\n\n"
                    f"History of actions and tool results:\n{obs_text}\n\n"
                    "Provide a final, comprehensive, structured response to the user in the language used in their prompt. "
                    "Explain the findings and results clearly. "
                    "If search tools (e.g. web_search) were used, cite and explain the retrieved information accurately."
                )
                synthesis_budget = min(policy.reasoning_budget, 512) if policy.reasoning_budget > 0 else 0
                syn_res = _call_llm_with_phase(call_llm_fn, summary_prompt, system_prompt=summary_system_prompt, reasoning_budget=synthesis_budget, reasoning_phase="Sintesi Risultati Tool")
                raw_syn = syn_res.get("content", "") if syn_res else ""
                syn_reasoning = syn_res.get("reasoning_content", "") if syn_res else ""
                if syn_reasoning:
                    accumulated_reasonings.append(("Sintesi Risultati Tool", syn_reasoning))
                syn_ans = clean_synthesis_content(raw_syn)
                final_ans = syn_ans if syn_ans else (
                    "The model processed the information but did not produce a text response. Please retry or adjust mode."
                )
                reasoning_content = "\n\n---\n\n".join(
                    f"#### {'🔍' if 'Analisi' in title else '💡'} {title}\n\n{body}"
                    for title, body in accumulated_reasonings
                ) if accumulated_reasonings else None
            # 3. Se la richiesta non richiede tool (es. domande concettuali o coperte da prefetch), generiamo una risposta diretta
            elif call_llm_fn:
                direct_system_prompt = base_system_prompt + (
                    "You are in direct dialogue mode with the user.\n"
                    "Respond in a natural, comprehensive, clear, and helpful manner in the language used by the user in their prompt.\n"
                    "If web context is present, use it to provide an accurate, up-to-date response.\n"
                    "If the request involves recent events or dates not covered in the context and unverifiable with certainty, "
                    "transparently state that a web search is recommended."
                )
                direct_prompt_parts = []
                if prefetch_block:
                    direct_prompt_parts.append(prefetch_block)
                direct_prompt_parts.append(
                    f"Respond completely, clearly, and thoroughly in the language used by the user in their prompt.\n"
                    f"User request: '{task}'\n"
                    f"Memory context:\n{memory_context or ''}"
                )
                direct_prompt = "\n\n".join(direct_prompt_parts)
                syn_res = _call_llm_with_phase(call_llm_fn, direct_prompt, system_prompt=direct_system_prompt, reasoning_budget=policy.reasoning_budget, reasoning_phase="Elaborazione Risposta Finale")
                raw_syn = syn_res.get("content", "") if syn_res else ""
                syn_reasoning = syn_res.get("reasoning_content", "") if syn_res else ""
                if syn_reasoning:
                    accumulated_reasonings.append(("Elaborazione Risposta Finale", syn_reasoning))
                syn_ans = clean_synthesis_content(raw_syn)
                final_ans = syn_ans if syn_ans else (
                    "Il modello ha elaborato le informazioni ma non ha prodotto una risposta testuale. Riprova o cambia modalità."
                )
                reasoning_content = "\n\n---\n\n".join(
                    f"#### {'🔍' if 'Analisi' in title else '💡'} {title}\n\n{body}"
                    for title, body in accumulated_reasonings
                ) if accumulated_reasonings else None
            else:
                final_ans = "Richiesta completata."
                reasoning_content = "\n\n---\n\n".join(
                    f"#### {'🔍' if 'Analisi' in title else '💡'} {title}\n\n{body}"
                    for title, body in accumulated_reasonings
                ) if accumulated_reasonings else None

            return {"final_response": final_ans, "execution_trace": execution_trace, "reasoning_content": reasoning_content}

        # Chiamate parallele per tool read-only indipendenti
        if selection.parallel_calls and len(selection.parallel_calls) > 1:
            import guardrails as _gr
            readonly_calls = [
                c for c in selection.parallel_calls
                if isinstance(c, dict) and c.get("tool_name") and _gr.classify_tool(c["tool_name"]) == "safe"
            ]
            if len(readonly_calls) > 1:
                logger.info(f"Step {step_id}: esecuzione parallela di {len(readonly_calls)} tool read-only")
                results = manager.execute_tools_parallel(
                    readonly_calls, policy.allowed_registries, thread_id=thread_id, mode=mode,
                    security_mode=security_mode
                )
                for i, (call, res) in enumerate(zip(readonly_calls, results)):
                    execution_trace.append({
                        "step_id": step_id,
                        "parallel_index": i,
                        "tool_name": call["tool_name"],
                        "args": call.get("arguments", {}),
                        "result": res,
                        "reasoning": selection.reasoning,
                        "parallel": True,
                        "error": res.get("error") if isinstance(res, dict) else None
                    })
                    res_str = json.dumps(res, ensure_ascii=False) if isinstance(res, (dict, list)) else str(res)
                    if call.get("tool_name") == "web_search":
                        from registry.search_security import GUARD_CLOSE, GUARD_OPEN, escape_guard_delimiters
                        res_str = f"{GUARD_OPEN}\n{escape_guard_delimiters(res_str)}\n{GUARD_CLOSE}"
                        executed_search_queries.append(str(call.get("arguments", {}).get("query", "")).strip())
                    p_sig = _normalize_call_signature(call.get("tool_name", ""), call.get("arguments", {}))
                    call_history_counts[p_sig] = call_history_counts.get(p_sig, 0) + 1
                    history_observations.append(f"Step {step_id}.{i} [parallelo]: {call['tool_name']}({call.get('arguments')}) -> {res_str}")
                continue

        tool_name = selection.tool_name
        arguments = selection.arguments or {}

        # Validazione argomenti
        val_error = validate_tool_args(tool_name, arguments, available_tools)
        if val_error:
            logger.warning(f"Step {step_id}: errore validazione argomenti per '{tool_name}': {val_error}")
            execution_trace.append({
                "step_id": step_id,
                "tool_name": tool_name,
                "args": arguments,
                "reasoning": selection.reasoning if selection else None,
                "error": f"Validazione fallita: {val_error}"
            })
            history_observations.append(f"Step {step_id}: Chiamata a '{tool_name}' fallita la validazione -> {val_error}")
            continue

        # Verifica duplicati e prevenzione loop
        call_sig = _normalize_call_signature(tool_name, arguments)
        is_duplicate = False

        if call_sig in call_history_counts:
            is_duplicate = True
            call_history_counts[call_sig] += 1
        else:
            call_history_counts[call_sig] = 1

        if tool_name == "web_search" and not is_duplicate:
            current_q = str(arguments.get("query", "")).strip()
            for prev_q in executed_search_queries:
                sim = _query_jaccard_similarity(current_q, prev_q)
                if sim >= 0.80:
                    logger.info(f"Step {step_id}: query '{current_q}' ha similarità {sim:.2f} con precedente '{prev_q}', trattata come duplicato")
                    is_duplicate = True
                    call_history_counts[call_sig] = call_history_counts.get(call_sig, 1) + 1
                    break

        if is_duplicate:
            repeat_count = call_history_counts[call_sig]
            if repeat_count >= 2:
                logger.warning(f"Step {step_id}: Rilevata ripetizione persistente per '{tool_name}'. Interruzione loop ReAct per prevenire cicli infiniti.")
                history_observations.append(f"Step {step_id}: [LOOP INTERROTTO] L'azione '{tool_name}' è già stata eseguita in precedenza. Si procede alla sintesi finale.")
                execution_trace.append({
                    "step_id": step_id,
                    "tool_name": tool_name,
                    "args": arguments,
                    "result": {"warning": "Chiamata duplicata bloccata. Interruzione loop ReAct per convergenza rapida."},
                    "reasoning": selection.reasoning if selection else None,
                    "cached": True,
                    "duplicate_blocked": True
                })
                break
            else:
                warning_msg = (
                    f"ATTENZIONE: Hai già eseguito la chiamata '{tool_name}' con parametri analoghi. "
                    "Non ripetere la stessa azione. Se le informazioni non sono reperibili nel web o i dati ottenuti sono sufficienti, "
                    "imposta `tool_needed=false` e sintetizza la risposta in `final_answer`."
                )
                logger.warning(f"Step {step_id}: Chiamata duplicata per '{tool_name}'. Iniezione feedback correttivo.")
                execution_trace.append({
                    "step_id": step_id,
                    "tool_name": tool_name,
                    "args": arguments,
                    "result": {"warning": warning_msg},
                    "reasoning": selection.reasoning if selection else None,
                    "cached": True,
                    "duplicate_blocked": True
                })
                history_observations.append(f"Step {step_id}: [DUPLICATO BLOCCATO] {warning_msg}")
                continue

        if tool_name == "web_search":
            executed_search_queries.append(str(arguments.get("query", "")).strip())

        # Esecuzione del tool via Registry Manager (con guardrail + approval + audit)
        cache_key = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
        is_cached = False
        if cache_key in call_cache:
            logger.info(f"Step {step_id}: hit cache deduplicazione per '{tool_name}'")
            res = call_cache[cache_key]
            is_cached = True
        else:
            try:
                res = manager.execute_tool(tool_name, arguments, policy.allowed_registries, thread_id=thread_id, mode=mode, security_mode=security_mode, task=task)
                import guardrails as _gr
                if _gr.classify_tool(tool_name) == "safe":
                    call_cache[cache_key] = res
            except Exception as e:
                logger.error(f"Step {step_id}: eccezione esecuzione tool '{tool_name}': {e}")
                res = {"error": f"Eccezione durante l'esecuzione: {str(e)}"}

        if isinstance(res, dict) and res.get("approval_required"):
            logger.info(f"Step {step_id}: Tool '{tool_name}' richiede approvazione esplicita ({res.get('risk_reason')}).")
            req_id = res.get("request_id")
            msg = res.get("message", "Richiesta di approvazione richiesta.")
            cmd_prev = res.get("command_preview")
            cmd_pref = res.get("command_prefix")
            risk_rsn = res.get("risk_reason")

            q = stream_queue.get()
            if q:
                q.put({
                    "type": "approval_required",
                    "request_id": req_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "command_preview": cmd_prev,
                    "command_prefix": cmd_pref,
                    "risk_reason": risk_rsn,
                    "message": msg
                })

            execution_trace.append({
                "step_id": step_id,
                "tool_name": tool_name,
                "args": arguments,
                "result": res,
                "reasoning": selection.reasoning,
                "approval_required": True,
                "request_id": req_id,
                "approval_prompt": msg,
                "command_preview": cmd_prev,
                "command_prefix": cmd_pref,
                "risk_reason": risk_rsn
            })
            return {
                "final_response": msg,
                "execution_trace": execution_trace,
                "reasoning_content": selection.reasoning,
                "approval_required": True,
                "request_id": req_id,
                "approval_prompt": msg,
                "command_preview": cmd_prev,
                "command_prefix": cmd_pref,
                "risk_reason": risk_rsn
            }

        res_str = json.dumps(res, ensure_ascii=False) if isinstance(res, (dict, list)) else str(res)
        logger.info(f"Step {step_id}: Risultato tool '{tool_name}': {res_str[:200]}...")

        execution_trace.append({
            "step_id": step_id,
            "tool_name": tool_name,
            "args": arguments,
            "result": res,
            "reasoning": selection.reasoning,
            "cached": is_cached,
            "error": res.get("error") if isinstance(res, dict) else None
        })

        if tool_name == "web_search":
            from registry.search_security import GUARD_CLOSE, GUARD_OPEN, escape_guard_delimiters
            safe_res_str = f"{GUARD_OPEN}\n{escape_guard_delimiters(res_str)}\n{GUARD_CLOSE}"
            obs_entry = f"Step {step_id}: {tool_name}({arguments}) -> {safe_res_str}"
        else:
            obs_entry = f"Step {step_id}: {tool_name}({arguments}) -> {res_str}"
        history_observations.append(obs_entry)

    # Se abbiamo completato tutti gli step del loop, sintetizziamo il risultato
    if history_observations and call_llm_fn:
        from registry.search_security import UNTRUSTED_CONTEXT_POLICY
        summary_system_prompt = (
            f"Current System Date and Time: {datetime.now().strftime('%A %d %B %Y, %H:%M:%S')}\n"
            "You are the Proxmox VE Homelab AI Agent.\n"
            "Language Directive: English is your internal instruction language. ALWAYS detect and respond in the language used by the user in their prompt (e.g. if the user writes in Italian, respond in natural and fluent Italian; if in English, respond in English), unless explicitly instructed otherwise.\n"
            f"{UNTRUSTED_CONTEXT_POLICY}"
        )
        obs_text = "\n".join(history_observations)
        if len(obs_text) > config.TRUNCATION_LIMIT:
            obs_text = obs_text[:config.TRUNCATION_LIMIT] + "\n... [observations truncated for brevity]"
        summary_prompt = (
            f"User task: '{task}'\n\n"
            f"History of executed actions:\n{obs_text}\n\n"
            "Provide a final, comprehensive, structured response in the language used by the user in their prompt. "
            "Respond in natural prose (no raw JSON dump): this is the final answer for the user."
        )
        synthesis_budget = min(policy.reasoning_budget, 512) if policy.reasoning_budget > 0 else 0
        syn_res = _call_llm_with_phase(call_llm_fn, summary_prompt, system_prompt=summary_system_prompt, reasoning_budget=synthesis_budget, reasoning_phase="Sintesi Risultati Finali")
        raw_ans = syn_res.get("content", "") if syn_res else ""
        syn_reasoning = syn_res.get("reasoning_content", "") if syn_res else ""
        if syn_reasoning:
            accumulated_reasonings.append(("Sintesi Risultati Finali", syn_reasoning))
        final_ans = clean_synthesis_content(raw_ans) or "Operazione completata."
        reasoning_content = "\n\n---\n\n".join(
            f"#### {'🔍' if 'Analisi' in title else '💡'} {title}\n\n{body}"
            for title, body in accumulated_reasonings
        ) if accumulated_reasonings else None
        return {"final_response": final_ans, "execution_trace": execution_trace, "reasoning_content": reasoning_content}

    reasoning_content = "\n\n---\n\n".join(
        f"#### {'🔍' if 'Analisi' in title else '💡'} {title}\n\n{body}"
        for title, body in accumulated_reasonings
    ) if accumulated_reasonings else None
    return {"final_response": "Richiesta completata.", "execution_trace": execution_trace, "reasoning_content": reasoning_content}
