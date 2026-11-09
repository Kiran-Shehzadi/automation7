# automation7

Character design specs and prompt tooling for consistent AI image generation.

## Layout

```
characters/
  ayesha/
    ayesha.json    # source of truth: character design spec (AYESHA_HUMAN_001)
    PROMPTS.md     # generated prompt sheet (portrait, full body, 6 expressions, negative prompt)
    prompts.json   # same prompts as JSON, for automation pipelines
projects/
  ayesha-learns-bismillah/
    project.json   # video locks: 9:16, 2:00, Urdu, characters, home, voices
    shots.json     # 21-shot list with Urdu dialogue (edit this)
    PRODUCTION.md  # how to generate, voice, and assemble the video
    build/         # generated: SHOT_PROMPTS.md, shot_prompts.json, subtitles_ur.srt, VOICE_SCRIPT.md
      animation/   # rendered 2D animation: clips/<shot>.mp4 + full 2:00 9:16 video
  ayesha-dua-before-eating/   # Little Muslim Learners Ep. 01, 16:9, 5-person family dinner
    project.json, shots.json, PRODUCTION.md, build/ (same layout; animation/ has the 16:9 video)
    audio/         # optional: one WAV per dialogue line, mixed in and lip-synced on render
scripts/
  build_prompts.py        # turns a character JSON into prompts
  build_video_package.py  # turns a project folder into shot prompts, subtitles and voice script
  render_animation.py     # renders the 21 shots as 2D animated 9:16 clips + the full video
  render_episode.py       # renders the 16:9 dinner episode; mixes and lip-syncs voice WAVs
```

## Regenerating prompts

Edit the character JSON, then run:

```bash
python3 scripts/build_prompts.py characters/ayesha/ayesha.json > characters/ayesha/PROMPTS.md
python3 scripts/build_prompts.py characters/ayesha/ayesha.json --format json > characters/ayesha/prompts.json
```

Each prompt reuses the same **identity block** so the face, eye colour, skin tone,
age and proportions stay fixed between generations. For best consistency, also
use a fixed seed or feed the first approved portrait back as a face reference.

## Building a video package

```bash
python3 scripts/build_video_package.py projects/ayesha-learns-bismillah
```

The script fails if the shot durations don't add up to the project length.

## Rendering the animated version

Needs `pycairo`, Pillow (with raqm), numpy, ffmpeg and the Noto Nastaliq Urdu /
Noto Naskh Arabic fonts (`apt-get install fonts-noto-core libcairo2-dev pkg-config && pip install pycairo`).

```bash
python3 scripts/render_animation.py projects/ayesha-learns-bismillah            # all clips + final video (~1 min)
python3 scripts/render_animation.py projects/ayesha-learns-bismillah --preview  # PNG stills only
python3 scripts/render_animation.py projects/ayesha-learns-bismillah --no-subs  # clips without subtitles
```

The clips have Urdu subtitles and home ambience sound but **no voices**. Record
the lines in `build/VOICE_SCRIPT.md`. Mouths move during each line's subtitle
window, so place each recording at its subtitle time.

## Rendering the 16:9 dinner episode

```bash
python3 scripts/build_video_package.py projects/ayesha-dua-before-eating
python3 scripts/render_episode.py projects/ayesha-dua-before-eating            # ~2.5 min
python3 scripts/render_episode.py projects/ayesha-dua-before-eating --preview  # PNG stills only
```

Camera moves, line timing and on-screen text all come from `shots.json`. Put recorded voices in
`projects/ayesha-dua-before-eating/audio/` using the file names in `build/VOICE_SCRIPT.md`. On the next
render each recording is mixed in at its line time, and the speaker's mouth follows its loudness.
