"""Dialog Edit Transkrip — Fase 2.

Tabel segmen (mulai, selesai, teks) yang bisa diedit.
Simpan → kembalikan segments teredit. Word timestamps TIDAK dihitung
ulang (keterbatasan Fase 2) — karaoke memakai timing kata asli.
"""
import copy

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QMessageBox, QLabel, QHeaderView,
)


class TranscriptEditorDialog(QDialog):
    """Dialog edit transkrip. `segments()` → list segmen hasil edit."""

    def __init__(self, segments, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Transkrip")
        self.resize(720, 480)
        self._segments = copy.deepcopy(segments or [])

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Edit teks / waktu segmen. <i>Word timestamps tidak dihitung ulang.</i>"))

        self.tbl = QTableWidget(len(self._segments), 3, self)
        self.tbl.setHorizontalHeaderLabels(["Mulai (dtk)", "Selesai (dtk)", "Teks"])
        hdr = self.tbl.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        for r, s in enumerate(self._segments):
            self.tbl.setItem(r, 0, QTableWidgetItem(f"{s.get('start', 0):.2f}"))
            self.tbl.setItem(r, 1, QTableWidgetItem(f"{s.get('end', 0):.2f}"))
            self.tbl.setItem(r, 2, QTableWidgetItem(str(s.get("text", ""))))
        lay.addWidget(self.tbl)

        row = QHBoxLayout()
        row.addStretch(1)
        b_cancel = QPushButton("Batal")
        b_cancel.clicked.connect(self.reject)
        b_save = QPushButton("💾 Simpan")
        b_save.setDefault(True)
        b_save.clicked.connect(self._on_save)
        row.addWidget(b_cancel)
        row.addWidget(b_save)
        lay.addLayout(row)

    def _on_save(self):
        out = []
        for r in range(self.tbl.rowCount()):
            try:
                start = float(self.tbl.item(r, 0).text().replace(",", "."))
                end = float(self.tbl.item(r, 1).text().replace(",", "."))
            except (ValueError, AttributeError):
                QMessageBox.warning(self, "Edit Transkrip",
                                    f"Baris {r + 1}: waktu harus angka.")
                return
            if not (0 <= start < end):
                QMessageBox.warning(self, "Edit Transkrip",
                                    f"Baris {r + 1}: harus 0 ≤ mulai < selesai.")
                return
            text = self.tbl.item(r, 2).text() if self.tbl.item(r, 2) else ""
            seg = dict(self._segments[r])
            seg["start"], seg["end"], seg["text"] = start, end, text
            out.append(seg)
        self._segments = out
        self.accept()

    def segments(self):
        """List segmen hasil edit (deep copy)."""
        return copy.deepcopy(self._segments)


if __name__ == "__main__":
    # Smoke test: isi sintetis, simpan programatik.
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    d = TranscriptEditorDialog([
        {"start": 0.0, "end": 2.5, "text": "Halo dunia", "words": []},
        {"start": 2.5, "end": 5.0, "text": "tes kedua", "words": []},
    ])
    assert d.tbl.rowCount() == 2
    d.tbl.item(0, 2).setText("Halo dunia edit")
    d._on_save()
    assert d.result() == QDialog.Accepted
    assert d.segments()[0]["text"] == "Halo dunia edit"
    print("SMOKE transcript_editor: LULUS")
