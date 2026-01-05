import sys
import subprocess
import os
import platform

PORT = 8678

def check_dependencies():
    missing = []
    try:
        import fastapi
    except ImportError:
        missing.append("fastapi")
    
    try:
        import uvicorn
    except ImportError:
        missing.append("uvicorn")
        
    try:
        import websockets
    except ImportError:
        missing.append("websockets")

    if missing:
        print("Missing backend dependencies.")
        print(f"Please run: pip install {' '.join(missing)}")
        sys.exit(1)

if __name__ == "__main__":
    check_dependencies()
    print(f"Starting ArcadiaForge Backend on http://localhost:{PORT}")
    
    # Run uvicorn directly
    try:
        is_windows = platform.system() == "Windows"
        enable_reload = os.environ.get("ARCADIA_BACKEND_RELOAD", "1") == "1"
        if enable_reload and is_windows:
            print("Note: disabling --reload on Windows to allow agent subprocesses.")

        args = [
            sys.executable,
            "-m",
            "uvicorn",
            "arcadiaforge.web.backend.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            f"{PORT}",
        ]
        if enable_reload and not is_windows:
            args.append("--reload")

        subprocess.run(args, check=True)
    except KeyboardInterrupt:
        print("\nStopping server...")
