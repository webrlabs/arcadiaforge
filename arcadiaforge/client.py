"""
Claude SDK Client Configuration
===============================

Functions for creating and configuring the Claude Agent SDK client.
"""

import copy
import json
import os
import platform
from pathlib import Path
from typing import Dict, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from arcadiaforge.project_analyzer import ProjectAnalysis
from dotenv import load_dotenv

from claude_code_sdk import ClaudeCodeOptions, ClaudeSDKClient
from claude_code_sdk.types import HookMatcher

from arcadiaforge.security import bash_security_hook
from arcadiaforge.feature_tools import create_feature_tools_server, FEATURE_TOOLS
from arcadiaforge.progress_tools import create_progress_tools_server, PROGRESS_TOOLS
from arcadiaforge.troubleshooting_tools import create_troubleshooting_tools_server, TROUBLESHOOTING_TOOLS
from arcadiaforge.image_tools import create_image_tools_server, IMAGE_TOOLS
from arcadiaforge.messaging_tools import create_messaging_server, MESSAGING_TOOLS
from arcadiaforge.capability_tools import create_capability_server, CAPABILITY_TOOLS
from arcadiaforge.file_tools import create_file_tools_server, FILE_TOOLS
from arcadiaforge.puppeteer_helpers import create_puppeteer_helpers_server, PUPPETEER_HELPER_TOOLS
from arcadiaforge.evidence_tools import create_evidence_tools_server, EVIDENCE_TOOLS
from arcadiaforge.native_screenshot import create_native_screenshot_server, NATIVE_SCREENSHOT_TOOLS
from arcadiaforge.capabilities import configure_capabilities_for_project
from arcadiaforge.db import init_db
from arcadiaforge.process_tools import (
    create_process_tools_server,
    PROCESS_TOOLS,
    process_tracking_hook,
    set_session_id as set_process_session_id,
)
from arcadiaforge.server_tools import (
    create_server_tools_server,
    SERVER_TOOLS,
    set_session_id as set_server_session_id,
)
from arcadiaforge.screenshot_hook import screenshot_saver_hook
from arcadiaforge.output import (
    console,
    print_success,
    print_warning,
    print_info,
    print_muted,
    print_subheader,
    icon,
)

load_dotenv()

# =============================================================================
# Tool Definitions
# =============================================================================

# Puppeteer MCP tools
PUPPETEER_TOOLS = [
    "mcp__puppeteer__puppeteer_navigate",
    "mcp__puppeteer__puppeteer_screenshot",
    "mcp__puppeteer__puppeteer_click",
    "mcp__puppeteer__puppeteer_fill",
    "mcp__puppeteer__puppeteer_select",
    "mcp__puppeteer__puppeteer_hover",
    "mcp__puppeteer__puppeteer_evaluate",
]

# GitHub MCP tools
GITHUB_TOOLS = [
    "mcp__github__create_issue",
    "mcp__github__list_issues",
    "mcp__github__update_issue",
    "mcp__github__add_issue_comment",
    "mcp__github__search_repositories",
    "mcp__github__create_repository",
    "mcp__github__get_file_contents",
    "mcp__github__create_or_update_file",
    "mcp__github__push_files",
    "mcp__github__create_pull_request",
    "mcp__github__list_pull_requests",
    "mcp__github__get_pull_request",
    "mcp__github__merge_pull_request",
    "mcp__github__get_branch",
    "mcp__github__list_branches",
    "mcp__github__list_commits",
]

# Brave Search MCP tools
SEARCH_TOOLS = [
    "mcp__search__brave_web_search",
    "mcp__search__brave_local_search",
]

# Fetch MCP tools
FETCH_TOOLS = [
    "mcp__fetch__fetch",
]

# PostgreSQL MCP tools
POSTGRES_TOOLS = [
    "mcp__postgres__query",
    "mcp__postgres__get_table_schema",
    "mcp__postgres__list_tables",
]

# SQLite MCP tools
SQLITE_TOOLS = [
    "mcp__sqlite__query",
    "mcp__sqlite__get_table_schema",
    "mcp__sqlite__list_tables",
]

# Built-in tools
BUILTIN_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Bash",
]

# Default MCP Configuration
DEFAULT_MCP_CONFIG = {
    "puppeteer": {
        "enabled": True,
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "tools": PUPPETEER_TOOLS
    },
    "github": {
        "enabled": False,  # Disabled by default, requires token
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env_vars": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
        "tools": GITHUB_TOOLS
    },
    "search": {
        "enabled": False,  # Disabled by default, requires key
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env_vars": ["BRAVE_API_KEY"],
        "tools": SEARCH_TOOLS
    },
    "fetch": {
        "enabled": True,   # Enabled by default, no key needed
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-fetch"],
        "tools": FETCH_TOOLS
    },
    "postgres": {
        "enabled": False,  # Disabled by default, requires DB URL
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres"],
        "args_append_env": ["POSTGRES_URL"],  # Append env var value to args
        "tools": POSTGRES_TOOLS
    },
    "sqlite": {
        "enabled": False,
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite"],
        "args_append_env": ["SQLITE_FILE"],
        "tools": SQLITE_TOOLS
    }
}


def load_mcp_config() -> Dict[str, Any]:
    """
    Load MCP configuration from mcp_config.json or return defaults.
    """
    config_path = Path.cwd() / "mcp_config.json"
    config = copy.deepcopy(DEFAULT_MCP_CONFIG)

    if config_path.exists():
        try:
            with open(config_path, "r") as f:
                user_config = json.load(f)
                # Deep merge or simple update? Simple update for now.
                for key, value in user_config.items():
                    if key in config:
                        config[key].update(value)
                    else:
                        config[key] = value
            print_info(f"Loaded MCP config from {config_path}")
        except Exception as e:
            print_warning(f"Failed to load mcp_config.json: {e}")
            print_muted("Using default configuration.")
    
    return config


def create_client(
    project_dir: Path,
    model: str,
    project_analysis: Optional["ProjectAnalysis"] = None
) -> ClaudeSDKClient:
    """
    Create a Claude Agent SDK client with multi-layered security.

    Args:
        project_dir: Directory for the project
        model: Claude model to use
        project_analysis: Optional analysis result for tool configuration

    Returns:
        Configured ClaudeSDKClient
    """
    # Load MCP configuration (user can override via mcp_config.json)
    mcp_config = load_mcp_config()

    # If project analysis is available, use it to configure MCP servers
    # Otherwise fall back to mcp_config.json or defaults
    if project_analysis is not None:
        profile = project_analysis.profile
        # Override mcp_config with analysis results (unless user explicitly set them)
        if "puppeteer" not in mcp_config or mcp_config.get("puppeteer", {}).get("enabled") is None:
            mcp_config["puppeteer"] = {"enabled": profile.puppeteer_enabled}
        puppeteer_enabled = profile.puppeteer_enabled
        print_info(f"Tool profile: {profile.name} (Puppeteer: {'enabled' if puppeteer_enabled else 'disabled'})")
    else:
        puppeteer_enabled = mcp_config.get("puppeteer", {}).get("enabled", True)

    # Configure capabilities based on Puppeteer usage
    # If Puppeteer is disabled, node/npx are not required
    configure_capabilities_for_project(puppeteer_enabled=puppeteer_enabled)

    # Prepare lists for configuration
    active_mcp_servers = {}
    active_tools = [
        *BUILTIN_TOOLS,
        *FEATURE_TOOLS,
        *PROGRESS_TOOLS,
        *TROUBLESHOOTING_TOOLS,
        *PROCESS_TOOLS,
        *SERVER_TOOLS,
        *IMAGE_TOOLS,
        *MESSAGING_TOOLS,
        *CAPABILITY_TOOLS,
        *FILE_TOOLS,
        *PUPPETEER_HELPER_TOOLS,
        *EVIDENCE_TOOLS,
        *NATIVE_SCREENSHOT_TOOLS,
    ]
    
    # Platform specific check for npx command
    is_windows = platform.system().lower() == "windows"
    
    # Process external MCP servers
    print_subheader("Configuring MCP Servers")
    for name, server_config in mcp_config.items():
        if not server_config.get("enabled", False):
            console.print(f"  [af.muted]{icon('bullet')} {name}: Disabled[/]")
            continue

        # Prepare server definition
        server_def = {
            "command": server_config["command"],
            "args": server_config["args"].copy()
        }

        # Inject environment variables
        env = {}
        missing_env = False
        for env_var in server_config.get("env_vars", []):
            val = os.environ.get(env_var)
            if val:
                env[env_var] = val
            else:
                console.print(f"  [af.warn]{icon('warning')} {name}: Missing {env_var}[/]")
                missing_env = True

        # Some servers take config as args (like postgres/sqlite)
        for env_var in server_config.get("args_append_env", []):
             val = os.environ.get(env_var)
             if val:
                 server_def["args"].append(val)
             else:
                 console.print(f"  [af.warn]{icon('warning')} {name}: Missing {env_var} for args[/]")
                 missing_env = True

        if missing_env:
            console.print(f"  [af.muted]{icon('bullet')} {name}: Skipped (Missing Config)[/]")
            continue

        if env:
            server_def["env"] = env

        # Add to active servers
        active_mcp_servers[name] = server_def

        # Add tools
        tools = server_config.get("tools", [])
        active_tools.extend(tools)
        console.print(f"  [af.ok]{icon('check')} {name}:[/] [af.number]{len(tools)}[/] [af.muted]tools[/]")

    # Add internal Python MCP servers
    active_mcp_servers["features"] = create_feature_tools_server(project_dir)
    active_mcp_servers["progress"] = create_progress_tools_server(project_dir)
    active_mcp_servers["troubleshooting"] = create_troubleshooting_tools_server(project_dir)
    active_mcp_servers["processes"] = create_process_tools_server(project_dir)
    active_mcp_servers["servers"] = create_server_tools_server(project_dir)
    active_mcp_servers["images"] = create_image_tools_server(project_dir)
    active_mcp_servers["messaging"] = create_messaging_server(project_dir)
    active_mcp_servers["capabilities"] = create_capability_server(project_dir)
    active_mcp_servers["file-operations"] = create_file_tools_server(project_dir)
    active_mcp_servers["puppeteer-helpers"] = create_puppeteer_helpers_server(project_dir)
    active_mcp_servers["evidence"] = create_evidence_tools_server(project_dir)
    active_mcp_servers["native-screenshot"] = create_native_screenshot_server(project_dir)

    console.print()

    # Create security settings
    security_settings = {
        "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True},
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": [
                "Read(./**)",
                "Write(./**)",
                "Edit(./**)",
                "Glob(./**)",
                "Grep(./**)",
                "Bash(*)",
                *active_tools, # Allow all enabled MCP tools
            ],
        },
    }

    # Ensure project directory exists
    project_dir.mkdir(parents=True, exist_ok=True)

    # Write settings file
    settings_file = project_dir / ".claude_settings.json"
    with open(settings_file, "w") as f:
        json.dump(security_settings, f, indent=2)

    return ClaudeSDKClient(
        options=ClaudeCodeOptions(
            model=model,
            system_prompt="You are an expert full-stack developer building a production-quality web application.",
            allowed_tools=active_tools,
            mcp_servers=active_mcp_servers,
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="Bash", hooks=[bash_security_hook]),
                ],
                "PostToolUse": [
                    HookMatcher(matcher="Bash", hooks=[process_tracking_hook]),
                    HookMatcher(matcher="mcp__puppeteer__puppeteer_screenshot", hooks=[screenshot_saver_hook]),
                ],
            },
            max_turns=1000,
            cwd=str(project_dir.resolve()),
            settings=str(settings_file.resolve()),
        )
    )