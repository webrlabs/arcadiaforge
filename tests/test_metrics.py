"""
Tests for Metrics Collection Module
====================================

Tests for the MetricsCollector class and related functionality.
"""

import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

from arcadiaforge.metrics import (
    MetricsCollector,
    FeatureMetrics,
    ToolMetrics,
    TimeMetrics,
    QualityMetrics,
    ComprehensiveMetrics,
    create_metrics_collector,
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
def obs(temp_project):
    """Create an Observability instance with test data."""
    obs = Observability(temp_project)
    return obs


@pytest.fixture
def collector(temp_project):
    """Create a MetricsCollector instance."""
    return MetricsCollector(temp_project)


@pytest.fixture
def populated_collector(temp_project):
    """Create a MetricsCollector with sample events."""
    obs = Observability(temp_project)

    # Session 1
    obs.start_session(1)
    obs.log_tool_call("Read", {"file_path": "/test.py"})
    obs.log_tool_result("Read", success=True, duration_ms=50)
    obs.log_tool_call("Write", {"file_path": "/test.py"})
    obs.log_tool_result("Write", success=True, duration_ms=100)
    obs.log_feature_event(EventType.FEATURE_STARTED, 0, "Test feature")
    obs.log_feature_event(EventType.FEATURE_COMPLETED, 0, "Test feature")
    obs.log_decision("feature_selection", "feature 0", confidence=0.9)
    obs.end_session(1, status="completed")

    # Session 2
    obs.start_session(2)
    obs.log_tool_call("Read", {"file_path": "/test2.py"})
    obs.log_tool_result("Read", success=True, duration_ms=60)
    obs.log_tool_call("Bash", {"command": "rm -rf /"})
    obs.log_tool_result("Bash", success=False, is_blocked=True)
    obs.log_feature_event(EventType.FEATURE_STARTED, 1, "Another feature")
    obs.log_feature_event(EventType.FEATURE_FAILED, 1, "Another feature")
    obs.log_error("Something went wrong", error_type="test_error")
    obs.end_session(2, status="error")

    return MetricsCollector(temp_project)


# =============================================================================
# MetricsCollector Initialization Tests
# =============================================================================

class TestMetricsCollectorInit:
    """Tests for MetricsCollector initialization."""

    def test_create_collector(self, temp_project):
        """Test creating a MetricsCollector."""
        collector = MetricsCollector(temp_project)

        assert collector.project_dir == temp_project
        assert collector.obs is not None

    def test_metrics_dir_created(self, temp_project):
        """Test that .metrics directory is created."""
        collector = MetricsCollector(temp_project)

        assert (temp_project / ".metrics").exists()

    def test_create_metrics_collector_function(self, temp_project):
        """Test convenience function."""
        collector = create_metrics_collector(temp_project)

        assert isinstance(collector, MetricsCollector)


# =============================================================================
# Comprehensive Metrics Tests
# =============================================================================

class TestComprehensiveMetrics:
    """Tests for comprehensive metrics collection."""

    def test_empty_project(self, collector):
        """Test metrics for empty project."""
        metrics = collector.get_comprehensive_metrics()

        assert metrics.sessions_total == 0
        assert metrics.sessions_completed == 0
        assert metrics.features_completed == 0

    def test_with_data(self, populated_collector):
        """Test metrics with actual data."""
        metrics = populated_collector.get_comprehensive_metrics()

        assert metrics.sessions_total == 2
        assert metrics.sessions_completed == 1
        assert metrics.features_completed == 1
        assert metrics.features_failed == 1

    def test_time_metrics(self, populated_collector):
        """Test time metrics."""
        metrics = populated_collector.get_comprehensive_metrics()

        assert isinstance(metrics.time_metrics, TimeMetrics)
        # Sessions should have some duration
        assert metrics.time_metrics.total_active_time_seconds >= 0

    def test_quality_metrics(self, populated_collector):
        """Test quality metrics."""
        metrics = populated_collector.get_comprehensive_metrics()

        assert isinstance(metrics.quality_metrics, QualityMetrics)
        assert metrics.quality_metrics.session_completion_rate == 0.5  # 1/2 sessions
        assert metrics.quality_metrics.total_decisions == 1

    def test_tool_metrics(self, populated_collector):
        """Test per-tool metrics."""
        metrics = populated_collector.get_comprehensive_metrics()

        assert "Read" in metrics.tool_metrics
        assert "Write" in metrics.tool_metrics
        assert "Bash" in metrics.tool_metrics

        read_metrics = metrics.tool_metrics["Read"]
        assert read_metrics["total_calls"] == 2
        assert read_metrics["successful_calls"] == 2

        bash_metrics = metrics.tool_metrics["Bash"]
        assert bash_metrics["blocked_calls"] == 1

    def test_feature_metrics(self, populated_collector):
        """Test per-feature metrics."""
        metrics = populated_collector.get_comprehensive_metrics()

        assert 0 in metrics.feature_metrics
        assert 1 in metrics.feature_metrics

        feature_0 = metrics.feature_metrics[0]
        assert feature_0["is_passing"] is True
        assert feature_0["successful_attempts"] == 1

        feature_1 = metrics.feature_metrics[1]
        assert feature_1["is_passing"] is False
        assert feature_1["failed_attempts"] == 1


# =============================================================================
# Time Metrics Tests
# =============================================================================

class TestTimeMetrics:
    """Tests for time metrics computation."""

    def test_session_duration(self, temp_project):
        """Test session duration calculation."""
        obs = Observability(temp_project)

        obs.start_session(1)
        obs.log_tool_call("Read", {})
        obs.end_session(1)

        collector = MetricsCollector(temp_project)
        metrics = collector.get_comprehensive_metrics()

        # Should have some duration
        assert metrics.time_metrics.total_active_time_seconds >= 0

    def test_multiple_sessions(self, populated_collector):
        """Test metrics across multiple sessions."""
        metrics = populated_collector.get_comprehensive_metrics()

        # Should have session-level data
        assert len(metrics.session_metrics) == 2


# =============================================================================
# Quality Metrics Tests
# =============================================================================

class TestQualityMetrics:
    """Tests for quality metrics computation."""

    def test_feature_success_rate(self, populated_collector):
        """Test feature success rate."""
        metrics = populated_collector.get_comprehensive_metrics()

        # 1 completed, 1 failed = 50% success rate
        assert metrics.quality_metrics.feature_success_rate == 0.5

    def test_decision_confidence(self, temp_project):
        """Test decision confidence tracking."""
        obs = Observability(temp_project)

        obs.start_session(1)
        obs.log_decision("test", "choice1", confidence=0.8)
        obs.log_decision("test", "choice2", confidence=0.4)  # Low confidence
        obs.log_decision("test", "choice3", confidence=0.9)
        obs.end_session(1)

        collector = MetricsCollector(temp_project)
        metrics = collector.get_comprehensive_metrics()

        assert metrics.quality_metrics.total_decisions == 3
        assert metrics.quality_metrics.low_confidence_decisions == 1  # 0.4 < 0.5
        assert 0.7 <= metrics.quality_metrics.avg_confidence <= 0.71


# =============================================================================
# Export Tests
# =============================================================================

class TestExport:
    """Tests for metrics export functionality."""

    def test_export_to_json(self, populated_collector, temp_project):
        """Test JSON export."""
        output_path = temp_project / "test_metrics.json"
        result_path = populated_collector.export_to_json(output_path)

        assert result_path == output_path
        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)

        assert "sessions_total" in data
        assert "time_metrics" in data
        assert "tool_metrics" in data

    def test_export_to_csv(self, populated_collector, temp_project):
        """Test CSV export."""
        output_path = temp_project / "test_sessions.csv"
        result_path = populated_collector.export_to_csv(output_path)

        assert result_path == output_path
        assert output_path.exists()

    def test_export_tool_metrics_csv(self, populated_collector, temp_project):
        """Test tool metrics CSV export."""
        result_path = populated_collector.export_tool_metrics_csv()

        assert result_path.exists()
        assert result_path.name == "tools.csv"


# =============================================================================
# Dashboard Tests
# =============================================================================

class TestDashboard:
    """Tests for dashboard generation."""

    def test_dashboard_output(self, populated_collector):
        """Test dashboard string output."""
        dashboard = populated_collector.get_dashboard()

        assert "METRICS DASHBOARD" in dashboard
        assert "SESSION METRICS" in dashboard
        assert "FEATURE METRICS" in dashboard
        assert "TOOL METRICS" in dashboard
        assert "TIME METRICS" in dashboard
        assert "QUALITY METRICS" in dashboard

    def test_session_summary(self, populated_collector):
        """Test session summary generation."""
        summary = populated_collector.get_session_summary(1)

        assert "Session #1" in summary
        assert "Tool Calls:" in summary
        assert "Features:" in summary


# =============================================================================
# FeatureMetrics Tests
# =============================================================================

class TestFeatureMetricsDataclass:
    """Tests for FeatureMetrics dataclass."""

    def test_default_values(self):
        """Test default values."""
        fm = FeatureMetrics(feature_index=0)

        assert fm.feature_index == 0
        assert fm.attempts == 0
        assert fm.successful_attempts == 0
        assert fm.is_passing is False

    def test_with_values(self):
        """Test with custom values."""
        fm = FeatureMetrics(
            feature_index=5,
            description="Test feature",
            attempts=3,
            successful_attempts=2,
            is_passing=True,
        )

        assert fm.feature_index == 5
        assert fm.attempts == 3
        assert fm.is_passing is True


# =============================================================================
# ToolMetrics Tests
# =============================================================================

class TestToolMetricsDataclass:
    """Tests for ToolMetrics dataclass."""

    def test_default_values(self):
        """Test default values."""
        tm = ToolMetrics(tool_name="Read")

        assert tm.tool_name == "Read"
        assert tm.total_calls == 0
        assert tm.error_rate == 0.0

    def test_with_values(self):
        """Test with custom values."""
        tm = ToolMetrics(
            tool_name="Write",
            total_calls=10,
            successful_calls=8,
            failed_calls=2,
            error_rate=0.2,
        )

        assert tm.total_calls == 10
        assert tm.error_rate == 0.2


# =============================================================================
# Edge Cases Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_no_events(self, collector):
        """Test with no events."""
        metrics = collector.get_comprehensive_metrics()

        assert metrics.sessions_total == 0
        assert metrics.quality_metrics.feature_success_rate == 0.0

    def test_only_session_start(self, temp_project):
        """Test with only session start, no end."""
        obs = Observability(temp_project)
        obs.start_session(1)

        collector = MetricsCollector(temp_project)
        metrics = collector.get_comprehensive_metrics()

        assert metrics.sessions_total == 1
        assert metrics.sessions_completed == 0

    def test_multiple_features_same_session(self, temp_project):
        """Test multiple features in same session."""
        obs = Observability(temp_project)

        obs.start_session(1)
        for i in range(5):
            obs.log_feature_event(EventType.FEATURE_STARTED, i, f"Feature {i}")
            if i % 2 == 0:
                obs.log_feature_event(EventType.FEATURE_COMPLETED, i, f"Feature {i}")
            else:
                obs.log_feature_event(EventType.FEATURE_FAILED, i, f"Feature {i}")
        obs.end_session(1)

        collector = MetricsCollector(temp_project)
        metrics = collector.get_comprehensive_metrics()

        assert metrics.features_completed == 3  # 0, 2, 4
        assert metrics.features_failed == 2  # 1, 3

    def test_high_volume_events(self, temp_project):
        """Test with many events."""
        obs = Observability(temp_project)

        obs.start_session(1)
        for i in range(100):
            obs.log_tool_call("Read", {"file": f"file{i}.py"})
            obs.log_tool_result("Read", success=True, duration_ms=10)
        obs.end_session(1)

        collector = MetricsCollector(temp_project)
        metrics = collector.get_comprehensive_metrics()

        assert metrics.tool_metrics["Read"]["total_calls"] == 100
        assert metrics.tool_metrics["Read"]["successful_calls"] == 100


# =============================================================================
# Duration Formatting Tests
# =============================================================================

class TestDurationFormatting:
    """Tests for duration formatting."""

    def test_format_seconds(self, collector):
        """Test formatting seconds."""
        assert collector._format_duration(30) == "30.0s"
        assert collector._format_duration(59.9) == "59.9s"

    def test_format_minutes(self, collector):
        """Test formatting minutes."""
        assert collector._format_duration(60) == "1.0m"
        assert collector._format_duration(150) == "2.5m"

    def test_format_hours(self, collector):
        """Test formatting hours."""
        assert collector._format_duration(3600) == "1.0h"
        assert collector._format_duration(7200) == "2.0h"
