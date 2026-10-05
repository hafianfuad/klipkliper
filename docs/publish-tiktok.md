# Autopost TikTok — Klipkliper ⏳ EKSPERIMENTAL

> Status: eksperimental (seperti AutoClip). Jangan andalkan untuk produksi
> sebelum aplikasi TikTok-mu lolos audit.

## 1. Buat aplikasi TikTok Developer

1. Buka https://developers.tiktok.com/apps → **Create an app**.
2. Isi nama (mis. `Klipkliper`), kategori, simpan **Client Key** & **Client Secret**.
3. **Add products** → tambahkan **Login Kit for TikTok**.
4. Di Settings → Login Kit, daftarkan Redirect URI untuk desktop:
   `http://localhost:8080/callback`

## 2. Scope yang dibutuhkan

- `user.info.basic` (wajib untuk Login Kit)
- `video.upload` (upload file)
- `video.publish` (direct post)

## 3. Dapatkan token (Login Kit / OAuth)

1. Buka di browser (ganti `CLIENT_KEY` & `REDIRECT`):
   ```
   https://www.tiktok.com/v2/auth/authorize/?client_key=CLIENT_KEY&scope=user.info.basic,video.upload,video.publish&response_type=code&redirect_uri=REDIRECT&state=klipkliper
   ```
2. Login TikTok → browser redirect ke `REDIRECT?code=XXXX`.
3. Tukar code → token:
   ```bash
   curl -X POST https://open.tiktokapis.com/v2/oauth/token/ \
     -d client_key=CLIENT_KEY -d client_secret=CLIENT_SECRET \
     -d code=XXXX -d grant_type=authorization_code \
     -d redirect_uri=REDIRECT
   ```
4. Simpan hasilnya ke `~/.klipkliper/tiktok_token.json`:
   ```json
   {"access_token": "...", "refresh_token": "...", "expires_in": 86400}
   ```
   File permission otomatis 0600 oleh Klipkliper. Atau set env `TIKTOK_ACCESS_TOKEN`.

Refresh: `TikTokPublisher.refresh_if_needed()` (butuh `TIKTOK_CLIENT_KEY` &
`TIKTOK_CLIENT_SECRET`).

## 4. Batasan penting

| Batasan | Detail |
|---|---|
| Audit aplikasi | `privacy_level=PUBLIC_TO_EVERYONE` **butuh audit** TikTok (bisa berminggu-minggu). Selama itu pakai `SELF_ONLY` (default Klipkliper — aman). |
| Sandbox vs Production | Mode sandbox hanya untuk akun test yang didaftarkan. |
| Rate limit | init: 6 req/mnt/token; creator_info: 20 req/mnt/token. |
| Chunk upload | 5–64 MB per chunk, 1–1000 chunk; file < 5 MB = 1 chunk. PUT sequential. |
| Status | Poll `.../status/fetch/` hingga `PUBLISH_COMPLETE`. |
| URL publik | Direct Post **tidak** mengembalikan URL — video masuk ke akun user. |

## 5. Cek cepat

```bash
PYTHONPATH=src python -m klipkliper.cli publish-now klip.mp4 --to tiktok \
  --title "Judul #fyp" --dry-run
```

## Referensi

- https://developers.tiktok.com/docs/en/content-posting-api-get-started (Direct Post)
- https://developers.tiktok.com/docs/en/content-posting-api-get-started-upload-content
