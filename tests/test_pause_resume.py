"""
Tests for Pause/Resume Functionality
=====================================

Tests for the pause/resume capability in checkpoint.py.
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from arcadiaforge.checkpoint import (
    PausedSession,
    SessionPauseManager,
    create_pause_manager,
    format_paused_session,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_project():
    """Create a temporary project directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def pause_manager(temp_project):
    """Create a SessionPauseManager for testing."""
    return SessionPauseManager(temp_project)


# =============================================================================
# PausedSession Tests
# =============================================================================

class TestPausedSession:
    """Tests for the PausedSession dataclass."""

    def test_paused_session_creation(self):
        """Test creating a PausedSession."""
        paused = PausedSession(
            session_id=5,
            paused_at="2025-12-18T10:00:00Z",
            current_feature=10,
            last_checkpoint_id="CP-5-1",
            resume_prompt="Continue from feature 10",
            features_passing=5,
            features_total=20,
        )

        assert paused.session_id == 5
        assert paused.current_feature == 10
        assert paused.features_passing == 5

    def test_paused_session_defaults(self):
        """Test default values for PausedSession."""
        paused = PausedSession(
            session_id=1,
            paused_at="2025-12-18T10:00:00Z",
        )

        assert paused.current_feature is None
        assert paused.pending_decisions == []
        assert paused.human_notes is None
        assert paused.iteration == 0

    def test_to_dict(self):
        """Test converting PausedSession to dictionary."""
        paused = PausedSession(
            session_id=3,
            paused_at="2025-12-18T10:00:00Z",
            pause_reason="User requested",
            features_passing=10,
            features_total=50,
        )

        d = paused.to_dict()
        assert d["session_id"] == 3
        assert d["features_passing"] == 10

    def test_from_dict(self):
        """Test creating PausedSession from dictionary."""
        data = {
            "session_id": 7,
            "paused_at": "2025-12-18T10:00:00Z",
            "current_feature": 15,
            "pending_decisions": ["D-7-1"],
            "pending_injections": [],
            "last_checkpoint_id": "CP-7-5",
            "resume_prompt": "Continue",
            "work_summary": "Working on auth",
            "pause_reason": "Break time",
            "human_notes": "Review this",
            "iteration": 7,
            "features_passing": 12,
            "features_total": 25,
        }

        paused = PausedSession.from_dict(data)
        assert paused.session_id == 7
        assert paused.current_feature == 15
        assert paused.human_notes == "Review this"

    def test_summary(self):
        """Test summary method."""
        paused = PausedSession(
            session_id=5,
            paused_at="2025-12-18T10:00:00Z",
            current_feature=10,
        )

        summary = paused.summary()
        assert "Session 5" in summary
        assert "#10" in summary


# =============================================================================
# SessionPauseManager Tests
# =============================================================================

class TestSessionPauseManager:
    """Tests for the SessionPauseManager class."""

    def test_manager_initialization(self, temp_project):
        """Test manager initialization."""
        manager = SessionPauseManager(temp_project)

        assert manager.project_dir == temp_project
        assert manager.pause_file == temp_project / ".paused_session.json"

    def test_is_paused_false(self, pause_manager):
        """Test is_paused returns False when not paused."""
        assert pause_manager.is_paused() is False

    def test_is_paused_true(self, pause_manager):
        """Test is_paused returns True when paused."""
        pause_manager.pause_session(session_id=1)
        assert pause_manager.is_paused() is True

    def test_pause_session(self, pause_manager):
        """Test pausing a session."""
        paused = pause_manager.pause_session(
            session_id=5,
            pause_reason="User request",
            current_feature=10,
            last_checkpoint_id="CP-5-1",
            resume_prompt="Continue from feature 10",
            iteration=5,
            features_passing=15,
            features_total=50,
        )

        assert paused.session_id == 5
        assert paused.pause_reason == "User request"
        assert paused.current_feature == 10

        # File should exist
        assert pause_manager.pause_file.exists()

    def test_get_paused_session(self, pause_manager):
        """Test getting paused session."""
        pause_manager.pause_session(
            session_id=3,
            pause_reason="Test",
            features_passing=5,
            features_total=20,
        )

        paused = pause_manager.get_paused_session()
        assert paused is not None
        assert paused.session_id == 3

    def test_get_paused_session_none(self, pause_manager):
        """Test getting paused session when none exists."""
        paused = pause_manager.get_paused_session()
        assert paused is None

    def test_resume_session(self, pause_manager):
        """Test resuming a session."""
        pause_manager.pause_session(
            session_id=5,
            pause_reason="Break",
            resume_prompt="Continue working",
        )

        resumed = pause_manager.resume_session(human_notes="Ready to continue")

        assert resumed is not None
        assert resumed.session_id == 5
        assert resumed.human_notes == "Ready to continue"

        # Pause file should be deleted
        assert not pause_manager.pause_file.exists()

    def test_resume_session_none(self, pause_manager):
        """Test resuming when no session is paused."""
        resumed = pause_manager.resume_session()
        assert resumed is None

    def test_cancel_pause(self, pause_manager):
        """Test cancelling a pause."""
        pause_manager.pause_session(session_id=1)

        cancelled = pause_manager.cancel_pause()
        assert cancelled is True
        assert not pause_manager.pause_file.exists()

    def test_cancel_pause_none(self, pause_manager):
        """Test cancelling when no pause exists."""
        cancelled = pause_manager.cancel_pause()
        assert cancelled is False

    def test_update_pause_notes(self, pause_manager):
        """Test updating pause notes."""
        pause_manager.pause_session(session_id=1)

        updated = pause_manager.update_pause_notes("New notes here")
        assert updated is True

        paused = pause_manager.get_paused_session()
        assert paused.human_notes == "New notes here"

    def test_update_pause_notes_none(self, pause_manager):
        """Test updating notes when no pause exists."""
        updated = pause_manager.update_pause_notes("Notes")
        assert updated is False

    def test_pause_history_logging(self, pause_manager):
        """Test that pause/resume events are logged."""
        pause_manager.pause_session(session_id=1, pause_reason="Test")
        pause_manager.resume_session()

        history = pause_manager.get_pause_history()

        # Should have pause and resume events
        assert len(history) >= 2

        event_types = [e.get("event_type") for e in history]
        assert "pause" in event_types
        assert "resume" in event_types

    def test_get_pause_history_empty(self, pause_manager):
        """Test getting empty pause history."""
        history = pause_manager.get_pause_history()
        assert history == []

    def test_multiple_pause_resume_cycles(self, pause_manager):
        """Test multiple pause/resume cycles."""
        for i in range(3):
            pause_manager.pause_session(
                session_id=i + 1,
                pause_reason=f"Pause {i + 1}",
            )
            pause_manager.resume_session()

        history = pause_manager.get_pause_history()
        assert len(history) == 6  # 3 pauses + 3 resumes


# =============================================================================
# Pause State Persistence Tests
# =============================================================================

class TestPauseStatePersistence:
    """Tests for pause state persistence."""

    def test_pause_persists_across_instances(self, temp_project):
        """Test that pause state persists across manager instances."""
        manager1 = SessionPauseManager(temp_project)
        manager1.pause_session(
            session_id=5,
            pause_reason="Test persistence",
            current_feature=10,
        )

        # Create new instance
        manager2 = SessionPauseManager(temp_project)
        paused = manager2.get_paused_session()

        assert paused is not None
        assert paused.session_id == 5
        assert paused.current_feature == 10

    def test_resume_clears_persistence(self, temp_project):
        """Test that resume clears the persisted state."""
        manager1 = SessionPauseManager(temp_project)
        manager1.pause_session(session_id=3)

        # Resume
        manager1.resume_session()

        # Create new instance
        manager2 = SessionPauseManager(temp_project)
        assert manager2.is_paused() is False


# =============================================================================
# Format Functions Tests
# =============================================================================

class TestFormatFunctions:
    """Tests for formatting functions."""

    def test_format_paused_session(self):
        """Test formatting a paused session."""
        paused = PausedSession(
            session_id=5,
            paused_at="2025-12-18T10:00:00Z",
            pause_reason="User requested",
            iteration=5,
            current_feature=10,
            last_checkpoint_id="CP-5-3",
            work_summary="Implementing authentication",
            resume_prompt="Continue with feature 10",
            features_passing=15,
            features_total=50,
            pending_decisions=["D-5-1"],
            pending_injections=["INJ-5-1"],
            human_notes="Review auth approach",
        )

        formatted = format_paused_session(paused)

        assert "PAUSED SESSION: 5" in formatted
        assert "User requested" in formatted
        assert "Iteration:     5" in formatted
        assert "Feature #10" in formatted
        assert "CP-5-3" in formatted
        assert "15/50" in formatted
        assert "Pending decisions: 1" in formatted
        assert "Review auth approach" in formatted
        assert "python agent.py --resume" in formatted

    def test_format_minimal_paused_session(self):
        """Test formatting a minimal paused session."""
        paused = PausedSession(
            session_id=1,
            paused_at="2025-12-18T10:00:00Z",
        )

        formatted = format_paused_session(paused)

        assert "PAUSED SESSION: 1" in formatted
        assert "0/0 features" in formatted


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_pause_manager(self, temp_project):
        """Test create_pause_manager factory function."""
        manager = create_pause_manager(temp_project)
        assert isinstance(manager, SessionPauseManager)
        assert manager.project_dir == temp_project


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_pause_with_empty_lists(self, pause_manager):
        """Test pausing with empty pending lists."""
        paused = pause_manager.pause_session(
            session_id=1,
            pending_decisions=[],
            pending_injections=[],
        )

        assert paused.pending_decisions == []
        assert paused.pending_injections == []

    def test_pause_with_long_text(self, pause_manager):
        """Test pausing with long text fields."""
        long_prompt = "Continue working on " + "feature " * 100
        long_summary = "Working on " + "stuff " * 100

        paused = pause_manager.pause_session(
            session_id=1,
            resume_prompt=long_prompt,
            work_summary=long_summary,
        )

        retrieved = pause_manager.get_paused_session()
        assert retrieved.resume_prompt == long_prompt
        assert retrieved.work_summary == long_summary

    def test_corrupted_pause_file(self, pause_manager):
        """Test handling of corrupted pause file."""
        # Write invalid JSON
        with open(pause_manager.pause_file, "w") as f:
            f.write("not valid json {{{")

        paused = pause_manager.get_paused_session()
        assert paused is None
