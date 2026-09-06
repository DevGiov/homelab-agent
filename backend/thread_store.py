import json
import logging
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger("thread_store")

def _get_conn():
    return sqlite3.connect(config.CHECKPOINT_DB_PATH)

def init_db():
    """Inizializza la tabella thread_messages nel database SQLite dei checkpoint."""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS thread_messages (
                thread_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                mode TEXT,
                tool_used TEXT,
                reasoning TEXT,
                plan_steps_json TEXT,
                plan_structure_json TEXT,
                execution_trace_json TEXT,
                rollback_trace_json TEXT,
                is_error INTEGER DEFAULT 0,
                reasoning_content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (thread_id, message_id)
            )
        """)
        conn.commit()

        # Migrazione sicura per tabelle esistenti
        try:
            cursor.execute("ALTER TABLE thread_messages ADD COLUMN reasoning_content TEXT")
            conn.commit()
        except Exception:
            pass  # La colonna esiste già

        conn.close()
    except Exception as e:
        logger.error(f"Errore inizializzazione thread_store SQLite: {e}")

# Inizializza al caricamento del modulo
init_db()

def save_user_message(thread_id: str, user_input: str, user_msg_id: Optional[str] = None, timestamp_str: Optional[str] = None) -> str:
    """Salva immediatamente il messaggio dell'utente in SQLite."""
    if not thread_id or not user_input:
        return ""
    init_db()
    conn = _get_conn()
    cursor = conn.cursor()
    now_time = time.time()
    time_str = timestamp_str or time.strftime("%H:%M", time.localtime(now_time))
    msg_id = user_msg_id or f"user_{int(now_time * 1000)}"
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO thread_messages
            (thread_id, message_id, sender, content, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (thread_id, msg_id, "user", user_input, time_str))
        conn.commit()
        return msg_id
    except Exception as e:
        logger.error(f"Errore salvataggio messaggio utente thread '{thread_id}': {e}")
        return ""
    finally:
        conn.close()


def save_assistant_message(thread_id: str, response_data: Dict[str, Any], ast_msg_id: Optional[str] = None, timestamp_str: Optional[str] = None) -> str:
    """Salva o aggiorna la risposta dell'assistente in SQLite con tutti i campi strutturati."""
    if not thread_id:
        return ""
    init_db()
    conn = _get_conn()
    cursor = conn.cursor()
    now_time = time.time()
    time_str = timestamp_str or time.strftime("%H:%M", time.localtime(now_time))
    msg_id = ast_msg_id or f"msg_{int(now_time * 1000)}"
    try:
        resp_text = response_data.get("response", "")
        mode = response_data.get("mode")
        tool_used = response_data.get("tool_used")
        reasoning_content = response_data.get("reasoning_content")

        plan_steps = response_data.get("plan_steps")
        plan_steps_json = json.dumps(plan_steps, ensure_ascii=False) if plan_steps else None

        plan_structure = response_data.get("plan_structure")
        plan_structure_json = json.dumps(plan_structure, ensure_ascii=False) if plan_structure else None

        execution_trace = response_data.get("execution_trace")
        execution_trace_json = json.dumps(execution_trace, ensure_ascii=False) if execution_trace else None

        rollback_trace = response_data.get("rollback_trace")
        rollback_trace_json = json.dumps(rollback_trace, ensure_ascii=False) if rollback_trace else None

        reasoning = None
        if execution_trace and isinstance(execution_trace, list):
            for tr in execution_trace:
                if isinstance(tr, dict) and tr.get("reasoning"):
                    reasoning = tr.get("reasoning")
                    break

        is_error = 1 if response_data.get("error") else 0

        cursor.execute("""
            INSERT OR REPLACE INTO thread_messages
            (thread_id, message_id, sender, content, timestamp, mode, tool_used, reasoning,
             plan_steps_json, plan_structure_json, execution_trace_json, rollback_trace_json, is_error, reasoning_content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            thread_id,
            msg_id,
            "assistant",
            resp_text,
            time_str,
            mode,
            tool_used,
            reasoning,
            plan_steps_json,
            plan_structure_json,
            execution_trace_json,
            rollback_trace_json,
            is_error,
            reasoning_content
        ))
        conn.commit()
        return msg_id
    except Exception as e:
        logger.error(f"Errore salvataggio risposta assistente thread '{thread_id}': {e}")
        return ""
    finally:
        conn.close()


def save_turn(thread_id: str, user_input: str, response_data: Dict[str, Any]):
    """
    Salva atomicamente in SQLite sia il messaggio utente che la risposta assistente.
    """
    if not thread_id:
        return
    now_time = time.time()
    time_str = time.strftime("%H:%M", time.localtime(now_time))
    user_msg_id = f"user_{int(now_time * 1000)}"
    ast_msg_id = f"msg_{int(now_time * 1000) + 1}"
    save_user_message(thread_id, user_input, user_msg_id=user_msg_id, timestamp_str=time_str)
    save_assistant_message(thread_id, response_data, ast_msg_id=ast_msg_id, timestamp_str=time_str)


def get_thread_messages(thread_id: str) -> List[Dict[str, Any]]:
    """
    Recupera la cronologia messaggi tipata e strutturata per un thread.
    """
    if not thread_id:
        return []

    init_db()
    conn = _get_conn()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT message_id, sender, content, timestamp, mode, tool_used, reasoning,
                   plan_steps_json, plan_structure_json, execution_trace_json, rollback_trace_json, is_error, reasoning_content
            FROM thread_messages
            WHERE thread_id = ?
            ORDER BY rowid ASC
        """, (thread_id,))
        rows = cursor.fetchall()
        conn.close()

        messages = []
        for row in rows:
            m_id, sender, content, ts, mode, tool_used, reasoning, ps_json, pst_json, et_json, rt_json, is_err, reasoning_content = row

            msg_obj = {
                "id": m_id,
                "sender": sender,
                "content": content,
                "timestamp": ts,
                "mode": mode,
                "tool_used": tool_used,
                "reasoning": reasoning,
                "plan_steps": json.loads(ps_json) if ps_json else None,
                "plan_structure": json.loads(pst_json) if pst_json else None,
                "execution_trace": json.loads(et_json) if et_json else None,
                "rollback_trace": json.loads(rt_json) if rt_json else None,
                "isError": bool(is_err),
                "reasoning_content": reasoning_content
            }
            messages.append(msg_obj)

        return messages
    except Exception as e:
        logger.error(f"Errore lettura messaggi thread '{thread_id}': {e}")
        return []


def get_last_message(thread_id: str) -> Optional[str]:
    """Recupera l'anteprima del testo dell'ultimo messaggio non vuoto di un thread."""
    if not thread_id:
        return None

    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT content FROM thread_messages
            WHERE thread_id = ? AND content IS NOT NULL AND TRIM(content) != ''
            ORDER BY rowid DESC LIMIT 1
        """, (thread_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def delete_thread_messages(thread_id: str):
    """Elimina tutti i messaggi associati a un thread."""
    if not thread_id:
        return
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM thread_messages WHERE thread_id = ?", (thread_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore eliminazione messaggi thread '{thread_id}': {e}")


def clear_all_thread_messages():
    """Svuota l'intera tabella dei messaggi."""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM thread_messages")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore azzeramento tabella thread_messages: {e}")


def backfill_from_state_history(thread_id: str, app_graph) -> List[Dict[str, Any]]:
    """
    Ricostruisce i turni di conversazione dallo state history di LangGraph
    e li salva nello store per accesso futuro istantaneo.
    
    Supporta sia turni completati che turni interrotti a metà (es. durante pause o refresh).
    """
    if not thread_id or not app_graph:
        return []

    try:
        cfg = {"configurable": {"thread_id": thread_id}}
        history = list(app_graph.get_state_history(cfg))
    except Exception as e:
        logger.warning(f"Errore lettura state history per thread '{thread_id}': {e}")
        return []

    if not history:
        return []

    # 1. Raccoglie i turni completati (snapshot terminali dove next == ())
    completed_turns = []
    seen_tasks = set()

    for snap in reversed(history):
        next_nodes = snap.next
        if next_nodes != ():
            continue

        values = snap.values
        task = values.get("task")
        final_response = values.get("final_response")

        if not task or not final_response:
            continue
        if task in seen_tasks:
            continue
        seen_tasks.add(task)

        mode = values.get("mode")
        plan_dict = values.get("plan", {})
        execution_trace = values.get("execution_trace")
        plan_structure = values.get("plan_structure")
        rollback_trace = values.get("rollback_trace")
        reasoning_content = values.get("reasoning_content")

        if not execution_trace and isinstance(plan_dict, dict):
            execution_trace = plan_dict.get("execution_log")
        if not plan_structure and isinstance(plan_dict, dict):
            plan_structure = plan_dict.get("plan_structure")

        tool_used = plan_dict.get("tool_name") if isinstance(plan_dict, dict) else None
        plan_steps = plan_dict.get("plan_steps") if isinstance(plan_dict, dict) else None

        completed_turns.append({
            "task": task,
            "mode": mode,
            "final_response": final_response,
            "tool_used": tool_used,
            "plan_steps": plan_steps,
            "plan_structure": plan_structure,
            "execution_trace": execution_trace,
            "rollback_trace": rollback_trace,
            "reasoning_content": reasoning_content,
        })

    # 2. Se non ci sono turni completati (o l'ultimo turno è rimasto interrotto/incompleto)
    # Recupera il task dallo snapshot più recente
    if history:
        latest_snap = history[0]
        latest_task = latest_snap.values.get("task")
        if latest_task and latest_task not in seen_tasks:
            seen_tasks.add(latest_task)
            values = latest_snap.values
            mode = values.get("mode") or "chat"
            plan_dict = values.get("plan", {})
            execution_trace = values.get("execution_trace") or (plan_dict.get("execution_log") if isinstance(plan_dict, dict) else None)
            plan_structure = values.get("plan_structure") or (plan_dict.get("plan_structure") if isinstance(plan_dict, dict) else None)
            rollback_trace = values.get("rollback_trace")
            tool_used = plan_dict.get("tool_name") if isinstance(plan_dict, dict) else None
            plan_steps = plan_dict.get("plan_steps") if isinstance(plan_dict, dict) else None
            reasoning_content = values.get("reasoning_content")
            final_response = values.get("final_response") or "[Esecuzione interrotta o non completata]"

            completed_turns.append({
                "task": latest_task,
                "mode": mode,
                "final_response": final_response,
                "tool_used": tool_used,
                "plan_steps": plan_steps,
                "plan_structure": plan_structure,
                "execution_trace": execution_trace,
                "rollback_trace": rollback_trace,
                "reasoning_content": reasoning_content,
            })

    if not completed_turns:
        return []

    # Salva nello store SQLite con timestamp sintetici sequenziali
    init_db()
    conn = _get_conn()
    cursor = conn.cursor()
    all_messages = []

    try:
        base_ts = time.time() - (len(completed_turns) * 60)

        for idx, turn in enumerate(completed_turns):
            ts = base_ts + (idx * 60)
            time_str = time.strftime("%H:%M", time.localtime(ts))
            user_msg_id = f"backfill_user_{thread_id}_{idx}"
            ast_msg_id = f"backfill_ast_{thread_id}_{idx}"

            # Salva messaggio utente
            cursor.execute("""
                INSERT OR IGNORE INTO thread_messages
                (thread_id, message_id, sender, content, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (thread_id, user_msg_id, "user", turn["task"], time_str))

            all_messages.append({
                "id": user_msg_id,
                "sender": "user",
                "content": turn["task"],
                "timestamp": time_str,
                "mode": None,
                "tool_used": None,
                "reasoning": None,
                "plan_steps": None,
                "plan_structure": None,
                "execution_trace": None,
                "rollback_trace": None,
                "isError": False,
                "reasoning_content": None
            })

            # Prepara contenuto risposta assistente
            resp_text = turn["final_response"] or ""
            if isinstance(resp_text, str):
                resp_text = re.sub(r'\[Mode:\s*[A-Za-z]+\]\n?', '', resp_text, flags=re.IGNORECASE).strip()

            et = turn.get("execution_trace")
            et_json = json.dumps(et, ensure_ascii=False) if et else None
            ps = turn.get("plan_steps")
            ps_json = json.dumps(ps, ensure_ascii=False) if ps else None
            pst = turn.get("plan_structure")
            pst_json = json.dumps(pst, ensure_ascii=False) if pst else None
            rt = turn.get("rollback_trace")
            rt_json = json.dumps(rt, ensure_ascii=False) if rt else None
            rc = turn.get("reasoning_content")

            reasoning = None
            if et and isinstance(et, list):
                for tr in et:
                    if isinstance(tr, dict) and tr.get("reasoning"):
                        reasoning = tr["reasoning"]
                        break

            cursor.execute("""
                INSERT OR IGNORE INTO thread_messages
                (thread_id, message_id, sender, content, timestamp, mode, tool_used, reasoning,
                 plan_steps_json, plan_structure_json, execution_trace_json, rollback_trace_json, is_error, reasoning_content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                thread_id, ast_msg_id, "assistant", resp_text, time_str,
                turn.get("mode"), turn.get("tool_used"), reasoning,
                ps_json, pst_json, et_json, rt_json, 0, rc
            ))

            all_messages.append({
                "id": ast_msg_id,
                "sender": "assistant",
                "content": resp_text,
                "timestamp": time_str,
                "mode": turn.get("mode"),
                "tool_used": turn.get("tool_used"),
                "reasoning": reasoning,
                "plan_steps": ps,
                "plan_structure": pst,
                "execution_trace": et,
                "rollback_trace": rt,
                "isError": False,
                "reasoning_content": rc
            })

        conn.commit()
        logger.info(f"Backfill completato per thread '{thread_id}': {len(completed_turns)} turni ricostruiti.")
    except Exception as e:
        logger.error(f"Errore backfill thread '{thread_id}': {e}")
        all_messages = []
    finally:
        conn.close()

    return all_messages

