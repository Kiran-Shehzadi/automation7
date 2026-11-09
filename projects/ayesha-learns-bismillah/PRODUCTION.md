# Ayesha Learns Bismillah: Production Guide

**Output:** 9:16 vertical · 2:00 · Urdu · photorealistic · 21 shots

| File | What it is |
|---|---|
| `project.json` | Locks: format, Ayesha, mother, home, voices, negative prompt |
| `shots.json` | Shot list: timing, action, camera, Urdu dialogue, sound effects, text overlays (**edit this**) |
| `build/SHOT_PROMPTS.md` | Ready-to-paste prompt for every shot |
| `build/subtitles_ur.srt` | Urdu subtitles timed to the 2:00 edit |
| `build/VOICE_SCRIPT.md` | Every line grouped by speaker, for recording |

Rebuild after any edit: `python3 scripts/build_video_package.py projects/ayesha-learns-bismillah`

## Timeline

| Scene | Time | Content |
|---|---|---|
| 1. Ayesha at Home | 0:00–0:16 | Walks to the kitchen, greets Mama |
| 2. Ayesha Asks | 0:16–0:29 | "Mama, khana khanay se pehle kya parhna chahiye?" |
| 3. Learning Bismillah | 0:29–0:45 | Repeats Bismillah; learns "Allah ke naam se" |
| 4. Preparing Lunch | 0:45–1:04 | Food on the table, washes her hands |
| 5. Eating Habits | 1:04–1:21 | Right hand, eat from what is in front of you |
| 6. Ayesha Remembers | 1:21–1:37 | Pauses, says Bismillah, MashaAllah |
| 7. A Beautiful Lesson | 1:37–2:00 | Promise, mother's advice, narrator, end card |

## Step 1: Lock the faces first

1. Use `characters/ayesha/PROMPTS.md` (portrait + full body) to generate Ayesha's reference
   images. Pick one approved portrait and **reuse it for every shot**.
2. Do the same for the mother, using `mother_character.identity` from `project.json`.
3. Generate each shot as **image-to-video** or with **character/face reference**, at 9:16, from
   those approved images. Text-only generation will drift between shots.

## Step 2: Generate the 21 clips

- Paste each shot's prompt from `build/SHOT_PROMPTS.md`, plus the negative prompt.
- Save the clips as `clips/1.1.mp4`, `clips/1.2.mp4` … in shot order.
- Reject any clip with changed clothes or hijab, extra fingers, a different face, or text drawn on screen.
- If your tool generates audio and lip-sync from the prompt's `Audio:` line, check the Urdu
  pronunciation. If it's wrong, mute the clip and use Step 3.

## Step 3: Human voices

For the most natural "human sound", **record real voices**: a young girl for Ayesha, a woman for
the mother, a woman for the narrator. Read the lines from `build/VOICE_SCRIPT.md` and save one WAV per line,
e.g. `audio/2.1_ayesha.wav`. An Urdu voice-cloning or text-to-speech (TTS) service also works. Then
run the clips through a lip-sync tool with each shot's audio.

Pronunciation: *Bismillah* = بِسْمِ اللّٰهِ (bis-mil-lāh), *MashaAllah* = ماشاءاللہ.

## Step 4: Assemble (ffmpeg)

```bash
cd projects/ayesha-learns-bismillah
# 1. Join the clips in order (all clips must share resolution/fps)
ls clips/*.mp4 | sort -V | sed "s/^/file '/; s/$/'/" > clips.txt
ffmpeg -f concat -safe 0 -i clips.txt -c copy joined.mp4
# 2. Burn in Urdu subtitles (needs an Urdu font such as Noto Nastaliq Urdu installed)
ffmpeg -i joined.mp4 -vf "subtitles=build/subtitles_ur.srt:force_style='FontName=Noto Nastaliq Urdu,FontSize=14,Alignment=2,MarginV=60'" \
  -c:a copy ayesha_learns_bismillah_9x16.mp4
```

Add the **Arabic بِسْمِ اللّٰهِ overlays** (shots 3.2 and 6.2), the "اللہ کے نام سے" overlay
(3.3) and the end card (7.3–7.4) in your editor (CapCut, Premiere, DaVinci). Use a proper Arabic font, e.g.
Amiri or Noto Naskh Arabic, so the lettering is correct. Never let the video model draw it.

## Final checks

- [ ] 1080x1920 or 2160x3840, total length exactly 2:00
- [ ] Ayesha's face, pink hijab and outfit identical in all shots; mother identical in all shots
- [ ] Arabic بِسْمِ اللّٰهِ correct, with full diacritics
- [ ] Lip sync matches; no background music; natural home ambience
- [ ] Hands: five fingers, eating with the right hand in shots 5.2, 6.1 and 6.3
