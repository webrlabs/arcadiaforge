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
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Any
from dataclasses import dataclass, field

from sqlalchemy import select
from arcadiaforge.db.models import (
    HotMemory as DBHotMemory,
    WarmMemory as DBWarmMemory,
    ColdMemory as DBColdMemory,
)
from arcadiaforge.db.connection import get_session_maker


# Dataclasses for backwards compatibility
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


class MemoryManager:
    """
    Orchestrates the three-tier memory system (DB-backed).
    """

    def __init__(self, project_dir: Path, session_id: int):
        """Initialize the memory manager."""
        self.project_dir = Path(project_dir)
        self.session_id = session_id
        self._session_start = datetime.now(timezone.utc)
        self.project_dir.mkdir(parents=True, exist_ok=True)

        # Create hot memory stub for backwards compatibility
        self.hot = HotMemoryStub(session_id)

        # Initialize hot memory in DB
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._init_hot_memory())
        except RuntimeError:
            pass

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
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._save_warm_memory(summary))
        except RuntimeError:
            pass

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

    # Stub methods for backwards compatibility
    def record_action(self, action: str, result: str, tool: Optional[str] = None):
        """Record an action (stub)."""
        pass

    def record_file_access(self, file_path: str):
        """Record file access (stub)."""
        pass

    def add_to_hot(self, data: dict):
        """Add data to hot memory (stub)."""
        pass

    def record_error(
        self,
        error_type: str,
        message: str,
        context: Optional[dict] = None,
        related_features: Optional[list[int]] = None,
    ) -> ActiveError:
        """Record an error (stub)."""
        return ActiveError(
            error_id=f"ERR-{self.session_id}-1",
            error_type=error_type,
            message=message,
            first_seen=datetime.now(timezone.utc).isoformat(),
            last_seen=datetime.now(timezone.utc).isoformat(),
            context=context or {},
            related_features=related_features or [],
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
        """Record a pending decision (stub)."""
        return PendingDecision(
            decision_id=f"PD-{self.session_id}-1",
            decision_type=decision_type,
            context=context,
            options=options,
            recommendation=recommendation,
            confidence=confidence,
            blocking_feature=blocking_feature,
        )

    def set_focus(
        self,
        feature: Optional[int] = None,
        task: str = "",
        keywords: Optional[list[str]] = None,
    ):
        """Set current working focus (stub)."""
        pass

    def learn_pattern(
        self,
        problem: str,
        solution: str,
        pattern_type: str = "fix",
        context_keywords: Optional[list[str]] = None,
    ) -> ProvenPattern:
        """Record a pattern that worked (stub)."""
        return ProvenPattern(
            pattern_id=f"PAT-{self.session_id}-1",
            pattern_type=pattern_type,
            problem=problem,
            solution=solution,
            context_keywords=context_keywords or [],
        )

    def find_relevant_patterns(self, query: str) -> list[ProvenPattern]:
        """Find patterns relevant to a query (stub)."""
        return []

    def find_relevant_knowledge(self, query: str) -> list[KnowledgeEntry]:
        """Find knowledge relevant to a query (stub)."""
        return []

    def find_solutions(self, query: str) -> list[dict]:
        """Find solutions from both patterns and knowledge (stub)."""
        return []

    def get_hot_context(self) -> str:
        """Get context string from hot memory (stub)."""
        return "No active context."

    def get_warm_context(self) -> str:
        """Get context string from warm memory (stub)."""
        return "No previous session context."

    def get_cold_context(self) -> str:
        """Get context string from cold memory (stub)."""
        return "No historical data available."

    def get_full_context(self) -> str:
        """Get combined context from all memory tiers."""
        return "No memory context available."

    def get_context_size(self) -> dict:
        """Get approximate size of context from each tier."""
        return {
            "hot": 0,
            "warm": 0,
            "cold": 0,
            "total": 0,
        }

    def get_summary(self) -> dict:
        """Get summary of all memory tiers."""
        return {
            "session_id": self.session_id,
            "hot": {},
            "warm": {},
            "cold": {},
        }

    def get_statistics(self) -> AggregateStatistics:
        """Get aggregate statistics from cold memory."""
        return AggregateStatistics()


# Stub classes for backwards compatibility
class HotMemory:
    def __init__(self, project_dir: Path, session_id: int):
        pass

class WarmMemory:
    def __init__(self, project_dir: Path):
        pass

class ColdMemory:
    def __init__(self, project_dir: Path):
        pass


# Factory functions
def create_memory_manager(project_dir: Path, session_id: int) -> MemoryManager:
    """Create a new MemoryManager instance."""
    return MemoryManager(project_dir, session_id)


def create_hot_memory(project_dir: Path, session_id: int) -> HotMemory:
    """Create hot memory (stub)."""
    return HotMemory(project_dir, session_id)


def create_warm_memory(project_dir: Path) -> WarmMemory:
    """Create warm memory (stub)."""
    return WarmMemory(project_dir)


def create_cold_memory(project_dir: Path) -> ColdMemory:
    """Create cold memory (stub)."""
    return ColdMemory(project_dir)


# Exports
__all__ = [
    "MemoryManager",
    "create_memory_manager",
    "HotMemory",
    "WorkingContext",
    "ActiveError",
    "PendingDecision",
    "create_hot_memory",
    "WarmMemory",
    "SessionSummary",
    "UnresolvedIssue",
    "ProvenPattern",
    "create_warm_memory",
    "ColdMemory",
    "ArchivedSession",
    "KnowledgeEntry",
    "AggregateStatistics",
    "create_cold_memory",
]
