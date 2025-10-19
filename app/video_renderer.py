"""
Handles the rendering of video clips and the final concatenated video.

This module is responsible for:
- Taking an image and an audio file and creating a video clip using FFmpeg.
- Scaling and padding images to fit the output video resolution.
- Concatenating multiple video clips into a single final video.
- Optionally mixing in background music.
- Updating the manifest item with the paths to the generated clip and final video.
"""
import logging
from pathlib import Path
from typing import List

from .config import app_config
from .manifest import manifest
from .models import ItemState, ManifestItem
from .utils import CLIPS_DIR, OUTPUT_DIR, run_ffmpeg, FfmpegExecutionError

logger = logging.getLogger(__name__)

class VideoRenderer:
    """A class to handle video rendering tasks using FFmpeg."""

    def __init__(self):
        self.output_cfg = app_config.get("output", {})
        self.audio_cfg = app_config.get("audio", {})
        self.width = self.output_cfg.get("width", 1280)
        self.height = self.output_cfg.get("height", 720)
        self.fps = self.output_cfg.get("fps", 30)

    def _render_clip(self, item: ManifestItem) -> bool:
        """
        Renders a single clip from an item's image and audio.
        """
        item_id = item['id']
        image_path = item['paths'].get('image')
        audio_path = item['paths'].get('audio')
        duration = item.get('duration_s')

        if not all([image_path, audio_path, duration]):
            logger.error(f"Item {item_id} is missing image, audio, or duration for rendering.")
            return False

        clip_path = CLIPS_DIR / f"{item_id}_clip.mp4"

        # FFmpeg video filtergraph to scale and pad the image to 16:9
        vf = (
            f"scale=w={self.width}:h={self.height}:force_original_aspect_ratio=decrease,"
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
        )

        ffmpeg_args = [
            "-y",                   # Overwrite output file if it exists
            "-loop", "1",           # Loop the input image
            "-i", str(image_path),  # Input image
            "-i", str(audio_path),  # Input audio
            "-t", str(duration),    # Set duration from audio
            "-r", str(self.fps),    # Set frame rate
            "-vf", vf,              # Apply video filtergraph
            "-c:v", "libx264",      # Video codec
            "-preset", self.output_cfg.get("preset", "veryfast"),
            "-crf", str(self.output_cfg.get("crf", 23)),
            "-c:a", "aac",          # Audio codec
            "-b:a", f"{self.audio_cfg.get('bitrate_kbps', 128)}k",
            "-shortest",            # Finish encoding when the shortest input ends (the audio)
            str(clip_path),
        ]

        try:
            list(run_ffmpeg(ffmpeg_args))
            logger.info(f"Successfully rendered clip for item {item_id} at {clip_path}")

            # Update manifest with clip path
            updates = {"paths": {**item['paths'], "clip": str(clip_path)}}
            manifest.update_item(item_id, updates)

            return True
        except FfmpegExecutionError as e:
            logger.error(f"Failed to render clip for item {item_id}: {e}")
            return False

    def _concatenate_clips(self, clip_paths: List[Path], final_video_path: Path) -> bool:
        """
        Concatenates a list of video clips into a single video file.
        """
        if not clip_paths:
            logger.warning("No clips provided for concatenation.")
            return False

        filelist_path = OUTPUT_DIR / "filelist.txt"
        with open(filelist_path, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p.resolve()}'\n")

        ffmpeg_args = [
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(filelist_path),
            "-c", "copy",  # Fast re-muxing without re-encoding
            str(final_video_path),
        ]

        try:
            list(run_ffmpeg(ffmpeg_args))
            logger.info(f"Successfully concatenated {len(clip_paths)} clips into {final_video_path}")
            return True
        except FfmpegExecutionError as e:
            logger.error(f"Failed to concatenate clips: {e}")
            return False
        finally:
            filelist_path.unlink(missing_ok=True)

    def _add_background_music(self, video_path: Path, bgm_path: str) -> bool:
        """
        Adds background music to a video file. This creates a new file.
        """
        if not Path(bgm_path).exists():
            logger.error(f"Background music file not found: {bgm_path}")
            return False

        output_with_bgm_path = video_path.with_name(f"{video_path.stem}_bgm.mp4")
        bgm_volume = self.audio_cfg.get("bgm_volume", 0.15)

        # FFmpeg filtergraph to mix audio. 'amerge' merges, 'volume' adjusts BGM level.
        # 'pan' maps the merged stereo to a standard stereo layout.
        # '-shortest' ensures output ends with the video stream.
        filter_complex = (
            f"[0:a][1:a]amerge=inputs=2[a];"
            f"[a]volume=1.0[a_main];" # This is a placeholder, assuming main audio is already correct
            f"[1:a]volume={bgm_volume}[a_bgm];"
            f"[0:a][a_bgm]amix=inputs=2:duration=first:dropout_transition=3[a_out]"
        )

        # A simpler filter that might work better if the above is complex
        simple_filter = f"[0:a]volume=1.0[a0]; [1:a]volume={bgm_volume}[a1]; [a0][a1]amix=inputs=2:duration=first"


        ffmpeg_args = [
            "-y",
            "-i", str(video_path),          # Input video
            "-i", str(bgm_path),            # Input BGM
            "-filter_complex", simple_filter,
            "-map", "0:v",                  # Map video from first input
            "-map", "[a_out]",              # Map mixed audio
            "-c:v", "copy",                 # Copy video stream without re-encoding
            "-c:a", "aac",                  # Re-encode audio to AAC
            "-b:a", f"{self.audio_cfg.get('bitrate_kbps', 128)}k",
            "-shortest",
            str(output_with_bgm_path),
        ]

        try:
            list(run_ffmpeg(ffmpeg_args))
            logger.info(f"Added background music to create {output_with_bgm_path}")
            # Replace original file with the new one
            video_path.unlink()
            output_with_bgm_path.rename(video_path)
            return True
        except FfmpegExecutionError as e:
            logger.error(f"Failed to add background music: {e}")
            output_with_bgm_path.unlink(missing_ok=True)
            return False

    def process_item(self, item: ManifestItem) -> bool:
        """Renders a clip for a single manifest item."""
        return self._render_clip(item)

    def create_final_video(self, items: List[ManifestItem]) -> Optional[Path]:
        """
        Creates the final video by concatenating clips from the given items.
        """
        if not items:
            logger.info("No items provided to create final video.")
            return None

        final_video_path = OUTPUT_DIR / "final_video.mp4"

        clip_paths = [Path(item['paths']['clip']) for item in items if item['paths'].get('clip')]

        if not self._concatenate_clips(clip_paths, final_video_path):
            return None

        # Add BGM if configured
        bgm_path = self.audio_cfg.get("bgm_path")
        if bgm_path:
            if not self._add_background_music(final_video_path, bgm_path):
                logger.warning("Failed to add BGM, continuing with original video.")

        # Update all items to point to the final video path and set state to RENDERED
        publish_config = app_config.get("publish", {})
        next_state = ItemState.AWAITING_APPROVAL if publish_config.get("require_approval") else ItemState.APPROVED

        for item in items:
            updates = {
                "state": next_state,
                "paths": {**item['paths'], "final": str(final_video_path)}
            }
            manifest.update_item(item['id'], updates)

        logger.info(f"Final video created. Items moved to '{next_state.value}' state.")
        return final_video_path


def process_render_queue():
    """
    Renders clips for all items in the TTS_DONE state and then
    concatenates them into a single video if there are any.
    """
    logger.info("Checking for items ready for video rendering...")
    items_to_process = manifest.get_by_state(ItemState.TTS_DONE)

    if not items_to_process:
        logger.info("No items in the rendering queue.")
        return

    renderer = VideoRenderer()
    processed_items = []
    fail_count = 0

    for item in items_to_process:
        if renderer.process_item(item):
            # Reload item from manifest to get the updated clip path
            updated_item = manifest.get_by_id(item['id'])
            if updated_item:
                processed_items.append(updated_item)
        else:
            fail_count += 1
            manifest.update_item(item['id'], {"state": ItemState.ERROR, "notes": "Video rendering failed"})

    if processed_items:
        renderer.create_final_video(processed_items)

    logger.info(f"Video rendering run complete. Succeeded clips: {len(processed_items)}, Failed clips: {fail_count}")
