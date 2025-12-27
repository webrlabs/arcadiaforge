"""
Failure Analysis Module for Autonomous Coding Framework
========================================================

Provides automated analysis of why runs fail, including pattern detection,
root cause analysis, and fix suggestions.

Storage: All data is persisted in the .arcadia/project.db SQLite database.

Usage:
    from arcadiaforge.failure_analysis import FailureAnalyzer

    analyzer = FailureAnalyzer(project_dir)

    # Analyze a failed session
    report = analyzer.analyze_session(session_id=5)

    # Get pattern matches
    patterns = analyzer.detect_patterns(session_id=5)

    # Find similar past failures
    similar = analyzer.find_similar_failures(error_message="...")
"""

import asyncio
import re
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from enum import Enum
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.models import FailureReportModel
from arcadiaforge.observability import Observability, EventType, Event


class FailureType(Enum):
    """Types of failures that can occur."""
    CYCLIC_ERROR = "cyclic_error"  # Same error repeated
    BLOCKED_COMMAND = "blocked_command"  # Security blocked action
    TOOL_ERROR = "tool_error"  # Tool execution failed
    TIMEOUT = "timeout"  # Operation timed out
    CRASH = "crash"  # Unexpected crash
    REGRESSION = "regression"  # Previously passing feature failed
    STUCK = "stuck"  # No progress being made
    ESCALATION = "escalation"  # Human escalation required
    UNKNOWN = "unknown"


class Severity(Enum):
    """Severity levels for failures."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class FailurePattern:
    """A detected failure pattern."""
    pattern_id: str
    pattern_type: str
    description: str
    occurrences: int = 1
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    affected_sessions: list = field(default_factory=list)
    affected_features: list = field(default_factory=list)
    signature: str = ""  # Hash for matching


@dataclass
class FailureReport:
    """A comprehensive failure report for a session."""
    session_id: int
    generated_at: str
    failure_type: str
    severity: int

    # Context
    last_successful_action: str = ""
    failing_action: str = ""
    error_messages: list = field(default_factory=list)

    # Analysis
    likely_cause: str = ""
    confidence: float = 0.0
    patterns_detected: list = field(default_factory=list)
    similar_past_failures: list = field(default_factory=list)

    # Recommendations
    suggested_fixes: list = field(default_factory=list)
    relevant_kb_entries: list = field(default_factory=list)

    # Timeline
    failure_timeline: list = field(default_factory=list)

    # Statistics
    error_count: int = 0
    tool_failures: int = 0
    blocked_actions: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class FailureSignature:
    """A normalized signature for matching similar failures."""
    error_types: list = field(default_factory=list)
    tool_sequence: list = field(default_factory=list)
    features_involved: list = field(default_factory=list)

    def compute_hash(self) -> str:
        """Compute a hash for this signature."""
        data = json.dumps({
            "error_types": sorted(self.error_types),
            "tool_sequence": self.tool_sequence[:5],
            "features": sorted(self.features_involved),
        }, sort_keys=True)
        return hashlib.md5(data.encode()).hexdigest()[:12]


class FailureAnalyzer:
    """
    Analyzes failures in autonomous coding runs.

    Provides pattern detection, root cause analysis, and fix suggestions.

    Storage: All reports are persisted in the .arcadia/project.db database.
    """

    def __init__(self, project_dir: Path):
        """
        Initialize the failure analyzer.

        Args:
            project_dir: Path to the project directory
        """
        self.project_dir = Path(project_dir)
        self.obs = Observability(project_dir)

        # Database session (set via set_session or init_async)
        self._db_session: Optional[AsyncSession] = None

        # Known patterns and their fixes
        self._known_patterns = self._load_known_patterns()

    def set_session(self, session: AsyncSession) -> None:
        """Set the database session for async operations."""
        self._db_session = session

    async def init_async(self, session: AsyncSession) -> None:
        """
        Initialize the analyzer asynchronously with a database session.
        """
        self._db_session = session

    def _load_known_patterns(self) -> dict:
        """Load known failure patterns and their fixes."""
        # These are built-in patterns based on common failure modes
        return {
            "repeated_same_error": {
                "description": "Same error message repeated multiple times",
                "suggested_fixes": [
                    "Try a different approach to solve the problem",
                    "Check if there's a prerequisite step missing",
                    "Consider if the feature is blocked by another issue",
                ],
            },
            "security_blocked": {
                "description": "Command blocked by security rules",
                "suggested_fixes": [
                    "Use allowed alternatives for the blocked command",
                    "Check security.py for allowed command patterns",
                    "Request human approval for sensitive operations",
                ],
            },
            "file_not_found": {
                "description": "File or directory not found",
                "suggested_fixes": [
                    "Verify the file path is correct",
                    "Check if the file was created by a previous step",
                    "List directory contents to find correct path",
                ],
            },
            "import_error": {
                "description": "Python import failed",
                "suggested_fixes": [
                    "Check if required package is installed",
                    "Verify module path and name",
                    "Check for circular imports",
                ],
            },
            "test_failure": {
                "description": "Test assertions failed",
                "suggested_fixes": [
                    "Review test output for specific assertion failure",
                    "Check if test data/fixtures are correct",
                    "Verify the implementation matches test expectations",
                ],
            },
            "timeout": {
                "description": "Operation timed out",
                "suggested_fixes": [
                    "Break down the operation into smaller steps",
                    "Check for infinite loops or blocking operations",
                    "Increase timeout if operation is legitimately slow",
                ],
            },
            "permission_denied": {
                "description": "Permission denied for operation",
                "suggested_fixes": [
                    "Check file/directory permissions",
                    "Run with appropriate privileges",
                    "Use allowed paths only",
                ],
            },
            "dependency_missing": {
                "description": "Required dependency not available",
                "suggested_fixes": [
                    "Install missing dependencies",
                    "Check package.json or requirements.txt",
                    "Verify version compatibility",
                ],
            },
        }

    def analyze_session(self, session_id: int) -> FailureReport:
        """
        Analyze a session for failures and generate a report.

        Args:
            session_id: The session to analyze

        Returns:
            FailureReport with analysis results
        """
        events = self.obs.get_session_events(session_id)

        if not events:
            return FailureReport(
                session_id=session_id,
                generated_at=datetime.now(timezone.utc).isoformat(),
                failure_type=FailureType.UNKNOWN.value,
                severity=Severity.LOW.value,
                likely_cause="No events found for session",
            )

        # Initialize report
        report = FailureReport(
            session_id=session_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            failure_type=FailureType.UNKNOWN.value,
            severity=Severity.LOW.value,
        )

        # Collect errors and context
        errors = []
        tool_failures = []
        blocked_actions = []
        last_successful_action = ""
        failing_action = ""

        for event in events:
            if event.event_type == EventType.ERROR.value:
                errors.append(event)
                report.error_count += 1
                failing_action = event.data.get("error_message", "")[:100]
                report.error_messages.append(failing_action)

            elif event.event_type == EventType.TOOL_ERROR.value:
                tool_failures.append(event)
                report.tool_failures += 1
                failing_action = f"Tool {event.tool_name}: {event.data.get('error_message', '')[:50]}"

            elif event.event_type == EventType.TOOL_BLOCKED.value:
                blocked_actions.append(event)
                report.blocked_actions += 1

            elif event.event_type == EventType.TOOL_RESULT.value:
                if event.data.get("success"):
                    last_successful_action = f"Tool {event.tool_name}"

        report.last_successful_action = last_successful_action
        report.failing_action = failing_action

        # Determine failure type and severity
        report.failure_type, report.severity, report.likely_cause, report.confidence = \
            self._determine_failure_type(events, errors, tool_failures, blocked_actions)

        # Detect patterns
        patterns = self.detect_patterns(session_id)
        report.patterns_detected = [asdict(p) for p in patterns]

        # Find similar past failures
        if report.error_messages:
            similar = self.find_similar_failures(report.error_messages[0], exclude_session=session_id)
            report.similar_past_failures = similar[:5]

        # Generate fix suggestions
        report.suggested_fixes = self._generate_fix_suggestions(
            report.failure_type, patterns, report.error_messages
        )

        # Build failure timeline
        report.failure_timeline = self._build_failure_timeline(events)

        # Save report
        self._save_report(report)

        return report

    def _determine_failure_type(
        self,
        events: list[Event],
        errors: list[Event],
        tool_failures: list[Event],
        blocked_actions: list[Event],
    ) -> tuple[str, int, str, float]:
        """
        Determine the type and severity of failure.

        Returns:
            (failure_type, severity, likely_cause, confidence)
        """
        # Check for cyclic errors
        if len(errors) >= 3:
            error_messages = [e.data.get("error_message", "") for e in errors]
            if len(set(error_messages)) <= 2:  # Same 1-2 errors repeated
                return (
                    FailureType.CYCLIC_ERROR.value,
                    Severity.HIGH.value,
                    f"Same error repeated {len(errors)} times",
                    0.9,
                )

        # Check for blocked commands
        if blocked_actions:
            return (
                FailureType.BLOCKED_COMMAND.value,
                Severity.MEDIUM.value,
                f"{len(blocked_actions)} actions blocked by security",
                0.95,
            )

        # Check for tool errors
        if tool_failures:
            # Analyze error messages for patterns
            error_msgs = [e.data.get("error_message", "") for e in tool_failures]

            for msg in error_msgs:
                msg_lower = msg.lower()
                if "timeout" in msg_lower:
                    return (
                        FailureType.TIMEOUT.value,
                        Severity.MEDIUM.value,
                        "Operation timed out",
                        0.8,
                    )
                if "permission denied" in msg_lower or "access denied" in msg_lower:
                    return (
                        FailureType.TOOL_ERROR.value,
                        Severity.HIGH.value,
                        "Permission denied",
                        0.85,
                    )
                if "not found" in msg_lower or "no such file" in msg_lower:
                    return (
                        FailureType.TOOL_ERROR.value,
                        Severity.MEDIUM.value,
                        "File or resource not found",
                        0.85,
                    )

            return (
                FailureType.TOOL_ERROR.value,
                Severity.MEDIUM.value,
                f"{len(tool_failures)} tool execution errors",
                0.7,
            )

        # Check for escalations
        escalations = [e for e in events if e.event_type == EventType.ESCALATION_TRIGGERED.value]
        if escalations:
            return (
                FailureType.ESCALATION.value,
                Severity.MEDIUM.value,
                "Human intervention required",
                0.95,
            )

        # Check for stuck state (no progress)
        feature_completed = any(e.event_type == EventType.FEATURE_COMPLETED.value for e in events)
        tool_calls = sum(1 for e in events if e.event_type == EventType.TOOL_CALL.value)

        if not feature_completed and tool_calls > 10:
            return (
                FailureType.STUCK.value,
                Severity.MEDIUM.value,
                "Many tool calls without completing features",
                0.6,
            )

        # Check if session ended with error status
        session_end = [e for e in events if e.event_type == EventType.SESSION_END.value]
        if session_end:
            status = session_end[-1].data.get("status", "")
            if status == "error":
                return (
                    FailureType.CRASH.value,
                    Severity.HIGH.value,
                    "Session ended with error status",
                    0.7,
                )

        # General errors
        if errors:
            return (
                FailureType.TOOL_ERROR.value,
                Severity.MEDIUM.value,
                f"{len(errors)} errors occurred",
                0.5,
            )

        return (
            FailureType.UNKNOWN.value,
            Severity.LOW.value,
            "No clear failure detected",
            0.3,
        )

    def detect_patterns(self, session_id: int = None) -> list[FailurePattern]:
        """
        Detect failure patterns in events.

        Args:
            session_id: Specific session to analyze (None for all)

        Returns:
            List of detected patterns
        """
        if session_id:
            events = self.obs.get_session_events(session_id)
        else:
            events = self.obs._load_all_events()

        patterns = []

        # Pattern 1: Repeated same error
        error_messages = [
            e.data.get("error_message", "")
            for e in events
            if e.event_type in [EventType.ERROR.value, EventType.TOOL_ERROR.value]
        ]

        error_counts = Counter(error_messages)
        for msg, count in error_counts.items():
            if count >= 2 and msg:
                pattern = FailurePattern(
                    pattern_id=hashlib.md5(msg.encode()).hexdigest()[:8],
                    pattern_type="repeated_same_error",
                    description=f"Error repeated {count} times: {msg[:50]}",
                    occurrences=count,
                    signature=hashlib.md5(msg.encode()).hexdigest()[:12],
                )
                patterns.append(pattern)

        # Pattern 2: Security blocked sequence
        blocked = [e for e in events if e.event_type == EventType.TOOL_BLOCKED.value]
        if len(blocked) >= 2:
            tools = [e.tool_name for e in blocked]
            pattern = FailurePattern(
                pattern_id=f"blocked-{len(blocked)}",
                pattern_type="security_blocked",
                description=f"{len(blocked)} commands blocked: {', '.join(set(tools))}",
                occurrences=len(blocked),
            )
            patterns.append(pattern)

        # Pattern 3: Tool failure after tool failure
        tool_errors = [e for e in events if e.event_type == EventType.TOOL_ERROR.value]
        if len(tool_errors) >= 3:
            tools = [e.tool_name for e in tool_errors]
            pattern = FailurePattern(
                pattern_id=f"tool-chain-{len(tool_errors)}",
                pattern_type="tool_error_chain",
                description=f"Chain of {len(tool_errors)} tool failures",
                occurrences=len(tool_errors),
            )
            patterns.append(pattern)

        # Pattern 4: Feature regression
        feature_events = [
            e for e in events
            if e.event_type in [
                EventType.FEATURE_COMPLETED.value,
                EventType.FEATURE_FAILED.value
            ]
        ]
        features_completed = set()
        features_failed_after = []

        for e in feature_events:
            if e.feature_index is not None:
                if e.event_type == EventType.FEATURE_COMPLETED.value:
                    features_completed.add(e.feature_index)
                elif e.event_type == EventType.FEATURE_FAILED.value:
                    if e.feature_index in features_completed:
                        features_failed_after.append(e.feature_index)

        if features_failed_after:
            pattern = FailurePattern(
                pattern_id=f"regression-{len(features_failed_after)}",
                pattern_type="regression",
                description=f"Features regressed: {features_failed_after}",
                occurrences=len(features_failed_after),
                affected_features=features_failed_after,
            )
            patterns.append(pattern)

        return patterns

    def find_similar_failures(
        self,
        error_message: str,
        exclude_session: int = None,
    ) -> list[dict]:
        """
        Find similar past failures based on error message.

        Args:
            error_message: The error to match
            exclude_session: Session to exclude from results

        Returns:
            List of similar failure contexts
        """
        all_events = self.obs._load_all_events()

        # Normalize error message for matching
        normalized = self._normalize_error(error_message)

        similar = []

        for event in all_events:
            if event.event_type in [EventType.ERROR.value, EventType.TOOL_ERROR.value]:
                if exclude_session and event.session_id == exclude_session:
                    continue

                event_error = event.data.get("error_message", "")
                if self._similarity_score(normalized, self._normalize_error(event_error)) > 0.7:
                    similar.append({
                        "session_id": event.session_id,
                        "timestamp": event.timestamp,
                        "error_message": event_error[:100],
                        "tool": event.tool_name,
                        "feature": event.feature_index,
                    })

        # Sort by recency
        similar.sort(key=lambda x: x["timestamp"], reverse=True)

        return similar

    def _normalize_error(self, error: str) -> str:
        """Normalize error message for comparison."""
        # Remove paths
        error = re.sub(r'[A-Za-z]:\\[^\s]+', '<PATH>', error)
        error = re.sub(r'/[^\s]+', '<PATH>', error)
        # Remove numbers
        error = re.sub(r'\b\d+\b', '<NUM>', error)
        # Remove UUIDs
        error = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '<UUID>', error)
        return error.lower().strip()

    def _similarity_score(self, a: str, b: str) -> float:
        """Calculate similarity between two strings."""
        if not a or not b:
            return 0.0

        # Simple token-based similarity
        tokens_a = set(a.split())
        tokens_b = set(b.split())

        if not tokens_a or not tokens_b:
            return 0.0

        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b

        return len(intersection) / len(union)

    def _generate_fix_suggestions(
        self,
        failure_type: str,
        patterns: list[FailurePattern],
        error_messages: list[str],
    ) -> list[str]:
        """Generate fix suggestions based on analysis."""
        suggestions = []

        # Add suggestions based on failure type
        if failure_type == FailureType.CYCLIC_ERROR.value:
            suggestions.extend([
                "The agent appears stuck in a loop. Try a different approach.",
                "Consider breaking down the task into smaller steps.",
                "Check if there's a prerequisite that's missing.",
            ])

        elif failure_type == FailureType.BLOCKED_COMMAND.value:
            suggestions.extend([
                "Review security.py for allowed command patterns.",
                "Use allowed alternatives for the blocked command.",
                "Request human approval for sensitive operations.",
            ])

        elif failure_type == FailureType.TIMEOUT.value:
            suggestions.extend([
                "Break the operation into smaller steps.",
                "Check for infinite loops or blocking calls.",
                "Consider if the timeout needs to be increased.",
            ])

        # Add suggestions based on patterns
        for pattern in patterns:
            if pattern.pattern_type in self._known_patterns:
                known = self._known_patterns[pattern.pattern_type]
                for fix in known["suggested_fixes"]:
                    if fix not in suggestions:
                        suggestions.append(fix)

        # Add suggestions based on error messages
        for msg in error_messages[:3]:
            msg_lower = msg.lower()

            if "import" in msg_lower:
                suggestions.append("Check if required module is installed and path is correct")
            if "assert" in msg_lower:
                suggestions.append("Review test expectations and actual implementation")
            if "syntax" in msg_lower:
                suggestions.append("Check for syntax errors in the code")
            if "connection" in msg_lower:
                suggestions.append("Verify network connectivity and service availability")

        # Deduplicate
        seen = set()
        unique_suggestions = []
        for s in suggestions:
            if s not in seen:
                seen.add(s)
                unique_suggestions.append(s)

        return unique_suggestions[:10]  # Limit to 10 suggestions

    def _build_failure_timeline(self, events: list[Event]) -> list[dict]:
        """Build a timeline of failure-related events."""
        timeline = []

        failure_types = [
            EventType.ERROR.value,
            EventType.TOOL_ERROR.value,
            EventType.TOOL_BLOCKED.value,
            EventType.FEATURE_FAILED.value,
            EventType.ESCALATION_TRIGGERED.value,
        ]

        for event in events:
            if event.event_type in failure_types:
                entry = {
                    "timestamp": event.timestamp,
                    "type": event.event_type,
                }
                if event.tool_name:
                    entry["tool"] = event.tool_name
                if event.feature_index is not None:
                    entry["feature"] = event.feature_index
                if event.data.get("error_message"):
                    entry["message"] = event.data["error_message"][:100]

                timeline.append(entry)

        return timeline

    # =========================================================================
    # Async Database Methods
    # =========================================================================

    async def _save_report_async(self, report: FailureReport) -> None:
        """Save a failure report to the database."""
        if self._db_session is None:
            return

        db_report = FailureReportModel(
            session_id=report.session_id,
            failure_type=report.failure_type,
            severity=report.severity,
            last_successful_action=report.last_successful_action,
            failing_action=report.failing_action,
            error_messages=report.error_messages,
            likely_cause=report.likely_cause,
            confidence=report.confidence,
            patterns_detected=report.patterns_detected,
            similar_past_failures=report.similar_past_failures,
            suggested_fixes=report.suggested_fixes,
            failure_timeline=report.failure_timeline,
            error_count=report.error_count,
            tool_failures=report.tool_failures,
            blocked_actions=report.blocked_actions,
        )
        self._db_session.add(db_report)
        await self._db_session.commit()

    async def get_report_async(self, session_id: int) -> Optional[FailureReport]:
        """
        Get an existing failure report for a session from the database.

        Args:
            session_id: The session to get report for

        Returns:
            FailureReport if found, None otherwise
        """
        if self._db_session is None:
            return None

        result = await self._db_session.execute(
            select(FailureReportModel)
            .where(FailureReportModel.session_id == session_id)
            .order_by(FailureReportModel.generated_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()

        if row:
            report = FailureReport(
                session_id=row.session_id,
                generated_at=row.generated_at.isoformat() if row.generated_at else "",
                failure_type=row.failure_type,
                severity=row.severity,
            )
            report.last_successful_action = row.last_successful_action or ""
            report.failing_action = row.failing_action or ""
            report.error_messages = row.error_messages or []
            report.likely_cause = row.likely_cause or ""
            report.confidence = row.confidence or 0.0
            report.patterns_detected = row.patterns_detected or []
            report.similar_past_failures = row.similar_past_failures or []
            report.suggested_fixes = row.suggested_fixes or []
            report.failure_timeline = row.failure_timeline or []
            report.error_count = row.error_count or 0
            report.tool_failures = row.tool_failures or 0
            report.blocked_actions = row.blocked_actions or 0
            return report

        return None

    async def get_all_reports_async(
        self,
        limit: int = 50,
        failure_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Get all failure reports from the database.

        Args:
            limit: Maximum number to return
            failure_type: Optional filter by failure type

        Returns:
            List of report summaries
        """
        if self._db_session is None:
            return []

        query = select(FailureReportModel).order_by(
            FailureReportModel.generated_at.desc()
        )

        if failure_type:
            query = query.where(FailureReportModel.failure_type == failure_type)

        query = query.limit(limit)

        result = await self._db_session.execute(query)
        rows = result.scalars().all()

        reports = []
        for row in rows:
            reports.append({
                "session_id": row.session_id,
                "generated_at": row.generated_at.isoformat() if row.generated_at else None,
                "failure_type": row.failure_type,
                "severity": row.severity,
                "likely_cause": row.likely_cause,
                "confidence": row.confidence,
                "error_count": row.error_count,
            })

        return reports

    # =========================================================================
    # Sync Wrappers (for backward compatibility)
    # =========================================================================

    def _save_report(self, report: FailureReport) -> None:
        """Save a failure report (sync wrapper)."""
        if self._db_session is not None:
            try:
                asyncio.get_running_loop()
                asyncio.create_task(self._save_report_async(report))
            except RuntimeError:
                asyncio.run(self._save_report_async(report))

    def get_report(self, session_id: int) -> Optional[FailureReport]:
        """
        Get an existing failure report for a session (sync wrapper).

        Args:
            session_id: The session to get report for

        Returns:
            FailureReport if found, None otherwise
        """
        if self._db_session is None:
            return None

        try:
            asyncio.get_running_loop()
            # In async context, return None - use get_report_async
            return None
        except RuntimeError:
            return asyncio.run(self.get_report_async(session_id))

    def format_report(self, report: FailureReport) -> str:
        """Format a failure report for display."""
        severity_names = {1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}

        lines = [
            "=" * 60,
            f"FAILURE REPORT - Session #{report.session_id}",
            "=" * 60,
            f"Generated: {report.generated_at[:19]}",
            f"Type:      {report.failure_type}",
            f"Severity:  {severity_names.get(report.severity, 'UNKNOWN')}",
            f"Confidence: {report.confidence:.0%}",
            "",
            "-" * 60,
            "ANALYSIS",
            "-" * 60,
            f"Likely Cause: {report.likely_cause}",
            "",
            f"Last Successful: {report.last_successful_action}",
            f"Failing Action:  {report.failing_action[:60]}",
            "",
            f"Errors: {report.error_count}  |  Tool Failures: {report.tool_failures}  |  Blocked: {report.blocked_actions}",
            "",
        ]

        if report.patterns_detected:
            lines.extend([
                "-" * 60,
                "PATTERNS DETECTED",
                "-" * 60,
            ])
            for p in report.patterns_detected[:5]:
                lines.append(f"  - {p['pattern_type']}: {p['description'][:50]}")
            lines.append("")

        if report.error_messages:
            lines.extend([
                "-" * 60,
                "ERROR MESSAGES",
                "-" * 60,
            ])
            for msg in report.error_messages[:5]:
                lines.append(f"  - {msg[:70]}")
            lines.append("")

        if report.suggested_fixes:
            lines.extend([
                "-" * 60,
                "SUGGESTED FIXES",
                "-" * 60,
            ])
            for i, fix in enumerate(report.suggested_fixes[:7], 1):
                lines.append(f"  {i}. {fix}")
            lines.append("")

        if report.similar_past_failures:
            lines.extend([
                "-" * 60,
                "SIMILAR PAST FAILURES",
                "-" * 60,
            ])
            for similar in report.similar_past_failures[:3]:
                lines.append(f"  Session #{similar['session_id']} ({similar['timestamp'][:10]})")
                lines.append(f"    {similar['error_message'][:50]}")
            lines.append("")

        lines.append("=" * 60)

        return "\n".join(lines)


# =============================================================================
# Convenience Functions
# =============================================================================

def create_failure_analyzer(project_dir: Path) -> FailureAnalyzer:
    """Create a FailureAnalyzer instance for a project."""
    return FailureAnalyzer(project_dir)


async def create_failure_analyzer_async(
    project_dir: Path,
    session: AsyncSession,
) -> FailureAnalyzer:
    """
    Create a FailureAnalyzer with async database initialization.

    Args:
        project_dir: Project directory
        session: Async database session

    Returns:
        Configured FailureAnalyzer with database connection
    """
    analyzer = FailureAnalyzer(project_dir)
    await analyzer.init_async(session)
    return analyzer


def analyze_session(project_dir: Path, session_id: int) -> FailureReport:
    """Analyze a session and return a failure report."""
    analyzer = FailureAnalyzer(project_dir)
    return analyzer.analyze_session(session_id)
