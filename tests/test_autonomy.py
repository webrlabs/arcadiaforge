"""
Tests for Autonomy Management Module
=====================================

Tests for the AutonomyManager class and related functionality.
"""

import json
import pytest
import tempfile
from pathlib import Path

from arcadiaforge.autonomy import (
    AutonomyLevel,
    ActionCategory,
    AutonomyConfig,
    AutonomyDecision,
    PerformanceMetrics,
    AutonomyManager,
    create_autonomy_manager,
    DEFAULT_ACTION_CATEGORIES,
    CATEGORY_REQUIRED_LEVELS,
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
def manager(temp_project):
    """Create an AutonomyManager instance."""
    return AutonomyManager(temp_project)


@pytest.fixture
def elevated_manager(temp_project):
    """Create an AutonomyManager with elevated level."""
    config = AutonomyConfig(level=AutonomyLevel.EXECUTE_REVIEW)
    return AutonomyManager(temp_project, config)


# =============================================================================
# AutonomyLevel Tests
# =============================================================================

class TestAutonomyLevel:
    """Tests for AutonomyLevel enum."""

    def test_level_ordering(self):
        """Test that levels are properly ordered."""
        assert AutonomyLevel.OBSERVE < AutonomyLevel.PLAN
        assert AutonomyLevel.PLAN < AutonomyLevel.EXECUTE_SAFE
        assert AutonomyLevel.EXECUTE_SAFE < AutonomyLevel.EXECUTE_REVIEW
        assert AutonomyLevel.EXECUTE_REVIEW < AutonomyLevel.FULL_AUTO

    def test_level_values(self):
        """Test level integer values."""
        assert AutonomyLevel.OBSERVE == 1
        assert AutonomyLevel.FULL_AUTO == 5

    def test_level_comparison(self):
        """Test level comparisons."""
        assert AutonomyLevel.EXECUTE_SAFE >= AutonomyLevel.OBSERVE
        assert AutonomyLevel.EXECUTE_SAFE >= AutonomyLevel.EXECUTE_SAFE
        assert not AutonomyLevel.OBSERVE >= AutonomyLevel.PLAN


# =============================================================================
# AutonomyConfig Tests
# =============================================================================

class TestAutonomyConfig:
    """Tests for AutonomyConfig dataclass."""

    def test_default_config(self):
        """Test default configuration."""
        config = AutonomyConfig()

        assert config.level == AutonomyLevel.EXECUTE_SAFE
        assert config.confidence_threshold == 0.5
        assert config.auto_adjust is True

    def test_custom_config(self):
        """Test custom configuration."""
        config = AutonomyConfig(
            level=AutonomyLevel.PLAN,
            confidence_threshold=0.7,
            error_demotion_count=5,
        )

        assert config.level == AutonomyLevel.PLAN
        assert config.confidence_threshold == 0.7
        assert config.error_demotion_count == 5

    def test_to_dict(self):
        """Test serialization to dict."""
        config = AutonomyConfig(level=AutonomyLevel.EXECUTE_REVIEW)
        data = config.to_dict()

        assert data["level"] == 4
        assert "confidence_threshold" in data
        assert "auto_adjust" in data

    def test_from_dict(self):
        """Test deserialization from dict."""
        data = {
            "level": 3,
            "confidence_threshold": 0.6,
            "auto_adjust": False,
        }
        config = AutonomyConfig.from_dict(data)

        assert config.level == AutonomyLevel.EXECUTE_SAFE
        assert config.confidence_threshold == 0.6
        assert config.auto_adjust is False

    def test_action_levels(self):
        """Test per-action level overrides."""
        config = AutonomyConfig(
            level=AutonomyLevel.EXECUTE_SAFE,
            action_levels={"feature_mark": AutonomyLevel.FULL_AUTO}
        )

        assert config.action_levels["feature_mark"] == AutonomyLevel.FULL_AUTO


# =============================================================================
# PerformanceMetrics Tests
# =============================================================================

class TestPerformanceMetrics:
    """Tests for PerformanceMetrics dataclass."""

    def test_default_metrics(self):
        """Test default metrics."""
        metrics = PerformanceMetrics()

        assert metrics.consecutive_successes == 0
        assert metrics.consecutive_errors == 0
        assert metrics.total_actions == 0

    def test_record_success(self):
        """Test recording success."""
        metrics = PerformanceMetrics()

        metrics.record_success()
        assert metrics.consecutive_successes == 1
        assert metrics.consecutive_errors == 0
        assert metrics.total_actions == 1

        metrics.record_success()
        assert metrics.consecutive_successes == 2

    def test_record_error(self):
        """Test recording error."""
        metrics = PerformanceMetrics()

        metrics.record_error()
        assert metrics.consecutive_errors == 1
        assert metrics.consecutive_successes == 0
        assert metrics.total_errors == 1

    def test_success_resets_errors(self):
        """Test that success resets error count."""
        metrics = PerformanceMetrics()

        metrics.record_error()
        metrics.record_error()
        assert metrics.consecutive_errors == 2

        metrics.record_success()
        assert metrics.consecutive_errors == 0
        assert metrics.consecutive_successes == 1

    def test_error_resets_successes(self):
        """Test that error resets success count."""
        metrics = PerformanceMetrics()

        metrics.record_success()
        metrics.record_success()
        assert metrics.consecutive_successes == 2

        metrics.record_error()
        assert metrics.consecutive_successes == 0
        assert metrics.consecutive_errors == 1

    def test_success_rate(self):
        """Test success rate calculation."""
        metrics = PerformanceMetrics()

        # No actions
        assert metrics.get_success_rate() == 1.0

        # All successes
        for _ in range(5):
            metrics.record_success()
        assert metrics.get_success_rate() == 1.0

        # Some errors
        for _ in range(5):
            metrics.record_error()
        assert metrics.get_success_rate() == 0.5

    def test_level_change_tracking(self):
        """Test level change tracking."""
        metrics = PerformanceMetrics()

        metrics.record_level_change(
            AutonomyLevel.EXECUTE_SAFE,
            AutonomyLevel.PLAN,
            "demotion test"
        )

        assert len(metrics.level_changes) == 1
        assert metrics.level_changes[0]["from_level"] == 3
        assert metrics.level_changes[0]["to_level"] == 2


# =============================================================================
# AutonomyManager Initialization Tests
# =============================================================================

class TestAutonomyManagerInit:
    """Tests for AutonomyManager initialization."""

    def test_create_manager(self, temp_project):
        """Test creating an AutonomyManager."""
        manager = AutonomyManager(temp_project)

        assert manager.project_dir == temp_project
        assert manager.current_level == AutonomyLevel.EXECUTE_SAFE

    def test_autonomy_dir_created(self, temp_project):
        """Test that .autonomy directory is created."""
        manager = AutonomyManager(temp_project)

        assert (temp_project / ".autonomy").exists()

    def test_custom_config(self, temp_project):
        """Test creating with custom config."""
        config = AutonomyConfig(level=AutonomyLevel.FULL_AUTO)
        manager = AutonomyManager(temp_project, config)

        assert manager.current_level == AutonomyLevel.FULL_AUTO

    def test_convenience_function(self, temp_project):
        """Test create_autonomy_manager function."""
        manager = create_autonomy_manager(
            temp_project,
            level=AutonomyLevel.PLAN,
            auto_adjust=False
        )

        assert isinstance(manager, AutonomyManager)
        assert manager.current_level == AutonomyLevel.PLAN
        assert manager.config.auto_adjust is False


# =============================================================================
# Action Checking Tests
# =============================================================================

class TestActionChecking:
    """Tests for action permission checking."""

    def test_read_always_allowed(self, manager):
        """Test that read operations are always allowed."""
        decision = manager.check_action("Read", {"file_path": "/test.py"})

        assert decision.allowed is True
        assert decision.required_level == AutonomyLevel.OBSERVE

    def test_write_requires_execute_safe(self, manager):
        """Test that write requires EXECUTE_SAFE."""
        decision = manager.check_action("Write", {"file_path": "/test.py"})

        assert decision.allowed is True  # Default level is EXECUTE_SAFE
        assert decision.required_level == AutonomyLevel.EXECUTE_SAFE

    def test_feature_mark_requires_review(self, temp_project):
        """Test that feature_mark requires EXECUTE_REVIEW."""
        config = AutonomyConfig(level=AutonomyLevel.EXECUTE_SAFE)
        manager = AutonomyManager(temp_project, config)

        decision = manager.check_action("feature_mark", {"index": 0})

        assert decision.allowed is False
        assert decision.required_level == AutonomyLevel.EXECUTE_REVIEW
        assert decision.requires_approval is True

    def test_feature_mark_allowed_at_review(self, elevated_manager):
        """Test feature_mark allowed at EXECUTE_REVIEW."""
        decision = elevated_manager.check_action("feature_mark", {"index": 0})

        assert decision.allowed is True

    def test_per_action_override(self, temp_project):
        """Test per-action level override."""
        config = AutonomyConfig(
            level=AutonomyLevel.PLAN,
            action_levels={"special_tool": AutonomyLevel.OBSERVE}
        )
        manager = AutonomyManager(temp_project, config)

        decision = manager.check_action("special_tool", {})

        assert decision.allowed is True
        assert decision.required_level == AutonomyLevel.OBSERVE

    def test_decision_has_alternatives(self, temp_project):
        """Test that denied actions have alternatives."""
        config = AutonomyConfig(level=AutonomyLevel.OBSERVE)
        manager = AutonomyManager(temp_project, config)

        decision = manager.check_action("Write", {"file_path": "/test.py"})

        assert decision.allowed is False
        assert len(decision.alternatives) > 0

    def test_decision_logged(self, manager, temp_project):
        """Test that decisions are logged."""
        manager.check_action("Read", {"file_path": "/test.py"})

        assert (temp_project / ".autonomy" / "decisions.jsonl").exists()


# =============================================================================
# Effective Level Tests
# =============================================================================

class TestEffectiveLevel:
    """Tests for effective level calculation."""

    def test_normal_confidence(self, manager):
        """Test effective level with normal confidence."""
        effective = manager.get_effective_level(confidence=0.8)

        assert effective == AutonomyLevel.EXECUTE_SAFE

    def test_low_confidence_reduces_level(self, manager):
        """Test that low confidence reduces level."""
        effective = manager.get_effective_level(confidence=0.3)

        assert effective < manager.current_level

    def test_very_low_confidence_reduces_more(self, elevated_manager):
        """Test very low confidence reduces level more."""
        effective = elevated_manager.get_effective_level(confidence=0.2)

        # Should reduce by more than 1 level
        assert effective <= AutonomyLevel.PLAN

    def test_level_never_below_minimum(self, temp_project):
        """Test that level doesn't go below minimum."""
        config = AutonomyConfig(
            level=AutonomyLevel.PLAN,
            min_level=AutonomyLevel.PLAN
        )
        manager = AutonomyManager(temp_project, config)

        effective = manager.get_effective_level(confidence=0.1)

        assert effective >= AutonomyLevel.PLAN


# =============================================================================
# Dynamic Adjustment Tests
# =============================================================================

class TestDynamicAdjustment:
    """Tests for dynamic level adjustment."""

    def test_demotion_on_errors(self, temp_project):
        """Test demotion after consecutive errors."""
        config = AutonomyConfig(
            level=AutonomyLevel.EXECUTE_SAFE,
            error_demotion_count=3
        )
        manager = AutonomyManager(temp_project, config)

        # Record errors
        for _ in range(3):
            manager.record_outcome(success=False)

        assert manager.current_level == AutonomyLevel.PLAN

    def test_promotion_on_successes(self, temp_project):
        """Test promotion after consecutive successes."""
        config = AutonomyConfig(
            level=AutonomyLevel.PLAN,
            success_promotion_count=5,
            max_level=AutonomyLevel.EXECUTE_SAFE
        )
        manager = AutonomyManager(temp_project, config)

        # Record successes
        for _ in range(5):
            manager.record_outcome(success=True)

        assert manager.current_level == AutonomyLevel.EXECUTE_SAFE

    def test_no_auto_adjust_when_disabled(self, temp_project):
        """Test no adjustment when auto_adjust is disabled."""
        config = AutonomyConfig(
            level=AutonomyLevel.EXECUTE_SAFE,
            auto_adjust=False,
            error_demotion_count=1
        )
        manager = AutonomyManager(temp_project, config)

        manager.record_outcome(success=False)

        assert manager.current_level == AutonomyLevel.EXECUTE_SAFE

    def test_level_never_exceeds_maximum(self, temp_project):
        """Test that level doesn't exceed maximum."""
        config = AutonomyConfig(
            level=AutonomyLevel.EXECUTE_REVIEW,
            success_promotion_count=1,
            max_level=AutonomyLevel.EXECUTE_REVIEW
        )
        manager = AutonomyManager(temp_project, config)

        manager.record_outcome(success=True)

        assert manager.current_level == AutonomyLevel.EXECUTE_REVIEW


# =============================================================================
# Level Setting Tests
# =============================================================================

class TestLevelSetting:
    """Tests for setting autonomy level."""

    def test_set_level(self, manager):
        """Test setting level."""
        manager.set_level(AutonomyLevel.FULL_AUTO, "test")

        assert manager.current_level == AutonomyLevel.FULL_AUTO

    def test_level_persisted(self, temp_project):
        """Test that level is persisted."""
        manager1 = AutonomyManager(temp_project)
        manager1.set_level(AutonomyLevel.PLAN, "test")

        manager2 = AutonomyManager(temp_project)
        assert manager2.current_level == AutonomyLevel.PLAN

    def test_level_change_tracked(self, manager):
        """Test that level changes are tracked."""
        manager.set_level(AutonomyLevel.OBSERVE, "test demotion")

        assert len(manager.metrics.level_changes) == 1


# =============================================================================
# Custom Checker Tests
# =============================================================================

class TestCustomChecker:
    """Tests for custom action checkers."""

    def test_register_checker(self, manager):
        """Test registering a custom checker."""
        def custom_checker(action_input):
            if action_input.get("dangerous"):
                return AutonomyLevel.FULL_AUTO
            return AutonomyLevel.OBSERVE

        manager.register_action_checker("custom_tool", custom_checker)

        # Safe action
        decision = manager.check_action("custom_tool", {"dangerous": False})
        assert decision.allowed is True

        # Dangerous action
        decision = manager.check_action("custom_tool", {"dangerous": True})
        assert decision.allowed is False


# =============================================================================
# Status and History Tests
# =============================================================================

class TestStatusAndHistory:
    """Tests for status and history retrieval."""

    def test_get_status(self, manager):
        """Test getting status."""
        status = manager.get_status()

        assert "configured_level" in status
        assert "effective_level" in status
        assert "performance" in status
        assert "thresholds" in status

    def test_get_decision_history(self, manager):
        """Test getting decision history."""
        manager.check_action("Read", {"file_path": "/a.py"})
        manager.check_action("Write", {"file_path": "/b.py"})

        history = manager.get_decision_history()

        assert len(history) == 2

    def test_filter_history_by_tool(self, manager):
        """Test filtering history by tool."""
        manager.check_action("Read", {"file_path": "/a.py"})
        manager.check_action("Write", {"file_path": "/b.py"})
        manager.check_action("Read", {"file_path": "/c.py"})

        history = manager.get_decision_history(tool="Read")

        assert len(history) == 2

    def test_filter_history_by_allowed(self, temp_project):
        """Test filtering history by allowed status."""
        config = AutonomyConfig(level=AutonomyLevel.OBSERVE)
        manager = AutonomyManager(temp_project, config)

        manager.check_action("Read", {})  # Allowed
        manager.check_action("Write", {})  # Denied

        allowed = manager.get_decision_history(allowed_only=True)
        denied = manager.get_decision_history(allowed_only=False)

        assert len(allowed) == 1
        assert len(denied) == 1


# =============================================================================
# Elevation Request Tests
# =============================================================================

class TestElevationRequest:
    """Tests for elevation requests."""

    def test_request_elevation(self, manager):
        """Test requesting elevation."""
        request = manager.request_elevation(
            AutonomyLevel.FULL_AUTO,
            "Need to perform critical operation",
            duration_actions=5
        )

        assert request["request_type"] == "autonomy_elevation"
        assert request["target_level"] == "FULL_AUTO"
        assert request["requires_approval"] is True


# =============================================================================
# Reset Tests
# =============================================================================

class TestReset:
    """Tests for reset functionality."""

    def test_reset_metrics(self, manager):
        """Test resetting metrics."""
        manager.record_outcome(success=True)
        manager.record_outcome(success=False)

        manager.reset_metrics()

        assert manager.metrics.total_actions == 0
        assert manager.metrics.consecutive_successes == 0
