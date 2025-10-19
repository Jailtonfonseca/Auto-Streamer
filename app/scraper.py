"""
Handles the ingestion and scraping of content from RSS feeds and direct URLs.

This module is responsible for:
- Fetching and parsing RSS/Atom feeds using `feedparser`.
- Deduplicating items against the manifest.
- Scraping article content from URLs using `trafilatura` and `BeautifulSoup`.
- Extracting a primary image or generating a placeholder.
- Saving the extracted text and image to disk.
- Creating a new `ManifestItem` and adding it to the manifest.
"""
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont
from trafilatura import fetch_url, extract

from .config import app_config
from .manifest import manifest
from .models import ItemState, ManifestItem, SourceType
from .utils import network_retry, RAW_DIR

logger = logging.getLogger(__name__)

class Scraper:
    """A class to handle scraping content from URLs."""

    def __init__(self):
        self.config = app_config.get("scraper", {})
        self.headers = {"User-Agent": self.config.get("user_agent")}

    @network_retry
    def _fetch_html(self, url: str) -> Optional[str]:
        """Fetches HTML content from a URL with configured timeout and headers."""
        try:
            response = requests.get(
                url, headers=self.headers, timeout=self.config.get("timeout_s", 15)
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch URL {url}: {e}")
            return None

    def _extract_main_image(self, url: str, soup: BeautifulSoup) -> Optional[str]:
        """
        Extracts the main image URL from the page's metadata or content.
        Prioritizes Open Graph (og:image), then looks for a suitable <img> tag.
        """
        # 1. Try Open Graph
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            logger.info(f"Found og:image: {og_image['content']}")
            return urljoin(url, og_image["content"])

        # 2. Find the most prominent <img> tag
        # (A simple heuristic: largest image in the main content area)
        # This can be improved with more sophisticated logic.
        main_content = soup.find("main") or soup.find("article") or soup.body
        if main_content:
            images = main_content.find_all("img")
            if images:
                largest_image = None
                max_area = 0
                for img in images:
                    try:
                        width = int(img.get("width", 0))
                        height = int(img.get("height", 0))
                        area = width * height
                        if area > max_area:
                            max_area = area
                            largest_image = img
                    except (ValueError, TypeError):
                        continue

                if largest_image and largest_image.get("src"):
                    logger.info(f"Found largest image: {largest_image['src']}")
                    return urljoin(url, largest_image["src"])

        logger.warning(f"No main image found for {url}.")
        return None

    def _generate_placeholder_image(self, title: str, path: Path) -> bool:
        """Creates a placeholder image with the title text."""
        try:
            output_cfg = app_config.get("output", {})
            width, height = output_cfg.get("width", 1280), output_cfg.get("height", 720)

            img = Image.new('RGB', (width, height), color = (30, 30, 30))
            d = ImageDraw.Draw(img)

            # Use a basic font. For better results, provide a path to a .ttf file.
            try:
                font = ImageFont.truetype("DejaVuSans.ttf", size=40)
            except IOError:
                font = ImageFont.load_default()

            # Simple text wrapping
            lines = []
            words = title.split()
            current_line = ""
            for word in words:
                if d.textlength(current_line + word, font=font) <= width * 0.8:
                    current_line += f" {word}"
                else:
                    lines.append(current_line.strip())
                    current_line = word
            lines.append(current_line.strip())

            text_y = (height - len(lines) * 45) / 2
            for line in lines:
                line_width = d.textlength(line, font=font)
                d.text((width - line_width) / 2, text_y, line, fill=(255, 255, 255), font=font)
                text_y += 45

            img.save(path)
            logger.info(f"Generated placeholder image at {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to generate placeholder image: {e}")
            return False

    def scrape_article(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Scrapes a single article for its main text and image URL.

        Returns:
            A tuple of (text_content, image_url).
        """
        logger.info(f"Scraping article from {url}")

        # trafilatura is good for text, but we'll use requests+BS4 for images
        # as it gives us more control.
        html_content = self._fetch_html(url)
        if not html_content:
            return None, None

        # Extract text with trafilatura
        text_content = extract(html_content, include_comments=False, include_tables=False)

        # Extract image with BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        image_url = self._extract_main_image(url, soup)

        if not text_content:
            logger.warning(f"Could not extract main text from {url}")

        return text_content, image_url

def process_feeds():
    """
    Main function to ingest items from RSS feeds defined in the config.
    """
    ingest_config = app_config.get("ingest", {})
    scraper = Scraper()
    new_items_count = 0

    for feed_url in ingest_config.get("rss_feeds", []):
        logger.info(f"Processing RSS feed: {feed_url}")
        feed = feedparser.parse(feed_url)

        if feed.bozo:
            logger.warning(f"Feed {feed_url} is ill-formed. Reason: {feed.bozo_exception}")

        for entry in feed.entries:
            # Check if we have reached the max items for this run
            if new_items_count >= ingest_config.get("max_items_per_run", 10):
                logger.info(f"Reached max items per run ({ingest_config['max_items_per_run']}). Stopping.")
                return

            guid = entry.get("guid", entry.link)
            link = entry.link

            # --- Deduplication ---
            if manifest.find_by_guid_or_link(guid, link):
                logger.debug(f"Skipping duplicate item: {entry.title}")
                continue

            # --- Date Filtering ---
            min_pubdate_hours = ingest_config.get("min_pubdate_hours", 0)
            if min_pubdate_hours > 0 and "published_parsed" in entry:
                pub_date = datetime.fromtimestamp(time.mktime(entry.published_parsed)).astimezone(timezone.utc)
                if pub_date < datetime.now(timezone.utc) - timedelta(hours=min_pubdate_hours):
                    logger.debug(f"Skipping old item: {entry.title}")
                    continue

            logger.info(f"Found new item: '{entry.title}' from {link}")

            # --- Scrape Content ---
            text, image_url = scraper.scrape_article(link)
            if not text:
                logger.warning(f"No text extracted for '{entry.title}'. Skipping.")
                continue

            item_id = manifest.generate_id()
            text_path = RAW_DIR / f"{item_id}_text.txt"
            image_path = RAW_DIR / f"{item_id}_image.jpg"

            # --- Save Text ---
            with open(text_path, "w", encoding="utf-8") as f:
                f.write(text)

            # --- Save Image ---
            if image_url:
                try:
                    with requests.get(image_url, stream=True, headers=scraper.headers) as r:
                        r.raise_for_status()
                        with open(image_path, 'wb') as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                except requests.RequestException as e:
                    logger.error(f"Failed to download image {image_url}: {e}. Generating placeholder.")
                    scraper._generate_placeholder_image(entry.title, image_path)
            else:
                scraper._generate_placeholder_image(entry.title, image_path)

            # --- Create Manifest Entry ---
            now = datetime.now(timezone.utc).isoformat()

            manifest_item = ManifestItem(
                id=item_id,
                source={
                    "type": SourceType.RSS,
                    "feed": feed_url,
                    "link": link,
                    "guid": guid,
                },
                title=entry.title,
                original_text=text,
                processed_text=text, # Can be modified later
                paths={
                    "text": str(text_path),
                    "image": str(image_path),
                    "audio": None,
                    "clip": None,
                    "final": None,
                },
                duration_s=None,
                state=ItemState.INGESTED,
                created_at=now,
                updated_at=now,
                approved_by=None,
                rejected_reason=None,
                auto_approval=None,
                notes=None,
                retries=0
            )

            manifest.add_item(manifest_item)
            new_items_count += 1

    logger.info(f"Ingestion run complete. Found {new_items_count} new items.")
