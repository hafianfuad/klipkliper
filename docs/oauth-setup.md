# Setup Google OAuth untuk Klipkliper (provider Gemini)

Tujuan: Klipkliper memakai **akun Google kamu** (bukan API key bayar-per-token)
untuk memanggil Gemini API — mekanisme yang sama dipakai Gemini CLI.

> **Status verifikasi (2026-10-05):** kode & alur sudah direview dan unit logika
> teruji. **Login sungguhan dengan akun Google BELUM dicoba** — butuh kamu
> yang klik authorize di browser. Ikuti langkah di bawah, lalu laporkan
> hasilnya (berhasil / error apa).

---

## Langkah-langkah

### 1. Buat project di Google Cloud Console

1. Buka https://console.cloud.google.com/ → pilih / buat project.
2. **APIs & Services → Library** → cari **"Generative Language API"** → **Enable**.
   (Tanpa ini, panggilan API akan 403.)

### 2. Konfigurasi OAuth consent screen

1. **APIs & Services → OAuth consent screen** → User type: **External** → Create.
2. Isi App name (mis. `Klipkliper`), User support email, Developer contact email.
3. **Test users**: tambahkan alamat Gmail kamu (selama app masih "Testing",
   hanya test user yang bisa login).
4. Scope: tidak perlu tambah manual — Klipkliper meminta scope saat login
   (`openid`, `userinfo.email`, `cloud-platform`).

### 3. Buat OAuth Client ID (tipe Desktop)

1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Desktop app**. Nama: `Klipkliper Desktop`.
3. **Authorized redirect URIs**: tambahkan `http://localhost:8080/`
   (untuk tipe Desktop, loopback umumnya sudah diizinkan; menambahkan
   eksplisit menghindari error `redirect_uri_mismatch`).
4. **Download JSON** → simpan sebagai `client_secret.json`
   di tempat aman, mis. `~/.klipkliper/client_secret.json`.

> ⚠️ **JANGAN** commit `client_secret.json` ke repo / kirim ke siapapun.
> File ini setara password untuk OAuth client-mu.

### 4. Login dari Klipkliper

```bash
cd ~/workspace/auto-clipper-clone
.venv/bin/python -m klipkliper.providers.gemini_oauth login \
    --client-secret-file ~/.klipkliper/client_secret.json
```

1. Copy URL yang dicetak → buka di browser → login Google → **Allow**.
2. Kamu dapat **authorization code** (atau URL redirect) → paste ke terminal.
3. Token tersimpan di `~/.klipkliper/gemini_token.json`
   (permission 600, hanya bisa dibaca user-mu).

Alternatif tanpa file: set env var
`KLIPKLIPER_GOOGLE_CLIENT_ID` dan `KLIPKLIPER_GOOGLE_CLIENT_SECRET`.

> 💡 **Penting:** token di-refresh otomatis tiap `chat()`, dan refresh butuh
> client_secret. Supaya sesi berikutnya tetap bisa refresh tanpa login ulang,
> simpan permanen salah satu ini di environment kamu:
> `KLIPKLIPER_GOOGLE_CLIENT_SECRET` (isi secret) atau
> `KLIPKLIPER_GOOGLE_CLIENT_SECRET_FILE` (path ke client_secret.json).

### 5. Tes koneksi

```bash
.venv/bin/python -m klipkliper.providers.gemini_oauth test
```

Harusnya model membalas `OK`. Kalau berhasil, provider siap dipakai
modul pemilih-momen (`chat(messages, json_mode=True)`).

### 6. Pakai model lain (opsional)

Default: `gemini-2.0-flash`. Ganti via env:

```bash
export KLIPKLIPER_GEMINI_MODEL=gemini-flash-latest   # alias stabil terbaru
# atau: gemini-3.6-flash
```

---

## Troubleshooting

| Gejala | Artinya | Aksi |
|---|---|---|
| `Error 400: invalid_scope` di halaman Google | Scope salah (mis. `.../auth/generative-language` — scope itu tidak valid untuk client pihak ketiga) | Pastikan pakai scope bawaan Klipkliper (`cloud-platform` + openid + userinfo.email) |
| `redirect_uri_mismatch` | Redirect URI tidak terdaftar | Tambahkan `http://localhost:8080/` di Credentials → OAuth client |
| `Token exchange gagal` | Code salah / sudah dipakai / >10 menit | Ulangi `login` dari awal, paste code dengan cepat |
| `Tidak ada refresh_token` | Login tanpa consent offline | Login ulang (Klipkliper selalu minta `access_type=offline&prompt=consent`) |
| API `401 UNAUTHENTICATED` | Token invalid & refresh gagal | `login` ulang |
| API `403` | Kuota / lisensi / API belum di-enable | **Baca catatan penting di bawah** |
| API `404` model tidak tersedia | Model pensiun untuk akunmu | Set `KLIPKLIPER_GEMINI_MODEL` ke model lain |

### ⚠️ Catatan penting soal kuota OAuth (hasil riset 2026-10-05)

1. **Per 2026-06-18**, Google menghentikan jatah gratis Code Assist / AI Pro /
   AI Ultra melalui mekanisme "Login with Google" ala Gemini CLI untuk **akun
   konsumen**. Yang tetap didukung: lisensi **Code Assist Standard/Enterprise**.
   Artinya: login OAuth kemungkinan besar **tetap berhasil**, tapi panggilan
   API bisa 403/kehabisan kuota bila akunmu tidak punya lisensi.
2. Endpoint **publik** `generativelanguage.googleapis.com` secara resmi
   didokumentasikan untuk **API key**; dukungan token OAuth pihak ketiga di
   endpoint ini tidak dijamin dan laporan komunitas beragam.
3. **Fallback resmi** bila OAuth mentok:
   - **API key AI Studio** (https://aistudio.google.com/apikey) — gratis, ada
     free tier harian; atau
   - **Vertex AI** dengan project GCP + billing milikmu.
   
   Interface `AIProvider` memang dirancang pluggable — provider API-key
   (`claude.py`, `openai.py`, `openai_compat.py` untuk Groq/Ollama) tinggal
   ditambahkan tanpa mengubah modul lain.

## Mencabut akses

Hapus file `~/.klipkliper/gemini_token.json`, dan/atau cabut di
https://myaccount.google.com/permissions.

## Referensi

- OAuth client tipe Desktop & loopback redirect — Google Identity docs
- Scope dipakai = scope Gemini CLI (`cloud-platform`, terlihat di
  `~/.gemini/oauth_creds.json`)
- Endpoint: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
