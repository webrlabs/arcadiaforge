"""
Security Hooks for Autonomous Coding Agent
==========================================

Pre-tool-use hooks that validate bash commands for security.
Uses an allowlist approach - only explicitly permitted commands can run.
Supports cross-platform operation (Windows, macOS, Linux).
"""

import os
import shlex

from arcadiaforge.platform_utils import detect_os, OSType, get_platform_info


# =============================================================================
# Platform-Aware Allowed Commands
# =============================================================================

# Common commands that work across all platforms (or via Git Bash on Windows)
_COMMON_COMMANDS = {
    # File inspection
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    # File operations
    "cp",
    "mkdir",
    # Directory
    "pwd",
    # Node.js development
    "npm",
    "node",
    "npx",
    # Version control
    "git",
    # Process management
    "ps",
    "sleep",
    "timeout",
    # Python
    "python",
    "python3",
    "mamba",
    "conda",
    "pip",
    "pip3",
    # Other
    "curl",
    "echo",
}

# Windows-specific commands
_WINDOWS_COMMANDS = {
    # Windows equivalents and commands
    "dir",           # Windows ls equivalent
    "type",          # Windows cat equivalent
    "copy",          # Windows cp equivalent
    "md",            # Windows mkdir alias
    "taskkill",      # Windows process kill (validated separately)
    "where",         # Windows which equivalent
    "start",         # Open/run programs
    "cmd",           # Command prompt
    "powershell",    # PowerShell execution
    # Init scripts (including variants from shlex parsing of backslash paths)
    "init.bat",      # Windows batch init script (validated separately)
    "init.ps1",      # PowerShell init script (validated separately)
    ".init.bat",     # shlex parses .\init.bat as .init.bat
    ".init.ps1",     # shlex parses .\init.ps1 as .init.ps1
}

# Unix-specific commands (Linux and macOS)
_UNIX_COMMANDS = {
    # Unix-only commands
    "chmod",         # Make executable (validated separately)
    "pkill",         # Process kill (validated separately)
    "lsof",          # List open files
    "sh",            # Shell execution
    "bash",          # Bash execution
    # Init scripts
    "init.sh",       # Unix init script (validated separately)
}


def get_allowed_commands() -> set[str]:
    """
    Get the set of allowed commands for the current platform.

    Returns:
        Set of allowed command names
    """
    os_type = detect_os()

    if os_type == OSType.WINDOWS:
        return _COMMON_COMMANDS | _WINDOWS_COMMANDS
    else:
        return _COMMON_COMMANDS | _UNIX_COMMANDS


def get_commands_needing_extra_validation() -> set[str]:
    """
    Get commands that need additional validation for the current platform.

    Returns:
        Set of command names requiring extra validation
    """
    os_type = detect_os()

    if os_type == OSType.WINDOWS:
        # Include variants from shlex parsing of backslash paths
        return {"taskkill", "init.bat", "init.ps1", ".init.bat", ".init.ps1", "powershell", "cmd"}
    else:
        return {"pkill", "chmod", "init.sh", "bash", "sh"}


# Legacy constant for backwards compatibility (uses current platform)
ALLOWED_COMMANDS = get_allowed_commands()
COMMANDS_NEEDING_EXTRA_VALIDATION = get_commands_needing_extra_validation()


def split_command_segments(command_string: str) -> list[str]:
    """
    Split a compound command into individual command segments.

    Handles command chaining (&&, ||, ;) but not pipes (those are single commands).

    Args:
        command_string: The full shell command

    Returns:
        List of individual command segments
    """
    import re

    # Split on && and || while preserving the ability to handle each segment
    # This regex splits on && or || that aren't inside quotes
    segments = re.split(r"\s*(?:&&|\|\|)\s*", command_string)

    # Further split on semicolons
    result = []
    for segment in segments:
        sub_segments = re.split(r'(?<!["\'])\s*;\s*(?!["\'])', segment)
        for sub in sub_segments:
            sub = sub.strip()
            if sub:
                result.append(sub)

    return result


def extract_commands(command_string: str) -> list[str]:
    """
    Extract command names from a shell command string.

    Handles pipes, command chaining (&&, ||, ;), and subshells.
    Returns the base command names (without paths).

    Args:
        command_string: The full shell command

    Returns:
        List of command names found in the string
    """
    commands = []

    # shlex doesn't treat ; as a separator, so we need to pre-process
    import re

    # Split on semicolons that aren't inside quotes (simple heuristic)
    # This handles common cases like "echo hello; ls"
    segments = re.split(r'(?<!["\'])\s*;\s*(?!["\'])', command_string)

    def _split_tokens(segment_text: str) -> list[str] | None:
        try:
            return shlex.split(segment_text)
        except ValueError:
            if "\"" not in segment_text and "'" not in segment_text:
                return segment_text.split()
            if detect_os() == OSType.WINDOWS:
                try:
                    tokens = shlex.split(segment_text, posix=False)
                except ValueError:
                    return None
                cleaned = []
                for token in tokens:
                    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
                        cleaned.append(token[1:-1])
                    else:
                        cleaned.append(token)
                return cleaned
            return None

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        try:
            tokens = _split_tokens(segment)
        except ValueError:
            # Malformed command (unclosed quotes, etc.)
            # Return empty to trigger block (fail-safe)
            return []

        if tokens is None:
            return []

        if not tokens:
            continue

        # Track when we expect a command vs arguments
        expect_command = True

        for token in tokens:
            # Shell operators indicate a new command follows
            if token in ("|", "||", "&&", "&"):
                expect_command = True
                continue

            # Skip shell keywords that precede commands
            if token in (
                "if",
                "then",
                "else",
                "elif",
                "fi",
                "for",
                "while",
                "until",
                "do",
                "done",
                "case",
                "esac",
                "in",
                "!",
                "{",
                "}",
            ):
                continue

            # Skip flags/options
            if token.startswith("-"):
                continue

            # Skip variable assignments (VAR=value)
            if "=" in token and not token.startswith("="):
                continue

            if expect_command:
                # Extract the base command name (handle paths like /usr/bin/python)
                cmd = os.path.basename(token).lower()
                commands.append(cmd)
                expect_command = False

    return commands


def validate_pkill_command(command_string: str) -> tuple[bool, str]:
    """
    Validate pkill commands - allow killing dev processes safely.

    Rules:
    - Direct 'pkill python' or 'pkill node' is BLOCKED (would kill framework)
    - 'pkill -f "python app.py"' is ALLOWED (targets specific script)
    - 'pkill -f "node server.js"' is ALLOWED (targets specific script)
    - 'pkill vite' etc. is ALLOWED (dev server processes)

    Uses shlex to parse the command, avoiding regex bypass vulnerabilities.

    Returns:
        Tuple of (is_allowed, reason_if_blocked)
    """
    # Always allowed process names (dev servers, not python/node itself)
    always_allowed = {
        "vite",
        "next",
        "webpack",
        "esbuild",
        "parcel",
        "rollup",
        "tsc",           # TypeScript compiler
        "jest",          # Test runner
        "vitest",        # Test runner
        "playwright",    # E2E test runner
        "cypress",       # E2E test runner
        "uvicorn",       # Python ASGI server
        "gunicorn",      # Python WSGI server
        "flask",         # Flask dev server
        "django",        # Django
        "fastapi",       # FastAPI
        "streamlit",     # Streamlit
        "gradio",        # Gradio
    }

    # Protected processes - only allowed with -f flag and specific script
    protected_processes = {
        "python", "python3", "python.exe", "python3.exe",
        "node", "node.exe",
    }

    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return False, "Could not parse pkill command"

    if not tokens:
        return False, "Empty pkill command"

    # Check for -f flag (full command line match)
    has_f_flag = "-f" in tokens

    # Separate flags from arguments
    args = []
    for token in tokens[1:]:
        if not token.startswith("-"):
            args.append(token)

    if not args:
        return False, "pkill requires a process name"

    # The target is typically the last non-flag argument
    target = args[-1]
    target_lower = target.lower()

    # For -f flag, the target is a pattern like "python app.py" or "node server.js"
    if has_f_flag and " " in target:
        # Extract the base command (first word)
        base_cmd = target.split()[0].lower()

        # If it's a protected process, -f with a script pattern is allowed
        # This lets agents kill their own spawned backend servers
        if base_cmd in protected_processes:
            # Make sure there's actually a script/pattern specified
            script_part = target.split(maxsplit=1)[1] if len(target.split()) > 1 else ""
            if script_part:
                return True, ""
            else:
                return False, f"BLOCKED: 'pkill -f {base_cmd}' requires a script name (e.g., 'pkill -f \"python app.py\"')"

    # Direct pkill of protected processes without -f pattern is blocked
    if target_lower in protected_processes:
        return False, f"BLOCKED: 'pkill {target}' would kill the Arcadia Forge framework. Use 'pkill -f \"{target} your_script.py\"' to kill a specific process."

    # Always-allowed processes
    if target_lower in always_allowed:
        return True, ""

    # For -f flag with non-protected processes, allow it
    if has_f_flag:
        return True, ""

    return False, f"pkill only allowed for dev server processes or with -f flag for specific scripts. Allowed: {', '.join(sorted(always_allowed))}"


def validate_wrapper_command(
    command_string: str,
    allowed_commands: set[str],
    commands_needing_validation: set[str],
) -> tuple[bool, str]:
    """
    Validate shell wrapper commands like cmd/powershell/bash/sh.

    For wrappers that execute a subcommand, validate the subcommand
    with the same allowlist and extra validation rules.
    """
    try:
        tokens = shlex.split(command_string)
    except ValueError:
        if detect_os() == OSType.WINDOWS:
            try:
                tokens = shlex.split(command_string, posix=False)
            except ValueError:
                return False, "Could not parse wrapper command"
            tokens = [
                t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"') else t
                for t in tokens
            ]
        else:
            return False, "Could not parse wrapper command"

    if not tokens:
        return False, "Empty wrapper command"

    wrapper = tokens[0].lower()

    if wrapper == "cmd":
        # Require /c or /k to execute a subcommand
        tokens_lower = [t.lower() for t in tokens]
        if "/c" in tokens_lower:
            idx = tokens_lower.index("/c")
        elif "/k" in tokens_lower:
            idx = tokens_lower.index("/k")
        else:
            return False, "cmd requires /c or /k with a subcommand"

        if idx + 1 >= len(tokens):
            return False, "cmd requires a subcommand after /c or /k"

        subcommand = " ".join(tokens[idx + 1:])
        return validate_command_string(subcommand, allowed_commands, commands_needing_validation)

    if wrapper == "powershell":
        tokens_lower = [t.lower() for t in tokens]

        if "-file" in tokens_lower:
            # Only allow init.ps1 execution
            allowed, reason = validate_init_script(command_string)
            return (allowed, reason)

        if "-command" in tokens_lower:
            idx = tokens_lower.index("-command")
            if idx + 1 >= len(tokens):
                return False, "powershell -Command requires a subcommand"
            subcommand = " ".join(tokens[idx + 1:])
            return validate_command_string(subcommand, allowed_commands, commands_needing_validation)

        return False, "powershell requires -File or -Command"

    if wrapper in ("bash", "sh"):
        tokens_lower = [t.lower() for t in tokens]
        if "-c" not in tokens_lower:
            return False, f"{wrapper} requires -c with a subcommand"
        idx = tokens_lower.index("-c")
        if idx + 1 >= len(tokens):
            return False, f"{wrapper} -c requires a subcommand"
        subcommand = " ".join(tokens[idx + 1:])
        return validate_command_string(subcommand, allowed_commands, commands_needing_validation)

    return False, f"Unknown wrapper command: {wrapper}"


def validate_command_string(
    command_string: str,
    allowed_commands: set[str],
    commands_needing_validation: set[str],
) -> tuple[bool, str]:
    """
    Validate a command string against allowlist and extra validation rules.
    """
    commands = extract_commands(command_string)
    if not commands:
        return False, f"Could not parse command for security validation: {command_string}"

    segments = split_command_segments(command_string)

    for cmd in commands:
        if cmd == "cd":
            return False, "BLOCKED: 'cd' is not allowed. The agent runs in a fixed root. Please use relative paths or flags like '--prefix' for npm or '-C' for git."

        if cmd not in allowed_commands:
            return False, f"Command '{cmd}' is not in the allowed commands list for this platform"

        if cmd in commands_needing_validation:
            cmd_segment = get_command_for_validation(cmd, segments) or command_string

            if cmd == "pkill":
                allowed, reason = validate_pkill_command(cmd_segment)
                if not allowed:
                    return False, reason
            elif cmd == "chmod":
                allowed, reason = validate_chmod_command(cmd_segment)
                if not allowed:
                    return False, reason
            elif cmd == "init.sh":
                allowed, reason = validate_init_script(cmd_segment)
                if not allowed:
                    return False, reason
            elif cmd == "taskkill":
                allowed, reason = validate_taskkill_command(cmd_segment)
                if not allowed:
                    return False, reason
            elif cmd in ("init.bat", "init.ps1", ".init.bat", ".init.ps1"):
                allowed, reason = validate_init_script(cmd_segment)
                if not allowed:
                    return False, reason
            elif cmd in ("powershell", "cmd", "bash", "sh"):
                allowed, reason = validate_wrapper_command(
                    cmd_segment,
                    allowed_commands,
                    commands_needing_validation,
                )
                if not allowed:
                    return False, reason

    return True, ""


def validate_taskkill_command(command_string: str) -> tuple[bool, str]:
    """
    Validate taskkill commands (Windows) - allow killing dev processes safely.

    Rules:
    - Direct 'taskkill /IM python.exe' is BLOCKED (would kill framework)
    - 'taskkill /IM python.exe /FI "WINDOWTITLE eq app.py"' is ALLOWED (targets specific window)
    - 'taskkill /IM vite.exe' etc. is ALLOWED (dev server processes)

    Uses shlex to parse the command, avoiding regex bypass vulnerabilities.

    Returns:
        Tuple of (is_allowed, reason_if_blocked)
    """
    # Always allowed process names (dev servers, not python/node itself)
    always_allowed = {
        "vite.exe", "vite.cmd",
        "next.exe", "next.cmd",
        "webpack.exe", "webpack.cmd",
        "esbuild.exe", "esbuild.cmd",
        "parcel.exe", "parcel.cmd",
        "rollup.exe", "rollup.cmd",
        "tsc.exe", "tsc.cmd",
        "jest.exe", "jest.cmd",
        "vitest.exe", "vitest.cmd",
        "playwright.exe", "playwright.cmd",
        "cypress.exe", "cypress.cmd",
        "uvicorn.exe",       # Python ASGI server
        "gunicorn.exe",      # Python WSGI server
        "flask.exe",         # Flask
        "streamlit.exe",     # Streamlit
    }

    # Protected processes - only allowed with /FI filter
    protected_processes = {
        "python.exe", "python", "python3.exe", "pythonw.exe",
        "node.exe", "node",
        "npm.exe", "npm", "npm.cmd",
        "npx.exe", "npx", "npx.cmd",
    }

    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return False, "Could not parse taskkill command"

    if not tokens:
        return False, "Empty taskkill command"

    # Convert to lowercase for case-insensitive matching
    tokens_lower = [t.lower() for t in tokens]

    # Check for /FI flag (filter) - allows targeting specific processes
    has_filter = "/fi" in tokens_lower

    # Look for /IM flag (image name)
    process_name = None
    for i, token in enumerate(tokens_lower):
        if token == "/im" and i + 1 < len(tokens):
            process_name = tokens[i + 1].lower()
            break

    if process_name is None:
        # Check if /PID is used (we don't allow killing by PID for security)
        if "/pid" in tokens_lower:
            return False, "taskkill by PID is not allowed; use /IM with process name"
        return False, "taskkill must specify process with /IM flag"

    # Check if it's a protected process
    if process_name in {p.lower() for p in protected_processes}:
        # If there's a filter, allow it (targeting specific instances)
        if has_filter:
            return True, ""
        # Otherwise block - would kill the framework
        return False, f"BLOCKED: 'taskkill /IM {process_name}' would kill the Arcadia Forge framework. Use a /FI filter to target specific processes."

    # Always-allowed processes
    if process_name in {p.lower() for p in always_allowed}:
        return True, ""

    return False, f"taskkill only allowed for dev server processes. Allowed: {', '.join(sorted(p for p in always_allowed if p.endswith('.exe')))}"


def validate_chmod_command(command_string: str) -> tuple[bool, str]:
    """
    Validate chmod commands - only allow making files executable with +x.

    Returns:
        Tuple of (is_allowed, reason_if_blocked)
    """
    try:
        tokens = shlex.split(command_string)
    except ValueError:
        return False, "Could not parse chmod command"

    if not tokens or tokens[0] != "chmod":
        return False, "Not a chmod command"

    # Look for the mode argument
    # Valid modes: +x, u+x, a+x, etc. (anything ending with +x for execute permission)
    mode = None
    files = []

    for token in tokens[1:]:
        if token.startswith("-"):
            # Skip flags like -R (we don't allow recursive chmod anyway)
            return False, "chmod flags are not allowed"
        elif mode is None:
            mode = token
        else:
            files.append(token)

    if mode is None:
        return False, "chmod requires a mode"

    if not files:
        return False, "chmod requires at least one file"

    # Only allow +x variants (making files executable)
    # This matches: +x, u+x, g+x, o+x, a+x, ug+x, etc.
    import re

    if not re.match(r"^[ugoa]*\+x$", mode):
        return False, f"chmod only allowed with +x mode, got: {mode}"

    return True, ""


def validate_init_script(command_string: str) -> tuple[bool, str]:
    """
    Validate init script execution - platform-aware validation.

    On Unix: allows ./init.sh or paths ending in /init.sh
    On Windows: allows init.bat, init.ps1, or paths ending in those

    Returns:
        Tuple of (is_allowed, reason_if_blocked)
    """
    os_type = detect_os()

    # On Windows, shlex.split() treats backslash as escape character
    # We need to handle this specially
    if os_type == OSType.WINDOWS:
        # Use the raw command string for Windows path handling
        # Split on spaces but preserve quoted strings
        try:
            # Replace backslashes with forward slashes for consistent parsing
            normalized = command_string.replace("\\", "/")
            tokens = shlex.split(normalized)
        except ValueError:
            return False, "Could not parse init script command"

        if not tokens:
            return False, "Empty command"

        script = tokens[0].lower()

        # Direct execution of init.bat
        if script in ("init.bat", "./init.bat"):
            return True, ""
        if script.endswith("/init.bat"):
            return True, ""

        # Direct execution of init.ps1
        if script in ("init.ps1", "./init.ps1"):
            return True, ""
        if script.endswith("/init.ps1"):
            return True, ""

        # PowerShell invocation: powershell -File .\init.ps1
        if script == "powershell":
            # Look for -File flag followed by init.ps1
            tokens_lower = [t.lower() for t in tokens]
            for i, token in enumerate(tokens_lower):
                if token == "-file" and i + 1 < len(tokens):
                    ps_script = tokens[i + 1].lower()
                    if ps_script in ("init.ps1", "./init.ps1"):
                        return True, ""
                    if ps_script.endswith("/init.ps1"):
                        return True, ""

        return False, f"Only init.bat or init.ps1 allowed on Windows, got: {tokens[0]}"
    else:
        # Unix: standard shlex parsing works fine
        try:
            tokens = shlex.split(command_string)
        except ValueError:
            return False, "Could not parse init script command"

        if not tokens:
            return False, "Empty command"

        script = tokens[0]

        # Allow ./init.sh or paths ending in /init.sh
        if script == "./init.sh" or script.endswith("/init.sh"):
            return True, ""

        return False, f"Only ./init.sh is allowed, got: {script}"


def get_command_for_validation(cmd: str, segments: list[str]) -> str:
    """
    Find the specific command segment that contains the given command.

    Args:
        cmd: The command name to find
        segments: List of command segments

    Returns:
        The segment containing the command, or empty string if not found
    """
    for segment in segments:
        segment_commands = extract_commands(segment)
        if cmd in segment_commands:
            return segment
    return ""


async def bash_security_hook(input_data, tool_use_id=None, context=None):
    """
    Pre-tool-use hook that validates bash commands using a platform-aware allowlist.

    Only commands in the allowed list for the current platform are permitted.
    Supports Windows (taskkill, init.bat, init.ps1) and Unix (pkill, chmod, init.sh).

    Args:
        input_data: Dict containing tool_name and tool_input
        tool_use_id: Optional tool use ID
        context: Optional context

    Returns:
        Empty dict to allow, or {"decision": "block", "reason": "..."} to block
    """
    if input_data.get("tool_name") != "Bash":
        return {}

    command = input_data.get("tool_input", {}).get("command", "")
    if not command:
        return {}

    # Get platform-specific allowed commands (called at runtime for accurate detection)
    allowed_commands = get_allowed_commands()
    commands_needing_validation = get_commands_needing_extra_validation()

    allowed, reason = validate_command_string(
        command,
        allowed_commands,
        commands_needing_validation,
    )
    if not allowed:
        return {"decision": "block", "reason": reason}

    return {}
