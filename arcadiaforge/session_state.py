"""
Session State Persistence for Crash Recovery
=============================================

Manages session state persistence to enable recovery from crashes.
Saves state before each tool execution and provides recovery mechanisms.

When the orchestrator restarts after a crash, it can:
1. Detect that a previous session was interrupted
2. Load the saved state
3. Inject recovery context into the agent's prompt
4. Continue from where the session left off
"""

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from arcadiaforge.output import print_info, print_warning, print_success


@dataclass
class SessionState:
    """
    Represents recoverable session state.

    This is persisted to disk before each tool execution to enable
    recovery if the session crashes or is interrupted.
    """
    session_id: int
    iteration: int
    current_feature: Optional[int]
    pending_features: List[int]
    completed_this_session: List[int]
    last_tool: Optional[str]
    last_tool_input: Optional[Dict[str, Any]]
    last_checkpoint: Optional[str]
    timestamp: str

    # Additional context for recovery
    git_hash: Optional[str] = None
    tests_passing: Optional[int] = None
    tests_total: Optional[int] = None
    session_type: Optional[str] = None  # "initializer", "coding", "update"
    recovery_attempt: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionState":
        """Create SessionState from dictionary."""
        # Handle missing fields for backwards compatibility
        data.setdefault("git_hash", None)
        data.setdefault("tests_passing", None)
        data.setdefault("tests_total", None)
        data.setdefault("session_type", None)
        data.setdefault("recovery_attempt", 0)
        data.setdefault("warnings", [])
        return cls(**data)

    def get_recovery_prompt(self) -> str:
        """
        Generate a recovery prompt to inject into the agent context.

        Returns:
            String describing what the agent was doing before the crash
        """
        lines = [
            "## CRASH RECOVERY NOTICE",
            "",
            f"The previous session (#{self.session_id}, iteration {self.iteration}) was interrupted.",
            "",
        ]

        if self.current_feature is not None:
            lines.append(f"**Last working on:** Feature #{self.current_feature}")

        if self.last_tool:
            lines.append(f"**Last tool called:** {self.last_tool}")
            if self.last_tool_input:
                # Truncate large inputs
                input_str = str(self.last_tool_input)
                if len(input_str) > 200:
                    input_str = input_str[:200] + "..."
                lines.append(f"**Last tool input:** {input_str}")

        if self.completed_this_session:
            lines.append(f"**Features completed this session:** {self.completed_this_session}")

        if self.pending_features:
            pending_preview = self.pending_features[:5]
            lines.append(f"**Pending features:** {pending_preview}{'...' if len(self.pending_features) > 5 else ''}")

        if self.tests_passing is not None and self.tests_total is not None:
            lines.append(f"**Progress at crash:** {self.tests_passing}/{self.tests_total} tests passing")

        if self.warnings:
            lines.append("")
            lines.append("**Warnings from previous session:**")
            for warning in self.warnings[-5:]:  # Last 5 warnings
                lines.append(f"  - {warning}")

        lines.extend([
            "",
            "Please check the current state and continue from where the previous session left off.",
            "Use `feature_stats` and `feature_next` to verify current progress.",
            ""
        ])

        return "\n".join(lines)


class SessionStateManager:
    """
    Manages session state persistence.

    Saves state to a JSON file in the .arcadia directory.
    State is saved before each tool execution and cleared on successful completion.
    """

    def __init__(self, project_dir: Path):
        """
        Initialize the session state manager.

        Args:
            project_dir: Project root directory
        """
        self.project_dir = Path(project_dir)
        self.arcadia_dir = self.project_dir / ".arcadia"
        self.state_file = self.arcadia_dir / "session_state.json"

        # Ensure directory exists
        self.arcadia_dir.mkdir(parents=True, exist_ok=True)

        # Current state (loaded on init if exists)
        self._current_state: Optional[SessionState] = None

    def initialize_state(
        self,
        session_id: int,
        iteration: int,
        session_type: str = "coding",
        pending_features: List[int] = None,
    ) -> SessionState:
        """
        Initialize a new session state.

        Args:
            session_id: Current session ID
            iteration: Current iteration number
            session_type: Type of session (initializer, coding, update)
            pending_features: List of pending feature indices

        Returns:
            New SessionState instance
        """
        self._current_state = SessionState(
            session_id=session_id,
            iteration=iteration,
            current_feature=None,
            pending_features=pending_features or [],
            completed_this_session=[],
            last_tool=None,
            last_tool_input=None,
            last_checkpoint=None,
            timestamp=datetime.now().isoformat(),
            session_type=session_type,
        )
        self.save(self._current_state)
        return self._current_state

    def save(self, state: SessionState) -> None:
        """
        Save session state to disk.

        Args:
            state: SessionState to save
        """
        try:
            state.timestamp = datetime.now().isoformat()
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state.to_dict(), f, indent=2, default=str)
            self._current_state = state
        except Exception as e:
            print_warning(f"Could not save session state: {e}")

    def load(self) -> Optional[SessionState]:
        """
        Load session state from disk.

        Returns:
            SessionState if file exists and is valid, None otherwise
        """
        if not self.state_file.exists():
            return None

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = SessionState.from_dict(data)
            self._current_state = state
            return state
        except json.JSONDecodeError as e:
            print_warning(f"Corrupted session state file: {e}")
            return None
        except Exception as e:
            print_warning(f"Could not load session state: {e}")
            return None

    def clear(self) -> None:
        """
        Clear saved state (on successful completion).

        Should be called when a session completes successfully.
        """
        try:
            if self.state_file.exists():
                self.state_file.unlink()
            self._current_state = None
            print_info("Session state cleared")
        except Exception as e:
            print_warning(f"Could not clear session state: {e}")

    def update(self, **kwargs) -> Optional[SessionState]:
        """
        Update specific fields in the current state.

        Args:
            **kwargs: Fields to update

        Returns:
            Updated SessionState, or None if no current state
        """
        if self._current_state is None:
            self._current_state = self.load()

        if self._current_state is None:
            return None

        for key, value in kwargs.items():
            if hasattr(self._current_state, key):
                setattr(self._current_state, key, value)

        self._current_state.timestamp = datetime.now().isoformat()
        self.save(self._current_state)
        return self._current_state

    def record_tool_execution(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        current_feature: Optional[int] = None,
    ) -> None:
        """
        Record a tool execution in the state.

        Called before each tool execution to enable recovery.

        Args:
            tool_name: Name of the tool being executed
            tool_input: Input parameters for the tool
            current_feature: Feature being worked on (if known)
        """
        self.update(
            last_tool=tool_name,
            last_tool_input=tool_input,
            current_feature=current_feature,
        )

    def record_feature_completed(self, feature_index: int) -> None:
        """
        Record that a feature was completed in this session.

        Args:
            feature_index: Index of the completed feature
        """
        if self._current_state is None:
            return

        if feature_index not in self._current_state.completed_this_session:
            self._current_state.completed_this_session.append(feature_index)

        # Remove from pending if present
        if feature_index in self._current_state.pending_features:
            self._current_state.pending_features.remove(feature_index)

        self.save(self._current_state)

    def record_checkpoint(self, checkpoint_id: str) -> None:
        """
        Record the latest checkpoint ID.

        Args:
            checkpoint_id: ID of the checkpoint that was created
        """
        self.update(last_checkpoint=checkpoint_id)

    def add_warning(self, warning: str) -> None:
        """
        Add a warning to the session state.

        Args:
            warning: Warning message to record
        """
        if self._current_state is None:
            return

        self._current_state.warnings.append(warning)
        # Keep only last 20 warnings
        self._current_state.warnings = self._current_state.warnings[-20:]
        self.save(self._current_state)

    def update_progress(self, tests_passing: int, tests_total: int, git_hash: str = None) -> None:
        """
        Update progress metrics in the state.

        Args:
            tests_passing: Number of passing tests
            tests_total: Total number of tests
            git_hash: Current git hash
        """
        self.update(
            tests_passing=tests_passing,
            tests_total=tests_total,
            git_hash=git_hash,
        )

    def check_for_crash_recovery(self, max_age_seconds: int = 3600) -> Optional[SessionState]:
        """
        Check if there's a crashed session that should be recovered.

        A session is considered crashed if:
        1. State file exists
        2. State was saved less than max_age_seconds ago

        Args:
            max_age_seconds: Maximum age of state to consider for recovery (default: 1 hour)

        Returns:
            SessionState if recovery is needed, None otherwise
        """
        state = self.load()
        if state is None:
            return None

        try:
            state_time = datetime.fromisoformat(state.timestamp)
            age = (datetime.now() - state_time).total_seconds()

            if age < max_age_seconds:
                # Increment recovery attempt counter
                state.recovery_attempt += 1
                self.save(state)
                return state
            else:
                # State is too old, clear it
                print_info(f"Stale session state found (age: {age/3600:.1f} hours), clearing")
                self.clear()
                return None
        except Exception as e:
            print_warning(f"Could not check session state age: {e}")
            return None

    def get_current_state(self) -> Optional[SessionState]:
        """Get the current session state."""
        return self._current_state


def create_session_state_manager(project_dir: Path) -> SessionStateManager:
    """
    Create a SessionStateManager for a project.

    Args:
        project_dir: Project root directory

    Returns:
        Configured SessionStateManager instance
    """
    return SessionStateManager(project_dir)
