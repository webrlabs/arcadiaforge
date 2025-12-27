"""
Escalation Rules Engine for Autonomous Coding Framework
========================================================

Provides explicit rules for when to escalate decisions to humans.
Rules are evaluated against context and can trigger human injection points.

Storage: All data is persisted in the .arcadia/project.db SQLite database.

Usage:
    from arcadiaforge.escalation import EscalationEngine, EscalationContext

    engine = EscalationEngine(project_dir)

    # Evaluate context against all rules
    result = engine.evaluate(EscalationContext(
        confidence=0.3,
        consecutive_failures=5,
        feature_index=10
    ))

    if result:
        # Escalation triggered
        print(f"Rule triggered: {result.rule.name}")
        print(f"Recommended action: {result.recommended_action}")
"""

import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.models import EscalationRuleModel, EscalationLogModel


class InjectionType(Enum):
    """Types of human injection points (mirrored from human_interface.py for decoupling)."""
    DECISION = "decision"           # Choose between options
    APPROVAL = "approval"           # Yes/no for risky action
    GUIDANCE = "guidance"           # Free-form input needed
    REVIEW = "review"               # Human should review output
    REDIRECT = "redirect"           # Change goals/direction


@dataclass
class EscalationRule:
    """
    A rule that defines when to escalate to human.

    Rules are evaluated against context dictionaries. When conditions match,
    the rule triggers an escalation with a specific injection type.
    """
    rule_id: str                    # Unique identifier
    name: str                       # Human-readable name
    description: str                # What this rule catches

    # Condition (evaluated against context dict)
    # This is a callable that takes context and returns bool
    # We can't serialize callables, so we use a condition_type + params approach
    condition_type: str             # Type of condition check
    condition_params: dict          # Parameters for the condition

    # Escalation details
    severity: int                   # 1-5 (5 = highest)
    injection_type: str             # InjectionType value
    message_template: str           # Template for escalation message
    suggested_actions: list[str]    # Actions the human can take

    # Behavior
    auto_pause: bool = False        # Should agent pause automatically?
    timeout_seconds: int = 300      # Default timeout for human response
    default_action: Optional[str] = None  # Default if timeout

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "EscalationRule":
        """Create EscalationRule from dictionary."""
        return cls(**data)


@dataclass
class EscalationContext:
    """
    Context for evaluating escalation rules.

    Pass relevant information about the current situation.
    Rules will check various fields in this context.
    """
    # Confidence
    confidence: float = 1.0

    # Feature context
    feature_index: Optional[int] = None
    consecutive_failures: int = 0
    previously_passing: bool = False
    currently_passing: bool = True

    # Action context
    action: Optional[str] = None
    is_irreversible: bool = False
    affects_source_of_truth: bool = False

    # Error context
    error_message: Optional[str] = None
    error_count: int = 0

    # Decision context
    decision_type: Optional[str] = None
    alternatives_count: int = 0

    # Custom context
    custom: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for condition evaluation."""
        result = asdict(self)
        # Flatten custom dict into main dict
        custom = result.pop("custom", {})
        result.update(custom)
        return result


@dataclass
class EscalationResult:
    """
    Result of an escalation rule being triggered.
    """
    rule: EscalationRule
    context: dict
    timestamp: str
    message: str                    # Formatted message
    recommended_action: str         # First suggested action


class EscalationEngine:
    """
    Evaluates escalation rules against context.

    The engine maintains a set of rules and can evaluate any context
    against all rules, returning the first (or highest severity) match.

    Storage: All rules and logs are persisted in the .arcadia/project.db database.
    """

    def __init__(
        self,
        project_dir: Path,
        load_custom: bool = True,
        session_id: int = 0,
    ):
        """
        Initialize EscalationEngine.

        Args:
            project_dir: Path to project directory
            load_custom: Whether to load custom rules from database
            session_id: Current session ID for logging
        """
        self.project_dir = Path(project_dir)
        self.session_id = session_id

        # Database session (set via set_session or init_async)
        self._db_session: Optional[AsyncSession] = None

        # Start with default rules
        self.rules: list[EscalationRule] = self._get_default_rules()

        # Sort default rules by severity (highest first)
        self.rules.sort(key=lambda r: r.severity, reverse=True)

        # Custom rules loaded flag (for sync backward compatibility)
        self._custom_rules_loaded = False
        self._load_custom_on_init = load_custom

    def set_session(self, session: AsyncSession) -> None:
        """Set the database session for async operations."""
        self._db_session = session

    def update_session_id(self, session_id: int) -> None:
        """Update the current session ID."""
        self.session_id = session_id

    async def init_async(self, session: AsyncSession) -> None:
        """
        Initialize the engine asynchronously with a database session.

        This loads custom rules from the database.
        """
        self._db_session = session
        if self._load_custom_on_init:
            await self._load_custom_rules_async()

    def _get_default_rules(self) -> list[EscalationRule]:
        """Get the default escalation rules."""
        return [
            EscalationRule(
                rule_id="low_confidence",
                name="Low Confidence Decision",
                description="Agent confidence is below 50% for a decision",
                condition_type="threshold_below",
                condition_params={"field": "confidence", "threshold": 0.5},
                severity=3,
                injection_type=InjectionType.DECISION.value,
                message_template="Agent confidence is {confidence:.0%} for: {decision_type}",
                suggested_actions=["Approve agent choice", "Select alternative", "Provide guidance"],
                auto_pause=False,
                timeout_seconds=300,
                default_action="Approve agent choice",
            ),
            EscalationRule(
                rule_id="very_low_confidence",
                name="Very Low Confidence Decision",
                description="Agent confidence is below 30%",
                condition_type="threshold_below",
                condition_params={"field": "confidence", "threshold": 0.3},
                severity=4,
                injection_type=InjectionType.GUIDANCE.value,
                message_template="Agent confidence is very low ({confidence:.0%}). Context: {action}",
                suggested_actions=["Provide guidance", "Take over manually", "Skip this task"],
                auto_pause=True,
                timeout_seconds=600,
                default_action=None,  # No default - must wait for human
            ),
            EscalationRule(
                rule_id="feature_regression",
                name="Feature Regression Detected",
                description="A previously passing feature is now failing",
                condition_type="regression",
                condition_params={},
                severity=4,
                injection_type=InjectionType.REVIEW.value,
                message_template="Feature #{feature_index} regressed from passing to failing",
                suggested_actions=["Investigate", "Rollback to checkpoint", "Accept regression"],
                auto_pause=True,
                timeout_seconds=600,
                default_action="Investigate",
            ),
            EscalationRule(
                rule_id="multiple_failures",
                name="Multiple Consecutive Failures",
                description="Agent has failed 3+ times on the same feature",
                condition_type="threshold_above",
                condition_params={"field": "consecutive_failures", "threshold": 3},
                severity=4,
                injection_type=InjectionType.GUIDANCE.value,
                message_template="Agent has failed {consecutive_failures} times on feature #{feature_index}",
                suggested_actions=["Skip feature", "Provide hints", "Take over manually"],
                auto_pause=True,
                timeout_seconds=600,
                default_action="Skip feature",
            ),
            EscalationRule(
                rule_id="many_failures",
                name="Many Consecutive Failures",
                description="Agent has failed 5+ times - serious stuck state",
                condition_type="threshold_above",
                condition_params={"field": "consecutive_failures", "threshold": 5},
                severity=5,
                injection_type=InjectionType.REDIRECT.value,
                message_template="Agent stuck: {consecutive_failures} failures on feature #{feature_index}",
                suggested_actions=["Skip feature", "Change approach", "Abort session"],
                auto_pause=True,
                timeout_seconds=900,
                default_action=None,  # Must wait for human
            ),
            EscalationRule(
                rule_id="irreversible_action",
                name="Irreversible Action Requested",
                description="Agent wants to perform an action that cannot be undone",
                condition_type="equals",
                condition_params={"field": "is_irreversible", "value": True},
                severity=5,
                injection_type=InjectionType.APPROVAL.value,
                message_template="Agent wants to perform irreversible action: {action}",
                suggested_actions=["Approve", "Deny", "Request checkpoint first"],
                auto_pause=True,
                timeout_seconds=600,
                default_action="Deny",  # Safe default
            ),
            EscalationRule(
                rule_id="source_of_truth_change",
                name="Source of Truth Modification",
                description="Agent wants to modify the feature database or other source of truth",
                condition_type="equals",
                condition_params={"field": "affects_source_of_truth", "value": True},
                severity=3,
                injection_type=InjectionType.APPROVAL.value,
                message_template="Agent wants to modify source of truth: {action}",
                suggested_actions=["Approve", "Deny", "Review first"],
                auto_pause=False,
                timeout_seconds=300,
                default_action="Approve",  # Usually OK if using proper tools
            ),
            EscalationRule(
                rule_id="repeated_errors",
                name="Repeated Errors",
                description="Same type of error occurring multiple times",
                condition_type="threshold_above",
                condition_params={"field": "error_count", "threshold": 3},
                severity=3,
                injection_type=InjectionType.REVIEW.value,
                message_template="Error occurring repeatedly ({error_count} times): {error_message}",
                suggested_actions=["Investigate error", "Skip task", "Change approach"],
                auto_pause=False,
                timeout_seconds=300,
                default_action="Investigate error",
            ),
        ]

    # =========================================================================
    # Async Database Methods
    # =========================================================================

    async def _load_custom_rules_async(self) -> None:
        """Load custom rules from database."""
        if self._db_session is None:
            return

        result = await self._db_session.execute(
            select(EscalationRuleModel).where(EscalationRuleModel.is_enabled == True)
        )
        rows = result.scalars().all()

        for row in rows:
            rule = EscalationRule(
                rule_id=row.rule_id,
                name=row.name,
                description=row.description,
                condition_type=row.condition_type,
                condition_params=row.condition_params or {},
                severity=row.severity,
                injection_type=row.injection_type,
                message_template=row.message_template,
                suggested_actions=row.suggested_actions or [],
                auto_pause=row.auto_pause,
                timeout_seconds=row.timeout_seconds,
                default_action=row.default_action,
            )
            # Add or replace rule
            self.rules = [r for r in self.rules if r.rule_id != rule.rule_id]
            self.rules.append(rule)

        # Sort by severity (highest first)
        self.rules.sort(key=lambda r: r.severity, reverse=True)
        self._custom_rules_loaded = True

    async def _save_custom_rules_async(self) -> None:
        """Save custom rules to database."""
        if self._db_session is None:
            return

        # Get default rule IDs to exclude
        default_ids = {r.rule_id for r in self._get_default_rules()}
        custom_rules = [r for r in self.rules if r.rule_id not in default_ids]

        for rule in custom_rules:
            # Check if rule exists
            result = await self._db_session.execute(
                select(EscalationRuleModel).where(EscalationRuleModel.rule_id == rule.rule_id)
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update existing
                await self._db_session.execute(
                    update(EscalationRuleModel)
                    .where(EscalationRuleModel.rule_id == rule.rule_id)
                    .values(
                        name=rule.name,
                        description=rule.description,
                        condition_type=rule.condition_type,
                        condition_params=rule.condition_params,
                        severity=rule.severity,
                        injection_type=rule.injection_type,
                        message_template=rule.message_template,
                        suggested_actions=rule.suggested_actions,
                        auto_pause=rule.auto_pause,
                        timeout_seconds=rule.timeout_seconds,
                        default_action=rule.default_action,
                        is_custom=True,
                        is_enabled=True,
                    )
                )
            else:
                # Insert new
                new_rule = EscalationRuleModel(
                    rule_id=rule.rule_id,
                    name=rule.name,
                    description=rule.description,
                    condition_type=rule.condition_type,
                    condition_params=rule.condition_params,
                    severity=rule.severity,
                    injection_type=rule.injection_type,
                    message_template=rule.message_template,
                    suggested_actions=rule.suggested_actions,
                    auto_pause=rule.auto_pause,
                    timeout_seconds=rule.timeout_seconds,
                    default_action=rule.default_action,
                    is_custom=True,
                    is_enabled=True,
                )
                self._db_session.add(new_rule)

        await self._db_session.commit()

    async def _log_escalation_async(self, result: EscalationResult) -> None:
        """Log an escalation to the database."""
        if self._db_session is None:
            return

        log_entry = EscalationLogModel(
            session_id=self.session_id,
            rule_id=result.rule.rule_id,
            severity=result.rule.severity,
            message=result.message,
            context_summary={
                k: v for k, v in result.context.items()
                if k in ["confidence", "feature_index", "consecutive_failures", "action", "error_message"]
            },
        )
        self._db_session.add(log_entry)
        await self._db_session.commit()

    async def get_escalation_history_async(
        self,
        limit: int = 50,
        rule_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Get recent escalation history from database.

        Args:
            limit: Maximum entries to return
            rule_id: Optional filter by rule ID

        Returns:
            List of escalation log entries (newest first)
        """
        if self._db_session is None:
            return []

        query = select(EscalationLogModel).order_by(
            EscalationLogModel.timestamp.desc()
        )

        if rule_id:
            query = query.where(EscalationLogModel.rule_id == rule_id)

        query = query.limit(limit)

        result = await self._db_session.execute(query)
        rows = result.scalars().all()

        entries = []
        for row in rows:
            entries.append({
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "rule_id": row.rule_id,
                "severity": row.severity,
                "message": row.message,
                "context_summary": row.context_summary or {},
            })

        return entries

    async def remove_rule_async(self, rule_id: str) -> bool:
        """
        Remove a rule by ID from database.

        Args:
            rule_id: Rule ID to remove

        Returns:
            True if removed, False if not found
        """
        # Remove from in-memory list
        original_count = len(self.rules)
        self.rules = [r for r in self.rules if r.rule_id != rule_id]

        if len(self.rules) < original_count:
            # Mark as disabled in database (soft delete)
            if self._db_session is not None:
                await self._db_session.execute(
                    update(EscalationRuleModel)
                    .where(EscalationRuleModel.rule_id == rule_id)
                    .values(is_enabled=False)
                )
                await self._db_session.commit()
            return True
        return False

    # =========================================================================
    # Sync Wrappers (for backward compatibility)
    # =========================================================================

    def _load_custom_rules(self) -> None:
        """Load custom rules (sync wrapper)."""
        if self._db_session is not None and not self._custom_rules_loaded:
            try:
                asyncio.get_running_loop()
                # In async context, skip - will be loaded via init_async
            except RuntimeError:
                asyncio.run(self._load_custom_rules_async())

    def _save_custom_rules(self) -> None:
        """Save custom rules (sync wrapper)."""
        if self._db_session is not None:
            try:
                asyncio.get_running_loop()
                asyncio.create_task(self._save_custom_rules_async())
            except RuntimeError:
                asyncio.run(self._save_custom_rules_async())

    def _evaluate_condition(self, rule: EscalationRule, context: dict) -> bool:
        """
        Evaluate a rule's condition against context.

        Args:
            rule: The rule to evaluate
            context: Context dictionary

        Returns:
            True if condition matches
        """
        ctype = rule.condition_type
        params = rule.condition_params

        if ctype == "threshold_below":
            field = params.get("field", "")
            threshold = params.get("threshold", 0)
            value = context.get(field, 1.0)
            return value < threshold

        elif ctype == "threshold_above":
            field = params.get("field", "")
            threshold = params.get("threshold", 0)
            value = context.get(field, 0)
            return value >= threshold

        elif ctype == "equals":
            field = params.get("field", "")
            expected = params.get("value")
            return context.get(field) == expected

        elif ctype == "not_equals":
            field = params.get("field", "")
            expected = params.get("value")
            return context.get(field) != expected

        elif ctype == "regression":
            # Special case: check for feature regression
            return (
                context.get("previously_passing", False)
                and not context.get("currently_passing", True)
            )

        elif ctype == "contains":
            field = params.get("field", "")
            substring = params.get("substring", "")
            value = str(context.get(field, ""))
            return substring.lower() in value.lower()

        elif ctype == "custom":
            # Custom conditions can be added via extension
            func_name = params.get("function", "")
            if hasattr(self, f"_condition_{func_name}"):
                func = getattr(self, f"_condition_{func_name}")
                return func(context, params)
            return False

        return False

    def _format_message(self, template: str, context: dict) -> str:
        """Format a message template with context values."""
        try:
            return template.format(**context)
        except KeyError:
            # If some keys are missing, do a safe format
            result = template
            for key, value in context.items():
                result = result.replace(f"{{{key}}}", str(value))
                # Handle format specs like {confidence:.0%}
                result = result.replace(f"{{{key}:.0%}}", f"{value:.0%}" if isinstance(value, (int, float)) else str(value))
            return result

    def evaluate(
        self,
        context: EscalationContext | dict,
        return_all: bool = False,
    ) -> Optional[EscalationResult] | list[EscalationResult]:
        """
        Evaluate all rules against the given context.

        Args:
            context: EscalationContext or dict with context values
            return_all: If True, return all matching rules; if False, return highest severity

        Returns:
            EscalationResult for highest severity match, or list if return_all=True
        """
        if isinstance(context, EscalationContext):
            ctx_dict = context.to_dict()
        else:
            ctx_dict = dict(context)

        matches: list[EscalationResult] = []

        # Evaluate rules (already sorted by severity, highest first)
        for rule in self.rules:
            if self._evaluate_condition(rule, ctx_dict):
                message = self._format_message(rule.message_template, ctx_dict)
                result = EscalationResult(
                    rule=rule,
                    context=ctx_dict,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    message=message,
                    recommended_action=rule.suggested_actions[0] if rule.suggested_actions else "Review",
                )
                matches.append(result)

                # Log the escalation
                self._log_escalation(result)

        if return_all:
            return matches

        # Return highest severity (first match since sorted)
        return matches[0] if matches else None

    def _log_escalation(self, result: EscalationResult) -> None:
        """Log an escalation (sync wrapper)."""
        if self._db_session is not None:
            try:
                asyncio.get_running_loop()
                asyncio.create_task(self._log_escalation_async(result))
            except RuntimeError:
                asyncio.run(self._log_escalation_async(result))

    async def add_rule_async(self, rule: EscalationRule) -> None:
        """
        Add a custom rule (async).

        Args:
            rule: The rule to add
        """
        # Remove existing rule with same ID
        self.rules = [r for r in self.rules if r.rule_id != rule.rule_id]
        self.rules.append(rule)
        # Re-sort by severity
        self.rules.sort(key=lambda r: r.severity, reverse=True)
        # Save to database
        await self._save_custom_rules_async()

    def add_rule(self, rule: EscalationRule) -> None:
        """
        Add a custom rule.

        Args:
            rule: The rule to add
        """
        # Remove existing rule with same ID
        self.rules = [r for r in self.rules if r.rule_id != rule.rule_id]
        self.rules.append(rule)
        # Re-sort by severity
        self.rules.sort(key=lambda r: r.severity, reverse=True)
        # Save to database
        self._save_custom_rules()

    def remove_rule(self, rule_id: str) -> bool:
        """
        Remove a rule by ID (sync wrapper).

        Args:
            rule_id: Rule ID to remove

        Returns:
            True if removed, False if not found
        """
        original_count = len(self.rules)
        self.rules = [r for r in self.rules if r.rule_id != rule_id]
        if len(self.rules) < original_count:
            if self._db_session is not None:
                try:
                    asyncio.get_running_loop()
                    asyncio.create_task(self.remove_rule_async(rule_id))
                except RuntimeError:
                    asyncio.run(self.remove_rule_async(rule_id))
            return True
        return False

    def get_rules(self) -> list[EscalationRule]:
        """Get all rules sorted by severity."""
        return list(self.rules)

    def get_rule(self, rule_id: str) -> Optional[EscalationRule]:
        """Get a specific rule by ID."""
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def get_escalation_history(
        self,
        limit: int = 50,
        rule_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Get recent escalation history (sync wrapper).

        Args:
            limit: Maximum entries to return
            rule_id: Optional filter by rule ID

        Returns:
            List of escalation log entries (newest first)
        """
        if self._db_session is None:
            return []

        try:
            asyncio.get_running_loop()
            # In async context, return empty - use get_escalation_history_async
            return []
        except RuntimeError:
            return asyncio.run(self.get_escalation_history_async(limit, rule_id))

    def get_stats(self) -> dict:
        """
        Get escalation statistics.

        Returns:
            Dictionary with statistics
        """
        history = self.get_escalation_history(limit=1000)

        if not history:
            return {
                "total_escalations": 0,
                "by_rule": {},
                "by_severity": {},
            }

        by_rule: dict[str, int] = {}
        by_severity: dict[int, int] = {}

        for entry in history:
            rule_id = entry.get("rule_id", "unknown")
            by_rule[rule_id] = by_rule.get(rule_id, 0) + 1

            severity = entry.get("severity", 0)
            by_severity[severity] = by_severity.get(severity, 0) + 1

        return {
            "total_escalations": len(history),
            "by_rule": by_rule,
            "by_severity": by_severity,
        }


def create_escalation_engine(
    project_dir: Path,
    session_id: int = 0,
) -> EscalationEngine:
    """Create an EscalationEngine for a project."""
    return EscalationEngine(project_dir, session_id=session_id)


async def create_escalation_engine_async(
    project_dir: Path,
    session: AsyncSession,
    session_id: int = 0,
) -> EscalationEngine:
    """
    Create an EscalationEngine with async database initialization.

    Args:
        project_dir: Project directory
        session: Async database session
        session_id: Current session ID for logging

    Returns:
        Configured EscalationEngine with database connection
    """
    engine = EscalationEngine(project_dir, load_custom=True, session_id=session_id)
    await engine.init_async(session)
    return engine


# Convenience function for quick evaluation
def should_escalate(
    project_dir: Path,
    context: EscalationContext | dict,
) -> Optional[EscalationResult]:
    """
    Quick check if context should trigger escalation.

    Args:
        project_dir: Project directory
        context: Context to evaluate

    Returns:
        EscalationResult if escalation needed, None otherwise
    """
    engine = EscalationEngine(project_dir, load_custom=True)
    return engine.evaluate(context)
