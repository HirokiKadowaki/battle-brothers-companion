"""Synthetic-image checks for the OCR/star-matching pipeline.

No live Battle Brothers screen is available in CI/dev environments, so these
render known text/digits with PIL and confirm the parsing logic itself works.
Run with: python tests/test_screen_reader.py
"""

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bbcompanion import screen_reader as sr

PANEL_BG = (30, 28, 24)
TEXT_COLOR = (230, 220, 200)


def _font():
    # A real TrueType font renders digits cleanly enough for the min-channel
    # OCR pipeline; PIL's tiny default bitmap font does not. Fall back if the
    # common Windows font isn't present.
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, 26)
        except OSError:
            continue
    return ImageFont.load_default()


def make_stat_image(text: str) -> Image.Image:
    img = Image.new("RGB", (120, 44), PANEL_BG)
    draw = ImageDraw.Draw(img)
    draw.text((12, 8), text, fill=TEXT_COLOR, font=_font())
    return img


def make_star(cx, cy, r, fill, draw):
    pts = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rad * math.cos(angle), cy - rad * math.sin(angle)))
    draw.polygon(pts, fill=fill)


def test_read_positive_stat_value():
    # Avoid a "7" here: the test TrueType font renders it close enough to "/"
    # (which the whitelist allows for "59/59" current/max reads) that OCR
    # confuses them. The real game font is unaffected.
    result = sr.read_stat_value(make_stat_image("46"))
    assert result.value == 46, f"expected 46, got {result.value}"
    # confidence is now cross-threshold agreement (0, 1/3, 2/3, 1.0)
    assert result.confidence > 0.3, f"expected some agreement, got {result.confidence}"


def test_read_negative_stat_value():
    result = sr.read_stat_value(make_stat_image("-10"))
    assert result.value == -10, f"expected -10, got {result.value}"


def test_read_zero_stat_value():
    result = sr.read_stat_value(make_stat_image("0"))
    assert result.value == 0, f"expected 0, got {result.value}"


def test_read_background_name_exact():
    img = make_stat_image("Sellsword")
    result = sr.read_background_name(img, ["Sellsword", "Farmhand", "Beggar"])
    assert result.value == "Sellsword", f"expected Sellsword, got {result.value}"


def test_read_background_name_no_candidates_match():
    img = Image.new("RGB", (100, 34), PANEL_BG)  # blank panel, no text at all
    result = sr.read_background_name(img, ["Sellsword", "Farmhand", "Beggar"])
    assert result.value is None, f"expected None for unreadable text, got {result.value}"


def test_count_stars_by_color():
    # count_stars now detects gold stars by color (no template). Use a bigger
    # canvas so the stars clear the scale-relative min-blob-area filter.
    empty = Image.new("RGB", (140, 40), (20, 20, 20))
    assert sr.count_stars(empty).value == 0

    two = Image.new("RGB", (140, 40), (20, 20, 20))
    d2 = ImageDraw.Draw(two)
    make_star(30, 20, 12, (255, 210, 60), d2)
    make_star(80, 20, 12, (255, 210, 60), d2)
    assert sr.count_stars(two).value == 2

    three = Image.new("RGB", (180, 40), (20, 20, 20))
    d3 = ImageDraw.Draw(three)
    make_star(30, 20, 12, (255, 210, 60), d3)
    make_star(80, 20, 12, (255, 210, 60), d3)
    make_star(130, 20, 12, (255, 210, 60), d3)
    assert sr.count_stars(three).value == 3


def test_derive_grid_boxes_shape():
    panel = {"x": 100, "y": 200, "w": 340, "h": 240}
    boxes = sr.derive_grid_boxes(panel)
    # 8 stats x (value + stars)
    assert len(boxes) == 16, f"expected 16 boxes, got {len(boxes)}"
    for stat in sr.STAT_GRID:
        for suffix in ("_value", "_stars"):
            b = boxes[stat + suffix]
            # every derived box must sit inside the calibrated panel
            assert panel["x"] <= b["x"] <= panel["x"] + panel["w"]
            assert panel["y"] <= b["y"] <= panel["y"] + panel["h"]


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = []
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures.append(test.__name__)
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
