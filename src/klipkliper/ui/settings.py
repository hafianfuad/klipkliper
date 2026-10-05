"""Dialog Pengaturan + QSettings Klipkliper.

API key: pakai keyring bila terinstal, else QSettings biasa.
"""
import os

from PySide6.QtCore import QSettings, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QLineEdit, QDialogButtonBox,
    QVBoxLayout, QPushButton, QLabel, QMessageBox,
)

ORG = "Klipkliper"
APP = "Klipkliper"

# value internal -> label
PROVIDERS = [
    ("none", "Tanpa AI (heuristic)"),
    ("groq", "Groq"),
    ("claude", "Claude (Anthropic)"),
    ("openai", "OpenAI (GPT)"),
    ("gemini-oauth", "Gemini (OAuth Google)"),
]
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large"]

_DEFAULTS = {
    "provider": "none",
    "api_key": "",
    "model": "",
    "whisper_model": "small",
    "lang": "id",
    "output_dir": "",
}

_ENV_BY_PROVIDER = {"groq": "GROQ_API_KEY", "claude": "ANTHROPIC_API_KEY",
                    "openai": "OPENAI_API_KEY"}


def _keyring():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def load_settings():
    """Baca pengaturan → dict."""
    s = QSettings(ORG, APP)
    cfg = {k: s.value(k, v) for k, v in _DEFAULTS.items()}
    kr = _keyring()
    if kr:
        try:
            cfg["api_key"] = kr.get_password(ORG, "api_key") or ""
        except Exception:
            pass
    return cfg


def save_settings(cfg):
    """Simpan dict pengaturan."""
    s = QSettings(ORG, APP)
    kr = _keyring()
    for k, v in cfg.items():
        if k == "api_key" and kr:
            try:
                if v:
                    kr.set_password(ORG, "api_key", v)
                else:
                    kr.delete_password(ORG, "api_key")
            except Exception:
                s.setValue(k, v)
        else:
            s.setValue(k, v)
    s.sync()


def get_api_key(cfg=None):
    """API key efektif: settings → keyring → env (per provider)."""
    cfg = cfg or load_settings()
    key = cfg.get("api_key") or ""
    if not key:
        env = _ENV_BY_PROVIDER.get(cfg.get("provider", "none"))
        if env:
            key = os.environ.get(env, "")
    return key


def _provider_name(cfg):
    # UI memakai "gemini-oauth"; factory memakai "gemini".
    return {"gemini-oauth": "gemini"}.get(cfg.get("provider"), cfg.get("provider"))


def get_provider(cfg=None):
    """Bangun provider dari pengaturan. None bila provider 'none'."""
    from klipkliper.providers import make_provider
    cfg = cfg or load_settings()
    name = _provider_name(cfg)
    if name == "none":
        return None
    return make_provider(name, api_key=get_api_key(cfg) or None,
                         model=cfg.get("model") or None)


class _TestWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg

    def run(self):
        try:
            p = get_provider(self.cfg)
            if p is None:
                self.done.emit(True, "Mode heuristic — tidak butuh koneksi.")
                return
            r = p.chat([{"role": "user", "content": "Balas persis: OK"}])
            ok = "OK" in r
            self.done.emit(ok, f"Respons: {r[:120]}" if ok else f"Respons tak terduga: {r[:120]}")
        except Exception as e:
            self.done.emit(False, str(e)[:300])


class SettingsDialog(QDialog):
    """Dialog pengaturan AI & transkripsi."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pengaturan — Klipkliper")
        self.setModal(True)
        self._test_worker = None
        cfg = load_settings()

        form = QFormLayout()
        self.cmb_provider = QComboBox()
        for val, label in PROVIDERS:
            self.cmb_provider.addItem(label, val)
        idx = self.cmb_provider.findData(cfg.get("provider", "none"))
        self.cmb_provider.setCurrentIndex(max(idx, 0))
        form.addRow("Provider AI:", self.cmb_provider)

        self.txt_key = QLineEdit(cfg.get("api_key", ""))
        self.txt_key.setEchoMode(QLineEdit.Password)
        self.txt_key.setPlaceholderText("API key (tidak wajib untuk Gemini OAuth)")
        form.addRow("API key:", self.txt_key)

        self.txt_model = QLineEdit(cfg.get("model", ""))
        self.txt_model.setPlaceholderText("Kosongkan = default provider")
        form.addRow("Model:", self.txt_model)

        self.cmb_whisper = QComboBox()
        self.cmb_whisper.addItems(WHISPER_MODELS)
        self.cmb_whisper.setCurrentText(cfg.get("whisper_model", "small"))
        form.addRow("Model Whisper:", self.cmb_whisper)

        self.txt_lang = QComboBox()
        self.txt_lang.setEditable(True)
        self.txt_lang.addItems(["id", "en"])
        self.txt_lang.setCurrentText(cfg.get("lang", "id"))
        form.addRow("Bahasa:", self.txt_lang)

        lay = QVBoxLayout(self)
        lay.addLayout(form)

        row = QVBoxLayout()
        self.btn_test = QPushButton("Tes koneksi")
        self.btn_test.clicked.connect(self._test)
        self.lbl_test = QLabel("")
        self.lbl_test.setWordWrap(True)
        row.addWidget(self.btn_test)
        row.addWidget(self.lbl_test)
        lay.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _collect(self):
        return {
            "provider": self.cmb_provider.currentData(),
            "api_key": self.txt_key.text().strip(),
            "model": self.txt_model.text().strip(),
            "whisper_model": self.cmb_whisper.currentText(),
            "lang": self.txt_lang.currentText().strip() or "id",
        }

    def _test(self):
        if self._test_worker and self._test_worker.isRunning():
            return
        cfg = self._collect()
        if cfg["provider"] != "none" and cfg["provider"] != "gemini-oauth" \
                and not get_api_key(cfg):
            QMessageBox.warning(self, "Klipkliper",
                                "API key kosong — isi dulu atau tes akan gagal.")
            return
        self.btn_test.setEnabled(False)
        self.lbl_test.setText("Mengetes…")
        self._test_worker = _TestWorker(cfg, self)
        self._test_worker.done.connect(self._on_test_done)
        self._test_worker.start()

    def _on_test_done(self, ok, msg):
        self.btn_test.setEnabled(True)
        self.lbl_test.setText(("✅ " if ok else "❌ ") + msg)

    def accept(self):
        save_settings(self._collect())
        super().accept()

    def closeEvent(self, ev):
        if self._test_worker and self._test_worker.isRunning():
            self._test_worker.terminate()
            self._test_worker.wait(3000)
        super().closeEvent(ev)


if __name__ == "__main__":
    # Smoke test: dialog terbuka/tertutup tanpa error (offscreen-safe).
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    d = SettingsDialog()
    assert d.cmb_provider.count() == len(PROVIDERS)
    assert d.cmb_whisper.count() == len(WHISPER_MODELS)
    d.show()
    d.close()
    print("SMOKE settings: LULUS")
