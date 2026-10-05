"""Provider OpenAI-compatible (Chat Completions) untuk Klipkliper.

Satu implementasi untuk semua endpoint bergaya OpenAI:
Groq, OpenAI, Ollama, Qwen, endpoint sendiri, dll.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

import requests

from .base import AIProvider, Message, ProviderError


def _hint_for_status(status: Optional[int]) -> Optional[str]:
    if status == 401:
        return "API key salah atau kedaluwarsa — cek key di dashboard provider."
    if status == 403:
        return "Akses ditolak — cek limit/kuota akun atau region yang didukung."
    if status == 429:
        return "Rate limit — tunggu sebentar lalu coba lagi."
    if status and 500 <= status < 600:
        return "Server provider error — coba lagi nanti."
    return None


class OpenAICompatProvider(AIProvider):
    """Chat Completions API format OpenAI: POST {base_url}/chat/completions."""

    name = "openai_compat"

    def __init__(self, base_url: str, api_key: Optional[str], model: str,
                 timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ProviderError(
                f"{self.name}: API key belum diisi.",
                hint="Isi API key via argumen atau environment variable.",
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def chat(self, messages: List[Message], json_mode: bool = False) -> str:
        body: Dict = {"model": self.model, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        url = f"{self.base_url}/chat/completions"
        try:
            resp = requests.post(url, headers=self._headers(),
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
            raise ProviderError(f"{self.name}: request timeout ({self.timeout}s).",
                                hint="Coba lagi; bila sering, naikkan timeout.")
        except requests.RequestException as e:
            raise ProviderError(f"{self.name}: jaringan bermasalah: {e}")
        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ProviderError(f"{self.name}: respons tak terduga: {e}")


class GroqProvider(OpenAICompatProvider):
    """Groq via endpoint OpenAI-compatible."""

    name = "groq"
    BASE_URL = "https://api.groq.com/openai/v1"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"

    def __init__(self, api_key: Optional[str] = None,
                 model: Optional[str] = None, timeout: int = 120,
                 base_url: Optional[str] = None):
        super().__init__(
            base_url=base_url or self.BASE_URL,
            api_key=api_key or os.environ.get("GROQ_API_KEY"),
            model=model or self.DEFAULT_MODEL,
            timeout=timeout,
        )


if __name__ == "__main__":
    # Smoke test tanpa jaringan: fake requests.post, verifikasi URL/header/body.
    import json as _json

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
        calls.update(url=url, headers=headers, body=json, timeout=timeout)
        return _FakeResp({"choices": [{"message": {"content": '{"ok": true}'}}]})

    _real = requests.post
    requests.post = _fake_post
    try:
        p = GroqProvider(api_key="kunci-rahasia")
        out = p.chat([{"role": "user", "content": "halo"}], json_mode=True)
        assert out == '{"ok": true}', out
        assert calls["url"] == "https://api.groq.com/openai/v1/chat/completions", calls["url"]
        assert calls["headers"]["Authorization"] == "Bearer kunci-rahasia"
        assert calls["body"]["model"] == "llama-3.3-70b-versatile"
        assert calls["body"]["response_format"] == {"type": "json_object"}
        print("chat + json_mode: OK")

        # json_mode=False -> tanpa response_format
        p.chat([{"role": "user", "content": "halo"}])
        assert "response_format" not in calls["body"]
        print("tanpa json_mode: OK")

        # error HTTP -> ProviderError + hint
        def _fake_401(url, headers=None, json=None, timeout=None):
            return _FakeResp({"error": "bad key"}, status=401)
        requests.post = _fake_401
        try:
            p.chat([{"role": "user", "content": "x"}])
            raise AssertionError("harus raise")
        except ProviderError as e:
            assert "401" in str(e) and e.hint, str(e)
            print("HTTP 401 -> ProviderError + hint: OK")

        # tanpa api key -> ProviderError
        requests.post = _fake_post
        try:
            GroqProvider(api_key=None).chat([{"role": "user", "content": "x"}])
            raise AssertionError("harus raise")
        except ProviderError as e:
            assert "API key" in str(e)
            print("tanpa API key -> ProviderError: OK")
    finally:
        requests.post = _real
    print("SMOKE openai_compat: LULUS")
