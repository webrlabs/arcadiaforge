#!/usr/bin/env python
"""
Events CLI - View and analyze event logs from autonomous coding sessions.

Usage:
    events-cli metrics [--project-dir DIR]
    events-cli list [--session ID] [--type TYPE] [--limit N]
    events-cli session SESSION_ID [--project-dir DIR]
    events-cli reconstruct SESSION_ID [--project-dir DIR]
    events-cli export [--output FILE] [--project-dir DIR]
    events-cli context TIMESTAMP [--project-dir DIR]
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from arcadiaforge.observability import (
    Observability,
    EventType,
    format_event_summary,
    format_metrics_summary,
)
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
    print_progress_bar,
    create_table,
    print_table,
    spinner,
    icon,
)


def get_event_style(event_type: str) -> str:
    """Get the style for an event type."""
    event_type_lower = event_type.lower()
    if "error" in event_type_lower or "fail" in event_type_lower:
        return "af.err"
    elif "blocked" in event_type_lower:
        return "af.warn"
    elif "success" in event_type_lower or "complete" in event_type_lower:
        return "af.ok"
    elif "tool" in event_type_lower:
        return "af.accent"
    else:
        return "af.info"


def format_event_row(event) -> tuple:
    """Format an event as a table row."""
    time_str = event.timestamp[:19] if event.timestamp else "N/A"
    event_type = str(event.event_type)
    style = get_event_style(event_type)

    tool = event.tool_name or ""
    session = str(event.session_id) if event.session_id else ""

    # Feature info
    feature = ""
    if event.feature_index is not None:
        feature = f"#{event.feature_index}"

    return (
        f"[af.timestamp]{time_str}[/]",
        f"[{style}]{event_type}[/]",
        session,
        tool,
        feature,
    )


def cmd_metrics(args):
    """Show run metrics summary."""
    obs = Observability(args.project_dir)

    if not obs.events_file.exists():
        print_warning(f"No events found at {obs.events_file}")
        return 1

    with spinner("Calculating metrics..."):
        metrics = obs.get_run_metrics()

    print_header("Run Metrics")

    # Sessions info
    print_key_value_table({
        "Total Sessions": str(metrics.get("sessions_total", 0)),
        "Total Duration": f"{metrics.get('total_duration_seconds', 0):.1f}s",
    }, title="Sessions")

    console.print()

    # Tool calls
    tool_total = metrics.get("tool_calls_total", 0)
    tool_success = metrics.get("tool_calls_successful", 0)
    tool_failed = metrics.get("tool_calls_failed", 0)
    tool_blocked = metrics.get("tool_calls_blocked", 0)

    print_subheader("Tool Calls")
    console.print(f"  [af.muted]Total:[/] [af.number]{tool_total}[/]")
    console.print(f"  [af.ok]Successful:[/] [af.number]{tool_success}[/]")
    console.print(f"  [af.err]Failed:[/] [af.number]{tool_failed}[/]")
    console.print(f"  [af.warn]Blocked:[/] [af.number]{tool_blocked}[/]")

    console.print()

    # Features
    print_subheader("Features")
    console.print(f"  [af.muted]Attempted:[/] [af.number]{metrics.get('features_attempted', 0)}[/]")
    console.print(f"  [af.ok]Completed:[/] [af.number]{metrics.get('features_completed', 0)}[/]")
    console.print(f"  [af.err]Failed:[/] [af.number]{metrics.get('features_failed', 0)}[/]")

    console.print()

    # Errors
    print_subheader("Issues")
    console.print(f"  [af.err]Errors:[/] [af.number]{metrics.get('errors_total', 0)}[/]")
    console.print(f"  [af.warn]Escalations:[/] [af.number]{metrics.get('escalations', 0)}[/]")

    return 0


def cmd_list(args):
    """List events with optional filters."""
    obs = Observability(args.project_dir)

    if not obs.events_file.exists():
        print_warning(f"No events found at {obs.events_file}")
        return 1

    # Build filter kwargs
    kwargs = {}
    if args.session:
        kwargs["session_id"] = args.session
    if args.type:
        try:
            kwargs["event_type"] = EventType[args.type.upper()]
        except KeyError:
            kwargs["event_type"] = args.type
    if args.limit:
        kwargs["limit"] = args.limit
    if args.tool:
        kwargs["tool_name"] = args.tool
    if args.feature is not None:
        kwargs["feature_index"] = args.feature

    with spinner("Loading events..."):
        events = obs.get_events(**kwargs)

    if not events:
        print_info("No matching events found")
        return 0

    print_header(f"Events ({len(events)})")

    table = create_table(columns=["Timestamp", "Type", "Session", "Tool", "Feature"])

    for event in events:
        table.add_row(*format_event_row(event))

    print_table(table)

    # Show verbose data if requested
    if args.verbose:
        console.print()
        print_subheader("Event Details")
        for event in events:
            if event.data:
                console.print(f"\n[af.accent]{event.timestamp[:19]}[/] - [af.info]{event.event_type}[/]")
                for key, value in event.data.items():
                    if key not in ("_truncated", "_preview"):
                        value_str = str(value)[:80]
                        console.print(f"  [af.key]{key}:[/] [af.muted]{value_str}[/]")

    return 0


def cmd_session(args):
    """Show events for a specific session."""
    obs = Observability(args.project_dir)

    if not obs.events_file.exists():
        print_warning(f"No events found at {obs.events_file}")
        return 1

    with spinner(f"Loading session {args.session_id}..."):
        events = obs.get_session_events(args.session_id)
        metrics = obs.get_session_metrics(args.session_id)

    if not events:
        print_warning(f"No events found for session {args.session_id}")
        return 0

    print_header(f"Session {args.session_id}")

    # Timing info
    print_key_value_table({
        "Started": metrics.started_at[:19] if metrics.started_at else "N/A",
        "Ended": metrics.ended_at[:19] if metrics.ended_at else "N/A",
        "Duration": f"{metrics.duration_seconds:.1f}s",
    }, title="Timing")

    console.print()

    # Tool calls summary
    print_subheader("Tool Calls")
    table = create_table(columns=["Status", "Count"])
    table.add_row("Total", f"[af.number]{metrics.tool_calls_total}[/]")
    table.add_row("[af.ok]Successful[/]", f"[af.number]{metrics.tool_calls_successful}[/]")
    table.add_row("[af.err]Errors[/]", f"[af.number]{metrics.tool_calls_failed}[/]")
    table.add_row("[af.warn]Blocked[/]", f"[af.number]{metrics.tool_calls_blocked}[/]")
    print_table(table)

    console.print()

    # Features summary
    print_subheader("Features")
    table = create_table(columns=["Status", "Count"])
    table.add_row("Attempted", f"[af.number]{metrics.features_attempted}[/]")
    table.add_row("[af.ok]Completed[/]", f"[af.number]{metrics.features_completed}[/]")
    table.add_row("[af.err]Failed[/]", f"[af.number]{metrics.features_failed}[/]")
    print_table(table)

    console.print()

    # Issues
    if metrics.errors_total > 0 or metrics.escalations > 0:
        print_subheader("Issues")
        console.print(f"  [af.err]Errors:[/] [af.number]{metrics.errors_total}[/]")
        console.print(f"  [af.warn]Escalations:[/] [af.number]{metrics.escalations}[/]")
        console.print()

    # Event timeline
    print_subheader("Event Timeline")
    print_divider()

    for event in events:
        time_str = event.timestamp[11:19] if event.timestamp else "??:??:??"
        style = get_event_style(str(event.event_type))

        line = f"[af.timestamp]{time_str}[/] [{style}]{event.event_type}[/]"
        if event.tool_name:
            line += f" [af.muted]({event.tool_name})[/]"
        if event.feature_index is not None:
            line += f" [af.accent]#{event.feature_index}[/]"

        console.print(line)

    return 0


def cmd_reconstruct(args):
    """Reconstruct a session for debugging."""
    obs = Observability(args.project_dir)

    if not obs.events_file.exists():
        print_warning(f"No events found at {obs.events_file}")
        return 1

    with spinner(f"Reconstructing session {args.session_id}..."):
        reconstruction = obs.reconstruct_session(args.session_id)

    print_header(f"Session {args.session_id} Reconstruction")

    # Metrics summary
    metrics = reconstruction["metrics"]
    print_key_value_table({
        "Duration": f"{metrics['duration_seconds']:.1f}s",
        "Tool Calls": str(metrics['tool_calls_total']),
        "Errors": str(metrics['errors_total']),
    }, title="Summary")

    console.print()

    # Timeline
    print_subheader("Timeline")
    print_divider()

    for entry in reconstruction["timeline"]:
        time_str = entry["time"][11:19] if "T" in entry["time"] else entry["time"][:8]
        event_type = entry["type"]
        style = get_event_style(event_type)

        line = f"[af.timestamp]{time_str}[/] [{style}]{event_type}[/]"

        if "tool" in entry:
            line += f" [af.muted]({entry['tool']})[/]"
        if "feature" in entry:
            line += f" [af.accent]#{entry['feature']}[/]"
        if "status" in entry:
            status_style = "af.ok" if entry["status"] == "success" else "af.err"
            line += f" [{status_style}]{entry['status']}[/]"

        console.print(line)

        if "error" in entry:
            console.print(f"    [af.err]{icon('cross')} {entry['error'][:80]}[/]")
        if "decision" in entry:
            console.print(f"    [af.info]{icon('info')} {entry['decision'][:80]}[/]")

    console.print()
    print_muted(f"Total events: {reconstruction['event_count']}")

    return 0


def cmd_export(args):
    """Export events to a JSON file."""
    obs = Observability(args.project_dir)

    if not obs.events_file.exists():
        print_warning(f"No events found at {obs.events_file}")
        return 1

    output_path = args.output if args.output else None

    with spinner("Exporting events..."):
        exported = obs.export_events(output_path)

    print_success(f"Events exported to: {exported}")
    return 0


def cmd_context(args):
    """Get context at a specific timestamp."""
    obs = Observability(args.project_dir)

    if not obs.events_file.exists():
        print_warning(f"No events found at {obs.events_file}")
        return 1

    # Parse timestamp
    try:
        if "T" not in args.timestamp:
            args.timestamp = args.timestamp.replace(" ", "T")
        timestamp = args.timestamp
    except Exception as e:
        print_error(f"Invalid timestamp format: {e}")
        return 1

    with spinner("Loading context..."):
        context = obs.get_context_at_time(timestamp)

    if "error" in context:
        print_error(context["error"])
        return 1

    print_header(f"Context at {timestamp}")

    console.print(f"[af.muted]Session:[/] [af.number]{context['session_id']}[/]")
    console.print()

    # Last event
    if context["last_event"]:
        print_subheader("Last Event")
        console.print(f"  [af.muted]Type:[/] {context['last_event']['event_type']}")
        if context['last_event'].get('tool_name'):
            console.print(f"  [af.muted]Tool:[/] {context['last_event']['tool_name']}")
        console.print()

    # Recent tool calls
    if context["recent_tool_calls"]:
        print_subheader("Recent Tool Calls")
        for tool in context["recent_tool_calls"][-5:]:
            console.print(f"  [af.accent]{icon('bullet')}[/] {tool}")
        console.print()

    # Recent errors
    if context["recent_errors"]:
        print_subheader("Recent Errors")
        for error in context["recent_errors"]:
            console.print(f"  [af.err]{icon('cross')}[/] {error}")
        console.print()

    # Features in progress
    if context["features_in_progress"]:
        print_subheader("Features In Progress")
        for feat in context["features_in_progress"]:
            console.print(f"  [af.accent]{icon('bullet')}[/] #{feat}")

    return 0


def cmd_tail(args):
    """Show the most recent events (like tail -f for logs)."""
    obs = Observability(args.project_dir)

    if not obs.events_file.exists():
        print_warning(f"No events found at {obs.events_file}")
        return 1

    with spinner("Loading recent events..."):
        events = obs.get_events(limit=args.lines)

    if not events:
        print_info("No events found")
        return 0

    print_header(f"Recent Events ({len(events)})")

    # Reverse to show oldest first (like tail)
    for event in reversed(events):
        time_str = event.timestamp[11:19] if event.timestamp else "??:??:??"
        style = get_event_style(str(event.event_type))

        line = f"[af.timestamp]{time_str}[/] [{style}]{event.event_type}[/]"
        if event.tool_name:
            line += f" [af.muted]({event.tool_name})[/]"

        console.print(line)

        if args.verbose and event.data:
            for key, value in list(event.data.items())[:3]:
                value_str = str(value)[:60]
                console.print(f"    [af.key]{key}:[/] [af.muted]{value_str}[/]")

    return 0


def cmd_errors(args):
    """Show all error events."""
    obs = Observability(args.project_dir)

    if not obs.events_file.exists():
        print_warning(f"No events found at {obs.events_file}")
        return 1

    with spinner("Loading error events..."):
        errors = obs.get_events(event_type=EventType.ERROR)
        tool_errors = obs.get_events(event_type=EventType.TOOL_ERROR)
        blocked = obs.get_events(event_type=EventType.TOOL_BLOCKED)

    all_errors = errors + tool_errors + blocked
    all_errors.sort(key=lambda e: e.timestamp, reverse=True)

    if args.limit:
        all_errors = all_errors[:args.limit]

    if not all_errors:
        print_success("No errors found!")
        return 0

    print_header(f"Errors ({len(all_errors)})")

    for event in all_errors:
        time_str = event.timestamp[:19] if event.timestamp else "N/A"
        event_type = str(event.event_type)

        # Determine style based on type
        if "blocked" in event_type.lower():
            style = "af.warn"
            type_icon = icon("blocked")
        else:
            style = "af.err"
            type_icon = icon("cross")

        console.print(f"[af.timestamp]{time_str}[/] [{style}]{type_icon} {event_type}[/]")

        if event.tool_name:
            console.print(f"  [af.muted]Tool:[/] {event.tool_name}")
        if event.data.get("error_message"):
            console.print(f"  [af.muted]Message:[/] {event.data['error_message'][:100]}")
        if event.data.get("error_type"):
            console.print(f"  [af.muted]Type:[/] {event.data['error_type']}")
        console.print()

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="View and analyze event logs from autonomous coding sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path("."),
        help="Project directory containing .events.jsonl (default: current dir)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # metrics command
    metrics_parser = subparsers.add_parser("metrics", help="Show run metrics summary")

    # list command
    list_parser = subparsers.add_parser("list", help="List events with filters")
    list_parser.add_argument("--session", "-s", type=int, help="Filter by session ID")
    list_parser.add_argument("--type", "-t", help="Filter by event type")
    list_parser.add_argument("--tool", help="Filter by tool name")
    list_parser.add_argument("--feature", "-f", type=int, help="Filter by feature index")
    list_parser.add_argument("--limit", "-n", type=int, default=50, help="Max events to show")
    list_parser.add_argument("--verbose", "-v", action="store_true", help="Show event data")

    # session command
    session_parser = subparsers.add_parser("session", help="Show session details")
    session_parser.add_argument("session_id", type=int, help="Session ID to show")

    # reconstruct command
    reconstruct_parser = subparsers.add_parser("reconstruct", help="Reconstruct session timeline")
    reconstruct_parser.add_argument("session_id", type=int, help="Session ID to reconstruct")

    # export command
    export_parser = subparsers.add_parser("export", help="Export events to JSON")
    export_parser.add_argument("--output", "-o", type=Path, help="Output file path")

    # context command
    context_parser = subparsers.add_parser("context", help="Get state at a timestamp")
    context_parser.add_argument("timestamp", help="ISO timestamp (e.g., 2025-12-18T10:30:00)")

    # tail command
    tail_parser = subparsers.add_parser("tail", help="Show most recent events")
    tail_parser.add_argument("--lines", "-n", type=int, default=20, help="Number of events")
    tail_parser.add_argument("--verbose", "-v", action="store_true", help="Show event data")

    # errors command
    errors_parser = subparsers.add_parser("errors", help="Show all error events")
    errors_parser.add_argument("--limit", "-n", type=int, help="Max errors to show")

    args = parser.parse_args()

    if not args.command:
        print_banner(version="Events CLI", subtitle="Analyze coding session events")
        console.print()
        parser.print_help()
        return 1

    # Dispatch to command handler
    commands = {
        "metrics": cmd_metrics,
        "list": cmd_list,
        "session": cmd_session,
        "reconstruct": cmd_reconstruct,
        "export": cmd_export,
        "context": cmd_context,
        "tail": cmd_tail,
        "errors": cmd_errors,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
