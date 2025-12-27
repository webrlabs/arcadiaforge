"""
Tests for Risk Classification Module
=====================================

Tests for the RiskClassifier class and related functionality.
"""

import json
import pytest
import tempfile
from pathlib import Path

from arcadiaforge.risk import (
    RiskLevel,
    RiskAssessment,
    RiskPattern,
    RiskClassifier,
    assess_bash_risk,
    create_risk_classifier,
    DEFAULT_RISK_PATTERNS,
    DEFAULT_TOOL_RISKS,
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
def classifier(temp_project):
    """Create a RiskClassifier instance."""
    return RiskClassifier(temp_project)


# =============================================================================
# RiskLevel Tests
# =============================================================================

class TestRiskLevel:
    """Tests for RiskLevel enum."""

    def test_level_ordering(self):
        """Test that levels are properly ordered."""
        assert RiskLevel.MINIMAL < RiskLevel.LOW
        assert RiskLevel.LOW < RiskLevel.MODERATE
        assert RiskLevel.MODERATE < RiskLevel.HIGH
        assert RiskLevel.HIGH < RiskLevel.CRITICAL

    def test_level_values(self):
        """Test level integer values."""
        assert RiskLevel.MINIMAL == 1
        assert RiskLevel.CRITICAL == 5


# =============================================================================
# RiskAssessment Tests
# =============================================================================

class TestRiskAssessment:
    """Tests for RiskAssessment dataclass."""

    def test_create_assessment(self):
        """Test creating an assessment."""
        assessment = RiskAssessment(
            action="Write to test.py",
            tool="Write",
            input_summary="file_path=test.py",
            risk_level=RiskLevel.MODERATE,
            is_reversible=True,
            affects_source_of_truth=False,
            has_external_side_effects=False,
        )

        assert assessment.risk_level == RiskLevel.MODERATE
        assert assessment.is_reversible is True

    def test_to_dict(self):
        """Test serialization to dict."""
        assessment = RiskAssessment(
            action="Test action",
            tool="Test",
            input_summary="test",
            risk_level=RiskLevel.HIGH,
            is_reversible=False,
            affects_source_of_truth=True,
            has_external_side_effects=True,
            concerns=["Concern 1", "Concern 2"],
            requires_approval=True,
        )

        data = assessment.to_dict()

        assert data["risk_level"] == 4
        assert data["risk_level_name"] == "HIGH"
        assert data["is_reversible"] is False
        assert len(data["concerns"]) == 2


# =============================================================================
# RiskPattern Tests
# =============================================================================

class TestRiskPattern:
    """Tests for RiskPattern dataclass."""

    def test_create_pattern(self):
        """Test creating a pattern."""
        pattern = RiskPattern(
            pattern_id="test_pattern",
            description="Test pattern",
            tool="Bash",
            input_pattern=r"rm\s+-rf",
            input_field="command",
            risk_level=RiskLevel.CRITICAL,
            is_reversible=False,
            requires_approval=True,
        )

        assert pattern.risk_level == RiskLevel.CRITICAL
        assert pattern.requires_approval is True


# =============================================================================
# RiskClassifier Initialization Tests
# =============================================================================

class TestRiskClassifierInit:
    """Tests for RiskClassifier initialization."""

    def test_create_classifier(self, temp_project):
        """Test creating a RiskClassifier."""
        classifier = RiskClassifier(temp_project)

        assert classifier.project_dir == temp_project
        assert len(classifier.patterns) > 0  # Has default patterns

    def test_risk_dir_created(self, temp_project):
        """Test that .risk directory is created."""
        classifier = RiskClassifier(temp_project)

        assert (temp_project / ".risk").exists()

    def test_default_patterns_loaded(self, classifier):
        """Test that default patterns are loaded."""
        # Check for some known patterns
        pattern_ids = [p.pattern_id for p in classifier.patterns]

        assert "feature_list_write" in pattern_ids
        assert "git_push" in pattern_ids
        assert "rm_recursive" in pattern_ids

    def test_convenience_function(self, temp_project):
        """Test create_risk_classifier function."""
        classifier = create_risk_classifier(temp_project)

        assert isinstance(classifier, RiskClassifier)


# =============================================================================
# Risk Assessment Tests
# =============================================================================

class TestRiskAssessmentMethods:
    """Tests for risk assessment methods."""

    def test_assess_read(self, classifier):
        """Test assessing read operations."""
        assessment = classifier.assess("Read", {"file_path": "/test.py"})

        assert assessment.risk_level == RiskLevel.MINIMAL
        assert assessment.is_reversible is True

    def test_assess_write(self, classifier):
        """Test assessing write operations."""
        assessment = classifier.assess("Write", {"file_path": "/test.py"})

        assert assessment.risk_level == RiskLevel.MODERATE

    def test_assess_feature_list_write(self, classifier):
        """Test assessing feature_list.json write."""
        assessment = classifier.assess("Write", {"file_path": "/project/feature_list.json"})

        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.affects_source_of_truth is True
        assert assessment.requires_checkpoint is True

    def test_assess_git_push(self, classifier):
        """Test assessing git push."""
        assessment = classifier.assess("Bash", {"command": "git push origin main"})

        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.has_external_side_effects is True
        assert assessment.requires_approval is True

    def test_assess_git_force_push(self, classifier):
        """Test assessing git force push."""
        assessment = classifier.assess("Bash", {"command": "git push --force origin main"})

        assert assessment.risk_level == RiskLevel.CRITICAL

    def test_assess_rm_recursive(self, classifier):
        """Test assessing rm -r."""
        assessment = classifier.assess("Bash", {"command": "rm -r /some/dir"})

        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.is_reversible is False

    def test_assess_npm_install(self, classifier):
        """Test assessing npm install."""
        assessment = classifier.assess("Bash", {"command": "npm install express"})

        assert assessment.risk_level == RiskLevel.MODERATE
        assert assessment.has_external_side_effects is True

    def test_assessment_logged(self, classifier, temp_project):
        """Test that assessments are logged."""
        classifier.assess("Read", {"file_path": "/test.py"})

        assert (temp_project / ".risk" / "assessments.jsonl").exists()


# =============================================================================
# Pattern Matching Tests
# =============================================================================

class TestPatternMatching:
    """Tests for pattern matching."""

    def test_multiple_patterns_match(self, classifier):
        """Test when multiple patterns match."""
        # rm -rf matches both rm_recursive and rm_force
        assessment = classifier.assess("Bash", {"command": "rm -rf /dir"})

        # Should use highest risk
        assert assessment.risk_level >= RiskLevel.HIGH
        assert len(assessment.concerns) >= 1

    def test_no_pattern_match_uses_default(self, classifier):
        """Test using default when no pattern matches."""
        assessment = classifier.assess("Bash", {"command": "echo hello"})

        assert assessment.risk_level == RiskLevel.MODERATE  # Default for Bash

    def test_env_file_pattern(self, classifier):
        """Test .env file pattern."""
        assessment = classifier.assess("Write", {"file_path": "/project/.env"})

        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_review is True


# =============================================================================
# Custom Pattern Tests
# =============================================================================

class TestCustomPatterns:
    """Tests for custom pattern management."""

    def test_add_pattern(self, classifier, temp_project):
        """Test adding a custom pattern."""
        pattern = RiskPattern(
            pattern_id="custom_test",
            description="Custom test pattern",
            tool="Bash",
            input_pattern=r"custom_command",
            input_field="command",
            risk_level=RiskLevel.CRITICAL,
        )

        classifier.add_pattern(pattern)

        # Should match new pattern
        assessment = classifier.assess("Bash", {"command": "custom_command --arg"})
        assert assessment.risk_level == RiskLevel.CRITICAL

    def test_custom_pattern_persisted(self, temp_project):
        """Test that custom patterns are persisted."""
        classifier1 = RiskClassifier(temp_project)
        pattern = RiskPattern(
            pattern_id="persistent_test",
            description="Persistent test",
            tool="Test",
            risk_level=RiskLevel.HIGH,
        )
        classifier1.add_pattern(pattern)

        classifier2 = RiskClassifier(temp_project)
        pattern_ids = [p.pattern_id for p in classifier2.patterns]
        assert "persistent_test" in pattern_ids


# =============================================================================
# Custom Rule Tests
# =============================================================================

class TestCustomRules:
    """Tests for custom risk assessment rules."""

    def test_register_rule(self, classifier):
        """Test registering a custom rule."""
        def custom_rule(action_input):
            if action_input.get("dangerous"):
                return RiskAssessment(
                    action="Dangerous operation",
                    tool="custom",
                    input_summary="dangerous=True",
                    risk_level=RiskLevel.CRITICAL,
                    is_reversible=False,
                    affects_source_of_truth=True,
                    has_external_side_effects=True,
                    requires_approval=True,
                )
            return RiskAssessment(
                action="Safe operation",
                tool="custom",
                input_summary="dangerous=False",
                risk_level=RiskLevel.MINIMAL,
                is_reversible=True,
                affects_source_of_truth=False,
                has_external_side_effects=False,
            )

        classifier.register_rule("custom_tool", custom_rule)

        # Test safe action
        assessment = classifier.assess("custom_tool", {"dangerous": False})
        assert assessment.risk_level == RiskLevel.MINIMAL

        # Test dangerous action
        assessment = classifier.assess("custom_tool", {"dangerous": True})
        assert assessment.risk_level == RiskLevel.CRITICAL


# =============================================================================
# assess_bash_risk Function Tests
# =============================================================================

class TestAssessBashRisk:
    """Tests for the assess_bash_risk function."""

    def test_simple_command(self):
        """Test assessing simple command."""
        assessment = assess_bash_risk("ls -la")

        assert assessment.risk_level == RiskLevel.MODERATE

    def test_rm_command(self):
        """Test assessing rm command."""
        assessment = assess_bash_risk("rm file.txt")

        assert assessment.risk_level == RiskLevel.MODERATE

    def test_rm_rf_command(self):
        """Test assessing rm -rf command."""
        assessment = assess_bash_risk("rm -rf /some/dir")

        assert assessment.risk_level == RiskLevel.CRITICAL
        assert "Destructive file deletion" in assessment.concerns

    def test_git_push(self):
        """Test assessing git push."""
        assessment = assess_bash_risk("git push origin main")

        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.has_external_side_effects is True

    def test_git_force_push(self):
        """Test assessing git force push."""
        assessment = assess_bash_risk("git push --force origin main")

        assert assessment.risk_level == RiskLevel.CRITICAL
        assert assessment.requires_approval is True

    def test_git_reset_hard(self):
        """Test assessing git reset --hard."""
        assessment = assess_bash_risk("git reset --hard HEAD~1")

        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.is_reversible is False

    def test_npm_install(self):
        """Test assessing npm install."""
        assessment = assess_bash_risk("npm install express")

        assert assessment.risk_level == RiskLevel.MODERATE
        assert assessment.has_external_side_effects is True

    def test_pip_install(self):
        """Test assessing pip install."""
        assessment = assess_bash_risk("pip install requests")

        assert assessment.risk_level == RiskLevel.MODERATE

    def test_database_drop(self):
        """Test assessing database drop."""
        assessment = assess_bash_risk("psql -c 'DROP TABLE users'")

        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_approval is True

    def test_sudo_command(self):
        """Test assessing sudo command."""
        assessment = assess_bash_risk("sudo apt-get update")

        assert assessment.risk_level == RiskLevel.HIGH
        assert assessment.requires_approval is True

    def test_curl_post(self):
        """Test assessing curl POST."""
        assessment = assess_bash_risk("curl -X POST https://api.example.com/data")

        assert assessment.has_external_side_effects is True


# =============================================================================
# History and Stats Tests
# =============================================================================

class TestHistoryAndStats:
    """Tests for history and statistics retrieval."""

    def test_get_assessment_history(self, classifier):
        """Test getting assessment history."""
        classifier.assess("Read", {"file_path": "/a.py"})
        classifier.assess("Write", {"file_path": "/b.py"})
        classifier.assess("Bash", {"command": "ls"})

        history = classifier.get_assessment_history()

        assert len(history) == 3

    def test_filter_history_by_tool(self, classifier):
        """Test filtering history by tool."""
        classifier.assess("Read", {"file_path": "/a.py"})
        classifier.assess("Write", {"file_path": "/b.py"})
        classifier.assess("Read", {"file_path": "/c.py"})

        history = classifier.get_assessment_history(tool="Read")

        assert len(history) == 2

    def test_filter_history_by_level(self, classifier):
        """Test filtering history by risk level."""
        classifier.assess("Read", {"file_path": "/a.py"})  # MINIMAL
        classifier.assess("Bash", {"command": "git push"})  # HIGH

        history = classifier.get_assessment_history(min_level=RiskLevel.HIGH)

        assert len(history) == 1
        assert history[0]["risk_level"] >= RiskLevel.HIGH

    def test_get_high_risk_summary(self, classifier):
        """Test getting high risk summary."""
        classifier.assess("Bash", {"command": "git push"})
        classifier.assess("Bash", {"command": "rm -rf /dir"})

        summary = classifier.get_high_risk_summary()

        assert summary["total_high_risk"] >= 2
        assert "Bash" in summary["by_tool"]

    def test_get_stats(self, classifier):
        """Test getting stats."""
        classifier.assess("Read", {})
        classifier.assess("Write", {})

        stats = classifier.get_stats()

        assert stats["total_assessments"] == 2
        assert "by_level" in stats


# =============================================================================
# Format Tests
# =============================================================================

class TestFormatting:
    """Tests for assessment formatting."""

    def test_format_assessment(self, classifier):
        """Test formatting an assessment."""
        assessment = classifier.assess("Bash", {"command": "git push --force"})
        formatted = classifier.format_assessment(assessment)

        assert "Risk Assessment:" in formatted
        assert "Risk Level:" in formatted
        assert "CRITICAL" in formatted or "HIGH" in formatted


# =============================================================================
# Default Tool Risks Tests
# =============================================================================

class TestDefaultToolRisks:
    """Tests for default tool risk levels."""

    def test_read_tools_minimal(self):
        """Test read tools have minimal risk."""
        assert DEFAULT_TOOL_RISKS["Read"] == RiskLevel.MINIMAL
        assert DEFAULT_TOOL_RISKS["Glob"] == RiskLevel.MINIMAL
        assert DEFAULT_TOOL_RISKS["Grep"] == RiskLevel.MINIMAL

    def test_write_tools_moderate(self):
        """Test write tools have moderate risk."""
        assert DEFAULT_TOOL_RISKS["Write"] == RiskLevel.MODERATE
        assert DEFAULT_TOOL_RISKS["Edit"] == RiskLevel.MODERATE

    def test_feature_tools(self):
        """Test feature tool risk levels."""
        assert DEFAULT_TOOL_RISKS["feature_list"] == RiskLevel.MINIMAL
        assert DEFAULT_TOOL_RISKS["feature_mark"] == RiskLevel.MODERATE
