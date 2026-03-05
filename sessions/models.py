"""Data models for conversation sessions (M3-002)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class MessageRole(str, Enum):
    """Role of a message in a conversation."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageStatus(str, Enum):
    """Status of a message."""
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETE = "complete"
    ERROR = "error"
    INTERRUPTED = "interrupted"


@dataclass
class ToolCall:
    """Represents a tool call within a message."""
    call_id: str
    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[str] = None
    error: Optional[str] = None
    status: str = "pending"  # pending, running, success, error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "result": self.result,
            "error": self.error,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCall":
        return cls(
            call_id=data["call_id"],
            tool_name=data["tool_name"],
            arguments=data.get("arguments", {}),
            result=data.get("result"),
            error=data.get("error"),
            status=data.get("status", "pending"),
        )


@dataclass
class Message:
    """A single message in a conversation."""
    message_id: str
    role: MessageRole
    content: str
    created_at: str
    status: MessageStatus = MessageStatus.COMPLETE
    tool_calls: List[ToolCall] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    parent_id: Optional[str] = None  # For branching conversations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "role": self.role.value,
            "content": self.content,
            "created_at": self.created_at,
            "status": self.status.value,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "metadata": self.metadata,
            "parent_id": self.parent_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        tool_calls = [ToolCall.from_dict(tc) for tc in data.get("tool_calls", [])]
        return cls(
            message_id=data["message_id"],
            role=MessageRole(data["role"]),
            content=data["content"],
            created_at=data["created_at"],
            status=MessageStatus(data.get("status", "complete")),
            tool_calls=tool_calls,
            metadata=data.get("metadata", {}),
            parent_id=data.get("parent_id"),
        )

    @classmethod
    def create(
        cls,
        role: MessageRole,
        content: str,
        parent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "Message":
        return cls(
            message_id=str(uuid.uuid4()),
            role=role,
            content=content,
            created_at=datetime.now().isoformat(timespec="microseconds"),
            status=MessageStatus.COMPLETE,
            metadata=metadata or {},
            parent_id=parent_id,
        )


@dataclass
class Session:
    """
    A conversation session containing messages.

    Sessions represent a complete conversation thread that can be:
    - Created and named
    - Persisted to disk
    - Restored after restart
    - Listed and switched between
    """
    session_id: str
    title: str
    created_at: str
    updated_at: str
    messages: List[Message] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "active"  # active, archived, deleted
    feature_id: Optional[str] = None  # Link to feature being worked on
    trace_id: Optional[str] = None  # Link to audit trace

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": [m.to_dict() for m in self.messages],
            "metadata": self.metadata,
            "status": self.status,
            "feature_id": self.feature_id,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        return cls(
            session_id=data["session_id"],
            title=data["title"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            messages=messages,
            metadata=data.get("metadata", {}),
            status=data.get("status", "active"),
            feature_id=data.get("feature_id"),
            trace_id=data.get("trace_id"),
        )

    @classmethod
    def create(
        cls,
        title: Optional[str] = None,
        feature_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "Session":
        now = datetime.now().isoformat(timespec="microseconds")
        return cls(
            session_id=str(uuid.uuid4()),
            title=title or f"Session {now[:10]}",
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
            feature_id=feature_id,
        )

    def add_message(self, message: Message) -> None:
        """Add a message to this session."""
        self.messages.append(message)
        self.updated_at = datetime.now().isoformat(timespec="microseconds")

    def get_message(self, message_id: str) -> Optional[Message]:
        """Get a message by ID."""
        for msg in self.messages:
            if msg.message_id == message_id:
                return msg
        return None

    def get_last_message(self) -> Optional[Message]:
        """Get the last message in this session."""
        return self.messages[-1] if self.messages else None

    def message_count(self) -> int:
        """Return the number of messages."""
        return len(self.messages)

    def to_summary(self) -> Dict[str, Any]:
        """Return a summary of this session (without full message content)."""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
            "status": self.status,
            "feature_id": self.feature_id,
            "preview": self.messages[-1].content[:100] if self.messages else "",
        }
