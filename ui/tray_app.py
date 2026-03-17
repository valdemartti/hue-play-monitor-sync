"""macOS menu bar tray app using rumps."""

import asyncio
import logging
import threading

import rumps

from src.config_manager import (
    AppConfig, AvailableLight, LightMapping,
    load_config, save_config,
)
from src.hue_bridge import HueBridgeClient
from src.screen_capture import ScreenCapture
from src.sync_engine import SyncEngine

logger = logging.getLogger(__name__)


class DesktopLightsApp(rumps.App):
    def __init__(self, config: AppConfig):
        super().__init__("💡", quit_button=None)
        self.config = config
        self.bridge = HueBridgeClient(config.bridge.ip, config.bridge.app_key)
        self.engine = SyncEngine(config, self.bridge)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

        self._build_menu()
        self._auto_start()

    def _auto_start(self):
        """Automatically start sync if a profile exists for the current layout."""
        fingerprint = self._get_current_fingerprint()
        mappings = self.config.get_mappings_for_fingerprint(fingerprint)
        if mappings:
            self._ensure_loop()
            self._run_async(self.engine.start())
            self.title = "💡✓"
            # Update menu item title
            for item in self.menu.values():
                if hasattr(item, "title") and item.title == "Start Sync":
                    item.title = "Stop Sync"
                    break
            self._fps_timer_start()
            logger.info("Auto-started sync for layout '%s'", fingerprint)

    def _build_menu(self):
        items = [
            rumps.MenuItem("Start Sync", callback=self._toggle_sync),
            None,
            rumps.MenuItem("FPS: --"),
            None,
        ]

        # Show current monitor layout and profile
        cap = ScreenCapture()
        fingerprint = cap.get_fingerprint()
        monitors = cap.get_monitors()
        cap.close()

        items.append(rumps.MenuItem(f"Layout: {fingerprint}"))

        mappings = self.config.get_mappings_for_fingerprint(fingerprint)
        if mappings:
            for m in mappings:
                name = m.light_name or m.light_id[:12]
                mon_label = f"Mon {m.monitor}"
                items.append(rumps.MenuItem(f"  {name} → {mon_label} {'(rev)' if m.reversed else ''}"))
        else:
            items.append(rumps.MenuItem("  No lights mapped for this layout"))

        items.append(None)

        # Map lights submenu — one entry per light
        map_menu = rumps.MenuItem("Map Lights")
        for light in self.config.available_lights:
            light_menu = rumps.MenuItem(f"{light.name} ({light.zone_count} zones)")

            # Find current mapping for this light
            current = next((m for m in mappings if m.light_id == light.id), None)

            # "Unmapped" option
            none_item = rumps.MenuItem("Unmapped")
            none_item._custom_data = {"light_id": light.id, "monitor": None}
            none_item.set_callback(self._assign_light)
            if current is None:
                none_item.state = 1
            light_menu.add(none_item)

            # One option per monitor
            for mon in monitors:
                mon_item = rumps.MenuItem(mon.label)
                mon_item._custom_data = {
                    "light_id": light.id,
                    "light_name": light.name,
                    "zone_count": light.zone_count,
                    "monitor": mon.index,
                }
                mon_item.set_callback(self._assign_light)
                if current and current.monitor == mon.index:
                    mon_item.state = 1
                light_menu.add(mon_item)

            # Toggle reversed
            is_reversed = current.reversed if current else False
            rev_item = rumps.MenuItem(f"Reversed: {'Yes' if is_reversed else 'No'}")
            rev_item._custom_data = {"light_id": light.id}
            rev_item.set_callback(self._toggle_reversed)
            light_menu.add(None)
            light_menu.add(rev_item)

            map_menu.add(light_menu)

        if not self.config.available_lights:
            map_menu.add(rumps.MenuItem("No lights discovered yet"))

        items.append(map_menu)

        # Brightness submenu
        brightness_menu = rumps.MenuItem("Brightness")
        current_brightness = self.config.sync.brightness
        for level in [20, 40, 60, 80, 100]:
            label = f"{level}%"
            item = rumps.MenuItem(label, callback=self._set_brightness)
            item._custom_data = {"brightness": level}
            if abs(current_brightness - level) < 1:
                item.state = 1
            brightness_menu.add(item)
        items.append(brightness_menu)

        items.extend([
            rumps.MenuItem("Setup Bridge", callback=self._setup_bridge),
            rumps.MenuItem("Discover Lights", callback=self._discover_lights),
            None,
            rumps.MenuItem("Quit", callback=self._quit),
        ])

        self.menu.clear()
        for item in items:
            self.menu.add(item)

    def _get_current_fingerprint(self) -> str:
        cap = ScreenCapture()
        fp = cap.get_fingerprint()
        cap.close()
        return fp

    def _assign_light(self, sender):
        data = sender._custom_data
        light_id = data["light_id"]
        monitor = data.get("monitor")

        fingerprint = self._get_current_fingerprint()
        mappings = list(self.config.get_mappings_for_fingerprint(fingerprint))

        # Remove existing mapping for this light
        mappings = [m for m in mappings if m.light_id != light_id]

        # Add new mapping if a monitor was selected
        if monitor is not None:
            mappings.append(LightMapping(
                monitor=monitor,
                light_id=light_id,
                light_name=data.get("light_name", ""),
                reversed=False,
                zone_count=data.get("zone_count", 5),
            ))

        self.config.set_mappings_for_fingerprint(fingerprint, mappings)
        save_config(self.config)

        # Rebuild engine and menu
        self.engine = SyncEngine(self.config, self.bridge)
        self._build_menu()

    def _set_brightness(self, sender):
        level = sender._custom_data["brightness"]
        self.config.sync.brightness = float(level)
        save_config(self.config)
        # Restart engine so it picks up new brightness
        if self.engine.running:
            self._run_async(self.engine.stop())
            self.engine = SyncEngine(self.config, self.bridge)
            self._run_async(self.engine.start())
        else:
            self.engine = SyncEngine(self.config, self.bridge)
        self._build_menu()

    def _toggle_reversed(self, sender):
        data = sender._custom_data
        light_id = data["light_id"]

        fingerprint = self._get_current_fingerprint()
        mappings = self.config.get_mappings_for_fingerprint(fingerprint)

        for m in mappings:
            if m.light_id == light_id:
                m.reversed = not m.reversed
                break

        self.config.set_mappings_for_fingerprint(fingerprint, mappings)
        save_config(self.config)
        self.engine = SyncEngine(self.config, self.bridge)
        self._build_menu()

    def _ensure_loop(self):
        """Start an asyncio event loop in a background thread."""
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self._thread.start()

    def _run_async(self, coro):
        """Schedule a coroutine on the background event loop and wait for result."""
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=30)

    def _toggle_sync(self, sender):
        self._ensure_loop()
        if self.engine.running:
            self._run_async(self.engine.stop())
            sender.title = "Start Sync"
            self.title = "💡"
            self._fps_timer_stop()
        else:
            fingerprint = self._get_current_fingerprint()
            mappings = self.config.get_mappings_for_fingerprint(fingerprint)
            if not mappings:
                rumps.alert(
                    "No lights mapped for this monitor layout.\n\n"
                    f"Layout: {fingerprint}\n\n"
                    "Use 'Map Lights' to assign lights to monitors."
                )
                return
            self._run_async(self.engine.start())
            sender.title = "Stop Sync"
            self.title = "💡✓"
            self._fps_timer_start()

    def _fps_timer_start(self):
        self._fps_timer = rumps.Timer(self._update_fps, 1)
        self._fps_timer.start()

    def _fps_timer_stop(self):
        if hasattr(self, "_fps_timer"):
            self._fps_timer.stop()

    def _update_fps(self, _):
        fps = self.engine.actual_fps
        for item in self.menu.values():
            if hasattr(item, "title") and item.title.startswith("FPS:"):
                item.title = f"FPS: {fps:.1f}"
                break

    def _setup_bridge(self, _):
        self._ensure_loop()

        if not self.config.bridge.ip:
            rumps.alert("Searching for Hue Bridge...")
            ip = self._run_async(HueBridgeClient.discover_bridge())
            if ip:
                self.config.bridge.ip = ip
                self.bridge.ip = ip
                self.bridge._base_url = f"https://{ip}"
            else:
                resp = rumps.Window(
                    message="Could not auto-discover bridge. Enter IP manually:",
                    title="Bridge IP",
                    default_text="192.168.1.x",
                ).run()
                if resp.clicked:
                    self.config.bridge.ip = resp.text.strip()
                    self.bridge.ip = resp.text.strip()
                    self.bridge._base_url = f"https://{resp.text.strip()}"
                else:
                    return

        rumps.alert("Press the link button on your Hue Bridge, then click OK.")
        try:
            app_key = self._run_async(self.bridge.authenticate())
            self.config.bridge.app_key = app_key
            save_config(self.config)
            rumps.alert(f"Paired successfully! Bridge at {self.config.bridge.ip}")
        except RuntimeError as e:
            rumps.alert(f"Pairing failed: {e}")

    def _discover_lights(self, _):
        if not self.config.bridge.app_key:
            rumps.alert("Setup bridge first.")
            return

        self._ensure_loop()
        lights = self._run_async(self.bridge.discover_gradient_lights())

        if not lights:
            rumps.alert("No gradient lights found on the bridge.")
            return

        # Store available lights
        self.config.available_lights = [
            AvailableLight(id=l.id, name=l.name, zone_count=l.zone_count)
            for l in lights
        ]
        save_config(self.config)

        msg = "\n".join(f"  {l.name} ({l.zone_count} zones)" for l in lights)
        rumps.alert(
            f"Found {len(lights)} gradient light(s):\n\n{msg}\n\n"
            "Use 'Map Lights' to assign them to monitors."
        )
        self._build_menu()

    def _quit(self, _):
        # Stop sync and close connections with a short timeout
        if self._loop and not self._loop.is_closed():
            try:
                if self.engine.running:
                    future = asyncio.run_coroutine_threadsafe(self.engine.stop(), self._loop)
                    future.result(timeout=3)
                future = asyncio.run_coroutine_threadsafe(self.bridge.close(), self._loop)
                future.result(timeout=2)
            except Exception:
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        rumps.quit_application()


def run_tray_app():
    config = load_config()
    app = DesktopLightsApp(config)
    app.run()
