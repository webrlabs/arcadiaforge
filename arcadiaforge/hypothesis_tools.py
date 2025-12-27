"""
Custom MCP Tools for Hypothesis Tracking (Database Backed)
===========================================================

These tools allow agents to track hypotheses across sessions.
Hypotheses are observations or theories about the codebase that need validation.

Types:
- bug: Suspected bug or issue
- performance: Performance-related observation
- architecture: Architectural concern
- dependency: Dependency-related issue
- pattern: Observed pattern in the codebase

Statuses:
- open: Hypothesis is active and needs investigation
- confirmed: Hypothesis was validated as true
- rejected: Hypothesis was proven false
- superseded: Replaced by a newer hypothesis
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Dict

from sqlalchemy import select, desc
from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig

from arcadiaforge.db.models import Hypothesis
from arcadiaforge.db.connection import get_session_maker


# Global project directory
_project_dir: Path | None = None
_current_session_id: int = 0


def set_session_id(session_id: int) -> None:
    """Set the current session ID for hypothesis creation."""
    global _current_session_id
    _current_session_id = session_id


@tool(
    "hypothesis_list",
    "List hypotheses. Use status filter to see open, confirmed, rejected, or superseded hypotheses.",
    {"status": str, "hypothesis_type": str}
)
async def hypothesis_list(args: dict[str, Any]) -> dict[str, Any]:
    """List hypotheses with optional filters."""
    status = args.get("status", "open")
    hypothesis_type = args.get("hypothesis_type", "")

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            query = select(Hypothesis).order_by(desc(Hypothesis.created_at))

            if status:
                query = query.where(Hypothesis.status == status)
            if hypothesis_type:
                query = query.where(Hypothesis.hypothesis_type == hypothesis_type)

            result = await session.execute(query.limit(20))
            hypotheses = result.scalars().all()

            if not hypotheses:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"No hypotheses found with status='{status}'."
                    }]
                }

            lines = [
                f"HYPOTHESES ({len(hypotheses)} {status})",
                "=" * 60
            ]

            for h in hypotheses:
                lines.append("")
                lines.append(f"[{h.hypothesis_id}] {h.hypothesis_type.upper()} - {h.status}")
                lines.append(f"  Observation: {h.observation[:100]}...")
                lines.append(f"  Hypothesis: {h.hypothesis[:100]}...")
                lines.append(f"  Confidence: {h.confidence:.0%} | Reviews: {h.review_count}")

                if h.related_features:
                    lines.append(f"  Related features: {h.related_features[:5]}")

                if h.context_keywords:
                    lines.append(f"  Keywords: {', '.join(h.context_keywords[:5])}")

                evidence_for = len(h.evidence_for or [])
                evidence_against = len(h.evidence_against or [])
                if evidence_for or evidence_against:
                    lines.append(f"  Evidence: {evidence_for} for, {evidence_against} against")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error listing hypotheses: {e}"}],
            "is_error": True
        }


@tool(
    "hypothesis_show",
    "Show full details for a specific hypothesis.",
    {"hypothesis_id": str}
)
async def hypothesis_show(args: dict[str, Any]) -> dict[str, Any]:
    """Show detailed information about a hypothesis."""
    hypothesis_id = args.get("hypothesis_id", "")

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(Hypothesis).where(Hypothesis.hypothesis_id == hypothesis_id)
            )
            h = result.scalar_one_or_none()

            if not h:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Hypothesis '{hypothesis_id}' not found."
                    }]
                }

            lines = [
                f"HYPOTHESIS: {h.hypothesis_id}",
                "=" * 60,
                f"Type: {h.hypothesis_type}",
                f"Status: {h.status}",
                f"Confidence: {h.confidence:.0%}",
                f"Created: Session #{h.created_session} at {h.created_at.isoformat() if h.created_at else 'unknown'}",
                "",
                "OBSERVATION:",
                h.observation,
                "",
                "HYPOTHESIS:",
                h.hypothesis,
            ]

            if h.context_keywords:
                lines.append(f"\nKeywords: {', '.join(h.context_keywords)}")

            if h.related_features:
                lines.append(f"Related features: {h.related_features}")

            if h.related_files:
                lines.append(f"Related files: {h.related_files}")

            if h.related_errors:
                lines.append(f"Related errors: {h.related_errors[:3]}")

            if h.evidence_for:
                lines.append(f"\nEvidence FOR ({len(h.evidence_for)}):")
                for e in h.evidence_for[-3:]:
                    lines.append(f"  + {e.get('description', str(e))[:80]}")

            if h.evidence_against:
                lines.append(f"\nEvidence AGAINST ({len(h.evidence_against)}):")
                for e in h.evidence_against[-3:]:
                    lines.append(f"  - {e.get('description', str(e))[:80]}")

            if h.status in ("confirmed", "rejected") and h.resolution:
                lines.append(f"\nRESOLUTION:")
                lines.append(h.resolution)

            lines.append(f"\nReviewed {h.review_count} times across sessions: {h.sessions_seen or []}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error showing hypothesis: {e}"}],
            "is_error": True
        }


@tool(
    "hypothesis_create",
    "Create a new hypothesis to track across sessions.",
    {
        "type": "object",
        "properties": {
            "hypothesis_type": {
                "type": "string",
                "description": "Type: bug, performance, architecture, dependency, pattern"
            },
            "observation": {
                "type": "string",
                "description": "What you observed that led to this hypothesis"
            },
            "hypothesis": {
                "type": "string",
                "description": "Your hypothesis about why/what is happening"
            },
            "confidence": {
                "type": "number",
                "description": "Initial confidence level (0.0 to 1.0)"
            },
            "context_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keywords for finding this hypothesis later"
            },
            "related_features": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Related feature indices"
            },
            "related_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Related file paths"
            }
        },
        "required": ["hypothesis_type", "observation", "hypothesis"]
    }
)
async def hypothesis_create(args: dict[str, Any]) -> dict[str, Any]:
    """Create a new hypothesis."""
    hypothesis_type = args.get("hypothesis_type", "pattern")
    valid_types = ("bug", "performance", "architecture", "dependency", "pattern")
    if hypothesis_type not in valid_types:
        hypothesis_type = "pattern"

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            # Generate hypothesis ID
            result = await session.execute(
                select(Hypothesis).order_by(desc(Hypothesis.id)).limit(1)
            )
            last = result.scalar_one_or_none()
            next_num = (last.id + 1) if last else 1

            new_hyp = Hypothesis(
                hypothesis_id=f"HYP-{_current_session_id}-{next_num}",
                created_session=_current_session_id,
                hypothesis_type=hypothesis_type,
                observation=args.get("observation", ""),
                hypothesis=args.get("hypothesis", ""),
                confidence=min(max(args.get("confidence", 0.5), 0.0), 1.0),
                status="open",
                context_keywords=args.get("context_keywords", []),
                related_features=args.get("related_features", []),
                related_files=args.get("related_files", []),
                sessions_seen=[_current_session_id]
            )
            session.add(new_hyp)
            await session.commit()

            return {
                "content": [{
                    "type": "text",
                    "text": f"Hypothesis [{new_hyp.hypothesis_id}] created successfully.\n\n"
                            f"Type: {hypothesis_type}\n"
                            f"Confidence: {new_hyp.confidence:.0%}\n\n"
                            f"Observation: {new_hyp.observation[:100]}...\n"
                            f"Hypothesis: {new_hyp.hypothesis[:100]}...\n\n"
                            f"Use hypothesis_add_evidence to add supporting/opposing evidence."
                }]
            }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error creating hypothesis: {e}"}],
            "is_error": True
        }


@tool(
    "hypothesis_add_evidence",
    "Add evidence for or against a hypothesis.",
    {
        "type": "object",
        "properties": {
            "hypothesis_id": {
                "type": "string",
                "description": "The hypothesis ID (e.g., HYP-1-1)"
            },
            "supports": {
                "type": "boolean",
                "description": "True if evidence supports the hypothesis, False if it contradicts"
            },
            "description": {
                "type": "string",
                "description": "Description of the evidence"
            },
            "source": {
                "type": "string",
                "description": "Where this evidence came from (file, test, observation)"
            }
        },
        "required": ["hypothesis_id", "supports", "description"]
    }
)
async def hypothesis_add_evidence(args: dict[str, Any]) -> dict[str, Any]:
    """Add evidence to a hypothesis."""
    hypothesis_id = args.get("hypothesis_id", "")
    supports = args.get("supports", True)

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(Hypothesis).where(Hypothesis.hypothesis_id == hypothesis_id)
            )
            h = result.scalar_one_or_none()

            if not h:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Hypothesis '{hypothesis_id}' not found."
                    }]
                }

            evidence = {
                "session": _current_session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "description": args.get("description", ""),
                "source": args.get("source", "observation")
            }

            if supports:
                if not h.evidence_for:
                    h.evidence_for = []
                h.evidence_for = h.evidence_for + [evidence]
            else:
                if not h.evidence_against:
                    h.evidence_against = []
                h.evidence_against = h.evidence_against + [evidence]

            # Update confidence based on evidence balance
            for_count = len(h.evidence_for or [])
            against_count = len(h.evidence_against or [])
            if for_count + against_count > 0:
                h.confidence = for_count / (for_count + against_count)

            # Track that this session reviewed it
            if _current_session_id not in (h.sessions_seen or []):
                h.sessions_seen = (h.sessions_seen or []) + [_current_session_id]
            h.review_count = (h.review_count or 0) + 1
            h.last_reviewed = datetime.now(timezone.utc)

            await session.commit()

            direction = "FOR" if supports else "AGAINST"
            return {
                "content": [{
                    "type": "text",
                    "text": f"Evidence added {direction} hypothesis [{hypothesis_id}].\n\n"
                            f"New confidence: {h.confidence:.0%}\n"
                            f"Evidence: {len(h.evidence_for or [])} for, {len(h.evidence_against or [])} against"
                }]
            }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error adding evidence: {e}"}],
            "is_error": True
        }


@tool(
    "hypothesis_resolve",
    "Resolve a hypothesis as confirmed, rejected, or superseded.",
    {
        "type": "object",
        "properties": {
            "hypothesis_id": {
                "type": "string",
                "description": "The hypothesis ID to resolve"
            },
            "status": {
                "type": "string",
                "description": "New status: confirmed, rejected, superseded"
            },
            "resolution": {
                "type": "string",
                "description": "Explanation of how this was resolved"
            },
            "superseded_by": {
                "type": "string",
                "description": "If superseded, the ID of the new hypothesis"
            }
        },
        "required": ["hypothesis_id", "status", "resolution"]
    }
)
async def hypothesis_resolve(args: dict[str, Any]) -> dict[str, Any]:
    """Resolve a hypothesis."""
    hypothesis_id = args.get("hypothesis_id", "")
    status = args.get("status", "confirmed")
    if status not in ("confirmed", "rejected", "superseded"):
        status = "confirmed"

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(Hypothesis).where(Hypothesis.hypothesis_id == hypothesis_id)
            )
            h = result.scalar_one_or_none()

            if not h:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Hypothesis '{hypothesis_id}' not found."
                    }]
                }

            h.status = status
            h.resolution = args.get("resolution", "")
            h.resolved_at = datetime.now(timezone.utc)
            h.resolved_session = _current_session_id

            if status == "superseded":
                h.superseded_by = args.get("superseded_by")

            await session.commit()

            return {
                "content": [{
                    "type": "text",
                    "text": f"Hypothesis [{hypothesis_id}] resolved as {status.upper()}.\n\n"
                            f"Resolution: {h.resolution}"
                }]
            }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error resolving hypothesis: {e}"}],
            "is_error": True
        }


@tool(
    "hypothesis_search",
    "Search hypotheses by keyword.",
    {"query": str}
)
async def hypothesis_search(args: dict[str, Any]) -> dict[str, Any]:
    """Search hypotheses by keyword."""
    query = args.get("query", "").lower()

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(Hypothesis).order_by(desc(Hypothesis.created_at))
            )
            all_hyps = result.scalars().all()

            matches = []
            for h in all_hyps:
                searchable = f"{h.observation} {h.hypothesis} {' '.join(h.context_keywords or [])} {h.hypothesis_type}".lower()
                if query in searchable:
                    matches.append(h)

            if not matches:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"No hypotheses found matching '{query}'."
                    }]
                }

            lines = [
                f"HYPOTHESIS SEARCH: '{query}' ({len(matches)} matches)",
                "=" * 60
            ]

            for h in matches[:10]:
                lines.append("")
                lines.append(f"[{h.hypothesis_id}] {h.hypothesis_type} - {h.status}")
                lines.append(f"  {h.hypothesis[:80]}...")
                lines.append(f"  Confidence: {h.confidence:.0%}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error searching hypotheses: {e}"}],
            "is_error": True
        }


# =============================================================================
# Tool Registration
# =============================================================================

HYPOTHESIS_TOOLS = [
    "mcp__hypothesis__hypothesis_list",
    "mcp__hypothesis__hypothesis_show",
    "mcp__hypothesis__hypothesis_create",
    "mcp__hypothesis__hypothesis_add_evidence",
    "mcp__hypothesis__hypothesis_resolve",
    "mcp__hypothesis__hypothesis_search",
]


def create_hypothesis_tools_server(project_dir: Path) -> McpSdkServerConfig:
    """
    Create an MCP server with hypothesis tracking tools.

    Args:
        project_dir: The project directory

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    global _project_dir
    _project_dir = project_dir

    return create_sdk_mcp_server(
        name="hypothesis",
        version="1.0.0",
        tools=[
            hypothesis_list,
            hypothesis_show,
            hypothesis_create,
            hypothesis_add_evidence,
            hypothesis_resolve,
            hypothesis_search,
        ]
    )
