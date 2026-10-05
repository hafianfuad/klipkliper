"""Publisher TikTok untuk Klipkliper (EKSPERIMENTAL).

Alur: Content Posting API v2 — Direct Post (FILE_UPLOAD):
  1. POST https://open.tiktokapis.com/v2/post/publish/video/init/
     body: post_info{title, privacy_level, ...} +
           source_info{source=FILE_UPLOAD, video_size, chunk_size, total_chunk_count}
     -> data{publish_id, upload_url}
  2. PUT tiap chunk ke upload_url (header Content-Type: video/mp4,
     Content-Range: bytes {first}-{last}/{size}); 206 = lanjut, 201 = selesai.
     Chunk 5-64 MB (file < 5 MB = 1 chunk utuh).
  3. Poll POST .../post/publish/status/fetch/ {publish_id} hingga PUBLISH_COMPLETE.

Sumber endpoint:
  - https://developers.tiktok.com/docs/en/content-posting-api-get-started (Direct Post)
  - https://developers.tiktok.com/docs/en/content-posting-api-get-started-upload-content

Batasan penting:
  - Butuh aplikasi di TikTok Developer Portal + scope video.upload & video.publish.
  - privacy_level PUBLIC_TO_EVERYONE butuh audit aplikasi (production);
    default SELF_ONLY (aman, tanpa audit) untuk fase internal.
  - Direct Post tidak mengembalikan URL publik langsung (video masuk ke akun user).

Token disimpan di ~/.klipkliper/tiktok_token.json (0600), JANGAN di repo.
"""
import json
import math
import os
import time
from pathlib import Path

import requests

from .base import Publisher, PublishError

INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
REFRESH_URL = "https://open.tiktokapis.com/v2/oauth/token/"

TOKEN_FILE = Path.home() / ".klipkliper" / "tiktok_token.json"
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB, dalam jendela 5-64 MB
MIN_SINGLE_CHUNK = 5 * 1024 * 1024
STATUS_TIMEOUT = 600  # detik, poll status publish

PRIVACY_LEVELS = ("SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR",
                  "PUBLIC_TO_EVERYONE")


def _save_json_secure(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


class TikTokPublisher(Publisher):
    name = "tiktok"

    def __init__(self, access_token: str | None = None,
                 client_key: str | None = None,
                 client_secret: str | None = None):
        tok = self._load_token_file()
        self.access_token = (access_token or os.environ.get("TIKTOK_ACCESS_TOKEN")
                             or tok.get("access_token"))
        self.refresh_token = tok.get("refresh_token")
        self.client_key = client_key or os.environ.get("TIKTOK_CLIENT_KEY")
        self.client_secret = client_secret or os.environ.get("TIKTOK_CLIENT_SECRET")

    # ---- konfigurasi -------------------------------------------------
    @staticmethod
    def _load_token_file() -> dict:
        try:
            return json.loads(TOKEN_FILE.read_text())
        except (OSError, ValueError):
            return {}

    def is_configured(self) -> bool:
        return bool(self.access_token)

    def authorize_flow(self) -> str:
        return (
            "Cara menghubungkan TikTok (Login Kit for TikTok):\n"
            "1. Buka https://developers.tiktok.com/apps -> 'Create an app'.\n"
            "   Isi nama 'Klipkliper', pilih kategori. Catat Client Key & Client Secret.\n"
            "2. Di 'Add products', tambahkan 'Login Kit for TikTok'.\n"
            "3. Di Settings -> Login Kit, daftarkan Redirect URI, mis. "
            "http://localhost:8080/callback (Desktop).\n"
            "4. Minta scope: 'video.upload' dan 'video.publish' (+ 'user.info.basic').\n"
            "5. Buka URL authorize (ganti CLIENT_KEY & REDIRECT):\n"
            "   https://www.tiktok.com/v2/auth/authorize/?client_key=CLIENT_KEY"
            "&scope=user.info.basic,video.upload,video.publish"
            "&response_type=code&redirect_uri=REDIRECT&state=klipkliper\n"
            "6. Login TikTok di browser -> dapat 'code' di redirect URL.\n"
            "7. Tukar code -> token: POST https://open.tiktokapis.com/v2/oauth/token/\n"
            "   {client_key, client_secret, code, grant_type='authorization_code',\n"
            "    redirect_uri=REDIRECT}\n"
            "8. Simpan access_token (+ refresh_token) ke:\n"
            f"   {TOKEN_FILE}  (format JSON, permission 0600)\n"
            "   atau set env TIKTOK_ACCESS_TOKEN.\n"
            "CATATAN: posting PUBLIC_TO_EVERYONE butuh audit aplikasi TikTok "
            "(bisa berminggu-minggu). Selama audit, pakai privacy_level SELF_ONLY."
        )

    def refresh_if_needed(self) -> dict:
        if not self.refresh_token:
            raise PublishError(
                "Tidak ada refresh_token TikTok.",
                hint="Ulangi authorize_flow untuk mendapatkan token baru.")
        if not (self.client_key and self.client_secret):
            raise PublishError(
                "Butuh client_key & client_secret untuk refresh token.",
                hint="Set env TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET.")
        try:
            r = requests.post(REFRESH_URL, data={
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            }, timeout=30)
        except requests.RequestException as e:
            raise PublishError(f"Refresh token gagal: {e}")
        data = r.json()
        if "access_token" not in data:
            raise PublishError(f"Refresh ditolak: {data}",
                               hint="Token mungkin kedaluwarsa; login ulang.")
        tok = self._load_token_file()
        tok.update({k: data[k] for k in ("access_token", "refresh_token",
                                        "expires_in") if k in data})
        _save_json_secure(TOKEN_FILE, tok)
        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        return {"access_token": "***", "refreshed": True}

    # ---- publish -----------------------------------------------------
    @staticmethod
    def _caption(title: str, description: str = "", tags=None) -> str:
        parts = [title.strip()]
        if description:
            parts.append(description.strip())
        for t in (tags or []):
            t = t.strip().lstrip("#")
            if t:
                parts.append(f"#{t}")
        return "\n\n".join(p for p in parts if p)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json; charset=UTF-8"}

    def _check_api_error(self, payload: dict, aksi: str) -> dict:
        err = payload.get("error", {})
        if err.get("code") != "ok":
            raise PublishError(
                f"TikTok {aksi} gagal: {err.get('code')}: {err.get('message')}",
                hint="Cek token/scope; privacy_level PUBLIC butuh audit app.")
        return payload.get("data", {})

    def publish(self, video_path, title, description="", tags=None,
                dry_run=False, **kw) -> dict:
        privacy = kw.get("privacy_level", "SELF_ONLY")
        if privacy not in PRIVACY_LEVELS:
            raise PublishError(f"privacy_level tidak valid: {privacy}",
                               hint=f"Pilih: {', '.join(PRIVACY_LEVELS)}")
        path = Path(video_path)
        if not path.is_file():
            raise PublishError(f"File tidak ada: {video_path}")
        size = path.stat().st_size
        caption = self._caption(title, description, tags)
        chunk = size if size < MIN_SINGLE_CHUNK else CHUNK_SIZE
        n_chunks = 1 if size < MIN_SINGLE_CHUNK else math.ceil(size / CHUNK_SIZE)

        init_body = {
            "post_info": {"title": caption, "privacy_level": privacy,
                          "disable_duet": False, "disable_comment": False,
                          "disable_stitch": False},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": chunk,
                            "total_chunk_count": n_chunks},
        }
        plan = {"endpoint": INIT_URL, "method": "POST",
                "body": init_body, "chunks": n_chunks,
                "chunk_size": chunk, "privacy_level": privacy}
        if dry_run:
            return {"dry_run": True, "configured": self.is_configured(),
                    "request": plan}
        if not self.access_token:
            raise PublishError("TikTok belum terhubung.",
                               hint=self.authorize_flow().split("\n")[0])

        # 1. init
        try:
            r = requests.post(INIT_URL, headers=self._headers(),
                              json=init_body, timeout=60)
        except requests.RequestException as e:
            raise PublishError(f"Init upload gagal: {e}")
        data = self._check_api_error(r.json(), "init upload")
        publish_id = data.get("publish_id")
        upload_url = data.get("upload_url")
        if not publish_id or not upload_url:
            raise PublishError(f"Respons init tak lengkap: {data}")

        # 2. upload chunks sequential
        with open(path, "rb") as f:
            for i in range(n_chunks):
                first = i * CHUNK_SIZE
                blob = f.read(CHUNK_SIZE)
                last = first + len(blob) - 1
                try:
                    up = requests.put(
                        upload_url, data=blob,
                        headers={"Content-Type": "video/mp4",
                                 "Content-Range": f"bytes {first}-{last}/{size}"},
                        timeout=300)
                except requests.RequestException as e:
                    raise PublishError(f"Upload chunk {i + 1}/{n_chunks} gagal: {e}")
                if up.status_code not in (201, 206):
                    raise PublishError(
                        f"Upload chunk {i + 1} ditolak (HTTP {up.status_code}): "
                        f"{up.text[:300]}")

        # 3. poll status
        deadline = time.time() + STATUS_TIMEOUT
        last_status = "UNKNOWN"
        while time.time() < deadline:
            try:
                s = requests.post(STATUS_URL, headers=self._headers(),
                                  json={"publish_id": publish_id}, timeout=30)
            except requests.RequestException as e:
                raise PublishError(f"Cek status gagal: {e}")
            sdata = self._check_api_error(s.json(), "cek status")
            last_status = sdata.get("status", "UNKNOWN")
            if last_status == "PUBLISH_COMPLETE":
                break
            if last_status == "FAILED":
                raise PublishError(f"TikTok gagal memproses video: {sdata}")
            time.sleep(10)
        else:
            raise PublishError(
                f"Timeout menunggu publish ({last_status}).",
                hint="Video mungkin tetap terbit; cek manual di aplikasi TikTok.")

        return {"id": publish_id, "url": None,
                "note": "Direct Post: video masuk ke akun TikTok user; "
                        "URL publik tidak dikembalikan API."}
