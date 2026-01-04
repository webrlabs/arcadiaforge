import asyncio
import uuid
import time
from collections import deque
from datetime import datetime
from typing import Optional, List, Callable, Any, Deque, Dict
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

        # Chat interface tracking
        self._tool_start_times: Dict[str, float] = {}  # Track tool execution times
        self._pending_question_id: Optional[str] = None  # Current pending question
        self._is_thinking: bool = False

    async def start(self):
        if self._active:
            return
        self._active = True
        await self._emit("system", "Terminal connected", "info")

    async def stop(self):
        if not self._active:
            return
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
                "id": str(uuid.uuid4()),
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
        """Output text - emits as agent_message for chat display."""
        # Use agent_message for chat-style display
        self._push_event("agent_message", {
            "content": text,
            "isStreaming": False
        })

    def output_tool(self, tool_name: str, summary: str, result: str) -> None:
        """Output tool result - emits as tool_call with completed status."""
        tool_id = str(uuid.uuid4())
        status = "failed" if result == "error" or result == "blocked" else "completed"
        self._push_event("tool_call", {
            "toolId": tool_id,
            "name": tool_name,
            "summary": summary,
            "status": status,
            "input": None
        })
        # Immediately emit the result
        self._push_event("tool_result", {
            "toolId": tool_id,
            "status": status,
            "result": None,  # Don't include full result for compact display
            "duration": None
        })

    def output_success(self, text: str) -> None:
        """Output success message - emits as system message."""
        self._push_event("system", {"message": text, "level": "success"})

    def output_error(self, text: str) -> None:
        """Output error message - emits as system message."""
        self._push_event("system", {"message": text, "level": "error"})

    def output_info(self, text: str) -> None:
        """Output info message - emits as system message."""
        self._push_event("system", {"message": text, "level": "info"})

    def output_warning(self, text: str) -> None:
        """Output warning message - emits as system message."""
        self._push_event("system", {"message": text, "level": "warning"})

    def output_muted(self, text: str) -> None:
        """Output muted text - emits as agent message."""
        self._push_event("agent_message", {"content": text, "isStreaming": False})

    def output_feedback_received(self, feedback: UserFeedback) -> None:
        self._push_event("feedback_ack", {
            "message": feedback.message,
            "type": feedback.feedback_type
        })

    # --- Chat Interface Methods (New Event Types) ---

    def emit_agent_message(self, content: str, is_streaming: bool = False) -> None:
        """Emit an agent text message (chat bubble)."""
        self._push_event("agent_message", {
            "content": content,
            "isStreaming": is_streaming
        })

    def emit_tool_start(self, tool_id: str, name: str, summary: str, input_data: dict = None) -> None:
        """Emit a tool call start event."""
        self._tool_start_times[tool_id] = time.time()
        self._push_event("tool_call", {
            "toolId": tool_id,
            "name": name,
            "summary": summary,
            "input": input_data,
            "status": "running"
        })

    def emit_tool_end(self, tool_id: str, status: str = "completed", result: str = None, image_url: str = None) -> None:
        """Emit a tool call completion event."""
        duration = None
        if tool_id in self._tool_start_times:
            duration = int((time.time() - self._tool_start_times[tool_id]) * 1000)
            del self._tool_start_times[tool_id]

        payload = {
            "toolId": tool_id,
            "status": status,
            "result": result,
            "duration": duration
        }
        if image_url:
            payload["imageUrl"] = image_url
        self._push_event("tool_result", payload)

    def emit_user_question(self, question: str, options: List[str] = None, input_type: str = "text") -> str:
        """Emit a question from agent to user. Returns the question ID."""
        question_id = str(uuid.uuid4())
        self._pending_question_id = question_id
        self._push_event("user_question", {
            "questionId": question_id,
            "question": question,
            "options": options,
            "inputType": input_type
        })
        return question_id

    def emit_user_response(self, question_id: str, response: str) -> None:
        """Emit the user's response to a question."""
        self._pending_question_id = None
        self._push_event("user_response", {
            "questionId": question_id,
            "response": response
        })

    def emit_thinking(self, is_thinking: bool) -> None:
        """Emit thinking state change."""
        if self._is_thinking != is_thinking:
            self._is_thinking = is_thinking
            self._push_event("thinking", {
                "isThinking": is_thinking
            })

    def emit_system(self, message: str, level: str = "info") -> None:
        """Emit a system message."""
        self._push_event("system", {
            "message": message,
            "level": level
        })

    def emit_error(self, message: str, details: str = None) -> None:
        """Emit an error message."""
        self._push_event("error", {
            "message": message,
            "details": details
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
            self.output_feedback_received(feedback)
            if feedback.feedback_type == "stop":
                self.emit_system("Stop requested. Will end after current operation.", "warning")
            elif feedback.feedback_type == "pause":
                self.emit_system("Pause requested. Will pause after current operation.", "warning")
            elif feedback.feedback_type == "skip":
                self.emit_system("Skip requested. Will skip the current feature when safe.", "info")
            if self._on_feedback:
                self._on_feedback(feedback)

    async def __aenter__(self) -> "WebTerminal":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()
