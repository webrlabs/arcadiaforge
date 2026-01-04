import os
import sys
import subprocess
import platform
import time
import webbrowser

from dotenv import load_dotenv


def main():
    load_dotenv()

    # Get paths
    root_dir = os.path.dirname(os.path.abspath(__file__))
    frontend_dir = os.path.join(root_dir, "arcadiaforge", "web", "frontend")

    is_windows = platform.system() == "Windows"
    npm_cmd = "npm.cmd" if is_windows else "npm"

    print("[*] Starting ArcadiaForge Web Interface...")

    # 1. Start Backend
    print("    - Launching Backend (FastAPI)...")
    try:
        if is_windows:
            # Opens in a new separate command window
            subprocess.Popen(
                [sys.executable, "run_backend.py"],
                cwd=root_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            # On Mac/Linux, this might run in background or need explicit terminal command
            # For now, we assume this is running in a way that handles background tasks or use standard Popen
            subprocess.Popen(
                [sys.executable, "run_backend.py"],
                cwd=root_dir
            )
    except Exception as e:
        print(f"    ! Failed to start backend: {e}")
        return

    # 2. Start Frontend
    print("    - Launching Frontend (Vite)...")
    try:
        if is_windows:
            # Opens in a new separate command window
            subprocess.Popen(
                [npm_cmd, "run", "dev"],
                cwd=frontend_dir,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
        else:
            subprocess.Popen(
                [npm_cmd, "run", "dev"],
                cwd=frontend_dir
            )
    except Exception as e:
        print(f"    ! Failed to start frontend: {e}")
        return

    print("\n[*] Servers launched!")
    print("    Backend: http://localhost:8000/docs")
    print("    Frontend: http://localhost:5173")

    print("\nOpening browser in 3 seconds...")
    time.sleep(3)
    webbrowser.open("http://localhost:5173")


if __name__ == "__main__":
    main()
