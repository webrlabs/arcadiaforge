"""
Custom MCP Tools for Troubleshooting Knowledge Base (Database Backed)
======================================================================

These tools allow agents to share troubleshooting knowledge with each other.
When an agent encounters an issue and solves it, they record the solution.
Future agents can search this knowledge base when they encounter similar issues.

All troubleshooting data is stored in the database (.arcadia/project.db).

Usage:
    from arcadiaforge.troubleshooting_tools import create_troubleshooting_tools_server, TROUBLESHOOTING_TOOLS

    server = create_troubleshooting_tools_server(project_dir)

    options = ClaudeCodeOptions(
        mcp_servers={"troubleshooting": server},
        allowed_tools=[...TROUBLESHOOTING_TOOLS]
    )
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from sqlalchemy import select, func
from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig

from arcadiaforge.db.models import TroubleshootingEntry
from arcadiaforge.db.connection import get_session_maker


# Global project directory - set when server is created
_project_dir: Path | None = None

# Common categories for troubleshooting entries
CATEGORIES = [
    "build",        # Build/compilation errors
    "runtime",      # Runtime errors
    "dependency",   # Package/dependency issues
    "config",       # Configuration problems
    "styling",      # CSS/UI styling issues
    "api",          # API/backend errors
    "database",     # Database issues
    "testing",      # Test failures
    "environment",  # Environment setup issues
    "git",          # Version control issues
    "performance",  # Performance problems
    "other",        # Miscellaneous
]


async def _load_entries() -> List[dict]:
    """Load all troubleshooting entries from database."""
    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(TroubleshootingEntry).order_by(TroubleshootingEntry.id)
            )
            entries = result.scalars().all()
            return [
                {
                    "id": e.id,
                    "timestamp": e.timestamp.isoformat() if e.timestamp else "",
                    "category": e.category,
                    "tags": e.tags or [],
                    "error_message": e.error_message,
                    "symptoms": e.symptoms or [],
                    "cause": e.cause or "",
                    "solution": e.solution,
                    "steps_to_fix": e.steps_to_fix or [],
                    "prevention": e.prevention or ""
                }
                for e in entries
            ]
    except Exception:
        return []


def _format_entry(entry: dict, verbose: bool = True) -> str:
    """Format a troubleshooting entry for display."""
    lines = [
        f"[#{entry.get('id', '?')}] {entry.get('category', 'unknown').upper()}",
        f"Error: {entry.get('error_message', 'No error message')}",
        "-" * 50,
    ]

    if entry.get("symptoms"):
        lines.append("Symptoms:")
        for symptom in entry["symptoms"]:
            lines.append(f"  - {symptom}")

    if entry.get("cause"):
        lines.append(f"\nCause: {entry['cause']}")

    lines.append(f"\nSolution: {entry.get('solution', 'No solution provided')}")

    if verbose and entry.get("steps_to_fix"):
        lines.append("\nSteps to fix:")
        for i, step in enumerate(entry["steps_to_fix"], 1):
            lines.append(f"  {i}. {step}")

    if verbose and entry.get("prevention"):
        lines.append(f"\nPrevention: {entry['prevention']}")

    if entry.get("tags"):
        lines.append(f"\nTags: {', '.join(entry['tags'])}")

    if verbose:
        lines.append(f"\nAdded: {entry.get('timestamp', 'unknown')[:10]}")

    return "\n".join(lines)


@tool(
    "troubleshoot_search",
    "Search the troubleshooting knowledge base for solutions to an error or issue. Use this FIRST when you encounter any error or unexpected behavior.",
    {"query": str}
)
async def troubleshoot_search(args: dict[str, Any]) -> dict[str, Any]:
    """Search troubleshooting entries by keyword."""
    query = args["query"].lower()
    entries = await _load_entries()

    if not entries:
        return {
            "content": [{
                "type": "text",
                "text": "No troubleshooting entries found. This knowledge base is empty.\n\n"
                        "If you solve this issue, please add it using troubleshoot_add so future agents can benefit."
            }]
        }

    matches = []
    for entry in entries:
        # Search in multiple fields
        searchable = [
            entry.get("error_message", ""),
            entry.get("cause", ""),
            entry.get("solution", ""),
            entry.get("category", ""),
            entry.get("prevention", ""),
            " ".join(entry.get("symptoms", [])),
            " ".join(entry.get("steps_to_fix", [])),
            " ".join(entry.get("tags", [])),
        ]
        text = " ".join(str(s) for s in searchable).lower()
        if query in text:
            matches.append(entry)

    if not matches:
        return {
            "content": [{
                "type": "text",
                "text": f"No troubleshooting entries found matching '{query}'.\n\n"
                        f"Available categories: {', '.join(CATEGORIES)}\n\n"
                        "If you solve this issue, please add it using troubleshoot_add."
            }]
        }

    lines = [
        f"TROUBLESHOOTING RESULTS FOR '{query}' ({len(matches)} matches)",
        "=" * 60
    ]

    for entry in matches:
        lines.append("")
        lines.append(_format_entry(entry, verbose=True))
        lines.append("")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "troubleshoot_add",
    "Add a new entry to the troubleshooting knowledge base. Use this after you solve an issue so future agents can benefit from your solution.",
    {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Category: build, runtime, dependency, config, styling, api, database, testing, environment, git, performance, other"
            },
            "error_message": {
                "type": "string",
                "description": "The exact error message or a summary of the problem"
            },
            "symptoms": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Observable symptoms (e.g., 'build fails', 'page won't load')"
            },
            "cause": {
                "type": "string",
                "description": "What caused the issue"
            },
            "solution": {
                "type": "string",
                "description": "Brief description of the fix"
            },
            "steps_to_fix": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Step-by-step instructions to fix the issue"
            },
            "prevention": {
                "type": "string",
                "description": "How to prevent this issue in the future"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keywords for searching (e.g., 'npm', 'react', 'typescript')"
            }
        },
        "required": ["category", "error_message", "solution"]
    }
)
async def troubleshoot_add(args: dict[str, Any]) -> dict[str, Any]:
    """Add a new troubleshooting entry to database."""
    # Validate category
    category = args.get("category", "other").lower()
    if category not in CATEGORIES:
        category = "other"

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            new_entry = TroubleshootingEntry(
                category=category,
                error_message=args.get("error_message", ""),
                symptoms=args.get("symptoms", []),
                cause=args.get("cause", ""),
                solution=args.get("solution", ""),
                steps_to_fix=args.get("steps_to_fix", []),
                prevention=args.get("prevention", ""),
                tags=[t.lower() for t in args.get("tags", [])]
            )
            session.add(new_entry)
            await session.commit()
            await session.refresh(new_entry)

            entry_dict = {
                "id": new_entry.id,
                "timestamp": new_entry.timestamp.isoformat() if new_entry.timestamp else "",
                "category": new_entry.category,
                "error_message": new_entry.error_message,
                "solution": new_entry.solution,
                "tags": new_entry.tags
            }

            return {
                "content": [{
                    "type": "text",
                    "text": f"Troubleshooting entry #{new_entry.id} added successfully.\n\n"
                            f"Future agents encountering similar issues can now find this solution.\n\n"
                            f"{_format_entry(entry_dict, verbose=False)}"
                }]
            }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error saving troubleshooting entry: {e}"
            }],
            "is_error": True
        }


@tool(
    "troubleshoot_get_recent",
    "Get the most recent troubleshooting entries. Useful to see what issues have been encountered recently.",
    {"count": int}
)
async def troubleshoot_get_recent(args: dict[str, Any]) -> dict[str, Any]:
    """Get the most recent troubleshooting entries."""
    count = args.get("count", 5)
    if count < 1:
        count = 1
    if count > 20:
        count = 20

    entries = await _load_entries()

    if not entries:
        return {
            "content": [{
                "type": "text",
                "text": "No troubleshooting entries found. The knowledge base is empty."
            }]
        }

    recent = entries[-count:][::-1]  # Most recent first

    lines = [
        f"RECENT TROUBLESHOOTING ENTRIES ({len(recent)} shown)",
        "=" * 60
    ]

    for entry in recent:
        lines.append("")
        lines.append(_format_entry(entry, verbose=False))

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "troubleshoot_get_by_category",
    "Get all troubleshooting entries for a specific category (build, runtime, dependency, config, styling, api, database, testing, environment, git, performance, other).",
    {"category": str}
)
async def troubleshoot_get_by_category(args: dict[str, Any]) -> dict[str, Any]:
    """Get troubleshooting entries by category."""
    category = args["category"].lower()

    if category not in CATEGORIES:
        return {
            "content": [{
                "type": "text",
                "text": f"Unknown category: '{category}'\n\n"
                        f"Available categories: {', '.join(CATEGORIES)}"
            }]
        }

    entries = await _load_entries()
    matches = [e for e in entries if e.get("category", "").lower() == category]

    if not matches:
        return {
            "content": [{
                "type": "text",
                "text": f"No troubleshooting entries found for category '{category}'."
            }]
        }

    lines = [
        f"TROUBLESHOOTING: {category.upper()} ({len(matches)} entries)",
        "=" * 60
    ]

    for entry in matches:
        lines.append("")
        lines.append(_format_entry(entry, verbose=False))

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "troubleshoot_list_categories",
    "List all categories and how many troubleshooting entries exist in each.",
    {}
)
async def troubleshoot_list_categories(args: dict[str, Any]) -> dict[str, Any]:
    """List categories with entry counts."""
    entries = await _load_entries()

    if not entries:
        return {
            "content": [{
                "type": "text",
                "text": "No troubleshooting entries found.\n\n"
                        f"Available categories: {', '.join(CATEGORIES)}"
            }]
        }

    # Count by category
    counts = {}
    for entry in entries:
        cat = entry.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1

    lines = [
        "TROUBLESHOOTING KNOWLEDGE BASE",
        "=" * 50,
        f"Total entries: {len(entries)}",
        "",
        "Entries by category:",
    ]

    for cat in CATEGORIES:
        count = counts.get(cat, 0)
        if count > 0:
            lines.append(f"  {cat:15} {count:3} entries")

    # Show most common tags
    all_tags = []
    for entry in entries:
        all_tags.extend(entry.get("tags", []))

    if all_tags:
        tag_counts = {}
        for tag in all_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        lines.append("")
        lines.append("Common tags:")
        lines.append(f"  {', '.join(t[0] for t in top_tags)}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# List of all troubleshooting tool names (for allowed_tools)
TROUBLESHOOTING_TOOLS = [
    "mcp__troubleshooting__troubleshoot_search",
    "mcp__troubleshooting__troubleshoot_add",
    "mcp__troubleshooting__troubleshoot_get_recent",
    "mcp__troubleshooting__troubleshoot_get_by_category",
    "mcp__troubleshooting__troubleshoot_list_categories",
]


def create_troubleshooting_tools_server(project_dir: Path) -> McpSdkServerConfig:
    """
    Create an MCP server with troubleshooting knowledge base tools.

    Args:
        project_dir: The project directory

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    global _project_dir
    _project_dir = project_dir

    return create_sdk_mcp_server(
        name="troubleshooting",
        version="1.0.0",
        tools=[
            troubleshoot_search,
            troubleshoot_add,
            troubleshoot_get_recent,
            troubleshoot_get_by_category,
            troubleshoot_list_categories,
        ]
    )
