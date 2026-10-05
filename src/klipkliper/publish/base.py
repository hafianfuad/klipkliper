"""Base class publisher Klipkliper (autopost ke platform video).

Pola mengikuti `providers/base.py`: ABC + error dengan hint aksi user.
Semua publisher WAJIB mendukung `dry_run=True` (validasi + bangun request
tanpa mengirim) agar bisa dites tanpa akun.
"""
from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional


class PublishError(Exception):
    """Error publish dengan hint aksi untuk user."""

    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.hint = hint

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base}\nHint: {self.hint}" if self.hint else base


class Publisher(abc.ABC):
    """Interface publisher ke satu platform."""

    name: str = "base"

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """True bila token/kredensial ada (belum tentu valid)."""

    @abc.abstractmethod
    def authorize_flow(self) -> str:
        """Kembalikan URL authorize / keterangan langkah user (teks)."""

    @abc.abstractmethod
    def publish(self, video_path: str, title: str, description: str = "",
                tags: Optional[List[str]] = None, dry_run: bool = False,
                **kw) -> Dict[str, Any]:
        """Posting video. Return {"id":..., "url":...}.

        dry_run=True -> return {"dry_run": True, "request": {...}} tanpa kirim.
        """

    def refresh_if_needed(self) -> None:
        """Refresh token bila didukung. Default: tidak melakukan apa-apa."""


__all__ = ["Publisher", "PublishError"]
