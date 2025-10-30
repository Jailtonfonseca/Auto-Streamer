"""
Handles background job processing using a simple in-process worker queue.

This module provides a basic framework for offloading long-running tasks
from the main web server thread. It includes a `WorkerManager` to start and
stop worker threads and `Job` definitions for pipeline tasks.
"""
import logging
from queue import Queue, Empty
from threading import Thread, Event
from typing import Callable, Dict, Any

from . import scraper, tts_generator, video_renderer

logger = logging.getLogger(__name__)

class Job:
    """Represents a job to be executed by a worker."""
    def __init__(self, name: str, func: Callable, args: tuple = (), kwargs: Dict[str, Any] = None):
        self.name = name
        self.func = func
        self.args = args
        self.kwargs = kwargs if kwargs is not None else {}

    def run(self):
        """Executes the job's function."""
        logger.info(f"Starting job: {self.name}")
        try:
            self.func(*self.args, **self.kwargs)
            logger.info(f"Finished job: {self.name}")
        except Exception:
            logger.exception(f"Job '{self.name}' failed unexpectedly.")

class Worker(Thread):
    """A worker thread that processes jobs from a queue."""
    def __init__(self, job_queue: Queue):
        super().__init__(daemon=True)
        self.job_queue = job_queue
        self._stop_event = Event()

    def run(self):
        logger.info("Worker thread started.")
        while not self._stop_event.is_set():
            try:
                job = self.job_queue.get(timeout=1)
                job.run()
                self.job_queue.task_done()
            except Empty:
                continue # No job in queue, continue waiting
            except Exception:
                logger.exception("An error occurred in the worker loop.")
        logger.info("Worker thread stopped.")

    def stop(self):
        """Signals the worker thread to stop."""
        self._stop_event.set()

class WorkerManager:
    """Manages the lifecycle of worker threads."""
    def __init__(self, num_workers: int = 1):
        self.job_queue: Queue[Job] = Queue()
        self.workers: list[Worker] = []
        self.num_workers = num_workers

    def start(self):
        """Starts the configured number of worker threads."""
        if self.workers:
            logger.warning("Workers are already running.")
            return

        for _ in range(self.num_workers):
            worker = Worker(self.job_queue)
            worker.start()
            self.workers.append(worker)
        logger.info(f"Started {self.num_workers} worker(s).")

    def stop(self):
        """Stops all running worker threads gracefully."""
        logger.info("Stopping all workers...")
        for worker in self.workers:
            worker.stop()
        for worker in self.workers:
            worker.join(timeout=5) # Wait for threads to finish
        self.workers = []
        logger.info("All workers stopped.")

    def add_job(self, job: Job):
        """Adds a new job to the queue for processing."""
        self.job_queue.put(job)
        logger.info(f"Added job '{job.name}' to the queue. Queue size: {self.job_queue.qsize()}")

# --- Singleton Instance ---
# A single worker manager for the entire application.
worker_manager = WorkerManager()

# --- Pre-defined Pipeline Job Functions ---

def run_full_pipeline():
    """Adds all pipeline stages as a single, sequential job to the queue."""
    def pipeline_task():
        logger.info("--- Starting Full Pipeline Run ---")

        logger.info("Stage 1: Ingesting from feeds.")
        scraper.process_feeds()

        logger.info("Stage 2: Generating TTS for new items.")
        tts_generator.process_tts_queue()

        logger.info("Stage 3: Rendering video from TTS items.")
        # Only render if there are items ready, otherwise the final video might be empty
        from .manifest import manifest
        from .models import ItemState
        if manifest.get_by_state(ItemState.TTS_DONE):
             video_renderer.process_render_queue()
        else:
             logger.info("Skipping render stage: no TTS-complete items.")

        logger.info("--- Full Pipeline Run Finished ---")

    worker_manager.add_job(Job(name="full_pipeline", func=pipeline_task))

def run_ingest_only():
    """Adds an ingest-only job to the queue."""
    worker_manager.add_job(Job(name="ingest", func=scraper.process_feeds))

def run_tts_only():
    """Adds a TTS-only job to the queue."""
    worker_manager.add_job(Job(name="tts", func=tts_generator.process_tts_queue))

def run_render_only():
    """Adds a render-only job to the queue."""
    worker_manager.add_job(Job(name="render", func=video_renderer.process_render_queue))
