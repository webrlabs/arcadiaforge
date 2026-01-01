"""
Custom MCP Tools for Agent Messaging (Database Backed)
======================================================

These tools allow agents to communicate across sessions via persistent messages.
Messages are stored in the project database and persist until acknowledged.

Message Types:
- warning: Alert about something dangerous or problematic
- hint: Suggestion for solving a problem
- blocker: Something that's blocking progress
- discovery: Important finding or insight
- handoff: Structured session handoff summary
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from sqlalchemy import select, func, desc
from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig

from arcadiaforge.db.models import AgentMessage
from arcadiaforge.db.connection import get_session_maker


# Global project directory and session ID
_project_dir: Path | None = None
_current_session_id: int = 1


def set_session_context(project_dir: Path, session_id: int) -> None:
    """Set the current session context for messaging tools."""
    global _project_dir, _current_session_id
    _project_dir = project_dir
    _current_session_id = session_id


async def _get_next_message_id() -> str:
    """Generate the next message ID."""
    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(func.count(AgentMessage.id))
            )
            count = result.scalar_one_or_none() or 0
            return f"MSG-{_current_session_id}-{count + 1}"
    except Exception:
        return f"MSG-{_current_session_id}-1"


def _format_message(msg: dict, include_body: bool = False) -> str:
    """Format a message for display."""
    priority_labels = {1: "CRITICAL", 2: "HIGH", 3: "NORMAL", 4: "LOW", 5: "INFO"}
    priority_label = priority_labels.get(msg.get("priority", 3), "NORMAL")

    lines = [
        f"[{msg.get('message_id', '?')}] [{msg.get('message_type', 'unknown').upper()}] [{priority_label}]",
        f"Subject: {msg.get('subject', 'No subject')}",
        f"From session: {msg.get('created_by_session', '?')} at {msg.get('created_at', 'unknown')}",
    ]

    if msg.get("related_features"):
        lines.append(f"Related features: {msg['related_features']}")

    if msg.get("tags"):
        lines.append(f"Tags: {', '.join(msg['tags'])}")

    if msg.get("acknowledged"):
        lines.append(f"ACKNOWLEDGED by session {msg.get('acknowledged_by_session', '?')}")

    if include_body:
        lines.append("")
        lines.append("--- Message Body ---")
        lines.append(msg.get("body", ""))
        lines.append("--- End ---")

    return "\n".join(lines)


@tool(
    "message_list",
    "List unread or unacknowledged messages from previous sessions. Use this at the start of each session to check for important information left by previous sessions.",
    {
        "type": "object",
        "properties": {
            "include_acknowledged": {
                "type": "boolean",
                "description": "Include acknowledged messages (default: false)"
            },
            "message_type": {
                "type": "string",
                "description": "Filter by message type (warning, hint, blocker, discovery, handoff)"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum messages to return (default: 20)"
            }
        }
    }
)
async def message_list(args: dict[str, Any]) -> dict[str, Any]:
    """List agent messages."""
    include_acknowledged = args.get("include_acknowledged", False)
    message_type = args.get("message_type")
    limit = args.get("limit", 20)

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            query = select(AgentMessage).order_by(desc(AgentMessage.created_at))

            if not include_acknowledged:
                query = query.where(AgentMessage.acknowledged == False)

            if message_type:
                query = query.where(AgentMessage.message_type == message_type)

            query = query.limit(limit)
            result = await session.execute(query)
            messages = result.scalars().all()

            if not messages:
                return {
                    "content": [{
                        "type": "text",
                        "text": "No messages found. Mailbox is empty."
                    }]
                }

            # Mark as read by this session
            for msg in messages:
                if _current_session_id not in (msg.read_by_sessions or []):
                    read_by = list(msg.read_by_sessions or [])
                    read_by.append(_current_session_id)
                    msg.read_by_sessions = read_by

            await session.commit()

            # Format output
            lines = [
                f"AGENT MESSAGES ({len(messages)} found)",
                "=" * 50,
            ]

            for msg in messages:
                lines.append("")
                lines.append(_format_message({
                    "message_id": msg.message_id,
                    "message_type": msg.message_type,
                    "priority": msg.priority,
                    "subject": msg.subject,
                    "created_by_session": msg.created_by_session,
                    "created_at": msg.created_at.isoformat() if msg.created_at else "unknown",
                    "related_features": msg.related_features,
                    "tags": msg.tags,
                    "acknowledged": msg.acknowledged,
                    "acknowledged_by_session": msg.acknowledged_by_session,
                }))

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error listing messages: {e}"}],
            "is_error": True
        }


@tool(
    "message_read",
    "Read the full content of a specific message by ID.",
    {"message_id": str}
)
async def message_read(args: dict[str, Any]) -> dict[str, Any]:
    """Read a specific message."""
    message_id = args["message_id"]

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(AgentMessage).where(AgentMessage.message_id == message_id)
            )
            msg = result.scalar_one_or_none()

            if not msg:
                return {
                    "content": [{"type": "text", "text": f"Message '{message_id}' not found."}],
                    "is_error": True
                }

            # Mark as read
            if _current_session_id not in (msg.read_by_sessions or []):
                read_by = list(msg.read_by_sessions or [])
                read_by.append(_current_session_id)
                msg.read_by_sessions = read_by
                await session.commit()

            return {
                "content": [{
                    "type": "text",
                    "text": _format_message({
                        "message_id": msg.message_id,
                        "message_type": msg.message_type,
                        "priority": msg.priority,
                        "subject": msg.subject,
                        "body": msg.body,
                        "created_by_session": msg.created_by_session,
                        "created_at": msg.created_at.isoformat() if msg.created_at else "unknown",
                        "related_features": msg.related_features,
                        "tags": msg.tags,
                        "acknowledged": msg.acknowledged,
                        "acknowledged_by_session": msg.acknowledged_by_session,
                    }, include_body=True)
                }]
            }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error reading message: {e}"}],
            "is_error": True
        }


@tool(
    "message_send",
    "Send a message for future sessions to read. Use this to leave warnings, hints, blockers, or discoveries.",
    {
        "type": "object",
        "properties": {
            "message_type": {
                "type": "string",
                "enum": ["warning", "hint", "blocker", "discovery"],
                "description": "Type of message"
            },
            "subject": {
                "type": "string",
                "description": "Brief subject line (max 255 chars)"
            },
            "body": {
                "type": "string",
                "description": "Full message content with details"
            },
            "priority": {
                "type": "integer",
                "description": "Priority 1-5 (1=critical, 3=normal, 5=info)"
            },
            "related_features": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Feature indices this message relates to"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tags for categorization (e.g., 'docker', 'auth', 'build')"
            }
        },
        "required": ["message_type", "subject", "body"]
    }
)
async def message_send(args: dict[str, Any]) -> dict[str, Any]:
    """Send a new message."""
    message_id = await _get_next_message_id()

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            msg = AgentMessage(
                message_id=message_id,
                created_by_session=_current_session_id,
                message_type=args["message_type"],
                priority=args.get("priority", 3),
                subject=args["subject"][:255],
                body=args["body"],
                related_features=args.get("related_features", []),
                tags=args.get("tags", []),
            )
            session.add(msg)
            await session.commit()

            return {
                "content": [{
                    "type": "text",
                    "text": f"Message sent successfully.\n\nID: {message_id}\nType: {args['message_type']}\nSubject: {args['subject']}"
                }]
            }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error sending message: {e}"}],
            "is_error": True
        }


@tool(
    "message_acknowledge",
    "Acknowledge a message to mark it as handled. Acknowledged messages won't appear in the default message list.",
    {"message_id": str}
)
async def message_acknowledge(args: dict[str, Any]) -> dict[str, Any]:
    """Acknowledge a message."""
    message_id = args["message_id"]

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(AgentMessage).where(AgentMessage.message_id == message_id)
            )
            msg = result.scalar_one_or_none()

            if not msg:
                return {
                    "content": [{"type": "text", "text": f"Message '{message_id}' not found."}],
                    "is_error": True
                }

            if msg.acknowledged:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Message '{message_id}' was already acknowledged by session {msg.acknowledged_by_session}."
                    }]
                }

            msg.acknowledged = True
            msg.acknowledged_by_session = _current_session_id
            msg.acknowledged_at = datetime.now(timezone.utc)
            await session.commit()

            return {
                "content": [{
                    "type": "text",
                    "text": f"Message '{message_id}' acknowledged successfully."
                }]
            }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error acknowledging message: {e}"}],
            "is_error": True
        }


@tool(
    "message_handoff",
    "Create a structured session handoff message. Use this at the end of each session to summarize work for the next session.",
    {
        "type": "object",
        "properties": {
            "current_work": {
                "type": "string",
                "description": "What you were working on"
            },
            "progress_made": {
                "type": "string",
                "description": "What progress was made"
            },
            "blockers": {
                "type": "string",
                "description": "What blockers remain (if any)"
            },
            "recommended_next": {
                "type": "string",
                "description": "Recommended next steps"
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Any warnings for the next session"
            },
            "related_features": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Feature indices worked on"
            }
        },
        "required": ["current_work", "progress_made", "recommended_next"]
    }
)
async def message_handoff(args: dict[str, Any]) -> dict[str, Any]:
    """Create a handoff message."""
    message_id = await _get_next_message_id()

    # Build structured handoff body
    body_parts = [
        "## Current Work",
        args["current_work"],
        "",
        "## Progress Made",
        args["progress_made"],
        "",
    ]

    if args.get("blockers"):
        body_parts.extend([
            "## Blockers",
            args["blockers"],
            "",
        ])

    body_parts.extend([
        "## Recommended Next Steps",
        args["recommended_next"],
    ])

    if args.get("warnings"):
        body_parts.extend([
            "",
            "## Warnings",
        ])
        for warning in args["warnings"]:
            body_parts.append(f"- {warning}")

    body = "\n".join(body_parts)
    subject = f"Session {_current_session_id} Handoff: {args['current_work'][:50]}"

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            msg = AgentMessage(
                message_id=message_id,
                created_by_session=_current_session_id,
                message_type="handoff",
                priority=2,  # Handoffs are high priority
                subject=subject[:255],
                body=body,
                related_features=args.get("related_features", []),
                tags=["handoff", f"session-{_current_session_id}"],
            )
            session.add(msg)
            await session.commit()

            return {
                "content": [{
                    "type": "text",
                    "text": f"Handoff message created successfully.\n\nID: {message_id}\n\n{body}"
                }]
            }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error creating handoff: {e}"}],
            "is_error": True
        }


# List of all messaging tool names (for allowed_tools)
MESSAGING_TOOLS = [
    "mcp__messaging__message_list",
    "mcp__messaging__message_read",
    "mcp__messaging__message_send",
    "mcp__messaging__message_acknowledge",
    "mcp__messaging__message_handoff",
]


def create_messaging_server(project_dir: Path, session_id: int = 1) -> McpSdkServerConfig:
    """
    Create an MCP server with agent messaging tools.

    Args:
        project_dir: The project directory
        session_id: Current session ID

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    set_session_context(project_dir, session_id)

    return create_sdk_mcp_server(
        name="messaging",
        version="1.0.0",
        tools=[
            message_list,
            message_read,
            message_send,
            message_acknowledge,
            message_handoff,
        ]
    )
