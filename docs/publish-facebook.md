# Autopost Facebook Page — Klipkliper ⏳ EKSPERIMENTAL

> Status: eksperimental (seperti AutoClip). API hanya bisa posting ke
> **Halaman Facebook**, bukan profil pribadi.

## 1. Buat Meta App

1. https://developers.facebook.com/apps → **Create App** → tipe **Business**.
2. Tambahkan produk **Facebook Login** (for Business).
3. Minta scope: `pages_manage_posts`, `pages_read_engagement`, `pages_show_list`.

## 2. Dapatkan Page Access Token

1. Via Graph API Explorer (developers.facebook.com/tools/explorer):
   dapatkan **User Access Token** dengan scope di atas.
2. Tukar ke Page token:
   ```
   GET https://graph.facebook.com/v21.0/me/accounts?access_token=USER_TOKEN
   ```
   Pilih halamanmu → salin `access_token` (Page token) dan `id` (Page ID).
   Page token tidak kedaluwarsa selama pemberinya tetap admin halaman.
3. Simpan ke `~/.klipkliper/facebook_token.json`:
   ```json
   {"page_access_token": "...", "page_id": "..."}
   ```
   Atau set env `FB_PAGE_TOKEN` dan `FB_PAGE_ID`.

## 3. Batasan penting

| Batasan | Detail |
|---|---|
| Target | Hanya **Halaman**. Posting ke profil pribadi tidak didukung API. |
| Endpoint | `POST https://graph-video.facebook.com/v21.0/{page-id}/videos` (multipart). |
| Format | MP4 (H.264 + AAC) disarankan; 9:16 didukung. |
| File besar | >1 GB: gunakan resumable upload (`upload_phase=start/transfer/finish`) — belum diimplementasikan (klip Klipkliper umumnya < 250 MB). |

## 4. Cek cepat

```bash
PYTHONPATH=src python -m klipkliper.cli publish-now klip.mp4 --to facebook \
  --title "Judul" --description "Deskripsi" --dry-run
```

## Referensi

- https://developers.facebook.com/docs/video-api/guides/publishing/
