"""
Observability Module with Database Support (Database Only)
===========================================================

Provides event logging, metrics collection, and run reconstruction capabilities.
All events are stored in the SQLite database for efficient querying.
"""

import asyncio
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import uuid

from sqlalchemy import select, func
from arcadiaforge.db.models import Event as DBEvent, Session as DBSession
from arcadiaforge.db.connection import get_session_maker

class EventType(Enum):
    """Types of events that can be logged."""
    # Session lifecycle
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    SESSION_PAUSE = "session_pause"
    SESSION_RESUME = "session_resume"

    # Tool interactions
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_BLOCKED = "tool_blocked"
    TOOL_ERROR = "tool_error"

    # Decisions and progress
    DECISION = "decision"
    FEATURE_STARTED = "feature_started"
    FEATURE_COMPLETED = "feature_completed"
    FEATURE_FAILED = "feature_failed"
    FEATURE_SKIPPED = "feature_skipped"

    # Checkpoints and recovery
    CHECKPOINT_CREATED = "checkpoint_created"
    CHECKPOINT_RESTORED = "checkpoint_restored"
    ROLLBACK = "rollback"

    # Human interaction
    ESCALATION_TRIGGERED = "escalation_triggered"
    HUMAN_INJECTION = "human_injection"
    HUMAN_RESPONSE = "human_response"

    # Errors and issues
    ERROR = "error"
    WARNING = "warning"

    # Git operations
    GIT_COMMIT = "git_commit"
    GIT_STATUS_CHANGE = "git_status_change"

    # Usage and cost
    USAGE_REPORT = "usage_report"


@dataclass
class Event:
    """A single logged event."""
    event_id: str
    timestamp: str  # ISO format
    event_type: str
    session_id: int
    data: dict = field(default_factory=dict)

    # Optional context
    feature_index: Optional[int] = None
    tool_name: Optional[str] = None
    duration_ms: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "session_id": self.session_id,
            "data": self.data,
        }
        if self.feature_index is not None:
            result["feature_index"] = self.feature_index
        if self.tool_name is not None:
            result["tool_name"] = self.tool_name
        if self.duration_ms is not None:
            result["duration_ms"] = self.duration_ms
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        """Create Event from dictionary."""
        return cls(
            event_id=data["event_id"],
            timestamp=data["timestamp"],
            event_type=data["event_type"],
            session_id=data["session_id"],
            data=data.get("data", {}),
            feature_index=data.get("feature_index"),
            tool_name=data.get("tool_name"),
            duration_ms=data.get("duration_ms"),
        )


@dataclass
class SessionMetrics:
    """Metrics for a single session."""
    session_id: int
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_seconds: float = 0.0

    # Tool metrics
    tool_calls_total: int = 0
    tool_calls_successful: int = 0
    tool_calls_failed: int = 0
    tool_calls_blocked: int = 0

    # Feature metrics
    features_attempted: int = 0
    features_completed: int = 0
    features_failed: int = 0

    # Error metrics
    errors_total: int = 0
    warnings_total: int = 0

    # Human interaction
    escalations: int = 0
    human_interventions: int = 0

    # Usage and Cost
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class RunMetrics:
    """Aggregate metrics across all sessions."""
    run_id: str
    project_dir: str
    first_event_at: Optional[str] = None
    last_event_at: Optional[str] = None

    # Session counts
    sessions_total: int = 0
    sessions_completed: int = 0

    # Aggregate tool metrics
    total_tool_calls: int = 0
    total_tool_errors: int = 0
    total_tool_blocked: int = 0

    # Aggregate feature metrics
    total_features_completed: int = 0
    total_features_failed: int = 0

    # Aggregate Usage
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_estimated_cost_usd: float = 0.0

    # Per-session breakdown
    session_metrics: dict = field(default_factory=dict)


class Observability:
    """
    Event logging and observability for the autonomous coding framework (DB-backed).
    """

    def __init__(self, project_dir: Path):
        """Initialize observability for a project."""
        self.project_dir = Path(project_dir)

        # Generate run ID from project dir for consistency
        self.run_id = hashlib.md5(str(self.project_dir.resolve()).encode()).hexdigest()[:12]

        # Current session tracking
        self._current_session_id: Optional[int] = None
        self._session_start_time: Optional[datetime] = None

        # Ensure project directory exists
        self.project_dir.mkdir(parents=True, exist_ok=True)

    def log_event(
        self,
        event_type: EventType,
        data: dict = None,
        session_id: int = None,
        feature_index: int = None,
        tool_name: str = None,
        duration_ms: int = None,
    ) -> str:
        """Log an event to the database."""
        sid = session_id or self._current_session_id or 0
        event = Event(
            event_id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type.value if isinstance(event_type, EventType) else event_type,
            session_id=sid,
            data=data or {},
            feature_index=feature_index,
            tool_name=tool_name,
            duration_ms=duration_ms,
        )

        # Persist to DB (fire-and-forget if loop is running)
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._persist_event_to_db(event))
        except RuntimeError:
            # No running loop, skip for now
            pass

        return event.event_id

    async def _persist_event_to_db(self, event: Event) -> None:
        """Persist event to SQLite database asynchronously."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                # Merge feature_index/tool_name/duration into payload
                payload = event.data.copy()
                if event.feature_index is not None:
                    payload["feature_index"] = event.feature_index
                if event.tool_name is not None:
                    payload["tool_name"] = event.tool_name
                if event.duration_ms is not None:
                    payload["duration_ms"] = event.duration_ms

                db_event = DBEvent(
                    session_id=event.session_id,
                    timestamp=datetime.fromisoformat(event.timestamp),
                    type=event.event_type,
                    source="agent",
                    payload=payload
                )
                session.add(db_event)
                await session.commit()
        except Exception:
            # Silently fail to prevent crashing the agent
            pass

    def start_session(self, session_id: int) -> str:
        """Mark the start of a new session."""
        self._current_session_id = session_id
        self._session_start_time = datetime.now(timezone.utc)

        # Create session in DB
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._create_db_session(session_id))
        except RuntimeError:
            pass

        return self.log_event(
            EventType.SESSION_START,
            data={
                "session_id": session_id,
                "started_at": self._session_start_time.isoformat(),
            },
            session_id=session_id,
        )

    async def _create_db_session(self, session_id: int) -> None:
        """Create the session record in DB if it doesn't exist."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                # Check if exists
                stmt = select(DBSession).where(DBSession.id == session_id)
                result = await session.execute(stmt)
                existing = result.scalar_one_or_none()

                if not existing:
                    new_session = DBSession(
                        id=session_id,
                        status="running",
                        start_time=datetime.now(timezone.utc)
                    )
                    session.add(new_session)
                    await session.commit()
        except Exception:
            pass

    def end_session(
        self,
        session_id: int = None,
        status: str = "completed",
        reason: str = "",
        features_completed: list = None,
    ) -> str:
        """Mark the end of a session."""
        sid = session_id or self._current_session_id

        duration_seconds = 0.0
        if self._session_start_time:
            duration_seconds = (datetime.now(timezone.utc) - self._session_start_time).total_seconds()

        # Update DB session status
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._update_db_session_end(sid, status, duration_seconds))
        except RuntimeError:
            pass

        event_id = self.log_event(
            EventType.SESSION_END,
            data={
                "session_id": sid,
                "status": status,
                "reason": reason,
                "duration_seconds": duration_seconds,
                "features_completed": features_completed or [],
            },
            session_id=sid,
            duration_ms=int(duration_seconds * 1000),
        )

        # Reset session tracking
        self._current_session_id = None
        self._session_start_time = None

        return event_id

    async def _update_db_session_end(self, session_id: int, status: str, duration: float) -> None:
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = select(DBSession).where(DBSession.id == session_id)
                result = await session.execute(stmt)
                db_session = result.scalar_one_or_none()

                if db_session:
                    db_session.status = status
                    db_session.end_time = datetime.now(timezone.utc)
                    await session.commit()
        except Exception:
            pass

    def log_tool_call(
        self,
        tool_name: str,
        tool_input: dict,
        feature_index: int = None,
    ) -> str:
        """Log a tool call."""
        # Truncate large inputs for storage
        import json
        input_str = json.dumps(tool_input)
        if len(input_str) > 1000:
            truncated_input = {"_truncated": True, "_preview": input_str[:500]}
        else:
            truncated_input = tool_input

        return self.log_event(
            EventType.TOOL_CALL,
            data={"tool_input": truncated_input},
            tool_name=tool_name,
            feature_index=feature_index,
        )

    def log_tool_result(
        self,
        tool_name: str,
        success: bool,
        is_error: bool = False,
        is_blocked: bool = False,
        error_message: str = "",
        duration_ms: int = None,
    ) -> str:
        """Log the result of a tool call."""
        if is_blocked:
            event_type = EventType.TOOL_BLOCKED
        elif is_error:
            event_type = EventType.TOOL_ERROR
        else:
            event_type = EventType.TOOL_RESULT

        return self.log_event(
            event_type,
            data={
                "success": success,
                "is_error": is_error,
                "is_blocked": is_blocked,
                "error_message": error_message[:500] if error_message else "",
            },
            tool_name=tool_name,
            duration_ms=duration_ms,
        )

    def log_feature_event(
        self,
        event_type: EventType,
        feature_index: int,
        description: str = "",
        details: dict = None,
    ) -> str:
        """Log a feature-related event."""
        return self.log_event(
            event_type,
            data={
                "description": description[:200] if description else "",
                **(details or {}),
            },
            feature_index=feature_index,
        )

    def log_error(
        self,
        error_message: str,
        error_type: str = "unknown",
        stack_trace: str = "",
        context: dict = None,
    ) -> str:
        """Log an error event."""
        return self.log_event(
            EventType.ERROR,
            data={
                "error_message": error_message[:1000],
                "error_type": error_type,
                "stack_trace": stack_trace[:2000] if stack_trace else "",
                "context": context or {},
            },
        )

    def log_decision(
        self,
        decision_type: str,
        choice: str,
        alternatives: list = None,
        rationale: str = "",
        confidence: float = 1.0,
        feature_index: int = None,
    ) -> str:
        """Log a decision event."""
        return self.log_event(
            EventType.DECISION,
            data={
                "decision_type": decision_type,
                "choice": choice,
                "alternatives": alternatives or [],
                "rationale": rationale[:500] if rationale else "",
                "confidence": confidence,
            },
            feature_index=feature_index,
        )

    def log_git_commit(
        self,
        commit_hash: str,
        message: str,
        files_changed: int = 0,
    ) -> str:
        """Log a git commit event."""
        return self.log_event(
            EventType.GIT_COMMIT,
            data={
                "commit_hash": commit_hash,
                "message": message[:200],
                "files_changed": files_changed,
            },
        )

    # =========================================================================
    # Query Methods (Database)
    # =========================================================================

    async def get_events(
        self,
        session_id: int = None,
        event_type: EventType = None,
        feature_index: int = None,
        tool_name: str = None,
        since: datetime = None,
        until: datetime = None,
        limit: int = None,
    ) -> list[Event]:
        """Query events with optional filters from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = select(DBEvent).order_by(DBEvent.timestamp.desc())

                if session_id is not None:
                    stmt = stmt.where(DBEvent.session_id == session_id)
                if event_type is not None:
                    type_value = event_type.value if isinstance(event_type, EventType) else event_type
                    stmt = stmt.where(DBEvent.type == type_value)
                if since is not None:
                    stmt = stmt.where(DBEvent.timestamp >= since)
                if until is not None:
                    stmt = stmt.where(DBEvent.timestamp <= until)
                if limit is not None:
                    stmt = stmt.limit(limit)

                result = await session.execute(stmt)
                db_events = result.scalars().all()

                # Convert to Event objects and filter by payload fields
                events = []
                for db_event in db_events:
                    payload = db_event.payload or {}

                    # Filter by feature_index if specified
                    if feature_index is not None and payload.get("feature_index") != feature_index:
                        continue

                    # Filter by tool_name if specified
                    if tool_name is not None and payload.get("tool_name") != tool_name:
                        continue

                    event = Event(
                        event_id=str(db_event.id),
                        timestamp=db_event.timestamp.isoformat(),
                        event_type=db_event.type,
                        session_id=db_event.session_id,
                        data=payload,
                        feature_index=payload.get("feature_index"),
                        tool_name=payload.get("tool_name"),
                        duration_ms=payload.get("duration_ms"),
                    )
                    events.append(event)

                return events
        except Exception:
            return []

    async def get_run_metrics(self) -> RunMetrics:
        """Compute aggregate metrics across all sessions from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                # Get all events
                result = await session.execute(select(DBEvent).order_by(DBEvent.timestamp.asc()))
                all_events = result.scalars().all()

                metrics = RunMetrics(
                    run_id=self.run_id,
                    project_dir=str(self.project_dir),
                )

                if not all_events:
                    return metrics

                metrics.first_event_at = all_events[0].timestamp.isoformat()
                metrics.last_event_at = all_events[-1].timestamp.isoformat()

                # Find unique sessions
                session_ids = set(e.session_id for e in all_events if e.session_id > 0)
                metrics.sessions_total = len(session_ids)

                # Count events
                for event in all_events:
                    if event.type == EventType.SESSION_END.value:
                        if event.payload.get("status") == "completed":
                            metrics.sessions_completed += 1
                    elif event.type == EventType.TOOL_CALL.value:
                        metrics.total_tool_calls += 1
                    elif event.type == EventType.TOOL_ERROR.value:
                        metrics.total_tool_errors += 1
                    elif event.type == EventType.TOOL_BLOCKED.value:
                        metrics.total_tool_blocked += 1
                    elif event.type == EventType.FEATURE_COMPLETED.value:
                        metrics.total_features_completed += 1
                    elif event.type == EventType.FEATURE_FAILED.value:
                        metrics.total_features_failed += 1
                    elif event.type == EventType.USAGE_REPORT.value:
                        metrics.total_input_tokens += event.payload.get("input_tokens", 0)
                        metrics.total_output_tokens += event.payload.get("output_tokens", 0)
                        metrics.total_estimated_cost_usd += event.payload.get("estimated_cost_usd", 0.0)

                return metrics
        except Exception:
            return RunMetrics(
                run_id=self.run_id,
                project_dir=str(self.project_dir),
            )


# =============================================================================
# Convenience Functions
# =============================================================================

def create_observability(project_dir: Path) -> Observability:
    """Create an Observability instance for a project."""
    return Observability(project_dir)


def format_event_summary(event: Event) -> str:
    """Format an event as a human-readable string."""
    parts = [f"[{event.timestamp[:19]}]", f"{event.event_type}"]

    if event.tool_name:
        parts.append(f"tool={event.tool_name}")
    if event.feature_index is not None:
        parts.append(f"feature=#{event.feature_index}")
    if event.duration_ms:
        parts.append(f"({event.duration_ms}ms)")

    return " ".join(parts)


def format_metrics_summary(metrics: RunMetrics) -> str:
    """Format run metrics as a human-readable summary."""
    lines = [
        "=" * 50,
        "RUN METRICS SUMMARY",
        "=" * 50,
        f"Run ID:              {metrics.run_id}",
        f"Project:             {metrics.project_dir}",
        f"First event:         {metrics.first_event_at[:19] if metrics.first_event_at else 'N/A'}",
        f"Last event:          {metrics.last_event_at[:19] if metrics.last_event_at else 'N/A'}",
        "",
        f"Sessions:            {metrics.sessions_completed}/{metrics.sessions_total} completed",
        f"Tool calls:          {metrics.total_tool_calls} total",
        f"  - Errors:          {metrics.total_tool_errors}",
        f"  - Blocked:         {metrics.total_tool_blocked}",
        f"Features completed:  {metrics.total_features_completed}",
        f"Features failed:     {metrics.total_features_failed}",
        "",
        f"Usage:",
        f"  - Input tokens:    {metrics.total_input_tokens:,}",
        f"  - Output tokens:   {metrics.total_output_tokens:,}",
        f"  - Estimated Cost:  ${metrics.total_estimated_cost_usd:.2f}",
        "=" * 50,
    ]
    return "\n".join(lines)
