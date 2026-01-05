"""
Server Management MCP Tools
============================

High-level tools for managing development servers. These tools handle:
- Starting servers and tracking their PIDs
- Finding and stopping processes by port
- Waiting for servers to become available
- Server health checks

These are higher-level than process_tools.py - they understand common
server patterns and can automatically detect ports, wait for startup, etc.

Usage:
    from arcadiaforge.server_tools import create_server_tools_server, SERVER_TOOLS

    server = create_server_tools_server(project_dir)

    options = ClaudeCodeOptions(
        mcp_servers={"servers": server},
        allowed_tools=[...SERVER_TOOLS]
    )
"""

import os
import platform
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig


# Global state
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
    """Set the project directory."""
    global _project_dir, _process_tracker
    _project_dir = project_dir
    _process_tracker = None


def set_session_id(session_id: int) -> None:
    """Set the current session ID."""
    global _current_session_id
    _current_session_id = session_id


def _is_windows() -> bool:
    """Check if running on Windows."""
    return platform.system().lower() == "windows"


def _is_port_in_use(port: int) -> bool:
    """Check if a port is currently in use."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('127.0.0.1', port))
            return result == 0
    except Exception:
        return False


def _find_process_on_port(port: int) -> Optional[dict]:
    """
    Find which process is using a specific port.

    Returns dict with 'pid', 'process_name', and 'details' if found.
    """
    try:
        if _is_windows():
            # Windows: use netstat -ano
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                shell=True,
                timeout=10
            )

            for line in result.stdout.split('\n'):
                # Match lines like: TCP    0.0.0.0:8678    0.0.0.0:0    LISTENING    12345
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = int(parts[-1])

                        # Get process name from PID
                        name_result = subprocess.run(
                            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                            capture_output=True,
                            text=True,
                            shell=True,
                            timeout=5
                        )

                        process_name = "unknown"
                        if name_result.stdout.strip():
                            # Parse CSV: "process.exe","12345","..."
                            match = re.match(r'"([^"]+)"', name_result.stdout.strip())
                            if match:
                                process_name = match.group(1)

                        return {
                            "pid": pid,
                            "process_name": process_name,
                            "details": line.strip()
                        }
        else:
            # Unix: use lsof
            result = subprocess.run(
                ["lsof", "-i", f":{port}", "-P", "-n"],
                capture_output=True,
                text=True,
                timeout=10
            )

            for line in result.stdout.split('\n')[1:]:  # Skip header
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        return {
                            "pid": int(parts[1]),
                            "process_name": parts[0],
                            "details": line.strip()
                        }
    except Exception as e:
        return None

    return None


def _kill_pid(pid: int, force: bool = False) -> bool:
    """Kill a process by PID."""
    try:
        if _is_windows():
            cmd = ["taskkill", "/PID", str(pid)]
            if force:
                cmd.append("/F")
            subprocess.run(cmd, capture_output=True, shell=True, timeout=10)
        else:
            import signal
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)

        # Wait and verify
        time.sleep(0.5)

        # Check if still running
        if _is_windows():
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                shell=True,
                timeout=5
            )
            return str(pid) not in result.stdout
        else:
            try:
                os.kill(pid, 0)
                return False  # Still running
            except OSError:
                return True  # Dead

    except Exception:
        return False


def _extract_port_from_command(command: str) -> Optional[int]:
    """Try to extract a port number from a command string."""
    patterns = [
        r'--port[=\s]+(\d+)',
        r'-p[=\s]+(\d+)',
        r':(\d{4,5})\b',
        r'PORT[=\s]+(\d+)',
        r'localhost:(\d+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, command, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
    return None


def _wait_for_port(port: int, timeout_seconds: float = 30) -> bool:
    """Wait for a port to become available."""
    start = time.time()
    while time.time() - start < timeout_seconds:
        if _is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False


def _wait_for_url(url: str, timeout_seconds: float = 30) -> tuple[bool, str]:
    """
    Wait for a URL to return a successful response.

    Returns (success, message).
    """
    import urllib.request
    import urllib.error

    start = time.time()
    last_error = ""

    while time.time() - start < timeout_seconds:
        try:
            req = urllib.request.Request(url, method='GET')
            req.add_header('User-Agent', 'ArcadiaForge-HealthCheck/1.0')

            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status < 500:
                    return True, f"Server responded with status {response.status}"
        except urllib.error.HTTPError as e:
            # Even 4xx means server is up
            if e.code < 500:
                return True, f"Server responded with status {e.code}"
            last_error = f"HTTP {e.code}"
        except urllib.error.URLError as e:
            last_error = str(e.reason)
        except Exception as e:
            last_error = str(e)

        time.sleep(0.5)

    return False, f"Timeout after {timeout_seconds}s. Last error: {last_error}"


@tool(
    "server_start",
    "Start a server command in the background and track its PID. Returns immediately with PID info. Use server_wait to wait for it to be ready.",
    {
        "command": str,  # Command to run (e.g., "npm run dev --prefix frontend")
        "name": str,     # Short name for the server (e.g., "frontend", "backend")
        "port": int,     # Expected port (optional, for tracking)
        "cwd": str,      # Working directory (optional)
    }
)
async def server_start(args: dict[str, Any]) -> dict[str, Any]:
    """Start a server in the background and track its PID."""
    command = args["command"]
    name = args.get("name", "server")
    port = args.get("port")
    cwd = args.get("cwd", str(_project_dir) if _project_dir else None)

    # Check if port is already in use
    if port and _is_port_in_use(port):
        existing = _find_process_on_port(port)
        if existing:
            return {
                "content": [{
                    "type": "text",
                    "text": (
                        f"Port {port} is already in use by {existing['process_name']} "
                        f"(PID {existing['pid']}). Use server_stop_port to stop it first."
                    )
                }],
                "is_error": True
            }
        return {
            "content": [{
                "type": "text",
                "text": f"Port {port} is already in use. Use server_stop_port to free it."
            }],
            "is_error": True
        }

    # Auto-detect port from command if not specified
    if not port:
        port = _extract_port_from_command(command)

    try:
        if _is_windows():
            # Windows: Use START /B for background process
            # We wrap in cmd to get the PID
            full_command = f'start /B {command}'

            # Alternative: use subprocess with CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
            pid = process.pid
        else:
            # Unix: Standard backgrounding
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )
            pid = process.pid

        # Track the process
        tracker = _get_tracker()
        tracker.track(
            pid=pid,
            command=command,
            session_id=_current_session_id,
            name=name,
            port=port
        )

        # Brief wait to check if it crashed immediately
        time.sleep(1)

        if not tracker.is_running(pid):
            # Process died immediately - get error output
            stdout, stderr = process.communicate(timeout=1)
            error_msg = stderr.decode() if stderr else stdout.decode() if stdout else "Process exited immediately"
            tracker.untrack(pid)
            return {
                "content": [{
                    "type": "text",
                    "text": f"Server '{name}' failed to start:\n{error_msg[:500]}"
                }],
                "is_error": True
            }

        result_text = f"Started server '{name}' (PID {pid})"
        if port:
            result_text += f" on port {port}"
        result_text += f"\nCommand: {command[:100]}"
        result_text += "\n\nUse server_wait to wait for it to be ready."

        return {"content": [{"type": "text", "text": result_text}]}

    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Failed to start server: {e}"}],
            "is_error": True
        }


@tool(
    "server_stop_port",
    "Stop whatever process is using a specific port. Useful for freeing ports before starting servers.",
    {"port": int, "force": bool}
)
async def server_stop_port(args: dict[str, Any]) -> dict[str, Any]:
    """Stop the process using a specific port."""
    port = args["port"]
    force = args.get("force", False)

    if not _is_port_in_use(port):
        return {
            "content": [{"type": "text", "text": f"Port {port} is not in use."}]
        }

    proc_info = _find_process_on_port(port)
    if not proc_info:
        return {
            "content": [{
                "type": "text",
                "text": f"Port {port} is in use but could not identify the process."
            }],
            "is_error": True
        }

    pid = proc_info["pid"]
    name = proc_info["process_name"]

    # Try to kill
    if _kill_pid(pid, force=force):
        # Also untrack if we were tracking it
        tracker = _get_tracker()
        if pid in tracker.processes:
            tracker.untrack(pid)

        return {
            "content": [{
                "type": "text",
                "text": f"Stopped {name} (PID {pid}) on port {port}."
            }]
        }
    elif not force:
        # Try force kill
        if _kill_pid(pid, force=True):
            tracker = _get_tracker()
            if pid in tracker.processes:
                tracker.untrack(pid)
            return {
                "content": [{
                    "type": "text",
                    "text": f"Force-killed {name} (PID {pid}) on port {port}."
                }]
            }

    return {
        "content": [{
            "type": "text",
            "text": f"Failed to stop {name} (PID {pid}) on port {port}."
        }],
        "is_error": True
    }


@tool(
    "server_wait",
    "Wait for a server to become available. Checks either a port or a health URL.",
    {
        "port": int,          # Port to check (optional if url provided)
        "url": str,           # Health check URL (optional)
        "timeout": int,       # Timeout in seconds (default 30)
    }
)
async def server_wait(args: dict[str, Any]) -> dict[str, Any]:
    """Wait for a server to become available."""
    port = args.get("port")
    url = args.get("url")
    timeout = args.get("timeout", 30)

    if not port and not url:
        return {
            "content": [{"type": "text", "text": "Must specify either 'port' or 'url'"}],
            "is_error": True
        }

    # If URL provided, use that for health check
    if url:
        success, message = _wait_for_url(url, timeout)
        if success:
            return {
                "content": [{"type": "text", "text": f"Server is ready! {message}"}]
            }
        else:
            return {
                "content": [{"type": "text", "text": f"Server not ready: {message}"}],
                "is_error": True
            }

    # Otherwise just check port
    if _wait_for_port(port, timeout):
        return {
            "content": [{"type": "text", "text": f"Server is listening on port {port}."}]
        }
    else:
        return {
            "content": [{
                "type": "text",
                "text": f"Timeout waiting for port {port} after {timeout} seconds."
            }],
            "is_error": True
        }


@tool(
    "server_status",
    "Check the status of servers on one or more ports. Shows what's running and if it's tracked.",
    {"ports": str}  # Comma-separated list of ports or single port
)
async def server_status(args: dict[str, Any]) -> dict[str, Any]:
    """Check status of servers on specified ports."""
    ports_str = args.get("ports", "")

    # Parse ports
    ports = []
    for p in ports_str.replace(",", " ").split():
        try:
            ports.append(int(p.strip()))
        except ValueError:
            pass

    if not ports:
        return {
            "content": [{"type": "text", "text": "No valid ports specified."}],
            "is_error": True
        }

    tracker = _get_tracker()
    lines = [
        "=" * 60,
        "SERVER STATUS",
        "=" * 60,
        f"{'Port':<8} {'Status':<12} {'PID':<8} {'Process':<15} {'Tracked'}",
        "-" * 60,
    ]

    for port in ports:
        if _is_port_in_use(port):
            proc_info = _find_process_on_port(port)
            if proc_info:
                pid = proc_info["pid"]
                name = proc_info["process_name"][:15]
                tracked = "Yes" if pid in tracker.processes else "No"
                lines.append(f"{port:<8} {'RUNNING':<12} {pid:<8} {name:<15} {tracked}")
            else:
                lines.append(f"{port:<8} {'RUNNING':<12} {'?':<8} {'unknown':<15} {'?'}")
        else:
            lines.append(f"{port:<8} {'STOPPED':<12} {'-':<8} {'-':<15} {'-'}")

    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


@tool(
    "server_restart",
    "Stop a server on a port and restart it with a new command.",
    {
        "port": int,      # Port to restart
        "command": str,   # New command to run
        "name": str,      # Server name
        "wait": bool,     # Wait for server to be ready (default True)
        "timeout": int,   # Wait timeout in seconds (default 30)
    }
)
async def server_restart(args: dict[str, Any]) -> dict[str, Any]:
    """Stop and restart a server on a port."""
    port = args["port"]
    command = args["command"]
    name = args.get("name", "server")
    wait = args.get("wait", True)
    timeout = args.get("timeout", 30)

    # Stop existing server
    if _is_port_in_use(port):
        stop_result = await server_stop_port({"port": port, "force": True})
        if stop_result.get("is_error"):
            return stop_result
        # Wait a moment for port to be freed
        time.sleep(1)

    # Start new server
    start_result = await server_start({
        "command": command,
        "name": name,
        "port": port
    })

    if start_result.get("is_error"):
        return start_result

    # Wait for server to be ready
    if wait:
        wait_result = await server_wait({"port": port, "timeout": timeout})
        if wait_result.get("is_error"):
            return {
                "content": [{
                    "type": "text",
                    "text": (
                        f"Server started but not responding on port {port}.\n"
                        f"Start result: {start_result['content'][0]['text']}\n"
                        f"Wait result: {wait_result['content'][0]['text']}"
                    )
                }],
                "is_error": True
            }

    return {
        "content": [{
            "type": "text",
            "text": f"Server '{name}' restarted successfully on port {port}."
        }]
    }


# List of all server tool names (for allowed_tools)
SERVER_TOOLS = [
    "mcp__servers__server_start",
    "mcp__servers__server_stop_port",
    "mcp__servers__server_wait",
    "mcp__servers__server_status",
    "mcp__servers__server_restart",
]


def create_server_tools_server(project_dir: Path) -> McpSdkServerConfig:
    """
    Create an MCP server with server management tools.

    Args:
        project_dir: The project directory

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    set_project_dir(project_dir)

    return create_sdk_mcp_server(
        name="servers",
        version="1.0.0",
        tools=[
            server_start,
            server_stop_port,
            server_wait,
            server_status,
            server_restart,
        ]
    )
