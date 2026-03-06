"""Streaming helpers for conversation sessions (M3-001)."""

from dataclasses import dataclass
from typing import Iterator, List, Optional

from .manager import SessionManager
from .models import Message, MessageRole, MessageStatus, Session


@dataclass
class StreamState:
    """Runtime state for a single assistant streaming response."""

    message_id: str
    stream_id: str
    status: MessageStatus
    content: str


class SessionStreamer:
    """Manage assistant token streaming with interrupt and retry support."""

    def __init__(self, manager: SessionManager):
        self.manager = manager

    def start_assistant_stream(
        self,
        session: Optional[Session] = None,
        initial_content: str = "",
        stream_id: str = "",
    ) -> Optional[Message]:
        target = session or self.manager.get_current_session()
        if not target:
            return None

        metadata = {}
        if stream_id:
            metadata["stream_id"] = stream_id

        message = self.manager.add_assistant_message(
            content=initial_content,
            session=target,
            metadata=metadata,
        )
        if not message:
            return None

        self.manager.update_message_status(
            message_id=message.message_id,
            status=MessageStatus.STREAMING,
            session=target,
        )
        return self.manager.get_message(message.message_id, session=target)

    def append_token(
        self,
        message_id: str,
        token: str,
        session: Optional[Session] = None,
    ) -> bool:
        return self.manager.append_to_message(message_id, token, session=session)

    def append_tokens(
        self,
        message_id: str,
        tokens: List[str],
        session: Optional[Session] = None,
    ) -> bool:
        ok = True
        for token in tokens:
            ok = self.append_token(message_id, token, session=session) and ok
        return ok

    def finalize_stream(self, message_id: str, session: Optional[Session] = None) -> bool:
        return self.manager.update_message_status(
            message_id=message_id,
            status=MessageStatus.COMPLETE,
            session=session,
        )

    def interrupt_stream(
        self,
        message_id: str,
        reason: str = "interrupted",
        session: Optional[Session] = None,
    ) -> bool:
        return self.manager.update_message_status(
            message_id=message_id,
            status=MessageStatus.INTERRUPTED,
            session=session,
            metadata_update={"interrupt_reason": reason},
        )

    def retry_interrupted_stream(
        self,
        interrupted_message_id: str,
        session: Optional[Session] = None,
    ) -> Optional[Message]:
        target = session or self.manager.get_current_session()
        if not target:
            return None

        interrupted = self.manager.get_message(interrupted_message_id, session=target)
        if not interrupted or interrupted.status != MessageStatus.INTERRUPTED:
            return None

        retry_message = self.start_assistant_stream(
            session=target,
            initial_content="",
            stream_id=str(interrupted.metadata.get("stream_id", "")),
        )
        if not retry_message:
            return None

        self.manager.update_message_status(
            message_id=retry_message.message_id,
            status=MessageStatus.STREAMING,
            session=target,
            metadata_update={"retry_of": interrupted_message_id},
        )
        return self.manager.get_message(retry_message.message_id, session=target)

    def stream_chunks(
        self,
        chunks: List[str],
        session: Optional[Session] = None,
        stream_id: str = "",
    ) -> Iterator[StreamState]:
        message = self.start_assistant_stream(session=session, stream_id=stream_id)
        if not message:
            return

        target = session or self.manager.get_current_session()
        if not target:
            return

        for chunk in chunks:
            self.append_token(message.message_id, chunk, session=target)
            current = self.manager.get_message(message.message_id, session=target)
            if not current:
                return
            yield StreamState(
                message_id=current.message_id,
                stream_id=str(current.metadata.get("stream_id", "")),
                status=current.status,
                content=current.content,
            )

        self.finalize_stream(message.message_id, session=target)
        current = self.manager.get_message(message.message_id, session=target)
        if not current:
            return
        yield StreamState(
            message_id=current.message_id,
            stream_id=str(current.metadata.get("stream_id", "")),
            status=current.status,
            content=current.content,
        )
