"""Async sync engine: capture screens → process colors → update lights."""

import asyncio
import logging
import time

from .color_processing import (
    color_distance, hex_to_rgb, rgb_array_to_xy, smooth_colors,
)
from .config_manager import AppConfig, LightMapping
from .hue_bridge import HueBridgeClient
from .screen_capture import ScreenCapture
from .zone_mapper import sample_zone_colors

logger = logging.getLogger(__name__)

# Zones with all channels below this are considered dark and filled with idle_color
_DARK_ZONE_THRESHOLD = 5.0


class SyncEngine:
    def __init__(self, config: AppConfig, bridge: HueBridgeClient):
        self.config = config
        self.bridge = bridge
        self.capture = ScreenCapture()
        self._running = False
        self._task: asyncio.Task | None = None
        self._previous_colors: dict[str, list[tuple[float, float]]] = {}
        self._actual_fps: float = 0.0
        self._active_mappings: list[LightMapping] = []
        self._active_fingerprint: str = ""

    @property
    def running(self) -> bool:
        return self._running

    @property
    def actual_fps(self) -> float:
        return self._actual_fps

    @property
    def active_fingerprint(self) -> str:
        return self._active_fingerprint

    @property
    def active_mappings(self) -> list[LightMapping]:
        return self._active_mappings

    def resolve_profile(self) -> tuple[str, list[LightMapping]]:
        """Detect current monitors and find matching profile."""
        fingerprint = self.capture.get_fingerprint()
        mappings = self.config.get_mappings_for_fingerprint(fingerprint)
        return fingerprint, mappings

    async def start(self):
        """Start the sync loop."""
        if self._running:
            return

        fingerprint, mappings = self.resolve_profile()
        self._active_fingerprint = fingerprint
        self._active_mappings = mappings

        if not mappings:
            logger.warning("No profile for monitor layout '%s'. Configure mappings first.", fingerprint)
            return

        # Validate monitor indices
        max_mon = self.capture.monitor_count
        valid = [m for m in mappings if 1 <= m.monitor <= max_mon]
        if len(valid) < len(mappings):
            logger.warning("Some mappings reference unavailable monitors (have %d)", max_mon)
        self._active_mappings = valid

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "Sync started: profile '%s', %d light(s), target %d FPS",
            fingerprint, len(valid), self.config.sync.fps,
        )

    async def stop(self):
        """Stop the sync loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.capture.close()
        logger.info("Sync engine stopped")

    def _process_monitor(self, mapping: LightMapping) -> list[tuple[float, float]] | None:
        """Capture and process one monitor's colors.

        Returns:
            colors as CIE xy tuples, or None if no update needed.
        """
        try:
            frame = self.capture.capture(mapping.monitor)
        except ValueError as e:
            logger.warning("Capture failed for monitor %d: %s", mapping.monitor, e)
            return None

        zone_rgb = sample_zone_colors(
            frame,
            num_zones=mapping.zone_count,
            margin_percent=self.config.sync.margin_percent,
            stride=self.config.sync.downsample_stride,
            reversed_zones=mapping.reversed,
        )

        # Replace dark zones with the configured idle color
        idle_rgb = hex_to_rgb(self.config.sync.idle_color)
        for i in range(len(zone_rgb)):
            if zone_rgb[i].max() < _DARK_ZONE_THRESHOLD:
                zone_rgb[i] = idle_rgb

        current_xy = rgb_array_to_xy(zone_rgb)

        # Temporal smoothing
        previous = self._previous_colors.get(mapping.light_id)
        smoothed = smooth_colors(current_xy, previous, self.config.sync.smoothing_alpha)

        # Check if colors changed enough
        if previous:
            max_delta = max(
                color_distance(s, p) for s, p in zip(smoothed, previous)
            )
            if max_delta < self.config.sync.delta_threshold:
                return None

        self._previous_colors[mapping.light_id] = smoothed
        return smoothed

    async def _run_loop(self):
        target_interval = 1.0 / self.config.sync.fps
        brightness = self.config.sync.brightness

        while self._running:
            loop_start = time.monotonic()

            updates = []
            for mapping in self._active_mappings:
                colors = self._process_monitor(mapping)
                if colors is not None:
                    updates.append(
                        self.bridge.set_gradient(mapping.light_id, colors, brightness=brightness)
                    )

            if updates:
                await asyncio.gather(*updates)

            elapsed = time.monotonic() - loop_start
            self._actual_fps = 1.0 / elapsed if elapsed > 0 else 0

            sleep_time = target_interval - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
