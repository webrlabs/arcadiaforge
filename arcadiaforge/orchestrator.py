"""
Session Orchestrator
====================

Manages the lifecycle of autonomous agent sessions.
"""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional

from arcadiaforge.client import create_client
from arcadiaforge.artifact_store import ArtifactStore
from arcadiaforge.checkpoint import CheckpointManager, CheckpointTrigger, SessionPauseManager, format_paused_session
from arcadiaforge.decision import DecisionLogger, DecisionType
from arcadiaforge.escalation import EscalationEngine, EscalationContext
from arcadiaforge.human_interface import HumanInterface
from arcadiaforge.hypotheses import HypothesisTracker
from arcadiaforge.memory import MemoryManager
from arcadiaforge.metrics import MetricsCollector
from arcadiaforge.failure_analysis import FailureAnalyzer
from arcadiaforge.observability import Observability, EventType, format_metrics_summary
from arcadiaforge.autonomy import AutonomyManager, AutonomyLevel, AutonomyConfig
from arcadiaforge.risk import RiskClassifier
from arcadiaforge.intervention_learning import InterventionLearner, InterventionType as LearningInterventionType
from arcadiaforge.feature_tools import set_checkpoint_manager, update_session_id, set_artifact_store
from arcadiaforge.process_tools import set_session_id as set_process_session_id
from arcadiaforge.feature_list import generate_status_file, FeatureList
from arcadiaforge.progress import print_session_header, print_progress_summary, count_passing_tests, print_final_summary
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
    print_session_divider,
    print_status_complete,
    print_status_intervention,
    print_status_cyclic,
    print_status_no_progress,
    print_status_error,
    print_auto_continue,
    print_update_mode_info,
    print_initializer_info,
    print_warning,
    print_error,
    print_info,
    print_success,
    set_live_terminal,
)
from arcadiaforge.live_terminal import LiveTerminal, UserFeedback
from prompt_toolkit.patch_stdout import patch_stdout
from arcadiaforge.agent import run_agent_session, SessionHistory, get_git_status_hash, check_for_cyclic_behavior
from arcadiaforge.process_tracker import ProcessTracker, get_tracker
from arcadiaforge.db import init_db


class SessionOrchestrator:
    """
    Orchestrates the autonomous agent loop, managing state, components, and transitions.
    """

    AUTO_CONTINUE_DELAY_SECONDS = 3

    def __init__(
        self,
        project_dir: Path,
        model: str,
        max_iterations: Optional[int] = None,
        max_no_progress: int = 3,
        audit_cadence: int = AUDIT_CADENCE_FEATURES,
        enable_live_terminal: bool = False,
    ):
        self.project_dir = project_dir
        self.model = model
        self.max_iterations = max_iterations
        self.max_no_progress = max_no_progress
        self.audit_cadence = audit_cadence
        self.enable_live_terminal = enable_live_terminal
        self.pause_requested = False

        # State
        self.iteration = 0
        self.consecutive_error_sessions = 0
        self.history = SessionHistory()

        # Components (initialized in setup)
        self.obs: Optional[Observability] = None
        self.checkpoint_mgr: Optional[CheckpointManager] = None
        self.memory_manager: Optional[MemoryManager] = None
        self.autonomy_manager: Optional[AutonomyManager] = None
        self.decision_logger: Optional[DecisionLogger] = None
        self.pause_manager: Optional[SessionPauseManager] = None
        self.human_interface: Optional[HumanInterface] = None
        self.metrics_collector: Optional[MetricsCollector] = None
        self.failure_analyzer: Optional[FailureAnalyzer] = None
        self.intervention_learner: Optional[InterventionLearner] = None
        self.escalation_engine: Optional[EscalationEngine] = None
        self.hypothesis_tracker: Optional[HypothesisTracker] = None
        self.process_tracker: Optional[ProcessTracker] = None
        self.live_terminal: Optional[LiveTerminal] = None

    def setup(self):
        """Initialize all subsystems and components."""
        self.project_dir.mkdir(parents=True, exist_ok=True)

        # Initialize observability for event logging
        self.obs = Observability(self.project_dir)

        # Initialize metrics collector and failure analyzer
        self.metrics_collector = MetricsCollector(self.project_dir)
        self.failure_analyzer = FailureAnalyzer(self.project_dir)

        # Initialize checkpoint manager
        self.checkpoint_mgr = CheckpointManager(self.project_dir)
        set_checkpoint_manager(self.checkpoint_mgr)

        # Initialize artifact store
        artifact_store = ArtifactStore(self.project_dir)
        set_artifact_store(artifact_store)

        # Initialize Phase 2: Human-in-the-Loop components
        self.decision_logger = DecisionLogger(self.project_dir)

        self.escalation_engine = EscalationEngine(self.project_dir)
        print_info(f"Escalation rules enabled: {len(self.escalation_engine.get_rules())} rules")

        self.pause_manager = SessionPauseManager(self.project_dir)
        self.human_interface = HumanInterface(self.project_dir)

        # Initialize Phase 3: Memory Architecture components
        self.memory_manager = MemoryManager(self.project_dir, session_id=1)

        self.hypothesis_tracker = HypothesisTracker(self.project_dir, session_id=1)

        # Initialize Phase 5: Advanced Autonomy components
        autonomy_config = AutonomyConfig(
            level=AutonomyLevel.EXECUTE_SAFE,
            auto_adjust=True,
            confidence_threshold=0.5,
        )
        self.autonomy_manager = AutonomyManager(self.project_dir, autonomy_config)
        print_info(f"Autonomy level: {self.autonomy_manager.current_level.name}")

        self.risk_classifier = RiskClassifier(self.project_dir)
        print_info(f"Risk classification enabled: {len(self.risk_classifier.patterns)} patterns")

        self.intervention_learner = InterventionLearner(self.project_dir)
        print_info(f"Intervention learning enabled: {len(self.intervention_learner.patterns)} learned patterns")

        # Initialize process tracker
        self.process_tracker = ProcessTracker(self.project_dir)
        running = self.process_tracker.get_running()
        if running:
            print_info(f"Process tracker: {len(running)} background processes running")
        else:
            print_info("Process tracker enabled")

        # Initialize live terminal if enabled
        if self.enable_live_terminal:
            self.live_terminal = LiveTerminal(
                max_output_lines=100,
                prompt_text="Feedback",
                show_help_on_start=True,
            )
            set_live_terminal(self.live_terminal)
            print_info("Live terminal enabled - type /help for commands")

        self._setup_signal_handlers()
        self._check_paused_session()

    def _setup_signal_handlers(self):
        """Register signal handlers for graceful pause."""
        def signal_handler(sig, frame):
            if self.pause_requested:
                print_warning("\nForce exit requested. Exiting immediately.")
                sys.exit(1)
            self.pause_requested = True
            print_warning("\nPause requested. Will pause after current operation completes.")
            print_info("Press Ctrl+C again to force exit immediately.")
            if self.human_interface:
                self.human_interface.request_pause()

        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, signal_handler)

    def _check_paused_session(self):
        """Check for and resume paused sessions."""
        paused_session = self.pause_manager.get_paused_session()
        if paused_session:
            print_info("Found paused session:")
            console.print(format_paused_session(paused_session))
            console.print()

            resumed = self.pause_manager.resume_session()
            if resumed:
                print_success(f"Resumed session {resumed.session_id}")
                if resumed.resume_prompt:
                    print_info(f"Resume context: {resumed.resume_prompt}")
                if resumed.human_notes:
                    print_info(f"Human notes: {resumed.human_notes}")

    async def run(
        self,
        new_requirements_path: Optional[Path] = None,
        num_new_features: Optional[int] = None,
        app_spec_path: Optional[Path] = None,
    ):
        """Run the main agent loop."""
        # print_banner()

        # Initialize Project Database
        await init_db(self.project_dir)

        extra_config = {}
        if new_requirements_path:
            extra_config["New requirements"] = str(new_requirements_path)
        if app_spec_path:
            extra_config["App spec"] = str(app_spec_path)

        print_config(self.project_dir, self.model, self.max_iterations, extra_config)
        self.setup()

        # Check project state
        # Check for features in database or legacy JSON file
        feature_list = FeatureList(self.project_dir)
        has_features = feature_list.exists()
        git_dir = self.project_dir / ".git"

        # Consider it a first run if no features exist OR git isn't initialized
        is_first_run = not has_features or not git_dir.exists()
        is_update_run = new_requirements_path is not None and has_features

        if is_update_run:
            print_update_mode_info(num_new_features)
            copy_new_requirements_to_project(new_requirements_path, self.project_dir)
            if num_new_features:
                config_file = self.project_dir / "update_config.txt"
                config_file.write_text(f"NUM_NEW_FEATURES={num_new_features}\n")
            print_progress_summary(self.project_dir)
        elif is_first_run:
            if new_requirements_path:
                print_error("Cannot use --new-requirements on a fresh project.")
                return
            print_initializer_info()
            copy_spec_to_project(self.project_dir, app_spec_path)
        else:
            print_info("Continuing existing project")
            print_progress_summary(self.project_dir)

        # Run main loop with live terminal if enabled
        if self.live_terminal:
            async with self.live_terminal:
                with patch_stdout():
                    await self._run_main_loop(is_first_run, is_update_run)
        else:
            await self._run_main_loop(is_first_run, is_update_run)

    async def _run_main_loop(self, is_first_run: bool, is_update_run: bool):
        """Execute the main agent iteration loop."""
        # Main Loop
        while True:
            self.iteration += 1
            
            # Update session IDs
            self.memory_manager.session_id = self.iteration
            self.memory_manager.hot.session_id = self.iteration
            self.hypothesis_tracker.session_id = self.iteration

            # Start memory session
            self.memory_manager.start_session()

            # Check termination conditions
            if self.max_iterations and self.iteration > self.max_iterations:
                self.obs.log_event(EventType.WARNING, data={"message": f"Reached max iterations ({self.max_iterations})"})
                print_warning(f"Reached max iterations ({self.max_iterations})")
                break

            if self.pause_requested:
                self._handle_pause()
                break

            # Process any pending user feedback from live terminal
            if self.live_terminal:
                should_break = await self._process_live_feedback()
                if should_break:
                    break

            print_session_header(self.iteration, is_first_run)
            
            session_type = "initializer" if is_first_run else ("update" if is_update_run else "coding")
            self.obs.start_session(self.iteration)
            
            self._log_session_start_decision(session_type)
            update_session_id(self.iteration)
            self.human_interface.update_session_id(self.iteration)
            set_process_session_id(self.iteration)
            
            self._create_session_checkpoint(session_type)
            generate_status_file(self.project_dir, self.iteration)
            copy_feature_tool_to_project(self.project_dir)

            client = create_client(self.project_dir, self.model)
            prompt = self._get_prompt(session_type, is_first_run, is_update_run)
            
            # One-time flags reset
            if is_update_run: is_update_run = False
            if is_first_run: is_first_run = False

            # Run Session
            async with client:
                result = await run_agent_session(
                    client,
                    prompt,
                    self.project_dir,
                    self.obs,
                    risk_classifier=self.risk_classifier,
                    autonomy_manager=self.autonomy_manager,
                )

            # Update History
            self._update_history(result)

            # Check Status
            if result.status == "complete":
                self._handle_complete(result)
                break
            elif result.status == "auth_error":
                self._handle_auth_error(result)
                break
            elif result.status == "intervention":
                self._handle_intervention(result)
                break
            elif result.status == "continue":
                should_break = await self._handle_continue(result)
                if should_break:
                    break
            elif result.status == "error":
                should_break = await self._handle_error(result)
                if should_break:
                    break

            if self.max_iterations is None or self.iteration < self.max_iterations:
                console.print("\n[dim]Preparing next session...[/dim]\n")
                await asyncio.sleep(1)

        await self._print_final_results()

    def _handle_pause(self):
        """Handle user requested pause."""
        current_passing, total_tests = count_passing_tests(self.project_dir)
        pause_checkpoint = self.checkpoint_mgr.create_checkpoint(
            trigger=CheckpointTrigger.HUMAN_REQUEST,
            session_id=self.iteration,
            metadata={"reason": "pause_requested"},
            human_note="Session paused by user request",
        )
        self.pause_manager.pause_session(
            session_id=self.iteration,
            pause_reason="User requested pause (Ctrl+C)",
            current_feature=None,
            last_checkpoint_id=pause_checkpoint.checkpoint_id,
            resume_prompt="Continue implementing features from where we left off.",
            work_summary=f"Progress: {current_passing}/{total_tests} tests passing",
            iteration=self.iteration,
            features_passing=current_passing,
            features_total=total_tests,
        )
        print_info("Session paused successfully.")
        print_info(f"Checkpoint: {pause_checkpoint.checkpoint_id}")

    async def _process_live_feedback(self) -> bool:
        """
        Process any pending feedback from the live terminal.

        Returns True if the loop should break (e.g., user requested stop).
        """
        all_feedback = self.live_terminal.get_all_feedback()
        if not all_feedback:
            return False

        for feedback in all_feedback:
            self.obs.log_event(
                EventType.DECISION,
                data={
                    "decision_type": "user_feedback",
                    "feedback_type": feedback.feedback_type,
                    "message": feedback.message,
                }
            )

            if feedback.feedback_type == "stop":
                self.live_terminal.output_warning("Stop requested by user")
                self.pause_requested = True
                self._handle_pause()
                return True

            elif feedback.feedback_type == "pause":
                self.live_terminal.output_info("Pausing for user review...")
                # Pause for a bit to let user review
                await asyncio.sleep(5)
                self.live_terminal.output_success("Resuming...")

            elif feedback.feedback_type == "skip":
                self.live_terminal.output_info(f"Skip requested: {feedback.message}")
                # Log the skip request - agent will pick this up from memory
                self.memory_manager.add_to_hot({
                    "type": "user_skip_request",
                    "message": feedback.message,
                    "session": self.iteration,
                })

            elif feedback.feedback_type == "hint":
                self.live_terminal.output_info(f"Hint received: {feedback.message}")
                # Store hint in memory for the agent to use
                self.memory_manager.add_to_hot({
                    "type": "user_hint",
                    "message": feedback.message,
                    "session": self.iteration,
                })

            elif feedback.feedback_type == "redirect":
                self.live_terminal.output_info(f"Redirect requested: {feedback.message}")
                # Store redirect in memory for the agent to use
                self.memory_manager.add_to_hot({
                    "type": "user_redirect",
                    "message": feedback.message,
                    "session": self.iteration,
                })

            else:  # general feedback
                self.live_terminal.output_muted(f"Feedback noted: {feedback.message}")
                # Store general feedback
                self.memory_manager.add_to_hot({
                    "type": "user_feedback",
                    "message": feedback.message,
                    "session": self.iteration,
                })

        return False

    def _log_session_start_decision(self, session_type: str):
        self.decision_logger.log_decision(
            session_id=self.iteration,
            decision_type=DecisionType.FEATURE_SELECTION,
            context="Starting new session",
            choice=session_type,
            alternatives=["initializer", "update", "coding"],
            rationale="Based on project state and configuration",
            confidence=1.0,
            inputs_consulted=["features_database", "update_config.txt"],
        )
        self.obs.log_event(
            EventType.DECISION, data={"decision_type": "session_type", "choice": session_type, "rationale": "Based on project state"}
        )

    def _create_session_checkpoint(self, session_type: str):
        try:
            self.checkpoint_mgr.create_checkpoint(
                trigger=CheckpointTrigger.SESSION_START,
                session_id=self.iteration,
                metadata={"session_type": session_type},
            )
        except Exception as e:
            print_warning(f"Could not create session start checkpoint: {e}")

    def _get_prompt(self, session_type: str, is_first_run: bool, is_update_run: bool) -> str:
        if is_update_run:
            return get_update_features_prompt()
        elif is_first_run:
            return get_initializer_prompt()
        else:
            return get_coding_prompt()

    def _update_history(self, result):
        for error_text in result.error_texts:
            self.history.add_error(error_text)
        for blocked_cmd in result.blocked_commands:
            self.history.add_blocked_command(blocked_cmd)
        
        git_hash = get_git_status_hash(self.project_dir)
        self.history.add_git_hash(git_hash)
        
        current_passing, total_tests = count_passing_tests(self.project_dir)
        if total_tests > 0:
            self.history.add_passing_count(current_passing)

    def _handle_auth_error(self, result):
        """Handle authentication errors - stop immediately, no retry."""
        self.obs.end_session(
            session_id=self.iteration,
            status="auth_error",
            reason=result.reason,
        )
        # The detailed error message is already printed in run_agent_session
        # Just log for observability and exit cleanly

    def _handle_complete(self, result):
        self.obs.end_session(session_id=self.iteration, status="completed", reason=result.reason)
        
        current_passing, _ = count_passing_tests(self.project_dir)
        previous_passing = self.history.passing_counts[-2] if len(self.history.passing_counts) >= 2 else 0
        
        self.memory_manager.end_session(
            ending_state="completed",
            features_started=1,
            features_completed=current_passing - previous_passing,
        )
        try:
            self.checkpoint_mgr.create_checkpoint(
                trigger=CheckpointTrigger.SESSION_END,
                session_id=self.iteration,
                metadata={"status": "completed", "reason": result.reason},
            )
        except Exception as e:
            print_warning(f"Could not create completion checkpoint: {e}")
            
        print_status_complete()
        print_progress_summary(self.project_dir)
        self._print_session_metrics()

    def _handle_intervention(self, result):
        self.obs.end_session(session_id=self.iteration, status="intervention", reason=result.reason)
        self.memory_manager.end_session(
            ending_state="interrupted",
            warnings_for_next=["Human intervention required: " + result.reason],
        )
        
        if self.intervention_learner:
            context_sig = self.intervention_learner.create_context_signature(
                trigger_type="intervention_required",
                error_message=result.reason if result.error_texts else None,
            )
            self.intervention_learner.record_intervention(
                session_id=self.iteration,
                intervention_type=LearningInterventionType.GUIDANCE,
                context_signature=context_sig,
                human_action="Session paused for human intervention",
                context_details={"reason": result.reason},
            )
            
        print_status_intervention(result.reason)
        print_progress_summary(self.project_dir)

    async def _handle_continue(self, result) -> bool:
        self.consecutive_error_sessions = 0
        
        current_passing, total_tests = count_passing_tests(self.project_dir)
        previous_passing = self.history.passing_counts[-2] if len(self.history.passing_counts) >= 2 else 0
        previous_git = self.history.git_hashes[-2] if len(self.history.git_hashes) >= 2 else ""
        git_hash = get_git_status_hash(self.project_dir)

        made_test_progress = current_passing > previous_passing
        made_git_progress = git_hash != previous_git and previous_git != ""
        made_progress = made_test_progress or made_git_progress

        if not made_progress:
            # Check escalation
            escalation_context = EscalationContext(
                confidence=0.5,
                consecutive_failures=len([e for e in self.history.error_hashes[-5:] if self.history.error_hashes.count(e) > 1]),
                feature_index=None,
            )
            escalation_result = self.escalation_engine.evaluate(escalation_context)
            if escalation_result and escalation_result.rule.auto_pause:
                 self.decision_logger.log_decision(
                    session_id=self.iteration,
                    decision_type=DecisionType.ESCALATION,
                    context=f"Escalation rule triggered: {escalation_result.rule.name}",
                    choice="pause_for_human_review",
                    alternatives=escalation_result.rule.suggested_actions,
                    rationale=escalation_result.message,
                    confidence=0.3,
                    inputs_consulted=["session_history", "escalation_rules"],
                )
                 print_warning(f"Escalation triggered: {escalation_result.rule.name}")

            # Check cyclic
            is_cyclic, cyclic_reason = check_for_cyclic_behavior(
                self.history,
                error_threshold=5,
                block_threshold=5,
                git_threshold=self.max_no_progress if self.max_no_progress > 0 else 999
            )
            if is_cyclic:
                self._log_stop_decision("Cyclic behavior", cyclic_reason)
                self.obs.end_session(session_id=self.iteration, status="cyclic", reason=cyclic_reason)
                print_status_cyclic(cyclic_reason)
                print_progress_summary(self.project_dir)
                return True
            
            # Check no test progress
            if total_tests > 0 and self.max_no_progress > 0:
                is_stuck, stuck_reason = self.history.detect_no_test_progress(self.max_no_progress)
                if is_stuck:
                    self._log_stop_decision("No test progress", stuck_reason)
                    self.obs.end_session(session_id=self.iteration, status="no_progress", reason=stuck_reason)
                    print_status_no_progress(stuck_reason)
                    print_progress_summary(self.project_dir)
                    return True
        else:
             if made_test_progress:
                print_info(f"Progress: {previous_passing} -> {current_passing} tests passing")

        self.obs.end_session(session_id=self.iteration, status="continue", reason=f"Progress: {current_passing}/{total_tests} tests passing")
        
        # Audit
        if total_tests > 0 and current_passing > 0 and should_run_audit(self.project_dir, current_passing, self.audit_cadence):
            await self._run_audit(current_passing)

        print_auto_continue(self.AUTO_CONTINUE_DELAY_SECONDS)
        print_progress_summary(self.project_dir)
        await asyncio.sleep(self.AUTO_CONTINUE_DELAY_SECONDS)
        return False

    async def _handle_error(self, result) -> bool:
        self.consecutive_error_sessions += 1
        print_warning(f"Session error ({self.consecutive_error_sessions} consecutive)")
        
        if self.consecutive_error_sessions >= 3:
            self.obs.end_session(session_id=self.iteration, status="error", reason=f"Too many consecutive errors: {self.consecutive_error_sessions}")
            print_status_error(self.consecutive_error_sessions)
            print_progress_summary(self.project_dir)
            self._generate_failure_report()
            return True
            
        self.obs.end_session(session_id=self.iteration, status="error_retry", reason=result.reason)
        print_info("Will retry with a fresh session...")
        await asyncio.sleep(self.AUTO_CONTINUE_DELAY_SECONDS)
        return False

    def _log_stop_decision(self, context_prefix: str, reason: str):
        self.decision_logger.log_decision(
            session_id=self.iteration,
            decision_type=DecisionType.ERROR_HANDLING,
            context=f"{context_prefix}: {reason}",
            choice="stop_session",
            alternatives=["continue", "skip_feature", "rollback"],
            rationale="Agent is stuck or not making progress",
            confidence=0.8,
            inputs_consulted=["session_history", "test_results"],
        )

    async def _run_audit(self, current_passing: int):
        candidates, regressions = select_audit_candidates(
            self.project_dir,
            self.checkpoint_mgr,
            max_candidates=AUDIT_MAX_CANDIDATES,
            high_risk_count=AUDIT_HIGH_RISK_COUNT,
            random_count=AUDIT_RANDOM_COUNT,
        )
        if candidates:
            print_info(f"Running audit on {len(candidates)} features...")
            self.obs.log_event(EventType.DECISION, data={"decision_type": "audit", "choice": "run_audit", "candidates": candidates})
            audit_prompt = get_audit_prompt(candidates, regressions)
            audit_client = create_client(self.project_dir, self.model)
            async with audit_client:
                await run_agent_session(
                    audit_client,
                    audit_prompt,
                    self.project_dir,
                    self.obs,
                    check_completion=False,
                    check_stop=False,
                    risk_classifier=self.risk_classifier,
                    autonomy_manager=self.autonomy_manager,
                )
        save_audit_state(self.project_dir, current_passing)

    def _generate_failure_report(self):
        try:
            report = self.failure_analyzer.analyze_session(self.iteration)
            print_warning("Failure Analysis:")
            print_info(f"  Type: {report.failure_type}")
            print_info(f"  Cause: {report.likely_cause}")
            if report.suggested_fixes:
                print_info("  Suggested Fixes:")
                for fix in report.suggested_fixes[:3]:
                     print_info(f"    - {fix}")
        except Exception as e:
            print_warning(f"Could not generate failure report: {e}")

    def _print_session_metrics(self):
        print_info("Session Metrics:")
        session_summary = self.metrics_collector.get_session_summary(self.iteration)
        for line in session_summary.split('\n'):
            print_info(f"  {line}")
        if self.autonomy_manager:
            autonomy_status = self.autonomy_manager.get_status()
            print_info(f"  Autonomy Level: {autonomy_status['effective_level']}")
            print_info(f"  Success Rate: {autonomy_status['performance']['success_rate']:.0%}")

    async def _print_final_results(self):
        passing, total = count_passing_tests(self.project_dir)
        print_final_summary(self.project_dir, passing, total)
        try:
            metrics = await self.obs.get_run_metrics()
            console.print()
            console.print(format_metrics_summary(metrics))
        except Exception as e:
            print_warning(f"Could not generate metrics summary: {e}")
