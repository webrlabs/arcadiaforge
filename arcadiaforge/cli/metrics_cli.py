#!/usr/bin/env python3
"""
Metrics CLI Tool
================

Command-line interface for viewing and exporting metrics.

Usage:
    metrics-cli dashboard [--project PATH]
    metrics-cli session SESSION_ID [--project PATH]
    metrics-cli export [--format FORMAT] [--output PATH] [--project PATH]
    metrics-cli compare SESSION1 SESSION2 [--project PATH]
"""

import argparse
import sys
from pathlib import Path

from arcadiaforge.metrics import MetricsCollector
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
    print_key_value_table,
    print_progress_bar,
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


def cmd_dashboard(args):
    """Show metrics dashboard."""
    project_dir = get_project_dir(args)
    collector = MetricsCollector(project_dir)

    with spinner("Loading metrics..."):
        dashboard = collector.get_dashboard()

    print_header("Metrics Dashboard")

    # The dashboard is already formatted text, but we can enhance it
    # For now, just print it with basic styling
    console.print(dashboard)


def cmd_session(args):
    """Show session summary."""
    project_dir = get_project_dir(args)
    collector = MetricsCollector(project_dir)

    with spinner(f"Loading session {args.session_id}..."):
        summary = collector.get_session_summary(args.session_id)

    print_header(f"Session {args.session_id}")
    console.print(summary)


def cmd_export(args):
    """Export metrics to file."""
    project_dir = get_project_dir(args)
    collector = MetricsCollector(project_dir)

    format_type = args.format or "json"
    output_path = Path(args.output) if args.output else None

    if format_type == "json":
        with spinner("Exporting to JSON..."):
            path = collector.export_to_json(output_path)
        print_success(f"Exported metrics to: {path}")

    elif format_type == "csv":
        with spinner("Exporting to CSV..."):
            sessions_path = collector.export_to_csv(output_path)
            tools_path = collector.export_tool_metrics_csv()
        print_success(f"Exported session metrics to: {sessions_path}")
        print_success(f"Exported tool metrics to: {tools_path}")

    else:
        print_error(f"Unknown format: {format_type}")
        sys.exit(1)


def cmd_compare(args):
    """Compare two sessions."""
    project_dir = get_project_dir(args)
    collector = MetricsCollector(project_dir)

    with spinner("Loading session data..."):
        s1 = collector.obs.get_session_metrics(args.session1)
        s2 = collector.obs.get_session_metrics(args.session2)

    print_header(f"Session Comparison: #{args.session1} vs #{args.session2}")

    # Create comparison table
    table = create_table(columns=["Metric", f"Session {args.session1}", f"Session {args.session2}", "Diff"])

    comparisons = [
        ("Duration (s)", s1.duration_seconds, s2.duration_seconds),
        ("Tool Calls", s1.tool_calls_total, s2.tool_calls_total),
        ("Tool Successes", s1.tool_calls_successful, s2.tool_calls_successful),
        ("Tool Failures", s1.tool_calls_failed, s2.tool_calls_failed),
        ("Features Attempted", s1.features_attempted, s2.features_attempted),
        ("Features Completed", s1.features_completed, s2.features_completed),
        ("Features Failed", s1.features_failed, s2.features_failed),
        ("Errors", s1.errors_total, s2.errors_total),
        ("Escalations", s1.escalations, s2.escalations),
    ]

    for name, v1, v2 in comparisons:
        diff = v2 - v1
        if diff > 0:
            diff_str = f"[af.ok]+{diff:.1f}[/]"
        elif diff < 0:
            diff_str = f"[af.err]{diff:.1f}[/]"
        else:
            diff_str = "[af.muted]0[/]"

        table.add_row(
            name,
            f"[af.number]{v1:.1f}[/]",
            f"[af.number]{v2:.1f}[/]",
            diff_str
        )

    print_table(table)


def cmd_tools(args):
    """Show tool-specific metrics."""
    project_dir = get_project_dir(args)
    collector = MetricsCollector(project_dir)

    with spinner("Calculating tool metrics..."):
        metrics = collector.get_comprehensive_metrics()

    print_header("Tool Usage Metrics")

    table = create_table(columns=["Tool", "Calls", "Success", "Failed", "Blocked", "Avg (ms)"])

    sorted_tools = sorted(
        metrics.tool_metrics.items(),
        key=lambda x: x[1].get("total_calls", 0),
        reverse=True
    )

    total_calls = 0
    for name, tm in sorted_tools:
        calls = tm.get("total_calls", 0)
        success = tm.get("successful_calls", 0)
        failed = tm.get("failed_calls", 0)
        blocked = tm.get("blocked_calls", 0)
        avg_ms = tm.get("avg_duration_ms", 0)
        total_calls += calls

        # Color code based on failure rate
        if calls > 0:
            fail_rate = (failed + blocked) / calls
            if fail_rate > 0.5:
                name_styled = f"[af.err]{name}[/]"
            elif fail_rate > 0.2:
                name_styled = f"[af.warn]{name}[/]"
            else:
                name_styled = f"[af.ok]{name}[/]"
        else:
            name_styled = name

        table.add_row(
            name_styled,
            f"[af.number]{calls}[/]",
            f"[af.ok]{success}[/]",
            f"[af.err]{failed}[/]" if failed > 0 else f"[af.muted]{failed}[/]",
            f"[af.warn]{blocked}[/]" if blocked > 0 else f"[af.muted]{blocked}[/]",
            f"[af.muted]{avg_ms:.1f}[/]"
        )

    print_table(table)
    print_divider()
    console.print(f"[af.muted]Total calls:[/] [af.number]{total_calls}[/]")


def cmd_features(args):
    """Show feature-specific metrics."""
    project_dir = get_project_dir(args)
    collector = MetricsCollector(project_dir)

    with spinner("Calculating feature metrics..."):
        metrics = collector.get_comprehensive_metrics()

    print_header("Feature Metrics")

    table = create_table(columns=["#", "Description", "Attempts", "Success", "Status", "Avg Time"])

    sorted_features = sorted(
        metrics.feature_metrics.items(),
        key=lambda x: x[0]
    )

    passing_count = 0
    total_count = len(sorted_features)

    for idx, fm in sorted_features:
        desc = fm.get("description", "")[:28]
        attempts = fm.get("attempts", 0)
        success = fm.get("successful_attempts", 0)
        is_passing = fm.get("is_passing", False)
        avg_time = fm.get("avg_attempt_seconds", 0)

        if is_passing:
            passing_count += 1
            status = f"[af.ok]{icon('check')} PASS[/]"
        else:
            status = f"[af.err]{icon('cross')} FAIL[/]"

        table.add_row(
            f"[af.number]{idx}[/]",
            desc,
            f"[af.number]{attempts}[/]",
            f"[af.ok]{success}[/]" if success > 0 else f"[af.muted]{success}[/]",
            status,
            f"[af.muted]{avg_time:.1f}s[/]"
        )

    print_table(table)

    # Summary
    console.print()
    print_progress_bar(passing_count, total_count, "Features Passing")


def main():
    parser = argparse.ArgumentParser(
        description="Metrics CLI Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Show metrics dashboard
    metrics-cli dashboard

    # Show session summary
    metrics-cli session 5

    # Export metrics to JSON
    metrics-cli export --format json

    # Compare two sessions
    metrics-cli compare 3 5

    # Show tool usage
    metrics-cli tools
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Dashboard command
    dashboard_parser = subparsers.add_parser("dashboard", help="Show metrics dashboard")
    dashboard_parser.add_argument("--project", "-p", help="Project directory")

    # Session command
    session_parser = subparsers.add_parser("session", help="Show session summary")
    session_parser.add_argument("session_id", type=int, help="Session ID to show")
    session_parser.add_argument("--project", "-p", help="Project directory")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export metrics")
    export_parser.add_argument("--format", "-f", choices=["json", "csv"], default="json",
                               help="Export format")
    export_parser.add_argument("--output", "-o", help="Output file path")
    export_parser.add_argument("--project", "-p", help="Project directory")

    # Compare command
    compare_parser = subparsers.add_parser("compare", help="Compare two sessions")
    compare_parser.add_argument("session1", type=int, help="First session ID")
    compare_parser.add_argument("session2", type=int, help="Second session ID")
    compare_parser.add_argument("--project", "-p", help="Project directory")

    # Tools command
    tools_parser = subparsers.add_parser("tools", help="Show tool metrics")
    tools_parser.add_argument("--project", "-p", help="Project directory")

    # Features command
    features_parser = subparsers.add_parser("features", help="Show feature metrics")
    features_parser.add_argument("--project", "-p", help="Project directory")

    args = parser.parse_args()

    if not args.command:
        print_banner(version="Metrics CLI", subtitle="View and export performance metrics")
        console.print()
        parser.print_help()
        sys.exit(1)

    commands = {
        "dashboard": cmd_dashboard,
        "session": cmd_session,
        "export": cmd_export,
        "compare": cmd_compare,
        "tools": cmd_tools,
        "features": cmd_features,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
