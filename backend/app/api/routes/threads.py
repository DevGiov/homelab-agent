"""Thread di conversazione: elenco, dettaglio, titoli, versioni dei messaggi, cancellazione."""
import logging
import sqlite3
import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from app.agent.stream_session import (
    get_session,
)
from app.api.agent_runner import app_graph
from app.api.deps import verify_api_key
from app.api.schemas import (
    SaveVersionsDataRequest,
    SetThreadTitleRequest,
    SwitchVersionRequest,
    ThreadSummary,
)
from app.core.config import settings
from app.memory import letta_client, thread_store

logger = logging.getLogger("api")

router = APIRouter(tags=["threads"])


@router.get("/v1/threads", response_model=List[ThreadSummary], dependencies=[Depends(verify_api_key)])
async def list_threads():
    try:
        thread_store.init_db()
        conn = sqlite3.connect(settings.checkpoint_db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT thread_id, MAX(cp_count) as checkpoint_count, MAX(last_activity) as sort_key
            FROM (
                SELECT thread_id, COUNT(*) as cp_count, MAX(rowid) as last_activity FROM checkpoints GROUP BY thread_id
                UNION ALL
                SELECT thread_id, 0 as cp_count, MAX(rowid) as last_activity FROM thread_messages GROUP BY thread_id
            )
            WHERE thread_id IS NOT NULL AND thread_id != ''
            GROUP BY thread_id
            ORDER BY sort_key DESC
        """)
        rows = cursor.fetchall()

        cursor.execute("SELECT thread_id, title FROM thread_metadata")
        titles_map = dict(cursor.fetchall())
        conn.close()

        summaries = []
        found_tids = set()
        for row in rows:
            tid = row[0]
            count = row[1]
            if not tid:
                continue
            found_tids.add(tid)
            last_msg = thread_store.get_last_message(tid)

            # Se non c'è last_message, tenta backfill da LangGraph per popolare lo store
            if last_msg is None and count > 0:
                backfilled = thread_store.backfill_from_state_history(tid, app_graph)
                if backfilled:
                    last_msg = thread_store.get_last_message(tid)

            sess = get_session(tid)
            is_active = sess is not None and sess.is_active()

            summaries.append(ThreadSummary(
                thread_id=tid,
                title=titles_map.get(tid),
                last_message=last_msg,
                checkpoint_count=count,
                is_active=is_active
            ))

        # Aggiungi eventuali sessioni attive non ancora persistite in SQLite
        from app.agent.stream_session import _active_sessions, _sessions_lock
        with _sessions_lock:
            active_items = [(tid, s) for tid, s in _active_sessions.items() if s.is_active()]
        for atid, asess in active_items:
            if atid not in found_tids:
                summaries.insert(0, ThreadSummary(
                    thread_id=atid,
                    title=titles_map.get(atid),
                    last_message=asess.task,
                    checkpoint_count=0,
                    is_active=True
                ))

        return summaries
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list threads: {str(e)}") from e


@router.get("/v1/threads/{thread_id}", dependencies=[Depends(verify_api_key)])
async def get_thread(thread_id: str):
    try:
        conn = sqlite3.connect(settings.checkpoint_db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (thread_id,))
        count = cursor.fetchone()[0]
        conn.close()

        # 1. Prova lo store locale (istantaneo)
        stored_messages = thread_store.get_thread_messages(thread_id)

        # 2. Se vuoto ma il thread ha checkpoint, ricostruisci da LangGraph state history
        if not stored_messages and count > 0:
            stored_messages = thread_store.backfill_from_state_history(thread_id, app_graph)
        elif stored_messages and count > 0 and any(m.get("sender") == "assistant" and not m.get("web_prefetch") for m in stored_messages):
            stored_messages = thread_store.repair_missing_web_prefetch(thread_id, app_graph)

        # 3. Controlla se c'è una sessione attiva per questo thread
        sess = get_session(thread_id)
        is_active = sess is not None and sess.is_active()
        is_paused = sess.is_paused() if sess else False
        active_snapshot = sess.get_snapshot() if is_active else None

        # Se la sessione è attiva, sintetizza lo stato in tempo reale nei messaggi
        if is_active:
            if not stored_messages and sess.task:
                stored_messages.append({
                    "id": f"user_live_{thread_id}",
                    "sender": "user",
                    "content": sess.task,
                    "timestamp": time.strftime("%H:%M")
                })
            last_msg = stored_messages[-1] if stored_messages else None
            if not last_msg or last_msg.get("sender") == "user":
                stored_messages.append({
                    "id": f"ast_live_{thread_id}",
                    "sender": "assistant",
                    "content": sess.partial_content or "",
                    "reasoning_content": sess.reasoning_content or "",
                    "mode": sess.mode or "plan",
                    "tool_used": sess.active_tool,
                    "plan_steps": sess.plan_steps,
                    "plan_structure": sess.plan_structure,
                    "execution_trace": sess.execution_trace,
                    "metrics": sess.get_metrics(),
                    "isRunning": True,
                    "timestamp": time.strftime("%H:%M")
                })

        # 4. Letta come fonte supplementare opzionale (mai bloccante)
        clean_messages = []
        agent_id = None
        try:
            agent_id = letta_client.create_thread(thread_id)
            if agent_id:
                raw_messages = letta_client.get_messages(agent_id)
                clean_messages = letta_client.filter_clean_messages(raw_messages) if raw_messages else []
        except Exception as letta_err:
            logger.warning(f"Letta non raggiungibile per thread '{thread_id}': {letta_err}")

        return {
            "thread_id": thread_id,
            "title": thread_store.get_thread_title(thread_id),
            "agent_id": agent_id,
            "checkpoint_count": count,
            "messages": stored_messages,
            "letta_messages": clean_messages,
            "is_active": is_active,
            "is_paused": is_paused,
            "active_snapshot": active_snapshot
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get thread details: {str(e)}") from e


@router.patch("/v1/threads/{thread_id}/title", dependencies=[Depends(verify_api_key)])
async def update_thread_title(thread_id: str, req: SetThreadTitleRequest):
    thread_store.set_thread_title(thread_id, req.title)
    return {"status": "ok", "thread_id": thread_id, "title": req.title}


@router.post("/v1/threads/{thread_id}/title/generate", dependencies=[Depends(verify_api_key)])
async def force_generate_thread_title(thread_id: str, model: Optional[str] = None):
    last_msg = thread_store.get_last_message(thread_id) or "Nuova chat"
    from app.llm import providers
    effective_model = model or providers.get_active_model_name()
    title = thread_store.generate_and_save_title(thread_id, last_msg, model=effective_model)
    return {"status": "ok", "thread_id": thread_id, "title": title}


@router.post("/v1/threads/{thread_id}/messages/{message_id}/version", dependencies=[Depends(verify_api_key)])
async def switch_message_version(thread_id: str, message_id: str, req: SwitchVersionRequest):
    thread_store.update_message_version(thread_id, message_id, req.version_index)
    return {"status": "ok", "thread_id": thread_id, "message_id": message_id, "version_index": req.version_index}


@router.post("/v1/threads/{thread_id}/messages/{message_id}/versions_data", dependencies=[Depends(verify_api_key)])
async def update_message_versions(thread_id: str, message_id: str, req: SaveVersionsDataRequest):
    thread_store.update_message_versions_data(thread_id, message_id, req.versions, req.version_index)
    return {"status": "ok", "thread_id": thread_id, "message_id": message_id}


@router.delete("/v1/threads/{thread_id}", dependencies=[Depends(verify_api_key)])
async def delete_single_thread(thread_id: str):
    try:
        conn = sqlite3.connect(settings.checkpoint_db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        deleted_rows = cursor.rowcount
        cursor.execute("DELETE FROM thread_metadata WHERE thread_id = ?", (thread_id,))
        conn.commit()
        conn.close()

        thread_store.delete_thread_messages(thread_id)

        # Delete from Letta if agent exists (non-blocking)
        try:
            agent_id = letta_client.create_thread(thread_id)
            if agent_id:
                letta_client.delete_thread(agent_id)
        except Exception:
            pass

        return {"status": "deleted", "thread_id": thread_id, "deleted_checkpoints": deleted_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete thread '{thread_id}': {str(e)}") from e

@router.delete("/v1/threads", dependencies=[Depends(verify_api_key)])
async def delete_all_threads():
    try:
        conn = sqlite3.connect(settings.checkpoint_db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM checkpoints")
        deleted_rows = cursor.rowcount
        cursor.execute("DELETE FROM thread_metadata")
        conn.commit()
        conn.close()

        thread_store.clear_all_thread_messages()

        return {"status": "cleared", "deleted_checkpoints": deleted_rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear threads: {str(e)}") from e
