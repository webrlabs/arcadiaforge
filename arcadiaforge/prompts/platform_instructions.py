"""
Platform-Specific Prompt Instructions
=====================================

This module provides platform-specific instruction snippets that are
substituted into prompt templates at runtime based on the detected OS.
"""

from arcadiaforge.platform_utils import detect_os, get_platform_info, OSType


def get_init_script_creation_instructions() -> str:
    """
    Get instructions for creating the init script.
    Used in initializer_prompt.md.
    """
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        return """### SECOND TASK: Create Init Scripts (Windows)

Create TWO scripts for Windows compatibility:

**1. Create `init.bat` (Command Prompt):**

This is a batch script that sets up the development environment:

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

This is a PowerShell script for users who prefer PowerShell:

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

Base the scripts on the technology stack specified in `app_spec.txt`."""
    else:
        return """### SECOND TASK: Create init.sh

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

Base the script on the technology stack specified in `app_spec.txt`."""


def get_run_init_instructions() -> str:
    """
    Get instructions for running the init script.
    Used in coding_prompt.md.
    """
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        return """### STEP 2: START SERVERS (IF NOT RUNNING)

Check if any init scripts exist and run the appropriate one:

**If `init.bat` exists (Command Prompt):**
```cmd
init.bat
```

**If `init.ps1` exists (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File .\\init.ps1
```

Otherwise, start servers manually and document the process:
```cmd
npm install
npm run dev
```"""
    else:
        return """### STEP 2: START SERVERS (IF NOT RUNNING)

If `init.sh` exists, run it:
```bash
chmod +x init.sh
./init.sh
```

Otherwise, start servers manually and document the process:
```bash
npm install
npm run dev
```"""


def get_init_script_files_list() -> str:
    """
    Get the list of init script files for the project structure.
    Used in initializer_prompt.md.
    """
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        return "- init.bat (Windows Command Prompt setup script)\n- init.ps1 (Windows PowerShell setup script)"
    else:
        return "- init.sh (environment setup script)"


def get_init_script_commit_message() -> str:
    """
    Get the commit message mentioning init scripts and .gitignore.
    Used in initializer_prompt.md.
    """
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        return 'Commit message: "Initial setup: feature database, init.bat, init.ps1, .gitignore, and project structure"'
    else:
        return 'Commit message: "Initial setup: feature database, init.sh, .gitignore, and project structure"'


def get_project_structure_init_line() -> str:
    """
    Get the init script line for project structure display.
    Used in README and documentation.
    """
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        return "├── init.bat                  # Windows Command Prompt setup script\n├── init.ps1                  # Windows PowerShell setup script"
    else:
        return "├── init.sh                   # Environment setup script"


def get_run_app_instructions() -> str:
    """
    Get instructions for running the generated application.
    Used in output messages and README.
    """
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        return """**To run the application (Windows):**

Command Prompt:
```cmd
cd <project_directory>
init.bat
```

PowerShell:
```powershell
cd <project_directory>
powershell -ExecutionPolicy Bypass -File .\\init.ps1
```

Or manually:
```cmd
npm install
npm run dev
```"""
    else:
        return """**To run the application:**

```bash
cd <project_directory>
chmod +x init.sh
./init.sh
```

Or manually:
```bash
npm install
npm run dev
```"""


def get_env_var_instructions() -> str:
    """
    Get instructions for setting environment variables.
    Used in README and setup documentation.
    """
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        return """**Setting up API Key (Windows):**

Command Prompt:
```cmd
set ANTHROPIC_API_KEY=your-api-key-here
```

PowerShell:
```powershell
$env:ANTHROPIC_API_KEY="your-api-key-here"
```

For permanent setup, add to System Environment Variables via:
Settings > System > About > Advanced system settings > Environment Variables"""
    else:
        shell = info.shell_name
        rc_file = ".zshrc" if shell == "zsh" else ".bashrc"
        return f"""**Setting up API Key:**

```{shell}
export ANTHROPIC_API_KEY='your-api-key-here'
```

For permanent setup, add to your `~/{rc_file}`:
```{shell}
echo "export ANTHROPIC_API_KEY='your-api-key-here'" >> ~/{rc_file}
source ~/{rc_file}
```"""


def get_process_kill_instructions() -> str:
    """
    Get instructions for killing dev server processes.
    Used in troubleshooting documentation.
    """
    info = get_platform_info()

    if info.os_type == OSType.WINDOWS:
        return """**Stopping dev servers (Windows):**

```cmd
taskkill /IM node.exe /F
```

Or in PowerShell:
```powershell
Stop-Process -Name "node" -Force
```"""
    else:
        return """**Stopping dev servers:**

```bash
pkill node
# or
pkill -f "npm run dev"
```"""


def get_filesystem_constraints() -> str:
    """
    Get file system constraint instructions.
    Used in all prompts.
    """
    return """**FILESYSTEM CONSTRAINTS (CRITICAL):**
- You CANNOT change the working directory using `cd`.
- You are permanently rooted in the project directory.
- Use relative paths (e.g., `folder/file.txt`).
- For commands needing a different directory, use command-specific flags:
  - `npm install --prefix frontend` (instead of cd frontend && npm install)
  - `git -C backend status` (instead of cd backend && git status)
  - `python -m backend.app.main` (run from root)"""


def get_platform_name() -> str:
    """Get a human-readable platform name."""
    info = get_platform_info()
    return info.os_type.value.title()


def get_shell_name() -> str:
    """Get the default shell name for the platform."""
    info = get_platform_info()
    return info.shell_name


def get_all_substitutions() -> dict[str, str]:
    """
    Get all platform-specific substitutions as a dictionary.
    Keys are placeholder names, values are the substitution text.
    """
    info = get_platform_info()

    return {
        "{{PLATFORM_NAME}}": get_platform_name(),
        "{{SHELL_NAME}}": get_shell_name(),
        "{{INIT_SCRIPT_CREATION}}": get_init_script_creation_instructions(),
        "{{RUN_INIT_INSTRUCTIONS}}": get_run_init_instructions(),
        "{{INIT_SCRIPT_FILES_LIST}}": get_init_script_files_list(),
        "{{INIT_SCRIPT_COMMIT_MESSAGE}}": get_init_script_commit_message(),
        "{{PROJECT_STRUCTURE_INIT_LINE}}": get_project_structure_init_line(),
        "{{RUN_APP_INSTRUCTIONS}}": get_run_app_instructions(),
        "{{ENV_VAR_INSTRUCTIONS}}": get_env_var_instructions(),
        "{{PROCESS_KILL_INSTRUCTIONS}}": get_process_kill_instructions(),
        "{{FILESYSTEM_CONSTRAINTS}}": get_filesystem_constraints(),
        "{{INIT_SCRIPT_NAME}}": info.init_script_name,
    }


# =============================================================================
# Module self-test
# =============================================================================

if __name__ == "__main__":
    print(f"Platform: {get_platform_name()}")
    print(f"Shell: {get_shell_name()}")
    print()
    print("=" * 60)
    print("Init Script Creation Instructions:")
    print("=" * 60)
    print(get_init_script_creation_instructions())
    print()
    print("=" * 60)
    print("Run Init Instructions:")
    print("=" * 60)
    print(get_run_init_instructions())
    print()
    print("=" * 60)
    print("Environment Variable Instructions:")
    print("=" * 60)
    print(get_env_var_instructions())
