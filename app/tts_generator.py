"""
Handles Text-to-Speech (TTS) generation using the OpenAI API.

This module is responsible for:
- Reading text content from files specified in a manifest item.
- Chunking long texts to fit within API limits.
- Calling the OpenAI Speech API to convert text chunks to audio.
- Concatenating the resulting audio chunks into a single file.
- Measuring the duration of the final audio file.
- Updating the manifest item with the audio path, duration, and new state.
"""
import logging
import math
from pathlib import Path
from typing import List

import mutagen
from openai import OpenAI, OpenAIError

from .config import app_config
from .manifest import manifest
from .models import ItemState, ManifestItem
from .utils import AUDIO_DIR, network_retry, run_ffmpeg, FfmpegExecutionError

logger = logging.getLogger(__name__)

class TTSGenerator:
    """A class to handle TTS generation with the OpenAI API."""

    def __init__(self):
        self.config = app_config.get("tts", {})
        self.api_key = self.config.get("api_key")
        if not self.api_key:
            raise ValueError("OpenAI API key is not configured.")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.config.get("base_url")
        )

    def _chunk_text(self, text: str) -> List[str]:
        """
        Splits text into chunks that are safe for the TTS API, respecting
        paragraph and sentence boundaries where possible.
        """
        chunk_size = self.config.get("chunk_chars", 3000)
        if len(text) <= chunk_size:
            return [text]

        import textwrap

        # Use textwrap to handle the basic splitting
        chunks = textwrap.wrap(text, chunk_size, break_long_words=True, replace_whitespace=False)
        logger.info(f"Split text into {len(chunks)} chunks.")
        return chunks

    @network_retry
    def _generate_audio_chunk(self, text: str, output_path: Path):
        """Calls the OpenAI API to generate audio for a single text chunk."""
        try:
            response = self.client.audio.speech.create(
                model=self.config.get("model", "tts-1"),
                voice=self.config.get("voice", "alloy"),
                input=text,
                response_format=self.config.get("format", "mp3"),
                speed=self.config.get("speed", 1.0),
            )
            response.stream_to_file(output_path)
            logger.debug(f"Successfully generated audio chunk: {output_path}")
        except OpenAIError as e:
            logger.error(f"OpenAI API error for {output_path.stem}: {e}")
            raise  # Re-raise to be caught by the network_retry decorator or the calling function

    def _concatenate_audio(self, chunk_paths: List[Path], final_path: Path):
        """
        Concatenates multiple audio chunks into a single file using FFmpeg.
        """
        if not chunk_paths:
            return

        # Create a file list for FFmpeg's concat demuxer
        filelist_path = final_path.with_suffix(".txt")
        with open(filelist_path, "w") as f:
            for p in chunk_paths:
                f.write(f"file '{p.resolve()}'\n")

        # FFmpeg command for concatenation without re-encoding (fast)
        ffmpeg_args = [
            "-f", "concat",
            "-safe", "0",
            "-i", str(filelist_path),
            "-c", "copy",
            str(final_path),
        ]

        try:
            # We don't need to stream the output for this command
            list(run_ffmpeg(ffmpeg_args, stream_output=False))
            logger.info(f"Concatenated {len(chunk_paths)} audio chunks into {final_path}")
        except FfmpegExecutionError as e:
            logger.error(f"FFmpeg failed to concatenate audio: {e}")
            raise
        finally:
            # Clean up the temporary file list and chunks
            filelist_path.unlink(missing_ok=True)
            for p in chunk_paths:
                p.unlink(missing_ok=True)

    def _get_audio_duration(self, file_path: Path) -> float:
        """Measures the duration of an audio file using mutagen."""
        try:
            audio = mutagen.File(file_path)
            if audio and audio.info:
                return audio.info.length
        except Exception as e:
            logger.error(f"Could not read audio duration from {file_path}: {e}")
        return 0.0

    def process_item(self, item: ManifestItem) -> bool:
        """
        Generates TTS for a given manifest item.

        Returns:
            True if successful, False otherwise.
        """
        item_id = item['id']
        logger.info(f"Starting TTS generation for item {item_id}")

        text_path_str = item['paths'].get('text')
        if not text_path_str:
            logger.error(f"Item {item_id} has no text path. Cannot generate TTS.")
            return False

        text_path = Path(text_path_str)
        if not text_path.exists():
            logger.error(f"Text file not found for item {item_id} at {text_path}")
            return False

        with open(text_path, "r", encoding="utf-8") as f:
            text = f.read()

        chunks = self._chunk_text(text)
        chunk_paths = []

        config = app_config.get("tts", {})
        # Generate audio for each chunk
        for i, chunk in enumerate(chunks):
            chunk_path = AUDIO_DIR / f"{item_id}_part{i+1}.{config.get('format', 'mp3')}"
            try:
                self._generate_audio_chunk(chunk, chunk_path)
                chunk_paths.append(chunk_path)
            except Exception:
                # Clean up partial files on failure
                for p in chunk_paths:
                    p.unlink(missing_ok=True)
                return False

        # Concatenate and update manifest
        final_audio_path = AUDIO_DIR / f"{item_id}_audio.{config.get('format', 'mp3')}"

        try:
            self._concatenate_audio(chunk_paths, final_audio_path)
            duration = self._get_audio_duration(final_audio_path)

            updates = {
                "state": ItemState.TTS_DONE,
                "paths": {**item['paths'], "audio": str(final_audio_path)},
                "duration_s": duration,
            }
            manifest.update_item(item_id, updates)

            logger.info(f"TTS generation for item {item_id} complete. Duration: {duration:.2f}s")
            return True
        except Exception as e:
            logger.error(f"Failed during concatenation or manifest update for {item_id}: {e}")
            final_audio_path.unlink(missing_ok=True) # Clean up final file on error
            return False

def process_tts_queue():
    """Processes all items in the INGESTED state."""
    logger.info("Checking for items ready for TTS generation...")
    items_to_process = manifest.get_by_state(ItemState.INGESTED)

    if not items_to_process:
        logger.info("No items in the TTS queue.")
        return

    try:
        tts_generator = TTSGenerator()
    except ValueError as e:
        logger.error(f"Failed to initialize TTSGenerator, likely due to missing API key: {e}")
        return

    success_count = 0
    fail_count = 0

    for item in items_to_process:
        if tts_generator.process_item(item):
            success_count += 1
        else:
            fail_count += 1
            manifest.update_item(item['id'], {"state": ItemState.ERROR, "notes": "TTS generation failed"})

    logger.info(f"TTS processing run complete. Succeeded: {success_count}, Failed: {fail_count}")
