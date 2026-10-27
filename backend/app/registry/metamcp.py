from typing import Any, Dict, List

from app.agent.tool_catalog import get_tool_catalog
from app.mcp.client import get_mcp_client
from app.registry.base import BaseToolRegistry


class MetaMCPRegistry(BaseToolRegistry):
    @property
    def name(self) -> str:
        return "metamcp"

    def get_tools(self) -> List[Dict[str, Any]]:
        return get_tool_catalog()

    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        return get_mcp_client().call_tool(tool_name, args)
