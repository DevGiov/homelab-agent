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



def run_agent_loop(
    task: str,
    mode: str,
    memory_context: Optional[str] = None,
    call_llm_fn: Any = None,
    call_llm_structured_fn: Any = None,
    thread_id: Optional[str] = None,
    web_prefetch_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Esegue il loop ReAct autonomo in base alla ModePolicy della modalità corrente.
    - Se max_tool_calls == 0 (es. chat), risponde direttamente senza tool.
    - Altrimenti cicla: Reason -> Act -> Observe -> Loop fino al raggiungimento di max_tool_calls o final answer.
    """
    policy = get_mode_policy(mode)
    logger.info(f"Avvio agent loop per mode='{mode}' (max_tool_calls={policy.max_tool_calls}, registries={policy.allowed_registries})")

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
                f"Sei l'Agente AI dell'Homelab Proxmox VE. Rispondi in modo naturale e completo in italiano.\n"
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

    # Cache/deduplicazione risultati tool identici nello stesso run
    call_cache: Dict[str, Any] = {}

    for step_id in range(1, policy.max_tool_calls + 1):
        obs_context = "\n".join(history_observations) if history_observations else "Nessuna azione eseguita finora."

        now_str = datetime.now().strftime('%A %d %B %Y, %H:%M:%S')
        from registry.search_security import UNTRUSTED_CONTEXT_POLICY
        base_system_prompt = (
            f"Data e Ora Corrente del Sistema: {now_str}\n"
            f"Sei l'Agente AI dell'Homelab Proxmox VE (modalità: {mode.upper()}).\n"
            f"Hai accesso all'ecosistema MCP e ai tool di gestione dell'infrastruttura, ricerca web ed esecuzione codice.\n"
            f"{UNTRUSTED_CONTEXT_POLICY}\n"
        )

        prefetch_guidance = ""
        if prefetch_block:
            prefetch_guidance = (
                f"\n\nDATI PREFETCH WEB DISPONIBILI:\n{prefetch_block}\n\n"
                "NOTA: Un prefetch web è già stato eseguito per questo turno. "
                "Se le informazioni sopra sono già sufficienti per rispondere alla richiesta dell'utente, "
                "imposta `tool_needed=false` e fornisci subito la risposta finale in `final_answer`. "
                "Usa `web_search` solo se ti occorrono approfondimenti o dati differenti non presenti nel prefetch.\n"
            )

        tool_system_prompt = base_system_prompt + (
            f"Catalogo tool disponibili per questa modalità:\n{catalog_str}\n\n"
            f"Contesto memoria conversazionale:\n{memory_context or ''}\n\n"
            f"{prefetch_guidance}"
            f"Storico azioni eseguite in questo turno:\n{obs_context}\n\n"
            "REGOLE FONDAMENTALI DI SELEZIONE TOOL:\n"
            "1. Se la richiesta riguarda eventi recenti, ultime notizie, aggiornamenti, date, orari, lanci spaziali, fatti esterni o informazioni non presenti nella tua conoscenza certa (e non coperte dal prefetch), DEVI IMPOSTARE `tool_needed=true` e selezionare `tool_name='web_search'`.\n"
            "2. Se la richiesta richiede di operare su Proxmox, file, container, IPAM, DNS o reverse proxy, DEVI IMPOSTARE `tool_needed=true` e specificare il relativo tool MCP.\n"
            "3. Se la risposta può essere fornita con certezza assoluta dalla tua conoscenza interna o dal prefetch web senza ulteriori azioni, imposta `tool_needed=false` e fornisci la risposta completa in `final_answer`.\n"
            "4. Per `web_search`: usa query naturali e concise senza aggiungere anni arbitrari (es. 'SpaceX Starship latest launch updates').\n"
            "5. CHIAMATE PARALLELE: se ti servono le informazioni di PIÙ tool di sola lettura (es. lista container + stato DNS) e sono indipendenti tra loro, usa `parallel_calls`.\n"
            "6. IMPORTANTE: Se devi ragionare, fallo liberamente nel campo `reasoning`. Se imposti `tool_needed=false`, fornisci SEMPRE la risposta finale per l'utente in `final_answer`."
        )

        if not call_llm_structured_fn:
            if call_llm_fn:
                direct_system_prompt = base_system_prompt + "Rispondi in modo naturale, completo, chiaro ed esaustivo alla richiesta in italiano. Se la richiesta riguarda eventi recenti o dati che non puoi conoscere con certezza, dillo esplicitamente invece di inventare informazioni."
                direct_prompt = f"Richiesta: '{task}'\nContesto memoria:\n{memory_context or ''}"
                syn_res = _call_llm_with_phase(call_llm_fn, direct_prompt, system_prompt=direct_system_prompt, reasoning_budget=policy.reasoning_budget, reasoning_phase="Elaborazione Risposta Finale")
                syn_ans = syn_res.get("content", "") if isinstance(syn_res, dict) else (syn_res or "")
                reasoning_content = syn_res.get("reasoning_content", "") if isinstance(syn_res, dict) else ""
                return {"final_response": syn_ans or "Richiesta completata.", "execution_trace": execution_trace, "reasoning_content": reasoning_content}
            break

        selection = call_llm_structured_fn(
            prompt=task,
            system_prompt=tool_system_prompt,
            schema_cls=ToolSelection,
            max_tokens=4096,
            temperature=0.0,
            max_retries=2,
            reasoning_budget=policy.reasoning_budget
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
                from graph import stream_queue
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
                    "Sei in fase di sintesi finale dopo aver eseguito le azioni con i tool.\n"
                    "Il tuo compito è sintetizzare le informazioni ottenute dai tool in una risposta fluida, completa, dettagliata ed esaustiva in italiano.\n"
                    "Presenta i dati in modo chiaro e strutturato. Rispondi in prosa naturale (nessun JSON): questa è la risposta finale per l'utente."
                )
                obs_text = "\n".join(history_observations)
                if len(obs_text) > config.TRUNCATION_LIMIT:
                    obs_text = obs_text[:config.TRUNCATION_LIMIT] + "\n... [osservazioni troncate per brevità]"
                summary_prompt = (
                    f"Task utente: '{task}'\n\n"
                    f"Storico azioni e risultati dei tool eseguiti:\n{obs_text}\n\n"
                    f"Fornisci una risposta finale all'utente in lingua ITALIANA. "
                    f"La risposta deve essere discorsiva, dettagliata ed esaustiva. "
                    f"Se sono stati usati tool di ricerca (es. web_search), cita e spiega le informazioni trovate in modo chiaro e completo."
                )
                syn_res = _call_llm_with_phase(call_llm_fn, summary_prompt, system_prompt=summary_system_prompt, reasoning_budget=policy.reasoning_budget, reasoning_phase="Sintesi Risultati Tool")
                raw_syn = syn_res.get("content", "") if syn_res else ""
                syn_reasoning = syn_res.get("reasoning_content", "") if syn_res else ""
                if syn_reasoning:
                    accumulated_reasonings.append(("Sintesi Risultati Tool", syn_reasoning))
                syn_ans = clean_synthesis_content(raw_syn)
                final_ans = syn_ans if syn_ans else (
                    "Il modello ha elaborato le informazioni ma non ha prodotto una risposta testuale. Riprova o cambia modalità."
                )
                reasoning_content = "\n\n---\n\n".join(
                    f"#### {'🔍' if 'Analisi' in title else '💡'} {title}\n\n{body}"
                    for title, body in accumulated_reasonings
                ) if accumulated_reasonings else None
            # 3. Se la richiesta non richiede tool (es. domande concettuali o coperte da prefetch), generiamo una risposta diretta
            elif call_llm_fn:
                direct_system_prompt = base_system_prompt + (
                    "Sei in fase di dialogo diretto con l'utente.\n"
                    "Rispondi in modo naturale, completo, chiaro ed esaustivo alla richiesta in italiano.\n"
                    "Se sono presenti dati web nel contesto, usali per fornire una risposta aggiornata, precisa ed esaustiva.\n"
                    "IMPORTANTE: se la richiesta riguarda eventi recenti, notizie o date non coperte dal contesto e non verificabili con certezza, "
                    "dichiara che per dati aggiornati serve una ricerca e suggerisci di riprovare con ricerca web attiva."
                )
                direct_prompt_parts = []
                if prefetch_block:
                    direct_prompt_parts.append(prefetch_block)
                direct_prompt_parts.append(
                    f"Rispondi in modo completo, chiaro ed esaustivo alla seguente richiesta dell'utente in italiano.\n"
                    f"Richiesta: '{task}'\n"
                    f"Contesto memoria:\n{memory_context or ''}"
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
                    readonly_calls, policy.allowed_registries, thread_id=thread_id, mode=mode
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

        # Esecuzione del tool via Registry Manager (con guardrail + approval + audit)
        cache_key = f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"
        is_cached = False
        if cache_key in call_cache:
            logger.info(f"Step {step_id}: hit cache deduplicazione per '{tool_name}'")
            res = call_cache[cache_key]
            is_cached = True
        else:
            try:
                res = manager.execute_tool(tool_name, arguments, policy.allowed_registries, thread_id=thread_id, mode=mode)
                import guardrails as _gr
                if _gr.classify_tool(tool_name) == "safe":
                    call_cache[cache_key] = res
            except Exception as e:
                logger.error(f"Step {step_id}: eccezione esecuzione tool '{tool_name}': {e}")
                res = {"error": f"Eccezione durante l'esecuzione: {str(e)}"}

        if isinstance(res, dict) and res.get("approval_required"):
            logger.info(f"Step {step_id}: Tool '{tool_name}' richiede approvazione esplicita.")
            req_id = res.get("request_id")
            msg = res.get("message", "Richiesta di approvazione richiesta.")
            execution_trace.append({
                "step_id": step_id,
                "tool_name": tool_name,
                "args": arguments,
                "result": res,
                "reasoning": selection.reasoning,
                "approval_required": True,
                "request_id": req_id,
                "approval_prompt": msg
            })
            return {
                "final_response": msg,
                "execution_trace": execution_trace,
                "reasoning_content": selection.reasoning,
                "approval_required": True,
                "request_id": req_id,
                "approval_prompt": msg
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
            f"Data e Ora Corrente del Sistema: {datetime.now().strftime('%A %d %B %Y, %H:%M:%S')}\n"
            f"Sei l'Agente AI dell'Homelab Proxmox VE. Sintetizza i risultati delle azioni in italiano.\n"
            f"{UNTRUSTED_CONTEXT_POLICY}"
        )
        obs_text = "\n".join(history_observations)
        if len(obs_text) > config.TRUNCATION_LIMIT:
            obs_text = obs_text[:config.TRUNCATION_LIMIT] + "\n... [osservazioni troncate per brevità]"
        summary_prompt = (
            f"Task utente: '{task}'\n\n"
            f"Storico azioni eseguite:\n{obs_text}\n\n"
            f"Fornisci una risposta finale completa, discorsiva e dettagliata in italiano. "
            f"Rispondi in prosa naturale (nessun JSON): questa è la risposta per l'utente."
        )
        syn_res = _call_llm_with_phase(call_llm_fn, summary_prompt, system_prompt=summary_system_prompt, reasoning_budget=policy.reasoning_budget, reasoning_phase="Sintesi Risultati Finali")
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
