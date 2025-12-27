"""
Tests for Memory Module
========================

Tests for the tiered memory system (hot, warm, cold) and MemoryManager.
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from arcadiaforge.memory import (
    MemoryManager,
    HotMemory,
    WarmMemory,
    ColdMemory,
    WorkingContext,
    ActiveError,
    PendingDecision,
    SessionSummary,
    UnresolvedIssue,
    ProvenPattern,
    ArchivedSession,
    KnowledgeEntry,
    create_memory_manager,
    create_hot_memory,
    create_warm_memory,
    create_cold_memory,
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
def hot_memory(temp_project):
    """Create a HotMemory instance."""
    return HotMemory(temp_project, session_id=1)


@pytest.fixture
def warm_memory(temp_project):
    """Create a WarmMemory instance."""
    return WarmMemory(temp_project)


@pytest.fixture
def cold_memory(temp_project):
    """Create a ColdMemory instance."""
    return ColdMemory(temp_project)


@pytest.fixture
def memory_manager(temp_project):
    """Create a MemoryManager instance."""
    return MemoryManager(temp_project, session_id=1)


# =============================================================================
# Hot Memory Tests
# =============================================================================

class TestHotMemory:
    """Tests for HotMemory class."""

    def test_initialization(self, temp_project):
        """Test hot memory initialization."""
        hot = HotMemory(temp_project, session_id=5)
        assert hot.session_id == 5
        assert hot.hot_dir.exists()

    def test_set_focus(self, hot_memory):
        """Test setting focus."""
        hot_memory.set_focus(
            feature=10,
            task="Implementing login",
            keywords=["auth", "login"],
        )

        assert hot_memory.context.current_feature == 10
        assert hot_memory.context.current_task == "Implementing login"
        assert "auth" in hot_memory.context.focus_keywords

    def test_add_action(self, hot_memory):
        """Test adding actions."""
        hot_memory.add_action("Read file", "Success", tool="Read")

        assert len(hot_memory.context.recent_actions) == 1
        assert hot_memory.context.recent_actions[0]["action"] == "Read file"

    def test_action_limit(self, hot_memory):
        """Test action limit enforcement."""
        for i in range(30):
            hot_memory.add_action(f"Action {i}", "Result", tool="Test")

        # Should be limited to MAX_RECENT_ACTIONS
        assert len(hot_memory.context.recent_actions) == 20

    def test_add_file(self, hot_memory):
        """Test adding files."""
        hot_memory.add_file("src/main.py")
        hot_memory.add_file("src/utils.py")

        assert "src/main.py" in hot_memory.context.recent_files
        assert "src/utils.py" in hot_memory.context.recent_files

    def test_add_error(self, hot_memory):
        """Test adding errors."""
        error = hot_memory.add_error(
            "TypeError",
            "Cannot read property 'x'",
            context={"line": 10},
            related_features=[5, 6],
        )

        assert error.error_type == "TypeError"
        assert hot_memory.get_error_count() == 1

    def test_error_deduplication(self, hot_memory):
        """Test that duplicate errors increment count."""
        hot_memory.add_error("TypeError", "Same error")
        hot_memory.add_error("TypeError", "Same error")
        hot_memory.add_error("TypeError", "Same error")

        # Should still be 1 error with count 3
        errors = hot_memory.get_active_errors()
        assert len(errors) == 1
        assert errors[0].occurrence_count == 3

    def test_resolve_error(self, hot_memory):
        """Test resolving errors."""
        error = hot_memory.add_error("SyntaxError", "Missing paren")
        hot_memory.resolve_error(error.error_id, "Added missing paren")

        assert hot_memory.get_error_count() == 0

    def test_add_pending_decision(self, hot_memory):
        """Test adding pending decisions."""
        decision = hot_memory.add_pending_decision(
            decision_type="implementation_approach",
            context="How to implement auth",
            options=["JWT", "Sessions", "OAuth"],
            recommendation="JWT",
            confidence=0.7,
        )

        assert decision.decision_type == "implementation_approach"
        assert len(hot_memory.get_pending_decisions()) == 1

    def test_resolve_decision(self, hot_memory):
        """Test resolving decisions."""
        decision = hot_memory.add_pending_decision(
            decision_type="test",
            context="Test decision",
            options=["A", "B"],
        )

        resolved = hot_memory.resolve_decision(decision.decision_id)
        assert resolved is not None
        assert len(hot_memory.get_pending_decisions()) == 0

    def test_clear(self, hot_memory):
        """Test clearing hot memory."""
        hot_memory.add_action("Action", "Result")
        hot_memory.add_error("Error", "Message")

        hot_memory.clear()

        assert len(hot_memory.context.recent_actions) == 0
        assert hot_memory.get_error_count() == 0

    def test_get_summary(self, hot_memory):
        """Test getting summary."""
        hot_memory.set_focus(feature=5, task="Testing")
        hot_memory.add_error("Error", "Test")

        summary = hot_memory.get_summary()
        assert summary["current_feature"] == 5
        assert summary["active_errors"] == 1

    def test_persistence(self, temp_project):
        """Test that hot memory persists across instances."""
        hot1 = HotMemory(temp_project, session_id=1)
        hot1.set_focus(feature=10, task="Test task")
        hot1.add_error("TestError", "Test message")
        hot1.save()

        hot2 = HotMemory(temp_project, session_id=1)
        assert hot2.context.current_feature == 10
        assert hot2.get_error_count() == 1


# =============================================================================
# Warm Memory Tests
# =============================================================================

class TestWarmMemory:
    """Tests for WarmMemory class."""

    def test_initialization(self, temp_project):
        """Test warm memory initialization."""
        warm = WarmMemory(temp_project)
        assert warm.summaries_dir.exists()

    def test_add_session_summary(self, warm_memory):
        """Test adding session summary."""
        summary = SessionSummary(
            session_id=1,
            started_at="2025-12-18T10:00:00Z",
            ended_at="2025-12-18T11:00:00Z",
            duration_seconds=3600,
            features_started=5,
            features_completed=3,
            features_regressed=0,
        )

        warm_memory.add_session_summary(summary)
        retrieved = warm_memory.get_session_summary(1)

        assert retrieved is not None
        assert retrieved.features_completed == 3

    def test_session_pruning(self, warm_memory):
        """Test that old sessions are pruned."""
        for i in range(10):
            summary = SessionSummary(
                session_id=i,
                started_at="2025-12-18T10:00:00Z",
                ended_at="2025-12-18T11:00:00Z",
                duration_seconds=3600,
                features_started=1,
                features_completed=1,
                features_regressed=0,
            )
            warm_memory.add_session_summary(summary)

        # Should only keep MAX_SESSIONS
        assert len(warm_memory.summaries) == warm_memory.MAX_SESSIONS

    def test_get_recent_summaries(self, warm_memory):
        """Test getting recent summaries."""
        for i in range(5):
            summary = SessionSummary(
                session_id=i,
                started_at=f"2025-12-18T1{i}:00:00Z",
                ended_at=f"2025-12-18T1{i}:30:00Z",
                duration_seconds=1800,
                features_started=1,
                features_completed=1,
                features_regressed=0,
            )
            warm_memory.add_session_summary(summary)

        recent = warm_memory.get_recent_summaries(3)
        assert len(recent) == 3
        # Should be in reverse order (most recent first)
        assert recent[0].session_id == 4

    def test_add_unresolved_issue(self, warm_memory):
        """Test adding unresolved issues."""
        issue = warm_memory.add_unresolved_issue(
            issue_type="error",
            description="Persistent timeout issue",
            context={"timeout": 30000},
            related_features=[10, 11],
            session_id=1,
            priority=2,
        )

        assert issue.issue_type == "error"
        assert len(warm_memory.get_unresolved_issues()) == 1

    def test_resolve_issue(self, warm_memory):
        """Test resolving issues."""
        issue = warm_memory.add_unresolved_issue(
            issue_type="error",
            description="Test issue",
        )

        resolved = warm_memory.resolve_issue(issue.issue_id)
        assert resolved is not None
        assert len(warm_memory.get_unresolved_issues()) == 0

    def test_add_pattern(self, warm_memory):
        """Test adding patterns."""
        pattern = warm_memory.add_pattern(
            pattern_type="fix",
            problem="Async timeout",
            solution="Add retry logic",
            context_keywords=["async", "timeout", "retry"],
            session_id=1,
        )

        assert pattern.pattern_type == "fix"
        assert len(warm_memory.patterns) == 1

    def test_find_patterns(self, warm_memory):
        """Test finding patterns by query."""
        warm_memory.add_pattern(
            pattern_type="fix",
            problem="Authentication timeout",
            solution="Increase timeout",
            context_keywords=["auth", "timeout"],
        )
        warm_memory.add_pattern(
            pattern_type="fix",
            problem="Database connection error",
            solution="Use connection pool",
            context_keywords=["database", "connection"],
        )

        matches = warm_memory.find_patterns("timeout")
        assert len(matches) == 1
        assert "timeout" in matches[0].problem.lower()

    def test_record_pattern_success(self, warm_memory):
        """Test recording pattern success."""
        pattern = warm_memory.add_pattern(
            pattern_type="fix",
            problem="Test problem",
            solution="Test solution",
        )

        warm_memory.record_pattern_success(pattern.pattern_id, session_id=2)

        updated = warm_memory.patterns[pattern.pattern_id]
        assert updated.success_count == 2
        assert updated.confidence > 0.5

    def test_get_continuity_context(self, warm_memory):
        """Test getting continuity context."""
        summary = SessionSummary(
            session_id=1,
            started_at="2025-12-18T10:00:00Z",
            ended_at="2025-12-18T11:00:00Z",
            duration_seconds=3600,
            features_started=5,
            features_completed=3,
            features_regressed=0,
            warnings_for_next=["Check auth flow"],
        )
        warm_memory.add_session_summary(summary)

        context = warm_memory.get_continuity_context()
        assert context["last_session"] is not None
        assert "Check auth flow" in context["warnings"]


# =============================================================================
# Cold Memory Tests
# =============================================================================

class TestColdMemory:
    """Tests for ColdMemory class."""

    def test_initialization(self, temp_project):
        """Test cold memory initialization."""
        cold = ColdMemory(temp_project)
        assert cold.archive_dir.exists()

    def test_archive_session(self, cold_memory):
        """Test archiving a session."""
        session = cold_memory.archive_session(
            session_id=1,
            started_at="2025-12-18T10:00:00Z",
            ended_at="2025-12-18T11:00:00Z",
            ending_state="completed",
            features_completed=5,
            features_regressed=0,
            errors_count=2,
            duration_seconds=3600,
        )

        assert session.session_id == 1
        assert cold_memory.statistics.total_sessions == 1

    def test_statistics_update(self, cold_memory):
        """Test statistics are updated on archive."""
        for i in range(5):
            cold_memory.archive_session(
                session_id=i,
                started_at="2025-12-18T10:00:00Z",
                ended_at="2025-12-18T11:00:00Z",
                ending_state="completed",
                features_completed=3,
                features_regressed=0,
                errors_count=1,
                duration_seconds=3600,
            )

        stats = cold_memory.get_statistics()
        assert stats.total_sessions == 5
        assert stats.total_features_completed == 15

    def test_add_knowledge(self, cold_memory):
        """Test adding knowledge."""
        entry = cold_memory.add_knowledge(
            knowledge_type="fix",
            title="Async timeout fix",
            description="Add retry with exponential backoff",
            context_keywords=["async", "timeout", "retry"],
            confidence=0.8,
        )

        assert entry.knowledge_type == "fix"
        assert len(cold_memory.knowledge) == 1

    def test_search_knowledge(self, cold_memory):
        """Test searching knowledge."""
        cold_memory.add_knowledge(
            knowledge_type="fix",
            title="Authentication timeout",
            description="Increase auth timeout to 30s",
            context_keywords=["auth", "timeout"],
            confidence=0.8,
        )
        cold_memory.add_knowledge(
            knowledge_type="pattern",
            title="Database pooling",
            description="Use connection pooling",
            context_keywords=["database", "pool"],
            confidence=0.9,
        )

        matches = cold_memory.search_knowledge("timeout")
        assert len(matches) == 1
        assert "timeout" in matches[0].title.lower()

    def test_verify_knowledge(self, cold_memory):
        """Test verifying knowledge."""
        entry = cold_memory.add_knowledge(
            knowledge_type="fix",
            title="Test fix",
            description="Test description",
            confidence=0.5,
        )

        cold_memory.verify_knowledge(entry.knowledge_id)
        updated = cold_memory.knowledge[entry.knowledge_id]

        assert updated.times_verified == 2
        assert updated.confidence > 0.5

    def test_get_summary(self, cold_memory):
        """Test getting cold memory summary."""
        cold_memory.archive_session(
            session_id=1,
            started_at="2025-12-18T10:00:00Z",
            ended_at="2025-12-18T11:00:00Z",
            ending_state="completed",
            features_completed=5,
            features_regressed=0,
            errors_count=0,
            duration_seconds=3600,
        )
        cold_memory.add_knowledge(
            knowledge_type="fix",
            title="Test",
            description="Test",
        )

        summary = cold_memory.get_summary()
        assert summary["archived_sessions"] == 1
        assert summary["knowledge_entries"] == 1


# =============================================================================
# Memory Manager Tests
# =============================================================================

class TestMemoryManager:
    """Tests for MemoryManager class."""

    def test_initialization(self, temp_project):
        """Test memory manager initialization."""
        manager = MemoryManager(temp_project, session_id=5)
        assert manager.session_id == 5
        assert manager.hot is not None
        assert manager.warm is not None
        assert manager.cold is not None

    def test_start_session(self, memory_manager):
        """Test starting a session."""
        info = memory_manager.start_session()
        assert info["session_id"] == 1
        assert "started_at" in info

    def test_record_action(self, memory_manager):
        """Test recording actions."""
        memory_manager.record_action("Test action", "Success", tool="Test")
        assert len(memory_manager.hot.context.recent_actions) == 1

    def test_record_error(self, memory_manager):
        """Test recording errors."""
        error = memory_manager.record_error("TestError", "Test message")
        assert error.error_type == "TestError"
        assert memory_manager.hot.get_error_count() == 1

    def test_set_focus(self, memory_manager):
        """Test setting focus."""
        memory_manager.set_focus(
            feature=10,
            task="Testing",
            keywords=["test"],
        )
        assert memory_manager.hot.context.current_feature == 10

    def test_end_session(self, memory_manager):
        """Test ending a session."""
        memory_manager.set_focus(feature=5, task="Testing")
        memory_manager.record_error("TestError", "Test")

        summary = memory_manager.end_session(
            ending_state="completed",
            features_started=3,
            features_completed=2,
        )

        assert summary.session_id == 1
        assert summary.features_completed == 2
        # Warm memory should have the summary
        assert memory_manager.warm.get_session_summary(1) is not None
        # Hot memory should be cleared
        assert memory_manager.hot.get_error_count() == 0

    def test_learn_pattern(self, memory_manager):
        """Test learning a pattern."""
        pattern = memory_manager.learn_pattern(
            problem="Test timeout",
            solution="Add retry",
            pattern_type="fix",
        )

        assert pattern.problem == "Test timeout"
        assert len(memory_manager.warm.patterns) == 1

    def test_find_solutions(self, memory_manager):
        """Test finding solutions from patterns and knowledge."""
        memory_manager.warm.add_pattern(
            pattern_type="fix",
            problem="Timeout issue",
            solution="Use retry logic",
            context_keywords=["timeout"],
        )
        memory_manager.cold.add_knowledge(
            knowledge_type="fix",
            title="Connection timeout",
            description="Set higher timeout value",
            context_keywords=["timeout", "connection"],
            confidence=0.8,
        )

        solutions = memory_manager.find_solutions("timeout")
        assert len(solutions) >= 1

    def test_get_full_context(self, memory_manager):
        """Test getting full context from all tiers."""
        memory_manager.set_focus(feature=5, task="Testing")

        context = memory_manager.get_full_context()
        assert "Current Session" in context or "No memory context" in context

    def test_get_summary(self, memory_manager):
        """Test getting overall summary."""
        summary = memory_manager.get_summary()
        assert "hot" in summary
        assert "warm" in summary
        assert "cold" in summary


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_memory_manager(self, temp_project):
        """Test create_memory_manager."""
        manager = create_memory_manager(temp_project, session_id=10)
        assert isinstance(manager, MemoryManager)
        assert manager.session_id == 10

    def test_create_hot_memory(self, temp_project):
        """Test create_hot_memory."""
        hot = create_hot_memory(temp_project, session_id=5)
        assert isinstance(hot, HotMemory)
        assert hot.session_id == 5

    def test_create_warm_memory(self, temp_project):
        """Test create_warm_memory."""
        warm = create_warm_memory(temp_project)
        assert isinstance(warm, WarmMemory)

    def test_create_cold_memory(self, temp_project):
        """Test create_cold_memory."""
        cold = create_cold_memory(temp_project)
        assert isinstance(cold, ColdMemory)


# =============================================================================
# DataClass Tests
# =============================================================================

class TestDataClasses:
    """Tests for dataclass serialization."""

    def test_working_context_serialization(self):
        """Test WorkingContext to_dict and from_dict."""
        ctx = WorkingContext(
            session_id=1,
            started_at="2025-12-18T10:00:00Z",
            current_feature=5,
            current_task="Testing",
        )

        data = ctx.to_dict()
        restored = WorkingContext.from_dict(data)

        assert restored.session_id == 1
        assert restored.current_feature == 5

    def test_session_summary_serialization(self):
        """Test SessionSummary serialization."""
        summary = SessionSummary(
            session_id=1,
            started_at="2025-12-18T10:00:00Z",
            ended_at="2025-12-18T11:00:00Z",
            duration_seconds=3600,
            features_started=5,
            features_completed=3,
            features_regressed=0,
            warnings_for_next=["Check auth"],
        )

        data = summary.to_dict()
        restored = SessionSummary.from_dict(data)

        assert restored.session_id == 1
        assert restored.features_completed == 3
        assert "Check auth" in restored.warnings_for_next

    def test_knowledge_entry_serialization(self):
        """Test KnowledgeEntry serialization."""
        entry = KnowledgeEntry(
            knowledge_id="KNOW-1",
            created_at="2025-12-18T10:00:00Z",
            knowledge_type="fix",
            title="Test",
            description="Test description",
            context_keywords=["test"],
            confidence=0.8,
        )

        data = entry.to_dict()
        restored = KnowledgeEntry.from_dict(data)

        assert restored.knowledge_id == "KNOW-1"
        assert restored.confidence == 0.8
