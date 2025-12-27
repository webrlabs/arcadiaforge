"""
Hot Memory - Current Session Working State
==========================================

Hot memory stores the current session's working context. It is:
- Cleared at session end (or promoted to warm)
- Designed for fast access during active work
- Contains only the most immediately relevant information

All data is stored in the `hot_memory` table in the project database.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.models import HotMemory as HotMemoryModel


@dataclass
class WorkingContext:
    """Current working state for the session."""
    session_id: int
    started_at: str
    current_feature: Optional[int] = None
    current_task: str = ""
    recent_actions: list[dict] = field(default_factory=list)
    recent_files: list[str] = field(default_factory=list)
    focus_keywords: list[str] = field(default_factory=list)

    # Limits for recent items
    MAX_RECENT_ACTIONS: int = 20
    MAX_RECENT_FILES: int = 10

    def add_action(self, action: str, result: str, tool: Optional[str] = None) -> None:
        """Record a recent action."""
        self.recent_actions.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "result": result[:200] if result else "",  # Truncate long results
            "tool": tool,
        })
        # Keep only recent actions
        if len(self.recent_actions) > self.MAX_RECENT_ACTIONS:
            self.recent_actions = self.recent_actions[-self.MAX_RECENT_ACTIONS:]

    def add_file(self, file_path: str) -> None:
        """Record a recently accessed file."""
        # Remove if already in list (will re-add at end)
        if file_path in self.recent_files:
            self.recent_files.remove(file_path)
        self.recent_files.append(file_path)
        # Keep only recent files
        if len(self.recent_files) > self.MAX_RECENT_FILES:
            self.recent_files = self.recent_files[-self.MAX_RECENT_FILES:]

    def set_focus(self, feature: Optional[int], task: str, keywords: list[str]) -> None:
        """Update current focus."""
        self.current_feature = feature
        self.current_task = task
        self.focus_keywords = keywords[:10]  # Limit keywords

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "current_feature": self.current_feature,
            "current_task": self.current_task,
            "recent_actions": self.recent_actions,
            "recent_files": self.recent_files,
            "focus_keywords": self.focus_keywords,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkingContext":
        """Create from dictionary."""
        ctx = cls(
            session_id=data.get("session_id", 0),
            started_at=data.get("started_at", datetime.now(timezone.utc).isoformat()),
            current_feature=data.get("current_feature"),
            current_task=data.get("current_task", ""),
            recent_actions=data.get("recent_actions", []),
            recent_files=data.get("recent_files", []),
            focus_keywords=data.get("focus_keywords", []),
        )
        return ctx


@dataclass
class ActiveError:
    """An error currently being debugged."""
    error_id: str
    first_seen: str
    last_seen: str
    error_type: str
    message: str
    context: dict
    occurrence_count: int = 1
    attempted_fixes: list[str] = field(default_factory=list)
    related_features: list[int] = field(default_factory=list)
    resolved: bool = False
    resolution: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "error_id": self.error_id,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "error_type": self.error_type,
            "message": self.message,
            "context": self.context,
            "occurrence_count": self.occurrence_count,
            "attempted_fixes": self.attempted_fixes,
            "related_features": self.related_features,
            "resolved": self.resolved,
            "resolution": self.resolution,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ActiveError":
        """Create from dictionary."""
        return cls(
            error_id=data.get("error_id", ""),
            first_seen=data.get("first_seen", ""),
            last_seen=data.get("last_seen", ""),
            error_type=data.get("error_type", ""),
            message=data.get("message", ""),
            context=data.get("context", {}),
            occurrence_count=data.get("occurrence_count", 1),
            attempted_fixes=data.get("attempted_fixes", []),
            related_features=data.get("related_features", []),
            resolved=data.get("resolved", False),
            resolution=data.get("resolution"),
        )


@dataclass
class PendingDecision:
    """A decision awaiting resolution."""
    decision_id: str
    created_at: str
    decision_type: str
    context: str
    options: list[str]
    recommendation: Optional[str] = None
    confidence: float = 0.5
    blocking_feature: Optional[int] = None
    notes: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "decision_id": self.decision_id,
            "created_at": self.created_at,
            "decision_type": self.decision_type,
            "context": self.context,
            "options": self.options,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "blocking_feature": self.blocking_feature,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PendingDecision":
        """Create from dictionary."""
        return cls(
            decision_id=data.get("decision_id", ""),
            created_at=data.get("created_at", ""),
            decision_type=data.get("decision_type", ""),
            context=data.get("context", ""),
            options=data.get("options", []),
            recommendation=data.get("recommendation"),
            confidence=data.get("confidence", 0.5),
            blocking_feature=data.get("blocking_feature"),
            notes=data.get("notes", ""),
        )


class HotMemory:
    """
    Manages hot (current session) memory.

    Hot memory is:
    - Fast to access
    - Limited in size
    - Cleared or promoted at session end

    Usage:
        hot = HotMemory(project_dir, session_id=5)
        hot.set_focus(feature=10, task="Implementing auth")
        hot.add_action("Read file", "Success", tool="Read")
        hot.add_error("TypeError", "Cannot read property 'x' of undefined")
        hot.save()
    """

    def __init__(self, project_dir: Path, session_id: int):
        """
        Initialize hot memory.

        Args:
            project_dir: Project directory path
            session_id: Current session ID
        """
        self.project_dir = Path(project_dir)
        self.session_id = session_id

        # Database session (set via set_session or init_async)
        self._db_session: Optional[AsyncSession] = None

        # Initialize empty state (will be loaded from DB)
        self.context: WorkingContext = WorkingContext(
            session_id=session_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.errors: dict[str, ActiveError] = {}
        self.decisions: dict[str, PendingDecision] = {}

        # Sequence counters
        self._error_seq = 1
        self._decision_seq = 1

    def set_session(self, session: AsyncSession) -> None:
        """Set the database session for async operations."""
        self._db_session = session

    async def init_async(self, session: AsyncSession) -> None:
        """Initialize with async database session and load state."""
        self._db_session = session
        await self._load_from_db()

    # =========================================================================
    # Database Operations
    # =========================================================================

    async def _load_from_db(self) -> None:
        """Load all state from database."""
        if not self._db_session:
            return

        result = await self._db_session.execute(
            select(HotMemoryModel).where(HotMemoryModel.session_id == self.session_id)
        )
        row = result.scalar_one_or_none()

        if row:
            # Load context
            self.context = WorkingContext(
                session_id=row.session_id,
                started_at=row.started_at.isoformat() if row.started_at else datetime.now(timezone.utc).isoformat(),
                current_feature=row.current_feature,
                current_task=row.current_task or "",
                recent_actions=row.recent_actions or [],
                recent_files=row.recent_files or [],
                focus_keywords=row.focus_keywords or [],
            )

            # Load errors
            self.errors = {}
            for err_data in (row.active_errors or []):
                if isinstance(err_data, dict) and "error_id" in err_data:
                    # Create a hash key for deduplication
                    import hashlib
                    error_hash = hashlib.md5(
                        f"{err_data.get('error_type', '')}:{err_data.get('message', '')}".encode()
                    ).hexdigest()[:8]
                    self.errors[error_hash] = ActiveError.from_dict(err_data)

            # Load decisions
            self.decisions = {}
            for dec_data in (row.pending_decisions or []):
                if isinstance(dec_data, dict) and "decision_id" in dec_data:
                    self.decisions[dec_data["decision_id"]] = PendingDecision.from_dict(dec_data)

            # Update sequence counters
            self._error_seq = len(self.errors) + 1
            self._decision_seq = len(self.decisions) + 1

    async def _save_to_db(self) -> None:
        """Save all state to database."""
        if not self._db_session:
            return

        # Check if row exists
        result = await self._db_session.execute(
            select(HotMemoryModel).where(HotMemoryModel.session_id == self.session_id)
        )
        existing = result.scalar_one_or_none()

        # Prepare data
        errors_list = [e.to_dict() for e in self.errors.values()]
        decisions_list = [d.to_dict() for d in self.decisions.values()]

        if existing:
            # Update existing row
            await self._db_session.execute(
                update(HotMemoryModel)
                .where(HotMemoryModel.session_id == self.session_id)
                .values(
                    current_feature=self.context.current_feature,
                    current_task=self.context.current_task,
                    recent_actions=self.context.recent_actions,
                    recent_files=self.context.recent_files,
                    focus_keywords=self.context.focus_keywords,
                    active_errors=errors_list,
                    pending_decisions=decisions_list,
                )
            )
        else:
            # Insert new row
            db_model = HotMemoryModel(
                session_id=self.session_id,
                started_at=datetime.fromisoformat(self.context.started_at.replace('Z', '+00:00')),
                current_feature=self.context.current_feature,
                current_task=self.context.current_task,
                recent_actions=self.context.recent_actions,
                recent_files=self.context.recent_files,
                focus_keywords=self.context.focus_keywords,
                active_errors=errors_list,
                pending_decisions=decisions_list,
            )
            self._db_session.add(db_model)

        await self._db_session.commit()

    def _save_context(self) -> None:
        """Save context (sync wrapper for backward compatibility)."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._save_to_db())
        except RuntimeError:
            if self._db_session:
                asyncio.run(self._save_to_db())

    def set_focus(
        self,
        feature: Optional[int] = None,
        task: str = "",
        keywords: Optional[list[str]] = None,
    ) -> None:
        """
        Set current working focus.

        Args:
            feature: Feature index being worked on
            task: Description of current task
            keywords: Relevant keywords for context matching
        """
        self.context.set_focus(feature, task, keywords or [])
        self._save_context()

    def add_action(
        self,
        action: str,
        result: str,
        tool: Optional[str] = None,
    ) -> None:
        """
        Record a recent action.

        Args:
            action: Description of action taken
            result: Result or outcome
            tool: Tool used (if any)
        """
        self.context.add_action(action, result, tool)
        self._save_context()

    def add_file(self, file_path: str) -> None:
        """
        Record a recently accessed file.

        Args:
            file_path: Path to file accessed
        """
        self.context.add_file(file_path)
        self._save_context()

    def get_context(self) -> WorkingContext:
        """Get current working context."""
        return self.context

    def get_focus_keywords(self) -> list[str]:
        """Get current focus keywords for context matching."""
        return self.context.focus_keywords

    def get_recent_files(self) -> list[str]:
        """Get recently accessed files."""
        return self.context.recent_files

    # =========================================================================
    # Error Tracking
    # =========================================================================

    def _save_errors(self) -> None:
        """Save errors (sync wrapper for backward compatibility)."""
        self._save_context()  # Unified save

    def add_error(
        self,
        error_type: str,
        message: str,
        context: Optional[dict] = None,
        related_features: Optional[list[int]] = None,
    ) -> ActiveError:
        """
        Record an active error.

        If the same error (by type + message hash) already exists,
        increments the occurrence count instead.

        Args:
            error_type: Type of error (e.g., "TypeError", "SyntaxError")
            message: Error message
            context: Additional context
            related_features: Feature indices related to this error

        Returns:
            The ActiveError object
        """
        # Create a hash for deduplication
        import hashlib
        error_hash = hashlib.md5(
            f"{error_type}:{message}".encode()
        ).hexdigest()[:8]

        now = datetime.now(timezone.utc).isoformat()

        if error_hash in self.errors:
            # Update existing error
            error = self.errors[error_hash]
            error.last_seen = now
            error.occurrence_count += 1
            if related_features:
                error.related_features = list(set(
                    error.related_features + related_features
                ))
        else:
            # Create new error
            error = ActiveError(
                error_id=f"ERR-{self.session_id}-{self._error_seq}",
                first_seen=now,
                last_seen=now,
                error_type=error_type,
                message=message[:500],  # Truncate long messages
                context=context or {},
                related_features=related_features or [],
            )
            self.errors[error_hash] = error
            self._error_seq += 1

        self._save_errors()
        return error

    def record_fix_attempt(self, error_id: str, fix_description: str) -> bool:
        """
        Record an attempted fix for an error.

        Args:
            error_id: Error ID
            fix_description: Description of the fix attempted

        Returns:
            True if error found and updated
        """
        for error in self.errors.values():
            if error.error_id == error_id:
                error.attempted_fixes.append(fix_description)
                self._save_errors()
                return True
        return False

    def resolve_error(self, error_id: str, resolution: str) -> bool:
        """
        Mark an error as resolved.

        Args:
            error_id: Error ID
            resolution: Description of how it was resolved

        Returns:
            True if error found and resolved
        """
        for error in self.errors.values():
            if error.error_id == error_id:
                error.resolved = True
                error.resolution = resolution
                self._save_errors()
                return True
        return False

    def get_active_errors(self) -> list[ActiveError]:
        """Get list of unresolved errors."""
        return [e for e in self.errors.values() if not e.resolved]

    def get_error_count(self) -> int:
        """Get count of active (unresolved) errors."""
        return len(self.get_active_errors())

    # =========================================================================
    # Decision Tracking
    # =========================================================================

    def _save_decisions(self) -> None:
        """Save decisions (sync wrapper for backward compatibility)."""
        self._save_context()  # Unified save

    def add_pending_decision(
        self,
        decision_type: str,
        context: str,
        options: list[str],
        recommendation: Optional[str] = None,
        confidence: float = 0.5,
        blocking_feature: Optional[int] = None,
    ) -> PendingDecision:
        """
        Record a pending decision.

        Args:
            decision_type: Type of decision
            context: Context for the decision
            options: Available options
            recommendation: Recommended option
            confidence: Confidence in recommendation
            blocking_feature: Feature blocked by this decision

        Returns:
            The PendingDecision object
        """
        decision_id = f"PD-{self.session_id}-{self._decision_seq}"
        self._decision_seq += 1

        decision = PendingDecision(
            decision_id=decision_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            decision_type=decision_type,
            context=context,
            options=options,
            recommendation=recommendation,
            confidence=confidence,
            blocking_feature=blocking_feature,
        )

        self.decisions[decision_id] = decision
        self._save_decisions()
        return decision

    def resolve_decision(self, decision_id: str) -> Optional[PendingDecision]:
        """
        Remove a decision (when it's been made).

        Args:
            decision_id: Decision ID

        Returns:
            The removed decision, or None if not found
        """
        if decision_id in self.decisions:
            decision = self.decisions.pop(decision_id)
            self._save_decisions()
            return decision
        return None

    def get_pending_decisions(self) -> list[PendingDecision]:
        """Get list of pending decisions."""
        return list(self.decisions.values())

    def get_low_confidence_decisions(self, threshold: float = 0.5) -> list[PendingDecision]:
        """Get decisions with confidence below threshold."""
        return [d for d in self.decisions.values() if d.confidence < threshold]

    # =========================================================================
    # Session Lifecycle
    # =========================================================================

    async def save_async(self) -> None:
        """Save all hot memory state to database."""
        await self._save_to_db()

    def save(self) -> None:
        """Save all hot memory state (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._save_to_db())
        except RuntimeError:
            if self._db_session:
                asyncio.run(self._save_to_db())

    async def clear_async(self) -> None:
        """Clear all hot memory (for session end)."""
        self.context = WorkingContext(
            session_id=self.session_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.errors.clear()
        self.decisions.clear()

        # Delete from database
        if self._db_session:
            await self._db_session.execute(
                delete(HotMemoryModel).where(HotMemoryModel.session_id == self.session_id)
            )
            await self._db_session.commit()

    def clear(self) -> None:
        """Clear all hot memory (sync wrapper)."""
        self.context = WorkingContext(
            session_id=self.session_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.errors.clear()
        self.decisions.clear()
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self.clear_async())
        except RuntimeError:
            if self._db_session:
                asyncio.run(self.clear_async())

    def get_summary(self) -> dict:
        """
        Get a summary of hot memory state.

        Returns:
            Dictionary with key statistics
        """
        return {
            "session_id": self.session_id,
            "current_feature": self.context.current_feature,
            "current_task": self.context.current_task,
            "recent_actions_count": len(self.context.recent_actions),
            "recent_files_count": len(self.context.recent_files),
            "active_errors": self.get_error_count(),
            "pending_decisions": len(self.decisions),
            "focus_keywords": self.context.focus_keywords,
        }

    def get_context_for_prompt(self) -> str:
        """
        Generate context string suitable for including in prompts.

        Returns:
            Formatted string with current context
        """
        lines = []

        if self.context.current_feature is not None:
            lines.append(f"Current Feature: #{self.context.current_feature}")

        if self.context.current_task:
            lines.append(f"Current Task: {self.context.current_task}")

        if self.context.focus_keywords:
            lines.append(f"Focus Areas: {', '.join(self.context.focus_keywords)}")

        if self.context.recent_files:
            lines.append(f"Recently Modified: {', '.join(self.context.recent_files[-5:])}")

        active_errors = self.get_active_errors()
        if active_errors:
            lines.append(f"Active Errors: {len(active_errors)} unresolved")
            for err in active_errors[:3]:  # Show top 3
                lines.append(f"  - {err.error_type}: {err.message[:50]}...")

        pending = self.get_pending_decisions()
        if pending:
            lines.append(f"Pending Decisions: {len(pending)}")
            for dec in pending[:2]:  # Show top 2
                lines.append(f"  - {dec.decision_type}: {dec.context[:50]}...")

        return "\n".join(lines) if lines else "No active context."


# =============================================================================
# Factory Functions
# =============================================================================

def create_hot_memory(project_dir: Path, session_id: int) -> HotMemory:
    """
    Create a new HotMemory instance.

    Args:
        project_dir: Project directory path
        session_id: Current session ID

    Returns:
        HotMemory instance
    """
    return HotMemory(project_dir, session_id)


async def create_hot_memory_async(
    project_dir: Path,
    session_id: int,
    session: AsyncSession,
) -> HotMemory:
    """
    Create a HotMemory with async database session.

    Args:
        project_dir: Path to project directory
        session_id: Current session ID
        session: AsyncSession for database operations

    Returns:
        Initialized HotMemory
    """
    memory = HotMemory(project_dir, session_id)
    await memory.init_async(session)
    return memory
