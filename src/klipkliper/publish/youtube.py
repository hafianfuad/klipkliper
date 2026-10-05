"""Publisher YouTube untuk Klipkliper (EKSPERIMENTAL).

Upload via resumable upload MANUAL dengan `requests` (TANPA
google-api-python-client), sesuai dokumentasi resmi YouTube Data API v3:
    1. POST .../upload/youtube/v3/videos?uploadType=resumable&part=snippet,status
       -> dapat session URI dari header Location.
    2. PUT chunk 8MB ke session URI dengan header Content-Range.
       308 = chunk diterima, lanjut; 200/201 = selesai, baca videoId.
    3. Return {"id": videoId, "url": "https://youtu.be/{id}"}.

Sumber: https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol

Default privacy="unlisted" — aman untuk tool internal (tidak langsung publik).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import requests

from .base import Publisher, PublishError
from . import google_oauth as goauth

UPLOAD_INIT_URL = ("https://www.googleapis.com/upload/youtube/v3/videos"
                   "?uploadType=resumable&part=snippet,status")
CHUNK_SIZE = 8 * 1024 * 1024  # 8MB per PUT, sesuai rekomendasi Google
DEFAULT_CATEGORY_ID = "27"    # Education
VALID_PRIVACY = ("private", "unlisted", "public")


class YouTubePublisher(Publisher):
    """Upload video ke YouTube via OAuth user."""

    name = "youtube"

    def __init__(self, token_path: Optional[Path] = None,
                 client_secret: Optional[str] = None,
                 timeout: int = 120):
        self.token_path = Path(token_path) if token_path else goauth.TOKEN_PATH
        self.client_secret = client_secret
        self.timeout = timeout

    # ---- konfigurasi ----

    def is_configured(self) -> bool:
        tok = goauth.load_token(self.token_path)
        return bool(tok and tok.get("access_token"))

    def authorize_flow(self) -> str:
        """Teks langkah authorize untuk user (URL diminta terpisah via CLI)."""
        cid = goauth.client_id_from_env_or_file()
        url, _ = goauth.authorize_url(cid or "<CLIENT_ID>")
        return (
            "Langkah hubungkan YouTube:\n"
            "1. Buat OAuth client (tipe Desktop) di Google Cloud Console\n"
            "   dan enable YouTube Data API v3 (lihat docs/publish-youtube.md).\n"
            "2. Jalankan: python -m klipkliper.cli publish authorize --to youtube\n"
            "   (atau buka URL ini manual bila client_id sudah diset):\n"
            f"   {url}\n"
            "3. Login Google -> authorize -> paste code yang diberikan."
        )

    def refresh_if_needed(self) -> Dict:
        return goauth.refresh(self.token_path, self.client_secret)

    # ---- body request ----

    @staticmethod
    def _build_body(title: str, description: str, tags: Optional[List[str]],
                    privacy: str, made_for_kids: bool) -> Dict:
        if not title or not title.strip():
            raise PublishError("Judul video wajib diisi.",
                               hint="Isi --title atau biarkan default dari nama file.")
        if len(title) > 100:
            raise PublishError(f"Judul terlalu panjang ({len(title)} > 100 karakter).")
        if privacy not in VALID_PRIVACY:
            raise PublishError(f"privacy tidak valid: {privacy!r}",
                               hint=f"Pilih: {', '.join(VALID_PRIVACY)}.")
        if len(description or "") > 5000:
            raise PublishError("Deskripsi terlalu panjang (>5000 karakter).")
        clean_tags = [t.strip()[:30] for t in (tags or []) if t and t.strip()][:500]
        return {
            "snippet": {
                "title": title.strip(),
                "description": description or "",
                "tags": clean_tags,
                "categoryId": DEFAULT_CATEGORY_ID,
            },
            "status": {
                "privacyStatus": privacy,
                "madeForKids": bool(made_for_kids),
            },
        }

    # ---- publish ----

    def publish(self, video_path: str, title: str, description: str = "",
                tags: Optional[List[str]] = None, dry_run: bool = False,
                privacy: str = "unlisted", made_for_kids: bool = False,
                **kw) -> Dict:
        p = Path(video_path)
        body = self._build_body(title, description, tags, privacy, made_for_kids)

        if dry_run:
            if not p.exists():
                raise PublishError(f"File tidak ada: {video_path}")
            return {
                "dry_run": True,
                "platform": "youtube",
                "request": {
                    "method": "POST",
                    "url": UPLOAD_INIT_URL,
                    "body": body,
                    "headers": {
                        "Authorization": "Bearer <token>",
                        "Content-Type": "application/json",
                        "X-Upload-Content-Type": "video/*",
                        "X-Upload-Content-Length": str(p.stat().st_size),
                    },
                },
                "then": f"PUT {CHUNK_SIZE // 1024 // 1024}MB chunks ke session URI "
                        "dengan Content-Range",
            }

        if not p.exists():
            raise PublishError(f"File tidak ada: {video_path}")
        size = p.stat().st_size
        if size == 0:
            raise PublishError(f"File kosong: {video_path}")
        if not self.is_configured():
            raise PublishError(
                "YouTube belum terhubung (token tidak ada).",
                hint="Jalankan: python -m klipkliper.cli publish authorize --to youtube "
                     "(lihat docs/publish-youtube.md).",
            )
        creds = self.refresh_if_needed()
        token = creds["access_token"]

        session_uri = self._init_session(token, body, size)
        video_id = self._upload_chunks(session_uri, p, size)
        return {"id": video_id, "url": f"https://youtu.be/{video_id}"}

    def _init_session(self, token: str, body: Dict, size: int) -> str:
        try:
            resp = requests.post(
                UPLOAD_INIT_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Type": "video/*",
                    "X-Upload-Content-Length": str(size),
                },
                json=body,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise PublishError(f"Gagal memulai upload session: {e}")
        if resp.status_code != 200:
            raise PublishError(
                f"Init upload gagal (HTTP {resp.status_code}): {resp.text[:400]}",
                hint=self._hint_for_status(resp.status_code),
            )
        uri = resp.headers.get("Location") or resp.headers.get("location")
        if not uri:
            raise PublishError("Respons init tidak mengandung session URI "
                               "(header Location hilang).")
        return uri

    def _upload_chunks(self, session_uri: str, path: Path, size: int) -> str:
        offset = 0
        with open(path, "rb") as fh:
            while offset < size:
                chunk = fh.read(CHUNK_SIZE)
                if not chunk:
                    break
                start, end = offset, offset + len(chunk) - 1
                try:
                    resp = requests.put(
                        session_uri,
                        headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {start}-{end}/{size}",
                        },
                        data=chunk,
                        timeout=self.timeout,
                    )
                except requests.RequestException as e:
                    raise PublishError(
                        f"Gagal upload chunk @{offset}: {e}",
                        hint="Upload resumable bisa dilanjutkan — implementasi "
                             "resume otomatis belum ada di versi ini; ulangi publish.",
                    )
                if resp.status_code in (200, 201):
                    try:
                        return resp.json()["id"]
                    except (ValueError, KeyError):
                        raise PublishError(
                            f"Upload selesai tapi respons tak terduga: {resp.text[:300]}")
                if resp.status_code == 308:
                    # Chunk diterima; server bisa kasih tahu offset via header Range.
                    rng = resp.headers.get("Range") or resp.headers.get("range")
                    if rng and "-" in rng:
                        try:
                            offset = int(rng.split("-")[1]) + 1
                            fh.seek(offset)
                            continue
                        except ValueError:
                            pass
                    offset = end + 1
                    continue
                raise PublishError(
                    f"Upload chunk gagal (HTTP {resp.status_code}): {resp.text[:400]}",
                    hint=self._hint_for_status(resp.status_code),
                )
        raise PublishError("Upload selesai tanpa videoId (tak terduga).")

    @staticmethod
    def _hint_for_status(status: int) -> Optional[str]:
        if status == 401:
            return ("Token tidak valid/kedaluwarsa. Coba: "
                    "python -m klipkliper.cli publish authorize --to youtube (login ulang).")
        if status == 403:
            return ("Akses ditolak. Kemungkinan: kuota YouTube Data API habis "
                    "(upload ~1600 unit, default 10.000/hari), atau channel belum "
                    "terverifikasi untuk upload via API.")
        return None


if __name__ == "__main__":
    # Smoke test tanpa kredensial: dry_run membangun request yang valid.
    import tempfile
    pub = YouTubePublisher()
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"\x00" * 1024)
        tmp = f.name
    try:
        r = pub.publish(tmp, title="Judul Tes Klip",
                        description="Deskripsi tes",
                        tags=["ai", "klip", "tes"],
                        privacy="unlisted", dry_run=True)
        assert r["dry_run"] is True
        body = r["request"]["body"]
        assert body["snippet"]["title"] == "Judul Tes Klip"
        assert body["snippet"]["tags"] == ["ai", "klip", "tes"]
        assert body["snippet"]["categoryId"] == "27"
        assert body["status"]["privacyStatus"] == "unlisted"
        assert body["status"]["madeForKids"] is False
        print("dry_run body: OK")
        # validasi: judul kosong & privacy salah harus raise
        for bad in (dict(title=""), dict(title="x", privacy="everyone")):
            try:
                pub.publish(tmp, description="x", dry_run=True, **bad)
            except PublishError:
                pass
            else:
                raise AssertionError(f"validasi gagal untuk {bad}")
        print("validasi judul/privacy: OK")
    finally:
        os.unlink(tmp)
    print("is_configured (tanpa token):", pub.is_configured())
