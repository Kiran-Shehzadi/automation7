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
scripts/
  build_prompts.py        # turns a character JSON into prompts
  build_video_package.py  # turns a project folder into shot prompts, subtitles and voice script
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
