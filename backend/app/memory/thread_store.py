import json
import logging
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger("thread_store")

def _get_conn():
    return sqlite3.connect(settings.checkpoint_db_path)

def init_db():
    """Inizializza le tabelle dei thread: metadati, messaggi e riassunto della parte vecchia della conversazione."""
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS thread_metadata (
                thread_id TEXT PRIMARY KEY,
                title TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
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
                versions_json TEXT,
                version_index INTEGER DEFAULT 0,
                images_json TEXT,
                metrics_json TEXT,
                web_prefetch_json TEXT,
                model TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (thread_id, message_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS thread_summaries (
                thread_id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                covered INTEGER NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
    finally:
        conn.close()


def get_thread_title(thread_id: str) -> Optional[str]:
    """Recupera il titolo salvato per un thread."""
    if not thread_id:
        return None
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM thread_metadata WHERE thread_id = ?", (thread_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else None
    except Exception as e:
        logger.warning(f"Errore lettura titolo per thread '{thread_id}': {e}")
        return None


def set_thread_title(thread_id: str, title: str):
    """Imposta o aggiorna il titolo di un thread."""
    if not thread_id or not title:
        return
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO thread_metadata (thread_id, title, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(thread_id) DO UPDATE SET title = excluded.title, updated_at = CURRENT_TIMESTAMP
        """, (thread_id, title.strip()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore aggiornamento titolo per thread '{thread_id}': {e}")


def generate_and_save_title(thread_id: str, user_prompt: str, model: Optional[str] = None) -> str:
    """Genera via LLM un titolo conciso in italiano (3-5 parole) e lo salva in SQLite."""
    if not thread_id or not user_prompt:
        return "Nuova Conversazione"
    try:
        from app.llm import providers
        provider = providers.get_provider()
        prompt_msgs = [
            {
                "role": "system",
                "content": (
                    "You are an assistant that creates a concise conversation title. "
                    "Respond EXCLUSIVELY with a 3-5 word title matching the language used in the prompt, "
                    "without quotes, trailing punctuation, markdown, or explanations."
                )
            },
            {
                "role": "user",
                "content": f"Title for this initial request:\n{user_prompt[:300]}"
            }
        ]
        res = provider.chat(prompt_msgs, model=model, max_tokens=25, temperature=0.3)
        raw_title = res.get("content", "").strip()
        clean = re.sub(r'["\'`\n#]', '', raw_title).strip()
        if clean.endswith('.'):
            clean = clean[:-1].strip()
        title = clean[:50] if clean else user_prompt[:30].strip()
        set_thread_title(thread_id, title)
        return title
    except Exception as e:
        logger.warning(f"Impossibile generare titolo con LLM per '{thread_id}': {e}")
        fallback = user_prompt[:35].strip()
        set_thread_title(thread_id, fallback)
        return fallback


def save_user_message(
    thread_id: str,
    user_input: str,
    user_msg_id: Optional[str] = None,
    timestamp_str: Optional[str] = None,
    versions: Optional[List[Dict[str, Any]]] = None,
    version_index: int = 0,
    images: Optional[List[str]] = None
) -> str:
    """Salva o aggiorna il messaggio dell'utente in SQLite con supporto a versioni multiple e immagini."""
    if not thread_id:
        return ""
    if not user_input and not images:
        return ""
    conn = _get_conn()
    cursor = conn.cursor()
    now_time = time.time()
    time_str = timestamp_str or time.strftime("%H:%M", time.localtime(now_time))
    msg_id = user_msg_id or f"user_{int(now_time * 1000)}"
    versions_json = json.dumps(versions, ensure_ascii=False) if versions else None
    images_json = json.dumps(images, ensure_ascii=False) if images else None
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO thread_messages
            (thread_id, message_id, sender, content, timestamp, versions_json, version_index, images_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (thread_id, msg_id, "user", user_input or "", time_str, versions_json, version_index, images_json))
        conn.commit()
        return msg_id
    except Exception as e:
        logger.error(f"Errore salvataggio messaggio utente thread '{thread_id}': {e}")
        return ""
    finally:
        conn.close()


def save_assistant_message(
    thread_id: str,
    response_data: Dict[str, Any],
    ast_msg_id: Optional[str] = None,
    timestamp_str: Optional[str] = None,
    versions: Optional[List[Dict[str, Any]]] = None,
    version_index: int = 0
) -> str:
    """Salva o aggiorna la risposta dell'assistente in SQLite con tutti i campi strutturati e versioni."""
    if not thread_id:
        return ""
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
        versions_json = json.dumps(versions, ensure_ascii=False) if versions else response_data.get("versions_json")
        v_idx = version_index if versions is not None else response_data.get("version_index", 0)

        metrics = response_data.get("metrics")
        metrics_json = json.dumps(metrics, ensure_ascii=False) if metrics else None

        web_prefetch = response_data.get("web_prefetch")
        web_prefetch_json = json.dumps(web_prefetch, ensure_ascii=False) if web_prefetch else None
        model = response_data.get("model")

        cursor.execute("""
            INSERT OR REPLACE INTO thread_messages
            (thread_id, message_id, sender, content, timestamp, mode, tool_used, reasoning,
             plan_steps_json, plan_structure_json, execution_trace_json, rollback_trace_json,
             is_error, reasoning_content, versions_json, version_index, metrics_json, web_prefetch_json, model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            reasoning_content,
            versions_json,
            v_idx,
            metrics_json,
            web_prefetch_json,
            model
        ))
        conn.commit()
        return msg_id
    except Exception as e:
        logger.error(f"Errore salvataggio risposta assistente thread '{thread_id}': {e}")
        return ""
    finally:
        conn.close()


def update_message_version(thread_id: str, message_id: str, version_index: int):
    """Aggiorna l'indice della versione attiva per un messaggio."""
    if not thread_id or not message_id:
        return
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE thread_messages SET version_index = ?
            WHERE thread_id = ? AND message_id = ?
        """, (version_index, thread_id, message_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore update version_index msg '{message_id}': {e}")


def update_message_versions_data(thread_id: str, message_id: str, versions: List[Dict[str, Any]], version_index: int):
    """Aggiorna lo storico completo delle versioni e l'indice attivo per un messaggio."""
    if not thread_id or not message_id:
        return
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        versions_json = json.dumps(versions, ensure_ascii=False)
        cursor.execute("""
            UPDATE thread_messages SET versions_json = ?, version_index = ?
            WHERE thread_id = ? AND message_id = ?
        """, (versions_json, version_index, thread_id, message_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore update versions_data msg '{message_id}': {e}")


def save_turn(thread_id: str, user_input: str, response_data: Dict[str, Any], images: Optional[List[str]] = None):
    """
    Salva atomicamente in SQLite sia il messaggio utente che la risposta assistente.
    """
    if not thread_id:
        return
    now_time = time.time()
    time_str = time.strftime("%H:%M", time.localtime(now_time))
    user_msg_id = f"user_{int(now_time * 1000)}"
    ast_msg_id = f"msg_{int(now_time * 1000) + 1}"
    save_user_message(thread_id, user_input, user_msg_id=user_msg_id, timestamp_str=time_str, images=images)
    save_assistant_message(thread_id, response_data, ast_msg_id=ast_msg_id, timestamp_str=time_str)


def get_thread_messages(thread_id: str) -> List[Dict[str, Any]]:
    """
    Recupera la cronologia messaggi tipata e strutturata per un thread.
    """
    if not thread_id:
        return []

    conn = _get_conn()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT message_id, sender, content, timestamp, mode, tool_used, reasoning,
                   plan_steps_json, plan_structure_json, execution_trace_json, rollback_trace_json,
                   is_error, reasoning_content, versions_json, version_index, images_json, metrics_json,
                   web_prefetch_json, model
            FROM thread_messages
            WHERE thread_id = ?
            ORDER BY rowid ASC
        """, (thread_id,))
        rows = cursor.fetchall()
        conn.close()

        messages = []
        for row in rows:
            (m_id, sender, content, ts, mode, tool_used, reasoning,
             ps_json, pst_json, et_json, rt_json, is_err, reasoning_content,
             vers_json, v_idx, img_json, met_json, wp_json, model_val) = row

            versions_parsed = None
            if vers_json:
                try:
                    versions_parsed = json.loads(vers_json)
                except Exception:
                    versions_parsed = None

            images_parsed = None
            if img_json:
                try:
                    images_parsed = json.loads(img_json)
                except Exception:
                    images_parsed = None

            metrics_parsed = None
            if met_json:
                try:
                    metrics_parsed = json.loads(met_json)
                except Exception:
                    metrics_parsed = None

            web_prefetch_parsed = None
            if wp_json:
                try:
                    web_prefetch_parsed = json.loads(wp_json)
                except Exception:
                    web_prefetch_parsed = None

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
                "reasoning_content": reasoning_content,
                "versions": versions_parsed,
                "versionIndex": v_idx if v_idx is not None else 0,
                "images": images_parsed,
                "metrics": metrics_parsed,
                "web_prefetch": web_prefetch_parsed,
                "model": model_val
            }
            messages.append(msg_obj)

        return messages
    except Exception as e:
        logger.error(f"Errore lettura messaggi thread '{thread_id}': {e}")
        return []


def _active_content(content: str, versions_json: Optional[str], version_index: Optional[int]) -> str:
    """Il testo della versione mostrata nella UI (una rigenerazione o una modifica aggiunge versioni)."""
    if versions_json:
        try:
            versions = json.loads(versions_json)
            if 0 <= (version_index or 0) < len(versions):
                return versions[version_index or 0].get("content") or content
        except (ValueError, AttributeError, TypeError):
            pass
    return content


def get_history(thread_id: str) -> List[Dict[str, Any]]:
    """La conversazione come la vede l'agente: ruolo, testo della versione attiva, modalità, tool e data di
    creazione (UTC). Esclude i messaggi vuoti e gli errori."""
    if not thread_id:
        return []
    conn = _get_conn()
    try:
        rows = conn.execute("""
            SELECT sender, content, versions_json, version_index, mode, tool_used, created_at
            FROM thread_messages
            WHERE thread_id = ? AND COALESCE(is_error, 0) = 0
            ORDER BY rowid ASC
        """, (thread_id,)).fetchall()
    finally:
        conn.close()
    history = []
    for sender, content, versions_json, version_index, mode, tool_used, created_at in rows:
        text = _active_content(content, versions_json, version_index).strip()
        if text:
            history.append({"role": sender, "content": text, "mode": mode, "tool_used": tool_used, "created_at": created_at})
    return history


def get_summary(thread_id: str) -> Tuple[str, int]:
    """Riassunto dei primi `covered` messaggi della cronologia; ("", 0) se il thread non ne ha."""
    conn = _get_conn()
    try:
        row = conn.execute("SELECT summary, covered FROM thread_summaries WHERE thread_id = ?", (thread_id,)).fetchone()
    finally:
        conn.close()
    return (row[0], row[1]) if row else ("", 0)


def save_summary(thread_id: str, summary: str, covered: int) -> None:
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO thread_summaries (thread_id, summary, covered, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (thread_id, summary, covered),
        )
        conn.commit()
    finally:
        conn.close()


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
    """Elimina i messaggi e il riassunto di un thread."""
    if not thread_id:
        return
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM thread_messages WHERE thread_id = ?", (thread_id,))
        cursor.execute("DELETE FROM thread_summaries WHERE thread_id = ?", (thread_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore eliminazione messaggi thread '{thread_id}': {e}")


def clear_all_thread_messages():
    """Elimina i messaggi e i riassunti di tutti i thread."""
    try:
        conn = _get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM thread_messages")
        cursor.execute("DELETE FROM thread_summaries")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Errore azzeramento tabella thread_messages: {e}")
