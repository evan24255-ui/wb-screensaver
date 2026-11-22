#!/usr/bin/env python3
"""Calm drifting starfield screensaver for the 480x320 Pi LCD.
Click / touch / any key exits (after a 2 s startup grace period).
"""
import datetime
import math
import os
import random
import time

import pygame

GRACE_SECONDS = 2.0
BG = (0, 0, 0)


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
    pygame.display.set_caption("WB Stars")
    log("stars started %dx%d" % (width, height))

    stars = []
    for _ in range(70):
        stars.append({
            "x": random.uniform(0, width),
            "y": random.uniform(0, height),
            "speed": random.uniform(5, 25),
            "radius": random.choice([1, 1, 1, 2]),
            "phase": random.uniform(0, 2 * math.pi),
            "hue": random.choice([(210, 230, 255), (255, 255, 255), (255, 235, 200)]),
        })

    clock = pygame.time.Clock()
    start = time.monotonic()
    running = True

    while running:
        now = time.monotonic()
        dt = clock.tick(20) / 1000.0
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
        for star in stars:
            star["y"] += star["speed"] * dt
            if star["y"] - star["radius"] > height:
                star["y"] = -star["radius"]
                star["x"] = random.uniform(0, width)
            twinkle = 0.55 + 0.45 * math.sin(now * 2 + star["phase"])
            color = tuple(int(c * twinkle) for c in star["hue"])
            pygame.draw.circle(
                screen, color,
                (int(star["x"]), int(star["y"])), star["radius"]
            )
        pygame.display.flip()

    log("stars exited")
    pygame.quit()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("stars ERROR: %r" % exc)
        raise
