"""
File Operations MCP Server
==========================

MCP server providing platform-agnostic file operations for the coding agent.
These tools work identically on Windows, macOS, and Linux.
"""

from pathlib import Path
from mcp.server.fastmcp import FastMCP

from .file_ops import FileOps


# Create the MCP server
mcp = FastMCP("file-operations")


# Tool name constants for registration
FILE_TOOLS = [
    "mcp__file-operations__file_copy",
    "mcp__file-operations__file_move",
    "mcp__file-operations__file_delete",
    "mcp__file-operations__file_list",
    "mcp__file-operations__file_latest",
    "mcp__file-operations__file_ensure_dir",
    "mcp__file-operations__file_exists",
    "mcp__file-operations__file_glob",
]


@mcp.tool()
def file_copy(src: str, dest: str) -> dict:
    """
    Copy a file or directory from src to dest (cross-platform).

    Use this instead of shell commands like 'cp' or 'copy'.

    Args:
        src: Source path (file or directory)
        dest: Destination path

    Returns:
        Dict with success status and message
    """
    return FileOps.copy(src, dest)


@mcp.tool()
def file_move(src: str, dest: str) -> dict:
    """
    Move a file or directory from src to dest (cross-platform).

    Use this instead of shell commands like 'mv' or 'move'.

    Args:
        src: Source path
        dest: Destination path

    Returns:
        Dict with success status and message
    """
    return FileOps.move(src, dest)


@mcp.tool()
def file_delete(path: str, recursive: bool = False) -> dict:
    """
    Delete a file or directory (cross-platform).

    Use this instead of shell commands like 'rm' or 'del'.

    Args:
        path: Path to delete
        recursive: Set to True to delete non-empty directories

    Returns:
        Dict with success status and message
    """
    return FileOps.delete(path, recursive)


@mcp.tool()
def file_list(path: str, pattern: str = "*") -> dict:
    """
    List directory contents with optional glob pattern (cross-platform).

    Use this instead of shell commands like 'ls' or 'dir'.

    Args:
        path: Directory to list
        pattern: Glob pattern to filter (default: "*")

    Returns:
        Dict with items list and count
    """
    return FileOps.list_dir(path, pattern)


@mcp.tool()
def file_latest(directory: str, pattern: str = "*.png") -> dict:
    """
    Get the most recently modified file matching pattern.

    Use this instead of 'ls -t | head -1' which doesn't work on Windows.

    Args:
        directory: Directory to search
        pattern: Glob pattern (default: "*.png" for screenshots)

    Returns:
        Dict with path to latest file
    """
    return FileOps.latest_file(directory, pattern)


@mcp.tool()
def file_ensure_dir(path: str) -> dict:
    """
    Ensure a directory exists, creating it if needed (cross-platform).

    Use this instead of 'mkdir -p' which doesn't work on Windows.

    Args:
        path: Directory path to ensure exists

    Returns:
        Dict with success status
    """
    return FileOps.ensure_dir(path)


@mcp.tool()
def file_exists(path: str) -> dict:
    """
    Check if a path exists and get its type (cross-platform).

    Use this instead of 'test -e' which doesn't work on Windows.

    Args:
        path: Path to check

    Returns:
        Dict with exists status and type (file/directory)
    """
    return FileOps.exists(path)


@mcp.tool()
def file_glob(pattern: str, root: str = ".") -> dict:
    """
    Find files matching a glob pattern (cross-platform).

    Use this instead of 'find' with pattern matching.

    Args:
        pattern: Glob pattern (e.g., "**/*.py" for all Python files)
        root: Root directory to search from (default: current dir)

    Returns:
        Dict with list of matching files
    """
    return FileOps.glob_files(pattern, root)


def create_file_tools_server(project_dir: Path) -> dict:
    """
    Create the file tools MCP server configuration.

    Args:
        project_dir: Project directory path

    Returns:
        Server configuration dict for claude-code-sdk
    """
    return {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "arcadiaforge.file_tools"],
        "cwd": str(project_dir),
    }


if __name__ == "__main__":
    mcp.run()
