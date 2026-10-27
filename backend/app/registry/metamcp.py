# Assicura che la directory backend sia nell'import path
import logging
from typing import Any, Dict, List

from app.agent.tool_catalog import get_tool_catalog
from app.core import config
from app.mcp.client import MetaMCPClient
from app.registry.base import BaseToolRegistry

logger = logging.getLogger("metamcp_registry")

try:
    from app.mcp.sdk_client import _SDK_AVAILABLE, MetaMCPSdkClient
except ImportError:
    _SDK_AVAILABLE = False

class MetaMCPRegistry(BaseToolRegistry):
    def __init__(self):
        self._client = MetaMCPClient(config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
        # Fase 1.2: preferisci SDK ufficiale MCP, fallback al client legacy
        self._sdk_client = None
        if _SDK_AVAILABLE:
            try:
                self._sdk_client = MetaMCPSdkClient(config.METAMCP_URL, api_key=config.METAMCP_API_KEY)
            except Exception as e:
                logger.warning(f"SDK client non inizializzabile: {e}")

    @property
    def name(self) -> str:
        return "metamcp"

    def get_tools(self) -> List[Dict[str, Any]]:
        return get_tool_catalog()

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        if self._sdk_client is not None:
            try:
                return self._sdk_client.call_tool(tool_name, args)
            except Exception as e:
                logger.warning(f"SDK call fallito per '{tool_name}', fallback legacy: {e}")
        return self._client.call_tool(tool_name, args)
