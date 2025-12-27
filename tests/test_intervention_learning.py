"""
Tests for Intervention Learning Module
======================================

Tests for the InterventionLearner class and related functionality.
"""

import json
import pytest
import tempfile
from pathlib import Path

from arcadiaforge.intervention_learning import (
    InterventionType,
    ContextSignature,
    Intervention,
    InterventionPattern,
    MatchResult,
    InterventionLearner,
    create_intervention_learner,
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
def learner(temp_project):
    """Create an InterventionLearner instance."""
    return InterventionLearner(temp_project)


@pytest.fixture
def populated_learner(temp_project):
    """Create a learner with some recorded interventions."""
    learner = InterventionLearner(temp_project)

    # Record some interventions
    sig1 = learner.create_context_signature(
        tool="Bash",
        trigger_type="error",
        error_message="Permission denied: /etc/passwd"
    )
    learner.record_intervention(
        session_id=1,
        intervention_type=InterventionType.CORRECTION,
        context_signature=sig1,
        human_action="Use sudo or change permissions",
        human_rationale="Need elevated permissions for system files",
    )

    sig2 = learner.create_context_signature(
        tool="Write",
        trigger_type="low_confidence",
        feature_category="authentication"
    )
    learner.record_intervention(
        session_id=1,
        intervention_type=InterventionType.GUIDANCE,
        context_signature=sig2,
        human_action="Use JWT instead of sessions",
        human_rationale="Better for stateless API",
    )

    return learner


# =============================================================================
# InterventionType Tests
# =============================================================================

class TestInterventionType:
    """Tests for InterventionType enum."""

    def test_all_types_exist(self):
        """Test that all expected types exist."""
        assert InterventionType.CORRECTION
        assert InterventionType.OVERRIDE
        assert InterventionType.GUIDANCE
        assert InterventionType.APPROVAL
        assert InterventionType.REDIRECT


# =============================================================================
# ContextSignature Tests
# =============================================================================

class TestContextSignature:
    """Tests for ContextSignature dataclass."""

    def test_create_signature(self):
        """Test creating a signature."""
        sig = ContextSignature(
            tool="Bash",
            action_type="execute",
            trigger_type="error",
        )

        assert sig.tool == "Bash"
        assert sig.trigger_type == "error"

    def test_compute_hash(self):
        """Test hash computation."""
        sig = ContextSignature(tool="Bash", trigger_type="error")
        hash1 = sig.compute_hash()

        assert len(hash1) == 16
        assert sig.hash == hash1

    def test_same_content_same_hash(self):
        """Test that same content produces same hash."""
        sig1 = ContextSignature(tool="Bash", trigger_type="error")
        sig2 = ContextSignature(tool="Bash", trigger_type="error")

        assert sig1.hash == sig2.hash

    def test_different_content_different_hash(self):
        """Test that different content produces different hash."""
        sig1 = ContextSignature(tool="Bash", trigger_type="error")
        sig2 = ContextSignature(tool="Write", trigger_type="error")

        assert sig1.hash != sig2.hash

    def test_similarity_score_identical(self):
        """Test similarity score for identical signatures."""
        sig1 = ContextSignature(tool="Bash", trigger_type="error")
        sig2 = ContextSignature(tool="Bash", trigger_type="error")

        assert sig1.similarity_score(sig2) == 1.0

    def test_similarity_score_different(self):
        """Test similarity score for different signatures."""
        sig1 = ContextSignature(tool="Bash", trigger_type="error")
        sig2 = ContextSignature(tool="Write", trigger_type="success")

        assert sig1.similarity_score(sig2) == 0.0

    def test_similarity_score_partial(self):
        """Test similarity score for partially matching signatures."""
        sig1 = ContextSignature(tool="Bash", trigger_type="error", action_type="execute")
        sig2 = ContextSignature(tool="Bash", trigger_type="error", action_type="write")

        score = sig1.similarity_score(sig2)
        assert 0 < score < 1

    def test_to_dict(self):
        """Test serialization to dict."""
        sig = ContextSignature(tool="Bash", trigger_type="error")
        data = sig.to_dict()

        assert data["tool"] == "Bash"
        assert data["trigger_type"] == "error"
        assert "hash" in data

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "tool": "Write",
            "trigger_type": "low_confidence",
            "hash": "abc123",
        }
        sig = ContextSignature.from_dict(data)

        assert sig.tool == "Write"
        assert sig.trigger_type == "low_confidence"


# =============================================================================
# Intervention Tests
# =============================================================================

class TestIntervention:
    """Tests for Intervention dataclass."""

    def test_create_intervention(self):
        """Test creating an intervention."""
        sig = ContextSignature(tool="Bash")
        intervention = Intervention(
            intervention_id="INT-001",
            session_id=1,
            timestamp="2025-01-01T00:00:00Z",
            intervention_type=InterventionType.CORRECTION,
            context_signature=sig,
            human_action="Do something else",
        )

        assert intervention.intervention_id == "INT-001"
        assert intervention.intervention_type == InterventionType.CORRECTION

    def test_to_dict(self):
        """Test serialization to dict."""
        sig = ContextSignature(tool="Bash")
        intervention = Intervention(
            intervention_id="INT-001",
            session_id=1,
            timestamp="2025-01-01T00:00:00Z",
            intervention_type=InterventionType.GUIDANCE,
            context_signature=sig,
            human_action="Use alternative approach",
        )

        data = intervention.to_dict()

        assert data["intervention_id"] == "INT-001"
        assert data["intervention_type"] == "guidance"
        assert "context_signature" in data

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "intervention_id": "INT-002",
            "session_id": 2,
            "timestamp": "2025-01-01T00:00:00Z",
            "intervention_type": "override",
            "context_signature": {"tool": "Write"},
            "human_action": "Override action",
        }

        intervention = Intervention.from_dict(data)

        assert intervention.intervention_id == "INT-002"
        assert intervention.intervention_type == InterventionType.OVERRIDE


# =============================================================================
# InterventionPattern Tests
# =============================================================================

class TestInterventionPattern:
    """Tests for InterventionPattern dataclass."""

    def test_create_pattern(self):
        """Test creating a pattern."""
        sig = ContextSignature(tool="Bash", trigger_type="error")
        pattern = InterventionPattern(
            pattern_id="PAT-001",
            context_signature=sig,
            recommended_action="Use sudo",
            confidence=0.8,
        )

        assert pattern.pattern_id == "PAT-001"
        assert pattern.confidence == 0.8

    def test_update_confidence(self):
        """Test confidence update."""
        sig = ContextSignature(tool="Bash")
        pattern = InterventionPattern(
            pattern_id="PAT-001",
            context_signature=sig,
            success_count=8,
            failure_count=2,
        )

        pattern.update_confidence()

        assert pattern.confidence == 0.8

    def test_auto_apply_enabled_on_high_confidence(self):
        """Test auto-apply enabled with high confidence."""
        sig = ContextSignature(tool="Bash")
        pattern = InterventionPattern(
            pattern_id="PAT-001",
            context_signature=sig,
            success_count=10,
            failure_count=1,
            min_confidence_for_auto=0.8,
        )

        pattern.update_confidence()

        assert pattern.auto_apply is True

    def test_auto_apply_disabled_on_low_confidence(self):
        """Test auto-apply disabled with low confidence."""
        sig = ContextSignature(tool="Bash")
        pattern = InterventionPattern(
            pattern_id="PAT-001",
            context_signature=sig,
            success_count=2,
            failure_count=8,
        )

        pattern.update_confidence()

        assert pattern.auto_apply is False

    def test_record_match(self):
        """Test recording a match."""
        sig = ContextSignature(tool="Bash")
        pattern = InterventionPattern(
            pattern_id="PAT-001",
            context_signature=sig,
        )

        pattern.record_match()

        assert pattern.times_matched == 1
        assert pattern.last_matched is not None

    def test_record_application(self):
        """Test recording an application."""
        sig = ContextSignature(tool="Bash")
        pattern = InterventionPattern(
            pattern_id="PAT-001",
            context_signature=sig,
        )

        pattern.record_application(success=True)

        assert pattern.times_applied == 1
        assert pattern.success_count == 1


# =============================================================================
# InterventionLearner Initialization Tests
# =============================================================================

class TestInterventionLearnerInit:
    """Tests for InterventionLearner initialization."""

    def test_create_learner(self, temp_project):
        """Test creating an InterventionLearner."""
        learner = InterventionLearner(temp_project)

        assert learner.project_dir == temp_project

    def test_learning_dir_created(self, temp_project):
        """Test that .learning directory is created."""
        learner = InterventionLearner(temp_project)

        assert (temp_project / ".learning").exists()

    def test_convenience_function(self, temp_project):
        """Test create_intervention_learner function."""
        learner = create_intervention_learner(temp_project)

        assert isinstance(learner, InterventionLearner)


# =============================================================================
# Context Signature Creation Tests
# =============================================================================

class TestContextSignatureCreation:
    """Tests for context signature creation."""

    def test_create_signature_basic(self, learner):
        """Test creating a basic signature."""
        sig = learner.create_context_signature(
            tool="Bash",
            trigger_type="error"
        )

        assert sig.tool == "Bash"
        assert sig.trigger_type == "error"
        assert sig.hash is not None

    def test_error_normalization(self, learner):
        """Test error message normalization."""
        sig1 = learner.create_context_signature(
            error_message="Error at /path/to/file.py:123: undefined variable 'x'"
        )
        sig2 = learner.create_context_signature(
            error_message="Error at /other/path/test.py:456: undefined variable 'y'"
        )

        # Should have similar patterns after normalization
        assert sig1.error_pattern is not None
        assert sig2.error_pattern is not None


# =============================================================================
# Record Intervention Tests
# =============================================================================

class TestRecordIntervention:
    """Tests for recording interventions."""

    def test_record_intervention(self, learner):
        """Test recording an intervention."""
        sig = learner.create_context_signature(tool="Bash")
        intervention = learner.record_intervention(
            session_id=1,
            intervention_type=InterventionType.CORRECTION,
            context_signature=sig,
            human_action="Use alternative command",
        )

        assert intervention.intervention_id.startswith("INT-")
        assert intervention.session_id == 1

    def test_intervention_logged(self, learner, temp_project):
        """Test that interventions are logged."""
        sig = learner.create_context_signature(tool="Bash")
        learner.record_intervention(
            session_id=1,
            intervention_type=InterventionType.GUIDANCE,
            context_signature=sig,
            human_action="Do X instead",
        )

        assert (temp_project / ".learning" / "interventions.jsonl").exists()

    def test_pattern_created_from_intervention(self, learner):
        """Test that pattern is created from intervention."""
        sig = learner.create_context_signature(tool="NewTool", trigger_type="error")
        learner.record_intervention(
            session_id=1,
            intervention_type=InterventionType.CORRECTION,
            context_signature=sig,
            human_action="Use correct approach",
        )

        assert len(learner.patterns) >= 1


# =============================================================================
# Pattern Matching Tests
# =============================================================================

class TestPatternMatching:
    """Tests for pattern matching."""

    def test_find_matching_patterns(self, populated_learner):
        """Test finding matching patterns."""
        # Create signature matching the populated_learner's first intervention
        sig = populated_learner.create_context_signature(
            tool="Bash",
            trigger_type="error",
            error_message="Permission denied: /etc/passwd"  # Same error pattern
        )

        matches = populated_learner.find_matching_patterns(sig, min_similarity=0.5)

        # Should find at least one match
        assert len(matches) >= 1

    def test_no_match_for_unrelated(self, populated_learner):
        """Test no match for unrelated context."""
        sig = populated_learner.create_context_signature(
            tool="CompletelyDifferentTool",
            trigger_type="unknown",
        )

        matches = populated_learner.find_matching_patterns(sig)

        # Should not find matches
        assert len(matches) == 0

    def test_get_recommendation(self, populated_learner):
        """Test getting recommendation."""
        # Use lower threshold to find matching pattern
        populated_learner.similarity_threshold = 0.5

        sig = populated_learner.create_context_signature(
            tool="Bash",
            trigger_type="error",
            error_message="Permission denied: /some/file"  # Similar error pattern
        )

        rec = populated_learner.get_recommendation(sig)

        assert rec is not None
        assert rec.recommendation != ""


# =============================================================================
# Auto-Apply Tests
# =============================================================================

class TestAutoApply:
    """Tests for auto-apply functionality."""

    def test_should_auto_apply_new_pattern(self, learner):
        """Test that new patterns don't auto-apply."""
        sig = learner.create_context_signature(tool="Bash")
        learner.record_intervention(
            session_id=1,
            intervention_type=InterventionType.CORRECTION,
            context_signature=sig,
            human_action="Do X",
        )

        result = learner.should_auto_apply(sig)

        # New patterns shouldn't auto-apply
        assert result is None

    def test_should_auto_apply_proven_pattern(self, temp_project):
        """Test that proven patterns can auto-apply."""
        learner = InterventionLearner(temp_project)

        sig = learner.create_context_signature(tool="TestTool", trigger_type="error")

        # Create a pattern with high confidence
        pattern = InterventionPattern(
            pattern_id="PAT-TEST",
            context_signature=sig,
            recommended_action="Use proven approach",
            auto_apply=True,
            confidence=0.9,
            success_count=10,
            failure_count=1,
        )
        learner.patterns.append(pattern)

        result = learner.should_auto_apply(sig)

        assert result is not None
        assert result.should_auto_apply is True


# =============================================================================
# Outcome Recording Tests
# =============================================================================

class TestOutcomeRecording:
    """Tests for outcome recording."""

    def test_record_outcome(self, learner):
        """Test recording outcome."""
        sig = learner.create_context_signature(tool="Bash")
        intervention = learner.record_intervention(
            session_id=1,
            intervention_type=InterventionType.CORRECTION,
            context_signature=sig,
            human_action="Use X",
        )

        result = learner.record_outcome(
            intervention.intervention_id,
            success=True,
            notes="Worked perfectly"
        )

        assert result is True

    def test_outcome_updates_pattern_confidence(self, learner):
        """Test that outcome updates pattern confidence."""
        sig = learner.create_context_signature(tool="Bash", trigger_type="test")
        intervention = learner.record_intervention(
            session_id=1,
            intervention_type=InterventionType.CORRECTION,
            context_signature=sig,
            human_action="Use X",
        )

        # Record successful outcomes
        for _ in range(5):
            learner.record_outcome(intervention.intervention_id, success=True)

        # Pattern should have updated confidence
        matching = [p for p in learner.patterns
                   if intervention.intervention_id in p.source_intervention_ids]
        if matching:
            assert matching[0].success_count >= 1


# =============================================================================
# Intervention Retrieval Tests
# =============================================================================

class TestInterventionRetrieval:
    """Tests for intervention retrieval."""

    def test_get_interventions(self, populated_learner):
        """Test getting interventions."""
        interventions = populated_learner.get_interventions()

        assert len(interventions) >= 2

    def test_filter_by_session(self, populated_learner):
        """Test filtering by session."""
        interventions = populated_learner.get_interventions(session_id=1)

        assert all(i.session_id == 1 for i in interventions)

    def test_filter_by_type(self, populated_learner):
        """Test filtering by type."""
        interventions = populated_learner.get_interventions(
            intervention_type=InterventionType.CORRECTION
        )

        assert all(i.intervention_type == InterventionType.CORRECTION
                  for i in interventions)


# =============================================================================
# Pattern Retrieval Tests
# =============================================================================

class TestPatternRetrieval:
    """Tests for pattern retrieval."""

    def test_get_patterns(self, populated_learner):
        """Test getting patterns."""
        patterns = populated_learner.get_patterns()

        assert len(patterns) >= 2

    def test_filter_auto_apply_only(self, temp_project):
        """Test filtering auto-apply only."""
        learner = InterventionLearner(temp_project)

        # Create patterns with different auto_apply settings
        sig1 = ContextSignature(tool="Tool1")
        sig2 = ContextSignature(tool="Tool2")

        learner.patterns = [
            InterventionPattern(
                pattern_id="PAT-1",
                context_signature=sig1,
                auto_apply=True,
            ),
            InterventionPattern(
                pattern_id="PAT-2",
                context_signature=sig2,
                auto_apply=False,
            ),
        ]

        auto_only = learner.get_patterns(auto_apply_only=True)

        assert len(auto_only) == 1
        assert auto_only[0].pattern_id == "PAT-1"


# =============================================================================
# Learning Stats Tests
# =============================================================================

class TestLearningStats:
    """Tests for learning statistics."""

    def test_get_learning_stats(self, populated_learner):
        """Test getting learning stats."""
        stats = populated_learner.get_learning_stats()

        assert "total_interventions" in stats
        assert "by_type" in stats
        assert "total_patterns" in stats

    def test_stats_by_type(self, populated_learner):
        """Test stats breakdown by type."""
        stats = populated_learner.get_learning_stats()

        assert "correction" in stats["by_type"]
        assert "guidance" in stats["by_type"]


# =============================================================================
# Format Tests
# =============================================================================

class TestFormatting:
    """Tests for pattern formatting."""

    def test_format_pattern(self, learner):
        """Test formatting a pattern."""
        sig = ContextSignature(tool="Bash", trigger_type="error")
        pattern = InterventionPattern(
            pattern_id="PAT-001",
            context_signature=sig,
            recommended_action="Use sudo",
            rationale="Need elevated permissions",
            confidence=0.85,
        )

        formatted = learner.format_pattern(pattern)

        assert "PAT-001" in formatted
        assert "Use sudo" in formatted
        assert "85%" in formatted


# =============================================================================
# Reset Tests
# =============================================================================

class TestReset:
    """Tests for reset functionality."""

    def test_reset_learning(self, populated_learner):
        """Test resetting learning."""
        assert len(populated_learner.patterns) > 0

        populated_learner.reset_learning()

        assert len(populated_learner.patterns) == 0

    def test_reset_keeps_history(self, populated_learner, temp_project):
        """Test that reset keeps intervention history."""
        populated_learner.reset_learning()

        # Interventions file should still exist
        assert (temp_project / ".learning" / "interventions.jsonl").exists()
