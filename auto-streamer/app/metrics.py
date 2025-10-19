"""
Configures and exposes Prometheus metrics for the application.

This module uses `starlette-exporter` to create a Prometheus metrics endpoint
and defines various gauges and counters to monitor the application's health and
performance.
"""
from prometheus_client import Counter, Gauge
from starlette_exporter import PrometheusMiddleware, handle_metrics

# --- Metric Definitions ---

# --- System Metrics ---
CPU_USAGE = Gauge("autostreamer_cpu_usage_percent", "Current CPU usage percentage")
MEMORY_USAGE = Gauge("autostreamer_memory_usage_mb", "Current memory usage in MB")
DISK_USAGE = Gauge("autostreamer_disk_usage_percent", "Current disk usage percentage for the output directory")

# --- Pipeline Metrics ---
JOBS_IN_QUEUE = Gauge("autostreamer_jobs_in_queue", "Number of jobs currently in the processing queue")
ITEMS_PROCESSED = Counter("autostreamer_items_processed_total", "Total number of items processed by the pipeline", ["state"]) # states: success, error

# --- FFmpeg/Stream Metrics ---
STREAM_STATUS = Gauge("autostreamer_stream_status", "Status of the RTMP stream (1=streaming, 0=offline)")
STREAM_FPS = Gauge("autostreamer_stream_fps", "Current FPS of the RTMP stream")
STREAM_BITRATE = Gauge("autostreamer_stream_bitrate_kbits", "Current bitrate of the RTMP stream in kbits/s")
STREAM_SPEED = Gauge("autostreamer_stream_speed", "Current streaming speed multiplier (e.g., 1.0x)")
STREAM_RECONNECTS = Counter("autostreamer_stream_reconnects_total", "Total number of stream reconnection attempts")

# --- Approval Metrics ---
AUTO_APPROVALS = Counter("autostreamer_auto_approvals_total", "Total number of items approved automatically", ["decision"]) # decisions: pass, fail
HUMAN_APPROVALS = Counter("autostreamer_human_approvals_total", "Total number of items approved or rejected by a human", ["decision"]) # decisions: approved, rejected


def setup_metrics_middleware(app):
    """
    Adds the Prometheus middleware to a FastAPI application.

    This also adds the `/metrics` endpoint to the app.
    """
    app.add_middleware(PrometheusMiddleware)
    app.add_route("/metrics", handle_metrics)

def update_system_metrics():
    """
    Updates the system-related Prometheus gauges.
    This function should be called periodically by a background task.
    """
    import psutil
    import shutil
    from .utils import OUTPUT_DIR

    # CPU
    CPU_USAGE.set(psutil.cpu_percent(interval=None))

    # Memory
    MEMORY_USAGE.set(psutil.virtual_memory().used / (1024 * 1024))

    # Disk
    if OUTPUT_DIR.exists():
        disk_usage = shutil.disk_usage(OUTPUT_DIR)
        DISK_USAGE.set(disk_usage.used / disk_usage.total * 100)

def update_stream_metrics(streamer_instance):
    """
    Updates stream-related metrics from a Streamer instance.
    This is just a placeholder for where you'd parse ffmpeg output
    and update the gauges.
    """
    if streamer_instance and streamer_instance.is_streaming():
        STREAM_STATUS.set(1)
        # In a real implementation, you would get these values from
        # parsing ffmpeg's stderr.
        # e.g., STREAM_FPS.set(parsed_fps)
        # e.g., STREAM_BITRATE.set(parsed_bitrate)
    else:
        STREAM_STATUS.set(0)
        STREAM_FPS.set(0)
        STREAM_BITRATE.set(0)
        STREAM_SPEED.set(0)

    # Reconnects are a counter, so we'd increment it when a reconnect happens.
    # e.g., STREAM_RECONNECTS.inc()
