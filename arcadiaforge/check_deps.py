"""
Dependency Checker
==================

Checks for external dependencies required by the framework and its MCP servers.
Pre-installs MCP packages to avoid delays during first agent session.
"""

import platform
import shutil
import subprocess
import sys
from typing import List, Tuple

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


# MCP packages that should be pre-installed
MCP_PACKAGES = [
    ("@modelcontextprotocol/server-puppeteer", "Puppeteer (browser automation)"),
    ("@modelcontextprotocol/server-fetch", "Fetch (HTTP requests)"),
]


def check_node_environment() -> bool:
    """
    Check if Node.js and npx are available.

    Returns:
        True if available, False otherwise.
    """
    node_path = shutil.which("node")
    npx_path = shutil.which("npx")

    if not node_path:
        print_error("'node' (Node.js) is not found in PATH")
        console.print("   [af.muted]The framework requires Node.js to run MCP servers.[/]")
        console.print("   [af.info]Please install Node.js from https://nodejs.org/[/]")
        return False

    if not npx_path:
        print_error("'npx' is not found in PATH")
        console.print("   [af.muted]It is usually installed with Node.js.[/]")
        return False

    # Check that they actually run and get versions
    is_windows = platform.system().lower() == "windows"
    try:
        node_result = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            check=True,
            shell=is_windows,
            text=True
        )
        npx_result = subprocess.run(
            ["npx", "--version"],
            capture_output=True,
            check=True,
            shell=is_windows,
            text=True
        )
        node_version = node_result.stdout.strip()
        npx_version = npx_result.stdout.strip()
        print_success(f"Node.js {node_version} and npx {npx_version} available")
        return True
    except subprocess.CalledProcessError:
        print_error("Node.js or npx is installed but failing to run")
        return False
    except Exception as e:
        print_error(f"Error checking Node.js environment: {e}")
        return False


def check_mcp_package(package: str, description: str) -> Tuple[bool, str]:
    """
    Check if an MCP package is installed, install if not.

    Args:
        package: npm package name
        description: Human-readable description

    Returns:
        (success, message) tuple
    """
    is_windows = platform.system().lower() == "windows"

    # Try to resolve the package (checks if it's cached/installed)
    try:
        result = subprocess.run(
            ["npx", "--yes", "--package", package, "--", "echo", "installed"],
            capture_output=True,
            shell=is_windows,
            text=True,
            timeout=120  # 2 minute timeout for package install
        )
        if result.returncode == 0:
            return True, "ready"
        else:
            return False, result.stderr.strip()[:100] if result.stderr else "unknown error"
    except subprocess.TimeoutExpired:
        return False, "timeout (check your internet connection)"
    except Exception as e:
        return False, str(e)[:100]


def preinstall_mcp_packages() -> bool:
    """
    Pre-install MCP packages to avoid delays during agent sessions.

    Returns:
        True if all critical packages installed, False otherwise.
    """
    print_subheader("Preparing MCP Servers")

    all_ok = True
    for package, description in MCP_PACKAGES:
        with spinner(f"Checking {description}..."):
            success, message = check_mcp_package(package, description)

        if success:
            console.print(f"  [af.ok]{icon('check')}[/] [af.muted]{description}:[/] ready")
        else:
            console.print(f"  [af.warn]{icon('warning')}[/] [af.muted]{description}:[/] [af.err]{message}[/]")
            # Puppeteer is critical, others are optional
            if "puppeteer" in package.lower():
                all_ok = False

    return all_ok


def check_external_deps(skip_mcp_preinstall: bool = False) -> bool:
    """
    Run all dependency checks.

    Args:
        skip_mcp_preinstall: Skip MCP package pre-installation (faster but may delay first run)

    Returns:
        True if all critical dependencies are met.
    """
    print_subheader("Checking Dependencies")

    # Check Node.js environment
    with spinner("Verifying Node.js environment..."):
        node_ok = check_node_environment()

    if not node_ok:
        return False

    # Pre-install MCP packages
    if not skip_mcp_preinstall:
        console.print()
        mcp_ok = preinstall_mcp_packages()
        if not mcp_ok:
            print_warning("Some MCP packages failed to install")
            print_muted("The framework may still work, but some features might be unavailable.")
            # Don't fail completely - the SDK will try again at runtime

    print_success("All dependencies verified")
    return True


if __name__ == "__main__":
    if check_external_deps():
        sys.exit(0)
    else:
        sys.exit(1)
