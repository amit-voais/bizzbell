# Stage 4: Screenplay, every second

**Made by:** you. **Output:** `screenplay.json` (the source of truth) and `screenplay.md` (the readable copy).
**Rubric:** `rubrics/screenplay.json`, judged against `story_humanized.md`, `brief.md` and `research.md`.

## Inputs

`story_humanized.md` and `story.md` (both passed), `brief.md`, `research.md`.

## Do

1. Copy `templates/screenplay.json` into the project and fill it (a full example:
   `examples/bakery-diwali/screenplay.json`).
2. Write `screenplay.md` from `templates/screenplay.md`, with the bibles copied **word for word** from the JSON.
3. Gate it. Most questions are answered by local checks, at no cost.

## screenplay.json

| Field | What it holds |
|---|---|
| `title`, `slug`, `lang`, `aspect`, `fps` | as in the brief; `slug` repeats the project's (`bb init --slug`), which is what names the output files; `aspect` is the master (9:16, 16:9, 1:1 or 4:5) |
| `duration` | whole seconds; `rows` cover 0 .. duration-1 |
| `continuity` | rules every prompt follows (light, screen direction, fixed details, "no text in AI frames") |
| `bibles.characters.<ID>` | `name`, `text` (verbatim block: face, skin, hair, build, fixed details **and wardrobe**), `real_person`, `photos` (consented photos in `refs/`, real people only) |
| `bibles.locations.<ID>` | `name`, `text` (layout, window/door side, **time of day and light**) |
| `bibles.props.<ID>` | `name`, `text` (shape, colour, material; "no print, no logo") |
| `voice` | `name` (a Hidrogen stock voice, default `priya`; `bb voice list`), `gender` (female or male, for the default audition), `candidates` (voices to audition), `audition_text` (the line they read; default the first two VO lines), `style` (who speaks to whom, the mood) |
| `music` | `prompt` (mood, instruments, length, "no vocals"), `instrumental: true`, `seconds` |
| `captions` | `max_chars` (default 42), `style` |
| `shots[]` | `id` (S01 live, G08 graphic), `start`, `end`, `kind` (`live` AI picture, `still` a reference photo used as is, `graphic` built in HyperFrames), `source`, `screen` |
| live shots | `keyframe_prompt`, `motion` (one small action), `camera`, `characters` [IDs], `location` ID, `props` [IDs], `refs` (extra reference files in `refs/` only; sheets, plates and the previous keyframe are added automatically) |
| still shots | `image`: the reference photo, for example `refs/product.png` |
| graphic shots | `graphic`: `type` (`card`, `number` or `endcard`), `title`, `subtitle`, `number`, `label`, `cta`, `icon`, `sample`; optional `image` as the background |
| `rows[]` | one per second: `t`, `shot`, `screen`, `source` (keyframe / reference / graphic), `camera`, `motion`, `vo` (the words spoken in that second), `caption` (shown in that second), `sfx`, `music` |
| `lines[]` | `id` (L01 = the humanized line), `shot`, `at` (start, s), `end`, `text` (caption spelling, Roman), `tts` (what the voice reads: Devanagari for Hindi and Hinglish), `hint` (delivery) |
| `overlays[]` | extra on-screen words: `text`, `start`, `end`, `sample` |
| `claims[]` | each claim shown or said, with its `source` (research.md C-id) |

Icon names: `arrow`, `bolt`, `camera`, `cart`, `chart`, `chat`, `check`, `clock`, `code`, `film`, `gift`, `heart`, `key`, `layers`, `leaf`, `mail`, `mic`, `music`, `phone`, `pin`, `play`, `search`, `shield`, `spark`, `star`, `tag`, `user`. An unknown name shows no icon, and `bb version_b` says so.

The prompt for a live shot is built as: `keyframe_prompt`, the camera, then the shot's bibles verbatim (characters,
location, props), then `continuity`. Write each bible once; never paraphrase it in a shot.

## Rules (from the films this method was proven on)

- **Shots of 1-3 s, one small action each.** Graphics at most 4 s. The video model adds actions later in a take, so
  the cut uses the early window.
- **Nobody enters or leaves frame.** Five fingers and a real grip; phones held, screens away from the lens.
- **No text, logo, emblem, uniform insignia or number plate inside any AI frame.** Every word is an overlay
  (captions, `graphic`, `overlays`). Saying "no logo" in a prompt is fine; asking for one is a hard fail.
- **References first.** Every live shot names at least one character, location or prop, so its keyframe is made
  from sheets and plates, never from text alone.
- **The voice-over is word for word** the humanized story (`lines[].text`, punctuation aside) and the rows carry the
  same words second by second.
- **Sound = picture:** an SFX only in a second whose picture shows its action. The music column describes a
  voice-free bed.
- **Every claim on screen comes from research.md.** Every number on screen is in research.md or the brief, or is
  marked `"sample": true` / shows the word "Sample".
- **Captions** fit `captions.max_chars`, in Roman script.

## Gate

```
python3 scripts/bb.py gate screenplay -p <folder>
python3 scripts/bb.py restructure screenplay -p <folder>   # only after a fail; then gate again
```

Local checks: `rows_cover_every_second` (hard), `shots_cover_timeline`, `shot_lengths`, `vo_word_for_word` (hard),
`rows_vo_match_lines`, `lines_timed`, `captions_short`, `prompts_no_text` (hard), `numbers_sourced` (hard),
`live_shots_complete`, `bibles_verbatim`. The judge answers the rest.

## Done when

`bb gate screenplay` passes. Every later stage reads `screenplay.json`; if you change it later, gate it again.
