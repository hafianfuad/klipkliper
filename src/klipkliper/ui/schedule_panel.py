"""Panel Jadwal Posting Fase 3 — dock di main window.

Tabel jadwal (waktu, platform, judul, status), tombol Batal,
tombol "Jalankan yang jatuh tempo" (+ toggle dry-run untuk tes).
Modul klipkliper.publish.scheduler di-import LAZY.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QMessageBox, QCheckBox, QAbstractItemView,
)

from klipkliper.ui.worker import PublishWorker


class SchedulePanel(QWidget):
    """Panel jadwal posting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>🗓 Jadwal Posting</b> "
                             "<i>(eksperimental)</i>"))

        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["Waktu", "Platform", "Judul", "Status"])
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.tbl, stretch=1)

        r1 = QHBoxLayout()
        b_refresh = QPushButton("🔄 Muat ulang")
        b_refresh.clicked.connect(self.refresh)
        b_cancel = QPushButton("✖ Batalkan jadwal")
        b_cancel.clicked.connect(self._do_cancel)
        r1.addWidget(b_refresh)
        r1.addWidget(b_cancel)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        self.chk_dry = QCheckBox("Dry-run (tes tanpa posting)")
        self.chk_dry.setChecked(True)
        b_due = QPushButton("▶ Jalankan yang jatuh tempo")
        b_due.clicked.connect(self._run_due)
        r2.addWidget(self.chk_dry)
        r2.addWidget(b_due, stretch=1)
        lay.addLayout(r2)

        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)

    # ---------- scheduler (lazy) ----------
    def _scheduler(self):
        try:
            from klipkliper.publish.scheduler import Scheduler
        except Exception as e:
            QMessageBox.warning(
                self, "Jadwal",
                f"Modul publish.scheduler belum tersedia: {e}\n"
                "Dibuat tim modul publish — coba lagi nanti.")
            return None
        try:
            return Scheduler()
        except Exception as e:
            QMessageBox.warning(self, "Jadwal", f"Gagal buat scheduler:\n{e}")
            return None

    def _jobs(self):
        s = self._scheduler()
        if s is None:
            return None
        try:
            return list(s.list())
        except Exception as e:
            QMessageBox.warning(self, "Jadwal", f"Gagal baca jadwal:\n{e}")
            return None

    # ---------- tampilan ----------
    def refresh(self):
        jobs = self._jobs()
        if jobs is None:
            return
        self.tbl.setRowCount(len(jobs))
        for r, j in enumerate(jobs):
            vals = [str(j.get("at", j.get("at_iso", "")))[:16],
                    str(j.get("platform", "")),
                    str(j.get("title", ""))[:50],
                    str(j.get("status", "queued"))]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() ^ Qt.ItemIsEditable)
                it.setData(Qt.UserRole, j.get("id"))
                self.tbl.setItem(r, c, it)
        self.tbl.resizeColumnsToContents()

    # ---------- aksi ----------
    def _selected_id(self):
        row = self.tbl.currentRow()
        if row < 0:
            return None
        it = self.tbl.item(row, 0)
        return it.data(Qt.UserRole) if it else None

    def _do_cancel(self):
        jid = self._selected_id()
        if not jid:
            QMessageBox.information(self, "Jadwal", "Pilih dulu baris jadwal.")
            return
        s = self._scheduler()
        if s is None:
            return
        try:
            s.cancel(jid)
        except Exception as e:
            QMessageBox.warning(self, "Jadwal", f"Gagal batalkan:\n{e}")
            return
        self.refresh()

    def _run_due(self):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Jadwal", "Sedang berjalan.")
            return
        dry = self.chk_dry.isChecked()
        self.lbl.setText("Menjalankan jadwal jatuh tempo…"
                         + (" (dry-run)" if dry else ""))
        self._worker = PublishWorker("run_due", dry_run=dry, parent=self)
        self._worker.progress.connect(lambda s, f: self.lbl.setText(s))
        self._worker.job_done.connect(
            lambda info: self.lbl.setText(
                self.lbl.text() + f"\n• {info.get('platform', '?')}: "
                f"{'OK' if info.get('ok', True) else info.get('error', '?')}"))
        self._worker.error.connect(
            lambda m: QMessageBox.warning(self, "Jadwal", f"Gagal:\n{m[:400]}"))
        self._worker.finished.connect(self._on_due_finished)
        self._worker.start()

    def _on_due_finished(self):
        self._worker = None
        self.refresh()


if __name__ == "__main__":
    # Smoke: panel ter-construct tanpa modul scheduler (offscreen-safe).
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    p = SchedulePanel()
    assert p.tbl.columnCount() == 4
    p.show()
    p.close()
    print("SMOKE schedule_panel: LULUS")
