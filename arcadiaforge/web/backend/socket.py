import asyncio
import json
import traceback
import sys
import os
import shutil
import subprocess
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from arcadiaforge.orchestrator import SessionOrchestrator
from arcadiaforge.output import set_live_terminal
from arcadiaforge import output as af_output
from arcadiaforge.web.backend.bridge import WebTerminal

router = APIRouter()

LOG_FILE = r"C:\Users\onlyj\Documents\arcadiaforge\backend_debug.txt"

def log_debug(msg: str):
    print(msg, file=sys.stderr)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except Exception as e:
        print(f"Failed to write to log: {e}", file=sys.stderr)

@router.websocket("/ws/run/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    await websocket.accept()
    log_debug(f"\n--- New Connection: {project_id} ---")
    log_debug(f"[WS] CWD: {os.getcwd()}")
    
    # Verify npx execution
    try:
        proc = subprocess.run(["npx", "--version"], capture_output=True, text=True, shell=True)
        log_debug(f"[WS] npx check: code={proc.returncode}, out={proc.stdout.strip()}, err={proc.stderr.strip()}")
    except Exception as e:
        log_debug(f"[WS] npx execution failed: {e}")

    project_dir = Path("generations") / project_id
    if not project_dir.exists():
        log_debug(f"[WS] Error: Project directory not found: {project_dir}")
        await websocket.close(code=4000, reason="Project not found")
        return

    # Monkey patch console.print to also send to web terminal
    original_print = af_output.console.print
    terminal_ref = [None] 

    def patched_print(*args, **kwargs):
        original_print(*args, **kwargs)
        if terminal_ref[0]:
            try:
                msg = " ".join(str(a) for a in args)
                terminal_ref[0].output(msg)
            except:
                pass

    af_output.console.print = patched_print

    try:
        terminal = WebTerminal()
        terminal_ref[0] = terminal
        
        log_debug(f"[WS] Initializing orchestrator for {project_dir}")
        
        orchestrator = SessionOrchestrator(
            project_dir=project_dir,
            model="claude-3-5-sonnet-20241022", # Default model
            enable_live_terminal=True
        )
        
        orchestrator.live_terminal = terminal
        set_live_terminal(terminal) 
        
        await terminal.start()
        log_debug("[WS] Terminal started")

    except Exception as e:
        log_debug(f"[WS] Error initializing orchestrator: {e}")
        log_debug(traceback.format_exc())
        await websocket.close(code=1011, reason=f"Init error: {str(e)}")
        af_output.console.print = original_print
        return

    # Task to pump events from Terminal -> WebSocket
    async def sender_task():
        try:
            while True:
                event = await terminal.get_next_event()
                await websocket.send_json(event)
        except Exception as e:
            log_debug(f"[WS] Sender task error: {e}")

    # Task to pump messages from WebSocket -> Terminal
    async def receiver_task():
        try:
            while True:
                data = await websocket.receive_text()
                terminal.receive_input(data)
        except WebSocketDisconnect:
            log_debug("[WS] Client disconnected")
            await terminal.stop()
        except Exception as e:
            log_debug(f"[WS] Receiver task error: {e}")

    # Task to run the actual agent
    async def agent_task():
        try:
            # First run detection logic (similar to CLI)
            has_features = (project_dir / ".arcadia" / "project.db").exists()
            app_spec = project_dir / "app_spec.txt"
            
            log_debug(f"[WS] Starting agent session... (has_features={has_features})")
            
            # Start the orchestrator
            await orchestrator.run(
                app_spec_path=app_spec if not has_features else None
            )
            
            await terminal._emit("system", "Session ended", "info")
            log_debug("[WS] Agent session ended normally")
        except Exception as e:
            error_msg = f"Critical Error: {str(e)}"
            log_debug(f"[WS] {error_msg}")
            log_debug(traceback.format_exc())
            await terminal._emit("system", error_msg, "error")

    # Run everything concurrently
    try:
        sender = asyncio.create_task(sender_task())
        receiver = asyncio.create_task(receiver_task())
        agent = asyncio.create_task(agent_task())
        
        done, pending = await asyncio.wait(
            [agent, receiver], 
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in pending:
            task.cancel()
        sender.cancel()
        
    except Exception as e:
        log_debug(f"[WS] Main loop error: {e}")
    finally:
        await terminal.stop()
        af_output.console.print = original_print
        log_debug("[WS] Connection closed, monkeypatch restored")
