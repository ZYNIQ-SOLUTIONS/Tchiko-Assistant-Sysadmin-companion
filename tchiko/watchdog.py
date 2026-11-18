"""Proactive Background System Watchdog for Tchiko Assistant.

Periodically inspects `/proc` resource thresholds (RAM > 90%, Disk > 90%, high load)
and failed systemd units in a daemon thread, notifying the desktop companion via
a thread-safe callback when a new anomaly is detected.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from typing import Callable, Dict, Optional

from .system_tools import LinuxSystemToolkit


class SystemWatchdog:
    """Lightweight background anomaly detector with alert cooldown deduplication."""

    def __init__(
        self,
        toolkit: LinuxSystemToolkit,
        on_anomaly: Callable[[str], None],
        interval_sec: float = 45.0,
        cooldown_sec: float = 600.0,
        ram_threshold_pct: float = 90.0,
        disk_threshold_pct: float = 90.0,
    ) -> None:
        self.toolkit = toolkit
        self.on_anomaly = on_anomaly
        self.interval_sec = max(5.0, float(interval_sec))
        self.cooldown_sec = max(30.0, float(cooldown_sec))
        self.ram_threshold_pct = ram_threshold_pct
        self.disk_threshold_pct = disk_threshold_pct
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_alerts: Dict[str, float] = {}

    def check_once(self) -> Optional[str]:
        """Run one synchronous anomaly check; return an alert message if a threshold tripped."""
        now = time.monotonic()
        telemetry = self.toolkit.get_system_telemetry()
        alerts: list[str] = []

        ram_pct = float(telemetry.get("ram_pct", 0.0) or 0.0)
        if ram_pct >= self.ram_threshold_pct and self._should_notify("ram", now):
            alerts.append(f"RAM usage is critical ({ram_pct:.1f}%)")

        disk_pct = float(telemetry.get("disk_pct", 0.0) or 0.0)
        if disk_pct >= self.disk_threshold_pct and self._should_notify("disk", now):
            alerts.append(f"Root disk usage is critical ({disk_pct:.1f}%)")

        if shutil.which("systemctl"):
            try:
                proc = subprocess.run(
                    ["systemctl", "--failed", "--no-legend", "--plain"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                failed = [ln.strip().split()[0] for ln in proc.stdout.splitlines() if ln.strip()]
                if failed and self._should_notify("systemd:" + ",".join(failed[:3]), now):
                    alerts.append(f"Failed systemd units: {', '.join(failed[:3])}")
            except Exception:
                pass

        if not alerts:
            return None
        return "⚠️ **Watchdog Alert:** " + " • ".join(alerts) + "\nRun `/doctor` or `/systemd` to inspect."

    def _should_notify(self, key: str, now: float) -> bool:
        prev = self._last_alerts.get(key, -1e9)
        if (now - prev) < self.cooldown_sec:
            return False
        self._last_alerts[key] = now
        return True

    def start(self) -> None:
        """Start the background watchdog daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="tchiko-watchdog")
        self._thread.start()

    def stop(self) -> None:
        """Signal the watchdog thread to exit."""
        self._stop_event.set()

    def _loop(self) -> None:
        # Initial delay so startup stays snappy
        if self._stop_event.wait(12.0):
            return
        while not self._stop_event.is_set():
            try:
                msg = self.check_once()
                if msg:
                    self.on_anomaly(msg)
            except Exception:
                pass
            if self._stop_event.wait(self.interval_sec):
                break
