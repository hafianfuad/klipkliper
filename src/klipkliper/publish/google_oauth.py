"""Helper Google OAuth untuk publisher Klipkliper (saat ini: YouTube).

Reuse fungsi aman dari `providers.gemini_oauth` (authorize URL PKCE,
exchange code, refresh, penyimpanan token 0600) — JANGAN duplikat logika
itu di sini. Yang spesifik YouTube hanya: scope + path token.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..providers.gemini_oauth import (
    GeminiOAuthProvider,
    ProviderError as _ProviderError,  # noqa: F401 (diekspor ulang bila perlu)
)

from .base import PublishError

# Scope minimal untuk upload video. JANGAN minta scope lebih luas
# (mis. youtube.force-ssl) kecuali benar-benar dibutuhkan.
YOUTUBE_SCOPES: List[str] = [
    "openid",
    "https://www.googleapis.com/auth/youtube.upload",
]

CONFIG_DIR = Path.home() / ".klipkliper"
TOKEN_PATH = CONFIG_DIR / "youtube_token.json"


def authorize_url(client_id: str,
                  redirect_uri: str = "http://localhost:8080/",
                  ) -> Tuple[str, str]:
    """Bangun URL authorize YouTube (PKCE). Returns (url, code_verifier)."""
    return GeminiOAuthProvider.get_authorize_url(
        client_id, redirect_uri, scopes=YOUTUBE_SCOPES)


def exchange_code(code: str, client_id: str, client_secret: str,
                  redirect_uri: str, code_verifier: str,
                  token_path: Path = TOKEN_PATH) -> Dict:
    """Tukar code -> token, simpan ke youtube_token.json (0600)."""
    try:
        return GeminiOAuthProvider.exchange_code(
            code, client_id, client_secret, redirect_uri, code_verifier,
            token_path=Path(token_path),
        )
    except _ProviderError as e:
        raise PublishError(str(e), hint=getattr(e, "hint", None))


def refresh(token_path: Path = TOKEN_PATH,
            client_secret: Optional[str] = None) -> Dict:
    """Refresh access token bila perlu. Return creds (dict)."""
    provider = GeminiOAuthProvider(token_path=Path(token_path))
    try:
        return provider.refresh_if_needed(client_secret=client_secret)
    except _ProviderError as e:
        raise PublishError(str(e), hint=getattr(e, "hint", None))


def load_token(token_path: Path = TOKEN_PATH) -> Optional[Dict]:
    """Baca token tersimpan; None bila belum ada/rusak (jangan raise)."""
    p = Path(token_path)
    if not p.exists():
        return None
    try:
        import json
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def client_id_from_env_or_file(path: Optional[str] = None) -> Optional[str]:
    """Ambil client_id: env KLIPKLIPER_YOUTUBE_CLIENT_ID / file client_secret.json."""
    if os.environ.get("KLIPKLIPER_YOUTUBE_CLIENT_ID"):
        return os.environ["KLIPKLIPER_YOUTUBE_CLIENT_ID"]
    p = path or os.environ.get("KLIPKLIPER_YOUTUBE_CLIENT_SECRET_FILE")
    if p and Path(p).exists():
        import json
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        node = data.get("installed") or data.get("web") or {}
        return node.get("client_id")
    return None


def client_secret_from_env_or_file(path: Optional[str] = None) -> Optional[str]:
    """Ambil client_secret: env KLIPKLIPER_YOUTUBE_CLIENT_SECRET / file."""
    if os.environ.get("KLIPKLIPER_YOUTUBE_CLIENT_SECRET"):
        return os.environ["KLIPKLIPER_YOUTUBE_CLIENT_SECRET"]
    p = path or os.environ.get("KLIPKLIPER_YOUTUBE_CLIENT_SECRET_FILE")
    if p and Path(p).exists():
        import json
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        node = data.get("installed") or data.get("web") or {}
        return node.get("client_secret")
    return None


if __name__ == "__main__":
    # Smoke test: URL authorize terbentuk benar (tanpa kredensial asli).
    url, verifier = authorize_url("DUMMY_CLIENT_ID")
    assert "accounts.google.com" in url
    assert "youtube.upload" in url  # scope ter-encode
    assert "code_challenge" in url and verifier
    print("authorize_url: OK")
    print("load_token (belum ada):", load_token(Path("/tmp/klipkliper-test-nope.json")))
