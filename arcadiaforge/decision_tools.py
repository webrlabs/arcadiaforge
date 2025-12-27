"""
Custom MCP Tools for Decision Logging (Database Backed)
========================================================

These tools allow agents to log and review decisions made during development.
Decisions provide traceability for why certain choices were made.

Decision Types:
- architecture: Architectural choices
- implementation: Implementation approach decisions
- fix: Bug fix approach decisions
- refactor: Refactoring decisions
- dependency: Dependency choices
- testing: Testing strategy decisions
- prioritization: Feature prioritization decisions

Each decision records:
- Context: What situation prompted the decision
- Choice: What was decided
- Alternatives: What other options were considered
- Rationale: Why this choice was made
- Outcome: (filled in later) What happened as a result
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Dict

from sqlalchemy import select, desc
from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig

from arcadiaforge.db.models import Decision
from arcadiaforge.db.connection import get_session_maker


# Global state
_project_dir: Path | None = None
_current_session_id: int = 0


def set_session_id(session_id: int) -> None:
    """Set the current session ID for decision logging."""
    global _current_session_id
    _current_session_id = session_id


@tool(
    "decision_log",
    "Log a significant decision for future reference and traceability.",
    {
        "type": "object",
        "properties": {
            "decision_type": {
                "type": "string",
                "description": "Type: architecture, implementation, fix, refactor, dependency, testing, prioritization"
            },
            "context": {
                "type": "string",
                "description": "What situation prompted this decision"
            },
            "choice": {
                "type": "string",
                "description": "What was decided"
            },
            "alternatives": {
                "type": "array",
                "items": {"type": "string"},
                "description": "What other options were considered"
            },
            "rationale": {
                "type": "string",
                "description": "Why this choice was made"
            },
            "confidence": {
                "type": "number",
                "description": "Confidence in this decision (0.0 to 1.0)"
            },
            "related_features": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Related feature indices"
            }
        },
        "required": ["decision_type", "context", "choice", "rationale"]
    }
)
async def decision_log(args: dict[str, Any]) -> dict[str, Any]:
    """Log a new decision."""
    decision_type = args.get("decision_type", "implementation")
    valid_types = ("architecture", "implementation", "fix", "refactor", "dependency", "testing", "prioritization")
    if decision_type not in valid_types:
        decision_type = "implementation"

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            # Generate decision ID
            result = await session.execute(
                select(Decision).order_by(desc(Decision.id)).limit(1)
            )
            last = result.scalar_one_or_none()
            next_num = (last.id + 1) if last else 1

            new_decision = Decision(
                decision_id=f"D-{_current_session_id}-{next_num}",
                session_id=_current_session_id,
                decision_type=decision_type,
                context=args.get("context", ""),
                choice=args.get("choice", ""),
                alternatives=args.get("alternatives", []),
                rationale=args.get("rationale", ""),
                confidence=min(max(args.get("confidence", 0.7), 0.0), 1.0),
                related_features=args.get("related_features", []),
                inputs_consulted=[]
            )
            session.add(new_decision)
            await session.commit()

            return {
                "content": [{
                    "type": "text",
                    "text": f"Decision [{new_decision.decision_id}] logged successfully.\n\n"
                            f"Type: {decision_type}\n"
                            f"Choice: {new_decision.choice[:100]}...\n"
                            f"Confidence: {new_decision.confidence:.0%}\n\n"
                            f"Future agents can review this decision for context."
                }]
            }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error logging decision: {e}"}],
            "is_error": True
        }


@tool(
    "decision_list",
    "List recent decisions, optionally filtered by type.",
    {"decision_type": str, "count": int}
)
async def decision_list(args: dict[str, Any]) -> dict[str, Any]:
    """List recent decisions."""
    decision_type = args.get("decision_type", "")
    count = min(max(args.get("count", 10), 1), 50)

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            query = select(Decision).order_by(desc(Decision.timestamp))

            if decision_type:
                query = query.where(Decision.decision_type == decision_type)

            result = await session.execute(query.limit(count))
            decisions = result.scalars().all()

            if not decisions:
                msg = f"No decisions found"
                if decision_type:
                    msg += f" of type '{decision_type}'"
                return {"content": [{"type": "text", "text": msg + "."}]}

            lines = [
                f"DECISIONS ({len(decisions)} shown)",
                "=" * 60
            ]

            for d in decisions:
                lines.append("")
                lines.append(f"[{d.decision_id}] {d.decision_type.upper()} (Session #{d.session_id})")
                lines.append(f"  Context: {d.context[:80]}...")
                lines.append(f"  Choice: {d.choice[:80]}...")
                lines.append(f"  Confidence: {d.confidence:.0%}")

                if d.outcome:
                    outcome_status = "✓" if d.outcome_success else "✗"
                    lines.append(f"  Outcome: {outcome_status} {d.outcome[:60]}...")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error listing decisions: {e}"}],
            "is_error": True
        }


@tool(
    "decision_show",
    "Show full details for a specific decision.",
    {"decision_id": str}
)
async def decision_show(args: dict[str, Any]) -> dict[str, Any]:
    """Show detailed information about a decision."""
    decision_id = args.get("decision_id", "")

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(Decision).where(Decision.decision_id == decision_id)
            )
            d = result.scalar_one_or_none()

            if not d:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Decision '{decision_id}' not found."
                    }]
                }

            lines = [
                f"DECISION: {d.decision_id}",
                "=" * 60,
                f"Type: {d.decision_type}",
                f"Session: #{d.session_id}",
                f"Time: {d.timestamp.isoformat() if d.timestamp else 'unknown'}",
                f"Confidence: {d.confidence:.0%}",
                "",
                "CONTEXT:",
                d.context,
                "",
                "CHOICE:",
                d.choice,
                "",
                "RATIONALE:",
                d.rationale,
            ]

            if d.alternatives:
                lines.append("")
                lines.append("ALTERNATIVES CONSIDERED:")
                for alt in d.alternatives:
                    lines.append(f"  - {alt}")

            if d.related_features:
                lines.append(f"\nRelated features: {d.related_features}")

            if d.git_commit:
                lines.append(f"Git commit: {d.git_commit}")

            if d.checkpoint_id:
                lines.append(f"Checkpoint: {d.checkpoint_id}")

            if d.outcome:
                lines.append("")
                lines.append("OUTCOME:")
                status = "SUCCESS" if d.outcome_success else "FAILURE" if d.outcome_success is False else "UNKNOWN"
                lines.append(f"Status: {status}")
                lines.append(d.outcome)
                if d.outcome_timestamp:
                    lines.append(f"Recorded: {d.outcome_timestamp.isoformat()}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error showing decision: {e}"}],
            "is_error": True
        }


@tool(
    "decision_record_outcome",
    "Record the outcome of a previous decision. This helps track which decisions worked well.",
    {
        "type": "object",
        "properties": {
            "decision_id": {
                "type": "string",
                "description": "The decision ID to update"
            },
            "success": {
                "type": "boolean",
                "description": "Whether the decision led to a successful outcome"
            },
            "outcome": {
                "type": "string",
                "description": "Description of what happened as a result of this decision"
            }
        },
        "required": ["decision_id", "success", "outcome"]
    }
)
async def decision_record_outcome(args: dict[str, Any]) -> dict[str, Any]:
    """Record the outcome of a decision."""
    decision_id = args.get("decision_id", "")

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(Decision).where(Decision.decision_id == decision_id)
            )
            d = result.scalar_one_or_none()

            if not d:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Decision '{decision_id}' not found."
                    }]
                }

            d.outcome = args.get("outcome", "")
            d.outcome_success = args.get("success", None)
            d.outcome_timestamp = datetime.now(timezone.utc)

            await session.commit()

            status = "SUCCESS" if d.outcome_success else "FAILURE"
            return {
                "content": [{
                    "type": "text",
                    "text": f"Outcome recorded for decision [{decision_id}].\n\n"
                            f"Status: {status}\n"
                            f"Outcome: {d.outcome[:100]}..."
                }]
            }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error recording outcome: {e}"}],
            "is_error": True
        }


@tool(
    "decision_search",
    "Search decisions by keyword in context, choice, or rationale.",
    {"query": str}
)
async def decision_search(args: dict[str, Any]) -> dict[str, Any]:
    """Search decisions by keyword."""
    query = args.get("query", "").lower()

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(Decision).order_by(desc(Decision.timestamp))
            )
            all_decisions = result.scalars().all()

            matches = []
            for d in all_decisions:
                searchable = f"{d.context} {d.choice} {d.rationale} {d.decision_type}".lower()
                if query in searchable:
                    matches.append(d)

            if not matches:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"No decisions found matching '{query}'."
                    }]
                }

            lines = [
                f"DECISION SEARCH: '{query}' ({len(matches)} matches)",
                "=" * 60
            ]

            for d in matches[:15]:
                lines.append("")
                lines.append(f"[{d.decision_id}] {d.decision_type} (Session #{d.session_id})")
                lines.append(f"  {d.choice[:80]}...")

                if d.outcome_success is not None:
                    status = "✓" if d.outcome_success else "✗"
                    lines.append(f"  Outcome: {status}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error searching decisions: {e}"}],
            "is_error": True
        }


@tool(
    "decision_for_feature",
    "Get all decisions related to a specific feature.",
    {"feature_index": int}
)
async def decision_for_feature(args: dict[str, Any]) -> dict[str, Any]:
    """Get decisions related to a feature."""
    feature_index = args.get("feature_index", -1)

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(Decision).order_by(desc(Decision.timestamp))
            )
            all_decisions = result.scalars().all()

            # Filter by feature index in related_features JSON
            matches = [d for d in all_decisions if feature_index in (d.related_features or [])]

            if not matches:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"No decisions found for feature #{feature_index}."
                    }]
                }

            lines = [
                f"DECISIONS FOR FEATURE #{feature_index} ({len(matches)} found)",
                "=" * 60
            ]

            for d in matches:
                lines.append("")
                lines.append(f"[{d.decision_id}] {d.decision_type}")
                lines.append(f"  Context: {d.context[:60]}...")
                lines.append(f"  Choice: {d.choice[:60]}...")

                if d.outcome_success is not None:
                    status = "✓ SUCCESS" if d.outcome_success else "✗ FAILURE"
                    lines.append(f"  Outcome: {status}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error getting decisions: {e}"}],
            "is_error": True
        }


# =============================================================================
# Tool Registration
# =============================================================================

DECISION_TOOLS = [
    "mcp__decision__decision_log",
    "mcp__decision__decision_list",
    "mcp__decision__decision_show",
    "mcp__decision__decision_record_outcome",
    "mcp__decision__decision_search",
    "mcp__decision__decision_for_feature",
]


def create_decision_tools_server(project_dir: Path) -> McpSdkServerConfig:
    """
    Create an MCP server with decision logging tools.

    Args:
        project_dir: The project directory

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    global _project_dir
    _project_dir = project_dir

    return create_sdk_mcp_server(
        name="decision",
        version="1.0.0",
        tools=[
            decision_log,
            decision_list,
            decision_show,
            decision_record_outcome,
            decision_search,
            decision_for_feature,
        ]
    )
