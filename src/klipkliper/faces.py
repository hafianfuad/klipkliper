"""Face tracking + smart 9:16 crop untuk Klipkliper (Spike A).

Pipeline:
    tracker = FaceTracker()
    bboxes, valid, confs, meta = tracker.track("video.mp4", sample_fps=5)
    xs = tracker.crop_window(bboxes, valid, src_w=1280, src_h=720)

- track(): deteksi wajah (MediaPipe FaceDetector, model blaze_face_short_range)
  tiap 1/sample_fps detik, lalu interpolasi linear agar tiap frame punya bbox.
- crop_window(): window 9:16 (405x720) mengikuti center wajah, di-smoothing
  moving average ±15 frame, fallback ke tengah bila tak ada wajah.
"""
import os

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions

_MODEL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "assets", "models",
    "blaze_face_short_range.tflite")


class FaceTracker:
    """Deteksi wajah + hitung window crop 9:16 yang mulus."""

    def __init__(self, min_detection_confidence=0.5, model_path=None):
        self.min_conf = min_detection_confidence
        self.model_path = model_path or _MODEL
        if not os.path.exists(self.model_path):
            raise IOError(f"model tidak ditemukan: {self.model_path}")

    def _make_detector(self):
        base = BaseOptions(model_asset_path=self.model_path)
        opts = vision.FaceDetectorOptions(
            base_options=base,
            min_detection_confidence=self.min_conf,
        )
        return vision.FaceDetector.create_from_options(opts)

    def track(self, video_path, sample_fps=5):
        """Deteksi wajah per sampel, interpolasi ke tiap frame.

        Returns:
            bboxes: (n_frames, 4) float32 [x, y, w, h] piksel; NaN bila tak ada
                    sampel valid yang bisa diinterpolasi.
            valid: (n_frames,) bool — frame dianggap ada wajah.
            confs: (n_frames,) float32 — confidence terinterpolasi (0 bila invalid).
            meta: dict berisi fps, n_frames, src_w, src_h, sample_idx,
                  sample_confs (confidence per sampel valid).
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise IOError(f"cannot open {video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        step = max(1, int(round(fps / sample_fps)))
        sample_idx = list(range(0, n_frames, step))

        det = self._make_detector()
        # bbox per sampel: (x, y, w, h, conf) atau None
        samp = {}
        try:
            for i in sample_idx:
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ok, frame = cap.read()
                if not ok:
                    samp[i] = None
                    continue
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB,
                                  data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                res = det.detect(mp_img)
                best = None
                if res.detections:
                    d = max(res.detections,
                            key=lambda dd: dd.categories[0].score)
                    bb = d.bounding_box  # piksel: origin_x/y, width, height
                    best = (
                        float(bb.origin_x), float(bb.origin_y),
                        float(bb.width), float(bb.height),
                        float(d.categories[0].score),
                    )
                samp[i] = best
        finally:
            det.close()
            cap.release()

        frames = np.arange(n_frames, dtype=np.float64)
        valid_idx = np.array([i for i in sample_idx if samp[i] is not None],
                             dtype=np.float64)

        bboxes = np.full((n_frames, 4), np.nan, dtype=np.float32)
        confs = np.zeros(n_frames, dtype=np.float32)
        valid = np.zeros(n_frames, dtype=bool)
        sample_confs = []

        if len(valid_idx):
            vals = np.array([samp[int(i)][:4] for i in valid_idx])  # (m,4)
            cvals = np.array([samp[int(i)][4] for i in valid_idx])
            sample_confs = [float(c) for c in cvals]
            for k in range(4):
                bboxes[:, k] = np.interp(frames, valid_idx, vals[:, k]).astype(np.float32)
            confs = np.interp(frames, valid_idx, cvals).astype(np.float32)
            # validitas: interpolasi 0/1 dari titik sampel, threshold 0.5
            vflag = np.array([1.0 if samp[i] is not None else 0.0
                              for i in sample_idx])
            sidx = np.array(sample_idx, dtype=np.float64)
            valid = np.interp(frames, sidx, vflag) >= 0.5
            bboxes[~valid] = np.nan
            confs[~valid] = 0.0

        meta = {
            "fps": fps, "n_frames": n_frames, "src_w": src_w, "src_h": src_h,
            "sample_idx": sample_idx, "sample_confs": sample_confs,
        }
        return bboxes, valid, confs, meta

    def crop_window(self, bboxes, valid, src_w=1280, src_h=720,
                    smooth_radius=15):
        """Hitung posisi x window 9:16 per frame.

        Window: 405x720 (lebar = 720*9/16). x mengikuti center wajah,
        clamp ke [0, src_w-405], di-smoothing moving average ±smooth_radius.
        Frame tanpa wajah -> posisi tengah.
        """
        crop_w, crop_h = 405, 720
        max_x = src_w - crop_w
        center_x = max_x / 2.0

        cx = bboxes[:, 0] + bboxes[:, 2] / 2.0  # center wajah (NaN bila invalid)
        raw_x = np.clip(cx - crop_w / 2.0, 0, max_x)
        raw_x = np.where(valid, raw_x, center_x)

        # moving average dengan edge handling (pakai frame yang ada saja)
        n = len(raw_x)
        xs = np.empty(n, dtype=np.float64)
        for i in range(n):
            lo = max(0, i - smooth_radius)
            hi = min(n, i + smooth_radius + 1)
            xs[i] = raw_x[lo:hi].mean()
        return np.round(xs).astype(int), (crop_w, crop_h)
