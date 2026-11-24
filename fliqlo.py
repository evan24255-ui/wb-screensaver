#!/usr/bin/env python3
"""Fliqlo-style flip clock screensaver for the Raspberry Pi 3.5" 480x320 LCD.

Retro seven-segment look: configurable colour, dim ghost segments, brightness
and optional CRT-style afterglow. Click / touch / Esc exits.
Designed to be launched by idle_watch.sh.
"""
import datetime
import os
import time

import pygame
import pygame.freetype

try:
    import weather as weather_mod
except Exception as _weather_exc:  # keep the clock usable without the module
    weather_mod = None
    _WEATHER_IMPORT_ERROR = _weather_exc
else:
    _WEATHER_IMPORT_ERROR = None

FONT_CANDIDATES = [
    os.environ.get("WB_FONT", ""),
    "/usr/share/fonts/truetype/quicksand/Quicksand-Medium.ttf",
    "/usr/share/fonts/truetype/quicksand/Quicksand-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

CARD_BG = (10, 10, 10)
CARD_EDGE = (42, 42, 42)
SEAM = (0, 0, 0)
BG = (0, 0, 0)

FLIP_SECONDS = 0.38
# The touchscreen can deliver a stale press when the fullscreen window is mapped.
GRACE_SECONDS = 2.0


def parse_color(value, default):
    """Parse #RRGGBB or #RGB into (r, g, b); return default on bad input."""
    if not value:
        return default
    s = value.lstrip("#")
    try:
        if len(s) == 3:
            s = "".join(c * 2 for c in s)
        if len(s) != 6:
            return default
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


def apply_brightness(rgb, percent):
    """Scale an RGB tuple by a brightness percentage (0-100)."""
    factor = max(0, min(100, percent)) / 100.0
    return tuple(int(c * factor + 0.5) for c in rgb)


def env_int(name, default, minimum=None):
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value) if minimum is not None else value


def parse_hhmm(value, default):
    """Parse HH:MM into minutes since midnight; fall back on bad input."""
    try:
        hour, minute = (int(part) for part in value.strip().split(":"))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour * 60 + minute
    except (ValueError, AttributeError):
        pass
    return default


def night_active(start_min, end_min, now=None):
    """True inside [start, end); supports ranges that wrap past midnight."""
    now = now or datetime.datetime.now()
    minute = now.hour * 60 + now.minute
    if start_min == end_min:
        return False
    if start_min < end_min:
        return start_min <= minute < end_min
    return minute >= start_min or minute < end_min


# Configured in main() before any glyph surfaces are rendered.
FG = (255, 164, 43)
GHOST = (42, 20, 0)

# All digits share one cell, aligned by the font's own glyph origin. Narrow
# glyphs such as "1" then sit on the right, exactly like a real 7-segment LED.
glyph_cell = None
glyph_offsets = {}


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


def build_glyph_layout(font):
    """Build one shared cell anchored on the full-height '8' glyph.

    font.render() returns a tightly cropped surface plus the glyph origin.
    Horizontal offsets come from that origin, so DSEG7's narrow "1" lands on
    the right-hand segments like a real LED. Vertically we centre each glyph's
    ink in the cell instead of using its origin: DSEG7 draws "1"/"4" 12px
    shorter and shifted up, which otherwise leaves them misaligned with the
    ghost "8" and with the flip seam.
    """
    global glyph_cell, glyph_offsets
    rendered = {ch: font.render(ch, FG) for ch in "0123456789"}
    ref_surface, ref_rect = rendered["8"]
    ref_w, ref_h = ref_surface.get_size()
    left = min(rect[0] for _, rect in rendered.values())
    width = max(rect[0] + surface.get_width() for surface, rect in rendered.values()) - left
    glyph_cell = (width, ref_h)
    glyph_offsets = {
        ch: (
            rect[0] - left,
            (ref_h - surface.get_height()) // 2,
        )
        for ch, (surface, rect) in rendered.items()
    }


def render_digit(font, char, color=None):
    """Render one digit into the shared cell, honouring its glyph origin."""
    glyph = font.render(char, FG if color is None else color)[0]
    if glyph_cell is None:
        return glyph
    cell = pygame.Surface(glyph_cell, pygame.SRCALPHA)
    cell.blit(glyph, glyph_offsets.get(char, (0, 0)))
    return cell


def split_halves(surface):
    width, height = surface.get_size()
    mid = height // 2
    top = surface.subsurface(pygame.Rect(0, 0, width, mid)).copy()
    bottom = surface.subsurface(pygame.Rect(0, mid, width, height - mid)).copy()
    return top, bottom


# Small caches shared by all digits; populated in main().
digit_cache = {}
ghost_cache = {}
font_store = None
afterglow_on = False
afterglow_ms = 700


def render_digit_cache(char, font):
    if char not in digit_cache:
        digit_cache[char] = split_halves(render_digit(font, char))
    return digit_cache[char]


def render_ghost_cache(font):
    """A dim '8' lights every segment, so it shows through unlit strokes."""
    if GHOST is None:
        return None
    if "8" not in ghost_cache:
        ghost_cache["8"] = split_halves(render_digit(font, "8", GHOST))
    return ghost_cache["8"]


class FlapDigit:
    def __init__(self, char):
        self.char = char
        self.previous = char
        self.flip_start = 0.0
        self.glow_char = None
        self.glow_start = 0.0

    def set(self, char, now):
        if char == self.char:
            return
        self.previous = self.char
        self.char = char
        self.flip_start = now
        if afterglow_on:
            self.glow_char = self.previous
            self.glow_start = now

    def draw(self, surface, x, y, now):
        new_top, new_bottom = render_digit_cache(self.char, font_store)
        width, half = new_top.get_size()
        elapsed = now - self.flip_start

        # Dim "8" beneath the digit: the unlit segments of a real LED display.
        ghost = render_ghost_cache(font_store)
        if ghost is not None:
            surface.blit(ghost[0], (x, y))
            surface.blit(ghost[1], (x, y + half))

        # Afterglow: the old glyph fades under the new one, so it is only
        # visible where the new digit has no lit segment.
        if self.glow_char is not None:
            age_ms = (now - self.glow_start) * 1000.0
            if 0 <= age_ms < afterglow_ms:
                alpha = int(255 * (1.0 - age_ms / afterglow_ms) ** 2)
                old_top, old_bottom = render_digit_cache(self.glow_char, font_store)
                faded_top = old_top.copy()
                faded_top.set_alpha(alpha)
                faded_bottom = old_bottom.copy()
                faded_bottom.set_alpha(alpha)
                surface.blit(faded_top, (x, y))
                surface.blit(faded_bottom, (x, y + half))
            else:
                self.glow_char = None

        if elapsed >= FLIP_SECONDS:
            surface.blit(new_top, (x, y))
            surface.blit(new_bottom, (x, y + half))
            return

        old_top, old_bottom = render_digit_cache(self.previous, font_store)
        progress = elapsed / FLIP_SECONDS
        if progress < 0.5:
            surface.blit(new_top, (x, y))
            surface.blit(new_bottom, (x, y + half))
            shrink = max(1, int(half * (1.0 - progress * 2.0)))
            flap = pygame.transform.smoothscale(old_top, (width, shrink))
            surface.blit(flap, (x, y + half - shrink))
        else:
            surface.blit(new_top, (x, y))
            surface.blit(old_bottom, (x, y + half))
            grow = max(1, int(half * (progress - 0.5) * 2.0))
            flap = pygame.transform.smoothscale(new_bottom, (width, grow))
            surface.blit(flap, (x, y + half))


def main():
    global FG, GHOST, font_store, afterglow_on, afterglow_ms

    # Colour configuration. Defaults give a soft amber vintage LED look.
    base = parse_color(os.environ.get("WB_COLOR", "#FFA42B"), (255, 164, 43))
    day_brightness = env_int("WB_BRIGHTNESS", 85)
    night_brightness = env_int("WB_NIGHT_BRIGHTNESS", 50)
    night_enabled = os.environ.get("WB_NIGHT_MODE", "1") != "0"
    night_start = parse_hhmm(os.environ.get("WB_NIGHT_START", "22:00"), 22 * 60)
    night_end = parse_hhmm(os.environ.get("WB_NIGHT_END", "07:00"), 7 * 60)
    period = "night" if night_enabled and night_active(night_start, night_end) else "day"
    active_brightness = night_brightness if period == "night" else day_brightness
    FG = apply_brightness(base, active_brightness)
    ghost_value = os.environ.get("WB_GHOST_COLOR", "#2A1400")
    GHOST = None if ghost_value.lower() in ("off", "0", "none") else parse_color(
        ghost_value, (42, 20, 0)
    )
    afterglow_on = os.environ.get("WB_AFTERGLOW", "0") != "0"
    afterglow_ms = max(100, env_int("WB_AFTERGLOW_MS", 700))

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
    log("started %dx%d fg=%s ghost=%s period=%s brightness=%d afterglow=%s" % (
        width, height, FG, GHOST, period, active_brightness, afterglow_on
    ))

    # ---- weather scene: clock and weather alternate inside one saver process
    weather_only = os.environ.get("WB_WEATHER_ONLY", "0") != "0"
    weather_enabled = weather_mod is not None and (
        weather_only or os.environ.get("WB_WEATHER", "1") != "0"
    )
    board = None
    if weather_enabled:
        try:
            weather_service = weather_mod.WeatherService()
            weather_service.start()
            board = weather_mod.WeatherBoard(
                (width, height),
                FG,
                GHOST,
                theme=os.environ.get("WB_WEATHER_THEME", "dark"),
                service=weather_service,
            )
            log("weather scene enabled (only=%s)" % weather_only)
        except Exception as exc:
            log("weather scene disabled: %r" % exc)
            board = None
    elif weather_mod is None:
        log("weather module unavailable: %r" % _WEATHER_IMPORT_ERROR)

    clock_seconds = max(5, env_int("WB_CLOCK_SECONDS", 20))
    weather_seconds = max(5, env_int("WB_WEATHER_SECONDS", 12))
    scene = "weather" if (weather_only and board is not None) else "clock"
    scene_start = time.monotonic()

    font_size = int(height * 0.48)
    while True:
        font_store = load_font(font_size)
        build_glyph_layout(font_store)
        digit_w, digit_h = glyph_cell
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
    render_ghost_cache(font_store)

    digits = [FlapDigit(ch) for ch in "0000"]

    running = True
    weather_snap_done = False
    last_time = None
    start_time = time.monotonic()
    snapshot_done = False
    redraw = True
    was_animating = False
    clock_tick = pygame.time.Clock()

    # Colon blink: WB_BLINK=0 disables it, WB_BLINK_MS sets the half-period.
    blink_enabled = os.environ.get("WB_BLINK", "1") != "0"
    blink_ms = max(100, env_int("WB_BLINK_MS", 1000))
    was_blink_on = True

    while running:
        now = time.monotonic()

        # Re-evaluate every frame so a boundary crossed mid-session takes
        # effect immediately (e.g. left running across 22:00 or 07:00).
        new_period = (
            "night" if night_enabled and night_active(night_start, night_end) else "day"
        )
        if new_period != period:
            period = new_period
            active_brightness = (
                night_brightness if period == "night" else day_brightness
            )
            FG = apply_brightness(base, active_brightness)
            # Cached glyphs were tinted with the old colour; rebuild them.
            digit_cache.clear()
            ghost_cache.clear()
            for ch in "0123456789":
                render_digit_cache(ch, font_store)
            render_ghost_cache(font_store)
            redraw = True
            if board is not None:
                board.set_colors(FG, GHOST)
            log("period -> %s fg=%s brightness=%d" % (period, FG, active_brightness))

        blink_on = (not blink_enabled) or (int(now * 1000) // blink_ms) % 2 == 0
        if blink_on != was_blink_on:
            redraw = True
        was_blink_on = blink_on

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
        # Afterglow keeps changing after the flap settles; keep redrawing.
        glowing = afterglow_on and any(d.glow_char is not None for d in digits)
        if was_animating and not animating:
            redraw = True
        was_animating = animating

        if board is not None and not weather_only:
            elapsed = now - scene_start
            if scene == "clock" and elapsed >= clock_seconds:
                scene, scene_start, redraw = "weather", now, True
                board.invalidate()
                log("scene -> weather")
            elif scene == "weather" and elapsed >= weather_seconds:
                scene, scene_start, redraw = "clock", now, True
                log("scene -> clock")

        if scene == "weather" and board is not None:
            if board.draw(screen, now):
                pygame.display.flip()
            # Force a full repaint when the clock comes back.
            redraw = True
            if os.environ.get("WB_SNAP_WEATHER") and not weather_snap_done:
                pygame.image.save(screen, "/tmp/wb_snap_weather.png")
                weather_snap_done = True
                log("weather snapshot saved")
        elif redraw or animating or glowing:
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
                    dot = max(6, colon_w // 3)
                    colon_color = FG if blink_on else BG
                    pygame.draw.rect(
                        screen, colon_color,
                        pygame.Rect(
                            cx - dot // 2,
                            digit_y + int(digit_h * 0.36) - dot // 2,
                            dot, dot,
                        ),
                    )
                    pygame.draw.rect(
                        screen, colon_color,
                        pygame.Rect(
                            cx - dot // 2,
                            digit_y + int(digit_h * 0.74) - dot // 2,
                            dot, dot,
                        ),
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
    except Exception as exc:
        log("ERROR: %r" % exc)
        raise
