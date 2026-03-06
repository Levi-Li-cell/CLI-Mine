"""
Session management for conversation persistence and restore (M3-002).

This module provides:
- Conversation list and session switching
- Message persistence
- Session restore after restart

Usage:
    from sessions import SessionManager, MessageRole

    # Create a session manager
    manager = SessionManager()

    # Create a new conversation
    session = manager.create_session(title="My Conversation")

    # Add messages
    manager.add_user_message("Hello, how are you?")
    manager.add_assistant_message("I'm doing well, thank you!")

    # List all conversations
    sessions = manager.list_sessions()

    # Switch to a different session
    manager.switch_session(sessions[0]["session_id"])

    # Restore last session after restart
    manager.restore_last_session()
"""

from .manager import SessionManager
from .models import (
    Message,
    MessageRole,
    MessageStatus,
    Session,
    ToolCall,
)
from .persistence import SessionPersistence
from .streaming import SessionStreamer, StreamState

__all__ = [
    # Manager
    "SessionManager",
    # Models
    "Session",
    "Message",
    "MessageRole",
    "MessageStatus",
    "ToolCall",
    # Persistence
    "SessionPersistence",
    # Streaming
    "SessionStreamer",
    "StreamState",
]
