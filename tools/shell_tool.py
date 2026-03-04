"""Shell tool for running system commands safely."""
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseTool, ToolResult, ToolSchema


# Default blocked command patterns for safety
DEFAULT_BLOCKED_PATTERNS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=",
    "> /dev/sd",
    ":(){ :|:& };:",  # Fork bomb
    "chmod -R 777 /",
    "chown -R",
    "wget | sh",
    "curl | sh",
]


class ShellTool(BaseTool):
    """Tool for executing shell commands with safety restrictions."""

    def __init__(
        self,
        allowed_dir: Optional[Path] = None,
        blocked_patterns: Optional[List[str]] = None,
        default_timeout: int = 60,
    ):
        self.allowed_dir = Path(allowed_dir).resolve() if allowed_dir else None
        self.blocked_patterns = blocked_patterns or DEFAULT_BLOCKED_PATTERNS
        self.default_timeout = default_timeout

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="shell",
            description="Execute shell commands safely. Commands are validated against blocked patterns. Output is captured and returned.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "default": 60,
                        "description": "Timeout in seconds (default: 60)",
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Working directory (default: current directory)",
                    },
                    "check": {
                        "type": "boolean",
                        "default": True,
                        "description": "Raise error on non-zero exit code",
                    },
                },
            },
            required=["command"],
        )

    def _is_blocked(self, command: str) -> Optional[str]:
        """Check if command matches blocked patterns. Returns reason or None."""
        cmd_lower = command.lower().strip()
        for pattern in self.blocked_patterns:
            if pattern.lower() in cmd_lower:
                return f"Command matches blocked pattern: {pattern}"
        return None

    def execute(
        self,
        command: str,
        timeout: Optional[int] = None,
        cwd: Optional[str] = None,
        check: bool = True,
        **kwargs,
    ) -> ToolResult:
        # Safety check
        blocked_reason = self._is_blocked(command)
        if blocked_reason:
            return ToolResult(success=False, output="", error=f"BLOCKED: {blocked_reason}")

        # Determine working directory
        work_dir = Path(cwd).resolve() if cwd else (self.allowed_dir or Path.cwd())

        # If allowed_dir is set, verify cwd is within it
        if self.allowed_dir and work_dir != self.allowed_dir:
            try:
                work_dir.relative_to(self.allowed_dir)
            except ValueError:
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Working directory must be within {self.allowed_dir}",
                )

        actual_timeout = timeout if timeout is not None else self.default_timeout

        try:
            cp = subprocess.run(
                command,
                cwd=str(work_dir),
                shell=True,
                text=True,
                capture_output=True,
                timeout=actual_timeout,
                encoding="utf-8",
                errors="replace",
            )

            success = cp.returncode == 0
            if check and not success:
                return ToolResult(
                    success=False,
                    output=cp.stdout or "",
                    error=cp.stderr or f"Command exited with code {cp.returncode}",
                    metadata={
                        "returncode": cp.returncode,
                        "command": command,
                        "cwd": str(work_dir),
                    },
                )

            return ToolResult(
                success=success,
                output=cp.stdout or "",
                error=cp.stderr if cp.stderr else None,
                metadata={
                    "returncode": cp.returncode,
                    "command": command,
                    "cwd": str(work_dir),
                },
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Command timed out after {actual_timeout} seconds",
                metadata={"command": command, "timeout": actual_timeout},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to execute command: {e}",
                metadata={"command": command},
            )
