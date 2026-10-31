# Stage 3: Humanize

**Made by:** you. **Output:** `story_humanized.md`. **Rubric:** `rubrics/humanize.json`, judged against
`story.md` and `brief.md`.

## Inputs

`story.md` (passed), `brief.md`.

## Do

1. Write the **Tone**: who speaks, to whom, in what mood. Not an announcer and not an ad read.
2. Write the **Voice-over**: the exact words the voice will say, one list item per line, each with an id:
   `- L01: <words>`. These lines are copied word for word into the screenplay (a hard check there).
3. Add **Notes**: word count against length (about 2.5 words per second or fewer), how the brand name is said.
4. Gate it.

## Hindi and Hinglish

Put real spoken fillers **in the voice-over words**, where a person would really say them: *yaar, matlab, umm, na,
haan, arre* (also *accha, dekho, suno, chalo*). A few per film, not one per sentence. They are words to be spoken,
never stage directions: write `Arre yaar, ...`, not `(sighs)`.

- Hinglish voice-over is written in Roman script here (it becomes the captions); the screenplay adds the Devanagari
  spelling for the voice (`lines[].tts`).
- A local check counts the fillers: at least 2, and no more than about 15 % of the words.

Example (from `examples/bakery-diwali`):

```
- L01: Arre yaar, Diwali mein bas paanch din bache hain...
- L02: Aur gift ka ek bhi dabba ready nahi. Umm...
```

## Other languages

Use that language's natural spoken tone: contractions, short sentences, the small turns of phrase people use with a
friend (English: "honestly", "okay so"; Spanish: "mira", "bueno"). Do not translate Hindi fillers into it.

## Rules

- Keep every beat and the call to action of the story. Add no new claim, number or promise (hard).
- No stage directions, brackets or notes inside the spoken lines.

## Gate

```
python3 scripts/bb.py gate humanize -p <folder>
python3 scripts/bb.py restructure humanize -p <folder>     # only after a fail; then gate again
```

## Done when

`bb gate humanize` passes. The screenplay does not start before both story and humanize have passed.
