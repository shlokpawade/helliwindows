"""
actions/web.py – Browser-based web actions (offline browser, online content).

Uses the system's default browser via webbrowser module – no API keys needed.
"""

import re
import urllib.parse
import webbrowser

import requests

from utils import logger, speak, speak_async


def _get_first_youtube_video_id(query: str) -> str | None:
    """
    Scrape the YouTube search-results page and return the first video ID.
    Falls back to None if scraping fails (network error, rate-limit, etc.).
    """
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        # YouTube inlines video data as JSON; extract the first 11-char video ID.
        matches = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
        if matches:
            return matches[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch YouTube video ID for '%s': %s", query, exc)
    return None


class WebActions:
    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def web_search(self, query: str) -> None:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}"
        logger.info("Web search: %s", query)
        speak_async(f"Searching for {query} now.")
        webbrowser.open(url)

    # ------------------------------------------------------------------
    # YouTube
    # ------------------------------------------------------------------
    def youtube_search(self, query: str) -> None:
        speak_async(f"Playing {query} on YouTube.")
        video_id = _get_first_youtube_video_id(query)
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
            logger.info("YouTube auto-play: %s (id=%s)", query, video_id)
        else:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://www.youtube.com/results?search_query={encoded}"
            logger.info("YouTube search fallback: %s", query)
        webbrowser.open(url)

    def play_media(self, query: str) -> None:
        """Play media by finding and opening the first YouTube result."""
        speak_async(f"Playing {query}.")
        video_id = _get_first_youtube_video_id(query)
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}&autoplay=1"
            logger.info("Play media (YouTube auto-play): %s (id=%s)", query, video_id)
        else:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://www.youtube.com/results?search_query={encoded}"
            logger.info("Play media (YouTube search fallback): %s", query)
        webbrowser.open(url)

    # ------------------------------------------------------------------
    # Open URL directly
    # ------------------------------------------------------------------
    def open_url(self, query: str) -> None:
        url = query if query.startswith("http") else f"https://{query}"
        logger.info("Opening URL: %s", url)
        speak_async(f"Opening {url}.")
        webbrowser.open(url)
