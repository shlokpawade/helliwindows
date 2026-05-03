"""
actions/network.py – Network and Wi-Fi diagnostic actions.

All operations use subprocess + built-in Windows tools (ping, netsh,
ipconfig).  No additional Python packages are required.
"""

import re
import subprocess

from utils import logger, speak, speak_async


class NetworkActions:
    """Network / connectivity diagnostics for Windows."""

    # ------------------------------------------------------------------
    # Internet check
    # ------------------------------------------------------------------

    def check_internet(self) -> None:
        """Ping a public DNS server and report latency."""
        try:
            result = subprocess.run(
                ["ping", "-n", "3", "8.8.8.8"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            output = result.stdout
            avg_match = re.search(r"Average\s*=\s*(\d+)ms", output, re.IGNORECASE)
            if result.returncode == 0 and avg_match:
                speak(
                    f"Internet is connected. "
                    f"Average latency is {avg_match.group(1)} milliseconds."
                )
            elif result.returncode == 0:
                speak("Internet is connected.")
            else:
                speak("Internet appears to be disconnected or unreachable.")
            logger.info("check_internet returncode=%d", result.returncode)
        except subprocess.TimeoutExpired:
            speak("Internet check timed out.")
        except FileNotFoundError:
            speak("ping command not found on this system.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("check_internet failed: %s", exc)
            speak("Sorry, I couldn't check the internet connection.")

    # ------------------------------------------------------------------
    # Wi-Fi networks
    # ------------------------------------------------------------------

    def list_wifi_networks(self) -> None:
        """List nearby Wi-Fi SSIDs via netsh."""
        try:
            result = subprocess.run(
                ["netsh", "wlan", "show", "networks"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            if result.returncode != 0:
                speak("I couldn't list Wi-Fi networks. Make sure Wi-Fi is enabled.")
                return

            ssids = re.findall(r"SSID\s+\d+\s*:\s+(.+)", result.stdout)
            ssids = [s.strip() for s in ssids if s.strip()]
            if not ssids:
                speak("No Wi-Fi networks found nearby.")
                return

            speak(f"I found {len(ssids)} network{'s' if len(ssids) != 1 else ''} nearby.")
            for i, ssid in enumerate(ssids[:8], start=1):
                speak(f"{i}: {ssid}.")
            logger.info("Listed %d Wi-Fi networks", len(ssids))
        except FileNotFoundError:
            speak("netsh command not available. This feature requires Windows.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("list_wifi_networks failed: %s", exc)
            speak("Sorry, I couldn't list Wi-Fi networks.")

    # ------------------------------------------------------------------
    # Wi-Fi connect
    # ------------------------------------------------------------------

    def connect_wifi(self, ssid: str = "") -> None:
        """Connect to a saved Wi-Fi network by SSID."""
        if not ssid.strip():
            speak("Please specify the Wi-Fi network name.")
            return
        # Reject shell-injection characters
        _unsafe = set(';&|<>`$\'"\\')
        if any(c in _unsafe for c in ssid):
            speak("That network name contains invalid characters.")
            return

        speak_async(f"Connecting to {ssid}.")
        try:
            result = subprocess.run(
                ["netsh", "wlan", "connect", f"name={ssid}"],
                capture_output=True, text=True, timeout=15, check=False,
            )
            if result.returncode == 0:
                speak(f"Connected to {ssid}.")
            else:
                speak(
                    f"I couldn't connect to {ssid}. "
                    "Make sure the network profile exists on this device."
                )
            logger.info("connect_wifi '%s' rc=%d", ssid, result.returncode)
        except FileNotFoundError:
            speak("netsh command not available. This feature requires Windows.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("connect_wifi failed: %s", exc)
            speak(f"Sorry, I couldn't connect to {ssid}.")

    # ------------------------------------------------------------------
    # IP address
    # ------------------------------------------------------------------

    def get_ip_address(self) -> None:
        """Read out the current IPv4 address(es)."""
        try:
            result = subprocess.run(
                ["ipconfig"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            ips = re.findall(r"IPv4 Address[^:]*:\s*([\d.]+)", result.stdout)
            # Exclude loopback
            ips = [ip for ip in ips if not ip.startswith("127.")]
            if ips:
                speak(f"Your IP address is {ips[0]}.")
                if len(ips) > 1:
                    speak(
                        f"Other addresses: {', '.join(ips[1:])}."
                    )
            else:
                speak("I couldn't find your IP address.")
            logger.info("get_ip_address: %s", ips)
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_ip_address failed: %s", exc)
            speak("Sorry, I couldn't retrieve your IP address.")
