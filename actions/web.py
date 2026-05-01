"""
actions/web.py – Browser-based web actions (offline browser, online content).

Uses the system's default browser via webbrowser module – no API keys needed.
"""

import urllib.parse
import webbrowser

from utils import logger, speak


class WebActions:
    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def web_search(self, query: str) -> None:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded}"
        logger.info("Web search: %s", query)
        speak(f"Searching for {query}.")
        webbrowser.open(url)

    # ------------------------------------------------------------------
    # YouTube
    # ------------------------------------------------------------------
    def youtube_search(self, query: str) -> None:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        logger.info("YouTube search: %s", query)
        speak(f"Searching YouTube for {query}.")
        webbrowser.open(url)

    # ------------------------------------------------------------------
    # Open URL directly
    # ------------------------------------------------------------------
    def open_url(self, query: str) -> None:
        url = query if query.startswith("http") else f"https://{query}"
        logger.info("Opening URL: %s", url)
        speak(f"Opening {url}.")
        webbrowser.open(url)
