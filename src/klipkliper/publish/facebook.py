"""Publisher Facebook Page untuk Klipkliper (EKSPERIMENTAL).

Alur: upload video ke Halaman Facebook via Graph API:
  POST https://graph-video.facebook.com/v21.0/{page-id}/videos
  multipart/form-data: source=<file>, title, description
  -> {id: video_id}; permalink via GET /{video_id}?fields=permalink
     (atau https://www.facebook.com/{page_id}/videos/{video_id})

Untuk file sangat besar (>1 GB) gunakan resumable upload
(upload_phase=start/transfer/finish) — tidak diimplementasikan di sini,
klip Klipkliper umumnya < 250 MB.

Sumber endpoint:
  - https://developers.facebook.com/docs/video-api/guides/publishing/
  - Referensi: POST /{page-id}/videos (Video API)

Batasan penting:
  - Video terbit ke HALAMAN Facebook, bukan profil pribadi (API tidak
    mendukung posting ke profil user).
  - Butuh Page Access Token dengan scope pages_manage_posts
    (+ pages_read_engagement). Token jangan pernah di-commit.
  - Video: mp4 (H.264+AAC) disarankan; 9:16 didukung (tampil sebagai reel-like
    di feed bila < 90 dtk, tergantung kebijakan Meta saat ini).

Token disimpan di ~/.klipkliper/facebook_token.json (0600), JANGAN di repo.
"""
import json
import os
from pathlib import Path

import requests

from .base import Publisher, PublishError

GRAPH = "https://graph.facebook.com/v21.0"
GRAPH_VIDEO = "https://graph-video.facebook.com/v21.0"
TOKEN_FILE = Path.home() / ".klipkliper" / "facebook_token.json"


def _save_json_secure(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


class FacebookPublisher(Publisher):
    name = "facebook"

    def __init__(self, page_access_token: str | None = None,
                 page_id: str | None = None,
                 app_id: str | None = None,
                 app_secret: str | None = None):
        cfg = self._load_cfg()
        self.page_token = (page_access_token
                           or os.environ.get("FB_PAGE_TOKEN")
                           or cfg.get("page_access_token"))
        self.page_id = (page_id or os.environ.get("FB_PAGE_ID")
                        or cfg.get("page_id"))
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
        return bool(self.page_token and self.page_id)

    def authorize_flow(self) -> str:
        return (
            "Cara menghubungkan Halaman Facebook (Graph API):\n"
            "1. Buat app di https://developers.facebook.com/apps -> tipe 'Business'.\n"
            "2. Tambahkan produk 'Facebook Login' (untuk Business).\n"
            "3. Minta scope: pages_manage_posts, pages_read_engagement "
            "(+ pages_show_list).\n"
            "4. Dapatkan User Access Token via Graph API Explorer "
            "(developers.facebook.com/tools/explorer) dengan scope di atas.\n"
            "5. Tukar ke Page Access Token: GET graph.facebook.com/v21.0/me/accounts\n"
            "   -> pilih halamanmu -> salin 'access_token' dan 'id' halaman.\n"
            "   (Page token tidak kedaluwarsa selama user pemberi tetap admin.)\n"
            "6. Simpan ke:\n"
            f"   {TOKEN_FILE}\n"
            '   {"page_access_token": "...", "page_id": "..."}  (permission 0600)\n'
            "   atau set env FB_PAGE_TOKEN dan FB_PAGE_ID.\n"
            "CATATAN: API hanya bisa posting ke Halaman, BUKAN ke profil pribadi."
        )

    def refresh_if_needed(self) -> dict:
        """Tukar user token -> long-lived (60 hari), lalu ambil ulang page token."""
        if not (self.app_id and self.app_secret):
            raise PublishError(
                "Butuh META_APP_ID & META_APP_SECRET untuk exchange token.",
                hint="Page token sendiri umumnya tidak kedaluwarsa; "
                     "refresh hanya perlu bila memakai user token berumur pendek.")
        short = os.environ.get("FB_USER_TOKEN") or self._load_cfg().get(
            "user_access_token")
        if not short:
            raise PublishError("Tidak ada user token untuk di-exchange.",
                               hint="Set env FB_USER_TOKEN lalu ulangi.")
        try:
            r = requests.get(f"{GRAPH}/oauth/access_token", params={
                "grant_type": "fb_exchange_token", "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": short}, timeout=30)
            data = r.json()
        except requests.RequestException as e:
            raise PublishError(f"Token exchange gagal: {e}")
        if "access_token" not in data:
            raise PublishError(f"Exchange ditolak: {data}")
        cfg = self._load_cfg()
        cfg["user_access_token"] = data["access_token"]
        _save_json_secure(TOKEN_FILE, cfg)
        return {"refreshed": True, "expires_in": data.get("expires_in"),
                "note": "Ambil ulang Page token via /me/accounts memakai "
                        "user token baru ini."}

    # ---- publish -----------------------------------------------------
    def _api(self, method: str, host: str, path: str, **kw):
        params = kw.pop("params", {}) or {}
        params.setdefault("access_token", self.page_token)
        try:
            r = requests.request(method, f"{host}{path}", params=params,
                                 timeout=kw.pop("timeout", 600), **kw)
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
                hint="Cek page token, scope pages_manage_posts, dan status halaman.")
        return data

    def publish(self, video_path, title, description="", tags=None,
                dry_run=False, **kw) -> dict:
        path = Path(video_path)
        if not path.is_file():
            raise PublishError(f"File tidak ada: {video_path}")
        desc = description or ""
        if tags:
            tagline = " ".join(f"#{t.strip().lstrip('#')}"
                               for t in tags if t.strip())
            desc = (desc + "\n\n" + tagline).strip()

        plan = {"endpoint": f"{GRAPH_VIDEO}/{self.page_id or '{page_id}'}/videos",
                "method": "POST (multipart)",
                "fields": {"title": title, "description": desc[:500],
                           "file": str(path),
                           "size_bytes": path.stat().st_size}}
        if dry_run:
            return {"dry_run": True, "configured": self.is_configured(),
                    "request": plan}
        if not self.is_configured():
            raise PublishError(
                "Facebook Page belum terhubung (butuh page token + page_id).",
                hint=self.authorize_flow().split("\n")[0])

        with open(path, "rb") as f:
            data = self._api(
                "POST", GRAPH_VIDEO, f"/{self.page_id}/videos",
                files={"source": (path.name, f, "video/mp4")},
                data={"title": title, "description": desc})

        video_id = data.get("id")
        if not video_id:
            raise PublishError(f"Upload tak mengembalikan id: {data}")

        url = f"https://www.facebook.com/{self.page_id}/videos/{video_id}"
        try:
            info = self._api("GET", GRAPH, f"/{video_id}",
                             params={"fields": "permalink_url"})
            url = info.get("permalink_url", url)
        except PublishError:
            pass
        return {"id": video_id, "url": url}
