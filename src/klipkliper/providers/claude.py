"""Provider Claude (Anthropic Messages API) untuk Klipkliper.

Jalur resmi: API key dari console.anthropic.com
(Anthropic tidak menyediakan OAuth pihak ketiga).
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import requests

from .base import AIProvider, Message, ProviderError
from .openai_compat import _hint_for_status

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-5"


class ClaudeProvider(AIProvider):
    """Messages API: header x-api-key + anthropic-version."""

    name = "claude"

    def __init__(self, api_key: Optional[str] = None,
                 model: str = DEFAULT_MODEL, timeout: int = 120,
                 max_tokens: int = 2048):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens

    def chat(self, messages: List[Message], json_mode: bool = False) -> str:
        if not self.api_key:
            raise ProviderError(
                f"{self.name}: API key belum diisi.",
                hint="Isi ANTHROPIC_API_KEY atau dapatkan key di console.anthropic.com.",
            )
        # Messages API: "system" dipisah ke field sendiri.
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        convo = [{"role": m["role"], "content": m["content"]}
                 for m in messages if m["role"] in ("user", "assistant")]
        if json_mode:
            # Messages API tidak punya response_format -> instruksi eksplisit.
            system_parts.append("Balas HANYA dengan JSON valid, tanpa teks lain.")
        body: Dict = {"model": self.model, "max_tokens": self.max_tokens,
                      "messages": convo}
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        try:
            resp = requests.post(
                API_URL,
                headers={"x-api-key": self.api_key,
                         "anthropic-version": API_VERSION,
                         "Content-Type": "application/json"},
                json=body, timeout=self.timeout)
            resp.raise_for_status()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            detail = ""
            try:
                detail = str(e.response.json())[:300]
            except Exception:
                pass
            raise ProviderError(f"{self.name}: HTTP {status}. {detail}",
                                hint=_hint_for_status(status))
        except requests.Timeout:
            raise ProviderError(f"{self.name}: request timeout ({self.timeout}s).")
        except requests.RequestException as e:
            raise ProviderError(f"{self.name}: jaringan bermasalah: {e}")
        try:
            data = resp.json()
            texts = [b.get("text", "") for b in data.get("content", [])
                     if b.get("type") == "text"]
            return "".join(texts)
        except (KeyError, TypeError, ValueError) as e:
            raise ProviderError(f"{self.name}: respons tak terduga: {e}")


if __name__ == "__main__":
    # Smoke test tanpa jaringan.
    calls = {}

    class _FakeResp:
        def __init__(self, payload, status=200):
            self._payload = payload
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                err = requests.HTTPError(f"HTTP {self.status_code}")
                err.response = self
                raise err

        def json(self):
            return self._payload

    def _fake_post(url, headers=None, json=None, timeout=None):
        calls.update(url=url, headers=headers, body=json)
        return _FakeResp({"content": [{"type": "text", "text": '{"a": 1}'}]})

    _real = requests.post
    requests.post = _fake_post
    try:
        p = ClaudeProvider(api_key="sk-ant-tes")
        out = p.chat([{"role": "system", "content": "kamu editor"},
                      {"role": "user", "content": "halo"}], json_mode=True)
        assert out == '{"a": 1}', out
        assert calls["url"] == API_URL
        assert calls["headers"]["x-api-key"] == "sk-ant-tes"
        assert calls["headers"]["anthropic-version"] == "2023-06-01"
        assert calls["body"]["model"] == "claude-sonnet-4-5"
        # system dipisah + instruksi JSON ditambahkan
        assert "kamu editor" in calls["body"]["system"]
        assert "JSON valid" in calls["body"]["system"]
        # pesan system tidak ikut di messages
        assert all(m["role"] != "system" for m in calls["body"]["messages"])
        print("chat + system split + json_mode: OK")

        # tanpa api key -> ProviderError
        try:
            ClaudeProvider(api_key=None).chat([{"role": "user", "content": "x"}])
            raise AssertionError("harus raise")
        except ProviderError as e:
            assert "API key" in str(e)
            print("tanpa API key -> ProviderError: OK")
    finally:
        requests.post = _real
    print("SMOKE claude: LULUS")
