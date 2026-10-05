#!/usr/bin/env python3
"""Spike A: face tracking + smart crop 9:16 -> testdata/test-crop.mp4 (+debug).

Jalankan: ~/workspace/auto-clipper-clone/.venv/bin/python spike_a.py
"""
import os
import subprocess
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from klipkliper.faces import FaceTracker

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "testdata", "test-video.mp4")
OUT_CLEAN = os.path.join(ROOT, "testdata", "test-crop.mp4")
OUT_DEBUG = os.path.join(ROOT, "testdata", "test-crop-debug.mp4")
OUT_W, OUT_H = 608, 1080
FPS_OUT = 30


def render(xs, crop_wh, bboxes, valid, meta, out_path, debug=False):
    crop_w, crop_h = crop_wh
    sx, sy = OUT_W / crop_w, OUT_H / crop_h
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{OUT_W}x{OUT_H}", "-r", str(FPS_OUT),
        "-i", "-", "-an",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "medium", "-crf", "20",
        "-movflags", "+faststart",
        out_path,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cap = cv2.VideoCapture(SRC)
    n = meta["n_frames"]
    i = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            x = int(xs[i])
            crop = frame[0:crop_h, x:x + crop_w]
            out = cv2.resize(crop, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)
            if debug and valid[i] and not np.isnan(bboxes[i, 0]):
                fx, fy, fw, fh = bboxes[i]
                # koordinat wajah relatif terhadap crop, lalu skala ke output
                rx, ry = (fx - x) * sx, fy * sy
                rw, rh = fw * sx, fh * sy
                cv2.rectangle(out, (int(rx), int(ry)),
                              (int(rx + rw), int(ry + rh)), (0, 255, 0), 3)
                cv2.putText(out, f"f{i} det",
                            (int(rx), max(0, int(ry) - 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
            elif debug:
                cv2.putText(out, f"f{i} NO-FACE", (20, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)
            proc.stdin.write(out.tobytes())
            i += 1
            if i % 300 == 0:
                print(f"  render {i}/{n}", flush=True)
    finally:
        cap.release()
        proc.stdin.close()
        proc.wait()
    return i


def main():
    t0 = time.time()
    tracker = FaceTracker(min_detection_confidence=0.5)
    print("tracking faces...", flush=True)
    bboxes, valid, confs, meta = tracker.track(SRC, sample_fps=5)
    t_track = time.time() - t0
    print(f"track selesai: {t_track:.1f}s", flush=True)

    xs, crop_wh = tracker.crop_window(
        bboxes, valid, src_w=meta["src_w"], src_h=meta["src_h"])

    # --- metrik ---
    n = meta["n_frames"]
    det_rate = float(valid.mean()) * 100
    avg_conf = float(np.mean(meta["sample_confs"])) if meta["sample_confs"] else 0.0
    dx = np.diff(xs.astype(np.float64))
    smooth_std = float(dx.std())
    smooth_max = float(np.abs(dx).max())
    # seberapa sering window diam total (0 px) vs bergerak
    still_pct = float((np.abs(dx) < 0.5).mean()) * 100

    print("render clean...", flush=True)
    t1 = time.time()
    n1 = render(xs, crop_wh, bboxes, valid, meta, OUT_CLEAN, debug=False)
    print("render debug...", flush=True)
    n2 = render(xs, crop_wh, bboxes, valid, meta, OUT_DEBUG, debug=True)
    t_render = time.time() - t1
    total = time.time() - t0

    # verifikasi dimensi output
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate,duration",
         "-of", "default=noprint_wrappers=1", OUT_CLEAN],
        capture_output=True, text=True).stdout.strip()

    print("\n===== HASIL SPIKE A =====")
    print(f"frame video        : {n} ({meta['src_w']}x{meta['src_h']} @ {meta['fps']:.0f}fps)")
    print(f"frame terdeteksi   : {det_rate:.1f}%")
    print(f"confidence rata2   : {avg_conf:.3f} (n={len(meta['sample_confs'])} sampel)")
    print(f"kehalusan dx std   : {smooth_std:.2f} px/frame")
    print(f"dx maks            : {smooth_max:.1f} px/frame")
    print(f"frame window diam  : {still_pct:.1f}%")
    print(f"waktu tracking     : {t_track:.1f}s")
    print(f"waktu render 2x    : {t_render:.1f}s")
    print(f"waktu total        : {total:.1f}s")
    print(f"frame dirender     : clean={n1} debug={n2}")
    print(f"output             :\n{probe}")
    print(f"file               : {OUT_CLEAN}")
    print(f"file               : {OUT_DEBUG}")

    go = det_rate > 90 and smooth_std < 3.0
    print(f"\nVERDICT: {'GO' if go else 'NO-GO'} "
          f"(det>90%: {det_rate > 90}, dx_std<3px: {smooth_std < 3.0})")


if __name__ == "__main__":
    main()
