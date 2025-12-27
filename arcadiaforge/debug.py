#!/usr/bin/env python3
"""
Debug CLI Tool
==============

Command-line interface for debugging and reconstructing runs.

Usage:
    debug-cli reconstruct --session SESSION_ID
    debug-cli context --timestamp "2025-12-18T10:30:00"
    debug-cli events --tool TOOL_NAME [--session SESSION_ID]
    debug-cli decisions --feature FEATURE_ID
    debug-cli timeline --session SESSION_ID
    debug-cli errors [--session SESSION_ID]
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from arcadiaforge.observability import Observability, EventType, Event
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
    spinner,
    icon,
)


def get_project_dir(args) -> Path:
    """Get project directory from args or current directory."""
    if hasattr(args, 'project') and args.project:
        return Path(args.project)
    return Path.cwd()


def format_timestamp(ts: str) -> str:
    """Format ISO timestamp for display."""
    if ts:
        return ts[:19].replace('T', ' ')
    return 'N/A'


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
    elif "decision" in event_type_lower:
        return "af.info"
    else:
        return "af.muted"


def cmd_reconstruct(args):
    """Reconstruct a session."""
    project_dir = get_project_dir(args)
    obs = Observability(project_dir)

    session_id = args.session
    if session_id is None:
        session_id = obs.get_latest_session_id()
        print_info(f"Using latest session: #{session_id}")

    with spinner(f"Reconstructing session #{session_id}..."):
        result = obs.reconstruct_session(session_id)

    print_header(f"Session #{session_id} Reconstruction")

    # Metrics summary
    metrics = result["metrics"]
    print_key_value_table({
        "Started": format_timestamp(metrics.get('started_at')),
        "Ended": format_timestamp(metrics.get('ended_at')),
        "Duration": f"{metrics.get('duration_seconds', 0):.1f}s",
        "Tool Calls": str(metrics.get('tool_calls_total', 0)),
        "Features": f"{metrics.get('features_completed', 0)} completed, {metrics.get('features_failed', 0)} failed",
        "Errors": str(metrics.get('errors_total', 0)),
    }, title="Summary")

    console.print()

    # Timeline
    print_subheader("Timeline")
    print_divider()

    for entry in result["timeline"]:
        time_str = entry["time"][11:19]  # HH:MM:SS
        event_type = entry["type"]
        style = get_event_style(event_type)

        line = f"[af.timestamp]{time_str}[/] [{style}]{event_type}[/]"

        if "tool" in entry:
            line += f" [af.muted]tool={entry['tool']}[/]"
        if "feature" in entry:
            line += f" [af.accent]#[/][af.number]{entry['feature']}[/]"
        if "decision" in entry:
            line += f" [af.info]-> {entry['decision'][:30]}[/]"
        if "error" in entry:
            line += f" [af.err]ERROR: {entry['error'][:40]}[/]"
        if "status" in entry:
            status_style = "af.ok" if entry["status"] == "success" else "af.err"
            line += f" [{status_style}][{entry['status']}][/]"

        console.print(f"  {line}")

    console.print()
    print_muted(f"Total events: {result['event_count']}")


def cmd_context(args):
    """Show context at a specific timestamp."""
    project_dir = get_project_dir(args)
    obs = Observability(project_dir)

    timestamp = args.timestamp

    # Handle relative timestamps like "5 minutes ago"
    if "ago" in timestamp.lower():
        parts = timestamp.lower().split()
        try:
            amount = int(parts[0])
            unit = parts[1]
            now = datetime.now(timezone.utc)
            if "minute" in unit:
                delta = now - timedelta(minutes=amount)
            elif "hour" in unit:
                delta = now - timedelta(hours=amount)
            elif "second" in unit:
                delta = now - timedelta(seconds=amount)
            else:
                delta = now
            timestamp = delta.isoformat()
        except (ValueError, IndexError):
            print_error(f"Could not parse relative time: {args.timestamp}")
            sys.exit(1)

    with spinner("Loading context..."):
        result = obs.get_context_at_time(timestamp)

    if "error" in result:
        print_error(result["error"])
        sys.exit(1)

    print_header(f"Context at {format_timestamp(timestamp)}")

    console.print(f"[af.muted]Session:[/] [af.number]#{result.get('session_id', 'N/A')}[/]")
    console.print()

    # Last event
    last_event = result.get("last_event", {})
    print_subheader("Last Event")
    console.print(f"  [af.muted]Type:[/] {last_event.get('event_type', 'N/A')}")
    console.print(f"  [af.muted]Time:[/] [af.timestamp]{format_timestamp(last_event.get('timestamp'))}[/]")
    if last_event.get('tool_name'):
        console.print(f"  [af.muted]Tool:[/] {last_event['tool_name']}")
    console.print()

    # Recent tool calls
    if result.get("recent_tool_calls"):
        print_subheader("Recent Tool Calls")
        for tool in result["recent_tool_calls"]:
            console.print(f"  [af.accent]{icon('bullet')}[/] {tool}")
        console.print()

    # Recent errors
    if result.get("recent_errors"):
        print_subheader("Recent Errors")
        for error in result["recent_errors"]:
            console.print(f"  [af.err]{icon('cross')}[/] {error}")
        console.print()

    # Features in progress
    if result.get("features_in_progress"):
        print_subheader("Features In Progress")
        for f in result["features_in_progress"]:
            console.print(f"  [af.accent]{icon('bullet')}[/] Feature #{f}")


def cmd_events(args):
    """List events with filters."""
    project_dir = get_project_dir(args)
    obs = Observability(project_dir)

    # Build filters
    kwargs = {}
    if args.session:
        kwargs["session_id"] = args.session
    if args.tool:
        kwargs["tool_name"] = args.tool
    if args.type:
        try:
            kwargs["event_type"] = EventType(args.type)
        except ValueError:
            print_error(f"Unknown event type: {args.type}")
            print_muted(f"Valid types: {[e.value for e in EventType]}")
            sys.exit(1)
    if args.feature is not None:
        kwargs["feature_index"] = args.feature
    if args.limit:
        kwargs["limit"] = args.limit

    with spinner("Loading events..."):
        events = obs.get_events(**kwargs)

    if not events:
        print_info("No matching events found.")
        return

    print_header(f"Events ({len(events)})")

    table = create_table(columns=["Time", "Type", "Tool", "Feature", "Details"])

    for event in events:
        time_str = format_timestamp(event.timestamp)
        event_type = event.event_type[:23]
        style = get_event_style(event_type)
        tool = (event.tool_name or "")[:13]
        feature = f"#{event.feature_index}" if event.feature_index is not None else ""

        # Extract key details
        details = ""
        if event.data:
            if "error_message" in event.data:
                details = f"[af.err]{event.data['error_message'][:28]}[/]"
            elif "choice" in event.data:
                details = event.data["choice"][:28]
            elif "status" in event.data:
                details = event.data["status"][:28]
            elif "description" in event.data:
                details = event.data["description"][:28]

        table.add_row(
            f"[af.timestamp]{time_str}[/]",
            f"[{style}]{event_type}[/]",
            tool,
            f"[af.number]{feature}[/]" if feature else "",
            details
        )

    print_table(table)


def cmd_decisions(args):
    """Show decision chain for a feature."""
    project_dir = get_project_dir(args)
    obs = Observability(project_dir)

    with spinner("Loading decisions..."):
        events = obs.get_events(
            event_type=EventType.DECISION,
            feature_index=args.feature if args.feature is not None else None,
        )

    if not events:
        print_info("No decisions found.")
        return

    title = "Decision Chain"
    if args.feature is not None:
        title += f" for Feature #{args.feature}"
    print_header(title)

    # Reverse to chronological order
    events.reverse()

    for i, event in enumerate(events, 1):
        data = event.data

        console.print(f"[af.accent]Decision #{i}[/]")
        console.print(f"  [af.muted]Time:[/]        [af.timestamp]{format_timestamp(event.timestamp)}[/]")
        console.print(f"  [af.muted]Session:[/]     [af.number]#{event.session_id}[/]")
        if event.feature_index is not None:
            console.print(f"  [af.muted]Feature:[/]     [af.number]#{event.feature_index}[/]")
        console.print(f"  [af.muted]Type:[/]        {data.get('decision_type', 'N/A')}")
        console.print(f"  [af.muted]Choice:[/]      [af.ok]{data.get('choice', 'N/A')}[/]")

        confidence = data.get('confidence', 1.0)
        conf_style = "af.ok" if confidence > 0.8 else "af.warn" if confidence > 0.5 else "af.err"
        console.print(f"  [af.muted]Confidence:[/]  [{conf_style}]{confidence:.1%}[/]")

        if data.get("alternatives"):
            alts = ', '.join(data['alternatives'][:3])
            console.print(f"  [af.muted]Alternatives:[/] {alts}")
        if data.get("rationale"):
            console.print(f"  [af.muted]Rationale:[/]   {data['rationale'][:60]}")
        console.print()


def cmd_timeline(args):
    """Show visual timeline for a session."""
    project_dir = get_project_dir(args)
    obs = Observability(project_dir)

    session_id = args.session
    if session_id is None:
        session_id = obs.get_latest_session_id()

    with spinner(f"Loading session #{session_id}..."):
        events = obs.get_session_events(session_id)

    if not events:
        print_warning(f"No events found for session #{session_id}")
        return

    print_header(f"Session #{session_id} Visual Timeline")

    # Group events by minute
    by_minute = defaultdict(list)

    for event in events:
        minute = event.timestamp[:16]  # YYYY-MM-DDTHH:MM
        by_minute[minute].append(event)

    # Print timeline
    for minute in sorted(by_minute.keys()):
        minute_events = by_minute[minute]
        time_str = minute[11:16]  # HH:MM

        # Count event types
        type_counts = defaultdict(int)
        has_error = False
        for e in minute_events:
            type_counts[e.event_type] += 1
            if e.event_type in [EventType.ERROR.value, EventType.TOOL_ERROR.value]:
                has_error = True

        # Build visual indicators
        parts = []
        if type_counts.get(EventType.TOOL_CALL.value, 0) > 0:
            parts.append(f"[af.accent]T:{type_counts[EventType.TOOL_CALL.value]}[/]")
        if type_counts.get(EventType.FEATURE_COMPLETED.value, 0) > 0:
            parts.append(f"[af.ok]F+:{type_counts[EventType.FEATURE_COMPLETED.value]}[/]")
        if type_counts.get(EventType.FEATURE_FAILED.value, 0) > 0:
            parts.append(f"[af.err]F-:{type_counts[EventType.FEATURE_FAILED.value]}[/]")
        if type_counts.get(EventType.ERROR.value, 0) > 0:
            parts.append(f"[af.err]E:{type_counts[EventType.ERROR.value]}[/]")
        if type_counts.get(EventType.DECISION.value, 0) > 0:
            parts.append(f"[af.info]D:{type_counts[EventType.DECISION.value]}[/]")

        status_icon = f"[af.err]{icon('warning')}[/]" if has_error else " "
        event_count = f"[af.number]{len(minute_events):>3}[/]"

        console.print(f"[af.timestamp]{time_str}[/] {status_icon} [{event_count} events] {' '.join(parts)}")


def cmd_errors(args):
    """Show all errors."""
    project_dir = get_project_dir(args)
    obs = Observability(project_dir)

    with spinner("Loading errors..."):
        kwargs = {"event_type": EventType.ERROR}
        if args.session:
            kwargs["session_id"] = args.session
        if args.limit:
            kwargs["limit"] = args.limit

        events = obs.get_events(**kwargs)

        # Also get tool errors
        tool_errors = obs.get_events(
            event_type=EventType.TOOL_ERROR,
            session_id=args.session if args.session else None,
            limit=args.limit if args.limit else None,
        )

    all_errors = events + tool_errors
    all_errors.sort(key=lambda e: e.timestamp, reverse=True)

    if not all_errors:
        print_success("No errors found!")
        return

    print_header(f"Errors ({len(all_errors)})")

    for event in all_errors[:args.limit or 50]:
        console.print(f"[af.timestamp]{format_timestamp(event.timestamp)}[/] [af.muted]Session[/] [af.number]#{event.session_id}[/]")

        if event.tool_name:
            console.print(f"  [af.muted]Tool:[/] {event.tool_name}")
        if event.feature_index is not None:
            console.print(f"  [af.muted]Feature:[/] [af.number]#{event.feature_index}[/]")

        data = event.data
        if data.get("error_type"):
            console.print(f"  [af.muted]Type:[/] [af.warn]{data['error_type']}[/]")
        if data.get("error_message"):
            console.print(f"  [af.muted]Message:[/] [af.err]{data['error_message'][:100]}[/]")
        console.print()


def cmd_replay(args):
    """Replay events from a point in time."""
    project_dir = get_project_dir(args)
    obs = Observability(project_dir)

    with spinner("Loading events..."):
        all_events = obs._load_all_events()
        all_events.sort(key=lambda e: e.timestamp)

    # Filter to session if specified
    if args.session:
        all_events = [e for e in all_events if e.session_id == args.session]

    # Find starting point
    start_idx = 0
    if args.from_timestamp:
        for i, e in enumerate(all_events):
            if e.timestamp >= args.from_timestamp:
                start_idx = i
                break

    if args.from_event:
        for i, e in enumerate(all_events):
            if e.event_id == args.from_event:
                start_idx = i
                break

    # Replay events
    events_to_replay = all_events[start_idx:]
    if args.limit:
        events_to_replay = events_to_replay[:args.limit]

    print_header(f"Replaying {len(events_to_replay)} Events")

    for event in events_to_replay:
        time_str = format_timestamp(event.timestamp)
        style = get_event_style(event.event_type)

        console.print(f"[af.timestamp]{time_str}[/] [{style}]{event.event_type}[/]")

        if event.tool_name:
            console.print(f"    [af.muted]Tool:[/] {event.tool_name}")
        if event.feature_index is not None:
            console.print(f"    [af.muted]Feature:[/] [af.number]#{event.feature_index}[/]")

        # Show key data
        if event.data:
            if event.event_type == EventType.DECISION.value:
                console.print(f"    [af.muted]Choice:[/] [af.ok]{event.data.get('choice', 'N/A')}[/]")
                console.print(f"    [af.muted]Confidence:[/] {event.data.get('confidence', 1.0):.1%}")
            elif event.event_type in [EventType.ERROR.value, EventType.TOOL_ERROR.value]:
                console.print(f"    [af.err]Error: {event.data.get('error_message', 'N/A')[:60]}[/]")
            elif event.event_type == EventType.FEATURE_COMPLETED.value:
                console.print(f"    [af.ok]Description: {event.data.get('description', 'N/A')[:40]}[/]")

        if args.verbose:
            console.print(f"    [af.muted]Full data: {json.dumps(event.data, indent=6)[:200]}[/]")

        console.print()

        # Optional delay for "replay" feel
        if args.delay and args.delay > 0:
            import time
            time.sleep(args.delay / 1000)


def main():
    parser = argparse.ArgumentParser(
        description="Debug CLI Tool for run reconstruction and analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Reconstruct latest session
    debug-cli reconstruct

    # Reconstruct specific session
    debug-cli reconstruct --session 5

    # Show context at a timestamp
    debug-cli context --timestamp "2025-12-18T10:30:00"

    # List events with filters
    debug-cli events --tool Read --session 5

    # Show decision chain for a feature
    debug-cli decisions --feature 42

    # Show visual timeline
    debug-cli timeline --session 5

    # Show all errors
    debug-cli errors --session 5
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Reconstruct command
    reconstruct_parser = subparsers.add_parser("reconstruct", help="Reconstruct a session")
    reconstruct_parser.add_argument("--session", "-s", type=int, help="Session ID (default: latest)")
    reconstruct_parser.add_argument("--project", "-p", help="Project directory")

    # Context command
    context_parser = subparsers.add_parser("context", help="Show context at a timestamp")
    context_parser.add_argument("--timestamp", "-t", required=True,
                                help="ISO timestamp or relative (e.g., '5 minutes ago')")
    context_parser.add_argument("--project", "-p", help="Project directory")

    # Events command
    events_parser = subparsers.add_parser("events", help="List events with filters")
    events_parser.add_argument("--session", "-s", type=int, help="Filter by session")
    events_parser.add_argument("--tool", help="Filter by tool name")
    events_parser.add_argument("--type", help="Filter by event type")
    events_parser.add_argument("--feature", type=int, help="Filter by feature index")
    events_parser.add_argument("--limit", "-n", type=int, default=50, help="Max events to show")
    events_parser.add_argument("--project", "-p", help="Project directory")

    # Decisions command
    decisions_parser = subparsers.add_parser("decisions", help="Show decision chain")
    decisions_parser.add_argument("--feature", "-f", type=int, help="Filter by feature")
    decisions_parser.add_argument("--project", "-p", help="Project directory")

    # Timeline command
    timeline_parser = subparsers.add_parser("timeline", help="Show visual timeline")
    timeline_parser.add_argument("--session", "-s", type=int, help="Session ID (default: latest)")
    timeline_parser.add_argument("--project", "-p", help="Project directory")

    # Errors command
    errors_parser = subparsers.add_parser("errors", help="Show all errors")
    errors_parser.add_argument("--session", "-s", type=int, help="Filter by session")
    errors_parser.add_argument("--limit", "-n", type=int, default=50, help="Max errors to show")
    errors_parser.add_argument("--project", "-p", help="Project directory")

    # Replay command
    replay_parser = subparsers.add_parser("replay", help="Replay events from a point")
    replay_parser.add_argument("--session", "-s", type=int, help="Session ID")
    replay_parser.add_argument("--from-timestamp", help="Start from this timestamp")
    replay_parser.add_argument("--from-event", help="Start from this event ID")
    replay_parser.add_argument("--limit", "-n", type=int, help="Max events to replay")
    replay_parser.add_argument("--delay", "-d", type=int, default=0, help="Delay between events (ms)")
    replay_parser.add_argument("--verbose", "-v", action="store_true", help="Show full event data")
    replay_parser.add_argument("--project", "-p", help="Project directory")

    args = parser.parse_args()

    if not args.command:
        print_banner(version="Debug CLI", subtitle="Debug and analyze coding sessions")
        console.print()
        parser.print_help()
        sys.exit(1)

    commands = {
        "reconstruct": cmd_reconstruct,
        "context": cmd_context,
        "events": cmd_events,
        "decisions": cmd_decisions,
        "timeline": cmd_timeline,
        "errors": cmd_errors,
        "replay": cmd_replay,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
