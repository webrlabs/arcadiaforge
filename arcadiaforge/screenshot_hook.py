"""
Puppeteer Screenshot Handler
============================

Hook to intercept puppeteer_screenshot results, save them to disk,
and return the file path to the agent.
"""

import base64
import time
from pathlib import Path
from typing import Any, Dict

from arcadiaforge.output import print_info, print_success, print_error

# Global counter for screenshots
_screenshot_seq = 0

def get_next_screenshot_seq() -> int:
    """Get next screenshot sequence number."""
    global _screenshot_seq
    _screenshot_seq += 1
    return _screenshot_seq

async def screenshot_saver_hook(context, tool_use, tool_result):
    """
    Post-tool-use hook to save Puppeteer screenshots to disk.

    Intercepts the base64 output from mcp__puppeteer__puppeteer_screenshot,
    saves it to the project's screenshots/ directory, and updates
    the tool result to point to the file path.

    Returns an empty dict when no action is needed (SDK requires object, not None).
    """
    tool_name = getattr(tool_use, "name", "")

    # Only handle the screenshot tool
    if tool_name != "mcp__puppeteer__puppeteer_screenshot":
        return {}

    # Check if tool execution was successful
    if getattr(tool_result, "is_error", False):
        return {}

    # Extract content
    content = getattr(tool_result, "content", [])
    if not content:
        return {}

    # Look for image content block
    image_data = None
    image_block_index = -1
    
    # Iterate through blocks to find image data (base64)
    # The MCP tool usually returns an ImageContent or TextContent with base64
    for i, block in enumerate(content):
        # Handle ImageContent object (SDK typed)
        if hasattr(block, "type") and block.type == "image":
            image_data = getattr(block, "data", None)
            image_block_index = i
            break
        # Handle dict representation (if SDK returns dicts)
        elif isinstance(block, dict) and block.get("type") == "image":
            image_data = block.get("data")
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
        # Some versions might return base64 string directly in text?
        # Let's assume standard MCP ImageContent behavior first.
        return {}

    try:
        # Determine project root (CWD is set in client options)
        # We can try to get it from context if available, or assume CWD
        cwd = Path.cwd()
        
        # Ensure screenshots directory exists
        screenshots_dir = cwd / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate filename
        seq = get_next_screenshot_seq()
        timestamp = int(time.time())
        filename = f"screenshot_{timestamp}_{seq:03d}.png"
        file_path = screenshots_dir / filename
        
        # Save file
        image_bytes = base64.b64decode(image_data)
        with open(file_path, "wb") as f:
            f.write(image_bytes)
            
        print_success(f"Screenshot saved: {file_path.relative_to(cwd)}")
        
        # Modify the tool result to show the path instead of the image data
        # This saves context tokens and gives the agent the path it needs
        
        # Create a new text block with the path info
        from claude_code_sdk.types import TextBlock
        
        new_text = (
            f"Screenshot captured and saved to: {file_path.relative_to(cwd)}\n"
            f"(Base64 image data hidden from context to save space)"
        )
        
        # Replace the image block with text block
        # We need to construct a new list because content might be immutable tuple
        new_content = list(content)
        new_content[image_block_index] = TextBlock(type="text", text=new_text)
        
        # Update tool_result content
        # Note: Depending on SDK implementation, we might need to set attribute
        if hasattr(tool_result, "content"):
            tool_result.content = new_content

        return {}

    except Exception as e:
        print_error(f"Failed to save screenshot in hook: {e}")
        return {}
