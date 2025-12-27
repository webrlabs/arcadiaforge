"""
Prompt Loading Utilities
========================

Functions for loading prompt templates from the prompts package.
Supports cross-platform operation with dynamic placeholder substitution.
"""

import importlib
from importlib import resources
import shutil
from pathlib import Path

PROMPTS_PACKAGE = "arcadiaforge.prompts"


def _load_platform_instructions():
    """
    Load the platform_instructions module directly from the prompts package.
    """
    return importlib.import_module(f"{PROMPTS_PACKAGE}.platform_instructions")


# Load the module at import time
_platform_instructions = _load_platform_instructions()


def _get_prompt_path(name: str):
    return resources.files(PROMPTS_PACKAGE) / f"{name}.md"


def load_prompt(name: str, apply_substitutions: bool = True) -> str:
    """
    Load a prompt template from the prompts package.

    Args:
        name: Name of the prompt file (without .md extension)
        apply_substitutions: Whether to apply platform-specific substitutions

    Returns:
        Prompt text with optional platform-specific substitutions applied
    """
    prompt_path = _get_prompt_path(name)
    prompt = prompt_path.read_text(encoding="utf-8")

    if apply_substitutions:
        substitutions = _platform_instructions.get_all_substitutions()
        for placeholder, value in substitutions.items():
            prompt = prompt.replace(placeholder, value)

    return prompt


def get_initializer_prompt() -> str:
    """Load the initializer prompt with platform-specific substitutions."""
    return load_prompt("initializer_prompt")


def get_coding_prompt() -> str:
    """Load the coding agent prompt with platform-specific substitutions."""
    return load_prompt("coding_prompt")


def get_update_features_prompt() -> str:
    """Load the update features prompt with platform-specific substitutions."""
    return load_prompt("update_features_prompt")


def get_audit_prompt(candidates: list[int], regressions: list[int]) -> str:
    """Load the audit prompt and inject candidate indices."""
    prompt = load_prompt("audit_prompt")
    candidates_text = ", ".join(str(i) for i in candidates) if candidates else "none"
    regressions_text = ", ".join(str(i) for i in regressions) if regressions else "none"
    prompt = prompt.replace("{{AUDIT_CANDIDATES}}", candidates_text)
    prompt = prompt.replace("{{AUDIT_REGRESSIONS}}", regressions_text)
    return prompt


def copy_spec_to_project(project_dir: Path, custom_spec_path: Path = None) -> None:
    """Copy the app spec file into the project directory for the agent to read.

    Args:
        project_dir: Target project directory
        custom_spec_path: Optional path to a custom spec file. If None, uses default.
    """
    spec_dest = project_dir / "app_spec.txt"
    if spec_dest.exists():
        return

    if custom_spec_path:
        shutil.copy(custom_spec_path, spec_dest)
        print(f"Copied {custom_spec_path.name} to project directory")
        return

    spec_source = resources.files(PROMPTS_PACKAGE) / "app_spec.txt"
    with resources.as_file(spec_source) as spec_path:
        shutil.copy(spec_path, spec_dest)
        print("Copied app_spec.txt to project directory")


def copy_new_requirements_to_project(source_path: Path, project_dir: Path) -> None:
    """Copy a new requirements file into the project directory."""
    dest = project_dir / "new_requirements.txt"
    shutil.copy(source_path, dest)
    print(f"Copied {source_path} to {dest}")


def copy_feature_tool_to_project(project_dir: Path) -> None:
    """Copy the feature_tool.py utility to the project directory.

    This tool allows agents to efficiently query the feature database.
    """
    source = resources.files(PROMPTS_PACKAGE) / "feature_tool.py"
    dest = project_dir / "feature_tool.py"

    if source.is_file():
        with resources.as_file(source) as source_path:
            shutil.copy(source_path, dest)