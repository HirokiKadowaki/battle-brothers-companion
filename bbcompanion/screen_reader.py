import difflib
import re
import shutil
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
STAR_MATCH_THRESHOLD = 0.7
STAR_LOW_CONFIDENCE_THRESHOLD = 0.55
MAX_STARS = 3


@dataclass
class FieldRead:
    value: object
    confidence: float  # 0.0-1.0, lower means the GUI should flag it for review


def capture_region(sct, box: dict) -> Image.Image:
    """box: {'x': int, 'y': int, 'w': int, 'h': int}. sct: an mss.mss() instance."""
    monitor = {"left": box["x"], "top": box["y"], "width": box["w"], "height": box["h"]}
    shot = sct.grab(monitor)
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _preprocess_for_ocr(image: Image.Image) -> np.ndarray:
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    scaled = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    # Battle Brothers panels are dark with light text; Otsu handles either polarity,
    # try both and let the caller's OCR confidence decide which read to keep.
    _, thresh = cv2.threshold(scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
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
    processed = _preprocess_for_ocr(image)
    # psm 4 (single column of variable-size text) reliably keeps "current/max"
    # values like "59/59" as separate tokens; psm 7 (single line) tends to
    # merge them into garbage (e.g. "59759") on real in-game crops that have
    # a border/icon bleeding into the frame.
    config = "--psm 4 -c tessedit_char_whitelist=0123456789/-"
    text, conf = _ocr_with_confidence(processed, config)

    # Otsu can pick the wrong polarity on some crops; if nothing usable came out,
    # retry against the inverted image before giving up.
    if not text:
        inverted = cv2.bitwise_not(processed)
        text, conf = _ocr_with_confidence(inverted, config)

    numbers = re.findall(r"-?\d+", text)
    if not numbers:
        return FieldRead(value=0, confidence=0.0)

    # Stats are often shown as "current/max" (e.g. HP "59/59"); the max is the
    # base attribute we want, and for a freshly hired recruit current == max.
    value = int(numbers[-1])
    return FieldRead(value=value, confidence=conf)


def read_background_name(image: Image.Image, candidates: list[str]) -> FieldRead:
    processed = _preprocess_for_ocr(image)
    config = "--psm 7"
    text, conf = _ocr_with_confidence(processed, config)
    text = text.strip()
    if not text:
        return FieldRead(value=None, confidence=0.0)

    matches = difflib.get_close_matches(text, candidates, n=1, cutoff=BACKGROUND_NAME_MATCH_THRESHOLD)
    if not matches:
        return FieldRead(value=None, confidence=0.0)

    similarity = difflib.SequenceMatcher(None, text, matches[0]).ratio()
    return FieldRead(value=matches[0], confidence=min(conf, similarity) if conf else similarity)


def count_stars(image: Image.Image, star_template: np.ndarray) -> FieldRead:
    """Slide the single-star template across `image` and count non-overlapping matches."""
    gray = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    template_gray = cv2.cvtColor(star_template, cv2.COLOR_RGB2GRAY) if star_template.ndim == 3 else star_template

    th, tw = template_gray.shape[:2]
    ih, iw = gray.shape[:2]
    if th > ih or tw > iw:
        # The template and each stat's star-slot box are drawn freehand during
        # calibration and can end up slightly different sizes; shrink the
        # template (with a small safety margin) rather than failing outright.
        scale = min(ih / th, iw / tw) * 0.9
        tw, th = max(1, int(tw * scale)), max(1, int(th * scale))
        if tw < 1 or th < 1:
            return FieldRead(value=0, confidence=1.0)
        template_gray = cv2.resize(template_gray, (tw, th), interpolation=cv2.INTER_AREA)

    result = cv2.matchTemplate(gray, template_gray, cv2.TM_CCOEFF_NORMED)
    matches = []
    confidences = []
    search = result.copy()
    for _ in range(MAX_STARS):
        _, max_val, _, max_loc = cv2.minMaxLoc(search)
        if max_val < STAR_MATCH_THRESHOLD:
            break
        matches.append(max_loc)
        confidences.append(max_val)
        x, y = max_loc
        # Suppress the region around this match so the next iteration finds a
        # different star instead of re-matching the same one.
        x0, x1 = max(0, x - tw // 2), min(search.shape[1], x + tw // 2)
        y0, y1 = max(0, y - th // 2), min(search.shape[0], y + th // 2)
        search[y0:y1, x0:x1] = -1.0

    count = len(matches)
    confidence = min(confidences) if confidences else 1.0  # 0 stars found = confident "no stars"
    return FieldRead(value=count, confidence=confidence)


def load_star_template(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    return np.array(img)
