"""
Enhanced Error Messages with Context and Suggestions
=====================================================

Provides helpful suggestions when common errors occur, guiding the agent
toward the correct tools and approaches.

This module intercepts error messages and enriches them with:
- Alternative commands/tools to use
- Links to relevant documentation
- Common fixes for platform-specific issues
"""

from typing import Dict, List, Optional, Tuple
import re


# =============================================================================
# Error Suggestion Database
# =============================================================================

ERROR_SUGGESTIONS: Dict[str, Dict[str, str]] = {
    # Unix commands that don't work on Windows
    "command not found": {
        "copy": "Use `file_copy` tool instead of the `copy` shell command",
        "cp": "Use `file_copy` tool for cross-platform file copying",
        "mv": "Use `file_move` tool for cross-platform file moving",
        "rm": "Use `file_delete` tool for cross-platform file deletion",
        "mkdir": "Use `file_ensure_dir` tool for cross-platform directory creation",
        "xargs": "Use Python list comprehension or the `file_glob` tool",
        "tee": "Use the `Write` tool to save output to a file",
        "test": "Use the `file_exists` tool to check if paths exist",
        "ls": "Use the `file_list` tool for cross-platform directory listing",
        "cat": "Use the `Read` tool to read file contents",
        "head": "Use the `Read` tool with limit parameter",
        "tail": "Use the `Read` tool with offset and limit parameters",
        "find": "Use the `file_glob` tool with recursive patterns like '**/*.py'",
        "grep": "Use the `Grep` tool for searching file contents",
        "awk": "Use Python string operations or the `Read` tool",
        "sed": "Use the `Edit` tool for find-and-replace operations",
        "touch": "Use the `Write` tool with empty content to create files",
        "which": "Use `capability_check` to verify tool availability",
    },

    # Windows-specific command issues
    "'copy' is not recognized": {
        "": "Use `file_copy` tool instead of Windows copy command",
    },
    "is not recognized as an internal or external command": {
        "copy": "Use `file_copy` tool for cross-platform file operations",
        "xcopy": "Use `file_copy` tool for cross-platform file operations",
        "del": "Use `file_delete` tool for cross-platform file deletion",
        "rd": "Use `file_delete` tool with recursive=True",
        "rmdir": "Use `file_delete` tool with recursive=True",
        "move": "Use `file_move` tool for cross-platform file moving",
        "type": "Use the `Read` tool to read file contents",
        "dir": "Use `file_list` tool for cross-platform directory listing",
    },

    # Puppeteer selector issues
    "not a valid selector": {
        ":has-text": "Use `browser_click_text` helper - :has-text() is not supported in Puppeteer",
        ":contains": "Use `browser_find_elements` with text_filter parameter",
        ":has(": "Use JavaScript via `puppeteer_evaluate` - :has() has limited support",
        ":nth-match": "Use JavaScript via `puppeteer_evaluate` for complex selectors",
    },
    "failed to find element": {
        ":has-text": "The :has-text() selector is not supported. Use `browser_click_text` instead",
        "": "Element not found. Try using `browser_find_elements` to see available elements",
    },
    "waiting for selector": {
        "": "Selector timeout. Use `browser_wait_and_click` for dynamic elements",
    },

    # Process management issues
    "taskkill": {
        "by pid": "Use `process_stop` tool with the process name instead of PID",
        "access is denied": "Try `process_stop` tool or run with elevated permissions",
    },
    "cannot kill process": {
        "": "Use `process_stop` tool with force=True, or use `server_stop` for managed servers",
    },

    # Docker issues
    "docker": {
        "daemon is not running": "Docker Desktop is not running. Mark Docker features as blocked with `feature_mark_blocked`",
        "error during connect": "Docker is not available. Use `feature_mark_blocked` for Docker-dependent features",
        "cannot connect to": "Docker daemon not responding. Check Docker Desktop status",
    },

    # Git issues
    "git": {
        "not a git repository": "Run `git init` first or check if you're in the correct directory",
        "nothing to commit": "No changes to commit. This is not an error.",
        "permission denied": "Check file permissions or close any editors locking files",
    },

    # npm/node issues
    "npm": {
        "command not found": "Node.js is not installed or not in PATH. Check `capability_list`",
        "eacces": "Permission error. Try running without sudo or fix npm permissions",
        "eresolve": "Dependency conflict. Try `npm install --legacy-peer-deps`",
    },

    # Python issues
    "python": {
        "no module named": "Module not installed. Use `pip install <module>` first",
        "syntaxerror": "Python syntax error. Check for missing colons, parentheses, or indentation",
    },

    # Port/network issues
    "address already in use": {
        "": "Port is busy. Use `server_list` to see running servers, then `server_stop` to free the port",
    },
    "eaddrinuse": {
        "": "Port is in use. Stop the conflicting service with `server_stop` or use a different port",
    },
}


# Pattern-based suggestions for more complex matching
PATTERN_SUGGESTIONS: List[Tuple[str, str, str]] = [
    # (regex_pattern, suggestion, category)
    (r"button:has-text\(['\"](.+?)['\"]\)",
     "Use `browser_click_text` with text='\\1' instead of :has-text() selector",
     "puppeteer"),
    (r"selector.*:has-text",
     "The :has-text() pseudo-selector is not supported by Puppeteer. Use `browser_click_text` helper",
     "puppeteer"),
    (r"copy\s+['\"]?[\w/\\]+['\"]?\s+['\"]?[\w/\\]+['\"]?",
     "Use `file_copy` tool instead of shell copy command for cross-platform compatibility",
     "file_ops"),
    (r"(rm|del)\s+-?r?f?\s+",
     "Use `file_delete` tool with recursive=True for safe, cross-platform deletion",
     "file_ops"),
    (r"mkdir\s+-p\s+",
     "Use `file_ensure_dir` tool for cross-platform directory creation",
     "file_ops"),
    (r"ls\s+-[lat]+\s+.*\|\s*head",
     "Use `file_latest` tool to get the most recent file",
     "file_ops"),
]


# =============================================================================
# Error Enhancement Functions
# =============================================================================

def enhance_error_message(error: str, context: dict = None) -> str:
    """
    Add helpful suggestions to error messages.

    Args:
        error: The original error message
        context: Optional context dict (command, tool, etc.)

    Returns:
        Enhanced error message with suggestions
    """
    if not error:
        return error

    error_lower = error.lower()
    suggestions = []

    # Check pattern-based suggestions first (more specific)
    for pattern, suggestion, category in PATTERN_SUGGESTIONS:
        match = re.search(pattern, error, re.IGNORECASE)
        if match:
            # Replace backreferences in suggestion
            resolved_suggestion = suggestion
            for i, group in enumerate(match.groups(), 1):
                if group:
                    resolved_suggestion = resolved_suggestion.replace(f"\\{i}", group)
            suggestions.append(resolved_suggestion)
            break  # Use first matching pattern

    # Check keyword-based suggestions
    for error_type, error_suggestions in ERROR_SUGGESTIONS.items():
        if error_type in error_lower:
            for trigger, suggestion in error_suggestions.items():
                if trigger == "" or trigger in error_lower:
                    if suggestion not in suggestions:
                        suggestions.append(suggestion)
                    break

    # Add context-specific suggestions
    if context:
        command = context.get("command", "")
        if command:
            extra = _get_command_specific_suggestion(command, error_lower)
            if extra and extra not in suggestions:
                suggestions.append(extra)

    # Build enhanced message
    if suggestions:
        enhanced = error
        for i, suggestion in enumerate(suggestions[:3], 1):  # Max 3 suggestions
            enhanced += f"\n\n💡 Suggestion {i}: {suggestion}"
        return enhanced

    return error


def _get_command_specific_suggestion(command: str, error: str) -> Optional[str]:
    """Get suggestion based on the specific command that failed."""
    command_lower = command.lower().strip()

    # Screenshot-related commands
    if "screenshot" in command_lower or "capture" in command_lower:
        return "For screenshots, use `puppeteer_screenshot` tool directly"

    # File copy patterns
    if command_lower.startswith("cp ") or command_lower.startswith("copy "):
        return "Use `file_copy` tool: file_copy with src='source', dest='destination'"

    # ls piped to head for latest file
    if "ls " in command_lower and "head" in command_lower:
        return "Use `file_latest` tool: file_latest with directory='path', pattern='*.png'"

    # mkdir -p
    if "mkdir" in command_lower and "-p" in command_lower:
        return "Use `file_ensure_dir` tool for recursive directory creation"

    return None


def get_tool_suggestion(failed_command: str) -> Optional[str]:
    """
    Get a suggested tool to use instead of a failed shell command.

    Args:
        failed_command: The command that failed

    Returns:
        Suggested tool name and usage, or None
    """
    command_lower = failed_command.lower().strip()
    first_word = command_lower.split()[0] if command_lower else ""

    tool_suggestions = {
        "cp": ("file_copy", "file_copy with src='source_path', dest='dest_path'"),
        "copy": ("file_copy", "file_copy with src='source_path', dest='dest_path'"),
        "mv": ("file_move", "file_move with src='source_path', dest='dest_path'"),
        "move": ("file_move", "file_move with src='source_path', dest='dest_path'"),
        "rm": ("file_delete", "file_delete with path='path', recursive=True"),
        "del": ("file_delete", "file_delete with path='path', recursive=True"),
        "mkdir": ("file_ensure_dir", "file_ensure_dir with path='directory_path'"),
        "ls": ("file_list", "file_list with path='directory_path', pattern='*'"),
        "dir": ("file_list", "file_list with path='directory_path', pattern='*'"),
        "cat": ("Read", "Read with file_path='path_to_file'"),
        "type": ("Read", "Read with file_path='path_to_file'"),
        "find": ("file_glob", "file_glob with pattern='**/*.ext', root='.'"),
        "grep": ("Grep", "Grep with pattern='search_term', path='.'"),
    }

    if first_word in tool_suggestions:
        tool_name, usage = tool_suggestions[first_word]
        return f"Use `{tool_name}` instead: {usage}"

    return None


def format_error_with_context(
    error: str,
    tool_name: str = None,
    tool_input: dict = None,
    session_id: int = None,
) -> str:
    """
    Format an error with full context for debugging.

    Args:
        error: The error message
        tool_name: Name of the tool that caused the error
        tool_input: Input that was passed to the tool
        session_id: Current session ID

    Returns:
        Formatted error with context
    """
    lines = ["=" * 60, "ERROR DETAILS", "=" * 60]

    if tool_name:
        lines.append(f"Tool: {tool_name}")

    if tool_input:
        # Truncate large inputs
        input_str = str(tool_input)
        if len(input_str) > 500:
            input_str = input_str[:500] + "..."
        lines.append(f"Input: {input_str}")

    if session_id:
        lines.append(f"Session: {session_id}")

    lines.append("")
    lines.append("Error:")
    lines.append(error)

    # Add enhanced suggestions
    context = {"command": tool_input.get("command", "")} if tool_input else {}
    enhanced = enhance_error_message(error, context)

    if enhanced != error:
        lines.append("")
        lines.append("-" * 40)
        # Extract just the suggestions part
        if "💡" in enhanced:
            suggestions_part = enhanced[enhanced.index("💡"):]
            lines.append(suggestions_part)

    lines.append("=" * 60)

    return "\n".join(lines)
