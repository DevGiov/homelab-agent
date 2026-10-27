from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseToolRegistry(ABC):
    """Classe base astratta per tutti i registry di tool."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome identificativo del registry (es. 'metamcp', 'web', 'code')."""
        pass

    @abstractmethod
    def get_tools(self) -> List[Dict[str, Any]]:
        """
        Restituisce la lista di definizioni di tool nel formato:
        [{"name": str, "description": str, "parameters": dict}]
        """
        pass

    @abstractmethod
    def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """
        Esegue un tool specifico di questo registry con gli argomenti forniti.
        """
        pass
