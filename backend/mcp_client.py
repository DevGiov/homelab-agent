import json
import logging
import re
import threading
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_client")


class MetaMCPClient:
    """
    Client dinamico per MetaMCP conforme alle specifiche Model Context Protocol (MCP).
    Supporta:
    - Auto-discovery degli endpoint tramite GET /metamcp
    - Streamable HTTP Transport (JSON-RPC POST con header mcp-session-id e Accept application/json, text/event-stream)
    - SSE Transport bidirezionale
    - Fallback resiliente e auto-reconnect
    """

    def __init__(self, base_url: str, api_key: str = "", timeout: int = 40):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self._endpoints_cache: Optional[Dict[str, str]] = None
        self._session_id: Optional[str] = None
        self._lock = threading.Lock()

    @property
    def headers(self) -> Dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "Homelab-Agent-MetaMCP/2.0"
        }
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
            h["x-api-key"] = self.api_key
        if self._session_id:
            h["mcp-session-id"] = self._session_id
        return h

    def _discover_endpoints(self) -> Dict[str, str]:
        """Auto-scopre gli endpoint disponibili interrogando GET /metamcp."""
        if self._endpoints_cache:
            return self._endpoints_cache

        base_parsed = urllib.parse.urlparse(self.base_url)
        origin = f"{base_parsed.scheme}://{base_parsed.netloc}"

        endpoints = {
            "mcp": f"{origin}/metamcp/MetaMCP/mcp",
            "sse": f"{origin}/metamcp/MetaMCP/sse",
            "api": f"{origin}/metamcp/MetaMCP/api",
            "openapi": f"{origin}/metamcp/MetaMCP/api/openapi.json"
        }

        try:
            r = requests.get(f"{origin}/metamcp", headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}, timeout=5)
            if r.status_code == 200:
                data = r.json()
                ep_list = data.get("endpoints", [])
                if ep_list and isinstance(ep_list, list):
                    first = ep_list[0].get("endpoints", {})
                    for k, v in first.items():
                        if v.startswith("/"):
                            endpoints[k] = f"{origin}{v}"
                        else:
                            endpoints[k] = v
                    logger.info(f"Auto-scoperti endpoint MetaMCP da /metamcp: {endpoints}")
        except Exception as e:
            logger.debug(f"Discovery /metamcp non disponibile ({e}), uso fallback URL.")

        self._endpoints_cache = endpoints
        return endpoints

    def _get_mcp_url(self) -> str:
        eps = self._discover_endpoints()
        if "mcp" in eps:
            return eps["mcp"]
        if self.base_url.endswith("/sse"):
            return self.base_url[:-4] + "/mcp"
        return self.base_url

    def _get_sse_url(self) -> str:
        eps = self._discover_endpoints()
        if "sse" in eps:
            return eps["sse"]
        if self.base_url.endswith("/mcp"):
            return self.base_url[:-4] + "/sse"
        return self.base_url

    def _parse_mcp_response(self, text: str) -> Optional[Dict[str, Any]]:
        """Estrae il payload JSON-RPC dal corpo della risposta (sia JSON standard sia text/event-stream)."""
        if not text:
            return None
        clean = text.strip()

        # Se è JSON diretto
        if clean.startswith("{") and clean.endswith("}"):
            try:
                return json.loads(clean)
            except Exception:
                pass

        # Se è un flusso SSE (event: message / data: ...)
        for line in clean.splitlines():
            line_s = line.strip()
            if line_s.startswith("data:"):
                json_str = line_s[5:].strip()
                try:
                    return json.loads(json_str)
                except Exception:
                    continue
        return None

    def _execute_http_streamable(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Esegue una chiamata JSON-RPC tramite il protocollo Streamable HTTP MCP."""
        mcp_url = self._get_mcp_url()
        sess = requests.Session()
        req_headers = self.headers

        # 1. Se non abbiamo ancora un session_id, effettuiamo l'handshake di initialize
        if not self._session_id:
            init_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "homelab-agent", "version": "2.0"}
                }
            }
            init_res = sess.post(mcp_url, headers=req_headers, json=init_payload, timeout=self.timeout)
            if init_res.status_code in (200, 201, 202):
                sid = init_res.headers.get("mcp-session-id") or init_res.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                    req_headers["mcp-session-id"] = sid
                # Notifica initialized
                try:
                    sess.post(mcp_url, headers=req_headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=10)
                except Exception:
                    pass
            else:
                logger.warning(f"Handshake initialize fallito con status {init_res.status_code}: {init_res.text[:150]}")

        # 2. Esegui la richiesta richiesta
        call_id = int(time.time() * 1000) % 1000000
        payload = {
            "jsonrpc": "2.0",
            "id": call_id,
            "method": method,
            "params": params if params is not None else {}
        }

        resp = sess.post(mcp_url, headers=req_headers, json=payload, timeout=self.timeout)
        if resp.status_code not in (200, 201, 202):
            # Se la sessione è scaduta, resetta e ritenta una volta
            if resp.status_code in (400, 404, 408):
                self._session_id = None
                return self._execute_http_streamable(method, params)
            raise RuntimeError(f"Chiamata MCP '{method}' fallita con status {resp.status_code}: {resp.text}")

        parsed = self._parse_mcp_response(resp.text)
        if parsed:
            if "error" in parsed:
                raise RuntimeError(f"Errore JSON-RPC da MetaMCP: {parsed['error']}")
            return parsed.get("result", {})

        return {"status": "ok", "raw": resp.text}

    def _execute_sse_session(self, action_func: Callable) -> Any:
        """Fallback SSE streaming per server MCP che richiedono canale SSE continuo."""
        sse_url = self._get_sse_url()
        sse_res = requests.get(sse_url, headers={**self.headers, "Accept": "text/event-stream"}, stream=True, timeout=self.timeout)
        if sse_res.status_code != 200:
            raise RuntimeError(f"Apertura stream SSE fallita, status {sse_res.status_code}")

        post_url_container = []
        responses: Dict[Any, Any] = {}
        stop_event = threading.Event()
        req_id_counter = 0
        req_lock = threading.Lock()
        post_session = requests.Session()

        def next_id():
            nonlocal req_id_counter
            with req_lock:
                req_id_counter += 1
                return req_id_counter

        def read_sse():
            try:
                for line in sse_res.iter_lines(decode_unicode=True):
                    if stop_event.is_set():
                        break
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if "sessionId=" in data_str:
                            base = urllib.parse.urlparse(sse_url)
                            p_url = f"{base.scheme}://{base.netloc}{data_str}" if data_str.startswith("/") else data_str
                            post_url_container.append(p_url)
                        else:
                            try:
                                msg = json.loads(data_str)
                                if "id" in msg and msg["id"] is not None:
                                    responses[msg["id"]] = msg
                            except Exception:
                                pass
            except Exception:
                pass

        listener = threading.Thread(target=read_sse, daemon=True)
        listener.start()

        start = time.time()
        while not post_url_container and time.time() - start < self.timeout:
            time.sleep(0.05)

        if not post_url_container:
            stop_event.set()
            sse_res.close()
            raise RuntimeError("Timeout in attesa del session endpoint SSE.")

        post_url = post_url_container[0]

        def send_request(method: str, params: dict = None, is_notification: bool = False):
            rid = None if is_notification else next_id()
            payload = {"jsonrpc": "2.0", "method": method}
            if rid is not None:
                payload["id"] = rid
            if params is not None:
                payload["params"] = params
            post_session.post(post_url, headers=self.headers, json=payload, timeout=self.timeout)
            return rid

        def wait_response(req_id: int, req_timeout: int = 30):
            s_time = time.time()
            while time.time() - s_time < req_timeout:
                if req_id in responses:
                    return responses[req_id]
                time.sleep(0.05)
            raise TimeoutError(f"Timeout in attesa della risposta JSON-RPC id {req_id}")

        try:
            init_id = send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "homelab-agent", "version": "2.0"}
            })
            wait_response(init_id, self.timeout)
            send_request("notifications/initialized", is_notification=True)
            return action_func(send_request, wait_response)
        finally:
            stop_event.set()
            sse_res.close()
            post_session.close()

    def list_tools(self) -> List[Dict[str, Any]]:
        """Recupera la lista dinamica dei tool registrati su MetaMCP."""
        # 1. Prova Streamable HTTP
        try:
            res = self._execute_http_streamable("tools/list", {})
            if isinstance(res, dict) and "tools" in res:
                return res["tools"]
            if isinstance(res, list):
                return res
        except Exception as e:
            logger.debug(f"Streamable HTTP tools/list fallito ({e}), provo fallback SSE.")

        # 2. Prova SSE
        try:
            def _action(send_req, wait_resp):
                rid = send_req("tools/list", {})
                resp = wait_resp(rid, self.timeout)
                if "result" in resp and "tools" in resp["result"]:
                    return resp["result"]["tools"]
                return resp.get("result", [])
            return self._execute_sse_session(_action)
        except Exception as e:
            logger.warning(f"SSE list_tools fallito: {e}")
            raise

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Esegue un tool chiamando tools/call su MetaMCP."""
        # 1. Prova Streamable HTTP
        try:
            res = self._execute_http_streamable("tools/call", {"name": tool_name, "arguments": arguments})
            if res:
                return res
        except Exception as e:
            logger.debug(f"Streamable HTTP call_tool fallito ({e}), provo fallback SSE.")

        # 2. Prova SSE
        def _action(send_req, wait_resp):
            rid = send_req("tools/call", {"name": tool_name, "arguments": arguments})
            resp = wait_resp(rid, self.timeout)
            if "result" in resp:
                return resp["result"]
            if "error" in resp:
                return resp["error"]
            return resp

        return self._execute_sse_session(_action)
