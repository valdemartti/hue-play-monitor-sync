"""Entry point for Desktop Lights."""

import asyncio
import logging
import sys

from .config_manager import AppConfig, AvailableLight, LightMapping, load_config, save_config
from .hue_bridge import HueBridgeClient
from .screen_capture import ScreenCapture


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def first_run_setup():
    """Interactive first-run setup: discover bridge, authenticate, find lights."""
    config = load_config()

    # Step 1: Discover bridge
    if not config.bridge.ip:
        print("Searching for Hue Bridge...")
        ip = await HueBridgeClient.discover_bridge()
        if ip:
            print(f"Found bridge at {ip}")
            config.bridge.ip = ip
        else:
            config.bridge.ip = input("Enter Hue Bridge IP: ").strip()

    bridge = HueBridgeClient(config.bridge.ip)

    # Step 2: Authenticate
    if not config.bridge.app_key:
        input("Press the link button on your Hue Bridge, then press Enter...")
        try:
            app_key = await bridge.authenticate()
            config.bridge.app_key = app_key
            print("Authentication successful!")
        except RuntimeError as e:
            print(f"Authentication failed: {e}")
            sys.exit(1)
    else:
        bridge.app_key = config.bridge.app_key

    # Step 3: Discover gradient lights
    print("Discovering gradient lights...")
    lights = await bridge.discover_gradient_lights()

    if not lights:
        print("No gradient-capable lights found.")
        await bridge.close()
        sys.exit(1)

    print(f"\nFound {len(lights)} gradient light(s):")
    for i, light in enumerate(lights):
        print(f"  {i + 1}. {light.name} ({light.zone_count} zones) [{light.id}]")

    # Store available lights
    config.available_lights = [
        AvailableLight(id=l.id, name=l.name, zone_count=l.zone_count)
        for l in lights
    ]

    # Step 4: Detect monitors and create initial profile
    cap = ScreenCapture()
    fingerprint = cap.get_fingerprint()
    monitors = cap.get_monitors()
    cap.close()

    print(f"\nDetected {len(monitors)} monitor(s) (layout: {fingerprint}):")
    for mon in monitors:
        print(f"  {mon.label} at ({mon.left}, {mon.top})")

    print("\nAssign lights to monitors (enter light number, or 0 to skip):")
    mappings = []
    for mon in monitors:
        while True:
            choice = input(f"  {mon.label} → light [0-{len(lights)}]: ").strip()
            if not choice:
                break
            try:
                idx = int(choice)
                if idx == 0:
                    break
                if 1 <= idx <= len(lights):
                    light = lights[idx - 1]
                    rev = input(f"    Reversed? [y/N]: ").strip().lower() == "y"
                    mappings.append(LightMapping(
                        monitor=mon.index,
                        light_id=light.id,
                        light_name=light.name,
                        reversed=rev,
                        zone_count=light.zone_count,
                    ))
                    break
                else:
                    print(f"    Enter 0-{len(lights)}")
            except ValueError:
                print(f"    Enter a number 0-{len(lights)}")

    config.set_mappings_for_fingerprint(fingerprint, mappings)

    save_config(config)
    print(f"\nConfig saved with {len(mappings)} mapping(s) for layout '{fingerprint}'.")
    await bridge.close()
    return config


def main():
    """Main entry point."""
    config = load_config()

    needs_setup = not config.bridge.ip or not config.bridge.app_key or not config.available_lights
    if needs_setup:
        print("=== Desktop Lights First-Run Setup ===\n")
        asyncio.run(first_run_setup())
        print("\nSetup complete. Run again to start the tray app, or use: python -m ui.tray_app")
    else:
        # Launch tray app
        from ui.tray_app import run_tray_app
        run_tray_app()


if __name__ == "__main__":
    main()
