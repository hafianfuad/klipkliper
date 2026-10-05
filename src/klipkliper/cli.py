"""CLI Klipkliper.

    python -m klipkliper.cli clip <video|url> --out DIR [opsi]
    python -m klipkliper.cli providers
    python -m klipkliper.cli publish now <klip> --to youtube --title ... [--dry-run]
    python -m klipkliper.cli publish schedule <klip> --at "YYYY-MM-DD HH:MM" ...
    python -m klipkliper.cli publish run-due [--dry-run]
    python -m klipkliper.cli publish list-schedule
    python -m klipkliper.cli publish cancel-schedule <job_id>
    python -m klipkliper.cli publish authorize --to youtube
"""
import argparse
import os
import sys
from pathlib import Path

_PROVIDER_ENV = {
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}


def _make_provider(name, api_key=None, model=None):
    """Bangun provider AI dari nama via factory pusat (providers.make_provider).

    API key diambil dari argumen atau env (GROQ_API_KEY/OPENAI_API_KEY/
    ANTHROPIC_API_KEY). Error konfigurasi -> pesan jelas + exit(1)."""
    from .providers import make_provider

    name = (name or "none").lower()
    if name == "none":
        return None
    kw = {}
    if name in _PROVIDER_ENV:
        key = api_key or os.environ.get(_PROVIDER_ENV[name])
        if not key:
            sys.exit(f"error: butuh API key {name}: "
                     f"--api-key atau env {_PROVIDER_ENV[name]}")
        kw["api_key"] = key
    elif api_key:
        kw["api_key"] = api_key
    if model:
        kw["model"] = model
    try:
        return make_provider(name, **kw)
    except (ImportError, ValueError) as e:
        sys.exit(f"error: {e} (pilih: groq|gemini|claude|openai|none)")


def _mask(v):
    return "ada" if v else "tidak ada"


def cmd_providers(_args):
    """Tampilkan daftar provider + status konfigurasi (tanpa bocorkan key)."""
    try:
        from .providers.gemini_oauth import TOKEN_PATH
        gemini_login = Path(TOKEN_PATH).is_file()
    except ImportError:
        gemini_login = False
    rows = [
        ("none", "heuristic", "tanpa AI — selalu tersedia", "ya"),
        ("groq", "API key", f"env GROQ_API_KEY: {_mask(os.environ.get('GROQ_API_KEY'))}",
         "ya" if os.environ.get("GROQ_API_KEY") else "butuh key"),
        ("openai", "API key", f"env OPENAI_API_KEY: {_mask(os.environ.get('OPENAI_API_KEY'))}",
         "ya" if os.environ.get("OPENAI_API_KEY") else "butuh key"),
        ("claude", "API key", f"env ANTHROPIC_API_KEY: {_mask(os.environ.get('ANTHROPIC_API_KEY'))}",
         "ya" if os.environ.get("ANTHROPIC_API_KEY") else "butuh key"),
        ("gemini", "OAuth Google", f"login tersimpan: {'ya' if gemini_login else 'belum'}",
         "ya" if gemini_login else "butuh login"),
    ]
    print(f"{'provider':<8} {'auth':<10} {'status':<42} {'siap'}")
    print("-" * 72)
    for r in rows:
        print(f"{r[0]:<8} {r[1]:<10} {r[2]:<42} {r[3]}")
    return 0


# ---------------------------------------------------------------- publish

def _make_publisher(name):
    """Bangun publisher via factory pusat (publish.make_publisher)."""
    from .publish import make_publisher, AVAILABLE
    name = (name or "youtube").lower()
    try:
        return make_publisher(name)
    except (ImportError, ValueError) as e:
        sys.exit(f"error: {e} (tersedia: {', '.join(AVAILABLE)})")


def _parse_tags(s):
    if not s:
        return None
    return [t.strip() for t in s.split(",") if t.strip()]


def cmd_publish(args):
    """Subcommand publish: now | schedule | run-due | list-schedule |
    cancel-schedule | authorize."""
    from .publish.scheduler import Scheduler
    from .publish.base import PublishError

    action = args.action

    if action == "authorize":
        return _cmd_publish_authorize(args)

    if action == "list-schedule":
        sched = Scheduler()
        jobs = sched.list()
        if not jobs:
            print("belum ada jadwal.")
            return 0
        print(f"{'id':<10} {'waktu':<17} {'platform':<9} {'status':<8} judul")
        print("-" * 70)
        for j in jobs:
            print(f"{j['id']:<10} {j['at']:<17} {j['platform']:<9} "
                  f"{j['status']:<8} {j['title'][:40]}")
        return 0

    if action == "cancel-schedule":
        job_id = args.target
        sched = Scheduler()
        if job_id and sched.cancel(job_id):
            print(f"jadwal {job_id} dibatalkan.")
            return 0
        sys.exit(f"error: job_id tidak ditemukan: {job_id}")

    if action == "run-due":
        from .publish import AVAILABLE
        sched = Scheduler()
        pubs = {}
        for plat in AVAILABLE:
            try:
                pubs[plat] = _make_publisher(plat)
            except SystemExit:
                continue
        results = sched.run_due(pubs, dry_run=args.dry_run)
        if not results:
            print("tidak ada jadwal yang jatuh tempo.")
            return 0
        for r in results:
            if r["ok"]:
                res = r.get("result") or {}
                print(f"OK {r['job_id']}: {res.get('url', res)}")
            else:
                print(f"GAGAL {r['job_id']}: {r['error']}")
        return 0 if all(r["ok"] for r in results) else 1

    # action: now | schedule — butuh file video
    video = args.target
    if not video or not Path(video).exists():
        sys.exit(f"error: file video tidak ada: {video}")
    title = args.title or Path(video).stem.replace("_", " ").replace("-", " ")
    tags = _parse_tags(args.tags)
    pub = _make_publisher(args.to)
    extra = {"privacy": args.privacy}
    if tags:
        extra["tags"] = tags

    if action == "now":
        try:
            res = pub.publish(video, title, args.description or "",
                              dry_run=args.dry_run, **extra)
        except PublishError as e:
            sys.exit(f"error publish: {e}")
        if args.dry_run:
            import json
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(f"terposting: {res['url']} (id: {res['id']})")
        return 0

    if action == "schedule":
        sched = Scheduler()
        try:
            job_id = sched.schedule(args.to, video, title,
                                    args.description or "",
                                    at_iso=args.at, **extra)
        except ValueError as e:
            sys.exit(f"error: {e}")
        print(f"terjadwal: {job_id} -> {args.to} @ {args.at}")
        return 0

    sys.exit(f"error: aksi tidak dikenal: {action}")


def _cmd_publish_authorize(args):
    """Alur OAuth authorize untuk publisher (saat ini: youtube)."""
    plat = (args.to or "youtube").lower()
    if plat != "youtube":
        sys.exit(f"error: authorize untuk '{plat}' belum didukung "
                 "(saat ini: youtube).")
    from .publish import google_oauth as goauth
    from .providers.gemini_oauth import _parse_code

    cid = args.client_id or goauth.client_id_from_env_or_file(args.client_secret_file)
    csec = args.client_secret or goauth.client_secret_from_env_or_file(args.client_secret_file)
    if not cid or not csec:
        sys.exit("error: butuh client_id & client_secret:\n"
                 "  --client-secret-file client_secret.json, atau\n"
                 "  env KLIPKLIPER_YOUTUBE_CLIENT_ID / KLIPKLIPER_YOUTUBE_CLIENT_SECRET")
    redirect = args.redirect_uri
    url, verifier = goauth.authorize_url(cid, redirect)
    print("1. Buka URL ini di browser, login Google, authorize:\n")
    print(url + "\n")
    print("2. Paste code (atau full redirect URL) di bawah:")
    try:
        code = _parse_code(input("code: "))
        creds = goauth.exchange_code(code, cid, csec, redirect, verifier)
    except Exception as e:  # noqa: BLE001 — tampilkan ringkas
        sys.exit(f"error authorize: {e}")
    has_rt = bool(creds.get("refresh_token"))
    print(f"\nOK — token YouTube tersimpan di {goauth.TOKEN_PATH} "
          f"(refresh_token: {'ada' if has_rt else 'TIDAK ADA — ulangi dengan consent'}).")
    if not has_rt:
        print("Hint: pastikan URL authorize memuat access_type=offline & prompt=consent.")
    return 0


def cmd_clip(args):
    from .ingest import from_local, from_youtube, IngestError
    from .render import run_pipeline

    outdir = Path(args.out)
    workdir = outdir / "work"
    src = args.src

    provider = _make_provider(args.provider, args.api_key, args.model)

    def _progress(stage, frac):
        print(f"[{frac * 100:3.0f}%] {stage}", flush=True)

    try:
        if src.startswith(("http://", "https://")):
            print("unduh YouTube…", flush=True)
            info = from_youtube(src, workdir)
        else:
            info = from_local(src, workdir)
    except IngestError as e:
        sys.exit(f"error ingest: {e}")
    print(f"sumber: {info['path']} ({info['duration']:.1f} dtk, "
          f"{info['width']}x{info['height']})", flush=True)

    try:
        res = run_pipeline(info["path"], outdir, provider=provider,
                           n_clips=args.n, style=args.style, lang=args.lang,
                           progress=_progress)
    except Exception as e:  # noqa: BLE001 — tampilkan ringkas ke user
        sys.exit(f"error pipeline: {e}")

    print(f"\nmaster: {res['master']}")
    print("klip:")
    for c in res["clips"]:
        print(f"- {c['path']} [{c['start']:.1f}-{c['end']:.1f}] "
              f"skor={c['score']:.0f} {c['title']}")
    return 0


def cmd_ingest_bulk(args):
    """Unduh banyak video dari channel/playlist YouTube."""
    from .ingest import bulk_youtube, IngestError

    outdir = Path(args.out)
    total = args.max

    def _progress(done, tot, label):
        print(f"[{done}/{tot}] {label}", flush=True)

    try:
        res = bulk_youtube(args.url, outdir, max_videos=total,
                           progress=_progress)
    except IngestError as e:
        sys.exit(f"error bulk: {e}")

    ok, failed = res["ok"], res["failed"]
    print(f"\nberhasil: {len(ok)}, gagal: {len(failed)}")
    for info in ok:
        print(f"  ✅ {Path(info['path']).name} "
              f"({info['duration']:.0f} dtk, {info['width']}x{info['height']})")
    for f in failed:
        print(f"  ❌ {f['url'][:70]} — {f['error'][:120]}")
    return 0 if ok else 1


def build_parser():
    ap = argparse.ArgumentParser(prog="klipkliper",
                                 description="Klipkliper — video panjang jadi klip vertikal.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("clip", help="buat klip dari video/URL YouTube")
    p.add_argument("src", help="path video lokal atau URL YouTube")
    p.add_argument("--out", required=True, help="direktori output")
    p.add_argument("--n", type=int, default=5, help="jumlah klip (default 5)")
    p.add_argument("--style", default="Hype", help="style caption (default Hype)")
    p.add_argument("--lang", default="id", help="bahasa transkrip (default id)")
    p.add_argument("--provider", default="none",
                   choices=["groq", "gemini", "claude", "openai", "none"],
                   help="provider AI untuk pilih momen (default none=heuristic)")
    p.add_argument("--model", default=None, help="model AI (opsional)")
    p.add_argument("--api-key", default=None, help="API key (atau via env)")
    p.add_argument("--whisper-model", default="small",
                   help="model whisper (default small)")
    p.set_defaults(func=cmd_clip)

    q = sub.add_parser("providers", help="daftar provider AI + status")
    q.set_defaults(func=cmd_providers)

    ig = sub.add_parser("ingest", help="ingest media")
    ig_sub = ig.add_subparsers(dest="ingest_cmd", required=True)
    b = ig_sub.add_parser("bulk",
                          help="unduh banyak video dari channel/playlist YouTube")
    b.add_argument("url", help="URL channel / playlist / video YouTube")
    b.add_argument("--out", required=True, help="direktori output")
    b.add_argument("--max", type=int, default=20,
                   help="maksimal video (default 20)")
    b.set_defaults(func=cmd_ingest_bulk)

    pb = sub.add_parser("publish", help="posting klip ke platform (eksperimental)")
    pb.add_argument("action",
                    choices=["now", "schedule", "run-due", "list-schedule",
                             "cancel-schedule", "authorize"],
                    help="aksi publish")
    pb.add_argument("target", nargs="?",
                    help="file klip (now/schedule) atau job_id (cancel-schedule)")
    pb.add_argument("--to", default="youtube",
                    help="platform tujuan (default youtube)")
    pb.add_argument("--dry-run", action="store_true",
                    help="validasi + tampilkan request tanpa mengirim")
    pb.add_argument("--title", default=None, help="judul video")
    pb.add_argument("--description", default="", help="deskripsi video")
    pb.add_argument("--tags", default=None,
                    help="tags dipisah koma, mis: \"ai,klip,shorts\"")
    pb.add_argument("--privacy", default="unlisted",
                    choices=["private", "unlisted", "public"],
                    help="privasi YouTube (default unlisted)")
    pb.add_argument("--at", default=None,
                    help='waktu jadwal "YYYY-MM-DD HH:MM" (untuk schedule)')
    pb.add_argument("--client-id", default=None)
    pb.add_argument("--client-secret", default=None)
    pb.add_argument("--client-secret-file", default=None,
                    help="path client_secret.json (untuk authorize)")
    pb.add_argument("--redirect-uri", default="http://localhost:8080/",
                    help="harus cocok dengan OAuth client (untuk authorize)")
    pb.set_defaults(func=cmd_publish)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
