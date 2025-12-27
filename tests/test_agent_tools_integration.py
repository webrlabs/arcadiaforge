#!/usr/bin/env python3
"""
Integration Test: Agent Tool Testing
=====================================

This test creates a minimal agent session that instructs the coding agent
to systematically test all available MCP tools and report the results.

Usage:
    python -m pytest tests/test_agent_tools_integration.py -v

    Or run directly:
    python tests/test_agent_tools_integration.py
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime
import dotenv

dotenv.load_dotenv()

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from arcadiaforge.client import create_client
from arcadiaforge.output import (
    console,
    print_banner,
    print_header,
    print_subheader,
    print_success,
    print_error,
    print_warning,
    print_info,
    print_muted,
    print_divider,
)


# Test prompt that instructs the agent to test all tools
TOOL_TEST_PROMPT = """
You are testing the Arcadia Forge MCP tools. Your task is to systematically test each available tool and report the results.

## Available Tool Categories

### 1. Feature Tools (mcp__features__)
- feature_stats - Get statistics about features
- feature_next - Get the next feature to work on
- feature_show - Show details of a specific feature
- feature_list - List features with optional filters
- feature_search - Search features by keyword
- feature_mark - Mark a feature as passing
- feature_audit - Record an audit review
- feature_audit_list - List features by audit status

### 2. Progress Tools (mcp__progress__)
- progress_summary - Get progress summary
- progress_history - Get progress history

### 3. Troubleshooting Tools (mcp__troubleshooting__)
- troubleshoot_analyze - Analyze recent errors
- troubleshoot_suggest - Get suggestions for issues

### 4. Process Tools (mcp__processes__)
- process_list - List tracked processes
- process_stop - Stop a specific process
- process_stop_all - Stop all tracked processes
- process_stop_session - Stop processes from a session
- process_track - Manually track a process
- process_find_port - Find process using a port

## Your Task

1. First, create a simple feature_list.json file with 3 test features
2. Test each tool category systematically
3. For each tool, call it and verify it returns a reasonable response
4. Report any errors or unexpected behavior
5. At the end, provide a summary of which tools passed and which failed

## Important Notes
- Some tools may return "not found" or "empty" responses - that's OK if the tool works
- Focus on whether the tool executes without errors
- Do NOT test process_stop or process_stop_all with real PIDs unless you tracked them first
- For process_find_port, test with a common port like 3000 or 8080

Start by creating the test feature_list.json, then test each tool category.
"""


async def run_tool_test(project_dir: Path, model: str = "claude-sonnet-4-5-20250929") -> dict:
    """
    Run the agent tool testing session.

    Args:
        project_dir: Directory for the test project
        model: Claude model to use

    Returns:
        dict with test results
    """
    print_header("Agent Tool Integration Test")
    print_info(f"Project directory: {project_dir}")
    print_info(f"Model: {model}")
    print_divider()

    # Create the client
    client = create_client(project_dir, model)

    results = {
        "started_at": datetime.now().isoformat(),
        "project_dir": str(project_dir),
        "model": model,
        "messages": [],
        "tool_calls": [],
        "errors": [],
        "success": False,
    }

    try:
        async with client:
            print_info("Sending test prompt to agent...")
            await client.query(TOOL_TEST_PROMPT)

            print_subheader("Agent Response")

            async for message in client.receive_response():
                msg_type = type(message).__name__

                if msg_type == "TextBlock":
                    console.print(f"[af.muted]{message.text}[/]")
                    results["messages"].append({
                        "type": "text",
                        "content": message.text
                    })

                elif msg_type == "ToolUseBlock":
                    tool_name = message.name
                    print_info(f"Tool call: {tool_name}")
                    results["tool_calls"].append({
                        "tool": tool_name,
                        "input": str(message.input)[:200]
                    })

                elif msg_type == "ToolResultBlock":
                    # Tool results are handled by the SDK
                    pass

                elif msg_type == "ErrorBlock":
                    print_error(f"Error: {message.error}")
                    results["errors"].append(str(message.error))

            results["success"] = len(results["errors"]) == 0
            results["completed_at"] = datetime.now().isoformat()

    except Exception as e:
        print_error(f"Test failed with exception: {e}")
        results["errors"].append(str(e))
        results["success"] = False

    return results


def print_test_summary(results: dict) -> None:
    """Print a summary of the test results."""
    print_divider()
    print_header("Test Summary")

    # Tool calls
    print_subheader(f"Tool Calls ({len(results['tool_calls'])})")
    tool_counts = {}
    for call in results["tool_calls"]:
        tool = call["tool"]
        tool_counts[tool] = tool_counts.get(tool, 0) + 1

    for tool, count in sorted(tool_counts.items()):
        console.print(f"  [af.muted]{tool}:[/] [af.number]{count}[/]")

    # Errors
    if results["errors"]:
        print_subheader(f"Errors ({len(results['errors'])})")
        for error in results["errors"]:
            print_error(f"  {error[:100]}...")

    # Final status
    print_divider()
    if results["success"]:
        print_success("Test completed successfully!")
    else:
        print_error("Test completed with errors.")


async def main():
    """Main entry point for the test."""
    print_banner(version="Tool Test", subtitle="Testing MCP tool integration")
    console.print()

    # Check for API token
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        print_error("CLAUDE_CODE_OAUTH_TOKEN not set")
        print_muted("Please set your API token to run this test.")
        sys.exit(1)

    # Create a temporary project directory
    with tempfile.TemporaryDirectory(prefix="arcadia_test_") as tmpdir:
        project_dir = Path(tmpdir)

        # Run the test
        results = await run_tool_test(project_dir)

        # Print summary
        print_test_summary(results)

        # Save results
        results_file = Path("test_results.json")
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print_info(f"Results saved to: {results_file}")

        return 0 if results["success"] else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
