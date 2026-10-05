# Autopost Instagram Reels — Klipkliper ⏳ EKSPERIMENTAL

> Status: eksperimental (seperti AutoClip). Hanya untuk akun
> **Bisnis/Kreator** yang tertaut ke Halaman Facebook.

## 1. Syarat akun

- Akun Instagram **Bisnis atau Kreator** (bukan pribadi).
- Akun tersebut **tertaut ke sebuah Halaman Facebook**
  (aplikasi IG → Pengaturan → Akun → Tautkan Halaman).

## 2. Buat Meta App

1. https://developers.facebook.com/apps → **Create App** → tipe **Business**.
2. Tambahkan produk **Instagram Graph API** (nama baru: "Instagram") dan
   **Facebook Login for Business**.
3. App Review → Permissions → minta:
   `instagram_basic`, `instagram_content_publish`,
   `pages_show_list`, `pages_read_engagement`.
4. Mode development: tambahkan akun IG sebagai **Tester** (Roles → Testers)
   agar bisa dipakai sebelum app review.

## 3. Dapatkan token + IG User ID

1. Buka https://developers.facebook.com/tools/explorer → pilih app-mu →
   dapatkan **User Access Token** dengan scope di atas.
2. Cari IG User ID:
   ```
   GET https://graph.facebook.com/v21.0/me/accounts?fields=instagram_business_account{name,username}&access_token=TOKEN
   ```
   Salin `instagram_business_account.id`.
3. Simpan ke `~/.klipkliper/instagram_token.json`:
   ```json
   {"access_token": "...", "ig_user_id": "..."}
   ```
   Atau set env `META_ACCESS_TOKEN` dan `IG_USER_ID`.

Token pendek (±1 jam) bisa ditukar ke long-lived (60 hari) via
`InstagramPublisher.refresh_if_needed()` — butuh `META_APP_ID` &
`META_APP_SECRET`.

## 4. Batasan penting

| Batasan | Detail |
|---|---|
| Jenis akun | Bisnis/Kreator + tertaut Halaman FB. Akun pribadi **tidak bisa**. |
| Limit posting | **100 post API / 24 jam** (cek `GET /{ig-id}/content_publishing_limit`). |
| Video | 3 dtk – 3 mnt, maks 250 MB (resumable), 9:16 disarankan, H.264+AAC. |
| Caption | Maks 2200 karakter. |
| Upload | Resumable: init → PUT byte mentah ke `rupload.facebook.com` → poll `status_code` → `media_publish` → permalink. |

## 5. Cek cepat

```bash
PYTHONPATH=src python -m klipkliper.cli publish-now klip.mp4 --to instagram \
  --title "Judul" --tags ai,teknologi --dry-run
```

## Referensi

- https://developers.facebook.com/documentation/instagram-platform/content-publishing/resumable-uploads.md
- https://developers.facebook.com/documentation/instagram-platform/content-publishing
- https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media.md
