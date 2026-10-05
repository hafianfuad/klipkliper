"""Klipkliper caption engine — build subtitle ASS dengan karaoke highlight per kata.

Alur: list kata {word, start, end} (detik, dari transkrip faster-whisper)
  -> build_ass() -> file .ass -> ffmpeg -vf ass=... (burn-in via libass)

Spike C membuktikan: highlight kuning sinkron dengan timing kata (±0.1 dtk),
tidak ada error libass. Fase 2A: 31 gaya + 8 sequence animasi.

CATATAN KOMPATIBILITAS
----------------------
Style "Hype" dan "Clean" DIBEKUKAN — definisinya tidak boleh diubah.
Field baru pada style bersifat opsional dengan default yang membuat
_style_line("Hype"/"Clean") byte-identical dengan versi lama:
  italic=False, border_style=1, back_color="&H80000000", prefix_tags="",
  line_words=4. build_ass(words, "Hype") dengan sequence "none" dan
avoid_face=False menghasilkan Dialogue & Style line yang identik
(hanya section [V4+ Styles] bertambah karena ada 29 style baru).

CARA MENAMBAH STYLE BARU
-------------------------
Tambahkan 1 entry ke dict STYLES. Key = nama style. Field wajib sama seperti
"Hype"; field opsional:

  {
      "italic": False,            # opsional, default False
      "border_style": 1,          # 1 = outline+shadow biasa, 3 = box background
      "back_color": "&H80000000", # warna box bila border_style=3 (&HAABBGGRR)
      "prefix_tags": "",          # blok override mentah di awal tiap event,
                                  # mis. r"{\\blur1}" untuk efek neon glow
      "line_words": 4,            # maks kata per baris caption
  }

Font: nama font PRIMER adalah font bawaan Windows (render target).
Di Linux dev, fontconfig/libass otomatis fallback (umumnya ke DejaVu Sans)
sehingga verifikasi tetap jalan. Font primer tiap style ditulis di komentar.

SEQUENCES (8 animasi, via tag override ASS per event — tanpa plugin):
---------------------------------------------------------------
Lihat dict SEQUENCES untuk deskripsi tiap efek. Dipakai via
build_ass(..., sequence_name="pop"). "typewriter" membangun event
per kata (tanpa karaoke sweep) mengikuti timing ucap.
"""

from __future__ import annotations

PLAYRES_X = 608
PLAYRES_Y = 1080

# Kalimat dipotong di tanda baca ini, atau maksimal MAX_WORDS_PER_EVENT kata.
SENT_END = (".", "!", "?")
MAX_WORDS_PER_EVENT = 8
MAX_WORDS_PER_LINE = 4

# avoid_face=True menaikkan caption bawah sebesar ini (px).
AVOID_FACE_LIFT = 200

STYLES = {
    # === DIBEKUKAN (jangan diubah) ===
    "Hype": {
        "fontname": "DejaVu Sans",
        "fontsize": 64,
        "bold": True,
        "primary": "&H0000FFFF",      # kuning — highlight kata aktif
        "secondary": "&H00FFFFFF",    # putih — teks dasar
        "outline_color": "&H00000000",
        "outline": 3,                # outline hitam tebal
        "shadow": 1,
        "alignment": 2,              # bawah-tengah
        "margin_v": 120,
        "karaoke": True,
    },
    "Clean": {
        "fontname": "DejaVu Sans",
        "fontsize": 64,
        "bold": True,
        "primary": "&H00FFFFFF",
        "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 1,                # outline tipis
        "shadow": 0,
        "alignment": 2,
        "margin_v": 120,
        "karaoke": False,            # tidak ada tag \kf
    },
    # === 29 gaya baru (Fase 2A). Komentar = font primer Windows. ===
    # 1. Neon — glow cyan (primer: Arial Black)
    "Neon": {
        "fontname": "Arial Black", "fontsize": 60, "bold": True,
        "primary": "&H0000FFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00FFFF00",  # outline cyan
        "outline": 2, "shadow": 0, "alignment": 2, "margin_v": 120,
        "karaoke": True, "prefix_tags": r"{\blur1}",
    },
    # 2. Fire — highlight oranye, outline tebal (primer: Impact)
    "Fire": {
        "fontname": "Impact", "fontsize": 68, "bold": False,
        "primary": "&H000080FF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 3, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 3. Mint — highlight hijau mint (primer: Trebuchet MS)
    "Mint": {
        "fontname": "Trebuchet MS", "fontsize": 62, "bold": True,
        "primary": "&H0088FF00", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 2, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 4. Candy — highlight pink (primer: Verdana)
    "Candy": {
        "fontname": "Verdana", "fontsize": 60, "bold": True,
        "primary": "&H00B469FF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 2, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 5. Aqua — highlight cyan, outline tipis (primer: Arial)
    "Aqua": {
        "fontname": "Arial", "fontsize": 62, "bold": True,
        "primary": "&H00FFFF00", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 1, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 6. TopHype — hype di posisi atas (primer: Arial Black)
    "TopHype": {
        "fontname": "Arial Black", "fontsize": 60, "bold": True,
        "primary": "&H0000FFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 3, "shadow": 1, "alignment": 8, "margin_v": 90,
        "karaoke": True,
    },
    # 7. TopClean — bersih di posisi atas (primer: Arial)
    "TopClean": {
        "fontname": "Arial", "fontsize": 60, "bold": True,
        "primary": "&H00FFFFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 2, "shadow": 1, "alignment": 8, "margin_v": 90,
        "karaoke": False,
    },
    # 8. CenterPop — tengah layar, cocok untuk sequence pop (primer: Trebuchet MS)
    "CenterPop": {
        "fontname": "Trebuchet MS", "fontsize": 66, "bold": True,
        "primary": "&H0000FFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 3, "shadow": 2, "alignment": 5, "margin_v": 0,
        "karaoke": True,
    },
    # 9. Box — background box hitam opaque (primer: Arial Black)
    "Box": {
        "fontname": "Arial Black", "fontsize": 56, "bold": True,
        "primary": "&H0000FFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 1, "shadow": 0, "alignment": 2, "margin_v": 120,
        "karaoke": True, "border_style": 3, "back_color": "&HC0000000",
    },
    # 10. BoxTop — box di posisi atas (primer: Arial)
    "BoxTop": {
        "fontname": "Arial", "fontsize": 56, "bold": True,
        "primary": "&H0000FFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 1, "shadow": 0, "alignment": 8, "margin_v": 90,
        "karaoke": True, "border_style": 3, "back_color": "&HC0000000",
    },
    # 11. Minimal — tanpa outline, bayangan halus (primer: Arial)
    "Minimal": {
        "fontname": "Arial", "fontsize": 58, "bold": False,
        "primary": "&H00FFFFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 0, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": False,
    },
    # 12. Serif — italic elegan (primer: Georgia)
    "Serif": {
        "fontname": "Georgia", "fontsize": 60, "bold": False, "italic": True,
        "primary": "&H0000D7FF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 2, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 13. Impact — huruf raksasa gaya meme (primer: Impact)
    "Impact": {
        "fontname": "Impact", "fontsize": 76, "bold": False,
        "primary": "&H0000FFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 3, "shadow": 1, "alignment": 2, "margin_v": 110,
        "karaoke": True, "line_words": 3,
    },
    # 14. News — lower-third berita (primer: Arial Black)
    "News": {
        "fontname": "Arial Black", "fontsize": 54, "bold": True,
        "primary": "&H00FFFFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 1, "shadow": 0, "alignment": 2, "margin_v": 100,
        "karaoke": False, "border_style": 3, "back_color": "&H1E0000AA",
    },
    # 15. Mono — terminal/hacker (primer: Courier New)
    "Mono": {
        "fontname": "Courier New", "fontsize": 56, "bold": True,
        "primary": "&H0000FF00", "secondary": "&H0000FF00",
        "outline_color": "&H00000000",
        "outline": 1, "shadow": 0, "alignment": 2, "margin_v": 120,
        "karaoke": True, "border_style": 3, "back_color": "&HF0000000",
    },
    # 16. Soft — lembut tanpa karaoke (primer: Verdana)
    "Soft": {
        "fontname": "Verdana", "fontsize": 58, "bold": False,
        "primary": "&H00FFFFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 1, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": False,
    },
    # 17. Titan — extra bold raksasa (primer: Arial Black)
    "Titan": {
        "fontname": "Arial Black", "fontsize": 72, "bold": True,
        "primary": "&H00FFFFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 4, "shadow": 1, "alignment": 2, "margin_v": 110,
        "karaoke": True, "line_words": 3,
    },
    # 18. Edge — outline super tebal, tanpa bayangan (primer: Tahoma)
    "Edge": {
        "fontname": "Tahoma", "fontsize": 62, "bold": True,
        "primary": "&H00FFFF00", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 4, "shadow": 0, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 19. LongShadow — bayangan panjang dramatis (primer: Trebuchet MS)
    "LongShadow": {
        "fontname": "Trebuchet MS", "fontsize": 64, "bold": True,
        "primary": "&H00FFFFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 1, "shadow": 3, "alignment": 2, "margin_v": 120,
        "karaoke": False,
    },
    # 20. Retro — nuansa 70-an (primer: Impact)
    "Retro": {
        "fontname": "Impact", "fontsize": 68, "bold": False,
        "primary": "&H000080FF", "secondary": "&H00FFF0D0",
        "outline_color": "&H00000050",
        "outline": 3, "shadow": 2, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 21. Ocean — highlight biru (primer: Arial)
    "Ocean": {
        "fontname": "Arial", "fontsize": 62, "bold": True,
        "primary": "&H00FF8000", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 2, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 22. Lime — highlight hijau terang (primer: Impact)
    "Lime": {
        "fontname": "Impact", "fontsize": 66, "bold": False,
        "primary": "&H0032CD32", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 2, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 23. Rose — pink elegan di tengah (primer: Georgia)
    "Rose": {
        "fontname": "Georgia", "fontsize": 60, "bold": False, "italic": True,
        "primary": "&H00B469FF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 2, "shadow": 1, "alignment": 5, "margin_v": 0,
        "karaoke": False,
    },
    # 24. Gold — highlight emas mewah (primer: Arial Black)
    "Gold": {
        "fontname": "Arial Black", "fontsize": 62, "bold": True,
        "primary": "&H0000D7FF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 3, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 25. Ghost — transparan halus (primer: Arial)
    "Ghost": {
        "fontname": "Arial", "fontsize": 58, "bold": False,
        "primary": "&H33FFFFFF", "secondary": "&H33FFFFFF",
        "outline_color": "&H00000000",
        "outline": 0, "shadow": 0, "alignment": 2, "margin_v": 120,
        "karaoke": False, "prefix_tags": r"{\blur1}",
    },
    # 26. Caption — gaya subtitle YouTube klasik (primer: Arial)
    "Caption": {
        "fontname": "Arial", "fontsize": 56, "bold": False,
        "primary": "&H00FFFFFF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 2, "shadow": 1, "alignment": 2, "margin_v": 90,
        "karaoke": False,
    },
    # 27. KaraokePro — sweep hijau tegas (primer: Trebuchet MS)
    "KaraokePro": {
        "fontname": "Trebuchet MS", "fontsize": 62, "bold": True,
        "primary": "&H0000FF00", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 2, "shadow": 1, "alignment": 2, "margin_v": 120,
        "karaoke": True,
    },
    # 28. Stamp — cap merah di atas (primer: Impact)
    "Stamp": {
        "fontname": "Impact", "fontsize": 64, "bold": False,
        "primary": "&H000000FF", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 3, "shadow": 1, "alignment": 8, "margin_v": 90,
        "karaoke": True,
    },
    # 29. Chill — santai di tengah (primer: Tahoma)
    "Chill": {
        "fontname": "Tahoma", "fontsize": 58, "bold": False,
        "primary": "&H00FFFF00", "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "outline": 1, "shadow": 1, "alignment": 5, "margin_v": 0,
        "karaoke": False,
    },
}

# 8 sequence animasi caption (nilai = deskripsi efek visual).
SEQUENCES = {
    "none": "Tanpa animasi — caption langsung tampil penuh selama event.",
    "pop": "Scale 50% -> 100% dalam 150ms pertama (efek muncul meletup).",
    "fade": "Fade in/out 150ms di awal dan akhir event.",
    "slide_up": "Teks meluncur dari 70px di bawah ke posisi normal dalam 250ms.",
    "typewriter": "Kata muncul satu per satu mengikuti timing ucap "
                  "(tanpa karaoke sweep); tiap kata menjadi event sendiri.",
    "bounce": "Scale 70% -> 112% -> 100% (efek memantul).",
    "glow": "Neon pulse: blur 2 -> 1 selama 700ms pertama.",
    "wave": "Teks mengambang naik-turun halus (gelombang vertikal).",
}

_ASS_HEADER = """[Script Info]
Title: Klipkliper Karaoke
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {rx}
PlayResY: {ry}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}
"""


def list_styles() -> list[str]:
    """Daftar nama style (31), urutan: Hype, Clean, lalu 29 gaya Fase 2A."""
    return list(STYLES.keys())


def list_sequences() -> list[str]:
    """Daftar nama sequence animasi (8)."""
    return list(SEQUENCES.keys())


def _ass_time(sec: float) -> str:
    """Detik -> format ASS H:MM:SS.cc (centiseconds)."""
    cs = int(round(sec * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _escape(text: str) -> str:
    return text.replace("{", "\\{").replace("}", "\\}")


def _style_line(name: str, d: dict) -> str:
    bold = -1 if d.get("bold") else 0
    italic = -1 if d.get("italic", False) else 0
    return (
        f"Style: {name},{d['fontname']},{d['fontsize']},"
        f"{d['primary']},{d['secondary']},{d['outline_color']},"
        f"{d.get('back_color', '&H80000000')},"
        f"{bold},{italic},0,0,100,100,0,0,{d.get('border_style', 1)},"
        f"{d['outline']},{d['shadow']},{d['alignment']},20,20,{d['margin_v']},1"
    )


def group_sentences(words: list[dict], max_words: int = MAX_WORDS_PER_EVENT) -> list[list[dict]]:
    """Gabung kata menjadi event per kalimat (potong di tanda baca / maks kata)."""
    events, cur = [], []
    for w in sorted(words, key=lambda x: x["start"]):
        cur.append(w)
        if w["word"].rstrip().endswith(SENT_END) or len(cur) >= max_words:
            events.append(cur)
            cur = []
    if cur:
        events.append(cur)
    return events


def _karaoke_text(words: list[dict], line_words: int = MAX_WORDS_PER_LINE) -> str:
    """Bangun teks event dengan tag \\kf per kata + wrap maks line_words/baris.

    Durasi \\kf dihitung sampai kata BERIKUTNYA mulai, sehingga highlight
    tiap kata mulai tepat di start-nya (sinkron by construction).
    """
    lines, line = [], []
    n = len(words)
    for i, w in enumerate(words):
        if i < n - 1:
            dur_cs = max(1, int(round((words[i + 1]["start"] - w["start"]) * 100)))
        else:
            dur_cs = max(1, int(round((w["end"] - w["start"]) * 100)))
        line.append("{\\kf%d}%s" % (dur_cs, _escape(w["word"])))
        if len(line) >= line_words or i == n - 1:
            lines.append(" ".join(line))
            line = []
    return "\\N".join(lines)


def _plain_text(words: list[dict], line_words: int = MAX_WORDS_PER_LINE) -> str:
    lines, line = [], []
    n = len(words)
    for i, w in enumerate(words):
        line.append(_escape(w["word"]))
        if len(line) >= line_words or i == n - 1:
            lines.append(" ".join(line))
            line = []
    return "\\N".join(lines)


def _seq_anchor(style: dict) -> tuple[int, int]:
    """Perkiraan posisi jangkar teks (x, y) dari alignment + margin_v style.

    Dipakai sequence slide_up/wave yang butuh koordinat absolut.
    Untuk \\an2, y = garis bawah teks (PlayResY - margin_v).
    """
    a = style["alignment"]
    mv = style["margin_v"]
    cx = PLAYRES_X // 2
    if a in (1, 2, 3):
        y = PLAYRES_Y - mv
    elif a in (4, 5, 6):
        y = PLAYRES_Y // 2
    else:
        y = mv
    return cx, y


def _seq_prefix(sequence_name: str, style: dict) -> str:
    """Blok tag override ASS untuk sequence (ditempel di awal teks event)."""
    if sequence_name == "pop":
        return r"{\fscx50\fscy50\t(0,150,\fscx100\fscy100)}"
    if sequence_name == "fade":
        return r"{\fad(150,150)}"
    if sequence_name == "slide_up":
        cx, y = _seq_anchor(style)
        return "{\\move(%d,%d,%d,%d,0,250)}" % (cx, y + 70, cx, y)
    if sequence_name == "bounce":
        return r"{\fscx70\fscy70\t(0,130,\fscx112\fscy112)\t(130,320,\fscx100\fscy100)}"
    if sequence_name == "glow":
        return r"{\t(0,350,\blur2)\t(350,700,\blur1)}"
    if sequence_name == "wave":
        cx, y = _seq_anchor(style)
        return "{\\t(0,450,\\pos(%d,%d))\\t(450,900,\\pos(%d,%d))}" % (cx, y - 14, cx, y)
    return ""


def _typewriter_events(words: list[dict]) -> list[tuple[float, float, str]]:
    """Event per kata untuk sequence typewriter: tiap kata muncul di start-nya.

    Tanpa karaoke sweep — timing event per kata yang menjadi efeknya.
    """
    ws = sorted(words, key=lambda x: x["start"])
    out = []
    n = len(ws)
    for i, w in enumerate(ws):
        start = w["start"]
        nxt = ws[i + 1]["start"] if i + 1 < n else w["end"] + 0.4
        end = min(w["end"] + 0.35, nxt - 0.03)
        if end <= start:
            end = start + 0.10
        out.append((start, end, _escape(w["word"])))
    return out


def build_ass(words: list[dict], style_name: str = "Hype", sequence_name: str = "none",
              out_path: str | None = None, avoid_face: bool = False) -> str:
    """Bangun subtitle ASS dari list kata.

    Args:
        words: [{word: str, start: float, end: float}] — detik.
        style_name: key di STYLES (31 gaya).
        sequence_name: key di SEQUENCES (8 animasi); default "none"
            menjaga kompatibilitas output lama.
        out_path: bila diisi, tulis file dan kembalikan path; jika tidak,
            kembalikan string ASS.
        avoid_face: bila True dan style berposisi bawah (alignment 1/2/3),
            MarginV event dinaikkan sebesar AVOID_FACE_LIFT agar caption
            tidak menutupi wajah di tengah-tengah bawah.

    Returns:
        str: isi ASS (bila out_path None) atau path file (bila out_path diisi).
    """
    if style_name not in STYLES:
        raise ValueError(f"style '{style_name}' tidak dikenal. Pilihan: {list(STYLES)}")
    if sequence_name not in SEQUENCES:
        raise ValueError(f"sequence '{sequence_name}' tidak dikenal. Pilihan: {list(SEQUENCES)}")
    style = STYLES[style_name]
    line_words = style.get("line_words", MAX_WORDS_PER_LINE)
    style_prefix = style.get("prefix_tags", "")

    # MarginV override per event (0 = pakai margin style).
    margin_v = 0
    if avoid_face and style["alignment"] in (1, 2, 3):
        margin_v = min(style["margin_v"] + AVOID_FACE_LIFT, 720)

    dialogue = []
    if sequence_name == "typewriter":
        # Tiap kata jadi event sendiri; karaoke style diabaikan by design.
        for start, end, text in _typewriter_events(words):
            dialogue.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},"
                f"{style_name},,0,0,{margin_v},,{text}"
            )
    else:
        seq = _seq_prefix(sequence_name, style)
        events = group_sentences(words)
        starts = [ev[0]["start"] for ev in events]
        for i, ev in enumerate(events):
            start = ev[0]["start"]
            end = ev[-1]["end"] + 0.4
            if i + 1 < len(starts):
                end = min(end, starts[i + 1] - 0.05)
            body = _karaoke_text(ev, line_words) if style["karaoke"] else _plain_text(ev, line_words)
            dialogue.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},"
                f"{style_name},,0,0,{margin_v},,{seq}{style_prefix}{body}"
            )

    ass = _ASS_HEADER.format(
        rx=PLAYRES_X,
        ry=PLAYRES_Y,
        styles="\n".join(_style_line(nm, st) for nm, st in STYLES.items()),
        events="\n".join(dialogue),
    )
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(ass)
        return out_path
    return ass


def sample_words() -> list[dict]:
    """3 kalimat Bahasa Indonesia (~16 dtk) dengan word timing sintetis realistis."""
    return [
        # Kalimat 1 (0.5 – 3.4)
        {"word": "Halo", "start": 0.50, "end": 0.80},
        {"word": "semuanya,", "start": 0.85, "end": 1.40},
        {"word": "selamat", "start": 1.50, "end": 2.00},
        {"word": "datang", "start": 2.05, "end": 2.50},
        {"word": "di", "start": 2.55, "end": 2.70},
        {"word": "Klipkliper.", "start": 2.75, "end": 3.40},
        # Kalimat 2 (5.5 – 11.0) — 11 kata, akan pecah jadi 2 event (8+3)
        {"word": "Aplikasi", "start": 5.50, "end": 6.00},
        {"word": "ini", "start": 6.05, "end": 6.30},
        {"word": "mengubah", "start": 6.40, "end": 7.00},
        {"word": "video", "start": 7.05, "end": 7.50},
        {"word": "panjang", "start": 7.55, "end": 8.10},
        {"word": "menjadi", "start": 8.20, "end": 8.70},
        {"word": "klip", "start": 8.75, "end": 9.10},
        {"word": "vertikal", "start": 9.15, "end": 9.70},
        {"word": "yang", "start": 9.75, "end": 10.00},
        {"word": "siap", "start": 10.05, "end": 10.35},
        {"word": "upload.", "start": 10.40, "end": 11.00},
        # Kalimat 3 (11.5 – 15.8)
        {"word": "Kecerdasan", "start": 11.50, "end": 12.20},
        {"word": "buatan", "start": 12.25, "end": 12.80},
        {"word": "memilih", "start": 12.90, "end": 13.50},
        {"word": "momen", "start": 13.55, "end": 14.10},
        {"word": "terbaik", "start": 14.15, "end": 14.70},
        {"word": "secara", "start": 14.75, "end": 15.10},
        {"word": "otomatis.", "start": 15.15, "end": 15.80},
    ]


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    td = os.path.join(here, "..", "..", "testdata")
    os.makedirs(td, exist_ok=True)
    print(f"styles: {len(STYLES)}, sequences: {len(SEQUENCES)}")
    words = sample_words()
    for style in ("Hype", "Clean"):
        p = build_ass(words, style_name=style,
                      out_path=os.path.join(td, f"spike_c_ass_{style.lower()}.ass"))
        print("wrote", p)
