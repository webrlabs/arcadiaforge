"""
Custom MCP Tools for Capability Queries (Database Backed)
=========================================================

These tools allow agents to query system capabilities before attempting
to use external tools. This helps agents gracefully handle missing
dependencies like Docker.

Capabilities are checked at startup and cached in the database.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from sqlalchemy import select
from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig

from arcadiaforge.db.models import SystemCapability
from arcadiaforge.db.connection import get_session_maker

if TYPE_CHECKING:
    from arcadiaforge.human_interface import HumanInterface


# Global references
_project_dir: Path | None = None
_human_interface: Optional["HumanInterface"] = None


def set_capability_context(
    project_dir: Path,
    human_interface: Optional["HumanInterface"] = None,
) -> None:
    """Set the context for capability tools."""
    global _project_dir, _human_interface
    _project_dir = project_dir
    _human_interface = human_interface


def _format_capability(cap: dict) -> str:
    """Format a capability for display."""
    status = "AVAILABLE" if cap.get("is_available") else "NOT AVAILABLE"
    lines = [f"  {cap.get('name', '?')}: {status}"]

    if cap.get("version"):
        lines.append(f"    Version: {cap['version']}")

    if cap.get("path"):
        lines.append(f"    Path: {cap['path']}")

    if not cap.get("is_available") and cap.get("error_message"):
        lines.append(f"    Error: {cap['error_message']}")

    if cap.get("details"):
        for key, value in cap["details"].items():
            lines.append(f"    {key}: {value}")

    return "\n".join(lines)


@tool(
    "capability_list",
    "List all system capabilities and their availability. Use this at the start of each session to understand what tools are available.",
    {}
)
async def capability_list(args: dict[str, Any]) -> dict[str, Any]:
    """List all capabilities."""
    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(SystemCapability).order_by(SystemCapability.capability_name)
            )
            caps = result.scalars().all()

            if not caps:
                return {
                    "content": [{
                        "type": "text",
                        "text": "No capability information available. Capabilities are checked at startup."
                    }]
                }

            available = [c for c in caps if c.is_available]
            unavailable = [c for c in caps if not c.is_available]

            lines = [
                "SYSTEM CAPABILITIES",
                "=" * 50,
                "",
                f"Available ({len(available)}):",
            ]

            for cap in available:
                lines.append(_format_capability({
                    "name": cap.capability_name,
                    "is_available": cap.is_available,
                    "version": cap.version,
                    "path": cap.path,
                    "details": cap.details,
                }))

            if unavailable:
                lines.append("")
                lines.append(f"Not Available ({len(unavailable)}):")
                for cap in unavailable:
                    lines.append(_format_capability({
                        "name": cap.capability_name,
                        "is_available": cap.is_available,
                        "error_message": cap.error_message,
                        "details": cap.details,
                    }))

            # Add timestamp of last check
            if caps:
                latest_check = max(c.checked_at for c in caps if c.checked_at)
                lines.append("")
                lines.append(f"Last checked: {latest_check.isoformat() if latest_check else 'unknown'}")

            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error listing capabilities: {e}"}],
            "is_error": True
        }


@tool(
    "capability_check",
    "Check if a specific capability is available. Use this before attempting to use a tool that requires a specific dependency.",
    {"capability": str}
)
async def capability_check(args: dict[str, Any]) -> dict[str, Any]:
    """Check a specific capability."""
    capability_name = args["capability"].lower()

    try:
        session_maker = get_session_maker()
        async with session_maker() as session:
            result = await session.execute(
                select(SystemCapability)
                .where(SystemCapability.capability_name == capability_name)
            )
            cap = result.scalar_one_or_none()

            if not cap:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Capability '{capability_name}' is not tracked. Known capabilities: node, npx, docker, git, python."
                    }]
                }

            if cap.is_available:
                version_info = f" ({cap.version})" if cap.version else ""
                return {
                    "content": [{
                        "type": "text",
                        "text": f"AVAILABLE: {capability_name}{version_info}\n\nYou can use features that require {capability_name}."
                    }]
                }
            else:
                error_info = f"\nError: {cap.error_message}" if cap.error_message else ""
                return {
                    "content": [{
                        "type": "text",
                        "text": f"NOT AVAILABLE: {capability_name}{error_info}\n\nFeatures requiring {capability_name} should be skipped or marked as blocked."
                    }]
                }

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Error checking capability: {e}"}],
            "is_error": True
        }


@tool(
    "capability_request_help",
    "Request human help for a missing capability. Use this when you need a capability that isn't available and cannot proceed without it.",
    {
        "type": "object",
        "properties": {
            "capability": {
                "type": "string",
                "description": "The capability that is needed"
            },
            "reason": {
                "type": "string",
                "description": "Why this capability is needed"
            },
            "blocked_features": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Feature indices blocked by this missing capability"
            }
        },
        "required": ["capability", "reason"]
    }
)
async def capability_request_help(args: dict[str, Any]) -> dict[str, Any]:
    """Request help for a missing capability."""
    capability = args["capability"]
    reason = args["reason"]
    blocked_features = args.get("blocked_features", [])

    # Try to use human interface if available
    if _human_interface:
        try:
            from arcadiaforge.human_interface import InjectionType

            response = await _human_interface.request_input(
                injection_type=InjectionType.GUIDANCE,
                context={
                    "missing_capability": capability,
                    "reason": reason,
                    "blocked_features": blocked_features,
                },
                options=[
                    f"Install {capability} and continue",
                    "Skip features requiring this capability",
                    "Continue without this capability",
                ],
                recommendation="Skip features requiring this capability",
                message=f"Agent needs '{capability}' capability.\n\nReason: {reason}\nBlocked features: {blocked_features if blocked_features else 'none specified'}",
                timeout=300,  # 5 minute timeout
                default_on_timeout="Skip features requiring this capability",
            )

            return {
                "content": [{
                    "type": "text",
                    "text": f"Human response: {response}\n\nProceeding based on guidance."
                }]
            }

        except Exception as e:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Could not reach human interface: {e}\n\nRecommendation: Skip features requiring '{capability}' and mark them as blocked."
                }]
            }
    else:
        return {
            "content": [{
                "type": "text",
                "text": f"Missing capability: {capability}\nReason: {reason}\nBlocked features: {blocked_features}\n\nHuman interface not available. Recommendation: Skip features requiring '{capability}' and mark them as blocked."
            }]
        }


# List of all capability tool names (for allowed_tools)
CAPABILITY_TOOLS = [
    "mcp__capabilities__capability_list",
    "mcp__capabilities__capability_check",
    "mcp__capabilities__capability_request_help",
]


def create_capability_server(
    project_dir: Path,
    human_interface: Optional["HumanInterface"] = None,
) -> McpSdkServerConfig:
    """
    Create an MCP server with capability query tools.

    Args:
        project_dir: The project directory
        human_interface: Human interface for help requests

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    set_capability_context(project_dir, human_interface)

    return create_sdk_mcp_server(
        name="capabilities",
        version="1.0.0",
        tools=[
            capability_list,
            capability_check,
            capability_request_help,
        ]
    )
