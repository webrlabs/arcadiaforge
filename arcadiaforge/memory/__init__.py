"""
Memory Module - Tiered Memory System (Database Only)
====================================================

This module implements a three-tier memory system for the autonomous coding agent.
All data is stored in the SQLite database.

1. **Hot Memory** - Current session working state
2. **Warm Memory** - Recent session context
3. **Cold Memory** - Archived historical data

Usage:
    from arcadiaforge.memory import MemoryManager

    # Create memory manager
    memory = MemoryManager(project_dir, session_id=5)

    # Record actions
    memory.record_action("Read file", "Success", tool="Read")
    memory.record_error("TypeError", "Cannot read property")

    # At session end
    memory.end_session(ending_state="completed", ...)

    # Get context for prompts
    context = memory.get_full_context()
"""

import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any
from dataclasses import dataclass, field

from sqlalchemy import select
from arcadiaforge.db.models import (
    HotMemory as DBHotMemory,
    WarmMemory as DBWarmMemory,
    WarmMemoryPattern as DBWarmMemoryPattern,
)
from arcadiaforge.db.connection import get_session_maker


MAX_RECENT_ACTIONS = 20
MAX_RECENT_FILES = 20
MAX_ACTIVE_ERRORS = 50
MAX_PENDING_DECISIONS = 50


# Dataclasses for memory payloads
@dataclass
class WorkingContext:
    current_feature: Optional[int] = None
    current_task: str = ""
    focus_keywords: list[str] = field(default_factory=list)


@dataclass
class ActiveError:
    error_id: str
    error_type: str
    message: str
    first_seen: str
    last_seen: str
    occurrence_count: int = 1
    context: dict = field(default_factory=dict)
    related_features: list[int] = field(default_factory=list)
    resolved: bool = False
    resolution: Optional[str] = None


@dataclass
class PendingDecision:
    decision_id: str
    decision_type: str
    context: str
    options: list[str]
    recommendation: Optional[str] = None
    confidence: float = 0.5
    blocking_feature: Optional[int] = None


@dataclass
class SessionSummary:
    session_id: int
    started_at: str
    ended_at: str
    duration_seconds: float
    features_started: int = 0
    features_completed: int = 0
    features_regressed: int = 0
    key_decisions: list[dict] = field(default_factory=list)
    errors_encountered: list[dict] = field(default_factory=list)
    errors_resolved: list[dict] = field(default_factory=list)
    last_feature_worked: Optional[int] = None
    last_checkpoint_id: Optional[str] = None
    ending_state: str = "completed"
    patterns_discovered: list[str] = field(default_factory=list)
    warnings_for_next: list[str] = field(default_factory=list)
    tool_calls: int = 0
    escalations: int = 0
    human_interventions: int = 0


@dataclass
class UnresolvedIssue:
    issue_id: str
    issue_type: str
    description: str
    priority: int = 3


@dataclass
class ProvenPattern:
    pattern_id: str
    pattern_type: str
    problem: str
    solution: str
    confidence: float = 0.5
    success_count: int = 1
    context_keywords: list[str] = field(default_factory=list)
    sessions_used: list[int] = field(default_factory=list)


@dataclass
class ArchivedSession:
    session_id: int
    started_at: str
    ended_at: str
    ending_state: str
    features_completed: int = 0
    features_regressed: int = 0
    errors_count: int = 0
    duration_seconds: float = 0.0


@dataclass
class KnowledgeEntry:
    knowledge_id: str
    knowledge_type: str
    title: str
    description: str
    confidence: float = 0.5
    times_verified: int = 1
    context_keywords: list[str] = field(default_factory=list)


@dataclass
class AggregateStatistics:
    total_sessions: int = 0
    total_features_completed: int = 0
    total_errors: int = 0
    knowledge_entries: int = 0


class HotMemoryStub:
    """Stub for hot memory access."""
    def __init__(self, session_id: int):
        self.session_id = session_id
        self.current_feature = None
        self.current_task = ""
        self.recent_actions = []
        self.recent_files = []
        self.focus_keywords = []
        self.active_errors = []
        self.pending_decisions = []
        self.current_hypotheses = []


class MemoryManager:
    """
    Orchestrates the three-tier memory system (DB-backed).
    """

    def _run_async(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        return loop.create_task(coro)

    def _get_db_path(self) -> Optional[Path]:
        db_path = self.project_dir / ".arcadia" / "project.db"
        return db_path if db_path.exists() else None

    @staticmethod
    def _parse_json(value: Any, default: Any):
        if value is None:
            return default
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default

    @staticmethod
    def _trim_list(values: list[Any], max_items: int) -> list[Any]:
        if max_items <= 0:
            return []
        if len(values) <= max_items:
            return values
        return values[-max_items:]

    def _fetch_hot_row(self) -> Optional[dict[str, Any]]:
        db_path = self._get_db_path()
        if not db_path:
            return None
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT current_feature, current_task, recent_actions, recent_files, "
                "focus_keywords, active_errors, pending_decisions, current_hypotheses "
                "FROM hot_memory WHERE session_id = ?",
                (self.session_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "current_feature": row["current_feature"],
            "current_task": row["current_task"] or "",
            "recent_actions": self._parse_json(row["recent_actions"], []),
            "recent_files": self._parse_json(row["recent_files"], []),
            "focus_keywords": self._parse_json(row["focus_keywords"], []),
            "active_errors": self._parse_json(row["active_errors"], []),
            "pending_decisions": self._parse_json(row["pending_decisions"], []),
            "current_hypotheses": self._parse_json(row["current_hypotheses"], []),
        }

    def _fetch_latest_warm_row(self) -> Optional[dict[str, Any]]:
        db_path = self._get_db_path()
        if not db_path:
            return None
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT session_id, started_at, ended_at, duration_seconds, "
                "features_started, features_completed, features_regressed, "
                "key_decisions, errors_encountered, errors_resolved, ending_state, "
                "patterns_discovered, warnings_for_next, tool_calls, escalations, "
                "human_interventions "
                "FROM warm_memory ORDER BY session_id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "session_id": row["session_id"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "duration_seconds": row["duration_seconds"],
            "features_started": row["features_started"],
            "features_completed": row["features_completed"],
            "features_regressed": row["features_regressed"],
            "key_decisions": self._parse_json(row["key_decisions"], []),
            "errors_encountered": self._parse_json(row["errors_encountered"], []),
            "errors_resolved": self._parse_json(row["errors_resolved"], []),
            "ending_state": row["ending_state"],
            "patterns_discovered": self._parse_json(row["patterns_discovered"], []),
            "warnings_for_next": self._parse_json(row["warnings_for_next"], []),
            "tool_calls": row["tool_calls"],
            "escalations": row["escalations"],
            "human_interventions": row["human_interventions"],
        }

    async def _update_hot_memory(self, update_fn) -> Optional[DBHotMemory]:
        try:
            session_maker = get_session_maker()
        except RuntimeError:
            return None
        async with session_maker() as session:
            result = await session.execute(
                select(DBHotMemory).where(DBHotMemory.session_id == self.session_id)
            )
            hot = result.scalar_one_or_none()
            if not hot:
                hot = DBHotMemory(
                    session_id=self.session_id,
                    started_at=self._session_start,
                )
                session.add(hot)
                await session.flush()
            update_fn(hot)
            await session.commit()
            return hot

    def _persist_hot_state(self) -> None:
        snapshot = {
            "current_feature": self.hot.current_feature,
            "current_task": self.hot.current_task,
            "recent_actions": list(self.hot.recent_actions),
            "recent_files": list(self.hot.recent_files),
            "focus_keywords": list(self.hot.focus_keywords),
            "active_errors": list(self.hot.active_errors),
            "pending_decisions": list(self.hot.pending_decisions),
            "current_hypotheses": list(self.hot.current_hypotheses),
        }

        def updater(hot: DBHotMemory) -> None:
            hot.current_feature = snapshot["current_feature"]
            hot.current_task = snapshot["current_task"]
            hot.recent_actions = snapshot["recent_actions"]
            hot.recent_files = snapshot["recent_files"]
            hot.focus_keywords = snapshot["focus_keywords"]
            hot.active_errors = snapshot["active_errors"]
            hot.pending_decisions = snapshot["pending_decisions"]
            hot.current_hypotheses = snapshot["current_hypotheses"]

        self._run_async(self._update_hot_memory(updater))

    def __init__(self, project_dir: Path, session_id: int):
        """Initialize the memory manager."""
        self.project_dir = Path(project_dir)
        self.session_id = session_id
        self._session_start = datetime.now(timezone.utc)
        self.project_dir.mkdir(parents=True, exist_ok=True)

        # Create hot memory stub for backwards compatibility
        self.hot = HotMemoryStub(session_id)

        # Initialize hot memory in DB
        self._run_async(self._init_hot_memory())

    async def _init_hot_memory(self):
        """Initialize hot memory in database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                # Check if hot memory exists for this session
                result = await session.execute(
                    select(DBHotMemory).where(DBHotMemory.session_id == self.session_id)
                )
                existing = result.scalar_one_or_none()

                if not existing:
                    hot = DBHotMemory(
                        session_id=self.session_id,
                        started_at=self._session_start,
                    )
                    session.add(hot)
                    await session.commit()
        except Exception:
            pass

    # Stub implementations for backwards compatibility
    def start_session(self, resume_from: Optional[int] = None) -> dict:
        """Initialize a new session."""
        self.hot = HotMemoryStub(self.session_id)
        self._run_async(self._init_hot_memory())
        return {
            "session_id": self.session_id,
            "started_at": self._session_start.isoformat(),
            "resuming_from": resume_from,
        }

    def end_session(
        self,
        ending_state: str = "completed",
        features_started: int = 0,
        features_completed: int = 0,
        features_regressed: int = 0,
        key_decisions: Optional[list[dict]] = None,
        patterns_discovered: Optional[list[str]] = None,
        warnings_for_next: Optional[list[str]] = None,
        tool_calls: int = 0,
        escalations: int = 0,
        human_interventions: int = 0,
    ) -> SessionSummary:
        """End the current session and save to warm memory."""
        ended_at = datetime.now(timezone.utc)
        duration = (ended_at - self._session_start).total_seconds()

        summary = SessionSummary(
            session_id=self.session_id,
            started_at=self._session_start.isoformat(),
            ended_at=ended_at.isoformat(),
            duration_seconds=duration,
            features_started=features_started,
            features_completed=features_completed,
            features_regressed=features_regressed,
            key_decisions=key_decisions or [],
            errors_encountered=[],
            errors_resolved=[],
            ending_state=ending_state,
            patterns_discovered=patterns_discovered or [],
            warnings_for_next=warnings_for_next or [],
            tool_calls=tool_calls,
            escalations=escalations,
            human_interventions=human_interventions,
        )

        # Save to DB
        self._run_async(self._save_warm_memory(summary))

        return summary

    async def _save_warm_memory(self, summary: SessionSummary):
        """Save session summary to warm memory."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                warm = DBWarmMemory(
                    session_id=summary.session_id,
                    started_at=datetime.fromisoformat(summary.started_at),
                    ended_at=datetime.fromisoformat(summary.ended_at),
                    duration_seconds=summary.duration_seconds,
                    features_started=summary.features_started,
                    features_completed=summary.features_completed,
                    features_regressed=summary.features_regressed,
                    key_decisions=summary.key_decisions,
                    errors_encountered=summary.errors_encountered,
                    errors_resolved=summary.errors_resolved,
                    ending_state=summary.ending_state,
                    patterns_discovered=summary.patterns_discovered,
                    warnings_for_next=summary.warnings_for_next,
                    tool_calls=summary.tool_calls,
                    escalations=summary.escalations,
                    human_interventions=summary.human_interventions,
                )
                session.add(warm)
                await session.commit()
        except Exception:
            pass

    async def _save_warm_pattern(self, pattern: ProvenPattern) -> None:
        """Persist a proven pattern to warm memory."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                db_pattern = DBWarmMemoryPattern(
                    pattern_id=pattern.pattern_id,
                    created_session=self.session_id,
                    pattern_type=pattern.pattern_type,
                    pattern=pattern.solution,
                    context=pattern.problem,
                    success_count=pattern.success_count,
                    confidence=pattern.confidence,
                    context_keywords=pattern.context_keywords,
                    source_sessions=pattern.sessions_used or [self.session_id],
                    last_used_session=self.session_id,
                )
                session.add(db_pattern)
                await session.commit()
        except Exception:
            pass

    # Stub methods for backwards compatibility
    def record_action(self, action: str, result: str, tool: Optional[str] = None):
        """Record an action in hot memory."""
        entry = {
            "action": action,
            "result": result,
            "tool": tool,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.hot.recent_actions.append(entry)
        self.hot.recent_actions = self._trim_list(self.hot.recent_actions, MAX_RECENT_ACTIONS)
        self._persist_hot_state()

    def record_file_access(self, file_path: str):
        """Record file access in hot memory."""
        if file_path in self.hot.recent_files:
            self.hot.recent_files.remove(file_path)
        self.hot.recent_files.append(file_path)
        self.hot.recent_files = self._trim_list(self.hot.recent_files, MAX_RECENT_FILES)
        self._persist_hot_state()

    def add_to_hot(self, data: dict):
        """Add generic data to hot memory."""
        if not data:
            return
        entry = dict(data)
        entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        self.hot.recent_actions.append(entry)
        self.hot.recent_actions = self._trim_list(self.hot.recent_actions, MAX_RECENT_ACTIONS)
        self._persist_hot_state()

    def record_error(
        self,
        error_type: str,
        message: str,
        context: Optional[dict] = None,
        related_features: Optional[list[int]] = None,
    ) -> ActiveError:
        """Record an error in hot memory."""
        now = datetime.now(timezone.utc).isoformat()
        error_entry = None
        for entry in self.hot.active_errors:
            if (
                entry.get("error_type") == error_type
                and entry.get("message") == message
                and not entry.get("resolved", False)
            ):
                entry["last_seen"] = now
                entry["occurrence_count"] = entry.get("occurrence_count", 1) + 1
                if context:
                    merged = dict(entry.get("context", {}))
                    merged.update(context)
                    entry["context"] = merged
                if related_features:
                    existing = set(entry.get("related_features", []))
                    entry["related_features"] = sorted(existing | set(related_features))
                error_entry = entry
                break

        if error_entry is None:
            error_entry = {
                "error_id": f"ERR-{self.session_id}-{uuid.uuid4().hex[:8]}",
                "error_type": error_type,
                "message": message,
                "first_seen": now,
                "last_seen": now,
                "occurrence_count": 1,
                "context": context or {},
                "related_features": related_features or [],
                "resolved": False,
                "resolution": None,
            }
            self.hot.active_errors.append(error_entry)

        self.hot.active_errors = self._trim_list(self.hot.active_errors, MAX_ACTIVE_ERRORS)
        self._persist_hot_state()

        return ActiveError(
            error_id=error_entry["error_id"],
            error_type=error_entry["error_type"],
            message=error_entry["message"],
            first_seen=error_entry["first_seen"],
            last_seen=error_entry["last_seen"],
            occurrence_count=error_entry.get("occurrence_count", 1),
            context=error_entry.get("context", {}),
            related_features=error_entry.get("related_features", []),
            resolved=error_entry.get("resolved", False),
            resolution=error_entry.get("resolution"),
        )

    def record_decision(
        self,
        decision_type: str,
        context: str,
        options: list[str],
        recommendation: Optional[str] = None,
        confidence: float = 0.5,
        blocking_feature: Optional[int] = None,
    ) -> PendingDecision:
        """Record a pending decision in hot memory."""
        decision_entry = {
            "decision_id": f"PD-{self.session_id}-{uuid.uuid4().hex[:8]}",
            "decision_type": decision_type,
            "context": context,
            "options": options,
            "recommendation": recommendation,
            "confidence": confidence,
            "blocking_feature": blocking_feature,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.hot.pending_decisions.append(decision_entry)
        self.hot.pending_decisions = self._trim_list(
            self.hot.pending_decisions, MAX_PENDING_DECISIONS
        )
        self._persist_hot_state()

        return PendingDecision(
            decision_id=decision_entry["decision_id"],
            decision_type=decision_entry["decision_type"],
            context=decision_entry["context"],
            options=decision_entry["options"],
            recommendation=decision_entry.get("recommendation"),
            confidence=decision_entry.get("confidence", 0.5),
            blocking_feature=decision_entry.get("blocking_feature"),
        )

    def set_focus(
        self,
        feature: Optional[int] = None,
        task: str = "",
        keywords: Optional[list[str]] = None,
    ):
        """Set current working focus in hot memory."""
        self.hot.current_feature = feature
        self.hot.current_task = task
        self.hot.focus_keywords = keywords or []
        self._persist_hot_state()

    def learn_pattern(
        self,
        problem: str,
        solution: str,
        pattern_type: str = "fix",
        context_keywords: Optional[list[str]] = None,
    ) -> ProvenPattern:
        """Record a pattern that worked in warm memory."""
        pattern = ProvenPattern(
            pattern_id=f"PAT-{self.session_id}-{uuid.uuid4().hex[:8]}",
            pattern_type=pattern_type,
            problem=problem,
            solution=solution,
            confidence=0.5,
            success_count=1,
            context_keywords=context_keywords or [],
            sessions_used=[self.session_id],
        )
        self._run_async(self._save_warm_pattern(pattern))
        return pattern

    def find_relevant_patterns(self, query: str) -> list[ProvenPattern]:
        """Find patterns relevant to a query from warm memory."""
        db_path = self._get_db_path()
        if not db_path:
            return []

        query_lower = query.lower()
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT pattern_id, pattern_type, pattern, context, success_count, "
                "confidence, context_keywords, source_sessions "
                "FROM warm_memory_patterns"
            ).fetchall()
        finally:
            conn.close()

        patterns: list[ProvenPattern] = []
        for row in rows:
            keywords = self._parse_json(row["context_keywords"], [])
            source_sessions = self._parse_json(row["source_sessions"], [])
            context = row["context"] or ""
            pattern_text = row["pattern"] or ""
            haystack = " ".join([pattern_text, context, " ".join(keywords)]).lower()
            if query_lower not in haystack:
                continue
            patterns.append(
                ProvenPattern(
                    pattern_id=row["pattern_id"],
                    pattern_type=row["pattern_type"],
                    problem=context,
                    solution=pattern_text,
                    confidence=row["confidence"] or 0.5,
                    success_count=row["success_count"] or 1,
                    context_keywords=keywords,
                    sessions_used=source_sessions,
                )
            )
        return patterns

    def find_relevant_knowledge(self, query: str) -> list[KnowledgeEntry]:
        """Find knowledge relevant to a query from cold memory."""
        db_path = self._get_db_path()
        if not db_path:
            return []

        query_lower = query.lower()
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT knowledge_id, knowledge_type, title, description, "
                "confidence, times_verified, context_keywords "
                "FROM cold_memory_knowledge"
            ).fetchall()
        finally:
            conn.close()

        knowledge: list[KnowledgeEntry] = []
        for row in rows:
            keywords = self._parse_json(row["context_keywords"], [])
            title = row["title"] or ""
            description = row["description"] or ""
            haystack = " ".join([title, description, " ".join(keywords)]).lower()
            if query_lower not in haystack:
                continue
            knowledge.append(
                KnowledgeEntry(
                    knowledge_id=row["knowledge_id"],
                    knowledge_type=row["knowledge_type"],
                    title=title,
                    description=description,
                    confidence=row["confidence"] or 0.5,
                    times_verified=row["times_verified"] or 1,
                    context_keywords=keywords,
                )
            )
        return knowledge

    def find_solutions(self, query: str) -> list[dict]:
        """Find solutions from both patterns and knowledge."""
        solutions = []
        for pattern in self.find_relevant_patterns(query):
            solutions.append(
                {
                    "type": "pattern",
                    "pattern_id": pattern.pattern_id,
                    "problem": pattern.problem,
                    "solution": pattern.solution,
                    "confidence": pattern.confidence,
                }
            )
        for entry in self.find_relevant_knowledge(query):
            solutions.append(
                {
                    "type": "knowledge",
                    "knowledge_id": entry.knowledge_id,
                    "title": entry.title,
                    "description": entry.description,
                    "confidence": entry.confidence,
                }
            )
        return solutions

    def get_hot_context(self) -> str:
        """Get context string from hot memory."""
        hot = self._fetch_hot_row()
        if not hot:
            return "No active context."

        lines = ["HOT MEMORY", "-" * 40]
        if hot["current_feature"] is not None:
            lines.append(f"Current feature: {hot['current_feature']}")
        if hot["current_task"]:
            lines.append(f"Current task: {hot['current_task']}")
        if hot["focus_keywords"]:
            lines.append(f"Keywords: {', '.join(hot['focus_keywords'][:8])}")
        if hot["recent_actions"]:
            lines.append(f"Recent actions: {len(hot['recent_actions'])}")
        if hot["active_errors"]:
            lines.append(f"Active errors: {len(hot['active_errors'])}")
        if hot["pending_decisions"]:
            lines.append(f"Pending decisions: {len(hot['pending_decisions'])}")
        return "\n".join(lines)

    def get_warm_context(self) -> str:
        """Get context string from warm memory."""
        warm = self._fetch_latest_warm_row()
        if not warm:
            return "No previous session context."

        lines = [
            "WARM MEMORY",
            "-" * 40,
            f"Last session: {warm['session_id']}",
            f"Completed: {warm['features_completed']}, Regressed: {warm['features_regressed']}",
            f"Ending state: {warm['ending_state']}",
        ]
        if warm["warnings_for_next"]:
            lines.append(
                f"Warnings: {', '.join(warm['warnings_for_next'][:3])}"
            )
        if warm["patterns_discovered"]:
            lines.append(
                f"Patterns: {', '.join(warm['patterns_discovered'][:3])}"
            )
        return "\n".join(lines)

    def get_cold_context(self) -> str:
        """Get context string from cold memory."""
        db_path = self._get_db_path()
        if not db_path:
            return "No historical data available."

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT knowledge_id, knowledge_type, title, description, "
                "times_verified, confidence "
                "FROM cold_memory_knowledge "
                "ORDER BY times_verified DESC LIMIT 3"
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return "No historical data available."

        lines = ["COLD MEMORY", "-" * 40]
        for row in rows:
            lines.append(
                f"[{row['knowledge_id']}] {row['knowledge_type']}: {row['title']}"
            )
        return "\n".join(lines)

    def get_full_context(self) -> str:
        """Get combined context from all memory tiers."""
        return "\n\n".join(
            [
                self.get_hot_context(),
                self.get_warm_context(),
                self.get_cold_context(),
            ]
        )

    def get_context_size(self) -> dict:
        """Get approximate size of context from each tier."""
        hot = self._fetch_hot_row() or {}
        warm = self._fetch_latest_warm_row() or {}
        hot_size = (
            len(hot.get("recent_actions", []))
            + len(hot.get("recent_files", []))
            + len(hot.get("active_errors", []))
            + len(hot.get("pending_decisions", []))
        )
        warm_size = len(warm.get("errors_encountered", [])) + len(
            warm.get("patterns_discovered", [])
        )
        cold_count = 0
        db_path = self._get_db_path()
        if db_path:
            conn = sqlite3.connect(str(db_path))
            try:
                result = conn.execute(
                    "SELECT COUNT(*) FROM cold_memory_knowledge"
                ).fetchone()
                cold_count = result[0] if result else 0
            finally:
                conn.close()
        return {
            "hot": hot_size,
            "warm": warm_size,
            "cold": cold_count,
            "total": hot_size + warm_size + cold_count,
        }

    def get_summary(self) -> dict:
        """Get summary of all memory tiers."""
        hot = self._fetch_hot_row() or {}
        warm = self._fetch_latest_warm_row() or {}
        cold_summary = {
            "sessions": 0,
            "knowledge_entries": 0,
        }
        db_path = self._get_db_path()
        if db_path:
            conn = sqlite3.connect(str(db_path))
            try:
                result = conn.execute("SELECT COUNT(*) FROM cold_memory").fetchone()
                cold_summary["sessions"] = result[0] if result else 0
                result = conn.execute(
                    "SELECT COUNT(*) FROM cold_memory_knowledge"
                ).fetchone()
                cold_summary["knowledge_entries"] = result[0] if result else 0
            finally:
                conn.close()
        return {
            "session_id": self.session_id,
            "hot": {
                "current_feature": hot.get("current_feature"),
                "current_task": hot.get("current_task", ""),
                "recent_actions": len(hot.get("recent_actions", [])),
                "recent_files": len(hot.get("recent_files", [])),
                "active_errors": len(hot.get("active_errors", [])),
                "pending_decisions": len(hot.get("pending_decisions", [])),
            },
            "warm": {
                "last_session": warm.get("session_id"),
                "features_completed": warm.get("features_completed", 0),
                "features_regressed": warm.get("features_regressed", 0),
                "ending_state": warm.get("ending_state"),
            },
            "cold": cold_summary,
        }

    def get_statistics(self) -> AggregateStatistics:
        """Get aggregate statistics from cold memory."""
        stats = AggregateStatistics()
        db_path = self._get_db_path()
        if not db_path:
            return stats
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(features_completed), 0), "
                "COALESCE(SUM(errors_count), 0) FROM cold_memory"
            ).fetchone()
            if row:
                stats.total_sessions = row[0]
                stats.total_features_completed = row[1]
                stats.total_errors = row[2]
            row = conn.execute(
                "SELECT COUNT(*) FROM cold_memory_knowledge"
            ).fetchone()
            if row:
                stats.knowledge_entries = row[0]
        finally:
            conn.close()
        return stats


# Factory functions
def create_memory_manager(project_dir: Path, session_id: int) -> MemoryManager:
    """Create a new MemoryManager instance."""
    return MemoryManager(project_dir, session_id)





# Exports
__all__ = [
    "MemoryManager",
    "create_memory_manager",
    "WorkingContext",
    "ActiveError",
    "PendingDecision",
    "SessionSummary",
    "UnresolvedIssue",
    "ProvenPattern",
    "ArchivedSession",
    "KnowledgeEntry",
    "AggregateStatistics",
]
