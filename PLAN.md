# RENCANA BUILD — Klipkliper

> **Keputusan locked (2026-10-05):**
> - Nama: **Klipkliper**
> - Target: **internal tim dulu** (Fase 4 komersialisasi ditunda)
> - AI engine: **OAuth ke AI berbasis langganan** (Claude, GPT, Gemini CLI, dst) — lihat §2.1
> - OS prioritas: **Windows dulu**, lalu macOS/Linux

Tujuan: aplikasi desktop yang mengubah video panjang jadi klip vertikal 9:16 siap upload,
dengan AI pemilih momen, caption bergaya, crop ngikutin wajah, dan autopost.
Dokumen ini: scope, arsitektur, roadmap fase, risiko, estimasi jujur.

---

## 1. PARITY CHECKLIST (dibedah dari turaturu.com/auto-clipper)

| # | Fitur | Keterangan |
|---|---|---|
| 1 | Import video | File lokal (mp4/mkv/mov/webm) + link YouTube + bulk channel/playlist |
| 2 | Transkripsi | Whisper lokal, word-level timestamps, 12 bahasa |
| 3 | AI pilih momen | Baca transkrip → skor klip (Hook/Suspense/Delivery 1–10) → urut skor tertinggi |
| 4 | Layar tinjau | Centang klip yang disuka; mode manual (timestamp sendiri); arahan fokus ("cari bagian lucu") |
| 5 | Hook & foreshadow | Teaser 2–8 dtk dari momen terkuat atau voice-over AI; transisi (Flash/Zoom/Slide/Swipe/Dissolve/Glitch) |
| 6 | Crop 9:16 pintar | Face tracking: Otomatis / Pembicara / Split 2–3 wajah; subtitle hindari wajah; landscape-fit blur |
| 7 | Caption | 31 gaya + 8 sequence, animasi masuk/keluar, highlight per kata, 25 font, edit transkrip |
| 8 | Batch render & antrean | Render banyak klip, jeda/lanjut, pilih encoder (GPU/CPU), color grade, 1080p, tanpa watermark |
| 9 | Thumbnail | 5 template + teks AI + editor |
| 10 | Autopost & jadwal | YouTube, TikTok, Facebook + Instagram, terjadwal (eksperimental) |
| 11 | AI engine | AI bawaan (kuota harian) atau API key sendiri (OpenAI/Gemini/Anthropic/Qwen/OpenAI-compatible) |
| 12 | Cross-platform | Windows 10/11, macOS (ARM+Intel), Linux; 1 lisensi = 3 perangkat |
| 13 | Komersial | Lisensi key, aktivasi perangkat, auto-update signed, garansi |

---

## 2. ARSITEKTUR & TECH STACK (rekomendasi)

```
┌─────────────────────────────────────────────┐
│ UI: PySide6 (Qt) — 1 codebase, 3 OS         │
├─────────────────────────────────────────────┤
│ Core (Python 3.11+):                        │
│  • ingest.py      — download (yt-dlp) / file│
│  • transcribe.py  — faster-whisper (lokal)  │
│  • faces.py       — MediaPipe detect+track  │
│  • score.py       — LLM pilih momen (H/S/D) │
│  • caption.py     — build file ASS (karaoke)│
│  • render.py      — ffmpeg: crop/caption/fx  │
│  • publish.py     — autopost APIs           │
│  • llm.py         — OpenAI-compatible client│
└─────────────────────────────────────────────┘
```

| Keputusan | Pilihan | Alasan |
|---|---|---|
| Bahasa inti | Python 3.11+ | Ekosistem AI/ML terkaya; semua library yang dibutuhkan ada |
| UI | PySide6 (Qt) | Native, 1 codebase 3 OS, packaging matang |
| Transkripsi | faster-whisper | 4–5x lebih cepat dari whisper asli, jalan di CPU |
| Face detect/track | MediaPipe (MVP) → InsightFace (opsional) | Ringan & cross-platform; upgrade bila perlu akurasi |
| Render | ffmpeg (static build dibundel) | Standar industri, semua efek via filter |
| Caption | Subtitle ASS + libass | Karaoke highlight per kata, animasi fade/move — ini cara profesionalnya |
| LLM | **Arsitektur provider OAuth-first** (lihat §2.1) |
| Packaging | PyInstaller **Windows dulu** (lalu macOS/Linux) |
| Autopost | YouTube Data API v3, TikTok Content Posting API, Meta Graph API | OAuth per platform |

### 2.1 AI Engine — OAuth ke AI langganan

Prinsip: pakai **langganan user yang sudah ada**, bukan API key bayar-per-token.
Arsitektur provider pluggable — 1 interface, N provider:

```
providers/
  base.py        # interface: chat(messages) -> text/JSON
  gemini_oauth.py  # Google OAuth (seperti Gemini CLI) → Generative Language API ✅ OAuth penuh
  claude.py        # API key (Anthropic Console) — lihat catatan
  openai.py        # API key (OpenAI Platform) — lihat catatan
  openai_compat.py # base URL + key → Groq, Ollama, Qwen, endpoint sendiri
```

**Catatan jujur per provider:**
- **Gemini ✅** — OAuth Google didukung resmi (mekanisme yang sama dipakai Gemini CLI:
  login akun Google → access token → Generative Language API). Ini yang paling mulus.
- **Claude ⚠️** — Anthropic **tidak menyediakan OAuth pihak ketiga** untuk API.
  Jalur resmi: API key dari console.anthropic.com. (OAuth hanya untuk CLI resmi mereka.)
- **GPT ⚠️** — OpenAI juga **tidak menyediakan OAuth** untuk langganan ChatGPT ke aplikasi pihak ketiga.
  Jalur resmi: API key dari platform.openai.com.
- **"Dan lainnya" ✅** — interface pluggable: provider baru tinggal tambah 1 file.

Jadi: **OAuth penuh untuk Google/Gemini; API key untuk Claude/GPT** (satu-satunya jalur resmi).
UI tetap satu: "Hubungkan AI" → pilih provider → login/key → tersimpan terenkripsi lokal.
Tidak ada "AI bawaan" berkuota di versi internal — tidak butuh server billing.

**Catatan penting soal "AI bawaan":** AutoClip kasih 50x AI/hari gratis — itu butuh **server proxy + billing** di sisi developer.
Untuk versi internal/tim: user pakai API key sendiri (kamu sudah punya Groq — langsung nyambung).
Untuk versi komersial: jadi Fase 4 (butuh backend).

---

## 3. ROADMAP FASE

### FASE 0 — Spike / Pembuktian konsep (3–5 hari)
Validasi 4 hal tersulit SEBELUM bangun UI:
- (a) Face tracking + smart crop 9:16 ngikutin pembicara — hasil mulus?
- (b) faster-whisper word timestamps Bahasa Indonesia — akurat?
- (c) Render ASS karaoke (highlight per kata) via ffmpeg — sesuai ekspektasi?
- (d) **Google OAuth (ala Gemini CLI) → panggil Gemini API dari Python** — flow login & refresh token jalan?
**Output:** prototype CLI: `video.mp4` masuk → 1 klip 9:16 + caption keluar. Go / no-go.

### FASE 1 — MVP internal ✅ SELESAI (2026-10-05)
Alur inti yang sudah bisa dipakai tim:
- Import file + link YouTube → transkrip otomatis (`ingest.py`, `transcribe.py`)
- AI pilih momen: `score.py` (LLM via provider, atau heuristic fallback tanpa LLM)
- Layar tinjau: centang klip → render (UI PySide6 `ui/`, lolos smoke test offscreen)
- Crop 9:16 ngikutin wajah (`faces.py` → `render_vertical_master()`), caption karaoke 2 style
- Pipeline + CLI: `render.py` `run_pipeline()`, `python -m klipkliper.cli clip`
- Provider AI: Groq / Claude / OpenAI (API key) + Gemini OAuth, via `make_provider` factory
- Windows: `klipkliper.spec` + `docs/windows-build.md` (build di mesin Windows)
- **E2E terverifikasi**: test-video.mp4 (46 dtk) → master 9:16 + klip 608×1080 caption sinkron
- Sisa butuh aksi Fian: build PyInstaller di Windows + tes login OAuth Google (`docs/oauth-setup.md`)

### FASE 2 — Polish kreator ✅ SELESAI (2026-10-05)
- **31 gaya caption** + **8 sequence animasi** (pop, fade, slide_up, typewriter, bounce, glow, wave) — `caption.py`, 248 kombinasi valid, regresi Hype/Clean byte-identical
- **Hook/teaser**: `hook.py` — teks hook 3 detik (style "Hook") disisip ke ASS sebelum burn
- **Voiceover AI**: `voiceover.py` via edge-tts (id-ID-ArdiNeural/GadisNeural) + ducking mix — ⚠️ belum tes live (proxy sandbox blokir Bing TTS; wajib tes di Windows)
- **Thumbnail generator**: `thumbnail.py` — 5 template (breaking, bold, split, minimal, quote), output 1280×720
- **Render upgrades**: 6 color grade, logo overlay (4 posisi), fade in/out, pilihan encoder — param opsional, kompatibel
- **Batch queue**: `queue.py` — tambah/pause/resume/hapus, state `queue.json` tahan restart
- **UI Fase 2**: dialog edit transkrip, dialog thumbnail, combo sequence/grade, logo browse, hook text + voiceover checkbox, dock antrean render + QueueWorker
- **Integrasi terverifikasi**: render sequence+hook+grade+fade+logo jalan; UI smoke offscreen lolos
- Sisa: tes voiceover live + build Windows + tes OAuth login (masih butuh aksi Fian/mesin Windows)

### FASE 3 — Distribusi ✅ SELESAI (2026-10-05)
- **Publisher interface** `publish/base.py` (`Publisher` ABC + `PublishError`), factory `make_publisher`, semua dukung `dry_run`
- **YouTube**: OAuth `youtube.upload` + resumable upload manual via requests (tanpa lib berat), default privacy unlisted; `docs/publish-youtube.md`
- **TikTok**: Content Posting API v2 Direct Post (init→chunk upload→status poll), default SELF_ONLY; `docs/publish-tiktok.md`
- **Instagram**: Graph API Reels resumable upload → container → publish → permalink; `docs/publish-instagram.md`
- **Facebook**: upload video ke Page via graph-video API; `docs/publish-facebook.md`
- **Scheduler**: `schedule/list/cancel/due/run_due`, persist `~/.klipkliper/schedule.json` tahan restart
- **CLI**: `publish now|schedule|run-due|list-schedule|cancel-schedule|authorize`, `ingest bulk <url> --max N`
- **Bulk ingest**: `list_youtube_videos` (extract_flat) + `bulk_youtube` (skip per-video error)
- **UI**: dialog Posting Klip (banner EKSPERIMENTAL), panel Jadwal, dialog kredensial per platform, PublishWorker
- **Terbatas sandbox**: upload live & download YouTube belum bisa dites dari sini (proxy/bot-check) — wajib tes di Windows dengan internet langsung + kredensial/app milik Fian (langkah di docs/publish-*.md)

### FASE 4 — Komersialisasi (opsional, 3–4 minggu)
- Sistem lisensi (key + aktivasi maks 3 perangkat + cabut perangkat)
- Auto-update signed per OS
- AI bawaan via proxy server (butuh backend + billing + kuota)
- Installer + halaman akun

---

## 4. RISIKO TEKNIS (jujur)

| Risiko | Dampak | Mitigasi |
|---|---|---|
| Kualitas crop wajah kalah dari AutoClip | Tinggi | Mereka polish bertahun-tahun; MVP target "cukup bagus", iterasi dari feedback |
| TikTok/Meta API berubah / butuh review | Tinggi | Autopost ditandai eksperimental (seperti AutoClip); fallback: render lalu upload manual |
| Performa CPU-only | Sedang | faster-whisper + MediaPipe relatif ringan; encoder CPU fallback otomatis |
| Ukuran bundle | Sedang | Python + torch + whisper ≈ 300–600MB; masih wajar untuk app desktop |
| YouTube OAuth verification (publik) | Sedang | Untuk internal: OAuth internal-mode cukup; publik butuh verifikasi Google |

---

## 5. ESTIMASI JUJUR

- **Fase 0 (spike):** 3–5 hari → prototype CLI terbukti jalan
- **Fase 1 (MVP internal):** 2–3 minggu → tim sudah bisa pakai harian
- **Fase 2+3 (parity fitur kreator):** 4–5 minggu
- **Fase 4 (komersial):** 3–4 minggu + butuh backend
- **Total parity penuh:** ±3–4 bulan kerja fokus

Fase 0 adalah filter: kalau 3 spike gagal, kita ubah pendekatan sebelum bakar waktu di UI.

---

## 6. KEPUTUSAN DARI KAMU (biar planning jadi build)

1. **Nama aplikasinya apa?** (biar bundle, window title, dan file konsisten dari awal)
2. **Internal tim dulu, atau langsung target dijual?** (menentukan perlu/tidaknya Fase 4)
3. **AI engine:** user bawa API key sendiri (Groq kamu langsung bisa dipakai) — atau mau AI bawaan berkuota? (yang kedua butuh server)
4. **OS prioritas pertama?** (usul: Windows dulu — mayoritas tim kreator, lalu macOS/Linux)

---

## 7. LANGKAH PERTAMA YANG KUSARANKAN

Mulai **Fase 0 spike sekarang**: aku bangun prototype CLI yang ambil 1 video panjang
→ keluar 1 klip vertikal 9:16 dengan caption highlight per kata. Kamu nilai hasilnya,
kalau oke baru kita bangun UI-nya. Tanpa komitmen besar di depan.

---

*Dibuat 2026-10-05. Lokasi proyek: `~/workspace/auto-clipper-clone/`*

---

## Hasil Fase 0 spike (2026-10-05) — 4/4 GO ✅

| Spike | Hasil | Angka kunci |
|---|---|---|
| A — Face tracking + crop 9:16 | **GO** ✅ | 99.2% frame terdeteksi, jitter 0.69 px/frame |
| B — faster-whisper ID + word timestamps | **GO** ✅ | ~97.6% akurat, 0.43x real-time (CPU) |
| C — Caption karaoke ASS via ffmpeg | **GO** ✅ | Sinkron ±0.1 dtk, 2 style jalan |
| D — Google OAuth → Gemini API | **GO (catatan)** ⚠️ | Kode lengkap & terverifikasi inspeksi; login live belum dites |

⚠️ **Catatan Spike D (penting):** per Juni 2026 Google menghentikan kuota gratis Code Assist/AI Pro/Ultra
via "Login with Google" ala Gemini CLI untuk akun konsumen — login OAuth kemungkinan berhasil tapi API bisa
403 tanpa lisensi. Fallback resmi sudah disiapkan: provider API-key (AI Studio free tier / Groq) via interface
pluggable yang sama. Untuk Claude & GPT, API key memang satu-satunya jalur resmi (tidak ada OAuth pihak ketiga).
