"""RGB to CIE xy conversion with Gamut C clamping for Hue lights."""

import numpy as np

# Gamut C triangle vertices (Hue Gradient Lightstrip)
GAMUT_C = {
    "red": (0.6915, 0.3083),
    "green": (0.17, 0.7),
    "blue": (0.1532, 0.0475),
}


def _gamma_correct(channel: float) -> float:
    """Apply inverse sRGB companding (linearize)."""
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def rgb_to_xy(r: int, g: int, b: int) -> tuple[float, float]:
    """Convert 8-bit RGB to CIE xy chromaticity, clamped to Gamut C."""
    # Normalize to 0-1 and linearize
    r_lin = _gamma_correct(r / 255.0)
    g_lin = _gamma_correct(g / 255.0)
    b_lin = _gamma_correct(b / 255.0)

    # Wide RGB D65 conversion matrix
    X = r_lin * 0.4124564 + g_lin * 0.3575761 + b_lin * 0.1804375
    Y = r_lin * 0.2126729 + g_lin * 0.7151522 + b_lin * 0.0721750
    Z = r_lin * 0.0193339 + g_lin * 0.1191920 + b_lin * 0.9503041

    total = X + Y + Z
    if total == 0:
        # Black — return white point
        return (0.3127, 0.3290)

    x = X / total
    y = Y / total

    return clamp_to_gamut(x, y)


def rgb_to_brightness(r: int, g: int, b: int) -> float:
    """Compute brightness (0-1) from RGB using max linearized channel.

    Using max channel rather than luminance (Y) avoids saturated colors
    like red or blue appearing much dimmer than they should.
    """
    r_lin = _gamma_correct(r / 255.0)
    g_lin = _gamma_correct(g / 255.0)
    b_lin = _gamma_correct(b / 255.0)
    return max(r_lin, g_lin, b_lin)


def rgb_array_to_xy(colors: np.ndarray) -> list[tuple[float, float]]:
    """Convert array of RGB values (Nx3) to list of CIE xy tuples."""
    return [rgb_to_xy(int(c[0]), int(c[1]), int(c[2])) for c in colors]


def rgb_array_brightness(colors: np.ndarray) -> list[float]:
    """Compute perceived brightness (0-1) for each RGB color in the array."""
    return [rgb_to_brightness(int(c[0]), int(c[1]), int(c[2])) for c in colors]


def _cross_product_2d(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _closest_point_on_segment(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> tuple[float, float]:
    """Return the closest point on line segment AB to point P."""
    ap = (p[0] - a[0], p[1] - a[1])
    ab = (b[0] - a[0], b[1] - a[1])
    ab2 = ab[0] ** 2 + ab[1] ** 2
    if ab2 == 0:
        return a
    t = max(0.0, min(1.0, (ap[0] * ab[0] + ap[1] * ab[1]) / ab2))
    return (a[0] + t * ab[0], a[1] + t * ab[1])


def _point_in_triangle(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> bool:
    d1 = _cross_product_2d(p, a, b)
    d2 = _cross_product_2d(p, b, c)
    d3 = _cross_product_2d(p, c, a)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def clamp_to_gamut(x: float, y: float) -> tuple[float, float]:
    """Clamp an xy point to the Gamut C triangle."""
    r = GAMUT_C["red"]
    g = GAMUT_C["green"]
    b = GAMUT_C["blue"]

    if _point_in_triangle((x, y), r, g, b):
        return (x, y)

    # Find closest point on each edge
    candidates = [
        _closest_point_on_segment((x, y), r, g),
        _closest_point_on_segment((x, y), g, b),
        _closest_point_on_segment((x, y), b, r),
    ]

    best = candidates[0]
    best_dist = (x - best[0]) ** 2 + (y - best[1]) ** 2
    for c in candidates[1:]:
        d = (x - c[0]) ** 2 + (y - c[1]) ** 2
        if d < best_dist:
            best = c
            best_dist = d

    return (round(best[0], 4), round(best[1], 4))


def color_distance(xy1: tuple[float, float], xy2: tuple[float, float]) -> float:
    """Euclidean distance in CIE xy space (simple delta for threshold checks)."""
    return ((xy1[0] - xy2[0]) ** 2 + (xy1[1] - xy2[1]) ** 2) ** 0.5 * 1000


def smooth_colors(
    current: list[tuple[float, float]],
    previous: list[tuple[float, float]] | None,
    alpha: float,
) -> list[tuple[float, float]]:
    """Apply exponential moving average smoothing between frames."""
    if previous is None or alpha <= 0:
        return current
    return [
        (
            prev[0] * alpha + cur[0] * (1 - alpha),
            prev[1] * alpha + cur[1] * (1 - alpha),
        )
        for cur, prev in zip(current, previous)
    ]
