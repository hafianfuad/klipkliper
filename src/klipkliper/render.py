"""Render pipeline Klipkliper: master vertikal 9:16 + klip + caption.

Fungsi utama:
    render_vertical_master(src, crop_xs, out_path, width=608, height=1080,
                           encoder="libx264")
    render_clip(master_9x16, clip, words, style, out_path, grade="none",
                logo_path=None, logo_pos="top-right", fade=0.3,
                encoder="libx264", crf=20)
    run_pipeline(src, outdir, provider=None, n_clips=5, style="Hype",
                 lang="id", progress=None, grade="none", logo_path=None,
                 logo_pos="top-right", fade=0.3)
"""
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from .caption import build_ass
from .ingest import probe
from .transcribe import transcribe

# Lebar window 9:16 untuk sumber 720p (720*9/16). Lihat faces.crop_window.
CROP_W = 405

# Preset color grade sebagai filter ffmpeg (sintaks valid ffmpeg 7/8).
GRADES = {
    "none": None,
    "warm": ("eq=brightness=0.03:saturation=1.15:contrast=1.02,"
             "colorbalance=rs=0.08:gs=0.02:bs=-0.06:rm=0.05:gm=0.0:bm=-0.04"),
    "cool": ("eq=brightness=0.02:saturation=1.10:contrast=1.03,"
             "colorbalance=rs=-0.06:gs=0.0:bs=0.08:rm=-0.04:gm=0.0:bm=0.06"),
    "vivid": "eq=brightness=0.02:contrast=1.08:saturation=1.50",
    "cinematic": ("eq=brightness=-0.04:contrast=1.10:saturation=0.85,"
                  "colorbalance=rs=0.05:gs=-0.02:bs=-0.05:"
                  "rm=0.03:gm=-0.01:bm=-0.03"),
    "bw": "eq=saturation=0:contrast=1.05",
}

# Posisi overlay logo (margin 20px dari tepi).
_LOGO_POS = {
    "top-right": "W-w-20:20",
    "top-left": "20:20",
    "bottom-right": "W-w-20:H-h-20",
    "bottom-left": "20:H-h-20",
}


def _video_codec_args(encoder="libx264", crf=20):
    """Argumen codec video; preset/crf hanya untuk encoder libx*."""
    args = ["-c:v", encoder]
    if encoder in ("libx264", "libx265"):
        args += ["-preset", "veryfast", "-crf", str(crf)]
    elif encoder == "mpeg4":
        args += ["-q:v", "3"]
    return args


def _ffmpeg(*args):
    """Jalankan ffmpeg, raise RuntimeError bila gagal."""
    p = subprocess.run(["ffmpeg", "-y", *args],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg gagal:\n{p.stderr.strip()[-800:]}")
    return p


def _escape_ass_path(path):
    """Escape path untuk filter libass, aman di Windows & Linux.

    Contoh Windows: ass='C\\:/Users/x/clip.ass'
    """
    s = str(Path(path).resolve()).replace("\\", "/")
    s = s.replace(":", "\\:").replace("'", "\\'")
    return f"ass='{s}'"


def render_vertical_master(src, crop_xs, out_path, width=608, height=1080,
                           encoder="libx264"):
    """Render master 9:16: crop per frame mengikuti crop_xs, audio di-copy.

    Args:
        src: path video sumber (landscape -> crop lebar ngikutin wajah;
            portrait/vertikal -> full frame, crop tinggi bila perlu).
        crop_xs: posisi x window crop per frame (dari faces.crop_window).
        out_path: path mp4 output.
        encoder: encoder ffmpeg (default "libx264").
    """
    info = probe(src)
    src_w = info["width"]
    src_h = info["height"]
    fps = info["fps"] or 30.0
    TARGET_AR = 9 / 16
    src_ar = src_w / src_h if src_h else TARGET_AR
    if src_ar <= TARGET_AR * 1.02:
        # Sumber sudah vertikal: crop tinggi agar pas 9:16 (tengah),
        # tanpa crop samping. Full frame bila sudah pas 9:16.
        crop_w = src_w
        crop_h = min(src_h, int(src_w / TARGET_AR))
        y0 = (src_h - crop_h) // 2
        portrait = True
    else:
        # Landscape: crop lebar 9:16 mengikuti wajah (crop_xs).
        crop_w = min(CROP_W, src_w)
        crop_h = src_h
        y0 = 0
        portrait = False
    max_x = max(0, src_w - crop_w)

    xs = list(crop_xs)
    if not xs:
        raise ValueError("crop_xs kosong")

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise IOError(f"tidak bisa buka video: {src}")
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or len(xs)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}", "-r", f"{fps:.3f}", "-i", "-",
        "-i", str(src),
        "-map", "0:v", "-map", "1:a?",
        *_video_codec_args(encoder),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        str(out_path),
    ]
    p = subprocess.Popen(["ffmpeg", "-y", *cmd],
                         stdin=subprocess.PIPE,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.PIPE)
    try:
        for i in range(n_frames):
            ok, frame = cap.read()
            if not ok:
                break
            if portrait:
                crop = frame[y0:y0 + crop_h, :]
            else:
                x = int(xs[min(i, len(xs) - 1)])
                x = max(0, min(x, max_x))
                crop = frame[:, x:x + crop_w]
            small = cv2.resize(crop, (width, height),
                               interpolation=cv2.INTER_AREA)
            try:
                p.stdin.write(small.tobytes())
            except BrokenPipeError:
                break  # ffmpeg mati duluan (mis. argumen salah)
    finally:
        cap.release()
    # Tutup stdin agar ffmpeg selesai encode, lalu ambil stderr.
    try:
        p.stdin.close()
    except (BrokenPipeError, ValueError):
        pass
    p.stdin = None  # cegah communicate() flush file yang sudah tutup
    _, err = p.communicate()
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg master gagal:\n{err.decode()[-800:]}")
    return str(out_path)


def render_clip(master_9x16, clip, words, style, out_path,
                grade="none", logo_path=None, logo_pos="top-right",
                fade=0.3, encoder="libx264", crf=20,
                sequence="none", hook_text=None, hook_duration=3.0):
    """Render 1 klip vertikal + caption karaoke burn-in + grade + logo + fade.

    Args:
        master_9x16: path master vertikal.
        clip: dict {"start","end",...} dalam detik.
        words: [{"word","start","end"}] dalam detik (waktu master).
        style: nama style di caption.STYLES.
        out_path: path mp4 output.
        grade: preset di GRADES ("none","warm","cool","vivid","cinematic","bw").
        logo_path: path PNG logo (None = tanpa logo). Logo >120px di-scale.
        logo_pos: "top-right"|"top-left"|"bottom-right"|"bottom-left".
        fade: durasi fade in/out detik (0 = mati).
        encoder: encoder ffmpeg. crf: kualitas (untuk libx264/libx265).
        sequence: nama sequence animasi caption di caption.SEQUENCES.
        hook_text: teks hook 0–hook_duration dtk (None/"" = mati).
        hook_duration: lama tampil hook (detik).
    """
    start = float(clip["start"])
    end = float(clip["end"])
    dur = end - start
    if dur <= 0:
        raise ValueError(f"durasi klip tidak valid: {start}-{end}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Filter kata yang overlap dengan klip, lalu offset ke waktu klip.
    sel = []
    for w in words:
        if w["end"] > start and w["start"] < end:
            sel.append({
                "word": w["word"],
                "start": max(0.0, w["start"] - start),
                "end": max(0.0, w["end"] - start),
            })
    sel.sort(key=lambda w: w["start"])

    # Rantai filter video: caption -> grade -> fade.
    chain = []
    if sel:
        ass_path = out_path.with_suffix(".ass")
        build_ass(sel, style_name=style, sequence_name=sequence or "none",
                  out_path=str(ass_path))
        ass_str = str(ass_path)
        if hook_text:
            from . import hook as hook_mod  # lazy: modul Fase 2
            ass_str = hook_mod.add_hook_text(ass_str, hook_text,
                                             duration=float(hook_duration or 3.0))
        chain.append(_escape_ass_path(ass_str))  # "ass='...'"
    g = GRADES.get(grade or "none")
    if g:
        chain.append(g)
    f = float(fade or 0)
    if f > 0 and dur > 0.2:
        f = min(f, dur / 2.0)
        chain.append(f"fade=t=in:st=0:d={f:.3f}")
        chain.append(f"fade=t=out:st={dur - f:.3f}:d={f:.3f}")
    vf = ",".join(chain)

    cmd = ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(master_9x16)]
    if logo_path and Path(logo_path).exists():
        # Overlay butuh filter_complex (2 input).
        pos = _LOGO_POS.get(logo_pos, _LOGO_POS["top-right"])
        base = vf if vf else "null"
        fc = (f"[0:v]{base},format=yuv420p[vmain];"
              f"[1:v]scale=w='min(iw,120)':h=-2[logo];"
              f"[vmain][logo]overlay={pos}[vout]")
        cmd += ["-i", str(logo_path),
                "-filter_complex", fc, "-map", "[vout]", "-map", "0:a?"]
    elif vf:
        cmd += ["-vf", vf]
    cmd += [*_video_codec_args(encoder, crf),
            "-pix_fmt", "yuv420p", "-c:a", "aac", str(out_path)]
    _ffmpeg(*cmd)
    return str(out_path)


def run_pipeline(src, outdir, provider=None, n_clips=5, style="Hype",
                 lang="id", progress=None,
                 grade="none", logo_path=None, logo_pos="top-right", fade=0.3,
                 sequence="none", hook_text=None, hook_duration=3.0):
    """Pipeline lengkap: probe → transcribe → faces → master → score → klip.

    Args:
        src: path video sumber.
        outdir: direktori artefak (master_9x16.mp4, transcript.json, clip_*.mp4).
        provider: AIProvider atau None (heuristic).
        progress: callback opsional progress(stage: str, frac: float).
        grade, logo_path, logo_pos, fade: diteruskan ke render_clip.
        sequence: sequence animasi caption (caption.SEQUENCES).
        hook_text: teks hook di awal klip (None/"" = mati).
        hook_duration: lama tampil hook (detik).

    Returns:
        {"master": path, "clips": [{"path","start","end","score","title"}],
         "segments": [...]}
    """
    try:
        from .score import score_moments
    except ImportError as e:
        raise RuntimeError(f"modul score belum tersedia: {e}")

    def _p(stage, frac):
        if progress:
            progress(stage, frac)

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    _p("probe", 0.02)
    info = probe(src)

    _p("transcribe", 0.05)
    segments = transcribe(str(src), lang=lang)
    _p("transcribe", 0.45)
    with open(outdir / "transcript.json", "w", encoding="utf-8") as f:
        json.dump({"source": info["path"], "segments": segments}, f,
                  ensure_ascii=False, indent=1)

    _p("faces", 0.47)
    from .faces import FaceTracker
    tracker = FaceTracker()
    bboxes, valid, confs, meta = tracker.track(str(src), sample_fps=5)
    res = tracker.crop_window(bboxes, valid,
                              src_w=info["width"], src_h=info["height"])
    crop_xs = res[0] if isinstance(res, tuple) else res
    _p("faces", 0.60)

    _p("master", 0.62)
    master = render_vertical_master(str(src), crop_xs,
                                    outdir / "master_9x16.mp4")
    _p("master", 0.80)

    _p("score", 0.82)
    clips = score_moments(segments, provider=provider, n=n_clips, lang=lang)
    _p("score", 0.85)

    words = [w for s in segments for w in s.get("words", [])]
    results = []
    for i, c in enumerate(clips):
        frac = 0.85 + 0.15 * (i + 1) / max(1, len(clips))
        _p(f"render clip {i + 1}/{len(clips)}", frac)
        # Clamp ke durasi master agar -t tidak overrun.
        c = dict(c)
        c["end"] = min(float(c["end"]), info["duration"])
        if c["end"] <= c["start"]:
            continue
        path = render_clip(master, c, words, style,
                           outdir / f"clip_{i + 1:02d}.mp4",
                           grade=grade, logo_path=logo_path,
                           logo_pos=logo_pos, fade=fade,
                           sequence=sequence, hook_text=hook_text,
                           hook_duration=hook_duration)
        results.append({"path": path, "start": c["start"], "end": c["end"],
                        "score": c.get("score", 0),
                        "title": c.get("title", "")})
    _p("selesai", 1.0)
    return {"master": master, "clips": results, "segments": segments}


if __name__ == "__main__":
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "testdata/test-video.mp4"
    out = sys.argv[2] if len(sys.argv) > 2 else "testdata/pipeline_out"
    # Smoke test ringan TANPA transcribe: pakai transkrip yang sudah ada.
    res = run_pipeline(src, out, provider=None, n_clips=2)
    print("master:", res["master"])
    for c in res["clips"]:
        print(f"- {c['path']} [{c['start']:.1f}-{c['end']:.1f}] {c['title']}")
