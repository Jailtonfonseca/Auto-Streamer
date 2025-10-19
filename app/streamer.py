"""
Handles the RTMP streaming of the final video to one or more endpoints.

This module is responsible for:
- Constructing and executing the FFmpeg command for RTMP streaming.
- Continuously looping the video stream if configured.
- Handling automatic reconnection with backoff on stream failure.
- Supporting multistreaming to multiple RTMP endpoints ("tee" output).
- Parsing FFmpeg's stderr to extract and log streaming metrics.
"""
import logging
import re
import subprocess
import time
from pathlib import Path
from threading import Event, Thread
from typing import List, Optional

from .config import app_config

logger = logging.getLogger(__name__)

class Streamer:
    """
    Manages the lifecycle of the FFmpeg streaming process.
    """

    def __init__(self, video_path: Path):
        self.config = app_config.get("stream", {})
        self.video_path = video_path

        self.rtmp_url = self.config.get("rtmp_url")
        self.stream_key = self.config.get("stream_key")

        if not self.rtmp_url or not self.stream_key:
            raise ValueError("RTMP URL and Stream Key must be configured.")

        self.full_rtmp_url = f"{self.rtmp_url.rstrip('/')}/{self.stream_key}"

        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[Thread] = None
        self._stop_event = Event()
        self.reconnect_attempts = 0

    def _build_ffmpeg_command(self) -> List[str]:
        """Constructs the FFmpeg command for streaming."""
        output_cfg = app_config.get("output", {})

        # Base command for streaming from a file
        command = [
            "ffmpeg",
            "-re",  # Read input at native frame rate
            "-stream_loop", "-1" if self.config.get("loop", True) else "0",
            "-i", str(self.video_path),
        ]

        # Video and audio codec options for streaming
        command.extend([
            "-c:v", "copy",  # Copy video stream without re-encoding
            "-c:a", "copy",  # Copy audio stream without re-encoding
            "-f", "flv",     # Force format to Flash Video for RTMP
        ])

        # Handle multistreaming with the "tee" muxer
        tee_outputs = self.config.get("tee_to", [])
        if tee_outputs:
            output_urls = [self.full_rtmp_url] + tee_outputs
            # Format for tee muxer: "[f=flv]rtmp_url1|[f=flv]rtmp_url2"
            tee_arg = "|".join([f"[f=flv]{url}" for url in output_urls])
            command.extend(["-map", "0", tee_arg])
        else:
            # Single output
            command.append(self.full_rtmp_url)

        return command

    def _monitor_stream(self):
        """
        The main loop that runs in a separate thread. It starts, monitors,
        and restarts the FFmpeg process as needed.
        """
        while not self._stop_event.is_set():
            command = self._build_ffmpeg_command()
            logger.info(f"Starting FFmpeg stream: {' '.join(command)}")

            try:
                self._process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, # Redirect stderr to stdout
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )

                # Reset reconnect attempts on successful start
                self.reconnect_attempts = 0

                # Process FFmpeg output line by line
                if self._process.stdout:
                    for line in iter(self._process.stdout.readline, ''):
                        if self._stop_event.is_set():
                            break
                        self._parse_ffmpeg_output(line.strip())

                self._process.wait()

                if self._stop_event.is_set():
                    logger.info("Streaming stopped by user.")
                    break

                logger.warning(f"FFmpeg process exited unexpectedly with code {self._process.returncode}.")

            except FileNotFoundError:
                logger.error("`ffmpeg` command not found. Cannot start stream.")
                break
            except Exception as e:
                logger.error(f"An unexpected error occurred with the FFmpeg process: {e}")

            if self._stop_event.is_set():
                break

            # --- Reconnection Logic ---
            self.reconnect_attempts += 1
            backoff_s = self.config.get("reconnect_backoff_s", 5) * self.reconnect_attempts
            logger.info(f"Attempting to reconnect in {backoff_s} seconds...")
            self._stop_event.wait(backoff_s) # Wait for backoff period, but exit early if stop is called

        logger.info("Stream monitoring thread has finished.")

    def _parse_ffmpeg_output(self, line: str):
        """
        Parses FFmpeg's progress output to extract metrics.
        Example line: frame= 123 fps= 30.0 q=28.0 size=   456kB time=00:00:04.10 bitrate= 911.2kbits/s speed=1.00x
        """
        logger.debug(f"[ffmpeg] {line}")

        # Regex to capture key streaming metrics
        match = re.search(
            r"frame=\s*(\d+)\s+fps=\s*([\d\.]+)\s+.*bitrate=\s*([\d\.]+kbits/s)\s+speed=\s*([\d\.]+)x",
            line
        )
        if match:
            # Here you would update a metrics object or Prometheus gauges
            frame, fps, bitrate, speed = match.groups()
            logger.info(f"Stream progress: Frame={frame}, FPS={fps}, Bitrate={bitrate}, Speed={speed}")

        # You can add more regex here to detect specific errors, like "Connection refused"


    def start(self):
        """Starts the streaming process in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Stream is already running.")
            return

        if not self.video_path.exists():
            logger.error(f"Video file not found: {self.video_path}. Cannot start stream.")
            return

        self._stop_event.clear()
        self._thread = Thread(target=self._monitor_stream, name="StreamMonitor")
        self._thread.daemon = True
        self._thread.start()
        logger.info("Streamer started.")

    def stop(self):
        """Stops the streaming process."""
        if not self._thread or not self._thread.is_alive():
            logger.info("Stream is not running.")
            return

        logger.info("Stopping stream...")
        self._stop_event.set()

        if self._process:
            try:
                # Politely ask FFmpeg to terminate
                self._process.terminate()
                # Wait for a moment to see if it complies
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg did not terminate gracefully, killing it.")
                self._process.kill()
            except Exception as e:
                logger.error(f"Error while stopping FFmpeg process: {e}")

        # Wait for the monitoring thread to finish
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            logger.warning("Stream monitoring thread did not exit cleanly.")

        self._process = None
        self._thread = None
        logger.info("Streamer stopped.")

    def is_streaming(self) -> bool:
        """Checks if the streaming process is currently active."""
        return self._process is not None and self._process.poll() is None
