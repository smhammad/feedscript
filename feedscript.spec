# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Feedscript (Windows).
# Build with:  pyinstaller feedscript.spec
# Runs on the Windows CI runner (see .github/workflows/build-windows.yml).

from pathlib import Path

ROOT = Path(SPECPATH).resolve()

hidden = [
    # uvicorn's plug-in loaders
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # pywebview's Windows backend
    "webview.platforms.edgechromium",
    "webview.platforms.mshtml",
    # Our FastAPI server so launcher.py's `import app` resolves
    "app",
]

datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("requirements.txt", "."),
]

icon_path = ROOT / "build" / "AppIcon.ico"

a = Analysis(
    ["launcher.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "pandas",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Feedscript",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)
