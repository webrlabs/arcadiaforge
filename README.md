```bash
      _                        _ _       ______                   
     / \   _ __ ___ __ _   ___| (_) __ _|  ____|__  _ __ __ _  ___ 
    / _ \ | '__/ __/ _` | / _ | | |/ _` | |__ / _ \| '__/ _` |/ _ \
   / ___ \| | | (_| (_| || (_)| | | (_| |  __| (_) | | | (_| |  __/
  /_/   \_\_|  \___\__,_| \___|_|_|\__,_|_|   \___/|_|  \__, |\___|
                                                        |___/        
                     Autonomous Coding Framework
```

# Arcadia Forge

An advanced harness for long-running autonomous coding, built on the Claude Agent SDK. This project is based on the Anthropic [autonomous-coding quickstart](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding) and extends it with sophisticated orchestration, safety, and observability features.

**Cross-Platform Support:** Works on Windows, macOS, and Linux with platform-specific init scripts and commands.

## Installation

### Step 1: Install Node.js and Claude Code CLI

First, ensure you have [Node.js](https://nodejs.org/) (v18+) installed, then install the Claude Code CLI:

```bash
npm install -g @anthropic-ai/claude-code
```

Verify the installation:
```bash
claude --version
```

### Step 2: Set Up Python Environment

Create and activate a conda/mamba environment with the required dependencies:

```bash
# Using mamba (recommended for speed)
mamba env create --file environment.yaml
mamba activate arcadiaforge

# Or using conda
conda env create --file environment.yaml
conda activate arcadiaforge
```

Verify the SDK is installed:
```bash
pip show claude-code-sdk
```

### Step 3: Configure Authentication

Generate an OAuth token for Claude Code:

```bash
claude setup-token
```

Then create your environment file:

```bash
cp .env.example .env
```

Edit `.env` and add your token:
```
CLAUDE_CODE_OAUTH_TOKEN=your_token_here
```

**Optional integrations** (see `.env.example` for details):
- `GITHUB_PERSONAL_ACCESS_TOKEN` - For GitHub MCP server integration
- `BRAVE_API_KEY` - For Brave Search MCP server integration

**Cost Control Settings** (optional):
- `ARCADIA_MAX_BUDGET` - Maximum USD budget per run (default: 10.0)
- `ARCADIA_INPUT_COST` - Cost per 1k input tokens (default: 0.003)
- `ARCADIA_OUTPUT_COST` - Cost per 1k output tokens (default: 0.015)

## Quick Start

Start the autonomous agent to build a project:

```bash
python -m arcadiaforge --project-dir ./my_project
```

For a quick test run with limited iterations:
```bash
python -m arcadiaforge --project-dir ./my_project --max-iterations 3
```

### Additional CLI Tools

| Command | Description |
|---------|-------------|
| `autonomous-agent` | Primary entry point for autonomous coding |
| `checkpoint-cli` | Manage project checkpoints and rollbacks |
| `events-cli` | Inspect session events and history |
| `metrics-cli` | View performance metrics |

## Important Timing Expectations

> **Warning: This demo takes a long time to run!**

- **First session (initialization):** The agent generates a `feature_list.json` with 200 test cases. This takes several minutes and may appear to hang - this is normal. The agent is writing out all the features.

- **Subsequent sessions:** Each coding iteration can take **5-15 minutes** depending on complexity.

- **Full app:** Building all 200 features typically requires **many hours** of total runtime across multiple sessions.

**Tip:** The 200 features parameter in the prompts is designed for comprehensive coverage. If you want faster demos, you can modify `arcadiaforge/prompts/initializer_prompt.md` to reduce the feature count (e.g., 20-50 features for a quicker demo).

## How It Works

### Core Capabilities

Arcadia Forge extends the basic autonomous coding pattern with several enterprise-grade features:

- **Advanced Auditing:** Automated, periodic review of completed features with targeted detection for high-risk changes (security, payments, sensitive data).
- **Cost Control & Budgeting:** Configurable USD budget limits with real-time usage tracking and safety cutoffs to prevent runaway costs.
- **Semantic Checkpointing:** Git-integrated state management that allows for reliable session rollbacks, semantic versioning of progress, and graceful pause/resume.
- **Risk-Aware Safety:** Pre-execution risk classification (Levels 1-5) for every tool call, with configurable gating and safety protocols.
- **Intelligent Escalation:** A rules-based engine that triggers human intervention for low-confidence decisions, repeated failures, or high-risk operations.
- **Automated Failure Analysis:** Root-cause detection with pattern matching across sessions and automated fix suggestions.
- **Tiered Memory System:** Optimized context management using Hot, Warm, and Cold memory tiers to maintain efficiency in long-running projects.
- **Observability & Metrics:** Comprehensive event logging, performance metrics, and structured traceability for every agent decision.

### Two-Agent Pattern

1. **Initializer Agent (Session 1):** Reads `app_spec.txt`, creates `feature_list.json` with 200 test cases, sets up project structure, and initializes git.

2. **Coding Agent (Sessions 2+):** Picks up where the previous session left off, implements features one by one, and marks them as passing in `feature_list.json`.

### Session Management

- Each session runs with a fresh context window
- Progress is persisted via `feature_list.json` and git commits
- The agent auto-continues between sessions (3 second delay)
- Press `Ctrl+C` to pause; run the same command to resume

## Security Model

This demo uses a defense-in-depth security approach (see `arcadiaforge/security.py` and `arcadiaforge/client.py`):

1. **OS-level Sandbox:** Bash commands run in an isolated environment
2. **Filesystem Restrictions:** File operations restricted to the project directory only
3. **Platform-Aware Allowlist:** Only specific commands are permitted, with platform-specific variations:

**Common Commands (all platforms):**
- File inspection: `ls`, `cat`, `head`, `tail`, `wc`, `grep`
- Node.js: `npm`, `node`, `npx`
- Version control: `git`
- Python: `python`, `pip`, `conda`, `mamba`
- Other: `curl`, `echo`, `sleep`

**Linux / macOS specific:**
- Process management: `pkill` (dev processes only), `lsof`
- File permissions: `chmod` (+x only)
- Init script: `./init.sh`

**Windows specific:**
- Process management: `taskkill` (dev processes only)
- Commands: `dir`, `type`, `start`, `powershell`
- Init scripts: `init.bat`, `init.ps1`

Commands not in the allowlist are blocked by the security hook.


## Project Structure

```
arcadia-forge/
|- autonomous_agent.py            # Compatibility wrapper
|- pyproject.toml                 # Package metadata and entrypoints
|- requirements.txt               # Python dependencies
|- arcadiaforge/                  # Main package
|     |- cli/                     # CLI entry points (autonomous-agent, checkpoint-cli, etc.)
|     |- agent.py                 # Agent session logic
|     |- audit.py                 # Automated feature auditing
|     |- checkpoint.py            # Semantic checkpointing and rollbacks
|     |- client.py                # Claude SDK client configuration
|     |- decision.py              # Decision logging and rationale capture
|     |- escalation.py            # Human-in-the-loop escalation engine
|     |- failure_analysis.py      # Automated root-cause and pattern detection
|     |- orchestrator.py          # High-level agent coordination
|     |- risk.py                  # Risk classification and gating
|     |- observability.py         # Metrics and event logging
|     |- security.py              # Command allowlist and validation
|     |- platform_utils.py        # Cross-platform OS detection utilities
|     |- prompts/                 # Agent instructions and templates
|     `- memory/                  # Tiered memory system (Hot/Warm/Cold)
`- tests/                         # Comprehensive pytest suite
```

## Generated Project Structure

After running, your project directory will contain several metadata files and directories used for tracking progress and ensuring safety:

**Common Metadata:**
- `feature_list.json`: The source of truth for all test cases and implementation status.
- `claude-progress.json`: High-level session progress log.
- `.events.jsonl`: Append-only event log for full session reconstruction and observability.
- `.metrics_cache.json`: Cached performance metrics for the project.
- `.risk/`: Directory containing risk assessments and custom risk patterns.
- `.failure_reports/`: Automated analysis reports for failed sessions.
- `.audit_state.json`: Tracking state for periodic feature auditing.
- `troubleshooting.json`: Shared knowledge base for common issues and fixes.
- `.claude_settings.json`: Security settings and project-specific configurations.

**Platform-Specific Scripts:**
- `init.sh` (Linux/macOS) or `init.bat`/`init.ps1` (Windows): Environment setup scripts.

**Application Code:**
- The generated application files will be located in the project root or a specified subdirectory.

## Running the Generated Application

After the agent completes (or pauses), you can run the generated application:

<details>
<summary><b>Linux / macOS</b></summary>

```bash
cd my_project

# Make the script executable and run it
chmod +x init.sh
./init.sh

# Or manually (typical for Node.js apps):
npm install
npm run dev
```
</details>

<details>
<summary><b>Windows (Command Prompt)</b></summary>

```cmd
cd my_project

:: Run the setup script
init.bat

:: Or manually:
npm install
npm run dev
```
</details>

<details>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
cd my_project

# Run the PowerShell setup script
powershell -ExecutionPolicy Bypass -File .\init.ps1

# Or manually:
npm install
npm run dev
```
</details>

The application will typically be available at `http://localhost:3000` or similar (check the agent's output or the init script for the exact URL).

## Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--project-dir` | Directory for the project | `./autonomous_demo_project` |
| `--max-iterations` | Max agent iterations | Unlimited |
| `--model` | Claude model to use | `claude-sonnet-4-5-20250929` |

## Customization

### Changing the Application

Edit `arcadiaforge/prompts/app_spec.txt` to specify a different application to build.

### Adjusting Feature Count

Edit `arcadiaforge/prompts/initializer_prompt.md` and change the "200 features" requirement to a smaller number for faster demos.

### Configuring Budget Limits

Set the `ARCADIA_MAX_BUDGET` environment variable to limit spending (e.g., `ARCADIA_MAX_BUDGET=5.0` for a $5 limit). The agent will automatically stop if this limit is exceeded. Token costs can be adjusted via `ARCADIA_INPUT_COST` and `ARCADIA_OUTPUT_COST` to match different model pricing.

### Modifying Allowed Commands

Edit `arcadiaforge/security.py` to add or remove commands. Commands are organized into:
- `_COMMON_COMMANDS` - Available on all platforms
- `_WINDOWS_COMMANDS` - Windows-specific commands
- `_UNIX_COMMANDS` - Linux/macOS-specific commands

### Adding Platform-Specific Prompt Content

Edit `arcadiaforge/prompts/platform_instructions.py` to modify platform-specific instructions. Available placeholders in prompt templates:
- `{{INIT_SCRIPT_CREATION}}` - Instructions for creating init scripts
- `{{RUN_INIT_INSTRUCTIONS}}` - Instructions for running init scripts
- `{{INIT_SCRIPT_NAME}}` - Name of the init script (init.sh, init.bat)
- `{{PLATFORM_NAME}}` - Current platform name (Windows, Linux, Macos)

## Troubleshooting

**"Appears to hang on first run"**
This is normal. The initializer agent is generating 200 detailed test cases, which takes significant time. Watch for `[Tool: ...]` output to confirm the agent is working.

**"Command blocked by security hook"**
The agent tried to run a command not in the allowlist. This is the security system working as intended. If needed, add the command to the appropriate set in `arcadiaforge/security.py`:
- `_COMMON_COMMANDS` for cross-platform commands
- `_WINDOWS_COMMANDS` for Windows-specific commands
- `_UNIX_COMMANDS` for Linux/macOS-specific commands

**"API key not set"**
Ensure `CLAUDE_CODE_OAUTH_TOKEN` is set. Either:
1. Add it to your `.env` file (recommended): `CLAUDE_CODE_OAUTH_TOKEN=your_token_here`
2. Or set it in your environment:
   - Linux/macOS: `export CLAUDE_CODE_OAUTH_TOKEN='your-token'`
   - Windows CMD: `set CLAUDE_CODE_OAUTH_TOKEN=your-token`
   - Windows PowerShell: `$env:CLAUDE_CODE_OAUTH_TOKEN="your-token"`

**"PowerShell script execution is disabled" (Windows)**
Run PowerShell as Administrator and execute:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
Or run init scripts with the bypass flag:
```powershell
powershell -ExecutionPolicy Bypass -File .\init.ps1
```

**"Permission denied: ./init.sh" (Linux/macOS)**
Make the script executable first:
```bash
chmod +x init.sh
./init.sh
```

**"pkill/taskkill blocked"**
Process killing is restricted to dev-related processes only (node, npm, npx, python, vite, next). To kill other processes, you'll need to do it manually outside the agent.

## Cross-Platform Development

This project automatically detects the operating system and adjusts:
- **Init scripts:** Creates `init.sh` on Unix or `init.bat`/`init.ps1` on Windows
- **Commands:** Uses platform-appropriate commands (e.g., `pkill` vs `taskkill`)
- **Prompts:** Agent instructions adapt to the current platform
- **Output:** User-facing messages show platform-specific instructions

The detection is handled by `platform_utils.py` which provides:
- `detect_os()` - Returns `OSType.WINDOWS`, `OSType.MACOS`, or `OSType.LINUX`
- `get_platform_info()` - Returns complete platform configuration
- Various helper functions for generating platform-specific instructions

## License

Internal Anthropic use.
