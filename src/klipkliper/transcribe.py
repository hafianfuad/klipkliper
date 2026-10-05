"""Transkripsi video memakai faster-whisper dengan word-level timestamps.

Fungsi utama:
    transcribe(video_path, model="small", lang="id") -> list[dict]
        Setiap segmen: {"start": float, "end": float, "text": str,
                        "words": [{"word": str, "start": float, "end": float}]}
"""
from faster_whisper import WhisperModel

# Kompatibilitas: beberapa build PyAV tidak punya kwarg `metadata_errors`
# yang dipakai faster-whisper>=1.2. Buang kwarg itu bila tidak didukung.
try:
    import av as _av

    _orig_open = _av.open

    def _open_compat(file, mode=None, **kwargs):
        kwargs.pop("metadata_errors", None)
        return _orig_open(file, mode=mode, **kwargs)

    _av.open = _open_compat
except Exception:
    pass


def _sanitize_proxy_env():
    """Buang entri no_proxy/NO_PROXY yang tak bisa di-parse httpx.

    Beberapa environment punya entri IPv6 dalam kurung seperti `[::1]`
    yang membuat httpx raise `InvalidURL: Invalid port` saat
    huggingface_hub memeriksa model. Fungsi ini menghapus entri
    ber-kurung tersebut; tidak berpengaruh di Windows.
    """
    import os
    for key in ("no_proxy", "NO_PROXY"):
        val = os.environ.get(key)
        if not val:
            continue
        clean = [p for p in val.split(",") if "[" not in p and "]" not in p]
        os.environ[key] = ",".join(clean)


def transcribe(video_path, model="small", lang="id", device="auto", compute_type="auto"):
    """Transkrip file video/audio.

    Args:
        video_path: path ke file video/audio.
        model: ukuran model whisper ("tiny","base","small","medium","large-v3").
        lang: kode bahasa ("id" untuk Indonesia).
        device: "auto" | "cpu" | "cuda".
        compute_type: "auto" | "int8" | "float16" | "float32".

    Returns:
        list segmen, tiap segmen dict {start, end, text, words:[{word,start,end}]}.
    """
    _sanitize_proxy_env()  # httpx gagal parse entri IPv6 bracket di no_proxy
    if device == "auto":
        try:
            import ctranslate2

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"

    mdl = WhisperModel(model, device=device, compute_type=compute_type)
    segments_iter, _info = mdl.transcribe(
        video_path,
        language=lang,
        word_timestamps=True,
        vad_filter=True,
    )

    out = []
    for seg in segments_iter:
        words = []
        for w in seg.words or []:
            words.append({"word": w.word, "start": float(w.start), "end": float(w.end)})
        out.append(
            {
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text.strip(),
                "words": words,
            }
        )
    return out


if __name__ == "__main__":
    import json
    import sys
    import time

    path = sys.argv[1] if len(sys.argv) > 1 else "testdata/test-video.mp4"
    model = sys.argv[2] if len(sys.argv) > 2 else "small"
    t0 = time.time()
    segs = transcribe(path, model=model)
    dt = time.time() - t0
    print(f"model={model} segments={len(segs)} time={dt:.1f}s")
    for s in segs:
        print(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}")
    json.dump(segs, open("testdata/test-transcript.json", "w"), ensure_ascii=False, indent=1)
