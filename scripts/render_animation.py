#!/usr/bin/env python3
"""Render "Ayesha Learns Bismillah" as 21 animated 9:16 clips (2D, Cairo + ffmpeg).

Usage:
    python3 scripts/render_animation.py projects/ayesha-learns-bismillah
    python3 scripts/render_animation.py projects/ayesha-learns-bismillah --shots 2.1 3.2
    python3 scripts/render_animation.py projects/ayesha-learns-bismillah --preview   # PNG stills only
    python3 scripts/render_animation.py projects/ayesha-learns-bismillah --no-subs   # clean clips

Outputs <project>/build/animation/clips/<shot>.mp4 (1080x1920, 24fps, ambience audio)
and <project>/build/animation/ayesha_learns_bismillah_animated_9x16.mp4.

Characters, rooms, mouths (synced to the subtitle timing in shots.json), Urdu
subtitles, Arabic overlays and ambience sound are all generated in code.
There are no voices: record them from build/VOICE_SCRIPT.md and lay them on top.
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import wave
from functools import lru_cache
from multiprocessing import Pool

import cairo
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, HGT, FPS = 1080, 1920, 24
FLOOR = 1450          # world y of the floor line
TABLE_Y = 1300        # world y of the dining table top
COUNTER_Y = 1080      # world y of the kitchen counter top
FONT_DIR = "/usr/share/fonts/truetype/noto"
URDU = f"{FONT_DIR}/NotoNastaliqUrdu-Regular.ttf"
URDU_B = f"{FONT_DIR}/NotoNastaliqUrdu-Bold.ttf"
ARABIC = f"{FONT_DIR}/NotoNaskhArabic-Bold.ttf"
LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

PEOPLE = {
    "ayesha": dict(H=560, head=(0.074, 0.093), skin="#F2D3BD", shade="#E2B79D",
                   iris="#A3713F", brow="#4A2E1C", lips="#E29A9B",
                   hijab="#F4B8CA", hijab_dk="#E39AB1", kameez="#F7C6D4",
                   sleeve="#F2B7C8", trim="#FFFFFF", shalwar="#FBDCE4", shoe="#C9768F",
                   blush=0.22),
    "mother": dict(H=740, head=(0.067, 0.087), skin="#DDB08C", shade="#C8977A",
                   iris="#5B3A22", brow="#2E1E14", lips="#C7837A",
                   hijab="#D9C4A4", hijab_dk="#C2A983", kameez="#EFE4D1",
                   sleeve="#E6D8C0", trim="#B89A70", shalwar="#E4D6BC", shoe="#8A6A4A",
                   blush=0.10),
}
LABELS = {"ayesha": ("عائشہ", "#F48FB1"), "mother": ("ماما", "#E8C98E"),
          "narrator": ("راوی", "#9FD3C7")}


# ----------------------------------------------------------------- helpers
def rgba(h, a=1.0):
    h = h.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


def setc(ctx, h, a=1.0):
    ctx.set_source_rgba(*rgba(h, a))


def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def lerp(a, b, x):
    return a + (b - a) * x


def seg(t, t0, t1):
    return ease((t - t0) / (t1 - t0))


def keys(t, kf):
    """Eased keyframe interpolation. kf = [(time, value-or-tuple), ...]."""
    if t <= kf[0][0]:
        return kf[0][1]
    for (t0, v0), (t1, v1) in zip(kf, kf[1:]):
        if t <= t1:
            x = ease((t - t0) / (t1 - t0))
            if isinstance(v0, tuple):
                return tuple(lerp(a, b, x) for a, b in zip(v0, v1))
            return lerp(v0, v1, x)
    return kf[-1][1]


def ellipse(ctx, cx, cy, rx, ry):
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(max(rx, 0.01), max(ry, 0.01))
    ctx.new_sub_path()
    ctx.arc(0, 0, 1, 0, 2 * math.pi)
    ctx.restore()


def rrect(ctx, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    ctx.close_path()


def fill(ctx, color, a=1.0):
    setc(ctx, color, a)
    ctx.fill()


def box(ctx, x, y, w, h, color, a=1.0):
    ctx.rectangle(x, y, w, h)
    fill(ctx, color, a)


def stroke(ctx, color, width, a=1.0):
    setc(ctx, color, a)
    ctx.set_line_width(width)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()


def vgrad(ctx, x, y, w, h, top, bottom):
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgba(0, *rgba(top))
    g.add_color_stop_rgba(1, *rgba(bottom))
    ctx.rectangle(x, y, w, h)
    ctx.set_source(g)
    ctx.fill()


def ik(sx, sy, tx, ty, l1, l2, bend):
    """Two-bone IK: returns (elbow, hand)."""
    dx, dy = tx - sx, ty - sy
    d = math.hypot(dx, dy)
    d = max(abs(l1 - l2) + 1, min(d, l1 + l2 - 0.5))
    a = math.atan2(dy, dx)
    cb = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)
    b = math.acos(max(-1.0, min(1.0, cb)))
    ex, ey = sx + l1 * math.cos(a + bend * b), sy + l1 * math.sin(a + bend * b)
    return (ex, ey), (sx + d * math.cos(a), sy + d * math.sin(a))


# ----------------------------------------------------------------- text
def pil_to_surface(img):
    arr = np.asarray(img.convert("RGBA")).astype(np.float32)
    a = arr[..., 3:4] / 255.0
    rgb = arr[..., :3] * a
    bgra = np.dstack([rgb[..., 2], rgb[..., 1], rgb[..., 0], arr[..., 3]]).astype(np.uint8)
    h, w = bgra.shape[:2]
    buf = bytearray(np.ascontiguousarray(bgra).tobytes())
    surf = cairo.ImageSurface.create_for_data(buf, cairo.FORMAT_ARGB32, w, h, w * 4)
    return surf, buf


@lru_cache(maxsize=None)
def font(path, size):
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)


def rtl(path):
    return path in (URDU, URDU_B, ARABIC)


def wrap(text, path, size, maxw):
    f = font(path, size)
    kw = dict(direction="rtl", language="ur") if rtl(path) else {}
    out = []
    for para in text.split("\n"):
        words, line = para.split(" "), ""
        for wd in words:
            cand = (line + " " + wd).strip()
            if line and f.getlength(cand, **kw) > maxw:
                out.append(line)
                line = wd
            else:
                line = cand
        out.append(line)
    return out


@lru_cache(maxsize=None)
def text_panel(rows, panel=None, pad=(36, 18), maxw=960, glow=None):
    """rows: tuple of (text, font_path, size, hex color). Returns (surface, buf, w, h)."""
    lines = []
    for text, path, size, color in rows:
        for ln in wrap(text, path, size, maxw):
            lines.append((ln, path, size, color))
    metrics = []
    for ln, path, size, color in lines:
        kw = dict(direction="rtl", language="ur" if path != ARABIC else "ar") if rtl(path) else {}
        bb = font(path, size).getbbox(ln, **kw)
        metrics.append((bb, kw))
    widths = [bb[2] - bb[0] for bb, _ in metrics]
    heights = [bb[3] - bb[1] for bb, _ in metrics]
    gap = 14
    wpx = int(max(widths) + 2 * pad[0])
    hpx = int(sum(heights) + gap * (len(lines) - 1) + 2 * pad[1])
    img = Image.new("RGBA", (wpx, hpx), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if panel:
        col, alpha = panel
        r, g, b, _ = [int(v * 255) for v in rgba(col)]
        d.rounded_rectangle([0, 0, wpx - 1, hpx - 1], radius=28, fill=(r, g, b, int(alpha * 255)))
    y = pad[1]
    for (ln, path, size, color), (bb, kw), w_, h_ in zip(lines, metrics, widths, heights):
        x = (wpx - w_) / 2 - bb[0]
        c = tuple(int(v * 255) for v in rgba(color)[:3])
        if glow:
            gc = tuple(int(v * 255) for v in rgba(glow)[:3])
            for ox, oy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, 2), (-2, 2), (2, -2)):
                d.text((x + ox, y - bb[1] + oy), ln, font=font(path, size), fill=gc, **kw)
        d.text((x, y - bb[1]), ln, font=font(path, size), fill=c, **kw)
        y += h_ + gap
    surf, buf = pil_to_surface(img)
    return surf, buf, wpx, hpx


def blit(ctx, panel, cx, cy, alpha):
    surf, _, w, h = panel
    ctx.save()
    ctx.identity_matrix()
    ctx.set_source_surface(surf, cx - w / 2, cy - h / 2)
    ctx.paint_with_alpha(max(0.0, min(1.0, alpha)))
    ctx.restore()


# ----------------------------------------------------------------- people
def draw_person(ctx, a, t):
    s = PEOPLE[a["kind"]]
    H = s["H"]
    rx, ry = s["head"][0] * H, s["head"][1] * H
    x0 = a["x"]
    y0 = a.get("y", FLOOR) + a.get("sit", 0.0) * 0.25 * H
    walk = a.get("walk")
    bob = -abs(math.sin(walk)) * 0.012 * H if walk is not None else 0.0
    breath = math.sin(t * 1.6 + (0 if a["kind"] == "ayesha" else 1.3)) * 0.0025 * H
    ctx.save()
    ctx.translate(x0, y0 + bob)
    oy = y0 + bob

    lean = a.get("lean", 0.0)
    nod = a.get("nod", 0.0)
    tilt = math.radians(a.get("tilt", 0.0))
    hx = 0.0
    hy = -0.885 * H + lean * 0.045 * H + nod * 0.012 * H + breath

    # legs + shoes ---------------------------------------------------
    swing = 0.32 * math.sin(walk) if walk is not None else 0.0
    for side, sw in ((-1, swing), (1, -swing)) if a.get("sit", 0.0) < 0.5 else ():
        ctx.save()
        ctx.translate(side * 0.055 * H, -0.31 * H)
        ctx.rotate(sw * 0.8)
        ctx.move_to(-0.05 * H, 0)
        ctx.line_to(0.05 * H, 0)
        ctx.curve_to(0.06 * H, 0.12 * H, 0.04 * H, 0.22 * H, 0.03 * H, 0.27 * H)
        ctx.line_to(-0.03 * H, 0.27 * H)
        ctx.curve_to(-0.04 * H, 0.22 * H, -0.06 * H, 0.12 * H, -0.05 * H, 0)
        fill(ctx, s["shalwar"])
        ctx.move_to(-0.03 * H, 0.255 * H)
        ctx.line_to(0.03 * H, 0.255 * H)
        stroke(ctx, s["trim"], 0.01 * H)
        ellipse(ctx, 0.005 * H, 0.283 * H, 0.042 * H, 0.016 * H)
        fill(ctx, s["shoe"])
        ctx.restore()

    # kameez -----------------------------------------------------------
    sway = math.sin(walk) * 0.012 * H if walk is not None else 0.0
    top = -0.70 * H + lean * 0.02 * H
    ctx.move_to(-0.115 * H, top)
    ctx.line_to(0.115 * H, top)
    ctx.curve_to(0.13 * H, -0.55 * H, 0.15 * H, -0.42 * H, 0.16 * H + sway, -0.30 * H)
    ctx.curve_to(0.05 * H, -0.29 * H, -0.05 * H, -0.29 * H, -0.16 * H + sway, -0.30 * H)
    ctx.curve_to(-0.15 * H, -0.42 * H, -0.13 * H, -0.55 * H, -0.115 * H, top)
    fill(ctx, s["kameez"])
    # hem trim + small white embroidery dots
    ctx.move_to(-0.155 * H + sway, -0.312 * H)
    ctx.curve_to(-0.05 * H, -0.302 * H, 0.05 * H, -0.302 * H, 0.155 * H + sway, -0.312 * H)
    stroke(ctx, s["trim"], 0.011 * H, 0.9)
    rnd = random.Random(7 if a["kind"] == "ayesha" else 11)
    for _ in range(16):
        px = rnd.uniform(-0.12, 0.12) * H
        py = rnd.uniform(-0.56, -0.34) * H
        for k in range(5):
            ang = k * 2 * math.pi / 5
            ellipse(ctx, px + math.cos(ang) * 0.006 * H, py + math.sin(ang) * 0.006 * H,
                    0.0035 * H, 0.0035 * H)
        fill(ctx, s["trim"], 0.75)
    # side slits
    for side in (-1, 1):
        ctx.move_to(side * 0.148 * H, -0.36 * H)
        ctx.line_to(side * 0.157 * H, -0.305 * H)
        stroke(ctx, s["sleeve"], 0.006 * H)

    # hijab back + drape -----------------------------------------------
    ctx.save()
    ctx.translate(hx, -0.80 * H + lean * 0.04 * H)
    ctx.rotate(tilt * 0.6)
    ctx.translate(0, hy - (-0.80 * H + lean * 0.04 * H))
    ellipse(ctx, 0, -0.07 * ry, rx * 1.45, ry * 1.30)
    fill(ctx, s["hijab"])
    ctx.restore()
    ctx.move_to(-rx * 1.30, hy + 0.35 * ry)
    ctx.curve_to(-rx * 1.6, -0.70 * H, -0.20 * H, -0.66 * H, -0.19 * H, -0.585 * H)
    ctx.curve_to(-0.08 * H, -0.555 * H, 0.08 * H, -0.555 * H, 0.19 * H, -0.585 * H)
    ctx.curve_to(0.20 * H, -0.66 * H, rx * 1.6, -0.70 * H, rx * 1.30, hy + 0.35 * ry)
    ctx.close_path()
    fill(ctx, s["hijab"])
    for k in (-1, 1):
        ctx.move_to(k * rx * 0.9, hy + 1.25 * ry)
        ctx.curve_to(k * 0.09 * H, -0.66 * H, k * 0.13 * H, -0.62 * H, k * 0.15 * H, -0.585 * H)
        stroke(ctx, s["hijab_dk"], 0.006 * H, 0.8)
    ctx.move_to(-rx * 0.8, hy + 1.32 * ry)
    ctx.curve_to(-0.02 * H, hy + 1.5 * ry, 0.02 * H, hy + 1.5 * ry, rx * 0.8, hy + 1.32 * ry)
    stroke(ctx, s["hijab_dk"], 0.006 * H, 0.7)

    # arms (behind the face so hands near the mouth stay in front) ----
    arm_l1, arm_l2 = 0.165 * H, 0.155 * H
    hands = {}
    for side in ("right", "left"):            # character's right = screen left
        sg = -1 if side == "right" else 1
        sx, sy = sg * 0.105 * H, -0.655 * H + lean * 0.02 * H
        tgt = a.get("arms", {}).get(side)
        if tgt is None:
            if a.get("sit", 0) > 0.5:
                tgt = ("w", x0 + sg * 0.10 * H, TABLE_Y - 6)
            else:
                swing_a = (0.03 * H * math.sin(walk) * -sg) if walk is not None else 0.0
                tgt = ("l", sg * 0.135 + swing_a / H, -0.395 + 0.003 * math.sin(t * 1.6))
        if tgt[0] == "w":
            tx, ty = tgt[1] - x0, tgt[2] - oy
        else:
            tx, ty = tgt[1] * H, tgt[2] * H
        (ex, ey), (hx2, hy2) = ik(sx, sy, tx, ty, arm_l1, arm_l2, 1 if sg < 0 else -1)
        hands[side] = (hx2, hy2, ex, ey, sx, sy)

    def draw_arm(side):
        hx2, hy2, ex, ey, sx, sy = hands[side]
        ctx.move_to(sx, sy)
        ctx.line_to(ex, ey)
        ctx.line_to(hx2, hy2)
        stroke(ctx, s["sleeve"], 0.058 * H)
        # cuff
        dx, dy = hx2 - ex, hy2 - ey
        dl = math.hypot(dx, dy) or 1
        cx_, cy_ = hx2 - dx / dl * 0.03 * H, hy2 - dy / dl * 0.03 * H
        ctx.move_to(cx_ - dy / dl * 0.028 * H, cy_ + dx / dl * 0.028 * H)
        ctx.line_to(cx_ + dy / dl * 0.028 * H, cy_ - dx / dl * 0.028 * H)
        stroke(ctx, s["trim"], 0.012 * H, 0.95)
        hold = a.get("hold", {}).get(side)
        ellipse(ctx, hx2, hy2, 0.024 * H, 0.026 * H)
        fill(ctx, s["skin"])
        ellipse(ctx, hx2 + (0.018 if side == "left" else -0.018) * H, hy2 - 0.008 * H,
                0.009 * H, 0.012 * H)
        fill(ctx, s["skin"])
        ellipse(ctx, hx2, hy2, 0.024 * H, 0.026 * H)
        stroke(ctx, s["shade"], 0.003 * H, 0.6)
        if hold:
            draw_held(ctx, hold, hx2, hy2, H, t)

    # face -------------------------------------------------------------
    ctx.save()
    ctx.translate(hx, -0.80 * H + lean * 0.04 * H)
    ctx.rotate(tilt)
    ctx.translate(0, hy - (-0.80 * H + lean * 0.04 * H))
    draw_face(ctx, s, rx, ry, a, t)
    ctx.restore()

    for side in ("left", "right"):
        draw_arm(side)
    ctx.restore()


def draw_face(ctx, s, rx, ry, a, t):
    expr = a.get("expr", "smile")
    talk = a.get("talk", 0.0)
    blink = a.get("blink", 0.0)
    gx, gy = a.get("gaze", (0.0, 0.0))
    # neck shadow + face
    g = cairo.RadialGradient(-0.15 * rx, -0.2 * ry, 0.1 * rx, 0, 0, 1.1 * ry)
    g.add_color_stop_rgba(0, *rgba(s["skin"]))
    g.add_color_stop_rgba(1, *rgba(s["shade"]))
    ctx.save()
    ctx.translate(0, 0)
    ctx.move_to(0, -ry)
    ctx.curve_to(rx * 0.75, -ry, rx * 1.02, -ry * 0.45, rx * 0.98, 0.05 * ry)
    ctx.curve_to(rx * 0.92, ry * 0.55, rx * 0.45, ry * 0.98, 0, ry)
    ctx.curve_to(-rx * 0.45, ry * 0.98, -rx * 0.92, ry * 0.55, -rx * 0.98, 0.05 * ry)
    ctx.curve_to(-rx * 1.02, -ry * 0.45, -rx * 0.75, -ry, 0, -ry)
    ctx.set_source(g)
    ctx.fill()
    ctx.restore()
    # blush
    for k in (-1, 1):
        ellipse(ctx, k * 0.55 * rx, 0.32 * ry, 0.22 * rx, 0.12 * ry)
        fill(ctx, "#F08A8A", s["blush"] * (1.3 if expr == "happy" else 1.0))

    # brows
    raise_ = {"surprised": 0.16, "curious": 0.08, "thoughtful": 0.05}.get(expr, 0.0)
    inner = {"sad": 0.08, "thoughtful": 0.0}.get(expr, 0.0)
    for k in (-1, 1):
        extra = 0.06 if (expr == "thoughtful" and k == 1) else 0.0
        by = -0.30 * ry - (raise_ + extra) * ry
        ctx.move_to(k * 0.15 * rx, by + 0.04 * ry - inner * ry)
        ctx.curve_to(k * 0.35 * rx, by - 0.07 * ry, k * 0.55 * rx, by - 0.07 * ry,
                     k * 0.70 * rx, by + 0.03 * ry)
        stroke(ctx, s["brow"], 0.075 * rx)

    # eyes (almond)
    open_ = {"surprised": 1.25, "happy": 0.8}.get(expr, 1.0) * (1 - blink)
    for k in (-1, 1):
        cx, cy = k * 0.40 * rx, -0.06 * ry
        ew, eh = 0.27 * rx, 0.115 * rx * max(open_, 0.06)
        ctx.move_to(cx - ew, cy)
        ctx.curve_to(cx - ew * 0.4, cy - eh * 1.6, cx + ew * 0.4, cy - eh * 1.6, cx + ew, cy - eh * 0.1)
        ctx.curve_to(cx + ew * 0.4, cy + eh * 1.15, cx - ew * 0.4, cy + eh * 1.15, cx - ew, cy)
        ctx.close_path()
        if open_ > 0.15:
            ctx.save()
            ctx.clip_preserve()
            fill(ctx, "#FBF7F2")
            ix, iy = cx + gx * ew * 0.38, cy + gy * 0.06 * rx
            ellipse(ctx, ix, iy, 0.125 * rx, 0.125 * rx)
            fill(ctx, s["iris"])
            ellipse(ctx, ix, iy, 0.06 * rx, 0.06 * rx)
            fill(ctx, "#1E120B")
            ellipse(ctx, ix - 0.04 * rx, iy - 0.045 * rx, 0.028 * rx, 0.028 * rx)
            fill(ctx, "#FFFFFF", 0.9)
            ctx.restore()
        else:
            ctx.new_path()
        # upper lid + lashes
        ctx.move_to(cx - ew * 1.02, cy + 0.01 * rx)
        ctx.curve_to(cx - ew * 0.4, cy - eh * 1.6, cx + ew * 0.4, cy - eh * 1.6,
                     cx + ew * 1.05, cy - eh * 0.15)
        stroke(ctx, "#2A1A12", 0.035 * rx)

    # nose
    ctx.move_to(0.03 * rx, 0.10 * ry)
    ctx.curve_to(0.07 * rx, 0.22 * ry, 0.08 * rx, 0.30 * ry, 0.02 * rx, 0.33 * ry)
    stroke(ctx, s["shade"], 0.03 * rx)
    for k in (-1, 1):
        ellipse(ctx, k * 0.075 * rx, 0.335 * ry, 0.035 * rx, 0.018 * ry)
        fill(ctx, s["shade"], 0.8)

    # mouth
    my, mw = 0.58 * ry, 0.27 * rx
    if talk > 0.06:
        oh = (0.05 + 0.17 * talk) * rx
        ctx.move_to(-mw * 0.85, my)
        ctx.curve_to(-mw * 0.4, my - 0.05 * rx, mw * 0.4, my - 0.05 * rx, mw * 0.85, my)
        ctx.curve_to(mw * 0.5, my + oh * 1.4, -mw * 0.5, my + oh * 1.4, -mw * 0.85, my)
        ctx.close_path()
        fill(ctx, "#7A2E2E")
        ctx.move_to(-mw * 0.55, my + 0.005 * rx)
        ctx.line_to(mw * 0.55, my + 0.005 * rx)
        stroke(ctx, "#FFFFFF", 0.035 * rx, 0.85)
        ctx.move_to(-mw * 0.85, my)
        ctx.curve_to(-mw * 0.5, my + oh * 1.4, mw * 0.5, my + oh * 1.4, mw * 0.85, my)
        stroke(ctx, s["lips"], 0.06 * rx)
    elif expr == "surprised":
        ellipse(ctx, 0, my + 0.04 * rx, 0.11 * rx, 0.14 * rx)
        fill(ctx, "#7A2E2E")
        ellipse(ctx, 0, my + 0.04 * rx, 0.11 * rx, 0.14 * rx)
        stroke(ctx, s["lips"], 0.05 * rx)
    elif expr == "happy":
        ctx.move_to(-mw, my - 0.03 * rx)
        ctx.curve_to(-mw * 0.4, my + 0.02 * rx, mw * 0.4, my + 0.02 * rx, mw, my - 0.03 * rx)
        ctx.curve_to(mw * 0.5, my + 0.24 * rx, -mw * 0.5, my + 0.24 * rx, -mw, my - 0.03 * rx)
        ctx.close_path()
        fill(ctx, "#8A3434")
        ctx.move_to(-mw * 0.75, my + 0.0)
        ctx.curve_to(-mw * 0.3, my + 0.05 * rx, mw * 0.3, my + 0.05 * rx, mw * 0.75, my)
        stroke(ctx, "#FFFFFF", 0.05 * rx, 0.9)
    else:
        curve = {"smile": 0.10, "curious": 0.03, "thoughtful": 0.0, "sad": -0.09,
                 "neutral": 0.02, "chew": 0.03}.get(expr, 0.08)
        off = 0.04 * rx if expr == "thoughtful" else 0.0
        w_ = mw * (0.75 if expr in ("curious", "thoughtful", "chew") else 1.0)
        if expr == "chew":
            w_ *= 1 + 0.15 * math.sin(t * 12)
        ctx.move_to(-w_ + off, my - curve * rx * 0.3)
        ctx.curve_to(-w_ * 0.3 + off, my + curve * rx, w_ * 0.3 + off, my + curve * rx,
                     w_ + off, my - curve * rx * 0.3 - (0.03 * rx if expr == "thoughtful" else 0))
        stroke(ctx, s["lips"], 0.06 * rx)
        ellipse(ctx, off, my + 0.07 * rx, w_ * 0.45, 0.03 * rx)
        fill(ctx, s["lips"], 0.35)

    # hijab framing band over hairline / ears
    ctx.save()
    ctx.scale(rx * 1.08, ry * 1.06)
    ctx.arc(0, 0.02, 1.0, math.pi * 0.86, math.pi * 2.14)
    ctx.restore()
    stroke(ctx, s["hijab"], 0.36 * rx)
    ctx.save()
    ctx.scale(rx * 0.93, ry * 0.94)
    ctx.arc(0, 0.02, 1.0, math.pi * 1.05, math.pi * 1.95)
    ctx.restore()
    stroke(ctx, s["hijab_dk"], 0.03 * rx, 0.6)


def draw_held(ctx, what, x, y, H, t):
    u = H / 560.0
    if what == "ladle":
        ctx.move_to(x, y)
        ctx.line_to(x + 8 * u, y + 70 * u)
        stroke(ctx, "#8E8E8E", 6 * u)
        ellipse(ctx, x + 9 * u, y + 74 * u, 14 * u, 7 * u)
        fill(ctx, "#9A9A9A")
    elif what == "knife":
        ctx.move_to(x, y)
        ctx.line_to(x - 10 * u, y + 18 * u)
        stroke(ctx, "#5A3A22", 8 * u)
        ctx.move_to(x - 10 * u, y + 18 * u)
        ctx.line_to(x - 22 * u, y + 56 * u)
        stroke(ctx, "#C9CED3", 9 * u)
    elif what == "roti":
        ellipse(ctx, x, y - 6 * u, 22 * u, 15 * u)
        fill(ctx, "#E2B573")
        ellipse(ctx, x - 6 * u, y - 9 * u, 5 * u, 3 * u)
        fill(ctx, "#B9844A", 0.8)
    elif what == "daal":
        draw_bowl(ctx, x + 30 * u, y + 4 * u, 46 * u, "#E3B23C")
    elif what == "basket":
        draw_roti_basket(ctx, x + 30 * u, y + 4 * u, 1.0)
    elif what == "towel":
        rrect(ctx, x - 20 * u, y - 10 * u, 40 * u, 70 * u, 8 * u)
        fill(ctx, "#FFFFFF")


# ----------------------------------------------------------------- props
def draw_bowl(ctx, cx, base_y, r, food):
    ctx.move_to(cx - r, base_y - r * 0.55)
    ctx.curve_to(cx - r, base_y + r * 0.1, cx + r, base_y + r * 0.1, cx + r, base_y - r * 0.55)
    ctx.close_path()
    fill(ctx, "#FAFAF7")
    ellipse(ctx, cx, base_y - r * 0.55, r, r * 0.22)
    fill(ctx, food)
    ellipse(ctx, cx, base_y - r * 0.55, r, r * 0.22)
    stroke(ctx, "#E2DED6", 3)
    ctx.move_to(cx - r * 0.7, base_y - r * 0.15)
    ctx.curve_to(cx - r * 0.2, base_y - r * 0.05, cx + r * 0.2, base_y - r * 0.05, cx + r * 0.7, base_y - r * 0.15)
    stroke(ctx, "#4E7FA8", 3, 0.7)


def draw_roti_basket(ctx, cx, base_y, k):
    r = 58 * k
    for i in range(3):
        ellipse(ctx, cx + (i - 1) * 6, base_y - r * 0.62 - i * 6, r * 0.85, r * 0.2)
        fill(ctx, "#E6BF7E" if i % 2 == 0 else "#D9AA63")
    ctx.move_to(cx - r, base_y - r * 0.55)
    ctx.line_to(cx + r, base_y - r * 0.55)
    ctx.line_to(cx + r * 0.8, base_y)
    ctx.line_to(cx - r * 0.8, base_y)
    ctx.close_path()
    fill(ctx, "#B88A4E")
    for i in range(6):
        ctx.move_to(cx - r * 0.9 + i * r * 0.36, base_y - r * 0.5)
        ctx.line_to(cx - r * 0.75 + i * r * 0.3, base_y - 3)
        stroke(ctx, "#8E6634", 3)
    ellipse(ctx, cx - 10, base_y - r * 0.7, r * 0.45, r * 0.12)
    fill(ctx, "#FFFFFF", 0.9)   # cloth


def draw_plate(ctx, cx, y, r=62):
    ellipse(ctx, cx, y, r, r * 0.2)
    fill(ctx, "#FBFBF8")
    ellipse(ctx, cx, y, r * 0.7, r * 0.13)
    stroke(ctx, "#E1DDD3", 3)


def draw_glass(ctx, cx, base_y, h=70):
    ctx.move_to(cx - 22, base_y - h)
    ctx.line_to(cx + 22, base_y - h)
    ctx.line_to(cx + 18, base_y)
    ctx.line_to(cx - 18, base_y)
    ctx.close_path()
    fill(ctx, "#CFE6F2", 0.55)
    ctx.rectangle(cx - 19, base_y - h * 0.6, 38, h * 0.6)
    fill(ctx, "#9CCBE3", 0.45)
    ctx.move_to(cx - 22, base_y - h)
    ctx.line_to(cx - 18, base_y)
    ctx.move_to(cx + 22, base_y - h)
    ctx.line_to(cx + 18, base_y)
    stroke(ctx, "#FFFFFF", 2.5, 0.8)


def draw_jug(ctx, cx, base_y):
    ctx.move_to(cx - 30, base_y - 120)
    ctx.line_to(cx + 22, base_y - 120)
    ctx.curve_to(cx + 40, base_y - 60, cx + 42, base_y - 20, cx + 34, base_y)
    ctx.line_to(cx - 38, base_y)
    ctx.curve_to(cx - 44, base_y - 30, cx - 42, base_y - 80, cx - 30, base_y - 120)
    fill(ctx, "#CFE6F2", 0.55)
    ctx.rectangle(cx - 40, base_y - 75, 78, 75)
    fill(ctx, "#9CCBE3", 0.4)
    ctx.move_to(cx + 32, base_y - 100)
    ctx.curve_to(cx + 75, base_y - 100, cx + 70, base_y - 40, cx + 36, base_y - 40)
    stroke(ctx, "#BFDCEB", 8, 0.8)


def draw_salad(ctx, cx, y):
    draw_plate(ctx, cx, y, 56)
    rnd = random.Random(3)
    for _ in range(14):
        ellipse(ctx, cx + rnd.uniform(-36, 36), y - 8 + rnd.uniform(-8, 4), 12, 7)
        fill(ctx, rnd.choice(["#5FA04E", "#7DBB5A", "#D9473B", "#E8E2B8", "#4F8B3A"]))


def draw_photo(ctx, x, y, w, h, people=2):
    rrect(ctx, x - 8, y - 8, w + 16, h + 16, 6)
    fill(ctx, "#7A5134")
    box(ctx, x, y, w, h, "#E9DCC6")
    vgrad(ctx, x, y, w, h * 0.6, "#BFD8E2", "#E9DCC6")
    for i in range(people):
        px = x + w * (i + 1) / (people + 1)
        ellipse(ctx, px, y + h * 0.45, w * 0.08, w * 0.09)
        fill(ctx, "#C69C7A")
        ellipse(ctx, px, y + h * 0.85, w * 0.15, h * 0.22)
        fill(ctx, ["#7E9BB8", "#D58FA6", "#B8A07E"][i % 3])


def draw_plant(ctx, x, base_y, k=1.0, t=0.0):
    for i in range(9):
        ang = -math.pi / 2 + (i - 4) * 0.28 + 0.03 * math.sin(t * 0.8 + i)
        L = (120 + 25 * (i % 3)) * k
        ex, ey = x + math.cos(ang) * L, base_y - 60 * k + math.sin(ang) * L
        ctx.move_to(x, base_y - 60 * k)
        ctx.curve_to(x + (ex - x) * 0.3, base_y - 60 * k - L * 0.5, ex - (ex - x) * 0.2, ey + 20, ex, ey)
        stroke(ctx, "#3F7D3A" if i % 2 else "#5C9A48", 16 * k)
    ctx.move_to(x - 45 * k, base_y - 70 * k)
    ctx.line_to(x + 45 * k, base_y - 70 * k)
    ctx.line_to(x + 34 * k, base_y)
    ctx.line_to(x - 34 * k, base_y)
    ctx.close_path()
    fill(ctx, "#B5643C")


def draw_window(ctx, x, y, w, h, t, curtain="#5E8C8A"):
    vgrad(ctx, x, y, w, h, "#CFE8F5", "#F4EAD2")
    for i in range(3):   # distant trees / buildings
        ellipse(ctx, x + w * (0.2 + 0.3 * i), y + h * 0.82, w * 0.18, h * 0.12)
        fill(ctx, "#9DBF8A", 0.8)
    ctx.rectangle(x, y, w, h)
    stroke(ctx, "#FFFFFF", 14)
    ctx.move_to(x + w / 2, y)
    ctx.line_to(x + w / 2, y + h)
    ctx.move_to(x, y + h * 0.45)
    ctx.line_to(x + w, y + h * 0.45)
    stroke(ctx, "#FFFFFF", 9)
    sw = 0.02 * math.sin(t * 0.9)
    for side in (0, 1):
        cx = x - 30 if side == 0 else x + w + 30
        dirn = 1 if side == 0 else -1
        ctx.move_to(cx - dirn * 20, y - 40)
        ctx.line_to(cx + dirn * w * 0.28, y - 40)
        ctx.curve_to(cx + dirn * w * (0.18 + sw), y + h * 0.4, cx + dirn * w * (0.25 + sw),
                     y + h * 0.8, cx + dirn * w * (0.2 + sw), y + h + 60)
        ctx.line_to(cx - dirn * 20, y + h + 60)
        ctx.close_path()
        fill(ctx, curtain)
        for f in range(3):
            ctx.move_to(cx + dirn * (10 + f * 30), y - 30)
            ctx.line_to(cx + dirn * (8 + f * 30 + sw * 200), y + h + 50)
            stroke(ctx, "#000000", 3, 0.12)
    box(ctx, x - 80, y - 52, w + 160, 14, "#8A6A4A")
    # light rays
    ctx.move_to(x, y)
    ctx.line_to(x + w, y)
    ctx.line_to(x + w + 420, FLOOR + 200)
    ctx.line_to(x + 260, FLOOR + 200)
    ctx.close_path()
    setc(ctx, "#FFF4D6", 0.12)
    ctx.fill()


def room_shell(ctx, wall_top, wall_bottom, floor_a, floor_b, tile=True):
    vgrad(ctx, -600, -200, 2280, FLOOR + 200, wall_top, wall_bottom)
    box(ctx, -600, -200, 2280, 260, "#F7F1E6")          # ceiling
    box(ctx, -600, 60, 2280, 18, "#D8CBB4")              # cornice
    vgrad(ctx, -600, FLOOR, 2280, 1200, floor_a, floor_b)
    box(ctx, -600, FLOOR - 26, 2280, 26, "#B9A88D")      # skirting
    if tile:
        for i in range(-6, 20):
            ctx.move_to(-600 + i * 160, FLOOR)
            ctx.line_to(-600 + i * 160 - (i - 7) * 60, FLOOR + 900)
        for j, yy in enumerate((FLOOR + 90, FLOOR + 230, FLOOR + 420, FLOOR + 700)):
            ctx.move_to(-600, yy)
            ctx.line_to(1700, yy)
        stroke(ctx, "#000000", 2, 0.07)


def draw_living(ctx, t):
    room_shell(ctx, "#F1E6D3", "#E7D6BB", "#CDB594", "#B79C79")
    draw_window(ctx, 110, 360, 340, 560, t, "#5E8C8A")
    draw_photo(ctx, 560, 560, 140, 110, 3)
    draw_photo(ctx, 600, 720, 90, 120, 2)
    # doorway to kitchen
    box(ctx, 840, 600, 240, FLOOR - 600, "#E2EAEC")
    for i in range(6):
        box(ctx, 840, 1000 + i * 70, 240, 3, "#C9D3D6")
    ctx.rectangle(840, 600, 240, FLOOR - 600)
    stroke(ctx, "#8A6A4A", 22)
    # rug
    ellipse(ctx, 520, FLOOR + 190, 430, 95)
    fill(ctx, "#A8463E", 0.9)
    ellipse(ctx, 520, FLOOR + 190, 380, 75)
    stroke(ctx, "#E8C27A", 6)
    # sofa
    rrect(ctx, 40, 1050, 560, 260, 40)
    fill(ctx, "#8C6D4F")
    rrect(ctx, 20, 1200, 600, 200, 36)
    fill(ctx, "#7A5C40")
    for i, c in enumerate(("#F2C4D0", "#FFFFFF", "#D9B36C")):
        rrect(ctx, 90 + i * 160, 1110, 130, 110, 30)
        fill(ctx, c)
    box(ctx, 50, 1400, 22, 50, "#4A3524")
    box(ctx, 568, 1400, 22, 50, "#4A3524")
    draw_plant(ctx, 700, FLOOR - 4, 0.9, t)


def draw_kitchen(ctx, t, st):
    room_shell(ctx, "#EEF1EE", "#E2E6E1", "#C9B79A", "#B6A283")
    # backsplash tiles
    box(ctx, -600, 720, 2280, COUNTER_Y - 720, "#E4EEF0")
    for i in range(-10, 40):
        ctx.move_to(-600 + i * 60, 720)
        ctx.line_to(-600 + i * 60, COUNTER_Y)
    for j in range(7):
        ctx.move_to(-600, 720 + j * 60)
        ctx.line_to(1680, 720 + j * 60)
    stroke(ctx, "#C5D2D5", 2)
    # window over sink
    draw_window(ctx, 120, 420, 230, 260, t, "#E3B8C3")
    # upper cabinets
    for x in (-200, 420, 640, 860, 1080):
        rrect(ctx, x, 400, 210, 290, 8)
        fill(ctx, "#B07C4F")
        rrect(ctx, x + 14, 414, 182, 262, 6)
        stroke(ctx, "#8B5E38", 4)
        ellipse(ctx, x + 185, 650, 6, 6)
        fill(ctx, "#E6D3A3")
    # utensil rail
    ctx.move_to(660, 780)
    ctx.line_to(960, 780)
    stroke(ctx, "#8A8A8A", 6)
    for i, x in enumerate((690, 750, 810, 870, 930)):
        ctx.move_to(x, 780)
        ctx.line_to(x, 850 + (i % 2) * 20)
        stroke(ctx, "#9B9B9B", 5)
        ellipse(ctx, x, 862 + (i % 2) * 20, 13, 9)
        fill(ctx, "#A6A6A6")
    # spice shelf
    box(ctx, 420, 880, 200, 10, "#8B5E38")
    for i, c in enumerate(("#C0392B", "#E1A23A", "#6E8B3D", "#8D5A2B")):
        rrect(ctx, 432 + i * 46, 830, 34, 50, 6)
        fill(ctx, c)
    # lower cabinets + counter
    box(ctx, -600, COUNTER_Y, 2280, FLOOR - COUNTER_Y, "#B98756")
    for x in range(-560, 1700, 220):
        rrect(ctx, x, COUNTER_Y + 40, 200, FLOOR - COUNTER_Y - 70, 6)
        stroke(ctx, "#8E6036", 4)
        box(ctx, x + 90, COUNTER_Y + 60, 20, 6, "#E6D3A3")
    box(ctx, -600, COUNTER_Y - 18, 2280, 30, "#D9D2C7")
    box(ctx, -600, COUNTER_Y + 10, 2280, 6, "#BDB4A6")
    # sink + tap
    ellipse(ctx, 235, COUNTER_Y - 4, 105, 16)
    fill(ctx, "#A9B3B8")
    ctx.move_to(235, COUNTER_Y - 14)
    ctx.line_to(235, 960)
    ctx.curve_to(235, 930, 290, 930, 290, 965)
    stroke(ctx, "#B9C2C7", 14)
    if st.get("water"):
        for i in range(5):
            ctx.move_to(288 + (i - 2) * 3, 975)
            ctx.line_to(288 + (i - 2) * 4 + 3 * math.sin(t * 30 + i), COUNTER_Y - 10)
        stroke(ctx, "#BFE3F5", 4, 0.75)
        for i in range(4):
            ph = (t * 3 + i * 0.25) % 1
            ellipse(ctx, 288 + (i - 1.5) * 18 * ph, COUNTER_Y - 12 - 20 * ph, 4, 4)
            fill(ctx, "#D7F0FA", 1 - ph)
    # cutting board with veg
    rrect(ctx, 380, COUNTER_Y - 34, 170, 22, 6)
    fill(ctx, "#D6A46A")
    for i, c in enumerate(("#E07A2E", "#E07A2E", "#5FA04E", "#F2F0E6", "#D9473B")):
        ellipse(ctx, 400 + i * 30, COUNTER_Y - 42, 13, 9)
        fill(ctx, c)
    # stove + pot
    box(ctx, 700, COUNTER_Y - 30, 240, 30, "#3E3E3E")
    for x in (750, 880):
        ellipse(ctx, x, COUNTER_Y - 30, 40, 7)
        fill(ctx, "#222222")
    for i in range(6):
        ellipse(ctx, 750 + (i - 2.5) * 10, COUNTER_Y - 32, 4, 6)
        fill(ctx, "#3E8EE8", 0.8)
    ctx.move_to(730, COUNTER_Y - 32)
    ctx.line_to(890, COUNTER_Y - 32)
    ctx.line_to(880, COUNTER_Y - 130)
    ctx.line_to(740, COUNTER_Y - 130)
    ctx.close_path()
    fill(ctx, "#9AA0A6")
    ellipse(ctx, 810, COUNTER_Y - 130, 72, 13)
    fill(ctx, "#D9A43A")
    ctx.move_to(730, COUNTER_Y - 115)
    ctx.line_to(708, COUNTER_Y - 120)
    ctx.move_to(890, COUNTER_Y - 115)
    ctx.line_to(912, COUNTER_Y - 120)
    stroke(ctx, "#5A5A5A", 8)
    draw_pot_on_stove = st.get("steam", True)
    if draw_pot_on_stove:
        for i in range(3):
            ph = (t * 0.35 + i / 3) % 1
            ctx.move_to(780 + i * 30, COUNTER_Y - 145)
            for k in range(1, 8):
                ctx.line_to(780 + i * 30 + 12 * math.sin(k * 1.2 + t * 2 + i), COUNTER_Y - 145 - k * 26 * (0.5 + ph))
            stroke(ctx, "#FFFFFF", 7, 0.35 * (1 - ph))
    draw_plant(ctx, 1010, COUNTER_Y - 20, 0.45, t)


def draw_dining_back(ctx, t, st):
    room_shell(ctx, "#EFE0C8", "#E3CFB1", "#C7AE8C", "#B19572")
    draw_window(ctx, 690, 360, 280, 470, t, "#B5567A")
    draw_photo(ctx, 110, 520, 160, 120, 3)
    draw_photo(ctx, 320, 560, 100, 130, 1)
    draw_plant(ctx, -40, FLOOR - 4, 1.0, t)
    # hanging lamp
    ctx.move_to(540, 0)
    ctx.line_to(540, 300)
    stroke(ctx, "#444444", 4)
    ctx.move_to(470, 380)
    ctx.line_to(610, 380)
    ctx.line_to(570, 300)
    ctx.line_to(510, 300)
    ctx.close_path()
    fill(ctx, "#E8C27A")
    ellipse(ctx, 540, 384, 70, 10)
    fill(ctx, "#FFF2C8", 0.9)
    # chair backs
    for x in st.get("chairs", ()):
        for dx in (-70, 70):
            box(ctx, x + dx - 9, 1050, 18, 260, "#7A4E2C")
        rrect(ctx, x - 80, 1040, 160, 34, 10)
        fill(ctx, "#8A5A33")
        box(ctx, x - 70, 1110, 140, 14, "#7A4E2C")


def draw_dining_front(ctx, t, st):
    # table
    ctx.move_to(-40, TABLE_Y - 30)
    ctx.line_to(1120, TABLE_Y - 30)
    ctx.line_to(1160, TABLE_Y + 10)
    ctx.line_to(-80, TABLE_Y + 10)
    ctx.close_path()
    fill(ctx, "#A86F42")
    # tablecloth hanging to the floor (hides legs of seated people)
    ctx.move_to(-90, TABLE_Y + 8)
    ctx.line_to(1170, TABLE_Y + 8)
    ctx.line_to(1190, FLOOR + 60)
    for k in range(40, -1, -1):
        ctx.line_to(-110 + k * 32.5, FLOOR + 60 + (8 if k % 2 else 0))
    ctx.close_path()
    fill(ctx, "#F3EBDD")
    for k in range(9):
        ctx.move_to(-60 + k * 150, TABLE_Y + 20)
        ctx.line_to(-70 + k * 152, FLOOR + 50)
        stroke(ctx, "#D9CDB8", 3, 0.6)
    box(ctx, -90, TABLE_Y + 70, 1260, 16, "#C8566E", 0.85)
    for k in range(42):
        ellipse(ctx, -80 + k * 30, TABLE_Y + 78, 4, 4)
        fill(ctx, "#FFFFFF", 0.9)
    base = TABLE_Y - 12
    draw_jug(ctx, 120, base)
    draw_glass(ctx, 225, base)
    for x in st.get("plates", ()):
        draw_plate(ctx, x, base)
        if x in st.get("food_on_plate", ()):
            ellipse(ctx, x - 14, base - 8, 22, 8)
            fill(ctx, "#E3B23C")
            ellipse(ctx, x + 22, base - 9, 24, 9)
            fill(ctx, "#E2B573")
    draw_bowl(ctx, 470, base, 46, "#C8682F")
    for i in range(5):
        ellipse(ctx, 450 + i * 10, base - 26, 4, 3)
        fill(ctx, "#5FA04E")
    if st.get("basket", True):
        draw_roti_basket(ctx, 570, base, 0.85)
    if st.get("daal", True):
        draw_bowl(ctx, 800, base, 46, "#E3B23C")
    draw_glass(ctx, 885, base)
    draw_salad(ctx, 985, base)


# ----------------------------------------------------------------- choreography
AH, MH = PEOPLE["ayesha"]["H"], PEOPLE["mother"]["H"]
KA, KM = 370, 600          # kitchen standing x
DA, DM = 360, 680          # dining seats x
POT = (800, 1005)
BOARD = (455, 1050)


def blink_at(t, off):
    ph = (t + off) % 3.4
    return 1.0 if ph < 0.13 else 0.0


def talking(t, windows, who):
    for s0, s1, spk in windows:
        if spk == who and s0 + 0.05 <= t <= s1 - 0.25:
            v = abs(math.sin(t * 2 * math.pi * 2.3 + (s0 * 3))) ** 0.8
            v *= 0.65 + 0.35 * math.sin(t * 2 * math.pi * 0.9 + 1.0)
            return max(0.0, v)
    return 0.0


def walker(t, kf, H):
    x = keys(t, kf)
    x2 = keys(t + 1 / FPS, kf)
    moving = abs(x2 - x) > 0.3
    return x, (abs(x - kf[0][1]) / (0.2 * H) * math.pi if moving else None), (1 if x2 >= x else -1)


def toward(x, other):
    return 0.8 if other > x else -0.8


def stir(t):
    return ("w", POT[0] - 10 + 26 * math.cos(t * 2.4), POT[1] + 8 * math.sin(t * 2.4))


def mouth_world(x, sit, H):
    s = PEOPLE["ayesha" if H == AH else "mother"]
    y0 = FLOOR + sit * 0.25 * H
    return x, y0 - 0.885 * H + 0.58 * s["head"][1] * H


def scene(shot_id, t, d):
    """Return dict(loc, cam=(cx,cy,zoom), actors=[...], props={...}, sfx={...}, overlay...)."""
    A = dict(kind="ayesha", blink=blink_at(t, 0.0))
    M = dict(kind="mother", blink=blink_at(t, 1.7))
    sfx = {}
    props = {}
    i = shot_id
    if i == "1.1":
        x, walk, dirn = walker(t, [(0.3, 180), (5.6, 860)], AH)
        A.update(x=x, walk=walk, expr="smile", gaze=(0.6 * dirn, 0))
        cam = (keys(t, [(0, 470.0), (6, 600.0)]), 1040, keys(t, [(0, 1.12), (6, 1.22)]))
        sfx = dict(birds=1)
        return dict(loc="living", cam=cam, actors=[A], props=props, sfx=sfx)
    if i == "1.2":
        chop_on = t > 2.4
        M.update(x=KM, expr="smile", gaze=(-0.5 if chop_on else 0.6, 0.5), tilt=-3 if chop_on else 3)
        if chop_on:
            ph = max(0.0, math.sin((t - 2.4) * 2 * math.pi * 2.2))
            M["arms"] = {"right": ("w", BOARD[0], BOARD[1] - 4 - 22 * ph)}
            M["hold"] = {"right": "knife"}
            sfx["chop_phase"] = (t - 2.4) * 2.2
        else:
            M["arms"] = {"left": stir(t)}
            M["hold"] = {"left": "ladle"}
        cam = (620, 1000, keys(t, [(0, 1.5), (5, 1.6)]))
        sfx.update(simmer=1)
        return dict(loc="kitchen", cam=cam, actors=[M], props=props, sfx=sfx)
    if i == "1.3":
        x, walk, dirn = walker(t, [(0.0, -120), (2.1, KA)], AH)
        A.update(x=x, walk=walk, expr="happy" if t > 2.0 else "smile", gaze=(0.7, -0.5))
        M.update(x=KM, expr="smile", gaze=(toward(KM, x), 0.4),
                 arms={"left": stir(t) if t < 1.5 else None}, hold={"left": "ladle"} if t < 1.5 else {})
        cam = (470, 1010, 1.3)
        return dict(loc="kitchen", cam=cam, actors=[A, M], props=props, sfx=dict(simmer=1))
    if i == "2.1":
        A.update(x=KA, expr="curious", gaze=(0.8, -0.7), tilt=keys(t, [(0, 0), (1.5, 6)]))
        M.update(x=KM, expr="smile", gaze=(-0.4, 0.6), arms={"left": stir(t * 0.6)}, hold={"left": "ladle"})
        cam = (420, 985, keys(t, [(0, 2.0), (6, 2.15)]))
        return dict(loc="kitchen", cam=cam, actors=[M, A], props=props, sfx=dict(simmer=1))
    if i == "2.2":
        A.update(x=KA, expr="curious", gaze=(0.8, -0.7), tilt=5)
        M.update(x=KM, expr="smile", gaze=(-0.8, 0.8), tilt=keys(t, [(0, 0), (1.2, -6)]))
        cam = (585, 860, 2.0)
        return dict(loc="kitchen", cam=cam, actors=[M, A], props=props, sfx=dict(simmer=1))
    if i == "3.1":
        A.update(x=KA, expr="smile", gaze=(0.8, -0.7))
        M.update(x=KM, expr="smile", gaze=(-0.8, 0.8), lean=keys(t, [(0, 0), (1.0, 1.0)]), tilt=-7)
        cam = (600, 850, 2.9)
        return dict(loc="kitchen", cam=cam, actors=[M, A], props=props, sfx=dict(simmer=0.6))
    if i == "3.2":
        A.update(x=KA, expr="smile" if t > 2.6 else "curious", gaze=(0.8, -0.6), tilt=keys(t, [(2.6, 0), (3.6, -5)]))
        M.update(x=KM, expr="smile", gaze=(-0.8, 0.8), lean=1.0, tilt=-7)
        cam = (KA, 975, 3.2)
        return dict(loc="kitchen", cam=cam, actors=[M, A], props=props, sfx=dict(simmer=0.5))
    if i == "3.3":
        nod = math.sin(max(0, t - 3.5) * 5) * (1 if 3.5 < t < 5.5 else 0) * 2
        A.update(x=KA, expr="happy", gaze=(0.8, -0.6), nod=nod)
        M.update(x=KM, expr="smile", gaze=(-0.8, 0.8), lean=keys(t, [(0, 1.0), (4.0, 0.4)]), tilt=-5,
                 arms={"right": ("w", KA + 0.11 * AH, FLOOR - 0.64 * AH) if 1.0 < t < 6.0 else None})
        cam = (480, 905, 1.9)
        return dict(loc="kitchen", cam=cam, actors=[M, A], props=props, sfx=dict(simmer=0.5))
    if i == "4.1":
        mx = 680
        by = keys(t, [(0.4, 1150), (2.6, TABLE_Y - 14)])
        ay = keys(t, [(0.8, 1170), (3.2, TABLE_Y - 14)])
        placed_m, placed_a = t > 2.6, t > 3.2
        M.update(x=mx, expr="smile", gaze=(0.3, 0.8) if not placed_m else (-0.7, 0.2))
        A.update(x=400, expr="smile", gaze=(0.6, 0.8) if not placed_a else (0.8, -0.4))
        if not placed_m:
            M["arms"] = {"right": ("w", 770, by), "left": ("w", 830, by)}
            M["hold"] = {"right": "daal"}
        if not placed_a:
            A["arms"] = {"left": ("w", 540, ay), "right": ("w", 470, ay)}
            A["hold"] = {"right": "basket"}
        props = dict(chairs=(DA, DM), plates=(DA, DM), daal=placed_m, basket=placed_a)
        sfx = dict(clinks=[2.6, 3.2])
        return dict(loc="dining", cam=(560, 1090, 1.15), actors=[A, M], props=props, sfx=sfx)
    if i == "4.2":
        x, walk, dirn = walker(t, [(5.2, 400), (7.0, -200)], AH)
        A.update(x=x, walk=walk, expr="happy" if t > 3.4 else "smile",
                 gaze=(-0.8, 0) if walk is not None else (0.8, -0.5))
        M.update(x=680, expr="smile", gaze=(toward(680, x), 0.5))
        props = dict(chairs=(DA, DM), plates=(DA, DM))
        return dict(loc="dining", cam=(560, 1040, 1.55), actors=[A, M], props=props, sfx={})
    if i == "4.3":
        x, walk, dirn = walker(t, [(0.0, 40), (0.8, 185), (4.4, 185), (6.0, 760)], AH)
        washing = 0.9 < t < 4.3
        A.update(x=x, walk=walk, expr="thoughtful" if washing else "smile",
                 gaze=(0.0, 1.0) if washing else (0.7 * dirn, 0))
        if washing:
            r = 9 * math.sin(t * 9)
            A["arms"] = {"right": ("w", 272 - 14 + r, 1032), "left": ("w", 272 + 14 - r, 1028)}
        props = dict(water=0.7 < t < 4.3, steam=True)
        return dict(loc="kitchen", cam=(330, 1000, 1.75), actors=[A], props=props,
                    sfx=dict(water=props["water"]))
    if i == "5.1":
        sit = keys(t, [(1.0, 0.0), (3.0, 1.0)])
        A.update(x=DA, sit=sit, expr="smile", gaze=(0.8, -0.2))
        M.update(x=DM, sit=keys(t, [(1.4, 0.0), (3.4, 1.0)]), expr="smile", gaze=(-0.8, 0.3))
        props = dict(chairs=(DA, DM), plates=(DA, DM))
        return dict(loc="dining", cam=(530, 1100, 1.2), actors=[A, M], props=props,
                    sfx=dict(scrape=[1.0, 1.4]))
    if i == "5.2":
        A.update(x=DA, sit=1, expr="curious", gaze=(0.8, -0.2))
        arms = {}
        if 1.0 < t < 2.8:
            arms["right"] = ("l", -0.15, -0.74)
        elif t >= 2.8:
            arms["right"] = ("w", DM - 25, TABLE_Y - 30)
        M.update(x=DM, sit=1, expr="smile", gaze=(-0.6, 0.4) if t < 2.8 else (-0.2, 1.0), arms=arms)
        props = dict(chairs=(DA, DM), plates=(DA, DM))
        return dict(loc="dining", cam=(700, 1065, 1.9), actors=[A, M], props=props, sfx={})
    if i == "5.3":
        A.update(x=DA, sit=1, expr="smile", gaze=(0.8, -0.2), nod=math.sin(t * 5) * 1.5 if t > 3 else 0,
                 arms={"right": ("l", -0.14, -0.72)} if 0.8 < t < 4.0 else {})
        M.update(x=DM, sit=1, expr="smile", gaze=(-0.8, 0.2))
        props = dict(chairs=(DA, DM), plates=(DA, DM))
        return dict(loc="dining", cam=(DA + 10, 1110, 2.2), actors=[A, M], props=props, sfx={})
    if i == "6.1":
        mx, my = mouth_world(DA, 1, AH)
        hand = keys(t, [(0.0, (DA - 30.0, TABLE_Y - 24.0)), (1.4, (DA - 30.0, TABLE_Y - 24.0)),
                        (3.0, (mx - 30.0, my + 50.0))])
        A.update(x=DA, sit=1, expr="thoughtful" if t > 2.6 else "smile",
                 gaze=(-0.5, -0.8) if t > 3.0 else (0, 1.0),
                 arms={"right": ("w", hand[0], hand[1])}, hold={"right": "roti"} if t > 1.0 else {})
        M.update(x=DM, sit=1, expr="smile", gaze=(-0.8, 0.2))
        props = dict(chairs=(DA, DM), plates=(DA, DM))
        return dict(loc="dining", cam=(DA, 1110, keys(t, [(0, 2.2), (6, 2.7)])), actors=[A, M],
                    props=props, sfx={})
    if i == "6.2":
        mx, my = mouth_world(DA, 1, AH)
        A.update(x=DA, sit=1, expr="smile", gaze=(0.3, -0.2),
                 arms={"right": ("w", mx - 30, my + 50)}, hold={"right": "roti"})
        M.update(x=DM, sit=1, expr="smile", gaze=(-0.8, 0.2))
        props = dict(chairs=(DA, DM), plates=(DA, DM))
        return dict(loc="dining", cam=(DA, 1100, 2.7), actors=[A, M], props=props, sfx={})
    if i == "6.3":
        mx, my = mouth_world(DA, 1, AH)
        cyc = keys(t, [(0.0, 0.0), (0.6, 1.0), (1.6, 1.0), (2.4, 0.0), (3.4, 0.0), (4.0, 1.0), (4.6, 1.0), (5.3, 0.0)])
        hx = lerp(mx - 30, DA - 30, 1 - cyc) if True else 0
        hy = lerp(my + 18, TABLE_Y - 24, 1 - cyc)
        A.update(x=DA, sit=1, expr="chew" if 0.6 < t < 3.0 or t > 4.0 else "smile", gaze=(0.6, 0.2),
                 arms={"right": ("w", hx, hy)}, hold={"right": "roti"} if cyc > 0.05 else {})
        M.update(x=DM, sit=1, expr="surprised" if t < 1.0 else "happy", gaze=(-0.8, 0.3))
        props = dict(chairs=(DA, DM), plates=(DA, DM), food_on_plate=(DA,))
        return dict(loc="dining", cam=(525, 1085, 1.45), actors=[A, M], props=props, sfx=dict(clinks=[2.5]))
    if i == "7.1":
        A.update(x=DA, sit=1, expr="happy", gaze=(0.8, -0.2), tilt=keys(t, [(0, 0), (2, 4)]))
        M.update(x=DM, sit=1, expr="smile", gaze=(-0.8, 0.2))
        props = dict(chairs=(DA, DM), plates=(DA, DM), food_on_plate=(DA,))
        return dict(loc="dining", cam=(DA + 30, 1095, 2.1), actors=[A, M], props=props, sfx={})
    if i == "7.2":
        reach = 0.9 < t < 6.2
        pat = math.sin(t * 6) * 6 if reach else 0
        A.update(x=DA, sit=1, expr="happy", gaze=(0.8, -0.3), tilt=keys(t, [(1, 0), (2, 6)]))
        M.update(x=DM, sit=1, expr="smile", gaze=(-0.8, 0.2), lean=0.5 if reach else 0,
                 arms={"right": ("w", DA + 0.10 * AH, FLOOR + 0.25 * AH - 0.64 * AH + pat)} if reach else {})
        props = dict(chairs=(DA, DM), plates=(DA, DM), food_on_plate=(DA,))
        return dict(loc="dining", cam=(530, 1060, 1.6), actors=[A, M], props=props, sfx={})
    if i in ("7.3", "7.4"):
        tt = t if i == "7.3" else 6.0
        mx, my = mouth_world(DA, 1, AH)
        cyc = keys(tt, [(0.5, 0.0), (1.2, 1.0), (2.0, 1.0), (2.8, 0.0)])
        A.update(x=DA, sit=1, expr="chew" if 1.2 < tt < 3.2 else "smile", gaze=(0.5, 0.3),
                 arms={"right": ("w", lerp(DA - 30, mx - 30, cyc), lerp(TABLE_Y - 24, my + 18, cyc))},
                 hold={"right": "roti"} if cyc > 0.05 else {})
        mmx, mmy = mouth_world(DM, 1, MH)
        cyc2 = keys(tt, [(2.0, 0.0), (2.8, 1.0), (3.6, 1.0), (4.4, 0.0)])
        M.update(x=DM, sit=1, expr="smile", gaze=(-0.6, 0.4),
                 arms={"right": ("w", lerp(DM - 35, mmx - 35, cyc2), lerp(TABLE_Y - 24, mmy + 22, cyc2))},
                 hold={"right": "roti"} if cyc2 > 0.05 else {})
        props = dict(chairs=(DA, DM), plates=(DA, DM), food_on_plate=(DA, DM))
        cam = (keys(tt, [(0, 525.0), (5.5, 540.0)]), keys(tt, [(0, 1060.0), (5.5, 1010.0)]),
               keys(tt, [(0, 1.6), (5.5, 1.0)]))
        return dict(loc="dining", cam=cam, actors=[A, M], props=props,
                    sfx=dict(birds=1, endcard=(i == "7.4")))
    raise KeyError(shot_id)


# ----------------------------------------------------------------- frame
def speech_windows(shot):
    lines = shot["dialogue"]
    if not lines:
        return []
    span = shot["duration"] / len(lines)
    return [(k * span + 0.2, (k + 1) * span - 0.2, d["speaker"]) for k, d in enumerate(lines)]


def render_frame(ctx, shot, t, subs=True):
    d = shot["duration"]
    sc = scene(shot["id"], t, d)
    win = speech_windows(shot)
    for a in sc["actors"]:
        a["talk"] = talking(t, win, a["kind"])
        if a["talk"] > 0 and a.get("expr") == "chew":
            a["expr"] = "smile"
    cx, cy, z = sc["cam"]
    ctx.identity_matrix()
    ctx.translate(W / 2, HGT / 2)
    ctx.scale(z, z)
    ctx.translate(-cx, -cy)
    loc, props = sc["loc"], sc["props"]
    if loc == "living":
        draw_living(ctx, t)
    elif loc == "kitchen":
        draw_kitchen(ctx, t, props)
    else:
        draw_dining_back(ctx, t, props)
    for a in sorted(sc["actors"], key=lambda a: a.get("y", FLOOR)):
        draw_person(ctx, a, t)
    if loc == "dining":
        draw_dining_front(ctx, t, props)

    ctx.identity_matrix()
    # soft vignette
    g = cairo.RadialGradient(W / 2, HGT / 2, HGT * 0.35, W / 2, HGT / 2, HGT * 0.75)
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, 0.15, 0.08, 0.02, 0.35)
    ctx.rectangle(0, 0, W, HGT)
    ctx.set_source(g)
    ctx.fill()

    # fades at very start / end of the film
    if shot["id"] == "1.1" and t < 0.6:
        ctx.rectangle(0, 0, W, HGT)
        ctx.set_source_rgba(0, 0, 0, 1 - t / 0.6)
        ctx.fill()

    # title
    if shot["id"] == "1.1":
        al = seg(t, 0.2, 0.9) * (1 - seg(t, 4.2, 5.2))
        blit(ctx, text_panel(((("عائشہ نے بسم اللہ سیکھی"), URDU_B, 74, "#FFFFFF"),),
                             panel=("#5B2333", 0.55)), W / 2, 260, al)

    # overlays
    ov = shot.get("overlay")
    if ov and shot["id"] != "7.4":
        t0 = {"3.2": 0.6, "6.2": 0.6, "3.3": 3.4, "7.3": 2.0}.get(shot["id"], 0.5)
        al = seg(t, t0, t0 + 0.5) * (1 - seg(t, d - 0.3, d))
        if "بِسْمِ" in ov:
            blit(ctx, text_panel(((ov, ARABIC, 130, "#F6D58A"),), panel=("#3B2410", 0.55), pad=(60, 30)),
                 W / 2, 330, al)
        else:
            blit(ctx, text_panel(((ov, URDU_B, 64, "#FFFFFF"),), panel=("#5B2333", 0.6)), W / 2, 330, al)

    if shot["id"] == "7.4":
        ctx.rectangle(0, 0, W, HGT)
        ctx.set_source_rgba(0.12, 0.06, 0.03, 0.62 * seg(t, 0, 0.6))
        ctx.fill()
        al = seg(t, 0.2, 0.9)
        blit(ctx, text_panel((("بِسْمِ اللّٰهِ", ARABIC, 150, "#F6D58A"),), glow="#3B2410"), W / 2, 760, al)
        blit(ctx, text_panel((("کھانے سے پہلے اللہ کو یاد کریں!", URDU_B, 66, "#FFFFFF"),)), W / 2, 1010, al)
        blit(ctx, text_panel((("Remember Allah Before Eating!", LATIN, 44, "#F4B8CA"),)), W / 2, 1160, al)
        if t > d - 0.8:
            ctx.rectangle(0, 0, W, HGT)
            ctx.set_source_rgba(0, 0, 0, seg(t, d - 0.8, d))
            ctx.fill()

    # subtitles
    if subs:
        for (s0, s1, spk), line in zip(win, shot["dialogue"]):
            if s0 <= t <= s1:
                al = seg(t, s0, s0 + 0.2) * (1 - seg(t, s1 - 0.2, s1))
                name, col = LABELS[spk]
                blit(ctx, text_panel(((name, URDU_B, 34, col), (line["urdu"], URDU, 50, "#FFFFFF")),
                                     panel=("#000000", 0.55), maxw=900), W / 2, 1640, al)


# ----------------------------------------------------------------- audio
SR = 48000


def synth_audio(shot, seed):
    d = shot["duration"]
    n = int(d * SR)
    rnd = np.random.default_rng(seed)
    out = np.zeros(n, dtype=np.float64)
    tt = np.arange(n) / SR

    def lowpass(x, k):
        return np.convolve(x, np.ones(k) / k, mode="same")

    def add(at, sig):
        s = int(at * SR)
        if 0 <= s < n:
            e = min(n, s + len(sig))
            out[s:e] += sig[: e - s]

    def env(sec, tau):
        t_ = np.arange(int(sec * SR)) / SR
        return np.exp(-t_ / tau), t_

    # room tone
    brown = np.cumsum(rnd.normal(0, 1, n))
    brown -= lowpass(brown, 4801)
    out += brown / (np.abs(brown).max() + 1e-9) * 0.008

    frames = [scene(shot["id"], k / FPS, d) for k in range(int(d * FPS))]
    sfx0 = frames[0]["sfx"]
    if sfx0.get("birds"):
        for at in np.arange(rnd.uniform(0.2, 1.0), d, 1.6):
            for r in range(rnd.integers(2, 4)):
                e, t_ = env(0.07, 0.03)
                f0 = rnd.uniform(2800, 3600)
                add(at + r * 0.1, np.sin(2 * np.pi * (f0 * t_ + 9000 * t_ * t_)) * e * 0.02)
    simmer = sfx0.get("simmer", 0)
    if simmer:
        for at in np.sort(rnd.uniform(0, d, int(10 * d))):
            e, t_ = env(0.05, 0.012)
            add(at, np.sin(2 * np.pi * rnd.uniform(160, 380) * t_) * e * 0.02 * simmer)
        out += lowpass(rnd.normal(0, 1, n), 9) * 0.004 * simmer
    # footsteps / chop from per-frame state
    last = {}
    for k, fr in enumerate(frames):
        t = k / FPS
        for a in fr["actors"]:
            w = a.get("walk")
            key = a["kind"]
            if w is not None:
                step = int(w // math.pi)
                if key in last and step != last[key]:
                    e, t_ = env(0.12, 0.03)
                    add(t, (np.sin(2 * np.pi * 85 * t_) * 0.10 + rnd.normal(0, 0.02, len(t_))) * e)
                last[key] = step
            else:
                last.pop(key, None)
        cp = fr["sfx"].get("chop_phase")
        if cp is not None:
            if int(cp + 0.25) != int((cp - 2.2 / FPS) + 0.25) and cp > 0.3:
                e, t_ = env(0.06, 0.012)
                add(t, (rnd.normal(0, 0.25, len(t_)) + np.sin(2 * np.pi * 140 * t_) * 0.2) * e)
    # water
    wmask = np.array([1.0 if fr["sfx"].get("water") else 0.0 for fr in frames])
    if wmask.any():
        m = np.interp(tt, np.arange(len(wmask)) / FPS, wmask)
        m = lowpass(m, 2400)
        out += lowpass(rnd.normal(0, 1, n), 3) * 0.06 * m
    for at in sfx0.get("clinks", []):
        e, t_ = env(0.5, 0.09)
        add(at, (np.sin(2 * np.pi * 2300 * t_) + 0.6 * np.sin(2 * np.pi * 3170 * t_)) * e * 0.03)
        e2, t2 = env(0.08, 0.02)
        add(at, np.sin(2 * np.pi * 180 * t2) * e2 * 0.08)
    for at in sfx0.get("scrape", []):
        e, t_ = env(0.5, 0.25)
        nz = rnd.normal(0, 1, len(t_))
        add(at, (nz - lowpass(nz, 30)) * e * 0.03)
    # global fades for first/last shot
    if shot["id"] == "1.1":
        out *= np.clip(tt / 0.6, 0, 1)
    if shot["id"] == "7.4":
        out *= np.clip((d - tt) / 1.2, 0, 1)
    return np.clip(out, -1, 1)


def write_wav(path, data):
    pcm = (data * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


# ----------------------------------------------------------------- driver
def render_shot(args):
    shot, out_dir, subs, preview = args
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, HGT)
    ctx = cairo.Context(surf)
    if preview:
        for frac in (0.25, 0.75):
            ctx.identity_matrix()
            ctx.set_source_rgb(0, 0, 0)
            ctx.paint()
            render_frame(ctx, shot, shot["duration"] * frac, subs)
            surf.write_to_png(os.path.join(out_dir, f"{shot['id']}_{int(frac * 100)}.png"))
        return shot["id"]
    wav = os.path.join(out_dir, f"{shot['id']}.wav")
    write_wav(wav, synth_audio(shot, seed=int(shot["id"].replace(".", ""))))
    mp4 = os.path.join(out_dir, f"{shot['id']}.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
           "-s", f"{W}x{HGT}", "-r", str(FPS), "-i", "-", "-i", wav,
           "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
           "-threads", "2", "-c:a", "aac", "-b:a", "128k", "-ar", str(SR), "-shortest",
           "-movflags", "+faststart", mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k in range(int(shot["duration"] * FPS)):
        ctx.identity_matrix()
        ctx.set_source_rgb(0, 0, 0)
        ctx.paint()
        render_frame(ctx, shot, k / FPS, subs)
        surf.flush()
        proc.stdin.write(surf.get_data())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for shot {shot['id']}")
    os.remove(wav)
    return shot["id"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--shots", nargs="*")
    ap.add_argument("--no-subs", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args()

    with open(os.path.join(args.project_dir, "shots.json"), encoding="utf-8") as fh:
        shots = json.load(fh)["shots"]
    if args.shots:
        shots = [s for s in shots if s["id"] in args.shots]
    base = os.path.join(args.project_dir, "build", "animation")
    out_dir = os.path.join(base, "preview" if args.preview else "clips")
    os.makedirs(out_dir, exist_ok=True)

    jobs = [(s, out_dir, not args.no_subs, args.preview) for s in shots]
    with Pool(max(1, args.jobs)) as pool:
        for sid in pool.imap_unordered(render_shot, jobs):
            print("rendered", sid, flush=True)

    if args.preview or args.shots:
        return
    lst = os.path.join(out_dir, "concat.txt")
    with open(lst, "w") as fh:
        for s in shots:
            fh.write(f"file '{s['id']}.mp4'\n")
    final = os.path.join(base, "ayesha_learns_bismillah_animated_9x16.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", "-movflags", "+faststart", final], check=True)
    os.remove(lst)
    print("final:", final)


if __name__ == "__main__":
    sys.exit(main())
