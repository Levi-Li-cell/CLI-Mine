"""Verification script for M3-001: chat streaming, interruption, retry."""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sessions import MessageStatus, SessionManager, SessionStreamer


def ok(name: str) -> None:
    print(f"   [PASS] {name}")


def fail(name: str, reason: str = "") -> None:
    print(f"   [FAIL] {name}")
    if reason:
        print(f"          Reason: {reason}")
    raise SystemExit(1)


def main() -> None:
    print("=== M3-001 VERIFICATION: Streaming, Interruption, Retry ===\n")
    tmp = Path(tempfile.mkdtemp(prefix="m3_001_test_"))

    try:
        print("1. Testing: create session and streamer...")
        manager = SessionManager(sessions_dir=tmp, auto_save=True)
        session = manager.create_session(title="M3-001 Stream Test", switch_to=True)
        streamer = SessionStreamer(manager)
        if not session:
            fail("Create session", "session is None")
        ok("Session and streamer created")

        print("\n2. Testing: assistant stream starts in STREAMING status...")
        msg = streamer.start_assistant_stream(session=session, stream_id="stream-1")
        if not msg:
            fail("Start stream", "message not created")
        if msg.status != MessageStatus.STREAMING:
            fail("Start stream", f"expected STREAMING got {msg.status}")
        ok("Stream starts with STREAMING status")

        print("\n3. Testing: tokens append in real time...")
        chunks = ["Hello", " ", "streaming", " ", "world"]
        for chunk in chunks:
            if not streamer.append_token(msg.message_id, chunk, session=session):
                fail("Append token", f"failed on chunk={chunk!r}")
        updated = manager.get_message(msg.message_id, session=session)
        if not updated or updated.content != "Hello streaming world":
            fail("Token append", f"unexpected content={updated.content if updated else None}")
        ok("Tokens appended correctly")

        print("\n4. Testing: finalize stream transitions to COMPLETE...")
        if not streamer.finalize_stream(msg.message_id, session=session):
            fail("Finalize stream")
        completed = manager.get_message(msg.message_id, session=session)
        if not completed or completed.status != MessageStatus.COMPLETE:
            fail("Finalize stream", "message not COMPLETE")
        ok("Finalize sets COMPLETE status")

        print("\n5. Testing: interruption support...")
        interrupted = streamer.start_assistant_stream(session=session, stream_id="stream-2")
        if not interrupted:
            fail("Create second stream")
        streamer.append_tokens(interrupted.message_id, ["partial", " response"], session=session)
        if not streamer.interrupt_stream(interrupted.message_id, reason="user_cancel", session=session):
            fail("Interrupt stream")
        after_interrupt = manager.get_message(interrupted.message_id, session=session)
        if not after_interrupt or after_interrupt.status != MessageStatus.INTERRUPTED:
            fail("Interrupt stream", "status not INTERRUPTED")
        if after_interrupt.metadata.get("interrupt_reason") != "user_cancel":
            fail("Interrupt stream", "reason metadata missing")
        ok("Interruption updates status and metadata")

        print("\n6. Testing: retry interrupted stream...")
        retry_msg = streamer.retry_interrupted_stream(interrupted.message_id, session=session)
        if not retry_msg:
            fail("Retry stream", "retry message not created")
        if retry_msg.status != MessageStatus.STREAMING:
            fail("Retry stream", f"expected STREAMING got {retry_msg.status}")
        if retry_msg.metadata.get("retry_of") != interrupted.message_id:
            fail("Retry stream", "retry_of metadata missing")
        streamer.append_tokens(retry_msg.message_id, ["new", " answer"], session=session)
        streamer.finalize_stream(retry_msg.message_id, session=session)
        retry_done = manager.get_message(retry_msg.message_id, session=session)
        if not retry_done or retry_done.content != "new answer":
            fail("Retry stream content", "unexpected retry content")
        ok("Retry flow creates fresh assistant message")

        print("\n7. Testing: stream_chunks generator path...")
        states = list(streamer.stream_chunks(["A", "B", "C"], session=session, stream_id="stream-3"))
        if len(states) < 2:
            fail("stream_chunks", "expected multiple states")
        if states[-1].status != MessageStatus.COMPLETE:
            fail("stream_chunks", f"last status={states[-1].status}")
        if states[-1].content != "ABC":
            fail("stream_chunks", f"final content={states[-1].content!r}")
        ok("stream_chunks yields incremental and final COMPLETE state")

        print("\n=== M3-001 VERIFICATION PASSED ===")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
