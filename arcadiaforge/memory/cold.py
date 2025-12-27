"""
Cold Memory - Archived Historical Data
=======================================

Cold memory stores historical data from old sessions.
It is:
- Append-only (immutable once written)
- Queryable but not actively monitored

All data is stored in the database (cold_memory and cold_memory_knowledge tables).
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any, Iterator

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.models import (
    ColdMemory as ColdMemoryModel,
    ColdMemoryKnowledge as ColdMemoryKnowledgeModel,
)


@dataclass
class ArchivedSession:
    """Minimal session record for cold storage."""
    session_id: int
    started_at: str
    ended_at: str
    ending_state: str
    features_completed: int
    features_regressed: int
    errors_count: int
    duration_seconds: float

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "ending_state": self.ending_state,
            "features_completed": self.features_completed,
            "features_regressed": self.features_regressed,
            "errors_count": self.errors_count,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArchivedSession":
        """Create from dictionary."""
        return cls(
            session_id=data.get("session_id", 0),
            started_at=data.get("started_at", ""),
            ended_at=data.get("ended_at", ""),
            ending_state=data.get("ending_state", ""),
            features_completed=data.get("features_completed", 0),
            features_regressed=data.get("features_regressed", 0),
            errors_count=data.get("errors_count", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
        )


@dataclass
class KnowledgeEntry:
    """A piece of proven knowledge extracted from history."""
    knowledge_id: str
    created_at: str
    knowledge_type: str  # "fix", "pattern", "warning", "best_practice"
    title: str
    description: str
    context_keywords: list[str] = field(default_factory=list)
    source_sessions: list[int] = field(default_factory=list)
    times_verified: int = 1
    confidence: float = 0.5
    last_used: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "knowledge_id": self.knowledge_id,
            "created_at": self.created_at,
            "knowledge_type": self.knowledge_type,
            "title": self.title,
            "description": self.description,
            "context_keywords": self.context_keywords,
            "source_sessions": self.source_sessions,
            "times_verified": self.times_verified,
            "confidence": self.confidence,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "KnowledgeEntry":
        """Create from dictionary."""
        return cls(
            knowledge_id=data.get("knowledge_id", ""),
            created_at=data.get("created_at", ""),
            knowledge_type=data.get("knowledge_type", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            context_keywords=data.get("context_keywords", []),
            source_sessions=data.get("source_sessions", []),
            times_verified=data.get("times_verified", 1),
            confidence=data.get("confidence", 0.5),
            last_used=data.get("last_used"),
        )


@dataclass
class AggregateStatistics:
    """Aggregate statistics across all sessions."""
    total_sessions: int = 0
    total_features_completed: int = 0
    total_features_regressed: int = 0
    total_errors: int = 0
    total_duration_seconds: float = 0.0
    successful_sessions: int = 0
    failed_sessions: int = 0
    avg_session_duration: float = 0.0
    avg_features_per_session: float = 0.0
    last_updated: str = ""

    def update(self, session: ArchivedSession) -> None:
        """Update statistics with a new session."""
        self.total_sessions += 1
        self.total_features_completed += session.features_completed
        self.total_features_regressed += session.features_regressed
        self.total_errors += session.errors_count
        self.total_duration_seconds += session.duration_seconds

        if session.ending_state == "completed":
            self.successful_sessions += 1
        elif session.ending_state in ("failed", "error"):
            self.failed_sessions += 1

        # Recalculate averages
        if self.total_sessions > 0:
            self.avg_session_duration = self.total_duration_seconds / self.total_sessions
            self.avg_features_per_session = self.total_features_completed / self.total_sessions

        self.last_updated = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "total_sessions": self.total_sessions,
            "total_features_completed": self.total_features_completed,
            "total_features_regressed": self.total_features_regressed,
            "total_errors": self.total_errors,
            "total_duration_seconds": self.total_duration_seconds,
            "successful_sessions": self.successful_sessions,
            "failed_sessions": self.failed_sessions,
            "avg_session_duration": self.avg_session_duration,
            "avg_features_per_session": self.avg_features_per_session,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AggregateStatistics":
        """Create from dictionary."""
        return cls(
            total_sessions=data.get("total_sessions", 0),
            total_features_completed=data.get("total_features_completed", 0),
            total_features_regressed=data.get("total_features_regressed", 0),
            total_errors=data.get("total_errors", 0),
            total_duration_seconds=data.get("total_duration_seconds", 0.0),
            successful_sessions=data.get("successful_sessions", 0),
            failed_sessions=data.get("failed_sessions", 0),
            avg_session_duration=data.get("avg_session_duration", 0.0),
            avg_features_per_session=data.get("avg_features_per_session", 0.0),
            last_updated=data.get("last_updated", ""),
        )


class ColdMemory:
    """
    Manages cold (archived) memory.

    Cold memory is:
    - Compressed and archived
    - Append-only (immutable)
    - Contains aggregated knowledge

    Usage:
        cold = ColdMemory(project_dir)

        # Archive sessions from warm memory
        cold.archive_session(session_summary)

        # Query knowledge
        entries = cold.search_knowledge("authentication error")

        # Get statistics
        stats = cold.get_statistics()
    """

    def __init__(self, project_dir: Path):
        """
        Initialize cold memory.

        Args:
            project_dir: Project directory path
        """
        self.project_dir = Path(project_dir)

        # Database session (set via set_session or init_async)
        self._db_session: Optional[AsyncSession] = None

        # State (loaded from DB)
        self.knowledge: dict[str, KnowledgeEntry] = {}
        self.statistics: AggregateStatistics = AggregateStatistics()

        # Sequence counter
        self._knowledge_seq = 1

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
        """Load all cold memory state from database."""
        await self._load_knowledge_async()
        await self._load_statistics_async()

    async def _load_knowledge_async(self) -> None:
        """Load knowledge entries from database."""
        if not self._db_session:
            return

        self.knowledge.clear()
        result = await self._db_session.execute(select(ColdMemoryKnowledgeModel))
        rows = result.scalars().all()

        for row in rows:
            self.knowledge[row.knowledge_id] = KnowledgeEntry(
                knowledge_id=row.knowledge_id,
                created_at=row.created_at.isoformat() if row.created_at else "",
                knowledge_type=row.knowledge_type or "",
                title=row.title or "",
                description=row.description or "",
                context_keywords=row.context_keywords or [],
                source_sessions=row.source_sessions or [],
                times_verified=row.times_verified or 1,
                confidence=row.confidence or 0.5,
                last_used=row.last_used.isoformat() if row.last_used else None,
            )

        # Update sequence counter
        if self.knowledge:
            try:
                max_id = max(
                    int(k.knowledge_id.split("-")[-1])
                    for k in self.knowledge.values()
                    if "-" in k.knowledge_id
                )
                self._knowledge_seq = max_id + 1
            except ValueError:
                pass

    async def _load_statistics_async(self) -> None:
        """Load aggregate statistics from database."""
        if not self._db_session:
            return

        # Calculate statistics from cold_memory table
        result = await self._db_session.execute(
            select(
                func.count(ColdMemoryModel.id),
                func.sum(ColdMemoryModel.features_completed),
                func.sum(ColdMemoryModel.features_regressed),
                func.sum(ColdMemoryModel.errors_count),
                func.sum(ColdMemoryModel.duration_seconds),
            )
        )
        row = result.one_or_none()

        if row and row[0]:
            total = row[0]
            self.statistics.total_sessions = total
            self.statistics.total_features_completed = row[1] or 0
            self.statistics.total_features_regressed = row[2] or 0
            self.statistics.total_errors = row[3] or 0
            self.statistics.total_duration_seconds = row[4] or 0.0

            if total > 0:
                self.statistics.avg_session_duration = self.statistics.total_duration_seconds / total
                self.statistics.avg_features_per_session = self.statistics.total_features_completed / total

            # Count successful/failed sessions
            success_result = await self._db_session.execute(
                select(func.count(ColdMemoryModel.id)).where(
                    ColdMemoryModel.ending_state == "completed"
                )
            )
            self.statistics.successful_sessions = success_result.scalar_one_or_none() or 0

            failed_result = await self._db_session.execute(
                select(func.count(ColdMemoryModel.id)).where(
                    ColdMemoryModel.ending_state.in_(["failed", "error"])
                )
            )
            self.statistics.failed_sessions = failed_result.scalar_one_or_none() or 0

            self.statistics.last_updated = datetime.now(timezone.utc).isoformat()

    # =========================================================================
    # Saving
    # =========================================================================

    async def _save_knowledge_async(self, entry: KnowledgeEntry) -> None:
        """Save a knowledge entry to database."""
        if not self._db_session:
            return

        # Check if exists
        result = await self._db_session.execute(
            select(ColdMemoryKnowledgeModel).where(
                ColdMemoryKnowledgeModel.knowledge_id == entry.knowledge_id
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            await self._db_session.execute(
                update(ColdMemoryKnowledgeModel)
                .where(ColdMemoryKnowledgeModel.knowledge_id == entry.knowledge_id)
                .values(
                    knowledge_type=entry.knowledge_type,
                    title=entry.title,
                    description=entry.description,
                    context_keywords=entry.context_keywords,
                    source_sessions=entry.source_sessions,
                    times_verified=entry.times_verified,
                    confidence=entry.confidence,
                    last_used=datetime.fromisoformat(entry.last_used.replace('Z', '+00:00')) if entry.last_used else None,
                )
            )
        else:
            db_model = ColdMemoryKnowledgeModel(
                knowledge_id=entry.knowledge_id,
                knowledge_type=entry.knowledge_type,
                title=entry.title,
                description=entry.description,
                context_keywords=entry.context_keywords,
                source_sessions=entry.source_sessions,
                times_verified=entry.times_verified,
                confidence=entry.confidence,
                last_used=datetime.fromisoformat(entry.last_used.replace('Z', '+00:00')) if entry.last_used else None,
            )
            self._db_session.add(db_model)

        await self._db_session.commit()

    def _save_knowledge(self) -> None:
        """Save knowledge (sync wrapper) - saves all entries."""
        try:
            loop = asyncio.get_running_loop()
            for entry in self.knowledge.values():
                asyncio.create_task(self._save_knowledge_async(entry))
        except RuntimeError:
            if self._db_session:
                for entry in self.knowledge.values():
                    asyncio.run(self._save_knowledge_async(entry))

    # =========================================================================
    # Session Archival
    # =========================================================================

    async def archive_session_async(
        self,
        session_id: int,
        started_at: str,
        ended_at: str,
        ending_state: str,
        features_completed: int,
        features_regressed: int,
        errors_count: int,
        duration_seconds: float,
    ) -> ArchivedSession:
        """
        Archive a session to cold storage (database).

        Args:
            session_id: Session ID
            started_at: Start timestamp
            ended_at: End timestamp
            ending_state: How session ended
            features_completed: Features completed
            features_regressed: Features that regressed
            errors_count: Number of errors
            duration_seconds: Duration in seconds

        Returns:
            The archived session record
        """
        session = ArchivedSession(
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            ending_state=ending_state,
            features_completed=features_completed,
            features_regressed=features_regressed,
            errors_count=errors_count,
            duration_seconds=duration_seconds,
        )

        # Save to database
        if self._db_session:
            db_model = ColdMemoryModel(
                session_id=session_id,
                started_at=datetime.fromisoformat(started_at.replace('Z', '+00:00')) if started_at else None,
                ended_at=datetime.fromisoformat(ended_at.replace('Z', '+00:00')) if ended_at else None,
                ending_state=ending_state,
                features_completed=features_completed,
                features_regressed=features_regressed,
                errors_count=errors_count,
                duration_seconds=duration_seconds,
            )
            self._db_session.add(db_model)
            await self._db_session.commit()

        # Update statistics
        self.statistics.update(session)

        return session

    def archive_session(
        self,
        session_id: int,
        started_at: str,
        ended_at: str,
        ending_state: str,
        features_completed: int,
        features_regressed: int,
        errors_count: int,
        duration_seconds: float,
    ) -> ArchivedSession:
        """Archive a session (sync wrapper)."""
        session = ArchivedSession(
            session_id=session_id,
            started_at=started_at,
            ended_at=ended_at,
            ending_state=ending_state,
            features_completed=features_completed,
            features_regressed=features_regressed,
            errors_count=errors_count,
            duration_seconds=duration_seconds,
        )

        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self.archive_session_async(
                session_id, started_at, ended_at, ending_state,
                features_completed, features_regressed, errors_count, duration_seconds
            ))
        except RuntimeError:
            if self._db_session:
                asyncio.run(self.archive_session_async(
                    session_id, started_at, ended_at, ending_state,
                    features_completed, features_regressed, errors_count, duration_seconds
                ))

        # Update statistics
        self.statistics.update(session)
        return session

    async def get_session_async(self, session_id: int) -> Optional[ArchivedSession]:
        """
        Get a specific archived session from database.

        Args:
            session_id: Session ID to find

        Returns:
            ArchivedSession if found, None otherwise
        """
        if not self._db_session:
            return None

        result = await self._db_session.execute(
            select(ColdMemoryModel).where(ColdMemoryModel.session_id == session_id)
        )
        row = result.scalar_one_or_none()

        if not row:
            return None

        return ArchivedSession(
            session_id=row.session_id,
            started_at=row.started_at.isoformat() if row.started_at else "",
            ended_at=row.ended_at.isoformat() if row.ended_at else "",
            ending_state=row.ending_state or "",
            features_completed=row.features_completed or 0,
            features_regressed=row.features_regressed or 0,
            errors_count=row.errors_count or 0,
            duration_seconds=row.duration_seconds or 0.0,
        )

    def get_session(self, session_id: int) -> Optional[ArchivedSession]:
        """Get a specific archived session (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return None
        except RuntimeError:
            if self._db_session:
                return asyncio.run(self.get_session_async(session_id))
            return None

    async def iter_archived_sessions_async(self) -> list[ArchivedSession]:
        """Get all archived sessions from database."""
        if not self._db_session:
            return []

        result = await self._db_session.execute(
            select(ColdMemoryModel).order_by(ColdMemoryModel.session_id)
        )
        rows = result.scalars().all()

        return [
            ArchivedSession(
                session_id=row.session_id,
                started_at=row.started_at.isoformat() if row.started_at else "",
                ended_at=row.ended_at.isoformat() if row.ended_at else "",
                ending_state=row.ending_state or "",
                features_completed=row.features_completed or 0,
                features_regressed=row.features_regressed or 0,
                errors_count=row.errors_count or 0,
                duration_seconds=row.duration_seconds or 0.0,
            )
            for row in rows
        ]

    def iter_archived_sessions(self) -> Iterator[ArchivedSession]:
        """Iterate over all archived sessions (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return iter([])
        except RuntimeError:
            if self._db_session:
                sessions = asyncio.run(self.iter_archived_sessions_async())
                return iter(sessions)
            return iter([])

    # =========================================================================
    # Knowledge Management
    # =========================================================================

    def add_knowledge(
        self,
        knowledge_type: str,
        title: str,
        description: str,
        context_keywords: Optional[list[str]] = None,
        source_sessions: Optional[list[int]] = None,
        confidence: float = 0.5,
    ) -> KnowledgeEntry:
        """
        Add a knowledge entry.

        Args:
            knowledge_type: Type of knowledge
            title: Short title
            description: Full description
            context_keywords: Keywords for matching
            source_sessions: Sessions this was learned from
            confidence: Initial confidence

        Returns:
            The created KnowledgeEntry
        """
        knowledge_id = f"KNOW-{self._knowledge_seq}"
        self._knowledge_seq += 1

        entry = KnowledgeEntry(
            knowledge_id=knowledge_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            knowledge_type=knowledge_type,
            title=title,
            description=description,
            context_keywords=context_keywords or [],
            source_sessions=source_sessions or [],
            confidence=confidence,
        )

        self.knowledge[knowledge_id] = entry
        self._save_knowledge()
        return entry

    def verify_knowledge(self, knowledge_id: str) -> bool:
        """
        Record verification of knowledge (it worked again).

        Args:
            knowledge_id: Knowledge ID

        Returns:
            True if found and updated
        """
        if knowledge_id not in self.knowledge:
            return False

        entry = self.knowledge[knowledge_id]
        entry.times_verified += 1
        entry.confidence = min(1.0, entry.confidence + 0.1)
        entry.last_used = datetime.now(timezone.utc).isoformat()

        self._save_knowledge()
        return True

    def search_knowledge(
        self,
        query: str,
        knowledge_type: Optional[str] = None,
        min_confidence: float = 0.0,
    ) -> list[KnowledgeEntry]:
        """
        Search knowledge entries.

        Args:
            query: Search query
            knowledge_type: Filter by type
            min_confidence: Minimum confidence threshold

        Returns:
            List of matching entries, sorted by relevance
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        matches = []
        for entry in self.knowledge.values():
            if entry.confidence < min_confidence:
                continue
            if knowledge_type and entry.knowledge_type != knowledge_type:
                continue

            # Score based on matches
            text = f"{entry.title} {entry.description}".lower()
            keywords_lower = [k.lower() for k in entry.context_keywords]

            score = 0
            if query_lower in text:
                score += 3
            for word in query_words:
                if word in text:
                    score += 1
                if word in keywords_lower:
                    score += 2

            if score > 0:
                matches.append((entry, score))

        # Sort by score * confidence
        matches.sort(key=lambda x: x[1] * x[0].confidence, reverse=True)
        return [m[0] for m in matches]

    def get_high_confidence_knowledge(
        self,
        min_confidence: float = 0.7,
    ) -> list[KnowledgeEntry]:
        """Get knowledge entries with high confidence."""
        return [
            e for e in self.knowledge.values()
            if e.confidence >= min_confidence
        ]

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_statistics(self) -> AggregateStatistics:
        """Get aggregate statistics."""
        return self.statistics

    def get_success_rate(self) -> float:
        """Get session success rate."""
        if self.statistics.total_sessions == 0:
            return 0.0
        return self.statistics.successful_sessions / self.statistics.total_sessions

    # =========================================================================
    # Summary
    # =========================================================================

    def get_summary(self) -> dict:
        """Get summary of cold memory state."""
        return {
            "archived_sessions": self.statistics.total_sessions,
            "pending_sessions": len(self._pending_sessions),
            "knowledge_entries": len(self.knowledge),
            "high_confidence_knowledge": len(self.get_high_confidence_knowledge()),
            "success_rate": self.get_success_rate(),
            "total_features_completed": self.statistics.total_features_completed,
            "avg_features_per_session": self.statistics.avg_features_per_session,
        }

    def get_context_for_prompt(self) -> str:
        """
        Generate context string for prompts.

        Returns:
            Formatted string with cold storage summary
        """
        lines = []

        stats = self.statistics
        if stats.total_sessions > 0:
            lines.append(f"Historical: {stats.total_sessions} sessions archived")
            lines.append(f"  Success rate: {self.get_success_rate():.1%}")
            lines.append(f"  Avg features/session: {stats.avg_features_per_session:.1f}")

        high_conf = self.get_high_confidence_knowledge()
        if high_conf:
            lines.append(f"\nProven Knowledge: {len(high_conf)} high-confidence entries")
            for entry in high_conf[:3]:
                lines.append(f"  - {entry.title}")

        return "\n".join(lines) if lines else "No historical data available."


# =============================================================================
# Factory Functions
# =============================================================================

def create_cold_memory(project_dir: Path) -> ColdMemory:
    """
    Create a new ColdMemory instance.

    Args:
        project_dir: Project directory path

    Returns:
        ColdMemory instance
    """
    return ColdMemory(project_dir)


async def create_cold_memory_async(
    project_dir: Path,
    session: AsyncSession,
) -> ColdMemory:
    """
    Create a ColdMemory with async database session.

    Args:
        project_dir: Path to project directory
        session: AsyncSession for database operations

    Returns:
        Initialized ColdMemory
    """
    memory = ColdMemory(project_dir)
    await memory.init_async(session)
    return memory
