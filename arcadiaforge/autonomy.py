"""
Autonomy Management Module
==========================

Defines and enforces graduated autonomy levels for the autonomous coding agent.
Autonomy levels range from OBSERVE (read-only) to FULL_AUTO (full independence).

The system supports:
- Explicit autonomy level configuration
- Per-action autonomy overrides
- Dynamic level adjustment based on performance
- Integration with security hooks and escalation rules

Storage: All data is persisted in the .arcadia/project.db SQLite database.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.models import (
    AutonomyConfigModel,
    AutonomyMetricsModel,
    AutonomyDecisionModel,
)


class AutonomyLevel(IntEnum):
    """
    Graduated autonomy levels from most restrictive to most permissive.

    Each level includes the capabilities of lower levels.
    """
    OBSERVE = 1      # Read-only, can observe but not modify
    PLAN = 2         # Can plan and suggest, requires approval for actions
    EXECUTE_SAFE = 3 # Can execute pre-approved safe actions
    EXECUTE_REVIEW = 4  # Can execute all actions, human reviews after
    FULL_AUTO = 5    # Full autonomy within security bounds


class ActionCategory(Enum):
    """Categories of actions for autonomy gating."""
    READ = "read"                # Reading files, observing state
    WRITE = "write"              # Writing/modifying files
    EXECUTE = "execute"          # Running commands
    FEATURE_MODIFY = "feature_modify"  # Modifying feature status
    EXTERNAL = "external"        # External side effects (network, APIs)
    DESTRUCTIVE = "destructive"  # Potentially destructive operations


# Default action categories for common tools
DEFAULT_ACTION_CATEGORIES: dict[str, ActionCategory] = {
    "Read": ActionCategory.READ,
    "Glob": ActionCategory.READ,
    "Grep": ActionCategory.READ,
    "Write": ActionCategory.WRITE,
    "Edit": ActionCategory.WRITE,
    "Bash": ActionCategory.EXECUTE,
    "feature_mark": ActionCategory.FEATURE_MODIFY,
    "feature_skip": ActionCategory.FEATURE_MODIFY,
    "feature_add": ActionCategory.FEATURE_MODIFY,
    "puppeteer_navigate": ActionCategory.EXTERNAL,
    "puppeteer_screenshot": ActionCategory.READ,
    "WebFetch": ActionCategory.EXTERNAL,
}

# Minimum autonomy level required for each action category
CATEGORY_REQUIRED_LEVELS: dict[ActionCategory, AutonomyLevel] = {
    ActionCategory.READ: AutonomyLevel.OBSERVE,
    ActionCategory.WRITE: AutonomyLevel.EXECUTE_SAFE,
    ActionCategory.EXECUTE: AutonomyLevel.EXECUTE_SAFE,
    ActionCategory.FEATURE_MODIFY: AutonomyLevel.EXECUTE_REVIEW,
    ActionCategory.EXTERNAL: AutonomyLevel.EXECUTE_SAFE,
    ActionCategory.DESTRUCTIVE: AutonomyLevel.FULL_AUTO,
}


@dataclass
class AutonomyConfig:
    """Configuration for autonomy management."""

    # Base autonomy level
    level: AutonomyLevel = AutonomyLevel.EXECUTE_SAFE

    # Per-action overrides (tool_name -> required level)
    action_levels: dict[str, AutonomyLevel] = field(default_factory=dict)

    # Dynamic adjustment thresholds
    confidence_threshold: float = 0.5  # Below this, reduce effective level
    error_demotion_count: int = 3      # After N consecutive errors, demote
    success_promotion_count: int = 10  # After N consecutive successes, promote

    # Auto-adjustment settings
    auto_adjust: bool = True           # Enable dynamic level adjustment
    min_level: AutonomyLevel = AutonomyLevel.OBSERVE  # Floor for demotion
    max_level: AutonomyLevel = AutonomyLevel.EXECUTE_REVIEW  # Ceiling for promotion

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "level": self.level.value,
            "action_levels": {k: v.value for k, v in self.action_levels.items()},
            "confidence_threshold": self.confidence_threshold,
            "error_demotion_count": self.error_demotion_count,
            "success_promotion_count": self.success_promotion_count,
            "auto_adjust": self.auto_adjust,
            "min_level": self.min_level.value,
            "max_level": self.max_level.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AutonomyConfig":
        """Create from dictionary."""
        return cls(
            level=AutonomyLevel(data.get("level", 3)),
            action_levels={
                k: AutonomyLevel(v)
                for k, v in data.get("action_levels", {}).items()
            },
            confidence_threshold=data.get("confidence_threshold", 0.5),
            error_demotion_count=data.get("error_demotion_count", 3),
            success_promotion_count=data.get("success_promotion_count", 10),
            auto_adjust=data.get("auto_adjust", True),
            min_level=AutonomyLevel(data.get("min_level", 1)),
            max_level=AutonomyLevel(data.get("max_level", 4)),
        )


@dataclass
class AutonomyDecision:
    """Result of an autonomy check."""

    action: str
    tool: str
    allowed: bool
    required_level: AutonomyLevel
    current_level: AutonomyLevel
    effective_level: AutonomyLevel  # After confidence/performance adjustments

    # Reason for decision
    reason: str

    # Suggestions if not allowed
    alternatives: list[str] = field(default_factory=list)
    requires_approval: bool = False
    requires_checkpoint: bool = False

    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "action": self.action,
            "tool": self.tool,
            "allowed": self.allowed,
            "required_level": self.required_level.value,
            "current_level": self.current_level.value,
            "effective_level": self.effective_level.value,
            "reason": self.reason,
            "alternatives": self.alternatives,
            "requires_approval": self.requires_approval,
            "requires_checkpoint": self.requires_checkpoint,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
        }


@dataclass
class PerformanceMetrics:
    """Tracks performance for dynamic autonomy adjustment."""

    consecutive_successes: int = 0
    consecutive_errors: int = 0
    total_actions: int = 0
    total_errors: int = 0

    # History for trend analysis
    recent_outcomes: list[bool] = field(default_factory=list)
    max_history: int = 50

    # Level change history
    level_changes: list[dict] = field(default_factory=list)

    def record_success(self) -> None:
        """Record a successful action."""
        self.consecutive_successes += 1
        self.consecutive_errors = 0
        self.total_actions += 1
        self._add_outcome(True)

    def record_error(self) -> None:
        """Record a failed action."""
        self.consecutive_errors += 1
        self.consecutive_successes = 0
        self.total_actions += 1
        self.total_errors += 1
        self._add_outcome(False)

    def _add_outcome(self, success: bool) -> None:
        """Add outcome to history."""
        self.recent_outcomes.append(success)
        if len(self.recent_outcomes) > self.max_history:
            self.recent_outcomes.pop(0)

    def get_success_rate(self) -> float:
        """Get recent success rate."""
        if not self.recent_outcomes:
            return 1.0
        return sum(self.recent_outcomes) / len(self.recent_outcomes)

    def record_level_change(
        self,
        from_level: AutonomyLevel,
        to_level: AutonomyLevel,
        reason: str
    ) -> None:
        """Record a level change."""
        self.level_changes.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from_level": from_level.value,
            "to_level": to_level.value,
            "reason": reason,
        })

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "consecutive_successes": self.consecutive_successes,
            "consecutive_errors": self.consecutive_errors,
            "total_actions": self.total_actions,
            "total_errors": self.total_errors,
            "recent_outcomes": self.recent_outcomes,
            "level_changes": self.level_changes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PerformanceMetrics":
        """Create from dictionary."""
        metrics = cls(
            consecutive_successes=data.get("consecutive_successes", 0),
            consecutive_errors=data.get("consecutive_errors", 0),
            total_actions=data.get("total_actions", 0),
            total_errors=data.get("total_errors", 0),
            recent_outcomes=data.get("recent_outcomes", []),
        )
        metrics.level_changes = data.get("level_changes", [])
        return metrics


class AutonomyManager:
    """
    Manages autonomy levels and action gating.

    Provides:
    - Action permission checking based on autonomy level
    - Dynamic level adjustment based on performance
    - Per-action overrides
    - Integration points for escalation and human approval

    Storage: All state is persisted in the .arcadia/project.db database.
    """

    def __init__(
        self,
        project_dir: Path,
        config: Optional[AutonomyConfig] = None,
        session_id: int = 0,
    ):
        self.project_dir = Path(project_dir)
        self.session_id = session_id

        # Database session (set via set_session or init_async)
        self._db_session: Optional[AsyncSession] = None

        # Load or create config (sync wrapper for backward compatibility)
        if config:
            self.config = config
        else:
            self.config = self._load_config_sync()

        # Load performance metrics (sync wrapper for backward compatibility)
        self.metrics = self._load_metrics_sync()

        # Current effective level (may differ from config due to adjustments)
        self._effective_level: Optional[AutonomyLevel] = None

        # Custom action checkers
        self._action_checkers: dict[str, Callable[[dict], AutonomyLevel]] = {}

    def set_session(self, session: AsyncSession) -> None:
        """Set the database session for async operations."""
        self._db_session = session

    def update_session_id(self, session_id: int) -> None:
        """Update the current session ID."""
        self.session_id = session_id

    async def init_async(self, session: AsyncSession) -> None:
        """
        Initialize the manager asynchronously with a database session.

        This loads config and metrics from the database.
        """
        self._db_session = session
        self.config = await self._load_config_async()
        self.metrics = await self._load_metrics_async()

    # =========================================================================
    # Async Database Methods
    # =========================================================================

    async def _load_config_async(self) -> AutonomyConfig:
        """Load config from database or create default."""
        if self._db_session is None:
            return AutonomyConfig()

        result = await self._db_session.execute(
            select(AutonomyConfigModel).where(AutonomyConfigModel.id == 1)
        )
        row = result.scalar_one_or_none()

        if row:
            return AutonomyConfig(
                level=AutonomyLevel(row.level),
                action_levels={k: AutonomyLevel(v) for k, v in (row.action_levels or {}).items()},
                confidence_threshold=row.confidence_threshold,
                error_demotion_count=row.error_demotion_count,
                success_promotion_count=row.success_promotion_count,
                auto_adjust=row.auto_adjust,
                min_level=AutonomyLevel(row.min_level),
                max_level=AutonomyLevel(row.max_level),
            )
        return AutonomyConfig()

    async def _save_config_async(self) -> None:
        """Save config to database."""
        if self._db_session is None:
            return

        # Check if config exists
        result = await self._db_session.execute(
            select(AutonomyConfigModel).where(AutonomyConfigModel.id == 1)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing
            await self._db_session.execute(
                update(AutonomyConfigModel)
                .where(AutonomyConfigModel.id == 1)
                .values(
                    level=self.config.level.value,
                    action_levels={k: v.value for k, v in self.config.action_levels.items()},
                    confidence_threshold=self.config.confidence_threshold,
                    error_demotion_count=self.config.error_demotion_count,
                    success_promotion_count=self.config.success_promotion_count,
                    auto_adjust=self.config.auto_adjust,
                    min_level=self.config.min_level.value,
                    max_level=self.config.max_level.value,
                )
            )
        else:
            # Insert new
            new_config = AutonomyConfigModel(
                id=1,
                level=self.config.level.value,
                action_levels={k: v.value for k, v in self.config.action_levels.items()},
                confidence_threshold=self.config.confidence_threshold,
                error_demotion_count=self.config.error_demotion_count,
                success_promotion_count=self.config.success_promotion_count,
                auto_adjust=self.config.auto_adjust,
                min_level=self.config.min_level.value,
                max_level=self.config.max_level.value,
            )
            self._db_session.add(new_config)

        await self._db_session.commit()

    async def _load_metrics_async(self) -> PerformanceMetrics:
        """Load metrics from database or create default."""
        if self._db_session is None:
            return PerformanceMetrics()

        result = await self._db_session.execute(
            select(AutonomyMetricsModel).where(AutonomyMetricsModel.id == 1)
        )
        row = result.scalar_one_or_none()

        if row:
            metrics = PerformanceMetrics(
                consecutive_successes=row.consecutive_successes,
                consecutive_errors=row.consecutive_errors,
                total_actions=row.total_actions,
                total_errors=row.total_errors,
                recent_outcomes=row.recent_outcomes or [],
            )
            metrics.level_changes = row.level_changes or []
            return metrics
        return PerformanceMetrics()

    async def _save_metrics_async(self) -> None:
        """Save metrics to database."""
        if self._db_session is None:
            return

        # Check if metrics exists
        result = await self._db_session.execute(
            select(AutonomyMetricsModel).where(AutonomyMetricsModel.id == 1)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing
            await self._db_session.execute(
                update(AutonomyMetricsModel)
                .where(AutonomyMetricsModel.id == 1)
                .values(
                    consecutive_successes=self.metrics.consecutive_successes,
                    consecutive_errors=self.metrics.consecutive_errors,
                    total_actions=self.metrics.total_actions,
                    total_errors=self.metrics.total_errors,
                    recent_outcomes=self.metrics.recent_outcomes,
                    level_changes=self.metrics.level_changes,
                )
            )
        else:
            # Insert new
            new_metrics = AutonomyMetricsModel(
                id=1,
                consecutive_successes=self.metrics.consecutive_successes,
                consecutive_errors=self.metrics.consecutive_errors,
                total_actions=self.metrics.total_actions,
                total_errors=self.metrics.total_errors,
                recent_outcomes=self.metrics.recent_outcomes,
                level_changes=self.metrics.level_changes,
            )
            self._db_session.add(new_metrics)

        await self._db_session.commit()

    async def _log_decision_async(self, decision: AutonomyDecision) -> None:
        """Log an autonomy decision to the database."""
        if self._db_session is None:
            return

        new_decision = AutonomyDecisionModel(
            session_id=self.session_id,
            action=decision.action,
            tool=decision.tool,
            allowed=decision.allowed,
            required_level=decision.required_level.value,
            current_level=decision.current_level.value,
            effective_level=decision.effective_level.value,
            reason=decision.reason,
            alternatives=decision.alternatives,
            requires_approval=decision.requires_approval,
            requires_checkpoint=decision.requires_checkpoint,
            confidence=decision.confidence,
        )
        self._db_session.add(new_decision)
        await self._db_session.commit()

    # =========================================================================
    # Sync Wrappers (for backward compatibility)
    # =========================================================================

    def _load_config_sync(self) -> AutonomyConfig:
        """Synchronous wrapper for loading config."""
        if self._db_session is not None:
            # Use existing async session via new event loop
            try:
                loop = asyncio.get_running_loop()
                # If we're in an async context, we can't use asyncio.run
                # Just return default and let init_async handle it
                return AutonomyConfig()
            except RuntimeError:
                # No running loop, safe to create one
                return asyncio.run(self._load_config_async())
        return AutonomyConfig()

    def _load_metrics_sync(self) -> PerformanceMetrics:
        """Synchronous wrapper for loading metrics."""
        if self._db_session is not None:
            try:
                loop = asyncio.get_running_loop()
                return PerformanceMetrics()
            except RuntimeError:
                return asyncio.run(self._load_metrics_async())
        return PerformanceMetrics()

    def _save_config(self) -> None:
        """Save config (sync wrapper)."""
        if self._db_session is not None:
            try:
                loop = asyncio.get_running_loop()
                # Schedule as task if in async context
                asyncio.create_task(self._save_config_async())
            except RuntimeError:
                asyncio.run(self._save_config_async())

    def _save_metrics(self) -> None:
        """Save metrics (sync wrapper)."""
        if self._db_session is not None:
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(self._save_metrics_async())
            except RuntimeError:
                asyncio.run(self._save_metrics_async())

    def _log_decision(self, decision: AutonomyDecision) -> None:
        """Log an autonomy decision (sync wrapper)."""
        if self._db_session is not None:
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(self._log_decision_async(decision))
            except RuntimeError:
                asyncio.run(self._log_decision_async(decision))

    @property
    def current_level(self) -> AutonomyLevel:
        """Get the configured autonomy level."""
        return self.config.level

    @property
    def effective_level(self) -> AutonomyLevel:
        """Get the effective autonomy level after adjustments."""
        if self._effective_level is not None:
            return self._effective_level
        return self.config.level

    def set_level(self, level: AutonomyLevel, reason: str = "manual") -> None:
        """Set the autonomy level."""
        old_level = self.config.level
        self.config.level = level
        self._effective_level = level
        self._save_config()

        if old_level != level:
            self.metrics.record_level_change(old_level, level, reason)
            self._save_metrics()

    def get_effective_level(self, confidence: Optional[float] = None) -> AutonomyLevel:
        """
        Get effective autonomy level, considering confidence and performance.

        Args:
            confidence: Current decision confidence (0.0-1.0)

        Returns:
            Effective autonomy level
        """
        base_level = self.config.level

        # Apply confidence adjustment
        if confidence is not None and confidence < self.config.confidence_threshold:
            # Reduce level for low confidence
            if confidence < 0.3:
                reduction = 2
            else:
                reduction = 1
            # Ensure we don't go below valid levels
            new_level_value = max(self.config.min_level.value, base_level - reduction)
            new_level_value = max(1, new_level_value)  # Ensure at least OBSERVE
            adjusted = AutonomyLevel(new_level_value)
            return adjusted

        # Apply performance adjustment if auto-adjust is enabled
        if self.config.auto_adjust:
            # Demote on consecutive errors
            if self.metrics.consecutive_errors >= self.config.error_demotion_count:
                new_level_value = max(self.config.min_level.value, base_level - 1)
                new_level_value = max(1, new_level_value)  # Ensure at least OBSERVE
                return AutonomyLevel(new_level_value)

        return base_level

    def check_action(
        self,
        tool: str,
        action_input: Optional[dict] = None,
        confidence: Optional[float] = None,
    ) -> AutonomyDecision:
        """
        Check if an action is allowed at the current autonomy level.

        Args:
            tool: The tool being invoked
            action_input: The tool's input parameters
            confidence: Confidence in this action (0.0-1.0)

        Returns:
            AutonomyDecision with permission result and guidance
        """
        action_input = action_input or {}

        # Get required level for this action
        required_level = self._get_required_level(tool, action_input)

        # Get effective level
        effective = self.get_effective_level(confidence)

        # Check permission
        allowed = effective >= required_level

        # Build decision
        decision = AutonomyDecision(
            action=self._summarize_action(tool, action_input),
            tool=tool,
            allowed=allowed,
            required_level=required_level,
            current_level=self.config.level,
            effective_level=effective,
            reason=self._build_reason(allowed, required_level, effective, tool),
            confidence=confidence,
        )

        # Add alternatives and flags if not allowed
        if not allowed:
            decision.alternatives = self._suggest_alternatives(tool, required_level)
            decision.requires_approval = True

            # Check if checkpoint recommended
            if required_level >= AutonomyLevel.EXECUTE_REVIEW:
                decision.requires_checkpoint = True

        # Log the decision
        self._log_decision(decision)

        return decision

    def _get_required_level(self, tool: str, action_input: dict) -> AutonomyLevel:
        """Get the required autonomy level for an action."""
        # Check for per-action override in config
        if tool in self.config.action_levels:
            return self.config.action_levels[tool]

        # Check for custom checker
        if tool in self._action_checkers:
            return self._action_checkers[tool](action_input)

        # Get category and lookup required level
        category = DEFAULT_ACTION_CATEGORIES.get(tool, ActionCategory.EXECUTE)
        return CATEGORY_REQUIRED_LEVELS.get(category, AutonomyLevel.EXECUTE_SAFE)

    def _summarize_action(self, tool: str, action_input: dict) -> str:
        """Create a brief summary of the action."""
        if tool == "Write" and "file_path" in action_input:
            return f"Write to {Path(action_input['file_path']).name}"
        elif tool == "Edit" and "file_path" in action_input:
            return f"Edit {Path(action_input['file_path']).name}"
        elif tool == "Bash" and "command" in action_input:
            cmd = action_input["command"][:50]
            return f"Run: {cmd}..."
        elif tool == "feature_mark" and "index" in action_input:
            return f"Mark feature #{action_input['index']} as passing"
        elif tool == "Read" and "file_path" in action_input:
            return f"Read {Path(action_input['file_path']).name}"
        else:
            return f"{tool} operation"

    def _build_reason(
        self,
        allowed: bool,
        required: AutonomyLevel,
        effective: AutonomyLevel,
        tool: str
    ) -> str:
        """Build explanation for the decision."""
        if allowed:
            return (
                f"Action allowed: {tool} requires level {required.name} "
                f"(current effective: {effective.name})"
            )
        else:
            return (
                f"Action denied: {tool} requires level {required.name} "
                f"but effective level is {effective.name}"
            )

    def _suggest_alternatives(
        self,
        tool: str,
        required_level: AutonomyLevel
    ) -> list[str]:
        """Suggest alternatives when action is denied."""
        alternatives = []

        if required_level == AutonomyLevel.FULL_AUTO:
            alternatives.append("Request human approval for this action")
            alternatives.append("Create a checkpoint before proceeding")

        if required_level >= AutonomyLevel.EXECUTE_REVIEW:
            alternatives.append("Queue action for human review")
            alternatives.append(f"Temporarily elevate to level {required_level.name}")

        if tool == "Write":
            alternatives.append("Use Read to review current state first")

        if tool == "Bash":
            alternatives.append("Use a safer alternative command")
            alternatives.append("Request approval for command execution")

        return alternatives

    def register_action_checker(
        self,
        tool: str,
        checker: Callable[[dict], AutonomyLevel]
    ) -> None:
        """
        Register a custom checker for determining required level.

        Args:
            tool: Tool name
            checker: Function that takes action_input and returns required level
        """
        self._action_checkers[tool] = checker

    def record_outcome(self, success: bool) -> Optional[AutonomyLevel]:
        """
        Record the outcome of an action and potentially adjust level.

        Args:
            success: Whether the action succeeded

        Returns:
            New level if changed, None otherwise
        """
        if success:
            self.metrics.record_success()
        else:
            self.metrics.record_error()

        new_level = None

        # Check for auto-adjustment
        if self.config.auto_adjust:
            current = self.config.level

            # Check for demotion
            if self.metrics.consecutive_errors >= self.config.error_demotion_count:
                new_level = max(self.config.min_level, AutonomyLevel(current - 1))
                if new_level != current:
                    self.set_level(
                        new_level,
                        f"Demoted due to {self.metrics.consecutive_errors} consecutive errors"
                    )

            # Check for promotion
            elif self.metrics.consecutive_successes >= self.config.success_promotion_count:
                new_level = min(self.config.max_level, AutonomyLevel(current + 1))
                if new_level != current:
                    self.set_level(
                        new_level,
                        f"Promoted due to {self.metrics.consecutive_successes} consecutive successes"
                    )
                    # Reset counter after promotion
                    self.metrics.consecutive_successes = 0

        self._save_metrics()
        return new_level

    def request_elevation(
        self,
        target_level: AutonomyLevel,
        reason: str,
        duration_actions: int = 1
    ) -> dict:
        """
        Request temporary elevation of autonomy level.

        Args:
            target_level: Level to elevate to
            reason: Why elevation is needed
            duration_actions: How many actions the elevation lasts

        Returns:
            Elevation request details for human approval
        """
        return {
            "request_type": "autonomy_elevation",
            "current_level": self.config.level.name,
            "target_level": target_level.name,
            "reason": reason,
            "duration_actions": duration_actions,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "requires_approval": True,
        }

    def get_status(self) -> dict:
        """Get current autonomy status."""
        return {
            "configured_level": self.config.level.name,
            "effective_level": self.effective_level.name,
            "auto_adjust": self.config.auto_adjust,
            "performance": {
                "consecutive_successes": self.metrics.consecutive_successes,
                "consecutive_errors": self.metrics.consecutive_errors,
                "success_rate": self.metrics.get_success_rate(),
                "total_actions": self.metrics.total_actions,
            },
            "thresholds": {
                "confidence": self.config.confidence_threshold,
                "error_demotion": self.config.error_demotion_count,
                "success_promotion": self.config.success_promotion_count,
            },
            "bounds": {
                "min_level": self.config.min_level.name,
                "max_level": self.config.max_level.name,
            },
        }

    async def get_decision_history_async(
        self,
        limit: int = 50,
        tool: Optional[str] = None,
        allowed_only: Optional[bool] = None
    ) -> list[dict]:
        """
        Get recent autonomy decisions from the database.

        Args:
            limit: Maximum number of decisions to return
            tool: Filter by tool name
            allowed_only: Filter by allowed status

        Returns:
            List of decision records
        """
        if self._db_session is None:
            return []

        # Build query
        query = select(AutonomyDecisionModel).order_by(
            AutonomyDecisionModel.timestamp.desc()
        )

        # Apply filters
        if tool:
            query = query.where(AutonomyDecisionModel.tool == tool)
        if allowed_only is not None:
            query = query.where(AutonomyDecisionModel.allowed == allowed_only)

        query = query.limit(limit)

        result = await self._db_session.execute(query)
        rows = result.scalars().all()

        # Convert to dicts and reverse to get chronological order
        decisions = []
        for row in reversed(rows):
            decisions.append({
                "action": row.action,
                "tool": row.tool,
                "allowed": row.allowed,
                "required_level": row.required_level,
                "current_level": row.current_level,
                "effective_level": row.effective_level,
                "reason": row.reason,
                "alternatives": row.alternatives or [],
                "requires_approval": row.requires_approval,
                "requires_checkpoint": row.requires_checkpoint,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "confidence": row.confidence,
            })

        return decisions

    def get_decision_history(
        self,
        limit: int = 50,
        tool: Optional[str] = None,
        allowed_only: Optional[bool] = None
    ) -> list[dict]:
        """
        Get recent autonomy decisions (sync wrapper).

        Args:
            limit: Maximum number of decisions to return
            tool: Filter by tool name
            allowed_only: Filter by allowed status

        Returns:
            List of decision records
        """
        if self._db_session is None:
            return []

        try:
            loop = asyncio.get_running_loop()
            # Can't run sync in async context, return empty
            return []
        except RuntimeError:
            return asyncio.run(self.get_decision_history_async(limit, tool, allowed_only))

    async def reset_metrics_async(self) -> None:
        """Reset performance metrics (async)."""
        self.metrics = PerformanceMetrics()
        await self._save_metrics_async()

    def reset_metrics(self) -> None:
        """Reset performance metrics."""
        self.metrics = PerformanceMetrics()
        self._save_metrics()


def create_autonomy_manager(
    project_dir: Path,
    level: AutonomyLevel = AutonomyLevel.EXECUTE_SAFE,
    auto_adjust: bool = True,
    session_id: int = 0,
) -> AutonomyManager:
    """
    Convenience function to create an AutonomyManager.

    Args:
        project_dir: Project directory
        level: Initial autonomy level
        auto_adjust: Enable dynamic level adjustment
        session_id: Current session ID for decision logging

    Returns:
        Configured AutonomyManager
    """
    config = AutonomyConfig(level=level, auto_adjust=auto_adjust)
    return AutonomyManager(project_dir, config, session_id=session_id)


async def create_autonomy_manager_async(
    project_dir: Path,
    session: AsyncSession,
    level: AutonomyLevel = AutonomyLevel.EXECUTE_SAFE,
    auto_adjust: bool = True,
    session_id: int = 0,
) -> AutonomyManager:
    """
    Create an AutonomyManager with async database initialization.

    Args:
        project_dir: Project directory
        session: Async database session
        level: Initial autonomy level
        auto_adjust: Enable dynamic level adjustment
        session_id: Current session ID for decision logging

    Returns:
        Configured AutonomyManager with database connection
    """
    config = AutonomyConfig(level=level, auto_adjust=auto_adjust)
    manager = AutonomyManager(project_dir, config, session_id=session_id)
    await manager.init_async(session)
    return manager
