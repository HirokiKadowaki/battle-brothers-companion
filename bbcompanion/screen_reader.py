import difflib
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pytesseract
from PIL import Image

# Winget's UB-Mannheim Tesseract build doesn't register itself on PATH.
# Fall back to its default install location if `tesseract` isn't resolvable.
_FALLBACK_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if shutil.which("tesseract") is None and _FALLBACK_TESSERACT.exists():
    pytesseract.pytesseract.tesseract_cmd = str(_FALLBACK_TESSERACT)

BACKGROUND_NAME_MATCH_THRESHOLD = 0.6
MAX_STARS = 3

# --- Fixed layout of the roster/character stats panel -----------------------
# The panel is a 2-column x 8-row grid of "icon + value-bar" cells. The 8
# attributes we care about live at fixed (column, row) positions, so the user
# only calibrates ONE box around the whole grid and we derive every cell from
# these fractions. Fractions are relative to that panel box, so they are
# resolution-independent (the whole UI scales together).
#
# Columns: (center_x_fraction, width_fraction). Rows: 0-7 top to bottom.
_LEFT_COL = (0.34, 0.42)
_RIGHT_COL = (0.82, 0.32)
STAT_GRID = {
    "hp": (_LEFT_COL, 2),
    "fatigue": (_LEFT_COL, 4),
    "resolve": (_LEFT_COL, 6),
    "initiative": (_LEFT_COL, 7),
    "melee_skill": (_RIGHT_COL, 0),
    "ranged_skill": (_RIGHT_COL, 1),
    "melee_defense": (_RIGHT_COL, 2),
    "ranged_defense": (_RIGHT_COL, 3),
}
_VALUE_CELL_HEIGHT_FRAC = 0.55  # of one row's height
_STAR_MIN_BLOB_AREA_FRAC = 0.003  # of the star-slot area; scale-invariant


@dataclass
class FieldRead:
    value: object
    confidence: float  # 0.0-1.0, lower means the GUI should flag it for review


def capture_region(sct, box: dict) -> Image.Image:
    """box: {'x': int, 'y': int, 'w': int, 'h': int}. sct: an mss.mss() instance."""
    monitor = {"left": box["x"], "top": box["y"], "width": box["w"], "height": box["h"]}
    shot = sct.grab(monitor)
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def derive_grid_boxes(panel: dict) -> dict:
    """Given the calibrated panel box (screen coords), return the value-cell and
    star-slot boxes for every stat, keyed '<stat>_value' and '<stat>_stars'.
    Rows span the full box height (used when no image is available to refine)."""
    return _derive(panel["x"], panel["y"], panel["w"], 0, panel["h"])


def detect_grid_vbounds(panel_image: Image.Image) -> tuple[int, int]:
    """Find the stat grid's top/bottom within a (possibly loosely-drawn) panel
    crop by locating the full-width-dark divider bands between rows. Returns
    (y0, y1) in panel-local pixels; falls back to the full height on failure.

    This makes calibration forgiving: the user drags a rough box and we snap to
    the real grid, instead of assuming the grid exactly fills the drawn box."""
    a = np.array(panel_image.convert("RGB")).astype(int)
    h, w = a.shape[:2]
    dark_rows = np.where((a.mean(axis=2) < 45).sum(axis=1) > 0.9 * w)[0]
    if len(dark_rows) < 2:
        return 0, h
    # Cluster runs of adjacent dark rows into single divider lines.
    lines, cur = [], [dark_rows[0]]
    for y in dark_rows[1:]:
        if y - cur[-1] <= 2:
            cur.append(y)
        else:
            lines.append(int(np.mean(cur)))
            cur = [y]
    lines.append(int(np.mean(cur)))
    if len(lines) < 2:
        return 0, h
    return lines[0], lines[-1]


def derive_grid_boxes_from_image(panel: dict, panel_image: Image.Image) -> dict:
    """Like derive_grid_boxes but snaps the 8 rows to the grid detected inside
    panel_image. Returned boxes are in the same screen coords as `panel`."""
    gy0, gy1 = detect_grid_vbounds(panel_image)
    return _derive(panel["x"], panel["y"], panel["w"], gy0, gy1 - gy0)


def _derive(px: int, py: int, pw: int, grid_top: int, grid_h: int) -> dict:
    row_h = grid_h / 8
    boxes = {}
    for stat, ((col_xc, col_w), row) in STAT_GRID.items():
        cx = px + col_xc * pw
        w = col_w * pw
        cy = py + grid_top + (row + 0.5) / 8 * grid_h
        vh = _VALUE_CELL_HEIGHT_FRAC * row_h
        boxes[f"{stat}_value"] = {
            "x": int(cx - w / 2),
            "y": int(cy - vh / 2),
            "w": int(w),
            "h": int(vh),
        }
        # Star icons sit at the top-left of the value bar; slot straddles the
        # top edge of the row, over the bar's left portion.
        boxes[f"{stat}_stars"] = {
            "x": int(cx - 0.55 * w),
            "y": int(py + grid_top + row / 8 * grid_h),
            "w": int(0.65 * w),
            "h": int(0.5 * row_h),
        }
    return boxes


def _gray_upscaled(image: Image.Image, factor: int = 4) -> np.ndarray:
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    return cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)


def _min_channel_upscaled(image: Image.Image, factor: int = 4) -> np.ndarray:
    # min(R,G,B) per pixel: white digits stay bright (all channels high) while
    # the warm tan "fill bar" texture and gold talent stars (low blue channel)
    # go dark. This separates the number from both far better than luminance,
    # which keeps the bright-but-warm fill and stars as OCR noise.
    arr = np.array(image)
    minc = np.minimum(np.minimum(arr[:, :, 0], arr[:, :, 1]), arr[:, :, 2])
    return cv2.resize(minc, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)


def _binarize(gray: np.ndarray, mode: str) -> np.ndarray:
    if mode == "otsu":
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:  # "fixedNNN" -> fixed threshold at NNN
        _, thresh = cv2.threshold(gray, int(mode[5:]), 255, cv2.THRESH_BINARY)
    return thresh


def _ocr_with_confidence(image: np.ndarray, config: str) -> tuple[str, float]:
    data = pytesseract.image_to_data(
        image, config=config, output_type=pytesseract.Output.DICT
    )
    words = [w.strip() for w in data["text"] if w.strip()]
    confidences = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]
    text = "".join(words)
    avg_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return text, avg_conf


def read_stat_value(image: Image.Image) -> FieldRead:
    gray = _min_channel_upscaled(image)
    config = "--psm 7 -c tessedit_char_whitelist=0123456789/-"
    # Read under several thresholds and majority-vote. In-game crops report OCR
    # confidence 0, so agreement across thresholds is a more useful confidence
    # signal for the GUI's low-confidence flagging than Tesseract's own number.
    reads = []
    for mode in ("fixed140", "fixed155", "otsu"):
        text, _ = _ocr_with_confidence(_binarize(gray, mode), config)
        numbers = re.findall(r"-?\d+", text)
        if numbers:
            # Stats can be shown as "current/max" (e.g. HP "59/59"); the last
            # number is the max/base attribute (current == max for a fresh hire).
            reads.append(int(numbers[-1]))

    if not reads:
        return FieldRead(value=0, confidence=0.0)
    value, agree = Counter(reads).most_common(1)[0]
    return FieldRead(value=value, confidence=agree / 3.0)


def read_background_name(image: Image.Image, candidates: list[str]) -> FieldRead:
    gray = _gray_upscaled(image, factor=3)
    text, conf = _ocr_with_confidence(_binarize(gray, "otsu"), "--psm 7")
    text = text.strip()
    if not text:
        return FieldRead(value=None, confidence=0.0)

    matches = difflib.get_close_matches(text, candidates, n=1, cutoff=BACKGROUND_NAME_MATCH_THRESHOLD)
    if not matches:
        return FieldRead(value=None, confidence=0.0)

    similarity = difflib.SequenceMatcher(None, text, matches[0]).ratio()
    return FieldRead(value=matches[0], confidence=min(conf, similarity) if conf else similarity)


def count_stars(image: Image.Image) -> FieldRead:
    """Count gold talent-star icons in a star-slot crop by their distinctive
    yellow color (more scale-robust than template matching). Presence is
    reliable; exact 1/2/3 count is best-effort, so callers flag it for review."""
    arr = np.array(image).astype(int)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mask = ((r > 170) & (g > 130) & (b < 110) & (r - b > 80)).astype(np.uint8)

    total_gold = int(mask.sum())
    if total_gold == 0:
        return FieldRead(value=0, confidence=1.0)  # confident: no stars

    n_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    area = image.size[0] * image.size[1]
    min_blob = max(3, area * _STAR_MIN_BLOB_AREA_FRAC)
    blobs = [i for i in range(1, n_labels) if stats[i, cv2.CC_STAT_AREA] >= min_blob]

    count = max(1, min(MAX_STARS, len(blobs)))
    # Star count is inherently fuzzy at low resolution; keep confidence modest
    # so the GUI prompts the user to double-check.
    return FieldRead(value=count, confidence=0.5)
