"""
Warm Memory - Recent Session Context
=====================================

Warm memory stores context from recent sessions (typically last 5).
It is:
- Preserved across sessions
- Contains summarized information from completed sessions
- Used to maintain continuity between sessions

All data is stored in the database (warm_memory, warm_memory_issues,
warm_memory_patterns tables).
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from sqlalchemy import select, update, delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.models import (
    WarmMemory as WarmMemoryModel,
    WarmMemoryIssue as WarmMemoryIssueModel,
    WarmMemoryPattern as WarmMemoryPatternModel,
)


@dataclass
class SessionSummary:
    """Summary of a completed session."""
    session_id: int
    started_at: str
    ended_at: str
    duration_seconds: float

    # Progress
    features_started: int
    features_completed: int
    features_regressed: int

    # Key events
    key_decisions: list[dict] = field(default_factory=list)
    errors_encountered: list[dict] = field(default_factory=list)
    errors_resolved: list[dict] = field(default_factory=list)

    # State at end
    last_feature_worked: Optional[int] = None
    last_checkpoint_id: Optional[str] = None
    ending_state: str = "completed"  # completed, paused, failed, interrupted

    # Learnings
    patterns_discovered: list[str] = field(default_factory=list)
    warnings_for_next: list[str] = field(default_factory=list)

    # Metrics
    tool_calls: int = 0
    escalations: int = 0
    human_interventions: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "features_started": self.features_started,
            "features_completed": self.features_completed,
            "features_regressed": self.features_regressed,
            "key_decisions": self.key_decisions,
            "errors_encountered": self.errors_encountered,
            "errors_resolved": self.errors_resolved,
            "last_feature_worked": self.last_feature_worked,
            "last_checkpoint_id": self.last_checkpoint_id,
            "ending_state": self.ending_state,
            "patterns_discovered": self.patterns_discovered,
            "warnings_for_next": self.warnings_for_next,
            "tool_calls": self.tool_calls,
            "escalations": self.escalations,
            "human_interventions": self.human_interventions,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionSummary":
        """Create from dictionary."""
        return cls(
            session_id=data.get("session_id", 0),
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at", ""),
            duration_seconds=data.get("duration_seconds", 0.0),
            features_started=data.get("features_started", 0),
            features_completed=data.get("features_completed", 0),
            features_regressed=data.get("features_regressed", 0),
            key_decisions=data.get("key_decisions", []),
            errors_encountered=data.get("errors_encountered", []),
            errors_resolved=data.get("errors_resolved", []),
            last_feature_worked=data.get("last_feature_worked"),
            last_checkpoint_id=data.get("last_checkpoint_id"),
            ending_state=data.get("ending_state", "completed"),
            patterns_discovered=data.get("patterns_discovered", []),
            warnings_for_next=data.get("warnings_for_next", []),
            tool_calls=data.get("tool_calls", 0),
            escalations=data.get("escalations", 0),
            human_interventions=data.get("human_interventions", 0),
        )

    def summary_text(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Session {self.session_id} ({self.ending_state})",
            f"  Duration: {self.duration_seconds / 60:.1f} minutes",
            f"  Features: {self.features_completed} completed, {self.features_regressed} regressed",
            f"  Errors: {len(self.errors_encountered)} encountered, {len(self.errors_resolved)} resolved",
        ]
        if self.warnings_for_next:
            lines.append(f"  Warnings: {len(self.warnings_for_next)}")
        return "\n".join(lines)


@dataclass
class UnresolvedIssue:
    """An issue that persists across sessions."""
    issue_id: str
    created_at: str
    last_updated: str
    issue_type: str  # "error", "decision", "blocker", "observation"
    description: str
    context: dict
    related_features: list[int] = field(default_factory=list)
    sessions_seen: list[int] = field(default_factory=list)
    priority: int = 3  # 1=critical, 5=low
    notes: list[str] = field(default_factory=list)
    resolution_attempts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "issue_id": self.issue_id,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "issue_type": self.issue_type,
            "description": self.description,
            "context": self.context,
            "related_features": self.related_features,
            "sessions_seen": self.sessions_seen,
            "priority": self.priority,
            "notes": self.notes,
            "resolution_attempts": self.resolution_attempts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UnresolvedIssue":
        """Create from dictionary."""
        return cls(
            issue_id=data.get("issue_id", ""),
            created_at=data.get("created_at", ""),
            last_updated=data.get("last_updated", ""),
            issue_type=data.get("issue_type", ""),
            description=data.get("description", ""),
            context=data.get("context", {}),
            related_features=data.get("related_features", []),
            sessions_seen=data.get("sessions_seen", []),
            priority=data.get("priority", 3),
            notes=data.get("notes", []),
            resolution_attempts=data.get("resolution_attempts", []),
        )


@dataclass
class ProvenPattern:
    """A pattern that has been proven to work."""
    pattern_id: str
    created_at: str
    pattern_type: str  # "fix", "approach", "workaround", "best_practice"
    problem: str
    solution: str
    context_keywords: list[str] = field(default_factory=list)
    success_count: int = 1
    sessions_used: list[int] = field(default_factory=list)
    confidence: float = 0.5

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "pattern_id": self.pattern_id,
            "created_at": self.created_at,
            "pattern_type": self.pattern_type,
            "problem": self.problem,
            "solution": self.solution,
            "context_keywords": self.context_keywords,
            "success_count": self.success_count,
            "sessions_used": self.sessions_used,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProvenPattern":
        """Create from dictionary."""
        return cls(
            pattern_id=data.get("pattern_id", ""),
            created_at=data.get("created_at", ""),
            pattern_type=data.get("pattern_type", ""),
            problem=data.get("problem", ""),
            solution=data.get("solution", ""),
            context_keywords=data.get("context_keywords", []),
            success_count=data.get("success_count", 1),
            sessions_used=data.get("sessions_used", []),
            confidence=data.get("confidence", 0.5),
        )


class WarmMemory:
    """
    Manages warm (recent sessions) memory.

    Warm memory is:
    - Preserved across sessions
    - Limited to recent N sessions (default 5)
    - Contains summarized, not raw, information

    Usage:
        warm = WarmMemory(project_dir)
        warm.load()

        # Add session summary after session end
        warm.add_session_summary(summary)

        # Query for patterns
        patterns = warm.find_patterns("authentication error")

        # Track persistent issues
        warm.add_unresolved_issue(issue)
    """

    MAX_SESSIONS: int = 5  # Keep last N sessions in warm storage

    def __init__(self, project_dir: Path):
        """
        Initialize warm memory.

        Args:
            project_dir: Project directory path
        """
        self.project_dir = Path(project_dir)

        # Database session (set via set_session or init_async)
        self._db_session: Optional[AsyncSession] = None

        # State (loaded from DB)
        self.summaries: dict[int, SessionSummary] = {}
        self.issues: dict[str, UnresolvedIssue] = {}
        self.patterns: dict[str, ProvenPattern] = {}

        # Sequence counters
        self._issue_seq = 1
        self._pattern_seq = 1

    def set_session(self, session: AsyncSession) -> None:
        """Set the database session for async operations."""
        self._db_session = session

    async def init_async(self, session: AsyncSession) -> None:
        """Initialize with async database session and load state."""
        self._db_session = session
        await self._load_all_async()

    # =========================================================================
    # Database Operations
    # =========================================================================

    async def _load_all_async(self) -> None:
        """Load all warm memory from database."""
        await self._load_summaries_async()
        await self._load_issues_async()
        await self._load_patterns_async()

    async def _load_summaries_async(self) -> None:
        """Load session summaries from database."""
        if not self._db_session:
            return

        self.summaries.clear()
        result = await self._db_session.execute(
            select(WarmMemoryModel).order_by(desc(WarmMemoryModel.session_id)).limit(self.MAX_SESSIONS)
        )
        rows = result.scalars().all()

        for row in rows:
            self.summaries[row.session_id] = SessionSummary(
                session_id=row.session_id,
                started_at=row.started_at.isoformat() if row.started_at else "",
                ended_at=row.ended_at.isoformat() if row.ended_at else "",
                duration_seconds=row.duration_seconds or 0.0,
                features_started=row.features_started or 0,
                features_completed=row.features_completed or 0,
                features_regressed=row.features_regressed or 0,
                key_decisions=row.key_decisions or [],
                errors_encountered=row.errors_encountered or [],
                errors_resolved=row.errors_resolved or [],
                last_feature_worked=row.last_feature_worked,
                last_checkpoint_id=row.last_checkpoint_id,
                ending_state=row.ending_state or "completed",
                patterns_discovered=row.patterns_discovered or [],
                warnings_for_next=row.warnings_for_next or [],
                tool_calls=row.tool_calls or 0,
                escalations=row.escalations or 0,
                human_interventions=row.human_interventions or 0,
            )

    async def _load_issues_async(self) -> None:
        """Load unresolved issues from database."""
        if not self._db_session:
            return

        self.issues.clear()
        result = await self._db_session.execute(select(WarmMemoryIssueModel))
        rows = result.scalars().all()

        for row in rows:
            self.issues[row.issue_id] = UnresolvedIssue(
                issue_id=row.issue_id,
                created_at=row.created_at.isoformat() if row.created_at else "",
                last_updated=row.created_at.isoformat() if row.created_at else "",
                issue_type=row.issue_type or "",
                description=row.description or "",
                context=row.context or {},
                related_features=row.related_features or [],
                sessions_seen=[row.created_session, row.last_seen_session] if row.last_seen_session else [row.created_session],
                priority=row.priority or 3,
                notes=[],
                resolution_attempts=row.attempted_solutions or [],
            )

        # Update sequence counter
        if self.issues:
            try:
                max_id = max(
                    int(i.issue_id.split("-")[-1])
                    for i in self.issues.values()
                    if "-" in i.issue_id
                )
                self._issue_seq = max_id + 1
            except ValueError:
                pass

    async def _load_patterns_async(self) -> None:
        """Load proven patterns from database."""
        if not self._db_session:
            return

        self.patterns.clear()
        result = await self._db_session.execute(select(WarmMemoryPatternModel))
        rows = result.scalars().all()

        for row in rows:
            self.patterns[row.pattern_id] = ProvenPattern(
                pattern_id=row.pattern_id,
                created_at=row.created_at.isoformat() if row.created_at else "",
                pattern_type=row.pattern_type or "",
                problem=row.pattern or "",
                solution=row.context or "",
                context_keywords=row.context_keywords or [],
                success_count=row.success_count or 1,
                sessions_used=row.source_sessions or [],
                confidence=row.confidence or 0.5,
            )

        # Update sequence counter
        if self.patterns:
            try:
                max_id = max(
                    int(p.pattern_id.split("-")[-1])
                    for p in self.patterns.values()
                    if "-" in p.pattern_id
                )
                self._pattern_seq = max_id + 1
            except ValueError:
                pass

    # =========================================================================
    # Saving
    # =========================================================================

    async def _save_summary_async(self, summary: SessionSummary) -> None:
        """Save a session summary to database."""
        if not self._db_session:
            return

        # Check if exists
        result = await self._db_session.execute(
            select(WarmMemoryModel).where(WarmMemoryModel.session_id == summary.session_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            await self._db_session.execute(
                update(WarmMemoryModel)
                .where(WarmMemoryModel.session_id == summary.session_id)
                .values(
                    started_at=datetime.fromisoformat(summary.started_at.replace('Z', '+00:00')) if summary.started_at else None,
                    ended_at=datetime.fromisoformat(summary.ended_at.replace('Z', '+00:00')) if summary.ended_at else None,
                    duration_seconds=summary.duration_seconds,
                    features_started=summary.features_started,
                    features_completed=summary.features_completed,
                    features_regressed=summary.features_regressed,
                    key_decisions=summary.key_decisions,
                    errors_encountered=summary.errors_encountered,
                    errors_resolved=summary.errors_resolved,
                    last_feature_worked=summary.last_feature_worked,
                    last_checkpoint_id=summary.last_checkpoint_id,
                    ending_state=summary.ending_state,
                    patterns_discovered=summary.patterns_discovered,
                    warnings_for_next=summary.warnings_for_next,
                    tool_calls=summary.tool_calls,
                    escalations=summary.escalations,
                    human_interventions=summary.human_interventions,
                )
            )
        else:
            db_model = WarmMemoryModel(
                session_id=summary.session_id,
                started_at=datetime.fromisoformat(summary.started_at.replace('Z', '+00:00')) if summary.started_at else None,
                ended_at=datetime.fromisoformat(summary.ended_at.replace('Z', '+00:00')) if summary.ended_at else None,
                duration_seconds=summary.duration_seconds,
                features_started=summary.features_started,
                features_completed=summary.features_completed,
                features_regressed=summary.features_regressed,
                key_decisions=summary.key_decisions,
                errors_encountered=summary.errors_encountered,
                errors_resolved=summary.errors_resolved,
                last_feature_worked=summary.last_feature_worked,
                last_checkpoint_id=summary.last_checkpoint_id,
                ending_state=summary.ending_state,
                patterns_discovered=summary.patterns_discovered,
                warnings_for_next=summary.warnings_for_next,
                tool_calls=summary.tool_calls,
                escalations=summary.escalations,
                human_interventions=summary.human_interventions,
            )
            self._db_session.add(db_model)

        await self._db_session.commit()

    def _save_summary(self, summary: SessionSummary) -> None:
        """Save a session summary (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._save_summary_async(summary))
        except RuntimeError:
            if self._db_session:
                asyncio.run(self._save_summary_async(summary))

    async def _save_issues_async(self) -> None:
        """Save all issues to database (full replace)."""
        if not self._db_session:
            return

        # For simplicity, update each issue individually
        for issue in self.issues.values():
            result = await self._db_session.execute(
                select(WarmMemoryIssueModel).where(WarmMemoryIssueModel.issue_id == issue.issue_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                await self._db_session.execute(
                    update(WarmMemoryIssueModel)
                    .where(WarmMemoryIssueModel.issue_id == issue.issue_id)
                    .values(
                        issue_type=issue.issue_type,
                        description=issue.description,
                        priority=issue.priority,
                        related_features=issue.related_features,
                        related_files=[],
                        context=issue.context,
                        attempted_solutions=issue.resolution_attempts,
                        last_seen_session=issue.sessions_seen[-1] if issue.sessions_seen else 0,
                        times_encountered=len(issue.sessions_seen),
                    )
                )
            else:
                db_model = WarmMemoryIssueModel(
                    issue_id=issue.issue_id,
                    created_session=issue.sessions_seen[0] if issue.sessions_seen else 0,
                    issue_type=issue.issue_type,
                    description=issue.description,
                    priority=issue.priority,
                    related_features=issue.related_features,
                    related_files=[],
                    context=issue.context,
                    attempted_solutions=issue.resolution_attempts,
                    last_seen_session=issue.sessions_seen[-1] if issue.sessions_seen else 0,
                    times_encountered=len(issue.sessions_seen),
                )
                self._db_session.add(db_model)

        await self._db_session.commit()

    def _save_issues(self) -> None:
        """Save issues (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._save_issues_async())
        except RuntimeError:
            if self._db_session:
                asyncio.run(self._save_issues_async())

    async def _save_patterns_async(self) -> None:
        """Save all patterns to database."""
        if not self._db_session:
            return

        for pattern in self.patterns.values():
            result = await self._db_session.execute(
                select(WarmMemoryPatternModel).where(WarmMemoryPatternModel.pattern_id == pattern.pattern_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                await self._db_session.execute(
                    update(WarmMemoryPatternModel)
                    .where(WarmMemoryPatternModel.pattern_id == pattern.pattern_id)
                    .values(
                        pattern_type=pattern.pattern_type,
                        pattern=pattern.problem,
                        context=pattern.solution,
                        success_count=pattern.success_count,
                        confidence=pattern.confidence,
                        context_keywords=pattern.context_keywords,
                        source_sessions=pattern.sessions_used,
                        last_used_session=pattern.sessions_used[-1] if pattern.sessions_used else None,
                    )
                )
            else:
                db_model = WarmMemoryPatternModel(
                    pattern_id=pattern.pattern_id,
                    created_session=pattern.sessions_used[0] if pattern.sessions_used else 0,
                    pattern_type=pattern.pattern_type,
                    pattern=pattern.problem,
                    context=pattern.solution,
                    success_count=pattern.success_count,
                    confidence=pattern.confidence,
                    context_keywords=pattern.context_keywords,
                    source_sessions=pattern.sessions_used,
                    last_used_session=pattern.sessions_used[-1] if pattern.sessions_used else None,
                )
                self._db_session.add(db_model)

        await self._db_session.commit()

    def _save_patterns(self) -> None:
        """Save patterns (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._save_patterns_async())
        except RuntimeError:
            if self._db_session:
                asyncio.run(self._save_patterns_async())

    # =========================================================================
    # Session Summaries
    # =========================================================================

    def add_session_summary(self, summary: SessionSummary) -> None:
        """
        Add a session summary.

        If we exceed MAX_SESSIONS, the oldest is promoted to cold storage.

        Args:
            summary: SessionSummary to add
        """
        self.summaries[summary.session_id] = summary
        self._save_summary(summary)

        # Prune old sessions if needed
        self._prune_old_sessions()

    async def _prune_old_sessions_async(self) -> None:
        """Remove oldest sessions beyond MAX_SESSIONS from database."""
        if not self._db_session:
            return

        if len(self.summaries) > self.MAX_SESSIONS:
            # Sort by session_id (older = lower)
            sorted_ids = sorted(self.summaries.keys())
            to_remove = sorted_ids[:-self.MAX_SESSIONS]

            for session_id in to_remove:
                # Delete from memory
                del self.summaries[session_id]
                # Delete from database
                await self._db_session.execute(
                    delete(WarmMemoryModel).where(WarmMemoryModel.session_id == session_id)
                )

            await self._db_session.commit()

    def _prune_old_sessions(self) -> None:
        """Remove oldest sessions (sync wrapper)."""
        if len(self.summaries) <= self.MAX_SESSIONS:
            return

        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._prune_old_sessions_async())
        except RuntimeError:
            if self._db_session:
                asyncio.run(self._prune_old_sessions_async())

    def get_session_summary(self, session_id: int) -> Optional[SessionSummary]:
        """Get a specific session summary."""
        return self.summaries.get(session_id)

    def get_recent_summaries(self, count: int = 5) -> list[SessionSummary]:
        """Get most recent session summaries."""
        sorted_ids = sorted(self.summaries.keys(), reverse=True)
        return [self.summaries[sid] for sid in sorted_ids[:count]]

    def get_last_session_summary(self) -> Optional[SessionSummary]:
        """Get the most recent session summary."""
        if not self.summaries:
            return None
        max_id = max(self.summaries.keys())
        return self.summaries[max_id]

    # =========================================================================
    # Unresolved Issues
    # =========================================================================

    def add_unresolved_issue(
        self,
        issue_type: str,
        description: str,
        context: Optional[dict] = None,
        related_features: Optional[list[int]] = None,
        session_id: Optional[int] = None,
        priority: int = 3,
    ) -> UnresolvedIssue:
        """
        Add an unresolved issue.

        Args:
            issue_type: Type of issue
            description: Description
            context: Additional context
            related_features: Related feature indices
            session_id: Session where issue was found
            priority: Priority (1=critical, 5=low)

        Returns:
            The created UnresolvedIssue
        """
        now = datetime.now(timezone.utc).isoformat()
        issue_id = f"ISSUE-{self._issue_seq}"
        self._issue_seq += 1

        issue = UnresolvedIssue(
            issue_id=issue_id,
            created_at=now,
            last_updated=now,
            issue_type=issue_type,
            description=description,
            context=context or {},
            related_features=related_features or [],
            sessions_seen=[session_id] if session_id else [],
            priority=priority,
        )

        self.issues[issue_id] = issue
        self._save_issues()
        return issue

    def update_issue(
        self,
        issue_id: str,
        session_id: Optional[int] = None,
        note: Optional[str] = None,
        resolution_attempt: Optional[dict] = None,
    ) -> bool:
        """
        Update an unresolved issue.

        Args:
            issue_id: Issue ID
            session_id: Session to add to sessions_seen
            note: Note to add
            resolution_attempt: Resolution attempt to record

        Returns:
            True if issue found and updated
        """
        if issue_id not in self.issues:
            return False

        issue = self.issues[issue_id]
        issue.last_updated = datetime.now(timezone.utc).isoformat()

        if session_id and session_id not in issue.sessions_seen:
            issue.sessions_seen.append(session_id)

        if note:
            issue.notes.append(note)

        if resolution_attempt:
            issue.resolution_attempts.append(resolution_attempt)

        self._save_issues()
        return True

    async def resolve_issue_async(self, issue_id: str) -> Optional[UnresolvedIssue]:
        """
        Mark an issue as resolved (removes from database).

        Args:
            issue_id: Issue ID

        Returns:
            The resolved issue, or None if not found
        """
        if issue_id not in self.issues:
            return None

        issue = self.issues.pop(issue_id)

        if self._db_session:
            await self._db_session.execute(
                delete(WarmMemoryIssueModel).where(WarmMemoryIssueModel.issue_id == issue_id)
            )
            await self._db_session.commit()

        return issue

    def resolve_issue(self, issue_id: str) -> Optional[UnresolvedIssue]:
        """Mark an issue as resolved (sync wrapper)."""
        if issue_id not in self.issues:
            return None

        try:
            loop = asyncio.get_running_loop()
            issue = self.issues.pop(issue_id)
            asyncio.create_task(self.resolve_issue_async(issue_id))
            return issue
        except RuntimeError:
            if self._db_session:
                return asyncio.run(self.resolve_issue_async(issue_id))
            else:
                return self.issues.pop(issue_id, None)

    def get_unresolved_issues(
        self,
        issue_type: Optional[str] = None,
        priority_max: Optional[int] = None,
    ) -> list[UnresolvedIssue]:
        """
        Get unresolved issues with optional filtering.

        Args:
            issue_type: Filter by type
            priority_max: Only issues with priority <= this

        Returns:
            List of matching issues
        """
        result = []
        for issue in self.issues.values():
            if issue_type and issue.issue_type != issue_type:
                continue
            if priority_max and issue.priority > priority_max:
                continue
            result.append(issue)

        # Sort by priority (lower = more important)
        result.sort(key=lambda i: i.priority)
        return result

    def get_high_priority_issues(self) -> list[UnresolvedIssue]:
        """Get critical and high priority issues (priority 1-2)."""
        return self.get_unresolved_issues(priority_max=2)

    # =========================================================================
    # Proven Patterns
    # =========================================================================

    def add_pattern(
        self,
        pattern_type: str,
        problem: str,
        solution: str,
        context_keywords: Optional[list[str]] = None,
        session_id: Optional[int] = None,
    ) -> ProvenPattern:
        """
        Add a proven pattern.

        Args:
            pattern_type: Type of pattern
            problem: Problem description
            solution: Solution that worked
            context_keywords: Keywords for matching
            session_id: Session where pattern was discovered

        Returns:
            The created ProvenPattern
        """
        pattern_id = f"PAT-{self._pattern_seq}"
        self._pattern_seq += 1

        pattern = ProvenPattern(
            pattern_id=pattern_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            pattern_type=pattern_type,
            problem=problem,
            solution=solution,
            context_keywords=context_keywords or [],
            sessions_used=[session_id] if session_id else [],
        )

        self.patterns[pattern_id] = pattern
        self._save_patterns()
        return pattern

    def record_pattern_success(
        self,
        pattern_id: str,
        session_id: int,
    ) -> bool:
        """
        Record successful use of a pattern.

        Args:
            pattern_id: Pattern ID
            session_id: Session where it was used

        Returns:
            True if pattern found and updated
        """
        if pattern_id not in self.patterns:
            return False

        pattern = self.patterns[pattern_id]
        pattern.success_count += 1
        if session_id not in pattern.sessions_used:
            pattern.sessions_used.append(session_id)

        # Increase confidence with more successes
        pattern.confidence = min(1.0, 0.5 + (pattern.success_count * 0.1))

        self._save_patterns()
        return True

    def find_patterns(
        self,
        query: str,
        min_confidence: float = 0.0,
    ) -> list[ProvenPattern]:
        """
        Find patterns matching a query.

        Args:
            query: Search query (matches problem, solution, keywords)
            min_confidence: Minimum confidence threshold

        Returns:
            List of matching patterns, sorted by confidence
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        matches = []
        for pattern in self.patterns.values():
            if pattern.confidence < min_confidence:
                continue

            # Check for matches
            text = f"{pattern.problem} {pattern.solution}".lower()
            keywords_lower = [k.lower() for k in pattern.context_keywords]

            # Score based on matches
            score = 0
            if query_lower in text:
                score += 2
            for word in query_words:
                if word in text:
                    score += 1
                if word in keywords_lower:
                    score += 1.5

            if score > 0:
                matches.append((pattern, score))

        # Sort by score * confidence
        matches.sort(key=lambda x: x[1] * x[0].confidence, reverse=True)
        return [m[0] for m in matches]

    def get_patterns_by_type(self, pattern_type: str) -> list[ProvenPattern]:
        """Get patterns of a specific type."""
        return [p for p in self.patterns.values() if p.pattern_type == pattern_type]

    # =========================================================================
    # Cross-Session Context
    # =========================================================================

    def get_continuity_context(self) -> dict:
        """
        Get context for session continuity.

        Returns information the agent should know at session start.

        Returns:
            Dictionary with continuity information
        """
        last_summary = self.get_last_session_summary()
        high_priority_issues = self.get_high_priority_issues()
        recent_warnings = []

        if last_summary:
            recent_warnings = last_summary.warnings_for_next

        return {
            "last_session": last_summary.to_dict() if last_summary else None,
            "unresolved_issues": [i.to_dict() for i in high_priority_issues],
            "warnings": recent_warnings,
            "sessions_in_memory": len(self.summaries),
            "patterns_available": len(self.patterns),
        }

    def get_context_for_prompt(self) -> str:
        """
        Generate context string for including in prompts.

        Returns:
            Formatted string with warm memory context
        """
        lines = []

        # Last session info
        last = self.get_last_session_summary()
        if last:
            lines.append(f"Last Session: #{last.session_id} ({last.ending_state})")
            if last.last_feature_worked is not None:
                lines.append(f"  Last feature: #{last.last_feature_worked}")
            if last.features_completed > 0:
                lines.append(f"  Completed: {last.features_completed} features")
            if last.warnings_for_next:
                lines.append(f"  Warnings: {', '.join(last.warnings_for_next[:3])}")

        # Unresolved issues
        issues = self.get_high_priority_issues()
        if issues:
            lines.append(f"\nUnresolved Issues: {len(issues)} high priority")
            for issue in issues[:3]:
                lines.append(f"  - [{issue.issue_type}] {issue.description[:50]}...")

        # Pattern count
        if self.patterns:
            lines.append(f"\nKnown Patterns: {len(self.patterns)} available")

        return "\n".join(lines) if lines else "No previous session context."

    # =========================================================================
    # Summary
    # =========================================================================

    def get_summary(self) -> dict:
        """Get summary of warm memory state."""
        return {
            "sessions_stored": len(self.summaries),
            "unresolved_issues": len(self.issues),
            "high_priority_issues": len(self.get_high_priority_issues()),
            "proven_patterns": len(self.patterns),
            "last_session_id": max(self.summaries.keys()) if self.summaries else None,
        }


# =============================================================================
# Factory Functions
# =============================================================================

def create_warm_memory(project_dir: Path) -> WarmMemory:
    """
    Create a new WarmMemory instance.

    Args:
        project_dir: Project directory path

    Returns:
        WarmMemory instance
    """
    return WarmMemory(project_dir)


async def create_warm_memory_async(
    project_dir: Path,
    session: AsyncSession,
) -> WarmMemory:
    """
    Create a WarmMemory with async database session.

    Args:
        project_dir: Path to project directory
        session: AsyncSession for database operations

    Returns:
        Initialized WarmMemory
    """
    memory = WarmMemory(project_dir)
    await memory.init_async(session)
    return memory
