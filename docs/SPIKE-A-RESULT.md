# SPIKE A — Hasil: Face tracking + smart crop 9:16

**Verdict: GO** (2026-10-05)

## Angka
| Metrik | Hasil | Kriteria |
|---|---|---|
| Frame terdeteksi wajah | **99.2%** | >90% ✅ |
| Confidence rata-rata | 0.611 (n=230 sampel @5fps) | — |
| Kehalusan dx (std) | **0.69 px/frame** | <3 px ✅ |
| dx maksimum | 2.0 px/frame | — |
| Frame window diam | 61.0% | — |
| Output | 608x1080, 30fps, 46.37s, libx264 | 9:16 ✅ |
| Waktu tracking (1391 frame) | 40.8s | — |
| Waktu render (2 video) | 77.6s | — |

Verifikasi visual: wajah konsisten di tengah crop pada t=5/20/35 dtk, tidak ada jitter.

## File
- `src/klipkliper/faces.py` — class `FaceTracker` (`track()` + `crop_window()`)
- `spike_a.py` — runner spike (tracking → metrik → render clean + debug)
- `assets/models/blaze_face_short_range.tflite` — model MediaPipe (230KB, dibundel)
- `testdata/test-crop.mp4` — hasil crop 9:16
- `testdata/test-crop-debug.mp4` — sama + kotak wajah hijau untuk verifikasi

## Masalah yang ditemui & solusi
1. **mediapipe 1.0.1 tidak punya `mp.solutions`** (dihapus di v1.x) → pakai Tasks API
   `mediapipe.tasks.python.vision.FaceDetector` + model `blaze_face_short_range.tflite`
   (diunduh dari storage.googleapis.com/mediapipe-models).
2. **Layout import non-standar** di build ini: `BaseOptions` harus dari
   `mediapipe.tasks.python.core.base_options`, bukan `vision.BaseOptions`.
3. **Native lib butuh `libEGL.so.1` + `libGLESv2.so.2`** yang tidak ada di container →
   install manual .deb `libegl1`, `libegl-mesa0`, `libgles2` (Ubuntu 24.04).
   **Catatan packaging:** installer Windows (PyInstaller) harus menyertakan DLL
   setara atau memastikan dependensi ini ada — perlu diuji di Windows sejak Fase 1.

## Catatan untuk Fase 1
- Sampling 5fps + interpolasi linear sudah cukup mulus; tidak perlu tracking tiap frame.
- Moving average ±15 frame efektif menekan jitter (std 0.69px).
- Multi-wajah: saat ini ambil confidence tertinggi; mode split 2–3 wajah (parity AutoClip)
  dikerjakan di Fase 2.
- Threshold `min_detection_confidence=0.5` cocok untuk video test ini; jadikan parameter UI.
