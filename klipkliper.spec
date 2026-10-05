# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec untuk Klipkliper (Windows).

Build di mesin Windows:
    pip install -r requirements.txt pyinstaller
    pyinstaller klipkliper.spec
Hasil: dist/Klipkliper/Klipkliper.exe (folder) atau onefile bila diubah.
"""
import os
from pathlib import Path

SRC = Path("src")

block_cipher = None

a = Analysis(
    [str(SRC / "klipkliper" / "ui" / "main.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        # Model face detection (dibundel agar tak perlu download)
        (str(Path("assets/models/blaze_face_short_range.tflite")),
         "klipkliper_assets/models"),
    ],
    hiddenimports=[
        "klipkliper.ingest",
        "klipkliper.transcribe",
        "klipkliper.faces",
        "klipkliper.score",
        "klipkliper.caption",
        "klipkliper.render",
        "klipkliper.cli",
        "klipkliper.providers",
        "klipkliper.providers.base",
        "klipkliper.providers.gemini_oauth",
        "klipkliper.providers.openai_compat",
        "klipkliper.providers.claude",
        "klipkliper.providers.openai",
        "klipkliper.ui.main",
        "klipkliper.ui.worker",
        "klipkliper.ui.settings",
        "klipkliper.ui.preview",
        "edge_tts",
        "PIL",
        "faster_whisper",
        "ctranslate2",
        "mediapipe",
        "cv2",
        "yt_dlp",
        "google_auth_oauthlib",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Klipkliper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # aplikasi GUI; ubah ke True untuk debug
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # TODO: assets/icon.ico
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Klipkliper",
)
