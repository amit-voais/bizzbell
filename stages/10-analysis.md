# Stage 10: Analysis (optional, after publishing)

**Made by:** `bb analyse`. **Gate:** none. **Cost:** nothing: no paid Hidrogen call, no budget, no key, no login, and
nothing is fetched. **Output:** `<folder>/analysis/<tool>.md` and `.json`.

Use this only when a video is published and the user has real data. It is not part of the stage order: it does not
change `bb status` or its next step, and a project that skips it is complete after stage 9.

## Inputs (the user brings them)

| Tool | File | Notes |
|---|---|---|
| `retention` | A UTF-8 CSV: a position (seconds, percent or `0:30`), the percent still watching, at least 8 rows | On YouTube: Studio, Analytics, the video, Engagement, the audience retention chart, the download icon. The user downloads it themselves; never log in for them |
| `edit` | A timed transcript: SRT, VTT or whisper JSON | Devanagari, Hinglish and files with a BOM are fine |
| `outliers` | A JSON list: `[{"channel", "title", "views", "url"}]`, or `{"videos": [...]}`. At least 4 videos per channel | Gathered by the user, or by you from pages open without a login. Do not write a scraper and do not log in |

If there is no such file yet, say what is needed and stop. Never fill one with made-up numbers.

## Do

```
python3 scripts/bb.py analyse retention retention.csv --transcript voice.srt -p <folder>
python3 scripts/bb.py analyse edit voice.srt -p <folder>
python3 scripts/bb.py analyse outliers collected.json -p <folder>
```

Options: `--json` on all three. `retention`: `--duration <seconds>`, `--axis percent|seconds`, `--hook-seconds`,
`--min-drop`, `--top`. `edit`: `--floor <seconds>`, `--filler <word>` (repeatable, any language). `outliers`: `--min`,
`--min-videos`, `--top`.

A bad file gives a one-line message and exit 1 (exit 2 for a missing file or a wrong option). Pass the message on.

## What each one reports

- **retention:** the loss in the opening window, the steepest single drops, the average loss after the opening, and
  with `--transcript` the words spoken around each drop. Rules of thumb: the opening is a quarter of the video, at
  most 30 s (the first 10% when the length is unknown); a drop is over 0.8 points in one step; the words shown run
  from 2 s before it to its end. The report says how the axis was decided, and says so when it is a guess.
- **edit:** suggested cuts (`dead`: a gap between spoken lines over 0.45 s; `retake`: a line opening with the same
  words as the next, the earlier one marked) and, apart from them, filler cues to review. It touches no media.
- **outliers:** videos at 1.5x or more of their own channel's median in your file. Channels with too few videos are
  listed and not scored.

## Rules

- **What happened, not why.** Retention and outlier results do not prove a cause. Say "people left around 9 s, while
  this line was spoken", not "this line lost them". Any reason you offer is your guess: say so.
- **Fillers are a cue, not a fault.** umm, matlab, yaani, haan, na, arre and the like are often written into a
  Bizzbell voice-over on purpose (stage 3). Show them to the user to review; do not call them mistakes or cut them
  on your own.
- **A dead-air cut needs a look.** A transcript cannot hear music or a planned pause.
- **Small samples.** One video's curve, or a few videos per channel, is thin evidence. Say so.
- **Nothing here re-edits a film or spends money.** If the user wants a new cut after reading this, that is a new
  decision, with its own budget where it is paid.
- **Never publish.** As in every stage.

## Done when

The reports are in `<folder>/analysis/`, you have shown the user the main points, and you have said plainly that they
show what happened, not why.
