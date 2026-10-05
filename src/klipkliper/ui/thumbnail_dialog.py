"""Dialog Buat Thumbnail — Fase 2.

Pilih template + judul + detik → Generate (via klipkliper.thumbnail, lazy) →
preview → Simpan ke file. Bila modul thumbnail belum ada: pesan jelas.
"""
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QDoubleSpinBox, QPushButton, QLabel, QMessageBox, QFileDialog,
)

# Fallback bila modul thumbnail belum dibuat (lihat docs/API.md Fase 2 D).
TEMPLATES_FALLBACK = [
    ("breaking", "Breaking — banner merah ala news"),
    ("bold", "Bold — judul besar tengah"),
    ("split", "Split — crop wajah kiri + teks kanan"),
    ("minimal", "Minimal — gradasi gelap + teks kecil"),
    ("quote", "Quote — teks kutipan tengah"),
]


def _template_items():
    try:
        from klipkliper import thumbnail as th_mod
        names = getattr(th_mod, "TEMPLATES", None) or getattr(th_mod, "_TEMPLATES", None)
        if names:
            return [(n, n) for n in names]
    except Exception:
        pass
    return TEMPLATES_FALLBACK


class ThumbnailDialog(QDialog):
    def __init__(self, src, title="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Buat Thumbnail")
        self.resize(560, 520)
        self._src = src
        self._tmp = None

        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.cmb_template = QComboBox()
        for val, label in _template_items():
            self.cmb_template.addItem(label, val)
        form.addRow("Template:", self.cmb_template)

        self.txt_title = QLineEdit(title)
        self.txt_title.setPlaceholderText("Judul thumbnail")
        form.addRow("Judul:", self.txt_title)

        self.spin_time = QDoubleSpinBox()
        self.spin_time.setRange(0, 36000)
        self.spin_time.setSingleStep(0.5)
        self.spin_time.setValue(1.0)
        self.spin_time.setSuffix(" dtk")
        form.addRow("Waktu frame:", self.spin_time)
        lay.addLayout(form)

        b_gen = QPushButton("🎨 Generate")
        b_gen.clicked.connect(self.generate)
        lay.addWidget(b_gen)

        self.lbl_preview = QLabel("Preview muncul di sini.")
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumHeight(300)
        self.lbl_preview.setStyleSheet("background:#222; color:#888;")
        lay.addWidget(self.lbl_preview, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        b_close = QPushButton("Tutup")
        b_close.clicked.connect(self.reject)
        self.b_save = QPushButton("💾 Simpan…")
        self.b_save.setEnabled(False)
        self.b_save.clicked.connect(self.save_as)
        row.addWidget(b_close)
        row.addWidget(self.b_save)
        lay.addLayout(row)

    def generate(self):
        try:
            from klipkliper import thumbnail as th_mod
        except Exception:
            QMessageBox.warning(
                self, "Thumbnail",
                "Modul thumbnail (thumbnail.py) belum tersedia.\n"
                "Dibuat tim modul — coba lagi nanti.")
            return
        title = self.txt_title.text().strip() or "Thumbnail"
        try:
            tmp = Path(tempfile.mkdtemp(prefix="klipkliper_thumb_")) / "thumb.png"
            th_mod.generate(
                self._src, at_time=float(self.spin_time.value()),
                title=title, template=self.cmb_template.currentData(),
                out_path=str(tmp))
        except Exception as e:
            QMessageBox.warning(self, "Thumbnail", f"Gagal generate:\n{e}")
            return
        self._tmp = tmp
        px = QPixmap(str(tmp))
        if not px.isNull():
            self.lbl_preview.setPixmap(
                px.scaled(self.lbl_preview.size(), Qt.KeepAspectRatio,
                          Qt.SmoothTransformation))
        self.b_save.setEnabled(True)

    def save_as(self):
        if not self._tmp or not self._tmp.exists():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Simpan Thumbnail", "thumbnail.png",
            "PNG (*.png);;JPEG (*.jpg)")
        if path:
            try:
                data = self._tmp.read_bytes()
                Path(path).write_bytes(data)
                QMessageBox.information(self, "Thumbnail", f"Tersimpan:\n{path}")
            except Exception as e:
                QMessageBox.warning(self, "Thumbnail", f"Gagal simpan:\n{e}")


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    d = ThumbnailDialog("dummy.mp4", title="Tes")
    assert d.cmb_template.count() == 5
    print("SMOKE thumbnail_dialog: LULUS")
