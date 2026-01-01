"""
Stall Detection Manager
=======================

Detects when agents get stuck making no progress across multiple sessions.
Escalates to human interface when stall threshold is reached.

Stall Types:
- no_progress: No features passed/tests improved for N consecutive sessions
- cyclic: Same errors repeating across sessions
- capability_missing: Blocked on a missing system capability (e.g., Docker)
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, TYPE_CHECKING

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.connection import get_session_maker
from arcadiaforge.db.models import StallRecord, ProgressEntry, SystemCapability
from arcadiaforge.output import (
    console,
    print_warning,
    print_error,
    print_info,
    print_muted,
    icon,
)

if TYPE_CHECKING:
    from arcadiaforge.human_interface import HumanInterface


@dataclass
class StallStatus:
    """Result of a stall detection check."""
    is_stalled: bool = False
    stall_type: Optional[str] = None  # no_progress, cyclic, capability_missing
    consecutive_sessions: int = 0
    message: str = ""
    should_escalate: bool = False
    blocked_on: Optional[str] = None
    blocked_features: List[int] = field(default_factory=list)
    missing_capability: Optional[str] = None


class StallDetectionManager:
    """
    Manages stall detection across sessions.

    Tracks progress between sessions and escalates to human interface
    when stalls are detected.
    """

    DEFAULT_THRESHOLD = 5  # Number of consecutive no-progress sessions before escalating

    def __init__(
        self,
        project_dir: Path,
        stall_threshold: int = DEFAULT_THRESHOLD,
        human_interface: Optional["HumanInterface"] = None,
    ):
        """
        Initialize the stall detection manager.

        Args:
            project_dir: Project root directory
            stall_threshold: Number of no-progress sessions before escalating
            human_interface: Human interface for escalation
        """
        self.project_dir = project_dir
        self.stall_threshold = stall_threshold
        self.human_interface = human_interface

        # Track progress within this session
        self._session_start_passing = 0
        self._session_start_git_hash: Optional[str] = None
        self._current_session_id: Optional[int] = None

    def set_session_baseline(
        self,
        session_id: int,
        passing_count: int,
        git_hash: Optional[str] = None,
    ) -> None:
        """
        Set the baseline for this session's progress tracking.

        Call this at the start of each session.
        """
        self._current_session_id = session_id
        self._session_start_passing = passing_count
        self._session_start_git_hash = git_hash

    async def check_progress(
        self,
        current_passing: int,
        current_git_hash: Optional[str] = None,
    ) -> StallStatus:
        """
        Check if there's been progress this session.

        Args:
            current_passing: Current number of passing features
            current_git_hash: Current git commit hash

        Returns:
            StallStatus indicating whether we're stalled
        """
        # Determine if progress was made this session
        tests_improved = current_passing > self._session_start_passing
        git_changed = (
            current_git_hash is not None
            and self._session_start_git_hash is not None
            and current_git_hash != self._session_start_git_hash
        )

        made_progress = tests_improved or git_changed

        if made_progress:
            # Reset stall tracking
            await self._clear_stall_record()
            return StallStatus(is_stalled=False, message="Progress made this session")

        # No progress - check historical stall data
        return await self._check_historical_stalls(current_passing, current_git_hash)

    async def _check_historical_stalls(
        self,
        current_passing: int,
        current_git_hash: Optional[str],
    ) -> StallStatus:
        """Check stall history and update stall record."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                # Get most recent unresolved stall record
                result = await session.execute(
                    select(StallRecord)
                    .where(StallRecord.resolved == False)
                    .order_by(desc(StallRecord.detected_at))
                    .limit(1)
                )
                existing_stall = result.scalar_one_or_none()

                if existing_stall:
                    # Update existing stall record
                    existing_stall.consecutive_sessions += 1
                    existing_stall.last_passing_count = current_passing
                    existing_stall.last_git_hash = current_git_hash
                    existing_stall.session_id = self._current_session_id or 0

                    consecutive = existing_stall.consecutive_sessions
                    stall_type = existing_stall.stall_type
                    blocked_on = existing_stall.blocked_on
                    missing_cap = existing_stall.missing_capability
                else:
                    # Create new stall record
                    new_stall = StallRecord(
                        session_id=self._current_session_id or 0,
                        stall_type="no_progress",
                        consecutive_sessions=1,
                        last_passing_count=current_passing,
                        last_git_hash=current_git_hash,
                    )
                    session.add(new_stall)
                    consecutive = 1
                    stall_type = "no_progress"
                    blocked_on = None
                    missing_cap = None

                await session.commit()

                # Determine if we should escalate
                should_escalate = consecutive >= self.stall_threshold

                if should_escalate:
                    message = (
                        f"STALL DETECTED: No progress for {consecutive} consecutive sessions. "
                        f"Features passing: {current_passing}. "
                    )
                    if blocked_on:
                        message += f"Blocked on: {blocked_on}. "
                    if missing_cap:
                        message += f"Missing capability: {missing_cap}. "
                else:
                    message = f"No progress this session ({consecutive}/{self.stall_threshold} threshold)"

                return StallStatus(
                    is_stalled=consecutive >= 2,  # Consider stalled after 2 sessions
                    stall_type=stall_type,
                    consecutive_sessions=consecutive,
                    message=message,
                    should_escalate=should_escalate,
                    blocked_on=blocked_on,
                    missing_capability=missing_cap,
                )

        except Exception as e:
            # Don't fail on database errors
            print_warning(f"Stall detection error: {e}")
            return StallStatus(is_stalled=False, message=f"Stall check error: {e}")

    async def _clear_stall_record(self) -> None:
        """Mark any existing stall as resolved."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(StallRecord).where(StallRecord.resolved == False)
                )
                stalls = result.scalars().all()
                for stall in stalls:
                    stall.resolved = True
                    stall.resolved_at = datetime.utcnow()
                    stall.resolution = "Progress made"
                await session.commit()
        except Exception as e:
            print_warning(f"Could not clear stall record: {e}")

    async def record_capability_stall(
        self,
        capability: str,
        reason: str,
        blocked_features: Optional[List[int]] = None,
    ) -> None:
        """
        Record a stall due to missing capability.

        Args:
            capability: The missing capability name (e.g., "docker")
            reason: Why this capability is needed
            blocked_features: Feature indices blocked by this capability
        """
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                stall = StallRecord(
                    session_id=self._current_session_id or 0,
                    stall_type="capability_missing",
                    consecutive_sessions=1,
                    blocked_on=reason,
                    blocked_features=blocked_features or [],
                    missing_capability=capability,
                )
                session.add(stall)
                await session.commit()
        except Exception as e:
            print_warning(f"Could not record capability stall: {e}")

    async def escalate_to_human(
        self,
        stall_status: StallStatus,
    ) -> Optional[str]:
        """
        Escalate a stall to the human interface.

        Per user preference, this shows a warning but continues running.

        Args:
            stall_status: The stall status to escalate

        Returns:
            Human response if available, None otherwise
        """
        # Mark as escalated in database
        await self._mark_escalated()

        # Display prominent warning
        self._display_stall_warning(stall_status)

        # If human interface is available, try to get input
        if self.human_interface:
            try:
                from arcadiaforge.human_interface import InjectionType

                response = await self.human_interface.request_input(
                    injection_type=InjectionType.GUIDANCE,
                    context={
                        "stall_type": stall_status.stall_type,
                        "consecutive_sessions": stall_status.consecutive_sessions,
                        "blocked_on": stall_status.blocked_on,
                        "missing_capability": stall_status.missing_capability,
                    },
                    options=[
                        "Continue anyway",
                        "Skip blocked features",
                        "Stop agent",
                    ],
                    recommendation="Continue anyway",
                    message=stall_status.message,
                    timeout=60,  # Give human 60 seconds to respond
                    default_on_timeout="Continue anyway",
                )
                return response
            except Exception as e:
                print_warning(f"Could not get human input: {e}")

        return None

    async def _mark_escalated(self) -> None:
        """Mark current stall as escalated."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                result = await session.execute(
                    select(StallRecord)
                    .where(StallRecord.resolved == False)
                    .order_by(desc(StallRecord.detected_at))
                    .limit(1)
                )
                stall = result.scalar_one_or_none()
                if stall:
                    stall.escalated = True
                    stall.escalated_at = datetime.utcnow()
                    await session.commit()
        except Exception as e:
            print_warning(f"Could not mark stall as escalated: {e}")

    def _display_stall_warning(self, stall_status: StallStatus) -> None:
        """Display a prominent stall warning."""
        console.print()
        console.print("[af.warn]" + "=" * 60 + "[/]")
        console.print(f"[af.warn]{icon('warning')} STALL DETECTED[/]")
        console.print("[af.warn]" + "=" * 60 + "[/]")
        console.print()
        console.print(f"[af.muted]Type:[/] {stall_status.stall_type}")
        console.print(f"[af.muted]Sessions without progress:[/] {stall_status.consecutive_sessions}")

        if stall_status.blocked_on:
            console.print(f"[af.muted]Blocked on:[/] {stall_status.blocked_on}")

        if stall_status.missing_capability:
            console.print(f"[af.muted]Missing capability:[/] [af.err]{stall_status.missing_capability}[/]")

        console.print()
        console.print("[af.info]The agent will continue running, but human intervention may be needed.[/]")
        console.print("[af.muted]Check the blocked features and consider providing guidance.[/]")
        console.print()

    async def get_stall_summary(self) -> Dict[str, Any]:
        """Get a summary of stall history for agent context."""
        try:
            session_maker = get_session_maker()
            async with session_maker() as session:
                # Get recent stalls
                result = await session.execute(
                    select(StallRecord)
                    .order_by(desc(StallRecord.detected_at))
                    .limit(10)
                )
                stalls = result.scalars().all()

                return {
                    "total_stalls": len(stalls),
                    "unresolved_stalls": len([s for s in stalls if not s.resolved]),
                    "recent_stalls": [
                        {
                            "type": s.stall_type,
                            "sessions": s.consecutive_sessions,
                            "resolved": s.resolved,
                            "blocked_on": s.blocked_on,
                            "missing_capability": s.missing_capability,
                        }
                        for s in stalls[:5]
                    ],
                }
        except Exception as e:
            return {"error": str(e)}


def create_stall_manager(
    project_dir: Path,
    stall_threshold: int = StallDetectionManager.DEFAULT_THRESHOLD,
    human_interface: Optional["HumanInterface"] = None,
) -> StallDetectionManager:
    """
    Create a stall detection manager.

    Args:
        project_dir: Project root directory
        stall_threshold: Number of no-progress sessions before escalating
        human_interface: Human interface for escalation

    Returns:
        Configured StallDetectionManager instance
    """
    return StallDetectionManager(
        project_dir=project_dir,
        stall_threshold=stall_threshold,
        human_interface=human_interface,
    )
