"""Provider AI untuk Klipkliper (OAuth-first, API key sebagai fallback resmi).

Import di sini ringan (hanya base). Provider konkret di-import MALAS
di dalam `make_provider` agar `python -m klipkliper.providers.<nama>`
tidak memicu import ganda / RuntimeWarning:

    from klipkliper.providers import make_provider
    p = make_provider("groq")          # GROQ_API_KEY dari env
    p = make_provider("claude", api_key="sk-ant-...")
    p = make_provider("none")          # -> None (mode heuristic)
"""
from .base import AIProvider, Message, ProviderError

__all__ = ["AIProvider", "Message", "ProviderError", "make_provider"]

_VALID = ("groq", "claude", "openai", "gemini", "none")


def make_provider(name: str, **kw):
    """Factory provider. name: groq|claude|openai|gemini|none.

    "none" -> None (pemilih-momen pakai heuristic, tanpa LLM).
    Kwargs diteruskan ke konstruktor provider (mis. api_key, model).
    """
    key = (name or "none").strip().lower()
    if key == "none":
        return None
    if key == "groq":
        from .openai_compat import GroqProvider
        return GroqProvider(**kw)
    if key == "claude":
        from .claude import ClaudeProvider
        return ClaudeProvider(**kw)
    if key == "openai":
        from .openai import OpenAIProvider
        return OpenAIProvider(**kw)
    if key == "gemini":
        from .gemini_oauth import GeminiOAuthProvider
        return GeminiOAuthProvider(**kw)
    raise ValueError(f"provider tak dikenal: {name!r} (pilih: {', '.join(_VALID)})")


if __name__ == "__main__":
    # Smoke test factory (tanpa jaringan, tanpa kredensial asli).
    assert make_provider("none") is None
    print("none -> None: OK")

    g = make_provider("groq", api_key="x")
    assert g.name == "groq" and g.model == "llama-3.3-70b-versatile"
    print("groq: OK")

    c = make_provider("claude", api_key="x")
    assert c.name == "claude" and c.model == "claude-sonnet-4-5"
    print("claude: OK")

    o = make_provider("openai", api_key="x")
    assert o.name == "openai" and o.model == "gpt-4o-mini"
    print("openai: OK")

    gm = make_provider("gemini")
    from .gemini_oauth import GeminiOAuthProvider
    assert isinstance(gm, GeminiOAuthProvider)
    print("gemini (lazy import): OK")

    try:
        make_provider("bukan-provider")
        raise AssertionError("harus raise")
    except ValueError as e:
        assert "tak dikenal" in str(e)
        print("nama salah -> ValueError: OK")

    print("SMOKE providers/__init__: LULUS")
