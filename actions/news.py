"""
actions/news.py – News headlines from RSS / Atom feeds.

Uses only the standard library (xml.etree.ElementTree, urllib) so no extra
dependencies are required.  Feed URLs are configured in config.NEWS_FEEDS.
"""

import urllib.request
import xml.etree.ElementTree as ET
from urllib.error import URLError

from config import NEWS_FEEDS, NEWS_HEADLINES_COUNT
from utils import logger, speak, speak_async

# Decorator registry (populated by @register_action in actions/__init__.py)
_action_registry: dict = {}


class NewsActions:
    """Read out news headlines from RSS / Atom feeds."""

    # ------------------------------------------------------------------
    # Public action
    # ------------------------------------------------------------------

    def get_news(self, source: str = "", count: int = NEWS_HEADLINES_COUNT) -> None:
        """
        Fetch and read aloud *count* headlines.

        *source* can be a key from NEWS_FEEDS (e.g. "bbc"), a full URL, or
        empty to use the first configured feed.
        """
        url = self._resolve_url(source)
        if not url:
            speak("No news feed configured.")
            return

        speak_async("Fetching headlines.")
        data = self._fetch(url)
        if data is None:
            return

        titles = self._parse_headlines(data, count)
        if not titles:
            speak("I found no headlines in that feed.")
            return

        label = source.strip() or "top"
        speak(f"Here are the {label} news headlines.")
        for i, headline in enumerate(titles, start=1):
            speak(f"{i}. {headline}.")
        logger.info("Read %d headlines from %s", len(titles), url)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_url(source: str) -> str:
        if source:
            lower = source.strip().lower()
            if lower in NEWS_FEEDS:
                return NEWS_FEEDS[lower]
            if source.startswith("http"):
                return source
        # Default: first configured feed
        return next(iter(NEWS_FEEDS.values()), "")

    @staticmethod
    def _fetch(url: str) -> bytes | None:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 Jarvis-News/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read()
        except URLError as exc:
            logger.warning("News fetch failed (%s): %s", url, exc)
            speak("Sorry, I couldn't retrieve the news right now.")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("News fetch error: %s", exc)
            speak("Sorry, there was a problem fetching the news.")
            return None

    @staticmethod
    def _parse_headlines(data: bytes, count: int) -> list[str]:
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            logger.warning("News XML parse error: %s", exc)
            speak("I couldn't understand the news feed.")
            return []

        titles: list[str] = []

        # RSS 2.0: <rss><channel><item><title>
        for item in root.iter("item"):
            t = (item.findtext("title") or "").strip()
            if t:
                titles.append(t)
            if len(titles) >= count:
                return titles

        # Atom 1.0 fallback: <feed><entry><title>
        if not titles:
            atom_ns = "http://www.w3.org/2005/Atom"
            for entry in root.iter(f"{{{atom_ns}}}entry"):
                t_el = entry.find(f"{{{atom_ns}}}title")
                if t_el is not None and t_el.text:
                    titles.append(t_el.text.strip())
                if len(titles) >= count:
                    return titles

        return titles
