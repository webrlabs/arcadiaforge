"""
Native Screenshot Tool
======================

Cross-platform screenshot capture without requiring Puppeteer/browser.
Useful for non-web projects (CLI apps, desktop apps, data pipelines, etc.)

Uses PIL/Pillow for screenshot capture which works on Windows, macOS, and Linux.
"""

import base64
import io
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from claude_code_sdk import tool, create_sdk_mcp_server, McpSdkServerConfig

from arcadiaforge.output import print_success, print_error, print_warning


# Global project directory
_project_dir: Path | None = None

# Screenshot sequence counter
_screenshot_seq = 0


def _get_next_seq() -> int:
    """Get next screenshot sequence number."""
    global _screenshot_seq
    _screenshot_seq += 1
    return _screenshot_seq


def _capture_screen_pil() -> Optional[bytes]:
    """Capture screenshot using PIL/Pillow (cross-platform)."""
    try:
        from PIL import ImageGrab

        # Capture entire screen
        screenshot = ImageGrab.grab()

        # Convert to PNG bytes
        buffer = io.BytesIO()
        screenshot.save(buffer, format='PNG')
        return buffer.getvalue()
    except ImportError:
        return None
    except Exception as e:
        print_error(f"PIL screenshot failed: {e}")
        return None


def _capture_screen_mss() -> Optional[bytes]:
    """Capture screenshot using mss (fast cross-platform alternative)."""
    try:
        import mss

        with mss.mss() as sct:
            # Capture the primary monitor
            monitor = sct.monitors[1]  # Primary monitor (0 is all monitors combined)
            screenshot = sct.grab(monitor)

            # Convert to PNG using mss.tools
            return mss.tools.to_png(screenshot.rgb, screenshot.size)
    except ImportError:
        return None
    except Exception as e:
        print_error(f"mss screenshot failed: {e}")
        return None


def _capture_screen_windows() -> Optional[bytes]:
    """Windows-specific fallback using PowerShell."""
    if platform.system() != 'Windows':
        return None

    try:
        # Create temp file path
        temp_path = Path.home() / '.arcadia_temp_screenshot.png'

        # PowerShell command to capture screen
        ps_script = f'''
Add-Type -AssemblyName System.Windows.Forms
$screen = [System.Windows.Forms.Screen]::PrimaryScreen
$bitmap = New-Object System.Drawing.Bitmap($screen.Bounds.Width, $screen.Bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Bounds.Location, [System.Drawing.Point]::Empty, $screen.Bounds.Size)
$bitmap.Save("{temp_path}")
$graphics.Dispose()
$bitmap.Dispose()
'''

        result = subprocess.run(
            ['powershell', '-Command', ps_script],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0 and temp_path.exists():
            with open(temp_path, 'rb') as f:
                data = f.read()
            temp_path.unlink()  # Clean up
            return data
        return None
    except Exception as e:
        print_error(f"Windows screenshot failed: {e}")
        return None


def _capture_screen_macos() -> Optional[bytes]:
    """macOS-specific fallback using screencapture."""
    if platform.system() != 'Darwin':
        return None

    try:
        temp_path = Path.home() / '.arcadia_temp_screenshot.png'

        result = subprocess.run(
            ['screencapture', '-x', str(temp_path)],  # -x for no sound
            capture_output=True,
            timeout=30
        )

        if result.returncode == 0 and temp_path.exists():
            with open(temp_path, 'rb') as f:
                data = f.read()
            temp_path.unlink()  # Clean up
            return data
        return None
    except Exception as e:
        print_error(f"macOS screenshot failed: {e}")
        return None


def _capture_screen_linux() -> Optional[bytes]:
    """Linux-specific fallback using scrot or gnome-screenshot."""
    if platform.system() != 'Linux':
        return None

    try:
        temp_path = Path.home() / '.arcadia_temp_screenshot.png'

        # Try scrot first
        result = subprocess.run(
            ['scrot', str(temp_path)],
            capture_output=True,
            timeout=30
        )

        if result.returncode != 0:
            # Try gnome-screenshot
            result = subprocess.run(
                ['gnome-screenshot', '-f', str(temp_path)],
                capture_output=True,
                timeout=30
            )

        if result.returncode == 0 and temp_path.exists():
            with open(temp_path, 'rb') as f:
                data = f.read()
            temp_path.unlink()  # Clean up
            return data
        return None
    except FileNotFoundError:
        return None
    except Exception as e:
        print_error(f"Linux screenshot failed: {e}")
        return None


def capture_native_screenshot() -> Optional[bytes]:
    """
    Capture a screenshot using available methods.

    Tries multiple methods in order of preference:
    1. PIL/Pillow ImageGrab (cross-platform, most reliable)
    2. mss (fast cross-platform alternative)
    3. OS-specific fallbacks (PowerShell, screencapture, scrot)

    Returns:
        PNG image bytes, or None if all methods fail.
    """
    # Try PIL first (most reliable cross-platform)
    result = _capture_screen_pil()
    if result:
        return result

    # Try mss (fast alternative)
    result = _capture_screen_mss()
    if result:
        return result

    # OS-specific fallbacks
    system = platform.system()
    if system == 'Windows':
        result = _capture_screen_windows()
    elif system == 'Darwin':
        result = _capture_screen_macos()
    elif system == 'Linux':
        result = _capture_screen_linux()

    if result:
        return result

    print_warning("No screenshot method available. Install Pillow: pip install Pillow")
    return None


@tool(
    "native_screenshot",
    """Capture a screenshot of the desktop/screen without using a browser.

Use this for non-web projects like:
- CLI applications (capture terminal output)
- Desktop applications
- Data pipelines and scripts
- Any project that doesn't have a web UI

The screenshot is saved to the screenshots/ directory and the path is returned.""",
    {
        "name": {
            "type": "string",
            "description": "Optional custom filename (without extension). If not provided, uses timestamp."
        },
        "feature_id": {
            "type": "integer",
            "description": "Optional feature ID for evidence collection."
        },
        "description": {
            "type": "string",
            "description": "Optional description of what the screenshot shows."
        }
    }
)
async def native_screenshot(args: dict[str, Any]) -> dict[str, Any]:
    """Capture a native screenshot and save it."""
    name = args.get("name")
    feature_id = args.get("feature_id")
    description = args.get("description")

    # Capture screenshot
    image_data = capture_native_screenshot()

    if not image_data:
        return {
            "content": [{
                "type": "text",
                "text": "ERROR: Could not capture screenshot. Install Pillow with: pip install Pillow"
            }],
            "is_error": True
        }

    try:
        # Determine project directory
        project_dir = _project_dir or Path.cwd()

        # Create screenshots directory
        screenshots_dir = project_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename
        if name:
            filename = f"{name}.png"
        elif feature_id:
            filename = f"feature_{feature_id}_evidence.png"
        else:
            seq = _get_next_seq()
            timestamp = int(time.time())
            filename = f"screenshot_{timestamp}_{seq:03d}.png"

        file_path = screenshots_dir / filename

        # Save screenshot
        with open(file_path, 'wb') as f:
            f.write(image_data)

        print_success(f"Native screenshot saved: {file_path.relative_to(project_dir)}")

        # Also save as evidence if feature_id provided
        evidence_path = None
        if feature_id:
            verification_dir = project_dir / "verification"
            verification_dir.mkdir(parents=True, exist_ok=True)
            evidence_path = verification_dir / f"feature_{feature_id}_evidence.png"

            import shutil
            shutil.copy2(file_path, evidence_path)
            print_success(f"Evidence saved: {evidence_path.relative_to(project_dir)}")

        # Build response
        response_parts = [
            f"Screenshot captured and saved to: {file_path.relative_to(project_dir)}"
        ]

        if evidence_path:
            response_parts.append(f"Evidence copy saved to: {evidence_path.relative_to(project_dir)}")

        if description:
            response_parts.append(f"Description: {description}")

        return {
            "content": [
                {
                    "type": "text",
                    "text": "\n".join(response_parts)
                }
            ]
        }

    except Exception as e:
        return {
            "content": [{
                "type": "text",
                "text": f"ERROR saving screenshot: {str(e)}"
            }],
            "is_error": True
        }


@tool(
    "screenshot_available",
    "Check if native screenshot capability is available (without browser/Puppeteer).",
    {}
)
async def screenshot_available(args: dict[str, Any]) -> dict[str, Any]:
    """Check if native screenshot is available."""
    methods = []

    # Check PIL
    try:
        from PIL import ImageGrab
        methods.append("PIL/Pillow")
    except ImportError:
        pass

    # Check mss
    try:
        import mss
        methods.append("mss")
    except ImportError:
        pass

    # Check OS-specific
    system = platform.system()
    if system == 'Windows':
        methods.append("PowerShell (fallback)")
    elif system == 'Darwin':
        methods.append("screencapture (fallback)")
    elif system == 'Linux':
        methods.append("scrot/gnome-screenshot (fallback)")

    if methods:
        return {
            "content": [{
                "type": "text",
                "text": f"Native screenshot available using: {', '.join(methods)}"
            }]
        }
    else:
        return {
            "content": [{
                "type": "text",
                "text": "No screenshot methods available. Install Pillow: pip install Pillow"
            }]
        }


@tool(
    "capture_terminal_output",
    """Capture terminal/console output as a screenshot.

Use this when you want to document CLI output, error messages, or
terminal-based application output as visual evidence.""",
    {
        "name": {
            "type": "string",
            "description": "Optional custom filename (without extension)."
        },
        "feature_id": {
            "type": "integer",
            "description": "Optional feature ID for evidence collection."
        }
    }
)
async def capture_terminal_output(args: dict[str, Any]) -> dict[str, Any]:
    """Capture terminal output as a screenshot."""
    # For now, this just captures the whole screen
    # In the future, we could detect and capture just the terminal window
    return await native_screenshot(args)


def set_project_dir(project_dir: Path) -> None:
    """Set the project directory for screenshot saving."""
    global _project_dir
    _project_dir = project_dir


def create_native_screenshot_server(project_dir: Path) -> McpSdkServerConfig:
    """
    Create an MCP server with native screenshot tools.

    Args:
        project_dir: The project directory for saving screenshots.

    Returns:
        McpSdkServerConfig to add to mcp_servers
    """
    set_project_dir(project_dir)

    return create_sdk_mcp_server(
        name="native-screenshot",
        version="1.0.0",
        tools=[
            native_screenshot,
            screenshot_available,
            capture_terminal_output,
        ]
    )


# List of all native screenshot tool names (for allowed_tools)
NATIVE_SCREENSHOT_TOOLS = [
    "mcp__native-screenshot__native_screenshot",
    "mcp__native-screenshot__screenshot_available",
    "mcp__native-screenshot__capture_terminal_output",
]
