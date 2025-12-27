"""
Human Interface for Autonomous Coding Framework
================================================

Provides explicit injection points where humans can intervene in agent operation.
Uses file-based communication to enable asynchronous human responses.

Usage:
    from arcadiaforge.human_interface import HumanInterface, InjectionType

    interface = HumanInterface(project_dir)

    # Request human input
    response = await interface.request_input(
        point_type=InjectionType.DECISION,
        context={"decision": "Which approach?"},
        options=["Option A", "Option B"],
        recommendation="Option A",
        timeout_seconds=300
    )

    if response.responded:
        print(f"Human chose: {response.response}")
    else:
        print(f"Timeout, using default: {response.response}")
"""

import asyncio
import json
import os
import signal
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select, update, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from arcadiaforge.db.models import InjectionPointModel
from arcadiaforge.output import (
    console,
    print_header,
    print_warning_panel,
    print_key_value,
    print_list,
    print_muted,
    icon,
)


class InjectionType(Enum):
    """Types of human injection points."""
    DECISION = "decision"           # Choose between options
    APPROVAL = "approval"           # Yes/no for risky action
    GUIDANCE = "guidance"           # Free-form input needed
    REVIEW = "review"               # Human should review output
    REDIRECT = "redirect"           # Change goals/direction


@dataclass
class InjectionPoint:
    """
    Represents a point where human input is requested.

    Injection points are persistent - they're written to a file
    and the agent polls for a response.
    """
    point_id: str               # "INJ-{session}-{seq}"
    timestamp: str              # ISO format
    session_id: int

    # The injection request
    point_type: str             # InjectionType value
    context: dict               # What agent was doing
    options: list[str]          # Available choices (for DECISION)
    recommendation: str         # Agent's preferred choice

    # Configuration
    timeout_seconds: int
    default_on_timeout: Optional[str]  # What to use if timeout

    # Response (filled when human responds)
    response: Optional[str] = None
    responded_at: Optional[str] = None
    responded_by: str = "pending"  # "pending", "human", "timeout_default", "escalation"

    # Additional context
    escalation_rule_id: Optional[str] = None  # If triggered by escalation
    message: Optional[str] = None  # Display message for human
    severity: int = 3           # 1-5 (for UI display)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "InjectionPoint":
        """Create InjectionPoint from dictionary."""
        return cls(**data)

    @property
    def is_pending(self) -> bool:
        """Check if still waiting for response."""
        return self.responded_by == "pending"

    @property
    def is_responded(self) -> bool:
        """Check if response received."""
        return self.responded_by in ("human", "timeout_default", "escalation")

    def summary(self) -> str:
        """Return a brief summary string."""
        status = "PENDING" if self.is_pending else f"RESPONDED ({self.responded_by})"
        return f"[{self.point_id}] {self.point_type} ({status}): {self.recommendation[:30]}..."


@dataclass
class InjectionResponse:
    """Response from a human injection request."""
    point_id: str
    responded: bool
    response: str
    responded_by: str           # "human", "timeout_default", "cancelled"
    timestamp: str


class HumanInterface:
    """
    Manages human injection points and database-based communication.

    All injection points are stored in the `injection_points` table in the
    project database (.arcadia/project.db). This replaces the previous
    file-based approach using the .human/ directory.

    Database schema:
        injection_points table with fields:
        - point_id: Unique identifier (e.g., "INJ-1-5")
        - timestamp: When the injection was created
        - session_id: Session that created the injection
        - point_type: Type of injection (decision, approval, guidance, etc.)
        - status: "pending", "responded", "timeout", or "cancelled"
        - response: Human's response (once provided)
        - responded_by: Who/what provided the response
    """

    def __init__(self, project_dir: Path, session_id: int = 0):
        """
        Initialize HumanInterface.

        Args:
            project_dir: Path to project directory
            session_id: Current session ID
        """
        self.project_dir = Path(project_dir)
        self.session_id = session_id

        # Database session (set via set_session or init_async)
        self._db_session: Optional[AsyncSession] = None

        # Sequence counter (will be loaded from DB)
        self._seq = 1

        # Pause flag for signal handling
        self._pause_requested = False

    def set_session(self, session: AsyncSession) -> None:
        """Set the database session for async operations."""
        self._db_session = session

    async def init_async(self, session: AsyncSession) -> None:
        """Initialize with async database session and load sequence counter."""
        self._db_session = session
        self._seq = await self._get_next_seq_async()

    async def _get_next_seq_async(self) -> int:
        """Get the next sequence number for injection IDs from database."""
        if not self._db_session:
            return 1

        result = await self._db_session.execute(
            select(func.max(InjectionPointModel.id))
        )
        max_id = result.scalar_one_or_none()
        return (max_id or 0) + 1

    def _get_next_seq(self) -> int:
        """Get the next sequence number (sync wrapper)."""
        if self._db_session:
            try:
                loop = asyncio.get_running_loop()
                # In async context, schedule as task
                future = asyncio.ensure_future(self._get_next_seq_async())
                return 1  # Will be updated on next async call
            except RuntimeError:
                # No running loop, use asyncio.run
                return asyncio.run(self._get_next_seq_async())
        return 1

    def update_session_id(self, session_id: int) -> None:
        """Update the current session ID."""
        self.session_id = session_id

    async def request_input(
        self,
        point_type: InjectionType | str,
        context: dict,
        options: list[str],
        recommendation: str,
        timeout_seconds: int = 300,
        default_on_timeout: Optional[str] = None,
        message: Optional[str] = None,
        severity: int = 3,
        escalation_rule_id: Optional[str] = None,
    ) -> InjectionResponse:
        """
        Request input from a human.

        Creates an injection point and polls for a response.

        Args:
            point_type: Type of injection
            context: Context dictionary for human understanding
            options: Available options to choose from
            recommendation: Agent's recommended choice
            timeout_seconds: How long to wait for response
            default_on_timeout: Value to use if timeout (None = wait forever)
            message: Optional message to display to human
            severity: 1-5 severity for UI display
            escalation_rule_id: If triggered by an escalation rule

        Returns:
            InjectionResponse with the human's choice or timeout default
        """
        # Generate injection point ID
        point_id = f"INJ-{self.session_id}-{self._seq}"
        self._seq += 1

        # Get type value
        if isinstance(point_type, InjectionType):
            type_value = point_type.value
        else:
            type_value = str(point_type)

        # Create injection point
        injection = InjectionPoint(
            point_id=point_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=self.session_id,
            point_type=type_value,
            context=context,
            options=options,
            recommendation=recommendation,
            timeout_seconds=timeout_seconds,
            default_on_timeout=default_on_timeout,
            message=message,
            severity=severity,
            escalation_rule_id=escalation_rule_id,
        )

        # Save to database
        await self._save_injection_async(injection)

        # Print notification for human
        self._notify_human(injection)

        # Poll for response
        response = await self._poll_for_response(injection)

        # Complete injection in database
        await self._complete_injection_async(injection, response)

        return response

    def _notify_human(self, injection: InjectionPoint) -> None:
        """Print notification about pending injection point."""
        severity_icons = {1: icon("info"), 2: icon("info"), 3: icon("warning"), 4: icon("warning"), 5: icon("blocked")}
        sev_icon = severity_icons.get(injection.severity, icon("warning"))

        console.print()
        print_header(f"{sev_icon} HUMAN INPUT REQUESTED")

        console.print(f"[af.muted]Point ID:[/] [af.accent]{injection.point_id}[/]")
        console.print(f"[af.muted]Type:[/] {injection.point_type}")

        if injection.message:
            console.print(f"[af.muted]Message:[/] {injection.message}")

        console.print(f"[af.muted]Recommendation:[/] [af.ok]{injection.recommendation}[/]")

        if injection.options:
            console.print("\n[af.muted]Options:[/]")
            for i, opt in enumerate(injection.options, 1):
                if opt == injection.recommendation:
                    console.print(f"  [af.number]{i}.[/] [af.ok]{opt}[/] [af.muted](recommended)[/]")
                else:
                    console.print(f"  [af.number]{i}.[/] {opt}")

        console.print(f"\n[af.muted]Timeout:[/] [af.number]{injection.timeout_seconds}[/] seconds")

        if injection.default_on_timeout:
            console.print(f"[af.muted]Default on timeout:[/] {injection.default_on_timeout}")
        else:
            console.print("[af.warn]No timeout default - will wait indefinitely[/]")

        console.print("\n[af.muted]Respond using:[/]")
        console.print(f"  [af.accent]python respond.py --point-id {injection.point_id} --response \"<your choice>\"[/]")
        console.print()

    async def _poll_for_response(self, injection: InjectionPoint) -> InjectionResponse:
        """
        Poll for a response in the database.

        Args:
            injection: The injection point waiting for response

        Returns:
            InjectionResponse when received or timeout
        """
        start_time = datetime.now(timezone.utc)
        timeout = injection.timeout_seconds
        has_default = injection.default_on_timeout is not None

        poll_interval = 1.0  # Check every second

        while True:
            # Check for response in database
            if self._db_session:
                result = await self._db_session.execute(
                    select(InjectionPointModel)
                    .where(InjectionPointModel.point_id == injection.point_id)
                )
                db_record = result.scalar_one_or_none()

                if db_record and db_record.status != "pending":
                    return InjectionResponse(
                        point_id=injection.point_id,
                        responded=db_record.status == "responded",
                        response=db_record.response or injection.recommendation,
                        responded_by=db_record.responded_by or "human",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )

            # Check for pause request
            if self._pause_requested:
                return InjectionResponse(
                    point_id=injection.point_id,
                    responded=False,
                    response=injection.default_on_timeout or injection.recommendation,
                    responded_by="pause_requested",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            # Check timeout
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            if has_default and elapsed >= timeout:
                return InjectionResponse(
                    point_id=injection.point_id,
                    responded=False,
                    response=injection.default_on_timeout,
                    responded_by="timeout_default",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )

            # Wait before next poll
            await asyncio.sleep(poll_interval)

    async def _complete_injection_async(self, injection: InjectionPoint, response: InjectionResponse) -> None:
        """Archive completed injection point in database."""
        if not self._db_session:
            return

        # Update injection record in DB
        await self._db_session.execute(
            update(InjectionPointModel)
            .where(InjectionPointModel.point_id == injection.point_id)
            .values(
                response=response.response,
                responded_at=datetime.fromisoformat(response.timestamp.replace('Z', '+00:00')) if response.timestamp else None,
                responded_by=response.responded_by,
                status="responded" if response.responded else "timeout",
            )
        )
        await self._db_session.commit()

    def _complete_injection(self, injection: InjectionPoint, response: InjectionResponse) -> None:
        """Archive completed injection point (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self._complete_injection_async(injection, response))
        except RuntimeError:
            asyncio.run(self._complete_injection_async(injection, response))

    async def _save_injection_async(self, injection: InjectionPoint) -> None:
        """Save injection point to database."""
        if not self._db_session:
            return

        db_model = InjectionPointModel(
            point_id=injection.point_id,
            timestamp=datetime.fromisoformat(injection.timestamp.replace('Z', '+00:00')),
            session_id=injection.session_id,
            point_type=injection.point_type,
            context=injection.context,
            options=injection.options,
            recommendation=injection.recommendation,
            timeout_seconds=injection.timeout_seconds,
            default_on_timeout=injection.default_on_timeout,
            message=injection.message,
            severity=injection.severity,
            escalation_rule_id=injection.escalation_rule_id,
            status="pending",
            responded_by="pending",
        )
        self._db_session.add(db_model)
        await self._db_session.commit()

    def _log_injection(self, injection: InjectionPoint, completed: bool = False) -> None:
        """Log injection point - now handled by database, kept for backward compatibility."""
        # Logging is now handled by the database operations
        pass

    async def get_pending_async(self) -> list[InjectionPoint]:
        """Get all pending injection points from database."""
        if not self._db_session:
            return []

        result = await self._db_session.execute(
            select(InjectionPointModel)
            .where(InjectionPointModel.status == "pending")
            .order_by(InjectionPointModel.timestamp)
        )
        rows = result.scalars().all()

        pending = []
        for row in rows:
            pending.append(InjectionPoint(
                point_id=row.point_id,
                timestamp=row.timestamp.isoformat() if row.timestamp else "",
                session_id=row.session_id,
                point_type=row.point_type,
                context=row.context or {},
                options=row.options or [],
                recommendation=row.recommendation or "",
                timeout_seconds=row.timeout_seconds or 300,
                default_on_timeout=row.default_on_timeout,
                response=row.response,
                responded_at=row.responded_at.isoformat() if row.responded_at else None,
                responded_by=row.responded_by or "pending",
                escalation_rule_id=row.escalation_rule_id,
                message=row.message,
                severity=row.severity or 3,
            ))
        return pending

    def get_pending(self) -> list[InjectionPoint]:
        """Get all pending injection points (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            # Can't block in async context, return empty
            return []
        except RuntimeError:
            return asyncio.run(self.get_pending_async())

    async def get_injection_async(self, point_id: str) -> Optional[InjectionPoint]:
        """Get an injection point by ID from database."""
        if not self._db_session:
            return None

        result = await self._db_session.execute(
            select(InjectionPointModel)
            .where(InjectionPointModel.point_id == point_id)
        )
        row = result.scalar_one_or_none()

        if not row:
            return None

        return InjectionPoint(
            point_id=row.point_id,
            timestamp=row.timestamp.isoformat() if row.timestamp else "",
            session_id=row.session_id,
            point_type=row.point_type,
            context=row.context or {},
            options=row.options or [],
            recommendation=row.recommendation or "",
            timeout_seconds=row.timeout_seconds or 300,
            default_on_timeout=row.default_on_timeout,
            response=row.response,
            responded_at=row.responded_at.isoformat() if row.responded_at else None,
            responded_by=row.responded_by or "pending",
            escalation_rule_id=row.escalation_rule_id,
            message=row.message,
            severity=row.severity or 3,
        )

    def get_injection(self, point_id: str) -> Optional[InjectionPoint]:
        """Get an injection point by ID (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return None  # Can't block in async context
        except RuntimeError:
            return asyncio.run(self.get_injection_async(point_id))

    async def respond_async(self, point_id: str, response: str) -> bool:
        """
        Respond to an injection point in database.

        This is typically called by the respond.py CLI tool.

        Args:
            point_id: Injection point ID
            response: The response

        Returns:
            True if response recorded, False if injection not found
        """
        if not self._db_session:
            return False

        # Check if pending
        result = await self._db_session.execute(
            select(InjectionPointModel)
            .where(InjectionPointModel.point_id == point_id)
            .where(InjectionPointModel.status == "pending")
        )
        row = result.scalar_one_or_none()

        if not row:
            return False

        # Update the record
        await self._db_session.execute(
            update(InjectionPointModel)
            .where(InjectionPointModel.point_id == point_id)
            .values(
                response=response,
                responded_at=datetime.now(timezone.utc),
                responded_by="human",
                status="responded",
            )
        )
        await self._db_session.commit()
        return True

    def respond(self, point_id: str, response: str) -> bool:
        """Respond to an injection point (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            # Can't block in async context
            asyncio.create_task(self.respond_async(point_id, response))
            return True
        except RuntimeError:
            return asyncio.run(self.respond_async(point_id, response))

    async def cancel_async(self, point_id: str) -> bool:
        """
        Cancel a pending injection point in database.

        Args:
            point_id: Injection point ID

        Returns:
            True if cancelled, False if not found
        """
        if not self._db_session:
            return False

        # Check if pending
        result = await self._db_session.execute(
            select(InjectionPointModel)
            .where(InjectionPointModel.point_id == point_id)
            .where(InjectionPointModel.status == "pending")
        )
        row = result.scalar_one_or_none()

        if not row:
            return False

        # Update the record
        await self._db_session.execute(
            update(InjectionPointModel)
            .where(InjectionPointModel.point_id == point_id)
            .values(
                responded_at=datetime.now(timezone.utc),
                responded_by="cancelled",
                status="cancelled",
            )
        )
        await self._db_session.commit()
        return True

    def cancel(self, point_id: str) -> bool:
        """Cancel a pending injection point (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self.cancel_async(point_id))
            return True
        except RuntimeError:
            return asyncio.run(self.cancel_async(point_id))

    def request_pause(self) -> None:
        """Request the interface to pause (for signal handling)."""
        self._pause_requested = True

    async def get_history_async(self, limit: int = 50, session_id: Optional[int] = None) -> list[dict]:
        """
        Get injection point history from database.

        Args:
            limit: Maximum entries to return
            session_id: Optional session filter

        Returns:
            List of history entries (newest first)
        """
        if not self._db_session:
            return []

        query = select(InjectionPointModel).order_by(desc(InjectionPointModel.timestamp))

        if session_id is not None:
            query = query.where(InjectionPointModel.session_id == session_id)

        query = query.limit(limit)

        result = await self._db_session.execute(query)
        rows = result.scalars().all()

        entries = []
        for row in rows:
            entry = {
                "point_id": row.point_id,
                "timestamp": row.timestamp.isoformat() if row.timestamp else "",
                "point_type": row.point_type,
                "session_id": row.session_id,
                "recommendation": row.recommendation,
                "completed": row.status != "pending",
            }
            if row.status != "pending":
                entry["response"] = row.response
                entry["responded_by"] = row.responded_by
                entry["responded_at"] = row.responded_at.isoformat() if row.responded_at else None
            entries.append(entry)

        return entries

    def get_history(self, limit: int = 50, session_id: Optional[int] = None) -> list[dict]:
        """Get injection point history (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return []  # Can't block in async context
        except RuntimeError:
            return asyncio.run(self.get_history_async(limit, session_id))

    async def get_stats_async(self) -> dict:
        """
        Get injection point statistics from database.

        Returns:
            Dictionary with statistics
        """
        if not self._db_session:
            return {
                "total_injections": 0,
                "pending_count": 0,
                "by_type": {},
                "by_responded_by": {},
            }

        # Get total count
        total_result = await self._db_session.execute(
            select(func.count(InjectionPointModel.id))
        )
        total_count = total_result.scalar_one_or_none() or 0

        # Get pending count
        pending_result = await self._db_session.execute(
            select(func.count(InjectionPointModel.id))
            .where(InjectionPointModel.status == "pending")
        )
        pending_count = pending_result.scalar_one_or_none() or 0

        # Get counts by type
        type_result = await self._db_session.execute(
            select(InjectionPointModel.point_type, func.count(InjectionPointModel.id))
            .group_by(InjectionPointModel.point_type)
        )
        by_type = {row[0]: row[1] for row in type_result.all()}

        # Get counts by responded_by (for completed only)
        responded_result = await self._db_session.execute(
            select(InjectionPointModel.responded_by, func.count(InjectionPointModel.id))
            .where(InjectionPointModel.status != "pending")
            .group_by(InjectionPointModel.responded_by)
        )
        by_responded_by = {row[0]: row[1] for row in responded_result.all()}

        return {
            "total_injections": total_count,
            "pending_count": pending_count,
            "by_type": by_type,
            "by_responded_by": by_responded_by,
        }

    def get_stats(self) -> dict:
        """Get injection point statistics (sync wrapper)."""
        try:
            loop = asyncio.get_running_loop()
            return {
                "total_injections": 0,
                "pending_count": 0,
                "by_type": {},
                "by_responded_by": {},
            }
        except RuntimeError:
            return asyncio.run(self.get_stats_async())


def create_human_interface(project_dir: Path, session_id: int = 0) -> HumanInterface:
    """Create a HumanInterface for a project."""
    return HumanInterface(project_dir, session_id)


async def create_human_interface_async(
    project_dir: Path,
    session_id: int,
    session: AsyncSession,
) -> HumanInterface:
    """
    Create a HumanInterface with async database session.

    Args:
        project_dir: Path to project directory
        session_id: Current session ID
        session: AsyncSession for database operations

    Returns:
        Initialized HumanInterface
    """
    interface = HumanInterface(project_dir, session_id)
    await interface.init_async(session)
    return interface


# Synchronous wrapper for non-async contexts
def request_human_input_sync(
    project_dir: Path,
    point_type: InjectionType | str,
    context: dict,
    options: list[str],
    recommendation: str,
    timeout_seconds: int = 300,
    default_on_timeout: Optional[str] = None,
    session_id: int = 0,
) -> InjectionResponse:
    """
    Synchronous wrapper for requesting human input.

    Args:
        project_dir: Project directory
        point_type: Type of injection
        context: Context dictionary
        options: Available options
        recommendation: Agent's recommendation
        timeout_seconds: Timeout in seconds
        default_on_timeout: Default value on timeout
        session_id: Current session ID

    Returns:
        InjectionResponse
    """
    interface = HumanInterface(project_dir, session_id)
    return asyncio.run(interface.request_input(
        point_type=point_type,
        context=context,
        options=options,
        recommendation=recommendation,
        timeout_seconds=timeout_seconds,
        default_on_timeout=default_on_timeout,
    ))
