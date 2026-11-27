"""Generate the welcome banner:  python tools/make_banner.py "RIA MUSIC" assets/welcome.jpg
Needs Pillow (pip install pillow). Not required to run the bot itself."""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def gradient():
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        for x in range(W):
            t = (x / W) * 0.55 + (y / H) * 0.45
            r = int(18 + 70 * t * t)
            g = int(10 + 24 * t)
            b = int(48 + 120 * (1 - abs(t - 0.45)))
            px[x, y] = (r, g, b)
    return img


def glow(img, box, color, blur):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(box, fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.paste(layer, (0, 0), layer)


def vinyl(img, cx, cy, r):
    d = ImageDraw.Draw(img, "RGBA")
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(12, 12, 20, 255), outline=(120, 90, 220, 255), width=4)
    for i in range(1, 22):
        rr = r * (0.34 + i * 0.03)
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=(255, 255, 255, 8 if i % 2 else 18), width=1)
    label = r * 0.32
    d.ellipse((cx - label, cy - label, cx + label, cy + label), fill=(124, 58, 237, 255))
    d.ellipse((cx - label * 0.62, cy - label * 0.62, cx + label * 0.62, cy + label * 0.62), fill=(236, 72, 153, 255))
    d.ellipse((cx - 9, cy - 9, cx + 9, cy + 9), fill=(12, 12, 20, 255))
    # light sweep
    sweep = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sweep).pieslice((cx - r, cy - r, cx + r, cy + r), -60, -35, fill=(255, 255, 255, 40))
    img.paste(sweep, (0, 0), sweep)


def bars(img, x0, y0, width, height):
    d = ImageDraw.Draw(img, "RGBA")
    random.seed(7)
    n, gap = 38, 8
    bw = (width - gap * (n - 1)) / n
    for i in range(n):
        h = height * (0.25 + 0.75 * abs(math.sin(i * 0.55)) * random.uniform(0.6, 1))
        x = x0 + i * (bw + gap)
        t = i / n
        col = (int(124 + 112 * t), int(58 + 14 * t), int(237 - 84 * t), 235)
        d.rounded_rectangle((x, y0 - h, x + bw, y0), radius=5, fill=col)


def main(title="RIA MUSIC", out="assets/welcome.jpg"):
    img = gradient().convert("RGBA")
    glow(img, (-200, -250, 600, 450), (168, 85, 247, 120), 120)
    glow(img, (700, 250, 1400, 900), (236, 72, 153, 90), 140)
    vinyl(img, 960, 330, 255)
    bars(img, 70, 650, 680, 150)
    d = ImageDraw.Draw(img, "RGBA")
    fs = 132
    while font(fs).getlength(title) > 620 and fs > 50:
        fs -= 6
    d.text((74, 206), title, font=font(fs), fill=(0, 0, 0, 110))
    d.text((70, 200), title, font=font(fs), fill=(255, 255, 255, 255))
    d.rounded_rectangle((74, 200 + fs + 34, 74 + 150, 200 + fs + 42), radius=4, fill=(236, 72, 153, 255))
    d.text((72, 200 + fs + 62), "Stream  •  Queue  •  Autoplay", font=font(40), fill=(220, 215, 255, 255))
    d.text((72, 200 + fs + 118), "YouTube · Spotify · Apple Music · JioSaavn", font=font(28), fill=(170, 165, 215, 255))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    img.convert("RGB").save(out, quality=88, optimize=True)
    print("saved", out, os.path.getsize(out) // 1024, "KB")


if __name__ == "__main__":
    main(*(sys.argv[1:3]))
