# automation7

Character design specs and prompt tooling for consistent AI image generation.

## Layout

```
characters/
  ayesha/
    ayesha.json    # source of truth: character design spec (AYESHA_HUMAN_001)
    PROMPTS.md     # generated prompt sheet (portrait, full body, 6 expressions, negative prompt)
    prompts.json   # same prompts as JSON, for automation pipelines
scripts/
  build_prompts.py # turns a character JSON into prompts
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
