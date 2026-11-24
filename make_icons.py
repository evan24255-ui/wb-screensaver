#!/usr/bin/env python3
"""Generate 64x64 desktop icons for the screensaver launchers."""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = "/home/evan/wb-screensaver/icons"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
# Weather Icons (SIL OFL 1.1) for the weather launcher.
WEATHER_FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fonts", "weathericons-regular-webfont.ttf")
DSEG_FONT = "/usr/share/fonts/truetype/dseg7-classic/dseg7-classic-latin-700-normal.ttf"
os.makedirs(OUT, exist_ok=True)


def base():
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((3, 3, 60, 60), radius=10, fill=(12, 12, 12),
                        outline=(120, 120, 120), width=2)
    return im, d


# Flip clock: split digits.
im, d = base()
f = ImageFont.truetype(FONT, 22)
d.text((7, 8), "12", font=f, fill=(235, 235, 235))
d.line((5, 31, 58, 31), fill=(0, 0, 0), width=3)
d.text((7, 30), "30", font=f, fill=(235, 235, 235))
im.save(os.path.join(OUT, "flip.png"))

# Matrix: green digits.
im, d = base()
f = ImageFont.truetype(FONT, 20)
d.text((9, 8), "01", font=f, fill=(70, 240, 110))
d.text((9, 30), "10", font=f, fill=(35, 150, 65))
im.save(os.path.join(OUT, "matrix.png"))

# Stars: dots on dark sky.
im, d = base()
for x, y, r in [(14, 16, 2), (32, 12, 1), (48, 22, 2), (20, 38, 1),
                (42, 44, 2), (30, 50, 1), (53, 52, 1)]:
    d.ellipse((x - r, y - r, x + r, y + r), fill=(230, 240, 255))
im.save(os.path.join(OUT, "stars.png"))

# Weather: sun behind cloud glyph from Weather Icons, amber on dark.
im, d = base()
gf = ImageFont.truetype(WEATHER_FONT, 46)
d.text((9, 4), "\uf002", font=gf, fill=(255, 164, 43))
im.save(os.path.join(OUT, "weather.png"))

# Weather (paper): same glyph in ink on a kraft-paper card.
im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
d.rounded_rectangle((3, 3, 60, 60), radius=10, fill=(201, 106, 30),
                    outline=(60, 28, 8), width=2)
d.text((9, 4), "\uf002", font=gf, fill=(24, 11, 2))
im.save(os.path.join(OUT, "weather-paper.png"))

print("icons written to", OUT)
