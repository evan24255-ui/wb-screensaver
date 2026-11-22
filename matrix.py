#!/usr/bin/env python3
"""Lightweight Matrix-style digital rain screensaver for the 480x320 Pi LCD.
Click / touch / any key exits (after a 2 s startup grace period).
"""
import datetime
import os
import random
import time

import pygame

GRACE_SECONDS = 2.0
BG = (0, 0, 0)
CHARS = "0123456789ABCDEF"
TAIL = 6


def log(message):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screensaver.log")
    with open(path, "a") as fh:
        fh.write("%s %s\n" % (datetime.datetime.now().strftime("%F %T"), message))


def main():
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")
    pygame.init()
    try:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    except pygame.error:
        screen = pygame.display.set_mode((480, 320))
    width, height = screen.get_size()
    pygame.mouse.set_visible(False)
    pygame.display.set_caption("WB Matrix")
    log("matrix started %dx%d" % (width, height))

    size = max(12, height // 22)
    font = pygame.font.Font(
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size
    )
    columns = width // size
    drops = [random.uniform(-height, 0) for _ in range(columns)]
    speeds = [random.uniform(50, 180) for _ in range(columns)]
    cache = {}
    for level in range(TAIL):
        fade = 1.0 - level / float(TAIL)
        color = (int(60 * fade), int(255 * fade), int(110 * fade))
        for ch in CHARS:
            cache[(level, ch)] = font.render(ch, True, color)

    clock = pygame.time.Clock()
    start = time.monotonic()
    running = True

    while running:
        now = time.monotonic()
        dt = clock.tick(18) / 1000.0
        for event in pygame.event.get():
            if now - start < GRACE_SECONDS:
                continue
            if event.type in (
                pygame.MOUSEBUTTONDOWN,
                pygame.FINGERDOWN,
                pygame.KEYDOWN,
                pygame.QUIT,
            ):
                running = False

        screen.fill(BG)
        for i in range(columns):
            y = int(drops[i])
            for t in range(TAIL):
                ty = y - t * size
                if 0 <= ty < height:
                    screen.blit(cache[(t, random.choice(CHARS))], (i * size, ty))
            drops[i] += speeds[i] * dt
            if drops[i] - TAIL * size > height:
                drops[i] = random.uniform(-height, 0)
                speeds[i] = random.uniform(50, 180)

        pygame.display.flip()

    log("matrix exited")
    pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("matrix ERROR: %r" % exc)
        raise
