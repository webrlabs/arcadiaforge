import asyncio
from collections import deque
from datetime import datetime
from typing import Optional, List, Callable, Any, Deque
from dataclasses import asdict

from arcadiaforge.live_terminal import UserFeedback, FeedbackProcessor

class WebTerminal:
    """
    A web-compatible implementation of LiveTerminal.
    Captures output events to send via WebSocket and receives input from WebSocket.
    """
    
    def __init__(self):
        # Output buffer (events to be sent to frontend)
        self._event_queue: asyncio.Queue = asyncio.Queue()
        
        # Input buffer (feedback received from frontend)
        self._feedback_queue: Deque[UserFeedback] = deque()
        self._processor = FeedbackProcessor()
        
        self._active = False
        self._on_feedback: Optional[Callable[[UserFeedback], None]] = None

    async def start(self):
        self._active = True
        await self._emit("system", "Terminal connected", "info")

    async def stop(self):
        self._active = False
        await self._emit("system", "Terminal disconnected", "info")

    @property
    def is_active(self) -> bool:
        return self._active

    def set_feedback_callback(self, callback: Callable[[UserFeedback], None]) -> None:
        self._on_feedback = callback

    # --- Output Methods (Called by Orchestrator) ---

    def _push_event(self, event_type: str, data: dict):
        if self._active:
            self._event_queue.put_nowait({
                "timestamp": datetime.now().isoformat(),
                "type": event_type,
                "data": data
            })

    async def _emit(self, category: str, message: str, style: str = "output"):
        """Internal helper to emit standard text logs."""
        self._push_event("log", {
            "category": category,
            "message": message,
            "style": style
        })

    def output(self, text: str, style: str = "output") -> None:
        self._push_event("log", {"message": text, "style": style})

    def output_tool(self, tool_name: str, summary: str, result: str) -> None:
        self._push_event("tool", {
            "name": tool_name,
            "summary": summary,
            "result": result
        })

    def output_success(self, text: str) -> None:
        self._push_event("log", {"message": text, "style": "success"})

    def output_error(self, text: str) -> None:
        self._push_event("log", {"message": text, "style": "error"})

    def output_info(self, text: str) -> None:
        self._push_event("log", {"message": text, "style": "info"})

    def output_warning(self, text: str) -> None:
        self._push_event("log", {"message": text, "style": "warning"})

    def output_muted(self, text: str) -> None:
        self._push_event("log", {"message": text, "style": "muted"})

    def output_feedback_received(self, feedback: UserFeedback) -> None:
        self._push_event("feedback_ack", {
            "message": feedback.message,
            "type": feedback.feedback_type
        })

    # --- Input Methods (Called by Orchestrator) ---

    def get_feedback(self) -> Optional[UserFeedback]:
        try:
            return self._feedback_queue.popleft()
        except IndexError:
            return None

    def get_all_feedback(self) -> List[UserFeedback]:
        items = list(self._feedback_queue)
        self._feedback_queue.clear()
        return items

    def has_feedback(self) -> bool:
        return len(self._feedback_queue) > 0

    # --- Web Interface Methods (Called by WebSocket Handler) ---

    async def get_next_event(self) -> dict:
        """Waits for and returns the next output event."""
        return await self._event_queue.get()

    def receive_input(self, text: str):
        """Receives raw text input from the web client."""
        feedback = self._processor.process(text)
        if feedback.feedback_type != "empty":
            self._feedback_queue.append(feedback)
            if self._on_feedback:
                self._on_feedback(feedback)
