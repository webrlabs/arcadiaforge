"""
Evidence Management MCP Server
==============================

MCP server for managing feature verification evidence.
Provides tools to set screenshot context, save evidence, and list evidence files.
"""

import shutil
from pathlib import Path
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from . import screenshot_hook


# Create the MCP server
mcp = FastMCP("evidence")


# Tool name constants for registration
EVIDENCE_TOOLS = [
    "mcp__evidence__evidence_set_context",
    "mcp__evidence__evidence_save",
    "mcp__evidence__evidence_list",
    "mcp__evidence__evidence_get_latest",
]


# Module-level project directory (set during server creation)
_project_dir: Optional[Path] = None


def set_project_dir(project_dir: Path) -> None:
    """Set the project directory for evidence operations."""
    global _project_dir
    _project_dir = project_dir


def get_project_dir() -> Path:
    """Get the project directory, falling back to cwd."""
    return _project_dir or Path.cwd()


@mcp.tool()
def evidence_set_context(
    feature_id: int,
    name: str = None,
    auto_save: bool = True,
    description: str = None
) -> dict:
    """
    Set context for the next screenshot to automatically save as evidence.

    Call this BEFORE taking a screenshot to customize naming and enable
    automatic evidence collection.

    Args:
        feature_id: The feature number this evidence is for
        name: Optional custom name (default: feature_{id}_evidence)
        auto_save: Whether to auto-copy to verification folder (default: True)
        description: Optional description for the screenshot

    Returns:
        Confirmation of context set

    Example:
        evidence_set_context(feature_id=107, description="Delete modal shown")
        puppeteer_screenshot()  # Will save as feature_107_evidence.png
    """
    screenshot_hook.set_screenshot_context(
        name=name,
        feature_id=feature_id,
        auto_evidence=auto_save,
        description=description
    )

    return {
        "success": True,
        "message": f"Next screenshot will be saved as evidence for feature #{feature_id}",
        "settings": {
            "feature_id": feature_id,
            "custom_name": name,
            "auto_save": auto_save,
            "description": description
        }
    }


@mcp.tool()
def evidence_save(feature_id: int, source_screenshot: str = None) -> dict:
    """
    Save a screenshot as evidence for a feature.

    If no source is provided, uses the most recent screenshot.

    Args:
        feature_id: The feature number
        source_screenshot: Path to existing screenshot (if not provided, uses latest)

    Returns:
        Path to saved evidence file

    Example:
        # Save latest screenshot as evidence
        evidence_save(feature_id=107)

        # Save specific screenshot
        evidence_save(feature_id=107, source_screenshot="screenshots/my_screenshot.png")
    """
    try:
        project_dir = get_project_dir()
        verification_dir = project_dir / "verification"
        verification_dir.mkdir(parents=True, exist_ok=True)

        if source_screenshot:
            source = Path(source_screenshot)
            if not source.is_absolute():
                source = project_dir / source
        else:
            # Find latest screenshot
            screenshots_dir = project_dir / "screenshots"
            if not screenshots_dir.exists():
                return {"success": False, "error": "No screenshots directory found"}

            screenshots = list(screenshots_dir.glob("*.png"))
            if not screenshots:
                return {"success": False, "error": "No screenshots found"}

            source = max(screenshots, key=lambda p: p.stat().st_mtime)

        if not source.exists():
            return {"success": False, "error": f"Source screenshot not found: {source}"}

        dest = verification_dir / f"feature_{feature_id}_evidence.png"
        shutil.copy2(source, dest)

        return {
            "success": True,
            "path": str(dest),
            "source": str(source),
            "feature_id": feature_id
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def evidence_list(feature_ids: List[int] = None) -> dict:
    """
    List all evidence files, optionally filtered by feature IDs.

    Args:
        feature_ids: Optional list of feature IDs to filter by

    Returns:
        List of evidence files with metadata

    Example:
        # List all evidence
        evidence_list()

        # List evidence for specific features
        evidence_list(feature_ids=[105, 106, 107])
    """
    try:
        project_dir = get_project_dir()
        verification_dir = project_dir / "verification"

        if not verification_dir.exists():
            return {"success": True, "evidence": [], "count": 0}

        evidence_files = []

        for f in verification_dir.glob("feature_*_evidence.png"):
            # Extract feature ID from filename
            parts = f.stem.split("_")
            if len(parts) >= 2:
                try:
                    fid = int(parts[1])
                    if feature_ids is None or fid in feature_ids:
                        evidence_files.append({
                            "feature_id": fid,
                            "path": str(f),
                            "filename": f.name,
                            "size": f.stat().st_size,
                            "modified": f.stat().st_mtime
                        })
                except ValueError:
                    # Not a valid feature ID, skip
                    pass

        # Sort by feature ID
        evidence_files.sort(key=lambda x: x["feature_id"])

        return {
            "success": True,
            "evidence": evidence_files,
            "count": len(evidence_files)
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def evidence_get_latest(count: int = 5) -> dict:
    """
    Get the most recent screenshots from the screenshots directory.

    Useful for checking what screenshots are available before saving as evidence.

    Args:
        count: Number of recent screenshots to return (default: 5)

    Returns:
        List of recent screenshot paths and metadata
    """
    try:
        project_dir = get_project_dir()
        screenshots_dir = project_dir / "screenshots"

        if not screenshots_dir.exists():
            return {"success": True, "screenshots": [], "count": 0}

        screenshots = list(screenshots_dir.glob("*.png"))

        if not screenshots:
            return {"success": True, "screenshots": [], "count": 0}

        # Sort by modification time, most recent first
        screenshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        result = []
        for s in screenshots[:count]:
            result.append({
                "path": str(s),
                "filename": s.name,
                "size": s.stat().st_size,
                "modified": s.stat().st_mtime
            })

        return {
            "success": True,
            "screenshots": result,
            "count": len(result),
            "total_available": len(screenshots)
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def create_evidence_tools_server(project_dir: Path) -> dict:
    """
    Create the evidence tools MCP server configuration.

    Args:
        project_dir: Project directory path

    Returns:
        Server configuration dict for claude-code-sdk
    """
    # Set the project directory for this server
    set_project_dir(project_dir)

    return {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "arcadiaforge.evidence_tools"],
        "cwd": str(project_dir),
    }


if __name__ == "__main__":
    mcp.run()
