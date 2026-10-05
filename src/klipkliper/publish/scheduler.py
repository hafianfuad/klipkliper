"""Scheduler posting Klipkliper.

Menyimpan jadwal di `~/.klipkliper/schedule.json` (atomic write, tahan restart).
Jalankan yang jatuh tempo via CLI: `klipkliper.cli publish run-due`
(atau cron/systemd timer di mesin user).
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CONFIG_DIR = Path.home() / ".klipkliper"
DEFAULT_PATH = CONFIG_DIR / "schedule.json"

STATUS_QUEUED = "queued"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


def _parse_at(at_iso: str) -> datetime:
    """Parse 'YYYY-MM-DD HH:MM[:SS]' (atau dengan 'T'). Naive = waktu lokal."""
    s = at_iso.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Format waktu tidak dikenal: {at_iso!r}. "
        "Pakai 'YYYY-MM-DD HH:MM' (contoh: '2026-10-06 18:00').")


def _now_local() -> datetime:
    return datetime.now().astimezone().replace(tzinfo=None)


class Scheduler:
    """Antrean jadwal posting."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self._lock = threading.Lock()
        self._jobs: List[Dict[str, Any]] = []
        self._load()

    # ---- persistensi ----

    def _load(self) -> None:
        if not self.path.exists():
            self._jobs = []
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._jobs = data if isinstance(data, list) else []
        except (OSError, ValueError):
            self._jobs = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._jobs, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    # ---- CRUD ----

    def schedule(self, platform: str, video_path: str, title: str,
                 description: str = "", at_iso: str = "",
                 **kw) -> str:
        """Tambah jadwal. Return job_id (8 hex)."""
        if not at_iso:
            raise ValueError("Parameter --at wajib diisi ('YYYY-MM-DD HH:MM').")
        at = _parse_at(at_iso)  # validasi format di sini
        if not Path(video_path).exists():
            raise ValueError(f"File video tidak ada: {video_path}")
        job = {
            "id": secrets.token_hex(4),
            "platform": (platform or "youtube").lower(),
            "video_path": str(video_path),
            "title": title,
            "description": description or "",
            "at": at.strftime("%Y-%m-%d %H:%M"),
            "status": STATUS_QUEUED,
            "created": _now_local().strftime("%Y-%m-%d %H:%M"),
            "attempts": 0,
            "last_error": None,
            "extra": dict(kw),  # tags, privacy, dll — diteruskan ke publish()
        }
        with self._lock:
            self._jobs.append(job)
            self._save()
        return job["id"]

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(j) for j in self._jobs]

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for j in self._jobs:
                if j["id"] == job_id:
                    return dict(j)
        return None

    def cancel(self, job_id: str) -> bool:
        """Hapus jadwal. Return True bila ketemu."""
        with self._lock:
            before = len(self._jobs)
            self._jobs = [j for j in self._jobs if j["id"] != job_id]
            if len(self._jobs) != before:
                self._save()
                return True
        return False

    def due(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Job berstatus queued dengan waktu <= now."""
        now = now or _now_local()
        with self._lock:
            return [dict(j) for j in self._jobs
                    if j["status"] == STATUS_QUEUED
                    and _parse_at(j["at"]) <= now]

    def mark_done(self, job_id: str, result: Optional[Dict] = None) -> None:
        with self._lock:
            for j in self._jobs:
                if j["id"] == job_id:
                    j["status"] = STATUS_DONE
                    j["last_error"] = None
                    if result:
                        j["result"] = {"id": result.get("id"),
                                       "url": result.get("url")}
                    self._save()
                    return

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._lock:
            for j in self._jobs:
                if j["id"] == job_id:
                    j["status"] = STATUS_FAILED
                    j["attempts"] = j.get("attempts", 0) + 1
                    j["last_error"] = str(error)[:500]
                    self._save()
                    return

    # ---- eksekusi ----

    def run_due(self, publishers: Dict[str, Any],
                dry_run: bool = False) -> List[Dict[str, Any]]:
        """Posting semua job yang jatuh tempo. Return list hasil per job."""
        results = []
        for job in self.due():
            pub = publishers.get(job["platform"])
            if pub is None:
                self.mark_failed(job["id"],
                                 f"publisher '{job['platform']}' tidak tersedia")
                results.append({"job_id": job["id"], "ok": False,
                                "error": "publisher tidak tersedia"})
                continue
            try:
                extra = job.get("extra") or {}
                res = pub.publish(job["video_path"], job["title"],
                                  job.get("description", ""),
                                  tags=extra.pop("tags", None),
                                  dry_run=dry_run, **extra)
                self.mark_done(job["id"], res if not dry_run else None)
                results.append({"job_id": job["id"], "ok": True,
                                "result": res})
            except Exception as e:  # noqa: BLE001 — catat & lanjut job berikut
                self.mark_failed(job["id"], str(e))
                results.append({"job_id": job["id"], "ok": False,
                                "error": str(e)})
        return results


if __name__ == "__main__":
    # Smoke test dengan path sementara (tidak menyentuh ~/.klipkliper).
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "sched.json"
    s = Scheduler(tmp)

    class FakePub:
        name = "youtube"
        def publish(self, video_path, title, description="", tags=None,
                    dry_run=False, **kw):
            assert dry_run is True
            return {"dry_run": True, "title": title}

    v = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
    j1 = s.schedule("youtube", v, "Due Job", at_iso="2020-01-01 00:00")
    j2 = s.schedule("youtube", v, "Future 1", at_iso="2099-01-01 00:00")
    j3 = s.schedule("youtube", v, "Future 2", at_iso="2099-06-01 00:00")
    assert len(s.due()) == 1 and s.due()[0]["id"] == j1, "due() harus 1 job"
    res = s.run_due({"youtube": FakePub()}, dry_run=True)
    assert len(res) == 1 and res[0]["ok"], f"run_due: {res}"
    assert s.get(j1)["status"] == "done"
    assert s.cancel(j2) is True and s.get(j2) is None
    assert len(s.list()) == 2  # j1 done + j3 queued
    s2 = Scheduler(tmp)  # reload dari file
    assert len(s2.list()) == 2 and s2.get(j3)["status"] == "queued"
    s.mark_failed(j3, "boom")
    assert s.get(j3)["status"] == "failed"
    print("scheduler: SEMUA OK (due/run_due/cancel/reload/mark_failed)")
