# Bizzbell

Bizzbell is an open-source agent skill for **Claude Code** and **Codex** that makes short videos and video ads with
AI. You copy one folder, save one **Hidrogen API key**, write a brief ("a 20 s Hinglish reel for my bakery's Diwali
box"), and the agent takes it from research to finished videos in every size. Every layer is scored by a quality
gate before the next one starts, and nothing is spent until you approve a budget.

Ek folder, ek key, aur brief likho: baaki agent sambhal lega.

**The pipeline**

1. Brief and budget (you say yes to a cap in INR)
2. Research, with every fact's source and the date it was read
3. Story: a few directions, one chosen, the beats
4. Humanize: a voice-over that sounds like a person (real fillers in Hindi and Hinglish)
5. Screenplay, every second: shots, prompts, voice-over, captions, sound, music
6. Characters: an in-depth bible and a turnaround sheet per character, a plate per location
7. Keyframes: one still per shot, made from the sheets and plates
8. Voice, music (no vocals) and the mix at -14 LUFS
9. Version A with the Hidrogen video API, and Version B with HyperFrames, from the same screenplay
10. Final: 9:16, 1:1, 16:9 (and 4:5), phone share copies, and a report with every score, flaw, claim and rupee spent

## Install

Claude Code:

```
git clone <repo-url> ~/.claude/skills/bizzbell
```

Codex:

```
git clone <repo-url> ~/.codex/skills/bizzbell
```

Then save your key and check the setup (from the skill folder):

```
cd ~/.claude/skills/bizzbell        # or ~/.codex/skills/bizzbell
python3 scripts/bb.py key           # hidden prompt; the key is never shown or logged
python3 scripts/bb.py doctor        # Python, ffmpeg, Node, the key, the gateway, the models
```

The key is saved to `~/.config/hidrogen/key.env` (mode 600). `HIDROGEN_API_KEY` in the environment works too.
To pipe it in from a password manager instead of typing it, use `--stdin` (nothing is echoed):
`<your password manager's read command> | python3 scripts/bb.py key --stdin`.
Get a key and top up the wallet on the Hidrogen dashboard (api.hidrogen.in).

## First run

Open Claude Code or Codex anywhere and ask, for example:

> Make a 20 second Instagram reel in Hinglish for my bakery's Diwali box: 12 hand-made cookies for Rs 499,
> order through the link in bio.

The agent asks a few short questions, shows you a budget, and waits for your yes. Then it works through the stages
on its own and stops only when it needs you: the budget, the optional ChatGPT step for characters, a real person's
face, or a layer that will not pass after three rewrites. At the end it shows you both versions' scores and where
the files are.

A worked example of the text layers (brief to screenplay, and the character bible) is in
`examples/bakery-diwali/`. To watch the whole pipeline run on it without a key or any money, against the offline
mock gateway:

```
python3 scripts/bb.py demo --mock           # stages 0-9; prints where the videos and the report are
python3 scripts/bb.py demo --mock --no-b    # quicker: skips the HyperFrames render
```

The mock's pictures are flat colour cards and test patterns, so the videos only show that every step works.

## What it costs

Bizzbell itself is free. The AI work is paid from **your Hidrogen wallet**, in INR, at Hidrogen's prices.

- **Nothing is spent before you approve a budget.** You give a cap in INR; every paid call is reserved in a local
  ledger before it is sent, and a call that would pass the cap is refused. The cap is raised only when you say so.
- **Prices are asked, not guessed.** Before the budget, the agent runs `bb budget estimate`, which asks Hidrogen
  for a quote (`/v1/media/quote`, free) for each kind of call and shows a likely and a worst-case cost per stage;
  where a quote is not available it uses the estimate rates in your project's `bizzbell.json` and says so. What
  was actually charged is read from each reply. A text call (a gate's judge, a rewrite) is reserved at its longest
  possible reply, so even one long answer cannot take the spend past the cap.
- **What drives the cost:** video seconds (Version A) cost the most, then images (sheets and keyframes), then the
  judge passes of the quality gates, voice and music. Retakes are capped by `max_takes` (default 3) and rewrites by
  three rounds per layer.
- **Version B costs no video seconds:** HyperFrames renders on your own machine.
- `python3 scripts/bb.py budget show -p <project>` shows the cap, the spend and the reserved amount at any time.

## Requirements

- Python 3.9 or newer (standard library only; nothing to pip install)
- ffmpeg and ffprobe
- Node.js 22 or newer, for HyperFrames (Version B), run with `npx` at a pinned version
- Claude Code or Codex, with web search for the research stage. A browser tool (Claude in Chrome) is only needed
  for the optional ChatGPT character step.

`bb doctor` checks all of these and prints the install command for your system. It never installs anything
without your yes.

## Troubleshooting

| You see | It means | What to do |
|---|---|---|
| `402` / "wallet" (exit 5) | your Hidrogen wallet is empty; nothing was sent or charged | top up the wallet, then ask the agent to continue |
| `404` on images, videos, voice or music (exit 6) | that media endpoint is not live on the gateway yet | `bb doctor` shows which. Without `/v1/videos`, Version A is skipped with a note and Version B is still made |
| "no Opus model" in `bb doctor` | your key has no Opus-class model | it picks the strongest model your key has for rewrites and saves the reason; set `BB_RESTRUCTURE_MODEL` to choose |
| "no approved budget" / over the cap (exit 7) | the ledger refused a paid call | approve or raise the budget: `bb budget set <inr>` / `bb budget raise <inr>` |
| a layer keeps failing (exit 4) | three rewrites did not reach 95 | the agent shows the failing questions: accept, edit by hand, or allow one more round |
| blocked by the safety filter (exit 8) | the prompt was refused, charged 0 | the agent rephrases it as the visible action and retries once |
| key missing | no `HIDROGEN_API_KEY` and no key file | run `python3 scripts/bb.py key` yourself |

Add `--debug` to any command for a traceback (keys are always redacted).

## Safety

- **Consent:** a real person's face is used only with a written `CONSENT.md` in the project (who, which film, which
  channels, how long, the date). The voice is always a synthetic stock voice, never a clone.
- **No logos or text in AI pictures:** no logos, emblems, uniform insignia or number plates inside any AI-made
  frame; every word on screen is an overlay. No real brands, celebrities or competitors.
- **Claims:** every claim on screen comes from the research, with its source; example numbers are marked "Sample".
- **AI label:** the report reminds you to switch on the platform's AI label when you upload.
- **Nothing is published:** Bizzbell never uploads, posts or sends anything. If you use the ChatGPT step, it runs in
  your own browser on your own account, you log in yourself, and ChatGPT's terms are yours to accept.
- **Keys:** never printed, logged or written into a project; every error message is redacted.

## Contributing

Everything runs against a mock Hidrogen server, so no key and no money are needed:

```
python3 -m unittest discover -s tests -v  # offline: no network at all
BB_RENDER_TESTS=1 python3 -m unittest discover -s tests   # also the real HyperFrames renders (npx, npm registry)
python3 scripts/bb.py mock --port 0       # a mock gateway for trying commands by hand
python3 scripts/bb.py demo --mock         # the whole pipeline end to end, with small real video files
```

Point the client at the mock with `HIDROGEN_API_URL=<the printed URL>` and the fake key
`HIDROGEN_API_KEY=hi_test_0000000000000000fake`. How to add a command, a rubric or a local check is in
`docs/extending.md`. Code is Python 3.9+ standard library only; examples stay generic (a bakery, a gym); icons are
SVG, never emoji.

## License

MIT (see `LICENSE`). Credits for HyperFrames and OpenFilm are in `NOTICE`.
