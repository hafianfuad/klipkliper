# Build Klipkliper untuk Windows

Aplikasi dikembangkan di Linux, tapi target utama adalah **Windows 10/11**.
Build harus dilakukan di mesin Windows (PyInstaller tidak bisa cross-compile).

## Yang dibutuhkan di mesin Windows

1. **Python 3.11** (64-bit) dari python.org — centang "Add to PATH".
2. **ffmpeg** static build:
   - Download dari https://www.gyan.dev/ffmpeg/builds/ → `ffmpeg-release-essentials.zip`
   - Extract, copy `bin/ffmpeg.exe` ke folder hasil build (`dist/Klipkliper/`) —
     Klipkliper memanggil `ffmpeg`/`ffprobe` dari PATH atau dari folder aplikasinya.
3. **Microsoft Visual C++ Redistributable** (biasanya sudah ada di Windows 10/11).

## Langkah build

```bat
cd C:\path\ke\auto-clipper-clone
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pyinstaller

:: (opsional) pre-download model Whisper agar tidak download saat pertama jalan:
set HF_HUB_OFFLINE=0

pyinstaller klipkliper.spec
```

Hasil: `dist\Klipkliper\Klipkliper.exe` — copy `ffmpeg.exe` ke folder yang sama.

## Catatan penting

- **Model Whisper** (`small`, ~500MB) di-download otomatis saat pertama kali
  transkripsi (ke `%USERPROFILE%\.cache\huggingface`). Untuk mesin offline,
  pre-download dulu lalu copy folder cache-nya.
- **MediaPipe** di Windows: bila PyInstaller gagal bundling native lib,
  alternatifnya ganti `faces.py` ke detektor OpenCV DNN (ada di Fase 2).
  Uji `dist\Klipkliper\Klipkliper.exe` di mesin Windows bersih sebelum distribusi.
- **API key / OAuth** tersimpan di `%APPDATA%\Klipkliper` (QSettings) dan
  `~\.klipkliper\` (token OAuth, permission 0600).
- Untuk **installer** (.msi/.exe installer): pakai Inno Setup dengan script
  sederhana mengarah ke `dist\Klipkliper\` (Fase 2).
- Versi **console=True** di `.spec` berguna untuk debugging — ganti sementara
  bila butuh lihat log error.
