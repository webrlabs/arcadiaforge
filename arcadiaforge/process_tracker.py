"""
Process Tracker
===============

Tracks child processes spawned during coding sessions and provides cleanup.
"""

import atexit
import json
import os
import platform
import signal
import subprocess
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from arcadiaforge.output import (
    console,
    print_success,
    print_warning,
    print_error,
    print_info,
    print_muted,
    print_subheader,
    create_table,
    print_table,
    spinner,
    icon,
)


@dataclass
class TrackedProcess:
    """A tracked child process."""
    pid: int
    command: str
    name: str  # Short name like "vite", "python app.py"
    started_at: str
    session_id: int
    port: Optional[int] = None  # If it's a server, what port

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TrackedProcess":
        return cls(**data)


class ProcessTracker:
    """
    Tracks spawned child processes for cleanup.

    Persists process info to disk so cleanup can happen even after restart.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.tracker_file = project_dir / ".processes.json"
        self.processes: Dict[int, TrackedProcess] = {}
        self._load()

        # Register cleanup on exit
        atexit.register(self._on_exit)

    def _load(self) -> None:
        """Load tracked processes from disk."""
        if self.tracker_file.exists():
            try:
                with open(self.tracker_file, "r") as f:
                    data = json.load(f)
                    for pid_str, proc_data in data.items():
                        pid = int(pid_str)
                        self.processes[pid] = TrackedProcess.from_dict(proc_data)
            except Exception as e:
                print_warning(f"Could not load process tracker: {e}")
                self.processes = {}

    def _save(self) -> None:
        """Save tracked processes to disk."""
        try:
            self.project_dir.mkdir(parents=True, exist_ok=True)
            with open(self.tracker_file, "w") as f:
                data = {str(pid): proc.to_dict() for pid, proc in self.processes.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            print_warning(f"Could not save process tracker: {e}")

    def track(
        self,
        pid: int,
        command: str,
        session_id: int,
        name: Optional[str] = None,
        port: Optional[int] = None,
    ) -> None:
        """
        Track a spawned process.

        Args:
            pid: Process ID
            command: Full command that was run
            session_id: Current session ID
            name: Short name (auto-generated if not provided)
            port: Server port if applicable
        """
        if name is None:
            # Generate a short name from the command
            name = self._extract_name(command)

        proc = TrackedProcess(
            pid=pid,
            command=command[:200],  # Truncate long commands
            name=name,
            started_at=datetime.now().isoformat(),
            session_id=session_id,
            port=port,
        )
        self.processes[pid] = proc
        self._save()

    def _extract_name(self, command: str) -> str:
        """Extract a short name from a command."""
        parts = command.split()
        if not parts:
            return "unknown"

        base = parts[0].lower()

        # Handle common patterns
        if "python" in base:
            # python app.py -> app.py
            for part in parts[1:]:
                if part.endswith(".py") and not part.startswith("-"):
                    return f"python {part}"
            return "python"
        elif "node" in base:
            # node server.js -> server.js
            for part in parts[1:]:
                if part.endswith(".js") and not part.startswith("-"):
                    return f"node {part}"
            return "node"
        elif "npm" in base:
            # npm run dev -> npm:dev
            if "run" in parts:
                idx = parts.index("run")
                if idx + 1 < len(parts):
                    return f"npm:{parts[idx + 1]}"
            return "npm"
        elif "npx" in base:
            # npx vite -> vite
            if len(parts) > 1:
                return parts[1]
            return "npx"
        else:
            return os.path.basename(base)

    def untrack(self, pid: int) -> None:
        """Stop tracking a process."""
        if pid in self.processes:
            del self.processes[pid]
            self._save()

    def is_running(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            if platform.system() == "Windows":
                # Windows: use tasklist
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True,
                    text=True,
                    shell=True,
                )
                return str(pid) in result.stdout
            else:
                # Unix: send signal 0 to check if process exists
                os.kill(pid, 0)
                return True
        except (OSError, subprocess.SubprocessError):
            return False

    def get_running(self) -> List[TrackedProcess]:
        """Get list of tracked processes that are still running."""
        running = []
        dead_pids = []

        for pid, proc in self.processes.items():
            if self.is_running(pid):
                running.append(proc)
            else:
                dead_pids.append(pid)

        # Clean up dead processes
        for pid in dead_pids:
            del self.processes[pid]
        if dead_pids:
            self._save()

        return running

    def kill_process(self, pid: int, force: bool = False) -> bool:
        """
        Kill a specific process.

        Args:
            pid: Process ID to kill
            force: Use SIGKILL instead of SIGTERM

        Returns:
            True if killed successfully
        """
        if not self.is_running(pid):
            self.untrack(pid)
            return True

        try:
            if platform.system() == "Windows":
                # Windows: use taskkill
                cmd = ["taskkill", "/PID", str(pid)]
                if force:
                    cmd.append("/F")
                subprocess.run(cmd, capture_output=True, shell=True)
            else:
                # Unix: send signal
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.kill(pid, sig)

            # Wait a moment and check if it died
            time.sleep(0.5)
            if not self.is_running(pid):
                self.untrack(pid)
                return True

            # If still running and we didn't force, try force
            if not force:
                return self.kill_process(pid, force=True)

            return False
        except Exception as e:
            print_warning(f"Failed to kill PID {pid}: {e}")
            return False

    def kill_all(self, force: bool = False) -> tuple[int, int]:
        """
        Kill all tracked processes.

        Returns:
            (killed_count, failed_count)
        """
        running = self.get_running()
        killed = 0
        failed = 0

        for proc in running:
            if self.kill_process(proc.pid, force=force):
                killed += 1
            else:
                failed += 1

        return killed, failed

    def kill_session(self, session_id: int, force: bool = False) -> tuple[int, int]:
        """
        Kill all processes from a specific session.

        Returns:
            (killed_count, failed_count)
        """
        running = self.get_running()
        killed = 0
        failed = 0

        for proc in running:
            if proc.session_id == session_id:
                if self.kill_process(proc.pid, force=force):
                    killed += 1
                else:
                    failed += 1

        return killed, failed

    def print_status(self) -> None:
        """Print status of all tracked processes."""
        running = self.get_running()

        if not running:
            print_info("No tracked processes running.")
            return

        print_subheader(f"Tracked Processes ({len(running)} running)")

        table = create_table(columns=["PID", "Name", "Session", "Port", "Started"])

        for proc in sorted(running, key=lambda p: p.pid):
            port_str = f"[af.number]{proc.port}[/]" if proc.port else "[af.muted]-[/]"

            # Parse and format the timestamp
            try:
                started = datetime.fromisoformat(proc.started_at)
                started_str = started.strftime("%H:%M:%S")
            except:
                started_str = proc.started_at[:8]

            table.add_row(
                f"[af.number]{proc.pid}[/]",
                proc.name,
                f"[af.muted]#{proc.session_id}[/]",
                port_str,
                f"[af.muted]{started_str}[/]",
            )

        print_table(table)

    def _on_exit(self) -> None:
        """Called when the framework exits."""
        running = self.get_running()
        if running:
            print_info(f"\n{len(running)} background processes still running.")
            print_muted("Run 'python -m arcadiaforge.process_tracker cleanup' to stop them.")

    def cleanup_interactive(self) -> None:
        """Interactive cleanup of processes."""
        running = self.get_running()

        if not running:
            print_success("No processes to clean up.")
            return

        self.print_status()
        console.print()

        # Ask for confirmation
        from arcadiaforge.output import confirm
        if confirm(f"Kill all {len(running)} tracked processes?"):
            with spinner("Stopping processes..."):
                killed, failed = self.kill_all()

            if killed > 0:
                print_success(f"Stopped {killed} process(es)")
            if failed > 0:
                print_warning(f"Failed to stop {failed} process(es)")
        else:
            print_muted("Cancelled.")


# Global tracker instance (lazily initialized)
_tracker: Optional[ProcessTracker] = None


def get_tracker(project_dir: Path) -> ProcessTracker:
    """Get or create the process tracker for a project."""
    global _tracker
    if _tracker is None or _tracker.project_dir != project_dir:
        _tracker = ProcessTracker(project_dir)
    return _tracker


def main():
    """CLI for process tracker."""
    import argparse

    parser = argparse.ArgumentParser(description="Manage tracked processes")
    parser.add_argument("command", choices=["status", "cleanup", "kill"],
                        help="Command to run")
    parser.add_argument("--project-dir", "-p", type=Path, default=Path.cwd(),
                        help="Project directory")
    parser.add_argument("--pid", type=int, help="Specific PID to kill")
    parser.add_argument("--force", "-f", action="store_true",
                        help="Force kill (SIGKILL)")

    args = parser.parse_args()
    tracker = ProcessTracker(args.project_dir)

    if args.command == "status":
        tracker.print_status()
    elif args.command == "cleanup":
        tracker.cleanup_interactive()
    elif args.command == "kill":
        if args.pid:
            if tracker.kill_process(args.pid, force=args.force):
                print_success(f"Killed process {args.pid}")
            else:
                print_error(f"Failed to kill process {args.pid}")
        else:
            print_error("--pid required for kill command")


if __name__ == "__main__":
    main()
