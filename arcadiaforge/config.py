"""
Configuration Management
========================

Handles loading configuration from environment variables and config files.
"""

import os
import json
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass

# Default configuration values
DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
CONFIG_FILENAME = "arcadia_config.json"


@dataclass
class ArcadiaConfig:
    """Arcadia Forge Configuration."""
    default_model: str
    
    @classmethod
    def load(cls) -> "ArcadiaConfig":
        """
        Load configuration from multiple sources in precedence order:
        1. Environment variables
        2. Local config file (arcadia_config.json)
        3. Default values
        """
        # Start with defaults
        config = {
            "default_model": DEFAULT_MODEL
        }
        
        # Load from config file if exists
        config_path = Path(CONFIG_FILENAME)
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    file_config = json.load(f)
                    config.update(file_config)
            except Exception as e:
                print(f"Warning: Failed to load config file: {e}")
        
        # Override with environment variables
        env_model = os.environ.get("ARCADIA_MODEL")
        if env_model:
            config["default_model"] = env_model
            
        return cls(
            default_model=config["default_model"]
        )

@dataclass
class BudgetConfig:
    """Configuration for cost control."""
    max_budget_usd: float = 10.0
    warning_threshold: float = 0.8
    currency: str = "USD"
    
    # Cost per 1k tokens (defaults to Sonnet 3.5 pricing approx)
    input_cost_per_1k: float = 0.003
    output_cost_per_1k: float = 0.015

    @classmethod
    def from_env(cls) -> "BudgetConfig":
        """Load budget settings from environment variables."""
        return cls(
            max_budget_usd=float(os.environ.get("ARCADIA_MAX_BUDGET", "10.0")),
            input_cost_per_1k=float(os.environ.get("ARCADIA_INPUT_COST", "0.003")),
            output_cost_per_1k=float(os.environ.get("ARCADIA_OUTPUT_COST", "0.015")),
        )

def get_default_model() -> str:
    """Get the default model from configuration."""
    return ArcadiaConfig.load().default_model
