"""Interface provider AI untuk Klipkliper.

Semua provider (Gemini OAuth, Claude API key, OpenAI API key,
OpenAI-compatible, ...) mengimplementasikan interface ini supaya
modul pemilih-momen (score.py) tidak peduli AI apa yang dipakai.
"""
from __future__ import annotations

import abc
import json
from typing import Any, Dict, List, Optional


# Format pesan standar: list of {"role": ..., "content": ...}
# role: "system" | "user" | "assistant"
Message = Dict[str, str]


class AIProvider(abc.ABC):
    """Kontrak minimal setiap provider AI."""

    name: str = "base"

    @abc.abstractmethod
    def chat(self, messages: List[Message], json_mode: bool = False) -> str:
        """Kirim percakapan, kembalikan teks respons model.

        Args:
            messages: list {"role": "system"|"user"|"assistant", "content": str}.
            json_mode: True -> minta model menjawab JSON valid
                (dipakai pemilih-momen untuk skor H/S/D terstruktur).

        Returns:
            Teks jawaban model (sudah digabung dari semua parts).

        Raises:
            ProviderError: untuk semua kegagalan (auth, jaringan, API).
        """
        raise NotImplementedError

    def chat_json(self, messages: List[Message]) -> Any:
        """Helper: chat dengan json_mode lalu parse hasilnya."""
        raw = self.chat(messages, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProviderError(f"{self.name}: respons bukan JSON valid: {e}\nIsi: {raw[:500]}")


class ProviderError(Exception):
    """Error dari provider AI. `hint` berisi saran aksi untuk user."""

    def __init__(self, message: str, hint: Optional[str] = None):
        super().__init__(message)
        self.hint = hint

    def __str__(self) -> str:
        base = super().__str__()
        return f"{base}\nSaran: {self.hint}" if self.hint else base
