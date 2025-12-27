"""
Tests for Hypothesis Tracking
==============================

Tests for the hypothesis tracking system in hypotheses.py.
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from arcadiaforge.hypotheses import (
    Hypothesis,
    HypothesisStatus,
    HypothesisType,
    Evidence,
    HypothesisTracker,
    create_hypothesis_tracker,
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
def tracker(temp_project):
    """Create a HypothesisTracker instance."""
    return HypothesisTracker(temp_project, session_id=1)


# =============================================================================
# Evidence Tests
# =============================================================================

class TestEvidence:
    """Tests for Evidence dataclass."""

    def test_evidence_creation(self):
        """Test creating evidence."""
        evidence = Evidence(
            added_at="2025-12-18T10:00:00Z",
            session_id=1,
            description="Reproduced the issue",
            supports=True,
            source="manual test",
            confidence=0.8,
        )

        assert evidence.supports is True
        assert evidence.confidence == 0.8

    def test_evidence_serialization(self):
        """Test evidence to_dict and from_dict."""
        evidence = Evidence(
            added_at="2025-12-18T10:00:00Z",
            session_id=1,
            description="Test evidence",
            supports=False,
            source="test",
            confidence=0.6,
        )

        data = evidence.to_dict()
        restored = Evidence.from_dict(data)

        assert restored.description == "Test evidence"
        assert restored.supports is False
        assert restored.confidence == 0.6


# =============================================================================
# Hypothesis Tests
# =============================================================================

class TestHypothesis:
    """Tests for Hypothesis dataclass."""

    def test_hypothesis_creation(self):
        """Test creating a hypothesis."""
        hyp = Hypothesis(
            hypothesis_id="HYP-1-1",
            created_at="2025-12-18T10:00:00Z",
            created_session=1,
            hypothesis_type="root_cause",
            observation="Tests fail intermittently",
            hypothesis="Race condition in async code",
            confidence=0.5,
        )

        assert hyp.hypothesis_id == "HYP-1-1"
        assert hyp.is_open is True
        assert hyp.is_resolved is False

    def test_add_evidence(self):
        """Test adding evidence to hypothesis."""
        hyp = Hypothesis(
            hypothesis_id="HYP-1-1",
            created_at="2025-12-18T10:00:00Z",
            created_session=1,
            hypothesis_type="root_cause",
            observation="Test",
            hypothesis="Test",
        )

        hyp.add_evidence(
            description="Confirmed race condition",
            supports=True,
            session_id=1,
            confidence=0.8,
        )

        assert len(hyp.evidence_for) == 1
        assert hyp.confidence > 0.5  # Should increase

    def test_add_counter_evidence(self):
        """Test adding counter evidence."""
        hyp = Hypothesis(
            hypothesis_id="HYP-1-1",
            created_at="2025-12-18T10:00:00Z",
            created_session=1,
            hypothesis_type="root_cause",
            observation="Test",
            hypothesis="Test",
        )

        hyp.add_evidence("Counter evidence", supports=False, session_id=1, confidence=0.9)

        assert len(hyp.evidence_against) == 1
        assert hyp.confidence < 0.5  # Should decrease

    def test_evidence_balance(self):
        """Test evidence balance calculation."""
        hyp = Hypothesis(
            hypothesis_id="HYP-1-1",
            created_at="2025-12-18T10:00:00Z",
            created_session=1,
            hypothesis_type="root_cause",
            observation="Test",
            hypothesis="Test",
        )

        # Add equal evidence both ways
        hyp.add_evidence("For", supports=True, session_id=1, confidence=0.5)
        hyp.add_evidence("Against", supports=False, session_id=1, confidence=0.5)

        assert hyp.evidence_balance == 0.0

    def test_resolve_hypothesis(self):
        """Test resolving a hypothesis."""
        hyp = Hypothesis(
            hypothesis_id="HYP-1-1",
            created_at="2025-12-18T10:00:00Z",
            created_session=1,
            hypothesis_type="root_cause",
            observation="Test",
            hypothesis="Test",
        )

        hyp.resolve(
            status=HypothesisStatus.CONFIRMED,
            session_id=2,
            resolution="Fixed the race condition",
        )

        assert hyp.is_resolved is True
        assert hyp.status == "confirmed"
        assert hyp.resolved_session == 2

    def test_mark_reviewed(self):
        """Test marking hypothesis as reviewed."""
        hyp = Hypothesis(
            hypothesis_id="HYP-1-1",
            created_at="2025-12-18T10:00:00Z",
            created_session=1,
            hypothesis_type="root_cause",
            observation="Test",
            hypothesis="Test",
        )

        hyp.mark_reviewed(session_id=2)

        assert hyp.review_count == 1
        assert 2 in hyp.sessions_seen

    def test_matches_context(self):
        """Test context matching."""
        hyp = Hypothesis(
            hypothesis_id="HYP-1-1",
            created_at="2025-12-18T10:00:00Z",
            created_session=1,
            hypothesis_type="root_cause",
            observation="Test",
            hypothesis="Test",
            context_keywords=["async", "timeout"],
            related_features=[5, 6],
            related_errors=["TimeoutError"],
        )

        # Good match
        score_good = hyp.matches_context({
            "keywords": ["async", "timeout"],
            "features": [5],
            "errors": ["TimeoutError"],
        })

        # No match
        score_bad = hyp.matches_context({
            "keywords": ["database"],
            "features": [10],
        })

        assert score_good > 0.5
        assert score_bad == 0.0

    def test_serialization(self):
        """Test hypothesis serialization."""
        hyp = Hypothesis(
            hypothesis_id="HYP-1-1",
            created_at="2025-12-18T10:00:00Z",
            created_session=1,
            hypothesis_type="root_cause",
            observation="Tests fail",
            hypothesis="Race condition",
            confidence=0.7,
            context_keywords=["async"],
            related_features=[5],
        )

        data = hyp.to_dict()
        restored = Hypothesis.from_dict(data)

        assert restored.hypothesis_id == "HYP-1-1"
        assert restored.observation == "Tests fail"
        assert restored.confidence == 0.7


# =============================================================================
# HypothesisTracker Tests
# =============================================================================

class TestHypothesisTracker:
    """Tests for HypothesisTracker class."""

    def test_initialization(self, temp_project):
        """Test tracker initialization."""
        tracker = HypothesisTracker(temp_project, session_id=5)
        assert tracker.session_id == 5
        assert tracker.hyp_dir.exists()

    def test_add_hypothesis(self, tracker):
        """Test adding a hypothesis."""
        hyp = tracker.add_hypothesis(
            observation="Tests fail randomly",
            hypothesis="Non-deterministic ordering",
            hypothesis_type=HypothesisType.ROOT_CAUSE,
            context_keywords=["random", "test"],
            related_features=[10, 11],
        )

        assert hyp.hypothesis_id.startswith("HYP-1-")
        assert len(tracker.active) == 1

    def test_get_hypothesis(self, tracker):
        """Test getting hypothesis by ID."""
        hyp = tracker.add_hypothesis(
            observation="Test",
            hypothesis="Test",
        )

        retrieved = tracker.get_hypothesis(hyp.hypothesis_id)
        assert retrieved is not None
        assert retrieved.hypothesis_id == hyp.hypothesis_id

    def test_update_hypothesis(self, tracker):
        """Test updating a hypothesis."""
        hyp = tracker.add_hypothesis(
            observation="Test",
            hypothesis="Initial hypothesis",
        )

        result = tracker.update_hypothesis(
            hyp.hypothesis_id,
            hypothesis="Updated hypothesis",
            context_keywords=["new", "keywords"],
        )

        assert result is True
        updated = tracker.get_hypothesis(hyp.hypothesis_id)
        assert updated.hypothesis == "Updated hypothesis"
        assert "new" in updated.context_keywords

    def test_add_evidence(self, tracker):
        """Test adding evidence via tracker."""
        hyp = tracker.add_hypothesis(
            observation="Test",
            hypothesis="Test",
        )

        result = tracker.add_evidence(
            hyp.hypothesis_id,
            description="Supporting evidence",
            supports=True,
            confidence=0.8,
        )

        assert result is True
        updated = tracker.get_hypothesis(hyp.hypothesis_id)
        assert len(updated.evidence_for) == 1

    def test_resolve_hypothesis(self, tracker):
        """Test resolving hypothesis via tracker."""
        hyp = tracker.add_hypothesis(
            observation="Test",
            hypothesis="Test",
        )

        result = tracker.resolve(
            hyp.hypothesis_id,
            status=HypothesisStatus.CONFIRMED,
            resolution="Fixed the issue",
        )

        assert result is True
        assert hyp.hypothesis_id not in tracker.active

    def test_mark_reviewed(self, tracker):
        """Test marking reviewed via tracker."""
        hyp = tracker.add_hypothesis(
            observation="Test",
            hypothesis="Test",
        )

        result = tracker.mark_reviewed(hyp.hypothesis_id)
        assert result is True

        updated = tracker.get_hypothesis(hyp.hypothesis_id)
        assert updated.review_count == 1

    def test_get_open_hypotheses(self, tracker):
        """Test getting open hypotheses."""
        tracker.add_hypothesis(observation="Test 1", hypothesis="Hyp 1")
        tracker.add_hypothesis(observation="Test 2", hypothesis="Hyp 2")
        hyp3 = tracker.add_hypothesis(observation="Test 3", hypothesis="Hyp 3")
        tracker.resolve(hyp3.hypothesis_id, HypothesisStatus.REJECTED, "Not valid")

        open_hyps = tracker.get_open_hypotheses()
        assert len(open_hyps) == 2

    def test_get_hypotheses_by_type(self, tracker):
        """Test filtering by type."""
        tracker.add_hypothesis(
            observation="Test",
            hypothesis="Root cause",
            hypothesis_type=HypothesisType.ROOT_CAUSE,
        )
        tracker.add_hypothesis(
            observation="Test",
            hypothesis="Side effect",
            hypothesis_type=HypothesisType.SIDE_EFFECT,
        )

        root_causes = tracker.get_hypotheses_by_type(HypothesisType.ROOT_CAUSE)
        assert len(root_causes) == 1

    def test_get_high_confidence_hypotheses(self, tracker):
        """Test filtering by confidence."""
        hyp = tracker.add_hypothesis(
            observation="Test",
            hypothesis="Test",
            initial_confidence=0.8,
        )

        high_conf = tracker.get_high_confidence_hypotheses(min_confidence=0.7)
        assert len(high_conf) == 1

    def test_get_low_confidence_hypotheses(self, tracker):
        """Test getting low confidence hypotheses."""
        hyp = tracker.add_hypothesis(
            observation="Test",
            hypothesis="Test",
            initial_confidence=0.2,
        )

        low_conf = tracker.get_low_confidence_hypotheses(max_confidence=0.3)
        assert len(low_conf) == 1

    def test_find_matching(self, tracker):
        """Test finding matching hypotheses."""
        tracker.add_hypothesis(
            observation="Async timeout",
            hypothesis="Connection pool exhausted",
            context_keywords=["async", "timeout", "pool"],
            related_features=[10],
        )
        tracker.add_hypothesis(
            observation="Database error",
            hypothesis="Schema mismatch",
            context_keywords=["database", "schema"],
        )

        matches = tracker.find_matching({
            "keywords": ["async", "timeout"],
            "features": [10],
        })

        assert len(matches) >= 1
        assert matches[0][0].observation == "Async timeout"

    def test_find_by_feature(self, tracker):
        """Test finding by feature."""
        tracker.add_hypothesis(
            observation="Test",
            hypothesis="Test",
            related_features=[5, 6],
        )

        matches = tracker.find_by_feature(5)
        assert len(matches) == 1

    def test_find_by_keyword(self, tracker):
        """Test finding by keyword."""
        tracker.add_hypothesis(
            observation="Timeout issue",
            hypothesis="Network delay",
            context_keywords=["timeout", "network"],
        )

        matches = tracker.find_by_keyword("timeout")
        assert len(matches) == 1

    def test_get_session_review_list(self, tracker):
        """Test getting session review list."""
        # High confidence
        tracker.add_hypothesis(
            observation="High conf",
            hypothesis="Test",
            initial_confidence=0.9,
        )
        # Low confidence
        tracker.add_hypothesis(
            observation="Low conf",
            hypothesis="Test",
            initial_confidence=0.1,
        )

        review_list = tracker.get_session_review_list()
        assert len(review_list) == 2

    def test_persistence(self, temp_project):
        """Test that hypotheses persist across instances."""
        tracker1 = HypothesisTracker(temp_project, session_id=1)
        hyp = tracker1.add_hypothesis(
            observation="Persistent observation",
            hypothesis="Persistent hypothesis",
            context_keywords=["test"],
        )
        hyp_id = hyp.hypothesis_id

        # Create new instance
        tracker2 = HypothesisTracker(temp_project, session_id=2)
        retrieved = tracker2.get_hypothesis(hyp_id)

        assert retrieved is not None
        assert retrieved.observation == "Persistent observation"

    def test_history_logging(self, tracker):
        """Test that events are logged to history."""
        hyp = tracker.add_hypothesis(
            observation="Test",
            hypothesis="Test",
        )
        tracker.add_evidence(hyp.hypothesis_id, "Evidence", supports=True)
        tracker.resolve(hyp.hypothesis_id, HypothesisStatus.CONFIRMED, "Done")

        history = tracker.get_history()
        events = [h["event"] for h in history]

        assert "created" in events
        assert "evidence_added" in events
        assert "resolved" in events

    def test_get_resolved_hypotheses(self, tracker):
        """Test getting resolved hypotheses from history."""
        hyp = tracker.add_hypothesis(
            observation="To be resolved",
            hypothesis="Test",
        )
        tracker.resolve(hyp.hypothesis_id, HypothesisStatus.CONFIRMED, "Fixed")

        resolved = tracker.get_resolved_hypotheses()
        assert len(resolved) == 1
        assert resolved[0].status == "confirmed"

    def test_get_summary(self, tracker):
        """Test getting tracker summary."""
        tracker.add_hypothesis(observation="Test 1", hypothesis="Test", initial_confidence=0.8)
        tracker.add_hypothesis(observation="Test 2", hypothesis="Test", initial_confidence=0.2)

        summary = tracker.get_summary()
        assert summary["total_active"] == 2
        assert summary["high_confidence"] == 1
        assert summary["low_confidence"] == 1

    def test_get_context_for_prompt(self, tracker):
        """Test getting context for prompts."""
        tracker.add_hypothesis(
            observation="Test observation",
            hypothesis="Test hypothesis",
            initial_confidence=0.8,
        )

        context = tracker.get_context_for_prompt()
        assert "Active Hypotheses" in context


# =============================================================================
# HypothesisStatus and HypothesisType Tests
# =============================================================================

class TestEnums:
    """Tests for enum values."""

    def test_hypothesis_status_values(self):
        """Test HypothesisStatus enum values."""
        assert HypothesisStatus.OPEN.value == "open"
        assert HypothesisStatus.CONFIRMED.value == "confirmed"
        assert HypothesisStatus.REJECTED.value == "rejected"
        assert HypothesisStatus.IRRELEVANT.value == "irrelevant"
        assert HypothesisStatus.SUPERSEDED.value == "superseded"

    def test_hypothesis_type_values(self):
        """Test HypothesisType enum values."""
        assert HypothesisType.ROOT_CAUSE.value == "root_cause"
        assert HypothesisType.SIDE_EFFECT.value == "side_effect"
        assert HypothesisType.DEPENDENCY.value == "dependency"
        assert HypothesisType.OBSERVATION.value == "observation"


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_hypothesis_tracker(self, temp_project):
        """Test create_hypothesis_tracker."""
        tracker = create_hypothesis_tracker(temp_project, session_id=10)
        assert isinstance(tracker, HypothesisTracker)
        assert tracker.session_id == 10


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_context_matching(self, tracker):
        """Test matching with empty context."""
        hyp = tracker.add_hypothesis(
            observation="Test",
            hypothesis="Test",
            context_keywords=["test"],
        )

        matches = tracker.find_matching({})
        assert len(matches) == 0

    def test_update_nonexistent_hypothesis(self, tracker):
        """Test updating nonexistent hypothesis."""
        result = tracker.update_hypothesis("HYP-99-99", hypothesis="New")
        assert result is False

    def test_add_evidence_nonexistent(self, tracker):
        """Test adding evidence to nonexistent hypothesis."""
        result = tracker.add_evidence("HYP-99-99", "Evidence", supports=True)
        assert result is False

    def test_resolve_nonexistent(self, tracker):
        """Test resolving nonexistent hypothesis."""
        result = tracker.resolve("HYP-99-99", HypothesisStatus.CONFIRMED, "Done")
        assert result is False

    def test_superseded_hypothesis(self, tracker):
        """Test superseding a hypothesis."""
        hyp1 = tracker.add_hypothesis(observation="Old", hypothesis="Old hypothesis")
        hyp2 = tracker.add_hypothesis(observation="New", hypothesis="New hypothesis")

        tracker.resolve(
            hyp1.hypothesis_id,
            HypothesisStatus.SUPERSEDED,
            "Replaced by newer hypothesis",
            superseded_by=hyp2.hypothesis_id,
        )

        resolved = tracker.get_resolved_hypotheses()
        assert len(resolved) == 1
        assert resolved[0].superseded_by == hyp2.hypothesis_id
