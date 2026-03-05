"""
Verification script for M3-002: Conversation list and session restore.

Tests:
1. Create and switch conversations
2. Persist messages
3. Restore after restart
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sessions import (
    Message,
    MessageRole,
    MessageStatus,
    Session,
    SessionManager,
    SessionPersistence,
    ToolCall,
)


def test_pass(name: str) -> None:
    print(f"   [PASS] {name}")


def test_fail(name: str, reason: str = "") -> None:
    print(f"   [FAIL] {name}")
    if reason:
        print(f"          Reason: {reason}")
    sys.exit(1)


def main():
    print("=== M3-002 VERIFICATION: Conversation List and Session Restore ===\n")

    # Use temp directory for isolation
    temp_dir = Path(tempfile.mkdtemp(prefix="m3_002_test_"))

    try:
        # ========================================
        # 1. Testing: Imports work correctly
        # ========================================
        print("1. Testing: Imports work correctly...")
        try:
            assert SessionManager is not None
            assert Session is not None
            assert Message is not None
            assert MessageRole is not None
            assert SessionPersistence is not None
            test_pass("All classes imported successfully")
        except Exception as e:
            test_fail("Import failed", str(e))

        # ========================================
        # 2. Testing: Create conversations
        # ========================================
        print("\n2. Testing: Create conversations...")
        manager = SessionManager(sessions_dir=temp_dir, auto_save=True)

        try:
            # Create first session
            session1 = manager.create_session(
                title="Test Conversation 1",
                feature_id="TEST-001",
                switch_to=True,
            )
            assert session1.session_id is not None
            assert session1.title == "Test Conversation 1"
            assert session1.feature_id == "TEST-001"
            assert manager.get_current_session() == session1
            test_pass("Create first conversation")
        except Exception as e:
            test_fail("Create first conversation", str(e))

        try:
            # Create second session
            session2 = manager.create_session(
                title="Test Conversation 2",
                feature_id="TEST-002",
                switch_to=False,  # Don't switch automatically
            )
            assert session2.session_id is not None
            assert session2.title == "Test Conversation 2"
            # Current session should still be session1
            assert manager.get_current_session().session_id == session1.session_id
            test_pass("Create second conversation without switching")
        except Exception as e:
            test_fail("Create second conversation", str(e))

        # ========================================
        # 3. Testing: Switch conversations
        # ========================================
        print("\n3. Testing: Switch conversations...")
        try:
            # Switch to session2
            switched = manager.switch_session(session2.session_id)
            assert switched is not None
            assert switched.session_id == session2.session_id
            assert manager.get_current_session().session_id == session2.session_id
            test_pass("Switch to second conversation")
        except Exception as e:
            test_fail("Switch conversation", str(e))

        try:
            # Switch back to session1
            switched = manager.switch_session(session1.session_id)
            assert switched.session_id == session1.session_id
            test_pass("Switch back to first conversation")
        except Exception as e:
            test_fail("Switch back", str(e))

        # ========================================
        # 4. Testing: Add and persist messages
        # ========================================
        print("\n4. Testing: Add and persist messages...")
        try:
            # Add messages to current session (session1)
            msg1 = manager.add_user_message("Hello, this is a test message")
            assert msg1 is not None
            assert msg1.role == MessageRole.USER
            assert "test message" in msg1.content
            test_pass("Add user message")
        except Exception as e:
            test_fail("Add user message", str(e))

        try:
            msg2 = manager.add_assistant_message("I received your message. How can I help?")
            assert msg2 is not None
            assert msg2.role == MessageRole.ASSISTANT
            test_pass("Add assistant message")
        except Exception as e:
            test_fail("Add assistant message", str(e))

        try:
            # Check messages are in session
            messages = manager.get_messages()
            assert len(messages) == 2
            assert messages[0].role == MessageRole.USER
            assert messages[1].role == MessageRole.ASSISTANT
            test_pass("Messages stored in session")
        except Exception as e:
            test_fail("Messages retrieval", str(e))

        # ========================================
        # 5. Testing: Message persistence to disk
        # ========================================
        print("\n5. Testing: Message persistence to disk...")
        try:
            # Check file exists
            persistence = SessionPersistence(temp_dir)
            assert persistence.exists(session1.session_id)
            test_pass("Session file created on disk")
        except Exception as e:
            test_fail("Session file existence", str(e))

        try:
            # Load from disk and verify messages
            loaded_session = persistence.load(session1.session_id)
            assert loaded_session is not None
            assert loaded_session.session_id == session1.session_id
            assert len(loaded_session.messages) == 2
            assert loaded_session.messages[0].content == msg1.content
            assert loaded_session.messages[1].content == msg2.content
            test_pass("Messages persisted correctly to disk")
        except Exception as e:
            test_fail("Message persistence verification", str(e))

        # ========================================
        # 6. Testing: Session list functionality
        # ========================================
        print("\n6. Testing: Session list functionality...")
        try:
            sessions = manager.list_sessions()
            assert len(sessions) == 2
            test_pass("List all sessions")
        except Exception as e:
            test_fail("List sessions", str(e))

        try:
            # Filter by feature_id
            filtered = manager.list_sessions(feature_id="TEST-001")
            assert len(filtered) == 1
            assert filtered[0]["feature_id"] == "TEST-001"
            test_pass("Filter sessions by feature_id")
        except Exception as e:
            test_fail("Filter by feature_id", str(e))

        # ========================================
        # 7. Testing: Restore after restart (simulate with new manager)
        # ========================================
        print("\n7. Testing: Restore after restart...")
        try:
            # Switch to session1 to make it most recently updated
            manager.switch_session(session1.session_id)
            manager.save_session()  # Ensure it's saved

            # Create new manager instance (simulates restart)
            new_manager = SessionManager(sessions_dir=temp_dir)

            # Restore last session
            restored = new_manager.restore_last_session()
            assert restored is not None
            # Should restore the most recently updated session (session1)
            assert restored.session_id == session1.session_id
            test_pass("Restore last session after restart")
        except Exception as e:
            test_fail("Restore last session", str(e))

        try:
            # Verify messages are intact
            messages = new_manager.get_messages()
            assert len(messages) == 2
            assert messages[0].content == msg1.content
            assert messages[1].content == msg2.content
            test_pass("Messages preserved after restore")
        except Exception as e:
            test_fail("Messages after restore", str(e))

        # ========================================
        # 8. Testing: Restore session by feature ID
        # ========================================
        print("\n8. Testing: Restore session by feature ID...")
        try:
            # Create new manager
            feature_manager = SessionManager(sessions_dir=temp_dir)

            # Restore by feature ID
            restored = feature_manager.restore_session_for_feature("TEST-001")
            assert restored is not None
            assert restored.feature_id == "TEST-001"
            assert restored.title == "Test Conversation 1"
            test_pass("Restore session by feature_id")
        except Exception as e:
            test_fail("Restore by feature_id", str(e))

        # ========================================
        # 9. Testing: Message history for API
        # ========================================
        print("\n9. Testing: Message history for API...")
        try:
            history = manager.get_message_history()
            assert len(history) == 2
            assert history[0]["role"] == "user"
            assert history[1]["role"] == "assistant"
            assert "role" in history[0]
            assert "content" in history[0]
            test_pass("Get message history in API format")
        except Exception as e:
            test_fail("Message history format", str(e))

        # ========================================
        # 10. Testing: Search sessions
        # ========================================
        print("\n10. Testing: Search sessions...")
        try:
            # Add a distinctive message
            manager.switch_session(session2.session_id)
            manager.add_user_message("UNIQUE_SEARCH_TERM_12345")

            # Search for it
            results = manager.search_sessions("UNIQUE_SEARCH_TERM_12345")
            assert len(results) == 1
            assert results[0]["session_id"] == session2.session_id
            test_pass("Search sessions by message content")
        except Exception as e:
            test_fail("Search sessions", str(e))

        # ========================================
        # 11. Testing: Tool calls in messages
        # ========================================
        print("\n11. Testing: Tool calls in messages...")
        try:
            tool_msg = Message.create(
                role=MessageRole.ASSISTANT,
                content="I'll read that file for you.",
            )
            tool_call = ToolCall(
                call_id="call_123",
                tool_name="file_read",
                arguments={"path": "/test/file.txt"},
                result="File contents here",
                status="success",
            )
            tool_msg.tool_calls.append(tool_call)

            # Serialize and deserialize
            msg_dict = tool_msg.to_dict()
            restored_msg = Message.from_dict(msg_dict)

            assert len(restored_msg.tool_calls) == 1
            assert restored_msg.tool_calls[0].tool_name == "file_read"
            assert restored_msg.tool_calls[0].result == "File contents here"
            test_pass("Tool calls serialize/deserialize correctly")
        except Exception as e:
            test_fail("Tool calls", str(e))

        # ========================================
        # 12. Testing: Session export/import
        # ========================================
        print("\n12. Testing: Session export/import...")
        try:
            export_path = temp_dir / "exported_session.json"
            success = manager.export_session(session1.session_id, export_path)
            assert success
            assert export_path.exists()
            test_pass("Export session to file")
        except Exception as e:
            test_fail("Export session", str(e))

        try:
            # Import with new ID
            new_manager2 = SessionManager(sessions_dir=temp_dir / "imported")
            imported = new_manager2.import_session(export_path, new_id=True, switch_to=True)
            assert imported is not None
            assert imported.session_id != session1.session_id  # New ID
            assert len(imported.messages) == 2  # Messages preserved
            test_pass("Import session with new ID")
        except Exception as e:
            test_fail("Import session", str(e))

        # ========================================
        # Summary
        # ========================================
        print("\n" + "=" * 50)
        print("=== M3-002 VERIFICATION PASSED (12/12) ===")
        print("=" * 50)

    finally:
        # Cleanup
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
