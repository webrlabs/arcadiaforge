import asyncio
import os
from pathlib import Path
from typing import Any

from arcadiaforge.orchestrator import SessionOrchestrator
from arcadiaforge.output import set_live_terminal
from arcadiaforge.web.backend.bridge import WebTerminal


def _ensure_windows_event_loop() -> None:
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


async def _pump_events(terminal: WebTerminal, output_queue: Any) -> None:
    try:
        while True:
            event = await terminal.get_next_event()
            output_queue.put(event)
    except asyncio.CancelledError:
        return


async def _pump_inputs(terminal: WebTerminal, input_queue: Any) -> None:
    try:
        while True:
            item = await asyncio.to_thread(input_queue.get)
            if item is None:
                break
            if isinstance(item, dict) and item.get("type") == "shutdown":
                break
            if isinstance(item, str):
                terminal.receive_input(item)
    except asyncio.CancelledError:
        return


async def _run_orchestrator(project_dir: Path, model: str, terminal: WebTerminal) -> None:
    has_features = (project_dir / ".arcadia" / "project.db").exists()
    app_spec = project_dir / "app_spec.txt"

    orchestrator = SessionOrchestrator(
        project_dir=project_dir,
        model=model,
        enable_live_terminal=False,
    )
    orchestrator.live_terminal = terminal
    set_live_terminal(terminal)

    await terminal.start()
    if has_features:
        terminal.emit_system("Starting coding session...", "info")
    else:
        terminal.emit_system("Initializing new project from app_spec.txt...", "info")
    try:
        await orchestrator.run(app_spec_path=app_spec if not has_features else None)
    except Exception as exc:
        terminal.emit_error("Session error", str(exc)[:200])
    finally:
        await terminal.stop()


def run_agent_worker(project_dir: str, model: str, input_queue: Any, output_queue: Any) -> None:
    _ensure_windows_event_loop()

    project_path = Path(project_dir)
    terminal = WebTerminal()

    async def main() -> None:
        event_task = asyncio.create_task(_pump_events(terminal, output_queue))
        input_task = asyncio.create_task(_pump_inputs(terminal, input_queue))
        run_task = asyncio.create_task(_run_orchestrator(project_path, model, terminal))

        done, pending = await asyncio.wait(
            [event_task, input_task, run_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
        for task in done:
            if task is run_task:
                continue
            try:
                task.result()
            except Exception:
                pass

        output_queue.put(None)

    asyncio.run(main())
