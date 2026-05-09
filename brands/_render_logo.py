"""Renders the Tasmota REST brand assets to PNG using Pillow.

Run:
    python brands/_render_logo.py

Outputs:
    brands/icon.png       (256x256)
    brands/icon@2x.png    (512x512)
    brands/logo.png       (720x256)
    brands/logo@2x.png    (1440x512)
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Iterable, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent

# ---- Palette ----
BG_GRAD = [(14, 165, 233), (3, 105, 161), (11, 31, 51)]
BOLT_GRAD = [(253, 230, 138), (245, 158, 11)]
WHITE = (255, 255, 255, 235)


def _vert_gradient(size: Tuple[int, int], stops: list[tuple[int, int, int]]) -> Image.Image:
    """Diagonal multi-stop gradient."""
    w, h = size
    img = Image.new("RGB", (w, h))
    px = img.load()
    n = len(stops) - 1
    for y in range(h):
        for x in range(w):
            t = (x + y) / (w + h - 2)
            seg = min(int(t * n), n - 1)
            local = t * n - seg
            a, b = stops[seg], stops[seg + 1]
            px[x, y] = (
                int(a[0] + (b[0] - a[0]) * local),
                int(a[1] + (b[1] - a[1]) * local),
                int(a[2] + (b[2] - a[2]) * local),
            )
    return img


def _rounded_mask(size: Tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(((0, 0), (size[0] - 1, size[1] - 1)), radius=radius, fill=255)
    return mask


def _draw_arc_band(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    radius: float,
    start_deg: float,
    end_deg: float,
    width: int,
    color: tuple,
    samples: int = 80,
) -> None:
    """Approximate an antialiased thick arc as a connected polyline of small circles."""
    pts = []
    for i in range(samples + 1):
        t = i / samples
        ang = math.radians(start_deg + (end_deg - start_deg) * t)
        pts.append((cx + math.cos(ang) * radius, cy + math.sin(ang) * radius))
    for x, y in pts:
        r = width / 2
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def _bolt_polygon(scale: float = 1.0, ox: float = 128, oy: float = 0) -> list[tuple[float, float]]:
    raw = [
        (138, 96), (102, 168), (124, 168), (110, 212),
        (168, 132), (144, 132), (156, 96),
    ]
    return [((x - 128) * scale + ox, y * scale + oy) for x, y in raw]


def _bolt_image(size: int) -> Image.Image:
    """Draw a vertical-gradient bolt with white outline on a transparent canvas."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    scale = size / 256
    poly = _bolt_polygon(scale=scale, ox=size / 2, oy=0)
    # gradient fill via masked paste
    grad = Image.new("RGB", (size, size))
    gpx = grad.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        gpx[0, y] = (
            int(BOLT_GRAD[0][0] + (BOLT_GRAD[1][0] - BOLT_GRAD[0][0]) * t),
            int(BOLT_GRAD[0][1] + (BOLT_GRAD[1][1] - BOLT_GRAD[0][1]) * t),
            int(BOLT_GRAD[0][2] + (BOLT_GRAD[1][2] - BOLT_GRAD[0][2]) * t),
        )
        for x in range(1, size):
            gpx[x, y] = gpx[0, y]
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)
    img.paste(grad, (0, 0), mask)
    # white outline
    draw.line(poly + [poly[0]], fill=(255, 255, 255, 255), width=max(2, int(3 * scale)), joint="curve")
    return img


def _draw_icon(size: int) -> Image.Image:
    radius = int(size * 56 / 256)
    bg = _vert_gradient((size, size), BG_GRAD).convert("RGBA")
    mask = _rounded_mask((size, size), radius)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(bg, (0, 0), mask)

    draw = ImageDraw.Draw(canvas)
    # subtle inset
    inset = max(2, int(size * 6 / 256))
    ImageDraw.Draw(canvas).rounded_rectangle(
        ((inset, inset), (size - 1 - inset, size - 1 - inset)),
        radius=radius - inset,
        outline=(255, 255, 255, 24),
        width=max(1, int(size * 2 / 256)),
    )

    # WiFi arcs (centered around y ~= 170/256 * size)
    cx, cy = size / 2, size * 178 / 256
    radii = [(76, 14, 235), (52, 11, 200), (32, 9, 150)]  # (radius_units_at_256, width_units_at_256, alpha)
    for r_u, w_u, alpha in radii:
        r = r_u / 256 * size
        w = max(2, int(w_u / 256 * size))
        _draw_arc_band(
            draw,
            cx,
            cy,
            r,
            start_deg=-180 + 25,
            end_deg=-25,
            width=w,
            color=(255, 255, 255, alpha),
        )

    # Bolt
    bolt = _bolt_image(size)
    canvas.alpha_composite(bolt)

    # Soft glow on the whole composite
    glow = canvas.filter(ImageFilter.GaussianBlur(radius=max(2, size / 100)))
    out = Image.alpha_composite(glow, canvas)
    return out


def _find_font(weight: str = "Bold", size: int = 64) -> ImageFont.FreeTypeFont:
    # Try a few likely-installed system fonts
    candidates_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    candidates_regular = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    pool = candidates_bold if weight.lower().startswith("b") else candidates_regular
    for path in pool:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _draw_logo(width: int, height: int) -> Image.Image:
    icon = _draw_icon(height)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # Background banner
    bg = _vert_gradient((width, height), BG_GRAD).convert("RGBA")
    mask = _rounded_mask((width, height), int(height * 56 / 256))
    canvas.paste(bg, (0, 0), mask)

    # Drop the icon's foreground (without its own bg square) over the banner
    canvas.alpha_composite(icon, (0, 0))

    # Wordmark
    draw = ImageDraw.Draw(canvas)
    title_font = _find_font("Bold", size=int(height * 74 / 256))
    sub_font = _find_font("Regular", size=int(height * 42 / 256))
    title_x = int(height * 276 / 256)
    title_y = int(height * 60 / 256)
    draw.text((title_x, title_y), "Tasmota", font=title_font, fill=(255, 255, 255, 255))
    sub_y = title_y + int(height * 78 / 256)
    draw.text((title_x, sub_y), "R E S T", font=sub_font, fill=(253, 230, 138, 255))
    return canvas


def main() -> None:
    icon_256 = _draw_icon(256)
    icon_512 = _draw_icon(512)
    logo_1x = _draw_logo(720, 256)
    logo_2x = _draw_logo(1440, 512)
    icon_256.save(OUT / "icon.png", optimize=True)
    icon_512.save(OUT / "icon@2x.png", optimize=True)
    logo_1x.save(OUT / "logo.png", optimize=True)
    logo_2x.save(OUT / "logo@2x.png", optimize=True)
    print("Wrote:", *(p.name for p in [OUT / "icon.png", OUT / "icon@2x.png", OUT / "logo.png", OUT / "logo@2x.png"]))


if __name__ == "__main__":
    main()
