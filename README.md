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
reel-studio-kit/          # Remotion kit for 9:16 reels (script, voice, synced captions, render, self-check)
scripts/
  build_prompts.py        # turns a character JSON into prompts
  build_video_package.py  # turns a project folder into shot prompts, subtitles and voice script
  render_animation.py     # renders the 21 shots as 2D animated 9:16 clips + the full video
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

## Reel Studio Kit

`reel-studio-kit/` makes vertical reels with Remotion. See `reel-studio-kit/README.md`.

```bash
cd reel-studio-kit
npm install && npm run typecheck
npm run setup:captions   # one-time, local Whisper caption sync (Python 3.11-3.13)
npm run demo             # -> out/Demo.mp4
```

In a cloud/Linux container without Chrome, point Remotion at a browser:
`export BROWSER_EXECUTABLE=/opt/pw-browsers/chromium`. Open Claude Code inside
`reel-studio-kit/` and type `reel banao: <topic>`.
