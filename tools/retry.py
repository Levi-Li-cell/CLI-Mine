"""Tool failure retry and fallback policy (M1-004)."""
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import ToolResult


class RetryAction(Enum):
    """Action to take after a tool failure."""
    RETRY = "retry"
    FALLBACK = "fallback"
    FAIL = "fail"


@dataclass
class TransientErrorPattern:
    """Pattern for detecting transient/retriable errors."""
    pattern: str  # Regex pattern to match in error message
    description: str
    tool_names: Optional[List[str]] = None  # None = all tools

    def matches(self, tool_name: str, error_message: str) -> bool:
        """Check if this pattern matches the error."""
        if self.tool_names and tool_name not in self.tool_names:
            return False
        return bool(re.search(self.pattern, error_message, re.IGNORECASE))


# Default transient error patterns
DEFAULT_TRANSIENT_PATTERNS = [
    # Network/Web transient errors
    TransientErrorPattern(
        pattern=r"(timeout|timed out|connection refused|connection reset|connection lost)",
        description="Network timeout or connection issue",
        tool_names=["web", "shell"],
    ),
    TransientErrorPattern(
        pattern=r"(HTTP 5\d{2}|internal server error|bad gateway|service unavailable|gateway timeout)",
        description="Server-side HTTP error (5xx)",
        tool_names=["web"],
    ),
    TransientErrorPattern(
        pattern=r"(HTTP 429|too many requests|rate limit)",
        description="Rate limiting",
        tool_names=["web"],
    ),
    TransientErrorPattern(
        pattern=r"(URLError|socket error|network unreachable|name or service not known)",
        description="Network/DNS error",
        tool_names=["web"],
    ),
    # Shell transient errors
    TransientErrorPattern(
        pattern=r"(resource temporarily unavailable|try again)",
        description="Temporary resource unavailability",
        tool_names=["shell"],
    ),
    # File system transient errors
    TransientErrorPattern(
        pattern=r"(resource deadlock avoided|lock|another process)",
        description="File lock or resource contention",
        tool_names=["file"],
    ),
]


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0  # Seconds
    max_delay: float = 30.0  # Seconds
    exponential_base: float = 2.0
    jitter: bool = True  # Add random jitter to prevent thundering herd

    # Patterns for detecting transient errors
    transient_patterns: List[TransientErrorPattern] = field(
        default_factory=lambda: DEFAULT_TRANSIENT_PATTERNS
    )

    # HTTP status codes to retry (for web tool)
    retryable_http_status_codes: List[int] = field(
        default_factory=lambda: [429, 500, 502, 503, 504]
    )

    def is_transient_error(
        self,
        tool_name: str,
        result: "ToolResult",
    ) -> bool:
        """Check if an error is transient and should be retried."""
        if result.success:
            return False

        error_msg = result.error or ""

        # Check against transient patterns
        for pattern in self.transient_patterns:
            if pattern.matches(tool_name, error_msg):
                return True

        # Check HTTP status codes in metadata
        status = result.metadata.get("status")
        if status and status in self.retryable_http_status_codes:
            return True

        return False

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number (0-indexed)."""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)

        if self.jitter:
            # Add up to 25% jitter
            import random
            delay = delay * (1 + random.random() * 0.25)

        return delay


@dataclass
class RetryAttempt:
    """Record of a single retry attempt."""
    attempt_number: int
    tool_name: str
    arguments: Dict[str, Any]
    result: "ToolResult"
    delay_before: float  # Delay before this attempt (0 for first)
    timestamp: str
    is_transient: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "result": self.result.to_dict() if hasattr(self.result, 'to_dict') else str(self.result),
            "delay_before": self.delay_before,
            "timestamp": self.timestamp,
            "is_transient": self.is_transient,
        }


@dataclass
class RetryLog:
    """Log of all retry attempts for a single tool execution."""
    tool_name: str
    arguments: Dict[str, Any]
    attempts: List[RetryAttempt] = field(default_factory=list)
    final_result: Optional["ToolResult"] = None
    total_duration: float = 0.0
    used_fallback: bool = False
    fallback_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "attempts": [a.to_dict() for a in self.attempts],
            "final_result": self.final_result.to_dict() if self.final_result and hasattr(self.final_result, 'to_dict') else None,
            "total_duration": self.total_duration,
            "used_fallback": self.used_fallback,
            "fallback_reason": self.fallback_reason,
        }


# Type for fallback handler
FallbackHandler = Callable[[str, Dict[str, Any], "ToolResult"], Optional["ToolResult"]]


class RetryExecutor:
    """Executes tools with retry and fallback logic."""

    def __init__(
        self,
        policy: Optional[RetryPolicy] = None,
        fallback_handler: Optional[FallbackHandler] = None,
        audit_log_path: Optional[Path] = None,
    ):
        self.policy = policy or RetryPolicy()
        self.fallback_handler = fallback_handler
        self.audit_log_path = audit_log_path

    def _log_retry(self, retry_log: RetryLog) -> None:
        """Log retry attempts to audit file."""
        if not self.audit_log_path:
            return

        try:
            # Ensure directory exists
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)

            # Append to JSONL file
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "type": "retry_log",
                    "at": datetime.now().isoformat(),
                    **retry_log.to_dict()
                }) + "\n")
        except Exception:
            # Don't fail execution if logging fails
            pass

    def execute_with_retry(
        self,
        execute_fn: Callable[[str, Dict[str, Any]], "ToolResult"],
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> "ToolResult":
        """Execute a tool with retry logic.

        Args:
            execute_fn: Function that executes the tool (takes name, args)
            tool_name: Name of the tool to execute
            arguments: Arguments to pass to the tool

        Returns:
            Final ToolResult (either success, or failure after all retries)
        """
        from .base import ToolResult

        start_time = time.time()
        retry_log = RetryLog(tool_name=tool_name, arguments=arguments.copy())

        attempt = 0
        delay = 0.0
        last_result: Optional[ToolResult] = None

        while attempt <= self.policy.max_retries:
            # Execute the tool
            result = execute_fn(tool_name, arguments)

            # Record the attempt
            is_transient = self.policy.is_transient_error(tool_name, result)
            retry_log.attempts.append(RetryAttempt(
                attempt_number=attempt,
                tool_name=tool_name,
                arguments=arguments.copy(),
                result=result,
                delay_before=delay,
                timestamp=datetime.now().isoformat(),
                is_transient=is_transient,
            ))

            # Success - return immediately
            if result.success:
                retry_log.final_result = result
                retry_log.total_duration = time.time() - start_time
                self._log_retry(retry_log)
                return result

            # Non-transient error - don't retry
            if not is_transient:
                retry_log.final_result = result
                retry_log.total_duration = time.time() - start_time
                self._log_retry(retry_log)
                return result

            # Transient error - check if we can retry
            if attempt >= self.policy.max_retries:
                # Exhausted retries - try fallback
                break

            # Calculate delay and sleep before next attempt
            delay = self.policy.get_delay(attempt)
            time.sleep(delay)
            attempt += 1
            last_result = result

        # All retries exhausted - try fallback
        if self.fallback_handler and last_result:
            try:
                fallback_result = self.fallback_handler(tool_name, arguments, last_result)
                if fallback_result:
                    retry_log.used_fallback = True
                    retry_log.fallback_reason = "All retries exhausted for transient error"
                    retry_log.final_result = fallback_result
                    retry_log.total_duration = time.time() - start_time
                    self._log_retry(retry_log)
                    return fallback_result
            except Exception as e:
                # Fallback failed - continue to return original error
                retry_log.fallback_reason = f"Fallback handler raised: {e}"

        # No fallback or fallback failed
        if last_result:
            # Enhance error message with retry info
            enhanced_result = ToolResult(
                success=False,
                output=last_result.output,
                error=f"{last_result.error} (retried {attempt} times)",
                metadata={
                    **last_result.metadata,
                    "retry_attempts": attempt,
                    "retry_exhausted": True,
                },
            )
            retry_log.final_result = enhanced_result
        else:
            retry_log.final_result = last_result

        retry_log.total_duration = time.time() - start_time
        self._log_retry(retry_log)
        return retry_log.final_result


# Built-in fallback handlers

def file_read_fallback(tool_name: str, arguments: Dict[str, Any], last_result: "ToolResult") -> Optional["ToolResult"]:
    """Fallback for file read operations - try with different encoding."""
    from .base import ToolResult

    if tool_name != "file":
        return None

    operation = arguments.get("operation", "")
    if operation != "read":
        return None

    path = arguments.get("path", "")
    encoding = arguments.get("encoding", "utf-8")

    # Try alternative encodings
    alternative_encodings = ["utf-8", "latin-1", "cp1252", "ascii"]

    for alt_encoding in alternative_encodings:
        if alt_encoding == encoding:
            continue
        try:
            with open(path, "r", encoding=alt_encoding) as f:
                content = f.read()
            return ToolResult(
                success=True,
                output=content,
                metadata={
                    "path": path,
                    "encoding_used": alt_encoding,
                    "fallback": True,
                },
            )
        except Exception:
            continue

    return None


def web_fetch_fallback(tool_name: str, arguments: Dict[str, Any], last_result: "ToolResult") -> Optional["ToolResult"]:
    """Fallback for web fetch - try with longer timeout."""
    from .base import ToolResult
    import urllib.request
    import urllib.error

    if tool_name != "web":
        return None

    operation = arguments.get("operation", "")
    if operation not in ("fetch", None):
        return None

    url = arguments.get("url", "")
    original_timeout = arguments.get("timeout", 30)

    # Try with 2x timeout
    extended_timeout = original_timeout * 2
    if extended_timeout > 120:  # Cap at 2 minutes
        return None

    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ClaudeLike-Agent/1.0"})
        with urllib.request.urlopen(request, timeout=extended_timeout) as response:
            content = response.read(10001)
            text = content.decode("utf-8", errors="replace")
            return ToolResult(
                success=True,
                output=text[:10000] + ("..." if len(text) > 10000 else ""),
                metadata={
                    "url": url,
                    "fallback": True,
                    "extended_timeout": extended_timeout,
                },
            )
    except Exception:
        return None


def create_default_fallback_handler() -> FallbackHandler:
    """Create a fallback handler that tries multiple strategies."""
    handlers = [file_read_fallback, web_fetch_fallback]

    def combined_handler(tool_name: str, arguments: Dict[str, Any], last_result: "ToolResult"):
        for handler in handlers:
            result = handler(tool_name, arguments, last_result)
            if result:
                return result
        return None

    return combined_handler
