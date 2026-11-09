#!/usr/bin/env python3
"""Build a video production package from a project folder.

Usage:
    python3 scripts/build_video_package.py projects/ayesha-learns-bismillah

Reads <project>/project.json and <project>/shots.json and writes into
<project>/build/:
  * SHOT_PROMPTS.md   - per-shot video-generation prompts (copy into your tool)
  * shot_prompts.json - same, machine readable
  * subtitles_ur.srt  - Urdu subtitles timed to the edit
  * VOICE_SCRIPT.md   - lines grouped by speaker for voice recording / TTS
Fails if the shot durations don't add up to project.duration_seconds.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_prompts import identity_block  # noqa: E402


def ts(seconds: float, srt: bool = False) -> str:
    m, s = divmod(int(seconds), 60)
    if srt:
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d},{int(round((seconds % 1) * 1000)):03d}"
    return f"{m}:{s:02d}"


def load(project_dir: str):
    with open(os.path.join(project_dir, "project.json"), encoding="utf-8") as fh:
        project = json.load(fh)
    with open(os.path.join(project_dir, "shots.json"), encoding="utf-8") as fh:
        shots = json.load(fh)["shots"]
    char_path = os.path.normpath(os.path.join(project_dir, project["character_file"]))
    with open(char_path, encoding="utf-8") as fh:
        character = json.load(fh)
    return project, shots, character


def cast_identities(project, character) -> dict:
    """Speaker key -> identity text. Ayesha comes from her character file; the rest
    from project["cast"] (or the older single project["mother_character"])."""
    ids = {"ayesha": identity_block(character)}
    for key, c in project.get("cast", {}).items():
        ids[key] = c["identity"]
    if "mother_character" in project:
        ids.setdefault("mother", project["mother_character"]["identity"])
    return ids


def orientation(project) -> str:
    w, h = (int(v) for v in project["project"]["aspect_ratio"].split(":"))
    return "Vertical" if h > w else "Widescreen" if w > h else "Square"


def line_times(shot):
    """(start, end) seconds within the shot for each dialogue line. Uses the line's own
    start/end when given, otherwise splits the shot evenly between its lines."""
    lines = shot["dialogue"]
    if not lines:
        return []
    span = shot["duration"] / len(lines)
    return [(d.get("start", i * span + 0.2), d.get("end", (i + 1) * span - 0.2))
            for i, d in enumerate(lines)]


def voice_file(shot, i, d) -> str:
    return f"{shot['id']}_{i + 1}_{d['speaker']}.wav"


def overlay_text(shot) -> list:
    out = []
    if shot.get("overlay"):
        out.append(shot["overlay"].replace("\n", " / "))
    for o in shot.get("overlays", []):
        out.append(" / ".join(x for x in (o["text"], o.get("sub", "")) if x)
                   + f" ({o['type']}, {o['start']:g}–{o['end']:g}s)")
    return out


def shot_prompt(shot, project, ids) -> str:
    env = project["environment_lock"]
    meta = project["project"]
    order = sorted(shot["characters"], key=lambda k: k != "ayesha")  # Ayesha first
    cast = [f"{k.upper()}: {ids[k]}" for k in order if k in ids]
    room = env.get(shot["location"], "")
    parts = [
        f"{orientation(project)} {meta['aspect_ratio']} {meta['visual_style'].lower()} video, "
        f"real human cinematography, {meta['resolution']}, {meta['fps']}fps.",
        f"Setting: {env['location']}; {room}; {env['decoration']}; "
        f"{env['lighting'].lower()}; {env['atmosphere'][0].lower() + env['atmosphere'][1:]}.",
    ]
    if cast:
        parts.append("Characters (keep identical in every shot): " + " | ".join(cast) + ".")
    parts.append(f"Action: {shot['action']}.")
    if shot.get("expression"):
        parts.append(f"Expression: {shot['expression'].lower()}.")
    parts.append(f"Camera: {shot['camera']}.")
    if shot["dialogue"]:
        spoken = " ".join(
            f"{d['speaker'].capitalize()} says in {'Arabic' if d.get('arabic') else 'Urdu'}: "
            f"\"{d['roman']}\""
            + (" (voice-over, not on screen)" if d["speaker"] == "narrator" else "")
            for d in shot["dialogue"]
        )
        parts.append(f"Audio: {spoken}. Accurate natural lip sync.")
    parts.append(f"Sound: {shot['sfx']}. No music.")
    parts.append(
        "Motion: natural eye movement, realistic hands with five fingers, "
        "natural walking and sitting, no exaggerated movement. No on-screen text."
    )
    return " ".join(parts)


def build(project_dir: str) -> None:
    project, shots, character = load(project_dir)
    target = project["project"]["duration_seconds"]
    total = sum(s["duration"] for s in shots)
    if total != target:
        sys.exit(f"Shot durations total {total}s, expected {target}s")

    ids = cast_identities(project, character)
    negative = ", ".join(project["negative_prompt"])
    out_dir = os.path.join(project_dir, "build")
    os.makedirs(out_dir, exist_ok=True)

    t = 0
    rows, srt, voice = [], [], {}
    for shot in shots:
        start, end = t, t + shot["duration"]
        t = end
        prompt = shot_prompt(shot, project, ids)
        rows.append({**shot, "start": ts(start), "end": ts(end), "prompt": prompt,
                     "negative_prompt": negative})
        for i, (d, (a, b)) in enumerate(zip(shot["dialogue"], line_times(shot))):
            srt.append((start + a, start + b, d["urdu"]))
            voice.setdefault(d["speaker"], []).append(
                (shot["id"], ts(start + a), d, voice_file(shot, i, d), b - a))

    with open(os.path.join(out_dir, "shot_prompts.json"), "w", encoding="utf-8") as fh:
        json.dump({**{f"{k}_identity": v for k, v in ids.items()},
                   "negative_prompt": negative, "shots": rows},
                  fh, indent=2, ensure_ascii=False)

    with open(os.path.join(out_dir, "subtitles_ur.srt"), "w", encoding="utf-8") as fh:
        for i, (a, b, text) in enumerate(srt, 1):
            fh.write(f"{i}\n{ts(a, True)} --> {ts(b, True)}\n{text}\n\n")

    title = project["project"]["title"]
    md = [f"# {title}: Shot Prompts", "",
          "_Generated by `scripts/build_video_package.py`. Edit `shots.json`, then rebuild._", "",
          f"**Format:** {project['project']['aspect_ratio']} {orientation(project).lower()} · "
          f"{target // 60}:{target % 60:02d} · Urdu · {len(rows)} shots", "",
          "## Negative prompt (use on every shot)", "", "```text", negative, "```", ""]
    for r in rows:
        md += [f"## Shot {r['id']}: {r['scene_title']} ({r['start']}–{r['end']}, {r['duration']}s)", ""]
        for d in r["dialogue"]:
            md.append(f"- **{d['speaker'].capitalize()}:** {d['urdu']}  \n  _{d['roman']}_")
        for ov in overlay_text(r):
            md.append(f"- **Text overlay (add in editor):** {ov}")
        md += ["", "```text", r["prompt"], "```", ""]
    with open(os.path.join(out_dir, "SHOT_PROMPTS.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    vmd = [f"# {title}: Voice Script (Urdu)", "",
           "Record each line separately, one WAV file per line, named as in the **File** column, "
           "and keep each take about as long as **Length**.", ""]
    for speaker, items in voice.items():
        vmd += [f"## {speaker.capitalize()}", "",
                f"_Voice:_ {project['voices'][speaker]}", "",
                "| Shot | Time | Length | File | Line | Roman |", "|---|---|---|---|---|---|"]
        vmd += [f"| {sid} | {tm} | {ln:.1f}s | `{fn}` | {d['urdu']} | {d['roman']} |"
                for sid, tm, d, fn, ln in items]
        vmd.append("")
    with open(os.path.join(out_dir, "VOICE_SCRIPT.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(vmd))

    print(f"OK: {len(rows)} shots, {total}s, {len(srt)} subtitle lines -> {out_dir}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(sys.argv[1])
