"""
Tests for Decision Logging Module
=================================

Tests for decision.py - structured logging of agent decisions.
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from arcadiaforge.decision import (
    Decision,
    DecisionType,
    DecisionLogger,
    create_decision_logger,
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
def decision_logger(temp_project):
    """Create a DecisionLogger for testing."""
    return DecisionLogger(temp_project)


# =============================================================================
# Decision Dataclass Tests
# =============================================================================

class TestDecision:
    """Tests for the Decision dataclass."""

    def test_decision_creation(self):
        """Test creating a Decision."""
        decision = Decision(
            decision_id="D-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            decision_type="implementation_approach",
            context="Implementing auth",
            choice="Use JWT",
            alternatives=["Session cookies", "OAuth"],
            rationale="JWT is stateless",
            confidence=0.8,
            inputs_consulted=["auth_module.py"],
        )

        assert decision.decision_id == "D-1-1"
        assert decision.session_id == 1
        assert decision.confidence == 0.8
        assert len(decision.alternatives) == 2

    def test_decision_to_dict(self):
        """Test converting Decision to dictionary."""
        decision = Decision(
            decision_id="D-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            decision_type="feature_selection",
            context="Selecting next feature",
            choice="Feature 5",
            alternatives=["Feature 3", "Feature 7"],
            rationale="Highest priority",
            confidence=0.9,
            inputs_consulted=[],
            related_features=[5],
        )

        d = decision.to_dict()
        assert d["decision_id"] == "D-1-1"
        assert d["related_features"] == [5]

    def test_decision_from_dict(self):
        """Test creating Decision from dictionary."""
        data = {
            "decision_id": "D-2-3",
            "timestamp": "2025-12-18T10:00:00Z",
            "session_id": 2,
            "decision_type": "bug_fix_strategy",
            "context": "Fixing auth bug",
            "choice": "Refactor",
            "alternatives": ["Patch", "Rewrite"],
            "rationale": "Cleaner solution",
            "confidence": 0.7,
            "inputs_consulted": ["error_log.txt"],
        }

        decision = Decision.from_dict(data)
        assert decision.decision_id == "D-2-3"
        assert decision.confidence == 0.7

    def test_decision_summary(self):
        """Test Decision summary method."""
        decision = Decision(
            decision_id="D-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            decision_type="implementation_approach",
            context="Test",
            choice="Use JWT tokens for authentication",
            alternatives=[],
            rationale="Test",
            confidence=0.85,
            inputs_consulted=[],
            related_features=[1, 2, 3],
        )

        summary = decision.summary()
        assert "D-1-1" in summary
        assert "85%" in summary
        assert "features=" in summary

    def test_is_low_confidence(self):
        """Test low confidence detection."""
        low = Decision(
            decision_id="D-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            decision_type="test",
            context="",
            choice="",
            alternatives=[],
            rationale="",
            confidence=0.4,
            inputs_consulted=[],
        )
        high = Decision(
            decision_id="D-1-2",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            decision_type="test",
            context="",
            choice="",
            alternatives=[],
            rationale="",
            confidence=0.8,
            inputs_consulted=[],
        )

        assert low.is_low_confidence is True
        assert high.is_low_confidence is False

    def test_needs_review(self):
        """Test needs_review property."""
        skip_decision = Decision(
            decision_id="D-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            decision_type="skip_feature",
            context="",
            choice="",
            alternatives=[],
            rationale="",
            confidence=0.9,
            inputs_consulted=[],
        )

        assert skip_decision.needs_review is True


# =============================================================================
# DecisionType Tests
# =============================================================================

class TestDecisionType:
    """Tests for DecisionType enum."""

    def test_all_types_have_values(self):
        """Test that all decision types have string values."""
        for dtype in DecisionType:
            assert isinstance(dtype.value, str)
            assert len(dtype.value) > 0

    def test_expected_types_exist(self):
        """Test that expected decision types exist."""
        assert DecisionType.FEATURE_SELECTION.value == "feature_selection"
        assert DecisionType.IMPLEMENTATION_APPROACH.value == "implementation_approach"
        assert DecisionType.BUG_FIX_STRATEGY.value == "bug_fix_strategy"
        assert DecisionType.SKIP_FEATURE.value == "skip_feature"


# =============================================================================
# DecisionLogger Tests
# =============================================================================

class TestDecisionLogger:
    """Tests for the DecisionLogger class."""

    def test_logger_initialization(self, temp_project):
        """Test logger creates directories."""
        logger = DecisionLogger(temp_project)

        assert logger.decisions_dir.exists()
        assert logger.decisions_dir == temp_project / ".decisions"

    def test_log_decision(self, decision_logger):
        """Test logging a decision."""
        decision = decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Selecting next feature",
            choice="Feature 5",
            alternatives=["Feature 3", "Feature 7"],
            rationale="Highest priority",
            confidence=0.9,
        )

        assert decision.decision_id == "D-1-1"
        assert decision.session_id == 1
        assert decision.choice == "Feature 5"

    def test_log_multiple_decisions(self, decision_logger):
        """Test logging multiple decisions."""
        d1 = decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Test 1",
            choice="A",
            alternatives=["B"],
            rationale="Reason 1",
            confidence=0.9,
        )
        d2 = decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.IMPLEMENTATION_APPROACH,
            context="Test 2",
            choice="X",
            alternatives=["Y"],
            rationale="Reason 2",
            confidence=0.8,
        )

        assert d1.decision_id == "D-1-1"
        assert d2.decision_id == "D-1-2"

    def test_log_decision_with_type_string(self, decision_logger):
        """Test logging with string type instead of enum."""
        decision = decision_logger.log_decision(
            session_id=1,
            decision_type="custom_type",
            context="Test",
            choice="A",
            alternatives=[],
            rationale="Test",
            confidence=0.5,
        )

        assert decision.decision_type == "custom_type"

    def test_get_decision(self, decision_logger):
        """Test retrieving a decision by ID."""
        logged = decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Test",
            choice="A",
            alternatives=[],
            rationale="Test",
            confidence=0.9,
        )

        retrieved = decision_logger.get(logged.decision_id)
        assert retrieved is not None
        assert retrieved.decision_id == logged.decision_id
        assert retrieved.choice == "A"

    def test_get_nonexistent_decision(self, decision_logger):
        """Test retrieving nonexistent decision returns None."""
        result = decision_logger.get("D-99-99")
        assert result is None

    def test_update_outcome(self, decision_logger):
        """Test updating decision outcome."""
        decision = decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.IMPLEMENTATION_APPROACH,
            context="Test",
            choice="Approach A",
            alternatives=["Approach B"],
            rationale="Test",
            confidence=0.7,
        )

        updated = decision_logger.update_outcome(
            decision.decision_id,
            success=True,
            outcome="Feature implemented successfully",
        )

        assert updated is not None
        assert updated.outcome == "Feature implemented successfully"
        assert updated.outcome_success is True

    def test_get_decisions_for_feature(self, decision_logger):
        """Test getting decisions related to a feature."""
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Working on feature 5",
            choice="A",
            alternatives=[],
            rationale="Test",
            confidence=0.9,
            related_features=[5],
        )
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.IMPLEMENTATION_APPROACH,
            context="Implementing feature 5",
            choice="B",
            alternatives=[],
            rationale="Test",
            confidence=0.8,
            related_features=[5],
        )
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Other feature",
            choice="C",
            alternatives=[],
            rationale="Test",
            confidence=0.9,
            related_features=[10],
        )

        feature_5_decisions = decision_logger.get_decisions_for_feature(5)
        assert len(feature_5_decisions) == 2

    def test_get_decisions_for_session(self, decision_logger):
        """Test getting decisions for a session."""
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Session 1",
            choice="A",
            alternatives=[],
            rationale="Test",
            confidence=0.9,
        )
        decision_logger.log_decision(
            session_id=2,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Session 2",
            choice="B",
            alternatives=[],
            rationale="Test",
            confidence=0.9,
        )
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.IMPLEMENTATION_APPROACH,
            context="Session 1 again",
            choice="C",
            alternatives=[],
            rationale="Test",
            confidence=0.8,
        )

        session_1 = decision_logger.get_decisions_for_session(1)
        assert len(session_1) == 2

        session_2 = decision_logger.get_decisions_for_session(2)
        assert len(session_2) == 1

    def test_get_low_confidence_decisions(self, decision_logger):
        """Test getting low confidence decisions."""
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="High confidence",
            choice="A",
            alternatives=[],
            rationale="Test",
            confidence=0.9,
        )
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.IMPLEMENTATION_APPROACH,
            context="Low confidence",
            choice="B",
            alternatives=[],
            rationale="Test",
            confidence=0.3,
        )
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.BUG_FIX_STRATEGY,
            context="Very low confidence",
            choice="C",
            alternatives=[],
            rationale="Test",
            confidence=0.2,
        )

        low_conf = decision_logger.get_low_confidence_decisions()
        assert len(low_conf) == 2
        # Should be sorted by confidence (lowest first)
        assert low_conf[0].confidence == 0.2
        assert low_conf[1].confidence == 0.3

    def test_get_stats(self, decision_logger):
        """Test getting decision statistics."""
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Test 1",
            choice="A",
            alternatives=[],
            rationale="Test",
            confidence=0.9,
        )
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Test 2",
            choice="B",
            alternatives=[],
            rationale="Test",
            confidence=0.4,
        )

        stats = decision_logger.get_stats()
        assert stats["total_decisions"] == 2
        assert stats["low_confidence_count"] == 1
        assert "feature_selection" in stats["by_type"]

    def test_list_recent(self, decision_logger):
        """Test listing recent decisions."""
        for i in range(5):
            decision_logger.log_decision(
                session_id=1,
                decision_type=DecisionType.FEATURE_SELECTION,
                context=f"Decision {i}",
                choice=f"Choice {i}",
                alternatives=[],
                rationale="Test",
                confidence=0.9,
            )

        recent = decision_logger.list_recent(limit=3)
        assert len(recent) == 3
        # Should be newest first
        assert recent[0].context == "Decision 4"

    def test_rebuild_index(self, decision_logger):
        """Test rebuilding index from log file."""
        # Log some decisions
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Test 1",
            choice="A",
            alternatives=[],
            rationale="Test",
            confidence=0.9,
        )
        decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.IMPLEMENTATION_APPROACH,
            context="Test 2",
            choice="B",
            alternatives=[],
            rationale="Test",
            confidence=0.8,
        )

        # Delete the index file
        decision_logger.index_file.unlink()

        # Rebuild
        count = decision_logger.rebuild_index()
        assert count == 2

        # Verify we can still retrieve decisions
        recent = decision_logger.list_recent()
        assert len(recent) == 2

    def test_confidence_normalization(self, decision_logger):
        """Test that confidence is normalized to 0.0-1.0."""
        d1 = decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Test",
            choice="A",
            alternatives=[],
            rationale="Test",
            confidence=1.5,  # Above 1.0
        )
        d2 = decision_logger.log_decision(
            session_id=1,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Test",
            choice="B",
            alternatives=[],
            rationale="Test",
            confidence=-0.5,  # Below 0.0
        )

        assert d1.confidence == 1.0
        assert d2.confidence == 0.0


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_decision_logger(self, temp_project):
        """Test create_decision_logger factory function."""
        logger = create_decision_logger(temp_project)
        assert isinstance(logger, DecisionLogger)
        assert logger.project_dir == temp_project
