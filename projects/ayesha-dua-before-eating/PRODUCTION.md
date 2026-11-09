# Little Muslim Learners, Episode 01: Ayesha Learns the Dua Before Eating

**Output:** 16:9 widescreen · 2:00 · Urdu (Arabic dua) · 5 characters · 18 shots

| File | What it is |
|---|---|
| `project.json` | Locks: format, the five character identities, seating, dining room, voices, audio rules, negative prompt |
| `shots.json` | Shot list: timing, camera, action, Urdu dialogue with per-line timing, on-screen text (**edit this**) |
| `build/SHOT_PROMPTS.md` | Ready-to-paste realistic 3D prompt for every shot |
| `build/subtitles_ur.srt` | Urdu subtitles (and the dua lines) timed to the 2:00 edit |
| `build/VOICE_SCRIPT.md` | Every line grouped by character, with the WAV file name and target length |
| `build/animation/ayesha_learns_the_dua_before_eating_16x9.mp4` | Animated 1080p version with subtitles, Arabic text and room ambience. It has no voices until you add recordings (see Step 3) |

Rebuild the prompts, subtitles and voice script after any edit:
`python3 scripts/build_video_package.py projects/ayesha-dua-before-eating`

## Timeline

| Scene | Time | Shots | Content |
|---|---|---|---|
| 1. Family Dinner | 0:00–0:15 | 1.1–1.2 | Title, wide establishing push-in, narrator |
| 2. Father Introduces the Lesson | 0:15–0:35 | 2.1–2.4 | Father and Ayesha conversation |
| 3. Father Teaches the Dua | 0:35–1:05 | 3.1–3.4 | Father recites, Ayesha repeats, translation |
| 4. Family Appreciation | 1:05–1:30 | 4.1–4.4 | Grandmother, grandfather, mother, Ayesha |
| 5. Ayesha Repeats the Dua | 1:30–1:45 | 5.1–5.2 | Recites alone, eats with her right hand |
| 6. Lesson for Children | 1:45–2:00 | 6.1–6.2 | Speaks to camera, end card, narrator goodbye |

Seating is fixed for every shot (camera side, left to right): **grandfather, grandmother, Ayesha,
father, mother, empty sixth chair**. Keep it identical in generated shots so cuts match.

One addition to your script: in shot 3.3 the **narrator reads the translation**
(اللہ کے نام سے اور اللہ کی برکت کے ساتھ۔) as well as showing it on screen, so young children who
can't read yet still hear the meaning. Delete that line from `shots.json` if you only want it on screen.

## Two ways to finish the video

**A. Animated version (this repo, ready now).** `scripts/render_episode.py` draws the episode in
2D: the dining room, all five characters, blinking, head turns, gestures, eating with the right
hand, mouth movement during each line, Urdu subtitles, the Arabic dua and the end card. Add voices
(Step 3) and re-render; each character's mouth then follows the loudness of their own recording.

**B. Realistic 3D human version.** Generate the shots in an AI video tool from the prompts
(Steps 1–2), add voices (Step 3), then lip-sync and assemble (Step 4). This repo can't render
photoreal 3D humans itself; that needs a video-generation tool.

## Step 1: Lock all five faces first

1. Generate Ayesha's reference from `characters/ayesha/PROMPTS.md` (portrait + full body). Pick
   **one** approved image and reuse it for every shot.
2. Do the same for father, mother, grandfather and grandmother using their `identity` text in
   `project.json` → `cast`. Then generate one **wide family reference still** of all five at the
   table in the fixed seating. Use it as the start frame for the wide shots (1.1, 1.2, 3.3, 4.4, 5.2, 6.2).
3. Generate every shot **image-to-video** or with **character/face references** at 16:9. If you
   generate from text alone, the faces will change between shots.

## Step 2: Generate the 18 clips

- Paste each shot's prompt from `build/SHOT_PROMPTS.md`, plus the negative prompt.
- Save as `clips/1.1.mp4`, `clips/1.2.mp4` … in shot order, at the exact durations listed.
- Reject any clip with a changed face, hijab or clothes, extra or distorted fingers, the wrong
  hand used for eating (must be **right**), or text drawn into the picture.

## Step 3: Voices (one separate track per character)

`build/VOICE_SCRIPT.md` lists every line with its file name (e.g. `2.1_1_father.wav`) and target length.

- **Best:** record real voices: a girl about 10–11 for Ayesha, a man for the father, a woman for the
  mother, an elderly man and an elderly woman for the grandparents, and a narrator.
- **Or** use an Urdu voice-cloning or TTS service with a separate, consistent voice per character.
  Check every line by ear before using it.
- Dua pronunciation: **bis-mil-lā-hi wa ʿa-lā ba-ra-ka-til-lāh**. Have it checked by someone
  who recites Qur'an. There is no music under it, only room tone.
- Put the files in `projects/ayesha-dua-before-eating/audio/` and run:

```bash
python3 scripts/render_episode.py projects/ayesha-dua-before-eating
```

Each recording is placed at its line's start time, lip movement follows the recording, and the
subtitle stays on screen for as long as the recording runs. Only one line plays at a time, because the
lines don't overlap in `shots.json`.

## Step 4: Lip-sync and assemble (realistic 3D version)

1. Run each generated clip and its line's WAV through a lip-sync tool.
2. Join and burn in the subtitles:

```bash
cd projects/ayesha-dua-before-eating
ls clips/*.mp4 | sort -V | sed "s/^/file '/; s/$/'/" > clips.txt
ffmpeg -f concat -safe 0 -i clips.txt -c copy joined.mp4
ffmpeg -i joined.mp4 -vf "subtitles=build/subtitles_ur.srt:force_style='FontName=Noto Nastaliq Urdu,FontSize=20,Alignment=2,MarginV=40'" \
  -c:a copy little_muslim_learners_ep01_16x9.mp4
```

3. Add the on-screen text from `shots.json` → `overlays` in your editor: the title (1.1), the
   **Arabic dua** (3.1, 3.2, 3.4, 5.1), the translation (3.3, 3.4) and the end card (6.2). Use a proper
   Arabic font such as Amiri or Noto Naskh Arabic so every diacritic is correct.

## Final checks

- [ ] 1920x1080 or 3840x2160, 16:9, exactly 2:00
- [ ] Same Ayesha face, pink hijab and pink shalwar kameez in every shot; other four characters unchanged
- [ ] Seating order the same in every wide shot
- [ ] بِسْمِ اللّٰهِ وَعَلَى بَرَكَةِ اللّٰهِ correct on screen and clearly pronounced; no music anywhere
- [ ] Each voice matches its character; nobody speaks over anyone else; lips match the audio
- [ ] Ayesha eats with her **right** hand from the food in front of her (5.2)
