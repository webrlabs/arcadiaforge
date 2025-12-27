"""
Custom MCP Tools for Progress Log Management (Database Backed)
==============================================================

These tools allow the agent to manage progress entries stored in the
project database (.arcadia/project.db).

Progress entries track:
- What was accomplished in each session
- Tests completed
- Issues found and fixed
- Next steps for future sessions
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from sqlalchemy import select, func
from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig

from arcadiaforge.db.models import ProgressEntry
from arcadiaforge.db.connection import get_session_maker


# Global project directory - set when server is created
_project_dir: Path | None = None


async def _get_next_session_id() -> int:
    """Get the next session ID from database."""
    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(func.max(ProgressEntry.session_id))
            )
            max_id = result.scalar_one_or_none()
            return (max_id or 0) + 1
    except Exception:
        return 1


async def _load_entries() -> List[dict]:
    """Load all progress entries from database."""
    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(ProgressEntry).order_by(ProgressEntry.session_id)
            )
            entries = result.scalars().all()
            return [
                {
                    "session_id": e.session_id,
                    "timestamp": e.timestamp.isoformat() if e.timestamp else "",
                    "accomplished": e.accomplished or [],
                    "tests_completed": e.tests_completed or [],
                    "tests_status": e.tests_status or "unknown",
                    "issues_found": e.issues_found or [],
                    "issues_fixed": e.issues_fixed or [],
                    "next_steps": e.next_steps or [],
                    "notes": e.notes or ""
                }
                for e in entries
            ]
    except Exception:
        return []


def _format_entry(entry: dict, verbose: bool = False) -> str:
    """Format a progress entry for display."""
    lines = [
        f"Session #{entry.get('session_id', '?')} - {entry.get('timestamp', 'Unknown time')}",
        "-" * 50,
        f"Status: {entry.get('tests_status', 'Unknown')}",
    ]

    if entry.get("accomplished"):
        lines.append("\nAccomplished:")
        for item in entry["accomplished"]:
            lines.append(f"  - {item}")

    if entry.get("tests_completed"):
        tests = entry["tests_completed"]
        if len(tests) <= 5:
            lines.append(f"\nTests completed: {tests}")
        else:
            lines.append(f"\nTests completed: {len(tests)} tests ({tests[:3]}...)")

    if entry.get("issues_fixed"):
        lines.append("\nIssues fixed:")
        for item in entry["issues_fixed"]:
            lines.append(f"  - {item}")

    if entry.get("issues_found"):
        lines.append("\nIssues found (needs attention):")
        for item in entry["issues_found"]:
            lines.append(f"  - {item}")

    if entry.get("next_steps"):
        lines.append("\nNext steps:")
        for item in entry["next_steps"]:
            lines.append(f"  - {item}")

    if verbose and entry.get("notes"):
        lines.append(f"\nNotes: {entry['notes']}")

    return "\n".join(lines)


@tool(
    "progress_get_last",
    "Get the last progress entry from the previous coding session. Use this at the start of each session to understand what was done previously.",
    {"count": int}
)
async def progress_get_last(args: dict[str, Any]) -> dict[str, Any]:
    """Get the last N progress entries."""
    count = args.get("count", 1)
    if count < 1:
        count = 1

    entries = await _load_entries()

    if not entries:
        return {
            "content": [{
                "type": "text",
                "text": "No progress entries found. This appears to be the first session."
            }]
        }

    # Get last N entries (most recent first)
    recent = entries[-count:][::-1]

    lines = [f"LAST {len(recent)} PROGRESS ENTRY/ENTRIES", "=" * 50]
    for entry in recent:
        lines.append("")
        lines.append(_format_entry(entry, verbose=True))

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "progress_add",
    "Add a new progress entry at the end of a coding session. Records what was accomplished, tests completed, issues found/fixed, and next steps.",
    {
        "type": "object",
        "properties": {
            "accomplished": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of things accomplished this session"
            },
            "tests_completed": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of test/feature indices that were completed"
            },
            "tests_status": {
                "type": "string",
                "description": "Current test status (e.g., '45/200 passing')"
            },
            "issues_found": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of issues discovered that need attention"
            },
            "issues_fixed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of issues that were fixed this session"
            },
            "next_steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Recommended next steps for the following session"
            },
            "notes": {
                "type": "string",
                "description": "Optional additional notes"
            }
        },
        "required": ["accomplished", "tests_status", "next_steps"]
    }
)
async def progress_add(args: dict[str, Any]) -> dict[str, Any]:
    """Add a new progress entry to database."""
    session_id = await _get_next_session_id()

    new_entry = {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "accomplished": args.get("accomplished", []),
        "tests_completed": args.get("tests_completed", []),
        "tests_status": args.get("tests_status", "unknown"),
        "issues_found": args.get("issues_found", []),
        "issues_fixed": args.get("issues_fixed", []),
        "next_steps": args.get("next_steps", []),
        "notes": args.get("notes", "")
    }

    # Save to database
    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            entry = ProgressEntry(
                session_id=session_id,
                accomplished=new_entry["accomplished"],
                tests_completed=new_entry["tests_completed"],
                tests_status=new_entry["tests_status"],
                issues_found=new_entry["issues_found"],
                issues_fixed=new_entry["issues_fixed"],
                next_steps=new_entry["next_steps"],
                notes=new_entry["notes"]
            )
            session.add(entry)
            await session.commit()
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error saving progress: {e}"
            }],
            "is_error": True
        }

    return {
        "content": [{
            "type": "text",
            "text": f"Progress entry #{new_entry['session_id']} added successfully.\n\n{_format_entry(new_entry)}"
        }]
    }


@tool(
    "progress_summary",
    "Get a summary of all progress entries showing overall project progression.",
    {}
)
async def progress_summary(args: dict[str, Any]) -> dict[str, Any]:
    """Get a summary of all progress."""
    entries = await _load_entries()

    if not entries:
        return {
            "content": [{
                "type": "text",
                "text": "No progress entries found. This appears to be a new project."
            }]
        }

    total_sessions = len(entries)
    first_entry = entries[0]
    last_entry = entries[-1]

    # Count total accomplishments and issues
    total_accomplished = sum(len(e.get("accomplished", [])) for e in entries)
    total_tests_completed = set()
    for e in entries:
        total_tests_completed.update(e.get("tests_completed", []))
    total_issues_fixed = sum(len(e.get("issues_fixed", [])) for e in entries)

    # Get current status from last entry
    current_status = last_entry.get("tests_status", "unknown")

    lines = [
        "PROJECT PROGRESS SUMMARY",
        "=" * 50,
        f"Total sessions:        {total_sessions}",
        f"First session:         {first_entry.get('timestamp', 'unknown')[:10]}",
        f"Last session:          {last_entry.get('timestamp', 'unknown')[:10]}",
        "",
        f"Total accomplishments: {total_accomplished}",
        f"Total tests completed: {len(total_tests_completed)}",
        f"Total issues fixed:    {total_issues_fixed}",
        "",
        f"Current status:        {current_status}",
        "",
        "Recent sessions:",
    ]

    # Show last 5 sessions briefly
    for entry in entries[-5:][::-1]:
        sid = entry.get("session_id", "?")
        status = entry.get("tests_status", "?")
        accomplished_count = len(entry.get("accomplished", []))
        lines.append(f"  Session #{sid}: {status} ({accomplished_count} items done)")

    if last_entry.get("next_steps"):
        lines.append("")
        lines.append("Pending next steps (from last session):")
        for step in last_entry["next_steps"]:
            lines.append(f"  - {step}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "progress_search",
    "Search progress entries for a keyword in accomplishments, issues, or notes.",
    {"query": str}
)
async def progress_search(args: dict[str, Any]) -> dict[str, Any]:
    """Search progress entries by keyword."""
    query = args["query"].lower()
    entries = await _load_entries()

    if not entries:
        return {
            "content": [{
                "type": "text",
                "text": "No progress entries to search."
            }]
        }

    matches = []
    for entry in entries:
        # Search in various fields
        searchable = []
        searchable.extend(entry.get("accomplished", []))
        searchable.extend(entry.get("issues_found", []))
        searchable.extend(entry.get("issues_fixed", []))
        searchable.extend(entry.get("next_steps", []))
        searchable.append(entry.get("notes", ""))

        text = " ".join(str(s) for s in searchable).lower()
        if query in text:
            matches.append(entry)

    if not matches:
        return {
            "content": [{
                "type": "text",
                "text": f"No progress entries found matching '{query}'."
            }]
        }

    lines = [
        f"SEARCH RESULTS FOR '{query}' ({len(matches)} matches)",
        "=" * 50
    ]

    for entry in matches:
        lines.append("")
        lines.append(_format_entry(entry, verbose=False))

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "progress_get_issues",
    "Get all unresolved issues from progress entries. Shows issues that were found but not yet marked as fixed.",
    {}
)
async def progress_get_issues(args: dict[str, Any]) -> dict[str, Any]:
    """Get all unresolved issues."""
    entries = await _load_entries()

    if not entries:
        return {
            "content": [{
                "type": "text",
                "text": "No progress entries found."
            }]
        }

    # Collect all issues found and fixed
    all_found = []
    all_fixed = set()

    for entry in entries:
        for issue in entry.get("issues_found", []):
            all_found.append((entry.get("session_id", "?"), issue))
        for issue in entry.get("issues_fixed", []):
            all_fixed.add(issue.lower())

    # Find unresolved (found but not in fixed)
    unresolved = [
        (sid, issue) for sid, issue in all_found
        if issue.lower() not in all_fixed
    ]

    if not unresolved:
        return {
            "content": [{
                "type": "text",
                "text": "No unresolved issues found. All discovered issues have been fixed!"
            }]
        }

    lines = [
        f"UNRESOLVED ISSUES ({len(unresolved)} total)",
        "=" * 50,
    ]

    for sid, issue in unresolved:
        lines.append(f"  [Session #{sid}] {issue}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# List of all progress tool names (for allowed_tools)
PROGRESS_TOOLS = [
    "mcp__progress__progress_get_last",
    "mcp__progress__progress_add",
    "mcp__progress__progress_summary",
    "mcp__progress__progress_search",
    "mcp__progress__progress_get_issues",
]


def create_progress_tools_server(project_dir: Path) -> McpSdkServerConfig:
    """
    Create an MCP server with progress management tools.

    Args:
        project_dir: The project directory

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    global _project_dir
    _project_dir = project_dir

    return create_sdk_mcp_server(
        name="progress",
        version="1.0.0",
        tools=[
            progress_get_last,
            progress_add,
            progress_summary,
            progress_search,
            progress_get_issues,
        ]
    )
