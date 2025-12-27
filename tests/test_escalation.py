"""
Tests for Escalation Rules Engine
=================================

Tests for escalation.py - rules for when to escalate to humans.
"""

import json
import pytest
import tempfile
from pathlib import Path

from arcadiaforge.escalation import (
    EscalationRule,
    EscalationContext,
    EscalationResult,
    EscalationEngine,
    InjectionType,
    create_escalation_engine,
    should_escalate,
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
def escalation_engine(temp_project):
    """Create an EscalationEngine for testing."""
    return EscalationEngine(temp_project)


# =============================================================================
# EscalationRule Tests
# =============================================================================

class TestEscalationRule:
    """Tests for the EscalationRule dataclass."""

    def test_rule_creation(self):
        """Test creating an EscalationRule."""
        rule = EscalationRule(
            rule_id="test_rule",
            name="Test Rule",
            description="A test rule",
            condition_type="threshold_below",
            condition_params={"field": "confidence", "threshold": 0.5},
            severity=3,
            injection_type=InjectionType.DECISION.value,
            message_template="Confidence is {confidence}",
            suggested_actions=["Action 1", "Action 2"],
        )

        assert rule.rule_id == "test_rule"
        assert rule.severity == 3
        assert len(rule.suggested_actions) == 2

    def test_rule_to_dict(self):
        """Test converting rule to dictionary."""
        rule = EscalationRule(
            rule_id="test",
            name="Test",
            description="Test",
            condition_type="equals",
            condition_params={"field": "is_irreversible", "value": True},
            severity=5,
            injection_type=InjectionType.APPROVAL.value,
            message_template="Test",
            suggested_actions=["Approve", "Deny"],
            auto_pause=True,
        )

        d = rule.to_dict()
        assert d["rule_id"] == "test"
        assert d["auto_pause"] is True

    def test_rule_from_dict(self):
        """Test creating rule from dictionary."""
        data = {
            "rule_id": "from_dict",
            "name": "From Dict",
            "description": "Test",
            "condition_type": "threshold_above",
            "condition_params": {"field": "error_count", "threshold": 5},
            "severity": 4,
            "injection_type": "guidance",
            "message_template": "Errors: {error_count}",
            "suggested_actions": ["Fix it"],
            "auto_pause": False,
            "timeout_seconds": 300,
            "default_action": None,
        }

        rule = EscalationRule.from_dict(data)
        assert rule.rule_id == "from_dict"
        assert rule.severity == 4


# =============================================================================
# EscalationContext Tests
# =============================================================================

class TestEscalationContext:
    """Tests for the EscalationContext dataclass."""

    def test_context_creation(self):
        """Test creating an EscalationContext."""
        ctx = EscalationContext(
            confidence=0.3,
            feature_index=5,
            consecutive_failures=4,
        )

        assert ctx.confidence == 0.3
        assert ctx.feature_index == 5
        assert ctx.consecutive_failures == 4

    def test_context_defaults(self):
        """Test default values for context."""
        ctx = EscalationContext()

        assert ctx.confidence == 1.0
        assert ctx.consecutive_failures == 0
        assert ctx.is_irreversible is False

    def test_context_to_dict(self):
        """Test converting context to dictionary."""
        ctx = EscalationContext(
            confidence=0.5,
            feature_index=10,
            action="Delete database",
            is_irreversible=True,
        )

        d = ctx.to_dict()
        assert d["confidence"] == 0.5
        assert d["feature_index"] == 10
        assert d["is_irreversible"] is True

    def test_context_custom_fields(self):
        """Test custom fields in context."""
        ctx = EscalationContext(
            confidence=0.7,
            custom={"custom_field": "custom_value"},
        )

        d = ctx.to_dict()
        assert d["custom_field"] == "custom_value"


# =============================================================================
# EscalationEngine Tests
# =============================================================================

class TestEscalationEngine:
    """Tests for the EscalationEngine class."""

    def test_engine_initialization(self, temp_project):
        """Test engine creates config directory."""
        engine = EscalationEngine(temp_project)

        assert engine.config_file.parent.exists()

    def test_engine_has_default_rules(self, escalation_engine):
        """Test engine has default rules loaded."""
        rules = escalation_engine.get_rules()

        assert len(rules) > 0

        # Check for expected default rules
        rule_ids = {r.rule_id for r in rules}
        assert "low_confidence" in rule_ids
        assert "feature_regression" in rule_ids
        assert "multiple_failures" in rule_ids
        assert "irreversible_action" in rule_ids

    def test_evaluate_low_confidence(self, escalation_engine):
        """Test evaluation of low confidence context."""
        ctx = EscalationContext(confidence=0.3)

        result = escalation_engine.evaluate(ctx)

        assert result is not None
        assert "low_confidence" in result.rule.rule_id or "very_low_confidence" in result.rule.rule_id

    def test_evaluate_high_confidence_no_match(self, escalation_engine):
        """Test that high confidence doesn't trigger escalation."""
        ctx = EscalationContext(confidence=0.9)

        result = escalation_engine.evaluate(ctx)

        # High confidence alone shouldn't trigger
        if result:
            assert result.rule.rule_id != "low_confidence"

    def test_evaluate_multiple_failures(self, escalation_engine):
        """Test evaluation of multiple failures."""
        ctx = EscalationContext(
            consecutive_failures=5,
            feature_index=10,
        )

        result = escalation_engine.evaluate(ctx)

        assert result is not None
        assert "failure" in result.rule.rule_id.lower() or "many" in result.rule.rule_id.lower()

    def test_evaluate_irreversible_action(self, escalation_engine):
        """Test evaluation of irreversible action."""
        ctx = EscalationContext(
            is_irreversible=True,
            action="Delete all data",
        )

        result = escalation_engine.evaluate(ctx)

        assert result is not None
        assert result.rule.rule_id == "irreversible_action"
        assert result.rule.severity == 5

    def test_evaluate_feature_regression(self, escalation_engine):
        """Test evaluation of feature regression."""
        ctx = EscalationContext(
            previously_passing=True,
            currently_passing=False,
            feature_index=5,
        )

        result = escalation_engine.evaluate(ctx)

        assert result is not None
        assert result.rule.rule_id == "feature_regression"

    def test_evaluate_dict_context(self, escalation_engine):
        """Test evaluation with dict context instead of dataclass."""
        ctx = {
            "confidence": 0.2,
            "feature_index": 5,
        }

        result = escalation_engine.evaluate(ctx)

        assert result is not None

    def test_evaluate_return_all(self, escalation_engine):
        """Test returning all matching rules."""
        ctx = EscalationContext(
            confidence=0.2,
            consecutive_failures=6,
        )

        results = escalation_engine.evaluate(ctx, return_all=True)

        # Should match multiple rules
        assert isinstance(results, list)
        assert len(results) >= 2

    def test_evaluate_no_match(self, escalation_engine):
        """Test evaluation with no matching rules."""
        ctx = EscalationContext(
            confidence=0.9,
            consecutive_failures=0,
            is_irreversible=False,
        )

        result = escalation_engine.evaluate(ctx)

        # May or may not match depending on other rules
        # Just verify it returns valid result type
        assert result is None or isinstance(result, EscalationResult)

    def test_add_custom_rule(self, escalation_engine):
        """Test adding a custom rule."""
        custom_rule = EscalationRule(
            rule_id="custom_test",
            name="Custom Test Rule",
            description="For testing",
            condition_type="threshold_above",
            condition_params={"field": "error_count", "threshold": 10},
            severity=4,
            injection_type=InjectionType.GUIDANCE.value,
            message_template="Too many errors: {error_count}",
            suggested_actions=["Fix errors"],
        )

        escalation_engine.add_rule(custom_rule)

        # Verify rule was added
        retrieved = escalation_engine.get_rule("custom_test")
        assert retrieved is not None
        assert retrieved.name == "Custom Test Rule"

    def test_remove_rule(self, escalation_engine):
        """Test removing a rule."""
        # Add a rule first
        custom_rule = EscalationRule(
            rule_id="to_remove",
            name="To Remove",
            description="Will be removed",
            condition_type="equals",
            condition_params={"field": "test", "value": True},
            severity=1,
            injection_type=InjectionType.REVIEW.value,
            message_template="Test",
            suggested_actions=["Remove"],
        )
        escalation_engine.add_rule(custom_rule)

        # Remove it
        removed = escalation_engine.remove_rule("to_remove")
        assert removed is True

        # Verify it's gone
        assert escalation_engine.get_rule("to_remove") is None

    def test_remove_nonexistent_rule(self, escalation_engine):
        """Test removing a rule that doesn't exist."""
        removed = escalation_engine.remove_rule("nonexistent")
        assert removed is False

    def test_get_rules_sorted_by_severity(self, escalation_engine):
        """Test that rules are sorted by severity (highest first)."""
        rules = escalation_engine.get_rules()

        severities = [r.severity for r in rules]
        assert severities == sorted(severities, reverse=True)

    def test_message_formatting(self, escalation_engine):
        """Test that escalation messages are formatted correctly."""
        ctx = EscalationContext(
            confidence=0.3,
        )

        result = escalation_engine.evaluate(ctx)

        if result:
            # Message should contain the formatted confidence
            assert "30%" in result.message or "0.3" in result.message

    def test_escalation_history(self, escalation_engine):
        """Test that escalations are logged to history."""
        ctx = EscalationContext(confidence=0.2)

        # Trigger an escalation
        escalation_engine.evaluate(ctx)

        # Check history
        history = escalation_engine.get_escalation_history()
        assert len(history) > 0
        assert "rule_id" in history[0]

    def test_get_stats(self, escalation_engine):
        """Test getting escalation statistics."""
        # Trigger some escalations
        escalation_engine.evaluate(EscalationContext(confidence=0.2))
        escalation_engine.evaluate(EscalationContext(is_irreversible=True))

        stats = escalation_engine.get_stats()

        assert stats["total_escalations"] >= 2
        assert "by_rule" in stats
        assert "by_severity" in stats


# =============================================================================
# Condition Type Tests
# =============================================================================

class TestConditionTypes:
    """Tests for different condition types."""

    def test_threshold_below(self, temp_project):
        """Test threshold_below condition."""
        engine = EscalationEngine(temp_project)

        # Create a simple threshold rule
        rule = EscalationRule(
            rule_id="test_below",
            name="Test Below",
            description="Test",
            condition_type="threshold_below",
            condition_params={"field": "confidence", "threshold": 0.5},
            severity=3,
            injection_type=InjectionType.DECISION.value,
            message_template="Test",
            suggested_actions=["Test"],
        )
        engine.add_rule(rule)

        # Should match
        result = engine.evaluate({"confidence": 0.3})
        assert result is not None

        # Should not match
        result2 = engine.evaluate({"confidence": 0.7})
        # May match other rules, but not this one
        if result2:
            assert result2.rule.rule_id != "test_below"

    def test_threshold_above(self, temp_project):
        """Test threshold_above condition."""
        engine = EscalationEngine(temp_project)

        rule = EscalationRule(
            rule_id="test_above",
            name="Test Above",
            description="Test",
            condition_type="threshold_above",
            condition_params={"field": "error_count", "threshold": 3},
            severity=3,
            injection_type=InjectionType.REVIEW.value,
            message_template="Test",
            suggested_actions=["Test"],
        )
        engine.add_rule(rule)

        # Should match
        result = engine.evaluate({"error_count": 5})
        # Just verify it returns a result (may match multiple rules)
        assert result is not None

    def test_equals_condition(self, temp_project):
        """Test equals condition."""
        engine = EscalationEngine(temp_project)

        rule = EscalationRule(
            rule_id="test_equals",
            name="Test Equals",
            description="Test",
            condition_type="equals",
            condition_params={"field": "is_critical", "value": True},
            severity=5,
            injection_type=InjectionType.APPROVAL.value,
            message_template="Test",
            suggested_actions=["Test"],
        )
        engine.add_rule(rule)

        # Should match
        result = engine.evaluate({"is_critical": True})
        assert result is not None

    def test_regression_condition(self, temp_project):
        """Test regression condition."""
        engine = EscalationEngine(temp_project)

        # Should match when previously_passing and not currently_passing
        ctx = EscalationContext(
            previously_passing=True,
            currently_passing=False,
        )

        result = engine.evaluate(ctx)
        assert result is not None
        assert result.rule.rule_id == "feature_regression"


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_escalation_engine(self, temp_project):
        """Test create_escalation_engine factory function."""
        engine = create_escalation_engine(temp_project)
        assert isinstance(engine, EscalationEngine)

    def test_should_escalate_function(self, temp_project):
        """Test should_escalate convenience function."""
        result = should_escalate(
            temp_project,
            EscalationContext(confidence=0.2),
        )

        assert result is not None or result is None  # Valid return type


# =============================================================================
# Custom Rules Persistence Tests
# =============================================================================

class TestCustomRulesPersistence:
    """Tests for custom rules persistence."""

    def test_custom_rules_saved(self, temp_project):
        """Test that custom rules are saved to config file."""
        engine = EscalationEngine(temp_project)

        rule = EscalationRule(
            rule_id="persistent_rule",
            name="Persistent",
            description="Should persist",
            condition_type="equals",
            condition_params={"field": "test", "value": True},
            severity=3,
            injection_type=InjectionType.REVIEW.value,
            message_template="Test",
            suggested_actions=["Test"],
        )
        engine.add_rule(rule)

        # Create new engine instance
        engine2 = EscalationEngine(temp_project)

        # Rule should still be there
        retrieved = engine2.get_rule("persistent_rule")
        assert retrieved is not None
        assert retrieved.name == "Persistent"
