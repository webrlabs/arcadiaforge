"""
Custom MCP Tools for Image Handling
===================================

These tools allow the agent to read image files (like screenshots)
back into their context as image blocks.
"""

import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict

from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig


# Global project directory
_project_dir: Path | None = None


@tool(
    "read_image",
    "Read an image file and return its content as an image block. Use this to view screenshots or other images in the project.",
    {"file_path": str}
)
async def read_image(args: dict[str, Any]) -> dict[str, Any]:
    """Read an image file and return it as an image content block."""
    file_path_str = args["file_path"]
    file_path = Path(file_path_str)
    
    # Resolve relative path
    if not file_path.is_absolute() and _project_dir:
        file_path = _project_dir / file_path
        
    if not file_path.exists():
        return {
            "content": [{
                "type": "text", 
                "text": f"Error: Image file not found: {file_path_str}"
            }],
            "is_error": True
        }
        
    try:
        # Detect mime type
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type or not mime_type.startswith("image/"):
            # Fallback to common types if extension is missing or weird
            if file_path.suffix.lower() in ('.png', '.png'):
                mime_type = "image/png"
            elif file_path.suffix.lower() in ('.jpg', '.jpeg'):
                mime_type = "image/jpeg"
            elif file_path.suffix.lower() == '.webp':
                mime_type = "image/webp"
            else:
                mime_type = "image/png"  # Last resort default
            
        with open(file_path, "rb") as f:
            image_bytes = f.read()
            
        base64_data = base64.b64encode(image_bytes).decode("utf-8")
        
        # The Claude Agent SDK expects this format for image results
        return {
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime_type,
                        "data": base64_data
                    }
                },
                {
                    "type": "text",
                    "text": f"Successfully read image: {file_path_str}"
                }
            ]
        }
    except Exception as e:
        return {
            "content": [{
                "type": "text", 
                "text": f"Error reading image {file_path_str}: {str(e)}"
            }],
            "is_error": True
        }


def create_image_tools_server(project_dir: Path) -> McpSdkServerConfig:
    """
    Create an MCP server with image handling tools.

    Args:
        project_dir: The project directory

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    global _project_dir
    _project_dir = project_dir

    return create_sdk_mcp_server(
        name="images",
        version="1.0.0",
        tools=[
            read_image,
        ]
    )


# List of all image tool names (for allowed_tools)
IMAGE_TOOLS = [
    "mcp__images__read_image",
]
