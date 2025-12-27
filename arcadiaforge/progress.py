"""
Progress Tracking Utilities
===========================

Functions for tracking and displaying progress of the autonomous coding agent.
"""

from pathlib import Path

from arcadiaforge.feature_list import FeatureList
from arcadiaforge.output import print_session_header as _print_session_header
from arcadiaforge.output import print_progress_bar, print_final_summary


def count_passing_tests(project_dir: Path) -> tuple[int, int]:
    """
    Count passing and total tests from the database.

    Args:
        project_dir: Directory containing the project

    Returns:
        (passing_count, total_count)
    """
    fl = FeatureList(project_dir)
    if not fl.exists():
        return 0, 0

    fl.load()
    stats = fl.get_stats()
    return stats.passing, stats.total


def print_session_header(session_num: int, is_initializer: bool) -> None:
    """Print a formatted header for the session."""
    session_type = "INITIALIZER" if is_initializer else "CODING AGENT"
    _print_session_header(session_num, session_type)


def print_progress_summary(project_dir: Path) -> None:
    """Print a summary of current progress."""
    passing, total = count_passing_tests(project_dir)
    print_progress_bar(passing, total)
