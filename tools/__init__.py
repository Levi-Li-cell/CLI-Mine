"""
Tools package for the AI Agent harness.

Provides core tools for:
- File operations (read, write, list, delete)
- Shell command execution (with safety restrictions)
- Web content fetching

Usage:
    from tools import ToolRegistry, FileTool, ShellTool, WebTool

    registry = ToolRegistry()
    registry.register(FileTool())
    registry.register(ShellTool())
    registry.register(WebTool())

    # Get tool schemas for function calling
    schemas = registry.get_all_schemas()

    # Execute a tool
    result = registry.execute("file", {"operation": "read", "path": "/tmp/test.txt"})

    # With constitutional safety policy (M2-001):
    from safety import Constitution, PolicyChecker

    constitution = Constitution.from_yaml("safety/policies/default.json")
    registry.set_policy_checker(PolicyChecker(constitution))

    # Now all executions are checked against the constitution
    result = registry.execute("shell", {"command": "rm -rf /"})
    # Returns: ToolResult(success=False, error="BLOCKED by policy: ...")

    # With retry policy (M1-004):
    from tools import RetryPolicy, RetryExecutor, create_default_fallback_handler

    policy = RetryPolicy(max_retries=3, base_delay=1.0)
    registry.set_retry_executor(RetryExecutor(
        policy=policy,
        fallback_handler=create_default_fallback_handler(),
        audit_log_path=Path(".agent/runtime/retry_log.jsonl"),
    ))

    result = registry.execute_with_retry("web", {"url": "https://example.com"})
"""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type, TYPE_CHECKING

from .base import BaseTool, ToolResult, ToolSchema, SchemaValidator, ValidationError
from .file_tool import FileTool
from .shell_tool import ShellTool
from .web_tool import WebTool
from .retry import (
    RetryPolicy,
    RetryExecutor,
    RetryAttempt,
    RetryLog,
    RetryAction,
    TransientErrorPattern,
    FallbackHandler,
    create_default_fallback_handler,
)

if TYPE_CHECKING:
    from safety import PolicyChecker, PolicyDecision


class ToolRegistry:
    """Registry for managing and executing tools."""

    def __init__(
        self,
        policy_checker: Optional["PolicyChecker"] = None,
        retry_executor: Optional[RetryExecutor] = None,
    ):
        self._tools: Dict[str, BaseTool] = {}
        self._policy_checker: Optional["PolicyChecker"] = policy_checker
        self._retry_executor: Optional[RetryExecutor] = retry_executor

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        name = tool.schema.name
        if name in self._tools:
            raise ValueError(f"Tool already registered: {name}")
        self._tools[name] = tool

    def unregister(self, name: str) -> bool:
        """Unregister a tool by name. Returns True if found."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_schema(self, name: str) -> Optional[ToolSchema]:
        """Get a tool's schema by name."""
        tool = self.get(name)
        return tool.schema if tool else None

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """Get all registered tool schemas as dicts."""
        return [tool.schema.to_dict() for tool in self._tools.values()]

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def set_policy_checker(self, checker: Optional["PolicyChecker"]) -> None:
        """Set or clear the policy checker for this registry.

        When set, all tool executions will be checked against the constitutional
        policy before being executed.

        Args:
            checker: PolicyChecker instance or None to disable policy checking
        """
        self._policy_checker = checker

    def get_policy_checker(self) -> Optional["PolicyChecker"]:
        """Get the current policy checker, if any."""
        return self._policy_checker

    def set_retry_executor(self, executor: Optional[RetryExecutor]) -> None:
        """Set or clear the retry executor for this registry.

        When set, execute_with_retry() will use this executor to handle
        transient failures with automatic retries and fallback strategies.

        Args:
            executor: RetryExecutor instance or None to disable retry logic
        """
        self._retry_executor = executor

    def get_retry_executor(self) -> Optional[RetryExecutor]:
        """Get the current retry executor, if any."""
        return self._retry_executor

    def execute(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        """Execute a tool by name with given arguments.

        Arguments are validated against the tool's schema before execution.
        If a policy checker is set, the action is also checked against the
        constitutional policy before execution.

        Validation errors and policy violations are returned as ToolResult
        with success=False.
        """
        tool = self.get(name)
        if not tool:
            return ToolResult(
                success=False,
                output="",
                error=f"Unknown tool: {name}. Available: {', '.join(self.list_tools())}",
            )

        # Validate arguments against schema
        errors = SchemaValidator.validate(arguments, tool.schema)
        if errors:
            return ToolResult(
                success=False,
                output="",
                error=f"Validation failed: {'; '.join(errors)}",
            )

        # Check constitutional policy (M2-001)
        if self._policy_checker:
            decision = self._policy_checker.check(name, arguments)
            if not decision.allowed:
                error_msg = f"BLOCKED by policy: {decision.reason}"
                if decision.alternative:
                    error_msg += f"\nSuggested alternative: {decision.alternative}"
                return ToolResult(
                    success=False,
                    output="",
                    error=error_msg,
                    metadata={
                        "policy_decision": decision.to_dict(),
                        "blocked": True,
                    },
                )

        return tool.execute(**arguments)

    def execute_with_retry(
        self,
        name: str,
        arguments: Dict[str, Any],
    ) -> ToolResult:
        """Execute a tool with retry logic for transient failures.

        This method wraps execute() with automatic retry handling:
        - Detects transient errors (timeouts, rate limits, 5xx errors)
        - Retries with exponential backoff
        - Calls fallback handler if all retries fail
        - Logs all retry attempts

        If no retry executor is configured, falls back to regular execute().

        Args:
            name: Tool name to execute
            arguments: Arguments to pass to the tool

        Returns:
            ToolResult with success/failure and retry metadata
        """
        if not self._retry_executor:
            return self.execute(name, arguments)

        return self._retry_executor.execute_with_retry(
            execute_fn=self.execute,
            tool_name=name,
            arguments=arguments,
        )

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


def create_default_registry(
    allowed_dir: Optional[str] = None,
    shell_timeout: int = 60,
    web_timeout: int = 30,
    constitution_path: Optional[str] = None,
    retry_policy: Optional[RetryPolicy] = None,
    retry_audit_log: Optional[str] = None,
) -> ToolRegistry:
    """Create a registry with default tools registered.

    Args:
        allowed_dir: Optional directory to restrict shell operations to
        shell_timeout: Default timeout for shell commands
        web_timeout: Default timeout for web requests
        constitution_path: Optional path to constitution file for policy checking
        retry_policy: Optional RetryPolicy for automatic retry on transient failures
        retry_audit_log: Optional path for retry attempt logging (JSONL)

    Returns:
        Configured ToolRegistry instance
    """
    from pathlib import Path

    registry = ToolRegistry()
    registry.register(FileTool())
    registry.register(
        ShellTool(
            allowed_dir=Path(allowed_dir) if allowed_dir else None,
            default_timeout=shell_timeout,
        )
    )
    registry.register(WebTool(default_timeout=web_timeout))

    # Load constitution if path provided (M2-001)
    if constitution_path:
        try:
            from safety import Constitution, PolicyChecker
            constitution = Constitution.from_yaml(Path(constitution_path))
            registry.set_policy_checker(PolicyChecker(constitution))
        except Exception as e:
            # Log warning but don't fail - registry still works without policy
            import warnings
            warnings.warn(f"Failed to load constitution from {constitution_path}: {e}")

    # Configure retry executor if policy provided (M1-004)
    if retry_policy:
        audit_path = Path(retry_audit_log) if retry_audit_log else None
        registry.set_retry_executor(RetryExecutor(
            policy=retry_policy,
            fallback_handler=create_default_fallback_handler(),
            audit_log_path=audit_path,
        ))

    return registry


__all__ = [
    "BaseTool",
    "ToolSchema",
    "ToolResult",
    "ToolRegistry",
    "SchemaValidator",
    "ValidationError",
    "FileTool",
    "ShellTool",
    "WebTool",
    "create_default_registry",
    # Retry policy (M1-004)
    "RetryPolicy",
    "RetryExecutor",
    "RetryAttempt",
    "RetryLog",
    "RetryAction",
    "TransientErrorPattern",
    "FallbackHandler",
    "create_default_fallback_handler",
]
