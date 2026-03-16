"""Unit tests for color processing."""

from src.color_processing import rgb_to_xy, clamp_to_gamut, color_distance, smooth_colors


def test_rgb_to_xy_red():
    x, y = rgb_to_xy(255, 0, 0)
    assert 0.6 < x < 0.7
    assert 0.3 < y < 0.35


def test_rgb_to_xy_green():
    x, y = rgb_to_xy(0, 255, 0)
    # sRGB green maps to ~(0.30, 0.60), clamped to Gamut C
    assert 0.15 < x < 0.35
    assert 0.55 < y < 0.75


def test_rgb_to_xy_blue():
    x, y = rgb_to_xy(0, 0, 255)
    assert 0.13 < x < 0.18
    assert 0.04 < y < 0.08


def test_rgb_to_xy_white():
    x, y = rgb_to_xy(255, 255, 255)
    assert 0.3 < x < 0.35
    assert 0.3 < y < 0.35


def test_rgb_to_xy_black():
    x, y = rgb_to_xy(0, 0, 0)
    # Black returns white point
    assert 0.3 < x < 0.35
    assert 0.3 < y < 0.35


def test_clamp_inside_gamut():
    # Point inside gamut should not change
    x, y = clamp_to_gamut(0.35, 0.35)
    assert abs(x - 0.35) < 0.001
    assert abs(y - 0.35) < 0.001


def test_clamp_outside_gamut():
    # Point far outside should be clamped
    x, y = clamp_to_gamut(0.0, 0.0)
    # Should be on the gamut boundary
    assert 0.1 <= x <= 0.7
    assert 0.04 <= y <= 0.7


def test_color_distance():
    d = color_distance((0.3, 0.3), (0.3, 0.3))
    assert d == 0.0

    d = color_distance((0.3, 0.3), (0.4, 0.3))
    assert d > 0


def test_smooth_colors():
    current = [(0.4, 0.4), (0.2, 0.2)]
    previous = [(0.3, 0.3), (0.3, 0.3)]
    result = smooth_colors(current, previous, alpha=0.5)
    # Should be midpoint
    assert abs(result[0][0] - 0.35) < 0.001
    assert abs(result[1][1] - 0.25) < 0.001


def test_smooth_no_previous():
    current = [(0.4, 0.4)]
    result = smooth_colors(current, None, alpha=0.5)
    assert result == current
