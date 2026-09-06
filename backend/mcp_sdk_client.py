"""Client MCP basato sull'SDK ufficiale `mcp` (Fase 1.2).

Mantiene la stessa interfaccia di MetaMCPClient (list_tools / call_tool)
ma usa il transport SSE ufficiale con sessione persistente e lock.
Fallback automatico al client legacy se l'SDK non è installato o fallisce.
"""
import asyncio
import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mcp_sdk_client")

try:
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    logger.info("SDK 'mcp' non installato: uso il client legacy")


class MetaMCPSdkClient:
    """Wrapper sincrono attorno a ClientSession dell'SDK MCP (SSE transport)."""

    def __init__(self, base_url: str, api_key: str = "", timeout: int = 25):
        clean_url = (base_url or "").rstrip("/")
        if clean_url.endswith("/mcp"):
            clean_url = clean_url[:-4] + "/sse"
        elif not clean_url.endswith("/sse"):
            clean_url = clean_url + "/sse"
        self.base_url = clean_url
        self.api_key = api_key
        self.timeout = timeout
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._session = None
        self._lock = threading.Lock()

    def _ensure_loop(self):
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            threading.Thread(target=self._loop.run_forever, daemon=True).start()
        return self._loop

    def _run(self, coro, timeout: Optional[float] = None):
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout or self.timeout)

    def _connect(self):
        """Stabilisce la sessione MCP se assente."""
        if self._session is not None:
            return

        async def _do_connect():
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
                headers["x-api-key"] = self.api_key
            cm = sse_client(url=self.base_url, headers=headers, timeout=self.timeout)
            read_stream, write_stream = await cm.__aenter__()
            session = ClientSession(read_stream, write_stream)
            await session.__aenter__()
            await session.initialize()
            return cm, session

        self._cm, self._session = self._run(_do_connect(), timeout=self.timeout + 10)

    async def _aclose(self):
        try:
            if self._session:
                await self._session.__aexit__(None, None, None)
        except Exception:
            pass
        try:
            if getattr(self, "_cm", None):
                await self._cm.__aexit__(None, None, None)
        except Exception:
            pass
        self._session = None
        self._cm = None

    def reset(self):
        """Chiude la sessione corrente (usata in caso di errore per riconnettere)."""
        with self._lock:
            if self._loop and not self._loop.is_closed() and self._session is not None:
                try:
                    asyncio.run_coroutine_threadsafe(self._aclose(), self._loop).result(timeout=5)
                except Exception:
                    pass
            self._session = None

    def list_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            for attempt in (1, 2):
                try:
                    self._connect()

                    async def _do_list():
                        result = await self._session.list_tools()
                        return [
                            {
                                "name": t.name,
                                "description": t.description or "",
                                "inputSchema": t.inputSchema.model_dump(exclude_none=True) if t.inputSchema else {"type": "object", "properties": {}},
                            }
                            for t in result.tools
                        ]

                    return self._run(_do_list())
                except Exception as e:
                    logger.warning(f"[sdk] list_tools attempt {attempt} failed: {e}")
                    self.reset()
            raise RuntimeError("MCP SDK list_tools failed after retries")

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        with self._lock:
            for attempt in (1, 2):
                try:
                    self._connect()

                    async def _do_call():
                        result = await self._session.call_tool(tool_name, arguments=arguments)
                        content_parts = []
                        for item in (result.content or []):
                            if hasattr(item, "text"):
                                content_parts.append(item.text)
                        payload: Dict[str, Any] = {
                            "content": "\n".join(content_parts),
                            "isError": bool(result.isError),
                        }
                        structured = getattr(result, "structuredContent", None)
                        if structured:
                            payload["structured"] = structured
                        # Se c'è contenuto JSON nel testo, prova a parsarlo per compatibilità col resto del codice
                        text = payload["content"]
                        if text and text.lstrip().startswith(("{", "[")):
                            import json as _json
                            try:
                                parsed = _json.loads(text)
                                if isinstance(parsed, dict):
                                    parsed.setdefault("content", text)
                                    return parsed
                            except Exception:
                                pass
                        return payload

                    return self._run(_do_call())
                except Exception as e:
                    logger.warning(f"[sdk] call_tool('{tool_name}') attempt {attempt} failed: {e}")
                    self.reset()
            raise RuntimeError(f"MCP SDK call_tool('{tool_name}') failed after retries")
