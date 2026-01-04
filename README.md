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

An advanced harness for long-running autonomous coding, built on the Claude Agent SDK. This project extends the Anthropic [autonomous-coding quickstart](https://github.com/anthropics/claude-quickstarts/tree/main/autonomous-coding) with enterprise-grade orchestration, safety, state management, and observability features.

**Cross-Platform Support:** Works on Windows, macOS, and Linux with platform-specific init scripts and commands.

## Key Features

| Feature | Description |
|---------|-------------|
| **Multi-Session Development** | Split work across many sessions with auto-continue and crash recovery |
| **Database-Backed State** | SQLite persistence for features, memory, checkpoints, and events |
| **200+ Feature Management** | Test cases with steps, dependencies, audit tracking, and evidence screenshots |
| **Defense-in-Depth Security** | Allowlist-based command validation, sandboxed bash, risk classification |
| **Cost Control** | Real-time budget tracking with configurable USD limits |
| **5-Level Autonomy** | Graduated levels from OBSERVE to FULL_AUTO with action gating |
| **Tiered Memory System** | Hot/Warm/Cold memory for efficient long-running context management |
| **Automated Auditing** | Periodic feature review with high-risk change detection |
| **Web Dashboard** | Real-time progress monitoring and activity visualization |
| **50+ Built-in Tools** | File ops, browser control, process management, evidence capture |

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

### CLI Commands

| Command | Description |
|---------|-------------|
| `python -m arcadiaforge` | Primary entry point for autonomous coding |
| `python -m arcadiaforge processes` | Show tracked development processes |
| `python -m arcadiaforge cleanup` | Clean up tracked processes |
| `python -m arcadiaforge dashboard` | Start the web dashboard |
| `checkpoint-cli` | Manage project checkpoints and rollbacks |
| `events-cli` | Inspect session events and history |
| `feature-cli` | Manage features database |
| `metrics-cli` | View performance metrics |

## Important Timing Expectations

> **Warning: This demo takes a long time to run!**

- **First session (initialization):** The agent generates 200+ test cases in the database. This takes several minutes and may appear to hang - this is normal. The agent is writing out all the features.

- **Subsequent sessions:** Each coding iteration can take **5-15 minutes** depending on complexity.

- **Full app:** Building all 200+ features typically requires **many hours** of total runtime across multiple sessions.

**Tip:** The 200 features parameter in the prompts is designed for comprehensive coverage. If you want faster demos, you can modify `arcadiaforge/prompts/initializer_prompt.md` to reduce the feature count (e.g., 20-50 features for a quicker demo).

## How It Works

### Core Architecture

Arcadia Forge uses a sophisticated multi-component architecture:

```
┌─────────────────────────────────────────────────────────────────┐
│                     SessionOrchestrator                         │
│  (Main loop: setup → execution → result processing → cleanup)   │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  Agent.py     │    │  FeatureList  │    │  MemoryMgr    │
│  (Claude SDK) │    │  (SQLite DB)  │    │  (Hot/Warm/   │
│               │    │               │    │   Cold)       │
└───────────────┘    └───────────────┘    └───────────────┘
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────────────────────────────────────────────────────┐
│                    .arcadia/project.db                        │
│  (Features, Sessions, Events, Memory, Checkpoints, Decisions) │
└───────────────────────────────────────────────────────────────┘
```

### Two-Agent Pattern

1. **Initializer Agent (Session 1):** Reads `app_spec.txt`, creates 200+ features in the database with detailed test steps, sets up project structure, and initializes git.

2. **Coding Agent (Sessions 2+):** Picks up where the previous session left off, implements features one by one, captures evidence screenshots, and marks them as passing.

### Session Management

- Each session runs with a fresh context window
- Progress is persisted in `.arcadia/project.db` and via git commits
- The agent auto-continues between sessions (3 second delay)
- Press `Ctrl+C` to pause; run the same command to resume
- Crash recovery via `session_state.json`

### Autonomy Levels

The framework supports five graduated autonomy levels:

| Level | Description | Allowed Actions |
|-------|-------------|-----------------|
| OBSERVE | Watch only | Read operations |
| PLAN | Can plan | Read + planning |
| EXECUTE_SAFE | Safe execution | Read + safe writes |
| EXECUTE_REVIEW | With review | All with human review |
| FULL_AUTO | Full autonomy | All operations |

### Tiered Memory System

- **Hot Memory:** Current session working state (recent actions, active errors, pending decisions)
- **Warm Memory:** Previous session summaries (features completed, patterns discovered, warnings)
- **Cold Memory:** Historical knowledge base (proven patterns, solutions, aggregate statistics)

## Security Model

This demo uses a defense-in-depth security approach (see `arcadiaforge/security.py` and `arcadiaforge/client.py`):

1. **OS-level Sandbox:** Bash commands run in an isolated environment
2. **Filesystem Restrictions:** File operations restricted to the project directory only
3. **Risk Classification:** Every tool call is classified (Low/Medium/High/Critical)
4. **Auto-Checkpoints:** Triggered before destructive operations
5. **Platform-Aware Allowlist:** Only specific commands are permitted:

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

### Auto-Checkpoint Triggers

Checkpoints are automatically created before:
- `git push` / `git push -f`
- `git reset` / `git revert`
- `rm -rf` / `rmdir /s`
- `drop table` / `drop database`
- `npm uninstall` / `pip uninstall`

## Project Structure

```
arcadiaforge/
├── __main__.py                 # Module entry with subcommands
├── orchestrator.py             # SessionOrchestrator - main control loop
├── agent.py                    # Claude SDK integration
├── client.py                   # SDK client factory with MCP servers
│
├── Feature Management
├── feature_list.py             # Database-backed Feature class
├── feature_tools.py            # MCP tools: feature_*, evidence_*
│
├── Security & Capabilities
├── security.py                 # Command allowlist and hooks
├── capabilities.py             # System capability detection
├── platform_utils.py           # Cross-platform utilities
│
├── State & Memory
├── checkpoint.py               # Git-integrated checkpoints
├── session_state.py            # Crash recovery state
├── memory/                     # Tiered memory system
│
├── Autonomy & Risk
├── autonomy.py                 # 5-level autonomy management
├── risk.py                     # Risk classification
│
├── Tool Servers (Custom MCP)
├── file_tools.py               # File operations
├── process_tools.py            # Process tracking
├── server_tools.py             # Dev server control
├── evidence_tools.py           # Screenshot evidence
├── puppeteer_helpers.py        # Browser automation helpers
├── native_screenshot.py        # Desktop screenshots
│
├── Analysis & Observability
├── observability.py            # Event logging
├── metrics.py                  # Performance metrics
├── failure_analysis.py         # Root-cause detection
├── stall_detection.py          # Progress stall detection
│
├── Human Interface
├── escalation.py               # Escalation engine
├── human_interface.py          # User interaction
├── live_terminal.py            # Async terminal UI
│
├── Database
├── db/
│   ├── connection.py           # Async SQLite connection
│   └── models.py               # SQLAlchemy ORM models
│
├── Web Interface
├── web/
│   ├── dashboard.py            # FastAPI server
│   ├── backend/                # Backend services
│   └── frontend/               # Frontend application
│
├── Prompts
├── prompts/
│   ├── initializer_prompt.md   # Session 1 instructions
│   ├── coding_prompt.md        # Coding session instructions
│   ├── audit_prompt.md         # Feature audit instructions
│   └── platform_instructions.py
│
└── CLI Entrypoints
    └── cli/
        ├── autonomous_agent.py # Main CLI
        ├── checkpoint_cli.py   # Checkpoint management
        ├── events_cli.py       # Event inspection
        ├── feature_cli.py      # Feature management
        └── metrics_cli.py      # Metrics viewing
```

## Generated Project Structure

After running, your project directory will contain:

```
my_project/
├── .arcadia/                   # Agent metadata (gitignored)
│   ├── project.db              # SQLite database (features, memory, sessions)
│   └── session_state.json      # Crash recovery context
├── .events.jsonl               # Append-only event log
├── screenshots/                # Browser/desktop screenshots
├── verification/               # Evidence screenshots for features
├── .claude_settings.json       # Security permissions
├── claude-progress.json        # Session progress
├── .audit_state.json           # Audit tracking
├── .metrics_cache.json         # Performance metrics
├── troubleshooting.json        # Knowledge base
├── init.sh / init.bat / init.ps1  # Platform-specific setup
├── .gitignore
├── README.md
└── [application code]          # Generated based on app_spec
```

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

## Web Dashboard

Start the real-time monitoring dashboard:

```bash
python -m arcadiaforge dashboard --project-dir ./my_project --port 8080
```

The dashboard provides:
- Live feature progress tracking
- Session activity visualization
- Event log streaming
- Cost and metrics display

## Customization

### Changing the Application

Edit `arcadiaforge/prompts/app_spec.txt` to specify a different application to build.

### Adjusting Feature Count

Edit `arcadiaforge/prompts/initializer_prompt.md` and change the "200 features" requirement to a smaller number for faster demos.

### Configuring the Model

The default Claude model (`claude-sonnet-4-5-20250929`) can be changed via:

1. **Command line flag**: `--model claude-opus-4-20250514`
2. **Environment variable**: `ARCADIA_MODEL=claude-opus-4-20250514`
3. **Config file**: Create `arcadia_config.json` with `{"default_model": "claude-opus-4-20250514"}`

Precedence order: command line > environment variable > config file > default.

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
This is normal. The initializer agent is generating 200+ detailed test cases, which takes significant time. Watch for `[Tool: ...]` output to confirm the agent is working.

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

**"Database locked"**
If you see SQLite database lock errors, ensure only one instance of the agent is running against the same project directory.

## Recovery

- **Crash recovery:** Session state auto-saves for automatic recovery on restart
- **Checkpoint rollback:** Use `checkpoint-cli` to rollback to a previous state
- **Event reconstruction:** Query `.events.jsonl` for full session history
- **Failure analysis:** Check `.failure_reports/` for automated analysis

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

## Dependencies

### Python Requirements
- `claude-code-sdk>=0.0.25` - Claude Agent SDK
- `rich>=13.0.0` - Terminal formatting
- `python-dotenv>=1.0.0` - Environment variables
- `prompt_toolkit>=3.0.0` - Interactive terminal
- `sqlalchemy>=2.0.0` - ORM for database
- `aiosqlite>=0.19.0` - Async SQLite driver

### System Requirements
- Node.js v18+ (for Claude Code CLI and Puppeteer)
- Python 3.10+
- Git
- Optional: Docker, PostgreSQL

## License

Internal Anthropic use.
