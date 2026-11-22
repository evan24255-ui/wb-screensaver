#!/usr/bin/env python3
"""Fliqlo-style flip clock screensaver for the Raspberry Pi 3.5" 480x320 LCD.

Black background, thin white split-flap digits, smooth flip animation.
Click / touch / Esc exits.  Designed to be launched by idle_watch.sh.
"""
import datetime
import os
import sys
import time

import pygame
import pygame.freetype

FONT_CANDIDATES = [
    os.environ.get("WB_FONT", ""),
    "/usr/share/fonts/truetype/quicksand/Quicksand-Medium.ttf",
    "/usr/share/fonts/truetype/quicksand/Quicksand-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

FG = (232, 232, 232)
CARD_BG = (10, 10, 10)
CARD_EDGE = (42, 42, 42)
SEAM = (0, 0, 0)
BG = (0, 0, 0)

FLIP_SECONDS = 0.38
# The touchscreen can deliver a stale press when the fullscreen window is mapped.
# Ignore input for the first two seconds so the saver does not exit instantly.
GRACE_SECONDS = 2.0


def log(message):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screensaver.log")
    with open(path, "a") as fh:
        fh.write("%s %s\n" % (datetime.datetime.now().strftime("%F %T"), message))


def load_font(size):
    for path in FONT_CANDIDATES:
        if path and os.path.exists(path):
            try:
                return pygame.freetype.Font(path, size)
            except Exception:
                continue
    return pygame.freetype.SysFont("sans-serif", size)


def render_digit(font, char):
    surface, _ = font.render(char, FG)
    return surface


def split_halves(surface):
    width, height = surface.get_size()
    mid = height // 2
    top = surface.subsurface(pygame.Rect(0, 0, width, mid)).copy()
    bottom = surface.subsurface(pygame.Rect(0, mid, width, height - mid)).copy()
    return top, bottom


class FlapDigit:
    def __init__(self, char, font):
        self.char = char
        self.surface = render_digit(font, char)
        self.top, self.bottom = split_halves(self.surface)
        self.previous = char
        self.flip_start = 0.0

    def set(self, char, now):
        if char == self.char:
            return
        self.previous = self.char
        self.char = char
        self.flip_start = now

    def draw(self, surface, x, y, now):
        new_top, new_bottom = render_digit_cache(self.char, font_store)
        old_top, old_bottom = render_digit_cache(self.previous, font_store)
        width, half = new_top.get_size()
        elapsed = now - self.flip_start

        if elapsed >= FLIP_SECONDS:
            surface.blit(new_top, (x, y))
            surface.blit(new_bottom, (x, y + half))
            return

        progress = elapsed / FLIP_SECONDS
        if progress < 0.5:
            # First half: new top is revealed while the old top folds down.
            surface.blit(new_top, (x, y))
            surface.blit(new_bottom, (x, y + half))
            shrink = max(1, int(half * (1.0 - progress * 2.0)))
            flap = pygame.transform.smoothscale(old_top, (width, shrink))
            surface.blit(flap, (x, y + half - shrink))
        else:
            # Second half: the flap swings down and becomes the new bottom.
            surface.blit(new_top, (x, y))
            surface.blit(old_bottom, (x, y + half))
            grow = max(1, int(half * (progress - 0.5) * 2.0))
            flap = pygame.transform.smoothscale(new_bottom, (width, grow))
            surface.blit(flap, (x, y + half))


# Small cache shared by all digits; populated in main().
digit_cache = {}
font_store = None


def render_digit_cache(char, font):
    if char not in digit_cache:
        digit_cache[char] = split_halves(render_digit(font, char))
    return digit_cache[char]


def main():
    global font_store

    os.environ.setdefault("SDL_VIDEODRIVER", "x11")
    pygame.init()
    pygame.freetype.init()
    pygame.display.set_caption("WB Flip Clock")

    try:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    except pygame.error as exc:
        log("fullscreen failed (%s), falling back to 480x320 window" % exc)
        screen = pygame.display.set_mode((480, 320))

    width, height = screen.get_size()
    pygame.mouse.set_visible(False)
    log("started %dx%d" % (width, height))

    # Scale the font until the four cards plus colon fit the panel.
    font_size = int(height * 0.48)
    while True:
        font_store = load_font(font_size)
        sample, _ = font_store.render("8", FG)
        digit_w, digit_h = sample.get_size()
        card_w = digit_w + 18
        card_h = digit_h + 16
        gap = max(5, int(width * 0.015))
        colon_w = max(18, int(width * 0.06))
        total = 4 * card_w + 3 * gap + colon_w
        if total <= width - 12 or font_size <= 40:
            break
        font_size -= 4

    start_x = (width - total) // 2
    card_y = (height - card_h) // 2
    digit_y = card_y + 8

    for ch in "0123456789":
        render_digit_cache(ch, font_store)

    clock = ["0", "0", "0", "0"]
    digits = [FlapDigit(ch, font_store) for ch in clock]

    running = True
    last_time = None
    start_time = time.monotonic()
    snapshot_done = False
    redraw = True
    was_animating = False
    clock_tick = pygame.time.Clock()

    while running:
        now = time.monotonic()

        for event in pygame.event.get():
            if now - start_time < GRACE_SECONDS:
                continue
            if event.type in (
                pygame.MOUSEBUTTONDOWN,
                pygame.FINGERDOWN,
                pygame.KEYDOWN,
                pygame.QUIT,
            ):
                running = False

        current = datetime.datetime.now().strftime("%H%M")
        if current != last_time:
            if os.environ.get("WB_DEBUG"):
                log("time=%s digits=%s" % (current, "".join(d.char for d in digits)))
            for index, char in enumerate(current):
                digits[index].set(char, now)
            last_time = current
            redraw = True

        animating = any(
            0 <= now - d.flip_start < FLIP_SECONDS for d in digits
        )
        if was_animating and not animating:
            redraw = True
        was_animating = animating

        # Redraw only on a change or while a flap is moving: keeps CPU low on a Pi 3B.
        if redraw or animating:
            screen.fill(BG)

            x = start_x
            for index, digit in enumerate(digits):
                pygame.draw.rect(
                    screen, CARD_BG,
                    pygame.Rect(x, card_y, card_w, card_h),
                    border_radius=5,
                )
                pygame.draw.rect(
                    screen, CARD_EDGE,
                    pygame.Rect(x, card_y, card_w, card_h),
                    width=1,
                    border_radius=5,
                )
                digit.draw(screen, x + 9, digit_y, now)

                if index == 1:
                    cx = x + card_w + gap + colon_w // 2
                    radius = max(4, colon_w // 5)
                    pygame.draw.circle(
                        screen, FG, (cx, digit_y + int(digit_h * 0.36)), radius
                    )
                    pygame.draw.circle(
                        screen, FG, (cx, digit_y + int(digit_h * 0.74)), radius
                    )
                    x += card_w + gap + colon_w
                else:
                    x += card_w + gap

            pygame.draw.line(
                screen, SEAM, (start_x, digit_y + digit_h // 2),
                (start_x + total - colon_w, digit_y + digit_h // 2), 1,
            )

            pygame.display.flip()
            redraw = False
            if os.environ.get("WB_SNAP") and not snapshot_done and now - start_time > 3:
                pygame.image.save(screen, "/tmp/wb_snap.png")
                snapshot_done = True

        clock_tick.tick(20)

    log("exited by user input")
    pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # keep a traceback in the log for debugging
        log("ERROR: %r" % exc)
        raise
