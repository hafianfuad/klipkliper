"""Jendela utama Klipkliper — Fase 1 MVP.

Alur: Import Video/YouTube → analisis di worker (transkrip+face+skor) →
daftar klip kandidat → centang → Render → klip 9:16 di folder output.
"""
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QToolBar, QSplitter, QWidget, QVBoxLayout,
    QHBoxLayout, QFormLayout, QListWidget, QListWidgetItem, QTextEdit,
    QComboBox, QSpinBox, QPushButton, QProgressBar, QLabel, QFileDialog,
    QInputDialog, QMessageBox, QLineEdit, QCheckBox, QDockWidget,
)

from klipkliper.ui.preview import VideoPreview
from klipkliper.ui.worker import AnalyzeWorker, RenderWorker
from klipkliper.ui import settings as app_settings
from klipkliper.ui.queue_panel import QueuePanel
from klipkliper.ui.schedule_panel import SchedulePanel

try:
    from klipkliper import caption as _caption_mod
    STYLE_NAMES = list(_caption_mod.STYLES.keys())
except Exception:
    STYLE_NAMES = ["Hype"]


def _sequence_names():
    """Daftar sequence caption — lazy, fallback ['none'] bila modul Fase 2 belum ada."""
    try:
        from klipkliper import caption as cap
        if hasattr(cap, "list_sequences"):
            names = cap.list_sequences()
            if names:
                return list(names)
        seq = getattr(cap, "SEQUENCES", None)
        if seq:
            return list(seq.keys())
    except Exception:
        pass
    return ["none"]


def _grade_names():
    """Daftar color grade — lazy, fallback ['none'] bila modul Fase 2 belum ada."""
    try:
        from klipkliper import render as rmod
        g = getattr(rmod, "GRADES", None)
        if g:
            return list(g.keys())
    except Exception:
        pass
    return ["none"]


def _fmt_dur(sec):
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Klipkliper")
        self.resize(1200, 750)

        # state pipeline
        self._src = None
        self._media = None
        self._segments = []
        self._clips = []
        self._crop_xs = []
        self._workdir = None
        self._worker = None
        self._last_outdir = None
        self._last_results = []  # klip hasil render terakhir (untuk posting)

        self._build_toolbar()
        self._build_central()
        self._build_menubar()
        self.setStatusBar(self.statusBar())
        self._sync_provider_combo()
        self.log("Klipkliper siap. Import video untuk mulai.")

    # ---------- toolbar ----------
    def _build_toolbar(self):
        tb = QToolBar("Utama", self)
        tb.setMovable(False)
        self.addToolBar(tb)

        a_imp = QAction("📥 Import Video", self)
        a_imp.triggered.connect(self.import_video)
        tb.addAction(a_imp)

        a_yt = QAction("▶ Import YouTube URL", self)
        a_yt.triggered.connect(self.import_youtube)
        tb.addAction(a_yt)
        tb.addSeparator()

        tb.addWidget(QLabel(" Provider AI: "))
        self.cmb_provider = QComboBox()
        for val, label in app_settings.PROVIDERS:
            self.cmb_provider.addItem(label, val)
        self.cmb_provider.currentIndexChanged.connect(self._on_provider_changed)
        tb.addWidget(self.cmb_provider)

        a_set = QAction("⚙ Pengaturan", self)
        a_set.triggered.connect(self.open_settings)
        tb.addAction(a_set)
        tb.addSeparator()

        a_render = QAction("🎬 Render", self)
        a_render.triggered.connect(self.render_selected)
        tb.addAction(a_render)
        self._act_render = a_render
        tb.addSeparator()

        a_queue = QAction("📋 Antrean", self)
        a_queue.setCheckable(True)
        a_queue.setChecked(True)
        a_queue.toggled.connect(self._toggle_queue_dock)
        tb.addAction(a_queue)
        self._act_queue = a_queue
        tb.addSeparator()

        # Fase 3: posting & jadwal.
        a_post = QAction("📤 Posting", self)
        a_post.triggered.connect(self.open_publish_dialog)
        tb.addAction(a_post)

        a_sched = QAction("🗓 Jadwal", self)
        a_sched.setCheckable(True)
        a_sched.setChecked(True)
        a_sched.toggled.connect(self._toggle_schedule_dock)
        tb.addAction(a_sched)
        self._act_schedule = a_sched

    def _toggle_schedule_dock(self, on):
        if hasattr(self, "_dock_schedule"):
            self._dock_schedule.setVisible(on)

    def _toggle_queue_dock(self, on):
        if hasattr(self, "_dock_queue"):
            self._dock_queue.setVisible(on)

    def _sync_provider_combo(self):
        cfg = app_settings.load_settings()
        idx = self.cmb_provider.findData(cfg.get("provider", "none"))
        self.cmb_provider.blockSignals(True)
        self.cmb_provider.setCurrentIndex(max(idx, 0))
        self.cmb_provider.blockSignals(False)

    def _on_provider_changed(self):
        cfg = app_settings.load_settings()
        cfg["provider"] = self.cmb_provider.currentData()
        app_settings.save_settings(cfg)
        self.log(f"Provider AI: {self.cmb_provider.currentText()}")

    # ---------- layout tengah ----------
    def _build_central(self):
        split = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(split)

        # kiri: klip kandidat
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>Klip kandidat</b> (centang yang mau di-render)"))
        self.lst_clips = QListWidget()
        self.lst_clips.itemDoubleClicked.connect(self._on_clip_doubleclick)
        ll.addWidget(self.lst_clips)
        split.addWidget(left)

        # tengah: preview + transcript
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.addWidget(QLabel("<b>Preview</b>"))
        self.preview = VideoPreview()
        self.preview.position_changed.connect(self._on_pos)
        cl.addWidget(self.preview, stretch=3)
        prow = QHBoxLayout()
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(40)
        self.btn_play.clicked.connect(self.preview.play)
        self.btn_pause = QPushButton("⏸")
        self.btn_pause.setFixedWidth(40)
        self.btn_pause.clicked.connect(self.preview.pause)
        self.lbl_pos = QLabel("0:00")
        prow.addWidget(self.btn_play)
        prow.addWidget(self.btn_pause)
        prow.addWidget(self.lbl_pos)
        prow.addStretch(1)
        cl.addLayout(prow)
        cl.addWidget(QLabel("<b>Transcript</b> (klik → lompat)"))
        self.lst_transcript = QListWidget()
        self.lst_transcript.itemClicked.connect(self._on_transcript_click)
        cl.addWidget(self.lst_transcript, stretch=2)
        split.addWidget(center)

        # kanan: log + kontrol render
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("<b>Log</b>"))
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        rl.addWidget(self.txt_log, stretch=3)

        grid = QVBoxLayout()
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Style caption:"))
        self.cmb_style = QComboBox()
        self.cmb_style.addItems(STYLE_NAMES)
        row1.addWidget(self.cmb_style, stretch=1)
        row1.addWidget(QLabel("Jml klip:"))
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, 20)
        self.spin_n.setValue(5)
        row1.addWidget(self.spin_n)
        grid.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Output:"))
        self.txt_outdir = QLineEdit()
        self.txt_outdir.setReadOnly(True)
        self.txt_outdir.setPlaceholderText("Folder output klip")
        row2.addWidget(self.txt_outdir, stretch=1)
        btn_out = QPushButton("…")
        btn_out.setFixedWidth(32)
        btn_out.clicked.connect(self.choose_outdir)
        row2.addWidget(btn_out)
        grid.addLayout(row2)

        # ---- Opsi Fase 2 (tambah, tidak rombak yang di atas) ----
        f2 = QFormLayout()
        self.cmb_sequence = QComboBox()
        self.cmb_sequence.addItems(_sequence_names())
        f2.addRow("Sequence:", self.cmb_sequence)

        self.cmb_grade = QComboBox()
        self.cmb_grade.addItems(_grade_names())
        f2.addRow("Grade:", self.cmb_grade)

        logo_row = QHBoxLayout()
        self.txt_logo = QLineEdit()
        self.txt_logo.setReadOnly(True)
        self.txt_logo.setPlaceholderText("Logo PNG (opsional)")
        logo_row.addWidget(self.txt_logo, stretch=1)
        btn_logo = QPushButton("…")
        btn_logo.setFixedWidth(32)
        btn_logo.clicked.connect(self.choose_logo)
        logo_row.addWidget(btn_logo)
        f2.addRow("Logo:", logo_row)

        self.txt_hook = QLineEdit()
        self.txt_hook.setPlaceholderText("Teks hook 3 dtk (kosong = mati)")
        f2.addRow("Hook:", self.txt_hook)

        self.chk_vo = QCheckBox("🔊 Voiceover hook (edge-tts)")
        f2.addRow("", self.chk_vo)
        grid.addLayout(f2)

        brow = QHBoxLayout()
        self.btn_edit_tr = QPushButton("✏ Edit Transkrip")
        self.btn_edit_tr.clicked.connect(self.open_transcript_editor)
        self.btn_thumb = QPushButton("🖼 Buat Thumbnail")
        self.btn_thumb.clicked.connect(self.open_thumbnail_dialog)
        brow.addWidget(self.btn_edit_tr)
        brow.addWidget(self.btn_thumb)
        grid.addLayout(brow)

        self.btn_render = QPushButton("🎬 Render yang dipilih")
        self.btn_render.setEnabled(False)
        self.btn_render.clicked.connect(self.render_selected)
        grid.addWidget(self.btn_render)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        grid.addWidget(self.progress)

        self.btn_open = QPushButton("📂 Buka folder")
        self.btn_open.setEnabled(False)
        self.btn_open.clicked.connect(self.open_outdir)
        grid.addWidget(self.btn_open)
        rl.addLayout(grid)
        split.addWidget(right)

        split.setSizes([300, 500, 400])

        # Dock antrean render (Fase 2) — bisa di-toggle dari toolbar.
        self.queue_panel = QueuePanel(self)
        self.queue_panel.add_requested.connect(self._on_queue_add_requested)
        self._dock_queue = QDockWidget("Antrean Render", self)
        self._dock_queue.setWidget(self.queue_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock_queue)

        # Dock jadwal posting (Fase 3) — bisa di-toggle dari toolbar.
        self.schedule_panel = SchedulePanel(self)
        self._dock_schedule = QDockWidget("Jadwal Posting", self)
        self._dock_schedule.setWidget(self.schedule_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self._dock_schedule)
        self.tabifyDockWidget(self._dock_queue, self._dock_schedule)

    def _build_menubar(self):
        m_file = self.menuBar().addMenu("File")
        m_file.addAction("Import Video…", self.import_video)
        m_file.addAction("Import YouTube URL…", self.import_youtube)
        m_file.addSeparator()
        m_file.addAction("Keluar", self.close)
        m_set = self.menuBar().addMenu("Pengaturan")
        m_set.addAction("Pengaturan AI…", self.open_settings)

    # ---------- log & status ----------
    def log(self, msg):
        t = datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f"[{t}] {msg}")

    def _set_busy(self, busy, status=""):
        for w in (self.btn_render, self._act_render):
            w.setEnabled(not busy and bool(self._clips))
        self.progress.setRange(0, 0 if busy else 100)
        if not busy:
            self.progress.setValue(0)
        if status:
            self.statusBar().showMessage(status)

    # ---------- import & analisis ----------
    def import_video(self):
        if self._busy():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Video", "",
            "Video (*.mp4 *.mkv *.mov *.avi *.webm);;Semua file (*.*)")
        if path:
            self._start_analyze(path, is_url=False)

    def import_youtube(self):
        if self._busy():
            return
        url, ok = QInputDialog.getText(self, "Import YouTube", "URL video YouTube:")
        if ok and url.strip():
            self._start_analyze(url.strip(), is_url=True)

    def _busy(self):
        return self._worker is not None and self._worker.isRunning()

    def _start_analyze(self, source, is_url):
        cfg = app_settings.load_settings()
        self._clear_results()
        self.log(f"Analisis dimulai: {source[:80]}")
        self._worker = AnalyzeWorker(source, is_url, cfg,
                                     n_clips=self.spin_n.value(), parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_analyze_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(lambda *a: self._worker_done())
        self._worker.error.connect(lambda *a: self._worker_done())
        self._set_busy(True, "Menganalisis video…")
        self._worker.start()

    def _worker_done(self):
        self._worker = None
        self._set_busy(False, "Siap.")

    def _on_progress(self, stage, frac):
        self.progress.setRange(0, 100)
        self.progress.setValue(int(frac * 100))
        self.statusBar().showMessage(stage)

    def _on_worker_error(self, msg):
        self.log(f"❌ Error: {msg}")
        QMessageBox.warning(self, "Klipkliper", f"Gagal:\n{msg[:500]}")

    def _clear_results(self):
        self.lst_clips.clear()
        self.lst_transcript.clear()
        self._src = self._media = None
        self._segments, self._clips, self._crop_xs = [], [], []
        self.btn_render.setEnabled(False)
        self.btn_open.setEnabled(False)

    def _on_analyze_done(self, data):
        self._src = data["src"]
        self._media = data["media"]
        self._segments = data["segments"]
        self._clips = data["clips"]
        self._crop_xs = data["crop_xs"]
        self._workdir = data["workdir"]

        dur = self._media.get("duration", 0)
        self.log(f"Media: {Path(self._src).name} "
                 f"({self._media.get('width')}x{self._media.get('height')}, "
                 f"{_fmt_dur(dur)})")
        self.log(f"Transkrip: {len(self._segments)} segmen. "
                 f"Klip kandidat: {len(self._clips)}.")

        self._fill_transcript()

        for c in self._clips:
            d = c["end"] - c["start"]
            it = QListWidgetItem(f"[{c.get('score', 0):.0f}] {c.get('title', '')} "
                                 f"({_fmt_dur(d)})")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, c)
            self.lst_clips.addItem(it)

        if self.preview.load(self._src):
            self.log("Preview siap.")
        self.btn_render.setEnabled(True)
        self.statusBar().showMessage(
            f"{len(self._clips)} klip kandidat — centang lalu Render.", 8000)

    # ---------- interaksi ----------
    def _fill_transcript(self):
        """Isi ulang daftar transkrip dari self._segments."""
        self.lst_transcript.clear()
        for s in self._segments:
            it = QListWidgetItem(f"[{_fmt_dur(s['start'])}] {s['text'][:90]}")
            it.setData(Qt.UserRole, s["start"])
            self.lst_transcript.addItem(it)

    def _on_transcript_click(self, item):
        self.preview.seek(float(item.data(Qt.UserRole) or 0))

    def _on_clip_doubleclick(self, item):
        c = item.data(Qt.UserRole) or {}
        self.preview.seek(float(c.get("start", 0)))
        self.preview.play()

    def _on_pos(self, ms):
        self.lbl_pos.setText(_fmt_dur(ms / 1000))

    def open_settings(self):
        from klipkliper.ui.settings import SettingsDialog
        d = SettingsDialog(self)
        if d.exec():
            self._sync_provider_combo()
            self.log("Pengaturan disimpan.")

    def choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Folder output klip")
        if d:
            self.txt_outdir.setText(d)

    # ---------- fitur Fase 2 ----------
    def choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Logo overlay", "", "Gambar (*.png *.jpg *.jpeg)")
        if path:
            self.txt_logo.setText(path)

    def _render_options(self):
        """Opsi Fase 2 untuk RenderWorker (sequence, grade, logo, hook, voiceover)."""
        return {
            "sequence": self.cmb_sequence.currentText(),
            "grade": self.cmb_grade.currentText(),
            "logo_path": self.txt_logo.text().strip() or None,
            "hook_text": self.txt_hook.text().strip() or None,
            "voiceover": self.chk_vo.isChecked(),
        }

    def open_transcript_editor(self):
        if not self._segments:
            QMessageBox.information(self, "Klipkliper", "Belum ada transkrip.")
            return
        from klipkliper.ui.transcript_editor import TranscriptEditorDialog
        d = TranscriptEditorDialog(self._segments, self)
        if d.exec():
            self._segments = d.segments()
            self._fill_transcript()
            self.log(f"Transkrip diedit: {len(self._segments)} segmen.")

    def open_thumbnail_dialog(self):
        if not self._src:
            QMessageBox.information(self, "Klipkliper", "Import dulu sebuah video.")
            return
        from klipkliper.ui.thumbnail_dialog import ThumbnailDialog
        title = self._clips[0].get("title", "") if self._clips else ""
        d = ThumbnailDialog(self._src, title=title, parent=self)
        d.exec()

    def _on_queue_add_requested(self):
        if not self._src:
            QMessageBox.information(self, "Antrean", "Analisis dulu sebuah video.")
            return
        opts = self._render_options()
        job = {
            "src": self._src,
            "outdir": str(self._outdir()),
            "n_clips": self.spin_n.value(),
            "style": self.cmb_style.currentText(),
            "sequence": opts["sequence"],
            "grade": opts["grade"],
            "logo_path": opts["logo_path"],
            "hook_text": opts["hook_text"],
            "voiceover": opts["voiceover"],
            "status": "queued",
        }
        if self.queue_panel.add_job(job):
            self.log(f"Job ditambah ke antrean: {Path(self._src).name}")

    def _outdir(self):
        base = self.txt_outdir.text().strip()
        if not base:
            cfg = app_settings.load_settings()
            base = cfg.get("output_dir") or str(Path.home() / "Videos" / "Klipkliper")
        stem = Path(self._src).stem if self._src else "klip"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return Path(base) / f"{stem}_{stamp}"

    # ---------- render ----------
    def _selected_clips(self):
        out = []
        for i in range(self.lst_clips.count()):
            it = self.lst_clips.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def render_selected(self):
        if self._busy():
            return
        sel = self._selected_clips()
        if not sel:
            QMessageBox.information(self, "Klipkliper",
                                    "Centang dulu klip yang mau di-render.")
            return
        if not self._src or not self._crop_xs:
            QMessageBox.warning(self, "Klipkliper", "Belum ada video yang dianalisis.")
            return
        outdir = self._outdir()
        self._last_outdir = outdir
        self.log(f"Render {len(sel)} klip → {outdir}")
        self._worker = RenderWorker(
            self._src, self._segments, sel, self._crop_xs,
            self.cmb_style.currentText(), str(outdir),
            parent=self, options=self._render_options())
        self._worker.progress.connect(self._on_progress)
        self._worker.clip_done.connect(
            lambda c: self.log(f"✅ {Path(c['path']).name} — {c.get('title', '')[:50]}"))
        self._worker.finished.connect(self._on_render_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(lambda *a: self._worker_done())
        self._worker.error.connect(lambda *a: self._worker_done())
        self.btn_open.setEnabled(False)
        self._set_busy(True, "Me-render klip…")
        self._worker.start()

    def _on_render_done(self, results):
        self._last_results = list(results or [])
        self.log(f"🎉 Selesai: {len(results)} klip.")
        for r in results:
            self.log(f"   → {r['path']}")
        self.btn_open.setEnabled(True)
        QMessageBox.information(self, "Klipkliper",
                                f"{len(results)} klip selesai di-render.\n"
                                f"{self._last_outdir}")

    def open_outdir(self):
        if self._last_outdir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_outdir)))

    # ---------- fitur Fase 3: publish ----------
    def open_publish_dialog(self):
        """Buka dialog Posting untuk klip hasil render terakhir."""
        if not self._last_results:
            QMessageBox.information(
                self, "Posting",
                "Belum ada klip hasil render.\n"
                "Render dulu klipnya, lalu posting dari sini.")
            return
        from klipkliper.ui.publish_dialog import PublishDialog
        d = PublishDialog(self._last_results, self)
        d.exec()
        # Segarkan panel jadwal (barangkali ada yang baru dijadwalkan).
        try:
            self.schedule_panel.refresh()
        except Exception:
            pass

    def closeEvent(self, ev):
        if self._busy():
            self._worker.terminate()
            self._worker.wait(3000)
        super().closeEvent(ev)


def main(argv=None):
    args = sys.argv if argv is None else argv
    app = QApplication(args)
    app.setOrganizationName("Klipkliper")
    app.setApplicationName("Klipkliper")
    win = MainWindow()
    win.show()
    if "--smoke" in args:
        QTimer.singleShot(2000, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
