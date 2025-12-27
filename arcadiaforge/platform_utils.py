"""
Platform Utilities for Cross-Platform Support
==============================================

Central module for OS detection and platform-specific utilities.
Supports Windows, macOS, and Linux.
"""

import platform
import os
import shutil
from enum import Enum
from typing import NamedTuple, Optional


class OSType(Enum):
    """Supported operating system types."""
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"


class PlatformInfo(NamedTuple):
    """Platform-specific configuration information."""
    os_type: OSType
    init_script_name: str           # init.sh, init.bat, or init.ps1
    init_script_extension: str      # .sh, .bat, or .ps1
    script_execute_prefix: str      # "./" or "" or "powershell -File "
    env_set_command: str            # "export" or "set" or "$env:"
    process_kill_command: str       # "pkill" or "taskkill"
    path_separator: str             # "/" or "\\"
    shell_name: str                 # "bash", "zsh", "cmd", or "powershell"
    needs_chmod: bool               # Whether chmod +x is needed for scripts


def detect_os() -> OSType:
    """
    Detect the current operating system.

    Returns:
        OSType enum value for the current OS
    """
    system = platform.system().lower()
    if system == "windows":
        return OSType.WINDOWS
    elif system == "darwin":
        return OSType.MACOS
    else:
        return OSType.LINUX


def get_default_shell() -> str:
    """
    Get the default shell for the current platform.

    Returns:
        Shell name (bash, zsh, cmd, powershell)
    """
    os_type = detect_os()

    if os_type == OSType.WINDOWS:
        # Check if PowerShell is preferred
        if shutil.which("pwsh") or shutil.which("powershell"):
            return "powershell"
        return "cmd"
    elif os_type == OSType.MACOS:
        # macOS defaults to zsh since Catalina
        shell = os.environ.get("SHELL", "/bin/zsh")
        if "zsh" in shell:
            return "zsh"
        return "bash"
    else:
        # Linux typically uses bash
        shell = os.environ.get("SHELL", "/bin/bash")
        if "zsh" in shell:
            return "zsh"
        return "bash"


def has_git_bash() -> bool:
    """
    Check if Git Bash is available on Windows.

    Returns:
        True if Git Bash is available, False otherwise
    """
    if detect_os() != OSType.WINDOWS:
        return False

    # Check common Git Bash locations
    git_bash_paths = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ]

    for path in git_bash_paths:
        if os.path.exists(path):
            return True

    # Also check if bash is in PATH (could be Git Bash or WSL)
    return shutil.which("bash") is not None


def has_wsl() -> bool:
    """
    Check if Windows Subsystem for Linux is available.

    Returns:
        True if WSL is available, False otherwise
    """
    if detect_os() != OSType.WINDOWS:
        return False

    return shutil.which("wsl") is not None


def get_platform_info() -> PlatformInfo:
    """
    Get platform-specific configuration.

    Returns:
        PlatformInfo with all platform-specific settings
    """
    os_type = detect_os()
    shell = get_default_shell()

    if os_type == OSType.WINDOWS:
        return PlatformInfo(
            os_type=OSType.WINDOWS,
            init_script_name="init.bat",
            init_script_extension=".bat",
            script_execute_prefix="",
            env_set_command="set",
            process_kill_command="taskkill",
            path_separator="\\",
            shell_name=shell,
            needs_chmod=False
        )
    elif os_type == OSType.MACOS:
        return PlatformInfo(
            os_type=OSType.MACOS,
            init_script_name="init.sh",
            init_script_extension=".sh",
            script_execute_prefix="./",
            env_set_command="export",
            process_kill_command="pkill",
            path_separator="/",
            shell_name=shell,
            needs_chmod=True
        )
    else:  # Linux
        return PlatformInfo(
            os_type=OSType.LINUX,
            init_script_name="init.sh",
            init_script_extension=".sh",
            script_execute_prefix="./",
            env_set_command="export",
            process_kill_command="pkill",
            path_separator="/",
            shell_name=shell,
            needs_chmod=True
        )


def get_init_script_name(prefer_powershell: bool = False) -> str:
    """
    Get the appropriate init script name for the current platform.

    Args:
        prefer_powershell: On Windows, prefer .ps1 over .bat

    Returns:
        Init script filename (init.sh, init.bat, or init.ps1)
    """
    os_type = detect_os()

    if os_type == OSType.WINDOWS:
        if prefer_powershell:
            return "init.ps1"
        return "init.bat"
    else:
        return "init.sh"


def get_all_init_script_names() -> list[str]:
    """
    Get all possible init script names for the current platform.

    Returns:
        List of init script filenames to check for
    """
    os_type = detect_os()

    if os_type == OSType.WINDOWS:
        # On Windows, also check for .sh if Git Bash is available
        scripts = ["init.bat", "init.ps1"]
        if has_git_bash():
            scripts.append("init.sh")
        return scripts
    else:
        return ["init.sh"]


def get_script_run_command(script_name: str) -> str:
    """
    Get the command to run a script on the current platform.

    Args:
        script_name: Name of the script file

    Returns:
        Full command string to execute the script
    """
    os_type = detect_os()

    if os_type == OSType.WINDOWS:
        if script_name.endswith(".ps1"):
            return f"powershell -ExecutionPolicy Bypass -File .\\{script_name}"
        elif script_name.endswith(".bat"):
            return script_name
        elif script_name.endswith(".sh") and has_git_bash():
            return f"bash {script_name}"
        else:
            return script_name
    else:
        return f"./{script_name}"


def get_chmod_command(script_name: str) -> Optional[str]:
    """
    Get the chmod command if needed for the current platform.

    Args:
        script_name: Name of the script file

    Returns:
        chmod command string, or None if not needed
    """
    info = get_platform_info()

    if info.needs_chmod:
        return f"chmod +x {script_name}"
    return None


def get_env_var_set_command(var_name: str, var_value: str) -> str:
    """
    Get the command to set an environment variable.

    Args:
        var_name: Environment variable name
        var_value: Value to set

    Returns:
        Command string to set the environment variable
    """
    os_type = detect_os()

    if os_type == OSType.WINDOWS:
        # Return both CMD and PowerShell versions
        return f"set {var_name}={var_value}"
    else:
        return f"export {var_name}='{var_value}'"


def get_process_kill_command(process_name: str) -> str:
    """
    Get the command to kill a process by name.

    Args:
        process_name: Name of the process to kill (e.g., "node")

    Returns:
        Command string to kill the process
    """
    os_type = detect_os()

    if os_type == OSType.WINDOWS:
        # Add .exe if not present
        if not process_name.endswith(".exe"):
            process_name = f"{process_name}.exe"
        return f"taskkill /IM {process_name} /F"
    else:
        return f"pkill {process_name}"


# =============================================================================
# Instruction Generation Functions
# =============================================================================

def get_init_script_instructions() -> str:
    """
    Get OS-specific instructions for running the init script.

    Returns:
        Markdown-formatted instructions
    """
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        instructions = """
### Running the Init Script (Windows)

**Command Prompt:**
```cmd
init.bat
```

**PowerShell:**
```powershell
powershell -ExecutionPolicy Bypass -File .\\init.ps1
```
"""
        if has_git_bash():
            instructions += """
**Git Bash (if init.sh exists):**
```bash
./init.sh
```
"""
        return instructions
    else:
        return f"""
### Running the Init Script ({info.os_type.value.title()})

```{info.shell_name}
chmod +x init.sh
./init.sh
```
"""


def get_env_var_instructions(var_name: str = "ANTHROPIC_API_KEY",
                             var_value: str = "your-api-key-here") -> str:
    """
    Get OS-specific environment variable setting instructions.

    Args:
        var_name: Name of the environment variable
        var_value: Example value to show

    Returns:
        Markdown-formatted instructions
    """
    os_type = detect_os()

    if os_type == OSType.WINDOWS:
        return f"""
**Setting Environment Variables (Windows)**

Command Prompt:
```cmd
set {var_name}={var_value}
```

PowerShell:
```powershell
$env:{var_name}="{var_value}"
```

For permanent setup, add to System Environment Variables via:
Settings > System > About > Advanced system settings > Environment Variables
"""
    else:
        shell = get_default_shell()
        rc_file = ".zshrc" if shell == "zsh" else ".bashrc"
        return f"""
**Setting Environment Variables ({detect_os().value.title()})**

```{shell}
export {var_name}='{var_value}'
```

For permanent setup, add to your `~/{rc_file}`:
```{shell}
echo "export {var_name}='{var_value}'" >> ~/{rc_file}
source ~/{rc_file}
```
"""


def get_init_script_creation_instructions() -> str:
    """
    Get instructions for creating the init script (for prompts).

    Returns:
        Markdown-formatted instructions for the agent
    """
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        return """
### Create Init Scripts (Windows)

Create TWO scripts for Windows compatibility:

**1. Create `init.bat` (Command Prompt):**
```batch
@echo off
echo Setting up development environment...

:: Install dependencies
call npm install

:: Start development server in background
start /B npm run dev

echo.
echo Development server starting...
echo Access the application at http://localhost:3000
```

**2. Create `init.ps1` (PowerShell):**
```powershell
Write-Host "Setting up development environment..." -ForegroundColor Cyan

# Install dependencies
npm install

# Start development server
Start-Process -NoNewWindow -FilePath "npm" -ArgumentList "run", "dev"

Write-Host ""
Write-Host "Development server starting..." -ForegroundColor Green
Write-Host "Access the application at http://localhost:3000"
```

Both scripts should:
1. Install any required dependencies
2. Start any necessary servers or services
3. Print helpful information about how to access the running application
"""
    else:
        return """
### Create init.sh

Create a script called `init.sh` that future agents can use to quickly
set up and run the development environment. The script should:

1. Install any required dependencies
2. Start any necessary servers or services
3. Print helpful information about how to access the running application

Example structure:
```bash
#!/bin/bash
echo "Setting up development environment..."

# Install dependencies
npm install

# Start development server in background
npm run dev &

echo ""
echo "Development server starting..."
echo "Access the application at http://localhost:3000"
```

Base the script on the technology stack specified in `app_spec.txt`.
"""


def get_run_server_instructions() -> str:
    """
    Get instructions for running/starting servers.

    Returns:
        Markdown-formatted instructions
    """
    info = get_platform_info()
    scripts = get_all_init_script_names()

    if info.os_type == OSType.WINDOWS:
        script_checks = " or ".join(f"`{s}`" for s in scripts)
        return f"""
### STEP 2: START SERVERS (IF NOT RUNNING)

Check if any of these init scripts exist: {script_checks}

**If `init.bat` exists:**
```cmd
init.bat
```

**If `init.ps1` exists:**
```powershell
powershell -ExecutionPolicy Bypass -File .\\init.ps1
```

**Otherwise**, start servers manually:
```cmd
npm install
npm run dev
```
"""
    else:
        return """
### STEP 2: START SERVERS (IF NOT RUNNING)

If `init.sh` exists, run it:
```bash
chmod +x init.sh
./init.sh
```

Otherwise, start servers manually:
```bash
npm install
npm run dev
```
"""


def get_platform_summary() -> str:
    """
    Get a summary of the current platform configuration.

    Returns:
        Human-readable summary string
    """
    info = get_platform_info()
    os_type = detect_os()

    summary = [
        f"Platform: {os_type.value.title()}",
        f"Shell: {info.shell_name}",
        f"Init script: {info.init_script_name}",
        f"Process killer: {info.process_kill_command}",
        f"Needs chmod: {info.needs_chmod}",
    ]

    if os_type == OSType.WINDOWS:
        summary.append(f"Git Bash available: {has_git_bash()}")
        summary.append(f"WSL available: {has_wsl()}")

    return "\n".join(summary)


# =============================================================================
# Module self-test when run directly
# =============================================================================

if __name__ == "__main__":
    print("Platform Detection Test")
    print("=" * 50)
    print()
    print(get_platform_summary())
    print()
    print("Init Script Instructions:")
    print("-" * 50)
    print(get_init_script_instructions())
    print()
    print("Environment Variable Instructions:")
    print("-" * 50)
    print(get_env_var_instructions())
