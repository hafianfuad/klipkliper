"""Worker QThread: analisis video & render klip. UI tidak pernah freeze."""
import inspect
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal


def _filtered_kwargs(func, options, mapping):
    """Ambil subset options yang didukung signature func.

    mapping: {kunci_ui: (nama_param_kandidat, ...)} — kandidat pertama
    yang ada di signature dipakai. Nilai None dilewati.
    """
    try:
        params = inspect.signature(func).parameters
    except Exception:
        return {}
    out = {}
    for key, candidates in mapping.items():
        val = options.get(key)
        if val is None:
            continue
        for cand in candidates:
            if cand in params:
                out[cand] = val
                break
    return out


# UI key -> kandidat nama param render_clip (Fase 2 E).
_RENDER_OPT_MAP = {
    "sequence": ("sequence", "sequence_name"),
    "grade": ("grade",),
    "logo_path": ("logo_path",),
    "hook_text": ("hook_text",),
}


class AnalyzeWorker(QThread):
    """Import → probe → transcribe → face track → crop → score.

    finished(dict): {"src","media","segments","clips","crop_xs","workdir"}
    """

    progress = Signal(str, float)  # (tahap, fraksi 0..1)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, source, is_url, cfg, n_clips=5, parent=None):
        super().__init__(parent)
        self.source = source
        self.is_url = is_url
        self.cfg = cfg
        self.n_clips = n_clips

    def run(self):
        try:
            from klipkliper import ingest, transcribe as tr_mod, faces as faces_mod, score as score_mod
            from klipkliper.providers import make_provider
        except Exception as e:
            self.error.emit(f"Modul inti belum tersedia: {e}")
            return
        try:
            workdir = Path(tempfile.mkdtemp(prefix="klipkliper_"))
            self.progress.emit("Mengambil media…", 0.05)
            if self.is_url:
                media = ingest.from_youtube(self.source, str(workdir))
            else:
                media = ingest.from_local(self.source, str(workdir))
            src = media["path"]

            self.progress.emit("Transkripsi…", 0.15)
            segments = tr_mod.transcribe(
                src, model=self.cfg.get("whisper_model", "small"),
                lang=self.cfg.get("lang", "id"))

            self.progress.emit("Lacak wajah…", 0.45)
            tracker = faces_mod.FaceTracker()
            bboxes, valid = tracker.track(src)
            crop_xs = tracker.crop_window(bboxes, valid, media["width"], media["height"])

            self.progress.emit("Memilih momen…", 0.75)
            provider = None
            pname = self.cfg.get("provider", "none")
            if pname != "none":
                provider = make_provider(
                    pname, api_key=self.cfg.get("api_key") or None,
                    model=self.cfg.get("model") or None)
            clips = score_mod.score_moments(
                segments, provider=provider, n=self.n_clips,
                lang=self.cfg.get("lang", "id"))

            self.progress.emit("Selesai", 1.0)
            self.finished.emit({
                "src": src, "media": media, "segments": segments,
                "clips": clips, "crop_xs": crop_xs, "workdir": str(workdir),
            })
        except Exception as e:
            self.error.emit(str(e))


class RenderWorker(QThread):
    """Render klip terpilih. Reuse master bila sudah ada (tidak duplikasi kerja).

    finished(list): [{"path","start","end","score","title"}]
    """

    progress = Signal(str, float)
    clip_done = Signal(dict)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, src, segments, clips, crop_xs, style, outdir,
                 parent=None, options=None):
        super().__init__(parent)
        self.src = src
        self.segments = segments
        self.clips = clips
        self.crop_xs = crop_xs
        self.style = style
        self.outdir = Path(outdir)
        # Opsi Fase 2: {"sequence","grade","logo_path","hook_text","voiceover"}.
        # Diteruskan ke render_clip hanya bila signature-nya mendukung
        # (kompatibel dengan modul render Fase 1 maupun Fase 2).
        self.options = dict(options or {})

    def run(self):
        try:
            from klipkliper import render as render_mod
        except Exception as e:
            self.error.emit(f"Modul render belum tersedia: {e}")
            return
        try:
            if hasattr(render_mod, "render_vertical_master") and hasattr(render_mod, "render_clip"):
                results = self._run_staged(render_mod)
            else:
                results = self._run_full(render_mod)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

    def _words(self):
        words = []
        for s in self.segments:
            words.extend(s.get("words", []))
        return words

    def _run_staged(self, render_mod):
        self.outdir.mkdir(parents=True, exist_ok=True)
        master = self.outdir / "master_9x16.mp4"
        if not master.exists():
            self.progress.emit("Render master 9:16…", 0.05)
            render_mod.render_vertical_master(self.src, self.crop_xs, str(master))
        words = self._words()
        results = []
        total = max(len(self.clips), 1)
        extra = _filtered_kwargs(render_mod.render_clip, self.options,
                                 _RENDER_OPT_MAP)
        if self.options.get("hook_text") and "hook_text" not in extra:
            self.progress.emit(
                "Catatan: modul render belum mendukung hook_text", 0.08)
        for i, clip in enumerate(self.clips):
            frac = 0.1 + 0.9 * (i / total)
            self.progress.emit(f"Render klip {i + 1}/{len(self.clips)}…", frac)
            out = self.outdir / f"clip_{i + 1:02d}.mp4"
            render_mod.render_clip(str(master), clip, words, self.style,
                                   str(out), **extra)
            self._maybe_voiceover(out, i, frac)
            item = {"path": str(out), "start": clip["start"], "end": clip["end"],
                    "score": clip.get("score", 0), "title": clip.get("title", "")}
            results.append(item)
            self.clip_done.emit(item)
            self.progress.emit(f"Klip {i + 1} jadi", 0.1 + 0.9 * ((i + 1) / total))
        return results

    def _maybe_voiceover(self, clip_path, idx, frac):
        """Campur voiceover hook ke klip bila dicentang (Fase 2 C).

        Dilewati dengan pesan bila modul voiceover belum tersedia —
        render klip tidak digagalkan.
        """
        vo_text = (self.options.get("hook_text") or "").strip()
        if not (self.options.get("voiceover") and vo_text):
            return
        try:
            from klipkliper import voiceover as vo_mod
        except Exception:
            self.progress.emit("Voiceover dilewati (modul belum tersedia)", frac)
            return
        try:
            vo_path = str(self.outdir / f"vo_{idx + 1:02d}.mp3")
            self.progress.emit("Sintesis voiceover…", frac)
            vo_mod.synthesize(vo_text, lang="id", out_path=vo_path)
            mixed = str(self.outdir / f"clip_{idx + 1:02d}_vo.mp4")
            self.progress.emit("Mix voiceover…", frac)
            vo_mod.mix_with_clip(str(clip_path), vo_path, mixed)
            os.replace(mixed, str(clip_path))
        except Exception as e:
            self.progress.emit(f"Voiceover gagal: {e}", frac)

    def _run_full(self, render_mod):
        # Fallback: pipeline penuh bila fungsi staged tak ada.
        from klipkliper.ui import settings as app_settings
        cfg = app_settings.load_settings()
        provider = app_settings.get_provider(cfg)
        self.progress.emit("Render pipeline penuh…", 0.1)
        extra = _filtered_kwargs(render_mod.run_pipeline, {
            "sequence": self.options.get("sequence"),
            "grade": self.options.get("grade"),
            "logo_path": self.options.get("logo_path"),
            "hook_text": self.options.get("hook_text"),
        }, _RENDER_OPT_MAP)
        res = render_mod.run_pipeline(
            self.src, str(self.outdir), provider=provider,
            n_clips=len(self.clips), style=self.style,
            progress=lambda s, f: self.progress.emit(s, f), **extra)
        return res.get("clips", [])


class QueueWorker(QThread):
    """Jalankan RenderQueue.run di thread terpisah.

    job_done(dict): tiap job yang statusnya menjadi "done".
    finished(): semua job selesai (atau antrean kosong).
    """

    progress = Signal(str, float)
    job_done = Signal(dict)
    finished = Signal()
    error = Signal(str)

    def __init__(self, queue, parent=None):
        super().__init__(parent)
        self.queue = queue

    def _statuses(self):
        try:
            return [j.get("status") for j in self.queue.list()]
        except Exception:
            return []

    def run(self):
        before = self._statuses()
        try:
            # queue.run memanggil callback sebagai (job, stage, frac).
            self.queue.run(
                lambda job, stage, frac: self.progress.emit(
                    f"{str(job.get('src', ''))[:40]} — {stage}",
                    float(frac or 0)))
        except Exception as e:
            self.error.emit(str(e))
            return
        try:
            jobs = list(self.queue.list())
            for idx, job in enumerate(jobs):
                old = before[idx] if idx < len(before) else None
                if old != "done" and job.get("status") == "done":
                    self.job_done.emit(dict(job))
        except Exception:
            pass
        self.finished.emit()


if __name__ == "__main__":
    # Smoke test: filter kwargs terhadap signature dummy.
    def _dummy(a, b, grade="none"):
        pass
    kw = _filtered_kwargs(_dummy, {"grade": "warm", "logo_path": None,
                                   "sequence": "pop"}, _RENDER_OPT_MAP)
    assert kw == {"grade": "warm"}, kw
    print("SMOKE worker: LULUS")


# ---------- publish Fase 3 ----------

class PublishWorker(QThread):
    """Publish / schedule / run-due di thread terpisah (UI tak freeze).

    mode="publish":  jobs=[{platform, video_path, title, description,
                            tags, extra{}}] → publisher.publish(...)
    mode="schedule": jobs=[{..., at_iso, extra{}}] → scheduler.schedule(...)
    mode="run_due":  kwargs dry_run → scheduler.run_due(publishers)

    job_done(dict): hasil per job. finished(): semua selesai.
    Modul klipkliper.publish.* di-import LAZY dengan pesan jelas.
    """

    progress = Signal(str, float)
    job_done = Signal(dict)
    finished = Signal()
    error = Signal(str)

    def __init__(self, mode, jobs=None, parent=None, dry_run=False):
        super().__init__(parent)
        self.mode = mode
        self.jobs = list(jobs or [])
        self.dry_run = dry_run

    # ----- helpers -----
    def _publisher(self, name):
        from klipkliper.ui.publish_common import get_publisher
        return get_publisher(name)

    def _scheduler(self):
        try:
            from klipkliper.publish.scheduler import Scheduler
        except Exception as e:
            raise RuntimeError(
                f"Modul publish.scheduler belum tersedia: {e}")
        return Scheduler()

    # ----- run -----
    def run(self):
        try:
            if self.mode == "publish":
                self._run_publish()
            elif self.mode == "schedule":
                self._run_schedule()
            elif self.mode == "run_due":
                self._run_due()
            else:
                raise RuntimeError(f"mode tak dikenal: {self.mode}")
        except Exception as e:
            self.error.emit(str(e)[:500])
            return
        self.finished.emit()

    def _run_publish(self):
        total = max(len(self.jobs), 1)
        for i, job in enumerate(self.jobs):
            plat = job["platform"]
            self.progress.emit(f"Posting ke {plat}…", i / total)
            try:
                pub = self._publisher(plat)
                res = pub.publish(
                    job["video_path"], job.get("title", ""),
                    description=job.get("description", ""),
                    tags=job.get("tags") or [],
                    dry_run=self.dry_run,
                    **(job.get("extra") or {}))
                self.job_done.emit({"platform": plat, "ok": True,
                                    "result": res,
                                    "video": job["video_path"]})
            except Exception as e:
                self.job_done.emit({"platform": plat, "ok": False,
                                    "error": str(e)[:300],
                                    "video": job["video_path"]})
            self.progress.emit(f"Selesai {i + 1}/{len(self.jobs)}",
                               (i + 1) / total)

    def _run_schedule(self):
        total = max(len(self.jobs), 1)
        sched = self._scheduler()
        for i, job in enumerate(self.jobs):
            plat = job["platform"]
            self.progress.emit(f"Menjadwalkan {plat}…", i / total)
            try:
                jid = sched.schedule(
                    plat, job["video_path"], job.get("title", ""),
                    job.get("description", ""), job["at_iso"],
                    tags=job.get("tags") or [], **(job.get("extra") or {}))
                self.job_done.emit({"platform": plat, "ok": True,
                                    "job_id": jid, "at": job["at_iso"],
                                    "video": job["video_path"]})
            except Exception as e:
                self.job_done.emit({"platform": plat, "ok": False,
                                    "error": str(e)[:300],
                                    "video": job["video_path"]})
            self.progress.emit(f"Selesai {i + 1}/{len(self.jobs)}",
                               (i + 1) / total)

    def _run_due(self):
        from klipkliper.ui import publish_common as pc
        sched = self._scheduler()
        pubs, skipped = {}, []
        for key, _label, _m, _c in pc.PLATFORMS:
            try:
                pubs[key] = self._publisher(key)
            except Exception as e:
                skipped.append(f"{key}: {e}")
        self.progress.emit("Menjalankan jadwal jatuh tempo…", 0.2)
        try:
            results = sched.run_due(pubs, dry_run=self.dry_run)
        except TypeError:
            # fallback bila signature run_due berbeda (tanpa dry_run)
            results = sched.run_due(pubs)
        for r in results or []:
            self.job_done.emit(dict(r) if isinstance(r, dict)
                               else {"result": str(r)})
        if skipped:
            self.progress.emit("Lewati: " + "; ".join(skipped)[:200], 1.0)
        else:
            self.progress.emit("Selesai", 1.0)
