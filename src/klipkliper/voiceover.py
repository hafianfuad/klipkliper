"""Voiceover Bahasa Indonesia via edge-tts + mixing ke klip dengan ducking.

Voice default:
- id-ID-ArdiNeural (pria) — default bila lang="id" dan voice=None
- id-ID-GadisNeural (wanita) — alternatif, pass via param `voice`

Contoh:
    synthesize("Halo semuanya!", lang="id", out_path="vo.mp3")
    synthesize("Halo semuanya!", voice="id-ID-GadisNeural", out_path="vo.mp3")

Butuh internet (edge-tts memanggil layanan Microsoft). Gagal -> VoiceoverError.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DEFAULT_VOICES = {
    "id": "id-ID-ArdiNeural",   # alternatif: "id-ID-GadisNeural"
    "en": "en-US-GuyNeural",
}


class VoiceoverError(Exception):
    """Gagal sintesis / mixing voiceover."""


def synthesize(text: str, lang: str = "id", voice: str | None = None,
               out_path: str = "voiceover.mp3") -> str:
    """Sintesis teks menjadi file audio (mp3).

    Args:
        text: teks yang diucapkan.
        lang: kode bahasa ("id" default).
        voice: nama voice edge-tts; bila None pakai default per lang.
        out_path: path file output.

    Returns:
        str: path file audio.

    Raises:
        VoiceoverError: bila edge-tts tak terinstal atau sintesis gagal.
    """
    try:
        import edge_tts
    except ImportError:
        raise VoiceoverError("edge-tts belum terinstal: pip install edge-tts")

    voice = voice or DEFAULT_VOICES.get(lang, "id-ID-ArdiNeural")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    import asyncio

    async def _run():
        comm = edge_tts.Communicate(text, voice)
        await comm.save(str(out))

    try:
        asyncio.run(_run())
    except Exception as e:
        raise VoiceoverError(f"gagal sintesis voiceover ({voice}): {e}")
    if not out.exists() or out.stat().st_size == 0:
        raise VoiceoverError("file voiceover kosong setelah sintesis")
    return str(out)


def _ffprobe_streams(path: str) -> list[dict]:
    import json
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", path],
        capture_output=True, text=True)
    if r.returncode != 0:
        return []
    return json.loads(r.stdout).get("streams", [])


def _duration(path: str) -> float:
    import json
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path], capture_output=True, text=True)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def mix_with_clip(clip_path: str, vo_path: str, out_path: str,
                  vo_volume: float = 1.0, duck: float = 0.25) -> str:
    """Campur voiceover di atas audio klip dengan ducking.

    Audio asli klip diturunkan ke level `duck` (dengan ramp 0.3 dtk agar
    tidak "klik") selama voiceover berbunyi (mulai t=0), lalu kembali normal.
    Bila klip tidak punya audio, voiceover menjadi audio utama.

    Args:
        clip_path: video klip sumber.
        vo_path: file audio voiceover (mulai di t=0).
        out_path: path video output.
        vo_volume: gain voiceover.
        duck: level audio asli selama voiceover (0.0–1.0).

    Returns:
        str: path output.
    """
    if shutil.which("ffmpeg") is None:
        raise VoiceoverError("ffmpeg tidak ditemukan di PATH")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    has_audio = any(s.get("codec_type") == "audio"
                    for s in _ffprobe_streams(clip_path))
    if not has_audio:
        # Voiceover jadi satu-satunya audio; video di-copy.
        cmd = ["ffmpeg", "-y", "-i", clip_path, "-i", vo_path,
               "-map", "0:v", "-map", "1:a",
               "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise VoiceoverError(f"ffmpeg gagal (tanpa audio asli): {r.stderr[-500:]}")
        return str(out)

    dv = _duration(vo_path)
    ramp = min(0.3, dv / 3) if dv > 0 else 0.3
    drop = 1.0 - duck
    # Volume automation: turun ke `duck` selama 0..dv (ramp di kedua ujung).
    expr = (
        f"if(lt(t,{ramp:.3f}),1-{drop:.3f}*t/{ramp:.3f},"
        f"if(lt(t,{dv - ramp:.3f}),{duck:.3f},"
        f"if(lt(t,{dv:.3f}),{duck:.3f}+{drop:.3f}*(t-{dv:.3f}+{ramp:.3f})/{ramp:.3f},1)))"
    )
    filt = (
        f"[0:a]volume='{expr}':eval=frame[ducked];"
        f"[1:a]volume={vo_volume}[vo];"
        f"[ducked][vo]amix=inputs=2:duration=first:dropout_transition=0[aout]"
    )
    cmd = ["ffmpeg", "-y", "-i", clip_path, "-i", vo_path,
           "-filter_complex", filt, "-map", "0:v", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise VoiceoverError(f"ffmpeg gagal saat mixing: {r.stderr[-800:]}")
    return str(out)


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    td = os.path.join(here, "..", "..", "testdata")
    os.makedirs(td, exist_ok=True)
    # Smoke test mixing saja (tanpa internet): vo palsu dari sine tone.
    vo = os.path.join(td, "vo_fake.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=2",
                    "-c:a", "libmp3lame", vo], check=True)
    clip = os.path.join(td, "mix_clip_src.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=blue:s=608x1080:d=5:r=30",
                    "-f", "lavfi", "-i", "sine=frequency=220:duration=5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", clip], check=True)
    out = mix_with_clip(clip, vo, os.path.join(td, "mix_clip_out.mp4"))
    streams = _ffprobe_streams(out)
    assert any(s.get("codec_type") == "audio" for s in streams), "audio hilang"
    assert any(s.get("codec_type") == "video" for s in streams), "video hilang"
    print("SMOKE mix_with_clip: LULUS ->", out)
