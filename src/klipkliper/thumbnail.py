"""Thumbnail generator — ekstrak frame via ffmpeg, render 5 template via PIL.

Template: breaking, bold, split, minimal, quote. Output 1280x720 JPG.
Font: DejaVuSans-Bold (/usr/share/fonts), fallback ImageFont.load_default().
"""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

W, H = 1280, 720
RED = (225, 29, 46)
DARK = (10, 10, 12)
WHITE = (255, 255, 255)
YELLOW = (255, 210, 40)

_TEMPLATES = ("breaking", "bold", "split", "minimal", "quote")

_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int):
    from PIL import ImageFont
    for p in _FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    """Wrap teks agar tiap baris muat dalam max_w piksel."""
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines or [""]


def _extract_frame(source_video: str, at_time: float, out_png: str) -> str:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg tidak ditemukan di PATH")
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", str(at_time),
           "-i", source_video, "-frames:v", "1",
           "-s", f"{W}x{H}", out_png]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not Path(out_png).exists():
        raise RuntimeError(f"gagal ekstrak frame: {r.stderr[-300:]}")
    return out_png


def _paste_logo(img, logo_path: str | None):
    if not logo_path:
        return
    from PIL import Image
    logo = Image.open(logo_path).convert("RGBA")
    tw = 140
    th = int(logo.height * tw / logo.width)
    logo = logo.resize((tw, th))
    img.paste(logo, (W - tw - 24, 24), logo)


def _template_breaking(img, draw, title: str):
    """Banner merah ala news di bawah + judul putih."""
    banner_h = 220
    draw.rectangle([0, H - banner_h, W, H], fill=RED)
    font = _font(64)
    lines = _wrap(draw, title, font, W - 120)
    y = H - banner_h + 30
    for ln in lines[:3]:
        draw.text((60, y), ln, font=font, fill=WHITE)
        y += 78


def _template_bold(img, draw, title: str):
    """Judul besar di tengah dengan outline hitam."""
    from PIL import Image
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 90))
    img.paste(overlay, (0, 0), overlay)
    font = _font(96)
    lines = _wrap(draw, title.upper(), font, W - 160)
    total = len(lines) * 112
    y = (H - total) // 2
    for ln in lines[:4]:
        lw = draw.textlength(ln, font=font)
        draw.text(((W - lw) / 2, y), ln, font=font, fill=YELLOW,
                  stroke_width=4, stroke_fill=(0, 0, 0))
        y += 112


def _template_split(img, draw, title: str):
    """Crop sepertiga kiri frame + panel warna + teks kanan."""
    from PIL import Image
    left = img.crop((0, 0, W // 3, H)).resize((426, H))
    base = Image.new("RGB", (W, H), DARK)
    base.paste(left, (0, 0))
    draw2 = __import__("PIL.ImageDraw", fromlist=["Draw"]).Draw(base)
    draw2.rectangle([426, 0, W, H], fill=(18, 18, 22))
    draw2.rectangle([426, 0, 440, H], fill=RED)
    font = _font(56)
    lines = _wrap(draw2, title, font, W - 426 - 120)
    y = 120
    for ln in lines[:6]:
        draw2.text((480, y), ln, font=font, fill=WHITE)
        y += 72
    return base


def _template_minimal(img, draw, title: str):
    """Gradasi gelap + teks kecil di bawah."""
    from PIL import Image, ImageDraw
    grad = Image.new("L", (1, H))
    for y in range(H):
        grad.putpixel((0, y), int(200 * (y / H) ** 1.5))
    black = Image.new("RGB", (W, H), (0, 0, 0))
    img.paste(Image.composite(black, img, grad.resize((W, H))))
    draw2 = ImageDraw.Draw(img)
    font = _font(44)
    lines = _wrap(draw2, title, font, W - 160)
    y = H - 60 - len(lines[:2]) * 58
    for ln in lines[:2]:
        draw2.text((80, y), ln, font=font, fill=WHITE)
        y += 58


def _template_quote(img, draw, title: str):
    """Tanda kutip besar + teks kutipan di tengah."""
    from PIL import Image
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 110))
    img.paste(overlay, (0, 0), overlay)
    qfont = _font(220)
    draw.text((80, 40), "\u201c", font=qfont, fill=RED)
    font = _font(60)
    lines = _wrap(draw, title, font, W - 320)
    y = 260
    for ln in lines[:5]:
        lw = draw.textlength(ln, font=font)
        draw.text(((W - lw) / 2, y), ln, font=font, fill=WHITE)
        y += 76


def generate(source_video: str, at_time: float, title: str,
             template: str = "breaking", out_path: str = "thumb.jpg",
             logo_path: str | None = None) -> str:
    """Buat thumbnail 1280x720 JPG dari frame video.

    Args:
        source_video: path video sumber.
        at_time: detik frame yang diambil.
        title: teks judul thumbnail.
        template: breaking|bold|split|minimal|quote.
        out_path: path JPG output.
        logo_path: path PNG logo (opsional, ditempel kanan-atas).

    Returns:
        str: path file JPG.
    """
    from PIL import Image, ImageDraw

    if template not in _TEMPLATES:
        raise ValueError(f"template '{template}' tidak dikenal: {_TEMPLATES}")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    frame_png = str(out.with_suffix(".frame.png"))
    _extract_frame(source_video, at_time, frame_png)
    img = Image.open(frame_png).convert("RGB").resize((W, H))
    draw = ImageDraw.Draw(img, "RGBA")

    if template == "breaking":
        _template_breaking(img, draw, title)
    elif template == "bold":
        _template_bold(img, draw, title)
    elif template == "split":
        img = _template_split(img, draw, title)
    elif template == "minimal":
        _template_minimal(img, draw, title)
    elif template == "quote":
        _template_quote(img, draw, title)

    _paste_logo(img, logo_path)
    img.save(str(out), "JPEG", quality=90)
    Path(frame_png).unlink(missing_ok=True)
    return str(out)


def list_templates() -> list[str]:
    return list(_TEMPLATES)


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.join(here, "..", "..")
    src = os.path.join(root, "testdata", "test-video.mp4")
    td = os.path.join(root, "testdata", "thumbs")
    for tpl in _TEMPLATES:
        p = generate(src, 10.0, "Rahasia AI yang Jarang Dibahas!",
                     template=tpl, out_path=os.path.join(td, f"thumb-{tpl}.jpg"))
        print("wrote", p)
    print("SMOKE thumbnail: LULUS")
