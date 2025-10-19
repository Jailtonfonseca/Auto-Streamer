"""
The main entry point for the Auto-Streamer application.

This module provides a command-line interface (CLI) using argparse to:
- Run the full pipeline (ingest, tts, render, stream).
- Run individual pipeline stages.
- Manage the stream (start, stop).
- Handle approvals and reviews.
- Validate the configuration and environment.
- Start the web UI server.
"""
import argparse
import logging
import os
import sys

from app.config import app_config, ConfigError
from app.utils import setup_logging, setup_paths
from app.web.server import app as fastapi_app

# Set up logging early
logger = logging.getLogger("main")

def main():
    """The main function that parses CLI arguments and executes commands."""

    # --- Main Parser ---
    parser = argparse.ArgumentParser(
        description="Auto-Streamer: A dockerized pipeline for automated RTMP live streaming."
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    # --- 'serve' Command ---
    parser_serve = subparsers.add_parser("serve", help="Start the web UI and API server.")
    parser_serve.add_argument("--host", default="0.0.0.0", help="Host to bind the server to.")
    parser_serve.add_argument("--port", type=int, help="Port to run the server on (overrides config).")

    # --- 'all' Command ---
    parser_all = subparsers.add_parser("all", help="Run the full pipeline from ingest to render.")
    parser_all.add_argument("--stream", action="store_true", help="Start streaming automatically after rendering.")

    # --- Individual Stage Commands ---
    subparsers.add_parser("ingest", help="Run the ingest (RSS feed processing) stage.")
    subparsers.add_parser("tts", help="Run the TTS generation stage for ingested items.")
    subparsers.add_parser("render", help="Run the video rendering stage for TTS-complete items.")

    # --- 'stream' Command ---
    parser_stream = subparsers.add_parser("stream", help="Control the RTMP stream.")
    stream_subparsers = parser_stream.add_subparsers(dest="stream_action", required=True)
    stream_subparsers.add_parser("start", help="Start the stream.")
    stream_subparsers.add_parser("stop", help="Stop the stream.")

    # --- 'validate' Command ---
    subparsers.add_parser("validate", help="Validate configuration, dependencies, and permissions.")

    # --- Approval Commands ---
    parser_approve = subparsers.add_parser("approve", help="Approve an item awaiting review.")
    parser_approve.add_argument("--id", required=True, help="The ID of the item to approve.")

    parser_reject = subparsers.add_parser("reject", help="Reject an item awaiting review.")
    parser_reject.add_argument("--id", required=True, help="The ID of the item to reject.")
    parser_reject.add_argument("--reason", default="Rejected via CLI.", help="Reason for rejection.")

    # Parse arguments
    args = parser.parse_args()

    # --- Load Config and Setup ---
    try:
        setup_paths()
        setup_logging()
        app_config.load()
        logger.info("Configuration loaded.")
    except ConfigError as e:
        logger.error(f"Configuration Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred during setup: {e}")
        sys.exit(1)

    # --- Command Handling ---
    if args.command == "serve":
        import uvicorn
        from app.workers import worker_manager

        # Start background workers for pipeline tasks
        worker_manager.start()

        port = args.port if args.port else app_config.get("ui", {}).get("port", 8080)
        logger.info(f"Starting Uvicorn server on {args.host}:{port}")
        uvicorn.run(fastapi_app, host=args.host, port=port)

        # This part will only be reached on server shutdown
        worker_manager.stop()

    elif args.command == "all":
        from app.scraper import process_feeds
        from app.tts_generator import process_tts_queue
        from app.video_renderer import process_render_queue
        logger.info("Running full pipeline...")
        process_feeds()
        process_tts_queue()
        process_render_queue()
        logger.info("Full pipeline run complete.")
        if args.stream:
            # This part is a placeholder for stream start logic via CLI
            logger.info("Auto-starting stream is not fully implemented in CLI mode yet.")

    elif args.command == "ingest":
        from app.scraper import process_feeds
        process_feeds()

    elif args.command == "tts":
        from app.tts_generator import process_tts_queue
        process_tts_queue()

    elif args.command == "render":
        from app.video_renderer import process_render_queue
        process_render_queue()

    elif args.command == "validate":
        validate_environment()

    elif args.command == "approve":
        from app.manifest import manifest
        from app.models import ItemState
        if manifest.update_item(args.id, {"state": ItemState.APPROVED, "approved_by": "human"}):
            logger.info(f"Item {args.id} approved.")
        else:
            logger.error(f"Could not find or approve item {args.id}.")

    elif args.command == "reject":
        from app.manifest import manifest
        from app.models import ItemState
        updates = {"state": ItemState.REJECTED, "rejected_reason": args.reason}
        if manifest.update_item(args.id, updates):
            logger.info(f"Item {args.id} rejected.")
        else:
            logger.error(f"Could not find or reject item {args.id}.")

    else:
        parser.print_help()

def validate_environment():
    """
    Performs a series of checks to validate the application's environment.
    Exits with a non-zero status code if any check fails.
    """
    logger.info("--- Running Environment Validation ---")
    errors = 0

    # 1. Check for FFmpeg
    try:
        import shutil
        if not shutil.which("ffmpeg"):
            logger.error("Validation Error: `ffmpeg` command not found. FFmpeg is essential for video processing.")
            errors += 1
        else:
            logger.info("FFmpeg found successfully.")
    except Exception as e:
        logger.error(f"An error occurred while checking for FFmpeg: {e}")
        errors += 1

    # 2. Validate config.json against schema
    try:
        # The app_config.load() already does this, but we can be explicit.
        app_config.load()
        logger.info("Configuration file is valid against the schema.")
    except ConfigError as e:
        logger.error(f"Validation Error: Configuration is invalid. {e}")
        errors += 1

    # 3. Check for write permissions in the output directory
    try:
        from app.utils import OUTPUT_DIR
        test_file = OUTPUT_DIR / ".permission_test"
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        logger.info("Write permissions for the output directory are correct.")
    except IOError as e:
        logger.error(f"Validation Error: Cannot write to the output directory at '{OUTPUT_DIR}'. Check permissions. {e}")
        errors += 1
    except Exception as e:
        logger.error(f"An unexpected error occurred while checking write permissions: {e}")
        errors += 1

    if errors == 0:
        logger.info("--- Environment Validation Successful ---")
        sys.exit(0)
    else:
        logger.error(f"--- Environment Validation Failed with {errors} error(s) ---")
        sys.exit(1)


if __name__ == "__main__":
    main()
