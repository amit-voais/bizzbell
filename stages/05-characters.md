# Stage 5: Characters

**Made by:** Hidrogen image (default), or ChatGPT in the user's own browser (optional). **Output:**
`characters/bible.md`, a turnaround sheet per character in `characters/sheets/<ID>.png`, a plate per location in
`characters/plates/<ID>.png`. **Rubric:** `rubrics/characters.json`, judged against `screenplay.json`.

## Inputs

`screenplay.json` (passed), `CONSENT.md` if any character is a real person, consented photos in `refs/`.

## Do

1. Write `characters/bible.md` from `templates/bible.md`: one `## <ID>: <name>` section per character and location,
   starting with the screenplay's block **word for word**, then in depth: face, skin, hair, build, wardrobe per
   scene, fixed details, and what must never appear.
2. Real person? Stop unless `CONSENT.md` names them, the film, the channels, how long and the date (permission
   point 3). Their photos go in `refs/` and in the bible's `photos`. The voice stays synthetic, never a clone.
3. Make the sheets and plates with Hidrogen (dry run first; it prints what would be sent and the ledger check):
   ```
   python3 scripts/bb.py characters make -p <folder> --dry-run
   python3 scripts/bb.py characters make -p <folder>
   ```
   A sheet is four views of the same person on a plain background (head front, three-quarter, profile, full body).
   Each take is checked locally, then judged with this stage's rubric; a failed take is made again with the
   judge's fix, up to `max_takes`.
4. Gate the layer.

## Optional: ChatGPT in the user's browser

Only when the host has a browser tool (Claude in Chrome for Claude Code; the host's browser tool in Codex).
Otherwise, or if the user says no, use Hidrogen (step 3).

1. **Ask first (permission point 2):** "Shall I make the characters with ChatGPT, in your browser, on your
   account?" (Hinglish: "Character ChatGPT se banwaun? Aapke browser mein, aapke account se.") Continue only after
   a yes.
2. Open chatgpt.com in the user's browser. **The user logs in themselves.** You never type a password, a code or a
   key, and you do not accept terms for them; ChatGPT's terms are theirs to accept.
3. Paste one prompt per character: "A character turnaround sheet for a short film: four views of the same person on
   one plain light-grey background (head front, head three-quarter, head profile, full body front). Photoreal.
   No text, labels, logos or emblems." followed by the character's full section of `characters/bible.md`, verbatim.
4. **Ask before downloading** each image into the project (name the file and where it goes).
5. Register it, then check it like any other sheet:
   ```
   python3 scripts/bb.py characters import <downloaded.png> --character <ID> -p <folder>
   python3 scripts/bb.py characters import <downloaded.png> --location <ID> -p <folder>
   ```

## Rules

- No text, letters, logos, emblems, insignia or number plates in any sheet or plate (hard).
- No face that resembles a famous or real person who is not in `CONSENT.md` (hard).
- The same person in every view; wardrobe as the bible says.

## Gate

```
python3 scripts/bb.py gate characters -p <folder>
python3 scripts/bb.py restructure characters -p <folder>   # rewrites characters/prompts.json; make again, gate again
```

## Done when

`bb gate characters` passes.
