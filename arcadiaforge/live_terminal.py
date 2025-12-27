"""
Live Terminal Interface
=======================

Provides a split-screen terminal with scrolling output and an integrated
input field using prompt_toolkit for proper cursor positioning.

Architecture:
    ┌─────────────────────────────────────────┐
    │  Agent Output (scrolling)               │
    │  ⚡ Read (file.txt) ✓                   │
    │  ⚡ Write (output.py) ✓                 │
    │  ...                                    │
    ├─────────────────────────────────────────┤
    │  Feedback> your_input_here_             │
    └─────────────────────────────────────────┘

Uses prompt_toolkit for:
    - Proper input field positioning
    - Async-compatible input handling
    - Output that doesn't interfere with input
"""

from __future__ import annotations

import asyncio
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Deque, List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app_or_none
from prompt_toolkit.formatted_text import HTML, FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import print_formatted_text
from prompt_toolkit.styles import Style


# =============================================================================
# Styles
# =============================================================================

TERMINAL_STYLE = Style.from_dict({
    # Output colors
    'output': '#E6E6E6',
    'tool': '#F59E0B bold',
    'tool-name': '#F59E0B',
    'tool-arg': '#9AA4B2',
    'success': '#22C55E bold',
    'error': '#EF4444 bold',
    'warning': '#FBBF24 bold',
    'info': '#22D3EE',
    'muted': '#9AA4B2',

    # Input prompt
    'prompt': '#22D3EE bold',
    'input': '#E6E6E6',

    # Feedback indicators
    'feedback-type': '#FBBF24 bold',
    'feedback-msg': '#E6E6E6',

    # Help
    'help-cmd': '#22D3EE bold',
    'help-desc': '#9AA4B2',
})


def _escape_html(text: str) -> str:
    """Escape HTML special characters in text."""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def _can_use_unicode_terminal() -> bool:
    """Check if terminal can handle Unicode characters."""
    import os
    if os.name == 'nt':
        encoding = (sys.stdout.encoding or '').lower()
        return 'utf-8' in encoding or 'utf8' in encoding
    return True


# Windows-safe symbols
_USE_UNICODE_TERM = _can_use_unicode_terminal()
SYMBOL_CHECK = '✓' if _USE_UNICODE_TERM else '[OK]'
SYMBOL_CROSS = '✗' if _USE_UNICODE_TERM else '[X]'
SYMBOL_BOLT = '⚡' if _USE_UNICODE_TERM else '->'


# =============================================================================
# User Feedback Data
# =============================================================================

@dataclass
class UserFeedback:
    """Represents feedback submitted by the user during agent execution."""
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    feedback_type: str = "general"  # general, stop, redirect, hint, pause, skip

    def __str__(self) -> str:
        return f"[{self.timestamp.strftime('%H:%M:%S')}] {self.message}"


# =============================================================================
# Feedback Processor
# =============================================================================

class FeedbackProcessor:
    """Processes user feedback and categorizes it."""

    COMMANDS = {
        "/stop": "stop",
        "/pause": "pause",
        "/skip": "skip",
        "/hint": "hint",
        "/redirect": "redirect",
        "/help": "help",
    }

    def process(self, message: str) -> UserFeedback:
        """Process a raw message into structured feedback."""
        message = message.strip()
        if not message:
            return UserFeedback(message="", feedback_type="empty")

        for cmd, feedback_type in self.COMMANDS.items():
            if message.lower().startswith(cmd):
                remainder = message[len(cmd):].strip()
                return UserFeedback(
                    message=remainder if remainder else cmd,
                    feedback_type=feedback_type,
                )

        return UserFeedback(message=message, feedback_type="general")


# =============================================================================
# Live Terminal Display
# =============================================================================

class LiveTerminal:
    """
    Manages a terminal with scrolling output and integrated input.

    Uses prompt_toolkit's patch_stdout to ensure output appears above
    the input prompt, keeping the input field at the bottom.
    """

    def __init__(
        self,
        max_output_lines: int = 100,
        prompt_text: str = "Feedback",
        show_help_on_start: bool = True,
    ):
        self.max_output_lines = max_output_lines
        self.prompt_text = prompt_text
        self.show_help_on_start = show_help_on_start

        # Output buffer
        self._output_buffer: Deque[str] = deque(maxlen=max_output_lines)

        # Feedback queue (thread-safe deque)
        self._feedback_queue: Deque[UserFeedback] = deque()

        # Components
        self._processor = FeedbackProcessor()
        self._session: Optional[PromptSession] = None

        # State
        self._active = False
        self._input_task: Optional[asyncio.Task] = None

        # Callbacks
        self._on_feedback: Optional[Callable[[UserFeedback], None]] = None

    def set_feedback_callback(self, callback: Callable[[UserFeedback], None]) -> None:
        """Set callback to be called when feedback is received."""
        self._on_feedback = callback

    def _format_output(self, text: str) -> FormattedText:
        """Convert markup text to prompt_toolkit FormattedText."""
        # Simple conversion of common patterns
        # This is a basic implementation - could be enhanced
        return FormattedText([('class:output', text)])

    def output(self, text: str, style: str = "output") -> None:
        """
        Add a line to the output.

        The text appears above the input prompt.
        """
        self._output_buffer.append(text)

        if self._active:
            # Print above the input prompt using patch_stdout
            styled_text = HTML(f'<{style}>{text}</{style}>')
            print_formatted_text(styled_text, style=TERMINAL_STYLE)

    def output_tool(self, tool_name: str, summary: str, result: str) -> None:
        """Output a formatted tool call line."""
        # Shorten MCP tool names
        if tool_name.startswith("mcp__"):
            parts = tool_name.split("__")
            tool_name = parts[-1] if len(parts) >= 3 else tool_name

        # Escape user-provided text
        tool_name = _escape_html(tool_name)
        summary = _escape_html(summary)

        # Result indicator (use safe symbols for Windows)
        if result == "done":
            indicator = f'<success>{SYMBOL_CHECK}</success>'
        elif result == "error":
            indicator = f'<error>{SYMBOL_CROSS}</error>'
        elif result == "blocked":
            indicator = '<error>[BLOCKED]</error>'
        else:
            indicator = '<warning>...</warning>'

        line = f'  <tool>{SYMBOL_BOLT}</tool> <tool-name>{tool_name}</tool-name> <muted>({summary})</muted> {indicator}'

        self._output_buffer.append(f"  {SYMBOL_BOLT} {tool_name} ({summary}) {result}")
        if self._active:
            print_formatted_text(HTML(line), style=TERMINAL_STYLE)

    def output_success(self, text: str) -> None:
        """Output a success message."""
        safe_text = _escape_html(text)
        self._output_buffer.append(f"{SYMBOL_CHECK} {text}")
        if self._active:
            print_formatted_text(HTML(f'<success>{SYMBOL_CHECK} {safe_text}</success>'), style=TERMINAL_STYLE)

    def output_error(self, text: str) -> None:
        """Output an error message."""
        safe_text = _escape_html(text)
        self._output_buffer.append(f"{SYMBOL_CROSS} {text}")
        if self._active:
            print_formatted_text(HTML(f'<error>{SYMBOL_CROSS} {safe_text}</error>'), style=TERMINAL_STYLE)

    def output_info(self, text: str) -> None:
        """Output an info message."""
        safe_text = _escape_html(text)
        symbol = 'i' if not _USE_UNICODE_TERM else 'ℹ'
        self._output_buffer.append(f"{symbol} {text}")
        if self._active:
            print_formatted_text(HTML(f'<info>{symbol} {safe_text}</info>'), style=TERMINAL_STYLE)

    def output_warning(self, text: str) -> None:
        """Output a warning message."""
        safe_text = _escape_html(text)
        symbol = '[!]' if not _USE_UNICODE_TERM else '⚠'
        self._output_buffer.append(f"{symbol} {text}")
        if self._active:
            print_formatted_text(HTML(f'<warning>{symbol} {safe_text}</warning>'), style=TERMINAL_STYLE)

    def output_muted(self, text: str) -> None:
        """Output muted/dim text."""
        self._output_buffer.append(text)
        if self._active:
            # Use FormattedText to avoid XML parsing issues with special chars
            print_formatted_text(FormattedText([('class:muted', text)]), style=TERMINAL_STYLE)

    def output_feedback_received(self, feedback: UserFeedback) -> None:
        """Output confirmation that feedback was received."""
        safe_msg = _escape_html(feedback.message)
        safe_type = _escape_html(feedback.feedback_type)
        self._output_buffer.append(f"{SYMBOL_CHECK} [{feedback.feedback_type}] {feedback.message}")
        if self._active:
            line = f'<success>{SYMBOL_CHECK}</success> <feedback-type>[{safe_type}]</feedback-type> <feedback-msg>{safe_msg}</feedback-msg>'
            print_formatted_text(HTML(line), style=TERMINAL_STYLE)

    def _show_help(self) -> None:
        """Show help information."""
        # Use safe border character for Windows
        border = '═' if _USE_UNICODE_TERM else '='
        help_lines = [
            "",
            f"<info>{border*3} Feedback Commands {border*3}</info>",
            "",
            "<help-cmd>/stop</help-cmd>        <help-desc>- Request agent to stop</help-desc>",
            "<help-cmd>/pause</help-cmd>       <help-desc>- Pause for review</help-desc>",
            "<help-cmd>/skip</help-cmd>        <help-desc>- Skip current feature</help-desc>",
            "<help-cmd>/hint</help-cmd> <msg>  <help-desc>- Provide hint to agent</help-desc>",
            "<help-cmd>/redirect</help-cmd> <msg> <help-desc>- Change direction</help-desc>",
            "<help-cmd>/help</help-cmd>        <help-desc>- Show this help</help-desc>",
            "",
            "<muted>Or type any message for general feedback</muted>",
            "",
        ]
        for line in help_lines:
            self._output_buffer.append(line)
            if self._active:
                print_formatted_text(HTML(line), style=TERMINAL_STYLE)

    def get_feedback(self) -> Optional[UserFeedback]:
        """Get the next feedback item if available (non-blocking)."""
        try:
            return self._feedback_queue.popleft()
        except IndexError:
            return None

    def get_all_feedback(self) -> List[UserFeedback]:
        """Get all pending feedback items."""
        items = list(self._feedback_queue)
        self._feedback_queue.clear()
        return items

    def has_feedback(self) -> bool:
        """Check if there's pending feedback."""
        return len(self._feedback_queue) > 0

    async def _input_loop(self) -> None:
        """Async loop that reads input from the user."""
        while self._active:
            try:
                # Get input asynchronously
                text = await self._session.prompt_async(
                    HTML(f'<prompt>{self.prompt_text}></prompt> '),
                    style=TERMINAL_STYLE,
                )

                if text is None:
                    continue

                # Process the input
                feedback = self._processor.process(text)

                # Handle empty input
                if feedback.feedback_type == "empty":
                    continue

                # Handle /help specially
                if feedback.feedback_type == "help":
                    self._show_help()
                    continue

                # Add to queue
                self._feedback_queue.append(feedback)

                # Show confirmation
                self.output_feedback_received(feedback)

                # Call callback if set
                if self._on_feedback:
                    self._on_feedback(feedback)

            except EOFError:
                # Ctrl+D pressed
                break
            except KeyboardInterrupt:
                # Ctrl+C pressed
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log but continue
                self.output_error(f"Input error: {e}")

    async def __aenter__(self) -> "LiveTerminal":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()

    async def start(self) -> None:
        """Start the live terminal."""
        if self._active:
            return

        self._active = True

        # Create prompt session
        self._session = PromptSession()

        # Show initial help if requested
        if self.show_help_on_start:
            print_formatted_text(HTML("<info>Type /help for commands. Enter feedback anytime.</info>"), style=TERMINAL_STYLE)
            # Use plain text for the divider to avoid XML parsing issues
            print_formatted_text(FormattedText([('class:muted', "─" * 50)]), style=TERMINAL_STYLE)

        # Start input loop in background
        self._input_task = asyncio.create_task(self._input_loop())

    async def stop(self) -> None:
        """Stop the live terminal."""
        if not self._active:
            return

        self._active = False

        # Cancel input task
        if self._input_task:
            self._input_task.cancel()
            try:
                await self._input_task
            except asyncio.CancelledError:
                pass
            self._input_task = None

        self._session = None

    @property
    def is_active(self) -> bool:
        """Check if the terminal is active."""
        return self._active

    async def run_with_agent(self, agent_coroutine: Any) -> Any:
        """
        Run an agent coroutine while accepting user input.

        Uses patch_stdout to ensure agent output appears above the input.
        """
        with patch_stdout():
            result = await agent_coroutine
        return result


# =============================================================================
# Global Instance Management
# =============================================================================

_live_terminal: Optional[LiveTerminal] = None


def get_live_terminal() -> Optional[LiveTerminal]:
    """Get the global LiveTerminal instance if active."""
    return _live_terminal


def create_live_terminal(**kwargs) -> LiveTerminal:
    """Create and set the global LiveTerminal instance."""
    global _live_terminal
    _live_terminal = LiveTerminal(**kwargs)
    return _live_terminal


def stop_live_terminal() -> None:
    """Stop and clear the global LiveTerminal instance."""
    global _live_terminal
    if _live_terminal:
        # Note: This is sync, caller should use await terminal.stop() if async
        _live_terminal._active = False
        _live_terminal = None
