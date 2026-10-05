"""Batch render queue Klipkliper.

Antrean job render yang tahan restart: state tersimpan di `queue.json`
di workdir. `pause()` menghentikan antar-job (tidak di tengah ffmpeg).

Contoh:
    q = RenderQueue("kerjaan/batch1")
    q.add({"src": "video.mp4", "outdir": "kerjaan/batch1/job1",
           "n_clips": 3, "style": "Hype", "grade": "cinematic"})
    q.run(progress_cb=lambda job, stage, frac: print(job["id"], stage, frac))

Job dict:
    {"src":..., "outdir":..., "n_clips":..., "style":..., "lang":...,
     "grade":..., "logo_path":..., "logo_pos":..., "fade":...,
     "sequence":..., "hook_text":...,
     "id":..., "status": "queued|running|done|failed|paused",
     "error":..., "result":..., "created_at":..., "started_at":...,
     "finished_at":...}

Catatan: `sequence`/`hook_text` disimpan & dipersist, tapi baru dipakai
saat modul Fase 2A (caption sequence) / 2B (hook) tersedia. Queue saat ini
menjalankan tiap job via `run_pipeline(provider=None)` — mode heuristic
tanpa LLM (provider object tidak bisa diserialisasi ke JSON).
"""
import copy
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

STATUSES = ("queued", "running", "done", "failed", "paused")

# Key job yang diteruskan ke run_pipeline sebagai kwargs.
_PIPELINE_KEYS = ("n_clips", "style", "lang", "grade",
                  "logo_path", "logo_pos", "fade",
                  "sequence", "hook_text", "hook_duration")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RenderQueue:
    """Antrean batch job render."""

    def __init__(self, workdir):
        self.workdir = Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        self._file = self.workdir / "queue.json"
        self._lock = threading.Lock()
        self._paused = False
        self._running = False
        self._jobs = []
        self._load()

    # ---------- persistensi ----------

    def _load(self):
        """Baca queue.json bila ada; job 'running' dianggap 'queued' lagi
        (proses sebelumnya mati di tengah jalan)."""
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return  # file rusak -> mulai kosong, jangan crash
        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        for j in jobs:
            if j.get("status") == "running":
                j["status"] = "queued"
                j["error"] = "proses sebelumnya terhenti; diantre ulang"
        self._jobs = jobs
        self._paused = bool(data.get("paused", False))

    def _save(self):
        """Tulis atomik (tmp + rename). Panggil dengan lock dipegang."""
        tmp = self._file.with_suffix(".json.tmp")
        payload = {"paused": self._paused, "jobs": self._jobs}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, self._file)

    # ---------- operasi ----------

    def add(self, job: dict) -> str:
        """Tambah job, kembalikan id. Wajib ada 'src' dan 'outdir'."""
        if not isinstance(job, dict):
            raise TypeError("job harus dict")
        if not job.get("src"):
            raise ValueError("job butuh 'src'")
        if not job.get("outdir"):
            raise ValueError("job butuh 'outdir'")
        if not Path(job["src"]).exists():
            raise ValueError(f"src tidak ada: {job['src']}")
        jid = uuid4().hex[:8]
        entry = {
            "id": jid,
            "status": "queued",
            "error": None,
            "result": None,
            "created_at": _now(),
            "started_at": None,
            "finished_at": None,
        }
        entry.update({k: v for k, v in job.items() if k != "id"})
        with self._lock:
            self._jobs.append(entry)
            self._save()
        return jid

    def list(self) -> list:
        """Salinan daftar job (aman dimutasi pemanggil)."""
        with self._lock:
            return copy.deepcopy(self._jobs)

    def get(self, job_id: str):
        with self._lock:
            for j in self._jobs:
                if j["id"] == job_id:
                    return copy.deepcopy(j)
        return None

    def remove(self, job_id: str) -> bool:
        """Hapus job (tidak boleh yang sedang running)."""
        with self._lock:
            for i, j in enumerate(self._jobs):
                if j["id"] == job_id:
                    if j["status"] == "running":
                        return False
                    del self._jobs[i]
                    self._save()
                    return True
        return False

    def pause(self):
        """Jeda: job yang belum jalan jadi 'paused'. Berhenti antar-job,
        tidak memotong ffmpeg yang sedang berjalan."""
        with self._lock:
            self._paused = True
            for j in self._jobs:
                if j["status"] == "queued":
                    j["status"] = "paused"
            self._save()

    def resume(self):
        """Lanjutkan: job 'paused' kembali 'queued'."""
        with self._lock:
            self._paused = False
            for j in self._jobs:
                if j["status"] == "paused":
                    j["status"] = "queued"
            self._save()

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def clear_done(self) -> int:
        """Hapus job berstatus done. Kembalikan jumlah yang dihapus."""
        with self._lock:
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if j["status"] != "done"]
            removed = before - len(self._jobs)
            if removed:
                self._save()
            return removed

    # ---------- eksekusi ----------

    def run(self, progress_cb=None) -> list:
        """Jalankan job 'queued' satu per satu via run_pipeline.

        progress_cb(job: dict, stage: str, frac: float) opsional.
        Mengembalikan ringkasan [{id, status, error}]. Thread-safe untuk
        pause()/resume() dari thread lain di sela job.
        """
        from .render import run_pipeline  # lazy: hindari circular import

        with self._lock:
            if self._running:
                raise RuntimeError("queue sudah berjalan")
            self._running = True

        summary = []
        try:
            while True:
                with self._lock:
                    if self._paused:
                        break
                    job = next((j for j in self._jobs
                                if j["status"] == "queued"), None)
                    if job is None:
                        break
                    job["status"] = "running"
                    job["started_at"] = _now()
                    job["error"] = None
                    self._save()
                    jid = job["id"]

                # Eksekusi di luar lock agar pause()/list() tetap responsif.
                def _prog(stage, frac, _j=job):
                    if progress_cb:
                        try:
                            progress_cb(copy.deepcopy(_j), stage, frac)
                        except Exception:
                            pass

                try:
                    kwargs = {k: job[k] for k in _PIPELINE_KEYS if k in job}
                    res = run_pipeline(job["src"], job["outdir"],
                                       provider=None, progress=_prog,
                                       **kwargs)
                    result = {
                        "master": res.get("master"),
                        "clips": [c["path"] for c in res.get("clips", [])],
                    }
                    err, status = None, "done"
                except Exception as e:  # noqa: BLE001 - simpan error per job
                    result, err, status = None, str(e)[-500:], "failed"

                with self._lock:
                    for j in self._jobs:
                        if j["id"] == jid:
                            j["status"] = status
                            j["error"] = err
                            j["result"] = result
                            j["finished_at"] = _now()
                            break
                    self._save()
                summary.append({"id": jid, "status": status, "error": err})
        finally:
            with self._lock:
                self._running = False
        return summary


if __name__ == "__main__":
    import sys
    q = RenderQueue(sys.argv[1] if len(sys.argv) > 1 else "testdata/qdemo")
    print("job di queue:", len(q.list()))
    for j in q.list():
        print(f"- {j['id']} [{j['status']}] {j.get('src')}")
