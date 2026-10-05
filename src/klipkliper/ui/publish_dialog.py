"""Dialog "Posting Klip" Fase 3 — autopost & schedule ke 4 platform.

Label EKSPERIMENTAL selalu terlihat (status AutoClip: experimental).
Modul klipkliper.publish.* di-import LAZY via publish_common + worker.
"""
from datetime import datetime

from PySide6.QtCore import Qt, QDateTime
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QListWidget,
    QListWidgetItem, QLineEdit, QTextEdit, QComboBox, QCheckBox,
    QPushButton, QLabel, QMessageBox, QDateTimeEdit, QDialogButtonBox,
)

from klipkliper.ui import publish_common as pc
from klipkliper.ui.worker import PublishWorker


class PublishDialog(QDialog):
    """Dialog posting klip hasil render.

    Args:
        clips: [{"path": str, "title": str}] — klip yang bisa dipilih.
    """

    def __init__(self, clips, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Posting Klip — Klipkliper")
        self.setModal(True)
        self.resize(560, 640)
        self._clips = list(clips or [])
        self._worker = None
        self._plat_check = {}
        self._plat_status = {}

        lay = QVBoxLayout(self)

        banner = QLabel("⚠️ EKSPERIMENTAL — autopost bisa gagal / kena limit API. "
                        "Cek hasil tiap posting.")
        banner.setStyleSheet("background:#fff3cd; color:#856404; padding:6px; "
                             "border:1px solid #ffeeba; border-radius:4px;")
        banner.setWordWrap(True)
        lay.addWidget(banner)

        lay.addWidget(QLabel("<b>Klip yang diposting:</b>"))
        self.lst_clips = QListWidget()
        self.lst_clips.setMaximumHeight(110)
        for c in self._clips:
            it = QListWidgetItem(f"{c.get('title', '')[:60]} "
                                 f"({c.get('path', '')[-24:]})")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, c)
            self.lst_clips.addItem(it)
        if not self._clips:
            self.lst_clips.addItem("(belum ada klip hasil render)")
            self.lst_clips.setEnabled(False)
        lay.addWidget(self.lst_clips)

        form = QFormLayout()
        self.txt_title = QLineEdit(
            self._clips[0].get("title", "") if self._clips else "")
        form.addRow("Judul:", self.txt_title)
        self.txt_desc = QTextEdit()
        self.txt_desc.setMaximumHeight(70)
        self.txt_desc.setPlaceholderText("Deskripsi (opsional)")
        form.addRow("Deskripsi:", self.txt_desc)
        self.txt_tags = QLineEdit()
        self.txt_tags.setPlaceholderText("tag1, tag2, tag3")
        form.addRow("Tags:", self.txt_tags)
        lay.addLayout(form)

        lay.addWidget(QLabel("<b>Platform:</b>"))
        for key, label, _m, _c in pc.PLATFORMS:
            row = QHBoxLayout()
            chk = QCheckBox(label)
            st = QLabel("")
            st.setStyleSheet("color:#666;")
            btn = QPushButton("Hubungkan…")
            btn.setMaximumWidth(110)
            btn.clicked.connect(lambda _=None, k=key: self._connect(k))
            row.addWidget(chk)
            row.addWidget(st, stretch=1)
            row.addWidget(btn)
            lay.addLayout(row)
            self._plat_check[key] = chk
            self._plat_status[key] = st
        self._refresh_platforms()

        prow = QHBoxLayout()
        prow.addWidget(QLabel("Privasi YouTube:"))
        self.cmb_privacy = QComboBox()
        for val, lab in [("private", "Private"), ("unlisted", "Tidak publik"),
                         ("public", "Publik")]:
            self.cmb_privacy.addItem(lab, val)
        prow.addWidget(self.cmb_privacy)
        prow.addStretch(1)
        lay.addLayout(prow)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("Jadwal:"))
        self.dt_when = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.dt_when.setCalendarPopup(True)
        self.dt_when.setDisplayFormat("dd-MM-yyyy HH:mm")
        srow.addWidget(self.dt_when)
        srow.addStretch(1)
        lay.addLayout(srow)

        brow = QHBoxLayout()
        self.btn_post = QPushButton("📤 Posting sekarang")
        self.btn_post.clicked.connect(lambda: self._start("publish"))
        self.btn_sched = QPushButton("🗓 Jadwalkan")
        self.btn_sched.clicked.connect(lambda: self._start("schedule"))
        brow.addWidget(self.btn_post)
        brow.addWidget(self.btn_sched)
        lay.addLayout(brow)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    # ---------- platform ----------
    def _refresh_platforms(self):
        for key, _label, _m, _c in pc.PLATFORMS:
            ok, note = pc.platform_status(key)
            chk = self._plat_check[key]
            chk.setEnabled(ok)
            if not ok:
                chk.setChecked(False)
            self._plat_status[key].setText(
                ("✅ " if ok else "⚠️ ") + note[:80])

    def _connect(self, platform):
        from klipkliper.ui.publish_settings import PublishSettingsDialog
        d = PublishSettingsDialog(self, select=platform)
        d.exec()
        self._refresh_platforms()

    # ---------- jobs ----------
    def _selected_clips(self):
        out = []
        for i in range(self.lst_clips.count()):
            it = self.lst_clips.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def _selected_platforms(self):
        return [k for k, chk in self._plat_check.items()
                if chk.isEnabled() and chk.isChecked()]

    def _tags(self):
        return [t.strip() for t in self.txt_tags.text().split(",") if t.strip()]

    def _collect(self, scheduled):
        clips = self._selected_clips()
        plats = self._selected_platforms()
        title = self.txt_title.text().strip()
        if not clips:
            QMessageBox.information(self, "Posting", "Pilih dulu klipnya.")
            return None
        if not plats:
            QMessageBox.information(
                self, "Posting",
                "Pilih dulu platformnya (hubungkan bila belum).")
            return None
        if not title:
            QMessageBox.information(self, "Posting", "Judul tidak boleh kosong.")
            return None
        at_iso = ""
        if scheduled:
            dt = self.dt_when.dateTime().toPython()
            if dt <= datetime.now():
                r = QMessageBox.question(
                    self, "Jadwal",
                    "Waktu jadwal sudah lewat — tetap simpan? "
                    "(akan dianggap jatuh tempo)")
                if r != QMessageBox.Yes:
                    return None
            at_iso = dt.isoformat(timespec="seconds")
        jobs = []
        for c in clips:
            for p in plats:
                extra = {}
                if p == "youtube":
                    extra["privacy"] = self.cmb_privacy.currentData()
                job = {
                    "platform": p,
                    "video_path": c["path"],
                    "title": title,
                    "description": self.txt_desc.toPlainText().strip(),
                    "tags": self._tags(),
                    "extra": extra,
                }
                if scheduled:
                    job["at_iso"] = at_iso
                jobs.append(job)
        return jobs

    # ---------- eksekusi ----------
    def _start(self, mode):
        if self._worker is not None and self._worker.isRunning():
            return
        jobs = self._collect(scheduled=(mode == "schedule"))
        if not jobs:
            return
        self.btn_post.setEnabled(False)
        self.btn_sched.setEnabled(False)
        self.lbl_status.setText("Bekerja…")
        self._worker = PublishWorker(mode, jobs=jobs, parent=self)
        self._worker.progress.connect(
            lambda s, f: self.lbl_status.setText(s))
        self._worker.job_done.connect(self._on_job_done)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _on_job_done(self, info):
        if info.get("ok"):
            if "job_id" in info:
                msg = (f"✅ Terjadwal: {info['platform']} @ {info.get('at')} "
                       f"(id {info['job_id']})")
            else:
                res = info.get("result") or {}
                url = res.get("url", "")
                msg = f"✅ {info['platform']}: {url or res}"
        else:
            msg = f"❌ {info['platform']}: {info.get('error')}"
        cur = self.lbl_status.text()
        self.lbl_status.setText((cur + "\n" if cur else "") + msg)

    def _on_error(self, msg):
        QMessageBox.warning(self, "Posting", f"Gagal:\n{msg[:500]}")
        self._on_finished()

    def _on_finished(self):
        self._worker = None
        self.btn_post.setEnabled(True)
        self.btn_sched.setEnabled(True)

    def closeEvent(self, ev):
        if self._worker is not None and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(3000)
        super().closeEvent(ev)


if __name__ == "__main__":
    # Smoke: dialog ter-construct tanpa modul publish/* (offscreen-safe).
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    d = PublishDialog([{"path": "/tmp/x.mp4", "title": "Tes"}])
    assert d.lst_clips.count() == 1
    assert len(d._plat_check) == 4
    d.show()
    d.close()
    print("SMOKE publish_dialog: LULUS")
