---
name: bizzbell
description: Make short AI videos and video ads end to end with one Hidrogen API key - Instagram reels, video ads, story films, product promos and explainer videos, in any language (Hindi and Hinglish first-class). Use when the user asks to make, script or produce a video ad, reel, short, story film or explainer, or to resume a Bizzbell project folder (one with project.json). Research, story, a per-second screenplay, character sheets, keyframes, voice, music, two finished versions (Hidrogen video and HyperFrames) in every size, each layer scored by a quality gate, inside a budget the user approves. After a video is published and the user has real data (a retention export, a timed transcript, a collected video list), it can also read that data, free.
---

# Bizzbell

You make a short video from a brief, layer by layer, and score every layer with a quality gate before the next one
starts. Every paid AI call goes through Hidrogen (one key) and through a hard INR budget the user approves. You run
on your own between the permission points below; everything else is yours to decide.

All commands are `python3 scripts/bb.py <command>`, run from this skill's folder (written `bb <command>` below).
Pass the project with `-p <folder>` or set `BB_PROJECT`. `bb status -p <folder>` always says where a project is and
what comes next, so you can stop and resume at any point.

## Permission points (stop and ask in chat; never skip)

1. **The budget, before anything is paid for.** Show a cap in INR, the estimate per stage
   (`bb budget estimate --seconds <length>`: free, from `/v1/media/quote` where it answers, else the rates in
   `bizzbell.json`), and `max_takes`. Wait for a clear yes, then
   `bb budget set <inr> --note "<the user's words>"`. Nothing is spent before it: the ledger refuses every paid
   call (exit 7). The cap is raised only on the user's word (`bb budget raise <inr>`), never by you.
2. **ChatGPT for the characters (optional).** Ask "Shall I make the characters with ChatGPT, in your browser, on
   your account?" Only after a yes, and only if you have a browser tool (Claude in Chrome in Claude Code; the
   host's browser tool in Codex). The user logs in themselves; you never type a password, a code or a key, and you
   never accept terms for them. Ask before downloading each image. No browser tool, or a no: use Hidrogen.
3. **A real person's face.** Only with `CONSENT.md` in the project (who, which film, channels, how long, the date)
   before the first sheet. The voice is always synthetic, never a clone.
4. **Another restructure round after 3, or anything above the cap.** Show the score and the failing questions and
   ask: accept as it is, edit by hand, or spend one more round.
5. **Never publish.** You do not upload, post or send anything. A render is not a publish.

## Keys and safety

- The key lives in `$HIDROGEN_API_KEY` or `~/.config/hidrogen/key.env`. If `bb doctor` says it is missing, ask the
  user to run `python3 scripts/bb.py key` themselves (hidden prompt). Never ask for a key in chat, never print,
  echo, grep or copy a key or a key file, and never write one into the project.
- HTTP 402 (exit 5) means the Hidrogen wallet is empty and nothing was sent: tell the user in plain words and stop.
- A safety-filter block (exit 8) is charged 0: rephrase as the visible behaviour and retry once.
- HTTP 502/503 after the retries (exit 9) means the Hidrogen service is down and nothing more was spent: tell the
  user, stop, and run the same command again later. Do not change prompts or models to "fix" it.
- Every claim on screen comes from `research.md`; example numbers carry a "Sample" tag. No real brands, logos or
  competitors. Tell the user to switch on the platform's AI label when they upload.

## The process (follow in order)

Each stage has a guide in `stages/` with its inputs, outputs, exact commands, rules and rubric. Read the guide when
you reach the stage.

- [ ] **0. Brief + budget** ([stages/00-brief-budget.md](stages/00-brief-budget.md)).
  `bb doctor`; `bb init <folder> --brief "..." --lang <lang> --aspect <ratio> --slug <short-name>`; fill
  `brief.md`; `bb doctor -p <folder>`; `bb budget estimate --seconds <length>`; ask for the budget (permission
  point 1); `bb budget set <inr>`.
- [ ] **1. Research** ([stages/01-research.md](stages/01-research.md)). Your own web search; `research.md` with
  every fact's URL and date read, and the claims list. Gate `research`.
- [ ] **2. Story** ([stages/02-story.md](stages/02-story.md)). 2-3 directions, one chosen, beats with times.
  Gate `story`.
- [ ] **3. Humanize** ([stages/03-humanize.md](stages/03-humanize.md)). The spoken voice-over; in Hindi and
  Hinglish real fillers (yaar, matlab, umm, na, haan, arre) in the words. Gate `humanize`.
- [ ] **4. Screenplay, every second** ([stages/04-screenplay.md](stages/04-screenplay.md)). Starts only when
  story and humanize have passed. `screenplay.json` (schema: `templates/screenplay.json`) + `screenplay.md`.
  Gate `screenplay`.
- [ ] **5. Characters** ([stages/05-characters.md](stages/05-characters.md)). `characters/bible.md`, then
  `bb characters make` (or ChatGPT after permission point 2, then `bb characters import`). Gate `characters`.
- [ ] **6. Keyframes** ([stages/06-keyframes.md](stages/06-keyframes.md)). `bb keyframes make`.
  Gate `keyframes`.
- [ ] **7. Voice, music, mix** ([stages/07-voice-music-mix.md](stages/07-voice-music-mix.md)).
  `bb voice list`, `bb voice audition <voice> <voice> <voice>`, `bb voice takes`, `bb voice place`,
  `bb music make`, `bb mix`. Gate `voice`, `music`, `mix`.
- [ ] **8A. Version A, Hidrogen video** ([stages/08a-version-a.md](stages/08a-version-a.md)). Only if
  `/v1/videos` is live, else `bb mark video_a skipped --note "..."`. `bb clips make`, gate `clips`;
  `bb version_a`, gate `version_a`.
- [ ] **8B. Version B, HyperFrames** ([stages/08b-version-b.md](stages/08b-version-b.md)). Always made (no video
  seconds). `bb version_b`, gate `video_b`.
- [ ] **9. Final** ([stages/09-final.md](stages/09-final.md)). `bb final`: every size, share copies, the final
  gate of each version against the screenplay (`final_a`, `final_b`, from `rubrics/final.json`) and
  `out/report.md`. Show the user both versions' scores and the file paths it prints.

## After publishing (optional)

**Stage 10, analysis** ([stages/10-analysis.md](stages/10-analysis.md)). Use it only when a video is published and the
user brings real data; never offer it during a film, and never make the data up. `bb analyse retention <csv>`,
`bb analyse edit <transcript>`, `bb analyse outliers <json>`. Local only: no paid call, no budget, no login, nothing
fetched. Outputs go in `<project>/analysis/`; `bb status` and the stage order do not change. Results show what
happened, not why. Filler cues in a Hindi or Hinglish voice-over are often intentional: pass them on to review, and
do not call them mistakes.

Before any paid command, run it with `--dry-run` when it has one: it prints what would be sent and the ledger
check, and sends nothing.

## The gate loop (every gated layer)

```
bb gate <layer>            # exit 0 pass, 3 fail, 7 no budget / over the cap
bb restructure <layer>     # only after a fail
bb gate <layer>            # again
```

1. `bb gate <layer>` scores the layer with the questions in `rubrics/<layer>.json` (yes 1, partly 0.5, no 0;
   weighted %). Local checks answer what code can see (per-second rows, shot length, word-for-word voice-over,
   caption length, aspect, duration, loudness) at no cost; the judge model answers the rest, quoting evidence.
   Two judge passes, a third if they disagree. Saved as `gates/<layer>.<n>.json`.
2. **Pass at 95 or more, with no hard question at no.** Hard questions include: a logo or text in an AI frame, a
   claim not in the research, a real face without consent, vocals in the music, a voice-over that is not word for
   word, any second missing from the screenplay, a shot outside 1-3 s, and any missing or flagged item of a media
   layer (a sheet, a keyframe, a clip, a VO line). A flagged item is one no take passed: show it to the user, who
   accepts it (`bb keyframes approve <shot>`, `bb clips pick <shot> --take N`) or has it made again.
3. **Below 95: `bb restructure <layer>`.** The restructure model (Opus-class where the key has one, chosen by
   `bb doctor`) gets the layer, its references and the failed questions with the judge's evidence, and rewrites
   the layer (text layers) or its prompts (media layers: then make the changed items again). Then gate again.
4. **At most 3 restructure rounds per layer.** Still below 95 after round 3 (`bb restructure` exits 4): stop, show
   the user the score and the failing questions, and ask (permission point 4): accept it
   (`bb mark <layer> passed --note "accepted by the user"`), edit it by hand and gate again, or allow one more
   round (`bb restructure <layer> --extra --note "user said yes"`). Never pass `--extra` without that yes.
5. Fix a failed layer before moving on: a later layer is judged against the earlier ones, and the paid media
   commands refuse to start (exit 3, nothing sent) while a layer they build on has not passed or been accepted.
6. A layer that passed and is then changed (a keyframe rejected, a file edited) shows as `changed` in
   `bb status`: gate it again.

Media sub-layers roll up into a stage: `voice`, `music` and `mix` make stage `audio`; `clips` and `version_a` make
stage `video_a`. The stage passes when all its layers have, and fails when one fails. `bb gate`, `bb restructure`
and `bb mark` take the layer names.

Layers: `research`, `story`, `humanize`, `screenplay`, `characters`, `keyframes`, `voice`, `music`, `mix`,
`clips`, `version_a`, `video_b`, `final` (both versions together), `final_a` and `final_b` (one version each,
written by `bb final`). A project can override any rubric with `<folder>/rubrics/<layer>.json`.

## Rules that make the films look real

- Shots of 1-3 s, one small action per shot; generate 4-10 s and use the early window.
- Nobody leaves frame; five fingers and a real grip; phone screens away from the lens.
- No text, logo, emblem, uniform insignia or number plate inside any AI frame. Every word is an overlay.
- Bibles pasted verbatim into every prompt; references first, never a text-only frame.
- Model speech is always discarded; the voice is TTS. Music has no vocals, checked on every pass.
- Sound = picture: no sound effect without its picture.

## When things go wrong

| Exit | Meaning | Do |
|---|---|---|
| 2 | usage | read the message; `bb <command> --help` |
| 3 | gate failed, or a paid stage asked for before the layers it builds on passed | the gate loop above |
| 4 | restructure rounds used up | permission point 4 |
| 5 | 402: wallet empty | tell the user to recharge their Hidrogen wallet; stop |
| 6 | 404: endpoint not live | media endpoints off: skip Version A (`bb mark video_a skipped`), still make Version B |
| 7 | no budget / over the cap | permission point 1; never raise the cap yourself |
| 8 | blocked by the safety filter (charged 0) | rephrase as visible behaviour, retry once |
| 9 | 502/503: the Hidrogen service is unavailable (charged 0) | tell the user nothing more was spent; retry the same command later (it replays safely) |

`--debug` on any command shows a traceback (keys are always redacted). No Opus model on the key: `bb doctor`
picks the strongest available model and saves the reason; you can set `BB_RESTRUCTURE_MODEL`.

## Files

- `stages/` the stage guides; `rubrics/` the gate questions; `templates/` the project files (brief, research, story,
  humanized story, screenplay.md/json, bible, consent, report); `examples/bakery-diwali/` a worked text-only example.
- `hyperframes/` the composition template Version B fills; `scripts/bb.py` the CLI; `docs/extending.md` how to add
  a command, a rubric or a check.
- Try the whole pipeline with no key and no spend: `bb demo --mock`.
