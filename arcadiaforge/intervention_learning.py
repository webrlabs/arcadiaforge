"""
Intervention Learning Module
============================

Learns from human interventions to improve future autonomy. When humans
correct the agent's behavior, this module:

1. Records the intervention context and action
2. Computes a context signature for pattern matching
3. Identifies similar past situations
4. Can auto-apply proven interventions in matching contexts
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.models import InterventionModel, InterventionPatternModel


class InterventionType(Enum):
    """Types of human interventions."""
    CORRECTION = "correction"       # Human corrected a decision
    OVERRIDE = "override"           # Human overrode agent action
    GUIDANCE = "guidance"           # Human provided guidance
    APPROVAL = "approval"           # Human approved/rejected action
    REDIRECT = "redirect"           # Human changed direction
    ESCALATION_RESPONSE = "escalation_response"  # Response to escalation


@dataclass
class ContextSignature:
    """
    Signature of context for matching similar situations.

    Captures the essential features of a situation without exact details.
    """

    # What tool/action was involved
    tool: Optional[str] = None
    action_type: Optional[str] = None

    # What triggered the intervention
    trigger_type: Optional[str] = None  # escalation, error, low_confidence, etc.

    # Error context (normalized)
    error_pattern: Optional[str] = None

    # Feature context
    feature_category: Optional[str] = None

    # Decision context
    decision_type: Optional[str] = None

    # Computed hash
    _hash: Optional[str] = None

    def compute_hash(self) -> str:
        """Compute a hash for this signature."""
        components = [
            self.tool or "",
            self.action_type or "",
            self.trigger_type or "",
            self.error_pattern or "",
            self.feature_category or "",
            self.decision_type or "",
        ]
        content = "|".join(components)
        self._hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return self._hash

    @property
    def hash(self) -> str:
        """Get the hash, computing if necessary."""
        if self._hash is None:
            self.compute_hash()
        return self._hash

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "tool": self.tool,
            "action_type": self.action_type,
            "trigger_type": self.trigger_type,
            "error_pattern": self.error_pattern,
            "feature_category": self.feature_category,
            "decision_type": self.decision_type,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContextSignature":
        """Create from dictionary."""
        sig = cls(
            tool=data.get("tool"),
            action_type=data.get("action_type"),
            trigger_type=data.get("trigger_type"),
            error_pattern=data.get("error_pattern"),
            feature_category=data.get("feature_category"),
            decision_type=data.get("decision_type"),
        )
        sig._hash = data.get("hash")
        return sig

    def similarity_score(self, other: "ContextSignature") -> float:
        """
        Calculate similarity to another signature.

        Returns:
            Similarity score from 0.0 to 1.0
        """
        score = 0.0
        total_fields = 0

        # Compare each field
        if self.tool or other.tool:
            total_fields += 1
            if self.tool == other.tool:
                score += 1.0

        if self.action_type or other.action_type:
            total_fields += 1
            if self.action_type == other.action_type:
                score += 1.0

        if self.trigger_type or other.trigger_type:
            total_fields += 1
            if self.trigger_type == other.trigger_type:
                score += 1.0

        if self.error_pattern or other.error_pattern:
            total_fields += 1
            if self.error_pattern == other.error_pattern:
                score += 1.0
            elif self.error_pattern and other.error_pattern:
                # Partial match for similar errors
                if self.error_pattern in other.error_pattern or other.error_pattern in self.error_pattern:
                    score += 0.5

        if self.feature_category or other.feature_category:
            total_fields += 1
            if self.feature_category == other.feature_category:
                score += 1.0

        if self.decision_type or other.decision_type:
            total_fields += 1
            if self.decision_type == other.decision_type:
                score += 1.0

        if total_fields == 0:
            return 0.0

        return score / total_fields


@dataclass
class Intervention:
    """Record of a human intervention."""

    intervention_id: str
    session_id: int
    timestamp: str

    # Type and context
    intervention_type: InterventionType
    context_signature: ContextSignature

    # Full context details
    context_details: dict = field(default_factory=dict)

    # Agent's original action/decision
    original_action: Optional[str] = None
    original_rationale: Optional[str] = None

    # Human's intervention
    human_action: str = ""
    human_rationale: Optional[str] = None

    # Outcome tracking
    outcome_tracked: bool = False
    outcome_success: Optional[bool] = None
    outcome_notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "intervention_id": self.intervention_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "intervention_type": self.intervention_type.value,
            "context_signature": self.context_signature.to_dict(),
            "context_details": self.context_details,
            "original_action": self.original_action,
            "original_rationale": self.original_rationale,
            "human_action": self.human_action,
            "human_rationale": self.human_rationale,
            "outcome_tracked": self.outcome_tracked,
            "outcome_success": self.outcome_success,
            "outcome_notes": self.outcome_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Intervention":
        """Create from dictionary."""
        return cls(
            intervention_id=data["intervention_id"],
            session_id=data["session_id"],
            timestamp=data["timestamp"],
            intervention_type=InterventionType(data["intervention_type"]),
            context_signature=ContextSignature.from_dict(data["context_signature"]),
            context_details=data.get("context_details", {}),
            original_action=data.get("original_action"),
            original_rationale=data.get("original_rationale"),
            human_action=data.get("human_action", ""),
            human_rationale=data.get("human_rationale"),
            outcome_tracked=data.get("outcome_tracked", False),
            outcome_success=data.get("outcome_success"),
            outcome_notes=data.get("outcome_notes"),
        )


@dataclass
class InterventionPattern:
    """A learned pattern from interventions."""

    pattern_id: str
    context_signature: ContextSignature

    # Pattern statistics
    times_matched: int = 0
    times_applied: int = 0
    success_count: int = 0
    failure_count: int = 0

    # The learned intervention
    recommended_action: str = ""
    rationale: str = ""

    # Auto-apply settings
    auto_apply: bool = False
    confidence: float = 0.0
    min_confidence_for_auto: float = 0.8

    # Source interventions
    source_intervention_ids: list[str] = field(default_factory=list)

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_matched: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "pattern_id": self.pattern_id,
            "context_signature": self.context_signature.to_dict(),
            "times_matched": self.times_matched,
            "times_applied": self.times_applied,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "recommended_action": self.recommended_action,
            "rationale": self.rationale,
            "auto_apply": self.auto_apply,
            "confidence": self.confidence,
            "min_confidence_for_auto": self.min_confidence_for_auto,
            "source_intervention_ids": self.source_intervention_ids,
            "created_at": self.created_at,
            "last_matched": self.last_matched,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InterventionPattern":
        """Create from dictionary."""
        return cls(
            pattern_id=data["pattern_id"],
            context_signature=ContextSignature.from_dict(data["context_signature"]),
            times_matched=data.get("times_matched", 0),
            times_applied=data.get("times_applied", 0),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            recommended_action=data.get("recommended_action", ""),
            rationale=data.get("rationale", ""),
            auto_apply=data.get("auto_apply", False),
            confidence=data.get("confidence", 0.0),
            min_confidence_for_auto=data.get("min_confidence_for_auto", 0.8),
            source_intervention_ids=data.get("source_intervention_ids", []),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            last_matched=data.get("last_matched"),
        )

    def update_confidence(self) -> None:
        """Update confidence based on success/failure counts."""
        total = self.success_count + self.failure_count
        if total == 0:
            self.confidence = 0.0
        else:
            self.confidence = self.success_count / total

        # Update auto-apply based on confidence and sample size
        if self.confidence >= self.min_confidence_for_auto and total >= 3:
            self.auto_apply = True
        elif self.confidence < 0.5 or self.failure_count > self.success_count:
            self.auto_apply = False

    def record_match(self) -> None:
        """Record that this pattern was matched."""
        self.times_matched += 1
        self.last_matched = datetime.now(timezone.utc).isoformat()

    def record_application(self, success: bool) -> None:
        """Record that this pattern was applied."""
        self.times_applied += 1
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        self.update_confidence()


@dataclass
class MatchResult:
    """Result of pattern matching."""

    pattern: InterventionPattern
    similarity: float
    should_auto_apply: bool
    recommendation: str
    rationale: str

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "pattern_id": self.pattern.pattern_id,
            "similarity": self.similarity,
            "should_auto_apply": self.should_auto_apply,
            "recommendation": self.recommendation,
            "rationale": self.rationale,
            "confidence": self.pattern.confidence,
            "times_applied": self.pattern.times_applied,
            "success_rate": self.pattern.confidence,
        }


class InterventionLearner:
    """
    Learns from human interventions to improve future autonomy.

    Provides:
    - Recording of interventions with context signatures
    - Pattern matching for similar situations
    - Auto-application of proven interventions
    - Outcome tracking for learning

    All data is stored in the database (interventions and intervention_patterns tables).
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)

        # Database session (set via set_session or init_async)
        self._db_session: Optional[AsyncSession] = None

        # Patterns loaded from DB
        self.patterns: list[InterventionPattern] = []

        # Intervention counter (loaded from DB)
        self._intervention_counter = 0

        # Settings
        self.similarity_threshold = 0.7  # Minimum similarity for pattern match
        self.auto_apply_threshold = 0.8  # Minimum confidence for auto-apply

    def set_session(self, session: AsyncSession) -> None:
        """Set the database session for async operations."""
        self._db_session = session

    async def init_async(self, session: AsyncSession) -> None:
        """Initialize with async database session."""
        self._db_session = session
        self.patterns = await self._load_patterns_async()
        self._intervention_counter = await self._count_interventions_async()

    async def _load_patterns_async(self) -> list[InterventionPattern]:
        """Load patterns from database."""
        if not self._db_session:
            return []

        result = await self._db_session.execute(select(InterventionPatternModel))
        rows = result.scalars().all()

        patterns = []
        for row in rows:
            sig = ContextSignature(
                tool=row.context_signature.get("tool") if row.context_signature else None,
                action_type=row.context_signature.get("action_type") if row.context_signature else None,
                trigger_type=row.context_signature.get("trigger_type") if row.context_signature else None,
                error_pattern=row.context_signature.get("error_pattern") if row.context_signature else None,
                feature_category=row.context_signature.get("feature_category") if row.context_signature else None,
                decision_type=row.context_signature.get("decision_type") if row.context_signature else None,
            )
            sig._hash = row.context_signature.get("hash") if row.context_signature else None

            patterns.append(InterventionPattern(
                pattern_id=row.pattern_id,
                context_signature=sig,
                times_matched=row.times_matched or 0,
                times_applied=row.times_applied or 0,
                success_count=row.success_count or 0,
                failure_count=row.failure_count or 0,
                recommended_action=row.recommended_action or "",
                rationale=row.rationale or "",
                auto_apply=row.auto_apply or False,
                confidence=row.confidence or 0.0,
                min_confidence_for_auto=row.min_confidence_for_auto or 0.8,
                source_intervention_ids=row.source_intervention_ids or [],
                created_at=row.created_at.isoformat() if row.created_at else datetime.now(timezone.utc).isoformat(),
                last_matched=row.last_matched.isoformat() if row.last_matched else None,
            ))
        return patterns

    def _load_patterns(self) -> list[InterventionPattern]:
        """Load patterns (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return []
        except RuntimeError:
            if self._db_session:
                return asyncio.run(self._load_patterns_async())
            return []

    async def _save_patterns_async(self) -> None:
        """Save all patterns to database."""
        if not self._db_session:
            return

        for pattern in self.patterns:
            # Check if pattern exists
            result = await self._db_session.execute(
                select(InterventionPatternModel).where(
                    InterventionPatternModel.pattern_id == pattern.pattern_id
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                await self._db_session.execute(
                    update(InterventionPatternModel)
                    .where(InterventionPatternModel.pattern_id == pattern.pattern_id)
                    .values(
                        context_signature=pattern.context_signature.to_dict(),
                        times_matched=pattern.times_matched,
                        times_applied=pattern.times_applied,
                        success_count=pattern.success_count,
                        failure_count=pattern.failure_count,
                        recommended_action=pattern.recommended_action,
                        rationale=pattern.rationale,
                        auto_apply=pattern.auto_apply,
                        confidence=pattern.confidence,
                        min_confidence_for_auto=pattern.min_confidence_for_auto,
                        source_intervention_ids=pattern.source_intervention_ids,
                        last_matched=datetime.fromisoformat(pattern.last_matched) if pattern.last_matched else None,
                    )
                )
            else:
                # Insert new
                db_model = InterventionPatternModel(
                    pattern_id=pattern.pattern_id,
                    context_signature=pattern.context_signature.to_dict(),
                    times_matched=pattern.times_matched,
                    times_applied=pattern.times_applied,
                    success_count=pattern.success_count,
                    failure_count=pattern.failure_count,
                    recommended_action=pattern.recommended_action,
                    rationale=pattern.rationale,
                    auto_apply=pattern.auto_apply,
                    confidence=pattern.confidence,
                    min_confidence_for_auto=pattern.min_confidence_for_auto,
                    source_intervention_ids=pattern.source_intervention_ids,
                    created_at=datetime.fromisoformat(pattern.created_at),
                    last_matched=datetime.fromisoformat(pattern.last_matched) if pattern.last_matched else None,
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

    async def _count_interventions_async(self) -> int:
        """Count existing interventions for ID generation from database."""
        if not self._db_session:
            return 0

        result = await self._db_session.execute(
            select(func.count(InterventionModel.id))
        )
        return result.scalar_one_or_none() or 0

    def _count_interventions(self) -> int:
        """Count existing interventions (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return 0
        except RuntimeError:
            if self._db_session:
                return asyncio.run(self._count_interventions_async())
            return 0

    def _generate_intervention_id(self) -> str:
        """Generate a unique intervention ID."""
        self._intervention_counter += 1
        return f"INT-{self._intervention_counter:04d}"

    async def _log_intervention_async(self, intervention: Intervention) -> None:
        """Log an intervention to database."""
        if not self._db_session:
            return

        db_model = InterventionModel(
            intervention_id=intervention.intervention_id,
            session_id=intervention.session_id,
            timestamp=datetime.fromisoformat(intervention.timestamp.replace('Z', '+00:00')),
            intervention_type=intervention.intervention_type.value,
            context_signature=intervention.context_signature.to_dict(),
            context_details=intervention.context_details,
            original_action=intervention.original_action,
            original_rationale=intervention.original_rationale,
            human_action=intervention.human_action,
            human_rationale=intervention.human_rationale,
            outcome_tracked=intervention.outcome_tracked,
            outcome_success=intervention.outcome_success,
            outcome_notes=intervention.outcome_notes,
        )
        self._db_session.add(db_model)
        await self._db_session.commit()

    def _log_intervention(self, intervention: Intervention) -> None:
        """Log an intervention (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._log_intervention_async(intervention))
        except RuntimeError:
            if self._db_session:
                asyncio.run(self._log_intervention_async(intervention))

    def create_context_signature(
        self,
        tool: Optional[str] = None,
        action_type: Optional[str] = None,
        trigger_type: Optional[str] = None,
        error_message: Optional[str] = None,
        feature_category: Optional[str] = None,
        decision_type: Optional[str] = None,
    ) -> ContextSignature:
        """
        Create a context signature from components.

        Args:
            tool: The tool involved
            action_type: Type of action (write, execute, etc.)
            trigger_type: What triggered the intervention
            error_message: Error message (will be normalized)
            feature_category: Category of feature being worked on
            decision_type: Type of decision being made

        Returns:
            Context signature for pattern matching
        """
        # Normalize error message to pattern
        error_pattern = None
        if error_message:
            error_pattern = self._normalize_error(error_message)

        sig = ContextSignature(
            tool=tool,
            action_type=action_type,
            trigger_type=trigger_type,
            error_pattern=error_pattern,
            feature_category=feature_category,
            decision_type=decision_type,
        )
        sig.compute_hash()
        return sig

    def _normalize_error(self, error_message: str) -> str:
        """Normalize an error message to a pattern."""
        import re

        normalized = error_message.lower()

        # Remove specific file paths
        normalized = re.sub(r'[/\\][\w./\\-]+\.\w+', '<path>', normalized)

        # Remove line numbers
        normalized = re.sub(r'line \d+', 'line <n>', normalized)
        normalized = re.sub(r':\d+:\d+', ':<n>:<n>', normalized)

        # Remove specific variable names in quotes
        normalized = re.sub(r"'[^']+?'", "'<var>'", normalized)
        normalized = re.sub(r'"[^"]+?"', '"<var>"', normalized)

        # Remove hex addresses
        normalized = re.sub(r'0x[0-9a-f]+', '<addr>', normalized)

        # Truncate
        if len(normalized) > 100:
            normalized = normalized[:100]

        return normalized

    def record_intervention(
        self,
        session_id: int,
        intervention_type: InterventionType,
        context_signature: ContextSignature,
        human_action: str,
        context_details: Optional[dict] = None,
        original_action: Optional[str] = None,
        original_rationale: Optional[str] = None,
        human_rationale: Optional[str] = None,
    ) -> Intervention:
        """
        Record a human intervention.

        Args:
            session_id: Current session ID
            intervention_type: Type of intervention
            context_signature: Signature of the context
            human_action: What the human did
            context_details: Full context details
            original_action: What the agent was going to do
            original_rationale: Why the agent chose that
            human_rationale: Why the human intervened

        Returns:
            The recorded intervention
        """
        intervention = Intervention(
            intervention_id=self._generate_intervention_id(),
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            intervention_type=intervention_type,
            context_signature=context_signature,
            context_details=context_details or {},
            original_action=original_action,
            original_rationale=original_rationale,
            human_action=human_action,
            human_rationale=human_rationale,
        )

        self._log_intervention(intervention)

        # Update or create pattern
        self._update_patterns(intervention)

        return intervention

    def _update_patterns(self, intervention: Intervention) -> None:
        """Update patterns based on new intervention."""
        # Find matching pattern
        matching_pattern = None
        best_similarity = 0.0

        for pattern in self.patterns:
            similarity = pattern.context_signature.similarity_score(
                intervention.context_signature
            )
            if similarity >= self.similarity_threshold and similarity > best_similarity:
                matching_pattern = pattern
                best_similarity = similarity

        if matching_pattern:
            # Update existing pattern
            matching_pattern.source_intervention_ids.append(intervention.intervention_id)
            matching_pattern.record_match()

            # If same action, treat as confirmation
            if matching_pattern.recommended_action == intervention.human_action:
                matching_pattern.record_application(success=True)
        else:
            # Create new pattern
            pattern = InterventionPattern(
                pattern_id=f"PAT-{len(self.patterns)+1:04d}",
                context_signature=intervention.context_signature,
                recommended_action=intervention.human_action,
                rationale=intervention.human_rationale or "",
                source_intervention_ids=[intervention.intervention_id],
                times_matched=1,
            )
            self.patterns.append(pattern)

        self._save_patterns()

    async def record_outcome_async(
        self,
        intervention_id: str,
        success: bool,
        notes: Optional[str] = None
    ) -> bool:
        """
        Record the outcome of an intervention in database.

        Args:
            intervention_id: ID of the intervention
            success: Whether the intervention led to success
            notes: Additional notes

        Returns:
            True if intervention was found and updated
        """
        if not self._db_session:
            return False

        # Update intervention in database
        result = await self._db_session.execute(
            select(InterventionModel).where(
                InterventionModel.intervention_id == intervention_id
            )
        )
        row = result.scalar_one_or_none()

        if not row:
            return False

        await self._db_session.execute(
            update(InterventionModel)
            .where(InterventionModel.intervention_id == intervention_id)
            .values(
                outcome_tracked=True,
                outcome_success=success,
                outcome_notes=notes,
            )
        )
        await self._db_session.commit()

        # Update pattern confidence
        self._update_pattern_outcomes(intervention_id, success)

        return True

    def record_outcome(
        self,
        intervention_id: str,
        success: bool,
        notes: Optional[str] = None
    ) -> bool:
        """Record the outcome of an intervention (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self.record_outcome_async(intervention_id, success, notes))
            return True
        except RuntimeError:
            if self._db_session:
                return asyncio.run(self.record_outcome_async(intervention_id, success, notes))
            return False

    def _update_pattern_outcomes(self, intervention_id: str, success: bool) -> None:
        """Update pattern confidence based on outcome."""
        for pattern in self.patterns:
            if intervention_id in pattern.source_intervention_ids:
                pattern.record_application(success)

        self._save_patterns()

    def find_matching_patterns(
        self,
        context_signature: ContextSignature,
        min_similarity: Optional[float] = None
    ) -> list[MatchResult]:
        """
        Find patterns matching the current context.

        Args:
            context_signature: Current context signature
            min_similarity: Minimum similarity threshold

        Returns:
            List of matching patterns with similarity scores
        """
        threshold = min_similarity or self.similarity_threshold
        matches = []

        for pattern in self.patterns:
            similarity = pattern.context_signature.similarity_score(context_signature)

            if similarity >= threshold:
                pattern.record_match()

                should_auto = (
                    pattern.auto_apply and
                    pattern.confidence >= self.auto_apply_threshold and
                    similarity >= 0.9  # High similarity for auto-apply
                )

                matches.append(MatchResult(
                    pattern=pattern,
                    similarity=similarity,
                    should_auto_apply=should_auto,
                    recommendation=pattern.recommended_action,
                    rationale=pattern.rationale,
                ))

        # Sort by similarity
        matches.sort(key=lambda m: m.similarity, reverse=True)

        self._save_patterns()  # Save updated match counts

        return matches

    def get_recommendation(
        self,
        context_signature: ContextSignature
    ) -> Optional[MatchResult]:
        """
        Get the best recommendation for the current context.

        Args:
            context_signature: Current context signature

        Returns:
            Best matching pattern result, or None
        """
        matches = self.find_matching_patterns(context_signature)

        if not matches:
            return None

        # Return highest similarity match
        return matches[0]

    def should_auto_apply(
        self,
        context_signature: ContextSignature
    ) -> Optional[MatchResult]:
        """
        Check if an intervention should be auto-applied.

        Args:
            context_signature: Current context signature

        Returns:
            Match result if should auto-apply, None otherwise
        """
        matches = self.find_matching_patterns(context_signature)

        for match in matches:
            if match.should_auto_apply:
                return match

        return None

    async def get_interventions_async(
        self,
        session_id: Optional[int] = None,
        intervention_type: Optional[InterventionType] = None,
        limit: int = 100
    ) -> list[Intervention]:
        """
        Get recorded interventions from database.

        Args:
            session_id: Filter by session
            intervention_type: Filter by type
            limit: Maximum number to return

        Returns:
            List of interventions
        """
        if not self._db_session:
            return []

        query = select(InterventionModel).order_by(InterventionModel.timestamp.desc())

        if session_id is not None:
            query = query.where(InterventionModel.session_id == session_id)

        if intervention_type is not None:
            query = query.where(InterventionModel.intervention_type == intervention_type.value)

        query = query.limit(limit)

        result = await self._db_session.execute(query)
        rows = result.scalars().all()

        interventions = []
        for row in rows:
            sig = ContextSignature.from_dict(row.context_signature or {})
            interventions.append(Intervention(
                intervention_id=row.intervention_id,
                session_id=row.session_id,
                timestamp=row.timestamp.isoformat() if row.timestamp else "",
                intervention_type=InterventionType(row.intervention_type),
                context_signature=sig,
                context_details=row.context_details or {},
                original_action=row.original_action,
                original_rationale=row.original_rationale,
                human_action=row.human_action or "",
                human_rationale=row.human_rationale,
                outcome_tracked=row.outcome_tracked or False,
                outcome_success=row.outcome_success,
                outcome_notes=row.outcome_notes,
            ))

        return interventions

    def get_interventions(
        self,
        session_id: Optional[int] = None,
        intervention_type: Optional[InterventionType] = None,
        limit: int = 100
    ) -> list[Intervention]:
        """Get recorded interventions (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return []
        except RuntimeError:
            if self._db_session:
                return asyncio.run(self.get_interventions_async(session_id, intervention_type, limit))
            return []

    def get_patterns(
        self,
        auto_apply_only: bool = False,
        min_confidence: Optional[float] = None
    ) -> list[InterventionPattern]:
        """
        Get learned patterns.

        Args:
            auto_apply_only: Only return patterns with auto-apply enabled
            min_confidence: Minimum confidence filter

        Returns:
            List of patterns
        """
        patterns = self.patterns.copy()

        if auto_apply_only:
            patterns = [p for p in patterns if p.auto_apply]

        if min_confidence is not None:
            patterns = [p for p in patterns if p.confidence >= min_confidence]

        return patterns

    def get_learning_stats(self) -> dict:
        """Get statistics about intervention learning."""
        interventions = self.get_interventions(limit=1000)

        # Count by type
        by_type = {}
        for intervention in interventions:
            type_name = intervention.intervention_type.value
            by_type[type_name] = by_type.get(type_name, 0) + 1

        # Outcome stats
        with_outcome = [i for i in interventions if i.outcome_tracked]
        successful = sum(1 for i in with_outcome if i.outcome_success)

        # Pattern stats
        auto_apply_patterns = [p for p in self.patterns if p.auto_apply]

        return {
            "total_interventions": len(interventions),
            "by_type": by_type,
            "outcomes_tracked": len(with_outcome),
            "successful_outcomes": successful,
            "outcome_success_rate": successful / len(with_outcome) if with_outcome else 0.0,
            "total_patterns": len(self.patterns),
            "auto_apply_patterns": len(auto_apply_patterns),
            "avg_pattern_confidence": (
                sum(p.confidence for p in self.patterns) / len(self.patterns)
                if self.patterns else 0.0
            ),
        }

    def format_pattern(self, pattern: InterventionPattern) -> str:
        """Format a pattern for display."""
        lines = [
            f"Pattern: {pattern.pattern_id}",
            f"  Recommendation: {pattern.recommended_action}",
            f"  Rationale: {pattern.rationale or '(none)'}",
            f"  Confidence: {pattern.confidence:.0%}",
            f"  Times Applied: {pattern.times_applied}",
            f"  Success Rate: {pattern.confidence:.0%}",
            f"  Auto-Apply: {'Yes' if pattern.auto_apply else 'No'}",
        ]

        sig = pattern.context_signature
        lines.append("  Context:")
        if sig.tool:
            lines.append(f"    Tool: {sig.tool}")
        if sig.trigger_type:
            lines.append(f"    Trigger: {sig.trigger_type}")
        if sig.error_pattern:
            lines.append(f"    Error: {sig.error_pattern}")

        return "\n".join(lines)

    def reset_learning(self) -> None:
        """Reset all learned patterns (keeps intervention history)."""
        self.patterns = []
        self._save_patterns()


def create_intervention_learner(project_dir: Path) -> InterventionLearner:
    """Create an InterventionLearner instance."""
    return InterventionLearner(project_dir)


async def create_intervention_learner_async(
    project_dir: Path,
    session: AsyncSession,
) -> InterventionLearner:
    """
    Create an InterventionLearner with async database session.

    Args:
        project_dir: Path to project directory
        session: AsyncSession for database operations

    Returns:
        Initialized InterventionLearner
    """
    learner = InterventionLearner(project_dir)
    await learner.init_async(session)
    return learner
