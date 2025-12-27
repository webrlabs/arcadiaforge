#!/usr/bin/env python3
"""
Human Response CLI for Autonomous Coding Framework
===================================================

A command-line tool for humans to respond to agent injection points.

Usage:
    # List pending injection points
    python respond.py --list

    # Respond to an injection point
    python respond.py --point-id INJ-1-5 --response "Option A"

    # Respond interactively
    python respond.py --point-id INJ-1-5

    # Accept the agent's recommendation
    python respond.py --point-id INJ-1-5 --accept

    # Cancel an injection point
    python respond.py --point-id INJ-1-5 --cancel

    # Show details of an injection point
    python respond.py --show INJ-1-5

    # Show recent history
    python respond.py --history
"""

import argparse
import json
import sys
from pathlib import Path

from arcadiaforge.human_interface import HumanInterface, InjectionPoint
from arcadiaforge.output import (
    console,
    print_banner,
    print_header,
    print_subheader,
    print_divider,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_muted,
    print_panel,
    print_key_value,
    print_key_value_table,
    create_table,
    print_table,
    select,
    prompt,
    icon,
)


def get_project_dir() -> Path:
    """Get the project directory (current working directory)."""
    return Path.cwd()


def list_pending(interface: HumanInterface) -> None:
    """List all pending injection points."""
    pending = interface.get_pending()

    if not pending:
        print_info("No pending injection points.")
        return

    print_header(f"Pending Injection Points ({len(pending)})")

    for inj in pending:
        # Severity styling
        if inj.severity >= 4:
            severity_style = "af.err"
            severity_icon = icon("warning")
        elif inj.severity >= 3:
            severity_style = "af.warn"
            severity_icon = icon("warning")
        else:
            severity_style = "af.muted"
            severity_icon = icon("bullet")

        console.print(f"[{severity_style}]{severity_icon}[/] [af.accent]{inj.point_id}[/]")
        console.print(f"    [af.muted]Type:[/] {inj.point_type}")
        console.print(f"    [af.muted]Time:[/] {inj.timestamp}")
        if inj.message:
            console.print(f"    [af.muted]Message:[/] {inj.message}")
        console.print(f"    [af.muted]Recommendation:[/] [af.ok]{inj.recommendation}[/]")
        console.print(f"    [af.muted]Options:[/] {', '.join(inj.options)}")
        console.print(f"    [af.muted]Timeout:[/] [af.number]{inj.timeout_seconds}s[/]")
        if inj.default_on_timeout:
            console.print(f"    [af.muted]Default:[/] {inj.default_on_timeout}")
        console.print()

    print_divider()
    console.print("[af.muted]To respond:[/] python respond.py --point-id <ID> --response \"<choice>\"")
    console.print("[af.muted]To accept recommendation:[/] python respond.py --point-id <ID> --accept")


def show_injection(interface: HumanInterface, point_id: str) -> None:
    """Show details of an injection point."""
    inj = interface.get_injection(point_id)

    if not inj:
        print_error(f"Injection point {point_id} not found.")
        return

    print_header(f"Injection Point: {inj.point_id}")

    # Status
    if inj.is_pending:
        status = f"[af.warn]{icon('bullet')} PENDING[/]"
    else:
        status = f"[af.ok]{icon('check')} RESPONDED ({inj.responded_by})[/]"

    # Basic info table
    info = {
        "Status": status,
        "Type": inj.point_type,
        "Severity": f"[af.number]{inj.severity}/5[/]",
        "Session": f"[af.number]{inj.session_id}[/]",
        "Timestamp": inj.timestamp,
    }
    print_key_value_table(info, title="Details")

    if inj.message:
        console.print()
        print_panel(inj.message, title="Message", style="af.info")

    if inj.context:
        console.print()
        print_subheader("Context")
        for key, value in inj.context.items():
            console.print(f"  [af.muted]{key}:[/] {value}")

    console.print()
    console.print(f"[af.accent]Recommendation:[/] [af.ok]{inj.recommendation}[/]")

    if inj.options:
        console.print()
        print_subheader("Available Options")
        for i, opt in enumerate(inj.options, 1):
            if opt == inj.recommendation:
                console.print(f"  [af.number]{i}.[/] [af.ok]{opt}[/] [af.muted](recommended)[/]")
            else:
                console.print(f"  [af.number]{i}.[/] {opt}")

    console.print()
    console.print(f"[af.muted]Timeout:[/] [af.number]{inj.timeout_seconds}[/] seconds")
    if inj.default_on_timeout:
        console.print(f"[af.muted]Default on timeout:[/] {inj.default_on_timeout}")

    if inj.escalation_rule_id:
        console.print()
        console.print(f"[af.warn]Triggered by escalation rule:[/] {inj.escalation_rule_id}")

    if not inj.is_pending:
        console.print()
        print_subheader("Response")
        console.print(f"  [af.muted]Response:[/] [af.ok]{inj.response}[/]")
        console.print(f"  [af.muted]Responded by:[/] {inj.responded_by}")
        console.print(f"  [af.muted]Responded at:[/] {inj.responded_at}")


def respond_interactive(interface: HumanInterface, point_id: str) -> None:
    """Interactively respond to an injection point."""
    inj = interface.get_injection(point_id)

    if not inj:
        print_error(f"Injection point {point_id} not found.")
        return

    if not inj.is_pending:
        print_warning(f"Injection point {point_id} has already been responded to.")
        return

    # Show the injection point
    show_injection(interface, point_id)

    print_divider()

    # Prompt for response
    if inj.options:
        console.print()
        console.print("[af.info]Enter your choice (number or text):[/]")
        console.print("  [af.muted]- Enter a number to select an option[/]")
        console.print("  [af.muted]- Enter 'r' to accept the recommendation[/]")
        console.print("  [af.muted]- Enter 'c' to cancel[/]")
        console.print("  [af.muted]- Or type your own response[/]")
        console.print()

        while True:
            choice = prompt("Choice").strip()

            if not choice:
                continue

            if choice.lower() == 'c':
                if interface.cancel(point_id):
                    print_warning(f"Injection point {point_id} cancelled.")
                return

            if choice.lower() == 'r':
                response = inj.recommendation
                break

            try:
                idx = int(choice) - 1
                if 0 <= idx < len(inj.options):
                    response = inj.options[idx]
                    break
                else:
                    print_warning(f"Invalid option number. Choose 1-{len(inj.options)}.")
            except ValueError:
                # Use the text as-is
                response = choice
                break
    else:
        console.print()
        console.print("[af.info]Enter your response (or 'c' to cancel):[/]")
        response = prompt("Response").strip()

        if response.lower() == 'c':
            if interface.cancel(point_id):
                print_warning(f"Injection point {point_id} cancelled.")
            return

    # Submit the response
    if interface.respond(point_id, response):
        console.print()
        print_success(f"Response submitted: {response}")
    else:
        console.print()
        print_error("Failed to submit response.")


def respond_direct(interface: HumanInterface, point_id: str, response: str) -> None:
    """Respond directly to an injection point."""
    inj = interface.get_injection(point_id)

    if not inj:
        print_error(f"Injection point {point_id} not found.")
        sys.exit(1)

    if not inj.is_pending:
        print_warning(f"Injection point {point_id} has already been responded to.")
        sys.exit(1)

    if interface.respond(point_id, response):
        print_success(f"Response submitted for {point_id}: {response}")
    else:
        print_error("Failed to submit response.")
        sys.exit(1)


def accept_recommendation(interface: HumanInterface, point_id: str) -> None:
    """Accept the agent's recommendation."""
    inj = interface.get_injection(point_id)

    if not inj:
        print_error(f"Injection point {point_id} not found.")
        sys.exit(1)

    if not inj.is_pending:
        print_warning(f"Injection point {point_id} has already been responded to.")
        sys.exit(1)

    if interface.respond(point_id, inj.recommendation):
        print_success(f"Accepted recommendation for {point_id}: {inj.recommendation}")
    else:
        print_error("Failed to submit response.")
        sys.exit(1)


def cancel_injection(interface: HumanInterface, point_id: str) -> None:
    """Cancel an injection point."""
    if interface.cancel(point_id):
        print_warning(f"Injection point {point_id} cancelled.")
    else:
        print_error(f"Injection point {point_id} not found or already completed.")
        sys.exit(1)


def show_history(interface: HumanInterface, limit: int = 20) -> None:
    """Show recent injection point history."""
    history = interface.get_history(limit=limit)

    if not history:
        print_info("No injection point history.")
        return

    print_header(f"Injection Point History (last {limit})")

    table = create_table(columns=["Point ID", "Type", "Status", "Time", "Response"])

    for entry in history:
        completed = entry.get("completed", False)
        responded_by = entry.get("responded_by", "")

        if completed:
            if responded_by:
                status = f"[af.ok]{icon('check')} {responded_by}[/]"
            else:
                status = f"[af.ok]{icon('check')} COMPLETED[/]"
        else:
            status = f"[af.warn]{icon('bullet')} PENDING[/]"

        response = entry.get("response", "")
        if response:
            response = f"[af.muted]{response[:20]}...[/]" if len(response) > 20 else f"[af.muted]{response}[/]"
        else:
            response = "[af.muted]-[/]"

        table.add_row(
            f"[af.accent]{entry.get('point_id', 'unknown')}[/]",
            entry.get('point_type', 'unknown'),
            status,
            entry.get('timestamp', 'unknown'),
            response,
        )

    print_table(table)


def show_stats(interface: HumanInterface) -> None:
    """Show injection point statistics."""
    stats = interface.get_stats()

    print_header("Injection Point Statistics")

    # Summary stats
    summary = {
        "Total Injections": f"[af.number]{stats.get('total_injections', 0)}[/]",
        "Currently Pending": f"[af.warn]{stats.get('pending_count', 0)}[/]",
    }
    print_key_value_table(summary, title="Summary")

    by_type = stats.get("by_type", {})
    if by_type:
        console.print()
        print_subheader("By Type")
        table = create_table(columns=["Type", "Count"])
        for ptype, count in sorted(by_type.items()):
            table.add_row(ptype, f"[af.number]{count}[/]")
        print_table(table)

    by_responded_by = stats.get("by_responded_by", {})
    if by_responded_by:
        console.print()
        print_subheader("By Response Method")
        table = create_table(columns=["Method", "Count"])
        for method, count in sorted(by_responded_by.items()):
            table.add_row(method, f"[af.number]{count}[/]")
        print_table(table)


def main():
    parser = argparse.ArgumentParser(
        description="Respond to agent injection points",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python respond.py --list                     # List pending injections
  python respond.py --point-id INJ-1-5         # Interactive response
  python respond.py --point-id INJ-1-5 --response "Use JWT"
  python respond.py --point-id INJ-1-5 --accept
  python respond.py --show INJ-1-5
  python respond.py --history
        """
    )

    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all pending injection points"
    )

    parser.add_argument(
        "--point-id", "-p",
        type=str,
        help="Injection point ID to respond to"
    )

    parser.add_argument(
        "--response", "-r",
        type=str,
        help="Response to submit"
    )

    parser.add_argument(
        "--accept", "-a",
        action="store_true",
        help="Accept the agent's recommendation"
    )

    parser.add_argument(
        "--cancel", "-c",
        action="store_true",
        help="Cancel the injection point"
    )

    parser.add_argument(
        "--show", "-s",
        type=str,
        metavar="POINT_ID",
        help="Show details of an injection point"
    )

    parser.add_argument(
        "--history", "-H",
        action="store_true",
        help="Show recent injection point history"
    )

    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show injection point statistics"
    )

    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Project directory (default: current directory)"
    )

    args = parser.parse_args()

    # Get project directory
    project_dir = args.project_dir or get_project_dir()
    interface = HumanInterface(project_dir)

    # Handle commands
    if args.list:
        list_pending(interface)
    elif args.show:
        show_injection(interface, args.show)
    elif args.history:
        show_history(interface)
    elif args.stats:
        show_stats(interface)
    elif args.point_id:
        if args.cancel:
            cancel_injection(interface, args.point_id)
        elif args.accept:
            accept_recommendation(interface, args.point_id)
        elif args.response:
            respond_direct(interface, args.point_id, args.response)
        else:
            respond_interactive(interface, args.point_id)
    else:
        # Default: show banner and list pending
        print_banner(version="Response CLI", subtitle="Respond to agent injection points")
        console.print()
        list_pending(interface)


if __name__ == "__main__":
    main()
