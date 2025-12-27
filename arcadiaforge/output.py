"""
Rich Output Utilities
=====================

Unified terminal output system for Arcadia Forge using Rich library.
Provides consistent styling, interactive elements, and cross-platform support.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Union

from rich.console import Console, Group
from rich.json import JSON
from rich.logging import RichHandler
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    Progress,
    BarColumn,
    TextColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    SpinnerColumn,
)
from rich.prompt import Confirm, Prompt, IntPrompt
from rich.rule import Rule
from rich.spinner import Spinner
from rich.status import Status
from rich.style import Style
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from arcadiaforge.platform_utils import detect_os, get_platform_info, OSType


# =============================================================================
# Color Scheme & Theme
# =============================================================================

@dataclass(frozen=True)
class ArcadiaColors:
    """Arcadia Forge color palette using hex for truecolor terminal support."""
    ink: str = "#E6E6E6"       # primary text
    dim: str = "#9AA4B2"       # muted text
    forge: str = "#F59E0B"     # warm accent (forge orange)
    arc: str = "#22D3EE"       # cool accent (arcadia cyan)
    steel: str = "#94A3B8"     # secondary accent
    ok: str = "#22C55E"        # success green
    warn: str = "#FBBF24"      # warning yellow
    err: str = "#EF4444"       # error red


def arcadia_theme(colors: ArcadiaColors = ArcadiaColors()) -> Theme:
    """
    Rich Theme for Arcadia Forge CLI.

    Style names are semantic so you can use them everywhere:
      console.print("...", style="af.ok")
    """
    return Theme(
        {
            # Banner + brand
            "af.banner": f"bold {colors.arc}",
            "af.subtitle": f"{colors.dim}",
            "af.border": f"{colors.arc}",
            "af.accent": f"bold {colors.forge}",
            "af.muted": f"{colors.dim}",
            "af.text": f"{colors.ink}",

            # Status
            "af.ok": f"bold {colors.ok}",
            "af.warn": f"bold {colors.warn}",
            "af.err": f"bold {colors.err}",
            "af.info": f"{colors.arc}",

            # Data display
            "af.key": f"{colors.steel}",
            "af.value": f"{colors.ink}",
            "af.number": f"bold {colors.forge}",
            "af.path": f"{colors.arc}",
            "af.timestamp": f"{colors.dim}",

            # Agent phases / roles
            "af.phase.plan": f"bold {colors.arc}",
            "af.phase.exec": f"bold {colors.forge}",
            "af.phase.verify": f"bold {colors.steel}",
            "af.phase.fix": f"bold {colors.warn}",

            # Table styling
            "af.table.header": f"bold {colors.arc}",
            "af.table.row.odd": f"{colors.ink}",
            "af.table.row.even": f"{colors.dim}",

            # Status indicators
            "af.status.pass": f"bold {colors.ok}",
            "af.status.fail": f"bold {colors.err}",
            "af.status.pending": f"{colors.warn}",
            "af.status.skip": f"{colors.dim}",
        }
    )


# =============================================================================
# Unicode / ASCII Fallbacks
# =============================================================================

def _can_use_unicode() -> bool:
    """Check if the terminal can handle Unicode/emoji characters."""
    import sys
    import os
    if os.name == 'nt':
        try:
            encoding = sys.stdout.encoding or 'utf-8'
            # Test with actual Unicode characters we want to use
            "\u2713\u2717\u2022".encode(encoding)
            return True
        except (UnicodeEncodeError, LookupError, AttributeError):
            return False
    return True


def _can_use_emoji() -> bool:
    """Check if the terminal can handle emoji characters (requires UTF-8)."""
    import sys
    import os
    if os.name == 'nt':
        encoding = (sys.stdout.encoding or '').lower()
        # Only UTF-8 can reliably handle emoji on Windows
        return 'utf-8' in encoding or 'utf8' in encoding
    return True


def _setup_windows_utf8() -> None:
    """Try to enable UTF-8 mode on Windows for better Unicode support."""
    import sys
    import os
    if os.name == 'nt':
        try:
            # Try to set UTF-8 mode for the console
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # SetConsoleOutputCP(65001) - 65001 is UTF-8
            kernel32.SetConsoleOutputCP(65001)
            # Also try to reconfigure stdout/stderr
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            if hasattr(sys.stderr, 'reconfigure'):
                sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass  # Silently fail - not all environments support this


# Try to set up UTF-8 on Windows early
_setup_windows_utf8()


def _sanitize_text(text: str) -> str:
    """
    Sanitize text for safe console output on Windows.
    Replaces characters that can't be encoded with safe alternatives.
    """
    import sys
    import os
    if os.name != 'nt':
        return text

    encoding = (sys.stdout.encoding or 'utf-8').lower()
    if 'utf-8' in encoding or 'utf8' in encoding:
        return text

    # Common emoji replacements for cp1252/latin-1 encoding
    emoji_map = {
        '\u2705': '[OK]',   # ✅ white heavy check mark
        '\u2714': '[OK]',   # ✔ heavy check mark
        '\u274c': '[X]',    # ❌ cross mark
        '\u274e': '[X]',    # ❎ negative squared cross mark
        '\u26a0': '[!]',    # ⚠ warning sign
        '\u2139': '[i]',    # ℹ information source
        '\U0001F680': '>>', # 🚀 rocket
        '\U0001F4DD': '**', # 📝 memo
        '\U0001F4BB': '##', # 💻 laptop
        '\U0001F389': '***', # 🎉 party popper
        '\U0001F551': '[T]', # 🕑 clock
        '\U0001F4C1': '[D]', # 📁 folder
        '\U0001F4C4': '[F]', # 📄 page
        '\U0001F500': '[G]', # 🔀 shuffle (git)
    }

    for emoji, replacement in emoji_map.items():
        text = text.replace(emoji, replacement)

    # Final pass: replace any remaining non-encodable characters
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        # Replace characters one by one
        result = []
        for char in text:
            try:
                char.encode(encoding)
                result.append(char)
            except UnicodeEncodeError:
                result.append('?')
        text = ''.join(result)

    return text


_UNICODE_ICONS = {
    "rocket": "\U0001F680",
    "pencil": "\U0001F4DD",
    "computer": "\U0001F4BB",
    "lightning": "\u26A1",
    "check": "\u2713",
    "cross": "\u2717",
    "blocked": "\u26D4",
    "party": "\U0001F389",
    "warning": "\u26A0\uFE0F",
    "info": "\u2139",
    "bar_filled": "\u2588",
    "bar_empty": "\u2591",
    "bullet": "\u2022",
    "arrow_right": "\u2192",
    "clock": "\U0001F551",
    "folder": "\U0001F4C1",
    "file": "\U0001F4C4",
    "git": "\U0001F500",
    "tag": "\U0001F3F7",
    "star": "\u2B50",
    "spinner": "\u23F3",
}

_ASCII_ICONS = {
    "rocket": ">>",
    "pencil": "**",
    "computer": "##",
    "lightning": "->",
    "check": "[OK]",
    "cross": "[X]",
    "blocked": "[BLOCKED]",
    "party": "***",
    "warning": "[!]",
    "info": "[i]",
    "bar_filled": "#",
    "bar_empty": "-",
    "bullet": "-",
    "arrow_right": "->",
    "clock": "[T]",
    "folder": "[D]",
    "file": "[F]",
    "git": "[G]",
    "tag": "[#]",
    "star": "[*]",
    "spinner": "[...]",
}

_USE_UNICODE = _can_use_unicode()
_ICONS = _UNICODE_ICONS if _USE_UNICODE else _ASCII_ICONS


def icon(name: str) -> str:
    """Get an icon by name, using ASCII fallback if needed."""
    return _ICONS.get(name, "")


# =============================================================================
# Global Console Instance
# =============================================================================

# Determine if we can use emoji (Rich's emoji rendering)
_CAN_USE_EMOJI = _can_use_emoji()

# Create themed console - this is the single source of truth for output
# Disable emoji on Windows with non-UTF-8 encoding to prevent UnicodeEncodeError
console = Console(
    theme=arcadia_theme(),
    emoji=_CAN_USE_EMOJI,
    # Use 'replace' error handling to avoid crashes on encoding issues
    force_terminal=None,  # Auto-detect
)

# Global verbosity flag
_VERBOSE = False

# Global live terminal reference (set by orchestrator when enabled)
_LIVE_TERMINAL = None


def set_verbose(verbose: bool) -> None:
    """Set global verbosity level."""
    global _VERBOSE
    _VERBOSE = verbose


def is_verbose() -> bool:
    """Check if verbose mode is enabled."""
    return _VERBOSE


def set_live_terminal(terminal) -> None:
    """Set the global live terminal instance for output routing."""
    global _LIVE_TERMINAL
    _LIVE_TERMINAL = terminal


def get_live_terminal():
    """Get the global live terminal instance if active."""
    return _LIVE_TERMINAL


def is_live_terminal_active() -> bool:
    """Check if live terminal mode is active."""
    return _LIVE_TERMINAL is not None and _LIVE_TERMINAL.is_active


# =============================================================================
# Basic Message Functions
# =============================================================================

def print_success(message: str) -> None:
    """Print a success message with checkmark."""
    console.print(f"[af.ok]{icon('check')} {message}[/]")


def print_error(message: str) -> None:
    """Print an error message with X."""
    console.print(f"[af.err]{icon('cross')} {message}[/]")


def print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[af.warn]{icon('warning')} {message}[/]")


def print_info(message: str) -> None:
    """Print an info message."""
    console.print(f"[af.info]{icon('info')} {message}[/]")


def print_muted(message: str) -> None:
    """Print muted/secondary text."""
    console.print(f"[af.muted]{message}[/]")


# =============================================================================
# Headers & Sections
# =============================================================================

def print_header(title: str, style: str = "af.accent") -> None:
    """Print a prominent section header with rule lines."""
    console.print()
    console.print(Rule(f"[{style}]{title}[/]", style=style))
    console.print()


def print_subheader(title: str, style: str = "af.info") -> None:
    """Print a smaller subsection header."""
    console.print(f"\n[{style}]{icon('arrow_right')} {title}[/]")


def print_divider(style: str = "af.muted") -> None:
    """Print a horizontal divider line."""
    console.print(Rule(style=style))


# =============================================================================
# Data Display Functions
# =============================================================================

def print_key_value(
    key: str,
    value: Any,
    *,
    key_style: str = "af.key",
    value_style: str = "af.value",
    indent: int = 0,
) -> None:
    """Print a key-value pair with alignment."""
    prefix = "  " * indent
    console.print(f"{prefix}[{key_style}]{key}:[/] [{value_style}]{value}[/]")


def print_key_value_table(
    data: Dict[str, Any],
    *,
    title: Optional[str] = None,
    border_style: str = "af.border",
) -> None:
    """Print multiple key-value pairs in a clean table format."""
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="af.key")
    table.add_column("Value", style="af.value")

    for key, value in data.items():
        table.add_row(key, str(value))

    if title:
        console.print(Panel(table, title=f"[bold]{title}[/]", border_style=border_style))
    else:
        console.print(table)


def print_list(
    items: Sequence[str],
    *,
    numbered: bool = False,
    style: str = "af.text",
    bullet_style: str = "af.accent",
) -> None:
    """Print a bulleted or numbered list."""
    for i, item in enumerate(items, 1):
        if numbered:
            console.print(f"  [{bullet_style}]{i}.[/] [{style}]{item}[/]")
        else:
            console.print(f"  [{bullet_style}]{icon('bullet')}[/] [{style}]{item}[/]")


def print_json_data(
    data: Any,
    *,
    title: Optional[str] = None,
    indent: int = 2,
) -> None:
    """Print JSON data with syntax highlighting."""
    json_str = json.dumps(data, indent=indent, default=str)
    syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)

    if title:
        console.print(Panel(syntax, title=f"[bold]{title}[/]", border_style="af.border"))
    else:
        console.print(syntax)


def print_diff(
    diff_text: str,
    *,
    title: Optional[str] = None,
) -> None:
    """Print git diff with syntax highlighting."""
    syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=False)

    if title:
        console.print(Panel(syntax, title=f"[bold]{title}[/]", border_style="af.border"))
    else:
        console.print(syntax)


def print_code(
    code: str,
    *,
    language: str = "python",
    title: Optional[str] = None,
    line_numbers: bool = True,
) -> None:
    """Print code with syntax highlighting."""
    syntax = Syntax(code, language, theme="monokai", line_numbers=line_numbers)

    if title:
        console.print(Panel(syntax, title=f"[bold]{title}[/]", border_style="af.border"))
    else:
        console.print(syntax)


def print_timestamp(
    dt: Optional[datetime] = None,
    *,
    prefix: str = "",
    style: str = "af.timestamp",
) -> None:
    """Print a formatted timestamp."""
    if dt is None:
        dt = datetime.now()
    formatted = dt.strftime("%Y-%m-%d %H:%M:%S")
    if prefix:
        console.print(f"[{style}]{prefix} {formatted}[/]")
    else:
        console.print(f"[{style}]{icon('clock')} {formatted}[/]")


# =============================================================================
# Table Functions
# =============================================================================

def create_table(
    *,
    title: Optional[str] = None,
    columns: Optional[List[str]] = None,
    show_header: bool = True,
    border_style: str = "af.border",
    header_style: str = "af.table.header",
) -> Table:
    """Create a styled Rich Table with Arcadia theme."""
    table = Table(
        title=title,
        show_header=show_header,
        header_style=header_style,
        border_style=border_style,
        title_style="af.accent",
    )

    if columns:
        for col in columns:
            table.add_column(col)

    return table


def print_table(table: Table) -> None:
    """Print a Rich Table to the console."""
    console.print(table)


# =============================================================================
# Panels
# =============================================================================

def print_panel(
    content: Union[str, Text],
    *,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    border_style: str = "af.border",
    padding: tuple = (1, 2),
) -> None:
    """Print content in a styled panel."""
    console.print(Panel(
        content,
        title=f"[bold]{title}[/]" if title else None,
        subtitle=f"[af.muted]{subtitle}[/]" if subtitle else None,
        border_style=border_style,
        padding=padding,
    ))


def print_success_panel(message: str, title: str = "Success") -> None:
    """Print a success panel with green border."""
    console.print(Panel(
        f"[af.ok]{icon('check')} {message}[/]",
        title=f"[af.ok]{title}[/]",
        border_style="af.ok",
        padding=(1, 2),
    ))


def print_error_panel(message: str, title: str = "Error") -> None:
    """Print an error panel with red border."""
    console.print(Panel(
        f"[af.err]{icon('cross')} {message}[/]",
        title=f"[af.err]{title}[/]",
        border_style="af.err",
        padding=(1, 2),
    ))


def print_warning_panel(message: str, title: str = "Warning") -> None:
    """Print a warning panel with yellow border."""
    console.print(Panel(
        f"[af.warn]{icon('warning')} {message}[/]",
        title=f"[af.warn]{title}[/]",
        border_style="af.warn",
        padding=(1, 2),
    ))


def print_info_panel(message: str, title: str = "Info") -> None:
    """Print an info panel with cyan border."""
    console.print(Panel(
        f"[af.info]{icon('info')} {message}[/]",
        title=f"[af.info]{title}[/]",
        border_style="af.info",
        padding=(1, 2),
    ))


# =============================================================================
# Progress & Spinners
# =============================================================================

@contextmanager
def spinner(message: str, *, style: str = "af.accent") -> Iterator[Status]:
    """
    Context manager for showing a spinner during long operations.

    Usage:
        with spinner("Loading data..."):
            load_data()
    """
    with console.status(f"[{style}]{message}[/]", spinner="dots") as status:
        yield status


def create_progress(
    *,
    transient: bool = False,
    show_time: bool = True,
) -> Progress:
    """Create a styled progress bar for tracking multiple tasks."""
    columns = [
        SpinnerColumn(),
        TextColumn("[af.accent]{task.description}[/]"),
        BarColumn(bar_width=30, style="af.muted", complete_style="af.ok"),
        TaskProgressColumn(),
    ]

    if show_time:
        columns.extend([
            TimeElapsedColumn(),
            TextColumn("[af.muted]/[/]"),
            TimeRemainingColumn(),
        ])

    return Progress(*columns, console=console, transient=transient)


def print_progress_bar(passing: int, total: int, title: str = "Progress") -> None:
    """Print a simple inline progress bar."""
    if total == 0:
        console.print(f"[af.muted]{title}: No items yet[/]")
        return

    percentage = (passing / total) * 100

    # Choose color based on progress
    if percentage >= 100:
        color = "af.ok"
    elif percentage >= 50:
        color = "af.warn"
    else:
        color = "af.info"

    # Create progress bar
    bar_width = 30
    filled = int(bar_width * passing / total)
    empty = bar_width - filled
    bar_char = icon("bar_filled")
    empty_char = icon("bar_empty")
    bar = f"[{color}]{bar_char * filled}[/][af.muted]{empty_char * empty}[/]"

    console.print(f"{title}: {bar} [af.number]{passing}[/][af.muted]/{total}[/] ({percentage:.1f}%)")


# =============================================================================
# Interactive Prompts
# =============================================================================

def confirm(
    message: str,
    *,
    default: bool = False,
) -> bool:
    """
    Ask for yes/no confirmation.

    Returns True for yes, False for no.
    """
    return Confirm.ask(f"[af.accent]{message}[/]", default=default, console=console)


def prompt(
    message: str,
    *,
    default: Optional[str] = None,
    password: bool = False,
) -> str:
    """
    Prompt for text input.

    Returns the user's input string.
    """
    return Prompt.ask(
        f"[af.accent]{message}[/]",
        default=default,
        password=password,
        console=console,
    )


def prompt_int(
    message: str,
    *,
    default: Optional[int] = None,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
) -> int:
    """Prompt for integer input with optional range validation."""
    while True:
        value = IntPrompt.ask(
            f"[af.accent]{message}[/]",
            default=default,
            console=console,
        )

        if min_value is not None and value < min_value:
            print_error(f"Value must be at least {min_value}")
            continue
        if max_value is not None and value > max_value:
            print_error(f"Value must be at most {max_value}")
            continue

        return value


def select(
    message: str,
    choices: List[str],
    *,
    default: Optional[str] = None,
) -> str:
    """
    Present a selection menu and return the chosen option.

    Usage:
        choice = select("Choose format:", ["JSON", "CSV", "YAML"])
    """
    console.print(f"\n[af.accent]{message}[/]")

    for i, choice in enumerate(choices, 1):
        marker = "[af.ok]*[/]" if choice == default else " "
        console.print(f"  {marker} [af.number]{i}.[/] {choice}")

    console.print()

    while True:
        selection = prompt(f"Enter choice (1-{len(choices)})")
        try:
            idx = int(selection) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            # Check if they typed the choice name
            if selection in choices:
                return selection

        print_error(f"Please enter a number between 1 and {len(choices)}")


def multi_select(
    message: str,
    choices: List[str],
    *,
    defaults: Optional[List[str]] = None,
) -> List[str]:
    """
    Present a multi-selection menu and return chosen options.

    Usage:
        selected = multi_select("Select features:", ["Auth", "API", "UI"])
    """
    defaults = defaults or []
    selected = set(defaults)

    console.print(f"\n[af.accent]{message}[/]")
    console.print("[af.muted]Enter numbers to toggle, 'done' to finish[/]")

    while True:
        console.print()
        for i, choice in enumerate(choices, 1):
            marker = f"[af.ok]{icon('check')}[/]" if choice in selected else " "
            console.print(f"  {marker} [af.number]{i}.[/] {choice}")

        console.print()
        selection = prompt("Toggle (or 'done')").strip().lower()

        if selection in ('done', 'd', ''):
            break

        try:
            idx = int(selection) - 1
            if 0 <= idx < len(choices):
                choice = choices[idx]
                if choice in selected:
                    selected.remove(choice)
                else:
                    selected.add(choice)
        except ValueError:
            print_error("Please enter a number or 'done'")

    return [c for c in choices if c in selected]


# =============================================================================
# Banner & Branding
# =============================================================================

ARCADIA_FORGE_BANNER = r"""
      _                        _ _       ______
     / \   _ __ ___ __ _   ___| (_) __ _|  ____|__  _ __ __ _  ___
    / _ \ | '__/ __/ _` | / _ | | |/ _` | |__ / _ \| '__/ _` |/ _ \
   / ___ \| | | (_| (_| || (_)| | | (_| |  __| (_) | | | (_| |  __/
  /_/   \_\_|  \___\__,_| \___|_|_|\__,_|_|   \___/|_|  \__, |\___|
                                                        |___/
""".rstrip("\n")


def print_banner(
    *,
    version: Optional[str] = None,
    subtitle: str = "Autonomous Coding Framework",
    quiet: bool = False,
) -> Console:
    """
    Print the Arcadia Forge banner.

    Returns the console instance for continued use.
    """
    if quiet:
        return console

    banner_text = Text(ARCADIA_FORGE_BANNER, style="af.banner")

    footer = subtitle.strip()
    if version:
        footer = f"{footer}  {icon('bullet')}  {version.strip()}"

    footer_text = Text(footer, style="af.subtitle")

    console.print(Panel(
        Text.assemble(banner_text, "\n", footer_text),
        border_style="af.border",
        padding=(1, 2),
    ))

    return console


def print_phase(label: str, message: str, *, style: str = "af.phase.exec") -> None:
    """
    Print a phase/role label with message.

    Usage:
        print_phase("PLANNER", "Analyzing intent...", style="af.phase.plan")
    """
    console.print(f"[{style}]{label:>10}[/] [af.text]{message}[/]")


# =============================================================================
# Session & Status Displays
# =============================================================================

def print_session_header(session_num: int, session_type: str) -> None:
    """Print a formatted session header."""
    if session_type == "INITIALIZER":
        style = "af.phase.plan"
        session_icon = icon("rocket")
    elif session_type == "UPDATE":
        style = "af.warn"
        session_icon = icon("pencil")
    else:
        style = "af.phase.exec"
        session_icon = icon("computer")

    title = f"{session_icon} SESSION {session_num}: {session_type}"
    console.print()
    console.print(Rule(title, style=style))
    console.print()


def print_config(
    project_dir: Path,
    model: str,
    max_iterations: Optional[int],
    extra_info: Optional[Dict[str, Any]] = None,
) -> None:
    """Print configuration summary."""
    data = {
        "Project": str(project_dir),
        "Model": model,
        "Max iterations": str(max_iterations) if max_iterations else "Unlimited",
    }

    if extra_info:
        data.update({k: str(v) for k, v in extra_info.items()})

    print_key_value_table(data, title="Configuration")


def print_status_complete() -> None:
    """Print project complete status."""
    console.print()
    print_success_panel(
        f"{icon('party')} PROJECT COMPLETE!\n\nAll tests are passing. The project is ready.",
        title="Complete"
    )


def print_status_intervention(reason: str) -> None:
    """Print intervention required status."""
    console.print()
    print_warning_panel(
        f"HUMAN INTERVENTION REQUIRED\n\n"
        f"Reason: {reason}\n\n"
        "Please review the output above and address the issue.\n"
        "To resume, run the script again after fixing the problem.",
        title="Intervention Required"
    )


def print_status_cyclic(reason: str) -> None:
    """Print cyclic behavior detected status."""
    console.print()
    print_warning_panel(
        f"CYCLIC BEHAVIOR DETECTED\n\n"
        f"Reason: {reason}\n\n"
        "The agent appears to be stuck in a loop.\n\n"
        "Suggestions:\n"
        "  1. Review claude-progress.json for details\n"
        "  2. Check error patterns in the output above\n"
        "  3. Consider simplifying the requirements\n"
        "  4. Check if a dependency is missing\n\n"
        "To continue anyway, run the script again.",
        title="Cyclic Behavior"
    )


def print_status_no_progress(reason: str) -> None:
    """Print no progress status."""
    console.print()
    print_warning_panel(
        f"NO TEST PROGRESS\n\n"
        f"Reason: {reason}\n\n"
        "The passing test count hasn't increased.\n"
        "This may indicate the agent is stuck.\n\n"
        "To continue anyway, run the script again.",
        title="No Progress"
    )


def print_status_error(consecutive_count: int) -> None:
    """Print consecutive error status."""
    console.print()
    print_error_panel(
        f"TOO MANY CONSECUTIVE ERRORS\n\n"
        f"The agent has failed {consecutive_count} consecutive sessions.\n\n"
        "Please review the error messages above.\n"
        "To retry, run the script again.",
        title="Error"
    )


def print_auto_continue(delay: int) -> None:
    """Print auto-continue message."""
    console.print(f"\n[af.muted]Auto-continuing in {delay}s...[/]")


def print_session_divider() -> None:
    """Print a divider between sessions."""
    console.print()
    print_divider()
    console.print()


def print_final_summary(project_dir: Path, passing: int, total: int) -> None:
    """Print final session summary with platform-specific instructions."""
    console.print()
    console.print(Rule("[bold]SESSION COMPLETE[/]", style="af.info"))
    console.print()
    console.print(f"[af.muted]Project:[/] [af.path]{project_dir.resolve()}[/]")
    print_progress_bar(passing, total, "Final progress")

    # Get platform-specific run instructions
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        run_instructions = (
            f"[bold]To run the application:[/]\n\n"
            f"  cd {project_dir.resolve()}\n\n"
            f"  [af.info]Command Prompt:[/]\n"
            f"  init.bat\n\n"
            f"  [af.info]PowerShell:[/]\n"
            f"  powershell -ExecutionPolicy Bypass -File .\\init.ps1\n\n"
            f"[af.muted]Or manually: npm install && npm run dev[/]"
        )
    else:
        run_instructions = (
            f"[bold]To run the application:[/]\n\n"
            f"  cd {project_dir.resolve()}\n"
            f"  chmod +x init.sh\n"
            f"  ./init.sh\n\n"
            f"[af.muted]Or manually: npm install && npm run dev[/]"
        )

    console.print()
    print_panel(
        run_instructions,
        title="Next Steps",
        border_style="af.info",
    )


# =============================================================================
# Tool Output Tracker
# =============================================================================

class ToolOutputTracker:
    """
    Tracks pending tool calls and prints them with results on the same line.

    This solves the async problem where tool calls and results arrive separately,
    causing misaligned output like:
        ⚡ Read
        ⚡ Write
        ✓ Done
        ✓ Done

    Instead, we buffer tool calls and print them when results arrive:
        ⚡ Read (file.txt) ✓
        ⚡ Write (output.txt) ✓
    """

    def __init__(self):
        self._pending: List[tuple[str, str]] = []  # (tool_name, summary)

    def _extract_summary(self, tool_name: str, tool_input: str) -> str:
        """Extract a short summary from tool input."""
        summary = ""
        try:
            if tool_input.strip().startswith("{"):
                args = json.loads(tool_input)
                # Common patterns
                if "file_path" in args:
                    summary = Path(args["file_path"]).name  # Just filename
                elif "command" in args:
                    cmd = args["command"].split('\n')[0]
                    summary = cmd[:40] + "..." if len(cmd) > 40 else cmd
                elif "path" in args:
                    summary = Path(args["path"]).name
                elif "pattern" in args:
                    summary = args["pattern"]
                elif "query" in args:
                    summary = args["query"][:30]
                elif "url" in args:
                    summary = args["url"][:40]
                elif "index" in args:
                    summary = f"#{args['index']}"
                elif "count" in args:
                    summary = f"n={args['count']}"
                elif "pid" in args:
                    summary = f"pid={args['pid']}"
                elif "port" in args:
                    summary = f"port={args['port']}"
        except Exception:
            pass

        # If extraction failed but input is short, use it
        if not summary and tool_input and len(tool_input) < 30:
            summary = tool_input.replace('\n', ' ').strip()

        return summary

    def _format_tool_name(self, tool_name: str) -> str:
        """Format tool name, shortening MCP tool names."""
        # mcp__features__feature_stats -> feature_stats
        if tool_name.startswith("mcp__"):
            parts = tool_name.split("__")
            if len(parts) >= 3:
                return parts[-1]
        return tool_name

    def add_tool_call(self, tool_name: str, tool_input: str) -> None:
        """Record a pending tool call."""
        summary = self._extract_summary(tool_name, tool_input)
        display_name = self._format_tool_name(tool_name)
        self._pending.append((display_name, summary))

    def complete_tool(self, result_type: str, content: str = "") -> None:
        """Complete the oldest pending tool call and print it with result."""
        if not self._pending:
            # No pending tool - just print result (shouldn't happen normally)
            self._print_orphan_result(result_type, content)
            return

        tool_name, summary = self._pending.pop(0)
        self._print_tool_with_result(tool_name, summary, result_type, content)

    def _print_tool_with_result(
        self,
        tool_name: str,
        summary: str,
        result_type: str,
        content: str
    ) -> None:
        """Print a tool call with its result on the same line."""
        # Route through live terminal if active
        if is_live_terminal_active():
            _LIVE_TERMINAL.output_tool(tool_name, summary, result_type)
            return

        # Sanitize summary and content for Windows encoding
        summary = _sanitize_text(summary) if summary else ""
        content = _sanitize_text(content) if content else ""

        # Build the tool part
        tool_part = f"[af.accent]{icon('lightning')} {tool_name}[/]"
        if summary:
            tool_part += f" [af.muted]({summary})[/]"

        # Build the result part
        if result_type == "done":
            result_part = f"[af.ok]{icon('check')}[/]"
        elif result_type == "blocked":
            result_part = f"[af.err]{icon('blocked')} BLOCKED[/]"
            if content and _VERBOSE:
                result_part += f" [af.muted]{content[:60]}...[/]"
        elif result_type == "error":
            result_part = f"[af.err]{icon('cross')} Error[/]"
            if content and _VERBOSE:
                result_part += f" [af.muted]{content[:60]}...[/]"
        else:
            result_part = ""

        console.print(f"  {tool_part} {result_part}")

    def _print_orphan_result(self, result_type: str, content: str) -> None:
        """Print a result without a matching tool call."""
        if result_type == "done":
            console.print(f"  [af.ok]{icon('check')} Done[/]")
        elif result_type == "blocked":
            console.print(f"  [af.err]{icon('blocked')} BLOCKED[/]")
        elif result_type == "error":
            console.print(f"  [af.err]{icon('cross')} Error[/]")

    def flush_pending(self) -> None:
        """Print any remaining pending tool calls (e.g., at end of session)."""
        while self._pending:
            tool_name, summary = self._pending.pop(0)
            tool_part = f"[af.accent]{icon('lightning')} {tool_name}[/]"
            if summary:
                tool_part += f" [af.muted]({summary})[/]"
            console.print(f"  {tool_part} [af.muted]...[/]")

    def has_pending(self) -> bool:
        """Check if there are pending tool calls."""
        return len(self._pending) > 0

    def clear(self) -> None:
        """Clear all pending tool calls."""
        self._pending.clear()


# Global tool tracker instance
_tool_tracker = ToolOutputTracker()


def get_tool_tracker() -> ToolOutputTracker:
    """Get the global tool output tracker."""
    return _tool_tracker


def reset_tool_tracker() -> None:
    """Reset the tool tracker (e.g., at start of new session)."""
    _tool_tracker.clear()


def print_tool_use(tool_name: str, tool_input: str, max_length: int = 200) -> None:
    """
    Record a tool call for later printing with its result.

    In verbose mode, prints immediately with details.
    In normal mode, buffers the call until result arrives.
    """
    if _VERBOSE:
        # Detailed output for verbose mode - print immediately
        if len(tool_input) > max_length:
            display_input = tool_input[:max_length] + "..."
        else:
            display_input = tool_input

        console.print(f"  [af.accent]{icon('lightning')} {tool_name}[/]")
        if display_input:
            for line in display_input.split('\n')[:3]:
                console.print(f"     [af.muted]{line}[/]")
    else:
        # Buffer the tool call - will print when result arrives
        _tool_tracker.add_tool_call(tool_name, tool_input)


def print_tool_result(result_type: str, content: str = "") -> None:
    """
    Print tool result, paired with buffered tool call if available.

    In verbose mode, prints result on its own line.
    In normal mode, prints tool call + result together.
    """
    if _VERBOSE:
        # Detailed result on its own line
        if result_type == "done":
            console.print(f"     [af.ok]{icon('check')} Done[/]")
        elif result_type == "blocked":
            console.print(f"     [af.err]{icon('blocked')} BLOCKED[/] [af.muted]{content[:100]}[/]")
        elif result_type == "error":
            console.print(f"     [af.err]{icon('cross')} Error[/] [af.muted]{content[:200]}[/]")
    else:
        # Print tool + result together
        _tool_tracker.complete_tool(result_type, content)


def print_agent_text(text: str) -> None:
    """Print agent response text."""
    if not _VERBOSE:
        return
    # Sanitize to handle emoji from LLM responses on Windows
    safe_text = _sanitize_text(text)
    console.print(safe_text, end="", highlight=False)


def print_update_mode_info(num_features: Optional[int] = None) -> None:
    """Print update mode information."""
    b = icon("bullet")
    content = (
        "[bold]Adding new requirements to existing project[/]\n\n"
        f"{b} New features will be added to the database\n"
        f"{b} Existing features will NOT be modified\n"
    )
    if num_features:
        content += f"{b} Target: [af.number]{num_features}[/] new features"

    print_panel(content, title="UPDATE MODE", border_style="af.warn")


def print_initializer_info() -> None:
    """Print initializer mode information with platform-specific details."""
    info = get_platform_info()
    b = icon("bullet")

    if info.os_type == OSType.WINDOWS:
        init_script_info = f"{b} Creating init.bat, init.ps1 and project structure"
    else:
        init_script_info = f"{b} Creating init.sh and project structure"

    print_panel(
        f"[bold]First session - Initializing project[/]\n\n"
        f"{b} Reading app_spec.txt\n"
        f"{b} Generating 200+ test cases (stored in database)\n"
        f"{init_script_info}\n\n"
        f"[af.muted]This may take 10-20+ minutes. Watch for tool output below.[/]",
        title="INITIALIZER MODE",
        border_style="af.phase.plan",
    )


def print_platform_info() -> None:
    """Print current platform information."""
    info = get_platform_info()

    platform_details = [
        f"[af.muted]Platform:[/] {info.os_type.value.title()}",
        f"[af.muted]Shell:[/] {info.shell_name}",
        f"[af.muted]Init script:[/] {info.init_script_name}",
    ]

    console.print("  ".join(platform_details))


# =============================================================================
# Logging Integration
# =============================================================================

def setup_rich_logging(level: int = logging.INFO) -> None:
    """
    Configure Python logging to use Rich for beautiful log output.

    Usage:
        setup_rich_logging()
        logging.info("This will be pretty!")
    """
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(
            console=console,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
        )],
    )


# =============================================================================
# Live Displays
# =============================================================================

@contextmanager
def live_display(renderable: Any, *, refresh_per_second: int = 4) -> Iterator[Live]:
    """
    Context manager for live-updating displays.

    Usage:
        table = create_table(columns=["Status", "Count"])
        with live_display(table) as live:
            for i in range(10):
                table.add_row("Processing", str(i))
                live.update(table)
    """
    with Live(renderable, console=console, refresh_per_second=refresh_per_second) as live:
        yield live
