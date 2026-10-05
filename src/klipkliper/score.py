"""Pilih momen terbaik dari transkrip untuk dijadikan klip vertikal.

Dua jalur:
- LLM (bila `provider` diberikan): minta AI memilih momen 20-90 detik,
  lalu validasi ketat (clamp durasi, buang overlap). Gagal -> heuristic.
- Heuristic (provider=None): sliding window + skor kata kunci Indonesia.

Tidak pernah raise untuk input valid.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .providers.base import AIProvider, ProviderError

# Batas durasi klip (detik) — sesuai kontrak API.md
CLIP_MIN = 20.0
CLIP_MAX = 90.0
DEFAULT_N = 5

# Clip = {"start": float, "end": float, "score": float 0..100,
#         "title": str, "reason": str}

# Kata kunci pemancing klik untuk heuristic (Indonesia)
_KEYWORDS = ("jangan", "rahasia", "gratis", "cara", "kenapa", "terbukti", "ai")
_WIN = 45.0   # lebar window heuristic (detik)
_STEP = 15.0  # langkah geser window (detik)


def _fmt_ts(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _parse_ts(val: Any) -> Optional[float]:
    """Terima angka atau string 'mm:ss' / 'hh:mm:ss' -> detik (float)."""
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        try:
            return float(s)  # "83.5"
        except ValueError:
            pass
        parts = s.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        if len(nums) == 2:  # mm:ss
            m, sec = nums
            return m * 60 + sec
        if len(nums) == 3:  # hh:mm:ss
            h, m, sec = nums
            return h * 3600 + m * 60 + sec
    return None


def _numbered_transcript(segments: List[Dict]) -> str:
    lines = []
    for s in segments:
        lines.append(f"[{_fmt_ts(s['start'])}-{_fmt_ts(s['end'])}] {s['text']}")
    return "\n".join(lines)


def _validate_clips(raw: Any, total: float, n: int) -> List[Dict]:
    """Validasi ketat output LLM: clamp, durasi, dedupe overlap >50%."""
    items = raw.get("clips") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise ProviderError("LLM: format JSON tak dikenal (butuh {\"clips\": [...]})")
    scored: List[Dict] = []
    for c in items:
        if not isinstance(c, dict):
            continue
        start = _parse_ts(c.get("start"))
        end = _parse_ts(c.get("end"))
        if start is None or end is None:
            continue
        # clamp ke durasi total
        start = max(0.0, min(start, total))
        end = max(0.0, min(end, total))
        if not start < end:
            continue
        dur = end - start
        if dur < CLIP_MIN or dur > CLIP_MAX:
            continue
        try:
            score = float(c.get("score", 50))
        except (TypeError, ValueError):
            score = 50.0
        score = max(0.0, min(100.0, score))
        scored.append({
            "start": round(start, 2),
            "end": round(end, 2),
            "score": round(score, 1),
            "title": str(c.get("title") or "Klip")[:80],
            "reason": str(c.get("reason") or "llm")[:200],
        })
    # urut skor menurun, buang overlap >50% (keep skor tertinggi)
    scored.sort(key=lambda c: c["score"], reverse=True)
    accepted: List[Dict] = []
    for c in scored:
        clash = False
        for a in accepted:
            ov = min(c["end"], a["end"]) - max(c["start"], a["start"])
            if ov > 0.5 * min(c["end"] - c["start"], a["end"] - a["start"]):
                clash = True
                break
        if not clash:
            accepted.append(c)
        if len(accepted) >= n:
            break
    return accepted[:n]


def _heuristic(segments: List[Dict], total: float, n: int) -> List[Dict]:
    """Sliding window 45 dtk / step 15 dtk + bonus kata kunci Indonesia."""
    if total <= 0:
        return []
    cands: List[Dict] = []
    t = 0.0
    while t < total:
        w0, w1 = t, min(t + _WIN, total)
        if w1 - w0 < CLIP_MIN:
            break
        texts = [s["text"] for s in segments
                 if s["end"] > w0 and s["start"] < w1]
        text = " ".join(texts)
        words = text.split()
        low = text.lower()
        base = len(words) / (w1 - w0) * 10.0          # kepadatan kata
        bonus = 2.0 * (text.count("?") + text.count("!"))
        bonus += 3.0 * sum(len(re.findall(rf"\b{re.escape(k)}\b", low))
                           for k in _KEYWORDS)
        bonus += 2.0 * len(re.findall(r"\d+", text))  # ada angka
        if len(words) < 10:                            # penalti window sepi
            base -= 25.0
        score = max(0.0, min(100.0, round(base + bonus, 1)))
        title = " ".join(words[:8]) or f"Momen {_fmt_ts(w0)}"
        cands.append({"start": round(w0, 2), "end": round(w1, 2),
                      "score": score, "title": title[:80], "reason": "heuristic"})
        t += _STEP
    # dedupe overlap seperti jalur LLM, urut skor menurun
    cands.sort(key=lambda c: c["score"], reverse=True)
    accepted: List[Dict] = []
    for c in cands:
        clash = False
        for a in accepted:
            ov = min(c["end"], a["end"]) - max(c["start"], a["start"])
            if ov > 0.5 * min(c["end"] - c["start"], a["end"] - a["start"]):
                clash = True
                break
        if not clash:
            accepted.append(c)
        if len(accepted) >= n:
            break
    return accepted[:n]


def score_moments(segments: List[Dict], provider: Optional[AIProvider] = None,
                  n: int = DEFAULT_N, lang: str = "id") -> List[Dict]:
    """Pilih <= n momen klip terbaik dari segmen transkrip.

    Args:
        segments: list {"start","end","text",...} (format transcribe.py).
        provider: AIProvider atau None (None -> heuristic murni).
        n: jumlah klip maksimal.
        lang: bahasa prompt LLM ("id" default).

    Returns:
        list Clip terurut skor menurun. Tidak pernah raise untuk input valid.
    """
    try:
        if not segments or n <= 0:
            return []
        total = float(segments[-1].get("end", 0) or 0)
        if total <= 0:
            return []
        if provider is not None:
            try:
                return _score_llm(segments, provider, total, n, lang)
            except Exception:
                pass  # jatuh ke heuristic
        return _heuristic(segments, total, n)
    except Exception:
        return []


def _score_llm(segments: List[Dict], provider: AIProvider,
               total: float, n: int, lang: str) -> List[Dict]:
    transcript = _numbered_transcript(segments)
    if lang == "id":
        system = (
            "Kamu editor video profesional. Dari transkrip bernomor di bawah, "
            f"pilih maksimal {n} momen TERBAIK untuk klip vertikal. Setiap klip "
            f"berdurasi {int(CLIP_MIN)}-{int(CLIP_MAX)} detik. Utamakan: hook kuat, "
            "insight mengejutkan, tips praktis, atau pernyataan kontroversial. "
            'Jawab HANYA JSON: {"clips": [{"start": detik (angka), '
            '"end": detik (angka), "title": "judul singkat", '
            '"reason": "alasan singkat", "score": 0-100}]}.'
        )
        user = (f"Durasi total video: {total:.0f} detik ({_fmt_ts(total)}).\n\n"
                f"Transkrip:\n{transcript}")
    else:
        system = (
            "You are a professional video editor. From the numbered transcript "
            f"below, pick at most {n} BEST moments for vertical clips. Each clip "
            f"lasts {int(CLIP_MIN)}-{int(CLIP_MAX)} seconds. "
            'Reply ONLY JSON: {"clips": [{"start": seconds, "end": seconds, '
            '"title": "short title", "reason": "short reason", "score": 0-100}]}.'
        )
        user = (f"Total video duration: {total:.0f} seconds ({_fmt_ts(total)}).\n\n"
                f"Transcript:\n{transcript}")
    raw = provider.chat_json([{"role": "system", "content": system},
                              {"role": "user", "content": user}])
    clips = _validate_clips(raw, total, n)
    if not clips:
        raise ProviderError("LLM: tidak ada klip valid dari respons.")
    return clips


if __name__ == "__main__":
    import json as _json

    from .providers.base import AIProvider as _AIProvider

    # --- bangun transkrip sintetis ~3 menit dengan keyword ---
    _kalimat = [
        "Halo semuanya selamat datang kembali di channel ini.",
        "Hari ini kita bahas rahasia AI yang jarang dibahas orang.",
        "Kenapa AI kadang jawabannya ngaco tapi pede banget? Kita bedah.",
        "Pertama kamu harus paham cara kerja model bahasa ini.",
        "Model itu dilatih membaca jutaan teks dari internet setiap hari.",
        "Lalu dia belajar menebak kata berikutnya dengan probabilitas.",
        "Jadi waktu kamu bertanya dia sebenarnya sedang menebak jawaban.",
        "Itulah kenapa halusinasi AI bisa terjadi kapan saja bro.",
        "Tapi jangan salah ada cara supaya hasilnya jauh lebih akurat.",
        "Kuncinya ada di prompt yang kamu tulis dengan sangat jelas.",
        "Makin spesifik instruksimu makin bagus output yang keluar.",
        "Contohnya begini saya kasih prompt gratis buat kamu coba.",
        "Tuliskan peran konteks format dan contoh sebelum bertanya.",
        "Teknik ini terbukti menaikkan kualitas jawaban sampai tujuh puluh persen.",
        "Banyak orang tidak tahu trik sederhana tapi powerful ini.",
        "Oke itu tips pertama sekarang kita lanjut ke tips kedua.",
        "Tips kedua adalah selalu verifikasi fakta penting dari AI.",
        "Jangan telan mentah-mentah apalagi untuk data angka dan tanggal.",
        "Cross check dengan sumber resmi sebelum kamu publikasikan.",
        "Nah sekarang bagian paling seru yaitu studi kasus nyata.",
        "Seorang kreator memakai AI untuk riset dan hemat tiga jam sehari.",
        "Bayangkan tiga jam sehari dikali tiga puluh hari lumayan banget.",
        "Itu sebabnya AI bukan pengganti tapi pengali produktivitas.",
        "Sekian video kali ini jangan lupa subscribe dan sampai jumpa.",
    ]
    _segs, _t = [], 0.0
    for k in _kalimat:
        _d = 6.0 + (len(k) % 5)
        _segs.append({"start": _t, "end": _t + _d, "text": k, "words": []})
        _t += _d + 1.0
    _total = _t
    print(f"transkrip sintetis: {len(_segs)} segmen, {_total:.0f} detik")

    # TES 1: provider=None -> heuristic
    klip = score_moments(_segs, provider=None, n=5)
    assert klip, "heuristic harus menghasilkan klip"
    assert all(k["end"] - k["start"] >= CLIP_MIN for k in klip)
    assert all(k["reason"] == "heuristic" for k in klip)
    assert [k["score"] for k in klip] == sorted([k["score"] for k in klip], reverse=True)
    print("TES 1 heuristic (provider=None): OK")
    for k in klip:
        print(f"  [{_fmt_ts(k['start'])}-{_fmt_ts(k['end'])}] skor={k['score']} {k['title'][:45]}")

    # TES 2: mock provider -> jalur LLM + validasi clamp/overlap
    class _Mock(_AIProvider):
        name = "mock"

        def chat(self, messages, json_mode=False):
            return _json.dumps({"clips": [
                # overlap dengan klip-1, skor lebih rendah -> harus dibuang
                {"start": -5, "end": 30, "title": "Awal", "reason": "hook", "score": 90},
                {"start": 10, "end": 40, "title": "Overlap", "reason": "x", "score": 70},
                # di luar durasi total -> clamp lalu gugur (start>=end)
                {"start": 500, "end": 600, "title": "Jauh", "reason": "x", "score": 99},
                # format string mm:ss -> harus diparse
                {"start": "02:00", "end": "03:00", "title": "String TS", "reason": "x", "score": 80},
                # terlalu pendek -> gugur
                {"start": 50, "end": 55, "title": "Pendek", "reason": "x", "score": 95},
                # skor >100 -> clamp ke 100
                {"start": 60, "end": 100, "title": "Skor gede", "reason": "x", "score": 150},
            ]})

    klip2 = score_moments(_segs, provider=_Mock(), n=5)
    titles = [k["title"] for k in klip2]
    assert "Awal" in titles and "Overlap" not in titles, titles       # overlap dibuang
    assert "Jauh" not in titles and "Pendek" not in titles, titles   # gugur
    assert "String TS" in titles, titles                              # mm:ss diparse
    sg = next(k for k in klip2 if k["title"] == "Skor gede")
    assert sg["score"] == 100.0, sg                                   # clamp skor
    awal = next(k for k in klip2 if k["title"] == "Awal")
    assert awal["start"] == 0.0, awal                                 # clamp start
    assert [k["score"] for k in klip2] == sorted([k["score"] for k in klip2], reverse=True)
    print("TES 2 mock LLM (clamp + overlap + mm:ss): OK")
    for k in klip2:
        print(f"  [{_fmt_ts(k['start'])}-{_fmt_ts(k['end'])}] skor={k['score']} {k['title']}")

    # TES 3: LLM gagal -> fallback heuristic, tidak raise
    class _Rusak(_AIProvider):
        name = "rusak"

        def chat(self, messages, json_mode=False):
            raise ProviderError("boom")

    klip3 = score_moments(_segs, provider=_Rusak(), n=3)
    assert klip3 and all(k["reason"] == "heuristic" for k in klip3)
    print("TES 3 LLM gagal -> fallback heuristic: OK")

    # TES 4: input kosong -> [] tanpa raise
    assert score_moments([], provider=None) == []
    assert score_moments(_segs, provider=None, n=0) == []
    print("TES 4 input kosong: OK")

    print("SMOKE score: LULUS")
