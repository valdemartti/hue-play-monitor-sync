"""Test script: Set a static rainbow gradient on gradient lights.

Usage: python -m tests.test_gradient
"""

import asyncio
import sys

from src.config_manager import load_config
from src.hue_bridge import HueBridgeClient

# Rainbow in CIE xy (approximate) — full palette, sliced per light
RAINBOW_COLORS = [
    (0.6400, 0.3300),  # Red
    (0.5500, 0.4000),  # Orange
    (0.4500, 0.4800),  # Yellow
    (0.2100, 0.7000),  # Green
    (0.1700, 0.3500),  # Cyan
    (0.1600, 0.1000),  # Blue
    (0.3200, 0.1500),  # Purple
]


def make_rainbow(zone_count: int) -> list[tuple[float, float]]:
    """Pick evenly spaced rainbow colors for the given zone count."""
    if zone_count >= len(RAINBOW_COLORS):
        return RAINBOW_COLORS[:zone_count]
    step = len(RAINBOW_COLORS) / zone_count
    return [RAINBOW_COLORS[int(i * step)] for i in range(zone_count)]


async def main():
    config = load_config()
    if not config.bridge.ip or not config.bridge.app_key:
        print("Run first-run setup first: python -m src.main")
        sys.exit(1)

    bridge = HueBridgeClient(config.bridge.ip, config.bridge.app_key)

    lights = await bridge.discover_gradient_lights()
    if not lights:
        print("No gradient lights found")
        await bridge.close()
        sys.exit(1)

    print(f"Setting rainbow gradient on {len(lights)} light(s)...")
    for light in lights:
        gradient = make_rainbow(light.zone_count)
        await bridge.turn_on(light.id)
        await bridge.set_gradient(light.id, gradient, brightness=80)
        print(f"  ✓ {light.name} ({light.zone_count} zones)")

    print("\nDone! You should see a rainbow gradient on your lightstrips.")
    print("Press Enter to turn them off...")
    input()

    for light in lights:
        await bridge.turn_off(light.id)

    await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
