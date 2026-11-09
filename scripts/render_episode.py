#!/usr/bin/env python3
"""Render a 16:9 family-dinner episode (e.g. "Ayesha Learns the Dua Before Eating") as an
animated video: 2D, Cairo + ffmpeg, reusing the drawing kit in render_animation.py.

Usage:
    python3 scripts/render_episode.py projects/ayesha-dua-before-eating
    python3 scripts/render_episode.py projects/ayesha-dua-before-eating --shots 3.1 3.2
    python3 scripts/render_episode.py projects/ayesha-dua-before-eating --preview   # PNG stills only
    python3 scripts/render_episode.py projects/ayesha-dua-before-eating --no-subs   # no burned-in subtitles

Everything is driven by <project>/shots.json: camera moves ("cam"), dialogue line timing
("start"/"end"), on-screen text ("overlays") and actions ("anim").

Voices: put one WAV per dialogue line in <project>/audio/, named as in
build/VOICE_SCRIPT.md (e.g. audio/2.1_1_father.wav). Any file found there is mixed in at
its line's start time, and that character's mouth then follows the loudness of the
recording, so the lip movement matches the real voice. Lines with no file stay silent
and the mouth uses a generic speaking motion over the line's subtitle window.

Outputs <project>/build/animation/clips/<shot>.mp4 and
<project>/build/animation/<slug>_16x9.mp4 (1920x1080, 24 fps, AAC audio).
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import wave
from multiprocessing import Pool

import cairo
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_animation as ra  # noqa: E402
from render_animation import (ARABIC, LATIN, URDU, URDU_B, FLOOR, TABLE_Y, blit, box,  # noqa: E402
                              ellipse, fill, ik, keys, lerp, rrect, seg, stroke, text_panel,
                              vgrad)

W, HGT, FPS, SR = 1920, 1080, 24, 48000

# ----------------------------------------------------------------- cast
ra.PEOPLE.update({
    "grandmother": dict(H=715, head=(0.067, 0.087), skin="#D9AE8E", shade="#C1937A",
                        iris="#4E3320", brow="#8E8478", lips="#BE837C",
                        hijab="#B9AFC4", hijab_dk="#9C91AA", kameez="#A99BB8",
                        sleeve="#9E90AE", trim="#E9E3EE", shalwar="#A99BB8", shoe="#6D5A4A",
                        blush=0.06),
    "father": dict(H=770, head=(0.064, 0.084), skin="#D6A47F", shade="#BC8A68",
                   iris="#4A2F1C", brow="#2A1A10", lips="#B57466",
                   hijab="#2A1C14", hijab_dk="#1C130D", hair="#2A1C14", beard="#2E2018",
                   kameez="#CFE0EE", sleeve="#C3D6E7", trim="#A9C0D6", blush=0.0),
    "grandfather": dict(H=750, head=(0.065, 0.085), skin="#CFA182", shade="#B48A6E",
                        iris="#4A2F1C", brow="#DCD8D2", lips="#AE7468",
                        hijab="#E8E6E2", hijab_dk="#CFCBC4", hair="#E8E6E2", beard="#EEECE8",
                        kameez="#F6F5F1", sleeve="#ECEBE6", trim="#D9D6CF", cap="#FBFBF8",
                        blush=0.0),
})
MEN = {"father", "grandfather"}
SEAT = {"grandfather": 300, "grandmother": 640, "ayesha": 980, "father": 1320, "mother": 1660}
EMPTY_CHAIR = 2000
LABELS = {"ayesha": ("عائشہ", "#F48FB1"), "father": ("ابو", "#9CC3E6"),
          "mother": ("امی", "#E8C98E"), "grandfather": ("دادا جان", "#E6E6E6"),
          "grandmother": ("دادی جان", "#C9B6E0"), "narrator": ("راوی", "#9FD3C7")}
DISHES = [(470, "daal"), (810, "roti"), (1150, "curry"), (1490, "salad"), (1860, "jug")]


def seated_y(kind):
    return FLOOR + 0.25 * ra.PEOPLE[kind]["H"]


def head_world(kind, lean=0.0):
    H = ra.PEOPLE[kind]["H"]
    return SEAT[kind], seated_y(kind) - 0.885 * H + lean * 0.045 * H


def mouth_world(kind):
    s = ra.PEOPLE[kind]
    x, y = head_world(kind)
    return x, y + 0.58 * s["head"][1] * s["H"]


# ----------------------------------------------------------------- men
def draw_man(ctx, a, t):
    """Seated man in shalwar kameez (body below the table top is hidden by the tablecloth)."""
    s = ra.PEOPLE[a["kind"]]
    H = s["H"]
    rx, ry = s["head"][0] * H, s["head"][1] * H
    x0, y0 = a["x"], seated_y(a["kind"])
    lean, nod = a.get("lean", 0.0), a.get("nod", 0.0)
    tilt = math.radians(a.get("tilt", 0.0))
    breath = math.sin(t * 1.5 + x0) * 0.0025 * H
    hy = -0.885 * H + lean * 0.045 * H + nod * 0.012 * H + breath
    ctx.save()
    ctx.translate(x0, y0)

    # torso
    top = -0.72 * H + lean * 0.02 * H
    ctx.move_to(-0.135 * H, top)
    ctx.line_to(0.135 * H, top)
    ctx.curve_to(0.15 * H, -0.58 * H, 0.16 * H, -0.45 * H, 0.17 * H, -0.30 * H)
    ctx.line_to(-0.17 * H, -0.30 * H)
    ctx.curve_to(-0.16 * H, -0.45 * H, -0.15 * H, -0.58 * H, -0.135 * H, top)
    fill(ctx, s["kameez"])
    # shoulders
    for k in (-1, 1):
        ellipse(ctx, k * 0.12 * H, top + 0.025 * H, 0.05 * H, 0.03 * H)
        fill(ctx, s["kameez"])
    # neck
    rrect(ctx, -0.028 * H, hy + 0.7 * ry, 0.056 * H, top - hy - 0.55 * ry, 0.01 * H)
    fill(ctx, s["shade"])
    # collar band + placket with buttons
    ctx.move_to(-0.045 * H, top - 0.004 * H)
    ctx.curve_to(-0.02 * H, top + 0.018 * H, 0.02 * H, top + 0.018 * H, 0.045 * H, top - 0.004 * H)
    stroke(ctx, s["trim"], 0.014 * H)
    box(ctx, -0.012 * H, top + 0.01 * H, 0.024 * H, 0.16 * H, s["trim"], 0.55)
    for k in range(3):
        ellipse(ctx, 0, top + (0.04 + k * 0.045) * H, 0.005 * H, 0.005 * H)
        fill(ctx, "#FFFFFF", 0.9)

    # arms
    l1, l2 = 0.17 * H, 0.16 * H
    hands = {}
    for side in ("right", "left"):            # character's right = screen left
        sg = -1 if side == "right" else 1
        sx, sy = sg * 0.125 * H, -0.68 * H + lean * 0.02 * H
        tgt = a.get("arms", {}).get(side) or ("w", x0 + sg * 0.11 * H, TABLE_Y - 34)
        tx, ty = (tgt[1] - x0, tgt[2] - y0) if tgt[0] == "w" else (tgt[1] * H, tgt[2] * H)
        (ex, ey), (hx2, hy2) = ik(sx, sy, tx, ty, l1, l2, 1 if sg < 0 else -1)
        hands[side] = (hx2, hy2, ex, ey, sx, sy)

    # head: ears, hair, face (hijab band = hairline), beard, cap
    ctx.save()
    ctx.translate(0, -0.80 * H + lean * 0.04 * H)
    ctx.rotate(tilt)
    ctx.translate(0, hy - (-0.80 * H + lean * 0.04 * H))
    for k in (-1, 1):
        ellipse(ctx, k * 0.98 * rx, 0.08 * ry, 0.16 * rx, 0.24 * ry)
        fill(ctx, s["shade"])
    ellipse(ctx, 0, -0.32 * ry, rx * 1.06, ry * 0.82)
    fill(ctx, s["hair"])
    ra.draw_face(ctx, s, rx, ry, a, t)
    # beard (leaves the mouth clear) + moustache
    ctx.move_to(-0.99 * rx, 0.0)
    ctx.curve_to(-1.0 * rx, 0.7 * ry, -0.55 * rx, 1.22 * ry, 0, 1.28 * ry)
    ctx.curve_to(0.55 * rx, 1.22 * ry, 1.0 * rx, 0.7 * ry, 0.99 * rx, 0.0)
    ctx.curve_to(0.88 * rx, 0.32 * ry, 0.62 * rx, 0.52 * ry, 0.36 * rx, 0.62 * ry)
    ctx.curve_to(0.30 * rx, 0.90 * ry, -0.30 * rx, 0.90 * ry, -0.36 * rx, 0.62 * ry)
    ctx.curve_to(-0.62 * rx, 0.52 * ry, -0.88 * rx, 0.32 * ry, -0.99 * rx, 0.0)
    ctx.close_path()
    fill(ctx, s["beard"])
    ctx.move_to(-0.34 * rx, 0.53 * ry)
    ctx.curve_to(-0.15 * rx, 0.43 * ry, 0.15 * rx, 0.43 * ry, 0.34 * rx, 0.53 * ry)
    stroke(ctx, s["beard"], 0.09 * rx)
    if "cap" in s:                           # white knitted topi
        ctx.save()
        ctx.rectangle(-rx * 1.3, -ry * 1.4, rx * 2.6, ry * 0.88)
        ctx.clip()
        ellipse(ctx, 0, -0.50 * ry, rx * 0.98, ry * 0.62)
        fill(ctx, s["cap"])
        for k in range(-3, 4):
            ctx.move_to(k * 0.26 * rx, -1.1 * ry)
            ctx.line_to(k * 0.26 * rx, -0.55 * ry)
            stroke(ctx, "#D8D6D0", 0.03 * rx, 0.8)
        ctx.restore()
        ctx.move_to(-0.97 * rx, -0.53 * ry)
        ctx.curve_to(-0.4 * rx, -0.47 * ry, 0.4 * rx, -0.47 * ry, 0.97 * rx, -0.53 * ry)
        stroke(ctx, "#DDDAD3", 0.06 * rx)
    ctx.restore()

    for side in ("left", "right"):
        hx2, hy2, ex, ey, sx, sy = hands[side]
        ctx.move_to(sx, sy)
        ctx.line_to(ex, ey)
        ctx.line_to(hx2, hy2)
        stroke(ctx, s["sleeve"], 0.052 * H)
        ellipse(ctx, hx2, hy2, 0.025 * H, 0.027 * H)
        fill(ctx, s["skin"])
        ellipse(ctx, hx2 + (0.019 if side == "left" else -0.019) * H, hy2 - 0.008 * H,
                0.009 * H, 0.012 * H)
        fill(ctx, s["skin"])
        hold = a.get("hold", {}).get(side)
        if hold:
            ra.draw_held(ctx, hold, hx2, hy2, H, t)
    ctx.restore()


def draw_actor(ctx, a, t):
    (draw_man if a["kind"] in MEN else ra.draw_person)(ctx, a, t)


# ----------------------------------------------------------------- set
def draw_room_back(ctx, t):
    vgrad(ctx, -500, -200, 3200, FLOOR + 200, "#EAD7BC", "#D9C2A0")
    box(ctx, -500, -200, 3200, 260, "#F3EBDD")
    box(ctx, -500, 60, 3200, 18, "#CDBC9F")
    vgrad(ctx, -500, FLOOR, 3200, 1200, "#BFA27E", "#A58763")
    box(ctx, -500, FLOOR - 26, 3200, 26, "#AC9A7E")
    for i in range(-4, 24):
        ctx.move_to(-500 + i * 160, FLOOR)
        ctx.line_to(-500 + i * 160 - (i - 10) * 60, FLOOR + 900)
    stroke(ctx, "#000000", 2, 0.06)
    # dusk window with curtains
    x, y, w, h = 1420, 330, 360, 470
    vgrad(ctx, x, y, w, h, "#F2B98A", "#7D86B0")
    for i in range(4):
        box(ctx, x + 20 + i * 85, y + h * (0.62 + 0.06 * (i % 2)), 60, h, "#5A5470", 0.7)
    ctx.rectangle(x, y, w, h)
    stroke(ctx, "#F7F1E6", 14)
    ctx.move_to(x + w / 2, y)
    ctx.line_to(x + w / 2, y + h)
    stroke(ctx, "#F7F1E6", 9)
    sw = 0.015 * math.sin(t * 0.7)
    for cx, d in ((x - 30, 1), (x + w + 30, -1)):
        ctx.move_to(cx - d * 20, y - 40)
        ctx.line_to(cx + d * w * 0.26, y - 40)
        ctx.curve_to(cx + d * w * (0.16 + sw), y + h * 0.4, cx + d * w * (0.22 + sw), y + h * 0.8,
                     cx + d * w * 0.18, y + h + 70)
        ctx.line_to(cx - d * 20, y + h + 70)
        ctx.close_path()
        fill(ctx, "#8C4A5E")
        for f in range(3):
            ctx.move_to(cx + d * (10 + f * 30), y - 30)
            ctx.line_to(cx + d * (8 + f * 30), y + h + 60)
            stroke(ctx, "#000000", 3, 0.12)
    box(ctx, x - 80, y - 52, w + 160, 14, "#7A5A3E")
    # wall decor
    ra.draw_photo(ctx, 180, 520, 200, 140, 3)
    ra.draw_photo(ctx, 470, 500, 120, 160, 2)
    ra.draw_photo(ctx, 2020, 540, 170, 125, 4)
    rrect(ctx, 820, 470, 300, 120, 10)                    # simple wall calligraphy frame
    fill(ctx, "#6E4A2E")
    rrect(ctx, 834, 484, 272, 92, 6)
    fill(ctx, "#F1E3C6")
    ra.draw_plant(ctx, -60, FLOOR - 4, 1.1, t)
    ra.draw_plant(ctx, 2330, FLOOR - 4, 0.9, t + 2)
    # sideboard
    box(ctx, 2150, 1140, 330, 300, "#7A4E2C")
    box(ctx, 2150, 1130, 330, 18, "#8E5E37")
    for k in range(2):
        rrect(ctx, 2170 + k * 160, 1170, 140, 240, 6)
        stroke(ctx, "#5E3B20", 4)
    # hanging lamps
    for lx in (700, 1600):
        ctx.move_to(lx, 0)
        ctx.line_to(lx, 270)
        stroke(ctx, "#4A3A2A", 4)
        ctx.move_to(lx - 75, 350)
        ctx.line_to(lx + 75, 350)
        ctx.line_to(lx + 32, 270)
        ctx.line_to(lx - 32, 270)
        ctx.close_path()
        fill(ctx, "#D9A85A")
        ellipse(ctx, lx, 354, 74, 10)
        fill(ctx, "#FFF2C8", 0.95)
        g = cairo.RadialGradient(lx, 380, 20, lx, 700, 760)
        g.add_color_stop_rgba(0, 1.0, 0.85, 0.55, 0.30)
        g.add_color_stop_rgba(1, 1.0, 0.85, 0.55, 0.0)
        ctx.rectangle(lx - 900, 340, 1800, 1400)
        ctx.set_source(g)
        ctx.fill()
    # chair backs
    for cx in list(SEAT.values()) + [EMPTY_CHAIR]:
        for dx in (-78, 78):
            box(ctx, cx + dx - 10, 1040, 20, 270, "#6E4426")
        rrect(ctx, cx - 92, 1026, 184, 40, 12)
        fill(ctx, "#7E5030")
        rrect(ctx, cx - 76, 1078, 152, 110, 10)
        fill(ctx, "#A8735A" if cx != EMPTY_CHAIR else "#A8735A")
        box(ctx, cx - 78, 1205, 156, 14, "#6E4426")


def draw_table_front(ctx, t, eaten):
    base = TABLE_Y - 12
    ctx.move_to(40, TABLE_Y - 30)
    ctx.line_to(2260, TABLE_Y - 30)
    ctx.line_to(2300, TABLE_Y + 10)
    ctx.line_to(0, TABLE_Y + 10)
    ctx.close_path()
    fill(ctx, "#9A643A")
    ctx.move_to(-10, TABLE_Y + 8)
    ctx.line_to(2310, TABLE_Y + 8)
    ctx.line_to(2330, FLOOR + 60)
    for k in range(72, -1, -1):
        ctx.line_to(-30 + k * 32.5, FLOOR + 60 + (8 if k % 2 else 0))
    ctx.close_path()
    fill(ctx, "#F3EBDD")
    for k in range(16):
        ctx.move_to(20 + k * 150, TABLE_Y + 20)
        ctx.line_to(10 + k * 152, FLOOR + 50)
        stroke(ctx, "#D9CDB8", 3, 0.6)
    box(ctx, -10, TABLE_Y + 70, 2320, 14, "#B5806A", 0.8)
    for kind, x in SEAT.items():
        ra.draw_plate(ctx, x, base, 64)
        if kind in eaten:                       # a little food on each plate
            ellipse(ctx, x - 16, base - 8, 22, 8)
            fill(ctx, "#E3B23C")
            ellipse(ctx, x + 20, base - 9, 24, 9)
            fill(ctx, "#E2B573")
        ra.draw_glass(ctx, x + 105, base, 62)
    for x, what in DISHES:
        if what == "daal":
            ra.draw_bowl(ctx, x, base, 48, "#E3B23C")
        elif what == "curry":
            ra.draw_bowl(ctx, x, base, 48, "#C8682F")
            for i in range(6):
                ellipse(ctx, x - 26 + i * 10, base - 27, 4, 3)
                fill(ctx, "#5FA04E" if i % 2 else "#E5C04A")
        elif what == "roti":
            ra.draw_roti_basket(ctx, x, base, 0.9)
        elif what == "salad":
            ra.draw_salad(ctx, x, base)
        elif what == "jug":
            ra.draw_jug(ctx, x, base)


# ----------------------------------------------------------------- voices + timing
def load_wav(path):
    with wave.open(path, "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768
    elif sw == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648
    elif sw == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128) / 128
    else:
        raise ValueError(f"{path}: unsupported sample width {sw}")
    x = x.reshape(-1, ch).mean(axis=1)
    if rate != SR:
        x = np.interp(np.arange(int(len(x) * SR / rate)) * rate / SR, np.arange(len(x)), x)
    peak = np.abs(x).max()
    return x / peak * 0.85 if peak > 0 else x


def line_plan(shot, audio_dir):
    """Per dialogue line: start/end in the shot, speaker, wav samples (or None), envelope."""
    lines = shot["dialogue"]
    span = shot["duration"] / max(1, len(lines))
    out = []
    for i, d in enumerate(lines):
        s0, s1 = d.get("start", i * span + 0.2), d.get("end", (i + 1) * span - 0.2)
        path = os.path.join(audio_dir, f"{shot['id']}_{i + 1}_{d['speaker']}.wav")
        wav, envl = None, None
        if os.path.exists(path):
            wav = load_wav(path)
            s1 = min(shot["duration"] - 0.05, s0 + len(wav) / SR)
            hop = SR // FPS
            rms = np.array([np.sqrt(np.mean(wav[k:k + hop] ** 2) + 1e-12)
                            for k in range(0, len(wav), hop)])
            ref = np.percentile(rms, 95) or 1.0
            envl = np.clip(rms / ref, 0, 1)
            envl = np.convolve(envl, [0.25, 0.5, 0.25], mode="same")
        out.append(dict(s0=s0, s1=s1, who=d["speaker"], wav=wav, env=envl, line=d))
    return out


def mouth_open(t, plan, who):
    for p in plan:
        if p["who"] != who or not (p["s0"] <= t <= p["s1"]):
            continue
        if p["env"] is not None:
            k = int((t - p["s0"]) * FPS)
            return float(p["env"][min(k, len(p["env"]) - 1)])
        if t > p["s1"] - 0.2:
            return 0.0
        rate = 1.7 if p["line"].get("arabic") else 2.4    # slower for the dua
        v = abs(math.sin(t * 2 * math.pi * rate + p["s0"] * 3)) ** 0.8
        return max(0.0, v * (0.65 + 0.35 * math.sin(t * 2 * math.pi * 0.9 + 1.0)))
    return 0.0


def current_speaker(t, plan):
    for p in plan:
        if p["s0"] - 0.3 <= t <= p["s1"] + 0.3 and p["who"] in SEAT:
            return p["who"]
    return None


# ----------------------------------------------------------------- choreography
EXPR = {  # (shot, kind) -> expression; default "smile"
    ("2.1", "ayesha"): "curious", ("2.2", "ayesha"): "curious", ("2.4", "ayesha"): "curious",
    ("3.1", "ayesha"): "neutral", ("3.4", "ayesha"): "happy", ("4.1", "ayesha"): "happy",
    ("4.4", "ayesha"): "happy", ("6.2", "ayesha"): "happy", ("5.1", "ayesha"): "smile",
}


def eat_arm(t, kind, t0, t1):
    """Right hand (screen left): plate -> mouth with a piece of roti -> plate, repeated."""
    H = ra.PEOPLE[kind]["H"]
    x0 = SEAT[kind]
    plate = (x0 - 0.02 * H, TABLE_Y - 36)
    mx, my = mouth_world(kind)
    mouth = (mx - 0.015 * H, my + 0.02 * H)
    if not (t0 <= t <= t1):
        return None, None, False
    ph = ((t - t0) % 3.0) / 3.0
    pos = keys(ph, [(0.0, plate), (0.25, plate), (0.5, mouth), (0.7, mouth), (1.0, plate)])
    holding = 0.2 < ph < 0.72
    chewing = 0.5 < ph < 0.95
    return ("w",) + tuple(pos), ("roti" if holding else None), chewing


def scene(shot, t, plan):
    sid, d = shot["id"], shot["duration"]
    spk = current_speaker(t, plan)
    anim = shot.get("anim", {})
    eat = anim.get("eat", {})
    actors = []
    for kind, x in SEAT.items():
        a = dict(kind=kind, x=x, y=FLOOR, sit=1.0, expr=EXPR.get((sid, kind), "smile"),
                 arms={}, hold={})
        # who looks where: listeners -> speaker, speaker -> Ayesha (Ayesha -> father)
        if spk and spk != kind:
            target = SEAT[spk]
        elif spk == kind:
            target = SEAT["father"] if kind == "ayesha" else SEAT["ayesha"]
        else:
            target = SEAT["ayesha"] if kind != "ayesha" else SEAT["father"]
        if sid == "4.4" and kind == "ayesha":          # looks around at everyone
            target = keys(t, [(0, 300.0), (1.6, 640.0), (2.6, 1320.0), (3.6, 1660.0), (5, 1320.0)])
        if kind in anim.get("to_camera", []) or (sid == "6.2" and t > 3.0):
            target = x
        dx = target - x
        gx = 0.0 if abs(dx) < 1 else max(-0.9, min(0.9, dx / 500))
        a["gaze"] = (gx, 0.15 if spk is None and kind != "ayesha" and eat else 0.0)
        a["tilt"] = max(-7, min(7, dx / 120)) + 1.2 * math.sin(t * 0.7 + x)
        a["blink"] = ra.blink_at(t, x / 97.0)
        # small nods while listening
        if spk and spk != kind:
            a["nod"] = 0.6 * max(0.0, math.sin(t * 2.2 + x)) ** 6
        if sid == "3.3" and kind == "grandmother":
            a["nod"] = abs(math.sin(t * 2.0)) * 0.9
        # gestures
        if sid == "2.3" and kind == "father":
            k = seg(t, 0.8, 1.5) * (1 - seg(t, 3.9, 4.6))
            if k > 0:
                a["arms"]["left"] = ("l", lerp(0.11, 0.20, k), lerp(-0.42, -0.56, k))
        if sid == "4.3" and kind == "mother":
            k = seg(t, 1.0, 1.7) * (1 - seg(t, 5.6, 6.4))
            if k > 0:
                a["arms"]["right"] = ("l", lerp(-0.10, -0.18, k), lerp(-0.42, -0.58, k))
        if kind in eat:
            arm, hold, chew = eat_arm(t, kind, *eat[kind])
            if arm:
                a["arms"]["right"] = arm
                if hold:
                    a["hold"]["right"] = hold
                if chew and a["expr"] != "happy":
                    a["expr"] = "chew"
        if kind not in MEN:                            # hands resting on the table edge
            H = ra.PEOPLE[kind]["H"]
            for side, sg in (("right", -1), ("left", 1)):
                a["arms"].setdefault(side, ("w", x + sg * 0.10 * H, TABLE_Y - 34))
        actors.append(a)
    eaten = {k for k, (t0, _) in eat.items() if t >= t0} if eat else set()
    if sid in ("6.1", "6.2"):
        eaten = set(SEAT)
    cam = shot["cam"]
    c = tuple(lerp(a_, b_, ra.ease(t / d)) for a_, b_ in zip(cam["from"], cam["to"]))
    return actors, c, eaten


# ----------------------------------------------------------------- frame
def draw_overlays(ctx, shot, t, plan):
    d = shot["duration"]
    has_arabic = False
    for o in shot.get("overlays", []):
        al = seg(t, o["start"], o["start"] + 0.5) * (1 - seg(t, o["end"] - 0.4, o["end"]))
        if al <= 0:
            continue
        if o["type"] == "title":
            blit(ctx, text_panel(((o["text"], LATIN, 64, "#FFFFFF"), (o["sub"], URDU_B, 46, "#F7D2DE")),
                                 panel=("#5B2333", 0.62), pad=(56, 26), maxw=1500), W / 2, 190, al)
        elif o["type"] == "arabic":
            has_arabic = True
            blit(ctx, text_panel(((o["text"], ARABIC, 92, "#F6D58A"),
                                  (o.get("roman", ""), LATIN, 30, "#F3E6CC")),
                                 panel=("#3B2410", 0.62), pad=(60, 24), maxw=1600), W / 2, 150, al)
        elif o["type"] == "translation":
            y = 330 if any(x["type"] == "arabic" and x["start"] <= t <= x["end"]
                           for x in shot.get("overlays", [])) else 150
            blit(ctx, text_panel(((o["text"], URDU_B, 52, "#FFFFFF"),), panel=("#5B2333", 0.62),
                                 pad=(48, 16), maxw=1500), W / 2, y, al)
        elif o["type"] == "endcard":
            ctx.rectangle(0, 0, W, HGT)
            ctx.set_source_rgba(0.12, 0.06, 0.03, 0.55 * al)
            ctx.fill()
            blit(ctx, text_panel(((o["text"], ARABIC, 120, "#F6D58A"),), glow="#3B2410", maxw=1700),
                 W / 2, 330, al)
            al2 = seg(t, o["start"] + 1.0, o["start"] + 1.6) * (1 - seg(t, o["end"] - 0.4, o["end"]))
            blit(ctx, text_panel(((o["sub"], URDU_B, 66, "#FFFFFF"),), glow="#3B2410", maxw=1700),
                 W / 2, 540, al2)
            blit(ctx, text_panel((("Little Muslim Learners", LATIN, 36, "#F4B8CA"),)), W / 2, 680, al2)
    if shot["id"] == shot.get("_first") and t < 0.8:
        ctx.rectangle(0, 0, W, HGT)
        ctx.set_source_rgba(0, 0, 0, 1 - t / 0.8)
        ctx.fill()
    if shot["id"] == shot.get("_last") and t > d - 1.0:
        ctx.rectangle(0, 0, W, HGT)
        ctx.set_source_rgba(0, 0, 0, seg(t, d - 1.0, d))
        ctx.fill()
    return has_arabic


def draw_subtitles(ctx, t, plan, has_arabic):
    for p in plan:
        s0, s1 = p["s0"], p["s1"]
        if not (s0 <= t <= s1 + 0.2):
            continue
        if p["line"].get("arabic") and has_arabic:     # the Arabic is already on screen
            name, col = LABELS[p["who"]]
            blit(ctx, text_panel(((name, URDU_B, 32, col),), panel=("#000000", 0.5), pad=(26, 8)),
                 W / 2, 960, seg(t, s0, s0 + 0.2) * (1 - seg(t, s1, s1 + 0.2)))
            continue
        al = seg(t, s0, s0 + 0.2) * (1 - seg(t, s1, s1 + 0.2))
        name, col = LABELS[p["who"]]
        body = (p["line"]["urdu"], ARABIC if p["line"].get("arabic") else URDU, 44, "#FFFFFF")
        blit(ctx, text_panel(((name, URDU_B, 30, col), body), panel=("#000000", 0.55), maxw=1500,
                             pad=(40, 14)), W / 2, 935, al)


def render_frame(ctx, shot, t, plan, subs=True):
    actors, (cx, cy, z), eaten = scene(shot, t, plan)
    for a in actors:
        a["talk"] = mouth_open(t, plan, a["kind"])
        if a["talk"] > 0.05 and a["expr"] == "chew":
            a["expr"] = "smile"
    ctx.identity_matrix()
    ctx.translate(W / 2, HGT / 2)
    ctx.scale(z, z)
    ctx.translate(-cx, -cy)
    draw_room_back(ctx, t)
    for a in actors:
        draw_actor(ctx, a, t)
    draw_table_front(ctx, t, eaten)
    ctx.identity_matrix()
    # warm evening grade + vignette
    ctx.rectangle(0, 0, W, HGT)
    ctx.set_source_rgba(1.0, 0.72, 0.4, 0.06)
    ctx.fill()
    g = cairo.RadialGradient(W / 2, HGT / 2, HGT * 0.45, W / 2, HGT / 2, W * 0.62)
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, 0.15, 0.08, 0.02, 0.38)
    ctx.rectangle(0, 0, W, HGT)
    ctx.set_source(g)
    ctx.fill()
    has_arabic = draw_overlays(ctx, shot, t, plan)
    if subs:
        draw_subtitles(ctx, t, plan, has_arabic)


# ----------------------------------------------------------------- audio
def synth_audio(shot, plan, seed):
    d = shot["duration"]
    n = int(d * SR)
    rnd = np.random.default_rng(seed)
    tt = np.arange(n) / SR
    out = np.zeros(n)

    def lowpass(x, k):
        return np.convolve(x, np.ones(k) / k, mode="same")

    def add(at, sig):
        s = int(at * SR)
        if 0 <= s < n:
            e = min(n, s + len(sig))
            out[s:e] += sig[: e - s]

    brown = np.cumsum(rnd.normal(0, 1, n))
    brown -= lowpass(brown, 4801)
    out += brown / (np.abs(brown).max() + 1e-9) * 0.010                    # room tone
    out += np.sin(2 * np.pi * 96 * tt) * 0.0025 * (1 + 0.3 * np.sin(2 * np.pi * 3.1 * tt))  # fan hum
    out += lowpass(rnd.normal(0, 1, n), 40) * 0.006 * (1 + 0.5 * np.sin(2 * np.pi * 3.1 * tt))
    quiet = "no cutlery" in shot["sfx"].lower()
    if not quiet:
        count = 7 if shot.get("anim", {}).get("eat") else 2
        for at in rnd.uniform(0.4, d - 0.6, count):
            e = np.exp(-np.arange(int(0.5 * SR)) / SR / 0.08)
            t_ = np.arange(len(e)) / SR
            f = rnd.uniform(2000, 2600)
            add(at, (np.sin(2 * np.pi * f * t_) + 0.5 * np.sin(2 * np.pi * f * 1.37 * t_)) * e * 0.018)
    if "chair" in shot["sfx"].lower():
        e = np.exp(-np.arange(int(0.6 * SR)) / SR / 0.3)
        nz = rnd.normal(0, 1, len(e))
        add(1.2, (nz - lowpass(nz, 30)) * e * 0.03)
    for p in plan:                                                          # voices
        if p["wav"] is not None:
            add(p["s0"], p["wav"])
    if shot["id"] == shot.get("_first"):
        out *= np.clip(tt / 0.8, 0, 1)
    if shot["id"] == shot.get("_last"):
        out *= np.clip((d - tt) / 1.2, 0, 1)
    return np.clip(out, -1, 1)


def write_wav(path, data):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((data * 32767).astype(np.int16).tobytes())


# ----------------------------------------------------------------- driver
def render_shot(args):
    shot, out_dir, audio_dir, subs, preview = args
    plan = line_plan(shot, audio_dir)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, HGT)
    ctx = cairo.Context(surf)
    if preview:
        for frac in (0.3, 0.7):
            ctx.identity_matrix()
            ctx.set_source_rgb(0, 0, 0)
            ctx.paint()
            render_frame(ctx, shot, shot["duration"] * frac, plan, subs)
            surf.write_to_png(os.path.join(out_dir, f"{shot['id']}_{int(frac * 100)}.png"))
        return shot["id"], sum(p["wav"] is not None for p in plan)
    wav = os.path.join(out_dir, f"{shot['id']}.wav")
    write_wav(wav, synth_audio(shot, plan, seed=int(shot["id"].replace(".", ""))))
    mp4 = os.path.join(out_dir, f"{shot['id']}.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
           "-s", f"{W}x{HGT}", "-r", str(FPS), "-i", "-", "-i", wav,
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-threads", "2", "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-shortest",
           "-movflags", "+faststart", mp4]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for k in range(int(shot["duration"] * FPS)):
        ctx.identity_matrix()
        ctx.set_source_rgb(0, 0, 0)
        ctx.paint()
        render_frame(ctx, shot, k / FPS, plan, subs)
        surf.flush()
        proc.stdin.write(surf.get_data())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for shot {shot['id']}")
    os.remove(wav)
    return shot["id"], sum(p["wav"] is not None for p in plan)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--shots", nargs="*")
    ap.add_argument("--no-subs", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args()

    with open(os.path.join(args.project_dir, "project.json"), encoding="utf-8") as fh:
        meta = json.load(fh)["project"]
    with open(os.path.join(args.project_dir, "shots.json"), encoding="utf-8") as fh:
        shots = json.load(fh)["shots"]
    for s in shots:
        s["_first"], s["_last"] = shots[0]["id"], shots[-1]["id"]
    if args.shots:
        shots = [s for s in shots if s["id"] in args.shots]
    base = os.path.join(args.project_dir, "build", "animation")
    out_dir = os.path.join(base, "preview" if args.preview else "clips")
    audio_dir = os.path.join(args.project_dir, "audio")
    os.makedirs(out_dir, exist_ok=True)

    jobs = [(s, out_dir, audio_dir, not args.no_subs, args.preview) for s in shots]
    voiced = 0
    with Pool(max(1, args.jobs)) as pool:
        for sid, nv in pool.imap_unordered(render_shot, jobs):
            voiced += nv
            print("rendered", sid, flush=True)
    total = sum(len(s["dialogue"]) for s in shots)
    print(f"voice files used: {voiced}/{total} lines" + ("" if voiced else
          f" (none found in {audio_dir}: the video has ambience only)"))
    if args.preview or args.shots:
        return
    lst = os.path.join(out_dir, "concat.txt")
    with open(lst, "w") as fh:
        for s in shots:
            fh.write(f"file '{s['id']}.mp4'\n")
    slug = meta["title"].lower().replace(" ", "_")
    final = os.path.join(base, f"{slug}{'_nosubs' if args.no_subs else ''}_16x9.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", "-movflags", "+faststart", final], check=True)
    os.remove(lst)
    print("final:", final)


if __name__ == "__main__":
    sys.exit(main())
