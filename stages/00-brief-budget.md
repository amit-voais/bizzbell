# Stage 0: Brief and budget

**Made by:** you, with the user. **Gate:** none; the user's yes to a budget is the gate.

## Inputs

- The user's request (what the video is for, who it is for, the language, the size).
- `python3 scripts/bb.py doctor` output: tools, key, models, which media endpoints are live.

## Do

1. Run the checks and make the project:
   ```
   python3 scripts/bb.py doctor
   python3 scripts/bb.py init <folder> --brief "<one or two sentences>" --lang <en|hi|hinglish|...> --aspect <9:16|16:9|1:1|4:5>
   ```
   `doctor` makes no paid call. If the key is missing, ask the user to run `python3 scripts/bb.py key` themselves
   (it reads the key from a hidden prompt). Never ask them to paste a key into the chat.
2. Fill `brief.md` (template: `templates/brief.md`): length, product and offer exactly as the user said it, audience,
   one call to action, must say / must not say, real people or not. Ask only for what you cannot infer; one short
   question at a time.
3. Run `python3 scripts/bb.py doctor -p <folder>` so the model choice and the endpoint status are saved in the project.
4. **Ask for the budget (permission point 1).** Show, in INR:
   - an estimate per stage from `/v1/media/quote` where the endpoint answers, else from the rates in
     `bizzbell.json` `budget.rates_inr` (say which);
   - the number of takes allowed per item (`budget.max_takes`, default 3);
   - that Version B (HyperFrames) costs no video seconds, and Version A is made only if `/v1/videos` is live.
   Stop and wait for a clear yes and an amount.
5. Record the yes, with the user's words as the note:
   ```
   python3 scripts/bb.py budget set <inr> -p <folder> --note "user approved <inr> in chat"
   ```

## Rules

- Nothing is spent before step 5. The ledger refuses every paid call until a cap is approved (exit 7).
- The cap is raised only on the user's word: `python3 scripts/bb.py budget raise <inr> --note "..."`.
- A real person's face in the film needs `CONSENT.md` (template `templates/CONSENT.md`) before any sheet is made.
- Never put a key in the brief, the project, a log or a message.

## Done when

`python3 scripts/bb.py status -p <folder>` shows the brief as passed and a cap with no "(no budget approved yet)".
