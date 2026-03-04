"""Base tool infrastructure for the AI Agent harness."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


class ValidationError(Exception):
    """Raised when tool argument validation fails."""
    pass


class SchemaValidator:
    """Validates tool arguments against JSON Schema-like definitions."""

    @staticmethod
    def validate(
        args: Dict[str, Any],
        schema: "ToolSchema",
    ) -> List[str]:
        """Validate args against schema. Returns list of error messages (empty if valid)."""
        errors: List[str] = []

        # Check required parameters
        for req in schema.required:
            if req not in args:
                errors.append(f"Missing required parameter: '{req}'")
            elif args[req] is None:
                errors.append(f"Required parameter '{req}' cannot be None")

        # Get parameter definitions
        params = schema.parameters.get("properties", {})

        # Validate each provided argument
        for key, value in args.items():
            if key not in params:
                # Check if additionalProperties is allowed
                additional = schema.parameters.get("additionalProperties", True)
                if additional is False:
                    errors.append(f"Unknown parameter: '{key}'")
                continue

            param_def = params[key]
            param_errors = SchemaValidator._validate_value(key, value, param_def)
            errors.extend(param_errors)

        return errors

    @staticmethod
    def _validate_value(key: str, value: Any, schema: Dict[str, Any]) -> List[str]:
        """Validate a single value against its schema definition."""
        errors: List[str] = []

        if value is None:
            # null is handled by required check; if optional and None, it's OK
            return errors

        expected_type = schema.get("type")
        if expected_type:
            type_valid = SchemaValidator._check_type(value, expected_type)
            if not type_valid:
                errors.append(
                    f"Parameter '{key}' has wrong type. "
                    f"Expected {expected_type}, got {SchemaValidator._typename(type(value))}"
                )
                return errors  # Skip further checks if type is wrong

        # Check enum constraint
        enum_values = schema.get("enum")
        if enum_values and value not in enum_values:
            errors.append(
                f"Parameter '{key}' has invalid value '{value}'. "
                f"Must be one of: {enum_values}"
            )

        # Check minimum/maximum for numbers
        if isinstance(value, (int, float)):
            minimum = schema.get("minimum")
            if minimum is not None and value < minimum:
                errors.append(f"Parameter '{key}' value {value} is below minimum {minimum}")
            maximum = schema.get("maximum")
            if maximum is not None and value > maximum:
                errors.append(f"Parameter '{key}' value {value} is above maximum {maximum}")

        # Check minLength/maxLength for strings
        if isinstance(value, str):
            min_len = schema.get("minLength")
            if min_len is not None and len(value) < min_len:
                errors.append(f"Parameter '{key}' is too short (min {min_len} chars)")
            max_len = schema.get("maxLength")
            if max_len is not None and len(value) > max_len:
                errors.append(f"Parameter '{key}' is too long (max {max_len} chars)")

        return errors

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        """Check if value matches the expected JSON Schema type."""
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }

        expected = type_map.get(expected_type)
        if expected is None:
            return True  # Unknown type, skip validation

        # Special case: number accepts both int and float
        if expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        # Special case: integer must be actual int, not bool
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)

        return isinstance(value, expected)

    @staticmethod
    def _typename(py_type: type) -> str:
        """Convert Python type to readable name."""
        type_names = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
            type(None): "null",
        }
        return type_names.get(py_type, py_type.__name__)


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
        errors = SchemaValidator.validate(kwargs, self.schema)
        if errors:
            return "; ".join(errors)
        return None

    def __call__(self, **kwargs) -> ToolResult:
        """Allow tool to be called directly."""
        error = self.validate_args(kwargs)
        if error:
            return ToolResult(success=False, output="", error=error)
        return self.execute(**kwargs)
