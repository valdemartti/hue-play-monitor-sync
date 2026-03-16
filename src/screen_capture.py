"""Screen capture using mss for fast monitor screenshots."""

import logging
from dataclasses import dataclass

import mss
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MonitorInfo:
    """Info about a connected monitor."""
    index: int          # 1-based mss index
    left: int           # x position
    top: int            # y position
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"Monitor {self.index} ({self.width}x{self.height})"


class ScreenCapture:
    def __init__(self):
        self._sct: mss.mss | None = None

    def _get_sct(self) -> mss.mss:
        if self._sct is None:
            self._sct = mss.mss()
        return self._sct

    @property
    def monitor_count(self) -> int:
        """Number of physical monitors (excludes virtual combined monitor at index 0)."""
        return len(self._get_sct().monitors) - 1

    def get_monitors(self) -> list[MonitorInfo]:
        """Get info about all connected monitors, sorted by x position (left to right)."""
        sct = self._get_sct()
        monitors = []
        for i in range(1, len(sct.monitors)):
            m = sct.monitors[i]
            monitors.append(MonitorInfo(
                index=i,
                left=m["left"],
                top=m["top"],
                width=m["width"],
                height=m["height"],
            ))
        monitors.sort(key=lambda m: (m.left, m.top))
        return monitors

    def get_fingerprint(self) -> str:
        """Generate a stable fingerprint for the current monitor configuration.

        Format: resolutions sorted by position, e.g. "1920x1080_2560x1440_1920x1080"
        This identifies a unique physical arrangement.
        """
        monitors = self.get_monitors()
        return "_".join(f"{m.width}x{m.height}" for m in monitors)

    def capture(self, monitor_index: int) -> np.ndarray:
        """Capture a monitor and return RGB numpy array.

        Args:
            monitor_index: 1-based monitor index (1 = first monitor, 2 = second)

        Returns:
            HxWx3 numpy array in RGB order
        """
        sct = self._get_sct()
        if monitor_index < 1 or monitor_index > self.monitor_count:
            raise ValueError(f"Monitor {monitor_index} not available (have {self.monitor_count})")

        monitor = sct.monitors[monitor_index]
        screenshot = sct.grab(monitor)

        # mss returns BGRA; convert to RGB
        frame = np.frombuffer(screenshot.rgb, dtype=np.uint8)
        frame = frame.reshape((screenshot.height, screenshot.width, 3))
        return frame

    def close(self):
        if self._sct is not None:
            self._sct.close()
            self._sct = None
