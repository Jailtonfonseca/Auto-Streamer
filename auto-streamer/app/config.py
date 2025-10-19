"""
Handles loading, validation, and access to the application configuration.

This module reads a JSON configuration file, validates it against a JSON schema,
and allows overriding specific values with environment variables.
"""
import json
import logging
import os
import shutil
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from jsonschema import validate
from jsonschema.exceptions import ValidationError

# Set up a logger for this module
logger = logging.getLogger(__name__)

# Define the base path for the application
# Assumes config.py is in auto-streamer/app/
APP_DIR = Path(__file__).parent.resolve()
ROOT_DIR = APP_DIR.parent

class ConfigError(Exception):
    """Custom exception for configuration errors."""
    pass

class Config:
    """A class to manage application configuration."""

    def __init__(self, config_path: Path, schema_path: Path):
        """
        Initializes the Config object.

        Args:
            config_path: Path to the configuration JSON file.
            schema_path: Path to the configuration JSON schema.
        """
        self._config_path = config_path
        self._schema_path = schema_path
        self._settings: Dict[str, Any] = {}
        self._lock = Lock()
        self._schema: Dict[str, Any] = self._load_json(self._schema_path)

    def load(self) -> None:
        """
        Loads, validates, and processes the configuration.
        """
        logger.info(f"Loading configuration from: {self._config_path}")
        if not self._config_path.exists():
            raise ConfigError(
                f"Configuration file not found at {self._config_path}. "
                f"Please create one, for example by copying 'app/config.json.example'."
            )

        config_data = self._load_json(self._config_path)
        self._validate(config_data)
        self._settings = config_data
        self._override_from_env()
        logger.info("Configuration loaded and validated successfully.")

    def _load_json(self, path: Path) -> Dict[str, Any]:
        """Loads a JSON file and returns its content."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            raise ConfigError(f"File not found: {path}")
        except json.JSONDecodeError as e:
            raise ConfigError(f"Error decoding JSON from {path}: {e}")

    def _validate(self, data: Dict[str, Any]) -> None:
        """Validates the configuration data against the schema."""
        try:
            validate(instance=data, schema=self._schema)
        except ValidationError as e:
            raise ConfigError(f"Configuration validation error: {e.message} in '{'.'.join(map(str, e.path))}'")

    def _override_from_env(self) -> None:
        """Overrides configuration settings with values from environment variables."""
        # Mapping of environment variables to config keys (path in dict)
        env_overrides = {
            "RTMP_URL": ("stream", "rtmp_url"),
            "STREAM_KEY": ("stream", "stream_key"),
            "OPENAI_API_KEY": ("tts", "api_key"), # Note: schema expects api_key_env, we are setting a value directly
            "OPENAI_BASE_URL": ("tts", "base_url"),
            "ADMIN_PASS_HASH": ("security", "admin_pass_hash"), # Assumes security section exists
            "UI_PORT": ("ui", "port"),
        }

        logger.info("Checking for environment variable overrides...")
        for env_var, keys in env_overrides.items():
            value = os.getenv(env_var)
            if value:
                logger.info(f"Overriding setting '{'.'.join(keys)}' with value from env var '{env_var}'.")
                # Navigate the nested dictionary to set the value
                d = self._settings
                for key in keys[:-1]:
                    d = d.setdefault(key, {})

                # Try to cast to the correct type if possible
                original_value = d.get(keys[-1])
                if original_value is not None:
                    try:
                        value = type(original_value)(value)
                    except (ValueError, TypeError):
                        logger.warning(
                            f"Could not cast env var {env_var} value to type {type(original_value)}. Using as string."
                        )

                d[keys[-1]] = value

        # Special handling for OpenAI API key from its env var
        api_key_env_name = self._settings.get("tts", {}).get("api_key_env")
        if api_key_env_name and os.getenv(api_key_env_name):
             self._settings["tts"]["api_key"] = os.getenv(api_key_env_name)

        base_url_env_name = self._settings.get("tts", {}).get("base_url_env")
        if base_url_env_name and os.getenv(base_url_env_name):
             self._settings["tts"]["base_url"] = os.getenv(base_url_env_name)


    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieves a configuration value.

        Args:
            key: The top-level configuration key.
            default: The value to return if the key is not found.

        Returns:
            The configuration value or the default.
        """
        return self._settings.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Allows dictionary-style access to top-level keys."""
        return self._settings[key]

    @property
    def all_settings(self) -> Dict[str, Any]:
        """Returns a copy of all settings."""
        return self._settings.copy()

    def save(self, new_settings: Dict[str, Any]) -> None:
        """
        Saves the updated configuration to the file.
        This method is thread-safe.
        """
        with self._lock:
            # Create a backup of the current config file
            if self._config_path.exists():
                backup_path = self._config_path.with_suffix(".json.bak")
                try:
                    shutil.copy2(self._config_path, backup_path)
                    logger.info(f"Created configuration backup at {backup_path}")
                except IOError as e:
                    logger.warning(f"Failed to create configuration backup: {e}")

            try:
                # Merge the new settings into the current settings
                # We do this to preserve any settings not exposed in the UI
                for key, value in new_settings.items():
                    if value is not None and value != "":
                        # This is a simple merge. For nested dicts, a deep merge would be needed.
                        # For now, we are only updating top-level keys in nested dicts.
                        if key == "rtmp_url":
                            self._settings["stream"]["rtmp_url"] = value
                        elif key == "stream_key":
                            self._settings["stream"]["stream_key"] = value
                        elif key == "openai_api_key":
                            self._settings["tts"]["api_key"] = value
                        elif key == "admin_pass_hash":
                            # This key might not exist, so we add it under a 'security' section
                            self._settings.setdefault("security", {})["admin_pass_hash"] = value

                # Validate before saving
                self._validate(self._settings)

                # Write the updated settings to the config file
                with open(self._config_path, "w", encoding="utf-8") as f:
                    json.dump(self._settings, f, indent=2)

                logger.info(f"Configuration saved successfully to {self._config_path}")

            except ValidationError as e:
                logger.error(f"Validation failed while saving new configuration: {e}")
                # Optionally, restore from backup here
                raise ConfigError(f"New configuration is invalid: {e.message}")
            except Exception as e:
                logger.exception("An unexpected error occurred while saving the configuration.")
                raise ConfigError(f"Could not save configuration file: {e}")

# --- Singleton Instance ---
# This part creates a single, globally accessible configuration object.

DEFAULT_CONFIG_PATH = ROOT_DIR / "config.json"
DEFAULT_SCHEMA_PATH = ROOT_DIR / "config.schema.json"

try:
    # Initialize the global config object
    app_config = Config(config_path=DEFAULT_CONFIG_PATH, schema_path=DEFAULT_SCHEMA_PATH)
    # Attempt to load it. In a real app, this might be delayed until a main() function.
    # For simplicity, we can try it here but catch the error.
    # app_config.load()
except Exception as e:
    # If initialization fails, log the error. The app should not start.
    logger.critical(f"Failed to initialize configuration: {e}")
    # You might want to provide a dummy config or exit, depending on app structure.
    app_config = None # type: ignore

# The main way to use the config in other modules is:
# from app.config import app_config
#
# if app_config:
#     port = app_config.get("ui", {}).get("port")
