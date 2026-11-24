#!/usr/bin/env python3
"""Weather board for the WB screensaver (480x320).

Layout: e-ink style date/time header, a dashed panel with the current
condition icon, and a right-hand column with temperature and humidity.
Numbers use DSEG7, icons come from the bundled Weather Icons font
(erikflowers/weather-icons, SIL OFL 1.1) rendered by codepoint.

Data sources, in order:
  1. wttr.in         (no key, reachable without a proxy)
  2. Open-Meteo      (no key; tries the proxy from WB_WEATHER_PROXY)
  3. ~/.cache/wb-weather.json   (last good reading)

Location comes from weather.conf next to this file, falling back to an
IP lookup so the board still works out of the box.
"""
import datetime
import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request

import pygame
import pygame.freetype

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_FONT = os.path.join(HERE, "fonts", "weathericons-regular-webfont.ttf")
DSEG_FONT = "/usr/share/fonts/truetype/dseg7-classic/dseg7-classic-latin-700-normal.ttf"
LABEL_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TEXT_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
CJK_FONT = "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"
CACHE_PATH = os.path.expanduser("~/.cache/wb-weather.json")
CONF_PATH = os.path.join(HERE, "weather.conf")

REFRESH_SECONDS = 600

# Weather Icons codepoints (see css/weather-icons.css in the upstream repo).
ICONS = {
    "sunny": 0xF00D,
    "partly": 0xF002,
    "cloudy": 0xF013,
    "cloud": 0xF041,
    "rain": 0xF019,
    "showers": 0xF01A,
    "thunder": 0xF01E,
    "snow": 0xF01B,
    "fog": 0xF014,
    "sleet": 0xF017,
    "night_clear": 0xF02E,
    "night_cloudy": 0xF031,
    "wind": 0xF050,
    "thermometer": 0xF055,
}

# ------------------------------------------------------------------ palettes
# "dark" reproduces the reference mock pixel for pixel: near-black warm
# background, saturated amber ink at 100 % (the screensaver's 85 % day
# brightness is for the clock only, it made the board look muddy), dim amber
# for secondary text and dark brown for the dashed rules.
# "paper" is the kraft-paper mock; "paper-light" a lighter cream variant.
PALETTES = {
    "dark": {
        "bg": (10, 7, 4),
        "ink": (255, 164, 43),
        "label": (255, 164, 43),
        "dim": (196, 122, 30),
        "rule": (110, 66, 16),
        "ghost": (46, 22, 0),
    },
    "paper": {
        "bg": (201, 106, 30),
        "ink": (24, 11, 2),
        "label": (24, 11, 2),
        "dim": (88, 44, 10),
        "rule": (60, 28, 8),
        "ghost": (176, 88, 24),
    },
    "paper-light": {
        "bg": (238, 222, 198),
        "ink": (38, 24, 12),
        "label": (128, 96, 64),
        "dim": (128, 96, 64),
        "rule": (162, 132, 102),
        "ghost": (206, 186, 158),
    },
}
THEMES = tuple(PALETTES)

# canonical condition -> (Chinese label, icon key)
CONDITIONS = {
    "sunny": ("晴", "sunny"),
    "partly": ("多云", "partly"),
    "cloudy": ("阴", "cloudy"),
    "rain": ("雨", "rain"),
    "showers": ("阵雨", "showers"),
    "thunder": ("雷阵雨", "thunder"),
    "snow": ("雪", "snow"),
    "sleet": ("雨夹雪", "sleet"),
    "fog": ("雾", "fog"),
}


def log(message):
    path = os.path.join(HERE, "screensaver.log")
    try:
        with open(path, "a") as fh:
            fh.write("%s [weather] %s\n" % (datetime.datetime.now().strftime("%F %T"), message))
    except OSError:
        pass


# ---------------------------------------------------------------- conditions
def from_wwo(code):
    """Map a WorldWeatherOnline condition code (wttr.in) to a canonical key."""
    if code == 113:
        return "sunny"
    if code == 116:
        return "partly"
    if code in (119, 122):
        return "cloudy"
    if code in (143, 248, 260):
        return "fog"
    if code in (200, 386, 389, 392, 395):
        return "thunder" if code == 200 else "sleet"
    if code in (179, 182, 185, 281, 284, 311, 314, 317, 320, 350, 362, 365, 374, 377):
        return "sleet"
    if code in (227, 230, 323, 326, 329, 332, 335, 338, 368, 371):
        return "snow"
    if code in (176, 263, 266, 293, 296, 299, 302, 305, 308, 353, 356, 359):
        return "rain"
    return "partly"


def from_wmo(code):
    """Map a WMO weather code (Open-Meteo) to a canonical key."""
    if code == 0:
        return "sunny"
    if code == 1:
        return "partly"
    if code == 2:
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if code in (51, 53, 55, 56, 57):
        return "rain"
    if code in (61, 63, 65, 80, 81, 82):
        return "rain"
    if code in (66, 67):
        return "sleet"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code in (95, 96, 99):
        return "thunder"
    return "partly"


# ------------------------------------------------------------------- helpers
def load_conf(path=CONF_PATH):
    """Read KEY=VALUE lines; unknown keys are ignored."""
    conf = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                conf[key.strip().upper()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return conf


def _http_get(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "wb-screensaver/1.0"})
    opener = urllib.request.build_opener()
    proxy = os.environ.get("WB_WEATHER_PROXY") or os.environ.get("https_proxy")
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    finally:
        opener.close()


def detect_location():
    """IP-based fallback so a fresh install still shows something useful."""
    try:
        raw = _http_get(
            "http://ip-api.com/json/?lang=zh-CN&fields=status,country,regionName,city,lat,lon",
            6,
        )
        data = json.loads(raw)
        if data.get("status") == "success":
            return {
                "city": data.get("city") or data.get("regionName") or "",
                "lat": float(data["lat"]),
                "lon": float(data["lon"]),
            }
    except Exception as exc:  # noqa: BLE001 - network shape varies a lot
        log("ip lookup failed: %r" % exc)
    return {}


def fetch_wttr(lat, lon):
    url = "https://wttr.in/%s,%s?format=j1&lang=zh-cn" % (round(lat, 3), round(lon, 3))
    data = json.loads(_http_get(url, 20))
    current = data["current_condition"][0]
    today = data["weather"][0]
    return {
        "temp": int(round(float(current["temp_C"]))),
        "feels": int(round(float(current["FeelsLikeC"]))),
        "humidity": int(current["humidity"]),
        "cond": from_wwo(int(current["weatherCode"])),
        "tmax": int(today["maxtempC"]),
        "tmin": int(today["mintempC"]),
        "wind": int(round(float(current.get("windspeedKmph", 0)))),
        "source": "wttr.in",
        "fetched": time.time(),
    }


def fetch_open_meteo(lat, lon):
    query = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
        "forecast_days": 1,
    })
    data = json.loads(_http_get("https://api.open-meteo.com/v1/forecast?" + query, 12))
    current = data["current"]
    daily = data["daily"]
    return {
        "temp": int(round(current["temperature_2m"])),
        "feels": int(round(current["apparent_temperature"])),
        "humidity": int(round(current["relative_humidity_2m"])),
        "cond": from_wmo(int(current["weather_code"])),
        "tmax": int(round(daily["temperature_2m_max"][0])),
        "tmin": int(round(daily["temperature_2m_min"][0])),
        "wind": int(round(current.get("wind_speed_10m", 0) or 0)),
        "source": "open-meteo",
        "fetched": time.time(),
    }


def read_cache(path=CACHE_PATH):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if "temp" in data and "fetched" in data:
            return data
    except (OSError, ValueError):
        pass
    return None


def write_cache(data, path=CACHE_PATH):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as exc:
        log("cache write failed: %r" % exc)


# ------------------------------------------------------------------- service
class WeatherService(threading.Thread):
    """Refresh weather in the background; the renderer never blocks on I/O."""

    def __init__(self, conf=None, interval=REFRESH_SECONDS):
        super().__init__(daemon=True)
        conf = load_conf() if conf is None else conf
        self.interval = interval
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

        city = conf.get("CITY", "")
        lat = conf.get("LAT", "")
        lon = conf.get("LON", "")
        self.lat = float(lat) if lat else None
        self.lon = float(lon) if lon else None
        self.city = city
        self.data = read_cache()
        if self.data and self.city and self.data.get("city") != self.city:
            # The cache belongs to another city (weather.conf was edited), so its
            # numbers would be wrong on screen. Drop it and wait for the refresh.
            log("cache is for %r, expected %r - ignoring" % (self.data.get("city"), self.city))
            self.data = None
        if self.data and not self.city:
            self.city = self.data.get("city", "")
        self.note = "cache" if self.data else "no data"

    # -- location
    def _ensure_location(self):
        if self.lat is not None and self.lon is not None:
            return True
        found = detect_location()
        if not found:
            return False
        self.lat = found["lat"]
        self.lon = found["lon"]
        self.city = self.city or found.get("city", "")
        log("location auto-detected: %s (%s, %s)" % (self.city, self.lat, self.lon))
        return True

    # -- fetching
    def refresh(self):
        if not self._ensure_location():
            self.note = "no location"
            return None
        attempts = (
            ("wttr.in", fetch_wttr),
            ("open-meteo", fetch_open_meteo),
        )
        for name, func in attempts:
            try:
                data = func(self.lat, self.lon)
                data["city"] = self.city
                self.note = name
                return data
            except Exception as exc:  # noqa: BLE001 - any failure means "try next"
                self.note = "%s failed" % name
                log("%s: %r" % (name, exc))
        return None

    def run(self):
        first = True
        while not self.stop_event.is_set():
            data = self.refresh()
            if data:
                with self.lock:
                    self.data = data
                write_cache(data)
                log("updated %s %s°C %s%%RH via %s" % (
                    CONDITIONS.get(data["cond"], ("?",))[0],
                    data["temp"], data["humidity"], data["source"],
                ))
            elif first and self.data:
                self.note = "cache"
            first = False
            self.stop_event.wait(self.interval)

    def snapshot(self):
        with self.lock:
            return dict(self.data) if self.data else None

    def stop(self):
        self.stop_event.set()


# ------------------------------------------------------------------ drawing
_font_cache = {}


def font(path, size):
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = pygame.freetype.Font(path, size)
    return _font_cache[key]


def text_size(path, size, text):
    rect = font(path, size).get_rect(text)
    return rect.width, rect.height


def draw_text(surface, path, size, text, xy, color, align="left"):
    """Blit a whole string; align against its ink box (left / center / right)."""
    try:
        glyph, _ = font(path, size).render(text, color)
    except Exception:
        return 0, 0
    width, height = glyph.get_size()
    x, y = xy
    if align == "right":
        x -= width
    elif align == "center":
        x -= width // 2
    surface.blit(glyph, (int(x), int(y)))
    return width, height


def _is_cjk(char):
    return ord(char) > 0x2E80


def _runs(text):
    """Split a string into (run, is_cjk) chunks so each gets the right font."""
    chunks = []
    for char in text:
        cjk = _is_cjk(char)
        if chunks and chunks[-1][1] == cjk:
            chunks[-1] = (chunks[-1][0] + char, cjk)
        else:
            chunks.append((char, cjk))
    return chunks


def draw_mixed(surface, text, xy, size, color):
    """Draw Chinese with the fallback font and Latin/digits with DejaVu."""
    x, y = xy
    start = x
    for run, is_cjk in _runs(text):
        path = CJK_FONT if is_cjk else TEXT_FONT
        width, _ = draw_text(surface, path, size, run, (x, y), color)
        x += width
    return x - start


def draw_dseg(surface, text, xy, size, color, ghost=None, align="left"):
    """Seven-segment number with optional dim ghost strokes underneath."""
    try:
        glyph, _ = font(DSEG_FONT, size).render(text, color)
    except Exception:
        return 0, 0
    width, height = glyph.get_size()
    x, y = xy
    if align == "right":
        x -= width
    elif align == "center":
        x -= width // 2
    if ghost is not None:
        try:
            dim, _ = font(DSEG_FONT, size).render(text, ghost)
            surface.blit(dim, (int(x), int(y)))
        except Exception:
            pass
    surface.blit(glyph, (int(x), int(y)))
    return width, height


def fit_size(path, text, max_w, max_h, start, low=10):
    size = start
    while size > low:
        width, height = text_size(path, size, text)
        if width <= max_w and height <= max_h:
            return size
        size -= 1
    return low


def draw_icon(surface, key, center, size, color):
    """Blit a Weather Icons glyph centred on its ink box.

    render() returns the tight glyph surface, which is what we want: get_rect()
    reports the font's tall layout box, and centring on that pushes the icon
    well above the requested point.
    """
    code = ICONS.get(key)
    if code is None:
        return
    try:
        glyph, _ = font(ICON_FONT, size).render(chr(code), color)
    except Exception as exc:  # noqa: BLE001
        log("icon %s failed: %r" % (key, exc))
        return
    width, height = glyph.get_size()
    surface.blit(glyph, (int(center[0] - width // 2), int(center[1] - height // 2)))


def _round_rect_path(rect, radius, step=2.0):
    """Sample the outline of a rounded rectangle so it can be dashed."""
    x0, y0, x1, y1 = rect
    r = max(0, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
    points = []

    def line(a, b):
        ax, ay = a
        bx, by = b
        count = max(1, int(math.hypot(bx - ax, by - ay) / step))
        for i in range(count + 1):
            points.append((ax + (bx - ax) * i / count, ay + (by - ay) * i / count))

    def arc(cx, cy, a0, a1):
        if r <= 0:
            return
        count = max(2, int(abs(a1 - a0) * r / step))
        for i in range(count + 1):
            angle = a0 + (a1 - a0) * i / count
            points.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))

    if r <= 0:
        line((x0, y0), (x1, y0))
        line((x1, y0), (x1, y1))
        line((x1, y1), (x0, y1))
        line((x0, y1), (x0, y0))
        return points

    line((x0 + r, y0), (x1 - r, y0))
    arc(x1 - r, y0 + r, -math.pi / 2, 0)
    line((x1, y0 + r), (x1, y1 - r))
    arc(x1 - r, y1 - r, 0, math.pi / 2)
    line((x1 - r, y1), (x0 + r, y1))
    arc(x0 + r, y1 - r, math.pi / 2, math.pi)
    line((x0, y1 - r), (x0, y0 + r))
    arc(x0 + r, y0 + r, math.pi, math.pi * 1.5)
    return points


def dashed_round_rect(surface, rect, color, width=2, radius=12, dash=9, gap=7):
    points = _round_rect_path(rect, radius)
    period = dash + gap
    offset = 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg <= 0:
            continue
        phase = offset % period
        if phase + seg <= dash:
            pygame.draw.line(surface, color, a, b, width)
        elif phase < dash:
            t = (dash - phase) / seg
            mid = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            pygame.draw.line(surface, color, a, mid, width)
        offset += seg


class WeatherBoard:
    """Renders the board onto the screen; re-renders once per minute or refresh."""

    def __init__(self, size, fg, ghost, theme="dark", service=None, brightness=100):
        self.width, self.height = size
        self.base = fg          # configured WB_COLOR, before brightness scaling
        self.ghost = ghost      # kept for API compatibility; palettes own the ghost
        self.brightness = max(0, min(100, brightness))
        self.theme = theme if theme in PALETTES else "dark"
        self.service = service
        self._cache_surface = None
        self._cache_key = None
        self._last_render = 0.0

    # -- appearance
    @property
    def colors(self):
        """Resolved palette; the dark theme follows WB_COLOR and brightness."""
        palette = dict(PALETTES[self.theme])
        if self.theme == "dark":
            scale = self.brightness / 100.0
            ink = tuple(int(c * scale + 0.5) for c in self.base)
            palette["ink"] = ink
            palette["label"] = ink
            palette["dim"] = tuple(
                int(c * k + 0.5) for c, k in zip(ink, (0.77, 0.75, 0.70))
            )
            palette["rule"] = tuple(
                int(c * k + 0.5) for c, k in zip(ink, (0.43, 0.40, 0.37))
            )
            palette["ghost"] = tuple(int(c * scale + 0.5) for c in (46, 22, 0))
        return palette

    @property
    def bg(self):
        return self.colors["bg"]

    @property
    def ink(self):
        return self.colors["ink"]

    @property
    def ghost_color(self):
        return self.colors["ghost"]

    def set_colors(self, fg, ghost=None):
        if fg != self.base:
            self.base = fg
            self._cache_key = None
        if ghost is not None:
            self.ghost = ghost

    def set_brightness(self, brightness):
        brightness = max(0, min(100, int(brightness)))
        if brightness != self.brightness:
            self.brightness = brightness
            self._cache_key = None

    def set_theme(self, theme):
        theme = theme if theme in PALETTES else "dark"
        if theme != self.theme:
            self.theme = theme
            self._cache_key = None

    def set_service(self, service):
        self.service = service
        self._cache_key = None

    # -- rendering
    def _data(self):
        return self.service.snapshot() if self.service else None

    def invalidate(self):
        """Force the next draw() to repaint (used when entering the scene)."""
        self._cache_key = None

    def draw(self, screen, now=None):
        """Repaint only when the minute, the data or the colours changed.

        The renderer runs at 20 fps, so the key must be stable across frames.
        Hashing the payload (rather than id() of a fresh dict) keeps the cache
        hot and leaves the board at a single blit instead of 20 renders/s.
        """
        data = self._data()
        if data:
            signature = (
                data.get("fetched"), data.get("temp"), data.get("feels"),
                data.get("humidity"), data.get("cond"), data.get("tmax"),
                data.get("tmin"), data.get("wind"), data.get("city"),
            )
        else:
            signature = None
        stamp = datetime.datetime.now().strftime("%Y%m%d%H%M")
        key = (stamp, signature, self.theme, self.brightness, self.base)
        if key == self._cache_key and self._cache_surface is not None:
            return False
        surface = self._render(data)
        self._cache_surface = surface
        self._cache_key = key
        screen.blit(surface, (0, 0))
        return True

    def _render(self, data):
        surface = pygame.Surface((self.width, self.height))
        colors = self.colors
        surface.fill(colors["bg"])
        ink, dim, rule, label_c = colors["ink"], colors["dim"], colors["rule"], colors["label"]
        ghost = colors["ghost"]
        pad = 14
        right = self.width - pad

        now = datetime.datetime.now()
        date_text = now.strftime("%Y-%m-%d")
        time_text = now.strftime("%H:%M")

        # ---- header
        draw_text(surface, LABEL_FONT, 10, "DATE", (pad, 5), label_c)
        date_size = fit_size(DSEG_FONT, date_text, 236, 30, 34)
        draw_dseg(surface, date_text, (pad, 20), date_size, ink, ghost)

        draw_text(surface, LABEL_FONT, 10, "TIME", (right, 5), label_c, align="right")
        time_size = fit_size(DSEG_FONT, time_text, 110, 32, 36)
        draw_dseg(surface, time_text, (right, 18), time_size, ink, ghost, align="right")

        # ---- dashed panel
        box = (pad, 84, 302, 252)
        dashed_round_rect(surface, box, rule, width=2, radius=12, dash=9, gap=7)

        cond_key = (data or {}).get("cond", "cloud")
        label, icon_key = CONDITIONS.get(cond_key, ("--", cond_key))
        # Centre the glyph further inside the dashed box: the widest icon
        # (partly = sun + cloud, 1.4x a square glyph) used to reach the left
        # border, and 96 px keeps even that one clear of the dashes.
        draw_icon(surface, icon_key, (94, 168), 88, ink)

        draw_text(surface, CJK_FONT, 30, label, (172, 104), ink)

        if data:
            draw_mixed(surface, "体感 %d°" % data["feels"], (172, 158), 14, dim)
            draw_mixed(surface, "今日 %d° ~ %d°" % (data["tmin"], data["tmax"]),
                       (172, 186), 14, dim)
            draw_mixed(surface, "风 %d km/h" % data.get("wind", 0), (172, 214), 14, dim)

        # ---- right column
        draw_text(surface, LABEL_FONT, 10, "TEMPERATURE", (right, 84), label_c, align="right")
        ty = 100
        unit_w, unit_h = text_size(LABEL_FONT, 14, "°C")
        num_right = right - unit_w - 4
        if data:
            temp_text = "%d" % data["temp"]
            temp_size = fit_size(DSEG_FONT, temp_text, 92, 56, 58)
            _, th = draw_dseg(surface, temp_text, (num_right, ty), temp_size, ink,
                              ghost, align="right")
        else:
            _, th = draw_dseg(surface, "--", (num_right, ty + 8), 52, ink,
                              ghost, align="right")
        draw_text(surface, LABEL_FONT, 14, "°C", (num_right + 4, ty + th - unit_h), dim)

        draw_text(surface, LABEL_FONT, 10, "HUMIDITY", (right, 184), label_c, align="right")
        hy = 200
        unit2_w, unit2_h = text_size(LABEL_FONT, 11, "%RH")
        num2_right = right - unit2_w - 4
        if data:
            hum_text = "%d" % data["humidity"]
            hum_size = fit_size(DSEG_FONT, hum_text, 76, 42, 46)
            _, hh = draw_dseg(surface, hum_text, (num2_right, hy), hum_size, ink,
                              ghost, align="right")
        else:
            _, hh = draw_dseg(surface, "--", (num2_right, hy), 38, ink,
                              ghost, align="right")
        draw_text(surface, LABEL_FONT, 11, "%RH", (num2_right + 4, hy + hh - unit2_h), dim)

        # ---- footer
        city = (data or {}).get("city") or (self.service.city if self.service else "")
        if data:
            stamp = datetime.datetime.fromtimestamp(data["fetched"]).strftime("%H:%M")
            footer = "%s · %s 更新" % (city or "本地", stamp)
        else:
            footer = "等待天气数据…"
        draw_mixed(surface, footer, (pad, 272), 12, dim)

        source = (data or {}).get("source", "")
        if source:
            draw_text(surface, TEXT_FONT, 11, source, (right, 273), rule, align="right")
        return surface


# ------------------------------------------------------------------- preview
def _preview(out_path, theme="dark", size=(480, 320)):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    pygame.freetype.init()
    service = WeatherService()
    data = service.refresh() or read_cache()
    if data is None:
        data = {"temp": 9, "feels": 5, "humidity": 22, "cond": "sunny",
                "tmax": 9, "tmin": 0, "source": "sample", "fetched": time.time()}

    class _Stub:
        city = data.get("city", "本地")

        @staticmethod
        def snapshot():
            return data

    board = WeatherBoard(size, (255, 164, 43), (42, 20, 0), theme=theme, service=_Stub())
    surface = board._render(data)
    pygame.image.save(surface, out_path)
    print("saved", out_path, surface.get_size(), data)


if __name__ == "__main__":
    import sys

    out = "/tmp/wb-weather.png"
    th = "dark"
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--out" and i + 1 < len(argv):
            out = argv[i + 1]
        elif arg == "--theme" and i + 1 < len(argv):
            th = argv[i + 1]
    _preview(out, th)
