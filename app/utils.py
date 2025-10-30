"""
Provides utility functions for logging, subprocess execution, and other helpers.

This module centralizes common functionalities like:
- Setting up structured logging for the entire application.
- A robust wrapper for running external commands, especially FFmpeg.
- Path management for project directories.
- Retry mechanisms for network-dependent operations.
- SSE (Server-Sent Events) message formatting.
"""
import logging
import logging.handlers
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

# --- Path Management ---
import os

# Use /data for all persistent data, configurable via environment variable
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/data/output"))
LOGS_DIR = OUTPUT_DIR / "logs"
RAW_DIR = OUTPUT_DIR / "raw"
AUDIO_DIR = OUTPUT_DIR / "audio"
CLIPS_DIR = OUTPUT_DIR / "clips"

def setup_paths():
    """Creates all necessary output directories."""
    for path in [OUTPUT_DIR, LOGS_DIR, RAW_DIR, AUDIO_DIR, CLIPS_DIR]:
        path.mkdir(parents=True, exist_ok=True)

# --- Logging Setup ---

def setup_logging(log_level: str = "INFO") -> None:
    """
    Configures structured logging for the application.

    Logs are sent to stdout and to a rotating file in the output directory.
    """
    log_level = log_level.upper()

    # Basic configuration
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

    # File handler with rotation
    log_file = LOGS_DIR / "auto_streamer.log"
    # Rotate logs after 5MB, keep 5 backup files
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    # Add the file handler to the root logger
    logging.getLogger().addHandler(file_handler)

    logging.info(f"Logging configured. Level: {log_level}. Log file: {log_file}")

    # Lower the log level of noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)


# --- Subprocess Execution ---

class FfmpegExecutionError(Exception):
    """Custom exception for errors during FFmpeg execution."""
    def __init__(self, command: List[str], stderr: str, return_code: int):
        self.command = command
        self.stderr = stderr
        self.return_code = return_code
        message = (
            f"FFmpeg command failed with exit code {return_code}.\n"
            f"Command: {' '.join(command)}\n"
            f"Stderr:\n{stderr}"
        )
        super().__init__(message)

def run_ffmpeg(
    args: List[str],
    stream_output: bool = False
) -> Generator[str, None, None]:
    """
    Executes an FFmpeg command and streams its stderr output.

    Args:
        args: A list of arguments for the FFmpeg command.
        stream_output: If True, yields stderr lines in real-time.
                         If False, collects and returns stderr on completion or error.

    Yields:
        Decoded stderr lines if stream_output is True.

    Raises:
        FfmpegExecutionError: If the FFmpeg process returns a non-zero exit code.
        FileNotFoundError: If the ffmpeg command is not found.
    """
    command = ["ffmpeg", "-hide_banner"] + args

    logger = logging.getLogger("ffmpeg")
    logger.info(f"Executing FFmpeg command: {' '.join(command)}")

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
    except FileNotFoundError:
        logger.error("`ffmpeg` command not found. Is FFmpeg installed and in your PATH?")
        raise

    stderr_output = []

    # Real-time streaming of stderr
    # Using a queue and a separate thread is a more robust way to handle this,
    # but for simplicity, we'll read line by line directly.
    if process.stderr:
        for line in iter(process.stderr.readline, ''):
            line = line.strip()
            if line:
                stderr_output.append(line)
                logger.debug(line)  # Tee to logs
                if stream_output:
                    yield line  # Yield to caller

    # Wait for the process to complete
    process.wait()

    if process.returncode != 0:
        stderr_str = "\n".join(stderr_output)
        raise FfmpegExecutionError(
            command=command, stderr=stderr_str, return_code=process.returncode
        )

    logger.info(f"FFmpeg command finished successfully: {' '.join(command)}")

# --- Retry Logic ---
# A default tenacity retry decorator for network calls
network_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)

# --- SSE Formatting ---

def format_sse(data: Dict[str, Any], event: Optional[str] = None) -> str:
    """
    Formats data into a Server-Sent Event string.

    Args:
        data: A dictionary containing the data to send.
        event: An optional event name.

    Returns:
        A string formatted for SSE.
    """
    import json

    message = f"data: {json.dumps(data)}\n\n"
    if event:
        message = f"event: {event}\n{message}"
    return message
