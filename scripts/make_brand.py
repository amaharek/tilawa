"""Generate the brand images (original artwork: an open book under a sound wave).

Run with ``uv run python scripts/make_brand.py``. Produces, in
``custom_components/tilawa/brand/``: icon.png (256x256), icon@2x.png (512x512) and
the dark_ variants, all with transparent backgrounds and no padding, as the Home
Assistant brand guidelines require.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "tilawa" / "brand"
SIZE = 1024  # render large, then downscale for smooth edges

LIGHT = {
    "book": (31, 111, 74, 255),
    "page": (238, 246, 241, 255),
    "wave": (201, 162, 39, 255),
}
DARK = {
    "book": (143, 211, 176, 255),
    "page": (22, 46, 34, 255),
    "wave": (232, 196, 86, 255),
}


def draw(colors: dict[str, tuple[int, int, int, int]]) -> Image.Image:
    """Draw the mark on a transparent square canvas."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = SIZE / 2

    # Sound wave: five rounded bars.
    heights = (0.18, 0.30, 0.42, 0.30, 0.18)
    bar_w = SIZE * 0.075
    gap = SIZE * 0.045
    total = 5 * bar_w + 4 * gap
    x = cx - total / 2
    wave_center = SIZE * 0.26
    for h in heights:
        half = SIZE * h / 2
        d.rounded_rectangle(
            (x, wave_center - half, x + bar_w, wave_center + half),
            radius=bar_w / 2,
            fill=colors["wave"],
        )
        x += bar_w + gap

    # Open book: cover, two pages, spine.
    top = SIZE * 0.52
    bottom = SIZE * 0.98
    left = SIZE * 0.02
    right = SIZE * 0.98
    sag = SIZE * 0.08  # outer corners rise, centre dips
    cover = [
        (left, top + sag),
        (cx, top + sag * 2.1),
        (right, top + sag),
        (right, bottom - sag * 0.4),
        (cx, bottom),
        (left, bottom - sag * 0.4),
    ]
    d.polygon(cover, fill=colors["book"])
    inset = SIZE * 0.045
    page_top = top + sag + inset * 0.9
    for sign in (-1, 1):
        outer = left + inset if sign < 0 else right - inset
        inner = cx - inset * 0.35 * -sign if sign < 0 else cx + inset * 0.35
        inner = cx - inset * 0.35 if sign < 0 else cx + inset * 0.35
        page = [
            (outer, page_top),
            (inner, page_top + sag * 1.1),
            (inner, bottom - inset * 1.6),
            (outer, bottom - inset * 1.6 - sag * 0.5),
        ]
        d.polygon(page, fill=colors["page"])
        # three text lines per page
        for i in range(3):
            y0 = page_top + sag * 1.4 + i * SIZE * 0.07
            x_a = min(outer, inner) + inset * 0.9
            x_b = max(outer, inner) - inset * 0.9
            d.rounded_rectangle(
                (x_a, y0, x_b, y0 + SIZE * 0.022),
                radius=SIZE * 0.011,
                fill=colors["book"],
            )
    d.rounded_rectangle(
        (cx - SIZE * 0.012, top + sag * 2.0, cx + SIZE * 0.012, bottom - inset * 0.6),
        radius=SIZE * 0.012,
        fill=colors["book"],
    )
    return img


def save(img: Image.Image, name: str) -> None:
    """Trim to content, pad to a square, write 512 and 256 px versions."""
    bbox = img.getbbox()
    assert bbox is not None
    cropped = img.crop(bbox)
    side = max(cropped.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(cropped, ((side - cropped.width) // 2, (side - cropped.height) // 2))
    OUT.mkdir(parents=True, exist_ok=True)
    square.resize((512, 512), Image.LANCZOS).save(OUT / f"{name}@2x.png", optimize=True)
    square.resize((256, 256), Image.LANCZOS).save(OUT / f"{name}.png", optimize=True)


if __name__ == "__main__":
    save(draw(LIGHT), "icon")
    save(draw(DARK), "dark_icon")
    for path in sorted(OUT.glob("*.png")):
        with Image.open(path) as im:
            print(path.name, im.size, im.mode)
