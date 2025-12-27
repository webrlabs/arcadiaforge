#!/usr/bin/env python
"""
Feature List CLI
================

Command-line tool for inspecting and managing the feature database.
This is useful for checking project status, debugging, and manual operations.

Usage:
    python feature_cli.py stats ./generations/my_project
    python feature_cli.py list ./generations/my_project --status failing --limit 10
    python feature_cli.py next ./generations/my_project
    python feature_cli.py search ./generations/my_project "authentication"
    python feature_cli.py validate ./generations/my_project
"""

import argparse
import sys
from pathlib import Path

from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from arcadiaforge.feature_list import FeatureList, FeatureStats
from arcadiaforge.output import console  # Use shared console with proper encoding


def cmd_stats(args: argparse.Namespace) -> int:
    """Show feature list statistics."""
    fl = FeatureList(args.project_dir)

    if not fl.exists():
        console.print(f"[red]Error:[/red] No features found in database for {args.project_dir}")
        return 1

    fl.load()
    stats = fl.get_stats()

    # Create a nice panel with stats
    content = Text()
    content.append("Total Features: ", style="bold")
    content.append(f"{stats.total}\n")

    content.append("\nProgress: ", style="bold")
    progress_color = "green" if stats.progress_percent > 80 else "yellow" if stats.progress_percent > 50 else "red"
    content.append(f"{stats.passing}/{stats.total} ({stats.progress_percent:.1f}%)\n", style=progress_color)

    content.append("\nBy Category:\n", style="bold")
    content.append(f"  Functional: {stats.functional_passing}/{stats.functional_total}\n")
    content.append(f"  Style: {stats.style_passing}/{stats.style_total}\n")

    # Progress bar
    bar_width = 40
    filled = int(bar_width * stats.progress_percent / 100)
    bar = "█" * filled + "░" * (bar_width - filled)
    content.append(f"\n[{bar}]", style=progress_color)

    console.print(Panel(content, title="Feature List Stats", border_style="blue"))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List features with optional filtering."""
    fl = FeatureList(args.project_dir)

    if not fl.exists():
        console.print(f"[red]Error:[/red] No features found in database for {args.project_dir}")
        return 1

    fl.load()

    features = fl.list_features(
        status=args.status,
        category=args.category,
        limit=args.limit,
    )

    if not features:
        console.print("[yellow]No features match the criteria[/yellow]")
        return 0

    # Create table
    table = Table(title=f"Features ({len(features)} shown)")
    table.add_column("#", style="dim", width=5)
    table.add_column("Status", width=8)
    table.add_column("Category", width=12)
    table.add_column("Description", overflow="fold")
    table.add_column("Steps", width=6)

    for f in features:
        status_icon = "✓" if f.passes else "○"
        status_style = "green" if f.passes else "red"

        table.add_row(
            str(f.index),
            Text(status_icon, style=status_style),
            f.category,
            f.description[:80] + ("..." if len(f.description) > 80 else ""),
            str(len(f.steps)),
        )

    console.print(table)
    return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Show the next incomplete feature."""
    fl = FeatureList(args.project_dir)

    if not fl.exists():
        console.print(f"[red]Error:[/red] No features found in database for {args.project_dir}")
        return 1

    fl.load()

    feature = fl.get_next_incomplete(category=args.category)

    if not feature:
        console.print("[green]All features are complete![/green]")
        return 0

    # Display feature details
    content = Text()
    content.append(f"Index: ", style="bold")
    content.append(f"{feature.index}\n")
    content.append(f"Category: ", style="bold")
    content.append(f"{feature.category}\n")
    content.append(f"\nDescription:\n", style="bold")
    content.append(f"{feature.description}\n")
    content.append(f"\nTest Steps:\n", style="bold")
    for i, step in enumerate(feature.steps, 1):
        content.append(f"  {i}. {step}\n")

    console.print(Panel(content, title="Next Feature to Implement", border_style="yellow"))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Show details for a specific feature."""
    fl = FeatureList(args.project_dir)

    if not fl.exists():
        console.print(f"[red]Error:[/red] No features found in database for {args.project_dir}")
        return 1

    fl.load()

    feature = fl.get_feature(args.index)

    if not feature:
        console.print(f"[red]Error:[/red] Feature {args.index} not found")
        return 1

    # Display feature details
    status = "PASSING" if feature.passes else "FAILING"
    status_color = "green" if feature.passes else "red"

    content = Text()
    content.append(f"Index: ", style="bold")
    content.append(f"{feature.index}\n")
    content.append(f"Status: ", style="bold")
    content.append(f"{status}\n", style=status_color)
    content.append(f"Category: ", style="bold")
    content.append(f"{feature.category}\n")
    content.append(f"\nDescription:\n", style="bold")
    content.append(f"{feature.description}\n")
    content.append(f"\nTest Steps ({len(feature.steps)}):\n", style="bold")
    for i, step in enumerate(feature.steps, 1):
        content.append(f"  {i}. {step}\n")

    console.print(Panel(content, title=f"Feature #{feature.index}", border_style="blue"))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Search features by description."""
    fl = FeatureList(args.project_dir)

    if not fl.exists():
        console.print(f"[red]Error:[/red] No features found in database for {args.project_dir}")
        return 1

    fl.load()

    features = fl.search(args.query, limit=args.limit)

    if not features:
        console.print(f"[yellow]No features match '{args.query}'[/yellow]")
        return 0

    console.print(f"\n[bold]Found {len(features)} features matching '{args.query}':[/bold]\n")

    for f in features:
        status_icon = "✓" if f.passes else "○"
        status_style = "green" if f.passes else "red"
        console.print(f"  [{status_style}]{status_icon}[/] [dim]#{f.index}[/dim] {f.description[:70]}...")

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate the feature list for issues."""
    fl = FeatureList(args.project_dir)

    if not fl.exists():
        console.print(f"[red]Error:[/red] No features found in database for {args.project_dir}")
        return 1

    fl.load()

    is_valid, issues = fl.validate()

    if is_valid:
        console.print("[green]✓ Feature list is valid![/green]")
        stats = fl.get_stats()
        console.print(f"  {stats.total} features, {stats.passing} passing")
        return 0

    console.print(f"[red]✗ Found {len(issues)} issue(s):[/red]\n")
    for issue in issues[:20]:  # Limit to first 20
        console.print(f"  • {issue}")

    if len(issues) > 20:
        console.print(f"\n  ... and {len(issues) - 20} more issues")

    return 1


def cmd_mark(args: argparse.Namespace) -> int:
    """Mark a feature as passing or failing."""
    fl = FeatureList(args.project_dir)

    if not fl.exists():
        console.print(f"[red]Error:[/red] No features found in database for {args.project_dir}")
        return 1

    fl.load()

    feature = fl.get_feature(args.index)
    if not feature:
        console.print(f"[red]Error:[/red] Feature {args.index} not found")
        return 1

    if args.status == "passing":
        fl.mark_passing(args.index)
        new_status = "passing"
    else:
        fl.mark_failing(args.index)
        new_status = "failing"

    if fl.save():
        console.print(f"[green]✓[/green] Feature #{args.index} marked as {new_status}")
        return 0
    else:
        console.print(f"[red]Error:[/red] Failed to save changes")
        return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Feature List CLI - Manage project features in database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show statistics
  python feature_cli.py stats ./generations/my_project

  # List all failing features
  python feature_cli.py list ./generations/my_project --status failing

  # List functional features only
  python feature_cli.py list ./generations/my_project --category functional

  # Show next feature to implement
  python feature_cli.py next ./generations/my_project

  # Show specific feature
  python feature_cli.py show ./generations/my_project 42

  # Search for features
  python feature_cli.py search ./generations/my_project "authentication"

  # Validate the feature list
  python feature_cli.py validate ./generations/my_project

  # Mark feature as passing
  python feature_cli.py mark ./generations/my_project 42 passing
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show feature list statistics")
    stats_parser.add_argument("project_dir", type=Path, help="Project directory")

    # list command
    list_parser = subparsers.add_parser("list", help="List features")
    list_parser.add_argument("project_dir", type=Path, help="Project directory")
    list_parser.add_argument("--status", choices=["passing", "failing"], help="Filter by status")
    list_parser.add_argument("--category", choices=["functional", "style"], help="Filter by category")
    list_parser.add_argument("--limit", type=int, default=20, help="Maximum features to show (default: 20)")

    # next command
    next_parser = subparsers.add_parser("next", help="Show next incomplete feature")
    next_parser.add_argument("project_dir", type=Path, help="Project directory")
    next_parser.add_argument("--category", choices=["functional", "style"], help="Filter by category")

    # show command
    show_parser = subparsers.add_parser("show", help="Show details for a specific feature")
    show_parser.add_argument("project_dir", type=Path, help="Project directory")
    show_parser.add_argument("index", type=int, help="Feature index (0-based)")

    # search command
    search_parser = subparsers.add_parser("search", help="Search features by description")
    search_parser.add_argument("project_dir", type=Path, help="Project directory")
    search_parser.add_argument("query", type=str, help="Search query")
    search_parser.add_argument("--limit", type=int, default=10, help="Maximum results (default: 10)")

    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate feature list")
    validate_parser.add_argument("project_dir", type=Path, help="Project directory")

    # mark command
    mark_parser = subparsers.add_parser("mark", help="Mark feature as passing/failing")
    mark_parser.add_argument("project_dir", type=Path, help="Project directory")
    mark_parser.add_argument("index", type=int, help="Feature index (0-based)")
    mark_parser.add_argument("status", choices=["passing", "failing"], help="New status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # Dispatch to command handler
    handlers = {
        "stats": cmd_stats,
        "list": cmd_list,
        "next": cmd_next,
        "show": cmd_show,
        "search": cmd_search,
        "validate": cmd_validate,
        "mark": cmd_mark,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
