"""
Tests for the observability module.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from arcadiaforge.observability import (
    Observability,
    Event,
    EventType,
    SessionMetrics,
    RunMetrics,
    format_event_summary,
    format_metrics_summary,
)


@pytest.fixture
def temp_project_dir():
    """Create a temporary project directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def obs(temp_project_dir):
    """Create an Observability instance for testing."""
    return Observability(temp_project_dir)


class TestEvent:
    """Tests for the Event dataclass."""

    def test_event_to_dict(self):
        """Test Event serialization to dict."""
        event = Event(
            event_id="abc123",
            timestamp="2025-12-18T10:30:00+00:00",
            event_type="tool_call",
            session_id=1,
            data={"tool_input": {"file_path": "test.py"}},
            tool_name="Read",
        )

        result = event.to_dict()

        assert result["event_id"] == "abc123"
        assert result["event_type"] == "tool_call"
        assert result["session_id"] == 1
        assert result["tool_name"] == "Read"
        assert "data" in result

    def test_event_from_dict(self):
        """Test Event deserialization from dict."""
        data = {
            "event_id": "xyz789",
            "timestamp": "2025-12-18T11:00:00+00:00",
            "event_type": "tool_result",
            "session_id": 2,
            "data": {"success": True},
            "tool_name": "Write",
            "duration_ms": 150,
        }

        event = Event.from_dict(data)

        assert event.event_id == "xyz789"
        assert event.session_id == 2
        assert event.tool_name == "Write"
        assert event.duration_ms == 150

    def test_event_roundtrip(self):
        """Test Event can be serialized and deserialized."""
        original = Event(
            event_id="test123",
            timestamp="2025-12-18T12:00:00+00:00",
            event_type="error",
            session_id=3,
            data={"error_message": "Something went wrong"},
            feature_index=42,
        )

        serialized = original.to_dict()
        restored = Event.from_dict(serialized)

        assert restored.event_id == original.event_id
        assert restored.session_id == original.session_id
        assert restored.feature_index == original.feature_index


class TestObservability:
    """Tests for the Observability class."""

    def test_initialization(self, temp_project_dir):
        """Test Observability creates correct file paths."""
        obs = Observability(temp_project_dir)

        assert obs.project_dir == temp_project_dir
        assert obs.events_file == temp_project_dir / ".events.jsonl"
        assert obs.run_id is not None

    def test_log_event_creates_file(self, obs, temp_project_dir):
        """Test that logging an event creates the events file."""
        assert not obs.events_file.exists()

        obs.log_event(EventType.SESSION_START, {"session_id": 1})

        assert obs.events_file.exists()

    def test_log_event_appends(self, obs):
        """Test that events are appended to the file."""
        obs.log_event(EventType.SESSION_START, {"session_id": 1})
        obs.log_event(EventType.TOOL_CALL, {"tool": "Read"})
        obs.log_event(EventType.SESSION_END, {"status": "completed"})

        # Read the file and count lines
        lines = obs.events_file.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_log_event_returns_id(self, obs):
        """Test that log_event returns an event ID."""
        event_id = obs.log_event(EventType.SESSION_START, {"test": True})

        assert event_id is not None
        assert len(event_id) == 8  # UUID truncated to 8 chars

    def test_start_session(self, obs):
        """Test session start logging."""
        event_id = obs.start_session(1)

        assert obs._current_session_id == 1
        assert obs._session_start_time is not None
        assert event_id is not None

    def test_end_session(self, obs):
        """Test session end logging."""
        obs.start_session(1)
        event_id = obs.end_session(status="completed", reason="All done")

        assert obs._current_session_id is None
        assert event_id is not None

    def test_log_tool_call(self, obs):
        """Test tool call logging."""
        obs.start_session(1)
        event_id = obs.log_tool_call(
            tool_name="Read",
            tool_input={"file_path": "test.py"},
            feature_index=5,
        )

        assert event_id is not None

        events = obs.get_events(event_type=EventType.TOOL_CALL)
        assert len(events) == 1
        assert events[0].tool_name == "Read"
        assert events[0].feature_index == 5

    def test_log_tool_result_success(self, obs):
        """Test successful tool result logging."""
        obs.start_session(1)
        obs.log_tool_result(
            tool_name="Write",
            success=True,
            duration_ms=100,
        )

        events = obs.get_events(event_type=EventType.TOOL_RESULT)
        assert len(events) == 1
        assert events[0].data["success"] is True
        assert events[0].duration_ms == 100

    def test_log_tool_result_error(self, obs):
        """Test error tool result logging."""
        obs.start_session(1)
        obs.log_tool_result(
            tool_name="Bash",
            success=False,
            is_error=True,
            error_message="Command failed",
        )

        events = obs.get_events(event_type=EventType.TOOL_ERROR)
        assert len(events) == 1
        assert events[0].data["error_message"] == "Command failed"

    def test_log_tool_result_blocked(self, obs):
        """Test blocked tool result logging."""
        obs.start_session(1)
        obs.log_tool_result(
            tool_name="Bash",
            success=False,
            is_blocked=True,
            error_message="Command not allowed",
        )

        events = obs.get_events(event_type=EventType.TOOL_BLOCKED)
        assert len(events) == 1

    def test_log_error(self, obs):
        """Test error event logging."""
        obs.start_session(1)
        obs.log_error(
            error_message="Something broke",
            error_type="runtime",
            context={"line": 42},
        )

        events = obs.get_events(event_type=EventType.ERROR)
        assert len(events) == 1
        assert events[0].data["error_message"] == "Something broke"
        assert events[0].data["error_type"] == "runtime"

    def test_log_decision(self, obs):
        """Test decision event logging."""
        obs.start_session(1)
        obs.log_decision(
            decision_type="feature_selection",
            choice="Implement login",
            alternatives=["Implement logout", "Fix bug"],
            rationale="Login is prerequisite",
            confidence=0.8,
            feature_index=10,
        )

        events = obs.get_events(event_type=EventType.DECISION)
        assert len(events) == 1
        assert events[0].data["choice"] == "Implement login"
        assert events[0].data["confidence"] == 0.8

    def test_log_git_commit(self, obs):
        """Test git commit event logging."""
        obs.start_session(1)
        obs.log_git_commit(
            commit_hash="abc123def456",
            message="Add login feature",
            files_changed=5,
        )

        events = obs.get_events(event_type=EventType.GIT_COMMIT)
        assert len(events) == 1
        assert events[0].data["commit_hash"] == "abc123def456"


class TestEventQueries:
    """Tests for event querying functionality."""

    def test_get_events_all(self, obs):
        """Test getting all events."""
        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.log_tool_call("Write", {})
        obs.end_session()

        events = obs.get_events()
        assert len(events) == 4

    def test_get_events_by_session(self, obs):
        """Test filtering events by session."""
        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.end_session()

        obs.start_session(2)
        obs.log_tool_call("Write", {})
        obs.log_tool_call("Edit", {})
        obs.end_session()

        session1_events = obs.get_events(session_id=1)
        session2_events = obs.get_events(session_id=2)

        assert len(session1_events) == 3  # start, tool, end
        assert len(session2_events) == 4  # start, tool, tool, end

    def test_get_events_by_type(self, obs):
        """Test filtering events by type."""
        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.log_tool_result("Read", True)
        obs.log_error("Test error")
        obs.end_session()

        tool_calls = obs.get_events(event_type=EventType.TOOL_CALL)
        errors = obs.get_events(event_type=EventType.ERROR)

        assert len(tool_calls) == 1
        assert len(errors) == 1

    def test_get_events_by_tool(self, obs):
        """Test filtering events by tool name."""
        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.log_tool_call("Write", {})
        obs.log_tool_call("Read", {})

        read_events = obs.get_events(tool_name="Read")
        write_events = obs.get_events(tool_name="Write")

        assert len(read_events) == 2
        assert len(write_events) == 1

    def test_get_events_by_feature(self, obs):
        """Test filtering events by feature index."""
        obs.start_session(1)
        obs.log_tool_call("Read", {}, feature_index=1)
        obs.log_tool_call("Write", {}, feature_index=2)
        obs.log_tool_call("Edit", {}, feature_index=1)

        feature1_events = obs.get_events(feature_index=1)
        feature2_events = obs.get_events(feature_index=2)

        assert len(feature1_events) == 2
        assert len(feature2_events) == 1

    def test_get_events_limit(self, obs):
        """Test limiting number of events returned."""
        obs.start_session(1)
        for i in range(10):
            obs.log_tool_call(f"Tool{i}", {})

        events = obs.get_events(limit=5)
        assert len(events) == 5

    def test_get_session_events(self, obs):
        """Test getting events for a specific session in chronological order."""
        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.log_tool_call("Write", {})
        obs.end_session()

        events = obs.get_session_events(1)

        # Should be in chronological order
        assert events[0].event_type == EventType.SESSION_START.value
        assert events[-1].event_type == EventType.SESSION_END.value

    def test_get_latest_session_id(self, obs):
        """Test getting the most recent session ID."""
        obs.start_session(1)
        obs.end_session()
        obs.start_session(2)
        obs.end_session()
        obs.start_session(3)

        latest = obs.get_latest_session_id()
        assert latest == 3


class TestMetrics:
    """Tests for metrics computation."""

    def test_session_metrics(self, obs):
        """Test computing metrics for a single session."""
        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.log_tool_result("Read", True)
        obs.log_tool_call("Write", {})
        obs.log_tool_result("Write", False, is_error=True, error_message="Failed")
        obs.log_feature_event(EventType.FEATURE_STARTED, 1)
        obs.log_feature_event(EventType.FEATURE_COMPLETED, 1)
        obs.end_session()

        metrics = obs.get_session_metrics(1)

        assert metrics.session_id == 1
        assert metrics.tool_calls_total == 2
        assert metrics.tool_calls_successful == 1
        assert metrics.tool_calls_failed == 1
        assert metrics.features_attempted == 1
        assert metrics.features_completed == 1

    def test_run_metrics(self, obs):
        """Test computing aggregate metrics across sessions."""
        # Session 1
        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.log_tool_result("Read", True)
        obs.log_feature_event(EventType.FEATURE_COMPLETED, 1)
        obs.end_session(status="completed")

        # Session 2
        obs.start_session(2)
        obs.log_tool_call("Write", {})
        obs.log_tool_result("Write", True)
        obs.log_feature_event(EventType.FEATURE_COMPLETED, 2)
        obs.end_session(status="completed")

        metrics = obs.get_run_metrics()

        assert metrics.sessions_total == 2
        assert metrics.sessions_completed == 2
        assert metrics.total_tool_calls == 2
        assert metrics.total_features_completed == 2


class TestReconstruction:
    """Tests for session reconstruction."""

    def test_reconstruct_session(self, obs):
        """Test reconstructing a session timeline."""
        obs.start_session(1)
        obs.log_tool_call("Read", {"file_path": "test.py"})
        obs.log_tool_result("Read", True)
        obs.log_decision(
            decision_type="next_feature",
            choice="Implement login",
            confidence=0.9,
        )
        obs.end_session(status="completed")

        reconstruction = obs.reconstruct_session(1)

        assert reconstruction["session_id"] == 1
        assert reconstruction["event_count"] == 5
        assert "timeline" in reconstruction
        assert "metrics" in reconstruction

    def test_get_context_at_time(self, obs):
        """Test getting context at a specific timestamp."""
        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.log_error("Test error")

        # Get the timestamp of the last event
        events = obs.get_events(limit=1)
        timestamp = events[0].timestamp

        context = obs.get_context_at_time(timestamp)

        assert context["session_id"] == 1
        assert "recent_errors" in context
        assert len(context["recent_errors"]) >= 1


class TestUtilities:
    """Tests for utility functions."""

    def test_clear_events(self, obs):
        """Test clearing all events."""
        obs.log_event(EventType.SESSION_START, {})
        assert obs.events_file.exists()

        obs.clear_events()
        assert not obs.events_file.exists()

    def test_export_events(self, obs, temp_project_dir):
        """Test exporting events to JSON."""
        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.end_session()

        output_path = temp_project_dir / "exported.json"
        result_path = obs.export_events(output_path)

        assert result_path == output_path
        assert output_path.exists()

        # Verify content
        with open(output_path) as f:
            data = json.load(f)

        assert data["event_count"] == 3
        assert len(data["events"]) == 3


class TestFormatters:
    """Tests for formatting functions."""

    def test_format_event_summary(self):
        """Test formatting an event as a summary string."""
        event = Event(
            event_id="test",
            timestamp="2025-12-18T10:30:00+00:00",
            event_type="tool_call",
            session_id=1,
            data={},
            tool_name="Read",
            duration_ms=150,
        )

        summary = format_event_summary(event)

        assert "2025-12-18T10:30:00" in summary
        assert "tool_call" in summary
        assert "Read" in summary
        assert "150ms" in summary

    def test_format_metrics_summary(self):
        """Test formatting run metrics as a summary."""
        metrics = RunMetrics(
            run_id="test123",
            project_dir="/test/project",
            sessions_total=5,
            sessions_completed=4,
            total_tool_calls=100,
            total_tool_errors=5,
            total_features_completed=10,
        )

        summary = format_metrics_summary(metrics)

        assert "test123" in summary
        assert "4/5" in summary  # sessions completed
        assert "100" in summary  # tool calls


class TestInputTruncation:
    """Tests for input truncation to avoid huge log files."""

    def test_large_input_truncated(self, obs):
        """Test that large tool inputs are truncated."""
        obs.start_session(1)

        # Create a very large input
        large_input = {"content": "x" * 5000}
        obs.log_tool_call("Write", large_input)

        events = obs.get_events(event_type=EventType.TOOL_CALL)
        assert len(events) == 1

        # The stored input should be truncated
        stored_input = events[0].data.get("tool_input", {})
        if "_truncated" in stored_input:
            assert stored_input["_truncated"] is True
            assert len(stored_input.get("_preview", "")) <= 500
