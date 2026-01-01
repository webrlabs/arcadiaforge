"""
Tests for Cross-Platform File Operations
========================================

Tests for arcadiaforge/file_ops.py and arcadiaforge/file_tools.py
"""

import pytest
import time
from pathlib import Path

from arcadiaforge.file_ops import FileOps


class TestFileOpsCopy:
    """Tests for FileOps.copy()"""

    def test_copy_file(self, tmp_path):
        """Test copying a single file."""
        src = tmp_path / "source.txt"
        src.write_text("test content")
        dest = tmp_path / "dest.txt"

        result = FileOps.copy(str(src), str(dest))

        assert result["success"]
        assert dest.exists()
        assert dest.read_text() == "test content"

    def test_copy_file_creates_parent_dirs(self, tmp_path):
        """Test that copy creates parent directories if needed."""
        src = tmp_path / "source.txt"
        src.write_text("test content")
        dest = tmp_path / "nested" / "deep" / "dest.txt"

        result = FileOps.copy(str(src), str(dest))

        assert result["success"]
        assert dest.exists()
        assert dest.read_text() == "test content"

    def test_copy_directory(self, tmp_path):
        """Test copying a directory recursively."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "file1.txt").write_text("content1")
        (src_dir / "subdir").mkdir()
        (src_dir / "subdir" / "file2.txt").write_text("content2")
        dest_dir = tmp_path / "dest"

        result = FileOps.copy(str(src_dir), str(dest_dir))

        assert result["success"]
        assert (dest_dir / "file1.txt").exists()
        assert (dest_dir / "subdir" / "file2.txt").exists()
        assert (dest_dir / "file1.txt").read_text() == "content1"

    def test_copy_nonexistent_source(self, tmp_path):
        """Test copying from nonexistent source fails gracefully."""
        src = tmp_path / "nonexistent.txt"
        dest = tmp_path / "dest.txt"

        result = FileOps.copy(str(src), str(dest))

        assert not result["success"]
        assert "does not exist" in result["error"]


class TestFileOpsMove:
    """Tests for FileOps.move()"""

    def test_move_file(self, tmp_path):
        """Test moving a file."""
        src = tmp_path / "source.txt"
        src.write_text("test content")
        dest = tmp_path / "dest.txt"

        result = FileOps.move(str(src), str(dest))

        assert result["success"]
        assert dest.exists()
        assert not src.exists()
        assert dest.read_text() == "test content"

    def test_move_creates_parent_dirs(self, tmp_path):
        """Test that move creates parent directories if needed."""
        src = tmp_path / "source.txt"
        src.write_text("test content")
        dest = tmp_path / "nested" / "dest.txt"

        result = FileOps.move(str(src), str(dest))

        assert result["success"]
        assert dest.exists()

    def test_move_nonexistent_source(self, tmp_path):
        """Test moving nonexistent source fails gracefully."""
        src = tmp_path / "nonexistent.txt"
        dest = tmp_path / "dest.txt"

        result = FileOps.move(str(src), str(dest))

        assert not result["success"]
        assert "does not exist" in result["error"]


class TestFileOpsDelete:
    """Tests for FileOps.delete()"""

    def test_delete_file(self, tmp_path):
        """Test deleting a file."""
        f = tmp_path / "delete_me.txt"
        f.write_text("bye")

        result = FileOps.delete(str(f))

        assert result["success"]
        assert not f.exists()

    def test_delete_empty_directory(self, tmp_path):
        """Test deleting an empty directory."""
        d = tmp_path / "empty_dir"
        d.mkdir()

        result = FileOps.delete(str(d))

        assert result["success"]
        assert not d.exists()

    def test_delete_nonempty_directory_requires_recursive(self, tmp_path):
        """Test that non-empty directory requires recursive flag."""
        d = tmp_path / "dir"
        d.mkdir()
        (d / "file.txt").write_text("content")

        result = FileOps.delete(str(d))

        assert not result["success"]
        assert "recursive" in result["error"].lower()

    def test_delete_directory_recursive(self, tmp_path):
        """Test deleting a directory recursively."""
        d = tmp_path / "dir"
        d.mkdir()
        (d / "file.txt").write_text("content")
        (d / "subdir").mkdir()
        (d / "subdir" / "file2.txt").write_text("content2")

        result = FileOps.delete(str(d), recursive=True)

        assert result["success"]
        assert not d.exists()

    def test_delete_nonexistent(self, tmp_path):
        """Test deleting nonexistent path fails gracefully."""
        f = tmp_path / "nonexistent.txt"

        result = FileOps.delete(str(f))

        assert not result["success"]
        assert "does not exist" in result["error"]


class TestFileOpsLatestFile:
    """Tests for FileOps.latest_file()"""

    def test_latest_file(self, tmp_path):
        """Test finding the most recently modified file."""
        # Create files with different modification times
        old = tmp_path / "old.png"
        old.write_bytes(b"old")

        time.sleep(0.1)  # Ensure different mtime

        new = tmp_path / "new.png"
        new.write_bytes(b"new")

        result = FileOps.latest_file(str(tmp_path), "*.png")

        assert result["success"]
        assert "new.png" in result["path"]
        assert result["filename"] == "new.png"

    def test_latest_file_no_matches(self, tmp_path):
        """Test when no files match the pattern."""
        (tmp_path / "file.txt").write_text("content")

        result = FileOps.latest_file(str(tmp_path), "*.png")

        assert not result["success"]
        assert "No files matching" in result["error"]

    def test_latest_file_nonexistent_directory(self, tmp_path):
        """Test with nonexistent directory."""
        result = FileOps.latest_file(str(tmp_path / "nonexistent"), "*.png")

        assert not result["success"]
        assert "does not exist" in result["error"]


class TestFileOpsEnsureDir:
    """Tests for FileOps.ensure_dir()"""

    def test_ensure_dir_creates_directory(self, tmp_path):
        """Test creating a new directory."""
        d = tmp_path / "new_dir"

        result = FileOps.ensure_dir(str(d))

        assert result["success"]
        assert d.exists()
        assert d.is_dir()

    def test_ensure_dir_creates_nested(self, tmp_path):
        """Test creating nested directories."""
        d = tmp_path / "a" / "b" / "c"

        result = FileOps.ensure_dir(str(d))

        assert result["success"]
        assert d.exists()

    def test_ensure_dir_existing_directory(self, tmp_path):
        """Test with already existing directory."""
        d = tmp_path / "existing"
        d.mkdir()

        result = FileOps.ensure_dir(str(d))

        assert result["success"]


class TestFileOpsExists:
    """Tests for FileOps.exists()"""

    def test_exists_file(self, tmp_path):
        """Test checking existence of a file."""
        f = tmp_path / "file.txt"
        f.write_text("content")

        result = FileOps.exists(str(f))

        assert result["success"]
        assert result["exists"]
        assert result["is_file"]
        assert not result["is_dir"]

    def test_exists_directory(self, tmp_path):
        """Test checking existence of a directory."""
        d = tmp_path / "dir"
        d.mkdir()

        result = FileOps.exists(str(d))

        assert result["success"]
        assert result["exists"]
        assert result["is_dir"]
        assert not result["is_file"]

    def test_exists_nonexistent(self, tmp_path):
        """Test checking nonexistent path."""
        f = tmp_path / "nonexistent.txt"

        result = FileOps.exists(str(f))

        assert result["success"]  # The check itself succeeded
        assert not result["exists"]


class TestFileOpsListDir:
    """Tests for FileOps.list_dir()"""

    def test_list_dir(self, tmp_path):
        """Test listing directory contents."""
        (tmp_path / "file1.txt").write_text("1")
        (tmp_path / "file2.txt").write_text("2")
        (tmp_path / "subdir").mkdir()

        result = FileOps.list_dir(str(tmp_path))

        assert result["success"]
        assert result["count"] == 3
        assert len(result["items"]) == 3

    def test_list_dir_with_pattern(self, tmp_path):
        """Test listing with glob pattern."""
        (tmp_path / "file1.txt").write_text("1")
        (tmp_path / "file2.py").write_text("2")
        (tmp_path / "file3.txt").write_text("3")

        result = FileOps.list_dir(str(tmp_path), "*.txt")

        assert result["success"]
        assert result["count"] == 2

    def test_list_dir_nonexistent(self, tmp_path):
        """Test listing nonexistent directory."""
        result = FileOps.list_dir(str(tmp_path / "nonexistent"))

        assert not result["success"]
        assert "does not exist" in result["error"]


class TestFileOpsGlob:
    """Tests for FileOps.glob_files()"""

    def test_glob_recursive(self, tmp_path):
        """Test recursive glob pattern."""
        (tmp_path / "file.py").write_text("1")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.py").write_text("2")

        result = FileOps.glob_files("**/*.py", str(tmp_path))

        assert result["success"]
        assert result["count"] == 2

    def test_glob_no_matches(self, tmp_path):
        """Test glob with no matches."""
        (tmp_path / "file.txt").write_text("1")

        result = FileOps.glob_files("*.py", str(tmp_path))

        assert result["success"]
        assert result["count"] == 0
        assert result["files"] == []


class TestFileOpsReadWrite:
    """Tests for FileOps.read_text() and write_text()"""

    def test_write_and_read(self, tmp_path):
        """Test writing and reading text file."""
        f = tmp_path / "test.txt"

        write_result = FileOps.write_text(str(f), "Hello, World!")
        assert write_result["success"]

        read_result = FileOps.read_text(str(f))
        assert read_result["success"]
        assert read_result["content"] == "Hello, World!"

    def test_write_append(self, tmp_path):
        """Test appending to a file."""
        f = tmp_path / "test.txt"
        f.write_text("Line 1\n")

        result = FileOps.write_text(str(f), "Line 2\n", append=True)

        assert result["success"]
        assert f.read_text() == "Line 1\nLine 2\n"

    def test_write_creates_parent_dirs(self, tmp_path):
        """Test that write creates parent directories."""
        f = tmp_path / "nested" / "deep" / "file.txt"

        result = FileOps.write_text(str(f), "content")

        assert result["success"]
        assert f.read_text() == "content"

    def test_read_nonexistent(self, tmp_path):
        """Test reading nonexistent file."""
        result = FileOps.read_text(str(tmp_path / "nonexistent.txt"))

        assert not result["success"]
        assert "does not exist" in result["error"]
