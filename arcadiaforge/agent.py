"""
Agent Session Logic
===================

Core agent interaction functions for running autonomous coding sessions.
"""

import asyncio
import hashlib
import re
import signal
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from claude_code_sdk import ClaudeSDKClient

from arcadiaforge.client import create_client
from arcadiaforge.artifact_store import ArtifactStore
from arcadiaforge.checkpoint import CheckpointManager, CheckpointTrigger, SessionPauseManager, format_paused_session
from arcadiaforge.decision import DecisionLogger, DecisionType
from arcadiaforge.escalation import EscalationEngine, EscalationContext
from arcadiaforge.human_interface import HumanInterface, InjectionType
from arcadiaforge.hypotheses import HypothesisTracker, HypothesisType
from arcadiaforge.memory import MemoryManager
from arcadiaforge.metrics import MetricsCollector
from arcadiaforge.failure_analysis import FailureAnalyzer
from arcadiaforge.observability import Observability, EventType
from arcadiaforge.autonomy import AutonomyManager, AutonomyLevel, AutonomyConfig
from arcadiaforge.risk import RiskClassifier
from arcadiaforge.intervention_learning import InterventionLearner, InterventionType as LearningInterventionType
from arcadiaforge.feature_tools import set_checkpoint_manager, update_session_id, set_artifact_store
from arcadiaforge.feature_list import generate_status_file, FeatureList
from arcadiaforge.progress import print_session_header, print_progress_summary, count_passing_tests
from arcadiaforge.prompts import (
    get_initializer_prompt,
    get_coding_prompt,
    get_update_features_prompt,
    get_audit_prompt,
    copy_spec_to_project,
    copy_new_requirements_to_project,
    copy_feature_tool_to_project,
)
from arcadiaforge.audit import (
    should_run_audit,
    select_audit_candidates,
    save_audit_state,
    AUDIT_CADENCE_FEATURES,
    AUDIT_MAX_CANDIDATES,
    AUDIT_HIGH_RISK_COUNT,
    AUDIT_RANDOM_COUNT,
)
from arcadiaforge.output import (
    console,
    print_banner,
    print_config,
    print_tool_use,
    print_tool_result,
    print_agent_text,
    print_session_divider,
    print_status_complete,
    print_status_intervention,
    print_status_cyclic,
    print_status_no_progress,
    print_status_error,
    print_auto_continue,
    print_final_summary,
    print_update_mode_info,
    print_initializer_info,
    print_warning,
    reset_tool_tracker,
    print_error,
    print_info,
    print_success,
    get_live_terminal,
    is_live_terminal_active,
)


# Configuration
AUTO_CONTINUE_DELAY_SECONDS = 3

# Only very explicit "giving up" patterns - agent must clearly state it cannot continue
EXPLICIT_STOP_PATTERNS = [
    # Agent explicitly giving up or requesting human action
    r"(?i)I\s+(cannot|can't|am unable to)\s+(continue|proceed|complete)\s+(this|the)\s+(task|project|work)",
    r"(?i)stopping\s+(here|now)\s+(because|as|since)",
    r"(?i)human\s+intervention\s+(is\s+)?(required|needed|necessary)",
    r"(?i)please\s+(manually|yourself)\s+(configure|set up|provide|add)",
    r"(?i)you\s+(will\s+)?need\s+to\s+(manually|yourself)",
    r"(?i)requires?\s+(your|manual|human)\s+(intervention|action|input)",
]

# Patterns that indicate the project is complete
COMPLETION_PATTERNS = [
    r"(?i)all\s+\d+\s+tests?\s+(are\s+)?(now\s+)?pass",
    r"(?i)all\s+tests?\s+(are\s+)?(now\s+)?passing",
    r"(?i)project\s+(is\s+)?(now\s+)?(complete|finished|done)",
    r"(?i)100%\s+(of\s+)?(tests?\s+)?(complete|passing|done)",
]


@dataclass
class SessionHistory:
    """Tracks history across sessions to detect cyclic behavior."""
    error_hashes: list[str] = field(default_factory=list)
    blocked_commands: list[str] = field(default_factory=list)
    git_hashes: list[str] = field(default_factory=list)
    passing_counts: list[int] = field(default_factory=list)

    def add_error(self, error_text: str) -> None:
        """Add an error hash to track repeated errors."""
        # Hash the error to normalize minor variations
        error_hash = hashlib.md5(error_text.strip()[:200].encode()).hexdigest()[:8]
        self.error_hashes.append(error_hash)

    def add_blocked_command(self, command: str) -> None:
        """Track blocked commands."""
        self.blocked_commands.append(command.strip()[:100])

    def add_git_hash(self, git_hash: str) -> None:
        """Track git state to detect no file changes."""
        self.git_hashes.append(git_hash)

    def add_passing_count(self, count: int) -> None:
        """Track passing test counts."""
        self.passing_counts.append(count)

    def detect_cyclic_errors(self, threshold: int = 3) -> tuple[bool, str]:
        """Detect if the same error is repeating."""
        if len(self.error_hashes) < threshold:
            return False, ""
        recent = self.error_hashes[-10:]  # Look at last 10 errors
        counter = Counter(recent)
        most_common = counter.most_common(1)
        if most_common and most_common[0][1] >= threshold:
            return True, f"Same error repeated {most_common[0][1]} times"
        return False, ""

    def detect_cyclic_blocks(self, threshold: int = 3) -> tuple[bool, str]:
        """Detect if the same command keeps getting blocked."""
        if len(self.blocked_commands) < threshold:
            return False, ""
        recent = self.blocked_commands[-10:]
        counter = Counter(recent)
        most_common = counter.most_common(1)
        if most_common and most_common[0][1] >= threshold:
            return True, f"Command '{most_common[0][0][:50]}' blocked {most_common[0][1]} times"
        return False, ""

    def detect_no_git_changes(self, threshold: int = 3) -> tuple[bool, str]:
        """Detect if git state hasn't changed across iterations."""
        if len(self.git_hashes) < threshold:
            return False, ""
        recent = self.git_hashes[-threshold:]
        if len(set(recent)) == 1:
            return True, f"No file changes for {threshold} iterations"
        return False, ""

    def detect_no_test_progress(self, threshold: int = 3) -> tuple[bool, str]:
        """Detect if passing count hasn't changed."""
        if len(self.passing_counts) < threshold:
            return False, ""
        recent = self.passing_counts[-threshold:]
        if len(set(recent)) == 1 and recent[0] > 0:
            return True, f"Test count stuck at {recent[0]} for {threshold} iterations"
        return False, ""


def get_git_status_hash(project_dir: Path) -> str:
    """Get a hash of the current git status to detect changes."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10
        )
        # Also get the HEAD commit hash
        head_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10
        )
        combined = result.stdout + head_result.stdout
        return hashlib.md5(combined.encode()).hexdigest()[:12]
    except Exception:
        return "no-git"


def check_for_explicit_stop(response_text: str) -> tuple[bool, str]:
    """
    Check if the agent explicitly indicates it cannot continue.
    Only triggers on very clear "giving up" statements.

    Returns:
        (should_stop, reason) tuple
    """
    for pattern in EXPLICIT_STOP_PATTERNS:
        match = re.search(pattern, response_text)
        if match:
            return True, f"Agent indicated stop: '{match.group(0)}'"
    return False, ""


def check_for_completion(response_text: str, project_dir: Path) -> tuple[bool, str]:
    """
    Check if the agent indicates the project is complete.

    Returns:
        (is_complete, reason) tuple
    """
    # Check text patterns
    for pattern in COMPLETION_PATTERNS:
        if re.search(pattern, response_text):
            # Verify by checking actual test counts
            passing, total = count_passing_tests(project_dir)
            if total > 0 and passing == total:
                return True, f"All {total} tests passing - project complete!"
            elif passing > 0:
                # Agent claims complete but tests don't match
                return False, ""

    # Also check if all tests are actually passing
    passing, total = count_passing_tests(project_dir)
    if total > 0 and passing == total:
        return True, f"All {total} tests passing - project complete!"

    return False, ""


def check_for_cyclic_behavior(
    history: SessionHistory,
    error_threshold: int = 3,
    block_threshold: int = 3,
    git_threshold: int = 3,
) -> tuple[bool, str]:
    """
    Check session history for cyclic/stuck behavior patterns.

    Returns:
        (is_stuck, reason) tuple
    """
    # Check for repeated errors
    is_cyclic, reason = history.detect_cyclic_errors(error_threshold)
    if is_cyclic:
        return True, reason

    # Check for repeated blocked commands
    is_cyclic, reason = history.detect_cyclic_blocks(block_threshold)
    if is_cyclic:
        return True, reason

    # Check for no git changes (files not being modified)
    is_cyclic, reason = history.detect_no_git_changes(git_threshold)
    if is_cyclic:
        return True, reason

    return False, ""


class AuthenticationError(Exception):
    """Raised when API authentication fails."""
    pass


def is_authentication_error(error: Exception) -> bool:
    """Check if an exception is an authentication error."""
    error_str = str(error).lower()
    return any(pattern in error_str for pattern in [
        "authentication_error",
        "invalid bearer token",
        "invalid api key",
        "invalid_api_key",
        "401",
        "unauthorized",
        "please run /login",
    ])


@dataclass
class SessionResult:
    """Results from a single agent session."""
    status: str  # "continue", "intervention", "complete", "error", "auth_error"
    response_text: str
    error_texts: list[str] = field(default_factory=list)
    blocked_commands: list[str] = field(default_factory=list)
    reason: str = ""
    # Metrics for observability
    tool_calls: int = 0
    tool_errors: int = 0
    tool_blocked: int = 0


async def run_agent_session(
    client: ClaudeSDKClient,
    message: str,
    project_dir: Path,
    obs: Optional[Observability] = None,
    check_completion: bool = True,
    check_stop: bool = True,
    risk_classifier: Optional[RiskClassifier] = None,
    autonomy_manager: Optional[AutonomyManager] = None,
) -> SessionResult:
    """
    Run a single agent session using Claude Agent SDK.

    Args:
        client: Claude SDK client
        message: The prompt to send
        project_dir: Project directory path
        obs: Optional Observability instance for event logging

    Returns:
        SessionResult with status and collected data for history tracking
    """
    print_info("Sending prompt to Claude Agent SDK...")
    console.print()

    error_texts: list[str] = []
    blocked_commands: list[str] = []
    tool_calls = 0
    tool_errors = 0
    tool_blocked = 0

    # Chat interface: track tool IDs for proper event pairing
    import uuid as uuid_module
    tool_states: dict[str, dict] = {}
    pending_tool_ids: list[str] = []

    def _truncate_tool_result(text: str, limit: int = 1200) -> str:
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[:limit] + "\n... (truncated)"

    def _extract_screenshot_url(tool_name: str, result_text: str) -> Optional[str]:
        if tool_name != "mcp__puppeteer__puppeteer_screenshot" or not result_text:
            return None

        match = re.search(r"Screenshot captured and saved to:\s*([^\r\n]+)", result_text)
        if not match:
            return None

        path_str = match.group(1).strip()
        filename = Path(path_str).name
        if not filename:
            return None

        screenshot_path = project_dir / "screenshots" / filename
        if not screenshot_path.exists():
            return None

        project_id = project_dir.name
        return f"projects/{project_id}/screenshots/{filename}"

    # Helper to emit chat events when live terminal is active
    def emit_chat_event(event_type: str, **kwargs):
        if is_live_terminal_active():
            terminal = get_live_terminal()
            if event_type == "thinking":
                terminal.emit_thinking(kwargs.get("is_thinking", False))
            elif event_type == "agent_message":
                terminal.emit_agent_message(kwargs.get("content", ""))
            elif event_type == "tool_start":
                terminal.emit_tool_start(
                    kwargs.get("tool_id", ""),
                    kwargs.get("name", ""),
                    kwargs.get("summary", ""),
                    kwargs.get("input_data")
                )
            elif event_type == "tool_end":
                terminal.emit_tool_end(
                    kwargs.get("tool_id", ""),
                    kwargs.get("status", "completed"),
                    kwargs.get("result"),
                    kwargs.get("image_url")
                )

    try:
        # Emit thinking state
        emit_chat_event("thinking", is_thinking=True)

        # Send the query (SDK may print errors directly to console)
        await client.query(message)

        # Collect response text and show tool use
        response_text = ""

        async for msg in client.receive_response():
            msg_type = type(msg).__name__

            # Check for usage information
            usage = getattr(msg, "usage", None)
            if usage:
                input_tokens = getattr(usage, "input_tokens", 0)
                output_tokens = getattr(usage, "output_tokens", 0)
                
                if input_tokens > 0 or output_tokens > 0:
                    # Log usage event
                    if obs:
                        # Estimate cost locally for the event log
                        from arcadiaforge.config import BudgetConfig
                        b_conf = BudgetConfig.from_env()
                        
                        cost = (input_tokens / 1000) * b_conf.input_cost_per_1k + \
                               (output_tokens / 1000) * b_conf.output_cost_per_1k
                               
                        obs.log_event(
                            EventType.USAGE_REPORT,
                            data={
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "estimated_cost_usd": cost
                            }
                        )

            # Handle AssistantMessage (text and tool use)
            if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                for block in msg.content:
                    block_type = type(block).__name__

                    if block_type == "TextBlock" and hasattr(block, "text"):
                        response_text += block.text
                        print_agent_text(block.text)
                        # Chat interface: emit agent message
                        emit_chat_event("agent_message", content=block.text)
                    elif block_type == "ToolUseBlock" and hasattr(block, "name"):
                        tool_calls += 1
                        tool_use_id = getattr(block, "id", None) or str(uuid_module.uuid4())
                        input_data = getattr(block, "input", None)
                        input_str = str(input_data) if input_data is not None else ""
                        input_dict = input_data if isinstance(input_data, dict) else {}
                        tool_states[tool_use_id] = {
                            "name": block.name,
                            "input_str": input_str,
                            "input_dict": input_dict,
                            "start_time": time.time(),
                        }
                        pending_tool_ids.append(tool_use_id)

                        print_tool_use(block.name, input_str)
                        summary = input_str[:100] + "..." if len(input_str) > 100 else input_str
                        emit_chat_event("tool_start", tool_id=tool_use_id, name=block.name, summary=summary, input_data=input_dict)

                        if risk_classifier:
                            risk_assessment = risk_classifier.assess(block.name, input_dict)
                            if risk_assessment.risk_level.value >= 4:  # HIGH or CRITICAL
                                print_warning(f"High-risk action: {risk_assessment.action} (level {risk_assessment.risk_level.name})")

                        if obs:
                            obs.log_tool_call(
                                tool_name=block.name,
                                tool_input=input_dict,
                            )

            # Handle UserMessage (tool results)
            elif msg_type == "UserMessage" and hasattr(msg, "content"):
                for block in msg.content:
                    block_type = type(block).__name__

                    if block_type == "ToolResultBlock":
                        result_content = getattr(block, "content", "")
                        is_error = getattr(block, "is_error", False)
                        result_str = str(result_content)
                        result_preview = _truncate_tool_result(result_str)
                        result_lower = result_str.lower()

                        tool_use_id = getattr(block, "tool_use_id", None) or getattr(block, "id", None)
                        tool_state = None
                        if tool_use_id and tool_use_id in tool_states:
                            tool_state = tool_states.pop(tool_use_id)
                            if tool_use_id in pending_tool_ids:
                                pending_tool_ids.remove(tool_use_id)
                        elif pending_tool_ids:
                            fallback_id = pending_tool_ids.pop(0)
                            tool_state = tool_states.pop(fallback_id, None)
                            tool_use_id = fallback_id

                        tool_name = tool_state["name"] if tool_state else "unknown"
                        tool_input_str = tool_state["input_str"] if tool_state else ""
                        tool_input_dict = tool_state["input_dict"] if tool_state else {}
                        start_time = tool_state["start_time"] if tool_state else None
                        duration_ms = int((time.time() - start_time) * 1000) if start_time else None
                        image_url = _extract_screenshot_url(tool_name, result_str)

                        # Check if command was blocked by security policy
                        # These are expected behaviors, not cyclic errors
                        is_security_block = (
                            "blocked" in result_lower or
                            "not in the allowed" in result_lower or
                            "not allowed" in result_lower or
                            "permission denied" in result_lower or
                            "access denied" in result_lower
                        )

                        if is_error and is_security_block:
                            blocked_commands.append(tool_input_str)
                            tool_blocked += 1
                            print_tool_result("blocked", result_str)
                            # Chat interface: emit tool end with blocked status
                            if tool_use_id:
                                emit_chat_event("tool_end", tool_id=tool_use_id, status="failed", result=result_preview[:200])

                            # Log blocked event
                            if obs:
                                obs.log_tool_result(
                                    tool_name=tool_name,
                                    success=False,
                                    is_blocked=True,
                                    error_message=result_str[:200],
                                    duration_ms=duration_ms,
                                )
                            # Phase 5: Record blocked as failure for autonomy
                            if autonomy_manager:
                                autonomy_manager.record_outcome(success=False)
                        elif is_error:
                            error_texts.append(result_str[:500])
                            tool_errors += 1
                            print_tool_result("error", result_str)
                            # Chat interface: emit tool end with error status
                            if tool_use_id:
                                emit_chat_event("tool_end", tool_id=tool_use_id, status="failed", result=result_preview[:200])

                            # Log error event
                            if obs:
                                obs.log_tool_result(
                                    tool_name=tool_name,
                                    success=False,
                                    is_error=True,
                                    error_message=result_str[:200],
                                    duration_ms=duration_ms,
                                )
                            # Phase 5: Record error for autonomy
                            if autonomy_manager:
                                autonomy_manager.record_outcome(success=False)
                        else:
                            print_tool_result("done")
                            # Chat interface: emit tool end with completed status
                            if tool_use_id:
                                emit_chat_event(
                                    "tool_end",
                                    tool_id=tool_use_id,
                                    status="completed",
                                    result=result_preview,
                                    image_url=image_url,
                                )

                            # Log success event
                            if obs:
                                obs.log_tool_result(
                                    tool_name=tool_name,
                                    success=True,
                                    duration_ms=duration_ms,
                                )
                            # Phase 5: Record success for autonomy
                            if autonomy_manager:
                                autonomy_manager.record_outcome(success=True)

        # Chat interface: stop thinking indicator
        emit_chat_event("thinking", is_thinking=False)

        print_session_divider()

        if check_stop:
            # Check for explicit stop request from agent
            should_stop, stop_reason = check_for_explicit_stop(response_text)
            if should_stop:
                print_warning(f"Agent requested stop: {stop_reason}")
                return SessionResult(
                    status="intervention",
                    response_text=response_text,
                    error_texts=error_texts,
                    blocked_commands=blocked_commands,
                    reason=stop_reason,
                    tool_calls=tool_calls,
                    tool_errors=tool_errors,
                    tool_blocked=tool_blocked,
                )

        if check_completion:
            # Check for completion
            is_complete, completion_reason = check_for_completion(response_text, project_dir)
            if is_complete:
                print_success(completion_reason)
                return SessionResult(
                    status="complete",
                    response_text=response_text,
                    error_texts=error_texts,
                    blocked_commands=blocked_commands,
                    reason=completion_reason,
                    tool_calls=tool_calls,
                    tool_errors=tool_errors,
                    tool_blocked=tool_blocked,
                )

        return SessionResult(
            status="continue",
            response_text=response_text,
            error_texts=error_texts,
            blocked_commands=blocked_commands,
            tool_calls=tool_calls,
            tool_errors=tool_errors,
            tool_blocked=tool_blocked,
        )

    except Exception as e:
        # Chat interface: stop thinking on error
        emit_chat_event("thinking", is_thinking=False)

        error_str = str(e)

        # Check for authentication errors - these should not retry
        if is_authentication_error(e):
            # Note: The SDK prints its own "API Error: 401..." message above
            print_session_divider()
            console.print()
            console.print("[af.err bold]Authentication Failed[/]")
            console.print()
            console.print("[af.muted]Your API token is invalid or expired.[/]")
            console.print()
            console.print("[af.info]To fix this:[/]")
            console.print("  [af.number]1.[/] Run [af.accent]claude /login[/] in your terminal")
            console.print("  [af.number]2.[/] Copy the token and add it to your [af.accent].env[/] file:")
            console.print()
            console.print("     [af.muted]CLAUDE_CODE_OAUTH_TOKEN=your-token-here[/]")
            console.print()

            if obs:
                obs.log_error(
                    error_message=error_str,
                    error_type="authentication_error",
                )

            return SessionResult(
                status="auth_error",
                response_text=error_str,
                error_texts=[error_str],
                blocked_commands=blocked_commands,
                reason="Authentication failed - invalid or expired token",
                tool_calls=tool_calls,
                tool_errors=tool_errors,
                tool_blocked=tool_blocked,
            )

        print_error(f"Agent session error: {e}")

        # Log error event
        if obs:
            obs.log_error(
                error_message=error_str,
                error_type="session_exception",
            )

        return SessionResult(
            status="error",
            response_text=error_str,
            error_texts=[error_str],
            blocked_commands=blocked_commands,
            reason=error_str,
            tool_calls=tool_calls,
            tool_errors=tool_errors,
            tool_blocked=tool_blocked,
        )


from arcadiaforge.config import BudgetConfig


async def run_autonomous_agent(
    project_dir: Path,
    model: str,
    max_iterations: Optional[int] = None,
    new_requirements_path: Optional[Path] = None,
    num_new_features: Optional[int] = None,
    max_no_progress: int = 3,
    app_spec_path: Optional[Path] = None,
) -> None:
    """
    Run the autonomous agent loop.

    Args:
        project_dir: Directory for the project
        model: Claude model to use
        max_iterations: Maximum number of iterations (None for unlimited)
        new_requirements_path: Optional path to new requirements file to add features
        num_new_features: Optional number of new features to add (None = agent decides)
        max_no_progress: Stop after this many iterations with no progress (0 to disable)
        app_spec_path: Optional path to custom app spec file (default: packaged app_spec.txt)
    """
    # Print banner and configuration
    # print_banner()

    extra_config = {}
    if new_requirements_path:
        extra_config["New requirements"] = str(new_requirements_path)
    if app_spec_path:
        extra_config["App spec"] = str(app_spec_path)

    print_config(project_dir, model, max_iterations, extra_config)

    # Create project directory
    project_dir.mkdir(parents=True, exist_ok=True)

    # Initialize observability for event logging
    obs = Observability(project_dir)
    print_info(f"Event logging enabled: {obs.events_file}")

    # Initialize metrics collector and failure analyzer
    budget_config = BudgetConfig.from_env()
    metrics_collector = MetricsCollector(project_dir, budget_config)
    failure_analyzer = FailureAnalyzer(project_dir)

    # Initialize checkpoint manager
    checkpoint_mgr = CheckpointManager(project_dir)
    set_checkpoint_manager(checkpoint_mgr)
    print_info(f"Checkpoints enabled: {checkpoint_mgr.checkpoints_dir}")

    # Initialize artifact store
    artifact_store = ArtifactStore(project_dir)
    set_artifact_store(artifact_store)
    print_info(f"Artifact store enabled: {artifact_store.artifacts_dir}")

    # Initialize Phase 2: Human-in-the-Loop components
    decision_logger = DecisionLogger(project_dir)
    print_info(f"Decision logging enabled: {decision_logger.decisions_dir}")

    escalation_engine = EscalationEngine(project_dir)
    print_info(f"Escalation rules enabled: {len(escalation_engine.get_rules())} rules")

    pause_manager = SessionPauseManager(project_dir)
    human_interface = HumanInterface(project_dir)

    # Initialize Phase 3: Memory Architecture components
    # Note: session_id will be updated once we know the iteration number
    memory_manager = MemoryManager(project_dir, session_id=1)
    print_info("Memory system enabled: hot/warm/cold tiers (DB-backed)")

    hypothesis_tracker = HypothesisTracker(project_dir, session_id=1)
    print_info("Hypothesis tracking enabled (DB-backed)")

    # Initialize Phase 5: Advanced Autonomy components
    autonomy_config = AutonomyConfig(
        level=AutonomyLevel.EXECUTE_SAFE,  # Default: can execute safe actions
        auto_adjust=True,  # Enable dynamic level adjustment
        confidence_threshold=0.5,  # Reduce level below this confidence
    )
    autonomy_manager = AutonomyManager(project_dir, autonomy_config)
    print_info(f"Autonomy level: {autonomy_manager.current_level.name}")

    risk_classifier = RiskClassifier(project_dir)
    print_info(f"Risk classification enabled: {len(risk_classifier.patterns)} patterns")

    intervention_learner = InterventionLearner(project_dir)
    print_info(f"Intervention learning enabled: {len(intervention_learner.patterns)} learned patterns")

    # Check for paused session
    paused_session = pause_manager.get_paused_session()
    if paused_session:
        print_info("Found paused session:")
        console.print(format_paused_session(paused_session))
        console.print()

        # Resume the paused session
        resumed = pause_manager.resume_session()
        if resumed:
            print_success(f"Resumed session {resumed.session_id}")
            # Use the resume prompt if available
            if resumed.resume_prompt:
                print_info(f"Resume context: {resumed.resume_prompt}")
            if resumed.human_notes:
                print_info(f"Human notes: {resumed.human_notes}")

    # Setup signal handlers for graceful pause
    pause_requested = False

    def signal_handler(sig, frame):
        nonlocal pause_requested
        if pause_requested:
            # Second signal - force exit
            print_warning("\nForce exit requested. Exiting immediately.")
            sys.exit(1)
        pause_requested = True
        print_warning("\nPause requested. Will pause after current operation completes.")
        print_info("Press Ctrl+C again to force exit immediately.")
        human_interface.request_pause()

    # Register signal handlers (Windows compatible)
    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)

    # Check if this is a fresh start or continuation
    feature_list = FeatureList(project_dir)
    has_features = feature_list.exists()
    is_first_run = not has_features
    is_update_run = new_requirements_path is not None and has_features

    if is_update_run:
        print_update_mode_info(num_new_features)
        # Copy the new requirements file into the project directory
        copy_new_requirements_to_project(new_requirements_path, project_dir)
        # Write the num_new_features config if specified
        if num_new_features:
            config_file = project_dir / "update_config.txt"
            config_file.write_text(f"NUM_NEW_FEATURES={num_new_features}\n")
        print_progress_summary(project_dir)
    elif is_first_run:
        if new_requirements_path:
            print_error("Cannot use --new-requirements on a fresh project.")
            print_info("Start the project first, then use --new-requirements to add features.")
            return
        print_initializer_info()
        # Copy the app spec into the project directory for the agent to read
        copy_spec_to_project(project_dir, app_spec_path)
    else:
        print_info("Continuing existing project")
        print_progress_summary(project_dir)

    # Main loop with session history tracking
    iteration = 0
    consecutive_error_sessions = 0
    max_no_progress_iterations = max_no_progress  # 0 means disabled
    history = SessionHistory()

    while True:
        iteration += 1
        
        # Check budget before starting session
        is_over_budget, cost, percent_used = metrics_collector.check_budget()
        if is_over_budget:
            print_error(f"Budget Exceeded! (${cost:.2f} / ${budget_config.max_budget_usd:.2f})")
            obs.log_event(
                EventType.WARNING,
                data={"message": f"Budget exceeded: ${cost:.2f} > ${budget_config.max_budget_usd:.2f}"}
            )
            print_info("To continue, increase ARCADIA_MAX_BUDGET in environment or config.")
            break
            
        if percent_used > budget_config.warning_threshold:
            print_warning(f"Budget Warning: {percent_used:.1%} used (${cost:.2f})")

        # Update session IDs for Phase 3 components
        memory_manager.session_id = iteration
        memory_manager.hot.session_id = iteration
        hypothesis_tracker.session_id = iteration

        # Start memory session (get context from previous sessions)
        memory_context = memory_manager.start_session()

        # Check max iterations
        if max_iterations and iteration > max_iterations:
            obs.log_event(
                EventType.WARNING,
                data={"message": f"Reached max iterations ({max_iterations})"},
            )
            print_warning(f"Reached max iterations ({max_iterations})")
            print_info("To continue, run the script again without --max-iterations")
            break

        # Check for pause request before starting session
        if pause_requested:
            current_passing, total_tests = count_passing_tests(project_dir)
            latest_checkpoint = checkpoint_mgr.get_latest_checkpoint()

            # Create pause checkpoint
            pause_checkpoint = checkpoint_mgr.create_checkpoint(
                trigger=CheckpointTrigger.HUMAN_REQUEST,
                session_id=iteration,
                metadata={"reason": "pause_requested"},
                human_note="Session paused by user request",
            )

            # Save pause state
            pause_manager.pause_session(
                session_id=iteration,
                pause_reason="User requested pause (Ctrl+C)",
                current_feature=None,  # Could extract from history if available
                last_checkpoint_id=pause_checkpoint.checkpoint_id,
                resume_prompt="Continue implementing features from where we left off.",
                work_summary=f"Progress: {current_passing}/{total_tests} tests passing",
                iteration=iteration,
                features_passing=current_passing,
                features_total=total_tests,
            )

            print_info("Session paused successfully.")
            print_info(f"Checkpoint: {pause_checkpoint.checkpoint_id}")
            print_info("To resume: python agent.py")
            print_progress_summary(project_dir)
            break

        # Print session header
        print_session_header(iteration, is_first_run)

        # Start session in observability
        session_type = "initializer" if is_first_run else ("update" if is_update_run else "coding")
        obs.start_session(iteration)

        # Log session start decision
        decision_logger.log_decision(
            session_id=iteration,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Starting new session",
            choice=session_type,
            alternatives=["initializer", "update", "coding"],
            rationale="Based on project state and configuration",
            confidence=1.0,
            inputs_consulted=["features_database", "update_config.txt"],
        )

        obs.log_event(
            EventType.DECISION,
            data={
                "decision_type": "session_type",
                "choice": session_type,
                "rationale": "Based on project state",
            },
        )

        # Update session ID for feature_tools checkpoint creation
        update_session_id(iteration)
        human_interface.update_session_id(iteration)

        # Create checkpoint at session start (for recovery)
        try:
            checkpoint_mgr.create_checkpoint(
                trigger=CheckpointTrigger.SESSION_START,
                session_id=iteration,
                metadata={"session_type": session_type},
            )
        except Exception as e:
            print_warning(f"Could not create session start checkpoint: {e}")

        # Generate status.txt for the agent to read (compact summary)
        generate_status_file(project_dir, iteration)

        # Copy feature_tool.py for the agent to use
        copy_feature_tool_to_project(project_dir)

        # Create client (fresh context)
        client = create_client(project_dir, model)

        # Reset tool output tracker for clean display
        reset_tool_tracker()

        # Choose prompt based on session type
        if is_update_run:
            prompt = get_update_features_prompt()
            is_update_run = False  # Only use update prompt for first iteration
        elif is_first_run:
            prompt = get_initializer_prompt()
            is_first_run = False  # Only use initializer once
        else:
            prompt = get_coding_prompt()

        # Run session with async context manager
        async with client:
            result = await run_agent_session(client, prompt, project_dir, obs)

        # Update history with session data
        for error_text in result.error_texts:
            history.add_error(error_text)
        for blocked_cmd in result.blocked_commands:
            history.add_blocked_command(blocked_cmd)

        # Track git state and test progress
        git_hash = get_git_status_hash(project_dir)
        history.add_git_hash(git_hash)

        current_passing, total_tests = count_passing_tests(project_dir)
        if total_tests > 0:
            history.add_passing_count(current_passing)

        audit_due = (
            total_tests > 0
            and current_passing > 0
            and should_run_audit(project_dir, current_passing, AUDIT_CADENCE_FEATURES)
        )

        # Handle status
        if result.status == "complete":
            obs.end_session(
                session_id=iteration,
                status="completed",
                reason=result.reason,
            )
            # End memory session
            memory_manager.end_session(
                ending_state="completed",
                features_started=1,
                features_completed=current_passing - (previous_passing if 'previous_passing' in dir() else 0),
            )
            # Create final checkpoint at session end
            try:
                checkpoint_mgr.create_checkpoint(
                    trigger=CheckpointTrigger.SESSION_END,
                    session_id=iteration,
                    metadata={"status": "completed", "reason": result.reason},
                )
            except Exception as e:
                print_warning(f"Could not create completion checkpoint: {e}")
            print_status_complete()
            print_progress_summary(project_dir)
            # Show session metrics summary
            print_info("Session Metrics:")
            session_summary = metrics_collector.get_session_summary(iteration)
            for line in session_summary.split('\n'):
                print_info(f"  {line}")
            # Show autonomy status
            if autonomy_manager:
                autonomy_status = autonomy_manager.get_status()
                print_info(f"  Autonomy Level: {autonomy_status['effective_level']}")
                print_info(f"  Success Rate: {autonomy_status['performance']['success_rate']:.0%}")
            break

        elif result.status == "intervention":
            obs.end_session(
                session_id=iteration,
                status="intervention",
                reason=result.reason,
            )
            # End memory session
            memory_manager.end_session(
                ending_state="interrupted",
                warnings_for_next=["Human intervention required: " + result.reason],
            )

            # Phase 5: Record intervention for learning
            if intervention_learner:
                context_sig = intervention_learner.create_context_signature(
                    trigger_type="intervention_required",
                    error_message=result.reason if result.error_texts else None,
                )
                intervention_learner.record_intervention(
                    session_id=iteration,
                    intervention_type=LearningInterventionType.GUIDANCE,
                    context_signature=context_sig,
                    human_action="Session paused for human intervention",
                    context_details={"reason": result.reason},
                )

            print_status_intervention(result.reason)
            print_progress_summary(project_dir)
            break

        elif result.status == "continue":
            consecutive_error_sessions = 0  # Reset error counter on success

            # Check if progress was made this session
            # Progress = test count increased OR git state changed
            previous_passing = history.passing_counts[-2] if len(history.passing_counts) >= 2 else 0
            previous_git = history.git_hashes[-2] if len(history.git_hashes) >= 2 else ""

            made_test_progress = current_passing > previous_passing
            made_git_progress = git_hash != previous_git and previous_git != ""
            made_progress = made_test_progress or made_git_progress

            # Only check for cyclic behavior if NO progress was made
            # If the agent is making progress, encountering errors along the way is fine
            if not made_progress:
                # Check escalation rules for stuck behavior
                escalation_context = EscalationContext(
                    confidence=0.5,  # Neutral confidence
                    consecutive_failures=len([e for e in history.error_hashes[-5:] if history.error_hashes.count(e) > 1]),
                    feature_index=None,  # Could extract from status.txt if available
                )
                escalation_result = escalation_engine.evaluate(escalation_context)

                if escalation_result and escalation_result.rule.auto_pause:
                    # Log escalation decision
                    decision_logger.log_decision(
                        session_id=iteration,
                        decision_type=DecisionType.ESCALATION,
                        context=f"Escalation rule triggered: {escalation_result.rule.name}",
                        choice="pause_for_human_review",
                        alternatives=escalation_result.rule.suggested_actions,
                        rationale=escalation_result.message,
                        confidence=0.3,
                        inputs_consulted=["session_history", "escalation_rules"],
                    )

                    print_warning(f"Escalation triggered: {escalation_result.rule.name}")
                    print_info(f"Message: {escalation_result.message}")
                    print_info(f"Suggested actions: {', '.join(escalation_result.rule.suggested_actions)}")

                # Check for cyclic behavior patterns
                is_cyclic, cyclic_reason = check_for_cyclic_behavior(
                    history,
                    error_threshold=5,  # Increased threshold - errors within a session are normal
                    block_threshold=5,  # Increased - agent adapts to blocked commands
                    git_threshold=max_no_progress_iterations if max_no_progress_iterations > 0 else 999
                )
                if is_cyclic:
                    # Log cyclic behavior decision
                    decision_logger.log_decision(
                        session_id=iteration,
                        decision_type=DecisionType.ERROR_HANDLING,
                        context=f"Cyclic behavior detected: {cyclic_reason}",
                        choice="stop_session",
                        alternatives=["continue", "skip_feature", "rollback"],
                        rationale="Agent is stuck in a loop without making progress",
                        confidence=0.8,
                        inputs_consulted=["session_history", "git_status", "error_logs"],
                    )

                    obs.end_session(
                        session_id=iteration,
                        status="cyclic",
                        reason=cyclic_reason,
                    )
                    print_status_cyclic(cyclic_reason)
                    print_progress_summary(project_dir)
                    break

                # Also check test progress specifically (only if enabled and after setup)
                if total_tests > 0 and max_no_progress_iterations > 0:
                    is_stuck, stuck_reason = history.detect_no_test_progress(max_no_progress_iterations)
                    if is_stuck:
                        # Log no progress decision
                        decision_logger.log_decision(
                            session_id=iteration,
                            decision_type=DecisionType.ERROR_HANDLING,
                            context=f"No test progress: {stuck_reason}",
                            choice="stop_session",
                            alternatives=["continue", "skip_current_feature", "request_help"],
                            rationale="Test count has not improved for multiple iterations",
                            confidence=0.7,
                            inputs_consulted=["test_results", "session_history"],
                        )

                        obs.end_session(
                            session_id=iteration,
                            status="no_progress",
                            reason=stuck_reason,
                        )
                        print_status_no_progress(stuck_reason)
                        print_progress_summary(project_dir)
                        break
            else:
                if made_test_progress:
                    print_info(f"Progress: {previous_passing} -> {current_passing} tests passing")

            # End session as continuing (will start fresh next iteration)
            obs.end_session(
                session_id=iteration,
                status="continue",
                reason=f"Progress: {current_passing}/{total_tests} tests passing",
            )

            if audit_due:
                candidates, regressions = select_audit_candidates(
                    project_dir,
                    checkpoint_mgr,
                    max_candidates=AUDIT_MAX_CANDIDATES,
                    high_risk_count=AUDIT_HIGH_RISK_COUNT,
                    random_count=AUDIT_RANDOM_COUNT,
                )
                if candidates:
                    print_info(f"Running audit on {len(candidates)} features...")
                    obs.log_event(
                        EventType.DECISION,
                        data={
                            "decision_type": "audit",
                            "choice": "run_audit",
                            "candidates": candidates,
                            "regressions": regressions,
                        },
                    )
                    audit_prompt = get_audit_prompt(candidates, regressions)
                    audit_client = create_client(project_dir, model)
                    async with audit_client:
                        await run_agent_session(
                            audit_client,
                            audit_prompt,
                            project_dir,
                            obs,
                            check_completion=False,
                            check_stop=False,
                            risk_classifier=risk_classifier,
                            autonomy_manager=autonomy_manager,
                        )
                save_audit_state(project_dir, current_passing)

            print_auto_continue(AUTO_CONTINUE_DELAY_SECONDS)
            print_progress_summary(project_dir)
            await asyncio.sleep(AUTO_CONTINUE_DELAY_SECONDS)

        elif result.status == "error":
            consecutive_error_sessions += 1
            print_warning(f"Session error ({consecutive_error_sessions} consecutive)")

            # Stop after too many consecutive error sessions
            if consecutive_error_sessions >= 3:
                obs.end_session(
                    session_id=iteration,
                    status="error",
                    reason=f"Too many consecutive errors: {consecutive_error_sessions}",
                )
                print_status_error(consecutive_error_sessions)
                print_progress_summary(project_dir)
                # Generate failure analysis report
                try:
                    report = failure_analyzer.analyze_session(iteration)
                    print_warning("Failure Analysis:")
                    print_info(f"  Type: {report.failure_type}")
                    print_info(f"  Cause: {report.likely_cause}")
                    if report.suggested_fixes:
                        print_info("  Suggested Fixes:")
                        for fix in report.suggested_fixes[:3]:
                            print_info(f"    - {fix}")
                except Exception as e:
                    print_warning(f"Could not generate failure report: {e}")
                break

            # End session with error but will retry
            obs.end_session(
                session_id=iteration,
                status="error_retry",
                reason=result.reason,
            )

            print_info("Will retry with a fresh session...")
            await asyncio.sleep(AUTO_CONTINUE_DELAY_SECONDS)

        # Small delay between sessions
        if max_iterations is None or iteration < max_iterations:
            console.print("\n[dim]Preparing next session...[/dim]\n")
            await asyncio.sleep(1)

    # Final summary
    passing, total = count_passing_tests(project_dir)
    print_final_summary(project_dir, passing, total)

    # Print observability metrics summary
    try:
        from arcadiaforge.observability import format_metrics_summary
        metrics = obs.get_run_metrics()
        console.print()
        console.print(format_metrics_summary(metrics))
    except Exception as e:
        print_warning(f"Could not generate metrics summary: {e}")
