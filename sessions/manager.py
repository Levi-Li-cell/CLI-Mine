"""Session manager for conversation management (M3-002)."""

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .models import Message, MessageRole, MessageStatus, Session
from .persistence import SessionPersistence


class SessionManager:
    """
    High-level API for managing conversation sessions.

    Provides:
    - Create, switch, and list conversations
    - Add and retrieve messages
    - Persist and restore sessions
    - Search and filter sessions
    """

    def __init__(
        self,
        sessions_dir: Optional[Path] = None,
        auto_save: bool = True,
    ):
        self.persistence = SessionPersistence(sessions_dir)
        self.auto_save = auto_save
        self._current_session: Optional[Session] = None
        self._on_session_change: Optional[Callable[[Session], None]] = None
        self._on_message_add: Optional[Callable[[Session, Message], None]] = None

    # --- Session CRUD ---

    def create_session(
        self,
        title: Optional[str] = None,
        feature_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        switch_to: bool = True,
    ) -> Session:
        """
        Create a new conversation session.

        Args:
            title: Optional title for the session
            feature_id: Optional feature ID this session is working on
            metadata: Optional metadata dict
            switch_to: If True, make this the current session

        Returns the newly created session.
        """
        session = Session.create(
            title=title,
            feature_id=feature_id,
            metadata=metadata,
        )

        if self.auto_save:
            self.persistence.save(session)

        if switch_to:
            self._current_session = session
            self._notify_session_change()

        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID (loads from disk if needed)."""
        return self.persistence.load(session_id)

    def get_current_session(self) -> Optional[Session]:
        """Get the current active session."""
        return self._current_session

    def switch_session(self, session_id: str) -> Optional[Session]:
        """
        Switch to a different session.

        Loads the session from disk and makes it current.
        Returns the session or None if not found.
        """
        session = self.persistence.load(session_id)
        if session:
            self._current_session = session
            self._notify_session_change()
        return session

    def save_session(self, session: Optional[Session] = None) -> bool:
        """
        Save a session to disk.

        Args:
            session: Session to save (defaults to current session)

        Returns True on success.
        """
        target = session or self._current_session
        if not target:
            return False
        target.updated_at = datetime.now().isoformat(timespec="microseconds")
        return self.persistence.save(target)

    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        If the deleted session is the current session, clears current session.
        Returns True if session was deleted.
        """
        result = self.persistence.delete(session_id)
        if result and self._current_session and self._current_session.session_id == session_id:
            self._current_session = None
            self._notify_session_change()
        return result

    def archive_session(self, session_id: str) -> bool:
        """Archive a session (soft delete)."""
        session = self.persistence.load(session_id)
        if not session:
            return False
        session.status = "archived"
        return self.persistence.save(session)

    def restore_session(self, session_id: str) -> bool:
        """Restore an archived session."""
        session = self.persistence.load(session_id)
        if not session:
            return False
        session.status = "active"
        return self.persistence.save(session)

    # --- Session Listing ---

    def list_sessions(
        self,
        status: Optional[str] = None,
        feature_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        List sessions with optional filtering.

        Args:
            status: Filter by status (active, archived, etc.)
            feature_id: Filter by feature ID
            limit: Maximum number of results

        Returns list of session summaries.
        """
        summaries = self.persistence.list_sessions()

        if status:
            summaries = [s for s in summaries if s.get("status") == status]
        if feature_id:
            summaries = [s for s in summaries if s.get("feature_id") == feature_id]

        return summaries[:limit]

    def get_recent_sessions(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get the most recently updated sessions."""
        return self.list_sessions(limit=count)

    def search_sessions(self, query: str) -> List[Dict[str, Any]]:
        """
        Search sessions by title or message content.

        Args:
            query: Search string

        Returns matching session summaries.
        """
        query_lower = query.lower()
        results = []

        for session_id in self.persistence.list_session_ids():
            session = self.persistence.load(session_id)
            if not session:
                continue

            # Check title
            if query_lower in session.title.lower():
                results.append(session.to_summary())
                continue

            # Check message content
            for msg in session.messages:
                if query_lower in msg.content.lower():
                    results.append(session.to_summary())
                    break

        # Sort by updated_at
        results.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return results

    # --- Message Management ---

    def add_message(
        self,
        role: MessageRole,
        content: str,
        session: Optional[Session] = None,
        parent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Message]:
        """
        Add a message to a session.

        Args:
            role: Message role (user, assistant, system, tool)
            content: Message content
            session: Target session (defaults to current)
            parent_id: Optional parent message ID for threading
            metadata: Optional message metadata

        Returns the created message or None if no session.
        """
        target = session or self._current_session
        if not target:
            return None

        message = Message.create(
            role=role,
            content=content,
            parent_id=parent_id,
            metadata=metadata,
        )

        target.add_message(message)

        if self.auto_save:
            self.persistence.save(target)

        self._notify_message_add(target, message)

        return message

    def add_user_message(
        self,
        content: str,
        session: Optional[Session] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Message]:
        """Add a user message to a session."""
        return self.add_message(
            role=MessageRole.USER,
            content=content,
            session=session,
            metadata=metadata,
        )

    def add_assistant_message(
        self,
        content: str,
        session: Optional[Session] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Message]:
        """Add an assistant message to a session."""
        return self.add_message(
            role=MessageRole.ASSISTANT,
            content=content,
            session=session,
            metadata=metadata,
        )

    def get_messages(
        self,
        session: Optional[Session] = None,
        limit: Optional[int] = None,
    ) -> List[Message]:
        """
        Get messages from a session.

        Args:
            session: Target session (defaults to current)
            limit: Optional limit on number of messages

        Returns list of messages.
        """
        target = session or self._current_session
        if not target:
            return []

        messages = target.messages
        if limit:
            messages = messages[-limit:]

        return messages

    def get_message(self, message_id: str, session: Optional[Session] = None) -> Optional[Message]:
        """Get a single message by ID from a session."""
        target = session or self._current_session
        if not target:
            return None
        return target.get_message(message_id)

    def append_to_message(
        self,
        message_id: str,
        content_chunk: str,
        session: Optional[Session] = None,
    ) -> bool:
        """Append streaming content to an existing message."""
        target = session or self._current_session
        if not target:
            return False

        message = target.get_message(message_id)
        if not message:
            return False

        message.content += content_chunk
        target.updated_at = datetime.now().isoformat(timespec="microseconds")
        if self.auto_save:
            self.persistence.save(target)
        return True

    def update_message_status(
        self,
        message_id: str,
        status: MessageStatus,
        session: Optional[Session] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update the status of a message and optionally merge metadata."""
        target = session or self._current_session
        if not target:
            return False

        message = target.get_message(message_id)
        if not message:
            return False

        message.status = status
        if metadata_update:
            message.metadata.update(metadata_update)
        target.updated_at = datetime.now().isoformat(timespec="microseconds")
        if self.auto_save:
            self.persistence.save(target)
        return True

    def mark_stream_interrupted(self, session: Optional[Session] = None) -> int:
        """Mark all streaming assistant messages in a session as interrupted."""
        target = session or self._current_session
        if not target:
            return 0

        changed = 0
        for message in target.messages:
            if message.role == MessageRole.ASSISTANT and message.status == MessageStatus.STREAMING:
                message.status = MessageStatus.INTERRUPTED
                changed += 1

        if changed > 0:
            target.updated_at = datetime.now().isoformat(timespec="microseconds")
            if self.auto_save:
                self.persistence.save(target)
        return changed

    def get_message_history(
        self,
        session: Optional[Session] = None,
        include_system: bool = True,
    ) -> List[Dict[str, str]]:
        """
        Get message history in API-ready format.

        Returns list of dicts with 'role' and 'content' keys,
        suitable for passing to an LLM API.
        """
        messages = self.get_messages(session)

        result = []
        for msg in messages:
            if not include_system and msg.role == MessageRole.SYSTEM:
                continue
            result.append({
                "role": msg.role.value,
                "content": msg.content,
            })

        return result

    def clear_messages(self, session: Optional[Session] = None) -> bool:
        """Clear all messages from a session."""
        target = session or self._current_session
        if not target:
            return False

        target.messages = []
        target.updated_at = datetime.now().isoformat(timespec="microseconds")

        if self.auto_save:
            self.persistence.save(target)

        return True

    # --- Session Restoration ---

    def restore_last_session(self) -> Optional[Session]:
        """
        Restore the most recently active session.

        Useful for resuming after application restart.
        Returns the restored session or None.
        """
        recent = self.get_recent_sessions(1)
        if not recent:
            return None

        session_id = recent[0].get("session_id")
        if session_id:
            return self.switch_session(session_id)
        return None

    def restore_session_for_feature(self, feature_id: str) -> Optional[Session]:
        """
        Restore the most recent session for a specific feature.

        Returns the session or None if no matching session exists.
        """
        sessions = self.list_sessions(feature_id=feature_id, limit=1)
        if not sessions:
            return None

        session_id = sessions[0].get("session_id")
        if session_id:
            return self.switch_session(session_id)
        return None

    def get_or_create_session_for_feature(
        self,
        feature_id: str,
        title: Optional[str] = None,
    ) -> Session:
        """
        Get existing session for a feature or create a new one.

        This is the primary method for the harness to use when
        starting work on a feature.
        """
        # Try to find existing session
        session = self.restore_session_for_feature(feature_id)
        if session:
            return session

        # Create new session
        return self.create_session(
            title=title or f"Feature: {feature_id}",
            feature_id=feature_id,
            switch_to=True,
        )

    # --- Callbacks ---

    def set_on_session_change(self, callback: Callable[[Session], None]) -> None:
        """Set callback for session changes."""
        self._on_session_change = callback

    def set_on_message_add(self, callback: Callable[[Session, Message], None]) -> None:
        """Set callback for message additions."""
        self._on_message_add = callback

    def _notify_session_change(self) -> None:
        if self._on_session_change and self._current_session:
            self._on_session_change(self._current_session)

    def _notify_message_add(self, session: Session, message: Message) -> None:
        if self._on_message_add:
            self._on_message_add(session, message)

    # --- Maintenance ---

    def rebuild_index(self) -> int:
        """Rebuild the session index. Returns count of sessions."""
        return self.persistence.rebuild_index()

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        return self.persistence.get_storage_stats()

    def export_session(self, session_id: str, export_path: Path) -> bool:
        """Export a session to a file."""
        return self.persistence.export_session(session_id, export_path)

    def import_session(
        self,
        import_path: Path,
        new_id: bool = False,
        switch_to: bool = False,
    ) -> Optional[Session]:
        """Import a session from a file."""
        session = self.persistence.import_session(import_path, new_id)
        if session and switch_to:
            self._current_session = session
            self._notify_session_change()
        return session
