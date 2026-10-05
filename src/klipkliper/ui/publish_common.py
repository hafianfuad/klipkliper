"""Helper bersama UI publish Fase 3.

Modul `klipkliper.publish.*` dibuat tim lain dan di-import LAZY di sini —
bila belum ada, fungsi mengembalikan pesan error yang jelas (bukan crash).
"""
from PySide6.QtWidgets import QMessageBox

# (key internal, label, modul, nama class)
PLATFORMS = [
    ("youtube", "YouTube", "klipkliper.publish.youtube", "YouTubePublisher"),
    ("tiktok", "TikTok", "klipkliper.publish.tiktok", "TikTokPublisher"),
    ("instagram", "Instagram", "klipkliper.publish.instagram", "InstagramPublisher"),
    ("facebook", "Facebook", "klipkliper.publish.facebook", "FacebookPublisher"),
]

_PUB_ERROR = {}  # name -> pesan error terakhir saat import/instansiasi


def get_publisher(name):
    """Bangun instance publisher. Raise RuntimeError bila modul belum ada."""
    for key, _label, modname, clsname in PLATFORMS:
        if key != name:
            continue
        try:
            mod = __import__(modname, fromlist=[clsname])
            cls = getattr(mod, clsname)
        except Exception as e:
            _PUB_ERROR[name] = f"Modul publish.{key} belum tersedia: {e}"
            raise RuntimeError(_PUB_ERROR[name])
        try:
            return cls()
        except Exception as e:
            _PUB_ERROR[name] = f"Gagal inisialisasi {key}: {e}"
            raise RuntimeError(_PUB_ERROR[name])
    raise RuntimeError(f"Platform tak dikenal: {name}")


def is_configured(name):
    """True bila publisher ada dan is_configured() True."""
    try:
        pub = get_publisher(name)
        return bool(pub.is_configured())
    except Exception:
        return False


def platform_status(name):
    """(configured: bool, catatan: str) untuk tampilan UI."""
    try:
        pub = get_publisher(name)
    except RuntimeError as e:
        return False, str(e)
    try:
        ok = bool(pub.is_configured())
    except Exception as e:
        return False, f"is_configured() error: {e}"
    return ok, ("terhubung" if ok else "belum dihubungkan")


def warn_missing(parent, name):
    """Tampilkan pesan jelas bila modul publish platform belum ada."""
    msg = _PUB_ERROR.get(name) or f"Modul publish.{name} belum tersedia."
    QMessageBox.warning(parent, "Publish",
                        f"{msg}\n\nDibuat tim modul publish — coba lagi nanti.")


if __name__ == "__main__":
    # Smoke: tanpa modul publish/*, semua platform reported missing (tanpa crash).
    for key, _label, _m, _c in PLATFORMS:
        ok, note = platform_status(key)
        print(f"{key}: configured={ok} ({note[:60]})")
    print("SMOKE publish_common: LULUS")
