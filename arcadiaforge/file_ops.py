"""
Platform-Agnostic File Operations
=================================

Cross-platform file operations wrapper for the coding agent.
Replaces Unix-specific commands (cp, xargs, tee) that fail on Windows.
"""

import shutil
import os
from pathlib import Path
from typing import List, Optional
import glob as glob_module


class FileOps:
    """Cross-platform file operations wrapper."""

    @staticmethod
    def copy(src: str, dest: str) -> dict:
        """
        Copy file or directory from src to dest.
        Works identically on Windows, macOS, and Linux.

        Args:
            src: Source path (file or directory)
            dest: Destination path

        Returns:
            Dict with success status and message or error
        """
        try:
            src_path = Path(src)
            dest_path = Path(dest)

            if not src_path.exists():
                return {"success": False, "error": f"Source does not exist: {src}"}

            # Create destination directory if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if src_path.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
                return {"success": True, "message": f"Copied directory {src} to {dest}"}
            else:
                shutil.copy2(src, dest)
                return {"success": True, "message": f"Copied file {src} to {dest}"}

        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def move(src: str, dest: str) -> dict:
        """
        Move file or directory from src to dest.
        Works identically on Windows, macOS, and Linux.

        Args:
            src: Source path
            dest: Destination path

        Returns:
            Dict with success status and message or error
        """
        try:
            src_path = Path(src)

            if not src_path.exists():
                return {"success": False, "error": f"Source does not exist: {src}"}

            # Create destination directory if needed
            Path(dest).parent.mkdir(parents=True, exist_ok=True)

            shutil.move(src, dest)
            return {"success": True, "message": f"Moved {src} to {dest}"}

        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def delete(path: str, recursive: bool = False) -> dict:
        """
        Delete file or directory.
        Works identically on Windows, macOS, and Linux.

        Args:
            path: Path to delete
            recursive: If True, delete directories recursively

        Returns:
            Dict with success status and message or error
        """
        try:
            p = Path(path)

            if not p.exists():
                return {"success": False, "error": f"Path does not exist: {path}"}

            if p.is_dir():
                if recursive:
                    shutil.rmtree(path)
                else:
                    p.rmdir()
            else:
                p.unlink()

            return {"success": True, "message": f"Deleted {path}"}

        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {e}"}
        except OSError as e:
            if "Directory not empty" in str(e):
                return {"success": False, "error": f"Directory not empty. Use recursive=True to delete non-empty directories."}
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def list_dir(path: str, pattern: str = "*") -> dict:
        """
        List directory contents with optional glob pattern.
        Works identically on Windows, macOS, and Linux.

        Args:
            path: Directory to list
            pattern: Glob pattern to filter results (default: "*")

        Returns:
            Dict with items list and count, or error
        """
        try:
            p = Path(path)

            if not p.exists():
                return {"success": False, "error": f"Path does not exist: {path}"}

            if not p.is_dir():
                return {"success": False, "error": f"Path is not a directory: {path}"}

            if pattern == "*":
                items = list(p.iterdir())
            else:
                items = list(p.glob(pattern))

            return {
                "success": True,
                "items": [str(item) for item in sorted(items)],
                "count": len(items)
            }

        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def latest_file(directory: str, pattern: str = "*.png") -> dict:
        """
        Get the most recently modified file matching pattern.
        Replaces Unix 'ls -t | head -1' pattern.

        Args:
            directory: Directory to search
            pattern: Glob pattern to match (default: "*.png")

        Returns:
            Dict with path to latest file, or error
        """
        try:
            p = Path(directory)

            if not p.exists():
                return {"success": False, "error": f"Directory does not exist: {directory}"}

            if not p.is_dir():
                return {"success": False, "error": f"Path is not a directory: {directory}"}

            files = list(p.glob(pattern))

            if not files:
                return {"success": False, "error": f"No files matching '{pattern}' found in {directory}"}

            latest = max(files, key=lambda x: x.stat().st_mtime)

            return {
                "success": True,
                "path": str(latest),
                "filename": latest.name,
                "modified": latest.stat().st_mtime
            }

        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def ensure_dir(path: str) -> dict:
        """
        Ensure directory exists, create if needed.
        Replaces Unix 'mkdir -p' command.

        Args:
            path: Directory path to ensure exists

        Returns:
            Dict with success status and message
        """
        try:
            p = Path(path)
            p.mkdir(parents=True, exist_ok=True)

            return {
                "success": True,
                "message": f"Directory ready: {path}",
                "created": not p.existed() if hasattr(p, 'existed') else True
            }

        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def read_text(path: str, encoding: str = "utf-8") -> dict:
        """
        Read text file contents.
        Replaces Unix 'cat' command for simple reads.

        Args:
            path: File path to read
            encoding: Text encoding (default: utf-8)

        Returns:
            Dict with file content or error
        """
        try:
            p = Path(path)

            if not p.exists():
                return {"success": False, "error": f"File does not exist: {path}"}

            if p.is_dir():
                return {"success": False, "error": f"Path is a directory, not a file: {path}"}

            content = p.read_text(encoding=encoding)

            return {
                "success": True,
                "content": content,
                "size": len(content),
                "lines": content.count('\n') + 1
            }

        except UnicodeDecodeError as e:
            return {"success": False, "error": f"Could not decode file as {encoding}: {e}"}
        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def write_text(path: str, content: str, encoding: str = "utf-8", append: bool = False) -> dict:
        """
        Write text to file.
        Replaces Unix 'tee' command.

        Args:
            path: File path to write
            content: Text content to write
            encoding: Text encoding (default: utf-8)
            append: If True, append to file instead of overwriting

        Returns:
            Dict with success status and message
        """
        try:
            p = Path(path)

            # Create parent directories if needed
            p.parent.mkdir(parents=True, exist_ok=True)

            mode = 'a' if append else 'w'
            with open(p, mode, encoding=encoding) as f:
                f.write(content)

            return {
                "success": True,
                "message": f"{'Appended to' if append else 'Wrote'} {path}",
                "size": len(content)
            }

        except PermissionError as e:
            return {"success": False, "error": f"Permission denied: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def exists(path: str) -> dict:
        """
        Check if path exists.
        Replaces Unix 'test -e' command.

        Args:
            path: Path to check

        Returns:
            Dict with exists status and type info
        """
        p = Path(path)

        if p.exists():
            return {
                "success": True,
                "exists": True,
                "is_file": p.is_file(),
                "is_dir": p.is_dir(),
                "path": str(p.resolve())
            }
        else:
            return {
                "success": True,
                "exists": False,
                "path": path
            }

    @staticmethod
    def glob_files(pattern: str, root: str = ".") -> dict:
        """
        Find files matching glob pattern.
        Replaces Unix 'find' with glob patterns.

        Args:
            pattern: Glob pattern (e.g., "**/*.py")
            root: Root directory to search from

        Returns:
            Dict with matching file paths
        """
        try:
            root_path = Path(root)

            if not root_path.exists():
                return {"success": False, "error": f"Root directory does not exist: {root}"}

            matches = list(root_path.glob(pattern))

            return {
                "success": True,
                "files": [str(m) for m in sorted(matches)],
                "count": len(matches)
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
