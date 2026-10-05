"""Dialog kredensial publish Fase 3 (YouTube/TikTok/Instagram/Facebook).

Penyimpanan: QSettings untuk field biasa + keyring untuk secret
(pola sama seperti ui/settings.py). Selain itu ditulis juga ke
`~/.klipkliper/publish_creds.json` (permission 0600) agar modul
`klipkliper.publish.*` dan CLI bisa membaca tanpa Qt.

Fungsi publik:
    load_pub_settings() -> {"youtube": {...}, "tiktok": {...}, ...}
"""
import json
import os
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QStackedWidget, QWidget, QFormLayout, QLineEdit, QPushButton,
    QLabel, QDialogButtonBox, QMessageBox, QInputDialog,
)

ORG = "Klipkliper"
APP = "Klipkliper"
CREDS_FILE = Path.home() / ".klipkliper" / "publish_creds.json"

# platform -> [(field_key, label, is_secret, placeholder)]
PLATFORM_FIELDS = {
    "youtube": [
        ("client_id", "Client ID (OAuth):", False,
         "xxxx.apps.googleusercontent.com"),
        ("client_secret", "Client Secret:", True, "GOCSPX-..."),
    ],
    "tiktok": [
        ("client_key", "Client Key:", True, "dari TikTok Developer Portal"),
        ("access_token", "Access Token:", True, ""),
    ],
    "instagram": [
        ("ig_user_id", "IG User ID:", False, "angka"),
        ("access_token", "Access Token:", True, "token Graph API"),
    ],
    "facebook": [
        ("page_id", "Page ID:", False, "angka"),
        ("access_token", "Access Token:", True, "token Page"),
    ],
}

PLATFORM_LABELS = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "facebook": "Facebook",
}


def _keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def _qsettings_key(platform, field):
    return f"pub_{platform}_{field}"


def load_pub_settings():
    """Baca kredensial publish → dict per platform (termasuk secret)."""
    s = QSettings(ORG, APP)
    kr = _keyring()
    out = {}
    for platform, fields in PLATFORM_FIELDS.items():
        d = {}
        for fkey, _label, secret, _ph in fields:
            val = ""
            if secret and kr:
                try:
                    val = kr.get_password(ORG, _qsettings_key(platform, fkey)) or ""
                except Exception:
                    val = ""
            if not val:
                val = s.value(_qsettings_key(platform, fkey), "") or ""
            d[fkey] = val
        out[platform] = d
    return out


def save_pub_settings(cfg):
    """Simpan dict kredensial (struktur seperti load_pub_settings)."""
    s = QSettings(ORG, APP)
    kr = _keyring()
    for platform, fields in cfg.items():
        for fkey, val in fields.items():
            secret = any(f == fkey and sec
                         for f, _l, sec, _p in PLATFORM_FIELDS.get(platform, []))
            if secret and kr:
                try:
                    if val:
                        kr.set_password(ORG, _qsettings_key(platform, fkey), val)
                    else:
                        kr.delete_password(ORG, _qsettings_key(platform, fkey))
                    continue
                except Exception:
                    pass
            s.setValue(_qsettings_key(platform, fkey), val)
    s.sync()
    _write_creds_file(cfg)


def _write_creds_file(cfg):
    """Tulis publish_creds.json (0600) untuk modul publish/CLI non-Qt."""
    try:
        CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Jangan tulis secret kosong berlebih; tulis apa adanya (0600).
        with open(CREDS_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
        os.chmod(CREDS_FILE, 0o600)
    except Exception:
        pass


def youtube_token_exists():
    """True bila file token YouTube OAuth sudah ada."""
    p = Path.home() / ".klipkliper" / "youtube_token.json"
    return p.is_file()


class _PlatformPage(QWidget):
    """Satu halaman form kredensial untuk satu platform."""

    def __init__(self, platform, parent=None):
        super().__init__(parent)
        self.platform = platform
        self.edits = {}
        cfg = load_pub_settings().get(platform, {})

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"<b>{PLATFORM_LABELS[platform]}</b>"))

        form = QFormLayout()
        for fkey, label, secret, ph in PLATFORM_FIELDS[platform]:
            e = QLineEdit(cfg.get(fkey, ""))
            if secret:
                e.setEchoMode(QLineEdit.Password)
            e.setPlaceholderText(ph)
            self.edits[fkey] = e
            form.addRow(label, e)
        lay.addLayout(form)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)

        if platform == "youtube":
            b = QPushButton("🔑 Authorize via browser…")
            b.clicked.connect(self._authorize_youtube)
            lay.addWidget(b)
        lay.addStretch(1)
        self.refresh_status()

    def collect(self):
        return {k: e.text().strip() for k, e in self.edits.items()}

    def refresh_status(self):
        if self.platform == "youtube":
            ok = youtube_token_exists()
            self.lbl_status.setText(
                "✅ Token YouTube tersimpan." if ok
                else "⚠️ Belum ada token YouTube — isi Client ID/Secret lalu Authorize.")
        else:
            vals = self.collect()
            filled = sum(1 for v in vals.values() if v)
            self.lbl_status.setText(
                f"{filled}/{len(vals)} field terisi." if filled
                else "Belum ada kredensial.")

    def _authorize_youtube(self):
        """Flow OAuth YouTube: URL authorize → browser → input code → tukar token."""
        vals = self.collect()
        cid, csec = vals.get("client_id", ""), vals.get("client_secret", "")
        if not cid or not csec:
            QMessageBox.warning(self, "YouTube",
                                "Isi Client ID dan Client Secret dulu, lalu simpan.")
            return
        try:
            from klipkliper.publish import google_oauth as go
        except Exception as e:
            QMessageBox.warning(
                self, "YouTube",
                f"Modul publish.google_oauth belum tersedia: {e}\n"
                "Dibuat tim modul publish — coba lagi nanti.")
            return
        try:
            url = go.authorize_url(cid)
        except Exception as e:
            QMessageBox.warning(self, "YouTube", f"Gagal buat URL authorize:\n{e}")
            return
        QDesktopServices.openUrl(QUrl(url))
        code, ok = QInputDialog.getText(
            self, "YouTube", "Paste kode dari browser:")
        if not (ok and code.strip()):
            return
        try:
            go.exchange_code(code.strip(), cid, csec)
        except Exception as e:
            QMessageBox.warning(self, "YouTube", f"Gagal tukar kode:\n{e}")
            return
        QMessageBox.information(self, "YouTube", "Token tersimpan. YouTube terhubung! ✅")
        self.refresh_status()


class PublishSettingsDialog(QDialog):
    """Dialog kredensial publish per platform."""

    def __init__(self, parent=None, select=None):
        super().__init__(parent)
        self.setWindowTitle("Kredensial Publish — Klipkliper")
        self.setModal(True)
        self.resize(560, 380)
        self._pages = {}

        lay = QHBoxLayout(self)
        self.lst = QListWidget()
        self.lst.setMaximumWidth(150)
        for key in PLATFORM_FIELDS:
            it = QListWidgetItem(PLATFORM_LABELS[key])
            it.setData(Qt.UserRole, key)
            self.lst.addItem(it)
        self.lst.currentRowChanged.connect(self._on_select)
        lay.addWidget(self.lst)

        right = QVBoxLayout()
        self.stack = QStackedWidget()
        for key in PLATFORM_FIELDS:
            page = _PlatformPage(key, self)
            self._pages[key] = page
            self.stack.addWidget(page)
        right.addWidget(self.stack, stretch=1)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
        btns.button(QDialogButtonBox.Save).setText("Simpan")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        right.addWidget(btns)
        lay.addLayout(right, stretch=1)

        if select in PLATFORM_FIELDS:
            keys = list(PLATFORM_FIELDS.keys())
            self.lst.setCurrentRow(keys.index(select))
        else:
            self.lst.setCurrentRow(0)

    def _on_select(self, row):
        self.stack.setCurrentIndex(max(row, 0))

    def _save(self):
        cfg = {k: p.collect() for k, p in self._pages.items()}
        save_pub_settings(cfg)
        for p in self._pages.values():
            p.refresh_status()
        QMessageBox.information(self, "Klipkliper", "Kredensial publish disimpan.")


if __name__ == "__main__":
    # Smoke: dialog ter-construct + halaman per platform ada (offscreen-safe).
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    d = PublishSettingsDialog()
    assert d.stack.count() == len(PLATFORM_FIELDS) == 4
    assert d.lst.count() == 4
    d.show()
    d.close()
    print("SMOKE publish_settings: LULUS")
