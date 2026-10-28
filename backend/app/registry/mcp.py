from typing import Any, Dict, List

from app.agent.tool_catalog import get_tool_catalog
from app.mcp.hub import get_mcp_hub
from app.registry.base import BaseToolRegistry


class MCPRegistry(BaseToolRegistry):
    """Tool dei server MCP registrati (MetaMCP e quelli aggiunti dalla UI)."""

    @property
    def name(self) -> str:
        return "mcp"

    def get_tools(self) -> List[Dict[str, Any]]:
        return get_tool_catalog()

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        return get_mcp_hub().call_tool(tool_name, args)
