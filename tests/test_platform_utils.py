#!/usr/bin/env python
"""
Tests for platform_utils.py - Cross-platform OS detection and utilities.
"""

import pytest
from unittest.mock import patch, MagicMock

from arcadiaforge.platform_utils import (
    OSType,
    PlatformInfo,
    detect_os,
    get_platform_info,
    get_default_shell,
    has_git_bash,
    has_wsl,
    get_init_script_name,
    get_all_init_script_names,
    get_script_run_command,
    get_chmod_command,
    get_env_var_set_command,
    get_process_kill_command,
    get_init_script_instructions,
    get_env_var_instructions,
    get_init_script_creation_instructions,
    get_run_server_instructions,
    get_platform_summary,
)


class TestOSDetection:
    """Test OS detection functionality."""

    @patch("arcadiaforge.platform_utils.platform.system")
    def test_detect_windows(self, mock_system):
        mock_system.return_value = "Windows"
        assert detect_os() == OSType.WINDOWS

    @patch("arcadiaforge.platform_utils.platform.system")
    def test_detect_macos(self, mock_system):
        mock_system.return_value = "Darwin"
        assert detect_os() == OSType.MACOS

    @patch("arcadiaforge.platform_utils.platform.system")
    def test_detect_linux(self, mock_system):
        mock_system.return_value = "Linux"
        assert detect_os() == OSType.LINUX

    @patch("arcadiaforge.platform_utils.platform.system")
    def test_detect_unknown_defaults_to_linux(self, mock_system):
        mock_system.return_value = "FreeBSD"
        assert detect_os() == OSType.LINUX


class TestPlatformInfo:
    """Test platform info retrieval."""

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.get_default_shell")
    def test_windows_platform_info(self, mock_shell, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_shell.return_value = "powershell"

        info = get_platform_info()

        assert info.os_type == OSType.WINDOWS
        assert info.init_script_name == "init.bat"
        assert info.init_script_extension == ".bat"
        assert info.script_execute_prefix == ""
        assert info.env_set_command == "set"
        assert info.process_kill_command == "taskkill"
        assert info.path_separator == "\\"
        assert info.needs_chmod is False

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.get_default_shell")
    def test_macos_platform_info(self, mock_shell, mock_os):
        mock_os.return_value = OSType.MACOS
        mock_shell.return_value = "zsh"

        info = get_platform_info()

        assert info.os_type == OSType.MACOS
        assert info.init_script_name == "init.sh"
        assert info.init_script_extension == ".sh"
        assert info.script_execute_prefix == "./"
        assert info.env_set_command == "export"
        assert info.process_kill_command == "pkill"
        assert info.path_separator == "/"
        assert info.needs_chmod is True

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.get_default_shell")
    def test_linux_platform_info(self, mock_shell, mock_os):
        mock_os.return_value = OSType.LINUX
        mock_shell.return_value = "bash"

        info = get_platform_info()

        assert info.os_type == OSType.LINUX
        assert info.init_script_name == "init.sh"
        assert info.init_script_extension == ".sh"
        assert info.script_execute_prefix == "./"
        assert info.env_set_command == "export"
        assert info.process_kill_command == "pkill"
        assert info.path_separator == "/"
        assert info.needs_chmod is True


class TestInitScriptNames:
    """Test init script name functions."""

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_windows_init_script_name(self, mock_os):
        mock_os.return_value = OSType.WINDOWS
        assert get_init_script_name() == "init.bat"
        assert get_init_script_name(prefer_powershell=True) == "init.ps1"

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_unix_init_script_name(self, mock_os):
        mock_os.return_value = OSType.LINUX
        assert get_init_script_name() == "init.sh"
        assert get_init_script_name(prefer_powershell=True) == "init.sh"

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.has_git_bash")
    def test_windows_all_init_scripts_with_git_bash(self, mock_git_bash, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_git_bash.return_value = True

        scripts = get_all_init_script_names()
        assert "init.bat" in scripts
        assert "init.ps1" in scripts
        assert "init.sh" in scripts

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.has_git_bash")
    def test_windows_all_init_scripts_without_git_bash(self, mock_git_bash, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_git_bash.return_value = False

        scripts = get_all_init_script_names()
        assert "init.bat" in scripts
        assert "init.ps1" in scripts
        assert "init.sh" not in scripts

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_linux_all_init_scripts(self, mock_os):
        mock_os.return_value = OSType.LINUX
        scripts = get_all_init_script_names()
        assert scripts == ["init.sh"]


class TestScriptRunCommand:
    """Test script run command generation."""

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.has_git_bash")
    def test_windows_bat_script(self, mock_git_bash, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_git_bash.return_value = False

        cmd = get_script_run_command("init.bat")
        assert cmd == "init.bat"

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.has_git_bash")
    def test_windows_ps1_script(self, mock_git_bash, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_git_bash.return_value = False

        cmd = get_script_run_command("init.ps1")
        assert "powershell" in cmd.lower()
        assert "init.ps1" in cmd

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.has_git_bash")
    def test_windows_sh_script_with_git_bash(self, mock_git_bash, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_git_bash.return_value = True

        cmd = get_script_run_command("init.sh")
        assert cmd == "bash init.sh"

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_unix_sh_script(self, mock_os):
        mock_os.return_value = OSType.LINUX
        cmd = get_script_run_command("init.sh")
        assert cmd == "./init.sh"


class TestChmodCommand:
    """Test chmod command generation."""

    @patch("arcadiaforge.platform_utils.get_platform_info")
    def test_windows_no_chmod_needed(self, mock_info):
        mock_info.return_value = PlatformInfo(
            os_type=OSType.WINDOWS,
            init_script_name="init.bat",
            init_script_extension=".bat",
            script_execute_prefix="",
            env_set_command="set",
            process_kill_command="taskkill",
            path_separator="\\",
            shell_name="powershell",
            needs_chmod=False
        )

        assert get_chmod_command("init.bat") is None

    @patch("arcadiaforge.platform_utils.get_platform_info")
    def test_unix_chmod_needed(self, mock_info):
        mock_info.return_value = PlatformInfo(
            os_type=OSType.LINUX,
            init_script_name="init.sh",
            init_script_extension=".sh",
            script_execute_prefix="./",
            env_set_command="export",
            process_kill_command="pkill",
            path_separator="/",
            shell_name="bash",
            needs_chmod=True
        )

        assert get_chmod_command("init.sh") == "chmod +x init.sh"


class TestEnvVarCommand:
    """Test environment variable command generation."""

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_windows_env_var(self, mock_os):
        mock_os.return_value = OSType.WINDOWS
        cmd = get_env_var_set_command("MY_VAR", "my_value")
        assert cmd == "set MY_VAR=my_value"

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_unix_env_var(self, mock_os):
        mock_os.return_value = OSType.LINUX
        cmd = get_env_var_set_command("MY_VAR", "my_value")
        assert cmd == "export MY_VAR='my_value'"


class TestProcessKillCommand:
    """Test process kill command generation."""

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_windows_process_kill(self, mock_os):
        mock_os.return_value = OSType.WINDOWS

        # Without .exe extension
        cmd = get_process_kill_command("node")
        assert cmd == "taskkill /IM node.exe /F"

        # With .exe extension
        cmd = get_process_kill_command("node.exe")
        assert cmd == "taskkill /IM node.exe /F"

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_unix_process_kill(self, mock_os):
        mock_os.return_value = OSType.LINUX
        cmd = get_process_kill_command("node")
        assert cmd == "pkill node"


class TestInstructionGeneration:
    """Test instruction generation functions."""

    @patch("arcadiaforge.platform_utils.get_platform_info")
    @patch("arcadiaforge.platform_utils.has_git_bash")
    def test_windows_init_instructions(self, mock_git_bash, mock_info):
        mock_info.return_value = PlatformInfo(
            os_type=OSType.WINDOWS,
            init_script_name="init.bat",
            init_script_extension=".bat",
            script_execute_prefix="",
            env_set_command="set",
            process_kill_command="taskkill",
            path_separator="\\",
            shell_name="powershell",
            needs_chmod=False
        )
        mock_git_bash.return_value = True

        instructions = get_init_script_instructions()
        assert "init.bat" in instructions
        assert "powershell" in instructions.lower()
        assert "Git Bash" in instructions

    @patch("arcadiaforge.platform_utils.get_platform_info")
    def test_unix_init_instructions(self, mock_info):
        mock_info.return_value = PlatformInfo(
            os_type=OSType.LINUX,
            init_script_name="init.sh",
            init_script_extension=".sh",
            script_execute_prefix="./",
            env_set_command="export",
            process_kill_command="pkill",
            path_separator="/",
            shell_name="bash",
            needs_chmod=True
        )

        instructions = get_init_script_instructions()
        assert "chmod +x init.sh" in instructions
        assert "./init.sh" in instructions

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_windows_env_var_instructions(self, mock_os):
        mock_os.return_value = OSType.WINDOWS

        instructions = get_env_var_instructions("API_KEY", "secret")
        assert "set API_KEY=secret" in instructions
        assert "$env:API_KEY" in instructions

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.get_default_shell")
    def test_unix_env_var_instructions(self, mock_shell, mock_os):
        mock_os.return_value = OSType.LINUX
        mock_shell.return_value = "bash"

        instructions = get_env_var_instructions("API_KEY", "secret")
        assert "export API_KEY='secret'" in instructions
        assert ".bashrc" in instructions

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.get_default_shell")
    def test_macos_zsh_env_var_instructions(self, mock_shell, mock_os):
        mock_os.return_value = OSType.MACOS
        mock_shell.return_value = "zsh"

        instructions = get_env_var_instructions("API_KEY", "secret")
        assert "export API_KEY='secret'" in instructions
        assert ".zshrc" in instructions


class TestPlatformSummary:
    """Test platform summary generation."""

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.get_platform_info")
    @patch("arcadiaforge.platform_utils.has_git_bash")
    @patch("arcadiaforge.platform_utils.has_wsl")
    def test_windows_summary(self, mock_wsl, mock_git_bash, mock_info, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_info.return_value = PlatformInfo(
            os_type=OSType.WINDOWS,
            init_script_name="init.bat",
            init_script_extension=".bat",
            script_execute_prefix="",
            env_set_command="set",
            process_kill_command="taskkill",
            path_separator="\\",
            shell_name="powershell",
            needs_chmod=False
        )
        mock_git_bash.return_value = True
        mock_wsl.return_value = True

        summary = get_platform_summary()
        assert "Windows" in summary
        assert "powershell" in summary
        assert "init.bat" in summary
        assert "taskkill" in summary
        assert "Git Bash available: True" in summary
        assert "WSL available: True" in summary

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.get_platform_info")
    def test_linux_summary(self, mock_info, mock_os):
        mock_os.return_value = OSType.LINUX
        mock_info.return_value = PlatformInfo(
            os_type=OSType.LINUX,
            init_script_name="init.sh",
            init_script_extension=".sh",
            script_execute_prefix="./",
            env_set_command="export",
            process_kill_command="pkill",
            path_separator="/",
            shell_name="bash",
            needs_chmod=True
        )

        summary = get_platform_summary()
        assert "Linux" in summary
        assert "bash" in summary
        assert "init.sh" in summary
        assert "pkill" in summary
        # No Git Bash or WSL lines for non-Windows
        assert "Git Bash" not in summary


class TestDefaultShell:
    """Test default shell detection."""

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.shutil.which")
    def test_windows_powershell(self, mock_which, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_which.return_value = "C:\\Windows\\System32\\powershell.exe"

        shell = get_default_shell()
        assert shell == "powershell"

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.shutil.which")
    def test_windows_cmd_fallback(self, mock_which, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_which.return_value = None

        shell = get_default_shell()
        assert shell == "cmd"

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.os.environ.get")
    def test_macos_zsh_default(self, mock_env, mock_os):
        mock_os.return_value = OSType.MACOS
        mock_env.return_value = "/bin/zsh"

        shell = get_default_shell()
        assert shell == "zsh"

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.os.environ.get")
    def test_linux_bash_default(self, mock_env, mock_os):
        mock_os.return_value = OSType.LINUX
        mock_env.return_value = "/bin/bash"

        shell = get_default_shell()
        assert shell == "bash"


class TestGitBashDetection:
    """Test Git Bash detection on Windows."""

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_non_windows_no_git_bash(self, mock_os):
        mock_os.return_value = OSType.LINUX
        assert has_git_bash() is False

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.os.path.exists")
    @patch("arcadiaforge.platform_utils.shutil.which")
    def test_windows_git_bash_in_path(self, mock_which, mock_exists, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_exists.return_value = False
        mock_which.return_value = "C:\\Program Files\\Git\\bin\\bash.exe"

        assert has_git_bash() is True

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.os.path.exists")
    @patch("arcadiaforge.platform_utils.shutil.which")
    def test_windows_git_bash_standard_location(self, mock_which, mock_exists, mock_os):
        mock_os.return_value = OSType.WINDOWS

        def exists_side_effect(path):
            return path == r"C:\Program Files\Git\bin\bash.exe"

        mock_exists.side_effect = exists_side_effect
        mock_which.return_value = None

        assert has_git_bash() is True


class TestWSLDetection:
    """Test WSL detection on Windows."""

    @patch("arcadiaforge.platform_utils.detect_os")
    def test_non_windows_no_wsl(self, mock_os):
        mock_os.return_value = OSType.LINUX
        assert has_wsl() is False

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.shutil.which")
    def test_windows_wsl_available(self, mock_which, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_which.return_value = "C:\\Windows\\System32\\wsl.exe"

        assert has_wsl() is True

    @patch("arcadiaforge.platform_utils.detect_os")
    @patch("arcadiaforge.platform_utils.shutil.which")
    def test_windows_wsl_not_available(self, mock_which, mock_os):
        mock_os.return_value = OSType.WINDOWS
        mock_which.return_value = None

        assert has_wsl() is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])