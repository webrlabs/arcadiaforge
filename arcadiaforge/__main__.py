"""
Entry point for running arcadiaforge as a module.

Usage:
    python -m arcadiaforge [args]           # Run the agent
    python -m arcadiaforge cleanup          # Clean up tracked processes
    python -m arcadiaforge processes        # Show tracked processes
    python -m arcadiaforge dashboard        # Start the web dashboard

This is equivalent to:
    python -m arcadiaforge.cli.autonomous_agent [args]
"""

import sys


def main():
    """Main entry point with subcommand support."""
    # Check for subcommands
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()

        if cmd == "cleanup":
            # Clean up tracked processes
            from pathlib import Path
            from arcadiaforge.process_tracker import ProcessTracker

            # Parse --project-dir if provided
            project_dir = Path.cwd()
            if "--project-dir" in sys.argv or "-p" in sys.argv:
                try:
                    idx = sys.argv.index("--project-dir") if "--project-dir" in sys.argv else sys.argv.index("-p")
                    project_dir = Path(sys.argv[idx + 1])
                except (IndexError, ValueError):
                    pass

            # Also check in generations/ directory
            if not (project_dir / ".processes.json").exists():
                gen_dir = Path("generations") / project_dir.name
                if (gen_dir / ".processes.json").exists():
                    project_dir = gen_dir

            tracker = ProcessTracker(project_dir)
            tracker.cleanup_interactive()
            return

        elif cmd == "processes":
            # Show tracked processes
            from pathlib import Path
            from arcadiaforge.process_tracker import ProcessTracker

            project_dir = Path.cwd()
            if "--project-dir" in sys.argv or "-p" in sys.argv:
                try:
                    idx = sys.argv.index("--project-dir") if "--project-dir" in sys.argv else sys.argv.index("-p")
                    project_dir = Path(sys.argv[idx + 1])
                except (IndexError, ValueError):
                    pass

            # Also check in generations/ directory
            if not (project_dir / ".processes.json").exists():
                gen_dir = Path("generations") / project_dir.name
                if (gen_dir / ".processes.json").exists():
                    project_dir = gen_dir

            tracker = ProcessTracker(project_dir)
            tracker.print_status()
            return

        elif cmd == "dashboard":
            # Start the web dashboard
            from pathlib import Path
            from arcadiaforge.web.dashboard import start_dashboard

            # Parse arguments
            project_dir = Path.cwd()
            port = 8080
            no_browser = False

            i = 2
            while i < len(sys.argv):
                arg = sys.argv[i]
                if arg in ("--project-dir", "-p") and i + 1 < len(sys.argv):
                    project_dir = Path(sys.argv[i + 1])
                    i += 2
                elif arg in ("--port",) and i + 1 < len(sys.argv):
                    port = int(sys.argv[i + 1])
                    i += 2
                elif arg == "--no-browser":
                    no_browser = True
                    i += 1
                else:
                    i += 1

            # Check generations/ directory
            if not (project_dir / ".arcadia").exists():
                gen_dir = Path("generations") / project_dir.name
                if (gen_dir / ".arcadia").exists():
                    project_dir = gen_dir

            print(f"Starting dashboard for: {project_dir}")
            start_dashboard(port=port, project_dir=project_dir, open_browser=not no_browser)
            return

    # Default: run the agent
    from arcadiaforge.cli.autonomous_agent import main as agent_main
    agent_main()


if __name__ == "__main__":
    main()
