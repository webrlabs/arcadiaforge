"""
Tests for Failure Analysis Module
==================================

Tests for the FailureAnalyzer class and related functionality.
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from arcadiaforge.failure_analysis import (
    FailureAnalyzer,
    FailureReport,
    FailurePattern,
    FailureSignature,
    FailureType,
    Severity,
    create_failure_analyzer,
    analyze_session,
)
from arcadiaforge.observability import Observability, EventType


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_project():
    """Create a temporary project directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def analyzer(temp_project):
    """Create a FailureAnalyzer instance."""
    return FailureAnalyzer(temp_project)


@pytest.fixture
def session_with_errors(temp_project):
    """Create a session with errors."""
    obs = Observability(temp_project)

    obs.start_session(1)
    obs.log_tool_call("Read", {"file_path": "/test.py"})
    obs.log_tool_result("Read", success=True, duration_ms=50)
    obs.log_error("File not found: /missing.py", error_type="file_error")
    obs.log_tool_call("Write", {"file_path": "/test.py"})
    obs.log_tool_result("Write", success=False, is_error=True, error_message="Permission denied")
    obs.log_feature_event(EventType.FEATURE_STARTED, 0, "Test feature")
    obs.log_feature_event(EventType.FEATURE_FAILED, 0, "Test feature")
    obs.end_session(1, status="error")

    return FailureAnalyzer(temp_project)


@pytest.fixture
def session_with_blocked(temp_project):
    """Create a session with blocked commands."""
    obs = Observability(temp_project)

    obs.start_session(1)
    obs.log_tool_call("Bash", {"command": "rm -rf /"})
    obs.log_tool_result("Bash", success=False, is_blocked=True, error_message="Command blocked")
    obs.log_tool_call("Bash", {"command": "sudo rm -rf /"})
    obs.log_tool_result("Bash", success=False, is_blocked=True, error_message="Command blocked")
    obs.end_session(1, status="error")

    return FailureAnalyzer(temp_project)


@pytest.fixture
def session_with_cyclic_errors(temp_project):
    """Create a session with cyclic errors."""
    obs = Observability(temp_project)

    obs.start_session(1)
    for i in range(5):
        obs.log_tool_call("Read", {"file": f"file{i}.py"})
        obs.log_error("Same error message", error_type="repeated_error")
    obs.end_session(1, status="error")

    return FailureAnalyzer(temp_project)


# =============================================================================
# FailureAnalyzer Initialization Tests
# =============================================================================

class TestFailureAnalyzerInit:
    """Tests for FailureAnalyzer initialization."""

    def test_create_analyzer(self, temp_project):
        """Test creating a FailureAnalyzer."""
        analyzer = FailureAnalyzer(temp_project)

        assert analyzer.project_dir == temp_project
        assert analyzer.obs is not None

    def test_reports_dir_created(self, temp_project):
        """Test that .failure_reports directory is created."""
        analyzer = FailureAnalyzer(temp_project)

        assert (temp_project / ".failure_reports").exists()

    def test_known_patterns_loaded(self, analyzer):
        """Test that known patterns are loaded."""
        assert "repeated_same_error" in analyzer._known_patterns
        assert "security_blocked" in analyzer._known_patterns
        assert "file_not_found" in analyzer._known_patterns

    def test_create_failure_analyzer_function(self, temp_project):
        """Test convenience function."""
        analyzer = create_failure_analyzer(temp_project)

        assert isinstance(analyzer, FailureAnalyzer)


# =============================================================================
# Failure Report Tests
# =============================================================================

class TestFailureReport:
    """Tests for FailureReport dataclass."""

    def test_default_values(self):
        """Test default values."""
        report = FailureReport(
            session_id=1,
            generated_at="2025-12-18T10:00:00Z",
            failure_type=FailureType.UNKNOWN.value,
            severity=Severity.LOW.value,
        )

        assert report.session_id == 1
        assert report.error_messages == []
        assert report.suggested_fixes == []
        assert report.confidence == 0.0

    def test_to_dict(self):
        """Test conversion to dictionary."""
        report = FailureReport(
            session_id=1,
            generated_at="2025-12-18T10:00:00Z",
            failure_type=FailureType.TOOL_ERROR.value,
            severity=Severity.HIGH.value,
            error_messages=["Error 1", "Error 2"],
        )

        data = report.to_dict()

        assert data["session_id"] == 1
        assert data["failure_type"] == "tool_error"
        assert len(data["error_messages"]) == 2


# =============================================================================
# Session Analysis Tests
# =============================================================================

class TestSessionAnalysis:
    """Tests for session analysis."""

    def test_analyze_empty_session(self, analyzer):
        """Test analyzing session with no events."""
        report = analyzer.analyze_session(999)

        assert report.session_id == 999
        assert report.failure_type == FailureType.UNKNOWN.value
        assert "No events" in report.likely_cause

    def test_analyze_session_with_errors(self, session_with_errors):
        """Test analyzing session with errors."""
        report = session_with_errors.analyze_session(1)

        assert report.session_id == 1
        assert report.error_count >= 1
        assert len(report.error_messages) >= 1
        assert report.severity >= Severity.MEDIUM.value

    def test_analyze_blocked_session(self, session_with_blocked):
        """Test analyzing session with blocked commands."""
        report = session_with_blocked.analyze_session(1)

        assert report.failure_type == FailureType.BLOCKED_COMMAND.value
        assert report.blocked_actions == 2
        assert report.confidence >= 0.9

    def test_analyze_cyclic_errors(self, session_with_cyclic_errors):
        """Test analyzing session with cyclic errors."""
        report = session_with_cyclic_errors.analyze_session(1)

        assert report.failure_type == FailureType.CYCLIC_ERROR.value
        assert report.severity == Severity.HIGH.value
        assert "repeated" in report.likely_cause.lower()


# =============================================================================
# Pattern Detection Tests
# =============================================================================

class TestPatternDetection:
    """Tests for failure pattern detection."""

    def test_detect_no_patterns(self, temp_project):
        """Test detecting patterns with no events."""
        analyzer = FailureAnalyzer(temp_project)
        patterns = analyzer.detect_patterns(session_id=1)

        assert patterns == []

    def test_detect_repeated_error_pattern(self, session_with_cyclic_errors):
        """Test detecting repeated error pattern."""
        patterns = session_with_cyclic_errors.detect_patterns(session_id=1)

        repeated_patterns = [p for p in patterns if p.pattern_type == "repeated_same_error"]
        assert len(repeated_patterns) >= 1
        assert repeated_patterns[0].occurrences >= 2

    def test_detect_blocked_pattern(self, session_with_blocked):
        """Test detecting security blocked pattern."""
        patterns = session_with_blocked.detect_patterns(session_id=1)

        blocked_patterns = [p for p in patterns if p.pattern_type == "security_blocked"]
        assert len(blocked_patterns) == 1
        assert blocked_patterns[0].occurrences == 2

    def test_detect_tool_error_chain(self, temp_project):
        """Test detecting chain of tool errors."""
        obs = Observability(temp_project)

        obs.start_session(1)
        for i in range(4):
            obs.log_tool_call("Tool", {})
            obs.log_tool_result("Tool", success=False, is_error=True, error_message=f"Error {i}")
        obs.end_session(1)

        analyzer = FailureAnalyzer(temp_project)
        patterns = analyzer.detect_patterns(session_id=1)

        chain_patterns = [p for p in patterns if p.pattern_type == "tool_error_chain"]
        assert len(chain_patterns) >= 1


# =============================================================================
# Failure Type Detection Tests
# =============================================================================

class TestFailureTypeDetection:
    """Tests for failure type determination."""

    def test_detect_timeout(self, temp_project):
        """Test detecting timeout failure."""
        obs = Observability(temp_project)

        obs.start_session(1)
        obs.log_tool_call("Bash", {"command": "long_running"})
        obs.log_tool_result("Bash", success=False, is_error=True, error_message="Timeout: operation took too long")
        obs.end_session(1)

        analyzer = FailureAnalyzer(temp_project)
        report = analyzer.analyze_session(1)

        assert report.failure_type == FailureType.TIMEOUT.value

    def test_detect_permission_denied(self, temp_project):
        """Test detecting permission denied failure."""
        obs = Observability(temp_project)

        obs.start_session(1)
        obs.log_tool_call("Write", {})
        obs.log_tool_result("Write", success=False, is_error=True, error_message="Permission denied")
        obs.end_session(1)

        analyzer = FailureAnalyzer(temp_project)
        report = analyzer.analyze_session(1)

        assert report.failure_type == FailureType.TOOL_ERROR.value
        assert "Permission" in report.likely_cause

    def test_detect_file_not_found(self, temp_project):
        """Test detecting file not found failure."""
        obs = Observability(temp_project)

        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.log_tool_result("Read", success=False, is_error=True, error_message="No such file or directory")
        obs.end_session(1)

        analyzer = FailureAnalyzer(temp_project)
        report = analyzer.analyze_session(1)

        assert "not found" in report.likely_cause.lower()

    def test_detect_escalation(self, temp_project):
        """Test detecting escalation failure."""
        obs = Observability(temp_project)

        obs.start_session(1)
        obs.log_event(EventType.ESCALATION_TRIGGERED, {"rule": "test_rule"})
        obs.end_session(1)

        analyzer = FailureAnalyzer(temp_project)
        report = analyzer.analyze_session(1)

        assert report.failure_type == FailureType.ESCALATION.value


# =============================================================================
# Similar Failures Tests
# =============================================================================

class TestSimilarFailures:
    """Tests for finding similar past failures."""

    def test_find_similar_no_history(self, analyzer):
        """Test finding similar with no history."""
        similar = analyzer.find_similar_failures("Some error message")

        assert similar == []

    def test_find_similar_with_history(self, temp_project):
        """Test finding similar with matching history."""
        obs = Observability(temp_project)

        # Create historical errors
        obs.start_session(1)
        obs.log_error("File not found: /path/to/file.py", error_type="file_error")
        obs.end_session(1)

        obs.start_session(2)
        obs.log_error("File not found: /other/path/to/file.py", error_type="file_error")
        obs.end_session(2)

        analyzer = FailureAnalyzer(temp_project)
        similar = analyzer.find_similar_failures(
            "File not found: /new/path/to/file.py",
            exclude_session=3
        )

        assert len(similar) >= 1

    def test_exclude_current_session(self, temp_project):
        """Test excluding current session from similar."""
        obs = Observability(temp_project)

        obs.start_session(1)
        obs.log_error("Same error", error_type="test")
        obs.end_session(1)

        analyzer = FailureAnalyzer(temp_project)
        similar = analyzer.find_similar_failures("Same error", exclude_session=1)

        assert len(similar) == 0


# =============================================================================
# Fix Suggestions Tests
# =============================================================================

class TestFixSuggestions:
    """Tests for fix suggestion generation."""

    def test_cyclic_error_suggestions(self, session_with_cyclic_errors):
        """Test suggestions for cyclic errors."""
        report = session_with_cyclic_errors.analyze_session(1)

        assert len(report.suggested_fixes) > 0
        # Should suggest trying a different approach
        suggestions_text = " ".join(report.suggested_fixes).lower()
        assert "different" in suggestions_text or "approach" in suggestions_text or "loop" in suggestions_text

    def test_blocked_command_suggestions(self, session_with_blocked):
        """Test suggestions for blocked commands."""
        report = session_with_blocked.analyze_session(1)

        assert len(report.suggested_fixes) > 0
        # Should mention security or allowed alternatives
        suggestions_text = " ".join(report.suggested_fixes).lower()
        assert "security" in suggestions_text or "allowed" in suggestions_text

    def test_import_error_suggestions(self, temp_project):
        """Test suggestions for import errors."""
        obs = Observability(temp_project)

        obs.start_session(1)
        obs.log_error("ImportError: No module named 'missing_module'", error_type="import_error")
        obs.end_session(1)

        analyzer = FailureAnalyzer(temp_project)
        report = analyzer.analyze_session(1)

        suggestions_text = " ".join(report.suggested_fixes).lower()
        assert "module" in suggestions_text or "install" in suggestions_text


# =============================================================================
# Failure Timeline Tests
# =============================================================================

class TestFailureTimeline:
    """Tests for failure timeline building."""

    def test_timeline_empty(self, analyzer):
        """Test timeline for session with no failures."""
        report = analyzer.analyze_session(999)

        assert report.failure_timeline == []

    def test_timeline_with_errors(self, session_with_errors):
        """Test timeline includes errors."""
        report = session_with_errors.analyze_session(1)

        assert len(report.failure_timeline) >= 1
        # Should have error events
        types = [e["type"] for e in report.failure_timeline]
        assert EventType.ERROR.value in types or EventType.TOOL_ERROR.value in types


# =============================================================================
# Report Formatting Tests
# =============================================================================

class TestReportFormatting:
    """Tests for report formatting."""

    def test_format_report(self, session_with_errors):
        """Test formatting a report."""
        report = session_with_errors.analyze_session(1)
        formatted = session_with_errors.format_report(report)

        assert "FAILURE REPORT" in formatted
        assert "Session #1" in formatted
        assert "ANALYSIS" in formatted
        # SUGGESTED FIXES section only appears if there are fixes
        assert "Likely Cause:" in formatted

    def test_format_includes_severity(self, session_with_errors):
        """Test that formatting includes severity."""
        report = session_with_errors.analyze_session(1)
        formatted = session_with_errors.format_report(report)

        assert "Severity:" in formatted


# =============================================================================
# Report Persistence Tests
# =============================================================================

class TestReportPersistence:
    """Tests for report saving and loading."""

    def test_report_saved(self, session_with_errors, temp_project):
        """Test that reports are saved."""
        session_with_errors.analyze_session(1)

        reports = list((temp_project / ".failure_reports").glob("failure_report_1_*.json"))
        assert len(reports) >= 1

    def test_get_saved_report(self, session_with_errors):
        """Test retrieving saved report."""
        session_with_errors.analyze_session(1)
        report = session_with_errors.get_report(1)

        assert report is not None
        assert report.session_id == 1


# =============================================================================
# Error Normalization Tests
# =============================================================================

class TestErrorNormalization:
    """Tests for error message normalization."""

    def test_normalize_paths(self, analyzer):
        """Test that paths are normalized."""
        normalized = analyzer._normalize_error("File not found: /home/user/file.py")

        # Normalization converts to lowercase
        assert "<path>" in normalized
        assert "/home/user" not in normalized

    def test_normalize_numbers(self, analyzer):
        """Test that numbers are normalized."""
        normalized = analyzer._normalize_error("Error at line 42: value was 123")

        # Normalization converts to lowercase
        assert "<num>" in normalized
        assert "42" not in normalized
        assert "123" not in normalized

    def test_similarity_score(self, analyzer):
        """Test similarity scoring."""
        score1 = analyzer._similarity_score("file not found", "file not found")
        assert score1 == 1.0

        score2 = analyzer._similarity_score("file not found", "directory not found")
        assert 0.3 < score2 < 0.8

        score3 = analyzer._similarity_score("completely different", "error message")
        assert score3 < 0.3


# =============================================================================
# Convenience Function Tests
# =============================================================================

class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_analyze_session_function(self, temp_project):
        """Test analyze_session convenience function."""
        obs = Observability(temp_project)
        obs.start_session(1)
        obs.log_error("Test error")
        obs.end_session(1)

        report = analyze_session(temp_project, 1)

        assert isinstance(report, FailureReport)
        assert report.session_id == 1


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_very_long_error_message(self, temp_project):
        """Test handling very long error messages."""
        obs = Observability(temp_project)

        obs.start_session(1)
        long_error = "Error: " + "x" * 5000
        obs.log_error(long_error)
        obs.end_session(1)

        analyzer = FailureAnalyzer(temp_project)
        report = analyzer.analyze_session(1)

        # Should not crash and should truncate appropriately
        assert report.session_id == 1

    def test_special_characters_in_error(self, temp_project):
        """Test handling special characters in errors."""
        obs = Observability(temp_project)

        obs.start_session(1)
        obs.log_error("Error with special chars: <>&\"'\\n\\t")
        obs.end_session(1)

        analyzer = FailureAnalyzer(temp_project)
        report = analyzer.analyze_session(1)

        assert report.session_id == 1

    def test_unicode_in_error(self, temp_project):
        """Test handling unicode in errors."""
        obs = Observability(temp_project)

        obs.start_session(1)
        obs.log_error("Error with unicode: \u2603 \u2764 \u00e9")
        obs.end_session(1)

        analyzer = FailureAnalyzer(temp_project)
        report = analyzer.analyze_session(1)

        assert report.session_id == 1
