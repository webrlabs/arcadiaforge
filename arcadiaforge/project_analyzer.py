"""
Project Analyzer
================

Analyzes app_spec.txt to determine project type and required tools.

Two modes of operation:
1. Quick mode: Uses keyword matching for fast startup (no API call)
2. Agent mode: Uses Claude to intelligently analyze the spec and select tools

The agent mode provides better accuracy for complex or hybrid projects.
"""

import json
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

from arcadiaforge.config import get_default_model
from arcadiaforge.output import print_info, print_subheader, print_muted, print_warning, console, icon


class ProjectType(Enum):
    """Types of projects the framework can build."""
    WEB_APP = auto()           # React, Vue, Next.js, etc. - needs browser/Puppeteer
    CLI_TOOL = auto()          # Command-line applications - terminal screenshots
    DESKTOP_APP = auto()       # Desktop GUI apps - native screenshots
    API_SERVICE = auto()       # REST/GraphQL APIs - no UI, test via HTTP
    DATA_PIPELINE = auto()     # Data processing, ML - verify outputs via files
    SIMULATION = auto()        # OpenFOAM, scientific computing - file-based verification
    LIBRARY = auto()           # Python/JS packages - test via unit tests
    MOBILE_APP = auto()        # iOS/Android - device screenshots (external)
    GAME = auto()              # Game development - screenshots optional
    UNKNOWN = auto()           # Fall back to full toolset


@dataclass
class ToolProfile:
    """Configuration for which tools a project type needs."""
    name: str
    description: str

    # MCP servers to enable
    puppeteer_enabled: bool = False
    fetch_enabled: bool = True
    postgres_enabled: bool = False
    sqlite_enabled: bool = False

    # Screenshot method
    screenshot_method: str = "none"  # "puppeteer", "native", "none"

    # Verification method
    verification_method: str = "files"  # "browser", "files", "tests", "api"

    # Node.js requirement
    node_required: bool = False

    # Additional notes for the agent
    agent_notes: str = ""


# Predefined tool profiles for each project type
TOOL_PROFILES: Dict[ProjectType, ToolProfile] = {
    ProjectType.WEB_APP: ToolProfile(
        name="Web Application",
        description="Frontend web app with browser UI",
        puppeteer_enabled=True,
        screenshot_method="puppeteer",
        verification_method="browser",
        node_required=True,
        agent_notes="Use puppeteer_screenshot() to capture UI state. Navigate to pages and interact with elements.",
    ),

    ProjectType.CLI_TOOL: ToolProfile(
        name="CLI Tool",
        description="Command-line application",
        puppeteer_enabled=False,
        screenshot_method="native",
        verification_method="tests",
        node_required=False,
        agent_notes="Use native_screenshot() to capture terminal output if needed. Verify via test output and exit codes.",
    ),

    ProjectType.DESKTOP_APP: ToolProfile(
        name="Desktop Application",
        description="Desktop GUI application",
        puppeteer_enabled=False,
        screenshot_method="native",
        verification_method="files",
        node_required=False,
        agent_notes="Use native_screenshot() to capture the application window. May need to run the app first.",
    ),

    ProjectType.API_SERVICE: ToolProfile(
        name="API Service",
        description="Backend API (REST, GraphQL, etc.)",
        puppeteer_enabled=False,
        fetch_enabled=True,
        screenshot_method="none",
        verification_method="api",
        node_required=False,
        agent_notes="No screenshots needed. Verify endpoints by making HTTP requests and checking responses.",
    ),

    ProjectType.DATA_PIPELINE: ToolProfile(
        name="Data Pipeline",
        description="Data processing, ETL, or ML pipeline",
        puppeteer_enabled=False,
        screenshot_method="none",
        verification_method="files",
        node_required=False,
        agent_notes="No screenshots needed. Verify by checking output files, logs, and data integrity.",
    ),

    ProjectType.SIMULATION: ToolProfile(
        name="Simulation",
        description="Scientific simulation (CFD, FEM, etc.)",
        puppeteer_enabled=False,
        screenshot_method="none",
        verification_method="files",
        node_required=False,
        agent_notes="No browser screenshots needed. Verify via simulation output files, convergence logs, and results data. May generate visualization images from results.",
    ),

    ProjectType.LIBRARY: ToolProfile(
        name="Library/Package",
        description="Reusable library or package",
        puppeteer_enabled=False,
        screenshot_method="none",
        verification_method="tests",
        node_required=False,
        agent_notes="No screenshots needed. Verify via unit tests and integration tests. Check test coverage.",
    ),

    ProjectType.MOBILE_APP: ToolProfile(
        name="Mobile App",
        description="iOS or Android application",
        puppeteer_enabled=False,
        screenshot_method="none",  # Would need device/emulator
        verification_method="tests",
        node_required=True,  # Often uses React Native, Flutter, etc.
        agent_notes="Cannot capture mobile screenshots directly. Focus on tests and build verification.",
    ),

    ProjectType.GAME: ToolProfile(
        name="Game",
        description="Video game or interactive experience",
        puppeteer_enabled=False,
        screenshot_method="native",
        verification_method="files",
        node_required=False,
        agent_notes="Use native_screenshot() if game runs in a window. Verify assets, builds, and test scenes.",
    ),

    ProjectType.UNKNOWN: ToolProfile(
        name="Unknown",
        description="Unrecognized project type - using full toolset",
        puppeteer_enabled=True,
        screenshot_method="puppeteer",
        verification_method="browser",
        node_required=True,
        agent_notes="Project type not recognized. All tools enabled as fallback.",
    ),
}


# Keywords for detecting project types
PROJECT_TYPE_KEYWORDS: Dict[ProjectType, List[str]] = {
    ProjectType.WEB_APP: [
        "react", "vue", "angular", "next.js", "nextjs", "nuxt", "svelte",
        "frontend", "web app", "webapp", "website", "browser", "html", "css",
        "tailwind", "bootstrap", "web interface", "web ui", "dashboard",
        "single page", "spa", "pwa", "web application",
    ],

    ProjectType.CLI_TOOL: [
        "cli", "command line", "command-line", "terminal", "console app",
        "shell", "argparse", "click", "typer", "commander", "yargs",
        "command interface", "terminal app", "console application",
    ],

    ProjectType.DESKTOP_APP: [
        "desktop", "electron", "tauri", "qt", "pyqt", "tkinter", "wxpython",
        "gtk", "win32", "cocoa", "native app", "gui application", "desktop app",
        "windows app", "macos app", "linux app",
    ],

    ProjectType.API_SERVICE: [
        "api", "rest", "graphql", "grpc", "fastapi", "flask", "express",
        "django rest", "backend", "microservice", "endpoint", "server",
        "web service", "restful", "api service", "backend service",
    ],

    ProjectType.DATA_PIPELINE: [
        "pipeline", "etl", "data processing", "airflow", "luigi", "prefect",
        "dagster", "dbt", "spark", "pandas", "data engineering", "ml pipeline",
        "machine learning", "data science", "analytics", "data lake",
        "data warehouse", "batch processing", "stream processing",
    ],

    ProjectType.SIMULATION: [
        "openfoam", "cfd", "fem", "fea", "simulation", "ansys", "abaqus",
        "comsol", "matlab", "simulink", "fluent", "star-ccm", "lammps",
        "computational", "solver", "mesh", "turbulence", "fluid dynamics",
        "finite element", "finite volume", "physics simulation", "numerical",
    ],

    ProjectType.LIBRARY: [
        "library", "package", "module", "sdk", "framework", "toolkit",
        "npm package", "pypi", "pip install", "published", "reusable",
        "utility library", "helper functions",
    ],

    ProjectType.MOBILE_APP: [
        "mobile", "ios", "android", "react native", "flutter", "swift",
        "kotlin", "xamarin", "cordova", "ionic", "phone", "tablet",
        "mobile app", "native mobile", "cross-platform mobile",
    ],

    ProjectType.GAME: [
        "game", "unity", "unreal", "godot", "pygame", "phaser", "gamedev",
        "game engine", "sprite", "level", "player", "enemy", "score",
        "game development", "video game", "2d game", "3d game",
    ],
}


@dataclass
class ProjectAnalysis:
    """Result of analyzing a project specification."""
    detected_type: ProjectType
    confidence: float  # 0.0 to 1.0
    profile: ToolProfile
    keywords_found: List[str] = field(default_factory=list)
    all_scores: Dict[ProjectType, float] = field(default_factory=dict)

    def get_mcp_config(self) -> Dict:
        """Generate mcp_config.json content based on analysis."""
        return {
            "puppeteer": {"enabled": self.profile.puppeteer_enabled},
            "fetch": {"enabled": self.profile.fetch_enabled},
            "postgres": {"enabled": self.profile.postgres_enabled},
            "sqlite": {"enabled": self.profile.sqlite_enabled},
        }


class ProjectAnalyzer:
    """
    Analyzes app_spec.txt to determine project type and required tools.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.spec_path = project_dir / "app_spec.txt"

    def _read_spec_text(self) -> str:
        try:
            return self.spec_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return self.spec_path.read_text(encoding="cp1252")
            except UnicodeDecodeError:
                return self.spec_path.read_text(encoding="utf-8", errors="replace")

    def analyze(self) -> ProjectAnalysis:
        """
        Analyze the project specification and return tool recommendations.

        Returns:
            ProjectAnalysis with detected type and tool profile
        """
        if not self.spec_path.exists():
            return ProjectAnalysis(
                detected_type=ProjectType.UNKNOWN,
                confidence=0.0,
                profile=TOOL_PROFILES[ProjectType.UNKNOWN],
            )

        spec_text = self._read_spec_text().lower()

        # Score each project type based on keyword matches
        scores: Dict[ProjectType, float] = {}
        keywords_found: Dict[ProjectType, List[str]] = {}

        for project_type, keywords in PROJECT_TYPE_KEYWORDS.items():
            score = 0.0
            found = []

            for keyword in keywords:
                # Count occurrences (weighted by specificity)
                count = len(re.findall(r'\b' + re.escape(keyword) + r'\b', spec_text))
                if count > 0:
                    # More specific keywords get higher weight
                    weight = len(keyword.split()) * 0.5 + 1.0
                    score += count * weight
                    found.append(keyword)

            scores[project_type] = score
            keywords_found[project_type] = found

        # Find the highest scoring type
        if not any(scores.values()):
            detected_type = ProjectType.UNKNOWN
            confidence = 0.0
            found_keywords = []
        else:
            max_score = max(scores.values())
            total_score = sum(scores.values())

            detected_type = max(scores.keys(), key=lambda k: scores[k])
            confidence = min(1.0, max_score / 10.0)  # Normalize confidence
            found_keywords = keywords_found[detected_type]

        profile = TOOL_PROFILES[detected_type]

        return ProjectAnalysis(
            detected_type=detected_type,
            confidence=confidence,
            profile=profile,
            keywords_found=found_keywords,
            all_scores=scores,
        )

    def print_analysis(self, analysis: ProjectAnalysis) -> None:
        """Print the analysis results to the console."""
        print_subheader("Project Analysis")

        console.print(f"  [af.info]Detected type:[/] [af.header]{analysis.profile.name}[/]")
        console.print(f"  [af.muted]Confidence:[/] {analysis.confidence:.0%}")

        if analysis.keywords_found:
            keywords_str = ", ".join(analysis.keywords_found[:5])
            if len(analysis.keywords_found) > 5:
                keywords_str += f" (+{len(analysis.keywords_found) - 5} more)"
            console.print(f"  [af.muted]Keywords found:[/] {keywords_str}")

        console.print()
        console.print(f"  [af.muted]Screenshot method:[/] {analysis.profile.screenshot_method}")
        console.print(f"  [af.muted]Verification:[/] {analysis.profile.verification_method}")
        console.print(f"  [af.muted]Node.js required:[/] {'Yes' if analysis.profile.node_required else 'No'}")
        console.print(f"  [af.muted]Puppeteer enabled:[/] {'Yes' if analysis.profile.puppeteer_enabled else 'No'}")
        console.print()


def analyze_project(project_dir: Path) -> ProjectAnalysis:
    """
    Analyze a project and return the analysis result.

    This is the main entry point for project analysis.

    Args:
        project_dir: Path to the project directory containing app_spec.txt

    Returns:
        ProjectAnalysis with detected type and tool profile
    """
    analyzer = ProjectAnalyzer(project_dir)
    analysis = analyzer.analyze()
    analyzer.print_analysis(analysis)
    return analysis


def get_agent_context(analysis: ProjectAnalysis) -> str:
    """
    Generate context text for the agent about tool usage.

    This text is injected into the agent's prompt to inform it
    about the appropriate tools to use for this project type.

    Args:
        analysis: The project analysis result

    Returns:
        Context string for the agent prompt
    """
    profile = analysis.profile

    lines = [
        f"## Project Type: {profile.name}",
        "",
        profile.agent_notes,
        "",
    ]

    if profile.screenshot_method == "none":
        lines.extend([
            "**Screenshot Policy:** This project does not require visual screenshots.",
            "Verify features through test results, file outputs, and API responses instead.",
            "Do NOT attempt to use puppeteer_screenshot() - it is not available.",
        ])
    elif profile.screenshot_method == "native":
        lines.extend([
            "**Screenshot Policy:** Use native_screenshot() to capture the screen.",
            "This captures the desktop/terminal without requiring a browser.",
            "Do NOT use puppeteer_screenshot() - use native_screenshot() instead.",
        ])
    else:  # puppeteer
        lines.extend([
            "**Screenshot Policy:** Use puppeteer_screenshot() to capture web UI.",
            "Navigate to the appropriate URL before taking screenshots.",
        ])

    if profile.verification_method == "files":
        lines.extend([
            "",
            "**Verification:** Check output files, logs, and generated data.",
            "Features can be marked as passing based on correct file outputs.",
        ])
    elif profile.verification_method == "tests":
        lines.extend([
            "",
            "**Verification:** Run the test suite to verify features.",
            "Features can be marked as passing when their tests pass.",
        ])
    elif profile.verification_method == "api":
        lines.extend([
            "",
            "**Verification:** Make HTTP requests to test API endpoints.",
            "Features can be marked as passing based on correct API responses.",
        ])

    return "\n".join(lines)


# =============================================================================
# Agent-Based Tool Selection
# =============================================================================

TOOL_SELECTION_PROMPT = '''You are analyzing a project specification to determine what tools are needed.

Read the following app_spec.txt and determine:
1. What type of project this is
2. Whether it has a web UI that needs browser automation
3. How features should be verified (screenshots, tests, file outputs, API responses)

## App Specification:
{spec_content}

## Available Tool Categories:

1. **Browser/Puppeteer** - For web apps with UI
   - puppeteer_navigate, puppeteer_screenshot, puppeteer_click, puppeteer_fill
   - Use when: React, Vue, Angular, Next.js, or any web frontend

2. **Native Screenshot** - For desktop/CLI apps
   - native_screenshot, capture_terminal_output
   - Use when: CLI tools, desktop apps, terminal-based apps

3. **No Screenshots** - For headless/backend projects
   - Use when: APIs, data pipelines, simulations, libraries
   - Verify via: file outputs, test results, API responses

## Respond with JSON only:

```json
{{
  "project_type": "<one of: web_app, cli_tool, desktop_app, api_service, data_pipeline, simulation, library, game>",
  "project_description": "<brief 1-line description>",
  "needs_browser": <true/false>,
  "needs_native_screenshot": <true/false>,
  "needs_node_js": <true/false>,
  "verification_method": "<one of: browser, tests, files, api>",
  "screenshot_method": "<one of: puppeteer, native, none>",
  "reasoning": "<brief explanation of your choices>"
}}
```

Respond ONLY with the JSON block, no other text.'''


@dataclass
class AgentToolSelection:
    """Result of agent-based tool selection."""
    project_type: str
    project_description: str
    needs_browser: bool
    needs_native_screenshot: bool
    needs_node_js: bool
    verification_method: str
    screenshot_method: str
    reasoning: str

    def to_profile(self) -> ToolProfile:
        """Convert agent selection to a ToolProfile."""
        return ToolProfile(
            name=self.project_type.replace("_", " ").title(),
            description=self.project_description,
            puppeteer_enabled=self.needs_browser,
            screenshot_method=self.screenshot_method,
            verification_method=self.verification_method,
            node_required=self.needs_node_js,
            agent_notes=self.reasoning,
        )


def parse_agent_response(response_text: str) -> Optional[AgentToolSelection]:
    """
    Parse the agent's JSON response into an AgentToolSelection.

    Args:
        response_text: The raw response from the agent

    Returns:
        AgentToolSelection if parsing succeeds, None otherwise
    """
    try:
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON
            json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                return None

        data = json.loads(json_str)

        return AgentToolSelection(
            project_type=data.get("project_type", "unknown"),
            project_description=data.get("project_description", ""),
            needs_browser=data.get("needs_browser", False),
            needs_native_screenshot=data.get("needs_native_screenshot", False),
            needs_node_js=data.get("needs_node_js", False),
            verification_method=data.get("verification_method", "files"),
            screenshot_method=data.get("screenshot_method", "none"),
            reasoning=data.get("reasoning", ""),
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print_warning(f"Failed to parse agent tool selection: {e}")
        return None


async def analyze_project_with_agent(project_dir: Path, model: str = None) -> Optional[ProjectAnalysis]:
    """
    Use Claude to analyze the project spec and select appropriate tools.

    This provides more intelligent tool selection than keyword matching,
    especially for hybrid or unusual projects.

    Args:
        project_dir: Path to the project directory
        model: Claude model to use (defaults to configured model from env/config)

    Returns:
        ProjectAnalysis if successful, None if analysis fails
    """
    from anthropic import Anthropic

    if model is None:
        model = get_default_model()

    spec_path = project_dir / "app_spec.txt"
    if not spec_path.exists():
        print_warning("No app_spec.txt found for agent analysis")
        return None

    spec_content = ProjectAnalyzer(project_dir)._read_spec_text()

    # Truncate if too long (save tokens)
    if len(spec_content) > 8000:
        spec_content = spec_content[:8000] + "\n\n[... truncated for analysis ...]"

    prompt = TOOL_SELECTION_PROMPT.format(spec_content=spec_content)

    try:
        client = Anthropic()

        print_info("Analyzing project to select appropriate tools...")

        response = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        response_text = response.content[0].text
        selection = parse_agent_response(response_text)

        if selection is None:
            print_warning("Could not parse agent response, falling back to keyword analysis")
            return None

        profile = selection.to_profile()

        # Map to closest ProjectType enum
        type_mapping = {
            "web_app": ProjectType.WEB_APP,
            "cli_tool": ProjectType.CLI_TOOL,
            "desktop_app": ProjectType.DESKTOP_APP,
            "api_service": ProjectType.API_SERVICE,
            "data_pipeline": ProjectType.DATA_PIPELINE,
            "simulation": ProjectType.SIMULATION,
            "library": ProjectType.LIBRARY,
            "game": ProjectType.GAME,
        }
        detected_type = type_mapping.get(selection.project_type, ProjectType.UNKNOWN)

        analysis = ProjectAnalysis(
            detected_type=detected_type,
            confidence=0.95,  # Agent analysis is high confidence
            profile=profile,
            keywords_found=[],  # Not applicable for agent analysis
            all_scores={},
        )

        # Print the analysis
        print_subheader("Agent Tool Selection")
        console.print(f"  [af.info]Project type:[/] [af.header]{profile.name}[/]")
        console.print(f"  [af.muted]Description:[/] {selection.project_description}")
        console.print()
        console.print(f"  [af.muted]Screenshot method:[/] {profile.screenshot_method}")
        console.print(f"  [af.muted]Verification:[/] {profile.verification_method}")
        console.print(f"  [af.muted]Browser needed:[/] {'Yes' if selection.needs_browser else 'No'}")
        console.print(f"  [af.muted]Node.js needed:[/] {'Yes' if selection.needs_node_js else 'No'}")
        console.print()
        console.print(f"  [af.muted]Reasoning:[/] {selection.reasoning}")
        console.print()

        return analysis

    except Exception as e:
        print_warning(f"Agent tool selection failed: {e}")
        print_info("Falling back to keyword-based analysis")
        return None


async def analyze_project_smart(project_dir: Path, use_agent: bool = True) -> ProjectAnalysis:
    """
    Smart project analysis - tries agent first, falls back to keywords.

    Args:
        project_dir: Path to the project directory
        use_agent: Whether to try agent-based analysis first

    Returns:
        ProjectAnalysis with tool configuration
    """
    if use_agent:
        analysis = await analyze_project_with_agent(project_dir)
        if analysis is not None:
            return analysis

    # Fall back to keyword-based analysis
    return analyze_project(project_dir)
