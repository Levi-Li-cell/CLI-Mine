"""Base tool infrastructure for the AI Agent harness."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolSchema:
    """JSON Schema-like tool definition for function calling."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema for parameters
    required: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "required": self.required,
        }


@dataclass
class ToolResult:
    """Result from tool execution."""
    success: bool
    output: str
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseTool(ABC):
    """Abstract base class for all tools."""

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """Return the tool's schema for function calling."""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters."""
        pass

    def validate_args(self, kwargs: Dict[str, Any]) -> Optional[str]:
        """Validate arguments against schema. Returns error message or None."""
        for req in self.schema.required:
            if req not in kwargs:
                return f"Missing required parameter: {req}"
            if kwargs[req] is None:
                return f"Parameter '{req}' cannot be None"
        return None

    def __call__(self, **kwargs) -> ToolResult:
        """Allow tool to be called directly."""
        error = self.validate_args(kwargs)
        if error:
            return ToolResult(success=False, output="", error=error)
        return self.execute(**kwargs)
