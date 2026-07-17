import json

import mss
from PIL import Image
from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .data_loader import LOCAL_CONFIG_DIR

SCREEN_REGIONS_PATH = LOCAL_CONFIG_DIR / "screen_regions.json"

INSTRUCTION = (
    "Draw ONE box around the whole stats grid — the two columns of stat bars, "
    "from the TOP row (Head Armor / Melee Skill) down to the BOTTOM row "
    "(Initiative / Vision). Include both the left and right columns.\n\n"
    "The 8 attributes are read from fixed positions inside this box, so it only "
    "needs to be done once. Draw a box, then click Save."
)


def screen_regions_exist() -> bool:
    if not SCREEN_REGIONS_PATH.exists():
        return False
    try:
        return "panel" in load_screen_regions()
    except (json.JSONDecodeError, OSError):
        return False


def load_screen_regions() -> dict:
    with open(SCREEN_REGIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _grab_virtual_desktop():
    """Return (PIL.Image of the whole virtual desktop, left, top) in physical px."""
    with mss.mss() as sct:
        mon = sct.monitors[0]  # bounding box across all monitors
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    return img, mon["left"], mon["top"]


class ImageCanvas(QWidget):
    """Shows a scaled screenshot and lets the user rubber-band a selection on it."""

    def __init__(self, pixmap: QPixmap, on_selection_changed, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._on_selection_changed = on_selection_changed
        self._drag_start = None
        self._sel = QRect()  # selection in widget coords
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setMinimumSize(400, 300)

    def _display_geom(self):
        """Return (scale, offset_x, offset_y) mapping image px -> widget px."""
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if pw == 0 or ph == 0:
            return 1.0, 0, 0
        scale = min(self.width() / pw, self.height() / ph)
        ox = (self.width() - pw * scale) / 2
        oy = (self.height() - ph * scale) / 2
        return scale, ox, oy

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(18, 18, 18))
        scale, ox, oy = self._display_geom()
        target = QRect(
            int(ox), int(oy), int(self._pixmap.width() * scale), int(self._pixmap.height() * scale)
        )
        painter.drawPixmap(target, self._pixmap)
        if not self._sel.isNull():
            painter.setPen(QPen(QColor(255, 210, 60), 2))
            painter.setBrush(QColor(255, 210, 60, 50))
            painter.drawRect(self._sel)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()
            self._sel = QRect(self._drag_start, self._drag_start)
            self.update()

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            self._sel = QRect(self._drag_start, event.pos()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_start is not None:
            self._sel = QRect(self._drag_start, event.pos()).normalized()
            self._drag_start = None
            self.update()
            self._on_selection_changed(self.has_selection())

    def has_selection(self) -> bool:
        return self._sel.width() > 3 and self._sel.height() > 3

    def clear_selection(self):
        self._sel = QRect()
        self.update()
        self._on_selection_changed(False)

    def selection_image_rect(self):
        """Map the widget-space selection to original image-pixel coords."""
        if not self.has_selection():
            return None
        scale, ox, oy = self._display_geom()
        ix = (self._sel.x() - ox) / scale
        iy = (self._sel.y() - oy) / scale
        iw = self._sel.width() / scale
        ih = self._sel.height() / scale
        ix = max(0, min(ix, self._pixmap.width()))
        iy = max(0, min(iy, self._pixmap.height()))
        return QRect(int(ix), int(iy), int(iw), int(ih))


class CalibrationWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Calibrate Stats Panel")

        self._screenshot, self._mon_left, self._mon_top = _grab_virtual_desktop()
        self._qimage_bytes = self._screenshot.tobytes("raw", "RGB")
        qimg = QImage(
            self._qimage_bytes,
            self._screenshot.width,
            self._screenshot.height,
            self._screenshot.width * 3,
            QImage.Format_RGB888,
        )
        pixmap = QPixmap.fromImage(qimg)

        self.panel_box = None

        layout = QVBoxLayout(self)
        prompt = QLabel(INSTRUCTION)
        prompt.setWordWrap(True)
        prompt.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px;")
        layout.addWidget(prompt)

        self.canvas = ImageCanvas(pixmap, self._on_selection_changed)
        layout.addWidget(self.canvas, stretch=1)

        button_row = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.setEnabled(False)
        redraw_btn = QPushButton("Redraw")
        redraw_btn.clicked.connect(self.canvas.clear_selection)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(self.save_btn)
        button_row.addWidget(redraw_btn)
        button_row.addStretch()
        button_row.addWidget(cancel_btn)
        layout.addLayout(button_row)

        self.resize(1000, 750)

    def _on_selection_changed(self, has_selection: bool):
        self.save_btn.setEnabled(has_selection)

    def _on_save(self):
        img_rect = self.canvas.selection_image_rect()
        if img_rect is None:
            return
        self.panel_box = {
            "x": self._mon_left + img_rect.x(),
            "y": self._mon_top + img_rect.y(),
            "w": img_rect.width(),
            "h": img_rect.height(),
        }
        LOCAL_CONFIG_DIR.mkdir(exist_ok=True)
        with open(SCREEN_REGIONS_PATH, "w", encoding="utf-8") as f:
            json.dump({"panel": self.panel_box}, f, indent=2)
        self.accept()


def run_calibration_wizard(parent=None) -> bool:
    wizard = CalibrationWizard(parent)
    wizard.showMaximized()
    result = wizard.exec_()
    if result == QDialog.Accepted:
        QMessageBox.information(
            parent,
            "Calibration Complete",
            "Stats panel saved. Press Ctrl+Alt+R on a recruit's character sheet to auto-fill.",
        )
        return True
    return False
