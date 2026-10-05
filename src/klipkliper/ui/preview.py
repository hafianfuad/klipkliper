"""Widget preview video dengan fallback aman.

Di platform/offscreen tanpa backend multimedia, widget menampilkan QLabel
placeholder — tidak pernah crash saat import maupun konstruksi.
"""
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PySide6.QtMultimediaWidgets import QVideoWidget
    _MULTIMEDIA_IMPORT_OK = True
except Exception:
    _MULTIMEDIA_IMPORT_OK = False


class VideoPreview(QWidget):
    """Preview video. API aman dipanggil walau backend tak tersedia."""

    position_changed = Signal(int)  # ms
    duration_changed = Signal(int)  # ms

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = None
        self._available = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        if _MULTIMEDIA_IMPORT_OK:
            try:
                vw = QVideoWidget()
                player = QMediaPlayer()
                audio = QAudioOutput()
                player.setAudioOutput(audio)
                player.setVideoOutput(vw)
                player.positionChanged.connect(self.position_changed)
                player.durationChanged.connect(self.duration_changed)
                player.errorOccurred.connect(self._on_error)
                lay.addWidget(vw)
                self._player = player
                self._available = True
            except Exception:
                self._player = None

        if not self._available:
            ph = QLabel("Preview video tidak tersedia\n di environment ini")
            ph.setAlignment(Qt.AlignCenter)
            ph.setStyleSheet("color:#888; border:1px dashed #888;")
            ph.setMinimumHeight(200)
            lay.addWidget(ph)

    # ---- API publik ----
    def is_available(self):
        return self._available

    def load(self, path):
        """Muat file video. Return True bila backend siap."""
        if not self._available:
            return False
        try:
            self._player.setSource(QUrl.fromLocalFile(str(path)))
            return True
        except Exception:
            return False

    def play(self):
        if self._available:
            self._player.play()

    def pause(self):
        if self._available:
            self._player.pause()

    def stop(self):
        if self._available:
            self._player.stop()

    def seek(self, seconds):
        """Lompat ke detik tertentu."""
        if self._available:
            try:
                self._player.setPosition(int(seconds * 1000))
            except Exception:
                pass

    def _on_error(self, *args):
        # Jangan crash — error player cukup diabaikan di MVP.
        pass
