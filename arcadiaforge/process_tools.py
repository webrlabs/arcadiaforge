"""
Process Management MCP Tools
=============================

These tools allow the agent to manage spawned processes - list running processes,
stop specific processes, and clean up all tracked processes.

Usage:
    from arcadiaforge.process_tools import create_process_tools_server, PROCESS_TOOLS

    server = create_process_tools_server(project_dir)

    options = ClaudeCodeOptions(
        mcp_servers={"processes": server},
        allowed_tools=[...PROCESS_TOOLS]
    )
"""

import os
import platform
import re
import signal
import subprocess
from pathlib import Path
from typing import Any, Optional

from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig


# Global project directory and session ID
_project_dir: Path | None = None
_current_session_id: int = 0

# Lazy import to avoid circular dependencies
_process_tracker: Optional[Any] = None


def _get_tracker():
    """Get or create the process tracker."""
    global _process_tracker
    if _process_tracker is None:
        if _project_dir is None:
            raise RuntimeError("Project directory not set")
        from arcadiaforge.process_tracker import ProcessTracker
        _process_tracker = ProcessTracker(_project_dir)
    return _process_tracker


def set_project_dir(project_dir: Path) -> None:
    """Set the project directory for the process tracker."""
    global _project_dir, _process_tracker
    _project_dir = project_dir
    _process_tracker = None  # Reset to force reload


def set_session_id(session_id: int) -> None:
    """Set the current session ID for tracking."""
    global _current_session_id
    _current_session_id = session_id


def cleanup_previous_processes(project_dir: Path, new_session_id: int) -> tuple[int, int]:
    """
    Clean up all tracked processes from previous sessions.

    Called at the start of each coding session to ensure processes
    from previous sessions don't linger and cause port conflicts.

    Args:
        project_dir: The project directory for process tracking
        new_session_id: The new session about to start

    Returns:
        (killed_count, failed_count)
    """
    from arcadiaforge.process_tracker import ProcessTracker
    from arcadiaforge.output import print_info, print_success, print_warning

    tracker = ProcessTracker(project_dir)
    running = tracker.get_running()

    if not running:
        return (0, 0)

    # Only cleanup processes from previous sessions (not current)
    # This allows manual process tracking during the same session
    previous_session_procs = [p for p in running if p.session_id < new_session_id]

    if not previous_session_procs:
        return (0, 0)

    print_info(f"Cleaning up {len(previous_session_procs)} process(es) from previous sessions...")

    killed = 0
    failed = 0

    for proc in previous_session_procs:
        if tracker.kill_process(proc.pid, force=False):
            killed += 1
        else:
            # Try force kill
            if tracker.kill_process(proc.pid, force=True):
                killed += 1
            else:
                failed += 1

    if killed > 0:
        print_success(f"Stopped {killed} lingering process(es)")
    if failed > 0:
        print_warning(f"Failed to stop {failed} process(es)")

    return (killed, failed)


def _extract_port_from_command(command: str) -> Optional[int]:
    """Try to extract a port number from a command string."""
    # Common patterns: --port 3000, -p 8000, :3000, PORT=3000
    patterns = [
        r'--port[=\s]+(\d+)',
        r'-p[=\s]+(\d+)',
        r':(\d{4,5})\b',
        r'PORT[=\s]+(\d+)',
        r'port[=\s]+(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, command, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
    return None


def _is_server_command(command: str) -> bool:
    """Check if a command is likely starting a server/daemon process."""
    server_indicators = [
        'npm run dev', 'npm start', 'npm run start',
        'npx vite', 'npx next', 'npx serve',
        'python -m http.server', 'python -m uvicorn', 'python -m flask',
        'uvicorn', 'gunicorn', 'flask run', 'django', 'manage.py runserver',
        'node server', 'node app', 'node index',
        'streamlit run', 'gradio',
        '--watch', '--serve', '--dev',
    ]
    command_lower = command.lower()
    return any(indicator in command_lower for indicator in server_indicators)


@tool(
    "process_list",
    "List all tracked background processes. Shows PID, name, port, session, and start time.",
    {}
)
async def process_list(args: dict[str, Any]) -> dict[str, Any]:
    """List all tracked background processes."""
    tracker = _get_tracker()
    running = tracker.get_running()

    if not running:
        return {
            "content": [{
                "type": "text",
                "text": "No tracked processes running."
            }]
        }

    lines = [
        "=" * 70,
        f"TRACKED PROCESSES ({len(running)} running)",
        "=" * 70,
        f"{'PID':<8} {'Name':<25} {'Port':<8} {'Session':<10}",
        "-" * 70,
    ]

    for proc in sorted(running, key=lambda p: p.pid):
        port_str = str(proc.port) if proc.port else "-"
        session_str = f"#{proc.session_id}"
        lines.append(f"{proc.pid:<8} {proc.name[:25]:<25} {port_str:<8} {session_str:<10}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "process_stop",
    "Stop a specific tracked process by PID. Use force=true for stubborn processes.",
    {"pid": int, "force": bool}
)
async def process_stop(args: dict[str, Any]) -> dict[str, Any]:
    """Stop a specific tracked process."""
    pid = args["pid"]
    force = args.get("force", False)

    tracker = _get_tracker()

    if pid not in tracker.processes:
        return {
            "content": [{
                "type": "text",
                "text": f"Process {pid} is not tracked. Use process_list to see tracked processes."
            }],
            "is_error": True
        }

    proc = tracker.processes[pid]
    if tracker.kill_process(pid, force=force):
        return {
            "content": [{
                "type": "text",
                "text": f"Stopped process {pid} ({proc.name})"
            }]
        }
    else:
        return {
            "content": [{
                "type": "text",
                "text": f"Failed to stop process {pid}. Try with force=true."
            }],
            "is_error": True
        }


@tool(
    "process_stop_all",
    "Stop all tracked background processes. Use this before running new servers to free ports.",
    {"force": bool}
)
async def process_stop_all(args: dict[str, Any]) -> dict[str, Any]:
    """Stop all tracked background processes."""
    force = args.get("force", False)

    tracker = _get_tracker()
    running = tracker.get_running()

    if not running:
        return {
            "content": [{
                "type": "text",
                "text": "No tracked processes to stop."
            }]
        }

    killed, failed = tracker.kill_all(force=force)

    if failed == 0:
        return {
            "content": [{
                "type": "text",
                "text": f"Stopped {killed} process(es)."
            }]
        }
    else:
        return {
            "content": [{
                "type": "text",
                "text": f"Stopped {killed} process(es), failed to stop {failed}. Try with force=true."
            }],
            "is_error": failed > 0 and killed == 0
        }


@tool(
    "process_stop_session",
    "Stop all processes from a specific session. Useful for cleaning up after failed sessions.",
    {"session_id": int, "force": bool}
)
async def process_stop_session(args: dict[str, Any]) -> dict[str, Any]:
    """Stop all processes from a specific session."""
    session_id = args["session_id"]
    force = args.get("force", False)

    tracker = _get_tracker()
    killed, failed = tracker.kill_session(session_id, force=force)

    if killed == 0 and failed == 0:
        return {
            "content": [{
                "type": "text",
                "text": f"No processes found from session #{session_id}."
            }]
        }

    if failed == 0:
        return {
            "content": [{
                "type": "text",
                "text": f"Stopped {killed} process(es) from session #{session_id}."
            }]
        }
    else:
        return {
            "content": [{
                "type": "text",
                "text": f"Stopped {killed}, failed {failed} from session #{session_id}."
            }],
            "is_error": failed > 0 and killed == 0
        }


@tool(
    "process_track",
    "Manually track a process by PID. Use when you started a background process and want to track it.",
    {"pid": int, "name": str, "port": int}
)
async def process_track(args: dict[str, Any]) -> dict[str, Any]:
    """Manually track a process by PID."""
    pid = args["pid"]
    name = args.get("name", f"process-{pid}")
    port = args.get("port")

    tracker = _get_tracker()

    # Check if process exists
    if not tracker.is_running(pid):
        return {
            "content": [{
                "type": "text",
                "text": f"Process {pid} is not running."
            }],
            "is_error": True
        }

    tracker.track(
        pid=pid,
        command=name,
        session_id=_current_session_id,
        name=name,
        port=port,
    )

    return {
        "content": [{
            "type": "text",
            "text": f"Now tracking process {pid} ({name})"
        }]
    }


@tool(
    "process_find_port",
    "Find which process is using a specific port. Useful for debugging port conflicts.",
    {"port": int}
)
async def process_find_port(args: dict[str, Any]) -> dict[str, Any]:
    """Find which process is using a specific port."""
    port = args["port"]

    is_windows = platform.system().lower() == "windows"

    try:
        if is_windows:
            # Windows: use netstat
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                shell=True,
            )
            # Find lines with our port
            lines = []
            for line in result.stdout.split('\n'):
                if f":{port}" in line and ("LISTENING" in line or "ESTABLISHED" in line):
                    lines.append(line.strip())

            if not lines:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"No process found using port {port}."
                    }]
                }

            return {
                "content": [{
                    "type": "text",
                    "text": f"Port {port} usage:\n" + "\n".join(lines)
                }]
            }
        else:
            # Unix: use lsof
            result = subprocess.run(
                ["lsof", "-i", f":{port}"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return {
                    "content": [{
                        "type": "text",
                        "text": f"No process found using port {port}."
                    }]
                }

            return {
                "content": [{
                    "type": "text",
                    "text": f"Port {port} usage:\n{result.stdout}"
                }]
            }
    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"Error checking port {port}: {e}"
            }],
            "is_error": True
        }


# List of all process tool names (for allowed_tools)
PROCESS_TOOLS = [
    "mcp__processes__process_list",
    "mcp__processes__process_stop",
    "mcp__processes__process_stop_all",
    "mcp__processes__process_stop_session",
    "mcp__processes__process_track",
    "mcp__processes__process_find_port",
]


def create_process_tools_server(project_dir: Path) -> McpSdkServerConfig:
    """
    Create an MCP server with process management tools.

    Args:
        project_dir: The project directory for process tracking

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    set_project_dir(project_dir)

    return create_sdk_mcp_server(
        name="processes",
        version="1.0.0",
        tools=[
            process_list,
            process_stop,
            process_stop_all,
            process_stop_session,
            process_track,
            process_find_port,
        ]
    )


# Hook function to track processes from Bash commands
async def process_tracking_hook(result_data: dict, tool_use_id: str = None, context: dict = None) -> dict:
    """
    PostToolUse hook that tracks background processes spawned by Bash commands.

    This hook examines Bash command results to detect and track background processes.
    """
    if result_data.get("tool_name") != "Bash":
        return {}

    tool_input = result_data.get("tool_input", {})
    command = tool_input.get("command", "")
    run_in_background = tool_input.get("run_in_background", False)

    # Only track background commands or server-like commands
    if not run_in_background and not _is_server_command(command):
        return {}

    # Try to extract PID from the result
    tool_result = result_data.get("tool_result", {})
    result_content = ""
    if isinstance(tool_result, dict):
        content = tool_result.get("content", [])
        if content and isinstance(content[0], dict):
            result_content = content[0].get("text", "")
    elif isinstance(tool_result, str):
        result_content = tool_result

    # Look for PID in output (common patterns from shell backgrounding)
    pid_patterns = [
        r'\[(\d+)\]\s+(\d+)',  # [1] 12345
        r'PID[:\s]+(\d+)',      # PID: 12345
        r'pid[:\s]+(\d+)',      # pid: 12345
        r'Started.*?(\d{4,})',  # Started process 12345
    ]

    pid = None
    for pattern in pid_patterns:
        match = re.search(pattern, result_content)
        if match:
            pid = int(match.group(2) if len(match.groups()) > 1 else match.group(1))
            break

    if pid:
        tracker = _get_tracker()
        port = _extract_port_from_command(command)
        tracker.track(
            pid=pid,
            command=command,
            session_id=_current_session_id,
            port=port,
        )

    return {}
