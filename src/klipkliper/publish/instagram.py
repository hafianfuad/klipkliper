"""Publisher Instagram Reels untuk Klipkliper (EKSPERIMENTAL).

Alur: Graph API — Resumable Upload (tanpa URL publik):
  1. POST https://graph.facebook.com/v21.0/{ig-user-id}/media
     {upload_type: resumable, media_type: REELS, caption, share_to_feed}
     -> {id: container_id, uri: https://rupload.facebook.com/ig-api-upload/...}
  2. POST {uri} body = byte video mentah,
     header {offset: 0, file_size: <bytes>} (+ access_token sbg query param)
  3. Poll GET /{container_id}?fields=status_code hingga FINISHED.
  4. POST /{ig-user-id}/media_publish {creation_id: container_id} -> {id: media_id}
  5. GET /{media_id}?fields=permalink -> URL publik.

Sumber endpoint:
  - https://developers.facebook.com/documentation/instagram-platform/content-publishing/resumable-uploads.md
  - https://developers.facebook.com/documentation/instagram-platform/content-publishing
  - Referensi ig-user/media: developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media.md

Batasan penting:
  - Hanya akun Instagram Bisnis/Kreator yang tertaut ke Halaman Facebook.
  - App butuh Facebook Login for Business + scope instagram_basic,
    instagram_content_publish (+ pages_show_list/pages_read_engagement).
  - Limit: 100 post API per 24 jam (cek GET /{ig-id}/content_publishing_limit).
  - Video: 3 dtk - 3 mnt (reels), maks 250 MB utk resumable, 9:16 disarankan.

Token disimpan di ~/.klipkliper/instagram_token.json (0600), JANGAN di repo.
"""
import json
import os
import time
from pathlib import Path

import requests

from .base import Publisher, PublishError

GRAPH = "https://graph.facebook.com/v21.0"
TOKEN_FILE = Path.home() / ".klipkliper" / "instagram_token.json"
POLL_TIMEOUT = 600  # detik menunggu FINISHED
MAX_CAPTION = 2200


def _save_json_secure(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


class InstagramPublisher(Publisher):
    name = "instagram"

    def __init__(self, access_token: str | None = None,
                 ig_user_id: str | None = None,
                 app_id: str | None = None,
                 app_secret: str | None = None):
        cfg = self._load_cfg()
        self.access_token = (access_token or os.environ.get("META_ACCESS_TOKEN")
                             or cfg.get("access_token"))
        self.ig_user_id = (ig_user_id or os.environ.get("IG_USER_ID")
                           or cfg.get("ig_user_id"))
        self.app_id = app_id or os.environ.get("META_APP_ID") or cfg.get("app_id")
        self.app_secret = (app_secret or os.environ.get("META_APP_SECRET")
                           or cfg.get("app_secret"))

    # ---- konfigurasi -------------------------------------------------
    @staticmethod
    def _load_cfg() -> dict:
        try:
            return json.loads(TOKEN_FILE.read_text())
        except (OSError, ValueError):
            return {}

    def is_configured(self) -> bool:
        return bool(self.access_token and self.ig_user_id)

    def authorize_flow(self) -> str:
        return (
            "Cara menghubungkan Instagram (Graph API):\n"
            "1. Pastikan akun Instagram adalah Bisnis/Kreator DAN tertaut ke "
            "sebuah Halaman Facebook (Pengaturan IG -> Akun -> Tautkan).\n"
            "2. Buat app di https://developers.facebook.com/apps -> tipe 'Business'.\n"
            "3. Tambahkan produk: 'Instagram Graph API' (atau 'Instagram' di "
            "dashboard baru) dan 'Facebook Login for Business'.\n"
            "4. Di App Review -> Permissions, minta scope: instagram_basic, "
            "instagram_content_publish, pages_show_list, pages_read_engagement.\n"
            "   (Mode dev: tambahkan akun IG sebagai Tester di Roles agar bisa dipakai.)\n"
            "5. Dapatkan User Access Token via Graph API Explorer "
            "(developers.facebook.com/tools/explorer) dengan scope di atas.\n"
            "6. Cari IG User ID: GET graph.facebook.com/v21.0/me/accounts"
            "?fields=instagram_business_account{name,username} "
            "-> salin id instagram_business_account.\n"
            "7. Simpan ke:\n"
            f"   {TOKEN_FILE}\n"
            '   {"access_token": "...", "ig_user_id": "..."}  (permission 0600)\n'
            "   atau set env META_ACCESS_TOKEN dan IG_USER_ID.\n"
            "8. (Opsional, token awet 60 hari) tukarkan ke long-lived token via "
            "refresh_if_needed() bila META_APP_ID & META_APP_SECRET diisi."
        )

    def refresh_if_needed(self) -> dict:
        """Tukar ke long-lived token (60 hari). Butuh app_id + app_secret."""
        if not (self.app_id and self.app_secret and self.access_token):
            raise PublishError(
                "Butuh META_APP_ID, META_APP_SECRET, dan access_token.",
                hint="Isi ketiganya lalu panggil refresh_if_needed().")
        try:
            r = requests.get(
                f"{GRAPH}/oauth/access_token",
                params={"grant_type": "fb_exchange_token",
                        "client_id": self.app_id,
                        "client_secret": self.app_secret,
                        "fb_exchange_token": self.access_token},
                timeout=30)
        except requests.RequestException as e:
            raise PublishError(f"Token exchange gagal: {e}")
        data = r.json()
        if "access_token" not in data:
            raise PublishError(f"Exchange ditolak: {data}")
        cfg = self._load_cfg()
        cfg["access_token"] = data["access_token"]
        _save_json_secure(TOKEN_FILE, cfg)
        self.access_token = data["access_token"]
        return {"refreshed": True, "expires_in": data.get("expires_in")}

    # ---- publish -----------------------------------------------------
    @staticmethod
    def _caption(title: str, description: str = "", tags=None) -> str:
        parts = [title.strip()]
        if description:
            parts.append(description.strip())
        tagline = " ".join(f"#{t.strip().lstrip('#')}"
                           for t in (tags or []) if t.strip())
        if tagline:
            parts.append(tagline)
        text = "\n\n".join(p for p in parts if p)
        return text[:MAX_CAPTION]

    def _api(self, method: str, path: str, **kw):
        params = kw.pop("params", {}) or {}
        params.setdefault("access_token", self.access_token)
        try:
            r = requests.request(method, f"{GRAPH}{path}",
                                 params=params, timeout=kw.pop("timeout", 60),
                                 **kw)
        except requests.RequestException as e:
            raise PublishError(f"Request {path} gagal: {e}")
        try:
            data = r.json()
        except ValueError:
            raise PublishError(f"Respons non-JSON dari {path}: {r.text[:200]}")
        if "error" in data:
            err = data["error"]
            raise PublishError(
                f"Graph API error ({err.get('code')}): {err.get('message')}",
                hint="Cek token, scope instagram_content_publish, dan limit 100 post/24 jam.")
        return data

    def publish(self, video_path, title, description="", tags=None,
                dry_run=False, **kw) -> dict:
        path = Path(video_path)
        if not path.is_file():
            raise PublishError(f"File tidak ada: {video_path}")
        caption = self._caption(title, description, tags)
        share_to_feed = kw.get("share_to_feed", True)

        plan = {"steps": [
            f"POST {GRAPH}/{{ig_id}}/media (upload_type=resumable, media_type=REELS)",
            "POST {upload_uri} (byte video, header offset/file_size)",
            "GET /{container_id}?fields=status_code (poll hingga FINISHED)",
            "POST /{ig_id}/media_publish (creation_id)",
            "GET /{media_id}?fields=permalink",
        ], "caption_preview": caption[:200],
            "share_to_feed": share_to_feed,
            "size_bytes": path.stat().st_size}
        if dry_run:
            return {"dry_run": True, "configured": self.is_configured(),
                    "request": plan}
        if not self.is_configured():
            raise PublishError(
                "Instagram belum terhubung (butuh token + ig_user_id).",
                hint=self.authorize_flow().split("\n")[0])

        # 1. init resumable container
        init = self._api("POST", f"/{self.ig_user_id}/media", data={
            "upload_type": "resumable", "media_type": "REELS",
            "caption": caption, "share_to_feed": str(share_to_feed).lower(),
        })
        container_id, upload_uri = init.get("id"), init.get("uri")
        if not container_id or not upload_uri:
            raise PublishError(f"Init container tak lengkap: {init}")

        # 2. upload byte mentah
        size = path.stat().st_size
        try:
            up = requests.post(
                upload_uri, params={"access_token": self.access_token},
                data=path.read_bytes(),
                headers={"offset": "0", "file_size": str(size),
                         "Content-Type": "application/octet-stream"},
                timeout=600)
        except requests.RequestException as e:
            raise PublishError(f"Upload byte gagal: {e}")
        if up.status_code not in (200, 201):
            raise PublishError(f"Upload byte ditolak (HTTP {up.status_code}): "
                               f"{up.text[:300]}")

        # 3. poll status
        deadline = time.time() + POLL_TIMEOUT
        status = "UNKNOWN"
        while time.time() < deadline:
            st = self._api("GET", f"/{container_id}",
                           params={"fields": "status_code"})
            status = st.get("status_code", "UNKNOWN")
            if status == "FINISHED":
                break
            if status == "ERROR":
                raise PublishError(f"Meta gagal memproses video: {st}")
            time.sleep(10)
        else:
            raise PublishError(f"Timeout menunggu FINISHED ({status}).")

        # 4. publish
        pub = self._api("POST", f"/{self.ig_user_id}/media_publish",
                        data={"creation_id": container_id})
        media_id = pub.get("id")
        if not media_id:
            raise PublishError(f"media_publish tak mengembalikan id: {pub}")

        # 5. permalink
        permalink = None
        try:
            info = self._api("GET", f"/{media_id}",
                             params={"fields": "permalink"})
            permalink = info.get("permalink")
        except PublishError:
            pass  # URL opsional; id sudah cukup
        return {"id": media_id, "url": permalink}
