"""
Hypothesis Tracking System (Database Only)
===========================================

Tracks observations, hypotheses, and uncertainties across sessions.
All data is stored in the SQLite database.

This enables the agent to:
- Record observations that "may matter later"
- Track hypotheses about root causes
- Review open hypotheses at session start
- Auto-flag when relevant context reappears

Usage:
    from arcadiaforge.hypotheses import HypothesisTracker

    tracker = HypothesisTracker(project_dir, session_id=5)

    # Add a hypothesis
    hyp = tracker.add_hypothesis(
        hypothesis_type=HypothesisType.ROOT_CAUSE,
        observation="Tests fail only on Windows",
        hypothesis="Path separator issue in file operations",
        context_keywords=["windows", "path", "file"],
    )

    # Add evidence
    tracker.add_evidence(hyp.hypothesis_id, "Found hardcoded / in code", supports=True)

    # Resolve hypothesis
    tracker.resolve_hypothesis(hyp.hypothesis_id, HypothesisStatus.CONFIRMED, "Fixed path separators")
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Any

from sqlalchemy import select, update as sql_update
from arcadiaforge.db.models import Hypothesis as DBHypothesis
from arcadiaforge.db.connection import get_session_maker


class HypothesisStatus(Enum):
    """Status of a hypothesis."""
    OPEN = "open"               # Still being investigated
    CONFIRMED = "confirmed"     # Proven to be correct
    REJECTED = "rejected"       # Proven to be incorrect
    IRRELEVANT = "irrelevant"  # No longer matters
    SUPERSEDED = "superseded"   # Replaced by another hypothesis


class HypothesisType(Enum):
    """Type of hypothesis."""
    ROOT_CAUSE = "root_cause"           # Hypothesis about why something is broken
    SIDE_EFFECT = "side_effect"         # Hypothesis about unintended consequences
    DEPENDENCY = "dependency"           # Hypothesis about hidden dependencies
    PERFORMANCE = "performance"         # Hypothesis about performance issues
    COMPATIBILITY = "compatibility"     # Hypothesis about compatibility issues
    DESIGN = "design"                   # Hypothesis about design problems
    OBSERVATION = "observation"         # General observation that may matter


@dataclass
class Evidence:
    """Evidence for or against a hypothesis."""
    added_at: str
    session_id: int
    description: str
    supports: bool  # True = evidence for, False = evidence against
    source: str = ""  # Where this evidence came from
    confidence: float = 0.5

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "added_at": self.added_at,
            "session_id": self.session_id,
            "description": self.description,
            "supports": self.supports,
            "source": self.source,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Evidence":
        """Create from dictionary."""
        return cls(
            added_at=data.get("added_at", ""),
            session_id=data.get("session_id", 0),
            description=data.get("description", ""),
            supports=data.get("supports", True),
            source=data.get("source", ""),
            confidence=data.get("confidence", 0.5),
        )


@dataclass
class Hypothesis:
    """
    A hypothesis or observation that may matter later.

    Hypotheses are tracked across sessions and can accumulate
    evidence for or against them over time.
    """
    hypothesis_id: str              # "HYP-{session}-{seq}"
    created_at: str
    created_session: int
    hypothesis_type: str            # From HypothesisType
    observation: str                # What was observed
    hypothesis: str                 # What might be causing it / what it means
    confidence: float = 0.5         # Current confidence (0.0-1.0)
    status: str = "open"            # From HypothesisStatus

    # Context
    context_keywords: list[str] = field(default_factory=list)
    related_features: list[int] = field(default_factory=list)
    related_errors: list[str] = field(default_factory=list)
    related_files: list[str] = field(default_factory=list)

    # Evidence
    evidence_for: list[Evidence] = field(default_factory=list)
    evidence_against: list[Evidence] = field(default_factory=list)

    # Resolution
    resolved_at: Optional[str] = None
    resolved_session: Optional[int] = None
    resolution: Optional[str] = None
    superseded_by: Optional[str] = None

    # Tracking
    last_reviewed: Optional[str] = None
    review_count: int = 0
    sessions_seen: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "hypothesis_id": self.hypothesis_id,
            "created_at": self.created_at,
            "created_session": self.created_session,
            "hypothesis_type": self.hypothesis_type,
            "observation": self.observation,
            "hypothesis": self.hypothesis,
            "confidence": self.confidence,
            "status": self.status,
            "context_keywords": self.context_keywords,
            "related_features": self.related_features,
            "related_errors": self.related_errors,
            "related_files": self.related_files,
            "evidence_for": [e.to_dict() for e in self.evidence_for],
            "evidence_against": [e.to_dict() for e in self.evidence_against],
            "resolved_at": self.resolved_at,
            "resolved_session": self.resolved_session,
            "resolution": self.resolution,
            "superseded_by": self.superseded_by,
            "last_reviewed": self.last_reviewed,
            "review_count": self.review_count,
            "sessions_seen": self.sessions_seen,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Hypothesis":
        """Create from dictionary."""
        return cls(
            hypothesis_id=data.get("hypothesis_id", ""),
            created_at=data.get("created_at", ""),
            created_session=data.get("created_session", 0),
            hypothesis_type=data.get("hypothesis_type", "observation"),
            observation=data.get("observation", ""),
            hypothesis=data.get("hypothesis", ""),
            confidence=data.get("confidence", 0.5),
            status=data.get("status", "open"),
            context_keywords=data.get("context_keywords", []),
            related_features=data.get("related_features", []),
            related_errors=data.get("related_errors", []),
            related_files=data.get("related_files", []),
            evidence_for=[Evidence.from_dict(e) for e in data.get("evidence_for", [])],
            evidence_against=[Evidence.from_dict(e) for e in data.get("evidence_against", [])],
            resolved_at=data.get("resolved_at"),
            resolved_session=data.get("resolved_session"),
            resolution=data.get("resolution"),
            superseded_by=data.get("superseded_by"),
            last_reviewed=data.get("last_reviewed"),
            review_count=data.get("review_count", 0),
            sessions_seen=data.get("sessions_seen", []),
        )

    @property
    def is_open(self) -> bool:
        """Check if hypothesis is still open."""
        return self.status == HypothesisStatus.OPEN.value

    @property
    def is_resolved(self) -> bool:
        """Check if hypothesis has been resolved."""
        return self.status in (
            HypothesisStatus.CONFIRMED.value,
            HypothesisStatus.REJECTED.value,
            HypothesisStatus.IRRELEVANT.value,
            HypothesisStatus.SUPERSEDED.value,
        )

    @property
    def evidence_balance(self) -> float:
        """
        Calculate the balance of evidence.

        Returns:
            Positive value if evidence leans toward confirmation,
            negative if toward rejection, 0 if balanced.
        """
        for_weight = sum(e.confidence for e in self.evidence_for)
        against_weight = sum(e.confidence for e in self.evidence_against)
        total = for_weight + against_weight
        if total == 0:
            return 0.0
        return (for_weight - against_weight) / total

    def summary(self) -> str:
        """Return a brief summary string."""
        evidence_count = len(self.evidence_for) + len(self.evidence_against)
        return (
            f"[{self.hypothesis_id}] {self.hypothesis_type} ({self.status})\n"
            f"  Observation: {self.observation[:60]}...\n"
            f"  Hypothesis: {self.hypothesis[:60]}...\n"
            f"  Confidence: {self.confidence:.0%}, Evidence: {evidence_count} items"
        )


class HypothesisTracker:
    """
    Manages hypothesis tracking for a project (DB-backed).
    """

    def __init__(self, project_dir: Path, session_id: int):
        """
        Initialize HypothesisTracker.

        Args:
            project_dir: Path to the project directory
            session_id: Current session ID
        """
        self.project_dir = Path(project_dir)
        self.session_id = session_id
        self._seq = 1  # Will be dynamically set from DB

    async def _get_next_seq(self) -> int:
        """Get the next sequence number for hypothesis IDs from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(select(DBHypothesis))
                hypotheses = result.scalars().all()
                if not hypotheses:
                    return 1
                max_seq = 0
                for hyp in hypotheses:
                    try:
                        parts = hyp.hypothesis_id.split("-")
                        if len(parts) >= 3:
                            seq = int(parts[-1])
                            max_seq = max(max_seq, seq)
                    except (ValueError, IndexError):
                        continue
                return max_seq + 1
        except Exception:
            return 1

    def add_hypothesis(
        self,
        hypothesis_type: HypothesisType | str,
        observation: str,
        hypothesis: str,
        confidence: float = 0.5,
        context_keywords: Optional[list[str]] = None,
        related_features: Optional[list[int]] = None,
        related_errors: Optional[list[str]] = None,
        related_files: Optional[list[str]] = None,
    ) -> Hypothesis:
        """
        Add a new hypothesis.

        Args:
            hypothesis_type: Type of hypothesis
            observation: What was observed
            hypothesis: What it might mean or what's causing it
            confidence: Initial confidence level (0.0-1.0)
            context_keywords: Keywords for matching
            related_features: Related feature indices
            related_errors: Related error messages
            related_files: Related file paths

        Returns:
            The created Hypothesis
        """
        # Generate hypothesis ID
        hypothesis_id = f"HYP-{self.session_id}-{self._seq}"
        self._seq += 1

        # Normalize type
        if isinstance(hypothesis_type, HypothesisType):
            type_value = hypothesis_type.value
        else:
            type_value = str(hypothesis_type)

        # Create hypothesis
        hyp = Hypothesis(
            hypothesis_id=hypothesis_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            created_session=self.session_id,
            hypothesis_type=type_value,
            observation=observation,
            hypothesis=hypothesis,
            confidence=max(0.0, min(1.0, confidence)),
            status=HypothesisStatus.OPEN.value,
            context_keywords=context_keywords or [],
            related_features=related_features or [],
            related_errors=related_errors or [],
            related_files=related_files or [],
            sessions_seen=[self.session_id],
        )

        # Persist to DB (fire-and-forget if loop exists)
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._persist_to_db(hyp))
        except RuntimeError:
            pass

        return hyp

    async def _persist_to_db(self, hyp: Hypothesis) -> None:
        """Persist hypothesis to database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                db_hyp = DBHypothesis(
                    hypothesis_id=hyp.hypothesis_id,
                    created_at=datetime.fromisoformat(hyp.created_at),
                    created_session=hyp.created_session,
                    hypothesis_type=hyp.hypothesis_type,
                    observation=hyp.observation,
                    hypothesis=hyp.hypothesis,
                    confidence=hyp.confidence,
                    status=hyp.status,
                    context_keywords=hyp.context_keywords,
                    related_features=hyp.related_features,
                    related_errors=hyp.related_errors,
                    related_files=hyp.related_files,
                    evidence_for=[e.to_dict() for e in hyp.evidence_for],
                    evidence_against=[e.to_dict() for e in hyp.evidence_against],
                    resolved_at=datetime.fromisoformat(hyp.resolved_at) if hyp.resolved_at else None,
                    resolved_session=hyp.resolved_session,
                    resolution=hyp.resolution,
                    superseded_by=hyp.superseded_by,
                    last_reviewed=datetime.fromisoformat(hyp.last_reviewed) if hyp.last_reviewed else None,
                    review_count=hyp.review_count,
                    sessions_seen=hyp.sessions_seen,
                )
                session.add(db_hyp)
                await session.commit()
        except Exception:
            pass

    def add_evidence(
        self,
        hypothesis_id: str,
        description: str,
        supports: bool = True,
        source: str = "",
        confidence: float = 0.5,
    ) -> bool:
        """
        Add evidence to a hypothesis (synchronous wrapper).

        Args:
            hypothesis_id: ID of hypothesis to update
            description: Evidence description
            supports: True if evidence supports hypothesis, False if against
            source: Source of evidence
            confidence: Confidence in this evidence (0.0-1.0)

        Returns:
            True if evidence was added, False if hypothesis not found
        """
        evidence = Evidence(
            added_at=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            description=description,
            supports=supports,
            source=source,
            confidence=max(0.0, min(1.0, confidence)),
        )

        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._add_evidence_to_db(hypothesis_id, evidence))
        except RuntimeError:
            pass

        return True

    async def _add_evidence_to_db(self, hypothesis_id: str, evidence: Evidence) -> None:
        """Add evidence to hypothesis in database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(DBHypothesis).where(DBHypothesis.hypothesis_id == hypothesis_id)
                )
                db_hyp = result.scalar_one_or_none()

                if db_hyp:
                    if evidence.supports:
                        evidence_list = db_hyp.evidence_for or []
                        evidence_list.append(evidence.to_dict())
                        db_hyp.evidence_for = evidence_list
                    else:
                        evidence_list = db_hyp.evidence_against or []
                        evidence_list.append(evidence.to_dict())
                        db_hyp.evidence_against = evidence_list

                    await session.commit()
        except Exception:
            pass

    def resolve_hypothesis(
        self,
        hypothesis_id: str,
        status: HypothesisStatus | str,
        resolution: str,
        superseded_by: Optional[str] = None,
    ) -> bool:
        """
        Resolve a hypothesis (synchronous wrapper).

        Args:
            hypothesis_id: ID of hypothesis to resolve
            status: New status
            resolution: Resolution description
            superseded_by: ID of superseding hypothesis (if applicable)

        Returns:
            True if resolved, False if hypothesis not found
        """
        status_value = status.value if isinstance(status, HypothesisStatus) else status

        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(
                    self._resolve_in_db(hypothesis_id, status_value, resolution, superseded_by)
                )
        except RuntimeError:
            pass

        return True

    async def _resolve_in_db(
        self, hypothesis_id: str, status: str, resolution: str, superseded_by: Optional[str]
    ) -> None:
        """Resolve hypothesis in database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = sql_update(DBHypothesis).where(
                    DBHypothesis.hypothesis_id == hypothesis_id
                ).values(
                    status=status,
                    resolution=resolution,
                    resolved_at=datetime.now(timezone.utc),
                    resolved_session=self.session_id,
                    superseded_by=superseded_by,
                )
                await session.execute(stmt)
                await session.commit()
        except Exception:
            pass

    async def get_hypothesis(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """Get a hypothesis by ID from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(DBHypothesis).where(DBHypothesis.hypothesis_id == hypothesis_id)
                )
                db_hyp = result.scalar_one_or_none()
                if db_hyp:
                    return self._db_to_hypothesis(db_hyp)
        except Exception:
            pass
        return None

    async def list_hypotheses(
        self,
        status: Optional[HypothesisStatus] = None,
        hypothesis_type: Optional[HypothesisType] = None,
        session_id: Optional[int] = None,
    ) -> list[Hypothesis]:
        """List hypotheses with optional filters."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = select(DBHypothesis).order_by(DBHypothesis.created_at.desc())

                if status is not None:
                    status_val = status.value if isinstance(status, HypothesisStatus) else status
                    stmt = stmt.where(DBHypothesis.status == status_val)
                if hypothesis_type is not None:
                    type_val = hypothesis_type.value if isinstance(hypothesis_type, HypothesisType) else hypothesis_type
                    stmt = stmt.where(DBHypothesis.hypothesis_type == type_val)
                if session_id is not None:
                    stmt = stmt.where(DBHypothesis.created_session == session_id)

                result = await session.execute(stmt)
                db_hypotheses = result.scalars().all()
                return [self._db_to_hypothesis(db_hyp) for db_hyp in db_hypotheses]
        except Exception:
            return []

    async def get_open_hypotheses(self) -> list[Hypothesis]:
        """Get all open hypotheses."""
        return await self.list_hypotheses(status=HypothesisStatus.OPEN)

    def _db_to_hypothesis(self, db_hyp: DBHypothesis) -> Hypothesis:
        """Convert database model to Hypothesis dataclass."""
        evidence_for = [Evidence.from_dict(e) for e in (db_hyp.evidence_for or [])]
        evidence_against = [Evidence.from_dict(e) for e in (db_hyp.evidence_against or [])]

        return Hypothesis(
            hypothesis_id=db_hyp.hypothesis_id,
            created_at=db_hyp.created_at.isoformat(),
            created_session=db_hyp.created_session,
            hypothesis_type=db_hyp.hypothesis_type,
            observation=db_hyp.observation,
            hypothesis=db_hyp.hypothesis,
            confidence=db_hyp.confidence,
            status=db_hyp.status,
            context_keywords=db_hyp.context_keywords or [],
            related_features=db_hyp.related_features or [],
            related_errors=db_hyp.related_errors or [],
            related_files=db_hyp.related_files or [],
            evidence_for=evidence_for,
            evidence_against=evidence_against,
            resolved_at=db_hyp.resolved_at.isoformat() if db_hyp.resolved_at else None,
            resolved_session=db_hyp.resolved_session,
            resolution=db_hyp.resolution,
            superseded_by=db_hyp.superseded_by,
            last_reviewed=db_hyp.last_reviewed.isoformat() if db_hyp.last_reviewed else None,
            review_count=db_hyp.review_count,
            sessions_seen=db_hyp.sessions_seen or [],
        )


def create_hypothesis_tracker(project_dir: Path, session_id: int) -> HypothesisTracker:
    """Create a HypothesisTracker for a project."""
    return HypothesisTracker(project_dir, session_id)
