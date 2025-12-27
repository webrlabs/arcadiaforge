#!/usr/bin/env python3
"""
Demo: Live Terminal with Persistent Input
==========================================

This demonstrates the live terminal interface where users can
provide feedback while the agent runs.

Uses prompt_toolkit for proper input handling - your typed input
appears at the bottom and output scrolls above it.

Usage:
    python examples/demo_live_terminal.py

Try typing commands like:
    /help     - Show available commands
    /stop     - Request stop (simulated)
    /pause    - Pause for 3 seconds
    /hint x   - Provide a hint
    hello     - Send general feedback
"""

import asyncio
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from prompt_toolkit.patch_stdout import patch_stdout

from arcadiaforge.live_terminal import LiveTerminal, UserFeedback


async def simulate_agent_work(terminal: LiveTerminal) -> None:
    """Simulate agent doing work and processing feedback."""

    # Simulated tool operations: (tool_name, summary, result)
    operations = [
        ("Read", "app.py", "done"),
        ("Glob", "*.tsx", "done"),
        ("mcp__features__feature_stats", "{}", "done"),
        ("Bash", "npm test", "done"),
        ("Write", "output.py", "error"),
        ("mcp__progress__progress_summary", "{}", "done"),
        ("Edit", "main.py", "done"),
        ("Grep", "TODO", "done"),
    ]

    terminal.output_info("Starting simulated agent work...")
    terminal.output_muted("─" * 40)

    for i, (tool, summary, result) in enumerate(operations):
        # Check for feedback before each operation
        feedback = terminal.get_feedback()
        if feedback:
            terminal.output_warning(f">>> Feedback ({feedback.feedback_type}): {feedback.message}")

            if feedback.feedback_type == "stop":
                terminal.output_error(">>> Stop requested, halting simulation")
                return
            elif feedback.feedback_type == "pause":
                terminal.output_info(">>> Pausing for 3 seconds...")
                await asyncio.sleep(3)
                terminal.output_success(">>> Resuming...")

        # Show tool execution using the typed output method
        terminal.output_tool(tool, summary, result)

        # Simulate work time
        await asyncio.sleep(0.7)

    terminal.output_muted("─" * 40)
    terminal.output_success("Simulation complete!")


async def main():
    """Main entry point for demo."""
    print("\n" + "=" * 55)
    print("         Live Terminal Demo (prompt_toolkit)")
    print("=" * 55)
    print()
    print("This demo uses prompt_toolkit for proper input handling.")
    print("Output scrolls above while input stays at the bottom.")
    print()
    print("Try these commands while the agent runs:")
    print("  /help     - Show all commands")
    print("  /stop     - Stop the simulation")
    print("  /pause    - Pause for 3 seconds")
    print("  /hint x   - Provide a hint")
    print("  hello     - Send general feedback")
    print()
    print("Press Enter to start...")
    input()

    # Create terminal
    terminal = LiveTerminal(
        max_output_lines=50,
        prompt_text="Feedback",
        show_help_on_start=True,
    )

    # Run with patch_stdout to keep input at bottom
    async with terminal:
        with patch_stdout():
            await simulate_agent_work(terminal)

    print("\n" + "=" * 55)
    print("Demo finished!")
    print("=" * 55)

    # Show any remaining feedback
    remaining = terminal.get_all_feedback()
    if remaining:
        print(f"\nUnprocessed feedback ({len(remaining)} items):")
        for fb in remaining:
            print(f"  - [{fb.feedback_type}] {fb.message}")


if __name__ == "__main__":
    asyncio.run(main())
