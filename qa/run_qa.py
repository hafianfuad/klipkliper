#!/usr/bin/env python3
"""QA harness Klipkliper: video masuk -> laporan lengkap + klip contoh.

Penggunaan:
    PYTHONPATH=src .venv/bin/python qa/run_qa.py <video.mp4> [--n 3] [--style Neon]

Output di qa/out-<nama>/ : report.md, klip mp4, thumbnail, frame contoh.
Pakai Groq (dari ~/.hermes/.env) bila tersedia, else heuristic.
"""
import json
import os
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC / "src"))

# Ambil GROQ_API_KEY dari ~/.hermes/.env bila ada (tanpa menampilkan nilainya)
_hermes_env = Path.home() / ".hermes" / ".env"
if _hermes_env.exists() and "GROQ_API_KEY" not in os.environ:
    for line in _hermes_env.read_text(errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("GROQ_API_KEY="):
            os.environ["GROQ_API_KEY"] = line.split("=", 1)[1].strip().strip("'\"")
            break

from klipkliper import render, thumbnail  # noqa: E402
from klipkliper.providers import make_provider  # noqa: E402


def main():
    if len(sys.argv) < 2:
        sys.exit("pakai: run_qa.py <video.mp4> [--n 3] [--style Neon]")
    src = Path(sys.argv[1])
    n = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 3
    style = sys.argv[sys.argv.index("--style") + 1] if "--style" in sys.argv else "Neon"

    outdir = Path("qa") / f"out-{src.stem}"
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    provider = None
    llm = "heuristic (tanpa LLM)"
    if os.environ.get("GROQ_API_KEY"):
        try:
            provider = make_provider("groq")
            llm = f"Groq ({provider.model})"
        except Exception as e:
            print(f"[!] Groq gagal dipakai: {e} -> fallback heuristic")

    log = []
    def progress(stage, frac):
        log.append(f"[{frac*100:5.1f}%] {stage}")
        print(log[-1], flush=True)

    res = render.run_pipeline(str(src), str(outdir), provider=provider,
                              n_clips=n, style=style, progress=progress)
    dt = time.time() - t0

    # Thumbnail tiap klip (template breaking, tengah klip)
    thumbs = []
    for c in res["clips"]:
        mid = (c["start"] + c["end"]) / 2
        tp = outdir / f"thumb-{Path(c['path']).stem}.jpg"
        try:
            thumbnail.generate(c["path"], 1.0, c["title"][:60], "breaking", str(tp))
            thumbs.append(str(tp))
        except Exception as e:
            thumbs.append(f"gagal: {e}")

    # Frame contoh tiap klip (tengah)
    import subprocess
    frames = []
    for c in res["clips"]:
        fp = outdir / f"frame-{Path(c['path']).stem}.png"
        mid = (c["end"] - c["start"]) / 2
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(mid),
                        "-i", c["path"], "-frames:v", "1", str(fp)],
                       check=False)
        frames.append(str(fp))

    segs = res["segments"]
    n_words = sum(len(s.get("words", [])) for s in segs)
    report = [
        "# QA Report Klipkliper", "",
        f"- Sumber: `{src}` ({src.stat().st_size/1e6:.1f} MB)",
        f"- Durasi pipeline: {dt:.0f} dtk | LLM: {llm}",
        f"- Transkrip: {len(segs)} segmen, {n_words} kata",
        f"- Klip: {len(res['clips'])}", "",
        "## Klip",
    ]
    for c, th in zip(res["clips"], thumbs):
        report += [f"- `{Path(c['path']).name}` [{c['start']:.1f}-{c['end']:.1f}] "
                   f"skor={c['score']:.0f} — {c['title']}"]
    report += ["", "## Contoh transkrip (3 segmen pertama)", ""]
    for s in segs[:3]:
        report += [f"- [{s['start']:.1f}-{s['end']:.1f}] {s['text']}"]
    report += ["", "## Log", "```"] + log + ["```"]
    (outdir / "report.md").write_text("\n".join(report))
    print(f"\nSELESAI -> {outdir}/report.md")


if __name__ == "__main__":
    main()
