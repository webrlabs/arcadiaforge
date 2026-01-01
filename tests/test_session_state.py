"""
Tests for Session State Persistence
====================================

Tests for arcadiaforge/session_state.py
"""

import pytest
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from arcadiaforge.session_state import (
    SessionState,
    SessionStateManager,
    create_session_state_manager,
)


class TestSessionState:
    """Tests for SessionState dataclass."""

    def test_basic_creation(self):
        """Test creating a basic SessionState."""
        state = SessionState(
            session_id=1,
            iteration=5,
            current_feature=107,
            pending_features=[108, 109, 110],
            completed_this_session=[105, 106],
            last_tool="bash",
            last_tool_input={"command": "pytest"},
            last_checkpoint="abc123",
            timestamp="2024-01-01T12:00:00",
        )

        assert state.session_id == 1
        assert state.iteration == 5
        assert state.current_feature == 107
        assert state.pending_features == [108, 109, 110]
        assert state.completed_this_session == [105, 106]
        assert state.last_tool == "bash"
        assert state.last_tool_input == {"command": "pytest"}

    def test_default_values(self):
        """Test default values for optional fields."""
        state = SessionState(
            session_id=1,
            iteration=1,
            current_feature=None,
            pending_features=[],
            completed_this_session=[],
            last_tool=None,
            last_tool_input=None,
            last_checkpoint=None,
            timestamp="2024-01-01T12:00:00",
        )

        assert state.git_hash is None
        assert state.tests_passing is None
        assert state.tests_total is None
        assert state.session_type is None
        assert state.recovery_attempt == 0
        assert state.warnings == []

    def test_to_dict(self):
        """Test converting SessionState to dictionary."""
        state = SessionState(
            session_id=2,
            iteration=10,
            current_feature=50,
            pending_features=[51, 52],
            completed_this_session=[49],
            last_tool="file_write",
            last_tool_input={"path": "test.py"},
            last_checkpoint="def456",
            timestamp="2024-01-01T12:00:00",
            tests_passing=5,
            tests_total=10,
        )

        data = state.to_dict()

        assert data["session_id"] == 2
        assert data["iteration"] == 10
        assert data["current_feature"] == 50
        assert data["tests_passing"] == 5
        assert data["tests_total"] == 10

    def test_from_dict(self):
        """Test creating SessionState from dictionary."""
        data = {
            "session_id": 3,
            "iteration": 15,
            "current_feature": 200,
            "pending_features": [201],
            "completed_this_session": [199],
            "last_tool": "git_commit",
            "last_tool_input": {"message": "test"},
            "last_checkpoint": "xyz789",
            "timestamp": "2024-01-01T12:00:00",
            "git_hash": "abcd1234",
            "tests_passing": 8,
            "tests_total": 10,
            "session_type": "coding",
            "recovery_attempt": 1,
            "warnings": ["Warning 1"],
        }

        state = SessionState.from_dict(data)

        assert state.session_id == 3
        assert state.iteration == 15
        assert state.git_hash == "abcd1234"
        assert state.warnings == ["Warning 1"]

    def test_from_dict_backwards_compatibility(self):
        """Test that from_dict handles missing fields."""
        # Minimal data without optional fields
        data = {
            "session_id": 1,
            "iteration": 1,
            "current_feature": None,
            "pending_features": [],
            "completed_this_session": [],
            "last_tool": None,
            "last_tool_input": None,
            "last_checkpoint": None,
            "timestamp": "2024-01-01T12:00:00",
        }

        state = SessionState.from_dict(data)

        assert state.git_hash is None
        assert state.tests_passing is None
        assert state.recovery_attempt == 0
        assert state.warnings == []


class TestSessionStateRecoveryPrompt:
    """Tests for SessionState.get_recovery_prompt()"""

    def test_basic_recovery_prompt(self):
        """Test basic recovery prompt generation."""
        state = SessionState(
            session_id=5,
            iteration=20,
            current_feature=None,
            pending_features=[],
            completed_this_session=[],
            last_tool=None,
            last_tool_input=None,
            last_checkpoint=None,
            timestamp="2024-01-01T12:00:00",
        )

        prompt = state.get_recovery_prompt()

        assert "CRASH RECOVERY NOTICE" in prompt
        assert "#5" in prompt
        assert "iteration 20" in prompt

    def test_recovery_prompt_with_feature(self):
        """Test recovery prompt includes current feature."""
        state = SessionState(
            session_id=1,
            iteration=1,
            current_feature=107,
            pending_features=[108, 109],
            completed_this_session=[105, 106],
            last_tool="bash",
            last_tool_input={"command": "pytest"},
            last_checkpoint=None,
            timestamp="2024-01-01T12:00:00",
        )

        prompt = state.get_recovery_prompt()

        assert "Feature #107" in prompt
        assert "bash" in prompt
        assert "[105, 106]" in prompt or "105" in prompt
        assert "[108, 109]" in prompt or "108" in prompt

    def test_recovery_prompt_truncates_large_input(self):
        """Test that recovery prompt truncates large tool input."""
        large_input = {"content": "x" * 500}

        state = SessionState(
            session_id=1,
            iteration=1,
            current_feature=None,
            pending_features=[],
            completed_this_session=[],
            last_tool="file_write",
            last_tool_input=large_input,
            last_checkpoint=None,
            timestamp="2024-01-01T12:00:00",
        )

        prompt = state.get_recovery_prompt()

        assert "..." in prompt
        assert len(prompt) < 1000  # Should be truncated

    def test_recovery_prompt_with_progress(self):
        """Test recovery prompt includes test progress."""
        state = SessionState(
            session_id=1,
            iteration=1,
            current_feature=None,
            pending_features=[],
            completed_this_session=[],
            last_tool=None,
            last_tool_input=None,
            last_checkpoint=None,
            timestamp="2024-01-01T12:00:00",
            tests_passing=5,
            tests_total=10,
        )

        prompt = state.get_recovery_prompt()

        assert "5/10 tests passing" in prompt

    def test_recovery_prompt_with_warnings(self):
        """Test recovery prompt includes warnings."""
        state = SessionState(
            session_id=1,
            iteration=1,
            current_feature=None,
            pending_features=[],
            completed_this_session=[],
            last_tool=None,
            last_tool_input=None,
            last_checkpoint=None,
            timestamp="2024-01-01T12:00:00",
            warnings=["Docker not available", "PostgreSQL connection failed"],
        )

        prompt = state.get_recovery_prompt()

        assert "Warnings" in prompt
        assert "Docker not available" in prompt

    def test_recovery_prompt_includes_instructions(self):
        """Test recovery prompt includes helpful instructions."""
        state = SessionState(
            session_id=1,
            iteration=1,
            current_feature=None,
            pending_features=[],
            completed_this_session=[],
            last_tool=None,
            last_tool_input=None,
            last_checkpoint=None,
            timestamp="2024-01-01T12:00:00",
        )

        prompt = state.get_recovery_prompt()

        assert "feature_stats" in prompt
        assert "feature_next" in prompt


class TestSessionStateManager:
    """Tests for SessionStateManager class."""

    def test_initialization(self, tmp_path):
        """Test manager initialization creates .arcadia directory."""
        manager = SessionStateManager(tmp_path)

        assert manager.project_dir == tmp_path
        assert manager.arcadia_dir == tmp_path / ".arcadia"
        assert manager.arcadia_dir.exists()

    def test_initialize_state(self, tmp_path):
        """Test initializing a new session state."""
        manager = SessionStateManager(tmp_path)

        state = manager.initialize_state(
            session_id=1,
            iteration=5,
            session_type="coding",
            pending_features=[100, 101, 102],
        )

        assert state.session_id == 1
        assert state.iteration == 5
        assert state.session_type == "coding"
        assert state.pending_features == [100, 101, 102]
        assert state.current_feature is None
        assert manager.state_file.exists()

    def test_save_and_load(self, tmp_path):
        """Test saving and loading state."""
        manager = SessionStateManager(tmp_path)

        original = SessionState(
            session_id=2,
            iteration=10,
            current_feature=50,
            pending_features=[51, 52],
            completed_this_session=[49],
            last_tool="bash",
            last_tool_input={"command": "npm test"},
            last_checkpoint="abc123",
            timestamp="2024-01-01T12:00:00",
        )

        manager.save(original)
        loaded = manager.load()

        assert loaded is not None
        assert loaded.session_id == original.session_id
        assert loaded.iteration == original.iteration
        assert loaded.current_feature == original.current_feature
        assert loaded.last_tool == original.last_tool

    def test_load_nonexistent(self, tmp_path):
        """Test loading when no state file exists."""
        manager = SessionStateManager(tmp_path)

        loaded = manager.load()

        assert loaded is None

    def test_load_corrupted(self, tmp_path):
        """Test loading corrupted state file."""
        manager = SessionStateManager(tmp_path)

        # Write invalid JSON
        manager.state_file.write_text("not valid json {{{")

        loaded = manager.load()

        assert loaded is None

    def test_clear(self, tmp_path):
        """Test clearing state."""
        manager = SessionStateManager(tmp_path)

        # Initialize state
        manager.initialize_state(session_id=1, iteration=1)
        assert manager.state_file.exists()

        manager.clear()

        assert not manager.state_file.exists()
        assert manager.get_current_state() is None

    def test_update(self, tmp_path):
        """Test updating specific fields."""
        manager = SessionStateManager(tmp_path)

        manager.initialize_state(session_id=1, iteration=1)

        updated = manager.update(
            current_feature=107,
            last_tool="file_write",
        )

        assert updated is not None
        assert updated.current_feature == 107
        assert updated.last_tool == "file_write"

    def test_update_no_state(self, tmp_path):
        """Test update when no state exists."""
        manager = SessionStateManager(tmp_path)

        result = manager.update(current_feature=100)

        assert result is None

    def test_record_tool_execution(self, tmp_path):
        """Test recording a tool execution."""
        manager = SessionStateManager(tmp_path)
        manager.initialize_state(session_id=1, iteration=1)

        manager.record_tool_execution(
            tool_name="bash",
            tool_input={"command": "pytest"},
            current_feature=105,
        )

        state = manager.get_current_state()
        assert state.last_tool == "bash"
        assert state.last_tool_input == {"command": "pytest"}
        assert state.current_feature == 105

    def test_record_feature_completed(self, tmp_path):
        """Test recording feature completion."""
        manager = SessionStateManager(tmp_path)
        manager.initialize_state(
            session_id=1,
            iteration=1,
            pending_features=[100, 101, 102],
        )

        manager.record_feature_completed(100)

        state = manager.get_current_state()
        assert 100 in state.completed_this_session
        assert 100 not in state.pending_features

    def test_record_feature_completed_no_duplicates(self, tmp_path):
        """Test that completing same feature twice doesn't duplicate."""
        manager = SessionStateManager(tmp_path)
        manager.initialize_state(session_id=1, iteration=1)

        manager.record_feature_completed(100)
        manager.record_feature_completed(100)

        state = manager.get_current_state()
        assert state.completed_this_session.count(100) == 1

    def test_record_checkpoint(self, tmp_path):
        """Test recording a checkpoint."""
        manager = SessionStateManager(tmp_path)
        manager.initialize_state(session_id=1, iteration=1)

        manager.record_checkpoint("checkpoint_abc123")

        state = manager.get_current_state()
        assert state.last_checkpoint == "checkpoint_abc123"

    def test_add_warning(self, tmp_path):
        """Test adding warnings."""
        manager = SessionStateManager(tmp_path)
        manager.initialize_state(session_id=1, iteration=1)

        manager.add_warning("Docker not available")
        manager.add_warning("PostgreSQL connection failed")

        state = manager.get_current_state()
        assert "Docker not available" in state.warnings
        assert "PostgreSQL connection failed" in state.warnings

    def test_add_warning_limit(self, tmp_path):
        """Test that warnings are limited to 20."""
        manager = SessionStateManager(tmp_path)
        manager.initialize_state(session_id=1, iteration=1)

        for i in range(30):
            manager.add_warning(f"Warning {i}")

        state = manager.get_current_state()
        assert len(state.warnings) == 20
        # Should keep the most recent
        assert "Warning 29" in state.warnings
        assert "Warning 0" not in state.warnings

    def test_update_progress(self, tmp_path):
        """Test updating progress metrics."""
        manager = SessionStateManager(tmp_path)
        manager.initialize_state(session_id=1, iteration=1)

        manager.update_progress(
            tests_passing=8,
            tests_total=10,
            git_hash="abc123",
        )

        state = manager.get_current_state()
        assert state.tests_passing == 8
        assert state.tests_total == 10
        assert state.git_hash == "abc123"


class TestSessionStateManagerCrashRecovery:
    """Tests for crash recovery functionality."""

    def test_check_for_crash_recovery_recent(self, tmp_path):
        """Test detecting recent crash for recovery."""
        manager = SessionStateManager(tmp_path)

        # Create recent state
        manager.initialize_state(session_id=1, iteration=5)
        manager.update(
            current_feature=107,
            last_tool="bash",
        )

        # Simulate restart - new manager instance
        new_manager = SessionStateManager(tmp_path)
        recovered = new_manager.check_for_crash_recovery()

        assert recovered is not None
        assert recovered.session_id == 1
        assert recovered.iteration == 5
        assert recovered.recovery_attempt == 1

    def test_check_for_crash_recovery_increments_attempt(self, tmp_path):
        """Test that recovery attempt counter increments."""
        manager = SessionStateManager(tmp_path)
        manager.initialize_state(session_id=1, iteration=1)

        # First recovery
        recovered1 = manager.check_for_crash_recovery()
        assert recovered1.recovery_attempt == 1

        # Second recovery attempt
        recovered2 = manager.check_for_crash_recovery()
        assert recovered2.recovery_attempt == 2

    def test_check_for_crash_recovery_stale(self, tmp_path):
        """Test that stale state is not recovered."""
        manager = SessionStateManager(tmp_path)

        # Create state with old timestamp
        state = SessionState(
            session_id=1,
            iteration=1,
            current_feature=None,
            pending_features=[],
            completed_this_session=[],
            last_tool=None,
            last_tool_input=None,
            last_checkpoint=None,
            timestamp=(datetime.now() - timedelta(hours=2)).isoformat(),
        )
        manager.save(state)

        # Check with 1 hour max age
        recovered = manager.check_for_crash_recovery(max_age_seconds=3600)

        assert recovered is None
        assert not manager.state_file.exists()  # Should be cleared

    def test_check_for_crash_recovery_no_state(self, tmp_path):
        """Test recovery check when no state exists."""
        manager = SessionStateManager(tmp_path)

        recovered = manager.check_for_crash_recovery()

        assert recovered is None


class TestCreateSessionStateManager:
    """Tests for create_session_state_manager helper."""

    def test_creates_manager(self, tmp_path):
        """Test factory function creates manager."""
        manager = create_session_state_manager(tmp_path)

        assert isinstance(manager, SessionStateManager)
        assert manager.project_dir == tmp_path


class TestSessionStatePersistence:
    """Integration tests for state persistence."""

    def test_full_session_lifecycle(self, tmp_path):
        """Test complete session lifecycle."""
        manager = SessionStateManager(tmp_path)

        # Initialize session
        manager.initialize_state(
            session_id=1,
            iteration=1,
            pending_features=[100, 101, 102],
        )

        # Record some work
        manager.record_tool_execution("bash", {"command": "pytest"}, current_feature=100)
        manager.update_progress(tests_passing=5, tests_total=10)
        manager.record_feature_completed(100)

        manager.record_tool_execution("file_write", {"path": "test.py"}, current_feature=101)
        manager.add_warning("Something went wrong")

        # Simulate crash - read from disk
        raw_data = json.loads(manager.state_file.read_text())

        assert raw_data["session_id"] == 1
        assert raw_data["current_feature"] == 101
        assert raw_data["last_tool"] == "file_write"
        assert 100 in raw_data["completed_this_session"]
        assert raw_data["tests_passing"] == 5
        assert "Something went wrong" in raw_data["warnings"]

        # Clear on completion
        manager.clear()
        assert not manager.state_file.exists()

    def test_state_survives_manager_restart(self, tmp_path):
        """Test that state survives manager instance restart."""
        # First manager instance
        manager1 = SessionStateManager(tmp_path)
        manager1.initialize_state(session_id=5, iteration=10)
        manager1.update(current_feature=200, last_tool="git_commit")

        # Completely new manager instance (simulating restart)
        manager2 = SessionStateManager(tmp_path)
        state = manager2.load()

        assert state is not None
        assert state.session_id == 5
        assert state.iteration == 10
        assert state.current_feature == 200
        assert state.last_tool == "git_commit"
