"""Provider Gemini via Google OAuth (ala Gemini CLI) untuk Klipkliper.

Alur:
    1. User buat OAuth client (tipe Desktop) di Google Cloud Console,
       download client_secret.json (JANGAN masuk repo).
    2. `python -m klipkliper.providers.gemini_oauth login`
       -> buka URL authorize -> user login Google -> paste code.
    3. Token (access + refresh) disimpan di ~/.klipkliper/gemini_token.json.
    4. `chat()` refresh otomatis bila kedaluwarsa, lalu panggil
       generativelanguage.googleapis.com dengan Bearer token.

PILIHAN SCOPE (hasil riset, 2026-10-05):
    Dipakai: https://www.googleapis.com/auth/cloud-platform
             (+ openid, userinfo.email)
    Alasan:
    - Ini scope yang dipakai Gemini CLI sendiri (terlihat di
      ~/.gemini/oauth_creds.json milik CLI).
    - Scope "https://www.googleapis.com/auth/generative-language" BUKAN
      scope OAuth yang valid untuk client pihak ketiga -> Google menolak
      dengan error `invalid_scope` di halaman consent. JANGAN dipakai.
    - Discovery doc generativelanguage.models.generateContent tidak
      mendeklarasikan scope wajib; token cloud-platform adalah yang
      dipakai ekosistem Gemini CLI untuk akses OAuth.

CATATAN JUJUR (risiko yang belum terverifikasi live):
    - Per 2026-06-18 Google menghentikan kuota Code Assist/AI Pro gratis
      via "Login with Google" untuk akun konsumen (hanya lisensi
      Standard/Enterprise yang tetap jalan). Login OAuth tetap bisa
      didapat, tapi panggilan API bisa ditolak kuota/403 untuk akun
      tanpa lisensi.
    - Dukungan OAuth di endpoint PUBLIK generativelanguage untuk client
      pihak ketiga tidak didokumentasikan resmi sejelas API key.
      Jika 401/403, fallback resmi: API key AI Studio (ada free tier)
      atau Vertex AI. Lihat docs/oauth-setup.md bagian Troubleshooting.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from .base import AIProvider, Message, ProviderError

# ---------------------------------------------------------------- konstanta

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# Scope ala Gemini CLI. JANGAN pakai ".../auth/generative-language" (invalid_scope).
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/cloud-platform",
]

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = os.environ.get("KLIPKLIPER_GEMINI_MODEL", "gemini-2.0-flash")

CONFIG_DIR = Path.home() / ".klipkliper"
TOKEN_PATH = CONFIG_DIR / "gemini_token.json"


# ---------------------------------------------------------------- util

def _now() -> int:
    return int(time.time())


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _save_json_secure(path: Path, obj: dict) -> None:
    """Simpan JSON dengan permission ketat (dir 0o700, file 0o600)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(path)


def _parse_code(user_input: str) -> str:
    """Terima authorization code mentah ATAU full redirect URL, kembalikan code."""
    s = user_input.strip().strip("'\"")
    if s.startswith("http"):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(s).query)
        if "error" in q:
            raise ProviderError(f"Google menolak authorize: {q['error'][0]}")
        if "code" not in q:
            raise ProviderError("URL redirect tidak mengandung parameter 'code'.")
        return q["code"][0]
    # kadang user paste "4/0A..." atau "code=..." mentah
    if s.startswith("code="):
        s = s[len("code="):]
    return s


# ---------------------------------------------------------------- provider

class GeminiOAuthProvider(AIProvider):
    """Gemini via OAuth Google. Token disimpan lokal, auto-refresh."""

    name = "gemini-oauth"

    def __init__(self, model: str = DEFAULT_MODEL,
                 token_path: Path = TOKEN_PATH):
        self.model = model
        self.token_path = Path(token_path)

    # ---- OAuth flow ----

    @staticmethod
    def get_authorize_url(client_id: str,
                          redirect_uri: str,
                          scopes: Optional[List[str]] = None,
                          state: Optional[str] = None) -> Tuple[str, str]:
        """Bangun URL authorize (PKCE S256).

        Returns:
            (url, code_verifier): buka `url` di browser, lalu pakai
            `code_verifier` saat `exchange_code`.
        """
        scopes = scopes or SCOPES
        verifier = _b64url(secrets.token_bytes(64))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",      # <- wajib supaya dapat refresh_token
            "prompt": "consent",           # <- paksa consent supaya offline dijamin
            "state": state or secrets.token_urlsafe(16),
        }
        return f"{AUTH_URL}?{urllib.parse.urlencode(params)}", verifier

    @staticmethod
    def exchange_code(code: str, client_id: str, client_secret: str,
                      redirect_uri: str, code_verifier: str,
                      token_path: Path = TOKEN_PATH) -> Dict:
        """Tukar authorization code -> token, simpan ke token_path."""
        token_path = Path(token_path)
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "code_verifier": code_verifier,
                    "grant_type": "authorization_code",
                    "redirect_uri": redirect_uri,
                },
                timeout=30,
            )
        except requests.RequestException as e:
            raise ProviderError(f"Gagal menghubungi token endpoint: {e}")
        if resp.status_code != 200:
            raise ProviderError(
                f"Token exchange gagal (HTTP {resp.status_code}): {resp.text[:300]}",
                hint="Pastikan code belum dipakai/kedaluwarsa (10 menit), "
                     "client_id/secret cocok dengan client_secret.json, "
                     "dan redirect_uri sama persis dengan saat authorize.",
            )
        data = resp.json()
        creds = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),  # bisa None bila bukan consent pertama
            "expiry": _now() + int(data.get("expires_in", 3600)),
            "scopes": data.get("scope", ""),
            "token_type": data.get("token_type", "Bearer"),
            "client_id": client_id,  # disimpan agar refresh pakai client yang sama
        }
        # client_secret TIDAK disimpan di file token (diambil dari
        # client_secret.json / env tiap refresh via _client_secret()).
        _save_json_secure(token_path, creds)
        return creds

    def _load_creds(self) -> Dict:
        if not self.token_path.exists():
            raise ProviderError(
                f"Token tidak ditemukan di {self.token_path}.",
                hint="Jalankan: python -m klipkliper.providers.gemini_oauth login",
            )
        try:
            return json.loads(self.token_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise ProviderError(f"File token rusak: {e}",
                                hint="Hapus file-nya lalu login ulang.")

    def refresh_if_needed(self, client_secret: Optional[str] = None) -> Dict:
        """Refresh access token bila <60 detik menuju kedaluwarsa. Return creds."""
        creds = self._load_creds()
        if creds.get("expiry", 0) - _now() > 60 and creds.get("access_token"):
            return creds  # masih valid
        rt = creds.get("refresh_token")
        if not rt:
            raise ProviderError(
                "Tidak ada refresh_token (mungkin login tanpa consent offline).",
                hint="Login ulang dengan prompt consent; pastikan URL authorize "
                     "memuat access_type=offline.",
            )
        secret = client_secret or _client_secret_from_env_or_file()
        if not secret:
            raise ProviderError(
                "Butuh client_secret untuk refresh.",
                hint="Set env KLIPKLIPER_GOOGLE_CLIENT_SECRET atau "
                     "--client-secret-file ke client_secret.json.",
            )
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "client_id": creds["client_id"],
                    "client_secret": secret,
                    "refresh_token": rt,
                    "grant_type": "refresh_token",
                },
                timeout=30,
            )
        except requests.RequestException as e:
            raise ProviderError(f"Gagal refresh token: {e}")
        if resp.status_code != 200:
            raise ProviderError(
                f"Refresh token gagal (HTTP {resp.status_code}): {resp.text[:300]}",
                hint="Refresh token mungkin dicabut/kedaluwarsa — login ulang.",
            )
        data = resp.json()
        creds["access_token"] = data["access_token"]
        creds["expiry"] = _now() + int(data.get("expires_in", 3600))
        if data.get("refresh_token"):
            creds["refresh_token"] = data["refresh_token"]
        _save_json_secure(self.token_path, creds)
        return creds

    # ---- chat ----

    @staticmethod
    def _to_gemini_contents(messages: List[Message]) -> Tuple[List[Dict], Optional[Dict]]:
        """Konversi pesan OpenAI-style -> format Gemini.

        Returns: (contents, system_instruction|None).
        role mapping: system -> systemInstruction (top-level),
                      user -> "user", assistant -> "model".
        """
        contents: List[Dict] = []
        system_parts: List[Dict] = []
        for m in messages:
            role = m.get("role", "user")
            text = m.get("content", "")
            if role == "system":
                system_parts.append({"text": text})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": text}]})
            else:  # "user" (dan apapun yang tak dikenal -> user)
                contents.append({"role": "user", "parts": [{"text": text}]})
        system_instruction = {"parts": system_parts} if system_parts else None
        return contents, system_instruction

    def chat(self, messages: List[Message], json_mode: bool = False) -> str:
        creds = self.refresh_if_needed()
        contents, system_instruction = self._to_gemini_contents(messages)
        body: Dict = {"contents": contents}
        if system_instruction:
            body["systemInstruction"] = system_instruction
        if json_mode:
            body["generationConfig"] = {"responseMimeType": "application/json"}

        url = f"{API_BASE}/models/{self.model}:generateContent"
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {creds['access_token']}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=120,
            )
        except requests.RequestException as e:
            raise ProviderError(f"Gagal menghubungi Gemini API: {e}")

        if resp.status_code == 200:
            return self._extract_text(resp.json())

        # ---- error mapping dengan hint aksi ----
        try:
            err = resp.json().get("error", {})
            msg = err.get("message", resp.text[:300])
            status = err.get("status", "")
        except ValueError:
            msg, status = resp.text[:300], ""
        if resp.status_code == 401:
            raise ProviderError(
                f"Gemini API 401 UNAUTHENTICATED: {msg}",
                hint="Token tidak valid/kedaluwarsa dan refresh gagal. "
                     "Login ulang: python -m klipkliper.providers.gemini_oauth login",
            )
        if resp.status_code == 403:
            raise ProviderError(
                f"Gemini API 403 ({status}): {msg}",
                hint="Kemungkinan: (1) kuota Code Assist habis / akun tanpa lisensi "
                     "(per 2026-06-18 akun konsumen tidak lagi dilayani via OAuth ini); "
                     "(2) API belum di-enable di project. Fallback resmi: API key "
                     "AI Studio (gratis) atau Vertex AI.",
            )
        if resp.status_code == 404:
            raise ProviderError(
                f"Gemini API 404: {msg}",
                hint=f"Model '{self.model}' tidak tersedia untuk akun ini. "
                     "Coba set env KLIPKLIPER_GEMINI_MODEL=gemini-flash-latest "
                     "atau gemini-3.6-flash.",
            )
        raise ProviderError(f"Gemini API HTTP {resp.status_code} ({status}): {msg}")

    @staticmethod
    def _extract_text(data: Dict) -> str:
        try:
            cands = data.get("candidates", [])
            parts = cands[0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
            if not text:
                raise KeyError("empty")
            return text
        except (KeyError, IndexError, TypeError):
            raise ProviderError(
                f"Respons Gemini tidak mengandung teks. finishReason="
                f"{(data.get('candidates') or [{}])[0].get('finishReason')}; "
                f"raw: {json.dumps(data)[:500]}",
                hint="Jika finishReason=SAFETY, prompt diblokir filter keamanan.",
            )


# ---------------------------------------------------------------- helpers CLI

def _client_secret_from_env_or_file(path: Optional[str] = None) -> Optional[str]:
    if os.environ.get("KLIPKLIPER_GOOGLE_CLIENT_SECRET"):
        return os.environ["KLIPKLIPER_GOOGLE_CLIENT_SECRET"]
    p = path or os.environ.get("KLIPKLIPER_GOOGLE_CLIENT_SECRET_FILE")
    if p and Path(p).exists():
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        node = data.get("installed") or data.get("web") or {}
        return node.get("client_secret")
    return None


def _client_id_from_env_or_file(path: Optional[str] = None) -> Optional[str]:
    if os.environ.get("KLIPKLIPER_GOOGLE_CLIENT_ID"):
        return os.environ["KLIPKLIPER_GOOGLE_CLIENT_ID"]
    p = path or os.environ.get("KLIPKLIPER_GOOGLE_CLIENT_SECRET_FILE")
    if p and Path(p).exists():
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        node = data.get("installed") or data.get("web") or {}
        return node.get("client_id")
    return None


def cmd_login(args: argparse.Namespace) -> int:
    client_id = args.client_id or _client_id_from_env_or_file(args.client_secret_file)
    client_secret = args.client_secret or _client_secret_from_env_or_file(args.client_secret_file)
    if not client_id or not client_secret:
        print("Butuh client_id & client_secret. Cara isi (salah satu):", file=sys.stderr)
        print("  --client-secret-file client_secret.json   (download dari Google Cloud Console)", file=sys.stderr)
        print("  env KLIPKLIPER_GOOGLE_CLIENT_ID / KLIPKLIPER_GOOGLE_CLIENT_SECRET", file=sys.stderr)
        return 2
    redirect_uri = args.redirect_uri
    url, verifier = GeminiOAuthProvider.get_authorize_url(client_id, redirect_uri)
    print("1. Buka URL ini di browser dan login dengan akun Google kamu:\n")
    print(url + "\n")
    print("2. Setelah authorize, kamu dapat code (atau URL redirect). Paste di bawah:")
    user_in = input("code: ")
    try:
        code = _parse_code(user_in)
        creds = GeminiOAuthProvider.exchange_code(
            code, client_id, client_secret, redirect_uri, verifier,
            token_path=Path(args.token_path),
        )
    except ProviderError as e:
        print(f"\nGAGAL: {e}", file=sys.stderr)
        return 1
    print(f"\nOK — token tersimpan di {args.token_path} "
          f"(refresh_token: {'ada' if creds.get('refresh_token') else 'TIDAK ADA — login ulang dengan consent'}).")
    print("Tes dengan: python -m klipkliper.providers.gemini_oauth test")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    provider = GeminiOAuthProvider(model=args.model, token_path=Path(args.token_path))
    try:
        out = provider.chat([{"role": "user", "content": "balas: OK"}])
    except ProviderError as e:
        print(f"GAGAL: {e}", file=sys.stderr)
        return 1
    print("Respons model:")
    print(out)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="klipkliper.providers.gemini_oauth",
                                 description="Login Google OAuth & tes Gemini API untuk Klipkliper.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="Jalankan alur login OAuth Google.")
    p_login.add_argument("--client-id", default=None)
    p_login.add_argument("--client-secret", default=None)
    p_login.add_argument("--client-secret-file", default=None,
                         help="Path ke client_secret.json (JANGAN commit ke repo).")
    p_login.add_argument("--redirect-uri", default="http://localhost:8080/",
                         help="Harus cocok dengan yang terdaftar di OAuth client.")
    p_login.add_argument("--token-path", default=str(TOKEN_PATH))
    p_login.set_defaults(func=cmd_login)

    p_test = sub.add_parser("test", help="Kirim 1 prompt pendek, tampilkan respons.")
    p_test.add_argument("--model", default=DEFAULT_MODEL)
    p_test.add_argument("--token-path", default=str(TOKEN_PATH))
    p_test.set_defaults(func=cmd_test)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
