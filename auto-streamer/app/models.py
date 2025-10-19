"""
Defines the core data structures and state models for the application.

This module contains dataclasses and TypedDicts that represent the state of
items as they move through the processing pipeline, from ingestion to publication.
These models are used for type hinting, validation, and serialization, ensuring
data consistency across different parts of the application.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional, TypedDict
from pydantic import BaseModel, Field

# --- Enums for State and other controlled vocabularies ---

class ItemState(str, Enum):
    """Enumeration of possible states for a content item in the pipeline."""
    INGESTED = "INGESTED"
    TTS_DONE = "TTS_DONE"
    RENDERED = "RENDERED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    ERROR = "ERROR"

class SourceType(str, Enum):
    """Enumeration for the origin of the content."""
    RSS = "rss"
    URL = "url"

# --- TypedDicts for structured, but not object-oriented data ---
# Useful for manifest entries which are primarily for serialization.

class SourceInfo(TypedDict):
    """Information about the origin of the content item."""
    type: SourceType
    feed: Optional[str]  # URL of the RSS feed
    link: str            # Direct URL to the article
    guid: Optional[str]  # GUID from the RSS feed

class Paths(TypedDict):
    """File paths for all artifacts generated for an item."""
    text: Optional[str]
    image: Optional[str]
    audio: Optional[str]
    clip: Optional[str]
    final: Optional[str] # Path to the final concatenated video

class AutoApprovalResult(TypedDict, total=False):
    """Result of the auto-approval process."""
    passed: bool
    score: float
    mode: str
    strategy: str
    rules_passed: List[str]
    rules_failed: List[str]
    timestamp: str

class ManifestItem(TypedDict):
    """
    Represents a single content item's metadata and state in the manifest.
    This is the primary model for serialization to manifest.json.
    """
    id: str
    source: SourceInfo
    title: str
    original_text: str
    processed_text: str
    paths: Paths
    duration_s: Optional[float]
    state: ItemState
    created_at: str
    updated_at: str
    approved_by: Optional[Literal["human", "system"]]
    rejected_reason: Optional[str]
    auto_approval: Optional[AutoApprovalResult]
    notes: Optional[str]
    retries: int

# --- Dataclasses for more complex objects with behavior ---
# These might be used internally for application logic.

@dataclass
class Job:
    """Represents a job to be processed by a worker."""
    item_id: str
    task_name: str # e.g., "tts", "render"
    payload: Dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

@dataclass
class AppMetrics:
    """A dataclass to hold current application metrics."""
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    disk_usage_percent: float = 0.0
    ffmpeg_fps: float = 0.0
    ffmpeg_bitrate_kbits: float = 0.0
    ffmpeg_speed: float = 0.0
    stream_status: str = "OFFLINE"
    reconnect_attempts: int = 0
    jobs_in_queue: int = 0
    items_processed: int = 0
    auto_approvals: int = 0
    human_approvals: int = 0

    def to_dict(self) -> Dict:
        """Serializes the metrics to a dictionary."""
        return {
            "cpu_usage_percent": self.cpu_usage_percent,
            "memory_usage_mb": self.memory_usage_mb,
            "disk_usage_percent": self.disk_usage_percent,
            "ffmpeg": {
                "fps": self.ffmpeg_fps,
                "bitrate_kbits": self.ffmpeg_bitrate_kbits,
                "speed": self.ffmpeg_speed,
            },
            "stream": {
                "status": self.stream_status,
                "reconnect_attempts": self.reconnect_attempts
            },
            "pipeline": {
                "jobs_in_queue": self.jobs_in_queue,
                "items_processed_total": self.items_processed,
            },
            "approvals":{
                "auto_approved_total": self.auto_approvals,
                "human_approved_total": self.human_approvals
            }
        }

# --- Pydantic Models for API Validation ---

class UpdateConfigRequest(BaseModel):
    """Defines the fields that can be updated in the config via the API."""
    rtmp_url: Optional[str] = Field(None, description="The RTMP URL for the stream.")
    stream_key: Optional[str] = Field(None, description="The stream key for the RTMP endpoint.")
    openai_api_key: Optional[str] = Field(None, description="The API key for OpenAI TTS.")
    admin_pass_hash: Optional[str] = Field(None, description="A new bcrypt hash for the admin password.")
