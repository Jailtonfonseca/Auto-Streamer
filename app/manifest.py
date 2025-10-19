"""
Manages the state of content items via a persistent JSON manifest file.

This module provides a thread-safe class for reading, writing, and querying
the manifest, which acts as the database for the application. Each item in the
pipeline has an entry in the manifest, tracking its state, associated files,
and metadata.
"""
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple

from .models import ItemState, ManifestItem

logger = logging.getLogger(__name__)

class Manifest:
    """
    Handles the lifecycle of the manifest.json file, providing thread-safe
    access and persistence for item states.
    """

    def __init__(self, manifest_path: Path):
        """
        Initializes the Manifest manager.

        Args:
            manifest_path: The path to the manifest.json file.
        """
        self.path = manifest_path
        self._lock = Lock()
        self._items: Dict[str, ManifestItem] = {}
        self.load()

    def load(self) -> None:
        """
        Loads the manifest from the JSON file into memory.
        If the file doesn't exist, it initializes an empty manifest.
        """
        with self._lock:
            if not self.path.exists():
                logger.warning(f"Manifest file not found at {self.path}. A new one will be created.")
                self._items = {}
                return

            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    # Handle empty file case
                    content = f.read()
                    if not content:
                        self._items = {}
                        return

                    items_list = json.loads(content)
                    self._items = {item['id']: item for item in items_list}
                    logger.info(f"Loaded {len(self._items)} items from manifest.")
            except json.JSONDecodeError:
                logger.exception(f"Could not decode manifest file at {self.path}. It might be corrupted.")
                # Consider loading a backup if one exists
            except Exception:
                logger.exception("An unexpected error occurred while loading the manifest.")


    def _save(self) -> None:
        """
        Saves the current state of the manifest back to the JSON file.
        This is a private method and should be called within a lock.
        """
        # Create a backup before writing
        if self.path.exists():
            backup_path = self.path.with_suffix(".json.bak")
            try:
                shutil.copy2(self.path, backup_path)
            except IOError:
                logger.warning(f"Failed to create manifest backup at {backup_path}")

        try:
            # Sort items by creation date for consistency
            sorted_items = sorted(self._items.values(), key=lambda i: i['created_at'], reverse=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(sorted_items, f, indent=2)
        except Exception:
            logger.exception(f"Failed to save manifest to {self.path}")

    def generate_id(self) -> str:
        """Generates a new, unique ID for a manifest item."""
        now = datetime.now(timezone.utc)
        # Find the highest sequence number for the current timestamp second
        prefix = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        # This is a simple way to avoid collisions within the same second.
        # For high-throughput systems, a more robust method like UUID would be better.
        seq = 1
        while f"{prefix}-{seq:04d}" in self._items:
            seq += 1
        return f"{prefix}-{seq:04d}"

    def add_item(self, item: ManifestItem) -> None:
        """
        Adds a new item to the manifest and saves the changes.

        Args:
            item: The ManifestItem to add.
        """
        with self._lock:
            if item['id'] in self._items:
                logger.warning(f"Item with ID {item['id']} already exists. Overwriting.")
            self._items[item['id']] = item
            self._save()
        logger.info(f"Added item {item['id']} to manifest.")

    def update_item(self, item_id: str, updates: Dict) -> Optional[ManifestItem]:
        """
        Updates an existing item in the manifest and saves.

        Args:
            item_id: The ID of the item to update.
            updates: A dictionary of fields to update.

        Returns:
            The updated ManifestItem, or None if not found.
        """
        with self._lock:
            if item_id in self._items:
                item = self._items[item_id]
                item.update(updates) # type: ignore
                item['updated_at'] = datetime.now(timezone.utc).isoformat()
                self._items[item_id] = item
                self._save()
                logger.info(f"Updated item {item_id} with: {updates}")
                return item
            else:
                logger.warning(f"Attempted to update non-existent item with ID {item_id}")
                return None

    def get_all(self) -> List[ManifestItem]:
        """Returns a list of all items in the manifest."""
        with self._lock:
            return list(self._items.values())

    def get_by_id(self, item_id: str) -> Optional[ManifestItem]:
        """
        Retrieves an item by its ID.

        Returns:
            The ManifestItem, or None if not found.
        """
        with self._lock:
            return self._items.get(item_id)

    def get_by_state(self, state: ItemState) -> List[ManifestItem]:
        """Returns all items currently in the specified state."""
        with self._lock:
            return [item for item in self._items.values() if item['state'] == state]

    def find_by_guid_or_link(self, guid: Optional[str], link: str) -> Optional[ManifestItem]:
        """
        Checks for duplicates based on GUID or link.

        Returns the first matching item found, or None.
        """
        with self._lock:
            for item in self._items.values():
                source = item['source']
                # Check for GUID match if both are present
                if guid and source.get('guid') and guid == source['guid']:
                    return item
                # Fallback to link match
                if link and source.get('link') and link == source['link']:
                    return item
        return None

# --- Singleton Instance ---
# Provides a single, globally accessible manifest object.
from .utils import OUTPUT_DIR

manifest = Manifest(OUTPUT_DIR / "manifest.json")
