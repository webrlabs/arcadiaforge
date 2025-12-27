"""
Metrics Collection Module for Autonomous Coding Framework
==========================================================

Provides comprehensive metrics collection, aggregation, and export capabilities.
Builds on the observability module to provide higher-level metrics analysis.

Usage:
    from arcadiaforge.metrics import MetricsCollector

    collector = MetricsCollector(project_dir)

    # Get comprehensive run metrics
    metrics = collector.get_comprehensive_metrics()

    # Export to various formats
    collector.export_to_json("metrics.json")
    collector.export_to_csv("metrics.csv")

    # Get formatted dashboard
    print(collector.get_dashboard())
"""

import csv
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from arcadiaforge.observability import (
    Observability,
    EventType,
    Event,
    SessionMetrics,
    RunMetrics,
)
from arcadiaforge.config import BudgetConfig


@dataclass
class FeatureMetrics:
    """Metrics for a specific feature."""
    feature_index: int
    description: str = ""

    # Attempt tracking
    attempts: int = 0
    successful_attempts: int = 0
    failed_attempts: int = 0

    # Time tracking
    first_attempted: Optional[str] = None
    last_attempted: Optional[str] = None
    total_time_seconds: float = 0.0
    avg_attempt_seconds: float = 0.0

    # Current status
    is_passing: bool = False
    completed_in_session: Optional[int] = None


@dataclass
class ToolMetrics:
    """Metrics for a specific tool."""
    tool_name: str

    # Call counts
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    blocked_calls: int = 0

    # Performance
    total_duration_ms: int = 0
    avg_duration_ms: float = 0.0
    max_duration_ms: int = 0
    min_duration_ms: int = 0

    # Error tracking
    error_rate: float = 0.0
    common_errors: list = field(default_factory=list)


@dataclass
class TimeMetrics:
    """Time-based metrics for a run."""
    # Duration
    total_run_duration_seconds: float = 0.0
    total_active_time_seconds: float = 0.0
    avg_session_duration_seconds: float = 0.0

    # Session timing
    longest_session_seconds: float = 0.0
    shortest_session_seconds: float = 0.0

    # Time distribution
    sessions_by_hour: dict = field(default_factory=dict)
    sessions_by_day: dict = field(default_factory=dict)


@dataclass
class QualityMetrics:
    """Quality and reliability metrics."""
    # Success rates
    feature_success_rate: float = 0.0
    tool_success_rate: float = 0.0
    session_completion_rate: float = 0.0

    # Error rates
    error_rate: float = 0.0
    blocked_rate: float = 0.0

    # Human interaction
    escalation_rate: float = 0.0
    intervention_rate: float = 0.0

    # Decisions
    total_decisions: int = 0
    low_confidence_decisions: int = 0
    avg_confidence: float = 0.0
    
    # Cost (from RunMetrics now)
    estimated_cost_usd: float = 0.0


@dataclass
class ComprehensiveMetrics:
    """Complete metrics for a run."""
    # Identification
    run_id: str
    project_dir: str
    computed_at: str

    # Core metrics (from RunMetrics)
    sessions_total: int = 0
    sessions_completed: int = 0
    features_completed: int = 0
    features_failed: int = 0

    # Enhanced metrics
    time_metrics: TimeMetrics = field(default_factory=TimeMetrics)
    quality_metrics: QualityMetrics = field(default_factory=QualityMetrics)

    # Per-entity metrics
    tool_metrics: dict = field(default_factory=dict)  # tool_name -> ToolMetrics
    feature_metrics: dict = field(default_factory=dict)  # feature_index -> FeatureMetrics
    session_metrics: dict = field(default_factory=dict)  # session_id -> SessionMetrics


class MetricsCollector:
    """
    Collects, aggregates, and exports metrics for autonomous coding runs.

    Provides higher-level metrics analysis beyond the basic observability module.
    """

    def __init__(self, project_dir: Path, budget_config: Optional[BudgetConfig] = None):
        """
        Initialize the metrics collector.

        Args:
            project_dir: Path to the project directory
            budget_config: Optional budget configuration
        """
        self.project_dir = Path(project_dir)
        self.obs = Observability(project_dir)
        # Export directory uses .arcadia/ (no separate .metrics/ directory needed)
        self._export_dir = self.project_dir / ".arcadia"
        self.budget_config = budget_config or BudgetConfig.from_env()

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost in USD."""
        input_cost = (input_tokens / 1000) * self.budget_config.input_cost_per_1k
        output_cost = (output_tokens / 1000) * self.budget_config.output_cost_per_1k
        return input_cost + output_cost

    def check_budget(self) -> tuple[bool, float, float]:
        """
        Check if budget is exceeded.
        
        Returns:
            (is_over_budget, current_cost, percent_used)
        """
        metrics = self.get_comprehensive_metrics()
        # The cost is already aggregated in RunMetrics which populates QualityMetrics (via our update below)
        # or we can access it directly from RunMetrics if we updated the flow.
        # Let's verify get_comprehensive_metrics implementation.
        # It calls get_run_metrics() which now includes total_estimated_cost_usd.
        
        cost = metrics.quality_metrics.estimated_cost_usd
        limit = self.budget_config.max_budget_usd
        
        is_over = cost > limit
        percent = (cost / limit) if limit > 0 else 0.0
        
        return is_over, cost, percent

    def get_comprehensive_metrics(self) -> ComprehensiveMetrics:
        """
        Compute comprehensive metrics for the entire run.

        Returns:
            ComprehensiveMetrics with all available metrics
        """
        run_metrics = self.obs.get_run_metrics()
        all_events = self.obs._load_all_events()

        metrics = ComprehensiveMetrics(
            run_id=run_metrics.run_id,
            project_dir=str(self.project_dir),
            computed_at=datetime.now(timezone.utc).isoformat(),
            sessions_total=run_metrics.sessions_total,
            sessions_completed=run_metrics.sessions_completed,
            features_completed=run_metrics.total_features_completed,
            features_failed=run_metrics.total_features_failed,
        )

        # Compute time metrics
        metrics.time_metrics = self._compute_time_metrics(all_events, run_metrics)

        # Compute quality metrics
        metrics.quality_metrics = self._compute_quality_metrics(all_events, run_metrics)

        # Compute per-tool metrics
        metrics.tool_metrics = self._compute_tool_metrics(all_events)

        # Compute per-feature metrics
        metrics.feature_metrics = self._compute_feature_metrics(all_events)

        # Include session metrics
        metrics.session_metrics = run_metrics.session_metrics

        return metrics

    def _compute_time_metrics(
        self,
        events: list[Event],
        run_metrics: RunMetrics
    ) -> TimeMetrics:
        """Compute time-based metrics."""
        time_metrics = TimeMetrics()

        if not events:
            return time_metrics

        # Sort events chronologically
        events.sort(key=lambda e: e.timestamp)

        # Total run duration
        if run_metrics.first_event_at and run_metrics.last_event_at:
            first = datetime.fromisoformat(run_metrics.first_event_at.replace('Z', '+00:00'))
            last = datetime.fromisoformat(run_metrics.last_event_at.replace('Z', '+00:00'))
            time_metrics.total_run_duration_seconds = (last - first).total_seconds()

        # Session durations
        session_durations = []
        sessions_by_hour = {}
        sessions_by_day = {}

        for sid, smetrics in run_metrics.session_metrics.items():
            duration = smetrics.get("duration_seconds", 0.0)
            if duration > 0:
                session_durations.append(duration)
                time_metrics.total_active_time_seconds += duration

            # Time distribution
            started_at = smetrics.get("started_at")
            if started_at:
                try:
                    dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                    hour = dt.hour
                    day = dt.strftime("%A")

                    sessions_by_hour[hour] = sessions_by_hour.get(hour, 0) + 1
                    sessions_by_day[day] = sessions_by_day.get(day, 0) + 1
                except (ValueError, AttributeError):
                    pass

        if session_durations:
            time_metrics.avg_session_duration_seconds = sum(session_durations) / len(session_durations)
            time_metrics.longest_session_seconds = max(session_durations)
            time_metrics.shortest_session_seconds = min(session_durations)

        time_metrics.sessions_by_hour = sessions_by_hour
        time_metrics.sessions_by_day = sessions_by_day

        return time_metrics

    def _compute_quality_metrics(
        self,
        events: list[Event],
        run_metrics: RunMetrics
    ) -> QualityMetrics:
        """Compute quality and reliability metrics."""
        quality = QualityMetrics()

        if not events:
            return quality

        # Feature success rate
        total_features = run_metrics.total_features_completed + run_metrics.total_features_failed
        if total_features > 0:
            quality.feature_success_rate = run_metrics.total_features_completed / total_features

        # Tool success rate
        total_tool_calls = run_metrics.total_tool_calls
        if total_tool_calls > 0:
            successful_tools = total_tool_calls - run_metrics.total_tool_errors - run_metrics.total_tool_blocked
            quality.tool_success_rate = successful_tools / total_tool_calls
            quality.error_rate = run_metrics.total_tool_errors / total_tool_calls
            quality.blocked_rate = run_metrics.total_tool_blocked / total_tool_calls

        # Session completion rate
        if run_metrics.sessions_total > 0:
            quality.session_completion_rate = run_metrics.sessions_completed / run_metrics.sessions_total

        # Human interaction metrics
        escalations = 0
        interventions = 0
        decisions = []

        for event in events:
            if event.event_type == EventType.ESCALATION_TRIGGERED.value:
                escalations += 1
            elif event.event_type == EventType.HUMAN_RESPONSE.value:
                interventions += 1
            elif event.event_type == EventType.DECISION.value:
                confidence = event.data.get("confidence", 1.0)
                decisions.append(confidence)

        if run_metrics.sessions_total > 0:
            quality.escalation_rate = escalations / run_metrics.sessions_total
            quality.intervention_rate = interventions / run_metrics.sessions_total

        # Decision metrics
        quality.total_decisions = len(decisions)
        if decisions:
            quality.avg_confidence = sum(decisions) / len(decisions)
            quality.low_confidence_decisions = sum(1 for c in decisions if c < 0.5)

        # Populate cost
        quality.estimated_cost_usd = run_metrics.total_estimated_cost_usd

        return quality

    def _compute_tool_metrics(self, events: list[Event]) -> dict[str, dict]:
        """Compute per-tool metrics."""
        tool_data: dict[str, ToolMetrics] = {}

        for event in events:
            if event.tool_name:
                if event.tool_name not in tool_data:
                    tool_data[event.tool_name] = ToolMetrics(tool_name=event.tool_name)

                tm = tool_data[event.tool_name]

                if event.event_type == EventType.TOOL_CALL.value:
                    tm.total_calls += 1

                elif event.event_type == EventType.TOOL_RESULT.value:
                    tm.successful_calls += 1
                    if event.duration_ms:
                        tm.total_duration_ms += event.duration_ms
                        if tm.max_duration_ms == 0 or event.duration_ms > tm.max_duration_ms:
                            tm.max_duration_ms = event.duration_ms
                        if tm.min_duration_ms == 0 or event.duration_ms < tm.min_duration_ms:
                            tm.min_duration_ms = event.duration_ms

                elif event.event_type == EventType.TOOL_ERROR.value:
                    tm.failed_calls += 1
                    error_msg = event.data.get("error_message", "")[:50]
                    if error_msg and error_msg not in tm.common_errors:
                        tm.common_errors.append(error_msg)
                        if len(tm.common_errors) > 5:
                            tm.common_errors = tm.common_errors[:5]

                elif event.event_type == EventType.TOOL_BLOCKED.value:
                    tm.blocked_calls += 1

        # Compute derived metrics
        for tm in tool_data.values():
            if tm.successful_calls > 0 and tm.total_duration_ms > 0:
                tm.avg_duration_ms = tm.total_duration_ms / tm.successful_calls
            if tm.total_calls > 0:
                tm.error_rate = (tm.failed_calls + tm.blocked_calls) / tm.total_calls

        # Convert to dicts for serialization
        return {name: asdict(tm) for name, tm in tool_data.items()}

    def _compute_feature_metrics(self, events: list[Event]) -> dict[int, dict]:
        """Compute per-feature metrics."""
        feature_data: dict[int, FeatureMetrics] = {}

        # Track feature start times for duration calculation
        feature_starts: dict[int, str] = {}

        for event in events:
            if event.feature_index is not None:
                idx = event.feature_index

                if idx not in feature_data:
                    feature_data[idx] = FeatureMetrics(feature_index=idx)

                fm = feature_data[idx]

                if event.event_type == EventType.FEATURE_STARTED.value:
                    fm.attempts += 1
                    feature_starts[idx] = event.timestamp
                    if not fm.first_attempted:
                        fm.first_attempted = event.timestamp
                    fm.last_attempted = event.timestamp
                    fm.description = event.data.get("description", "")[:100]

                elif event.event_type == EventType.FEATURE_COMPLETED.value:
                    fm.successful_attempts += 1
                    fm.is_passing = True
                    fm.completed_in_session = event.session_id

                    # Calculate duration
                    if idx in feature_starts:
                        try:
                            start = datetime.fromisoformat(feature_starts[idx].replace('Z', '+00:00'))
                            end = datetime.fromisoformat(event.timestamp.replace('Z', '+00:00'))
                            duration = (end - start).total_seconds()
                            fm.total_time_seconds += duration
                        except (ValueError, AttributeError):
                            pass

                elif event.event_type == EventType.FEATURE_FAILED.value:
                    fm.failed_attempts += 1

        # Compute averages
        for fm in feature_data.values():
            if fm.attempts > 0:
                fm.avg_attempt_seconds = fm.total_time_seconds / fm.attempts

        # Convert to dicts for serialization
        return {idx: asdict(fm) for idx, fm in feature_data.items()}

    # =========================================================================
    # Export Methods
    # =========================================================================

    def export_to_json(self, output_path: Path = None) -> Path:
        """
        Export comprehensive metrics to JSON.

        Args:
            output_path: Output file path (defaults to .metrics/metrics.json)

        Returns:
            Path to the exported file
        """
        output_path = Path(output_path) if output_path else self._export_dir / "metrics.json"
        metrics = self.get_comprehensive_metrics()

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(asdict(metrics), f, indent=2)

        return output_path

    def export_to_csv(self, output_path: Path = None) -> Path:
        """
        Export session metrics to CSV.

        Args:
            output_path: Output file path (defaults to .metrics/sessions.csv)

        Returns:
            Path to the exported file
        """
        output_path = Path(output_path) if output_path else self._export_dir / "sessions.csv"
        metrics = self.get_comprehensive_metrics()

        # Flatten session metrics for CSV
        rows = []
        for sid, smetrics in metrics.session_metrics.items():
            row = {"session_id": sid}
            row.update(smetrics)
            rows.append(row)

        if rows:
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

        return output_path

    def export_tool_metrics_csv(self, output_path: Path = None) -> Path:
        """
        Export tool metrics to CSV.

        Args:
            output_path: Output file path (defaults to .metrics/tools.csv)

        Returns:
            Path to the exported file
        """
        output_path = Path(output_path) if output_path else self._export_dir / "tools.csv"
        metrics = self.get_comprehensive_metrics()

        rows = list(metrics.tool_metrics.values())

        if rows:
            # Flatten common_errors list
            for row in rows:
                row["common_errors"] = "; ".join(row.get("common_errors", []))

            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

        return output_path

    # =========================================================================
    # Dashboard Methods
    # =========================================================================

    def get_dashboard(self) -> str:
        """
        Generate a formatted dashboard showing key metrics.

        Returns:
            Formatted string dashboard
        """
        metrics = self.get_comprehensive_metrics()

        lines = [
            "=" * 60,
            "METRICS DASHBOARD",
            "=" * 60,
            f"Run ID:     {metrics.run_id}",
            f"Project:    {metrics.project_dir}",
            f"Computed:   {metrics.computed_at[:19]}",
            "",
            "-" * 60,
            "SESSION METRICS",
            "-" * 60,
            f"  Total Sessions:       {metrics.sessions_total}",
            f"  Completed Sessions:   {metrics.sessions_completed}",
            f"  Completion Rate:      {metrics.quality_metrics.session_completion_rate:.1%}",
            "",
            "-" * 60,
            "FEATURE METRICS",
            "-" * 60,
            f"  Features Completed:   {metrics.features_completed}",
            f"  Features Failed:      {metrics.features_failed}",
            f"  Success Rate:         {metrics.quality_metrics.feature_success_rate:.1%}",
            "",
            "-" * 60,
            "TOOL METRICS",
            "-" * 60,
            f"  Total Tool Calls:     {sum(t.get('total_calls', 0) for t in metrics.tool_metrics.values())}",
            f"  Success Rate:         {metrics.quality_metrics.tool_success_rate:.1%}",
            f"  Error Rate:           {metrics.quality_metrics.error_rate:.1%}",
            f"  Blocked Rate:         {metrics.quality_metrics.blocked_rate:.1%}",
            "",
        ]

        # Top tools by usage
        if metrics.tool_metrics:
            lines.extend([
                "  Top Tools by Usage:",
            ])
            sorted_tools = sorted(
                metrics.tool_metrics.items(),
                key=lambda x: x[1].get("total_calls", 0),
                reverse=True
            )[:5]
            for name, tm in sorted_tools:
                calls = tm.get("total_calls", 0)
                success = tm.get("successful_calls", 0)
                rate = (success / calls * 100) if calls > 0 else 0
                lines.append(f"    {name}: {calls} calls ({rate:.0f}% success)")

        lines.extend([
            "",
            "-" * 60,
            "TIME METRICS",
            "-" * 60,
            f"  Total Run Duration:   {self._format_duration(metrics.time_metrics.total_run_duration_seconds)}",
            f"  Active Time:          {self._format_duration(metrics.time_metrics.total_active_time_seconds)}",
            f"  Avg Session:          {self._format_duration(metrics.time_metrics.avg_session_duration_seconds)}",
            f"  Longest Session:      {self._format_duration(metrics.time_metrics.longest_session_seconds)}",
            "",
            "-" * 60,
            "QUALITY METRICS",
            "-" * 60,
            f"  Decisions Made:       {metrics.quality_metrics.total_decisions}",
            f"  Avg Confidence:       {metrics.quality_metrics.avg_confidence:.1%}",
            f"  Low Confidence:       {metrics.quality_metrics.low_confidence_decisions}",
            f"  Escalations:          {int(metrics.quality_metrics.escalation_rate * metrics.sessions_total)}",
            f"  Interventions:        {int(metrics.quality_metrics.intervention_rate * metrics.sessions_total)}",
            "=" * 60,
        ])

        return "\n".join(lines)

    def get_session_summary(self, session_id: int) -> str:
        """
        Get a formatted summary for a specific session.

        Args:
            session_id: The session to summarize

        Returns:
            Formatted summary string
        """
        session_metrics = self.obs.get_session_metrics(session_id)

        lines = [
            f"Session #{session_id} Summary",
            "-" * 40,
            f"Started:      {session_metrics.started_at[:19] if session_metrics.started_at else 'N/A'}",
            f"Ended:        {session_metrics.ended_at[:19] if session_metrics.ended_at else 'N/A'}",
            f"Duration:     {self._format_duration(session_metrics.duration_seconds)}",
            "",
            "Tool Calls:",
            f"  Total:      {session_metrics.tool_calls_total}",
            f"  Successful: {session_metrics.tool_calls_successful}",
            f"  Failed:     {session_metrics.tool_calls_failed}",
            f"  Blocked:    {session_metrics.tool_calls_blocked}",
            "",
            "Features:",
            f"  Attempted:  {session_metrics.features_attempted}",
            f"  Completed:  {session_metrics.features_completed}",
            f"  Failed:     {session_metrics.features_failed}",
            "",
            "Issues:",
            f"  Errors:     {session_metrics.errors_total}",
            f"  Warnings:   {session_metrics.warnings_total}",
            f"  Escalations:{session_metrics.escalations}",
        ]

        return "\n".join(lines)

    def _format_duration(self, seconds: float) -> str:
        """Format seconds as human-readable duration."""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f}m"
        else:
            hours = seconds / 3600
            return f"{hours:.1f}h"


# =============================================================================
# Convenience Functions
# =============================================================================

def create_metrics_collector(project_dir: Path) -> MetricsCollector:
    """Create a MetricsCollector instance for a project."""
    return MetricsCollector(project_dir)
