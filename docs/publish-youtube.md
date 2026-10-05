# Posting ke YouTube — Klipkliper (EKSPERIMENTAL)

Klipkliper upload via **YouTube Data API v3** (resumable upload, tanpa SDK
Google — murni `requests`). Butuh OAuth client milikmu sendiri di
Google Cloud Console. Sekali setup, token tersimpan lokal
(`~/.klipkliper/youtube_token.json`, permission 0600).

## Langkah setup (sekali saja)

### 1. Buat project & aktifkan API
1. Buka https://console.cloud.google.com/ → buat project baru
   (mis. "klipkliper").
2. **APIs & Services → Library** → cari **YouTube Data API v3** → **Enable**.

### 2. OAuth consent screen
1. **APIs & Services → OAuth consent screen** → User type: **External** → Create.
2. Isi App name (mis. "Klipkliper"), User support email, Developer email → Save.
3. **Scopes**: tambah `https://www.googleapis.com/auth/youtube.upload`
   (cukup ini; jangan minta scope lebih luas).
4. **Test users**: tambahkan akun Google yang dipakai upload (selama app
   berstatus Testing, hanya test user yang bisa authorize).

### 3. Buat OAuth client
1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Desktop app** → Create.
3. Download JSON → simpan sebagai `client_secret.json`
   (JANGAN commit ke repo, JANGAN share).

### 4. Authorize via CLI
```bash
# cara A: via file
python -m klipkliper.cli publish authorize --to youtube \
    --client-secret-file /path/ke/client_secret.json

# cara B: via env
export KLIPKLIPER_YOUTUBE_CLIENT_ID="xxx.apps.googleusercontent.com"
export KLIPKLIPER_YOUTUBE_CLIENT_SECRET="GOCSPX-..."
python -m klipkliper.cli publish authorize --to youtube
```
Buka URL yang ditampilkan → login Google → authorize → paste code.
Token tersimpan di `~/.klipkliper/youtube_token.json`.

### 5. Tes posting (dry run dulu)
```bash
# validasi tanpa mengirim
python -m klipkliper.cli publish now klip.mp4 --to youtube \
    --title "Judul Klip" --description "..." --tags "ai,klip" \
    --privacy unlisted --dry-run

# posting beneran (default unlisted = tidak publik, aman untuk internal)
python -m klipkliper.cli publish now klip.mp4 --to youtube \
    --title "Judul Klip" --privacy unlisted
```

## Penjadwalan
```bash
# jadwalkan
python -m klipkliper.cli publish schedule klip.mp4 --to youtube \
    --at "2026-10-06 18:00" --title "Judul Klip"

# lihat & kelola
python -m klipkliper.cli publish list-schedule
python -m klipkliper.cli publish cancel-schedule <job_id>

# jalankan yang jatuh tempo (pasang di cron / Task Scheduler Windows)
python -m klipkliper.cli publish run-due
```

## Catatan kuota (penting)

- YouTube Data API v3 punya **kuota harian default 10.000 unit**.
- **Satu upload video ≈ 1.600 unit** → ~6 video/hari per project.
- Cek pemakaian: Console → APIs & Services → Dashboard → YouTube Data API v3.
- Butuh lebih? Ajukan **Quota extension** di Console (butuh review Google,
  bisa makan waktu hari–minggu). Untuk tim internal, 6 video/hari biasanya cukup.
- Upload via API ke channel **baru / belum verifikasi nomor HP** bisa ditolak —
  verifikasi channel dulu di https://www.youtube.com/verify.

## Batasan & troubleshooting

| Gejala | Penyebab umum |
|---|---|
| 401 saat upload | Token kedaluwarsa/dicabut → `publish authorize` ulang |
| 403 `quotaExceeded` | Kuota harian habis → tunggu reset (tengah malam PT) atau ajukan extension |
| 403 `forbidden` | Channel belum verifikasi / API belum di-enable di project |
| `invalid_scope` saat login | Scope salah ketik — harus persis `https://www.googleapis.com/auth/youtube.upload` |
| App "unverified" warning | Wajar untuk app Testing; klik Advanced → Go to (hanya untuk akun sendiri/test user) |

> Status fitur ini **EKSPERIMENTAL** (sama seperti AutoClip): API YouTube bisa
> berubah, dan upload massal berisiko kena rate limit. Untuk produksi tim,
> mulai dari `unlisted` + `run-due` terjadwal, bukan `public` massal.
