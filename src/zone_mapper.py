"""Map screen regions to gradient light zones."""

import numpy as np

# How far inward from each edge to sample (as fraction of screen dimension)
_EDGE_DEPTH_FRACTION = 0.20


def sample_zone_colors(
    frame: np.ndarray,
    num_zones: int = 5,
    margin_percent: float = 5.0,
    stride: int = 4,
    reversed_zones: bool = False,
) -> np.ndarray:
    """Sample colors along an arch path matching the Hue Play Gradient Lightstrip layout.

    The arch follows the screen perimeter: up the left edge, across the top,
    and down the right edge. Each zone samples a rectangular region near the
    corresponding edge section.

    Args:
        frame: HxWx3 RGB numpy array
        num_zones: Number of gradient zones
        margin_percent: Percentage of each edge to skip (avoids UI chrome)
        stride: Pixel sampling stride for performance
        reversed_zones: If True, reverse zone order (for strip mounted in opposite direction)

    Returns:
        Nx3 numpy array of mean RGB colors per zone
    """
    h, w, _ = frame.shape

    margin_x = int(w * margin_percent / 100)
    margin_y = int(h * margin_percent / 100)

    x0, x1 = margin_x, w - margin_x
    y0, y1 = margin_y, h - margin_y
    ew, eh = x1 - x0, y1 - y0

    if ew <= 0 or eh <= 0:
        x0, y0, x1, y1 = 0, 0, w, h
        ew, eh = w, h

    depth_x = max(1, int(ew * _EDGE_DEPTH_FRACTION))
    depth_y = max(1, int(eh * _EDGE_DEPTH_FRACTION))

    # Subsample both axes for performance
    sampled = frame[::stride, ::stride, :]

    def s(v: int) -> int:
        """Scale a coordinate to the subsampled frame."""
        return max(0, v // stride)

    # Arch perimeter: left (bottom→top) + top (left→right) + right (top→bottom)
    total = eh + ew + eh
    zone_len = total / num_zones

    colors = []
    for i in range(num_zones):
        seg_start = i * zone_len
        seg_end = (i + 1) * zone_len
        zone_pixels: list[np.ndarray] = []

        # Left edge: arch distance 0..eh (screen bottom→top)
        ls, le = max(0.0, seg_start), min(float(eh), seg_end)
        if ls < le:
            row_top = y0 + eh - int(le)
            row_bot = y0 + eh - int(ls)
            px = sampled[s(row_top):s(row_bot), s(x0):s(x0 + depth_x), :]
            if px.size > 0:
                zone_pixels.append(px.reshape(-1, 3))

        # Top edge: arch distance eh..eh+ew (screen left→right)
        ts = max(0.0, seg_start - eh)
        te = min(float(ew), seg_end - eh)
        if ts < te and te > 0:
            col_left = x0 + int(ts)
            col_right = x0 + int(te)
            px = sampled[s(y0):s(y0 + depth_y), s(col_left):s(col_right), :]
            if px.size > 0:
                zone_pixels.append(px.reshape(-1, 3))

        # Right edge: arch distance eh+ew..2*eh+ew (screen top→bottom)
        rs = max(0.0, seg_start - eh - ew)
        re = min(float(eh), seg_end - eh - ew)
        if rs < re and re > 0:
            row_top = y0 + int(rs)
            row_bot = y0 + int(re)
            px = sampled[s(row_top):s(row_bot), s(x1 - depth_x):s(x1), :]
            if px.size > 0:
                zone_pixels.append(px.reshape(-1, 3))

        if zone_pixels:
            all_px = np.concatenate(zone_pixels, axis=0)
            colors.append(all_px.mean(axis=0))
        else:
            colors.append(np.array([0.0, 0.0, 0.0]))

    result = np.array(colors, dtype=np.float64)

    if reversed_zones:
        result = result[::-1]

    return result
