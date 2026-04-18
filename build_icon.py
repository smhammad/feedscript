"""
Generate the macOS app icon (white mic on black squircle) and install it
into Feedscript.app/Contents/Resources/AppIcon.icns.

Run from the project root:
    ./venv/bin/python build_icon.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).parent.resolve()
APP_RES = ROOT / "Feedscript.app" / "Contents" / "Resources"
BUILD = ROOT / "build"
ICONSET = BUILD / "AppIcon.iconset"
ICNS = BUILD / "AppIcon.icns"
ICO = BUILD / "AppIcon.ico"
STATIC = ROOT / "static"

BG = (0, 0, 0, 255)
FG = (255, 255, 255, 255)
MASTER = 1024


def draw_master(size: int = MASTER) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 1024.0  # scaling factor if we ever render a different master

    # Black squircle background (radius ~22.5% — Apple-ish)
    bg_radius = int(230 * s)
    d.rounded_rectangle((0, 0, size, size), radius=bg_radius, fill=BG)

    # Capsule (pill) body
    cap_left   = int(387 * s)
    cap_top    = int(200 * s)
    cap_right  = int(637 * s)
    cap_bottom = int(580 * s)
    cap_radius = int(125 * s)
    d.rounded_rectangle((cap_left, cap_top, cap_right, cap_bottom),
                        radius=cap_radius, fill=FG)

    # Pickup arc (U-shape) below the capsule
    arc_bbox = (int(250 * s), int(345 * s), int(774 * s), int(869 * s))
    arc_width = int(52 * s)
    d.arc(arc_bbox, start=0, end=180, fill=FG, width=arc_width)

    # Short vertical stand
    st_left   = int(497 * s)
    st_top    = int(869 * s)
    st_right  = int(527 * s)
    st_bottom = int(934 * s)
    d.rectangle((st_left, st_top, st_right, st_bottom), fill=FG)

    # Horizontal base
    base_left   = int(357 * s)
    base_top    = int(934 * s)
    base_right  = int(667 * s)
    base_bottom = int(979 * s)
    d.rounded_rectangle((base_left, base_top, base_right, base_bottom),
                        radius=int(20 * s), fill=FG)

    return img


ICONSET_SIZES = [
    ("icon_16x16.png",      16),
    ("icon_16x16@2x.png",   32),
    ("icon_32x32.png",      32),
    ("icon_32x32@2x.png",   64),
    ("icon_128x128.png",    128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png",    256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png",    512),
    ("icon_512x512@2x.png", 1024),
]


def build() -> Path:
    (ROOT / "build").mkdir(exist_ok=True)
    if ICONSET.exists():
        shutil.rmtree(ICONSET)
    ICONSET.mkdir(parents=True)

    master = draw_master(MASTER)
    master.save(ROOT / "build" / "AppIcon_master.png")

    for name, px in ICONSET_SIZES:
        img = master.resize((px, px), Image.LANCZOS)
        img.save(ICONSET / name, format="PNG")

    if ICNS.exists():
        ICNS.unlink()
    subprocess.run(
        ["iconutil", "-c", "icns", "-o", str(ICNS), str(ICONSET)],
        check=True,
    )
    return ICNS


def build_ico() -> Path:
    BUILD.mkdir(exist_ok=True)
    master = draw_master(MASTER)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(ICO, format="ICO", sizes=sizes)
    return ICO


def install():
    icns = build()
    ico = build_ico()
    APP_RES.mkdir(parents=True, exist_ok=True)
    target = APP_RES / "AppIcon.icns"
    shutil.copyfile(icns, target)
    print(f"Installed {target}")
    print(f"Built {ico}")

    STATIC.mkdir(exist_ok=True)
    favicon_master = draw_master(MASTER)
    favicon_master.resize((256, 256), Image.LANCZOS).save(STATIC / "icon-256.png")
    favicon_master.resize((64, 64), Image.LANCZOS).save(STATIC / "icon-64.png")
    print(f"Installed {STATIC}/icon-256.png and icon-64.png")


if __name__ == "__main__":
    install()
