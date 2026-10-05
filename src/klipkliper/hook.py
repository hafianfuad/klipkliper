"""Hook/teaser text — sisipkan 1 event ASS detik 0–duration dengan style "Hook".

Dipakai sebelum burn-in: teks hook (mis. "JANGAN SKIP!") tampil besar di
atas selama beberapa detik pertama klip, tanpa karaoke.
"""

from __future__ import annotations

from pathlib import Path

from . import caption
from .caption import _ass_time, _escape, _style_line

HOOK_STYLE = {
    "fontname": "DejaVu Sans",
    "fontsize": 80,               # besar, untuk kanvas 608x1080
    "bold": True,
    "primary": "&H0000FFFF",      # kuning — warna aksen
    "secondary": "&H0000FFFF",
    "outline_color": "&H00000000",  # outline hitam
    "outline": 4,
    "shadow": 2,
    "alignment": 8,               # atas-tengah
    "margin_v": 60,               # jarak dari atas (px)
    "karaoke": False,             # tanpa highlight per kata
}

HOOK_MAX_WORDS_PER_LINE = 4


def ensure_hook_style() -> str:
    """Daftarkan style "Hook" ke caption.STYLES bila belum ada.

    Definisi tunggal ada di sini (HOOK_STYLE) — tidak diduplikat di caption.py.
    """
    if "Hook" not in caption.STYLES:
        caption.STYLES["Hook"] = HOOK_STYLE
    return "Hook"


def _wrap_hook(text: str) -> str:
    words = text.split()
    lines, line = [], []
    for w in words:
        line.append(_escape(w))
        if len(line) >= HOOK_MAX_WORDS_PER_LINE:
            lines.append(" ".join(line))
            line = []
    if line:
        lines.append(" ".join(line))
    return "\\N".join(lines)


def add_hook_text(ass_path: str, hook_text: str, duration: float = 3.0) -> str:
    """Sisipkan event hook 0–duration ke file ASS yang sudah ada.

    Args:
        ass_path: path file .ass (hasil caption.build_ass).
        hook_text: teks hook, mis. "JANGAN SKIP!".
        duration: lama tampil hook (detik).

    Returns:
        str: path file ASS baru ("<nama>_hook.ass").
    """
    ensure_hook_style()
    src = Path(ass_path)
    text = src.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 1. Sisipkan definisi Style Hook setelah baris "Style:" terakhir.
    style_line = _style_line("Hook", HOOK_STYLE)
    last_style = max(i for i, ln in enumerate(lines) if ln.startswith("Style:"))
    lines.insert(last_style + 1, style_line)

    # 2. Sisipkan Dialogue hook (layer 2 = di atas karaoke layer 0)
    #    tepat sebelum Dialogue pertama.
    hook_line = (
        f"Dialogue: 2,{_ass_time(0)},{_ass_time(duration)},"
        f"Hook,,0,0,0,,{_wrap_hook(hook_text)}"
    )
    first_dialogue = next(
        i for i, ln in enumerate(lines) if ln.startswith("Dialogue:")
    )
    lines.insert(first_dialogue, hook_line)

    out = src.with_name(f"{src.stem}_hook.ass")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)


if __name__ == "__main__":
    import os
    from .caption import build_ass, sample_words

    here = os.path.dirname(os.path.abspath(__file__))
    td = os.path.join(here, "..", "..", "testdata")
    os.makedirs(td, exist_ok=True)
    base = build_ass(sample_words(), style_name="Hype",
                     out_path=os.path.join(td, "hook_base.ass"))
    hooked = add_hook_text(base, "JANGAN SKIP VIDEO INI!", duration=3.0)
    print("wrote", hooked)
    txt = open(hooked, encoding="utf-8").read()
    assert "Style: Hook," in txt, "style Hook hilang"
    assert "Dialogue: 2,0:00:00.00,0:00:03.00,Hook," in txt, "event hook hilang"
    print("SMOKE hook: LULUS")
