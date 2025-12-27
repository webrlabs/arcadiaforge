#!/usr/bin/env python
"""
Autonomous Coding Agent Demo
============================

A minimal harness demonstrating long-running autonomous coding with Claude.
This script implements the two-agent pattern (initializer + coding agent) and
incorporates all the strategies from the long-running agents guide.

Example Usage:
    python autonomous_agent.py --project-dir ./claude_clone_demo
    python autonomous_agent.py --project-dir ./claude_clone_demo --max-iterations 5
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv

from arcadiaforge import __version__
from arcadiaforge.config import get_default_model
from arcadiaforge.orchestrator import SessionOrchestrator
from arcadiaforge.check_deps import check_external_deps
from arcadiaforge.client import DEFAULT_MCP_CONFIG
from arcadiaforge.output import (
    print_banner,
    console,
    print_success,
    print_error,
    print_warning,
    print_muted,
)

load_dotenv()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    default_model = get_default_model()
    
    parser = argparse.ArgumentParser(
        description="Autonomous Coding Agent Demo - Long-running agent harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Start fresh project
  python autonomous_agent.py --project-dir ./claude_clone

  # Use a specific model
  python autonomous_agent.py --project-dir ./claude_clone --model {default_model}

  # Limit iterations for testing
  python autonomous_agent.py --project-dir ./claude_clone --max-iterations 5

  # Continue existing project
  python autonomous_agent.py --project-dir ./claude_clone

  # Add new requirements to an existing project
  python autonomous_agent.py --project-dir ./claude_clone --new-requirements ./new_features.txt

  # Use a custom app spec file
  python autonomous_agent.py --project-dir ./my_app --app-spec ./my_app_spec.txt

Environment Variables:
  CLAUDE_CODE_OAUTH_TOKEN    Your Anthropic API key (required)
  ARCADIA_MODEL              Default Claude model (current: {default_model})
        """,
    )

    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path("./autonomous_demo_project"),
        help="Directory for the project (default: generations/autonomous_demo_project). Relative paths automatically placed in generations/ directory.",
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum number of agent iterations (default: unlimited)",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=default_model,
        help=f"Claude model to use (default: {default_model})",
    )

    parser.add_argument(
        "--new-requirements",
        type=Path,
        default=None,
        help="Path to a new requirements file to add to an existing project. The agent will add new features to the database based on this file.",
    )

    parser.add_argument(
        "--num-new-features",
        type=int,
        default=None,
        help="Number of new features/tests to add from the new requirements file. If not specified, the agent decides based on the requirements complexity.",
    )

    parser.add_argument(
        "--max-no-progress",
        type=int,
        default=3,
        help="Stop after this many iterations with no progress (default: 3). Set to 0 to disable.",
    )

    parser.add_argument(
        "--audit-cadence",
        type=int,
        default=10,
        help="Run audit every N completed features (default: 10). Set to 0 to disable.",
    )

    parser.add_argument(
        "--app-spec",
        type=Path,
        default=None,
        help="Path to a custom app specification file. If not specified, uses the packaged app spec.",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output (show all tool calls and agent reasoning)",
    )

    parser.add_argument(
        "--live-terminal",
        action="store_true",
        help="Enable live terminal with persistent input for user feedback during agent execution",
    )

    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Set verbosity
    from arcadiaforge.output import set_verbose
    set_verbose(args.verbose)

    # Print banner
    print_banner(version=f"v{__version__}")
    console.print()

    # Perform dependency checks
    if not check_external_deps():
        print_error("Dependency check failed. Please install required tools and try again.")
        return

    # Check for API key
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        print_error("CLAUDE_CODE_OAUTH_TOKEN environment variable not set")
        console.print("\nGet your token by running: [af.accent]claude setup-token[/]")
        console.print("\nThen set it in your .env file or environment:")
        print_muted("  export CLAUDE_CODE_OAUTH_TOKEN='your-token-here'")
        return

    # Ensure mcp_config.json exists (use 'x' mode for atomic creation)
    config_path = Path("mcp_config.json")
    try:
        with open(config_path, "x") as f:
            json.dump(DEFAULT_MCP_CONFIG, f, indent=2)
        print_success(f"Created default MCP configuration at {config_path}")
        print_muted("Edit this file to enable/disable specific MCP servers (GitHub, Brave Search, etc.)")
    except FileExistsError:
        pass  # Config already exists, nothing to do

    # Validate new-requirements file exists if provided
    new_requirements = args.new_requirements
    if new_requirements and not new_requirements.exists():
        print_error(f"New requirements file not found: {new_requirements}")
        return

    # Validate app-spec file exists if provided
    app_spec = args.app_spec
    if app_spec and not app_spec.exists():
        print_error(f"App spec file not found: {app_spec}")
        return

    # Automatically place projects in generations/ directory unless already specified
    project_dir = args.project_dir
    if "generations" not in project_dir.parts and not project_dir.is_absolute():
        # Prepend generations/ to relative paths that aren't already under generations/
        project_dir = Path("generations") / project_dir

    # Run the agent
    try:
        orchestrator = SessionOrchestrator(
            project_dir=project_dir,
            model=args.model,
            max_iterations=args.max_iterations,
            max_no_progress=args.max_no_progress,
            audit_cadence=args.audit_cadence,
            enable_live_terminal=args.live_terminal,
        )

        asyncio.run(
            orchestrator.run(
                new_requirements_path=new_requirements,
                num_new_features=args.num_new_features,
                app_spec_path=app_spec,
            )
        )
    except KeyboardInterrupt:
        console.print()
        print_warning("Interrupted by user")
        print_muted("To resume, run the same command again")
    except Exception as e:
        console.print()
        print_error(f"Fatal error: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
