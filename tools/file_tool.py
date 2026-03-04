"""File tool for reading and writing local files."""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .base import BaseTool, ToolResult, ToolSchema


class FileTool(BaseTool):
    """Tool for file system operations: read, write, list, delete."""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="file",
            description="Read, write, list, or delete files and directories. Use for file system operations.",
            parameters={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["read", "write", "list", "delete", "exists"],
                        "description": "The file operation to perform",
                    },
                    "path": {
                        "type": "string",
                        "description": "The file or directory path (absolute or relative to working directory)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write (only for write operation)",
                    },
                    "encoding": {
                        "type": "string",
                        "default": "utf-8",
                        "description": "File encoding (default: utf-8)",
                    },
                    "recursive": {
                        "type": "boolean",
                        "default": False,
                        "description": "For list/delete, operate recursively",
                    },
                },
            },
            required=["operation", "path"],
        )

    def execute(
        self,
        operation: str,
        path: str,
        content: Optional[str] = None,
        encoding: str = "utf-8",
        recursive: bool = False,
        **kwargs,
    ) -> ToolResult:
        try:
            p = Path(path).expanduser().resolve()

            if operation == "read":
                return self._read(p, encoding)
            elif operation == "write":
                if content is None:
                    return ToolResult(
                        success=False, output="", error="content required for write operation"
                    )
                return self._write(p, content, encoding)
            elif operation == "list":
                return self._list(p, recursive)
            elif operation == "delete":
                return self._delete(p, recursive)
            elif operation == "exists":
                return self._exists(p)
            else:
                return ToolResult(
                    success=False, output="", error=f"Unknown operation: {operation}"
                )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))

    def _read(self, path: Path, encoding: str) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output="", error=f"File not found: {path}")
        if not path.is_file():
            return ToolResult(success=False, output="", error=f"Not a file: {path}")
        try:
            content = path.read_text(encoding=encoding)
            return ToolResult(
                success=True,
                output=content,
                metadata={"path": str(path), "size": len(content)},
            )
        except UnicodeDecodeError:
            return ToolResult(
                success=False, output="", error=f"Cannot decode file as {encoding}: {path}"
            )

    def _write(self, path: Path, content: str, encoding: str) -> ToolResult:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return ToolResult(
            success=True,
            output=f"Wrote {len(content)} characters to {path}",
            metadata={"path": str(path), "size": len(content)},
        )

    def _list(self, path: Path, recursive: bool) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {path}")
        if not path.is_dir():
            return ToolResult(success=False, output="", error=f"Not a directory: {path}")

        if recursive:
            items = list(path.rglob("*"))
        else:
            items = list(path.iterdir())

        lines = []
        for item in sorted(items):
            prefix = "[D] " if item.is_dir() else "[F] "
            rel = item.relative_to(path) if recursive else item.name
            lines.append(f"{prefix}{rel}")

        output = "\n".join(lines) if lines else "(empty directory)"
        return ToolResult(
            success=True,
            output=output,
            metadata={"path": str(path), "count": len(lines)},
        )

    def _delete(self, path: Path, recursive: bool) -> ToolResult:
        if not path.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {path}")

        if path.is_file():
            path.unlink()
            return ToolResult(success=True, output=f"Deleted file: {path}")
        elif path.is_dir():
            if not recursive and any(path.iterdir()):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Directory not empty: {path}. Use recursive=true to delete.",
                )
            import shutil

            shutil.rmtree(path)
            return ToolResult(success=True, output=f"Deleted directory: {path}")
        else:
            return ToolResult(success=False, output="", error=f"Unknown path type: {path}")

    def _exists(self, path: Path) -> ToolResult:
        exists = path.exists()
        is_file = path.is_file() if exists else False
        is_dir = path.is_dir() if exists else False
        return ToolResult(
            success=True,
            output=str(exists),
            metadata={"exists": exists, "is_file": is_file, "is_dir": is_dir},
        )
