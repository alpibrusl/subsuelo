#!/usr/bin/env python3
"""Generate the static brand assets served from webapp/public/.

    python deploy/make_brand_assets.py

Writes (all committed — they ship in the bundle and must exist in the raw
HTML, since link-preview scrapers never run our JavaScript):

    public/og-cover.png        1200x630 social card (OpenGraph / Twitter)
    public/apple-touch-icon.png  180x180 iOS home-screen icon
    public/favicon.png           32x32 fallback for browsers without SVG icons

`public/favicon.svg` is hand-written, not generated here. Colours are the
app's own tokens from src/styles.css (--bg / --panel / --accent / --gold).
Re-run only when the wordmark or palette changes.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PUBLIC = Path(__file__).resolve().parent.parent / "public"

BG = (15, 20, 25)          # --bg   #0f1419
PANEL = (26, 34, 44)       # --panel
INK = (230, 237, 243)      # --ink
MUTED = (139, 152, 165)    # --muted
LINE = (45, 59, 74)        # --line
ACCENT = (79, 209, 197)    # --accent
GOLD = (246, 196, 84)      # --gold

FONTS = {  # (bold, regular) candidates, first that exists wins
    "bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"],
    "regular": ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"],
}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS[kind]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit(f"no {kind} font found — install fonts-dejavu")


def gradient_square(size: int, radius: int) -> Image.Image:
    """The brand mark: accent→gold diagonal gradient in a rounded square."""
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(ACCENT, GOLD))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(grad, (0, 0), mask)
    return out


def og_cover() -> None:
    W, H = 1200, 630
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # top hairline in the brand gradient
    for x in range(W):
        t = x / (W - 1)
        d.line([(x, 0), (x, 5)], fill=tuple(round(a + (b - a) * t) for a, b in zip(ACCENT, GOLD)))

    # a faint graticule, echoing the map the app actually is
    for x in range(0, W, 60):
        d.line([(x, 6), (x, H)], fill=(20, 27, 34))
    for y in range(6, H, 60):
        d.line([(0, y), (W, y)], fill=(20, 27, 34))

    mark = gradient_square(56, 16)
    img.paste(mark, (80, 92), mark)
    d.text((152, 100), "Subsuelo", font=font("bold", 46), fill=INK)

    d.text((80, 212), "Where to buy land", font=font("bold", 76), fill=INK)
    d.text((80, 300), "for critical raw materials", font=font("bold", 76), fill=ACCENT)

    d.text((80, 416), "Weights-of-Evidence prospectivity over open European geoscience,",
           font=font("regular", 27), fill=MUTED)
    d.text((80, 456), "drilled down to real cadastral parcels, mining rights and land prices.",
           font=font("regular", 27), fill=MUTED)

    # commodity strip — the two mineral systems the app models
    chips = ["Sn", "W", "Li", "Ta", "Nb", "U", "Mo", "Be", "Bi", "Cu", "Zn", "Pb", "Ag"]
    f = font("bold", 22)
    x = 80
    for c in chips:
        w = round(d.textlength(c, font=f))
        d.rounded_rectangle([x, 528, x + w + 30, 574], 12, fill=PANEL, outline=LINE)
        d.text((x + 15, 539), c, font=f, fill=ACCENT if c in ("Sn", "W", "Li") else MUTED)
        x += w + 42

    d.text((80, 596), "alpibrusl.github.io/subsuelo  ·  open data  ·  EUPL-1.2",
           font=font("regular", 19), fill=(94, 106, 118))

    img.save(PUBLIC / "og-cover.png", optimize=True)
    print("✓ public/og-cover.png")


def icons() -> None:
    for size, radius, name in ((180, 40, "apple-touch-icon.png"), (32, 7, "favicon.png")):
        canvas = Image.new("RGBA", (size, size), BG + (255,))
        pad = round(size * 0.14)
        mark = gradient_square(size - 2 * pad, max(2, radius - pad // 2))
        canvas.paste(mark, (pad, pad), mark)
        canvas.save(PUBLIC / name, optimize=True)
        print(f"✓ public/{name}")


if __name__ == "__main__":
    PUBLIC.mkdir(parents=True, exist_ok=True)
    og_cover()
    icons()
