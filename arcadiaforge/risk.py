"""
Risk Classification Module
==========================

Classifies actions by risk level before execution to enable risk-appropriate
gating and safety measures.

Risk dimensions:
- Level (1-5): Severity of potential negative outcomes
- Reversibility: Whether the action can be undone
- Source of truth impact: Whether it affects authoritative data
- External effects: Whether it has side effects outside the project

Storage: All data is persisted in the .arcadia/project.db SQLite database.
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.models import RiskPatternModel, RiskAssessmentModel


class RiskLevel(IntEnum):
    """Risk levels from minimal to critical."""
    MINIMAL = 1      # Read operations, no side effects
    LOW = 2          # Reversible writes, local changes
    MODERATE = 3     # Significant changes, but recoverable
    HIGH = 4         # Important system changes, hard to reverse
    CRITICAL = 5     # Potentially destructive, irreversible


@dataclass
class RiskAssessment:
    """Complete risk assessment for an action."""

    # Action identification
    action: str
    tool: str
    input_summary: str

    # Risk dimensions
    risk_level: RiskLevel
    is_reversible: bool
    affects_source_of_truth: bool
    has_external_side_effects: bool

    # Specific concerns
    concerns: list[str] = field(default_factory=list)

    # Cost estimates (optional)
    estimated_time_seconds: Optional[int] = None
    estimated_token_cost: Optional[int] = None

    # Gating recommendations
    requires_approval: bool = False
    requires_checkpoint: bool = False
    requires_review: bool = False
    suggested_mitigation: Optional[str] = None

    # Metadata
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "action": self.action,
            "tool": self.tool,
            "input_summary": self.input_summary,
            "risk_level": self.risk_level.value,
            "risk_level_name": self.risk_level.name,
            "is_reversible": self.is_reversible,
            "affects_source_of_truth": self.affects_source_of_truth,
            "has_external_side_effects": self.has_external_side_effects,
            "concerns": self.concerns,
            "estimated_time_seconds": self.estimated_time_seconds,
            "estimated_token_cost": self.estimated_token_cost,
            "requires_approval": self.requires_approval,
            "requires_checkpoint": self.requires_checkpoint,
            "requires_review": self.requires_review,
            "suggested_mitigation": self.suggested_mitigation,
            "timestamp": self.timestamp,
        }


@dataclass
class RiskPattern:
    """A pattern that indicates specific risk characteristics."""

    pattern_id: str
    description: str
    risk_level: RiskLevel

    # Pattern matching
    tool: Optional[str] = None  # None means any tool
    input_pattern: Optional[str] = None  # Regex pattern for input
    input_field: Optional[str] = None  # Which input field to check

    # Risk characteristics
    is_reversible: bool = True
    affects_source_of_truth: bool = False
    has_external_side_effects: bool = False

    # Gating
    requires_approval: bool = False
    requires_checkpoint: bool = False

    # Mitigation
    mitigation: Optional[str] = None


# Default risk patterns for common scenarios
DEFAULT_RISK_PATTERNS: list[RiskPattern] = [
    # Feature database modifications
    RiskPattern(
        pattern_id="feature_database_write",
        description="Direct write to feature database",
        tool="Write",
        input_field="file_path",
        input_pattern=r"\.arcadia/project\.db$",
        risk_level=RiskLevel.HIGH,
        affects_source_of_truth=True,
        requires_checkpoint=True,
        mitigation="Use feature tools (feature_mark, etc.) instead of direct database access",
    ),

    # Git operations
    RiskPattern(
        pattern_id="git_push",
        description="Git push to remote",
        tool="Bash",
        input_field="command",
        input_pattern=r"git\s+push",
        risk_level=RiskLevel.HIGH,
        is_reversible=False,
        has_external_side_effects=True,
        requires_approval=True,
    ),
    RiskPattern(
        pattern_id="git_force_push",
        description="Git force push",
        tool="Bash",
        input_field="command",
        input_pattern=r"git\s+push\s+.*(-f|--force)",
        risk_level=RiskLevel.CRITICAL,
        is_reversible=False,
        has_external_side_effects=True,
        requires_approval=True,
        mitigation="Avoid force push unless absolutely necessary",
    ),
    RiskPattern(
        pattern_id="git_reset_hard",
        description="Git hard reset",
        tool="Bash",
        input_field="command",
        input_pattern=r"git\s+reset\s+--hard",
        risk_level=RiskLevel.HIGH,
        is_reversible=False,
        requires_checkpoint=True,
        requires_approval=True,
    ),

    # Destructive file operations
    RiskPattern(
        pattern_id="rm_recursive",
        description="Recursive file deletion",
        tool="Bash",
        input_field="command",
        input_pattern=r"rm\s+.*-r",
        risk_level=RiskLevel.HIGH,
        is_reversible=False,
        requires_approval=True,
        requires_checkpoint=True,
    ),
    RiskPattern(
        pattern_id="rm_force",
        description="Force file deletion",
        tool="Bash",
        input_field="command",
        input_pattern=r"rm\s+.*-f",
        risk_level=RiskLevel.MODERATE,
        is_reversible=False,
        requires_checkpoint=True,
    ),

    # Package management
    RiskPattern(
        pattern_id="npm_install",
        description="NPM package installation",
        tool="Bash",
        input_field="command",
        input_pattern=r"npm\s+(install|i)\s",
        risk_level=RiskLevel.MODERATE,
        has_external_side_effects=True,
        requires_checkpoint=True,
    ),
    RiskPattern(
        pattern_id="pip_install",
        description="Python package installation",
        tool="Bash",
        input_field="command",
        input_pattern=r"pip\s+install",
        risk_level=RiskLevel.MODERATE,
        has_external_side_effects=True,
        requires_checkpoint=True,
    ),

    # Database operations
    RiskPattern(
        pattern_id="db_drop",
        description="Database drop operation",
        tool="Bash",
        input_field="command",
        input_pattern=r"(DROP\s+(TABLE|DATABASE)|dropdb)",
        risk_level=RiskLevel.CRITICAL,
        is_reversible=False,
        requires_approval=True,
        requires_checkpoint=True,
        mitigation="Create backup before dropping",
    ),
    RiskPattern(
        pattern_id="db_truncate",
        description="Database truncate operation",
        tool="Bash",
        input_field="command",
        input_pattern=r"TRUNCATE\s+TABLE",
        risk_level=RiskLevel.HIGH,
        is_reversible=False,
        requires_approval=True,
    ),

    # External API calls
    RiskPattern(
        pattern_id="curl_post",
        description="HTTP POST request",
        tool="Bash",
        input_field="command",
        input_pattern=r"curl\s+.*(-X\s*POST|-d\s)",
        risk_level=RiskLevel.MODERATE,
        has_external_side_effects=True,
    ),

    # Environment modifications
    RiskPattern(
        pattern_id="env_file_write",
        description="Environment file modification",
        tool="Write",
        input_field="file_path",
        input_pattern=r"\.env",
        risk_level=RiskLevel.HIGH,
        affects_source_of_truth=True,
        requires_approval=True,
    ),

    # Configuration files
    RiskPattern(
        pattern_id="config_file_write",
        description="Configuration file modification",
        tool="Write",
        input_field="file_path",
        input_pattern=r"(config|settings)\.(json|yaml|yml|toml)$",
        risk_level=RiskLevel.MODERATE,
        requires_checkpoint=True,
    ),
]


# Default risk levels by tool
DEFAULT_TOOL_RISKS: dict[str, RiskLevel] = {
    # Read operations
    "Read": RiskLevel.MINIMAL,
    "Glob": RiskLevel.MINIMAL,
    "Grep": RiskLevel.MINIMAL,
    "WebFetch": RiskLevel.LOW,

    # Write operations
    "Write": RiskLevel.MODERATE,
    "Edit": RiskLevel.MODERATE,

    # Execution
    "Bash": RiskLevel.MODERATE,

    # Feature operations
    "feature_mark": RiskLevel.MODERATE,
    "feature_skip": RiskLevel.LOW,
    "feature_add": RiskLevel.LOW,
    "feature_list": RiskLevel.MINIMAL,
    "feature_focus": RiskLevel.MINIMAL,

    # Browser operations
    "puppeteer_navigate": RiskLevel.LOW,
    "puppeteer_screenshot": RiskLevel.MINIMAL,
    "puppeteer_click": RiskLevel.LOW,
    "puppeteer_type": RiskLevel.LOW,
}


class RiskClassifier:
    """
    Classifies actions by risk before execution.

    Provides:
    - Per-action risk assessment
    - Pattern-based risk detection
    - Risk-appropriate gating recommendations
    - Risk history tracking

    Storage: All patterns and assessments are persisted in the .arcadia/project.db database.
    """

    def __init__(self, project_dir: Path, session_id: int = 0):
        self.project_dir = Path(project_dir)
        self.session_id = session_id

        # Database session (set via set_session or init_async)
        self._db_session: Optional[AsyncSession] = None

        # Load default patterns (custom patterns loaded via init_async)
        self.patterns = list(DEFAULT_RISK_PATTERNS)
        self._custom_patterns_loaded = False

        # Custom risk rules
        self._custom_rules: dict[str, Callable[[dict], RiskAssessment]] = {}

        # Statistics
        self.stats = {
            "total_assessments": 0,
            "by_level": {level.name: 0 for level in RiskLevel},
            "approvals_required": 0,
            "checkpoints_required": 0,
        }

    def set_session(self, session: AsyncSession) -> None:
        """Set the database session for async operations."""
        self._db_session = session

    def update_session_id(self, session_id: int) -> None:
        """Update the current session ID."""
        self.session_id = session_id

    async def init_async(self, session: AsyncSession) -> None:
        """
        Initialize the classifier asynchronously with a database session.

        This loads custom patterns from the database.
        """
        self._db_session = session
        await self._load_patterns_async()

    # =========================================================================
    # Async Database Methods
    # =========================================================================

    async def _load_patterns_async(self) -> None:
        """Load custom risk patterns from database."""
        if self._db_session is None:
            return

        result = await self._db_session.execute(
            select(RiskPatternModel).where(RiskPatternModel.is_enabled == True)
        )
        rows = result.scalars().all()

        for row in rows:
            pattern = RiskPattern(
                pattern_id=row.pattern_id,
                description=row.description,
                tool=row.tool,
                input_pattern=row.input_pattern,
                input_field=row.input_field,
                risk_level=RiskLevel(row.risk_level),
                is_reversible=row.is_reversible,
                affects_source_of_truth=row.affects_source_of_truth,
                has_external_side_effects=row.has_external_side_effects,
                requires_approval=row.requires_approval,
                requires_checkpoint=row.requires_checkpoint,
                mitigation=row.mitigation,
            )
            # Add if not already present (by pattern_id)
            existing_ids = {p.pattern_id for p in self.patterns}
            if pattern.pattern_id not in existing_ids:
                self.patterns.append(pattern)

        self._custom_patterns_loaded = True

    async def _save_pattern_async(self, pattern: RiskPattern) -> None:
        """Save a custom risk pattern to database."""
        if self._db_session is None:
            return

        # Check if pattern exists
        result = await self._db_session.execute(
            select(RiskPatternModel).where(RiskPatternModel.pattern_id == pattern.pattern_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing
            await self._db_session.execute(
                update(RiskPatternModel)
                .where(RiskPatternModel.pattern_id == pattern.pattern_id)
                .values(
                    description=pattern.description,
                    tool=pattern.tool,
                    input_pattern=pattern.input_pattern,
                    input_field=pattern.input_field,
                    risk_level=pattern.risk_level.value,
                    is_reversible=pattern.is_reversible,
                    affects_source_of_truth=pattern.affects_source_of_truth,
                    has_external_side_effects=pattern.has_external_side_effects,
                    requires_approval=pattern.requires_approval,
                    requires_checkpoint=pattern.requires_checkpoint,
                    mitigation=pattern.mitigation,
                    is_custom=True,
                    is_enabled=True,
                )
            )
        else:
            # Insert new
            new_pattern = RiskPatternModel(
                pattern_id=pattern.pattern_id,
                description=pattern.description,
                tool=pattern.tool,
                input_pattern=pattern.input_pattern,
                input_field=pattern.input_field,
                risk_level=pattern.risk_level.value,
                is_reversible=pattern.is_reversible,
                affects_source_of_truth=pattern.affects_source_of_truth,
                has_external_side_effects=pattern.has_external_side_effects,
                requires_approval=pattern.requires_approval,
                requires_checkpoint=pattern.requires_checkpoint,
                mitigation=pattern.mitigation,
                is_custom=True,
                is_enabled=True,
            )
            self._db_session.add(new_pattern)

        await self._db_session.commit()

    async def _log_assessment_async(self, assessment: RiskAssessment) -> None:
        """Log an assessment to the database."""
        if self._db_session is None:
            return

        log_entry = RiskAssessmentModel(
            session_id=self.session_id,
            action=assessment.action,
            tool=assessment.tool,
            input_summary=assessment.input_summary,
            risk_level=assessment.risk_level.value,
            is_reversible=assessment.is_reversible,
            affects_source_of_truth=assessment.affects_source_of_truth,
            has_external_side_effects=assessment.has_external_side_effects,
            concerns=assessment.concerns,
            requires_approval=assessment.requires_approval,
            requires_checkpoint=assessment.requires_checkpoint,
            requires_review=assessment.requires_review,
            suggested_mitigation=assessment.suggested_mitigation,
        )
        self._db_session.add(log_entry)
        await self._db_session.commit()

    async def get_assessment_history_async(
        self,
        limit: int = 50,
        min_level: Optional[RiskLevel] = None,
        tool: Optional[str] = None
    ) -> list[dict]:
        """
        Get recent risk assessments from database.

        Args:
            limit: Maximum number to return
            min_level: Minimum risk level filter
            tool: Filter by tool name

        Returns:
            List of assessment records
        """
        if self._db_session is None:
            return []

        query = select(RiskAssessmentModel).order_by(
            RiskAssessmentModel.timestamp.desc()
        )

        if tool:
            query = query.where(RiskAssessmentModel.tool == tool)
        if min_level:
            query = query.where(RiskAssessmentModel.risk_level >= min_level.value)

        query = query.limit(limit)

        result = await self._db_session.execute(query)
        rows = result.scalars().all()

        assessments = []
        for row in reversed(rows):  # Reverse to get chronological order
            assessments.append({
                "action": row.action,
                "tool": row.tool,
                "input_summary": row.input_summary,
                "risk_level": row.risk_level,
                "risk_level_name": RiskLevel(row.risk_level).name,
                "is_reversible": row.is_reversible,
                "affects_source_of_truth": row.affects_source_of_truth,
                "has_external_side_effects": row.has_external_side_effects,
                "concerns": row.concerns or [],
                "requires_approval": row.requires_approval,
                "requires_checkpoint": row.requires_checkpoint,
                "requires_review": row.requires_review,
                "suggested_mitigation": row.suggested_mitigation,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            })

        return assessments

    async def add_pattern_async(self, pattern: RiskPattern) -> None:
        """Add a custom risk pattern (async)."""
        # Add to in-memory list
        existing_ids = {p.pattern_id for p in self.patterns}
        if pattern.pattern_id not in existing_ids:
            self.patterns.append(pattern)

        # Save to database
        await self._save_pattern_async(pattern)

    # =========================================================================
    # Sync Wrappers (for backward compatibility)
    # =========================================================================

    def _load_patterns(self) -> list[RiskPattern]:
        """Load patterns (sync - returns defaults, custom loaded via init_async)."""
        return list(DEFAULT_RISK_PATTERNS)

    def add_pattern(self, pattern: RiskPattern) -> None:
        """Add a custom risk pattern."""
        # Add to in-memory list
        existing_ids = {p.pattern_id for p in self.patterns}
        if pattern.pattern_id not in existing_ids:
            self.patterns.append(pattern)

        # Save to database if session available
        if self._db_session is not None:
            try:
                asyncio.get_running_loop()
                asyncio.create_task(self._save_pattern_async(pattern))
            except RuntimeError:
                asyncio.run(self._save_pattern_async(pattern))

    def register_rule(
        self,
        tool: str,
        rule: Callable[[dict], RiskAssessment]
    ) -> None:
        """Register a custom risk assessment rule for a tool."""
        self._custom_rules[tool] = rule

    def assess(
        self,
        tool: str,
        action_input: Optional[dict] = None
    ) -> RiskAssessment:
        """
        Assess the risk of an action.

        Args:
            tool: The tool being invoked
            action_input: The tool's input parameters

        Returns:
            Complete risk assessment
        """
        action_input = action_input or {}

        # Check for custom rule first
        if tool in self._custom_rules:
            assessment = self._custom_rules[tool](action_input)
            self._log_assessment(assessment)
            return assessment

        # Check patterns for matches
        matched_patterns = self._match_patterns(tool, action_input)

        # Build assessment from matches or defaults
        if matched_patterns:
            assessment = self._build_assessment_from_patterns(
                tool, action_input, matched_patterns
            )
        else:
            assessment = self._build_default_assessment(tool, action_input)

        # Log and return
        self._log_assessment(assessment)
        return assessment

    def _match_patterns(
        self,
        tool: str,
        action_input: dict
    ) -> list[RiskPattern]:
        """Find all matching risk patterns."""
        matches = []

        for pattern in self.patterns:
            # Check tool match
            if pattern.tool and pattern.tool != tool:
                continue

            # Check input pattern match
            if pattern.input_pattern and pattern.input_field:
                field_value = str(action_input.get(pattern.input_field, ""))
                if not re.search(pattern.input_pattern, field_value, re.IGNORECASE):
                    continue

            matches.append(pattern)

        return matches

    def _build_assessment_from_patterns(
        self,
        tool: str,
        action_input: dict,
        patterns: list[RiskPattern]
    ) -> RiskAssessment:
        """Build assessment from matched patterns."""
        # Take highest risk level
        max_level = max(p.risk_level for p in patterns)

        # Aggregate concerns
        concerns = [p.description for p in patterns]

        # Check reversibility (false if any pattern is irreversible)
        is_reversible = all(p.is_reversible for p in patterns)

        # Check source of truth impact
        affects_source = any(p.affects_source_of_truth for p in patterns)

        # Check external effects
        has_external = any(p.has_external_side_effects for p in patterns)

        # Check gating requirements
        requires_approval = any(p.requires_approval for p in patterns)
        requires_checkpoint = any(p.requires_checkpoint for p in patterns)

        # Get first available mitigation
        mitigation = next(
            (p.mitigation for p in patterns if p.mitigation),
            None
        )

        return RiskAssessment(
            action=self._summarize_action(tool, action_input),
            tool=tool,
            input_summary=self._summarize_input(action_input),
            risk_level=max_level,
            is_reversible=is_reversible,
            affects_source_of_truth=affects_source,
            has_external_side_effects=has_external,
            concerns=concerns,
            requires_approval=requires_approval,
            requires_checkpoint=requires_checkpoint,
            requires_review=max_level >= RiskLevel.HIGH,
            suggested_mitigation=mitigation,
        )

    def _build_default_assessment(
        self,
        tool: str,
        action_input: dict
    ) -> RiskAssessment:
        """Build default assessment when no patterns match."""
        # Get default risk level for tool
        risk_level = DEFAULT_TOOL_RISKS.get(tool, RiskLevel.MODERATE)

        # Determine characteristics based on tool type
        is_reversible = tool in ["Read", "Glob", "Grep", "WebFetch", "puppeteer_screenshot"]
        affects_source = tool in ["Write", "Edit", "feature_mark"]
        has_external = tool in ["Bash", "WebFetch", "puppeteer_navigate"]

        # Gate based on level
        requires_checkpoint = risk_level >= RiskLevel.MODERATE
        requires_approval = risk_level >= RiskLevel.HIGH
        requires_review = risk_level >= RiskLevel.HIGH

        return RiskAssessment(
            action=self._summarize_action(tool, action_input),
            tool=tool,
            input_summary=self._summarize_input(action_input),
            risk_level=risk_level,
            is_reversible=is_reversible,
            affects_source_of_truth=affects_source,
            has_external_side_effects=has_external,
            requires_approval=requires_approval,
            requires_checkpoint=requires_checkpoint,
            requires_review=requires_review,
        )

    def _summarize_action(self, tool: str, action_input: dict) -> str:
        """Create brief action summary."""
        if tool == "Write" and "file_path" in action_input:
            return f"Write to {Path(action_input['file_path']).name}"
        elif tool == "Edit" and "file_path" in action_input:
            return f"Edit {Path(action_input['file_path']).name}"
        elif tool == "Bash" and "command" in action_input:
            cmd = action_input["command"][:50]
            return f"Run: {cmd}..."
        elif tool == "Read" and "file_path" in action_input:
            return f"Read {Path(action_input['file_path']).name}"
        else:
            return f"{tool} operation"

    def _summarize_input(self, action_input: dict) -> str:
        """Create brief input summary."""
        if not action_input:
            return "(no input)"

        # Truncate long values
        summary_parts = []
        for key, value in list(action_input.items())[:3]:
            value_str = str(value)[:50]
            if len(str(value)) > 50:
                value_str += "..."
            summary_parts.append(f"{key}={value_str}")

        return ", ".join(summary_parts)

    def _log_assessment(self, assessment: RiskAssessment) -> None:
        """Log an assessment (sync wrapper)."""
        # Update in-memory stats
        self.stats["total_assessments"] += 1
        self.stats["by_level"][assessment.risk_level.name] += 1
        if assessment.requires_approval:
            self.stats["approvals_required"] += 1
        if assessment.requires_checkpoint:
            self.stats["checkpoints_required"] += 1

        # Log to database if session available
        if self._db_session is not None:
            try:
                asyncio.get_running_loop()
                asyncio.create_task(self._log_assessment_async(assessment))
            except RuntimeError:
                asyncio.run(self._log_assessment_async(assessment))

    def get_assessment_history(
        self,
        limit: int = 50,
        min_level: Optional[RiskLevel] = None,
        tool: Optional[str] = None
    ) -> list[dict]:
        """
        Get recent risk assessments (sync wrapper).

        Args:
            limit: Maximum number to return
            min_level: Minimum risk level filter
            tool: Filter by tool name

        Returns:
            List of assessment records
        """
        if self._db_session is None:
            return []

        try:
            asyncio.get_running_loop()
            # In async context, return empty - use get_assessment_history_async
            return []
        except RuntimeError:
            return asyncio.run(self.get_assessment_history_async(limit, min_level, tool))

    def get_high_risk_summary(self) -> dict:
        """Get summary of high-risk actions taken."""
        high_risk = self.get_assessment_history(
            limit=100,
            min_level=RiskLevel.HIGH
        )

        return {
            "total_high_risk": len(high_risk),
            "by_tool": self._count_by_field(high_risk, "tool"),
            "approvals_required": sum(1 for a in high_risk if a.get("requires_approval")),
            "checkpoints_required": sum(1 for a in high_risk if a.get("requires_checkpoint")),
            "concerns": self._collect_concerns(high_risk),
        }

    def _count_by_field(self, items: list[dict], field: str) -> dict[str, int]:
        """Count items by field value."""
        counts: dict[str, int] = {}
        for item in items:
            value = item.get(field, "unknown")
            counts[value] = counts.get(value, 0) + 1
        return counts

    def _collect_concerns(self, assessments: list[dict]) -> list[str]:
        """Collect unique concerns from assessments."""
        concerns = set()
        for a in assessments:
            for concern in a.get("concerns", []):
                concerns.add(concern)
        return list(concerns)[:10]  # Limit to top 10

    def get_stats(self) -> dict:
        """Get risk assessment statistics."""
        return self.stats.copy()

    def format_assessment(self, assessment: RiskAssessment) -> str:
        """Format an assessment for display."""
        lines = [
            f"Risk Assessment: {assessment.action}",
            f"  Tool: {assessment.tool}",
            f"  Risk Level: {assessment.risk_level.name} ({assessment.risk_level.value}/5)",
            f"  Reversible: {'Yes' if assessment.is_reversible else 'NO'}",
        ]

        if assessment.affects_source_of_truth:
            lines.append("  Affects Source of Truth: YES")
        if assessment.has_external_side_effects:
            lines.append("  External Side Effects: YES")

        if assessment.concerns:
            lines.append("  Concerns:")
            for concern in assessment.concerns:
                lines.append(f"    - {concern}")

        if assessment.requires_approval:
            lines.append("  REQUIRES APPROVAL")
        if assessment.requires_checkpoint:
            lines.append("  REQUIRES CHECKPOINT")

        if assessment.suggested_mitigation:
            lines.append(f"  Suggested: {assessment.suggested_mitigation}")

        return "\n".join(lines)


def assess_bash_risk(command: str) -> RiskAssessment:
    """
    Specialized risk assessment for bash commands.

    Args:
        command: The bash command to assess

    Returns:
        Risk assessment for the command
    """
    concerns = []
    risk_level = RiskLevel.MODERATE
    is_reversible = True
    affects_source = False
    has_external = False
    requires_approval = False
    requires_checkpoint = False
    mitigation = None

    cmd_lower = command.lower()

    # Check for destructive commands
    if re.search(r'\brm\s', cmd_lower):
        if '-r' in cmd_lower or '-f' in cmd_lower:
            risk_level = max(risk_level, RiskLevel.HIGH)
            concerns.append("Destructive file deletion")
            is_reversible = False
            requires_checkpoint = True
        if '-rf' in cmd_lower:
            risk_level = RiskLevel.CRITICAL
            requires_approval = True

    # Check for git operations
    if 'git push' in cmd_lower:
        risk_level = max(risk_level, RiskLevel.HIGH)
        concerns.append("Pushing to remote repository")
        has_external = True
        is_reversible = False
        if '--force' in cmd_lower or '-f' in cmd_lower:
            risk_level = RiskLevel.CRITICAL
            concerns.append("Force push - may overwrite history")
            requires_approval = True

    if 'git reset --hard' in cmd_lower:
        risk_level = max(risk_level, RiskLevel.HIGH)
        concerns.append("Hard reset - discards uncommitted changes")
        is_reversible = False
        requires_checkpoint = True

    # Check for package operations
    if re.search(r'(npm|pip|yarn)\s+(install|add|remove|uninstall)', cmd_lower):
        risk_level = max(risk_level, RiskLevel.MODERATE)
        concerns.append("Package manager operation")
        has_external = True
        requires_checkpoint = True

    # Check for database operations
    if re.search(r'(drop|truncate|delete\s+from)\s', cmd_lower):
        risk_level = max(risk_level, RiskLevel.HIGH)
        concerns.append("Database destructive operation")
        is_reversible = False
        requires_approval = True
        mitigation = "Create backup before executing"

    # Check for network operations
    if re.search(r'(curl|wget|ssh|scp)\s', cmd_lower):
        if '-X' in command or '-d' in command or 'POST' in command:
            risk_level = max(risk_level, RiskLevel.MODERATE)
            concerns.append("HTTP request with side effects")
            has_external = True
        else:
            has_external = True

    # Check for system modifications
    if re.search(r'(chmod|chown|sudo)\s', cmd_lower):
        risk_level = max(risk_level, RiskLevel.HIGH)
        concerns.append("System permission modification")
        requires_approval = True

    return RiskAssessment(
        action=f"Run: {command[:50]}...",
        tool="Bash",
        input_summary=command[:100],
        risk_level=risk_level,
        is_reversible=is_reversible,
        affects_source_of_truth=affects_source,
        has_external_side_effects=has_external,
        concerns=concerns,
        requires_approval=requires_approval,
        requires_checkpoint=requires_checkpoint,
        requires_review=risk_level >= RiskLevel.HIGH,
        suggested_mitigation=mitigation,
    )


def create_risk_classifier(
    project_dir: Path,
    session_id: int = 0,
) -> RiskClassifier:
    """Create a RiskClassifier instance."""
    return RiskClassifier(project_dir, session_id=session_id)


async def create_risk_classifier_async(
    project_dir: Path,
    session: AsyncSession,
    session_id: int = 0,
) -> RiskClassifier:
    """
    Create a RiskClassifier with async database initialization.

    Args:
        project_dir: Project directory
        session: Async database session
        session_id: Current session ID for logging

    Returns:
        Configured RiskClassifier with database connection
    """
    classifier = RiskClassifier(project_dir, session_id=session_id)
    await classifier.init_async(session)
    return classifier
