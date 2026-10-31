# Stage 7: Voice, music and mix

**Made by:** Hidrogen voice and music; ffmpeg for the mix. **Output:** `audio/vo.wav` (the placed voice-over),
`audio/music_bed.wav` (the instrumental bed), `audio/mix.wav` (the final mix). **Rubrics:** `rubrics/voice.json`,
`rubrics/music.json`, `rubrics/mix.json`, each judged against `screenplay.json`. Stage `audio` passes when all three
have passed.

## Inputs

`screenplay.json` (`voice`, `lines[]`, `music`, the `sfx` and `music` columns).

## Voice

```
python3 scripts/bb.py voice list                     # the stock voices, female and male
python3 scripts/bb.py voice audition priya meera kavya -p <folder>   # each reads the same line; judged; show the user the top two
python3 scripts/bb.py voice takes -p <folder>        # one take per line; checked and judged; retakes up to max_takes
python3 scripts/bb.py voice place -p <folder>        # lines placed at lines[].at into audio/vo.wav
python3 scripts/bb.py gate voice -p <folder>
```

- The voice is a synthetic stock voice (`voice.name`, default `priya`). Never a clone of a real person.
- Audition three or more voices that fit the narrator (a man's voice for a male narrator). Name them on the command
  line, or put them in `screenplay.json` `voice.candidates` (and the words in `voice.audition_text`); with neither,
  `voice.name` and the next two stock voices like it are auditioned. The best-scored voice is chosen; show the user
  the top two and switch with `bb voice audition <name>` if they prefer the other.
- It reads `lines[].tts`: Devanagari for Hindi and Hinglish, so the pronunciation is native; captions use
  `lines[].text` in Roman script.
- Word for word: no added, dropped or changed word (hard). Each line ends inside its shot.

## Music

```
python3 scripts/bb.py music make -p <folder>
python3 scripts/bb.py gate music -p <folder>
```

- **No vocals, ever:** no singing, humming, choir, chant or spoken words, checked on every judge pass (hard).
- The bed follows the beats (a lift at the turn, a resolve at the end card) and leaves room for the voice.

## Mix

```
python3 scripts/bb.py mix -p <folder>
python3 scripts/bb.py gate mix -p <folder>
```

- Voice on top, the bed ducked under it, then loudness to **-14 LUFS integrated, true peak at or below -1 dBTP**
  (checked locally with ffmpeg).
- **Sound = picture:** an effect only where the screenplay shows its action in that second.
- Model speech from video clips is always discarded; only the TTS voice and the bed are heard.

## Gate loop

Each of `voice`, `music` and `mix` follows the gate loop. `bb restructure voice` rewrites
`audio/voice/prompts.json` and `bb restructure music` rewrites `audio/music/prompts.json`; make the changed items
again, then gate again. A mix that fails usually needs one stem remade (the failed questions say which).

## Done when

`bb gate voice`, `bb gate music` and `bb gate mix` have passed; `bb status` shows stage `audio` as passed.
