#!/usr/bin/env python
"""
Checkpoint CLI - View and manage checkpoints from autonomous coding sessions.

Usage:
    checkpoint-cli list [--project-dir DIR] [--limit N]
    checkpoint-cli show CHECKPOINT_ID [--project-dir DIR]
    checkpoint-cli diff CHECKPOINT_ID [--project-dir DIR]
    checkpoint-cli rollback CHECKPOINT_ID [--project-dir DIR] [--dry-run]
    checkpoint-cli create [--note NOTE] [--project-dir DIR]
    checkpoint-cli clean [--keep N] [--project-dir DIR]
"""

import argparse
import sys
from pathlib import Path

from arcadiaforge.checkpoint import CheckpointManager, CheckpointTrigger, Checkpoint
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
    print_diff,
    create_table,
    print_table,
    confirm,
    spinner,
    icon,
)


def format_checkpoint_row(checkpoint: Checkpoint) -> tuple:
    """Format a checkpoint as table row data."""
    trigger = checkpoint.trigger
    time_str = checkpoint.timestamp[:19]
    session = str(checkpoint.session_id)
    passing = checkpoint.features_passing
    total = checkpoint.features_total

    # Status indicator
    if checkpoint.git_clean:
        git_status = f"[af.ok]{icon('check')}[/]"
    else:
        git_status = f"[af.warn]{icon('warning')}[/]"

    # Progress
    if total > 0:
        pct = (passing / total) * 100
        if pct >= 100:
            progress = f"[af.ok]{passing}/{total}[/]"
        elif pct >= 50:
            progress = f"[af.warn]{passing}/{total}[/]"
        else:
            progress = f"[af.info]{passing}/{total}[/]"
    else:
        progress = "[af.muted]0/0[/]"

    return (
        f"[af.accent]{checkpoint.checkpoint_id}[/]",
        f"[af.timestamp]{time_str}[/]",
        session,
        trigger,
        progress,
        git_status,
    )


def cmd_list(args):
    """List all checkpoints."""
    import asyncio
    mgr = CheckpointManager(args.project_dir)

    with spinner("Loading checkpoints..."):
        checkpoints = asyncio.run(mgr.list_checkpoints(limit=args.limit))

    if not checkpoints:
        print_info("No checkpoints found")
        return 0

    print_header(f"Checkpoints ({len(checkpoints)})")

    table = create_table(columns=["ID", "Timestamp", "Session", "Trigger", "Features", "Git"])

    for cp in checkpoints:
        table.add_row(*format_checkpoint_row(cp))

    print_table(table)

    # Show notes if any
    notes = [cp for cp in checkpoints if cp.human_note]
    if notes:
        console.print()
        print_subheader("Notes")
        for cp in notes:
            console.print(f"  [af.accent]{cp.checkpoint_id}[/]: [af.muted]{cp.human_note}[/]")

    return 0


def cmd_show(args):
    """Show detailed info for a specific checkpoint."""
    import asyncio
    mgr = CheckpointManager(args.project_dir)

    with spinner("Loading checkpoint..."):
        checkpoint = asyncio.run(mgr.get_checkpoint(args.checkpoint_id))

    if not checkpoint:
        print_error(f"Checkpoint '{args.checkpoint_id}' not found")
        return 1

    print_header(f"Checkpoint: {checkpoint.checkpoint_id}")

    # Basic info
    print_key_value_table({
        "Timestamp": checkpoint.timestamp,
        "Trigger": checkpoint.trigger,
        "Session ID": str(checkpoint.session_id),
    }, title="Basic Info")

    console.print()

    # Git state
    git_clean = f"[af.ok]Yes[/]" if checkpoint.git_clean else f"[af.warn]No[/]"
    print_key_value_table({
        "Commit": checkpoint.git_commit[:12] if checkpoint.git_commit else "N/A",
        "Branch": checkpoint.git_branch or "N/A",
        "Clean": git_clean,
    }, title="Git State")

    console.print()

    # Feature status
    print_subheader("Feature Status")
    print_progress_bar(checkpoint.features_passing, checkpoint.features_total, "Progress")

    if checkpoint.last_successful_feature is not None:
        console.print(f"[af.muted]Last Success:[/] Feature #{checkpoint.last_successful_feature}")

    # Feature details (if not too many)
    if checkpoint.feature_status and len(checkpoint.feature_status) <= 50:
        console.print()
        print_subheader("Feature Details")

        table = create_table(columns=["#", "Status"])
        for idx, status in sorted(checkpoint.feature_status.items(), key=lambda x: int(x[0])):
            if status:
                status_str = f"[af.ok]{icon('check')} Pass[/]"
            else:
                status_str = f"[af.err]{icon('cross')} Fail[/]"
            table.add_row(f"#{idx}", status_str)

        print_table(table)

    # Pending work
    if checkpoint.pending_work:
        console.print()
        print_subheader("Pending Work")
        for item in checkpoint.pending_work:
            console.print(f"  [af.accent]{icon('bullet')}[/] {item}")

    # Human note
    if checkpoint.human_note:
        console.print()
        print_panel(checkpoint.human_note, title="Note", border_style="af.info")

    # Metadata
    if checkpoint.metadata:
        console.print()
        print_key_value_table(checkpoint.metadata, title="Metadata")

    console.print()
    print_muted(f"Files Hash: {checkpoint.files_hash}")

    return 0


def cmd_diff(args):
    """Show diff between checkpoint and current state."""
    import subprocess
    import asyncio

    mgr = CheckpointManager(args.project_dir)

    with spinner("Loading checkpoint..."):
        checkpoint = asyncio.run(mgr.get_checkpoint(args.checkpoint_id))

    if not checkpoint:
        print_error(f"Checkpoint '{args.checkpoint_id}' not found")
        return 1

    print_header(f"Diff: {args.checkpoint_id} -> Current")

    # Get current git commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=args.project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        current_commit = result.stdout.strip() if result.returncode == 0 else "unknown"
    except Exception:
        current_commit = "unknown"

    console.print(f"[af.muted]Git:[/] {checkpoint.git_commit[:8]} [af.accent]->[/] {current_commit[:8]}")
    console.print()

    # Compare feature status
    current_status, current_passing, current_total = _get_current_features(args.project_dir)

    newly_passing = []
    newly_failing = []

    for idx_str, passes in current_status.items():
        idx = int(idx_str) if isinstance(idx_str, str) else idx_str
        prev_passes = checkpoint.feature_status.get(str(idx), checkpoint.feature_status.get(idx, False))

        if passes and not prev_passes:
            newly_passing.append(idx)
        elif not passes and prev_passes:
            newly_failing.append(idx)

    if newly_passing:
        print_subheader(f"Newly Passing ({len(newly_passing)})")
        for idx in sorted(newly_passing):
            console.print(f"  [af.ok]+[/] Feature #{idx}")
        console.print()

    if newly_failing:
        print_subheader(f"Newly Failing ({len(newly_failing)})")
        for idx in sorted(newly_failing):
            console.print(f"  [af.err]-[/] Feature #{idx}")
        console.print()

    if not newly_passing and not newly_failing:
        print_info("No feature status changes")
        console.print()

    # Progress comparison
    console.print(f"[af.muted]Features:[/] {checkpoint.features_passing}/{checkpoint.features_total} [af.accent]->[/] {current_passing}/{current_total}")

    # Git diff
    if checkpoint.git_commit != "unknown" and current_commit != "unknown":
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", checkpoint.git_commit, current_commit],
                cwd=args.project_dir,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                console.print()
                print_subheader("Git Changes")
                diff_output = result.stdout
                if len(diff_output) > 3000:
                    diff_output = diff_output[:3000] + "\n... (truncated)"
                print_diff(diff_output)
        except Exception:
            pass

    return 0


def _get_current_features(project_dir: Path) -> tuple[dict, int, int]:
    """Get current feature status from database."""
    from arcadiaforge.feature_list import FeatureList

    try:
        fl = FeatureList(project_dir)
        if not fl.exists():
            return {}, 0, 0

        fl.load()
        stats = fl.get_stats()

        status = {}
        for feature in fl._features:
            status[feature.index] = feature.passes

        return status, stats.passing, stats.total
    except Exception:
        return {}, 0, 0


def cmd_rollback(args):
    """Rollback to a checkpoint."""
    import asyncio
    mgr = CheckpointManager(args.project_dir)

    with spinner("Loading checkpoint..."):
        checkpoint = asyncio.run(mgr.get_checkpoint(args.checkpoint_id))

    if not checkpoint:
        print_error(f"Checkpoint '{args.checkpoint_id}' not found")
        return 1

    print_header(f"Rollback to: {args.checkpoint_id}")

    print_key_value_table({
        "Timestamp": checkpoint.timestamp,
        "Git commit": checkpoint.git_commit[:12],
        "Features": f"{checkpoint.features_passing}/{checkpoint.features_total}",
    })
    console.print()

    if args.dry_run:
        print_warning("[DRY RUN] Would execute:")
        console.print(f"  [af.accent]git reset --hard {checkpoint.git_commit}[/]")
        console.print()
        print_muted("Run without --dry-run to actually perform rollback")
        return 0

    # Confirm
    if not confirm("Are you sure you want to rollback? This will discard changes"):
        print_info("Rollback cancelled")
        return 0

    with spinner("Rolling back..."):
        result = mgr.rollback_to(args.checkpoint_id)

    if result.success:
        print_success(f"Rollback successful: {result.message}")
        return 0
    else:
        print_error(f"Rollback failed: {result.message}")
        return 1


def cmd_create(args):
    """Create a manual checkpoint."""
    mgr = CheckpointManager(args.project_dir)

    with spinner("Creating checkpoint..."):
        checkpoint = mgr.create_checkpoint(
            trigger=CheckpointTrigger.MANUAL,
            session_id=0,  # Manual checkpoint outside session
            human_note=args.note,
            metadata={"source": "cli"},
        )

    if checkpoint:
        print_success(f"Checkpoint created: {checkpoint.checkpoint_id}")
        print_key_value_table({
            "Git commit": checkpoint.git_commit[:12],
            "Features": f"{checkpoint.features_passing}/{checkpoint.features_total}",
            "Note": args.note or "[none]",
        })
        return 0
    else:
        print_error("Failed to create checkpoint")
        return 1


def cmd_clean(args):
    """Clean old checkpoints, keeping the most recent N."""
    import asyncio
    mgr = CheckpointManager(args.project_dir)

    with spinner("Analyzing checkpoints..."):
        all_checkpoints = asyncio.run(mgr.list_checkpoints(limit=None))

    if len(all_checkpoints) <= args.keep:
        print_info(f"Only {len(all_checkpoints)} checkpoints exist, keeping all")
        return 0

    to_remove = len(all_checkpoints) - args.keep

    print_header("Checkpoint Cleanup")
    console.print(f"[af.muted]Total checkpoints:[/] {len(all_checkpoints)}")
    console.print(f"[af.muted]Will remove:[/] [af.warn]{to_remove}[/]")
    console.print(f"[af.muted]Will keep:[/] [af.ok]{args.keep}[/]")
    console.print()

    if args.dry_run:
        print_warning("[DRY RUN] Would remove:")
        for cp in all_checkpoints[args.keep:]:
            console.print(f"  [af.err]-[/] {cp.checkpoint_id} [af.timestamp]({cp.timestamp[:19]})[/]")
        return 0

    if not confirm("Are you sure you want to remove these checkpoints?"):
        print_info("Cancelled")
        return 0

    # Remove old checkpoints
    removed = 0
    with spinner("Removing checkpoints..."):
        for cp in all_checkpoints[args.keep:]:
            if mgr.delete_checkpoint(cp.checkpoint_id):
                removed += 1

    print_success(f"Removed {removed} checkpoints")
    return 0


def cmd_stats(args):
    """Show checkpoint statistics."""
    import asyncio
    mgr = CheckpointManager(args.project_dir)

    with spinner("Calculating statistics..."):
        checkpoints = asyncio.run(mgr.list_checkpoints(limit=None))

    if not checkpoints:
        print_info("No checkpoints found")
        return 0

    # Aggregate stats
    total = len(checkpoints)
    by_trigger = {}
    by_session = {}

    for cp in checkpoints:
        trigger = cp.trigger
        by_trigger[trigger] = by_trigger.get(trigger, 0) + 1

        session = cp.session_id
        if session > 0:
            by_session[session] = by_session.get(session, 0) + 1

    print_header("Checkpoint Statistics")

    console.print(f"[af.muted]Total checkpoints:[/] [af.number]{total}[/]")
    console.print()

    # By trigger table
    print_subheader("By Trigger")
    table = create_table(columns=["Trigger", "Count"])
    for trigger, count in sorted(by_trigger.items()):
        table.add_row(trigger, f"[af.number]{count}[/]")
    print_table(table)

    if by_session:
        console.print()
        console.print(f"[af.muted]Sessions with checkpoints:[/] [af.number]{len(by_session)}[/]")
        console.print(f"[af.muted]Average per session:[/] [af.number]{total / len(by_session):.1f}[/]")

    # Latest checkpoint info
    latest = checkpoints[0] if checkpoints else None
    if latest:
        console.print()
        print_subheader("Latest Checkpoint")
        print_key_value_table({
            "ID": latest.checkpoint_id,
            "Time": latest.timestamp[:19],
            "Features": f"{latest.features_passing}/{latest.features_total}",
        })

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="View and manage checkpoints from autonomous coding sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path("."),
        help="Project directory containing the .arcadia database (default: current dir)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # list command
    list_parser = subparsers.add_parser("list", help="List all checkpoints")
    list_parser.add_argument("--limit", "-n", type=int, default=20, help="Max checkpoints to show")

    # show command
    show_parser = subparsers.add_parser("show", help="Show checkpoint details")
    show_parser.add_argument("checkpoint_id", help="Checkpoint ID to show")

    # diff command
    diff_parser = subparsers.add_parser("diff", help="Show diff from checkpoint to current")
    diff_parser.add_argument("checkpoint_id", help="Checkpoint ID to diff from")

    # rollback command
    rollback_parser = subparsers.add_parser("rollback", help="Rollback to a checkpoint")
    rollback_parser.add_argument("checkpoint_id", help="Checkpoint ID to rollback to")
    rollback_parser.add_argument("--dry-run", action="store_true", help="Show what would happen")

    # create command
    create_parser = subparsers.add_parser("create", help="Create a manual checkpoint")
    create_parser.add_argument("--note", "-m", help="Human-readable note for the checkpoint")

    # clean command
    clean_parser = subparsers.add_parser("clean", help="Remove old checkpoints")
    clean_parser.add_argument("--keep", "-k", type=int, default=10, help="Number of checkpoints to keep")
    clean_parser.add_argument("--dry-run", action="store_true", help="Show what would be removed")

    # stats command
    stats_parser = subparsers.add_parser("stats", help="Show checkpoint statistics")

    args = parser.parse_args()

    if not args.command:
        print_banner(version="Checkpoint CLI", subtitle="Manage coding session checkpoints")
        console.print()
        parser.print_help()
        return 1

    commands = {
        "list": cmd_list,
        "show": cmd_show,
        "diff": cmd_diff,
        "rollback": cmd_rollback,
        "create": cmd_create,
        "clean": cmd_clean,
        "stats": cmd_stats,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
