"""Map screen regions to gradient light zones."""

import numpy as np


def sample_zone_colors(
    frame: np.ndarray,
    num_zones: int = 7,
    margin_percent: float = 5.0,
    stride: int = 4,
    reversed_zones: bool = False,
) -> np.ndarray:
    """Divide a screen frame into vertical zones and compute mean color per zone.

    Args:
        frame: HxWx3 RGB numpy array
        num_zones: Number of gradient zones (default 7 for Hue Gradient Lightstrip)
        margin_percent: Percentage of width to skip on each edge
        stride: Pixel sampling stride for performance
        reversed_zones: If True, reverse zone order (for strip mounted in opposite direction)

    Returns:
        Nx3 numpy array of mean RGB colors per zone
    """
    h, w, _ = frame.shape

    margin = int(w * margin_percent / 100)
    effective_start = margin
    effective_end = w - margin
    effective_width = effective_end - effective_start

    if effective_width <= 0:
        effective_start = 0
        effective_end = w
        effective_width = w

    zone_width = effective_width / num_zones

    # Subsample rows for performance
    sampled = frame[::stride, :, :]

    colors = []
    for i in range(num_zones):
        left = effective_start + int(i * zone_width)
        right = effective_start + int((i + 1) * zone_width)
        zone_pixels = sampled[:, left:right:stride, :]
        mean_color = zone_pixels.reshape(-1, 3).mean(axis=0)
        colors.append(mean_color)

    result = np.array(colors, dtype=np.float64)

    if reversed_zones:
        result = result[::-1]

    return result
