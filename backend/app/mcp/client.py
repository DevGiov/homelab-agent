"""Client MCP sincrono sull'SDK ufficiale (transport Streamable HTTP).

Il grafo e i registry sono sincroni: un event loop dedicato, in un thread daemon, tiene aperta
una sola sessione MCP per processo. La sessione vive dentro un unico task (`_hold_session`),
così trasporto e ClientSession vengono aperti e chiusi nello stesso task come richiede anyio.

Retry con reset di sessione:
- `list_tools` è di sola lettura: dopo un errore resetta la sessione e ritenta una volta.
- `call_tool` ritenta solo se la sessione era già aperta prima della chiamata (tipicamente
  scaduta perché MetaMCP è stato riavviato) e l'errore non è un timeout. Una sessione appena
  creata o un timeout non vengono ritentati: il tool potrebbe essere già stato eseguito.
"""
import asyncio
import json
import logging
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.core import config

logger = logging.getLogger("mcp_client")

CONNECT_TIMEOUT_SECONDS = 15.0
LIST_TIMEOUT_SECONDS = 25.0
CALL_TIMEOUT_SECONDS = 120.0


class MCPClient:
    def __init__(self, url: str, api_key: str = ""):
        self.url = url
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._session: Optional[ClientSession] = None
        self._close_event: Optional[asyncio.Event] = None
        self._holder: Optional[asyncio.Task] = None

    # --- event loop e sessione ------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            threading.Thread(target=self._loop.run_forever, name="mcp-client-loop", daemon=True).start()
        return self._loop

    def _run(self, coro, timeout: float):
        return asyncio.run_coroutine_threadsafe(coro, self._ensure_loop()).result(timeout=timeout)

    async def _hold_session(self, ready: asyncio.Future, close: asyncio.Event):
        try:
            timeout = httpx2.Timeout(CONNECT_TIMEOUT_SECONDS, read=CALL_TIMEOUT_SECONDS)
            async with httpx2.AsyncClient(headers=self.headers, timeout=timeout) as http_client:
                async with streamable_http_client(self.url, http_client=http_client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        ready.set_result(session)
                        await close.wait()
        except Exception as e:
            if not ready.done():
                ready.set_exception(e)
            else:
                logger.warning(f"Sessione MCP chiusa con errore: {e}")

    async def _open(self):
        ready = asyncio.get_running_loop().create_future()
        close = asyncio.Event()
        holder = asyncio.create_task(self._hold_session(ready, close))
        try:
            session = await asyncio.wait_for(ready, CONNECT_TIMEOUT_SECONDS)
        except BaseException:
            holder.cancel()
            raise
        return session, close, holder

    async def _close(self, close: asyncio.Event, holder: asyncio.Task):
        close.set()
        try:
            await asyncio.wait_for(holder, 5)
        except Exception:
            holder.cancel()

    def _session_alive(self) -> bool:
        return self._session is not None and self._holder is not None and not self._holder.done()

    def _connect(self) -> ClientSession:
        if not self._session_alive():
            self._reset()
            self._session, self._close_event, self._holder = self._run(self._open(), CONNECT_TIMEOUT_SECONDS + 5)
            logger.info(f"Sessione MCP aperta su {self.url}")
        return self._session

    def _reset(self):
        if self._close_event is not None and self._holder is not None:
            try:
                self._run(self._close(self._close_event, self._holder), 10)
            except Exception as e:
                logger.debug(f"Chiusura sessione MCP: {e}")
        self._session = self._close_event = self._holder = None

    # --- API ------------------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """Tool esposti dal server: [{name, description, inputSchema}]."""
        with self._lock:
            for attempt in (1, 2):
                try:
                    session = self._connect()
                    result = self._run(session.list_tools(), LIST_TIMEOUT_SECONDS)
                    return [
                        {
                            "name": t.name,
                            "description": t.description or "",
                            "inputSchema": t.input_schema or {"type": "object", "properties": {}},
                        }
                        for t in result.tools
                    ]
                except Exception as e:
                    self._reset()
                    if attempt == 2:
                        raise RuntimeError(f"MCP list_tools fallito: {e}") from e
                    logger.warning(f"MCP list_tools fallito ({e}): nuova sessione e nuovo tentativo")
        raise AssertionError("unreachable")

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Esegue un tool. Errore del tool → {"error": testo}; JSON oggetto → dict; altro testo → {"content": testo}."""
        with self._lock:
            for attempt in (1, 2):
                reused = self._session_alive()
                try:
                    session = self._connect()
                    result = self._run(session.call_tool(tool_name, arguments=arguments), CALL_TIMEOUT_SECONDS)
                    return _normalize_result(result)
                except Exception as e:
                    self._reset()
                    retry = attempt == 1 and reused and not isinstance(e, TimeoutError)
                    if not retry:
                        raise RuntimeError(f"MCP call_tool('{tool_name}') fallito: {e}") from e
                    logger.warning(f"MCP call_tool('{tool_name}') fallito su sessione esistente ({e}): nuova sessione e nuovo tentativo")
        raise AssertionError("unreachable")


def _normalize_result(result: Any) -> Dict[str, Any]:
    text = "\n".join(item.text for item in (getattr(result, "content", None) or []) if hasattr(item, "text"))
    if getattr(result, "is_error", False):
        return {"error": text or "Il tool MCP ha restituito un errore senza dettagli"}
    if text.lstrip().startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and not text:
        return structured
    return {"content": text}


@lru_cache(maxsize=1)
def get_mcp_client() -> MCPClient:
    """Client condiviso verso MetaMCP: una sessione per processo."""
    return MCPClient(config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
