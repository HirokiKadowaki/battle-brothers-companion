"""The company roster: brothers you've hired and the build you're aiming them at."""

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import composition, roster
from .data_loader import STATS, STAT_LABELS
from .gui import BACKGROUND_IMAGE, VERDICT_STYLE, BackgroundWidget

EMPTY_MESSAGE = "No brothers yet — evaluate a recruit, then use 'Add to Roster...'"
PLACE_HINT = "Click a brother, then click a slot to move him (swaps if the slot is taken)."

TILE_W, TILE_H = 74, 78
SELECTED_COLOR = QColor(120, 190, 255)


def _pretty_stat_tokens(token: str) -> str:
    for key, label in STAT_LABELS.items():
        token = token.replace(key, label)
    return token


class _RatingItem(QTableWidgetItem):
    """Sorts by the underlying number, not the '9.9/10' label — otherwise
    '10.0/10' would sort before '9.9/10' alphabetically."""

    def __init__(self, rating: float):
        super().__init__(f"{rating:.1f}/10")
        self.rating = rating

    def __lt__(self, other):
        if isinstance(other, _RatingItem):
            return self.rating < other.rating
        return super().__lt__(other)


class SlotTile(QFrame):
    """One formation slot: a painted silhouette (no game art) plus the name.

    Empty slots show a dim silhouette; occupied ones are brighter, named, and
    bordered in their fit-verdict colour.
    """

    clicked = pyqtSignal(int)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.entry = None
        self.selected = False
        self.setFixedSize(TILE_W, TILE_H)
        self.setCursor(Qt.PointingHandCursor)

    def set_entry(self, entry):
        self.entry = entry
        self.setToolTip(
            f"{entry['name']} — {entry.get('archetype', '-')}" if entry else "Empty slot"
        )
        self.update()

    def set_selected(self, selected: bool):
        if self.selected != selected:
            self.selected = selected
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        occupied = self.entry is not None

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(38, 33, 28) if occupied else QColor(26, 23, 20, 200))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)

        # Silhouette: head + shoulders, centred in the upper part of the tile.
        silhouette = QColor(150, 150, 150) if occupied else QColor(58, 52, 46)
        painter.setBrush(silhouette)
        cx, top = self.width() / 2, 12.0
        painter.drawEllipse(QRectF(cx - 9, top, 18, 18))
        shoulders = QPainterPath()
        shoulders.moveTo(cx - 19, top + 44)
        shoulders.cubicTo(cx - 19, top + 24, cx + 19, top + 24, cx + 19, top + 44)
        shoulders.lineTo(cx - 19, top + 44)
        painter.drawPath(shoulders)

        if occupied:
            verdict = self.entry.get("verdict")
            border = QColor(VERDICT_STYLE[verdict][1]) if verdict in VERDICT_STYLE else QColor(90, 90, 90)
            # Selection is a light blue, not gold: gold reads as the amber
            # "marginal" verdict border and the two are hard to tell apart.
            painter.setPen(QPen(SELECTED_COLOR, 3) if self.selected else QPen(border, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)

            painter.setPen(QColor(235, 230, 220))
            font = painter.font()
            font.setPointSize(7)
            painter.setFont(font)
            name = QFontMetrics(font).elidedText(self.entry["name"], Qt.ElideRight, self.width() - 6)
            painter.drawText(self.rect().adjusted(3, 0, -3, -4), Qt.AlignHCenter | Qt.AlignBottom, name)
        elif self.selected:
            painter.setPen(QPen(SELECTED_COLOR, 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)


class RosterWindow(QDialog):
    """A normal, focusable window (deliberately not the frameless always-on-top
    Tool style the overlay uses — that style couldn't reliably take keyboard
    focus on Windows)."""

    def __init__(self, guidance_by_name: dict, parent=None):
        super().__init__(parent)
        self._guidance_by_name = guidance_by_name
        self._entries = []
        self._selected_id = None
        self._syncing = False  # guards the table<->grid selection loop

        self.setWindowTitle("Company Roster")
        self.resize(900, 880)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        backdrop = BackgroundWidget(BACKGROUND_IMAGE)
        outer.addWidget(backdrop)

        layout = QVBoxLayout(backdrop)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        campaign_row = QHBoxLayout()
        campaign_row.addWidget(QLabel("Campaign:"))
        self.campaign_combo = QComboBox()
        self.campaign_combo.setView(QListView())
        self.campaign_combo.setMinimumWidth(220)
        self.campaign_combo.activated.connect(self._on_campaign_chosen)
        campaign_row.addWidget(self.campaign_combo)
        for label, slot in (
            ("New...", self._on_new_campaign),
            ("Rename...", self._on_rename_campaign),
            ("Delete", self._on_delete_campaign),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            campaign_row.addWidget(btn)
        campaign_row.addStretch()
        layout.addLayout(campaign_row)

        self.empty_label = QLabel(EMPTY_MESSAGE)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #b0bec5; font-style: italic; padding: 14px;")
        layout.addWidget(self.empty_label)

        # --- formation grid -------------------------------------------------
        formation_label = QLabel("Formation")
        formation_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(formation_label)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setSpacing(4)
        grid.setContentsMargins(0, 0, 0, 0)
        self.tiles = []
        for slot in range(roster.GRID_SLOTS):
            tile = SlotTile(slot)
            tile.clicked.connect(self._on_tile_clicked)
            grid.addWidget(tile, slot // roster.GRID_COLS, slot % roster.GRID_COLS)
            self.tiles.append(tile)
        layout.addWidget(grid_host, alignment=Qt.AlignHCenter)

        self.hint_label = QLabel(PLACE_HINT)
        self.hint_label.setStyleSheet("color: #90a4ae; font-size: 11px;")
        layout.addWidget(self.hint_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Background", "Building Toward", "Rating"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 260)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        self.detail = QTextBrowser()
        self.detail.setMinimumHeight(120)
        self.detail.setPlaceholderText("Select a brother to see his projected stats and target build.")

        # Splitter so BOTH the list and the lower panels grow when the window is
        # resized (the detail was previously fixed-height), and so the dividers
        # can be dragged to favour whichever part you're reading.
        bottom = QSplitter(Qt.Horizontal)
        bottom.addWidget(self.detail)
        bottom.addWidget(self._build_composition_panel())
        bottom.setStretchFactor(0, 3)
        bottom.setStretchFactor(1, 2)
        bottom.setChildrenCollapsible(False)
        bottom.setSizes([520, 360])

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(bottom)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setChildrenCollapsible(False)
        split.setSizes([280, 260])
        layout.addWidget(split, stretch=1)

        button_row = QHBoxLayout()
        self.remove_btn = QPushButton("Remove from Roster")
        self.remove_btn.clicked.connect(self._on_remove)
        self.remove_btn.setEnabled(False)
        button_row.addWidget(self.remove_btn)
        button_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self.refresh()

    def _reload_campaigns(self):
        self.campaign_combo.blockSignals(True)
        self.campaign_combo.clear()
        self.campaign_combo.addItems(roster.list_campaigns())
        idx = self.campaign_combo.findText(roster.active_campaign())
        if idx >= 0:
            self.campaign_combo.setCurrentIndex(idx)
        self.campaign_combo.blockSignals(False)

    def _switch_campaign(self, name):
        roster.set_active_campaign(name)
        self._selected_id = None  # a brother from the old campaign isn't in this one
        self.refresh()

    def _on_campaign_chosen(self, _index):
        self._switch_campaign(self.campaign_combo.currentText())

    def _on_new_campaign(self):
        name, ok = QInputDialog.getText(self, "New Campaign", "Name this campaign:")
        if not ok:
            return
        if not roster.create_campaign(name):
            QMessageBox.warning(
                self, "Can't Create", "Give it a name that isn't blank or already used."
            )
            return
        self._selected_id = None
        self.refresh()

    def _on_rename_campaign(self):
        current = roster.active_campaign()
        name, ok = QInputDialog.getText(self, "Rename Campaign", "New name:", text=current)
        if not ok:
            return
        if not roster.rename_campaign(current, name):
            QMessageBox.warning(
                self, "Can't Rename", "Give it a name that isn't blank or already used."
            )
            return
        self.refresh()

    def _on_delete_campaign(self):
        current = roster.active_campaign()
        count = len(roster.load_roster())
        confirm = QMessageBox.question(
            self,
            "Delete Campaign",
            f"Delete the campaign '{current}' and its {count} brother(s)?\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        if not roster.delete_campaign(current):
            QMessageBox.information(
                self, "Can't Delete", "This is your only campaign, so it can't be deleted."
            )
            return
        self._selected_id = None
        self.refresh()

    def _build_composition_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        header = QHBoxLayout()
        header.addWidget(QLabel("Composition:"))
        self.preset_combo = QComboBox()
        self.preset_combo.setView(QListView())  # see gui.py: private view eats the highlight
        self.preset_combo.currentIndexChanged.connect(lambda _: self._update_composition())
        header.addWidget(self.preset_combo, stretch=1)
        layout.addLayout(header)

        self.preset_note = QLabel()
        self.preset_note.setWordWrap(True)
        self.preset_note.setStyleSheet("color: #90a4ae; font-size: 11px;")
        layout.addWidget(self.preset_note)

        self.comp_tree = QTreeWidget()
        self.comp_tree.setColumnCount(2)
        self.comp_tree.setHeaderLabels(["Role / Build", "Have vs Target"])
        self.comp_tree.setRootIsDecorated(True)
        self.comp_tree.setEditTriggers(QTreeWidget.NoEditTriggers)
        self.comp_tree.setColumnWidth(0, 210)
        layout.addWidget(self.comp_tree, stretch=1)

        customise_btn = QPushButton("Customise Targets...")
        customise_btn.clicked.connect(self._on_customise_targets)
        layout.addWidget(customise_btn)

        self._reload_presets()
        return panel

    def _reload_presets(self, select_name=None):
        self._roles, self._presets = composition.all_presets()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems([p["name"] for p in self._presets])
        if select_name:
            idx = self.preset_combo.findText(select_name)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)

    def _current_preset(self):
        idx = self.preset_combo.currentIndex()
        return self._presets[idx] if 0 <= idx < len(self._presets) else None

    @staticmethod
    def _status_text_colour(have, target, delta):
        if delta == 0:
            return f"{have} / {target}  ·  on target", "#2e7d32"
        if delta > 0:
            return f"{have} / {target}  ·  over by {delta}", "#f9a825"
        return f"{have} / {target}  ·  need {-delta} more", "#c62828"

    def _update_composition(self):
        preset = self._current_preset()
        if preset is None:
            return
        self.preset_note.setText(preset.get("note", ""))
        result = composition.compare(
            self._entries, self._roles, preset["targets"], preset.get("archetype_targets")
        )

        self.comp_tree.clear()
        for role in result["roles"]:
            text, colour = self._status_text_colour(role["have"], role["target"], role["delta"])
            node = QTreeWidgetItem([role["label"], text])
            node.setForeground(1, QColor(colour))
            for build in role["breakdown"]:
                if "target" in build:
                    btext, bcolour = self._status_text_colour(
                        build["count"], build["target"], build["delta"]
                    )
                    child = QTreeWidgetItem([f"   {build['archetype']}", btext])
                    child.setForeground(1, QColor(bcolour))
                else:
                    child = QTreeWidgetItem([f"   {build['archetype']}", str(build["count"])])
                child.setForeground(0, QColor("#b0bec5"))
                node.addChild(child)
            self.comp_tree.addTopLevelItem(node)
            node.setExpanded(True)

        if result["unassigned"]:
            orphan = QTreeWidgetItem(
                ["Unassigned", f"{result['unassigned']} (archetype not in any role)"]
            )
            orphan.setForeground(1, QColor("#f9a825"))
            self.comp_tree.addTopLevelItem(orphan)

    def _on_customise_targets(self):
        preset = self._current_preset()
        if preset is None:
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Customise Composition")
        form = QGridLayout(dialog)

        form.addWidget(QLabel("Save as:"), 0, 0)
        name_edit = QLineEdit(preset["name"] if preset.get("custom") else f"{preset['name']} (mine)")
        form.addWidget(name_edit, 0, 1)

        spins = {}
        for row, role in enumerate(self._roles, start=1):
            form.addWidget(QLabel(role["label"]), row, 0)
            spin = QSpinBox()
            spin.setRange(0, 30)
            spin.setValue(int(preset["targets"].get(role["key"], 0)))
            form.addWidget(spin, row, 1)
            spins[role["key"]] = spin

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dialog.reject)
        buttons.addWidget(cancel)
        save = QPushButton("Save")
        save.setDefault(True)
        save.clicked.connect(dialog.accept)
        buttons.addWidget(save)
        form.addLayout(buttons, len(self._roles) + 1, 0, 1, 2)

        if dialog.exec_() != QDialog.Accepted:
            return
        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name Needed", "Give the composition a name so you can pick it later.")
            return
        composition.save_custom_preset(name, {k: s.value() for k, s in spins.items()})
        self._reload_presets(select_name=name)
        self._update_composition()

    def refresh(self):
        # The whole rebuild must be guarded, not just the selection restore:
        # shrinking the table destroys the selected row, which emits
        # itemSelectionChanged mid-mutation. Unguarded that re-enters refresh()
        # while the table is half-rebuilt, corrupting Qt's heap and hard-crashing
        # on Windows (0xc0000374) — e.g. when removing the selected brother.
        self._syncing = True
        try:
            self._reload_campaigns()
            self._entries = roster.ensure_positions(roster.load_roster())
            self.empty_label.setVisible(not self._entries)

            by_slot = {e.get("position"): e for e in self._entries}
            for slot, tile in enumerate(self.tiles):
                entry = by_slot.get(slot)
                tile.set_entry(entry)
                tile.set_selected(
                    self._selected_id is not None
                    and entry is not None
                    and entry["id"] == self._selected_id
                )

            # Sorting must be off while populating, or Qt re-sorts mid-insert and
            # scrambles which cell lands in which row.
            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(self._entries))
            for row, entry in enumerate(self._entries):
                name_item = QTableWidgetItem(entry.get("name", "?"))
                # Row order changes when the user sorts, so every lookup keys off
                # this id rather than the row index.
                name_item.setData(Qt.UserRole, entry["id"])
                self.table.setItem(row, 0, name_item)
                self.table.setItem(row, 1, QTableWidgetItem(entry.get("background", "?")))
                self.table.setItem(row, 2, QTableWidgetItem(entry.get("archetype", "-")))

                rating_item = _RatingItem(entry.get("rating", 0))
                rating_item.setTextAlignment(Qt.AlignCenter)
                verdict = entry.get("verdict")
                if verdict in VERDICT_STYLE:
                    rating_item.setForeground(Qt.white)
                    rating_item.setBackground(QColor(VERDICT_STYLE[verdict][1]))
                self.table.setItem(row, 3, rating_item)
            self.table.setSortingEnabled(True)

            # Restore the table selection to whoever is selected on the grid.
            self.table.clearSelection()
            if self._selected_id is not None:
                for row in range(self.table.rowCount()):
                    if self.table.item(row, 0).data(Qt.UserRole) == self._selected_id:
                        self.table.selectRow(row)
                        break
        finally:
            self._syncing = False

        self._show_detail(self._selected_entry())
        self._update_composition()

    def _selected_entry(self):
        if self._selected_id is None:
            return None
        return next((e for e in self._entries if e["id"] == self._selected_id), None)

    def _on_tile_clicked(self, slot: int):
        entry = next((e for e in self._entries if e.get("position") == slot), None)

        if self._selected_id is None:
            # Nothing held yet: clicking a brother picks him up.
            if entry is not None:
                self._select(entry["id"])
            return

        if entry is not None and entry["id"] == self._selected_id:
            self._select(None)  # click the held brother again to drop him
            return

        # A brother is held and a different slot was clicked -> move (or swap).
        roster.set_position(self._selected_id, slot)
        self.refresh()

    def _select(self, brother_id):
        self._selected_id = brother_id
        self.refresh()

    def _on_selection_changed(self):
        if self._syncing:
            return
        items = self.table.selectedItems()
        if not items:
            self._select(None)
            return
        # Read the id off the row rather than indexing self._entries by row
        # number — the two diverge as soon as the user sorts a column.
        brother_id = self.table.item(items[0].row(), 0).data(Qt.UserRole)
        self._select(brother_id)

    def _show_detail(self, entry):
        self.remove_btn.setEnabled(entry is not None)
        if entry is None:
            self.detail.clear()
            return

        projected = entry.get("projected", {})
        stars = entry.get("stars", {})
        rows = []
        for stat in STATS:
            star_count = stars.get(stat, 0)
            star_text = " " + "&#9733;" * star_count if star_count else ""
            rows.append(
                f'<tr><td style="padding-right:14px;">{STAT_LABELS[stat]}{star_text}</td>'
                f'<td align="right"><b>{projected.get(stat, "-")}</b></td></tr>'
            )

        guidance = self._guidance_by_name.get(entry.get("archetype")) or {}
        guidance_html = ""
        if guidance:
            priorities = " &rarr; ".join(
                _pretty_stat_tokens(t) for t in guidance.get("level_up_priority", [])
            )
            guidance_html = (
                f'<p style="margin:6px 0 2px 0;"><b>Level-up priority:</b> {priorities}</p>'
                f'<p style="margin:2px 0;"><b>Key perks:</b> {", ".join(guidance.get("key_perks", []))}</p>'
                f'<p style="margin:2px 0;"><b>Weapons / gear:</b> {", ".join(guidance.get("weapons", []))}</p>'
            )

        verdict_label = VERDICT_STYLE.get(entry.get("verdict"), ("", ""))[0]
        self.detail.setHtml(
            f'<h3 style="margin:2px 0;">{entry.get("name", "?")} '
            f'<span style="font-weight:normal; color:#b0bec5;">— {entry.get("background", "?")}</span></h3>'
            f'<p style="margin:2px 0; color:#b0bec5;">Building toward <b>{entry.get("archetype", "-")}</b>'
            f' &nbsp;·&nbsp; {verdict_label} {entry.get("rating", 0):.1f}/10'
            f' &nbsp;·&nbsp; added {entry.get("added", "?")}</p>'
            f'<p style="margin:6px 0 2px 0;"><b>Projected at level 11:</b></p>'
            f'<table>{"".join(rows)}</table>'
            f"{guidance_html}"
        )

    def _on_remove(self):
        entry = self._selected_entry()
        if entry is None:
            return
        confirm = QMessageBox.question(
            self,
            "Remove from Roster",
            f"Remove {entry.get('name', 'this brother')} from the roster?\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        roster.remove_brother(entry["id"])
        self._selected_id = None  # don't keep holding a brother who's now gone
        self.refresh()
