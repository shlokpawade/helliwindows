"""
tray.py – Optional system-tray icon for Jarvis.

Provides a coloured dot icon in the notification area and a right-click
context menu (Mute/Unmute + Quit).

This module is OPTIONAL: if pystray or Pillow is not installed the import
silently fails and JarvisAssistant runs without a tray icon.

Install optional dependencies:
    pip install pystray Pillow
"""

from __future__ import annotations

import threading
from typing import Callable

try:
    import pystray  # type: ignore[import]
    from PIL import Image, ImageDraw  # type: ignore[import]
    _TRAY_AVAILABLE = True
except ImportError:
    _TRAY_AVAILABLE = False


def _make_icon_image(color: str) -> "Image.Image":
    """Create a simple 64×64 filled-circle icon of the given hex colour."""
    from PIL import Image, ImageDraw  # type: ignore[import]
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=color)
    return img


class TrayIcon:
    """
    System-tray status indicator.

    Status colours:
      "ready"     → green  (#22cc44)
      "listening" → blue   (#00aaff)
      "muted"     → red    (#dd2222)

    Call :meth:`start` once to launch the icon in a daemon thread.
    Call :meth:`set_status` (thread-safe) to change the icon colour.
    Call :meth:`stop` to remove the icon cleanly.
    """

    _STATUS_COLORS: dict[str, str] = {
        "ready":     "#22cc44",
        "listening": "#00aaff",
        "muted":     "#dd2222",
    }

    def __init__(self, on_quit: Callable[[], None] | None = None) -> None:
        self._on_quit = on_quit
        self._icon: "pystray.Icon | None" = None
        self._muted = False
        self._status = "ready"

    # ------------------------------------------------------------------
    # Menu helpers
    # ------------------------------------------------------------------

    def _build_menu(self) -> "pystray.Menu":
        import pystray  # type: ignore[import]
        mute_label = "Unmute" if self._muted else "Mute"
        return pystray.Menu(
            pystray.MenuItem("Jarvis – Windows Assistant", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(mute_label, self._toggle_mute),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

    def _toggle_mute(self, icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
        self._muted = not self._muted
        self.set_status("muted" if self._muted else "ready")

    def _quit(self, icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
        icon.stop()
        if self._on_quit is not None:
            self._on_quit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_status(self, status: str) -> None:
        """Update the tray-icon colour.  Safe to call from any thread."""
        self._status = status
        if self._icon is not None:
            color = self._STATUS_COLORS.get(status, self._STATUS_COLORS["ready"])
            self._icon.icon = _make_icon_image(color)
            self._icon.menu = self._build_menu()

    def start(self) -> None:
        """Create and run the tray icon in a background daemon thread."""
        if not _TRAY_AVAILABLE:
            return
        import pystray  # type: ignore[import]
        icon_img = _make_icon_image(self._STATUS_COLORS["ready"])
        self._icon = pystray.Icon(
            "Jarvis",
            icon_img,
            "Jarvis – Windows Assistant",
            self._build_menu(),
        )
        t = threading.Thread(target=self._icon.run, name="tray-icon", daemon=True)
        t.start()

    def stop(self) -> None:
        """Remove the tray icon."""
        if self._icon is not None:
            self._icon.stop()
