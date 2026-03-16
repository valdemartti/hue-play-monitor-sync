"""Test script: Capture both screens and print zone colors.

Usage: python -m tests.test_capture
"""

from src.screen_capture import ScreenCapture
from src.zone_mapper import sample_zone_colors
from src.color_processing import rgb_array_to_xy


def main():
    capture = ScreenCapture()
    print(f"Detected {capture.monitor_count} monitor(s)\n")

    for mon in range(1, capture.monitor_count + 1):
        print(f"Monitor {mon}:")
        frame = capture.capture(mon)
        print(f"  Resolution: {frame.shape[1]}x{frame.shape[0]}")

        zone_colors = sample_zone_colors(frame)
        xy_colors = rgb_array_to_xy(zone_colors)

        for i, (rgb, xy) in enumerate(zip(zone_colors, xy_colors)):
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
            print(f"  Zone {i + 1}: RGB({r:3d}, {g:3d}, {b:3d}) → xy({xy[0]:.4f}, {xy[1]:.4f})")
        print()

    capture.close()


if __name__ == "__main__":
    main()
