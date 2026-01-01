"""
Puppeteer Screenshot Handler
============================

Hook to intercept puppeteer_screenshot results, save them to disk,
and return the file path to the agent.

Supports custom naming via screenshot context for evidence collection.
"""

import base64
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from arcadiaforge.output import print_info, print_success, print_error


# =============================================================================
# Screenshot Context Management
# =============================================================================

# Module-level state for screenshot naming context
_screenshot_context: Dict[str, Any] = {
    "custom_name": None,
    "feature_id": None,
    "auto_save_evidence": False,
    "description": None,
}

# Global counter for screenshots
_screenshot_seq = 0


def set_screenshot_context(
    name: str = None,
    feature_id: int = None,
    auto_evidence: bool = False,
    description: str = None
) -> None:
    """
    Set context for the next screenshot capture.

    Call this before taking a screenshot to customize the filename
    and enable automatic evidence collection.

    Args:
        name: Custom filename (without extension)
        feature_id: Feature ID for evidence naming
        auto_evidence: If True, auto-copy to verification folder
        description: Optional description for the screenshot
    """
    global _screenshot_context
    _screenshot_context = {
        "custom_name": name,
        "feature_id": feature_id,
        "auto_save_evidence": auto_evidence,
        "description": description,
    }


def clear_screenshot_context() -> None:
    """Clear screenshot context after capture."""
    global _screenshot_context
    _screenshot_context = {
        "custom_name": None,
        "feature_id": None,
        "auto_save_evidence": False,
        "description": None,
    }


def get_screenshot_context() -> Dict[str, Any]:
    """Get current screenshot context (read-only copy)."""
    return _screenshot_context.copy()


def get_next_screenshot_seq() -> int:
    """Get next screenshot sequence number."""
    global _screenshot_seq
    _screenshot_seq += 1
    return _screenshot_seq


# =============================================================================
# Screenshot Saving Hook
# =============================================================================

async def screenshot_saver_hook(result_data: dict, tool_use_id: str = None, context: dict = None) -> dict:
    """
    Post-tool-use hook to save Puppeteer screenshots to disk.

    Intercepts the base64 output from mcp__puppeteer__puppeteer_screenshot,
    saves it to the project's screenshots/ directory with optional custom naming.

    Args:
        result_data: Dict containing tool_name, tool_input, and tool_result
        tool_use_id: Optional tool use ID
        context: Optional context

    Returns:
        Empty dict to allow, or modified result
    """
    # Extract tool info from result_data dict
    tool_name = result_data.get("tool_name", "") if isinstance(result_data, dict) else getattr(result_data, "tool_name", "")

    # Only handle the screenshot tool
    if tool_name != "mcp__puppeteer__puppeteer_screenshot":
        return {}

    # Get tool response (SDK uses "tool_response", not "tool_result")
    tool_response = result_data.get("tool_response", {})

    # Check if tool execution was successful and extract content
    is_error = False
    content = []

    if isinstance(tool_response, list):
        # tool_response is directly a list of content blocks
        content = tool_response
    elif isinstance(tool_response, dict):
        is_error = tool_response.get("is_error", False)
        content = tool_response.get("content", [])
    elif hasattr(tool_response, "is_error"):
        is_error = tool_response.is_error
        content = getattr(tool_response, "content", [])

    if is_error or not content:
        return {}

    # Look for image content block
    image_data = None
    image_block_index = -1

    # Iterate through blocks to find image data (base64)
    for i, block in enumerate(content):
        # Handle ImageContent object (SDK typed)
        if hasattr(block, "type") and block.type == "image":
            # Check both 'data' attribute and 'source' attribute (MCP format)
            image_data = getattr(block, "data", None)
            if not image_data and hasattr(block, "source"):
                source = block.source
                if isinstance(source, dict):
                    image_data = source.get("data")
                elif hasattr(source, "data"):
                    image_data = source.data
            image_block_index = i
            break
        # Handle dict representation (if SDK returns dicts)
        elif isinstance(block, dict) and block.get("type") == "image":
            image_data = block.get("data")
            # Also check MCP source format
            if not image_data and "source" in block:
                source = block["source"]
                if isinstance(source, dict):
                    image_data = source.get("data")
            image_block_index = i
            break
        # Handle TextContent that might be base64 (less likely for standard MCP but possible)
        elif hasattr(block, "type") and block.type == "text":
            text = getattr(block, "text", "")
            if len(text) > 1000 and "base64" not in text[:100]: # Heuristic
                 # Some tools return base64 in text.
                 # Puppeteer MCP usually returns ImageContent.
                 pass

    if not image_data:
        # No image data found in content blocks
        return {}

    try:
        # Get project directory from result_data (SDK provides it as 'cwd')
        cwd_str = result_data.get("cwd", "") if isinstance(result_data, dict) else ""
        if cwd_str:
            cwd = Path(cwd_str)
        else:
            # Fallback to current working directory
            cwd = Path.cwd()

        # Ensure screenshots directory exists
        screenshots_dir = cwd / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Get screenshot context for custom naming
        ctx = get_screenshot_context()
        custom_name = ctx.get("custom_name")
        feature_id = ctx.get("feature_id")
        auto_evidence = ctx.get("auto_save_evidence", False)
        description = ctx.get("description")

        # Generate filename based on context
        if custom_name:
            # Use custom name provided
            filename = f"{custom_name}.png"
        elif feature_id:
            # Use feature-based naming
            filename = f"feature_{feature_id}_evidence.png"
        else:
            # Default: timestamp-based naming with sequence
            seq = get_next_screenshot_seq()
            timestamp = int(time.time())
            filename = f"screenshot_{timestamp}_{seq:03d}.png"

        file_path = screenshots_dir / filename

        # Save the image
        image_bytes = base64.b64decode(image_data)
        with open(file_path, "wb") as f:
            f.write(image_bytes)

        print_success(f"Screenshot saved: {file_path.relative_to(cwd)}")

        # Auto-save to verification folder if enabled
        evidence_path = None
        if auto_evidence and feature_id:
            verification_dir = cwd / "verification"
            verification_dir.mkdir(parents=True, exist_ok=True)
            evidence_path = verification_dir / f"feature_{feature_id}_evidence.png"
            shutil.copy2(file_path, evidence_path)
            print_success(f"Evidence saved: {evidence_path.relative_to(cwd)}")

        # Clear context after use (single-shot context)
        clear_screenshot_context()

        # Modify the tool result to show the path instead of the image data
        # This saves context tokens and gives the agent the path it needs
        from claude_code_sdk.types import TextBlock

        new_text_parts = [
            f"Screenshot captured and saved to: {file_path.relative_to(cwd)}",
        ]

        if evidence_path:
            new_text_parts.append(f"Evidence copy saved to: {evidence_path.relative_to(cwd)}")

        if description:
            new_text_parts.append(f"Description: {description}")

        new_text_parts.append("(Base64 image data hidden from context to save space)")

        new_text = "\n".join(new_text_parts)

        # Replace the image block with text block
        # We need to construct a new list because content might be immutable tuple
        new_content = list(content)
        # TextBlock only takes text - the type is implicit in the class
        new_content[image_block_index] = TextBlock(text=new_text)

        # Update tool_response content
        # Note: Depending on SDK implementation, we might need to set attribute
        if isinstance(tool_response, dict):
            tool_response["content"] = new_content
        elif hasattr(tool_response, "content"):
            tool_response.content = new_content

        return {}

    except Exception as e:
        print_error(f"Failed to save screenshot in hook: {e}")
        # Clear context even on failure
        clear_screenshot_context()
        return {}


# =============================================================================
# Utility Functions
# =============================================================================

def get_latest_screenshot(project_dir: Path, pattern: str = "*.png") -> Optional[Path]:
    """
    Get the path to the most recent screenshot.

    Args:
        project_dir: Project directory
        pattern: Glob pattern for screenshots

    Returns:
        Path to latest screenshot, or None if none found
    """
    screenshots_dir = project_dir / "screenshots"
    if not screenshots_dir.exists():
        return None

    screenshots = list(screenshots_dir.glob(pattern))
    if not screenshots:
        return None

    return max(screenshots, key=lambda p: p.stat().st_mtime)


def save_as_evidence(
    project_dir: Path,
    feature_id: int,
    source_screenshot: Path = None
) -> Optional[Path]:
    """
    Save a screenshot as evidence for a feature.

    Args:
        project_dir: Project directory
        feature_id: Feature ID for naming
        source_screenshot: Source screenshot path (uses latest if None)

    Returns:
        Path to evidence file, or None on failure
    """
    try:
        if source_screenshot is None:
            source_screenshot = get_latest_screenshot(project_dir)

        if source_screenshot is None:
            return None

        verification_dir = project_dir / "verification"
        verification_dir.mkdir(parents=True, exist_ok=True)

        evidence_path = verification_dir / f"feature_{feature_id}_evidence.png"
        shutil.copy2(source_screenshot, evidence_path)

        return evidence_path

    except Exception:
        return None
