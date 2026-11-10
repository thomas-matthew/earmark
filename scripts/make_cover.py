"""Draw the podcast cover: an earmarked page (folded corner) carrying sound-wave bars.

Pillow is only needed here, not by the app:
    uv run --with pillow python scripts/make_cover.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[1] / "src" / "earmark" / "delivery" / "assets" / "cover.png"
SIZE = 1400  # podcast apps want 1400-3000 px square
SCALE = 2  # draw large, then shrink for smooth edges
S = SIZE * SCALE

TOP, BOTTOM = (255, 140, 66), (214, 52, 70)  # warm orange to coral
PAPER, FOLD, FOLD_SHADE = (255, 248, 238), (246, 214, 186), (226, 186, 156)
INK = (31, 38, 66)
INITIALS = "TM"  # marks this as my personal feed
FONT = "/System/Library/Fonts/Avenir Next.ttc"


def bold_font(size: int) -> ImageFont.FreeTypeFont:
    for index in range(16):
        try:
            font = ImageFont.truetype(FONT, size, index=index)
        except OSError:
            break
        if font.getname()[1] == "Bold":
            return font
    return ImageFont.truetype(FONT, size)


def badge(image: Image.Image, center: tuple[float, float], radius: float, u: float) -> None:
    """A dark round monogram badge with a paper-coloured ring, so it stands out on page and background."""
    cx, cy = center
    shadow = Image.new("L", image.size, 0)
    ImageDraw.Draw(shadow).ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)
    shadow = shadow.filter(ImageFilter.GaussianBlur(28 * u))
    image.paste(Image.new("RGB", image.size, (120, 20, 30)), (int(10 * u), int(20 * u)), shadow.point(lambda v: v * 0.5))
    draw = ImageDraw.Draw(image)
    ring = 14 * u
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=PAPER)
    draw.ellipse((cx - radius + ring, cy - radius + ring, cx + radius - ring, cy + radius - ring), fill=INK)
    draw.text((cx, cy), INITIALS, font=bold_font(int(radius * 0.78)), fill=PAPER, anchor="mm")


def gradient() -> Image.Image:
    image = Image.new("RGB", (S, S))
    pixels = image.load()
    for y in range(S):
        for x in range(0, S, 4):
            t = (x + y) / (2 * S)
            color = tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM))
            for dx in range(4):
                pixels[x + dx, y] = color
    return image


def main() -> None:
    image = gradient()
    u = S / 1400  # layout unit, so the design is described at 1400 px

    left, top, right, bottom = 380 * u, 250 * u, 1020 * u, 1150 * u
    fold = 230 * u
    radius = 60 * u

    page = Image.new("L", (S, S), 0)
    draw = ImageDraw.Draw(page)
    draw.rounded_rectangle((left, top, right, bottom), radius, fill=255)
    draw.polygon([(right - fold, top - 2), (right + 2, top - 2), (right + 2, top + fold)], fill=0)

    shadow = page.filter(ImageFilter.GaussianBlur(40 * u))
    image.paste(Image.new("RGB", (S, S), (120, 20, 30)), (int(18 * u), int(30 * u)), shadow.point(lambda v: v * 0.45))
    image.paste(Image.new("RGB", (S, S), PAPER), (0, 0), page)

    draw = ImageDraw.Draw(image)
    draw.polygon([(right - fold, top), (right - fold, top + fold), (right, top + fold)], fill=FOLD)
    draw.line([(right - fold, top + fold), (right, top + fold)], fill=FOLD_SHADE, width=int(6 * u))
    draw.line([(right - fold, top), (right - fold, top + fold)], fill=FOLD_SHADE, width=int(6 * u))

    heights = [150, 300, 470, 380, 560, 330, 190]
    bar, gap = 46 * u, 26 * u
    total = len(heights) * bar + (len(heights) - 1) * gap
    x = (left + right) / 2 - total / 2
    middle = (top + fold + bottom) / 2 + 20 * u
    for h in heights:
        half = h * u / 2
        draw.rounded_rectangle((x, middle - half, x + bar, middle + half), bar / 2, fill=INK)
        x += bar + gap

    badge(image, (right - 10 * u, bottom - 10 * u), 150 * u, u)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.resize((SIZE, SIZE), Image.LANCZOS).save(OUT, optimize=True)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
