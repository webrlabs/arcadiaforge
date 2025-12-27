"""
Custom MCP Tools for Memory Access (Database Backed)
=====================================================

These tools allow agents to access the three-tier memory system:
- Hot Memory: Current session working state
- Warm Memory: Recent session context (last N sessions)
- Cold Memory: Archived historical data and proven knowledge

Memory data is stored in the database (.arcadia/project.db).
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Dict, Optional

from sqlalchemy import select, desc
from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig

from arcadiaforge.db.models import (
    HotMemory, WarmMemory, WarmMemoryIssue, WarmMemoryPattern,
    ColdMemory, ColdMemoryKnowledge
)
from arcadiaforge.db.connection import get_session_maker


# Global project directory
_project_dir: Path | None = None


# =============================================================================
# Hot Memory Tools (Current Session State)
# =============================================================================

@tool(
    "memory_hot_get",
    "Get current session's hot memory state. Shows current task, recent actions, active errors, and focus keywords.",
    {"session_id": int}
)
async def memory_hot_get(args: dict[str, Any]) -> dict[str, Any]:
    """Get hot memory for a session."""
    session_id = args.get("session_id", 0)

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            if session_id:
                result = await session.execute(
                    select(HotMemory).where(HotMemory.session_id == session_id)
                )
            else:
                # Get most recent
                result = await session.execute(
                    select(HotMemory).order_by(desc(HotMemory.id)).limit(1)
                )
            hot = result.scalar_one_or_none()

            if not hot:
                return {
                    "content": [{
                        "type": "text",
                        "text": "No hot memory found for this session."
                    }]
                }

            lines = [
                "HOT MEMORY - Current Session State",
                "=" * 50,
                f"Session ID: {hot.session_id}",
                f"Started: {hot.started_at.isoformat() if hot.started_at else 'unknown'}",
                "",
                f"Current Feature: #{hot.current_feature}" if hot.current_feature else "Current Feature: None",
                f"Current Task: {hot.current_task or 'None'}",
            ]

            if hot.focus_keywords:
                lines.append(f"\nFocus Keywords: {', '.join(hot.focus_keywords)}")

            if hot.recent_files:
                lines.append(f"\nRecent Files ({len(hot.recent_files)}):")
                for f in hot.recent_files[-5:]:
                    lines.append(f"  - {f}")

            if hot.active_errors:
                lines.append(f"\nActive Errors ({len(hot.active_errors)}):")
                for err in hot.active_errors[-3:]:
                    lines.append(f"  - {err.get('message', str(err))[:100]}")

            if hot.pending_decisions:
                lines.append(f"\nPending Decisions ({len(hot.pending_decisions)}):")
                for dec in hot.pending_decisions:
                    lines.append(f"  - {dec.get('context', str(dec))[:80]}")

            if hot.current_hypotheses:
                lines.append(f"\nActive Hypotheses: {', '.join(hot.current_hypotheses)}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error reading hot memory: {e}"}],
            "is_error": True
        }


# =============================================================================
# Warm Memory Tools (Recent Session Context)
# =============================================================================

@tool(
    "memory_warm_sessions",
    "Get summaries of recent sessions from warm memory. Shows what was accomplished, issues encountered, and key decisions.",
    {"count": int}
)
async def memory_warm_sessions(args: dict[str, Any]) -> dict[str, Any]:
    """Get recent session summaries from warm memory."""
    count = min(max(args.get("count", 5), 1), 20)

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(WarmMemory).order_by(desc(WarmMemory.session_id)).limit(count)
            )
            sessions = result.scalars().all()

            if not sessions:
                return {
                    "content": [{
                        "type": "text",
                        "text": "No warm memory sessions found. This may be the first session."
                    }]
                }

            lines = [
                f"WARM MEMORY - Last {len(sessions)} Sessions",
                "=" * 50
            ]

            for s in sessions:
                lines.append("")
                lines.append(f"Session #{s.session_id}")
                lines.append("-" * 30)
                lines.append(f"Duration: {s.duration_seconds:.0f}s | State: {s.ending_state}")
                lines.append(f"Features: {s.features_completed} completed, {s.features_regressed} regressed")

                if s.errors_encountered:
                    lines.append(f"Errors: {len(s.errors_encountered)} encountered, {len(s.errors_resolved or [])} resolved")

                if s.warnings_for_next:
                    lines.append("Warnings for next session:")
                    for w in s.warnings_for_next[:3]:
                        lines.append(f"  ⚠ {w}")

                if s.patterns_discovered:
                    lines.append(f"Patterns discovered: {len(s.patterns_discovered)}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error reading warm memory: {e}"}],
            "is_error": True
        }


@tool(
    "memory_warm_issues",
    "Get unresolved issues from previous sessions. These are problems that were identified but not yet fixed.",
    {"priority": int}
)
async def memory_warm_issues(args: dict[str, Any]) -> dict[str, Any]:
    """Get unresolved issues from warm memory."""
    priority = args.get("priority", 0)  # 0 = all, 1-5 = specific priority

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            query = select(WarmMemoryIssue).order_by(WarmMemoryIssue.priority, desc(WarmMemoryIssue.times_encountered))
            if priority:
                query = query.where(WarmMemoryIssue.priority == priority)

            result = await session.execute(query)
            issues = result.scalars().all()

            if not issues:
                return {
                    "content": [{
                        "type": "text",
                        "text": "No unresolved issues found in warm memory."
                    }]
                }

            lines = [
                f"UNRESOLVED ISSUES ({len(issues)} total)",
                "=" * 50
            ]

            for issue in issues:
                lines.append("")
                lines.append(f"[{issue.issue_id}] Priority {issue.priority}: {issue.issue_type}")
                lines.append(f"  {issue.description}")
                lines.append(f"  Seen {issue.times_encountered}x (last: session #{issue.last_seen_session})")

                if issue.related_features:
                    lines.append(f"  Related features: {issue.related_features}")

                if issue.attempted_solutions:
                    lines.append(f"  Attempted solutions: {len(issue.attempted_solutions)}")
                    for sol in issue.attempted_solutions[-2:]:
                        lines.append(f"    - {sol[:60]}...")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error reading issues: {e}"}],
            "is_error": True
        }


@tool(
    "memory_warm_patterns",
    "Get proven patterns from previous sessions. These are approaches that have worked well.",
    {"pattern_type": str}
)
async def memory_warm_patterns(args: dict[str, Any]) -> dict[str, Any]:
    """Get proven patterns from warm memory."""
    pattern_type = args.get("pattern_type", "")

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            query = select(WarmMemoryPattern).order_by(desc(WarmMemoryPattern.success_count))
            if pattern_type:
                query = query.where(WarmMemoryPattern.pattern_type == pattern_type)

            result = await session.execute(query.limit(20))
            patterns = result.scalars().all()

            if not patterns:
                return {
                    "content": [{
                        "type": "text",
                        "text": "No proven patterns found in warm memory."
                    }]
                }

            lines = [
                f"PROVEN PATTERNS ({len(patterns)} found)",
                "=" * 50
            ]

            for p in patterns:
                lines.append("")
                lines.append(f"[{p.pattern_id}] {p.pattern_type}")
                lines.append(f"  Pattern: {p.pattern}")
                lines.append(f"  Context: {p.context[:100]}...")
                lines.append(f"  Success: {p.success_count}x | Confidence: {p.confidence:.0%}")

                if p.context_keywords:
                    lines.append(f"  Keywords: {', '.join(p.context_keywords[:5])}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error reading patterns: {e}"}],
            "is_error": True
        }


# =============================================================================
# Cold Memory Tools (Historical Knowledge)
# =============================================================================

@tool(
    "memory_cold_history",
    "Get archived session history from cold memory. Shows high-level stats from older sessions.",
    {"count": int}
)
async def memory_cold_history(args: dict[str, Any]) -> dict[str, Any]:
    """Get archived session history from cold memory."""
    count = min(max(args.get("count", 10), 1), 50)

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(ColdMemory).order_by(desc(ColdMemory.session_id)).limit(count)
            )
            sessions = result.scalars().all()

            if not sessions:
                return {
                    "content": [{
                        "type": "text",
                        "text": "No archived sessions in cold memory."
                    }]
                }

            lines = [
                f"COLD MEMORY - Session Archive ({len(sessions)} sessions)",
                "=" * 50,
                "",
                "Session | Duration | Completed | Regressed | Errors | State",
                "-" * 60
            ]

            for s in sessions:
                dur = f"{s.duration_seconds/60:.0f}m" if s.duration_seconds else "?"
                lines.append(
                    f"#{s.session_id:4} | {dur:>8} | {s.features_completed:>9} | {s.features_regressed:>9} | {s.errors_count:>6} | {s.ending_state}"
                )

            # Summary stats
            total_completed = sum(s.features_completed for s in sessions)
            total_regressed = sum(s.features_regressed for s in sessions)
            total_errors = sum(s.errors_count for s in sessions)

            lines.append("-" * 60)
            lines.append(f"TOTALS | {'':>8} | {total_completed:>9} | {total_regressed:>9} | {total_errors:>6} |")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error reading cold memory: {e}"}],
            "is_error": True
        }


@tool(
    "memory_cold_knowledge",
    "Search proven knowledge extracted from historical sessions. This is distilled wisdom from past work.",
    {"query": str, "knowledge_type": str}
)
async def memory_cold_knowledge(args: dict[str, Any]) -> dict[str, Any]:
    """Search proven knowledge from cold memory."""
    query = args.get("query", "").lower()
    knowledge_type = args.get("knowledge_type", "")  # fix, pattern, warning, best_practice

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            db_query = select(ColdMemoryKnowledge).order_by(desc(ColdMemoryKnowledge.times_verified))

            if knowledge_type:
                db_query = db_query.where(ColdMemoryKnowledge.knowledge_type == knowledge_type)

            result = await session.execute(db_query)
            all_knowledge = result.scalars().all()

            if not all_knowledge:
                return {
                    "content": [{
                        "type": "text",
                        "text": "No proven knowledge in cold memory yet."
                    }]
                }

            # Filter by query if provided
            if query:
                matches = []
                for k in all_knowledge:
                    searchable = f"{k.title} {k.description} {' '.join(k.context_keywords or [])}".lower()
                    if query in searchable:
                        matches.append(k)
            else:
                matches = list(all_knowledge)

            if not matches:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"No knowledge found matching '{query}'."
                    }]
                }

            lines = [
                f"PROVEN KNOWLEDGE ({len(matches)} entries)",
                "=" * 50
            ]

            for k in matches[:15]:
                lines.append("")
                lines.append(f"[{k.knowledge_id}] {k.knowledge_type.upper()}: {k.title}")
                lines.append(f"  {k.description[:150]}...")
                lines.append(f"  Verified: {k.times_verified}x | Confidence: {k.confidence:.0%}")

                if k.context_keywords:
                    lines.append(f"  Keywords: {', '.join(k.context_keywords[:5])}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error searching knowledge: {e}"}],
            "is_error": True
        }


@tool(
    "memory_add_knowledge",
    "Add proven knowledge to cold memory for future sessions. Use this when you discover something that will help future agents.",
    {
        "type": "object",
        "properties": {
            "knowledge_type": {
                "type": "string",
                "description": "Type: fix, pattern, warning, best_practice"
            },
            "title": {
                "type": "string",
                "description": "Short title for this knowledge"
            },
            "description": {
                "type": "string",
                "description": "Detailed description of the knowledge"
            },
            "context_keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keywords for finding this knowledge"
            }
        },
        "required": ["knowledge_type", "title", "description"]
    }
)
async def memory_add_knowledge(args: dict[str, Any]) -> dict[str, Any]:
    """Add new knowledge to cold memory."""
    knowledge_type = args.get("knowledge_type", "best_practice")
    if knowledge_type not in ("fix", "pattern", "warning", "best_practice"):
        knowledge_type = "best_practice"

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            # Generate knowledge ID
            result = await session.execute(
                select(ColdMemoryKnowledge).order_by(desc(ColdMemoryKnowledge.id)).limit(1)
            )
            last = result.scalar_one_or_none()
            next_id = (last.id + 1) if last else 1

            new_knowledge = ColdMemoryKnowledge(
                knowledge_id=f"K-{next_id}",
                knowledge_type=knowledge_type,
                title=args.get("title", ""),
                description=args.get("description", ""),
                context_keywords=args.get("context_keywords", []),
                times_verified=1,
                confidence=0.5
            )
            session.add(new_knowledge)
            await session.commit()

            return {
                "content": [{
                    "type": "text",
                    "text": f"Knowledge [{new_knowledge.knowledge_id}] added successfully.\n\n"
                            f"Type: {knowledge_type}\n"
                            f"Title: {new_knowledge.title}\n\n"
                            f"Future agents will be able to find this knowledge."
                }]
            }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error adding knowledge: {e}"}],
            "is_error": True
        }


# =============================================================================
# Tool Registration
# =============================================================================

MEMORY_TOOLS = [
    "mcp__memory__memory_hot_get",
    "mcp__memory__memory_warm_sessions",
    "mcp__memory__memory_warm_issues",
    "mcp__memory__memory_warm_patterns",
    "mcp__memory__memory_cold_history",
    "mcp__memory__memory_cold_knowledge",
    "mcp__memory__memory_add_knowledge",
]


def create_memory_tools_server(project_dir: Path) -> McpSdkServerConfig:
    """
    Create an MCP server with memory access tools.

    Args:
        project_dir: The project directory

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    global _project_dir
    _project_dir = project_dir

    return create_sdk_mcp_server(
        name="memory",
        version="1.0.0",
        tools=[
            memory_hot_get,
            memory_warm_sessions,
            memory_warm_issues,
            memory_warm_patterns,
            memory_cold_history,
            memory_cold_knowledge,
            memory_add_knowledge,
        ]
    )
