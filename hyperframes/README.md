# Version B template (HyperFrames)

Version B (stage 8B) is the same screenplay made without any video model: the keyframes and sheets as stills with
a slow camera move, word-timed captions, graphic shots (cards, numbers, the end card) and the same voice and music,
composed in HyperFrames (run with `npx`, never copied into this package) and rendered locally. It costs nothing.

```
python3 scripts/bb.py version_b            # build + check + render (default)
python3 scripts/bb.py version_b build      # hf/<ratio>/index.html only (no Node needed)
python3 scripts/bb.py version_b check      # cut-off text + repeatability -> out/B/qa.json
python3 scripts/bb.py version_b render --quality delivery
python3 scripts/bb.py gate video_b
```

Exit codes: 0 all passed, 3 a check failed (the videos are still made), 1 an error (for example no Node).

## Files here

| File | Role |
|---|---|
| `composition.html` | the page skeleton: one standalone HyperFrames root, sized per ratio |
| `style.css` | the look: ink / paper / accent tokens, type scale on `--u`, safe-zone variables |
| `motion.js` | builds every animation from the JSON plan with the Web Animations API |

`scripts/bizzbell/hf/compose.py` fills them; edit these files to change the look for every project.

## What is read from the project

- `screenplay.json`: `duration`, `fps`, `shots[]` (`id`, `start`, `end`, `kind`, `camera`, `graphic`, `overlay`,
  `captions: false` to hide captions over a shot), `rows[]` (one per second), `lines[]`, `overlays[]`.
  A shot whose `kind` is `graphic`, `card`, `number` or `endcard` (or that has a `graphic` object) is drawn as a
  graphic; any other shot shows `keyframes/<id>.png` (or the image path in `image` / `keyframe`).
  - card: optional icon (an SVG name: check, arrow, star, gift, clock, phone, pin, spark, heart, cart, bolt, chat,
    tag, leaf), `title`, `number`, `subtitle`;
  - number: a large `number` with `label` / `subtitle`;
  - endcard: `title` (the brand name; falls back to `brand.name`), `subtitle`, `cta` (falls back to `brand.cta`),
    and the brand logo when `brand.logo` names an image in the project.
  - `sample: true` adds a "Sample" tag (example numbers must carry it).
- Captions, from the first source that exists: `audio/words.json` (word timings, Roman text only),
  `audio/vo_timing.json` (the placed voice lines), the rows' `caption` column, `lines[]` (`at`, `end`, `text`),
  the rows' `vo`. Captions are Roman script; the Devanagari voice text is never put on screen.
- Audio: `audio/mix.wav` when it exists, else `audio/vo.wav` plus `audio/music*.wav` (music at 0.32 under a voice).
- `bizzbell.json`: `hyperframes.version` (the pin) and an optional `brand`:

```json
"brand": {"name": "Gulmohar Bakery", "cta": "Order today", "logo": "refs/logo.png",
          "colors": {"ink": "#101318", "paper": "#F7F4EE", "accent": "#F2B53A"},
          "fonts": {"display": "Inter", "text": "Inter"}}
```

Colours are adjusted where needed so text stays readable (ink on paper at least 7:1, the spoken-word colour at
least 4.5:1 on the caption pill).

## Sizes and safe zones

Each size is laid out again from the same plan; nothing is cropped from another size. Images fill the frame
(they carry no text, so filling cannot cut words); when an image's shape is more than 2x off the frame's
(a 9:16 keyframe in 16:9), it is shown whole over a blurred, darkened copy of itself.

| Ratio | Size | Safe zone (left, top, right, bottom) |
|---|---|---|
| 9:16 | 1080 x 1920 | 6 %, 11 %, 6 %, 20 % (clear of the Reels / Shorts buttons and caption bar) |
| 1:1 | 1080 x 1080 | 6 %, 6 %, 6 %, 8 % |
| 16:9 | 1920 x 1080 | 5 %, 7 %, 5 %, 8 % |
| 4:5 | 1080 x 1350 | 6 %, 7 %, 6 %, 10 % (rendered only when its text fits) |

## Fonts and Devanagari

The page names the brand fonts (default Inter) and, when any text has Devanagari, Noto Sans Devanagari in a
Google Fonts link. HyperFrames downloads them once, caches them and inlines them as `@font-face` at render time,
so every frame uses the same font. The font stack then falls back to Kohinoor Devanagari, Devanagari Sangam MN or
Nirmala UI (system fonts on macOS / Windows), so Devanagari still renders offline. The DOM bounds check records
whether the named fonts loaded (`out/B/qa.json`, `bounds.fonts`).

## Determinism

No clocks, no randomness, no network at render time beyond the fonts above, no `requestAnimationFrame`. Every
animation is a Web Animation with an absolute start; HyperFrames seeks each one to the frame's time. Each element
has at most one animation, so fills never fight. The repeatability check proves it on every build.

## The two checks (borrowed ideas from OpenFilm, our own code)

1. **Cut-off text** (`hf_text_fits`): HyperFrames' `check --json` (lint errors, runtime errors, text outside the
   canvas or clipped by its container) plus a DOM bounds check, because HyperFrames has no safe-zone test: the
   page is opened in HyperFrames' own chrome-headless-shell (`--dump-dom`, no window), every element marked
   `data-bb-text` is measured at settled moments of its clip, and its box must lie inside the safe zone.
2. **Repeatability** (`hf_frames_repeatable`): `snapshot --at` renders a sample of frames (shot midpoints first),
   then the same frames again in shuffled order; each pair must hash the same or differ in at most 0.2 % of
   pixels by more than 12 grey levels (compared by ffmpeg at small size).

Both are saved per ratio in `out/B/qa.json` with a hash of the composition; the gate trusts a record only while
the hash matches the files on disk.

## Pinned HyperFrames

`bizzbell.json` `"hyperframes": {"version": "0.8.150"}` (published 12 Oct 2026, verified to render locally on
31 Oct 2026). Every call runs `npx -y hyperframes@<pin>` with telemetry, update checks and skill installs off.
Needs Node.js 22+ and ffmpeg.
