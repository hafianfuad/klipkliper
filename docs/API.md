# Klipkliper — Kontrak API antar modul (Fase 1)

Semua modul di `src/klipkliper/`. Venv: `.venv/bin/python`.
Modul yang SUDAH ADA (jangan ubah signature-nya, baca dulu sebelum pakai):

- `transcribe.py` → `transcribe(video_path, model="small", lang="id", device="auto", compute_type="auto")`
  → `list[Segment]` dengan `Segment = {"start": float, "end": float, "text": str,
  "words": [{"word": str, "start": float, "end": float}]}`
- `faces.py` → `FaceTracker(min_detection_confidence=0.5, model_path=None)`
  - `.track(video_path, sample_fps=5)` → `(bboxes, valid)`; bboxes = list per sampel
    `{"x","y","w","h"}` ternormalisasi 0..1 + confidence; valid = list[bool]
  - `.crop_window(bboxes, valid, src_w, src_h, out_w=405, out_h=720, smooth=15)`
    → `list[int]` crop-x per frame video (panjang = jumlah frame)
- `caption.py` → `build_ass(words, style_name="Hype", out_path=None) -> str(path .ass)`
  words = `[{"word","start","end"}]` dalam detik, style ada di `STYLES` dict
- `providers/base.py` → `AIProvider` (abc): `.chat(messages, json_mode=False) -> str`,
  `.chat_json(messages) -> Any`; `Message = {"role": "system|user|assistant", "content": str}`;
  `ProviderError(message, hint=None)`
- `providers/gemini_oauth.py` → `GeminiOAuthProvider` (sudah jadi, OAuth Google)

## Modul yang harus DIBUAT (kontrak di bawah — WAJIB dipatuhi)

### 1. `providers/openai_compat.py`
- `class OpenAICompatProvider(AIProvider)`: `__init__(base_url, api_key, model, timeout=120)`
  Chat Completions API (`POST {base_url}/chat/completions`, OpenAI format).
  `json_mode=True` → `"response_format": {"type": "json_object"}`.
  Error HTTP → `ProviderError` dengan hint.
- `class GroqProvider(OpenAICompatProvider)`: base_url `https://api.groq.com/openai/v1`,
  default model `llama-3.3-70b-versatile`.
- `providers/claude.py` → `class ClaudeProvider(AIProvider)`: `__init__(api_key, model="claude-sonnet-4-5", ...)`,
  pakai Messages API (`https://api.anthropic.com/v1/messages`, header `x-api-key`, `anthropic-version: 2023-06-01`).
- `providers/openai.py` → `class OpenAIProvider(OpenAICompatProvider)`: base_url
  `https://api.openai.com/v1`, default model `gpt-4o-mini`.
- Semua: `from .base import AIProvider, Message, ProviderError`; tanpa dependensi baru
  selain `requests` (sudah ada).

### 2. `score.py` — pilih momen klip
- `CLIP_MIN = 20.0`, `CLIP_MAX = 90.0` (detik), `DEFAULT_N = 5`
- `Clip = {"start": float, "end": float, "score": float 0..100, "title": str, "reason": str}`
- `score_moments(segments, provider=None, n=DEFAULT_N, lang="id") -> list[Clip]`
  - Jika `provider` diberikan: gabung segmen jadi teks bernomor `[00:12-00:18] teks...`,
    minta LLM (system prompt Indonesia) memilih ≤ n momen terbaik 20–90 dtk,
    output JSON `{"clips": [{"start","end","title","reason","score"}]}` via `chat_json`.
    Validasi: start<end, durasi dalam [CLIP_MIN, CLIP_MAX], clamp ke durasi total,
    buang yang overlap >50% (keep skor tertinggi). Jika LLM gagal/JSON rusak →
    fallback heuristic (jangan raise).
  - Jika `provider=None`: heuristic murni — sliding window 45 dtk (step 15 dtk),
    skor = kepadatan kata + bonus kata tanya/seru/keyword ("jangan","rahasia","gratis",
    "cara","kenapa","terbukti", angka, "AI") − penalti window terlalu sepi.
    Title = 8 kata pertama, reason = "heuristic".
  - Selalu kembalikan list terurut skor menurun. Jangan pernah raise untuk input valid.

### 3. `ingest.py`
- `MediaInfo = {"path": str, "duration": float, "width": int, "height": int, "fps": float}`
- `probe(path) -> MediaInfo` via ffprobe (subprocess, jangan tambah dependensi).
- `from_local(path, workdir) -> MediaInfo`: validasi file ada & bisa di-probe;
  copy/symlink ke workdir bila perlu. Raise `IngestError` (subclass Exception) bila gagal.
- `from_youtube(url, workdir) -> MediaInfo`: pakai `yt_dlp` (sudah di venv),
  format `bv*[height<=1080]+ba/b[height<=1080]/b`, output `%(id)s.%(ext)s` di workdir.
  Raise `IngestError` dengan pesan jelas bila diblokir (bot-check) — JANGAN retry loop.

### 4. `render.py` — orkestrasi pipeline
- `render_vertical_master(src, crop_xs, out_path, width=608, height=1080) -> str`:
  crop per frame memakai `crop_xs` (list crop-x per frame dari `faces.crop_window`).
  Implementasi: baca frame via `cv2.VideoCapture`, crop `frame[:, x:x+405]`,
  resize ke 608×1080, pipe rawvideo BGR ke ffmpeg (`-f rawvideo -pix_fmt bgr24 -s 608x1080 -r fps -i -`),
  audio di-copy dari src (`-i src -map 0:v -map 1:a? -c:v libx264 -preset veryfast -crf 20 -c:a aac`).
  Untuk MVP boleh render sequential (tanpa threading).
- `render_clip(master_9x16, clip: dict, words, style, out_path) -> str`:
  filter words ke rentang [start,end], offset waktu `-start`, `build_ass(...)`,
  ffmpeg `-ss {start} -t {dur} -i master -vf ass='{ass_path}' -c:v libx264 -preset veryfast -crf 20 -c:a aac out`.
  Escape path ASS untuk Windows (`ass='C\:/...'`).
- `run_pipeline(src, outdir, provider=None, n_clips=5, style="Hype", lang="id", progress=None) -> dict`:
  langkah: probe → transcribe → track faces → crop_window → render_vertical_master
  → score_moments → render_clip per klip. `progress(stage: str, frac: float)` optional callback.
  Return `{"master": path, "clips": [{"path","start","end","score","title"}], "segments": [...]}`.
  Simpan artefak di `outdir`: `master_9x16.mp4`, `transcript.json`, `clip_01.mp4`…

### 5. `cli.py`
- `python -m klipkliper.cli clip <video|url> --out DIR [--n 5] [--style Hype] [--lang id]
  [--provider groq|gemini|claude|openai|none] [--model ...] [--api-key ...] [--whisper-model small]`
  - `--provider none` (default) → heuristic, tanpa LLM.
  - API key via argumen atau env (`GROQ_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`).
  - Print progress ke stdout, akhiri dengan daftar path klip.
- `python -m klipkliper.cli providers` → list provider + status config (tanpa bocorkan key).

### 6. UI `ui/` (PySide6) — baca kontrak modul di atas
- `ui/main.py` → `python -m klipkliper.ui.main`: `QMainWindow` "Klipkliper":
  - Toolbar: [Import Video] [Import YouTube URL] [Pilih Provider AI ▾] [Render]
  - Panel kiri: daftar klip kandidat (checkbox, skor, judul, durasi, tombol Play-preview)
  - Panel tengah: preview video (QVideoWidget + QMediaPlayer; jika gagal, tampilkan QLabel placeholder —
    JANGAN crash), transcript (QListWidget segmen, klik → seek)
  - Panel kanan/bawah: log progress (QTextEdit), pilihan style caption (QComboBox dari `caption.STYLES`),
    jumlah klip (QSpinBox), tombol "Render yang dipilih" + QProgressBar
  - Render jalan di `QThread` (jangan freeze UI), panggil `render.run_pipeline` dengan provider
    dari setting (QSettings: provider, api key terenkripsi sederhana via keyring bila ada, else QSettings biasa)
  - Dialog Settings: provider AI (none/groq/claude/openai/gemini-oauth), api key, model, whisper model, bahasa
- Struktur: `ui/main.py`, `ui/worker.py` (QThread), `ui/settings.py` (dialog + QSettings),
  `ui/preview.py` (video widget dengan fallback). Kode harus import-safe dalam mode offscreen
  (`QT_QPA_PLATFORM=offscreen`) — jangan panggil platform-specific di import time.

## Aturan umum
- Bahasa komentar/docstring: Indonesia, ringkas.
- Jangan tambah dependensi di luar: stdlib + requests + opencv + numpy + faster-whisper +
  mediapipe + yt-dlp + google-auth* + PySide6.
- Semua path output via `pathlib`. Jangan hardcode path user.
- Test manual tiap modul: berikan `if __name__ == "__main__"` smoke test minimal.

---

## FASE 2 — Kreator polish (kontrak tambahan)

Aturan umum Fase 1 tetap berlaku. Dependensi baru yang dibolehkan: `edge-tts`
(voiceover), `Pillow` (sudah ada). Font: utamakan font bawaan Windows
(Arial, Arial Black, Impact, Verdana, Tahoma, Trebuchet MS, Georgia) dengan
fallback DejaVu Sans (Linux dev) — JANGAN download 25 font.

### A. `caption.py` — ekspansi
- `STYLES`: dict berisi **31 gaya** (termasuk "Hype" & "Clean" yang sudah ada).
  Tiap entry: `{font, size, bold, italic, color_primary, color_highlight,
  outline, outline_color, shadow, alignment, margin_v, max_words_per_line,
  karaoke: bool}`. Variasi: warna highlight, posisi (bawah/tengah/atas),
  karaoke on/off, gaya (bold outline / clean / box / neon / minimal...).
- `SEQUENCES`: dict **8 sequence animasi** caption: `none`, `pop` (scale masuk),
  `fade`, `slide_up`, `typewriter` (kata muncul berurutan tanpa karaoke sweep),
  `bounce`, `glow`, `wave`. Implementasi via tag ASS override
  (`\t`, `\move`, `\fad`, `\fscx`...) pada tiap event — tanpa plugin eksternal.
- `build_ass(words, style_name="Hype", sequence_name="none", out_path=None) -> str`
  (tambah param `sequence_name`; default menjaga kompatibilitas).
- `list_styles() -> list[str]`, `list_sequences() -> list[str]`.
- `avoid_face`: bila `True`, caption diposisikan di sepertiga bawah bila wajah
  di tengah (sederhana: pakai margin_v lebih besar) — param opsional di build_ass.

### B. `hook.py` (baru)
- `add_hook_text(words_ass_path, hook_text, duration=3.0) -> str(new .ass)`:
  sisipkan 1 event ASS (0–duration) gaya "Hook" (font besar, tengah-atas,
  warna aksen) ke file ASS yang sudah ada. Dipakai sebelum burn.
- `render_hook_clip(...)`: JANGAN buat fungsi render terpisah — hook cukup
  di level ASS + opsi voiceover di bawah.

### C. `voiceover.py` (baru)
- `synthesize(text, lang="id", voice=None, out_path) -> str` via `edge-tts`
  (voice default Indonesia: `id-ID-ArdiNeural` / `id-ID-GadisNeural`; param
  `voice` bisa override). Butuh internet; gagal → raise `VoiceoverError` jelas.
- `mix_with_clip(clip_path, vo_path, out_path, vo_volume=1.0, duck=0.25) -> str`:
  campur voiceover di atas audio klip dengan ducking sederhana
  (audio asli diturunkan ke `duck` selama vo berbunyi — via `sidechaincompress`
  atau volume automation sederhana; pilih yang stabil).
- Tanpa edge-tts terinstal → error jelas "pip install edge-tts".

### D. `thumbnail.py` (baru)
- `generate(source_video, at_time, title, template="breaking", out_path,
  logo_path=None) -> str` — ekstrak frame 1280×720 via ffmpeg, render dengan PIL.
- 5 template: `breaking` (banner merah ala news), `bold` (judul besar tengah),
  `split` (crop wajah kiri + teks kanan), `minimal` (gradasi gelap + teks kecil),
  `quote` (teks kutipan tengah). Ukuran output 1280×720.
- Font: DejaVuSans-Bold (cek via PIL; fallback default).

### E. `render.py` — upgrade (tambah fungsi, JANGAN ubah signature yang ada)
- `GRADES = {"none": None, "warm": "eq=...", "cool": ..., "vivid": ..., "cinematic": ..., "bw": ...}`
  preset color grade sebagai filter ffmpeg `eq`/`colorbalance`. 
- `render_clip(..., grade="none", logo_path=None, logo_pos="top-right",
  fade=0.3, encoder="libx264", crf=20)`: param baru opsional di akhir
  (kompatibel). fade = fade in/out detik (0 = mati). logo = overlay PNG.
- `render_vertical_master(..., encoder="libx264")`: param encoder opsional.

### F. `queue.py` (baru) — batch queue
- `class RenderQueue`: `add(job: dict)`, `list()`, `pause()`, `resume()`,
  `clear_done()`, `run(progress_cb)` — eksekusi job satu per satu via
  `run_pipeline`/`render_clip`; state tersimpan di `queue.json` (tahan restart);
  `pause()` menghentikan antar-job (tidak di tengah ffmpeg).
- Job dict: `{"src":..., "outdir":..., "n_clips":..., "style":..., "sequence":...,
  "grade":..., "hook_text":..., "status": "queued|running|done|failed|paused"}`.

### G. UI Fase 2 (tambah ke `ui/`, JANGAN rombak main.py — tambah panel/dialog)
- Dialog "Edit Transkrip": tabel segmen (start, end, teks bisa diedit) →
  simpan → render ulang caption klip terpilih.
- Panel/Combo baru di main window: sequence caption, grade, logo (pilih file),
  hook text (QLineEdit, kosong = mati), tombol "Buat Thumbnail" (pilih template
  + judul → preview + simpan), panel Queue (daftar job, pause/resume/hapus).
- Worker: dukung `RenderQueue`; progress per job.

---

## FASE 3 — Distribusi: autopost + bulk ingest (kontrak)

Tujuan: klip jadi bisa langsung diposting ke YouTube/TikTok/Instagram/Facebook,
dijadwalkan, dan ingest bulk dari channel/playlist YouTube.
Status AutoClip: "experimental" — di Klipkliper pun tandai eksperimental di UI.

Aturan: JANGAN tambah dependensi berat. Pakai `requests` + `google-auth-oauthlib`
(sudah ada). Semua token OAuth disimpan di `~/.klipkliper/<platform>_token.json`
(permission 0600), JANGAN di repo. Semua modul publish WAJIB punya mode
`dry_run=True` (validasi + bangun request tanpa kirim) untuk tes tanpa akun.

### A. `publish/base.py`
- `class Publisher(abc.ABC)`:
  - `name: str` (mis. "youtube")
  - `is_configured() -> bool` — token/kredensial ada & valid
  - `authorize_flow() -> str` — kembalikan URL/keterangan langkah user
    (untuk OAuth: URL authorize; untuk key: instruksi)
  - `publish(video_path, title, description="", tags=None, dry_run=False,
    **kw) -> dict` — return `{"id":..., "url":...}`; `dry_run` → return
    `{"dry_run": True, "request": {...}}` tanpa kirim.
  - `refresh_if_needed()` — refresh token bila didukung
- `class PublishError(Exception)` dengan `hint` aksi user (pola ProviderError).

### B. `publish/google_oauth.py` (bantu, dipakai youtube)
- Generalisasi pola dari `providers/gemini_oauth.py` — BOLEH import & pakai
  ulang fungsi amannya (jangan duplikat bila bisa diimport).
- `get_youtube_token(client_id, client_secret) -> dict` / simpan
  `~/.klipkliper/youtube_token.json`; scope:
  `https://www.googleapis.com/auth/youtube.upload` (+ openid).
- Flow: `authorize_url(...)`, `exchange_code(...)`, `refresh(...)`.

### C. `publish/youtube.py`
- `class YouTubePublisher(Publisher)`: upload via **resumable upload manual**
  dengan `requests` (JANGAN google-api-python-client):
  1. `POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status`
     header `Authorization: Bearer`, `Content-Type: application/json`,
     body `{snippet:{title,description,tags,categoryId:"27"},status:{privacyStatus}}`
  2. `PUT` ke session URI dengan file (chunk 8MB, header `Content-Range`).
  3. Return `{"id": videoId, "url": "https://youtu.be/{id}"}`.
  Param: `privacy="private|unlisted|public"`, `made_for_kids=False`.
- `docs/publish-youtube.md`: buat OAuth client, aktifkan YouTube Data API v3,
  langkah authorize via CLI, catatan kuota (upload ≈ 1600 unit, default 10rb/hari).

### D. `publish/tiktok.py`, `publish/instagram.py`, `publish/facebook.py`
- `TikTokPublisher`: Content Posting API (FILE_UPLOAD):
  `POST https://open.tiktokapis.com/v2/post/publish/video/init/` →
  upload chunk via PUT ke upload_url → publish. Auth: `client_key` dari
  TikTok Developer Portal (user buat app sendiri). `docs/publish-tiktok.md`
  (daftar app, scope video.upload, sandbox vs production).
- `InstagramPublisher`: Graph API Reels:
  `POST /{ig-user-id}/media` (media_type=REELS, video_url ATAU upload via
  `/{id}/media` containers... — pakai **resumable upload**: init → upload
  chunks → create container → `/{id}/media_publish`). Sederhanakan: dukung
  upload dari file lokal via upload session. `docs/publish-instagram.md`
  (akun Bisnis/Kreator + FB app + token Page).
- `FacebookPublisher`: `POST /{page-id}/videos` (upload video ke Page)
  via `https://graph-video.facebook.com`. `docs/publish-facebook.md`.
- Semua: `is_configured`, `authorize_flow` (instruksi jelas, bukan sekadar
  "baca docs"), `publish(..., dry_run)`, `PublishError` + hint.
  Implementasi mengikuti dokumentasi resmi API masing-masing (verifikasi
  endpoint via riset singkat bila ragu — catat sumber di docstring).

### E. `publish/scheduler.py`
- `class Scheduler`: simpan `~/.klipkliper/schedule.json` (atau workdir):
  `schedule(platform, video_path, title, description, at_iso, **kw) -> job_id`,
  `list()`, `cancel(job_id)`, `due(now=None) -> [jobs]` (at <= now &
  status queued), `mark_done/job_failed`.
- `run_due(publishers: dict, dry_run=False) -> [results]` — eksekusi job due.
- CLI: `python -m klipkliper.cli publish-now <clip> --to youtube --title ...
  [--dry-run]` dan `publish schedule ... --at "2026-10-06 18:00"` dan
  `publish run-due [--dry-run]`.

### F. `ingest.py` — tambah (JANGAN ubah yang ada)
- `list_youtube_videos(url, max_videos=20) -> list[{"id","title","url"}]`
  via yt_dlp `extract_flat` (tanpa download).
- `bulk_youtube(url, workdir, max_videos=20, progress=None) -> list[MediaInfo]`
  — download tiap video (pakai `from_youtube` yang ada per URL). Tangani
  error per video (skip + catat, jangan gagal total).

### G. UI Fase 3 (tambah ke `ui/`, lazy import publish.*)
- `publish_dialog.py`: dialog per klip — judul, deskripsi, tags, checkbox
  platform (youtube/tiktok/instagram/facebook, hanya yang configured yang
  enabled + tombol "Hubungkan"), privasi YT, tombol "Posting sekarang"
  / "Jadwalkan" (datetime picker). Label "EKSPERIMENTAL" jelas.
- `schedule_panel.py`: daftar jadwal (waktu, platform, judul, status),
  tombol batal, tombol "Jalankan yang jatuh tempo".
- `publish_settings.py`: dialog kredensial per platform (client key/secret,
  token path, tombol authorize → buka browser URL, input code).
- Worker: `PublishWorker` (QThread) untuk publish/schedule agar UI tak freeze.
