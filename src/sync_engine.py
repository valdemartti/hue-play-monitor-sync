"""Async sync engine: capture screens → process colors → update lights."""

import asyncio
import logging
import time

from .color_processing import (
    color_distance, rgb_array_brightness, rgb_array_to_xy, smooth_colors,
)
from .config_manager import AppConfig, LightMapping
from .hue_bridge import HueBridgeClient
from .screen_capture import ScreenCapture
from .zone_mapper import sample_zone_colors

logger = logging.getLogger(__name__)


class SyncEngine:
    def __init__(self, config: AppConfig, bridge: HueBridgeClient):
        self.config = config
        self.bridge = bridge
        self.capture = ScreenCapture()
        self._running = False
        self._task: asyncio.Task | None = None
        self._previous_colors: dict[str, list[tuple[float, float]]] = {}
        self._light_is_on: dict[str, bool] = {}
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

        # Assume lights are on at start
        for m in valid:
            self._light_is_on[m.light_id] = True

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

    def _process_monitor(self, mapping: LightMapping) -> tuple[list[tuple[float, float]] | None, float]:
        """Capture and process one monitor's colors.

        Returns:
            (colors, peak_brightness) — colors is None if no update needed.
            peak_brightness is the max zone luminance (0-1).
        """
        try:
            frame = self.capture.capture(mapping.monitor)
        except ValueError as e:
            logger.warning("Capture failed for monitor %d: %s", mapping.monitor, e)
            return None, 0.0

        zone_rgb = sample_zone_colors(
            frame,
            num_zones=mapping.zone_count,
            margin_percent=self.config.sync.margin_percent,
            stride=self.config.sync.downsample_stride,
            reversed_zones=mapping.reversed,
        )

        # Compute per-zone brightness before color conversion
        zone_brightness = rgb_array_brightness(zone_rgb)
        peak_brightness = max(zone_brightness)

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
                return None, peak_brightness

        self._previous_colors[mapping.light_id] = smoothed
        return smoothed, peak_brightness

    async def _run_loop(self):
        target_interval = 1.0 / self.config.sync.fps
        black_threshold = self.config.sync.black_threshold
        min_brightness = self.config.sync.min_brightness
        max_brightness = self.config.sync.brightness

        while self._running:
            loop_start = time.monotonic()

            updates = []
            for mapping in self._active_mappings:
                colors, peak = self._process_monitor(mapping)
                is_on = self._light_is_on.get(mapping.light_id, True)
                all_dark = peak < black_threshold

                if all_dark and is_on:
                    # Screen went dark — turn off
                    updates.append(self.bridge.turn_off(mapping.light_id))
                    self._light_is_on[mapping.light_id] = False
                    logger.debug("Turning off %s (dark content)", mapping.light_id)
                elif not all_dark and not is_on:
                    # Content appeared — turn on, then send gradient
                    updates.append(self.bridge.turn_on(mapping.light_id))
                    self._light_is_on[mapping.light_id] = True
                    logger.debug("Turning on %s (content detected)", mapping.light_id)
                    if colors is not None:
                        # Scale brightness by peak luminance
                        scaled = max(min_brightness, peak * max_brightness)
                        updates.append(
                            self.bridge.set_gradient(mapping.light_id, colors, brightness=scaled)
                        )
                elif not all_dark and colors is not None:
                    # Normal update — scale brightness by peak luminance
                    scaled = max(min_brightness, peak * max_brightness)
                    updates.append(
                        self.bridge.set_gradient(mapping.light_id, colors, brightness=scaled)
                    )

            if updates:
                await asyncio.gather(*updates)

            elapsed = time.monotonic() - loop_start
            self._actual_fps = 1.0 / elapsed if elapsed > 0 else 0

            sleep_time = target_interval - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
