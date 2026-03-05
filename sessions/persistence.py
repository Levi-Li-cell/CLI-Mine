"""Persistence layer for conversation sessions (M3-002)."""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import Session


class SessionPersistence:
    """
    Handles saving and loading sessions to/from disk.

    Sessions are stored as individual JSON files in a dedicated directory.
    This allows for:
    - Atomic updates (single file writes)
    - Easy backup/restore
    - Session export/import
    """

    DEFAULT_SESSIONS_DIR = ".agent/sessions"
    SESSION_FILE_SUFFIX = ".json"
    INDEX_FILE = "index.json"

    def __init__(self, sessions_dir: Optional[Path] = None):
        self.sessions_dir = Path(sessions_dir or self.DEFAULT_SESSIONS_DIR)
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Ensure the sessions directory exists."""
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        """Get the file path for a session."""
        return self.sessions_dir / f"{session_id}{self.SESSION_FILE_SUFFIX}"

    def _index_path(self) -> Path:
        """Get the path to the session index file."""
        return self.sessions_dir / self.INDEX_FILE

    def save(self, session: Session) -> bool:
        """
        Save a session to disk.

        Returns True on success, False on failure.
        """
        try:
            path = self._session_path(session.session_id)
            data = session.to_dict()

            # Write to temp file first, then rename for atomicity
            temp_path = path.with_suffix(".tmp")
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=True)

            # Atomic rename
            temp_path.replace(path)

            # Update index
            self._update_index(session)

            return True
        except Exception as e:
            return False

    def load(self, session_id: str) -> Optional[Session]:
        """
        Load a session from disk by ID.

        Returns None if session doesn't exist or is corrupted.
        """
        path = self._session_path(session_id)
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return Session.from_dict(data)
        except Exception:
            return None

    def delete(self, session_id: str) -> bool:
        """
        Delete a session from disk.

        Returns True if session was deleted, False if it didn't exist.
        """
        path = self._session_path(session_id)
        if not path.exists():
            return False

        try:
            path.unlink()
            self._remove_from_index(session_id)
            return True
        except Exception:
            return False

    def exists(self, session_id: str) -> bool:
        """Check if a session exists on disk."""
        return self._session_path(session_id).exists()

    def list_session_ids(self) -> List[str]:
        """
        List all session IDs in the storage directory.

        Returns list of session IDs (without .json suffix).
        """
        ids = []
        if not self.sessions_dir.exists():
            return ids

        for f in self.sessions_dir.iterdir():
            if f.is_file() and f.suffix == self.SESSION_FILE_SUFFIX:
                # Skip index file
                if f.stem == "index":
                    continue
                ids.append(f.stem)

        return sorted(ids)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """
        List all sessions with their summaries.

        Uses the index file for performance if available,
        otherwise loads each session file.
        """
        # Try to load from index first
        index_data = self._load_index()
        if index_data:
            return index_data

        # Fall back to loading each session
        summaries = []
        for session_id in self.list_session_ids():
            session = self.load(session_id)
            if session:
                summaries.append(session.to_summary())

        # Sort by updated_at descending (most recent first)
        summaries.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return summaries

    def _load_index(self) -> Optional[List[Dict[str, Any]]]:
        """Load the session index file."""
        path = self._index_path()
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            return None
        except Exception:
            return None

    def _update_index(self, session: Session) -> None:
        """Update the index with a session's summary."""
        summaries = self._load_index() or []

        # Remove existing entry for this session
        summaries = [s for s in summaries if s.get("session_id") != session.session_id]

        # Add updated summary
        summaries.append(session.to_summary())

        # Sort by updated_at descending
        summaries.sort(key=lambda s: s.get("updated_at", ""), reverse=True)

        # Save index
        path = self._index_path()
        temp_path = path.with_suffix(".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(summaries, f, indent=2, ensure_ascii=True)
            temp_path.replace(path)
        except Exception:
            pass  # Index update is best-effort

    def _remove_from_index(self, session_id: str) -> None:
        """Remove a session from the index."""
        summaries = self._load_index()
        if not summaries:
            return

        summaries = [s for s in summaries if s.get("session_id") != session_id]

        path = self._index_path()
        temp_path = path.with_suffix(".tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as f:
                json.dump(summaries, f, indent=2, ensure_ascii=True)
            temp_path.replace(path)
        except Exception:
            pass

    def rebuild_index(self) -> int:
        """
        Rebuild the session index from scratch.

        Returns the number of sessions indexed.
        """
        summaries = []
        for session_id in self.list_session_ids():
            session = self.load(session_id)
            if session:
                summaries.append(session.to_summary())

        summaries.sort(key=lambda s: s.get("updated_at", ""), reverse=True)

        path = self._index_path()
        temp_path = path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(summaries, f, indent=2, ensure_ascii=True)
        temp_path.replace(path)

        return len(summaries)

    def export_session(self, session_id: str, export_path: Path) -> bool:
        """
        Export a session to a specific path.

        Returns True on success.
        """
        session = self.load(session_id)
        if not session:
            return False

        try:
            with export_path.open("w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, indent=2, ensure_ascii=True)
            return True
        except Exception:
            return False

    def import_session(self, import_path: Path, new_id: bool = False) -> Optional[Session]:
        """
        Import a session from a file.

        Args:
            import_path: Path to the session JSON file
            new_id: If True, generate a new session ID

        Returns the imported session or None on failure.
        """
        try:
            with import_path.open("r", encoding="utf-8") as f:
                data = json.load(f)

            if new_id:
                import uuid
                data["session_id"] = str(uuid.uuid4())

            session = Session.from_dict(data)
            self.save(session)
            return session
        except Exception:
            return None

    def get_storage_stats(self) -> Dict[str, Any]:
        """Get statistics about session storage."""
        session_ids = self.list_session_ids()
        total_size = 0

        for sid in session_ids:
            path = self._session_path(sid)
            if path.exists():
                total_size += path.stat().st_size

        return {
            "sessions_dir": str(self.sessions_dir),
            "session_count": len(session_ids),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }
