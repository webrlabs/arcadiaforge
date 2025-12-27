"""
Tests for Human Interface Module
================================

Tests for human_interface.py - human injection points and responses.
"""

import asyncio
import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from arcadiaforge.human_interface import (
    InjectionPoint,
    InjectionType,
    InjectionResponse,
    HumanInterface,
    create_human_interface,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_project():
    """Create a temporary project directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def human_interface(temp_project):
    """Create a HumanInterface for testing."""
    return HumanInterface(temp_project, session_id=1)


# =============================================================================
# InjectionType Tests
# =============================================================================

class TestInjectionType:
    """Tests for InjectionType enum."""

    def test_all_types_have_values(self):
        """Test that all injection types have string values."""
        for itype in InjectionType:
            assert isinstance(itype.value, str)
            assert len(itype.value) > 0

    def test_expected_types_exist(self):
        """Test that expected injection types exist."""
        assert InjectionType.DECISION.value == "decision"
        assert InjectionType.APPROVAL.value == "approval"
        assert InjectionType.GUIDANCE.value == "guidance"
        assert InjectionType.REVIEW.value == "review"
        assert InjectionType.REDIRECT.value == "redirect"


# =============================================================================
# InjectionPoint Tests
# =============================================================================

class TestInjectionPoint:
    """Tests for the InjectionPoint dataclass."""

    def test_injection_point_creation(self):
        """Test creating an InjectionPoint."""
        point = InjectionPoint(
            point_id="INJ-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            point_type="decision",
            context={"decision": "Which approach?"},
            options=["Option A", "Option B"],
            recommendation="Option A",
            timeout_seconds=300,
            default_on_timeout="Option A",
        )

        assert point.point_id == "INJ-1-1"
        assert point.session_id == 1
        assert len(point.options) == 2

    def test_injection_point_to_dict(self):
        """Test converting InjectionPoint to dictionary."""
        point = InjectionPoint(
            point_id="INJ-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            point_type="approval",
            context={"action": "Delete files"},
            options=["Yes", "No"],
            recommendation="No",
            timeout_seconds=60,
            default_on_timeout="No",
            severity=5,
        )

        d = point.to_dict()
        assert d["point_id"] == "INJ-1-1"
        assert d["severity"] == 5

    def test_injection_point_from_dict(self):
        """Test creating InjectionPoint from dictionary."""
        data = {
            "point_id": "INJ-2-3",
            "timestamp": "2025-12-18T10:00:00Z",
            "session_id": 2,
            "point_type": "guidance",
            "context": {"question": "How to proceed?"},
            "options": [],
            "recommendation": "",
            "timeout_seconds": 600,
            "default_on_timeout": None,
        }

        point = InjectionPoint.from_dict(data)
        assert point.point_id == "INJ-2-3"
        assert point.point_type == "guidance"

    def test_is_pending(self):
        """Test is_pending property."""
        pending = InjectionPoint(
            point_id="INJ-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            point_type="decision",
            context={},
            options=[],
            recommendation="",
            timeout_seconds=300,
            default_on_timeout=None,
            responded_by="pending",
        )
        responded = InjectionPoint(
            point_id="INJ-1-2",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            point_type="decision",
            context={},
            options=[],
            recommendation="",
            timeout_seconds=300,
            default_on_timeout=None,
            responded_by="human",
        )

        assert pending.is_pending is True
        assert responded.is_pending is False

    def test_is_responded(self):
        """Test is_responded property."""
        point = InjectionPoint(
            point_id="INJ-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            point_type="decision",
            context={},
            options=[],
            recommendation="",
            timeout_seconds=300,
            default_on_timeout=None,
            responded_by="timeout_default",
        )

        assert point.is_responded is True

    def test_summary(self):
        """Test summary method."""
        point = InjectionPoint(
            point_id="INJ-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            point_type="decision",
            context={},
            options=[],
            recommendation="Use approach A for better performance",
            timeout_seconds=300,
            default_on_timeout=None,
        )

        summary = point.summary()
        assert "INJ-1-1" in summary
        assert "PENDING" in summary


# =============================================================================
# InjectionResponse Tests
# =============================================================================

class TestInjectionResponse:
    """Tests for the InjectionResponse dataclass."""

    def test_response_creation(self):
        """Test creating an InjectionResponse."""
        response = InjectionResponse(
            point_id="INJ-1-1",
            responded=True,
            response="Option B",
            responded_by="human",
            timestamp="2025-12-18T10:05:00Z",
        )

        assert response.point_id == "INJ-1-1"
        assert response.responded is True
        assert response.response == "Option B"


# =============================================================================
# HumanInterface Tests
# =============================================================================

class TestHumanInterface:
    """Tests for the HumanInterface class."""

    def test_interface_initialization(self, temp_project):
        """Test interface creates directories."""
        interface = HumanInterface(temp_project, session_id=1)

        assert interface.pending_dir.exists()
        assert interface.responses_dir.exists()
        assert interface.completed_dir.exists()

    def test_update_session_id(self, human_interface):
        """Test updating session ID."""
        human_interface.update_session_id(5)
        assert human_interface.session_id == 5

    def test_respond_to_pending(self, human_interface):
        """Test responding to a pending injection point."""
        # First create a pending injection point file manually
        point = InjectionPoint(
            point_id="INJ-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            point_type="decision",
            context={"test": True},
            options=["A", "B"],
            recommendation="A",
            timeout_seconds=300,
            default_on_timeout="A",
        )

        pending_file = human_interface.pending_dir / "INJ-1-1.json"
        with open(pending_file, "w") as f:
            json.dump(point.to_dict(), f)

        # Respond to it
        success = human_interface.respond("INJ-1-1", "B")
        assert success is True

        # Check response file was created
        response_file = human_interface.responses_dir / "INJ-1-1.json"
        assert response_file.exists()

    def test_respond_to_nonexistent(self, human_interface):
        """Test responding to nonexistent injection point."""
        success = human_interface.respond("INJ-99-99", "Test")
        assert success is False

    def test_get_pending(self, human_interface):
        """Test getting pending injection points."""
        # Create some pending points
        for i in range(3):
            point = InjectionPoint(
                point_id=f"INJ-1-{i}",
                timestamp=f"2025-12-18T10:0{i}:00Z",
                session_id=1,
                point_type="decision",
                context={},
                options=[],
                recommendation="",
                timeout_seconds=300,
                default_on_timeout=None,
            )
            pending_file = human_interface.pending_dir / f"INJ-1-{i}.json"
            with open(pending_file, "w") as f:
                json.dump(point.to_dict(), f)

        pending = human_interface.get_pending()
        assert len(pending) == 3

    def test_get_injection(self, human_interface):
        """Test getting an injection point by ID."""
        # Create a pending point
        point = InjectionPoint(
            point_id="INJ-1-5",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            point_type="approval",
            context={"action": "test"},
            options=["Yes", "No"],
            recommendation="No",
            timeout_seconds=60,
            default_on_timeout="No",
        )
        pending_file = human_interface.pending_dir / "INJ-1-5.json"
        with open(pending_file, "w") as f:
            json.dump(point.to_dict(), f)

        retrieved = human_interface.get_injection("INJ-1-5")
        assert retrieved is not None
        assert retrieved.point_id == "INJ-1-5"
        assert retrieved.point_type == "approval"

    def test_get_nonexistent_injection(self, human_interface):
        """Test getting nonexistent injection point."""
        result = human_interface.get_injection("INJ-99-99")
        assert result is None

    def test_cancel(self, human_interface):
        """Test cancelling an injection point."""
        # Create a pending point
        point = InjectionPoint(
            point_id="INJ-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            point_type="decision",
            context={},
            options=[],
            recommendation="",
            timeout_seconds=300,
            default_on_timeout=None,
        )
        pending_file = human_interface.pending_dir / "INJ-1-1.json"
        with open(pending_file, "w") as f:
            json.dump(point.to_dict(), f)

        # Cancel it
        success = human_interface.cancel("INJ-1-1")
        assert success is True

        # Should no longer be pending
        assert not pending_file.exists()

        # Should be in completed
        completed_file = human_interface.completed_dir / "INJ-1-1.json"
        assert completed_file.exists()

        # Check cancelled status
        with open(completed_file, "r") as f:
            data = json.load(f)
        assert data["responded_by"] == "cancelled"

    def test_cancel_nonexistent(self, human_interface):
        """Test cancelling nonexistent injection point."""
        success = human_interface.cancel("INJ-99-99")
        assert success is False

    def test_get_history(self, human_interface):
        """Test getting injection point history."""
        # Create and respond to some injection points
        for i in range(3):
            point = InjectionPoint(
                point_id=f"INJ-1-{i}",
                timestamp=f"2025-12-18T10:0{i}:00Z",
                session_id=1,
                point_type="decision",
                context={},
                options=[],
                recommendation="A",
                timeout_seconds=300,
                default_on_timeout=None,
            )
            pending_file = human_interface.pending_dir / f"INJ-1-{i}.json"
            with open(pending_file, "w") as f:
                json.dump(point.to_dict(), f)

            # Log creation
            human_interface._log_injection(point)

        history = human_interface.get_history()
        assert len(history) == 3

    def test_get_stats(self, human_interface):
        """Test getting injection point statistics."""
        # Create some injection points
        for i in range(2):
            point = InjectionPoint(
                point_id=f"INJ-1-{i}",
                timestamp=f"2025-12-18T10:0{i}:00Z",
                session_id=1,
                point_type="decision",
                context={},
                options=[],
                recommendation="A",
                timeout_seconds=300,
                default_on_timeout=None,
            )
            pending_file = human_interface.pending_dir / f"INJ-1-{i}.json"
            with open(pending_file, "w") as f:
                json.dump(point.to_dict(), f)

            human_interface._log_injection(point)

        stats = human_interface.get_stats()
        assert stats["pending_count"] == 2

    def test_request_pause(self, human_interface):
        """Test requesting pause."""
        human_interface.request_pause()
        assert human_interface._pause_requested is True


# =============================================================================
# Async Request Input Tests
# =============================================================================

class TestAsyncRequestInput:
    """Tests for async request_input method."""

    @pytest.mark.asyncio
    async def test_request_input_with_immediate_response(self, human_interface):
        """Test request_input when response is immediately available."""
        # Start request in background
        async def make_request():
            return await human_interface.request_input(
                point_type=InjectionType.DECISION,
                context={"test": True},
                options=["A", "B"],
                recommendation="A",
                timeout_seconds=1,
                default_on_timeout="A",
            )

        # Start the request
        task = asyncio.create_task(make_request())

        # Give it a moment to create the pending file
        await asyncio.sleep(0.1)

        # Find the pending file
        pending = list(human_interface.pending_dir.glob("INJ-*.json"))
        assert len(pending) == 1

        point_id = pending[0].stem

        # Respond to it
        human_interface.respond(point_id, "B")

        # Wait for result
        response = await task

        assert response.responded is True
        assert response.response == "B"
        assert response.responded_by == "human"

    @pytest.mark.asyncio
    async def test_request_input_timeout(self, human_interface):
        """Test request_input with timeout."""
        response = await human_interface.request_input(
            point_type=InjectionType.DECISION,
            context={"test": True},
            options=["A", "B"],
            recommendation="A",
            timeout_seconds=1,  # Very short timeout
            default_on_timeout="A",
        )

        # Should timeout and use default
        assert response.responded is False
        assert response.response == "A"
        assert response.responded_by == "timeout_default"


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_human_interface(self, temp_project):
        """Test create_human_interface factory function."""
        interface = create_human_interface(temp_project, session_id=5)
        assert isinstance(interface, HumanInterface)
        assert interface.session_id == 5


# =============================================================================
# Injection Point Completion Tests
# =============================================================================

class TestInjectionCompletion:
    """Tests for injection point completion workflow."""

    def test_complete_injection_moves_files(self, human_interface):
        """Test that completing an injection moves files correctly."""
        # Create a pending injection
        point = InjectionPoint(
            point_id="INJ-1-1",
            timestamp="2025-12-18T10:00:00Z",
            session_id=1,
            point_type="decision",
            context={"test": True},
            options=["A", "B"],
            recommendation="A",
            timeout_seconds=300,
            default_on_timeout="A",
        )
        pending_file = human_interface.pending_dir / "INJ-1-1.json"
        with open(pending_file, "w") as f:
            json.dump(point.to_dict(), f)

        # Simulate completion
        response = InjectionResponse(
            point_id="INJ-1-1",
            responded=True,
            response="B",
            responded_by="human",
            timestamp="2025-12-18T10:05:00Z",
        )
        human_interface._complete_injection(point, response)

        # Pending file should be gone
        assert not pending_file.exists()

        # Completed file should exist
        completed_file = human_interface.completed_dir / "INJ-1-1.json"
        assert completed_file.exists()

        # Verify completed data
        with open(completed_file, "r") as f:
            data = json.load(f)
        assert data["response"] == "B"
        assert data["responded_by"] == "human"


# =============================================================================
# Sequence Number Tests
# =============================================================================

class TestSequenceNumbers:
    """Tests for sequence number handling."""

    def test_sequence_increments(self, human_interface):
        """Test that sequence numbers increment correctly."""
        # Create some injection points manually
        for i in range(3):
            point = InjectionPoint(
                point_id=f"INJ-1-{i+1}",
                timestamp="2025-12-18T10:00:00Z",
                session_id=1,
                point_type="decision",
                context={},
                options=[],
                recommendation="",
                timeout_seconds=300,
                default_on_timeout=None,
            )
            pending_file = human_interface.pending_dir / f"INJ-1-{i+1}.json"
            with open(pending_file, "w") as f:
                json.dump(point.to_dict(), f)

        # Create a new interface - should pick up next sequence
        new_interface = HumanInterface(human_interface.project_dir, session_id=1)
        assert new_interface._seq == 4
