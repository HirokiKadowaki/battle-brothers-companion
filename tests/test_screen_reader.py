"""Synthetic-image checks for the OCR/star-matching pipeline.

No live Battle Brothers screen is available in CI/dev environments, so these
render known text/digits with PIL and confirm the parsing logic itself works.
Run with: python tests/test_screen_reader.py
"""

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bbcompanion import screen_reader as sr

PANEL_BG = (30, 28, 24)
TEXT_COLOR = (230, 220, 200)


def make_stat_image(text: str) -> Image.Image:
    img = Image.new("RGB", (100, 34), PANEL_BG)
    draw = ImageDraw.Draw(img)
    draw.text((10, 6), text, fill=TEXT_COLOR)
    return img


def make_star(cx, cy, r, fill, draw):
    pts = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rad * math.cos(angle), cy - rad * math.sin(angle)))
    draw.polygon(pts, fill=fill)


def test_read_positive_stat_value():
    result = sr.read_stat_value(make_stat_image("67"))
    assert result.value == 67, f"expected 67, got {result.value}"
    assert result.confidence > 0.5, f"expected reasonable confidence, got {result.confidence}"


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


def test_count_stars_zero_two_three():
    tmpl_img = Image.new("RGB", (20, 20), (20, 20, 20))
    d = ImageDraw.Draw(tmpl_img)
    make_star(10, 10, 8, (255, 210, 60), d)
    template = np.array(tmpl_img)

    empty = Image.new("RGB", (70, 20), (20, 20, 20))
    assert sr.count_stars(empty, template).value == 0

    two = Image.new("RGB", (70, 20), (20, 20, 20))
    d2 = ImageDraw.Draw(two)
    make_star(10, 10, 8, (255, 210, 60), d2)
    make_star(30, 10, 8, (255, 210, 60), d2)
    assert sr.count_stars(two, template).value == 2

    three = Image.new("RGB", (90, 20), (20, 20, 20))
    d3 = ImageDraw.Draw(three)
    make_star(10, 10, 8, (255, 210, 60), d3)
    make_star(30, 10, 8, (255, 210, 60), d3)
    make_star(50, 10, 8, (255, 210, 60), d3)
    assert sr.count_stars(three, template).value == 3


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
