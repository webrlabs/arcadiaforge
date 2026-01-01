"""
Capability Checker
==================

Checks system capabilities (node, docker, git, etc.) and persists results
to the database for agent queries.

Agents can query capabilities before attempting to use external tools,
allowing them to gracefully handle missing dependencies.
"""

import asyncio
import platform
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.connection import get_session_maker
from arcadiaforge.db.models import SystemCapability
from arcadiaforge.output import (
    console,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_muted,
    print_subheader,
    spinner,
    icon,
)


@dataclass
class CapabilityStatus:
    """Status of a single capability check."""
    name: str
    is_available: bool
    version: Optional[str] = None
    path: Optional[str] = None
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    is_required: bool = False


# Capability definitions
# Note: node/npx are only required when Puppeteer MCP is enabled
# They become optional for non-web projects
DEFAULT_REQUIRED_CAPABILITIES = ["node", "npx"]
DEFAULT_OPTIONAL_CAPABILITIES = ["docker", "git", "python"]

# Runtime capability lists (can be modified based on config)
REQUIRED_CAPABILITIES = list(DEFAULT_REQUIRED_CAPABILITIES)
OPTIONAL_CAPABILITIES = list(DEFAULT_OPTIONAL_CAPABILITIES)


def configure_capabilities_for_project(puppeteer_enabled: bool = True) -> None:
    """
    Configure which capabilities are required based on project needs.

    For non-web projects that don't use Puppeteer, node/npx are not required.

    Args:
        puppeteer_enabled: Whether Puppeteer MCP is enabled
    """
    global REQUIRED_CAPABILITIES, OPTIONAL_CAPABILITIES

    if puppeteer_enabled:
        REQUIRED_CAPABILITIES = list(DEFAULT_REQUIRED_CAPABILITIES)
        OPTIONAL_CAPABILITIES = list(DEFAULT_OPTIONAL_CAPABILITIES)
    else:
        # Node/npx are optional for non-web projects
        REQUIRED_CAPABILITIES = []
        OPTIONAL_CAPABILITIES = ["node", "npx", "docker", "git", "python"]


class CapabilityChecker:
    """
    Checks and caches system capabilities.

    Checks required and optional capabilities at startup, saves results
    to the database, and provides query methods for agents.
    """

    def __init__(self, project_dir: Path):
        """
        Initialize the capability checker.

        Args:
            project_dir: Project root directory (for database access)
        """
        self.project_dir = project_dir
        self._capabilities: Dict[str, CapabilityStatus] = {}
        self._is_windows = platform.system().lower() == "windows"

    async def check_all(self) -> Dict[str, CapabilityStatus]:
        """
        Check all capabilities (required and optional).

        Returns:
            Dictionary mapping capability names to their status.
        """
        # Check required capabilities
        for cap_name in REQUIRED_CAPABILITIES:
            status = self._check_capability(cap_name, is_required=True)
            self._capabilities[cap_name] = status

        # Check optional capabilities
        for cap_name in OPTIONAL_CAPABILITIES:
            status = self._check_capability(cap_name, is_required=False)
            self._capabilities[cap_name] = status

        # Save to database
        await self._save_all_capabilities()

        return self._capabilities

    def _check_capability(self, name: str, is_required: bool = False) -> CapabilityStatus:
        """Check a single capability."""
        checker_method = getattr(self, f"_check_{name}", None)
        if checker_method:
            return checker_method(is_required)
        else:
            # Generic check for unknown capabilities
            return self._generic_check(name, is_required)

    def _generic_check(self, name: str, is_required: bool) -> CapabilityStatus:
        """Generic check using shutil.which."""
        path = shutil.which(name)
        if path:
            return CapabilityStatus(
                name=name,
                is_available=True,
                path=path,
                is_required=is_required,
            )
        return CapabilityStatus(
            name=name,
            is_available=False,
            error_message=f"'{name}' not found in PATH",
            is_required=is_required,
        )

    def _check_node(self, is_required: bool) -> CapabilityStatus:
        """Check Node.js availability and version."""
        path = shutil.which("node")
        if not path:
            return CapabilityStatus(
                name="node",
                is_available=False,
                error_message="Node.js not found in PATH",
                is_required=is_required,
            )

        try:
            result = subprocess.run(
                ["node", "--version"],
                capture_output=True,
                text=True,
                shell=self._is_windows,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                return CapabilityStatus(
                    name="node",
                    is_available=True,
                    version=version,
                    path=path,
                    is_required=is_required,
                )
            else:
                return CapabilityStatus(
                    name="node",
                    is_available=False,
                    path=path,
                    error_message=f"node --version failed: {result.stderr.strip()}",
                    is_required=is_required,
                )
        except Exception as e:
            return CapabilityStatus(
                name="node",
                is_available=False,
                path=path,
                error_message=str(e),
                is_required=is_required,
            )

    def _check_npx(self, is_required: bool) -> CapabilityStatus:
        """Check npx availability and version."""
        path = shutil.which("npx")
        if not path:
            return CapabilityStatus(
                name="npx",
                is_available=False,
                error_message="npx not found in PATH",
                is_required=is_required,
            )

        try:
            result = subprocess.run(
                ["npx", "--version"],
                capture_output=True,
                text=True,
                shell=self._is_windows,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                return CapabilityStatus(
                    name="npx",
                    is_available=True,
                    version=version,
                    path=path,
                    is_required=is_required,
                )
            else:
                return CapabilityStatus(
                    name="npx",
                    is_available=False,
                    path=path,
                    error_message=f"npx --version failed: {result.stderr.strip()}",
                    is_required=is_required,
                )
        except Exception as e:
            return CapabilityStatus(
                name="npx",
                is_available=False,
                path=path,
                error_message=str(e),
                is_required=is_required,
            )

    def _check_docker(self, is_required: bool) -> CapabilityStatus:
        """
        Check Docker availability, version, and daemon status.

        Docker requires both the CLI and the daemon to be running.
        """
        path = shutil.which("docker")
        if not path:
            return CapabilityStatus(
                name="docker",
                is_available=False,
                error_message="Docker CLI not found in PATH",
                is_required=is_required,
                details={"cli_available": False, "daemon_running": False},
            )

        details = {"cli_available": True, "daemon_running": False}

        # Check version
        version = None
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                shell=self._is_windows,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
        except Exception:
            pass

        # Check daemon status with docker info
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                shell=self._is_windows,
                timeout=30,  # Longer timeout for daemon check
            )
            if result.returncode == 0:
                details["daemon_running"] = True
                return CapabilityStatus(
                    name="docker",
                    is_available=True,
                    version=version,
                    path=path,
                    is_required=is_required,
                    details=details,
                )
            else:
                error_msg = result.stderr.strip() if result.stderr else "Docker daemon not responding"
                # Common error on Windows when Docker Desktop isn't running
                if "error during connect" in error_msg.lower():
                    error_msg = "Docker Desktop is not running"
                return CapabilityStatus(
                    name="docker",
                    is_available=False,
                    version=version,
                    path=path,
                    error_message=error_msg,
                    is_required=is_required,
                    details=details,
                )
        except subprocess.TimeoutExpired:
            return CapabilityStatus(
                name="docker",
                is_available=False,
                version=version,
                path=path,
                error_message="Docker daemon check timed out",
                is_required=is_required,
                details=details,
            )
        except Exception as e:
            return CapabilityStatus(
                name="docker",
                is_available=False,
                version=version,
                path=path,
                error_message=str(e),
                is_required=is_required,
                details=details,
            )

    def _check_git(self, is_required: bool) -> CapabilityStatus:
        """Check Git availability and version."""
        path = shutil.which("git")
        if not path:
            return CapabilityStatus(
                name="git",
                is_available=False,
                error_message="git not found in PATH",
                is_required=is_required,
            )

        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                shell=self._is_windows,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                return CapabilityStatus(
                    name="git",
                    is_available=True,
                    version=version,
                    path=path,
                    is_required=is_required,
                )
            else:
                return CapabilityStatus(
                    name="git",
                    is_available=False,
                    path=path,
                    error_message=f"git --version failed: {result.stderr.strip()}",
                    is_required=is_required,
                )
        except Exception as e:
            return CapabilityStatus(
                name="git",
                is_available=False,
                path=path,
                error_message=str(e),
                is_required=is_required,
            )

    def _check_python(self, is_required: bool) -> CapabilityStatus:
        """Check Python availability and version."""
        # Try python3 first, then python
        for cmd in ["python3", "python"]:
            path = shutil.which(cmd)
            if path:
                try:
                    result = subprocess.run(
                        [cmd, "--version"],
                        capture_output=True,
                        text=True,
                        shell=self._is_windows,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        version = result.stdout.strip() or result.stderr.strip()
                        return CapabilityStatus(
                            name="python",
                            is_available=True,
                            version=version,
                            path=path,
                            is_required=is_required,
                        )
                except Exception:
                    continue

        return CapabilityStatus(
            name="python",
            is_available=False,
            error_message="Python not found in PATH",
            is_required=is_required,
        )

    async def _save_all_capabilities(self) -> None:
        """Save all capability statuses to the database."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                for name, status in self._capabilities.items():
                    await self._save_capability(session, status)
                await session.commit()
        except Exception as e:
            # Don't fail if database isn't available yet
            print_warning(f"Could not save capabilities to database: {e}")

    async def _save_capability(self, session: AsyncSession, status: CapabilityStatus) -> None:
        """Save a single capability status to the database."""
        # Check if record exists
        result = await session.execute(
            select(SystemCapability).where(SystemCapability.capability_name == status.name)
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing record
            existing.is_available = status.is_available
            existing.version = status.version
            existing.path = status.path
            existing.checked_at = datetime.utcnow()
            existing.error_message = status.error_message
            existing.details = status.details or {}
        else:
            # Create new record
            cap = SystemCapability(
                capability_name=status.name,
                is_available=status.is_available,
                version=status.version,
                path=status.path,
                error_message=status.error_message,
                details=status.details or {},
            )
            session.add(cap)

    def print_status(self) -> None:
        """Print capability status to console."""
        print_subheader("System Capabilities")

        # Required capabilities
        for name in REQUIRED_CAPABILITIES:
            status = self._capabilities.get(name)
            if status:
                self._print_capability_status(status, is_required=True)

        # Optional capabilities
        console.print()
        print_muted("Optional capabilities:")
        for name in OPTIONAL_CAPABILITIES:
            status = self._capabilities.get(name)
            if status:
                self._print_capability_status(status, is_required=False)

    def _print_capability_status(self, status: CapabilityStatus, is_required: bool) -> None:
        """Print a single capability status."""
        if status.is_available:
            version_str = f" ({status.version})" if status.version else ""
            console.print(f"  [af.ok]{icon('check')}[/] [af.muted]{status.name}:[/] available{version_str}")
        else:
            marker = icon('cross') if is_required else icon('warning')
            style = "af.err" if is_required else "af.warn"
            error_str = f" - {status.error_message}" if status.error_message else ""
            console.print(f"  [{style}]{marker}[/] [af.muted]{status.name}:[/] [{style}]not available{error_str}[/]")

    def all_required_available(self) -> bool:
        """Check if all required capabilities are available."""
        for name in REQUIRED_CAPABILITIES:
            status = self._capabilities.get(name)
            if not status or not status.is_available:
                return False
        return True

    def is_available(self, name: str) -> bool:
        """Check if a specific capability is available."""
        status = self._capabilities.get(name)
        return status.is_available if status else False

    def get_capability(self, name: str) -> Optional[CapabilityStatus]:
        """Get the status of a specific capability."""
        return self._capabilities.get(name)

    def get_unavailable_required(self) -> List[str]:
        """Get list of unavailable required capabilities."""
        return [
            name for name in REQUIRED_CAPABILITIES
            if not self._capabilities.get(name, CapabilityStatus(name=name, is_available=False)).is_available
        ]

    def get_all_capabilities(self) -> Dict[str, CapabilityStatus]:
        """Get all capability statuses."""
        return self._capabilities.copy()


async def check_capabilities(project_dir: Path) -> CapabilityChecker:
    """
    Check all system capabilities and return the checker instance.

    Args:
        project_dir: Project root directory

    Returns:
        Configured CapabilityChecker instance
    """
    checker = CapabilityChecker(project_dir)
    await checker.check_all()
    return checker
