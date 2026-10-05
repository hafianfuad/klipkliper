"""Ingest media untuk Klipkliper: probe, file lokal, unduh YouTube.

Fungsi utama:
    probe(path) -> MediaInfo
    from_local(path, workdir) -> MediaInfo
    from_youtube(url, workdir) -> MediaInfo
"""
import json
import os
import shutil
import subprocess
from pathlib import Path


class IngestError(Exception):
    """Gagal ingest media (file rusak, URL diblokir, dsb)."""


def _run(cmd):
    """Jalankan subprocess, kembalikan stdout. Raise IngestError bila gagal."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        raise IngestError(f"perintah tidak ditemukan: {cmd[0]}")
    except subprocess.TimeoutExpired:
        raise IngestError(f"timeout menjalankan: {' '.join(cmd)}")
    if p.returncode != 0:
        raise IngestError(f"gagal: {' '.join(cmd)}\n{p.stderr.strip()[:500]}")
    return p.stdout


def _parse_fps(s):
    """'30/1' atau '30000/1001' -> float. Kembalikan 0.0 bila tak valid."""
    try:
        if "/" in s:
            a, b = s.split("/", 1)
            b = float(b)
            return float(a) / b if b else 0.0
        return float(s)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path):
    """Baca metadata video via ffprobe.

    Returns:
        dict {"path", "duration", "width", "height", "fps"}.
    Raises:
        IngestError: file tidak ada / bukan video / ffprobe gagal.
    """
    p = Path(path)
    if not p.is_file():
        raise IngestError(f"file tidak ditemukan: {path}")
    out = _run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-show_entries", "stream=width,height,avg_frame_rate,codec_type",
        "-of", "json", str(p),
    ])
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise IngestError(f"ffprobe output tidak valid untuk: {path}")
    vstreams = [s for s in data.get("streams", [])
                if s.get("codec_type") == "video"]
    if not vstreams:
        raise IngestError(f"tidak ada stream video di: {path}")
    v = vstreams[0]
    try:
        duration = float(data.get("format", {}).get("duration") or 0.0)
    except (ValueError, TypeError):
        duration = 0.0
    if duration <= 0:
        raise IngestError(f"durasi tidak valid untuk: {path}")
    fps = _parse_fps(v.get("avg_frame_rate", "0/0")) or 30.0
    return {
        "path": str(p.resolve()),
        "duration": duration,
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "fps": fps,
    }


def from_local(path, workdir):
    """Siapkan file lokal ke workdir.

    Bila file sudah di dalam workdir dipakai langsung; bila tidak,
    buat symlink (fallback: copy). Validasi via probe().
    """
    p = Path(path)
    if not p.is_file():
        raise IngestError(f"file tidak ditemukan: {path}")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        if p.resolve().parent == workdir.resolve():
            target = p.resolve()
        else:
            link = workdir / p.name
            if link.exists() or link.is_symlink():
                link.unlink()
            try:
                os.symlink(p.resolve(), link)
            except OSError:
                shutil.copy2(p, link)
            target = link.resolve()
    except OSError as e:
        raise IngestError(f"gagal menyiapkan file lokal: {e}")
    info = probe(target)
    info["path"] = str(target)
    return info


def from_youtube(url, workdir):
    """Unduh video YouTube ke workdir via yt-dlp.

    Format: bv*[height<=1080]+ba/b[height<=1080]/b.
    Raise IngestError dengan pesan jelas bila diblokir (bot-check) —
    TANPA retry loop.
    """
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError:
        raise IngestError("yt-dlp tidak terinstal")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except DownloadError as e:
        msg = str(e)
        if "not a bot" in msg or "Sign in" in msg:
            raise IngestError(
                "YouTube memblokir unduhan (bot-check). "
                "Coba unduh manual lalu pakai file lokal, "
                "atau teruskan cookies browser via --cookies."
            )
        raise IngestError(f"unduh YouTube gagal: {msg[:300]}")
    except Exception as e:  # noqa: BLE001 — yt-dlp bisa raise macam-macam
        raise IngestError(f"unduh YouTube gagal: {e}")
    vid = (info or {}).get("id", "video")
    # Cari file hasil unduhan (ekstensi bisa berubah setelah merge).
    candidates = sorted(workdir.glob(f"{vid}.*"),
                        key=lambda f: f.stat().st_mtime, reverse=True)
    if not candidates:
        raise IngestError("unduhan selesai tapi file tidak ditemukan di workdir")
    target = candidates[0]
    meta = probe(target)
    meta["path"] = str(target.resolve())
    return meta


if __name__ == "__main__":
    import sys
    arg = sys.argv[1] if len(sys.argv) > 1 else "testdata/test-video.mp4"
    if arg.startswith(("http://", "https://")):
        print(from_youtube(arg, "testdata/work"))
    elif __import__("os").path.isfile(arg):
        print(probe(arg))
    else:
        print("pakai: ingest.py <file|url>")


# ---------- bulk YouTube (Fase 3) ----------

def list_youtube_videos(url, max_videos=20):
    """Daftar video dari channel/playlist YouTube TANPA download.

    Args:
        url: URL channel / playlist / video YouTube.
        max_videos: batas jumlah entri.

    Returns:
        list[{"id", "title", "url"}].

    Raises:
        IngestError: URL diblokir / tidak terbaca (TANPA retry loop).
    """
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError:
        raise IngestError("yt-dlp tidak terinstal")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,   # hanya metadata, tanpa download
        "skip_download": True,
        "playlistend": max_videos,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as e:
        msg = str(e)
        if "not a bot" in msg or "Sign in" in msg:
            raise IngestError(
                "YouTube memblokir akses (bot-check). "
                "Coba lagi nanti atau pakai URL video langsung."
            )
        raise IngestError(f"gagal membaca daftar video: {msg[:300]}")
    except Exception as e:  # noqa: BLE001 — yt-dlp bisa raise macam-macam
        raise IngestError(f"gagal membaca daftar video: {e}")
    entries = (info or {}).get("entries")
    if not entries:
        # URL video tunggal (bukan playlist/channel).
        vid = (info or {}).get("id")
        if not vid:
            return []
        entries = [info]
    out = []
    for e in entries:
        if not e:
            continue
        vid = e.get("id") or ""
        vurl = e.get("url") or e.get("webpage_url") or ""
        if vurl and not vurl.startswith("http"):
            vurl = f"https://www.youtube.com/watch?v={vurl}"
        if not vurl and vid:
            vurl = f"https://www.youtube.com/watch?v={vid}"
        out.append({
            "id": vid,
            "title": e.get("title") or vid or "(tanpa judul)",
            "url": vurl,
        })
        if len(out) >= max_videos:
            break
    return out


def bulk_youtube(url, workdir, max_videos=20, progress=None):
    """Unduh banyak video dari channel/playlist YouTube.

    Tiap video diunduh via `from_youtube`. Error per video TIDAK
    menggagalkan semuanya — dicatat di hasil.

    Args:
        progress: callback opsional `progress(done, total, label)`.

    Returns:
        {"ok": [MediaInfo, ...], "failed": [{"url", "error"}, ...]}.
    """
    videos = list_youtube_videos(url, max_videos=max_videos)
    total = len(videos)
    ok, failed = [], []
    for i, v in enumerate(videos, 1):
        label = v.get("title", v.get("url", "?"))[:60]
        if progress:
            try:
                progress(i - 1, total, f"Unduh {i}/{total}: {label}")
            except Exception:
                pass
        try:
            info = from_youtube(v["url"], workdir)
            ok.append(info)
        except IngestError as e:
            failed.append({"url": v.get("url", ""), "error": str(e)[:300]})
        if progress:
            try:
                progress(i, total, f"Selesai {i}/{total}")
            except Exception:
                pass
    return {"ok": ok, "failed": failed}
