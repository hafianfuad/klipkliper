"""Panel Antrean Render — Fase 2.

Daftar job RenderQueue: tambah (dari video aktif), jalankan, pause/resume,
hapus, hapus selesai. Modul klipkliper.queue di-import LAZY — bila belum
ada, tombol menampilkan pesan jelas (dibuat tim modul).
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QMessageBox, QProgressBar,
)

from klipkliper.ui.worker import QueueWorker


class QueuePanel(QWidget):
    """Panel antrean. `add_requested` → main window menyuplai job dict."""

    add_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue = None
        self._worker = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Antrean Render</b>"))

        self.lst = QListWidget()
        lay.addWidget(self.lst, stretch=1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        lay.addWidget(self.progress)

        r1 = QHBoxLayout()
        b_add = QPushButton("＋ Tambah video aktif")
        b_add.clicked.connect(self.add_requested.emit)
        b_run = QPushButton("▶ Jalankan")
        b_run.clicked.connect(self.run_queue)
        r1.addWidget(b_add)
        r1.addWidget(b_run)
        lay.addLayout(r1)

        r2 = QHBoxLayout()
        b_pause = QPushButton("⏸ Pause")
        b_pause.clicked.connect(self._do_pause)
        b_resume = QPushButton("⏵ Resume")
        b_resume.clicked.connect(self._do_resume)
        b_del = QPushButton("🗑 Hapus")
        b_del.clicked.connect(self._do_delete)
        b_clear = QPushButton("🧹 Hapus selesai")
        b_clear.clicked.connect(self._do_clear_done)
        for b in (b_pause, b_resume, b_del, b_clear):
            r2.addWidget(b)
        lay.addLayout(r2)

    # ---------- queue (lazy) ----------
    def get_queue(self):
        if self._queue is not None:
            return self._queue
        try:
            from klipkliper.queue import RenderQueue
        except Exception:
            QMessageBox.warning(
                self, "Antrean",
                "Modul antrean (queue.py) belum tersedia.\n"
                "Dibuat tim modul — coba lagi nanti.")
            return None
        try:
            from pathlib import Path
            workdir = Path.home() / ".klipkliper" / "queue"
            self._queue = RenderQueue(workdir)
        except Exception as e:
            QMessageBox.warning(self, "Antrean", f"Gagal buat antrean:\n{e}")
            return None
        return self._queue

    # ---------- aksi ----------
    def add_job(self, job):
        """Tambah job dict ke antrean. Return True bila masuk."""
        q = self.get_queue()
        if q is None:
            return False
        job = dict(job)
        job.setdefault("status", "queued")
        try:
            q.add(job)
        except Exception as e:
            QMessageBox.warning(self, "Antrean", f"Gagal tambah job:\n{e}")
            return False
        self.refresh()
        return True

    def run_queue(self):
        q = self.get_queue()
        if q is None:
            return
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Antrean", "Antrean sedang berjalan.")
            return
        self._worker = QueueWorker(q, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.job_done.connect(
            lambda j: self.refresh())
        self._worker.finished.connect(self._on_qfinished)
        self._worker.error.connect(self._on_qerror)
        self._worker.finished.connect(lambda: self.refresh())
        self._worker.error.connect(lambda *a: self._worker_done())
        self._worker.finished.connect(lambda *a: self._worker_done())
        self.progress.setRange(0, 100)
        self._worker.start()

    def _worker_done(self):
        self._worker = None

    def _on_progress(self, stage, frac):
        self.progress.setValue(int(frac * 100))

    def _on_qfinished(self):
        self.progress.setValue(100)
        self.refresh()

    def _on_qerror(self, msg):
        QMessageBox.warning(self, "Antrean", f"Gagal:\n{msg[:500]}")

    def _do_pause(self):
        q = self.get_queue()
        if q and hasattr(q, "pause"):
            q.pause()
            self.refresh()

    def _do_resume(self):
        q = self.get_queue()
        if q and hasattr(q, "resume"):
            q.resume()
            self.refresh()

    def _do_delete(self):
        q = self.get_queue()
        if q is None:
            return
        row = self.lst.currentRow()
        jobs = self._jobs(q)
        if 0 <= row < len(jobs):
            jid = jobs[row].get("id")
            try:
                if jid and hasattr(q, "remove"):
                    q.remove(jid)
                else:  # fallback: pop + save
                    q.list().pop(row)
                    if hasattr(q, "save"):
                        q.save()
            except Exception:
                pass
            self.refresh()

    def _do_clear_done(self):
        q = self.get_queue()
        if q and hasattr(q, "clear_done"):
            q.clear_done()
            self.refresh()

    # ---------- tampilan ----------
    def _jobs(self, q):
        try:
            return list(q.list())
        except Exception:
            return []

    def refresh(self):
        self.lst.clear()
        q = self._queue  # jangan trigger QMessageBox saat refresh
        if q is None:
            self.lst.addItem("(modul queue.py belum tersedia)")
            return
        jobs = self._jobs(q)
        if not jobs:
            self.lst.addItem("(antrean kosong)")
            return
        for j in jobs:
            src = str(j.get("src", "?"))
            name = src.split("/")[-1].split("\\")[-1]
            st = j.get("status", "queued")
            frac = j.get("progress", None)
            extra = f" {int(frac*100)}%" if isinstance(frac, (int, float)) else ""
            it = QListWidgetItem(f"[{st}]{extra} {name} "
                                 f"({j.get('n_clips', '?')} klip, {j.get('style', '?')})")
            if st in ("done",):
                it.setForeground(Qt.darkGreen)
            elif st in ("failed",):
                it.setForeground(Qt.red)
            self.lst.addItem(it)


if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    p = QueuePanel()
    assert p.lst is not None
    p.refresh()  # tanpa queue → placeholder, tanpa error
    assert p.lst.count() >= 1
    print("SMOKE queue_panel: LULUS")
