"""Web tool for fetching and summarizing web content."""
import json
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .base import BaseTool, ToolResult, ToolSchema

# Try to import HTTP library
try:
    import urllib.request
    import urllib.error
    HTTP_LIB = "urllib"
except ImportError:
    HTTP_LIB = None


class WebTool(BaseTool):
    """Tool for fetching and summarizing web content."""

    def __init__(
        self,
        default_timeout: int = 30,
        max_content_size: int = 1024 * 1024,  # 1MB
        user_agent: str = "ClaudeLike-Agent/1.0",
    ):
        self.default_timeout = default_timeout
        self.max_content_size = max_content_size
        self.user_agent = user_agent

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="web",
            description="Fetch content from URLs and optionally summarize. Supports HTTP/HTTPS. Returns text content.",
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["fetch", "head"],
                        "default": "fetch",
                        "description": "fetch: get content, head: get headers only",
                    },
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch (HTTP or HTTPS)",
                    },
                    "timeout": {
                        "type": "integer",
                        "default": 30,
                        "description": "Timeout in seconds (default: 30)",
                    },
                    "max_length": {
                        "type": "integer",
                        "default": 10000,
                        "description": "Max characters to return (default: 10000)",
                    },
                    "headers": {
                        "type": "object",
                        "description": "Additional request headers",
                    },
                },
            },
            required=["url"],
        )

    def _validate_url(self, url: str) -> Optional[str]:
        """Validate URL scheme. Returns error message or None."""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return f"Unsupported URL scheme: {parsed.scheme}. Only http and https are allowed."
            if not parsed.netloc:
                return "Invalid URL: missing host"
            return None
        except Exception as e:
            return f"Invalid URL: {e}"

    def execute(
        self,
        url: str,
        operation: str = "fetch",
        timeout: Optional[int] = None,
        max_length: int = 10000,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> ToolResult:
        # Validate URL
        url_error = self._validate_url(url)
        if url_error:
            return ToolResult(success=False, output="", error=url_error)

        actual_timeout = timeout if timeout is not None else self.default_timeout

        # Build request
        req_headers = {"User-Agent": self.user_agent}
        if headers:
            req_headers.update(headers)

        try:
            request = urllib.request.Request(url, headers=req_headers, method="HEAD" if operation == "head" else "GET")

            with urllib.request.urlopen(request, timeout=actual_timeout) as response:
                # Get headers
                response_headers = dict(response.headers)

                if operation == "head":
                    return ToolResult(
                        success=True,
                        output=json.dumps(response_headers, indent=2),
                        metadata={
                            "url": url,
                            "status": response.status,
                            "headers": response_headers,
                        },
                    )

                # Read content with size limit
                content = response.read(self.max_content_size + 1)
                if len(content) > self.max_content_size:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Content too large (>{self.max_content_size} bytes)",
                        metadata={"url": url, "content_length": len(content)},
                    )

                # Try to decode as text
                content_type = response_headers.get("Content-Type", "")
                encoding = "utf-8"
                if "charset=" in content_type:
                    encoding = content_type.split("charset=")[1].split(";")[0].strip()

                try:
                    text = content.decode(encoding)
                except (UnicodeDecodeError, LookupError):
                    # Fall back to utf-8 with error handling
                    text = content.decode("utf-8", errors="replace")

                # Truncate if needed
                truncated = len(text) > max_length
                if truncated:
                    text = text[:max_length] + "\n... [truncated]"

                return ToolResult(
                    success=True,
                    output=text,
                    metadata={
                        "url": url,
                        "status": response.status,
                        "content_type": content_type,
                        "content_length": len(content),
                        "truncated": truncated,
                    },
                )

        except urllib.error.HTTPError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {e.code}: {e.reason}",
                metadata={"url": url, "status": e.code},
            )
        except urllib.error.URLError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"URL error: {e.reason}",
                metadata={"url": url},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Request failed: {e}",
                metadata={"url": url},
            )
