import asyncio
import traceback
import sys
import os
import subprocess
from pathlib import Path
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import multiprocessing as mp

from arcadiaforge.config import get_default_model
from arcadiaforge.web.backend.agent_worker import run_agent_worker

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

    # Note: We do NOT monkey-patch console.print anymore
    # CLI output goes to server console, clean events go to WebTerminal via agent.py hooks

    ctx = mp.get_context("spawn")
    input_queue = ctx.Queue()
    output_queue = ctx.Queue()
    model = get_default_model()
    worker = ctx.Process(
        target=run_agent_worker,
        args=(str(project_dir), model, input_queue, output_queue),
    )

    try:
        log_debug(f"[WS] Starting worker for {project_dir}")
        worker.start()
        log_debug(f"[WS] Worker started (pid={worker.pid})")
    except Exception as e:
        log_debug(f"[WS] Error starting worker: {e}")
        log_debug(traceback.format_exc())
        await websocket.close(code=1011, reason=f"Init error: {str(e)}")
        return

    # Task to pump events from Terminal -> WebSocket
    async def sender_task():
        try:
            while True:
                event = await asyncio.to_thread(output_queue.get)
                if event is None:
                    break
                await websocket.send_json(event)
        except Exception as e:
            log_debug(f"[WS] Sender task error: {e}")

    # Task to pump messages from WebSocket -> Terminal
    async def receiver_task():
        try:
            while True:
                data = await websocket.receive_text()
                input_queue.put(data)
        except WebSocketDisconnect:
            log_debug("[WS] Client disconnected")
        except Exception as e:
            log_debug(f"[WS] Receiver task error: {e}")
        finally:
            input_queue.put({"type": "shutdown"})

    async def monitor_task():
        try:
            await asyncio.to_thread(worker.join)
            log_debug("[WS] Worker exited")
        except Exception as e:
            log_debug(f"[WS] Worker join error: {e}")
        finally:
            output_queue.put(None)

    # Run everything concurrently
    try:
        sender = asyncio.create_task(sender_task())
        receiver = asyncio.create_task(receiver_task())
        monitor = asyncio.create_task(monitor_task())
        
        done, pending = await asyncio.wait(
            [monitor, receiver], 
            return_when=asyncio.FIRST_COMPLETED
        )
        
        for task in pending:
            task.cancel()
        sender.cancel()
        
    except Exception as e:
        log_debug(f"[WS] Main loop error: {e}")
    finally:
        input_queue.put({"type": "shutdown"})
        try:
            await asyncio.to_thread(worker.join, 3)
        except Exception:
            pass
        if worker.is_alive():
            worker.terminate()
            try:
                await asyncio.to_thread(worker.join, 2)
            except Exception:
                pass
        log_debug("[WS] Connection closed")
