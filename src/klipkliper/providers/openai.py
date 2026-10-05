"""Provider OpenAI (Chat Completions) untuk Klipkliper.

Jalur resmi: API key dari platform.openai.com
(OpenAI tidak menyediakan OAuth langganan ChatGPT ke pihak ketiga).
"""
from __future__ import annotations

import os
from typing import Optional

from .base import AIProvider  # noqa: F401 (re-export untuk konsistensi)
from .openai_compat import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    """OpenAI API, format Chat Completions standar."""

    name = "openai"
    BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, api_key: Optional[str] = None,
                 model: Optional[str] = None, timeout: int = 120,
                 base_url: Optional[str] = None):
        super().__init__(
            base_url=base_url or self.BASE_URL,
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            model=model or self.DEFAULT_MODEL,
            timeout=timeout,
        )


if __name__ == "__main__":
    # Smoke test tanpa jaringan.
    import requests

    calls = {}

    class _FakeResp:
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

        def raise_for_status(self):
            pass

    def _fake_post(url, headers=None, json=None, timeout=None):
        calls.update(url=url, headers=headers, body=json)
        return _FakeResp()

    _real = requests.post
    requests.post = _fake_post
    try:
        p = OpenAIProvider(api_key="sk-tes")
        assert p.chat([{"role": "user", "content": "halo"}]) == "ok"
        assert calls["url"] == "https://api.openai.com/v1/chat/completions"
        assert calls["body"]["model"] == "gpt-4o-mini"
        assert calls["headers"]["Authorization"] == "Bearer sk-tes"
        print("URL + model default + auth header: OK")
    finally:
        requests.post = _real
    print("SMOKE openai: LULUS")
