"""
Decision Logging for Autonomous Coding Framework (Database Only)
=================================================================

Provides structured logging of all agent decisions with rationale,
enabling traceability, escalation evaluation, and learning from outcomes.

All decisions are stored in the SQLite database for fast querying.

Usage:
    from arcadiaforge.decision import DecisionLogger, DecisionType

    logger = DecisionLogger(project_dir)

    # Log a decision
    decision = logger.log_decision(
        session_id=1,
        decision_type=DecisionType.IMPLEMENTATION_APPROACH,
        context="Implementing user authentication",
        choice="Use JWT tokens with refresh",
        alternatives=["Session cookies", "OAuth only"],
        rationale="JWT allows stateless scaling",
        confidence=0.8,
        related_features=[15, 16]
    )

    # Update outcome later
    logger.update_outcome(decision.decision_id, success=True, outcome="Feature completed")
"""

import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select, update as sql_update, func
from arcadiaforge.db.models import Decision as DBDecision
from arcadiaforge.db.connection import get_session_maker


class DecisionType(Enum):
    """Types of decisions that can be logged."""
    FEATURE_SELECTION = "feature_selection"           # Why this feature next?
    IMPLEMENTATION_APPROACH = "implementation_approach"  # How to implement?
    BUG_FIX_STRATEGY = "bug_fix_strategy"             # How to fix this bug?
    SKIP_FEATURE = "skip_feature"                     # Why skip this feature?
    TOOL_CHOICE = "tool_choice"                       # Which tool to use?
    ERROR_HANDLING = "error_handling"                 # How to handle this error?
    ARCHITECTURE = "architecture"                     # Architectural decisions
    DEPENDENCY = "dependency"                         # Package/dependency choices
    REFACTOR = "refactor"                             # Refactoring approach
    TEST_STRATEGY = "test_strategy"                   # Testing approach
    ESCALATION = "escalation"                         # Decision to escalate to human


@dataclass
class Decision:
    """
    Represents a logged decision with full context and rationale.

    Decisions are immutable records of agent reasoning, enabling:
    - Traceability: Link features to the decisions that shaped them
    - Learning: Analyze which decision patterns lead to success
    - Escalation: Identify low-confidence decisions for human review
    """
    decision_id: str            # "D-{session}-{seq}"
    timestamp: str              # ISO format
    session_id: int

    # The decision
    decision_type: str          # DecisionType value
    context: str                # What prompted this decision
    choice: str                 # What was decided
    alternatives: list[str]     # What else was considered

    # Rationale
    rationale: str              # Why this choice
    confidence: float           # 0.0-1.0
    inputs_consulted: list[str] # Files, features, errors reviewed

    # Outcome (filled in later)
    outcome: Optional[str] = None
    outcome_success: Optional[bool] = None
    outcome_timestamp: Optional[str] = None

    # Traceability
    related_features: list[int] = field(default_factory=list)
    git_commit: Optional[str] = None
    checkpoint_id: Optional[str] = None

    # Metadata
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Decision":
        """Create Decision from dictionary."""
        return cls(**data)

    def summary(self) -> str:
        """Return a brief summary string."""
        confidence_pct = int(self.confidence * 100)
        features = f" features={self.related_features}" if self.related_features else ""
        return f"[{self.decision_id}] {self.decision_type} ({confidence_pct}%): {self.choice[:50]}...{features}"

    @property
    def is_low_confidence(self) -> bool:
        """Check if this is a low-confidence decision (< 50%)."""
        return self.confidence < 0.5

    @property
    def needs_review(self) -> bool:
        """Check if this decision should be flagged for review."""
        return self.is_low_confidence or self.decision_type in [
            DecisionType.SKIP_FEATURE.value,
            DecisionType.ESCALATION.value,
        ]


class DecisionLogger:
    """
    Manages decision logging for a project (DB-backed).

    Decisions are stored in SQLite database for efficient querying.
    """

    def __init__(self, project_dir: Path):
        """
        Initialize DecisionLogger for a project.

        Args:
            project_dir: Path to the project directory
        """
        self.project_dir = Path(project_dir)
        self._seq = 1  # Will be dynamically set from DB

    async def _get_next_seq(self) -> int:
        """Get the next sequence number for decision IDs from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(select(DBDecision))
                decisions = result.scalars().all()
                if not decisions:
                    return 1
                max_seq = 0
                for dec in decisions:
                    try:
                        parts = dec.decision_id.split("-")
                        if len(parts) >= 3:
                            seq = int(parts[-1])
                            max_seq = max(max_seq, seq)
                    except (ValueError, IndexError):
                        continue
                return max_seq + 1
        except Exception:
            return 1

    def log_decision(
        self,
        session_id: int,
        decision_type: DecisionType | str,
        context: str,
        choice: str,
        alternatives: list[str],
        rationale: str,
        confidence: float,
        inputs_consulted: Optional[list[str]] = None,
        related_features: Optional[list[int]] = None,
        git_commit: Optional[str] = None,
        checkpoint_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Decision:
        """
        Log a decision with full context and rationale.

        Args:
            session_id: Current session ID
            decision_type: Type of decision
            context: What prompted this decision
            choice: What was decided
            alternatives: Other options considered
            rationale: Why this choice was made
            confidence: Confidence level (0.0-1.0)
            inputs_consulted: Files, features, errors reviewed
            related_features: Feature indices related to this decision
            git_commit: Related git commit hash
            checkpoint_id: Related checkpoint ID
            metadata: Additional metadata

        Returns:
            The logged Decision
        """
        # Generate decision ID
        decision_id = f"D-{session_id}-{self._seq}"
        self._seq += 1

        # Normalize confidence to 0.0-1.0
        confidence = max(0.0, min(1.0, confidence))

        # Get decision type value
        if isinstance(decision_type, DecisionType):
            type_value = decision_type.value
        else:
            type_value = str(decision_type)

        # Create decision record
        decision = Decision(
            decision_id=decision_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            decision_type=type_value,
            context=context,
            choice=choice,
            alternatives=alternatives,
            rationale=rationale,
            confidence=confidence,
            inputs_consulted=inputs_consulted or [],
            related_features=related_features or [],
            git_commit=git_commit,
            checkpoint_id=checkpoint_id,
            metadata=metadata or {},
        )

        # Persist to DB (fire-and-forget if loop exists)
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.create_task(self._persist_to_db(decision))
        except RuntimeError:
            # No loop - skip DB write for now
            pass

        return decision

    async def _persist_to_db(self, decision: Decision) -> None:
        """Persist decision to database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                db_decision = DBDecision(
                    decision_id=decision.decision_id,
                    timestamp=datetime.fromisoformat(decision.timestamp),
                    session_id=decision.session_id,
                    decision_type=decision.decision_type,
                    context=decision.context,
                    choice=decision.choice,
                    alternatives=decision.alternatives,
                    rationale=decision.rationale,
                    confidence=decision.confidence,
                    inputs_consulted=decision.inputs_consulted,
                    outcome=decision.outcome,
                    outcome_success=decision.outcome_success,
                    outcome_timestamp=datetime.fromisoformat(decision.outcome_timestamp) if decision.outcome_timestamp else None,
                    related_features=decision.related_features,
                    git_commit=decision.git_commit,
                    checkpoint_id=decision.checkpoint_id,
                    decision_metadata=decision.metadata,
                )
                session.add(db_decision)
                await session.commit()
        except Exception:
            pass

    async def update_outcome(
        self,
        decision_id: str,
        success: bool,
        outcome: str,
    ) -> Optional[Decision]:
        """
        Update the outcome of a decision.

        Args:
            decision_id: Decision ID to update
            success: Whether the decision led to success
            outcome: Description of the outcome

        Returns:
            Updated Decision if found, None otherwise
        """
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = sql_update(DBDecision).where(
                    DBDecision.decision_id == decision_id
                ).values(
                    outcome=outcome,
                    outcome_success=success,
                    outcome_timestamp=datetime.now(timezone.utc)
                )
                await session.execute(stmt)
                await session.commit()

                # Fetch updated decision
                result = await session.execute(
                    select(DBDecision).where(DBDecision.decision_id == decision_id)
                )
                db_dec = result.scalar_one_or_none()
                if db_dec:
                    return self._db_to_decision(db_dec)
        except Exception:
            pass
        return None

    async def get(self, decision_id: str) -> Optional[Decision]:
        """Get a decision by ID from database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(DBDecision).where(DBDecision.decision_id == decision_id)
                )
                db_dec = result.scalar_one_or_none()
                if db_dec:
                    return self._db_to_decision(db_dec)
        except Exception:
            pass
        return None

    async def get_decisions_for_feature(self, feature_index: int) -> list[Decision]:
        """Get all decisions related to a specific feature."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                # SQLite doesn't support array operations, so we need to filter in Python
                result = await session.execute(select(DBDecision))
                all_decisions = result.scalars().all()

                # Filter decisions that have this feature_index in related_features
                decisions = [
                    self._db_to_decision(db_dec)
                    for db_dec in all_decisions
                    if feature_index in (db_dec.related_features or [])
                ]

                # Sort by timestamp (oldest first for feature history)
                decisions.sort(key=lambda d: d.timestamp)
                return decisions
        except Exception:
            return []

    async def get_decisions_for_session(self, session_id: int) -> list[Decision]:
        """Get all decisions for a specific session."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(DBDecision)
                    .where(DBDecision.session_id == session_id)
                    .order_by(DBDecision.timestamp.asc())
                )
                db_decisions = result.scalars().all()
                return [self._db_to_decision(db_dec) for db_dec in db_decisions]
        except Exception:
            return []

    async def get_low_confidence_decisions(
        self,
        session_id: Optional[int] = None,
        threshold: float = 0.5,
    ) -> list[Decision]:
        """Get low-confidence decisions."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = select(DBDecision).where(DBDecision.confidence < threshold)
                if session_id is not None:
                    stmt = stmt.where(DBDecision.session_id == session_id)
                stmt = stmt.order_by(DBDecision.confidence.asc())

                result = await session.execute(stmt)
                db_decisions = result.scalars().all()
                return [self._db_to_decision(db_dec) for db_dec in db_decisions]
        except Exception:
            return []

    async def get_pending_outcomes(self, session_id: Optional[int] = None) -> list[Decision]:
        """Get decisions that don't have outcomes recorded."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = select(DBDecision).where(DBDecision.outcome == None)
                if session_id is not None:
                    stmt = stmt.where(DBDecision.session_id == session_id)

                result = await session.execute(stmt)
                db_decisions = result.scalars().all()
                return [self._db_to_decision(db_dec) for db_dec in db_decisions]
        except Exception:
            return []

    async def get_stats(self, session_id: Optional[int] = None) -> dict:
        """Get decision statistics."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = select(DBDecision)
                if session_id is not None:
                    stmt = stmt.where(DBDecision.session_id == session_id)

                result = await session.execute(stmt)
                decisions = result.scalars().all()

                if not decisions:
                    return {
                        "total_decisions": 0,
                        "by_type": {},
                        "avg_confidence": 0.0,
                        "low_confidence_count": 0,
                        "outcomes_recorded": 0,
                        "success_rate": 0.0,
                    }

                # Count by type
                by_type: dict[str, int] = {}
                for d in decisions:
                    by_type[d.decision_type] = by_type.get(d.decision_type, 0) + 1

                # Calculate averages
                total = len(decisions)
                confidences = [d.confidence for d in decisions]
                avg_confidence = sum(confidences) / total if total > 0 else 0.0
                low_confidence = sum(1 for c in confidences if c < 0.5)

                # Calculate success rate
                with_outcomes = [d for d in decisions if d.outcome is not None]
                outcomes_recorded = len(with_outcomes)
                successes = sum(1 for d in with_outcomes if d.outcome_success)
                success_rate = successes / outcomes_recorded if outcomes_recorded > 0 else 0.0

                return {
                    "total_decisions": total,
                    "by_type": by_type,
                    "avg_confidence": round(avg_confidence, 3),
                    "low_confidence_count": low_confidence,
                    "outcomes_recorded": outcomes_recorded,
                    "success_count": successes,
                    "success_rate": round(success_rate, 3),
                }
        except Exception:
            return {
                "total_decisions": 0,
                "by_type": {},
                "avg_confidence": 0.0,
                "low_confidence_count": 0,
                "outcomes_recorded": 0,
                "success_rate": 0.0,
            }

    async def list_recent(self, limit: int = 10, session_id: Optional[int] = None) -> list[Decision]:
        """List recent decisions (newest first)."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stmt = select(DBDecision).order_by(DBDecision.timestamp.desc()).limit(limit)
                if session_id is not None:
                    stmt = stmt.where(DBDecision.session_id == session_id)

                result = await session.execute(stmt)
                db_decisions = result.scalars().all()
                return [self._db_to_decision(db_dec) for db_dec in db_decisions]
        except Exception:
            return []

    def _db_to_decision(self, db_dec: DBDecision) -> Decision:
        """Convert database model to Decision dataclass."""
        return Decision(
            decision_id=db_dec.decision_id,
            timestamp=db_dec.timestamp.isoformat(),
            session_id=db_dec.session_id,
            decision_type=db_dec.decision_type,
            context=db_dec.context,
            choice=db_dec.choice,
            alternatives=db_dec.alternatives or [],
            rationale=db_dec.rationale,
            confidence=db_dec.confidence,
            inputs_consulted=db_dec.inputs_consulted or [],
            outcome=db_dec.outcome,
            outcome_success=db_dec.outcome_success,
            outcome_timestamp=db_dec.outcome_timestamp.isoformat() if db_dec.outcome_timestamp else None,
            related_features=db_dec.related_features or [],
            git_commit=db_dec.git_commit,
            checkpoint_id=db_dec.checkpoint_id,
            metadata=db_dec.decision_metadata or {},
        )


def create_decision_logger(project_dir: Path) -> DecisionLogger:
    """Create a DecisionLogger for a project."""
    return DecisionLogger(project_dir)
